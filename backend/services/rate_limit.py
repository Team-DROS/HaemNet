"""
Sliding-window authentication counters.
"""

from __future__ import annotations

import time
from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException
from redis.exceptions import RedisError
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


class AuthRateLimiter:
    """Share authentication counters through Redis when configured."""

    _script = """
    local now = redis.call('TIME')
    local ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
    local window = tonumber(ARGV[1])
    local limit = tonumber(ARGV[2])
    local operation = ARGV[3]
    redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ms - window)
    if redis.call('ZCARD', KEYS[1]) >= limit then
        local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
        return math.ceil((tonumber(oldest[2]) + window - ms) / 1000)
    end
    if operation ~= 'check' then
        redis.call('ZADD', KEYS[1], ms, ARGV[4])
        redis.call('PEXPIRE', KEYS[1], window)
    end
    return 0
    """

    def __init__(self, namespace, max_events, window_seconds, redis_client=None):
        self.namespace = namespace
        self.local = SlidingWindowLimiter(max_events, window_seconds)
        self.redis = redis_client

    def _key(self, identity):
        return f"haemnet:auth:v1:{self.namespace}:{sha256(identity.encode()).hexdigest()}"

    async def _run(self, operation, identity):
        if self.redis is None:
            retry = self.local.retry_after(identity)
            if not retry and operation != "check":
                self.local.hit(identity)
            return retry
        try:
            return await self.redis.eval(
                self._script, 1, self._key(identity), int(self.local.window * 1000),
                self.local.max_events, operation, uuid4().hex,
            )
        except RedisError:
            raise HTTPException(503, "Authentication temporarily unavailable") from None

    async def check(self, identity):
        return await self._run("check", identity)

    async def record(self, identity):
        return await self._run("record", identity)

    async def reset(self, identity):
        if self.redis is None:
            self.local.reset(identity)
            return
        try:
            await self.redis.delete(self._key(identity))
        except RedisError:
            raise HTTPException(503, "Authentication temporarily unavailable") from None

    def clear(self):
        self.local.clear()
