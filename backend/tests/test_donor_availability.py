"""Short breaks from automated calls: the rule, the endpoint and the profile."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.api import donors as donors_api
from backend.schemas.models import Coordinates, DonorNode
from backend.services import donor_availability
from backend.services.errors import InvalidInputError
from backend.tests.conftest import donor_headers

PHONE = "+919000000001"
NOW = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)


def node(**kw) -> DonorNode:
    base = {
        "id": uuid4(),
        "name": "Asha",
        "phone": PHONE,
        "blood_group": "O-",
        "language": "english",
        "location": Coordinates(lat=13.0, lng=80.2),
    }
    return DonorNode(**{**base, **kw})


def test_pause_end_counts_days_from_now():
    assert donor_availability.pause_end(7, NOW) == NOW + timedelta(days=7)
    assert donor_availability.pause_end(0, NOW) is None
    naive = datetime(2026, 11, 25, 10, 0)
    assert donor_availability.pause_end(1, naive) == NOW + timedelta(days=1)


@pytest.mark.parametrize("days", [-1, donor_availability.MAX_PAUSE_DAYS + 1, True, 2.5, "7"])
def test_pause_length_is_checked(days):
    with pytest.raises(InvalidInputError):
        donor_availability.pause_end(days, NOW)


def test_paused_and_callable():
    assert donor_availability.callable_now(node(), NOW)
    paused = node(calls_paused_until=NOW + timedelta(hours=1))
    assert donor_availability.is_paused(paused, NOW) and not donor_availability.callable_now(paused, NOW)
    ended = node(calls_paused_until=NOW - timedelta(seconds=1))
    assert not donor_availability.is_paused(ended, NOW) and donor_availability.callable_now(ended, NOW)
    assert not donor_availability.callable_now(node(calls_opt_out=True), NOW)
    naive_future = node(calls_paused_until=datetime(2026, 11, 26))
    assert donor_availability.is_paused(naive_future, NOW)


@pytest.fixture
def saved(monkeypatch):
    seen: list[tuple] = []

    async def fake_set(phone, until):
        seen.append((phone, until))
        return True

    monkeypatch.setattr(donor_availability, "db_set_calls_paused_until", fake_set)
    return seen


def test_donor_pauses_for_a_week_and_resumes(client, saved):
    res = client.post("/api/donor/availability", json={"pause_days": 7}, headers=donor_headers(PHONE))
    assert res.status_code == 200
    until = datetime.fromisoformat(res.json()["calls_paused_until"])
    assert timedelta(days=6, hours=23) < until - datetime.now(timezone.utc) <= timedelta(days=7)
    res = client.post("/api/donor/availability", json={"pause_days": 0}, headers=donor_headers(PHONE))
    assert res.json() == {"status": "ok", "calls_paused_until": None}
    assert [phone for phone, _ in saved] == [PHONE, PHONE] and saved[1][1] is None


def test_availability_needs_sign_in_and_a_sensible_length(client, saved):
    assert client.post("/api/donor/availability", json={"pause_days": 7}).status_code == 401
    for bad in (-1, 31, "a week"):
        res = client.post("/api/donor/availability", json={"pause_days": bad}, headers=donor_headers(PHONE))
        assert res.status_code == 422
    assert saved == []


def test_availability_for_unknown_donor_and_neo4j(client, monkeypatch):
    async def missing(phone, until):
        return False

    monkeypatch.setattr(donor_availability, "db_set_calls_paused_until", missing)
    assert (
        client.post("/api/donor/availability", json={"pause_days": 3}, headers=donor_headers(PHONE)).status_code == 404
    )

    async def unsupported(phone, until):
        raise NotImplementedError

    monkeypatch.setattr(donor_availability, "db_set_calls_paused_until", unsupported)
    assert (
        client.post("/api/donor/availability", json={"pause_days": 3}, headers=donor_headers(PHONE)).status_code == 501
    )


def test_profile_reports_only_a_break_still_in_effect(client, monkeypatch):
    state = {"until": datetime.now(timezone.utc) + timedelta(days=2)}

    async def fake_get(phone):
        return node(calls_paused_until=state["until"])

    monkeypatch.setattr(donors_api, "get_donor_by_phone", fake_get)
    res = client.get(f"/api/donor/profile/{PHONE}", headers=donor_headers(PHONE))
    assert res.json()["donor"]["calls_paused_until"] == state["until"].isoformat()
    state["until"] = datetime.now(timezone.utc) - timedelta(days=1)
    res = client.get(f"/api/donor/profile/{PHONE}", headers=donor_headers(PHONE))
    assert res.json()["donor"]["calls_paused_until"] is None
