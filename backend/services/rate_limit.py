"""
Small in-process sliding-window rate limiter.

Good enough for a single backend instance. Behind several instances, move
the counters to a shared store (Redis or MongoDB) so limits hold globally.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> Deque[float]:
        events = self._events[key]
        while events and now - events[0] >= self.window:
            events.popleft()
        return events

    def allowed(self, key: str, now: Optional[float] = None) -> bool:
        """True if another event for `key` fits in the window (does not record it)."""
        now = time.monotonic() if now is None else now
        return len(self._prune(key, now)) < self.max_events

    def hit(self, key: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self._prune(key, now).append(now)

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
