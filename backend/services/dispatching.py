"""Planning an emergency request: who can be called, and the state the call pipeline starts from.

Kept free of HTTP concerns so the rules can be read, tested and reused on their own.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from backend.db_services import find_eligible_donors
from backend.orchestration.graph import DispatchState, donor_call_states
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

    # Every compatible group concurrently ("All positive" is four lookups).
    per_group = await asyncio.gather(
        *(find_eligible_donors(blood_group=group, lat=lat, lng=lng) for group in request_groups(request.blood_group))
    )
    donors = cap_donors([donor for group in per_group for donor in group], lat, lng)
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
    # Hand the matched donors to the pipeline so it calls exactly these
    # donors instead of querying the database a second time.
    state["donors"] = donor_call_states(donors, lat, lng)
    return PlannedDispatch(dispatch_id, created_at, len(donors), state)
