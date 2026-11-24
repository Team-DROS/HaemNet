"""Limits that keep one request or one hospital from running up call costs.

Every donor called costs telephony and speech minutes, so a request is capped
at MAX_DONORS_PER_DISPATCH (closest donors first) and a hospital at
MAX_DISPATCHES_PER_HOSPITAL_DAY requests per rolling 24 hours. Counters are
in Redis when REDIS_URL is set (shared by all instances), otherwise in process.
"""

from __future__ import annotations

from typing import List, TypeVar

from fastapi import HTTPException

from backend.config import settings
from backend.services.geo import haversine_km
from backend.services.rate_limit import Limiter

T = TypeVar("T")

_daily = Limiter("hospital_daily_dispatch", max_events=1, window_seconds=24 * 3600)


def cap_donors(donors: List[T], lat: float, lng: float) -> List[T]:
    """Keep the closest MAX_DONORS_PER_DISPATCH donors."""
    limit = settings.max_donors_per_dispatch
    if len(donors) <= limit:
        return donors
    return sorted(donors, key=lambda d: haversine_km(lat, lng, d.location.lat, d.location.lng))[:limit]


async def check_daily_quota(hospital_id: str) -> None:
    _daily.max_events = settings.max_dispatches_per_hospital_day
    if not await _daily.allowed(hospital_id):
        raise HTTPException(
            status_code=429,
            detail=f"Daily request limit reached ({settings.max_dispatches_per_hospital_day} per 24 hours). Contact HaemNet support if this is an emergency.",
            headers={"Retry-After": str(await _daily.retry_after(hospital_id))},
        )


async def record_dispatch(hospital_id: str) -> None:
    await _daily.hit(hospital_id)


def reset_quotas() -> None:
    _daily.clear()
