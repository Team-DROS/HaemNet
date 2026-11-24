import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from backend.services.rate_limit import AuthRateLimiter


@pytest.mark.asyncio
async def test_replicas_share_and_atomically_enforce_signup_limit():
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to a disposable Redis instance")
    namespace = f"test-{uuid4().hex}"
    async with Redis.from_url(url) as first, Redis.from_url(url) as second:
        a = AuthRateLimiter(namespace, 5, 60, first)
        b = AuthRateLimiter(namespace, 5, 60, second)
        try:
            results = await asyncio.gather(
                *(limiter.record("same-donor") for limiter in [a, b] * 5),
            )
            assert results.count(0) == 5
            assert all(1 <= retry <= 60 for retry in results if retry)
            assert await b.check("same-donor") > 0
            assert await b.check("other-donor") == 0
        finally:
            await a.reset("same-donor")
        assert await b.check("same-donor") == 0
