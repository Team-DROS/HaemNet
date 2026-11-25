"""Shared limits and live-update fan-out through Redis (fakeredis), plus fallbacks."""

import asyncio
import json

import fakeredis
import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.api.websockets import DashboardConnectionManager
from backend.config import settings
from backend.schemas.models import CallStatus, DonorStatusUpdate
from backend.services import rate_limit, redis_client


@pytest.fixture
def redis_server(monkeypatch):
    """One shared fake Redis that several 'instances' connect to."""
    server = fakeredis.FakeServer()
    clients = []

    def make():
        c = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
        clients.append(c)
        return c

    shared = make()
    monkeypatch.setattr(settings, "redis_url", "redis://fake")
    monkeypatch.setattr(redis_client, "get_redis", lambda: shared)
    return shared


# ── rate limits ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_limit_is_shared_between_two_instances(redis_server):
    instance_a = rate_limit.Limiter("t", max_events=3, window_seconds=60)
    instance_b = rate_limit.Limiter("t", max_events=3, window_seconds=60)  # another process, same Redis
    for _ in range(2):
        await instance_a.hit("1.2.3.4")
    assert await instance_b.allowed("1.2.3.4") is True
    await instance_b.hit("1.2.3.4")
    assert await instance_a.allowed("1.2.3.4") is False  # a sees b's hit
    assert 1 <= await instance_a.retry_after("1.2.3.4") <= 60


@pytest.mark.asyncio
async def test_keys_and_limiters_are_independent_and_reset_works(redis_server):
    a = rate_limit.Limiter("a", max_events=1, window_seconds=60)
    b = rate_limit.Limiter("b", max_events=1, window_seconds=60)
    await a.hit("k")
    assert await a.allowed("k") is False
    assert await a.allowed("other") is True and await b.allowed("k") is True
    await a.reset("k")
    assert await a.allowed("k") is True


@pytest.mark.asyncio
async def test_window_expires(redis_server):
    lim = rate_limit.Limiter("w", max_events=1, window_seconds=1)
    await lim.hit("k")
    assert await lim.allowed("k") is False
    await asyncio.sleep(1.2)
    assert await lim.allowed("k") is True


@pytest.mark.asyncio
async def test_falls_back_to_local_counters_when_redis_errors(monkeypatch):
    class Broken:
        def pipeline(self):
            raise RedisConnectionError("down")

        async def zcard(self, *a):
            raise RedisConnectionError("down")

        async def delete(self, *a):
            raise RedisConnectionError("down")

    monkeypatch.setattr(redis_client, "get_redis", lambda: Broken())
    lim = rate_limit.Limiter("f", max_events=2, window_seconds=60)
    await lim.hit("k")
    await lim.hit("k")
    assert await lim.allowed("k") is False  # still limited, per instance
    await lim.reset("k")
    assert await lim.allowed("k") is True


@pytest.mark.asyncio
async def test_memory_mode_without_redis(monkeypatch):
    monkeypatch.setattr(redis_client, "get_redis", lambda: None)
    lim = rate_limit.Limiter("m", max_events=1, window_seconds=60)
    await lim.hit("k")
    assert await lim.allowed("k") is False


def test_login_lockout_is_shared_across_instances(client, redis_server, monkeypatch):
    """The real sign-in endpoint locks out via Redis, not just local memory."""
    from backend.api import auth

    async def no_hospital(_):
        return None

    monkeypatch.setattr(auth, "db_get_hospital_by_id", no_hospital)
    for _ in range(10):
        client.post("/api/auth/token", data={"username": "HOSP-1", "password": "x"})
    auth._login_failures.clear()  # wipe THIS instance's memory; Redis still remembers
    assert client.post("/api/auth/token", data={"username": "HOSP-1", "password": "x"}).status_code == 429


# ── live dashboard events ─────────────────────────────────────────


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


async def owner_is_h1(_dispatch_id):
    return "H1"


def update(donor="d1"):
    return DonorStatusUpdate(donor_id=donor, name="Asha", status=CallStatus.ANSWERED)


async def settle():
    for _ in range(20):
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_event_from_one_instance_reaches_a_dashboard_on_another(redis_server, monkeypatch):
    producer = DashboardConnectionManager(owner_resolver=owner_is_h1)
    consumer = DashboardConnectionManager(owner_resolver=owner_is_h1)
    socket = FakeSocket()
    await consumer.register(socket, "H1")
    await producer.start_pubsub()
    await consumer.start_pubsub()
    try:
        await producer.broadcast("dp-1", update())
        await settle()
    finally:
        await producer.stop_pubsub()
        await consumer.stop_pubsub()
    assert [m["donor_id"] for m in socket.sent] == ["d1"]
    assert socket.sent[0]["dispatch_id"] == "dp-1"


@pytest.mark.asyncio
async def test_each_event_is_delivered_once_on_the_publishing_instance(redis_server):
    only = DashboardConnectionManager(owner_resolver=owner_is_h1)
    socket = FakeSocket()
    await only.register(socket, "H1")
    await only.start_pubsub()
    try:
        await only.broadcast_raw("dp-1", {"type": "dispatch_closed"})
        await settle()
    finally:
        await only.stop_pubsub()
    assert len(socket.sent) == 1


@pytest.mark.asyncio
async def test_other_hospitals_never_receive_the_event(redis_server):
    consumer = DashboardConnectionManager(owner_resolver=owner_is_h1)
    mine, theirs = FakeSocket(), FakeSocket()
    await consumer.register(mine, "H1")
    await consumer.register(theirs, "H2")
    await consumer.start_pubsub()
    try:
        await consumer.broadcast("dp-1", update())
        await settle()
    finally:
        await consumer.stop_pubsub()
    assert len(mine.sent) == 1 and theirs.sent == []


@pytest.mark.asyncio
async def test_delivers_locally_without_redis_or_before_the_subscriber_is_ready(monkeypatch):
    monkeypatch.setattr(redis_client, "get_redis", lambda: None)
    local = DashboardConnectionManager(owner_resolver=owner_is_h1)
    socket = FakeSocket()
    await local.register(socket, "H1")
    await local.broadcast("dp-1", update())
    assert len(socket.sent) == 1


@pytest.mark.asyncio
async def test_publish_failure_falls_back_to_local_delivery(monkeypatch):
    class Down:
        async def publish(self, *a):
            raise RedisConnectionError("down")

    monkeypatch.setattr(redis_client, "get_redis", lambda: Down())
    mgr = DashboardConnectionManager(owner_resolver=owner_is_h1)
    mgr._pubsub_ready = True
    socket = FakeSocket()
    await mgr.register(socket, "H1")
    await mgr.broadcast("dp-1", update())
    assert len(socket.sent) == 1


@pytest.mark.asyncio
async def test_malformed_message_does_not_stop_the_feed(redis_server):
    consumer = DashboardConnectionManager(owner_resolver=owner_is_h1)
    socket = FakeSocket()
    await consumer.register(socket, "H1")
    await consumer.start_pubsub()
    try:
        await redis_server.publish(consumer.PUBSUB_CHANNEL, "not json")
        await consumer.broadcast("dp-1", update())
        await settle()
    finally:
        await consumer.stop_pubsub()
    assert len(socket.sent) == 1


def test_deep_health_reports_redis(client, redis_server, monkeypatch):
    from backend.api import health

    async def db_ok():
        return {"status": "connected", "backend": "mongodb"}

    monkeypatch.setattr(health, "db_health", db_ok)
    monkeypatch.setattr(settings, "sarvam_api_key", "")
    assert client.get("/api/health/deep").json()["checks"]["redis"] is True

    class Dead:
        async def ping(self):
            raise RedisConnectionError("down")

    monkeypatch.setattr(redis_client, "get_redis", lambda: Dead())
    body = client.get("/api/health/deep").json()
    assert body["checks"]["redis"] is False and body["status"] == "degraded"
