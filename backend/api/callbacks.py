"""
Twilio callback and audio-stream endpoints.

Routes:
  POST  /api/twilio/status-callback    — Twilio call-status webhook
  WS    /ws/twilio/audio-stream        — Twilio live audio WebSocket
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from backend.api.websockets import manager
from backend.config import settings
from backend.db_services import get_donor_push_token
from backend.dispatch_store import dispatch_store
from backend.schemas.models import TERMINAL_OR_DECIDED, CallStatus, DonorStatusUpdate
from backend.services.call_retry import schedule_retry
from backend.services.push_service import send_dispatch_notification
from backend.services.telephony import get_telephony
from backend.services.twilio_signature import verify_twilio_request, verify_twilio_stream
from backend.services.voice_checkpoint import VoiceCheckpoint
from backend.services.voice_pipeline import create_voice_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio-callbacks"])


# ── Twilio status → our CallStatus mapping ────────────────────────
#
# None means "acknowledge, but don't change the donor's state". Anything
# Twilio sends that is not listed here is ignored rather than treated as a
# decline: previously an unexpected status marked the donor as declined.

_TWILIO_STATUS_MAP = {
    "queued": None,
    "initiated": None,
    "ringing": None,  # dashboard already shows ringing from dispatch
    "in-progress": CallStatus.ANSWERED,
    "completed": None,  # outcome comes from the voice intent, not hang-up
    "busy": CallStatus.NO_ANSWER,
    "no-answer": CallStatus.NO_ANSWER,
    # The donor was never reached, so these are not a decision.
    "failed": CallStatus.NO_ANSWER,
    "canceled": CallStatus.NO_ANSWER,
}


def map_twilio_status(twilio_status: str, current: Optional[str]) -> Optional[CallStatus]:
    """
    Translate a Twilio call status into our CallStatus, or None to ignore it.

    Telephony events never overwrite a decision the donor has already made:
    a late "answered" webhook must not flip an accepted donor back.
    """
    mapped = _TWILIO_STATUS_MAP.get((twilio_status or "").lower())
    if mapped is None:
        return None
    if current:
        try:
            current_status = CallStatus(current)
        except ValueError:
            current_status = None
        if current_status in TERMINAL_OR_DECIDED:
            return None
    return mapped


# ── GET/POST /api/twilio/twiml ────────────────────────────────────


@router.post("/api/twilio/twiml", dependencies=[Depends(verify_twilio_request)])
@router.get("/api/twilio/twiml", dependencies=[Depends(verify_twilio_request)])
async def get_twiml(
    request: Request,
    dispatch_id: str = Query(default=""),
    donor_id: str = Query(default=""),
    resume: bool = Query(default=False),
):
    """
    Returns the TwiML XML that instructs Twilio to connect the call
    to our Audio Stream WebSocket for real-time Sarvam AI conversational processing.
    """
    params = await request.form() if request.method == "POST" else request.query_params
    answered_by = str(params.get("AnsweredBy", "")).lower()
    sid = str(params.get("CallSid", ""))
    if resume:
        # A signed continuation after <Connect> only resumes its own unfinished call.
        checkpoint = VoiceCheckpoint(sid, dispatch_id, donor_id)
        if not sid or not await checkpoint.can_resume():
            return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
        donor = await dispatch_store.get_donor(dispatch_id, donor_id)
        if (
            not donor
            or donor.get("status") not in {"ringing", "answered"}
            or donor.get("call_sid") not in (None, "", sid)
        ):
            return Response(content="<Response><Hangup/></Response>", media_type="application/xml")
    if (
        answered_by == "fax"
        or answered_by.startswith("machine_")
        or (settings.twilio_machine_detection and answered_by != "human" and not resume)
    ):
        if sid and dispatch_id and donor_id:
            updated = await dispatch_store.update_donor_status(
                dispatch_id, donor_id, CallStatus.NO_ANSWER, only_from=("ringing", "answered"), call_sid=sid
            )
            if updated:
                donor = await dispatch_store.get_donor(dispatch_id, donor_id)
                if donor:
                    await manager.broadcast(
                        dispatch_id,
                        DonorStatusUpdate(donor_id=donor_id, name=donor["name"], status=CallStatus.NO_ANSWER),
                    )
        return Response(content="<Response><Hangup/></Response>", media_type="application/xml")

    ws_url = settings.server_base_url.replace("http", "ws") + settings.twilio_audio_ws_path

    xml_safe_url = html.escape(ws_url)
    continuation = ""
    if settings.redis_url and not resume:
        query = urlencode({"dispatch_id": dispatch_id, "donor_id": donor_id, "resume": "true"})
        redirect = f"{settings.server_base_url.rstrip('/')}/api/twilio/twiml?{query}"
        continuation = f'<Redirect method="POST">{html.escape(redirect)}</Redirect>'

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{xml_safe_url}">
            <Parameter name="dispatch_id" value="{html.escape(dispatch_id, quote=True)}" />
            <Parameter name="donor_id" value="{html.escape(donor_id, quote=True)}" />
        </Stream>
    </Connect>
    {continuation}
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ── POST /api/twilio/gather ──────────────────────────────────────


@router.post("/api/twilio/gather", dependencies=[Depends(verify_twilio_request)])
async def twilio_gather(
    dispatch_id: str = Query(default=""),
    donor_id: str = Query(default=""),
    Digits: str = Form(default=""),
    CallSid: str = Form(default=""),
):
    """
    Handles the donor's keypress response from <Gather>.
    Press 1 = accepted, Press 2 (or anything else) = declined.
    """
    logger.info(
        "Gather response: Digits=%s dispatch_id=%s donor_id=%s",
        Digits,
        dispatch_id,
        donor_id,
    )

    if Digits == "1":
        # Donor accepted
        new_status = CallStatus.ACCEPTED
        intent = "accepted"
        say_text = "Thank you for accepting! A representative will contact you shortly with directions to the hospital. Your generosity saves lives."
    else:
        # Donor declined or invalid input
        new_status = CallStatus.DECLINED
        intent = "declined"
        say_text = "Thank you for your time. We understand. Goodbye."

    updated = False
    if dispatch_id and donor_id and Digits in {"1", "2"}:
        updated = await dispatch_store.update_donor_status(
            dispatch_id,
            donor_id,
            new_status,
            eta_minutes=15 if intent == "accepted" else None,
            only_from=("ringing", "answered", "no_answer"),
            call_sid=CallSid,
        )
    if not updated:
        say_text = "Thank you. Goodbye."
    if updated:
        # Broadcast to dashboard via WebSocket
        donor = await dispatch_store.get_donor(dispatch_id, donor_id)
        donor_name = donor.get("name", "Unknown") if donor else "Unknown"
        ws_update = DonorStatusUpdate(
            donor_id=donor_id,
            name=donor_name,
            status=new_status,
            eta_minutes=15 if intent == "accepted" else None,
        )
        await manager.broadcast(dispatch_id, ws_update)
        logger.info("Broadcast %s for donor %s (dispatch %s)", intent, donor_id, dispatch_id)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>{say_text}</Say>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ── POST /api/twilio/status-callback ─────────────────────────────


@router.post("/api/twilio/status-callback", dependencies=[Depends(verify_twilio_request)])
async def twilio_status_callback(
    CallSid: str = Form(default=""),
    CallStatus_param: str = Form(default="", alias="CallStatus"),
    dispatch_id: str = Query(default=""),
    donor_id: str = Query(default=""),
):
    """
    Webhook endpoint that Twilio POSTs to whenever a call's status changes.
    """
    logger.info(
        "Twilio callback: SID=%s Status=%s dispatch_id=%s donor_id=%s",
        CallSid,
        CallStatus_param,
        dispatch_id,
        donor_id,
    )

    if not dispatch_id or not donor_id:
        logger.warning("Twilio callback missing query params for SID: %s", CallSid)
        return {"status": "ignored", "reason": "missing params"}

    # Map Twilio status to our enum, respecting any decision already made.
    current = await dispatch_store.get_donor(dispatch_id, donor_id)
    mapped_status = map_twilio_status(CallStatus_param, current.get("status") if current else None)

    if mapped_status is None:
        logger.debug(
            "Twilio status '%s' for SID %s — no status update emitted",
            CallStatus_param,
            CallSid,
        )
        return {"status": "ack", "call_sid": CallSid}

    # On MongoDB the no-answer transition and its delayed retry are one durable write.
    durable_retry = settings.db_backend == "mongodb" and mapped_status == CallStatus.NO_ANSWER
    updated = durable_retry and await schedule_retry(
        dispatch_id, donor_id, CallStatus_param.lower(), manager.broadcast, call_sid=CallSid
    )
    if not updated:
        updated = await dispatch_store.update_donor_status(
            dispatch_id,
            donor_id,
            mapped_status,
            only_from=("ringing", "answered"),
            call_sid=CallSid,
        )
        if updated and mapped_status == CallStatus.NO_ANSWER and not durable_retry:
            await schedule_retry(dispatch_id, donor_id, CallStatus_param.lower(), manager.broadcast, call_sid=CallSid)

    if updated:
        # Fetch the donor info to build the WebSocket payload.
        donor = await dispatch_store.get_donor(dispatch_id, donor_id)
        if donor:
            ws_update = DonorStatusUpdate(
                donor_id=donor_id,
                name=donor.get("name", "Unknown"),
                status=mapped_status,
                eta_minutes=donor.get("eta_minutes"),
            )
            await manager.broadcast(dispatch_id, ws_update)
            logger.info(
                "Broadcast %s for donor %s (dispatch %s)",
                mapped_status.value,
                donor_id,
                dispatch_id,
            )

    return {"status": "ok", "call_sid": CallSid, "mapped_status": mapped_status.value}


# ── WebSocket /ws/twilio/audio-stream ─────────────────────────────


@router.websocket("/ws/twilio/audio-stream")
async def twilio_audio_stream(websocket: WebSocket):
    """
    WebSocket endpoint for Twilio to stream live call audio.
    Twilio sends JSON messages with Base64 audio chunks.
    """

    if not verify_twilio_stream(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    logger.info("Audio stream WebSocket connected")

    session = None
    checkpoint = None
    stream_sid = ""
    dispatch_id = ""
    donor_id = ""

    async def send_audio(audio):
        # Only the AI engine uses playback acknowledgements; preserve legacy flow.
        playback_started = getattr(session, "playback_started", None)
        mark = playback_started() if callable(playback_started) else None
        await websocket.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(audio).decode("utf-8")},
                }
            )
        )
        if mark:
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": mark},
                    }
                )
            )
        return mark

    async def finish_audio(audio):
        mark = await send_audio(audio)
        if mark:

            async def wait_for_playback():
                while True:
                    event = json.loads(await websocket.receive_text())
                    if event.get("event") == "stop":
                        return
                    if event.get("event") == "mark" and event.get("mark", {}).get("name") == mark:
                        return

            try:
                await asyncio.wait_for(wait_for_playback(), timeout=20)
            except TimeoutError:
                logger.warning("Closing voice playback acknowledgement timed out")

    try:
        while True:
            if session is not None and hasattr(session, "playback_started"):
                # A lost mark or stalled stream must not leave a call open forever.
                try:
                    data_str = await asyncio.wait_for(websocket.receive_text(), timeout=35)
                except TimeoutError:
                    logger.warning("AI voice stream idle; ending without another decision")
                    if checkpoint is not None:
                        await checkpoint.save(*session.checkpoint_state(), ended=True)
                    break
            else:
                data_str = await websocket.receive_text()
            msg = json.loads(data_str)

            if msg["event"] == "start":
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"]["callSid"]

                # Extract params passed via <Parameter> tags
                custom_params = msg["start"].get("customParameters", {})
                dispatch_id = custom_params.get("dispatch_id", "")
                donor_id = custom_params.get("donor_id", "")

                if session is not None or not call_sid or not dispatch_id or not donor_id:
                    logger.warning("Audio stream missing customParameters — closing")
                    await websocket.close(code=1008, reason="Missing params")
                    return

                # Fetch donor info for language selection.
                donor = await dispatch_store.get_donor(dispatch_id, donor_id)
                if (
                    not donor
                    or donor.get("status") in TERMINAL_OR_DECIDED
                    or donor.get("call_sid") not in (None, "", call_sid)
                ):
                    await websocket.close(code=1008, reason="Inactive call")
                    return
                language = donor.get("language", "english")

                # Get dispatch info for the hospital context.
                dispatch = await dispatch_store.get_dispatch(dispatch_id)
                hospital_id = dispatch.get("hospital_id", "") if dispatch else ""
                blood_group = dispatch.get("blood_group", "") if dispatch else ""

                checkpoint = VoiceCheckpoint(call_sid, dispatch_id, donor_id)
                saved = await checkpoint.attach(settings.voice_intent_mode)
                if saved.get("ended") == "1":
                    await websocket.close()
                    return
                session = create_voice_session(
                    mode=saved["mode"],
                    call_sid=call_sid,
                    dispatch_id=dispatch_id,
                    donor_id=donor_id,
                    donor_name=donor.get("name", "Donor") if donor else "Donor",
                    language=language,
                    hospital_id=hospital_id,
                    blood_group=blood_group,
                )
                logger.info(
                    "Twilio stream started. StreamSid: %s, CallSid: %s, donor: %s", stream_sid, call_sid, donor_id
                )

                # Send the greeting immediately when stream starts
                greeting_audio = await session.opening_audio(saved)
                if greeting_audio:
                    await send_audio(greeting_audio)
                elif hasattr(session, "playback_started"):
                    await checkpoint.save(*session.checkpoint_state(), ended=True)
                    break

            elif msg["event"] == "mark":
                if session is not None and hasattr(session, "playback_finished"):
                    session.playback_finished(msg.get("mark", {}).get("name", ""))

            elif msg["event"] == "media":
                if session is None or msg.get("media", {}).get("track", "inbound") != "inbound":
                    continue
                audio_bytes = base64.b64decode(msg["media"]["payload"])

                # Process through the voice pipeline.
                response_audio, intent = await session.handle_audio_chunk(audio_bytes)

                # Check ownership only at turn boundaries, never per audio frame.
                if (
                    (response_audio or intent)
                    and checkpoint is not None
                    and not await checkpoint.save(*session.checkpoint_state(), ended=intent == "unconfirmed")
                ):
                    break

                # If the pipeline produced a TTS response, send it back.
                if response_audio:
                    await send_audio(response_audio)

                if intent == "unconfirmed":
                    # Do not record silence, errors or ambiguity as a donor decision.
                    closing = await session._speak(
                        "We could not confirm your response. This request has not been accepted. Goodbye."
                    )
                    if closing:
                        await finish_audio(closing)
                    break

                # If an intent was resolved, update the dispatch state.
                if intent in ("accepted", "declined"):
                    new_status = CallStatus.ACCEPTED if intent == "accepted" else CallStatus.DECLINED
                    updated = await dispatch_store.update_donor_status(
                        dispatch_id,
                        donor_id,
                        new_status,
                        eta_minutes=session.eta_minutes,
                        only_from=("ringing", "answered", "no_answer"),
                        call_sid=call_sid,
                    )
                    if not updated:
                        break
                    # Broadcast to dashboard.
                    ws_update = DonorStatusUpdate(
                        donor_id=donor_id,
                        name=session.donor_name,
                        status=new_status,
                        eta_minutes=session.eta_minutes,
                    )
                    await manager.broadcast(dispatch_id, ws_update)
                    logger.info(
                        "Voice intent '%s' for donor %s (dispatch %s)",
                        intent,
                        donor_id,
                        dispatch_id,
                    )

                    # ── Post-acceptance routing ───────────────────────
                    if intent == "accepted":
                        routed = await _route_accepted_donor(
                            dispatch_id=dispatch_id,
                            donor_id=donor_id,
                            donor=donor,
                            dispatch=dispatch,
                        )
                        if routed:
                            updated = await dispatch_store.update_donor_status(
                                dispatch_id,
                                donor_id,
                                CallStatus.EN_ROUTE,
                                eta_minutes=session.eta_minutes,
                                only_from=("accepted",),
                                call_sid=call_sid,
                            )
                            if not updated:
                                break
                            await manager.broadcast(
                                dispatch_id,
                                DonorStatusUpdate(
                                    donor_id=donor_id,
                                    name=session.donor_name,
                                    status=CallStatus.EN_ROUTE,
                                    eta_minutes=session.eta_minutes,
                                ),
                            )

                    # Deliver a closing message and end the session.
                    if intent == "accepted":
                        closing_audio = await session.generate_closing_message(accepted=True)
                    else:
                        closing_audio = await session.generate_closing_message(accepted=False)

                    if closing_audio:
                        await finish_audio(closing_audio)

                    break

            elif msg["event"] == "stop":
                logger.info("Twilio stream stopped for StreamSid: %s", stream_sid)
                break

    except WebSocketDisconnect:
        logger.info("Audio stream disconnected")
    except Exception as exc:
        logger.error("Audio stream error: %s", exc)


# ── Post-acceptance routing (called from audio stream) ────────────


async def _route_accepted_donor(
    dispatch_id: str,
    donor_id: str,
    donor: Optional[dict],
    dispatch: Optional[dict],
) -> bool:
    """Send the accepted donor directions. Returns True if something was sent."""

    if not donor or not dispatch:
        logger.warning("Cannot route donor %s — missing context", donor_id)
        return False

    has_app = donor.get("has_app", False)
    phone = donor.get("phone", "")
    hospital_id = dispatch.get("hospital_id", "")
    blood_group = dispatch.get("blood_group", "")

    if has_app:
        try:
            push_token = await get_donor_push_token(donor_id)
            if push_token:
                await send_dispatch_notification(
                    expo_token=push_token,
                    dispatch_id=dispatch_id,
                    hospital_id=hospital_id,
                    blood_group=blood_group,
                    hospital_lat=dispatch.get("lat", 0.0),
                    hospital_lng=dispatch.get("lng", 0.0),
                )
                logger.info("Donor %s routed via push notification", donor_id)
                return True
            logger.warning(
                "Donor %s has_app=true but no push token — SMS fallback",
                donor_id,
            )
        except Exception as exc:
            logger.error("Push failed for donor %s: %s — SMS fallback", donor_id, exc)

    # Fallback — SMS with tracking link.
    if phone:
        tracking_url = (
            f"https://www.google.com/maps/search/?api=1&query={dispatch.get('lat', 0.0)},{dispatch.get('lng', 0.0)}"
        )
        try:
            await get_telephony().send_sms(
                phone=phone,
                message=f"Thank you for accepting! Navigate to the hospital: {tracking_url}",
            )
            logger.info("Donor %s routed via SMS tracking link", donor_id)
            return True
        except Exception as exc:
            logger.error("SMS failed for donor %s: %s", donor_id, exc)
    else:
        logger.error("Donor %s has no phone number — cannot route", donor_id)
    return False
