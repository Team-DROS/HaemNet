"""
Twilio callback and audio-stream endpoints.

Routes:
  POST  /api/twilio/status-callback    — Twilio call-status webhook
  WS    /ws/twilio/audio-stream        — Twilio live audio WebSocket
"""

from __future__ import annotations

import json
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Form, Query, WebSocket, WebSocketDisconnect

from backend.api.websockets import manager
from backend.dispatch_store import dispatch_store
from backend.schemas.models import CallStatus, DonorStatusUpdate, TERMINAL_OR_DECIDED

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio-callbacks"])


# ── Twilio status → our CallStatus mapping ────────────────────────
#
# None means "acknowledge, but don't change the donor's state". Anything
# Twilio sends that is not listed here is ignored rather than treated as a
# decline: previously an unexpected status marked the donor as declined.

_TWILIO_STATUS_MAP = {
    "queued":      None,
    "initiated":   None,
    "ringing":     None,           # dashboard already shows ringing from dispatch
    "in-progress": CallStatus.ANSWERED,
    "completed":   None,           # outcome comes from the voice intent, not hang-up
    "busy":        CallStatus.NO_ANSWER,
    "no-answer":   CallStatus.NO_ANSWER,
    "failed":      CallStatus.DECLINED,
    "canceled":    CallStatus.DECLINED,
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

from fastapi.responses import Response
from backend.config import settings

@router.post("/api/twilio/twiml")
@router.get("/api/twilio/twiml")
async def get_twiml(dispatch_id: str = Query(default=""), donor_id: str = Query(default="")):
    """
    Returns the TwiML XML that instructs Twilio to connect the call
    to our Audio Stream WebSocket for real-time Sarvam AI conversational processing.
    """
    ws_url = settings.server_base_url.replace("http", "ws") + settings.twilio_audio_ws_path
    
    import html
    xml_safe_url = html.escape(ws_url)
    
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{xml_safe_url}">
            <Parameter name="dispatch_id" value="{dispatch_id}" />
            <Parameter name="donor_id" value="{donor_id}" />
        </Stream>
    </Connect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


# ── POST /api/twilio/gather ──────────────────────────────────────

@router.post("/api/twilio/gather")
async def twilio_gather(
    dispatch_id: str = Query(default=""),
    donor_id: str = Query(default=""),
    Digits: str = Form(default=""),
):
    """
    Handles the donor's keypress response from <Gather>.
    Press 1 = accepted, Press 2 (or anything else) = declined.
    """
    logger.info(
        "Gather response: Digits=%s dispatch_id=%s donor_id=%s",
        Digits, dispatch_id, donor_id,
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

    # Update dispatch store
    if dispatch_id and donor_id:
        await dispatch_store.update_donor_status(
            dispatch_id, donor_id, new_status,
            eta_minutes=15 if intent == "accepted" else None,
        )

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

@router.post("/api/twilio/status-callback")
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
        CallSid, CallStatus_param, dispatch_id, donor_id,
    )

    if not dispatch_id or not donor_id:
        logger.warning("Twilio callback missing query params for SID: %s", CallSid)
        return {"status": "ignored", "reason": "missing params"}

    # Map Twilio status to our enum, respecting any decision already made.
    current = await dispatch_store.get_donor(dispatch_id, donor_id)
    mapped_status = map_twilio_status(
        CallStatus_param, current.get("status") if current else None
    )

    if mapped_status is None:
        logger.debug(
            "Twilio status '%s' for SID %s — no status update emitted",
            CallStatus_param, CallSid,
        )
        return {"status": "ack", "call_sid": CallSid}

    # Update the in-memory store.
    updated = await dispatch_store.update_donor_status(
        dispatch_id, donor_id, mapped_status
    )

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
                mapped_status.value, donor_id, dispatch_id,
            )

    return {"status": "ok", "call_sid": CallSid, "mapped_status": mapped_status.value}


# ── WebSocket /ws/twilio/audio-stream ─────────────────────────────

@router.websocket("/ws/twilio/audio-stream")
async def twilio_audio_stream(websocket: WebSocket):
    """
    WebSocket endpoint for Twilio to stream live call audio.
    Twilio sends JSON messages with Base64 audio chunks.
    """
    from backend.services.voice_pipeline import active_sessions, VoiceSession

    await websocket.accept()
    logger.info("Audio stream WebSocket connected")

    session = None
    stream_sid = ""
    dispatch_id = ""
    donor_id = ""

    try:
        while True:
            data_str = await websocket.receive_text()
            msg = json.loads(data_str)
            
            if msg["event"] == "start":
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"]["callSid"]
                
                # Extract params passed via <Parameter> tags
                custom_params = msg["start"].get("customParameters", {})
                dispatch_id = custom_params.get("dispatch_id", "")
                donor_id = custom_params.get("donor_id", "")
                
                if not dispatch_id or not donor_id:
                    logger.warning("Audio stream missing customParameters — closing")
                    await websocket.close(code=1008, reason="Missing params")
                    return

                # Fetch donor info for language selection.
                donor = await dispatch_store.get_donor(dispatch_id, donor_id)
                language = donor.get("language", "english") if donor else "english"

                # Get dispatch info for the hospital context.
                dispatch = await dispatch_store.get_dispatch(dispatch_id)
                hospital_id = dispatch.get("hospital_id", "") if dispatch else ""
                blood_group = dispatch.get("blood_group", "") if dispatch else ""

                session = VoiceSession(
                    call_sid=call_sid, 
                    dispatch_id=dispatch_id,
                    donor_id=donor_id,
                    donor_name=donor.get("name", "Donor") if donor else "Donor",
                    language=language,
                    hospital_id=hospital_id,
                    blood_group=blood_group,
                )
                active_sessions[call_sid] = session
                logger.info("Twilio stream started. StreamSid: %s, CallSid: %s, donor: %s", stream_sid, call_sid, donor_id)
                
                # Send the greeting immediately when stream starts
                greeting_audio, _ = await session.handle_audio_chunk(b"")
                if greeting_audio:
                    out_msg = {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": base64.b64encode(greeting_audio).decode("utf-8")}
                    }
                    await websocket.send_text(json.dumps(out_msg))
                    
            elif msg["event"] == "media":
                audio_bytes = base64.b64decode(msg["media"]["payload"])
                
                # Process through the voice pipeline.
                response_audio, intent = await session.handle_audio_chunk(audio_bytes)

                # If the pipeline produced a TTS response, send it back.
                if response_audio:
                    out_msg = {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": base64.b64encode(response_audio).decode("utf-8")}
                    }
                    await websocket.send_text(json.dumps(out_msg))

                # If an intent was resolved, update the dispatch state.
                if intent in ("accepted", "declined"):
                    new_status = (
                        CallStatus.ACCEPTED if intent == "accepted"
                        else CallStatus.DECLINED
                    )
                    await dispatch_store.update_donor_status(
                        dispatch_id, donor_id, new_status,
                        eta_minutes=session.eta_minutes,
                    )
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
                        intent, donor_id, dispatch_id,
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
                            await dispatch_store.update_donor_status(
                                dispatch_id, donor_id, CallStatus.EN_ROUTE,
                                eta_minutes=session.eta_minutes,
                            )
                            await manager.broadcast(dispatch_id, DonorStatusUpdate(
                                donor_id=donor_id,
                                name=session.donor_name,
                                status=CallStatus.EN_ROUTE,
                                eta_minutes=session.eta_minutes,
                            ))

                    # Deliver a closing message and end the session.
                    if intent == "accepted":
                        closing_audio = await session.generate_closing_message(accepted=True)
                    else:
                        closing_audio = await session.generate_closing_message(accepted=False)
                        
                    if closing_audio:
                        out_msg = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": base64.b64encode(closing_audio).decode("utf-8")}
                        }
                        await websocket.send_text(json.dumps(out_msg))
                        
                    break

            elif msg["event"] == "stop":
                logger.info("Twilio stream stopped for StreamSid: %s", stream_sid)
                break

    except WebSocketDisconnect:
        logger.info("Audio stream disconnected")
    except Exception as exc:
        logger.error("Audio stream error: %s", exc)
    finally:
        # Cleanup the session. It is None if the stream closed before "start".
        if session is not None and session.call_sid:
            active_sessions.pop(session.call_sid, None)
            logger.debug("Voice session cleaned up for call_sid=%s", session.call_sid)


# ── Post-acceptance routing (called from audio stream) ────────────

async def _route_accepted_donor(
    dispatch_id: str,
    donor_id: str,
    donor: Optional[dict],
    dispatch: Optional[dict],
) -> bool:
    """Send the accepted donor directions. Returns True if something was sent."""
    from backend.db_services import get_donor_push_token
    from backend.services.twilio_service import send_sms
    from backend.services.push_service import send_dispatch_notification

    if not donor or not dispatch:
        logger.warning(
            "Cannot route donor %s — missing context", donor_id
        )
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
            else:
                logger.warning(
                    "Donor %s has_app=true but no push token — SMS fallback",
                    donor_id,
                )
        except Exception as exc:
            logger.error("Push failed for donor %s: %s — SMS fallback", donor_id, exc)

    # Fallback — SMS with tracking link.
    if phone:
        tracking_url = f"https://www.google.com/maps/search/?api=1&query={dispatch.get('lat', 0.0)},{dispatch.get('lng', 0.0)}"
        try:
            await send_sms(
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
