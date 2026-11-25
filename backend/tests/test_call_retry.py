"""Retrying a call that got no answer or a busy line."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.api import callbacks
from backend.config import settings
from backend.services import call_retry, calling
from backend.tests.conftest import donor
from backend.tests.test_twilio_signature import BASE, PATH, QUERY, TOKEN, sign  # noqa: F401  (signed fixture helpers)

PHONE = "+919000000001"
DID = "5b0a8f5e-3f0a-4c53-9a54-6f8f0d9d3b11"  # real donor IDs are UUIDs


class Recorder:
    """Stands in for the telephony provider, the donor lookup and the live feed."""

    def __init__(self):
        self.calls = []
        self.broadcasts = []

    async def start_call(self, node, dispatch_id, callback_url):
        self.calls.append((node.phone, dispatch_id))
        return f"CA-{len(self.calls)}"

    async def notify(self, dispatch_id, update):
        self.broadcasts.append((dispatch_id, update.donor_id, update.status.value))


@pytest.fixture
def rig(monkeypatch, store):
    recorder = Recorder()
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    async def no_wait():
        return None

    async def real_donor(donor_id):
        return SimpleNamespace(calls_opt_out=recorder.opted_out, calls_paused_until=recorder.paused_until)

    recorder.opted_out = False
    recorder.paused_until = None
    recorder.delays = delays
    monkeypatch.setattr(call_retry, "_sleep", fake_sleep)
    monkeypatch.setattr(call_retry, "dispatch_store", store)
    monkeypatch.setattr(call_retry, "get_donor_by_id", real_donor)
    monkeypatch.setattr(calling, "dispatch_store", store)
    monkeypatch.setattr(calling, "wait_for_slot", no_wait)
    monkeypatch.setattr(calling, "get_telephony", lambda: recorder)
    store.add("dp-1", donors=[donor(DID, PHONE, status="no_answer")])
    return recorder


async def retry(rig_, status="no-answer"):
    queued = await call_retry.schedule_retry("dp-1", DID, status, rig_.notify)
    await call_retry.wait_for_pending()
    return queued


@pytest.mark.asyncio
async def test_a_busy_or_unanswered_donor_is_called_again_after_the_delay(rig, store):
    assert await retry(rig, "busy") is True
    assert rig.delays == [settings.call_retry_delay_seconds]
    assert rig.calls == [(PHONE, "dp-1")]
    assert rig.broadcasts == [("dp-1", DID, "ringing")]
    assert store.dispatches["dp-1"]["donors"][DID]["status"] == "ringing"


@pytest.mark.asyncio
async def test_each_donor_is_retried_only_as_often_as_allowed(rig, store):
    assert await retry(rig) is True
    store.dispatches["dp-1"]["donors"][DID]["status"] = "no_answer"  # they did not pick up the retry either
    assert await retry(rig) is False
    assert len(rig.calls) == 1


@pytest.mark.asyncio
async def test_two_retries_when_configured(rig, store, monkeypatch):
    monkeypatch.setattr(settings, "call_max_retries", 2)
    for expected in (True, True, False):
        store.dispatches["dp-1"]["donors"][DID]["status"] = "no_answer"
        assert await retry(rig) is expected
    assert len(rig.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_status", ["failed", "canceled", "completed", "ringing", ""])
async def test_only_busy_and_no_answer_are_retried(rig, provider_status):
    assert await retry(rig, provider_status) is False
    assert rig.calls == []


@pytest.mark.asyncio
async def test_retries_can_be_turned_off(rig, monkeypatch):
    monkeypatch.setattr(settings, "call_max_retries", 0)
    assert await retry(rig) is False and rig.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("later", ["accepted", "declined", "en_route", "donated", "answered", "ringing"])
async def test_a_donor_who_moved_on_in_the_meantime_is_not_called(rig, store, later):
    queued = await call_retry.schedule_retry("dp-1", DID, "no-answer", rig.notify)
    store.dispatches["dp-1"]["donors"][DID]["status"] = later  # changed during the delay
    await call_retry.wait_for_pending()
    assert queued is True and rig.calls == []


@pytest.mark.asyncio
async def test_a_closed_request_is_not_retried(rig, store):
    await call_retry.schedule_retry("dp-1", DID, "no-answer", rig.notify)
    store.dispatches["dp-1"]["is_complete"] = True
    await call_retry.wait_for_pending()
    assert rig.calls == []


@pytest.mark.asyncio
async def test_a_donor_who_opted_out_meanwhile_is_not_called(rig):
    await call_retry.schedule_retry("dp-1", DID, "busy", rig.notify)
    rig.opted_out = True
    await call_retry.wait_for_pending()
    assert rig.calls == []


@pytest.mark.asyncio
async def test_a_donor_who_paused_calls_meanwhile_is_not_called(rig):
    await call_retry.schedule_retry("dp-1", DID, "busy", rig.notify)
    rig.paused_until = datetime.now(timezone.utc) + timedelta(days=7)
    await call_retry.wait_for_pending()
    assert rig.calls == []


@pytest.mark.asyncio
async def test_a_pause_that_already_ended_does_not_block_the_retry(rig):
    rig.paused_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert await retry(rig) is True
    assert rig.calls == [(PHONE, "dp-1")]


@pytest.mark.asyncio
async def test_a_retry_that_cannot_start_leaves_the_donor_as_no_answer(rig, store, monkeypatch):
    async def broken(node, dispatch_id, callback_url):
        raise RuntimeError("provider down")

    monkeypatch.setattr(rig, "start_call", broken)
    await retry(rig)
    assert store.dispatches["dp-1"]["donors"][DID]["status"] == "no_answer"


@pytest.mark.asyncio
async def test_an_error_inside_a_retry_never_escapes(rig, monkeypatch):
    async def boom(donor_id):
        raise RuntimeError("database down")

    monkeypatch.setattr(call_retry, "get_donor_by_id", boom)
    await retry(rig)  # must not raise
    assert rig.calls == []


# ── wired to the Twilio status callback ───────────────────────────


@pytest.fixture
def signed_callbacks(monkeypatch, store, broadcasts):
    monkeypatch.setattr(settings, "twilio_auth_token", TOKEN)
    monkeypatch.setattr(settings, "server_base_url", BASE)
    monkeypatch.setattr(callbacks, "dispatch_store", store)
    store.add("dp-1", donors=[donor("d1", PHONE, status="ringing")])  # matches QUERY in the signature helper
    scheduled = []

    async def fake_schedule(dispatch_id, donor_id, provider_status, notify):
        scheduled.append((dispatch_id, donor_id, provider_status))
        return True

    monkeypatch.setattr(callbacks, "schedule_retry", fake_schedule)
    return scheduled


@pytest.mark.parametrize("provider_status", ["no-answer", "busy", "failed"])
def test_the_status_callback_hands_unreached_donors_to_the_retry_rules(client, signed_callbacks, provider_status):
    """The callback reports every unreached donor; schedule_retry decides which statuses are retryable."""
    params = {"CallSid": "CA1", "CallStatus": provider_status}
    res = client.post(PATH + QUERY, data=params, headers={"X-Twilio-Signature": sign(params)})
    assert res.status_code == 200
    assert signed_callbacks == [("dp-1", "d1", provider_status)]


def test_a_call_that_is_merely_in_progress_or_finished_queues_nothing(client, signed_callbacks):
    for provider_status in ("completed", "ringing", "queued"):
        params = {"CallSid": "CA1", "CallStatus": provider_status}
        assert client.post(PATH + QUERY, data=params, headers={"X-Twilio-Signature": sign(params)}).status_code == 200
    assert signed_callbacks == []
