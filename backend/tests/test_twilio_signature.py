"""Twilio webhooks are rejected unless Twilio signed them."""

from __future__ import annotations

import pytest
from twilio.request_validator import RequestValidator

from backend.api import callbacks
from backend.config import settings

TOKEN = "test-twilio-auth-token"
BASE = "https://api.haemnet.test"


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.setattr(settings, "twilio_validate_signatures", True)
    monkeypatch.setattr(settings, "twilio_auth_token", TOKEN)
    monkeypatch.setattr(settings, "server_base_url", BASE)
    return RequestValidator(TOKEN)


@pytest.fixture
def callback_store(store, monkeypatch):
    """Point the callback module at the in-memory store and mute broadcasts."""
    monkeypatch.setattr(callbacks, "dispatch_store", store)

    async def no_broadcast(*_args, **_kwargs):
        return None

    monkeypatch.setattr(callbacks.manager, "broadcast", no_broadcast)
    return store


def _gather_url(dispatch_id="dp-1", donor_id="d1"):
    return f"/api/twilio/gather?dispatch_id={dispatch_id}&donor_id={donor_id}"


def test_unsigned_gather_is_rejected(client, callback_store, signing):
    callback_store.add(donors=[{"donor_id": "d1", "name": "Asha", "status": "answered"}])
    res = client.post(_gather_url(), data={"Digits": "1"})
    assert res.status_code == 403
    assert callback_store.dispatches["dp-1"]["donors"]["d1"]["status"] == "answered"


def test_forged_signature_is_rejected(client, callback_store, signing):
    callback_store.add(donors=[{"donor_id": "d1", "name": "Asha", "status": "answered"}])
    res = client.post(_gather_url(), data={"Digits": "1"},
                      headers={"X-Twilio-Signature": "bm90LWEtc2lnbmF0dXJl"})
    assert res.status_code == 403


def test_signed_gather_is_accepted(client, callback_store, signing):
    callback_store.add(donors=[{"donor_id": "d1", "name": "Asha", "status": "answered"}])
    path = _gather_url()
    signature = signing.compute_signature(BASE + path, {"Digits": "1"})
    res = client.post(path, data={"Digits": "1"}, headers={"X-Twilio-Signature": signature})
    assert res.status_code == 200
    assert callback_store.dispatches["dp-1"]["donors"]["d1"]["status"] == "accepted"


def test_signed_twiml_get_is_accepted(client, signing):
    path = "/api/twilio/twiml?dispatch_id=dp-1&donor_id=d1"
    signature = signing.compute_signature(BASE + path, {})
    res = client.get(path, headers={"X-Twilio-Signature": signature})
    assert res.status_code == 200


def test_missing_auth_token_rejects_when_required(client, monkeypatch):
    monkeypatch.setattr(settings, "twilio_validate_signatures", True)
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    res = client.post("/api/twilio/status-callback?dispatch_id=dp-1&donor_id=d1",
                      data={"CallStatus": "in-progress"})
    assert res.status_code == 403


def test_signatures_default_to_required_in_production(monkeypatch):
    monkeypatch.setattr(settings, "twilio_validate_signatures", None)
    monkeypatch.setattr(settings, "app_env", "production")
    assert settings.twilio_signature_required
    monkeypatch.setattr(settings, "app_env", "development")
    assert not settings.twilio_signature_required
