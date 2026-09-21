"""HTTP and WebSocket behaviour with the database replaced by FakeStore."""

import bcrypt
import pytest

from backend.api import auth, routes
from backend.api.websockets import DashboardConnectionManager
from backend.schemas.models import CallStatus, DonorStatusUpdate
from backend.tests.conftest import HOSPITAL, donor, donor_headers


# ── auth ──────────────────────────────────────────────────────────

def test_login_never_returns_password_hash(client, monkeypatch):
    hashed = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()

    async def fake_get(hospital_id):
        return {"id": hospital_id, "name": "Apollo", "location": "Chennai",
                "phone": "+914400000000", "password_hash": hashed}

    monkeypatch.setattr(auth, "db_get_hospital_by_id", fake_get)
    res = client.post("/api/auth/token", data={"username": HOSPITAL, "password": "pw"})
    assert res.status_code == 200
    user = res.json()["user"]
    assert "password_hash" not in user
    assert user["name"] == "Apollo"


def test_register_issues_an_id_when_none_given(client, monkeypatch):
    created = {}

    async def fake_get(hospital_id):
        return None

    async def fake_create(**kwargs):
        created.update(kwargs)
        return kwargs

    monkeypatch.setattr(auth, "db_get_hospital_by_id", fake_get)
    monkeypatch.setattr(auth, "db_create_hospital", fake_create)
    res = client.post("/api/auth/register", json={
        "name": "Apollo", "location": "Chennai", "phone": "+91", "password": "pw",
    })
    assert res.status_code == 200
    assert res.json()["id"].startswith("HOSP-")
    assert created["id"] == res.json()["id"]
    assert created["password_hash"] != "pw"


# ── dispatch ──────────────────────────────────────────────────────

def test_dispatch_is_recorded_against_the_authenticated_hospital(client, auth_headers, monkeypatch):
    captured = {}

    async def fake_find(**kwargs):
        return [object()]

    async def fake_run(dispatch_id, state):
        captured.update(state)

    monkeypatch.setattr(routes, "find_eligible_donors", fake_find)
    monkeypatch.setattr(routes, "_run_dispatch_graph", fake_run)

    res = client.post("/api/dispatch", headers=auth_headers, json={
        "hospital_id": "HOSP-SOMEONE-ELSE", "blood_group": "O-", "urgency": "critical",
        "coordinates": {"lat": 13.06, "lng": 80.25}, "units": 3,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["donors_matched"] == 1 and body["created_at"]
    assert captured["hospital_id"] == HOSPITAL
    assert captured["units"] == 3


def test_dispatch_requires_auth(client):
    res = client.post("/api/dispatch", json={})
    assert res.status_code == 401


def test_active_dispatches_hide_donor_phone_numbers(client, auth_headers, store):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    store.add("dp-other", hospital_id="HOSP-9999", donors=[donor("d2", "+919000000002")])
    res = client.get("/api/dispatches/active", headers=auth_headers)
    assert res.status_code == 200
    dispatches = res.json()["dispatches"]
    assert [d["dispatch_id"] for d in dispatches] == ["dp-1"]
    assert "phone" not in dispatches[0]["donors"][0]
    assert dispatches[0]["donors"][0]["distance_km"] == 2.4


def test_close_rejects_other_hospitals_dispatch(client, auth_headers, store, broadcasts):
    store.add("dp-other", hospital_id="HOSP-9999")
    assert client.post("/api/dispatches/dp-other/close", headers=auth_headers).status_code == 403
    assert client.post("/api/dispatches/missing/close", headers=auth_headers).status_code == 404


def test_close_marks_complete_and_notifies(client, auth_headers, store, broadcasts):
    store.add("dp-1")
    assert client.post("/api/dispatches/dp-1/close", headers=auth_headers).status_code == 200
    assert store.completed == ["dp-1"]
    assert broadcasts[-1][1]["type"] == "dispatch_closed"


# ── donation fulfils the request ──────────────────────────────────

@pytest.fixture
def fake_donation_date(monkeypatch):
    async def ok(**kwargs):
        return True
    monkeypatch.setattr(routes, "update_donation_date", ok)


def test_donation_closes_dispatch_once_units_are_met(client, auth_headers, store, broadcasts, fake_donation_date):
    store.add("dp-1", units=2, donors=[
        donor("d1", "+919000000001", status="en_route"),
        donor("d2", "+919000000002", status="en_route"),
    ])

    first = client.post("/api/donate", headers=auth_headers,
                        json={"donor_id": "d1", "hospital_id": HOSPITAL, "dispatch_id": "dp-1"})
    assert first.json()["dispatch_fulfilled"] is False
    assert store.dispatches["dp-1"]["donors"]["d1"]["status"] == "donated"

    second = client.post("/api/donate", headers=auth_headers,
                         json={"donor_id": "d2", "hospital_id": HOSPITAL, "dispatch_id": "dp-1"})
    assert second.json()["dispatch_fulfilled"] is True
    assert store.completed == ["dp-1"]
    assert store.dispatches["dp-1"]["fulfilled"] is True
    assert broadcasts[-1][1]["type"] == "dispatch_fulfilled"


def test_donation_without_dispatch_still_works(client, auth_headers, store, fake_donation_date):
    res = client.post("/api/donate", headers=auth_headers, json={"donor_id": "d1", "hospital_id": HOSPITAL})
    assert res.status_code == 200 and res.json()["dispatch_fulfilled"] is False


# ── donor app responses ───────────────────────────────────────────

def test_donor_sees_open_requests_with_eta(client, store):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    res = client.get("/api/donor/requests/9000000001", headers=donor_headers())
    reqs = res.json()["requests"]
    assert len(reqs) == 1
    assert reqs[0]["hospital_name"] == "Apollo Hospital"
    assert reqs[0]["eta_minutes"] > 0


def test_donor_accept_moves_to_en_route_and_notifies_dashboard(client, store, broadcasts):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    res = client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "accept": True}, headers=donor_headers())
    assert res.status_code == 200
    assert res.json()["donor_status"] == "en_route"
    statuses = [u.status for _, u in broadcasts if isinstance(u, DonorStatusUpdate)]
    assert statuses == [CallStatus.ACCEPTED, CallStatus.EN_ROUTE]
    assert store.dispatches["dp-1"]["donors"]["d1"]["eta_minutes"] > 0


def test_donor_response_is_idempotent_but_cannot_flip(client, store, broadcasts):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    h = donor_headers()
    client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "accept": True}, headers=h)
    again = client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "accept": True}, headers=h)
    assert again.status_code == 200 and again.json()["unchanged"] is True
    flip = client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "accept": False}, headers=h)
    assert flip.status_code == 409


def test_donor_not_in_dispatch_is_rejected(client, store):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    res = client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "accept": True},
                      headers=donor_headers("+919111111111"))
    assert res.status_code == 404


def test_closed_request_cannot_be_answered(client, store):
    store.add("dp-1", donors=[donor("d1", "+919000000001")], is_complete=True)
    res = client.post("/api/donor/respond", json={"dispatch_id": "dp-1", "accept": True}, headers=donor_headers())
    assert res.status_code == 404


# ── websocket stamping ────────────────────────────────────────────

class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(text)


async def test_broadcast_stamps_dispatch_id_and_time():
    import json
    mgr = DashboardConnectionManager()
    ws = _FakeWS()
    mgr.bind("dp-42", "HOSP-1001")
    await mgr.register(ws, "HOSP-1001")
    await mgr.broadcast("dp-42", DonorStatusUpdate(donor_id="d1", name="R", status=CallStatus.ANSWERED))
    msg = json.loads(ws.sent[-1])
    assert msg["dispatch_id"] == "dp-42"
    assert msg["status"] == "answered"
    assert msg["timestamp"]


# ── network availability ──────────────────────────────────────────

def test_availability_returns_every_group_with_zero_fill(client, auth_headers, monkeypatch):
    routes._hospital_coords_cache.clear()

    async def fake_hospital(hospital_id):
        return {"id": hospital_id, "location": "Greams Road, Chennai"}

    async def fake_geocode(address):
        return (13.06, 80.25)

    async def fake_counts(lat, lng, radius_km=10.0):
        assert (lat, lng) == (13.06, 80.25)
        return {"O-": 12, "B+": 38}

    import backend.services.geocoding as geocoding
    monkeypatch.setattr(routes, "db_get_hospital_by_id", fake_hospital)
    monkeypatch.setattr(geocoding, "geocode_address", fake_geocode)
    monkeypatch.setattr(routes, "db_eligible_counts_by_group", fake_counts)

    body = client.get("/api/network/availability", headers=auth_headers).json()
    assert body["groups"]["O-"] == 12 and body["groups"]["AB-"] == 0
    assert body["total"] == 50 and len(body["groups"]) == 8


def test_availability_explains_ungeocodable_location(client, auth_headers, monkeypatch):
    routes._hospital_coords_cache.clear()

    async def fake_hospital(hospital_id):
        return {"id": hospital_id, "location": "???"}

    async def fake_geocode(address):
        return None

    import backend.services.geocoding as geocoding
    monkeypatch.setattr(routes, "db_get_hospital_by_id", fake_hospital)
    monkeypatch.setattr(geocoding, "geocode_address", fake_geocode)
    res = client.get("/api/network/availability", headers=auth_headers)
    assert res.status_code == 422


# ── server-side history ───────────────────────────────────────────

def test_history_reports_outcomes_without_donor_details(client, store, auth_headers):
    base = {"hospital_id": HOSPITAL, "blood_group": "O-", "units": 2, "urgency": "critical",
            "created_at": "2026-09-18T12:00:00+00:00", "first_accept_at": "2026-09-18T12:00:40+00:00",
            "closed_at": "2026-09-18T12:30:00+00:00", "matched": 22, "answered": 11, "accepted": 7}
    store.history_rows = [
        {**base, "dispatch_id": "a", "is_complete": True, "fulfilled": True, "donated": 2},
        {**base, "dispatch_id": "b", "is_complete": True, "fulfilled": False, "donated": 1},
        {**base, "dispatch_id": "c", "is_complete": True, "fulfilled": False, "donated": 0},
        {**base, "dispatch_id": "d", "is_complete": False, "fulfilled": False, "donated": 0},
        {**base, "dispatch_id": "other", "hospital_id": "HOSP-2002", "is_complete": True, "fulfilled": True, "donated": 2},
    ]
    res = client.get("/api/dispatches/history?days=90", headers=auth_headers)
    assert res.status_code == 200
    rows = {r["dispatch_id"]: r for r in res.json()["dispatches"]}
    assert set(rows) == {"a", "b", "c", "d"}
    assert [rows[k]["status"] for k in "abcd"] == ["fulfilled", "partial", "closed", "active"]
    assert rows["a"]["contacted"] == 22 and rows["a"]["first_accept_at"].endswith("+00:00")
    assert "donors" not in rows["a"] and "phone" not in res.text
    assert store.history_since < "2026-09-21"


def test_history_range_is_bounded(client, store, auth_headers):
    assert client.get("/api/dispatches/history?days=0", headers=auth_headers).status_code == 422
    assert client.get("/api/dispatches/history?days=366", headers=auth_headers).status_code == 422


def test_manual_close_is_not_marked_fulfilled(client, store, auth_headers, broadcasts):
    store.add("dp-1", donors=[donor("d1", "+919000000001")])
    assert client.post("/api/dispatches/dp-1/close", headers=auth_headers).status_code == 200
    assert store.dispatches["dp-1"]["fulfilled"] is False
