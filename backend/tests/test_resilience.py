"""Retries, call pacing and database timeouts."""

import asyncio

import httpx
import pytest

from backend.config import settings
from backend.services import call_pacer, http_retry, sarvam_service, twilio_service


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(http_retry, "_sleep", fake_sleep)
    monkeypatch.setattr(call_pacer, "_sleep", fake_sleep)
    call_pacer.reset()
    return delays


def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://provider.test")


@pytest.mark.asyncio
async def test_retries_throttling_then_succeeds_and_honours_retry_after(no_real_sleep):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "2"}) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    async with client_with(handler) as c:
        res = await http_retry.post_with_retry(c, "/x", retry_statuses={429}, json={})
    assert res.status_code == 200 and len(calls) == 3 and no_real_sleep == [2.0, 2.0]


@pytest.mark.asyncio
async def test_retry_after_is_capped(no_real_sleep):
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "600"})

    async with client_with(handler) as c:
        res = await http_retry.post_with_retry(c, "/x", retry_statuses={429}, attempts=2)
    assert res.status_code == 429 and no_real_sleep == [5.0]


@pytest.mark.asyncio
async def test_statuses_not_listed_are_never_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    async with client_with(handler) as c:
        assert (await http_retry.post_with_retry(c, "/x", retry_statuses={429})).status_code == 500
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_connection_errors_retry_but_timeouts_only_when_idempotent():
    calls = {"connect": 0, "read": 0}

    def connect(request):
        calls["connect"] += 1
        raise httpx.ConnectError("refused")

    def read(request):
        calls["read"] += 1
        raise httpx.ReadTimeout("slow")

    async with client_with(connect) as c:
        with pytest.raises(httpx.ConnectError):
            await http_retry.post_with_retry(c, "/x")
    assert calls["connect"] == 3

    async with client_with(read) as c:
        with pytest.raises(httpx.ReadTimeout):
            await http_retry.post_with_retry(c, "/x", idempotent=False)
        assert calls["read"] == 1  # a call that may have started is not repeated
        with pytest.raises(httpx.ReadTimeout):
            await http_retry.post_with_retry(c, "/x", idempotent=True)
    assert calls["read"] == 4


@pytest.mark.asyncio
async def test_sarvam_speech_to_text_survives_a_503(monkeypatch):
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(503) if len(seen) == 1 else httpx.Response(200, json={"transcript": "yes"})

    async def fake_client():
        return client_with(handler)

    monkeypatch.setattr(sarvam_service, "_get_client", fake_client)
    result = await sarvam_service.transcribe_audio(b"wav", language="en-IN")
    assert result["transcript"] == "yes" and len(seen) == 2


@pytest.mark.asyncio
async def test_twilio_call_is_retried_on_429_but_not_after_a_timeout(monkeypatch):
    from types import SimpleNamespace
    donor = SimpleNamespace(phone="+919000000001", id="d1")
    seen = []

    def throttled_once(request):
        seen.append(1)
        return httpx.Response(429) if len(seen) == 1 else httpx.Response(201, json={"sid": "CA1"})

    async def fake_client():
        return client_with(throttled_once)

    monkeypatch.setattr(twilio_service, "_get_client", fake_client)
    assert (await twilio_service.initiate_call(donor, "dp-1", "cb"))["sid"] == "CA1" and len(seen) == 2

    timeouts = []

    def slow(request):
        timeouts.append(1)
        raise httpx.ReadTimeout("slow")

    async def slow_client():
        return client_with(slow)

    monkeypatch.setattr(twilio_service, "_get_client", slow_client)
    with pytest.raises(httpx.ReadTimeout):
        await twilio_service.initiate_call(donor, "dp-1", "cb")
    assert len(timeouts) == 1  # never risk ringing a donor twice


@pytest.mark.asyncio
async def test_call_starts_are_spaced_by_the_configured_rate(monkeypatch, no_real_sleep):
    monkeypatch.setattr(settings, "twilio_calls_per_second", 4)
    await asyncio.gather(*[call_pacer.wait_for_slot() for _ in range(5)])
    waits = sorted(no_real_sleep)
    assert len(waits) == 4 and all(abs(b - a - 0.25) < 0.05 for a, b in zip(waits, waits[1:], strict=False))


@pytest.mark.asyncio
async def test_pacing_can_be_turned_off(monkeypatch, no_real_sleep):
    monkeypatch.setattr(settings, "twilio_calls_per_second", 0)
    await asyncio.gather(*[call_pacer.wait_for_slot() for _ in range(5)])
    assert no_real_sleep == []


def test_mongo_client_fails_fast(monkeypatch):
    from backend.db_services import mongodb

    captured = {}

    class Fake:
        def __init__(self, uri, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(mongodb, "AsyncMongoClient", Fake)
    monkeypatch.setattr(mongodb, "_client", None)
    mongodb.get_client()
    monkeypatch.setattr(mongodb, "_client", None)
    assert captured["serverSelectionTimeoutMS"] == 5000 and captured["maxPoolSize"] == 100
