"""Authentication, authorisation and dashboard isolation."""

import json

import bcrypt
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.api import auth, routes
from backend.api.websockets import manager
from backend.schemas.models import CallStatus, DonorStatusUpdate
from backend.services import otp
from backend.tests.conftest import HOSPITAL, donor, donor_headers


def hospital_token(hospital_id=HOSPITAL):
    return auth.create_access_token({"sub": hospital_id, "role": "hospital"})


# ── token roles ───────────────────────────────────────────────────

def test_donor_token_cannot_call_hospital_endpoints(client, store):
    res = client.get("/api/dispatches/active", headers=donor_headers())
    assert res.status_code == 401


def test_hospital_token_cannot_call_donor_endpoints(client, store, auth_headers):
    res = client.get("/api/donor/requests/9000000001", headers=auth_headers)
    assert res.status_code == 401


def test_pre_role_hospital_tokens_still_work(client, store):
    legacy = auth.create_access_token({"sub": HOSPITAL})
    res = client.get("/api/dispatches/active", headers={"Authorization": f"Bearer {legacy}"})
    assert res.status_code == 200


def test_donor_endpoints_require_sign_in(client, store):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    assert client.get("/api/donor/requests/9000000001").status_code == 401
    assert client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "accept": True}).status_code == 401
    assert client.delete("/api/donor/profile/9000000001").status_code == 401


def test_donor_cannot_read_or_answer_for_someone_else(client, store):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    intruder = donor_headers("+919222222222")
    assert client.get("/api/donor/requests/9000000001", headers=intruder).status_code == 403
    res = client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "phone": "9000000001", "accept": True},
                      headers=intruder)
    assert res.status_code == 403
    assert store.dispatches["dp-1"]["donors"]["d1"]["status"] == "ringing"


def test_register_uses_verified_phone(client, monkeypatch):
    saved = {}

    async def fake_register(**kwargs):
        saved.update(kwargs)

    monkeypatch.setattr(routes, "register_donor", fake_register)
    body = {"name": "Ramesh", "phone": "9000000001", "blood_group": "O-", "language": "Tamil", "lat": 13.0, "lng": 80.2}
    assert client.post("/api/donor/register", json=body, headers=donor_headers("+919333333333")).status_code == 403
    assert client.post("/api/donor/register", json=body, headers=donor_headers()).status_code == 200
    assert saved["phone"] == "+919000000001"
    assert saved["language"] == "tamil"


# ── hospital login throttling ─────────────────────────────────────

def test_login_is_throttled_after_repeated_failures(client, monkeypatch):
    hashed = bcrypt.hashpw(b"right", bcrypt.gensalt(rounds=4)).decode()

    async def fake_get(hospital_id):
        return {"id": hospital_id, "name": "Apollo", "location": "Chennai", "phone": "1", "password_hash": hashed}

    monkeypatch.setattr(auth, "db_get_hospital_by_id", fake_get)
    for _ in range(10):
        assert client.post("/api/auth/token", data={"username": HOSPITAL, "password": "wrong"}).status_code == 401
    blocked = client.post("/api/auth/token", data={"username": HOSPITAL, "password": "right"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_successful_login_clears_failures(client, monkeypatch):
    hashed = bcrypt.hashpw(b"right", bcrypt.gensalt(rounds=4)).decode()

    async def fake_get(hospital_id):
        return {"id": hospital_id, "name": "Apollo", "location": "Chennai", "phone": "1", "password_hash": hashed}

    monkeypatch.setattr(auth, "db_get_hospital_by_id", fake_get)
    for _ in range(9):
        client.post("/api/auth/token", data={"username": HOSPITAL, "password": "wrong"})
    ok = client.post("/api/auth/token", data={"username": HOSPITAL.lower(), "password": "right"})
    assert ok.status_code == 200
    assert auth.hospital_from_token(ok.json()["access_token"]) == HOSPITAL


# ── donor email sign-in ───────────────────────────────────────────

PHONE = "+919000000001"
EMAIL = "donor@example.com"


@pytest.fixture
def dev_email(monkeypatch):
    """Development server with no email provider: codes come back in the response."""
    monkeypatch.setattr(auth.settings, "brevo_api_key", "")
    monkeypatch.setattr(auth.settings, "smtp_host", "")
    monkeypatch.setattr(auth.settings, "app_env", "development")


@pytest.fixture
def logins(monkeypatch):
    """In-memory stand-in for the phone -> email binding and donor lookup."""
    store = {}

    async def get_email(phone):
        return store.get(phone)

    async def set_email(phone, email):
        store[phone] = email

    async def no_donor(phone):
        return None

    monkeypatch.setattr(auth, "db_get_login_email", get_email)
    monkeypatch.setattr(auth, "db_set_login_email", set_email)
    monkeypatch.setattr(auth, "get_donor_by_phone", no_donor)
    return store


def _request(client, phone="90000 00001", email=EMAIL):
    return client.post("/api/donor/auth/request", json={"phone": phone, "email": email})


def _verify(client, code, phone="9000000001", email=EMAIL):
    return client.post("/api/donor/auth/verify", json={"phone": phone, "email": email, "code": code})


def test_email_code_round_trip_issues_donor_token_and_binds_email(client, dev_email, logins):
    sent = _request(client, email="  Donor@Example.com ").json()
    assert sent["phone"] == PHONE
    assert sent["email"] == "d***@example.com"
    res = _verify(client, sent["dev_code"])
    assert res.status_code == 200
    body = res.json()
    assert body["registered"] is False
    assert auth.donor_from_token(body["access_token"]) == PHONE
    assert auth.hospital_from_token(body["access_token"]) is None
    assert logins[PHONE] == EMAIL


def test_code_only_works_for_the_email_it_was_sent_to(client, dev_email, logins):
    code = _request(client).json()["dev_code"]
    assert _verify(client, code, email="someone@else.com").status_code == 401
    assert _verify(client, code).status_code == 200


def test_bound_number_refuses_a_different_email(client, dev_email, logins):
    logins[PHONE] = EMAIL
    res = _request(client, email="attacker@example.com")
    assert res.status_code == 409
    assert "dev_code" not in res.text
    assert _request(client).status_code == 200


def test_email_code_is_single_use(client, dev_email, logins):
    code = _request(client).json()["dev_code"]
    assert _verify(client, code).status_code == 200
    assert _verify(client, code).status_code == 401


def test_otp_burns_after_five_wrong_guesses():
    key = otp.login_key(PHONE, EMAIL)
    code = otp.issue_code(key, now=0)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert otp.verify_code(key, wrong, now=1) is False
    assert otp.verify_code(key, code, now=2) is False


def test_otp_expires_and_resend_is_rate_limited():
    key = otp.login_key(PHONE, EMAIL)
    code = otp.issue_code(key, now=0)
    with pytest.raises(otp.OtpError):
        otp.issue_code(key, now=10)
    assert otp.verify_code(key, code, now=otp.CODE_TTL_SECONDS + 1) is False
    for i in range(4):
        otp.issue_code(key, now=100 + i * 60)
    with pytest.raises(otp.OtpError):
        otp.issue_code(key, now=400)


def test_one_inbox_cannot_be_flooded_through_many_numbers():
    for _ in range(8):
        otp.check_email_quota(EMAIL, now=0)
    with pytest.raises(otp.OtpError):
        otp.check_email_quota(EMAIL, now=1)


def test_request_rejects_bad_numbers_and_emails(client, dev_email, logins):
    assert _request(client, phone="12345").status_code == 422
    assert _request(client, email="not-an-email").status_code == 422
    assert _request(client, email="a@b").status_code == 422


def test_otp_is_never_returned_outside_development(client, monkeypatch, logins):
    monkeypatch.setattr(auth.settings, "brevo_api_key", "")
    monkeypatch.setattr(auth.settings, "smtp_host", "")
    monkeypatch.setattr(auth.settings, "app_env", "production")
    res = _request(client)
    assert res.status_code == 503
    assert "dev_code" not in res.text


def test_configured_email_sends_code_and_hides_it(client, monkeypatch, logins):
    monkeypatch.setattr(auth.settings, "brevo_api_key", "xkeysib-test")
    monkeypatch.setattr(auth.settings, "email_from", "noreply@example.com")
    monkeypatch.setattr(auth.settings, "app_env", "production")
    outbox = []

    async def fake_send(to, code, minutes):
        outbox.append((to, code, minutes))

    monkeypatch.setattr(auth, "send_sign_in_code", fake_send)
    res = _request(client)
    assert res.status_code == 200
    assert "dev_code" not in res.json()
    assert outbox and outbox[0][0] == EMAIL and len(outbox[0][1]) == 6
    assert _verify(client, outbox[0][1]).status_code == 200


def test_provider_failure_is_a_clear_502(client, monkeypatch, logins):
    monkeypatch.setattr(auth.settings, "brevo_api_key", "xkeysib-test")
    monkeypatch.setattr(auth.settings, "email_from", "noreply@example.com")

    async def broken(to, code, minutes):
        raise auth.EmailError("Brevo HTTP 401")

    monkeypatch.setattr(auth, "send_sign_in_code", broken)
    res = _request(client)
    assert res.status_code == 502
    assert "Brevo" not in res.text


# ── dashboard WebSocket isolation ─────────────────────────────────

def test_websocket_rejects_missing_or_bad_token(client):
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "nope"}))
        assert ws.receive_json()["type"] == "auth_error"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
        assert closed.value.code == 4401


def test_websocket_rejects_donor_token(client):
    token = donor_headers()["Authorization"].split()[1]
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        assert ws.receive_json()["type"] == "auth_error"


def test_websocket_accepts_hospital_token_and_answers_pings(client):
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": hospital_token()}))
        assert ws.receive_json() == {"type": "auth_ok", "hospital_id": HOSPITAL}
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}


def test_websocket_cannot_subscribe_to_another_hospitals_dispatch(client):
    manager.bind("dp-theirs", "HOSP-2002")
    with client.websocket_connect("/ws/dashboard?dispatch_id=dp-theirs") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": hospital_token()}))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
        assert closed.value.code == 4401


class _Sock:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


async def test_events_reach_only_the_owning_hospital():
    from backend.api.websockets import DashboardConnectionManager

    async def nobody(_):
        return None

    mgr = DashboardConnectionManager(owner_resolver=nobody)
    mine, theirs, only_one = _Sock(), _Sock(), _Sock()
    mgr.bind("dp-mine", "HOSP-1001")
    mgr.bind("dp-theirs", "HOSP-2002")
    mgr.bind("dp-other-mine", "HOSP-1001")
    await mgr.register(mine, "HOSP-1001")
    await mgr.register(theirs, "HOSP-2002")
    await mgr.register(only_one, "HOSP-1001", dispatch_filter="dp-mine")

    await mgr.broadcast("dp-mine", DonorStatusUpdate(donor_id="d1", name="Ramesh", status=CallStatus.ACCEPTED))
    await mgr.broadcast_raw("dp-theirs", {"type": "dispatch_closed"})
    await mgr.broadcast_raw("dp-other-mine", {"type": "dispatch_closed"})

    assert [m["dispatch_id"] for m in mine.sent] == ["dp-mine", "dp-other-mine"]
    assert [m["dispatch_id"] for m in theirs.sent] == ["dp-theirs"]
    assert [m["dispatch_id"] for m in only_one.sent] == ["dp-mine"]
    assert all("Ramesh" not in json.dumps(m) for m in theirs.sent)


async def test_owner_is_resolved_from_the_store_after_restart():
    from backend.api.websockets import DashboardConnectionManager

    calls = []

    async def from_db(dispatch_id):
        calls.append(dispatch_id)
        return "HOSP-1001"

    mgr = DashboardConnectionManager(owner_resolver=from_db)
    sock = _Sock()
    await mgr.register(sock, "HOSP-1001")
    await mgr.broadcast_raw("dp-old", {"type": "dispatch_closed"})
    await mgr.broadcast_raw("dp-old", {"type": "dispatch_closed"})
    assert len(sock.sent) == 2
    assert calls == ["dp-old"]  # cached after the first lookup


async def test_events_with_unknown_owner_are_dropped():
    from backend.api.websockets import DashboardConnectionManager

    async def nobody(_):
        return None

    mgr = DashboardConnectionManager(owner_resolver=nobody)
    sock = _Sock()
    await mgr.register(sock, "HOSP-1001")
    await mgr.broadcast_raw("dp-x", {"type": "dispatch_closed"})
    assert sock.sent == []
