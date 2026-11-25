"""Push alerts for donors with the app: token rules, alert wording, expiry and the API."""

from __future__ import annotations

import asyncio

import pytest

from backend.api import donors as donors_api
from backend.config import settings
from backend.services import donor_push
from backend.services.errors import InvalidInputError
from backend.tests.conftest import donor_headers

TOKEN = "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"
PHONE = "+919000000001"


# ── token rules ────────────────────────────────────────────────────


@pytest.mark.parametrize("token", [TOKEN, "ExpoPushToken[abcdEFGH1234_-]"])
def test_expo_tokens_are_accepted(token):
    assert donor_push.is_expo_push_token(token)
    assert donor_push.clean_push_token(f"  {token} ") == token


@pytest.mark.parametrize("token", ["fcm:abc", "ExponentPushToken[]", "ExponentPushToken[a b]", "<script>"])
def test_other_strings_are_refused(token):
    assert not donor_push.is_expo_push_token(token)
    with pytest.raises(InvalidInputError):
        donor_push.clean_push_token(token)


@pytest.mark.parametrize("token", [None, "", "   "])
def test_empty_means_forget(token):
    assert donor_push.clean_push_token(token) is None


# ── wording ────────────────────────────────────────────────────────


def test_alert_names_group_units_and_distance_but_no_hospital():
    msg = donor_push.request_alert("O-", 2, "critical", 3.456)
    assert msg["title"] == "Critical: O- blood needed"
    assert msg["body"] == "A hospital 3.5 km from you needs 2 units. Open HaemNet to answer."
    one = donor_push.request_alert("B+", 1, "urgent", None)
    assert one["title"].startswith("Urgent") and "near you needs 1 unit." in one["body"]


def test_device_not_registered_is_detected_in_both_receipt_shapes():
    gone = {"status": "error", "details": {"error": "DeviceNotRegistered"}}
    assert donor_push.device_not_registered({"data": gone})
    assert donor_push.device_not_registered({"data": [gone]})
    assert not donor_push.device_not_registered({"data": {"status": "ok", "id": "x"}})
    assert not donor_push.device_not_registered(
        {"data": {"status": "error", "details": {"error": "MessageRateExceeded"}}}
    )
    assert not donor_push.device_not_registered({})


# ── alerting matched donors ────────────────────────────────────────


@pytest.fixture
def push_calls(monkeypatch):
    sent: list[dict] = []
    tokens = {"d1": TOKEN, "d2": None, "d3": "ExponentPushToken[yyyyyyyyyyyyyyyy]"}
    cleared: list[tuple] = []

    async def fake_token(donor_id):
        return tokens.get(donor_id)

    async def fake_send(**kw):
        sent.append(kw)
        return {"data": {"status": "ok", "id": "receipt"}}

    async def fake_set(phone, token):
        cleared.append((phone, token))
        return True

    monkeypatch.setattr(donor_push, "get_donor_push_token", fake_token)
    monkeypatch.setattr(donor_push, "send_push_notification", fake_send)
    monkeypatch.setattr(donor_push, "db_set_donor_push_token", fake_set)
    return {"sent": sent, "cleared": cleared, "tokens": tokens}


MATCHED = {
    "d1": {"has_app": True, "phone": "+919000000001", "distance_km": 1.2},
    "d2": {"has_app": True, "phone": "+919000000002", "distance_km": 2.0},  # app, but no token yet
    "d3": {"has_app": False, "phone": "+919000000003", "distance_km": 0.5},  # call only
}


async def test_only_app_donors_with_a_token_are_alerted(push_calls):
    sent = await donor_push.alert_donors_of_request("disp-1", MATCHED, "O-", 2, "urgent")
    assert sent == 1
    [push] = push_calls["sent"]
    assert push["expo_token"] == TOKEN
    assert push["data"] == {"type": "new_request", "dispatch_id": "disp-1"}
    assert "1.2 km from you" in push["body"]


async def test_alerts_can_be_switched_off(push_calls, monkeypatch):
    monkeypatch.setattr(settings, "push_request_alerts", False)
    assert await donor_push.alert_donors_of_request("disp-1", MATCHED, "O-", 2, "urgent") == 0
    assert push_calls["sent"] == []


async def test_an_expired_token_is_forgotten(push_calls, monkeypatch):
    async def gone(**kw):
        return {"data": {"status": "error", "details": {"error": "DeviceNotRegistered"}}}

    monkeypatch.setattr(donor_push, "send_push_notification", gone)
    assert await donor_push.alert_donors_of_request("disp-1", MATCHED, "O-", 1, "urgent") == 0
    assert push_calls["cleared"] == [("+919000000001", None)]


async def test_a_failing_push_never_raises(push_calls, monkeypatch):
    async def boom(**kw):
        raise ConnectionError("expo down")

    monkeypatch.setattr(donor_push, "send_push_notification", boom)
    assert await donor_push.alert_donors_of_request("disp-1", MATCHED, "O-", 1, "urgent") == 0


async def test_alerts_go_out_concurrently(push_calls, monkeypatch):
    many = {f"d{i}": {"has_app": True, "phone": f"+9190000000{i:02d}"} for i in range(10)}
    push_calls["tokens"].update({f"d{i}": TOKEN for i in range(10)})

    async def slow(**kw):
        await asyncio.sleep(0.05)
        return {"data": {"status": "ok"}}

    monkeypatch.setattr(donor_push, "send_push_notification", slow)
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await donor_push.alert_donors_of_request("disp-1", many, "A+", 1, "urgent") == 10
    assert loop.time() - started < 0.4


# ── API ────────────────────────────────────────────────────────────


@pytest.fixture
def stored(monkeypatch):
    seen: list[tuple] = []

    async def fake_set(phone, token):
        seen.append((phone, token))
        return True

    monkeypatch.setattr(donor_push, "db_set_donor_push_token", fake_set)
    return seen


def test_signed_in_donor_registers_and_clears_a_token(client, stored):
    res = client.post("/api/donor/push-token", json={"token": TOKEN}, headers=donor_headers(PHONE))
    assert res.status_code == 200 and res.json() == {"status": "ok", "push_enabled": True}
    res = client.post("/api/donor/push-token", json={"token": None}, headers=donor_headers(PHONE))
    assert res.json()["push_enabled"] is False
    assert stored == [(PHONE, TOKEN), (PHONE, None)]


def test_push_token_needs_sign_in_and_a_real_token(client, stored):
    assert client.post("/api/donor/push-token", json={"token": TOKEN}).status_code == 401
    res = client.post("/api/donor/push-token", json={"token": "not-a-token"}, headers=donor_headers(PHONE))
    assert res.status_code == 422
    assert (
        client.post("/api/donor/push-token", json={"token": "x" * 300}, headers=donor_headers(PHONE)).status_code == 422
    )
    assert stored == []


def test_push_token_for_a_donor_without_a_profile(client, monkeypatch):
    async def missing(phone, token):
        return False

    monkeypatch.setattr(donor_push, "db_set_donor_push_token", missing)
    res = client.post("/api/donor/push-token", json={"token": TOKEN}, headers=donor_headers(PHONE))
    assert res.status_code == 404


def test_push_token_on_the_neo4j_layer(client, monkeypatch):
    async def unsupported(phone, token):
        raise NotImplementedError

    monkeypatch.setattr(donor_push, "db_set_donor_push_token", unsupported)
    res = client.post("/api/donor/push-token", json={"token": TOKEN}, headers=donor_headers(PHONE))
    assert res.status_code == 501


def test_router_exposes_the_endpoint():
    paths = {route.path for route in donors_api.router.routes}
    assert "/api/donor/push-token" in paths


# ── dispatch graph ─────────────────────────────────────────────────


async def test_initiating_calls_also_alerts_app_donors(monkeypatch, store):
    from backend.orchestration import graph

    placed: list[str] = []
    alerted: list[dict] = []

    async def fake_place_call(node, dispatch_id, donor_id):
        placed.append(donor_id)

    async def fake_alert(dispatch_id, donors, **kw):
        alerted.append({"dispatch_id": dispatch_id, "donors": sorted(donors), **kw})
        return 1

    monkeypatch.setattr(graph, "place_call", fake_place_call)
    monkeypatch.setattr(graph, "alert_donors_of_request", fake_alert)
    state = {
        "dispatch_id": "disp-9",
        "hospital_id": "h1",
        "blood_group": "O-",
        "units": 3,
        "urgency": "critical",
        "lat": 13.0,
        "lng": 80.2,
        "donors": {
            "11111111-1111-1111-1111-111111111111": {
                "donor_id": "11111111-1111-1111-1111-111111111111",
                "name": "Asha",
                "phone": PHONE,
                "has_app": True,
                "language": "english",
                "distance_km": 1.0,
            }
        },
    }
    await graph.initiate_calls_node(state)
    assert placed == ["11111111-1111-1111-1111-111111111111"]
    assert alerted == [
        {
            "dispatch_id": "disp-9",
            "donors": ["11111111-1111-1111-1111-111111111111"],
            "blood_group": "O-",
            "units": 3,
            "urgency": "critical",
        }
    ]
