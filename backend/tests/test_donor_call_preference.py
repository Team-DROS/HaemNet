"""Donor consent to automated calls and opt-out."""

from backend.api import routes
from backend.tests.conftest import donor_headers

PHONE = "+919000000001"
REGISTER = {"name": "Asha", "phone": PHONE, "blood_group": "O-", "lat": 13.0, "lng": 80.2}


def test_consent_flag_is_passed_to_the_data_layer(client, monkeypatch):
    saved = {}

    async def fake_register(**kw):
        saved.update(kw)

    monkeypatch.setattr(routes, "register_donor", fake_register)
    res = client.post("/api/donor/register", json={**REGISTER, "calls_consent": True}, headers=donor_headers(PHONE))
    assert res.status_code == 200 and saved["calls_consent"] is True


def test_old_apps_without_the_flag_still_register(client, monkeypatch):
    saved = {}

    async def fake_register(**kw):
        saved.update(kw)

    monkeypatch.setattr(routes, "register_donor", fake_register)
    assert client.post("/api/donor/register", json=REGISTER, headers=donor_headers(PHONE)).status_code == 200
    assert "calls_consent" not in saved


def test_opt_out_and_back_in(client, monkeypatch):
    seen = []

    async def fake_set(phone, opt_out):
        seen.append((phone, opt_out))
        return True

    monkeypatch.setattr(routes, "db_set_calls_opt_out", fake_set)
    res = client.post("/api/donor/calls/preference", json={"opt_out": True}, headers=donor_headers(PHONE))
    assert res.json() == {"status": "ok", "calls_opt_out": True}
    client.post("/api/donor/calls/preference", json={"opt_out": False}, headers=donor_headers(PHONE))
    assert seen == [(PHONE, True), (PHONE, False)]


def test_preference_applies_only_to_the_signed_in_donor_and_needs_sign_in(client, monkeypatch):
    seen = []

    async def fake_set(phone, opt_out):
        seen.append(phone)
        return True

    monkeypatch.setattr(routes, "db_set_calls_opt_out", fake_set)
    assert client.post("/api/donor/calls/preference", json={"opt_out": True}).status_code == 401
    client.post("/api/donor/calls/preference", json={"opt_out": True, "phone": "+919222222222"},
                headers=donor_headers(PHONE))
    assert seen == [PHONE]  # a body phone number cannot redirect the change to someone else


def test_unknown_donor_and_unsupported_backend(client, monkeypatch):
    async def missing(phone, opt_out):
        return False

    monkeypatch.setattr(routes, "db_set_calls_opt_out", missing)
    assert client.post("/api/donor/calls/preference", json={"opt_out": True}, headers=donor_headers(PHONE)).status_code == 404

    async def unsupported(phone, opt_out):
        raise NotImplementedError

    monkeypatch.setattr(routes, "db_set_calls_opt_out", unsupported)
    assert client.post("/api/donor/calls/preference", json={"opt_out": True}, headers=donor_headers(PHONE)).status_code == 501
