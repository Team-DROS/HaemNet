"""Sliding-window rate limiting, shared through Redis when it is configured.

`Limiter` is the one to use. Counters live in Redis (a sorted set per key) so
limits hold across several backend instances. With no REDIS_URL, or if Redis
errors, it falls back to in-process counters (per instance) and logs a warning,
so a Redis outage weakens limits instead of breaking sign-in.

`SlidingWindowLimiter` is the in-process implementation.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from backend.services import redis_client

logger = logging.getLogger(__name__)


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

    def try_acquire(self, key: str, now: Optional[float] = None) -> bool:
        """Check and record in one step (nothing can run in between)."""
        now = time.monotonic() if now is None else now
        events = self._prune(key, now)
        if len(events) >= self.max_events:
            return False
        events.append(now)
        return True

    def release_one(self, key: str) -> None:
        """Give back the most recent slot (used when a reserved action did not happen)."""
        events = self._events.get(key)
        if events:
            events.pop()

    def reset(self, key: str) -> None:
        self._events.pop(key, None)

    def clear(self) -> None:
        self._events.clear()


class Limiter:
    """Async sliding-window limiter: Redis when configured, memory otherwise."""

    def __init__(self, name: str, max_events: int, window_seconds: float) -> None:
        self.name = name
        self.max_events = max_events
        self.window = window_seconds
        self._local = SlidingWindowLimiter(max_events, window_seconds)

    def _key(self, key: str) -> str:
        return f"rl:{self.name}:{key}"

    def _sync_local(self) -> SlidingWindowLimiter:
        self._local.max_events = self.max_events
        self._local.window = self.window
        return self._local

    async def _run(self, redis_op, local_op, now: Optional[float]):
        client = redis_client.get_redis()
        if client is None or now is not None:  # an explicit `now` is for tests of the memory path
            return local_op(self._sync_local())
        try:
            return await redis_op(client)
        except Exception as exc:
            logger.warning("Redis rate limit unavailable (%s); using local counters", type(exc).__name__)
            return local_op(self._sync_local())

    async def allowed(self, key: str, now: Optional[float] = None) -> bool:
        async def op(r):
            k, t = self._key(key), time.time()
            pipe = r.pipeline()
            pipe.zremrangebyscore(k, 0, t - self.window)
            pipe.zcard(k)
            _, count = await pipe.execute()
            return count < self.max_events
        return await self._run(op, lambda local: local.allowed(key, now), now)

    async def try_acquire(self, key: str, now: Optional[float] = None) -> bool:
        """Atomically take one slot. False means the limit is reached (nothing is recorded).

        Use this instead of allowed() followed by hit(): with a database call in between,
        a burst of concurrent requests would all pass the check before any is counted.
        """
        async def op(r):
            k, t = self._key(key), time.time()
            member = f"{t}:{uuid.uuid4().hex[:8]}"
            pipe = r.pipeline(transaction=True)
            pipe.zremrangebyscore(k, 0, t - self.window)
            pipe.zadd(k, {member: t})
            pipe.zcard(k)
            pipe.expire(k, int(self.window) + 1)
            _, _, count, _ = await pipe.execute()
            if count > self.max_events:
                await r.zrem(k, member)
                return False
            return True
        return await self._run(op, lambda local: local.try_acquire(key, now), now)

    async def release_one(self, key: str) -> None:
        async def op(r):
            await r.zpopmax(self._key(key))
        await self._run(op, lambda local: local.release_one(key), None)

    async def hit(self, key: str, now: Optional[float] = None) -> None:
        async def op(r):
            k, t = self._key(key), time.time()
            pipe = r.pipeline()
            pipe.zadd(k, {f"{t}:{uuid.uuid4().hex[:8]}": t})
            pipe.expire(k, int(self.window) + 1)
            await pipe.execute()
        await self._run(op, lambda local: local.hit(key, now), now)

    async def retry_after(self, key: str, now: Optional[float] = None) -> int:
        async def op(r):
            k, t = self._key(key), time.time()
            if await r.zcard(k) < self.max_events:
                return 0
            oldest = await r.zrange(k, 0, 0, withscores=True)
            if not oldest:
                return 0
            return max(1, int(self.window - (t - oldest[0][1]) + 0.999))
        return await self._run(op, lambda local: local.retry_after(key, now), now)

    async def reset(self, key: str) -> None:
        async def op(r):
            await r.delete(self._key(key))
        await self._run(op, lambda local: local.reset(key), None)

    def clear(self) -> None:
        """Forget local counters (tests). Redis keys expire on their own."""
        self._local.clear()
