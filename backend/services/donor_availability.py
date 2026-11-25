"""Short breaks from automated calls ("not available this week").

Separate from opting out: a pause ends by itself, so a donor who is travelling or unwell for a
few days does not have to remember to switch calls back on. Matching skips a paused donor, and a
retry re-checks the pause before calling again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.db_services import db_set_calls_paused_until
from backend.schemas.models import DonorNode
from backend.services.errors import InvalidInputError

MAX_PAUSE_DAYS = 30


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def pause_end(days: int, now: Optional[datetime] = None) -> Optional[datetime]:
    """When a pause of `days` ends. 0 means no pause (calls resume now)."""
    if isinstance(days, bool) or not isinstance(days, int) or days < 0 or days > MAX_PAUSE_DAYS:
        raise InvalidInputError(f"Pause for 0 to {MAX_PAUSE_DAYS} days")
    if days == 0:
        return None
    return _utc(now or datetime.now(timezone.utc)) + timedelta(days=days)


def is_paused(donor: DonorNode, now: Optional[datetime] = None) -> bool:
    if donor.calls_paused_until is None:
        return False
    return _utc(donor.calls_paused_until) > _utc(now or datetime.now(timezone.utc))


def callable_now(donor: DonorNode, now: Optional[datetime] = None) -> bool:
    """False if the donor opted out of automated calls or is on a break."""
    return not donor.calls_opt_out and not is_paused(donor, now)


async def pause_calls(phone: str, days: int) -> tuple[bool, Optional[datetime]]:
    """Start (or with 0 days, end) a break. Returns (donor found, when the break ends)."""
    until = pause_end(days)
    found = await db_set_calls_paused_until(phone, until)
    return found, until
