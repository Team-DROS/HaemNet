"""
REST API routes for the AI Blood Dispatch Network.

All endpoints are mounted under ``/api``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from backend.api.websockets import manager
from backend.api.auth import get_current_donor, get_current_hospital
from backend.db_services import (
    db_eligible_counts_by_group,
    db_get_hospital_by_id,
    delete_donor,
    find_eligible_donors,
    get_donor_by_phone,
    register_donor,
    update_donation_date,
)
from backend.dispatch_store import dispatch_store
from backend.orchestration.graph import DispatchState, dispatch_graph
from backend.schemas.models import (
    CallStatus,
    DispatchRequest,
    DispatchResponse,
    DonationLog,
    DonorRegistration,
    DonorResponse,
    DonorStatusUpdate,
    TERMINAL_OR_DECIDED,
    normalise_language,
)
from backend.services.geo import estimate_eta_minutes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dispatch"])


# ── Helpers ───────────────────────────────────────────────────────

def _public_dispatch(dispatch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dispatch state as the hospital dashboard sees it.

    Donor phone numbers stay on the server: the dashboard identifies donors
    by ID and name, and never needs to contact them directly.
    """
    donors = [
        {
            "donor_id": d.get("donor_id"),
            "name": d.get("name"),
            "status": d.get("status") or CallStatus.RINGING.value,
            "eta_minutes": d.get("eta_minutes"),
            "distance_km": d.get("distance_km"),
            "language": d.get("language"),
        }
        for d in (dispatch.get("donors") or {}).values()
    ]
    donors.sort(key=lambda d: (d["distance_km"] is None, d["distance_km"] or 0))
    return {
        "dispatch_id": dispatch.get("dispatch_id"),
        "blood_group": dispatch.get("blood_group"),
        "units": dispatch.get("units") or 1,
        "urgency": dispatch.get("urgency") or "urgent",
        "address": dispatch.get("address") or "",
        "created_at": dispatch.get("created_at"),
        "is_complete": bool(dispatch.get("is_complete")),
        "donors": donors,
    }


async def _owned_dispatch(dispatch_id: str, hospital_id: str) -> Dict[str, Any]:
    """Load a dispatch, 404 if missing, 403 if it belongs to another hospital."""
    dispatch = await dispatch_store.get_dispatch(dispatch_id)
    if not dispatch:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    if dispatch.get("hospital_id") != hospital_id:
        raise HTTPException(status_code=403, detail="Dispatch belongs to another hospital")
    return dispatch


def _phone_variants(phone: str) -> List[str]:
    digits = "".join(ch for ch in phone if ch.isdigit())
    local = digits[-10:]
    return list({phone, local, f"+91{local}", f"91{local}"})


def _require_same_donor(claimed_phone: Optional[str], token_phone: str) -> None:
    """A donor token only unlocks that donor's own records."""
    if claimed_phone and not set(_phone_variants(claimed_phone)) & set(_phone_variants(token_phone)):
        raise HTTPException(status_code=403, detail="This phone number is not yours")


# ── POST /api/dispatch ────────────────────────────────────────────

@router.post("/dispatch", response_model=DispatchResponse)
async def trigger_dispatch(
    payload: DispatchRequest,
    background_tasks: BackgroundTasks,
    hospital_id: str = Depends(get_current_hospital)
):
    """
    Emergency dispatch trigger.

    1. Queries Neo4j for eligible donors (blood group + 10 km radius + 56-day cooldown).
    2. Kicks off the LangGraph orchestration pipeline in the background.
    3. Returns immediately with a dispatch ID and donor count.

    The dispatch is always recorded against the authenticated hospital, not
    the ``hospital_id`` in the body, so one hospital cannot raise requests
    in another's name.
    """
    if payload.hospital_id != hospital_id:
        logger.warning(
            "Dispatch body hospital_id=%s differs from token hospital=%s; using token",
            payload.hospital_id, hospital_id,
        )

    dispatch_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    # Geocode if coordinates are missing/zero and address is provided
    lat = payload.coordinates.lat
    lng = payload.coordinates.lng
    if lat == 0.0 and lng == 0.0 and payload.address:
        from backend.services.geocoding import geocode_address
        coords = await geocode_address(payload.address)
        if coords:
            lat, lng = coords

    # Step 1 — find eligible donors
    donors = await find_eligible_donors(
        blood_group=payload.blood_group,
        lat=lat,
        lng=lng,
    )

    if not donors:
        return DispatchResponse(
            dispatch_id=dispatch_id,
            donors_matched=0,
            message="No eligible donors found within 10 km. Consider expanding search radius.",
            created_at=created_at,
        )

    # Step 2 — prepare initial state for LangGraph
    initial_state: dict = DispatchState(
        dispatch_id=dispatch_id,
        hospital_id=hospital_id,
        blood_group=payload.blood_group,
        urgency=payload.urgency.value,
        units=payload.units,
        address=payload.address or "",
        lat=lat,
        lng=lng,
    ).model_dump()

    # Step 3 — run orchestration in the background so we return fast.
    # Bind ownership first so live events only reach this hospital.
    manager.bind(dispatch_id, hospital_id)
    background_tasks.add_task(_run_dispatch_graph, dispatch_id, initial_state)

    logger.info(
        "Dispatch %s created — %d donors matched (hospital=%s, blood=%s, units=%d)",
        dispatch_id, len(donors), hospital_id, payload.blood_group, payload.units,
    )

    return DispatchResponse(
        dispatch_id=dispatch_id,
        donors_matched=len(donors),
        message="Dispatch initiated. Connect to /ws/dashboard for live updates.",
        created_at=created_at,
    )


async def _run_dispatch_graph(dispatch_id: str, initial_state: dict) -> None:
    """
    Execute the LangGraph dispatch pipeline and broadcast updates
    over WebSocket as the graph progresses.
    """
    try:
        result = await dispatch_graph.ainvoke(initial_state)

        # Broadcast any updates the graph produced.
        for update in result.get("updates", []):
            ws_update = DonorStatusUpdate(**update)
            await manager.broadcast(dispatch_id, ws_update)

        logger.info("Dispatch %s graph completed", dispatch_id)

    except Exception as exc:
        logger.exception("Dispatch %s graph failed: %s", dispatch_id, exc)
        # Notify connected dashboards of the failure.
        await manager.broadcast_raw(dispatch_id, {
            "type": "error",
            "message": str(exc),
        })


# ── GET /api/dispatches/active ────────────────────────────────────

@router.get("/dispatches/active")
async def list_active_dispatches(hospital_id: str = Depends(get_current_hospital)):
    """
    Every open dispatch for the signed-in hospital with current donor states.

    Lets the dashboard restore live emergencies after a page reload instead
    of starting empty while calls are still in progress.
    """
    dispatches = await dispatch_store.active_for_hospital(hospital_id)
    return {"dispatches": [_public_dispatch(d) for d in dispatches]}


# ── GET /api/dispatches/history ───────────────────────────────────

def _history_status(row: Dict[str, Any]) -> str:
    if not row.get("is_complete"):
        return "active"
    if row.get("fulfilled"):
        return "fulfilled"
    return "partial" if row.get("donated") else "closed"


@router.get("/dispatches/history")
async def dispatch_history(
    days: int = Query(30, ge=1, le=365),
    hospital_id: str = Depends(get_current_hospital),
):
    """
    Outcome of every request the hospital raised in the last `days` days.

    Powers Network Intelligence, so analytics are the same on every staff
    browser instead of living in one browser's storage. No donor details.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = await dispatch_store.history_for_hospital(hospital_id, since)
    return {"days": days, "dispatches": [{
        "dispatch_id": r["dispatch_id"],
        "blood_group": r.get("blood_group"),
        "units": r.get("units") or 1,
        "urgency": r.get("urgency") or "urgent",
        "created_at": r.get("created_at"),
        "first_accept_at": r.get("first_accept_at"),
        "closed_at": r.get("closed_at"),
        "status": _history_status(r),
        "matched": r.get("matched") or 0,
        "contacted": r.get("matched") or 0,  # every matched donor is dialled
        "answered": r.get("answered") or 0,
        "accepted": r.get("accepted") or 0,
        "donated": r.get("donated") or 0,
    } for r in rows]}


# ── GET /api/network/availability ─────────────────────────────────

BLOOD_GROUPS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
_hospital_coords_cache: Dict[str, tuple] = {}


@router.get("/network/availability")
async def network_availability(
    radius_km: float = 10.0,
    hospital_id: str = Depends(get_current_hospital),
):
    """
    Eligible donors per blood group within ``radius_km`` of this hospital,
    using the same cooldown rule as dispatch matching.

    Hospital coordinates come from geocoding the hospital's registered
    location once and caching it for the life of the process.
    """
    radius_km = max(1.0, min(radius_km, 50.0))
    coords = _hospital_coords_cache.get(hospital_id)
    if coords is None:
        hospital = await db_get_hospital_by_id(hospital_id)
        location = dict(hospital).get("location") if hospital else None
        if location:
            from backend.services.geocoding import geocode_address
            coords = await geocode_address(location)
        if not coords:
            raise HTTPException(
                status_code=422,
                detail="Hospital location could not be geocoded; update the hospital address.",
            )
        _hospital_coords_cache[hospital_id] = coords

    counts = await db_eligible_counts_by_group(coords[0], coords[1], radius_km=radius_km)
    groups = {group: int(counts.get(group, 0)) for group in BLOOD_GROUPS}
    return {
        "radius_km": radius_km,
        "lat": coords[0],
        "lng": coords[1],
        "groups": groups,
        "total": sum(groups.values()),
    }


# ── POST /api/dispatches/{dispatch_id}/close ──────────────────────

@router.post("/dispatches/{dispatch_id}/close")
async def close_dispatch(dispatch_id: str, hospital_id: str = Depends(get_current_hospital)):
    """Mark a dispatch as finished (fulfilled or cancelled by the hospital)."""
    await _owned_dispatch(dispatch_id, hospital_id)
    await dispatch_store.mark_complete(dispatch_id)
    await manager.broadcast_raw(dispatch_id, {"type": "dispatch_closed"})
    return {"status": "ok", "dispatch_id": dispatch_id}


# ── POST /api/donate — Log a Successful Donation ─────────────────

@router.post("/donate")
async def log_donation(
    payload: DonationLog,
    hospital_id: str = Depends(get_current_hospital)
):
    """
    Called by hospital staff after a successful transfusion.
    Updates the donor's `last_donated_date` in Neo4j, activating
    the 56-day medical cooldown.

    When ``dispatch_id`` is given, the donor is also marked as donated in
    that dispatch, and the dispatch closes itself once enough units are in.
    """
    dispatch = None
    if payload.dispatch_id:
        dispatch = await _owned_dispatch(payload.dispatch_id, hospital_id)

    success = await update_donation_date(
        donor_id=payload.donor_id,
        donated_at=datetime.now(timezone.utc),
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update donation record.")

    logger.info("Donation logged for donor %s at hospital %s", payload.donor_id, hospital_id)

    fulfilled = False
    if dispatch is not None:
        await dispatch_store.update_donor_status(
            payload.dispatch_id, payload.donor_id, CallStatus.DONATED,
        )
        donor = (dispatch.get("donors") or {}).get(payload.donor_id, {})
        await manager.broadcast(payload.dispatch_id, DonorStatusUpdate(
            donor_id=payload.donor_id,
            name=donor.get("name", "Donor"),
            status=CallStatus.DONATED,
        ))

        donated = sum(
            1 for d in (dispatch.get("donors") or {}).values()
            if d.get("status") == CallStatus.DONATED.value and d.get("donor_id") != payload.donor_id
        ) + 1
        if donated >= (dispatch.get("units") or 1):
            fulfilled = True
            await dispatch_store.mark_complete(payload.dispatch_id, fulfilled=True)
            await manager.broadcast_raw(payload.dispatch_id, {"type": "dispatch_fulfilled"})

    return {
        "status": "ok",
        "donor_id": payload.donor_id,
        "cooldown_until": (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=56)).isoformat(),
        "dispatch_fulfilled": fulfilled,
        "message": "Donation recorded. Donor is now on 56-day cooldown.",
    }


# ── POST /api/donor/register ───────────────────────────────────────

@router.post("/donor/register")
async def register_new_donor(payload: DonorRegistration, donor_phone: str = Depends(get_current_donor)):
    """
    Called by the mobile app to register a new donor or update an existing one.
    The phone must be the one the donor verified by SMS.
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
        )
        return {"status": "ok", "message": "Donor successfully registered"}
    except Exception as exc:
        logger.exception("Failed to register donor: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to register donor")


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
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to get donor profile: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to get donor profile")


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
        raise HTTPException(status_code=500, detail="Failed to delete donor profile")


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
    for variant in _phone_variants(donor_phone):
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

    variants = set(_phone_variants(donor_phone))
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
            CallStatus.ACCEPTED, CallStatus.EN_ROUTE, CallStatus.COMPLETED, CallStatus.DONATED,
        }
        if already_accepted == payload.accept:
            return {"status": "ok", "donor_status": current, "unchanged": True}
        raise HTTPException(status_code=409, detail="You have already responded to this request")

    eta = estimate_eta_minutes(donor.get("distance_km")) if payload.accept else None
    await dispatch_store.update_donor_status(payload.dispatch_id, donor_id, wanted, eta_minutes=eta)
    await manager.broadcast(payload.dispatch_id, DonorStatusUpdate(
        donor_id=donor_id, name=donor.get("name", "Donor"), status=wanted, eta_minutes=eta,
    ))

    final_status = wanted
    if payload.accept:
        await dispatch_store.update_donor_status(
            payload.dispatch_id, donor_id, CallStatus.EN_ROUTE, eta_minutes=eta,
        )
        await manager.broadcast(payload.dispatch_id, DonorStatusUpdate(
            donor_id=donor_id, name=donor.get("name", "Donor"),
            status=CallStatus.EN_ROUTE, eta_minutes=eta,
        ))
        final_status = CallStatus.EN_ROUTE

    logger.info("Donor %s responded %s in app (dispatch %s)", donor_id, wanted.value, payload.dispatch_id)
    return {
        "status": "ok",
        "donor_status": final_status.value,
        "eta_minutes": eta,
        "hospital": {"lat": dispatch.get("lat"), "lng": dispatch.get("lng"), "address": dispatch.get("address")},
    }


# ── GET /api/health ───────────────────────────────────────────────

@router.get("/health")
async def health_check():
    """Advanced liveness and readiness probe."""
    from backend.db_services import _get_driver
    db_status = "unknown"
    try:
        driver = _get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        db_status = "connected"
    except Exception as e:
        db_status = f"disconnected: {str(e)}"
        logger.error("Health check failed to connect to Neo4j: %s", e)

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": "blood-dispatch-backend",
        "neo4j": db_status
    }
