"""Turnstile bot check on hospital sign-up and the contact form."""

import pytest

from backend.api import auth
from backend.config import settings
from backend.services import turnstile

SIGNUP = {"name": "Apollo", "location": "Chennai", "phone": "+919876543210", "password": "pw12345",
          "official_email": "a@apollo.example", "contact_person": "Dr Rao", "hfr_id": "IN1"}
MESSAGE = {"name": "Asha", "email": "asha@example.com", "message": "Hello, we want to onboard."}


@pytest.fixture(autouse=True)
def hospital_db(monkeypatch):
    async def none(_): return None
    async def create(**kw): return kw
    monkeypatch.setattr(auth, "db_get_hospital_by_id", none)
    monkeypatch.setattr(auth, "db_create_hospital", create)


@pytest.fixture
def turnstile_on(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret", "secret")
    calls = []

    async def fake_verify(token, ip=None):
        calls.append(token)
        return token == "good"

    monkeypatch.setattr(turnstile, "verify_token", fake_verify)
    return calls


@pytest.fixture
def smtp(monkeypatch):
    from backend.api import contact
    sent = []

    async def fake_send(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(settings, "contact_to", "support@haemnet.example")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example")
    monkeypatch.setattr(settings, "smtp_from", "no-reply@haemnet.example")
    monkeypatch.setattr(contact, "send_email", fake_send)
    return sent


def test_check_is_off_without_a_secret(client):
    assert client.post("/api/auth/register", json=SIGNUP).status_code == 200


def test_signup_needs_a_valid_token_when_enabled(client, turnstile_on):
    assert client.post("/api/auth/register", json=SIGNUP).status_code == 400
    assert client.post("/api/auth/register", json={**SIGNUP, "turnstile_token": "bad"}).status_code == 400
    assert client.post("/api/auth/register", json={**SIGNUP, "turnstile_token": "good"}).status_code == 200


@pytest.mark.asyncio
async def test_verify_fails_closed_without_token_or_on_network_error(monkeypatch):
    monkeypatch.setattr(settings, "turnstile_secret", "secret")
    assert await turnstile.verify_token(None) is False

    class Boom:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): raise RuntimeError("down")
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", Boom)
    assert await turnstile.verify_token("anything") is False


def test_contact_sends_an_email(client, smtp):
    res = client.post("/api/contact", json=MESSAGE)
    assert res.json() == {"sent": True}
    to, subject, body = smtp[0]
    assert to == "support@haemnet.example" and "asha@example.com" in body


def test_contact_strips_line_breaks_from_subject(client, smtp):
    client.post("/api/contact", json={**MESSAGE, "name": "Eve\nBcc: x@evil.example"})
    assert "\n" not in smtp[0][1]


def test_contact_validation_and_unavailable(client, smtp, monkeypatch):
    assert client.post("/api/contact", json={**MESSAGE, "email": "nope"}).status_code == 422
    assert client.post("/api/contact", json={**MESSAGE, "message": "hi"}).status_code == 422
    monkeypatch.setattr(settings, "contact_to", "")
    assert client.post("/api/contact", json=MESSAGE).status_code == 503


def test_contact_needs_token_when_enabled_and_is_rate_limited(client, smtp, turnstile_on):
    assert client.post("/api/contact", json=MESSAGE).status_code == 400  # a failed bot check still uses a slot
    ok = {**MESSAGE, "turnstile_token": "good"}
    for _ in range(4):
        assert client.post("/api/contact", json=ok).status_code == 200
    assert client.post("/api/contact", json=ok).status_code == 429
