"""Call cost guards: donors per request and requests per hospital per day."""

from types import SimpleNamespace

from backend.api import dispatches
from backend.config import settings
from backend.services import call_guard
from backend.services import dispatching as planning

BODY = {
    "hospital_id": "HOSP-1001",
    "blood_group": "O-",
    "urgency": "critical",
    "coordinates": {"lat": 13.06, "lng": 80.25},
    "units": 1,
}


def donor_at(offset):
    return SimpleNamespace(location=SimpleNamespace(lat=13.06 + offset, lng=80.25))


def test_cap_keeps_the_closest_donors(monkeypatch):
    monkeypatch.setattr(settings, "max_donors_per_dispatch", 3)
    donors = [donor_at(o) for o in (0.09, 0.01, 0.07, 0.02, 0.05)]
    kept = call_guard.cap_donors(donors, 13.06, 80.25)
    assert [round(d.location.lat - 13.06, 2) for d in kept] == [0.01, 0.02, 0.05]


def test_cap_leaves_small_lists_alone(monkeypatch):
    monkeypatch.setattr(settings, "max_donors_per_dispatch", 5)
    donors = [donor_at(0.01), donor_at(0.02)]
    assert call_guard.cap_donors(donors, 13.06, 80.25) is donors


def test_dispatch_response_reports_the_capped_count(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "max_donors_per_dispatch", 2)

    async def fake_find(**kwargs):
        return [donor_at(0.01), donor_at(0.02), donor_at(0.03), donor_at(0.04)]

    async def fake_run(dispatch_id, state):
        pass

    monkeypatch.setattr(planning, "find_eligible_donors", fake_find)
    monkeypatch.setattr(dispatches, "run_dispatch_graph", fake_run)
    assert client.post("/api/dispatch", headers=auth_headers, json=BODY).json()["donors_matched"] == 2


def test_daily_quota_blocks_extra_requests_with_retry_after(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "max_dispatches_per_hospital_day", 2)

    async def fake_find(**kwargs):
        return [donor_at(0.01)]

    async def fake_run(dispatch_id, state):
        pass

    monkeypatch.setattr(planning, "find_eligible_donors", fake_find)
    monkeypatch.setattr(dispatches, "run_dispatch_graph", fake_run)
    assert client.post("/api/dispatch", headers=auth_headers, json=BODY).status_code == 200
    assert client.post("/api/dispatch", headers=auth_headers, json=BODY).status_code == 200
    res = client.post("/api/dispatch", headers=auth_headers, json=BODY)
    assert res.status_code == 429 and int(res.headers["Retry-After"]) > 0


def test_requests_that_match_nobody_do_not_use_the_quota(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "max_dispatches_per_hospital_day", 1)

    async def none_found(**kwargs):
        return []

    monkeypatch.setattr(planning, "find_eligible_donors", none_found)
    for _ in range(3):
        assert client.post("/api/dispatch", headers=auth_headers, json=BODY).json()["donors_matched"] == 0
