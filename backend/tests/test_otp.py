"""Donor phone verification by one-time code."""

import re

import pytest

from backend.api import auth
from backend.config import settings
from backend.services import otp, telephony

PHONE = "+919000000001"


class SmsOutbox:
    """A telephony provider that keeps the texts instead of sending them."""

    name = "twilio"

    def __init__(self):
        self.messages = []

    async def start_call(self, *args, **kwargs):
        return None

    async def send_sms(self, phone, message):
        self.messages.append((phone, message))

    async def close(self):
        return None

    def last_code(self):
        return re.search(r"\b(\d{6})\b", self.messages[-1][1]).group(1)


@pytest.fixture
def sms(monkeypatch):
    outbox = SmsOutbox()
    monkeypatch.setattr(telephony, "_instance", outbox)
    return outbox


def request_code(client, phone=PHONE):
    return client.post("/api/donor/auth/otp/request", json={"phone": phone})


def verify_code(client, code, phone=PHONE):
    return client.post("/api/donor/auth/otp/verify", json={"phone": phone, "code": code})


def test_a_code_is_texted_and_verifies_once(client, sms):
    assert request_code(client).json() == {"sent": True, "expires_in": 600}
    assert sms.messages[0][0] == PHONE and "HaemNet" in sms.messages[0][1]
    code = sms.last_code()
    res = verify_code(client, code)
    assert res.status_code == 200 and res.json()["otp_token"]
    assert verify_code(client, code).status_code == 400  # a code works once


def test_only_a_hash_of_the_code_is_kept_and_it_is_never_logged(client, sms, caplog):
    with caplog.at_level("DEBUG"):
        request_code(client)
    code = sms.last_code()
    assert code not in caplog.text
    assert code not in str(otp._memory) and otp._memory[PHONE][0] != code


def test_wrong_and_unknown_codes_are_refused(client, sms):
    assert verify_code(client, "123456").status_code == 400  # nothing was requested
    request_code(client)
    wrong = "000000" if sms.last_code() != "000000" else "111111"
    assert verify_code(client, wrong).status_code == 400


def test_a_new_request_replaces_the_old_code(client, sms):
    request_code(client)
    first = sms.last_code()
    request_code(client)
    second = sms.last_code()
    if first != second:
        assert verify_code(client, first).status_code == 400
    assert verify_code(client, second).status_code == 200


def test_codes_expire(client, sms, monkeypatch):
    request_code(client)
    code = sms.last_code()
    real_now = otp._now()
    monkeypatch.setattr(otp, "_now", lambda: real_now + settings.otp_ttl_seconds + 1)
    assert verify_code(client, code).status_code == 400


def test_guessing_is_capped_even_with_the_right_code_afterwards(client, sms):
    request_code(client)
    code = sms.last_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(settings.otp_max_attempts):
        assert verify_code(client, wrong).status_code == 400
    res = verify_code(client, code)
    assert res.status_code == 429 and "Retry-After" in res.headers


def test_requests_are_limited_per_number_and_per_client(client, sms):
    for _ in range(3):
        assert request_code(client).status_code == 200
    assert request_code(client).status_code == 429  # 3 texts per number per hour
    # 4 requests so far (the refused one counts too), so 6 more fit in this client's 10 per hour
    for i in range(6):
        assert request_code(client, f"+91900000010{i}").status_code == 200
    assert request_code(client, "+919000000200").status_code == 429


def test_a_sms_failure_is_a_503_and_leaves_no_code_behind(client, monkeypatch):
    class Broken(SmsOutbox):
        async def send_sms(self, phone, message):
            raise RuntimeError("provider down")

    monkeypatch.setattr(telephony, "_instance", Broken())
    assert request_code(client).status_code == 503
    assert PHONE not in otp._memory


def test_bad_numbers_are_rejected_before_any_text_is_sent(client, sms):
    assert request_code(client, "12345").status_code == 422
    assert sms.messages == []


# ── enforcing it at sign-up ───────────────────────────────────────


def register(client, token=None, phone=PHONE):
    body = {"phone": phone, "password": "longenough1"}
    if token:
        body["otp_token"] = token
    return client.post("/api/donor/auth/register", json=body)


@pytest.fixture
def otp_required(monkeypatch):
    async def create(phone, password_hash):
        return True

    monkeypatch.setattr(settings, "donor_otp_required", True)
    monkeypatch.setattr(auth, "db_create_donor_password", create)


def verified_token(client, sms, phone=PHONE):
    request_code(client, phone)
    return verify_code(client, sms.last_code(), phone).json()["otp_token"]


def test_registration_needs_a_verified_phone_when_required(client, sms, otp_required):
    assert register(client).status_code == 403
    assert register(client, token="garbage").status_code == 403
    assert register(client, token=verified_token(client, sms)).status_code == 200


def test_a_token_for_one_number_cannot_register_another(client, sms, otp_required):
    token = verified_token(client, sms, "+919000000001")
    assert register(client, token, phone="+919000000002").status_code == 403


def test_expired_verification_is_refused(client, sms, otp_required):
    token = auth.create_access_token(
        {"sub": PHONE, "role": auth.ROLE_PHONE_VERIFIED}, expires_delta=__import__("datetime").timedelta(seconds=-5)
    )
    assert register(client, token).status_code == 403


def test_registration_without_verification_still_works_while_it_is_optional(client, monkeypatch):
    async def create(phone, password_hash):
        return True

    monkeypatch.setattr(auth, "db_create_donor_password", create)
    assert settings.donor_otp_required is False
    assert register(client).status_code == 200


def test_a_verification_token_cannot_be_used_as_any_other_kind_of_token(client, sms):
    token = verified_token(client, sms)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/hospitals/me", headers=headers).status_code == 401
    assert client.get("/api/dispatches/active", headers=headers).status_code == 401
    assert client.get(f"/api/donor/profile/{PHONE}", headers=headers).status_code == 401
    assert client.get("/api/admin/hospitals", headers=headers).status_code == 401


def test_the_app_can_ask_whether_a_code_is_required(client, monkeypatch):
    assert client.get("/api/donor/auth/config").json() == {"otp_required": False}
    monkeypatch.setattr(settings, "donor_otp_required", True)
    assert client.get("/api/donor/auth/config").json() == {"otp_required": True}
