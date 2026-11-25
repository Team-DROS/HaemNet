"""Retry a call that got no answer or a busy line, once, a few minutes later.

MongoDB keeps pending retries on the call record. Legacy Neo4j uses the process-local timer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

from backend.config import settings
from backend.db_services import get_donor_by_id, retry_jobs
from backend.dispatch_store import dispatch_store
from backend.schemas.models import CallStatus, DonorStatusUpdate
from backend.services.call_pacer import wait_for_slot
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


async def schedule_retry(
    dispatch_id: str, donor_id: str, provider_status: str, notify: Notify, *, call_sid: str = ""
) -> bool:
    """Queue one more attempt for this donor if the rules allow it. Returns whether one was queued."""
    if settings.call_max_retries <= 0 or provider_status not in RETRYABLE_PROVIDER_STATUSES:
        return False
    if settings.db_backend == "mongodb":
        return bool(call_sid) and await retry_jobs.enqueue(
            dispatch_id, donor_id, call_sid, settings.call_retry_delay_seconds, settings.call_max_retries
        )
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
        await _run_retry(dispatch_id, donor_id, notify)
    except Exception:
        logger.exception("Retry for donor %s in dispatch %s failed", donor_id, dispatch_id)


async def _run_retry(dispatch_id, donor_id, notify, job=None):
    # Pacing can queue a worker; check consent and reserve the dial only after that wait.
    await wait_for_slot()
    dispatch = await dispatch_store.get_dispatch(dispatch_id)
    if not dispatch or dispatch.get("is_complete"):
        return
    donor = (dispatch.get("donors") or {}).get(donor_id)
    if not donor or donor.get("status") != CallStatus.NO_ANSWER.value:
        return  # answered, decided or otherwise moved on
    profile = await get_donor_by_id(donor_id)
    if profile is None or not callable_now(profile):
        return  # opted out or on a break since the first call

    node = donor_node_for_call(
        donor_id, donor, dispatch.get("blood_group") or "", dispatch.get("lat") or 0.0, dispatch.get("lng") or 0.0
    )
    if job:
        if not await retry_jobs.finish(job, dial=True):
            return
    else:
        await dispatch_store.update_donor_status(dispatch_id, donor_id, CallStatus.RINGING)
    started = await place_call(node, dispatch_id, donor_id, slot_reserved=True)
    if started:
        await notify(
            dispatch_id,
            DonorStatusUpdate(donor_id=donor_id, name=donor.get("name", "Donor"), status=CallStatus.RINGING),
        )


async def wait_for_pending() -> None:
    """Let queued retries finish (used by tests and graceful shutdown)."""
    if _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


def reset_for_tests() -> None:
    _attempts.clear()
    _pending.clear()


async def process_due_retry(notify: Notify) -> bool:
    job = await retry_jobs.claim_due()
    if not job:
        return False
    if settings.call_max_retries > 0 and job["retry_count"] <= settings.call_max_retries:
        await _run_retry(job["dispatch_id"], job["donor_id"], notify, job)
    # A skipped job should not be claimed again. A completed dial has already consumed its lease.
    await retry_jobs.finish(job, dial=False)
    return True


async def run_worker(notify: Notify, stopped: asyncio.Event) -> None:
    while not stopped.is_set():
        try:
            if await process_due_retry(notify):
                continue
        except Exception:
            logger.exception("Could not process a scheduled call retry")
        with suppress(TimeoutError):
            await asyncio.wait_for(stopped.wait(), timeout=2)
