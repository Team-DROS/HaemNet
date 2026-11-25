"""
Small in-process sliding-window rate limiter.

Good enough for a single backend instance. Behind several instances, move
the counters to a shared store (Redis or MongoDB) so limits hold globally.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional


# Scan for expired keys every this many recorded events, so keys that are
# tried once and never again (a script cycling through numbers) are freed.
SWEEP_EVERY = 1024


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._hits = 0

    def _prune(self, key: str, now: float) -> Deque[float]:
        events = self._events.get(key)
        if events is None:
            return deque()
        while events and now - events[0] >= self.window:
            events.popleft()
        if not events:
            # Forget idle keys; otherwise every phone number or ID ever tried
            # stays in memory for the life of the process.
            del self._events[key]
        return events

    def allowed(self, key: str, now: Optional[float] = None) -> bool:
        """True if another event for `key` fits in the window (does not record it)."""
        now = time.monotonic() if now is None else now
        return len(self._prune(key, now)) < self.max_events

    def hit(self, key: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self._prune(key, now)
        self._events[key].append(now)
        self._hits += 1
        if self._hits % SWEEP_EVERY == 0:
            self._sweep(now)

    def _sweep(self, now: float) -> None:
        """Drop every key whose newest event has left the window."""
        expired = [key for key, events in self._events.items() if now - events[-1] >= self.window]
        for key in expired:
            del self._events[key]

    def __len__(self) -> int:
        """Number of keys currently tracked."""
        return len(self._events)

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        """Seconds until the oldest event leaves the window."""
        now = time.monotonic() if now is None else now
        events = self._prune(key, now)
        if len(events) < self.max_events:
            return 0
        return max(1, int(self.window - (now - events[0]) + 0.999))

    def reset(self, key: str) -> None:
        self._events.pop(key, None)

    def clear(self) -> None:
        self._events.clear()
