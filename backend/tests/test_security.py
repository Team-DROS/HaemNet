"""Authentication, authorisation and dashboard isolation."""

import json

import bcrypt
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.api import auth, routes
from backend.api.websockets import manager
from backend.schemas.models import CallStatus, DonorStatusUpdate
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


# ── donor phone + password sign-in ────────────────────────────────

PHONE = "+919000000001"


@pytest.fixture
def logins(monkeypatch):
    """In-memory stand-in for the donor password store and donor lookup."""
    store = {}

    async def get_hash(phone):
        return store.get(phone)

    async def create(phone, password_hash):
        if phone in store:
            return False
        store[phone] = password_hash
        return True

    async def no_donor(phone):
        return None

    monkeypatch.setattr(auth, "db_get_donor_password_hash", get_hash)
    monkeypatch.setattr(auth, "db_create_donor_password", create)
    monkeypatch.setattr(auth, "get_donor_by_phone", no_donor)
    return store


def _register(client, phone="90000 00001", password="blood-saves-1"):
    return client.post("/api/donor/auth/register", json={"phone": phone, "password": password})


def _login(client, phone="9000000001", password="blood-saves-1"):
    return client.post("/api/donor/auth/login", json={"phone": phone, "password": password})


def test_register_then_login_issues_donor_tokens(client, logins):
    res = _register(client)
    assert res.status_code == 200
    body = res.json()
    assert body["phone"] == PHONE and body["registered"] is False
    assert auth.donor_from_token(body["access_token"]) == PHONE
    assert auth.hospital_from_token(body["access_token"]) is None

    res = _login(client)
    assert res.status_code == 200
    assert auth.donor_from_token(res.json()["access_token"]) == PHONE


def test_password_is_stored_hashed(client, logins):
    _register(client)
    assert logins[PHONE].startswith("$2") and "blood-saves-1" not in logins[PHONE]


def test_second_registration_for_a_number_is_refused(client, logins):
    assert _register(client).status_code == 200
    res = _register(client, password="another-password")
    assert res.status_code == 409
    assert _login(client, password="another-password").status_code == 401


def test_wrong_password_and_unknown_number_look_the_same(client, logins):
    _register(client)
    wrong = _login(client, password="not-the-password")
    unknown = _login(client, phone="9000000002")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_login_is_throttled_after_ten_failures(client, logins):
    _register(client)
    for _ in range(10):
        assert _login(client, password="nope-nope-nope").status_code == 401
    res = _login(client)  # even the right password waits now
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_register_validates_number_and_password(client, logins):
    assert _register(client, phone="12345").status_code == 422
    assert _register(client, password="short").status_code == 422
    assert _register(client, password="x" * 73).status_code == 422
    assert PHONE not in logins


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
