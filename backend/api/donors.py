"""Donor-facing endpoints: profile, call preference, open requests and in-app answers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.auth import get_current_donor
from backend.api.websockets import manager
from backend.db_services import (
    db_set_calls_opt_out,
    delete_donor,
    get_donor_by_phone,
    register_donor,
)
from backend.dispatch_store import dispatch_store
from backend.schemas.models import (
    TERMINAL_OR_DECIDED,
    CallStatus,
    DonorRegistration,
    DonorResponse,
    DonorStatusUpdate,
    normalise_language,
)
from backend.services.donor_availability import MAX_PAUSE_DAYS, is_paused, pause_calls
from backend.services.donor_push import save_push_token
from backend.services.geo import estimate_eta_minutes
from backend.services.phone import phone_variants

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["donors"])


def _require_same_donor(claimed_phone: Optional[str], token_phone: str) -> None:
    """A donor token only unlocks that donor's own records."""
    if claimed_phone and not set(phone_variants(claimed_phone)) & set(phone_variants(token_phone)):
        raise HTTPException(status_code=403, detail="This phone number is not yours")


@router.post("/donor/register")
async def register_new_donor(payload: DonorRegistration, donor_phone: str = Depends(get_current_donor)):
    """
    Called by the mobile app to register a new donor or update an existing one.
    The phone must be the one the donor signed in with.
    """
    _require_same_donor(payload.phone, donor_phone)
    try:
        await register_donor(
            name=payload.name,
            phone=donor_phone,
            blood_group=payload.blood_group,
            language=normalise_language(payload.language),
            lat=payload.lat,
            lng=payload.lng,
            calls_consent=payload.calls_consent,
        )
        return {"status": "ok", "message": "Donor successfully registered"}
    except Exception as exc:
        logger.exception("Failed to register donor: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to register donor") from exc


# ── POST /api/donor/calls/preference ───────────────────────────────


class CallPreference(BaseModel):
    opt_out: bool


@router.post("/donor/calls/preference")
async def set_call_preference(payload: CallPreference, donor_phone: str = Depends(get_current_donor)):
    """Opt out of (or back into) automated emergency calls. Takes effect for the next request."""
    try:
        found = await db_set_calls_opt_out(donor_phone, payload.opt_out)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail="Call preferences need the MongoDB data layer") from exc
    if not found:
        raise HTTPException(status_code=404, detail="Complete your donor profile first")
    logger.info("Donor …%s set calls_opt_out=%s", donor_phone[-4:], payload.opt_out)
    return {"status": "ok", "calls_opt_out": payload.opt_out}


# ── POST /api/donor/availability ───────────────────────────────────


class AvailabilityUpdate(BaseModel):
    # Days without automated calls, counted from now. 0 ends a break early.
    pause_days: int = Field(..., ge=0, le=MAX_PAUSE_DAYS)


@router.post("/donor/availability")
async def set_availability(payload: AvailabilityUpdate, donor_phone: str = Depends(get_current_donor)):
    """Take a short break from automated calls ("not available this week"). Ends by itself."""
    try:
        found, until = await pause_calls(donor_phone, payload.pause_days)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail="Pausing calls needs the MongoDB data layer") from exc
    if not found:
        raise HTTPException(status_code=404, detail="Complete your donor profile first")
    return {"status": "ok", "calls_paused_until": until.isoformat() if until else None}


# ── POST /api/donor/push-token ─────────────────────────────────────


class PushTokenUpdate(BaseModel):
    # None or empty forgets the token (sign-out, or notifications turned off on the phone).
    token: Optional[str] = Field(None, max_length=256)


@router.post("/donor/push-token")
async def set_push_token(payload: PushTokenUpdate, donor_phone: str = Depends(get_current_donor)):
    """Register this phone for request alerts, or stop them. Only for the signed-in donor."""
    try:
        found = await save_push_token(donor_phone, payload.token)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail="Push tokens need the MongoDB data layer") from exc
    if not found:
        raise HTTPException(status_code=404, detail="Complete your donor profile first")
    return {"status": "ok", "push_enabled": bool(payload.token and payload.token.strip())}


# ── GET /api/donor/profile/{phone} ─────────────────────────────────


@router.get("/donor/profile/{phone}")
async def get_donor_profile(phone: str, donor_phone: str = Depends(get_current_donor)):
    """
    Called by the mobile app on startup to sync the donor's profile
    and cooldown status from the database.
    """
    _require_same_donor(phone, donor_phone)
    try:
        donor = await get_donor_by_phone(donor_phone)
        if not donor:
            raise HTTPException(status_code=404, detail="Donor not found")

        return {
            "status": "ok",
            "donor": {
                "id": donor.id,
                "name": donor.name,
                "phone": donor.phone,
                "blood_group": donor.blood_group,
                "last_donated_date": donor.last_donated_date.isoformat() if donor.last_donated_date else None,
                "calls_opt_out": donor.calls_opt_out,
                # Only a break still in effect is reported; an expired one reads as available.
                "calls_paused_until": donor.calls_paused_until.isoformat()
                if donor.calls_paused_until and is_paused(donor)
                else None,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get donor profile: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to get donor profile") from exc


# ── DELETE /api/donor/profile/{phone} ───────────────────────────────


@router.delete("/donor/profile/{phone}")
async def remove_donor_profile(phone: str, donor_phone: str = Depends(get_current_donor)):
    """
    Called by the mobile app to delete the donor's profile from the DB.
    """
    _require_same_donor(phone, donor_phone)
    try:
        success = await delete_donor(donor_phone)
        if not success:
            raise HTTPException(status_code=404, detail="Donor not found")

        return {"status": "ok", "message": "Donor successfully deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to delete donor profile: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to delete donor profile") from exc


# ── GET /api/donor/requests/{phone} ────────────────────────────────


@router.get("/donor/requests/{phone}")
async def get_donor_requests(phone: str, donor_phone: str = Depends(get_current_donor)):
    """
    Open emergency requests this donor has been matched to and not yet
    answered. The donor app polls this to show its urgent-request screen,
    so a donor who misses the AI call can still respond in one tap.
    """
    _require_same_donor(phone, donor_phone)
    requests: List[Dict[str, Any]] = []
    seen = set()
    for variant in phone_variants(donor_phone):
        for req in await dispatch_store.requests_for_donor(variant):
            if req["dispatch_id"] in seen:
                continue
            seen.add(req["dispatch_id"])
            req["eta_minutes"] = estimate_eta_minutes(req.get("distance_km"))
            requests.append(req)
    return {"requests": requests}


# ── POST /api/donor/respond ───────────────────────────────────────


@router.post("/donor/respond")
async def donor_respond(payload: DonorResponse, donor_phone: str = Depends(get_current_donor)):
    """
    A donor accepts or declines a request from the app.

    Updates the same CallSession the AI voice call uses and broadcasts to the
    hospital dashboard, so an in-app answer and a spoken answer look alike.
    An accepted donor has the hospital's location in the app, so they are
    marked en route straight away.
    """
    _require_same_donor(payload.phone, donor_phone)
    dispatch = await dispatch_store.get_dispatch(payload.dispatch_id)
    if not dispatch or dispatch.get("is_complete"):
        raise HTTPException(status_code=404, detail="This request is no longer open")

    variants = set(phone_variants(donor_phone))
    donor = next(
        (d for d in (dispatch.get("donors") or {}).values() if d.get("phone") in variants),
        None,
    )
    if not donor:
        raise HTTPException(status_code=404, detail="You were not matched to this request")

    donor_id = donor["donor_id"]
    current = donor.get("status")
    wanted = CallStatus.ACCEPTED if payload.accept else CallStatus.DECLINED

    # Idempotent: repeating the same answer is fine, changing it is not.
    try:
        current_status: Optional[CallStatus] = CallStatus(current) if current else None
    except ValueError:
        current_status = None
    if current_status in TERMINAL_OR_DECIDED:
        already_accepted = current_status in {
            CallStatus.ACCEPTED,
            CallStatus.EN_ROUTE,
            CallStatus.COMPLETED,
            CallStatus.DONATED,
        }
        if already_accepted == payload.accept:
            return {"status": "ok", "donor_status": current, "unchanged": True}
        raise HTTPException(status_code=409, detail="You have already responded to this request")

    eta = estimate_eta_minutes(donor.get("distance_km")) if payload.accept else None
    await dispatch_store.update_donor_status(payload.dispatch_id, donor_id, wanted, eta_minutes=eta)
    await manager.broadcast(
        payload.dispatch_id,
        DonorStatusUpdate(
            donor_id=donor_id,
            name=donor.get("name", "Donor"),
            status=wanted,
            eta_minutes=eta,
        ),
    )

    final_status = wanted
    if payload.accept:
        await dispatch_store.update_donor_status(
            payload.dispatch_id,
            donor_id,
            CallStatus.EN_ROUTE,
            eta_minutes=eta,
        )
        await manager.broadcast(
            payload.dispatch_id,
            DonorStatusUpdate(
                donor_id=donor_id,
                name=donor.get("name", "Donor"),
                status=CallStatus.EN_ROUTE,
                eta_minutes=eta,
            ),
        )
        final_status = CallStatus.EN_ROUTE

    logger.info("Donor %s responded %s in app (dispatch %s)", donor_id, wanted.value, payload.dispatch_id)
    return {
        "status": "ok",
        "donor_status": final_status.value,
        "eta_minutes": eta,
        "hospital": {"lat": dispatch.get("lat"), "lng": dispatch.get("lng"), "address": dispatch.get("address")},
    }
