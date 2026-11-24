"""Space out outbound call starts so a big request does not trip provider rate limits."""

from __future__ import annotations

import asyncio
import time

from backend.config import settings

_lock = asyncio.Lock()
_next_slot = 0.0
_sleep = asyncio.sleep  # replaced in tests


async def wait_for_slot() -> None:
    """Return when this caller may start its call. Starts are spaced 1/TWILIO_CALLS_PER_SECOND apart."""
    global _next_slot
    rate = settings.twilio_calls_per_second
    if rate <= 0:
        return
    async with _lock:
        now = time.monotonic()
        start = max(now, _next_slot)
        _next_slot = start + 1.0 / rate
    if start > now:
        await _sleep(start - now)


def reset() -> None:
    global _next_slot
    _next_slot = 0.0
