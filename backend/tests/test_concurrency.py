"""Behaviour under concurrent load: limits must hold, hospitals must stay isolated."""

import asyncio
from types import SimpleNamespace

import fakeredis
import fakeredis.aioredis
import httpx
import pytest

from backend.api import auth, dispatches
from backend.api.auth import create_access_token
from backend.config import settings
from backend.main import app
from backend.services import dispatching as planning
from backend.services import rate_limit, redis_client


def asgi_client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ── the race that allowed() + hit() could not close ───────────────


@pytest.mark.asyncio
async def test_try_acquire_never_lets_more_than_the_limit_through_in_memory(monkeypatch):
    monkeypatch.setattr(redis_client, "get_redis", lambda: None)
    limiter = rate_limit.Limiter("race", max_events=10, window_seconds=60)
    results = await asyncio.gather(*[limiter.try_acquire("k") for _ in range(200)])
    assert sum(results) == 10


@pytest.mark.asyncio
async def test_try_acquire_never_lets_more_than_the_limit_through_with_redis(monkeypatch):
    server = fakeredis.FakeServer()
    clients = [fakeredis.aioredis.FakeRedis(server=server, decode_responses=True) for _ in range(4)]  # 4 "instances"
    limiters = [rate_limit.Limiter("race", max_events=10, window_seconds=60) for _ in clients]

    results = []
    for i in range(120):
        idx = i % 4
        monkeypatch.setattr(redis_client, "get_redis", lambda c=clients[idx]: c)
        results.append(limiters[idx].try_acquire("k"))

    # run them all concurrently, each bound to its own instance's client
    async def run(i):
        return await results[i]

    # coroutines were created with the right client captured at call time; now interleave them
    outcome = await asyncio.gather(*[run(i) for i in range(120)])
    assert sum(outcome) == 10


@pytest.mark.asyncio
async def test_a_burst_of_wrong_passwords_is_cut_off_at_the_limit(monkeypatch):
    seen = {"checked": 0}

    async def slow_lookup(_):
        seen["checked"] += 1
        await asyncio.sleep(0.01)  # a real database call: lets every request pass the old check
        return

    monkeypatch.setattr(auth, "db_get_hospital_by_id", slow_lookup)
    auth._login_failures.clear()
    async with asgi_client() as client:
        responses = await asyncio.gather(
            *[client.post("/api/auth/token", data={"username": "HOSP-1", "password": "wrong"}) for _ in range(60)]
        )
    codes = [r.status_code for r in responses]
    assert codes.count(401) == 10 and codes.count(429) == 50
    assert seen["checked"] == 10  # the throttled requests never reached the password check


# ── 50 concurrent dispatches ──────────────────────────────────────


@pytest.mark.asyncio
async def test_fifty_hospitals_dispatch_at_once_without_mixing_anything_up(monkeypatch):
    ran = []

    async def fake_find(**kwargs):
        await asyncio.sleep(0.01)
        return [SimpleNamespace(location=SimpleNamespace(lat=13.06, lng=80.25)) for _ in range(3)]

    async def fake_run(dispatch_id, state):
        ran.append((state["hospital_id"], dispatch_id))

    monkeypatch.setattr(planning, "find_eligible_donors", fake_find)
    monkeypatch.setattr(dispatches, "run_dispatch_graph", fake_run)

    def body(h):
        return {
            "hospital_id": h,
            "blood_group": "O-",
            "urgency": "critical",
            "coordinates": {"lat": 13.06, "lng": 80.25},
            "units": 1,
        }

    hospitals = [f"HOSP-{2000 + i}" for i in range(50)]
    async with asgi_client() as client:
        responses = await asyncio.gather(
            *[
                client.post(
                    "/api/dispatch",
                    json=body(h),
                    headers={"Authorization": "Bearer " + create_access_token({"sub": h, "role": "hospital"})},
                )
                for h in hospitals
            ]
        )
    assert all(r.status_code == 200 and r.json()["donors_matched"] == 3 for r in responses)
    assert len({r.json()["dispatch_id"] for r in responses}) == 50
    assert sorted(h for h, _ in ran) == sorted(hospitals)  # each dispatch recorded against its own hospital


@pytest.mark.asyncio
async def test_one_hospital_hammering_dispatch_is_stopped_by_the_daily_quota(monkeypatch):
    monkeypatch.setattr(settings, "max_dispatches_per_hospital_day", 5)

    async def fake_find(**kwargs):
        await asyncio.sleep(0.01)
        return [SimpleNamespace(location=SimpleNamespace(lat=13.06, lng=80.25))]

    async def fake_run(dispatch_id, state):
        pass

    monkeypatch.setattr(planning, "find_eligible_donors", fake_find)
    monkeypatch.setattr(dispatches, "run_dispatch_graph", fake_run)
    body = {
        "hospital_id": "HOSP-1001",
        "blood_group": "O-",
        "urgency": "critical",
        "coordinates": {"lat": 13.06, "lng": 80.25},
        "units": 1,
    }
    headers = {"Authorization": "Bearer " + create_access_token({"sub": "HOSP-1001", "role": "hospital"})}
    async with asgi_client() as client:
        responses = await asyncio.gather(*[client.post("/api/dispatch", json=body, headers=headers) for _ in range(30)])
    codes = [r.status_code for r in responses]
    assert codes.count(200) == 5 and codes.count(429) == 25  # exactly the cap, even for a simultaneous burst
    assert (await _one_more(headers, body)).status_code == 429


@pytest.mark.asyncio
async def test_failed_or_empty_requests_give_their_daily_slot_back(monkeypatch):
    monkeypatch.setattr(settings, "max_dispatches_per_hospital_day", 2)
    outcomes = iter(["none", "boom", "ok", "ok", "ok"])

    async def fake_find(**kwargs):
        kind = next(outcomes)
        if kind == "boom":
            raise RuntimeError("database down")
        return [] if kind == "none" else [SimpleNamespace(location=SimpleNamespace(lat=13.06, lng=80.25))]

    async def fake_run(dispatch_id, state):
        pass

    monkeypatch.setattr(planning, "find_eligible_donors", fake_find)
    monkeypatch.setattr(dispatches, "run_dispatch_graph", fake_run)
    body = {
        "hospital_id": "HOSP-1001",
        "blood_group": "O-",
        "urgency": "critical",
        "coordinates": {"lat": 13.06, "lng": 80.25},
        "units": 1,
    }
    headers = {"Authorization": "Bearer " + create_access_token({"sub": "HOSP-1001", "role": "hospital"})}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        codes = [(await c.post("/api/dispatch", json=body, headers=headers)).status_code for _ in range(5)]
    # empty result and a crash cost nothing; then two real dispatches fit, the third is refused
    assert codes == [200, 500, 200, 200, 429]


async def _one_more(headers, body):
    async with asgi_client() as client:
        return await client.post("/api/dispatch", json=body, headers=headers)
