"""Retry a call that got no answer or a busy line, once, a few minutes later.

Only donors who have not decided are retried. Before calling again the donor's record is re-checked:
the request must still be open, the donor still unanswered, and the donor must not have opted out of
calls in the meantime. Retries are held in memory by the instance that got the status callback, so a
restart before the delay ends drops them (the dispatch simply carries on without that donor).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from backend.config import settings
from backend.db_services import get_donor_by_id
from backend.dispatch_store import dispatch_store
from backend.schemas.models import CallStatus, DonorStatusUpdate
from backend.services.calling import donor_node_for_call, place_call
from backend.services.donor_availability import callable_now
from backend.services.rate_limit import Limiter

logger = logging.getLogger(__name__)

# Only these mean "the donor was not reached but might pick up later".
RETRYABLE_PROVIDER_STATUSES = {"busy", "no-answer"}

Notify = Callable[[str, DonorStatusUpdate], Awaitable[None]]

_attempts = Limiter("call_retry", max_events=1, window_seconds=3600)
_pending: set[asyncio.Task] = set()
_sleep = asyncio.sleep  # replaced in tests


async def schedule_retry(dispatch_id: str, donor_id: str, provider_status: str, notify: Notify) -> bool:
    """Queue one more attempt for this donor if the rules allow it. Returns whether one was queued."""
    if settings.call_max_retries <= 0 or provider_status not in RETRYABLE_PROVIDER_STATUSES:
        return False
    _attempts.max_events = settings.call_max_retries
    if not await _attempts.try_acquire(f"{dispatch_id}:{donor_id}"):
        return False  # already retried as often as allowed
    task = asyncio.create_task(_retry(dispatch_id, donor_id, notify))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return True


async def _retry(dispatch_id: str, donor_id: str, notify: Notify) -> None:
    try:
        await _sleep(settings.call_retry_delay_seconds)
        dispatch = await dispatch_store.get_dispatch(dispatch_id)
        if not dispatch or dispatch.get("is_complete"):
            return
        donor = (dispatch.get("donors") or {}).get(donor_id)
        if not donor or donor.get("status") != CallStatus.NO_ANSWER.value:
            return  # answered, decided or otherwise moved on
        profile = await get_donor_by_id(donor_id)
        if profile is None or not callable_now(profile):
            return  # opted out or on a break since the first call

        await dispatch_store.update_donor_status(dispatch_id, donor_id, CallStatus.RINGING)
        await notify(
            dispatch_id,
            DonorStatusUpdate(donor_id=donor_id, name=donor.get("name", "Donor"), status=CallStatus.RINGING),
        )
        node = donor_node_for_call(
            donor_id, donor, dispatch.get("blood_group") or "", dispatch.get("lat") or 0.0, dispatch.get("lng") or 0.0
        )
        await place_call(node, dispatch_id, donor_id)
        logger.info("Retried donor %s in dispatch %s", donor_id, dispatch_id)
    except Exception:
        logger.exception("Retry for donor %s in dispatch %s failed", donor_id, dispatch_id)


async def wait_for_pending() -> None:
    """Let queued retries finish (used by tests and graceful shutdown)."""
    if _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


def reset_for_tests() -> None:
    _attempts.clear()
    _pending.clear()
