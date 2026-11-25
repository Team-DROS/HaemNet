import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from backend.services import redis_client
from backend.services.rate_limit import Limiter


@pytest.mark.asyncio
async def test_replicas_share_live_redis_quota(monkeypatch):
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to a disposable Redis instance")
    name = uuid4().hex
    async with Redis.from_url(url) as first, Redis.from_url(url) as second:
        a, b = Limiter(name, 5, 60), Limiter(name, 5, 60)
        # Each task uses its replica's own connection pool.
        from contextvars import ContextVar

        connection = ContextVar("redis_connection")
        monkeypatch.setattr(redis_client, "get_redis", connection.get)

        async def reserve(limiter, client):
            connection.set(client)
            return await limiter.try_acquire("hospital")

        try:
            grants = await asyncio.gather(*(reserve(*pair) for pair in [(a, first), (b, second)] * 25))
            assert sum(grants) == 5
            connection.set(second)
            assert 0 < await b.retry_after("hospital") <= 60
        finally:
            await first.delete(a._key("hospital"))
