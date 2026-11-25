"""Twilio webhooks must be signed; forged callbacks cannot change a donor's answer."""

import pytest
from twilio.request_validator import RequestValidator

from backend.api import callbacks
from backend.config import settings
from backend.tests.conftest import donor

TOKEN = "twilio-test-token"
BASE = "https://api.haemnet.example"
PATH = "/api/twilio/status-callback"
QUERY = "?dispatch_id=dp-1&donor_id=d1"


@pytest.fixture(autouse=True)
def _callback_deps(monkeypatch, store, broadcasts):
    """The callback routes hold their own reference to the dispatch store."""
    monkeypatch.setattr(callbacks, "dispatch_store", store)
    monkeypatch.setattr(callbacks.manager, "broadcast", lambda *a, **k: _noop())


async def _noop():
    return None


@pytest.fixture
def signed(monkeypatch, store):
    monkeypatch.setattr(settings, "twilio_auth_token", TOKEN)
    monkeypatch.setattr(settings, "server_base_url", BASE)
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    return store


def sign(params, path=PATH, query=QUERY):
    return RequestValidator(TOKEN).compute_signature(BASE + path + query, params)


def test_valid_signature_is_accepted_and_applied(client, signed):
    params = {"CallSid": "CA1", "CallStatus": "no-answer"}
    res = client.post(PATH + QUERY, data=params, headers={"X-Twilio-Signature": sign(params)})
    assert res.status_code == 200
    assert signed.dispatches["dp-1"]["donors"]["d1"]["status"] == "no_answer"


def test_missing_and_wrong_signatures_are_rejected(client, signed):
    params = {"CallSid": "CA1", "CallStatus": "completed"}
    assert client.post(PATH + QUERY, data=params).status_code == 403
    assert client.post(PATH + QUERY, data=params, headers={"X-Twilio-Signature": "bogus"}).status_code == 403


def test_tampered_parameters_are_rejected(client, signed):
    good = {"CallSid": "CA1", "CallStatus": "completed"}
    res = client.post(
        PATH + QUERY, data={**good, "CallStatus": "no-answer"}, headers={"X-Twilio-Signature": sign(good)}
    )
    assert res.status_code == 403


def test_signature_for_another_donor_is_rejected(client, signed):
    params = {"CallSid": "CA1", "CallStatus": "completed"}
    sig = sign(params, query="?dispatch_id=dp-1&donor_id=other")
    assert client.post(PATH + QUERY, data=params, headers={"X-Twilio-Signature": sig}).status_code == 403


def test_gather_and_twiml_are_also_protected(client, signed):
    assert client.post("/api/twilio/gather?dispatch_id=dp-1&donor_id=d1", data={"Digits": "1"}).status_code == 403
    assert client.get("/api/twilio/twiml?dispatch_id=dp-1&donor_id=d1").status_code == 403
    sig = sign({}, "/api/twilio/twiml", "?dispatch_id=dp-1&donor_id=d1")
    res = client.get("/api/twilio/twiml?dispatch_id=dp-1&donor_id=d1", headers={"X-Twilio-Signature": sig})
    assert res.status_code == 200 and "<Stream" in res.text


def test_forged_accept_cannot_change_a_donor(client, signed):
    client.post("/api/twilio/gather?dispatch_id=dp-1&donor_id=d1", data={"Digits": "1"})
    assert signed.dispatches["dp-1"]["donors"]["d1"]["status"] == "ringing"


def test_no_token_allowed_in_development_but_not_in_production(client, store, monkeypatch):
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    assert client.post(PATH + QUERY, data={"CallSid": "CA1", "CallStatus": "completed"}).status_code == 200
    monkeypatch.setattr(settings, "app_env", "production")
    assert client.post(PATH + QUERY, data={"CallSid": "CA1", "CallStatus": "completed"}).status_code == 403


def test_failed_and_canceled_calls_are_not_recorded_as_declines(client, signed):
    for index, twilio_status in enumerate(["failed", "canceled"]):
        signed.dispatches["dp-1"]["donors"]["d1"]["status"] = "ringing"
        params = {"CallSid": f"CA{index}", "CallStatus": twilio_status}
        res = client.post(PATH + QUERY, data=params, headers={"X-Twilio-Signature": sign(params)})
        assert res.status_code == 200
        assert signed.dispatches["dp-1"]["donors"]["d1"]["status"] == "no_answer"
