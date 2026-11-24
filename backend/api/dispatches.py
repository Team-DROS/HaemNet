"""Hospital-facing endpoints: raise emergency requests, follow them and log donations."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from backend.api.auth import get_actor, get_current_hospital
from backend.api.dependencies import approved_hospital
from backend.api.websockets import manager
from backend.db_services import (
    db_eligible_counts_by_group,
    db_get_hospital_by_id,
    update_donation_date,
)
from backend.dispatch_store import dispatch_store
from backend.orchestration.graph import dispatch_graph
from backend.schemas.models import (
    CallStatus,
    DispatchRequest,
    DispatchResponse,
    DonationLog,
    DonorStatusUpdate,
)
from backend.services import hospital_platform as hp
from backend.services.call_guard import release_daily_quota, reserve_daily_quota
from backend.services.dispatching import plan_dispatch
from backend.services.geocoding import geocode_address

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


# ── POST /api/dispatch ────────────────────────────────────────────


@router.post("/dispatch", response_model=DispatchResponse)
async def trigger_dispatch(
    payload: DispatchRequest,
    background_tasks: BackgroundTasks,
    hospital_id: str = Depends(approved_hospital),
    actor: str = Depends(get_actor),
):
    """
    Raise an emergency request.

    Finds eligible donors (blood group, distance, 56-day cooldown, not opted out),
    starts the call pipeline in the background and returns at once with the
    dispatch ID and donor count. The request is always recorded against the
    authenticated hospital, never the ``hospital_id`` in the body.
    """
    if payload.hospital_id != hospital_id:
        logger.warning(
            "Dispatch body hospital_id=%s differs from token hospital=%s; using token",
            payload.hospital_id,
            hospital_id,
        )

    # Reserve the daily slot first so a burst of simultaneous requests cannot overshoot the cap.
    await reserve_daily_quota(hospital_id)
    try:
        planned = await plan_dispatch(payload, hospital_id)
    except BaseException:
        await release_daily_quota(hospital_id)  # nothing was dispatched: give the slot back
        raise

    if planned.state is None:
        await release_daily_quota(hospital_id)  # no calls placed, so it does not count
        return DispatchResponse(
            dispatch_id=planned.dispatch_id,
            donors_matched=0,
            message="No eligible donors found within 10 km. Consider expanding search radius.",
            created_at=planned.created_at,
        )

    # Bind ownership first so live events only reach this hospital.
    manager.bind(planned.dispatch_id, hospital_id)
    await hp.audit(
        hospital_id,
        actor,
        "dispatch_created",
        f"{planned.dispatch_id} {payload.blood_group} x{payload.units} {payload.urgency.value} "
        f"matched={planned.donors_matched}",
    )
    background_tasks.add_task(run_dispatch_graph, planned.dispatch_id, planned.state)

    logger.info(
        "Dispatch %s created: %d donors matched (hospital=%s, blood=%s, units=%d)",
        planned.dispatch_id,
        planned.donors_matched,
        hospital_id,
        payload.blood_group,
        payload.units,
    )
    return DispatchResponse(
        dispatch_id=planned.dispatch_id,
        donors_matched=planned.donors_matched,
        message="Dispatch initiated. Connect to /ws/dashboard for live updates.",
        created_at=planned.created_at,
    )


async def run_dispatch_graph(dispatch_id: str, initial_state: dict) -> None:
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
        await manager.broadcast_raw(
            dispatch_id,
            {
                "type": "error",
                "message": str(exc),
            },
        )


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
    return {
        "days": days,
        "dispatches": [
            {
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
            }
            for r in rows
        ],
    }


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
async def close_dispatch(
    dispatch_id: str, hospital_id: str = Depends(get_current_hospital), actor: str = Depends(get_actor)
):
    """Mark a dispatch as finished (fulfilled or cancelled by the hospital)."""
    await _owned_dispatch(dispatch_id, hospital_id)
    await dispatch_store.mark_complete(dispatch_id)
    await manager.broadcast_raw(dispatch_id, {"type": "dispatch_closed"})
    await hp.audit(hospital_id, actor, "dispatch_closed", dispatch_id)
    return {"status": "ok", "dispatch_id": dispatch_id}


# ── POST /api/donate — Log a Successful Donation ─────────────────


@router.post("/donate")
async def log_donation(
    payload: DonationLog,
    hospital_id: str = Depends(get_current_hospital),
    actor: str = Depends(get_actor),
):
    """
    Called by hospital staff after a successful transfusion.
    Updates the donor's `last_donated_date`, activating
    the 56-day medical cooldown.

    When ``dispatch_id`` is given, the donor is also marked as donated in
    that dispatch, and the dispatch closes itself once enough units are in.
    """
    dispatch_id = payload.dispatch_id
    dispatch = await _owned_dispatch(dispatch_id, hospital_id) if dispatch_id else None

    success = await update_donation_date(
        donor_id=payload.donor_id,
        donated_at=datetime.now(timezone.utc),
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update donation record.")

    logger.info("Donation logged for donor %s at hospital %s", payload.donor_id, hospital_id)
    await hp.audit(
        hospital_id, actor, "donation_logged", f"donor={payload.donor_id} dispatch={payload.dispatch_id or '-'}"
    )

    fulfilled = False
    if dispatch_id and dispatch is not None:
        await dispatch_store.update_donor_status(
            dispatch_id,
            payload.donor_id,
            CallStatus.DONATED,
        )
        donor = (dispatch.get("donors") or {}).get(payload.donor_id, {})
        await manager.broadcast(
            dispatch_id,
            DonorStatusUpdate(
                donor_id=payload.donor_id,
                name=donor.get("name", "Donor"),
                status=CallStatus.DONATED,
            ),
        )

        donated = (
            sum(
                1
                for d in (dispatch.get("donors") or {}).values()
                if d.get("status") == CallStatus.DONATED.value and d.get("donor_id") != payload.donor_id
            )
            + 1
        )
        if donated >= (dispatch.get("units") or 1):
            fulfilled = True
            await dispatch_store.mark_complete(dispatch_id, fulfilled=True)
            await manager.broadcast_raw(dispatch_id, {"type": "dispatch_fulfilled"})

    return {
        "status": "ok",
        "donor_id": payload.donor_id,
        "cooldown_until": (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=56)).isoformat(),
        "dispatch_fulfilled": fulfilled,
        "message": "Donation recorded. Donor is now on 56-day cooldown.",
    }
