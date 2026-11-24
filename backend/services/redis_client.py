"""Optional shared Redis connection.

With REDIS_URL empty everything stays in process memory (one instance).
With it set, rate limits, call quotas and live dashboard events are shared
across instances. Redis trouble never takes the API down: callers fall back to
local behaviour and log a warning.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

_client = None


def get_redis():
    """The shared async client, or None when Redis is not configured."""
    global _client
    if not settings.redis_url:
        return None
    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _client


async def ping() -> Optional[bool]:
    """True/False when Redis is configured, None when it is not."""
    client = get_redis()
    if client is None:
        return None
    try:
        return bool(await client.ping())
    except Exception:
        return False


async def close() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None
