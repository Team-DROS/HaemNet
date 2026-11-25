"""Planning an emergency request: who can be called, and the state the call pipeline starts from.

Kept free of HTTP concerns so the rules can be read, tested and reused on their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from backend.db_services import find_eligible_donors
from backend.orchestration.graph import DispatchState
from backend.schemas.models import DispatchRequest
from backend.services.blood_groups import request_groups
from backend.services.call_guard import cap_donors
from backend.services.geocoding import geocode_address


@dataclass(frozen=True)
class PlannedDispatch:
    dispatch_id: str
    created_at: str
    donors_matched: int
    state: dict | None  # initial pipeline state, or None when nobody can be called


async def plan_dispatch(request: DispatchRequest, hospital_id: str) -> PlannedDispatch:
    """Find the donors to call (closest first, capped) and build the pipeline's starting state."""
    dispatch_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    lat, lng = request.coordinates.lat, request.coordinates.lng
    if lat == 0.0 and lng == 0.0 and request.address:
        coords = await geocode_address(request.address)
        if coords:
            lat, lng = coords

    donors = []
    for group in request_groups(request.blood_group):
        donors.extend(await find_eligible_donors(blood_group=group, lat=lat, lng=lng))
    donors = cap_donors(donors, lat, lng)
    if not donors:
        return PlannedDispatch(dispatch_id, created_at, 0, None)

    state = DispatchState(
        dispatch_id=dispatch_id,
        hospital_id=hospital_id,
        blood_group=request.blood_group,
        urgency=request.urgency.value,
        units=request.units,
        address=request.address or "",
        lat=lat,
        lng=lng,
    ).model_dump()
    return PlannedDispatch(dispatch_id, created_at, len(donors), state)
