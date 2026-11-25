"""Limits that keep one request or one hospital from running up call costs.

Every donor called costs telephony and speech minutes, so a request is capped
at MAX_DONORS_PER_DISPATCH (closest donors first) and a hospital at
MAX_DISPATCHES_PER_HOSPITAL_DAY requests per rolling 24 hours. Counters are
in Redis when REDIS_URL is set (shared by all instances), otherwise in process.
"""

from __future__ import annotations

from typing import List, Protocol, TypeVar

from backend.config import settings
from backend.schemas.models import Coordinates
from backend.services.geo import haversine_km
from backend.services.rate_limit import Limiter, enforce


class _Located(Protocol):
    """Anything with a map position, such as a donor."""

    @property
    def location(self) -> Coordinates: ...


T = TypeVar("T", bound=_Located)

_daily = Limiter("hospital_daily_dispatch", max_events=1, window_seconds=24 * 3600)


def cap_donors(donors: List[T], lat: float, lng: float) -> List[T]:
    """Keep the closest MAX_DONORS_PER_DISPATCH donors."""
    limit = settings.max_donors_per_dispatch
    if len(donors) <= limit:
        return donors
    return sorted(donors, key=lambda d: haversine_km(lat, lng, d.location.lat, d.location.lng))[:limit]


async def reserve_daily_quota(hospital_id: str) -> None:
    """Take one of the hospital's daily requests, or raise 429.

    The slot is taken before donors are searched so a burst of simultaneous requests cannot
    overshoot the cap. Call `release_daily_quota` if the request ends up not placing any calls.
    """
    _daily.max_events = settings.max_dispatches_per_hospital_day
    await enforce(
        _daily,
        hospital_id,
        f"Daily request limit reached ({settings.max_dispatches_per_hospital_day} per 24 hours). "
        "Contact HaemNet support if this is an emergency.",
    )


async def release_daily_quota(hospital_id: str) -> None:
    await _daily.release_one(hospital_id)


def reset_quotas() -> None:
    _daily.clear()
