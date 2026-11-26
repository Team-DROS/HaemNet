"""
Query counts for endpoints the dashboard and donor app call constantly.

Runs against a tiny in-memory stand-in for the collections, so it needs no
MongoDB; test_mongo_repo.py covers the same functions against a real server.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from backend import dispatch_store as store_module
from backend.db_services import mongo_repo


def _matches(doc, query):
    for key, want in query.items():
        if isinstance(want, dict) and "$in" in want:
            if doc.get(key) not in want["$in"]:
                return False
        elif doc.get(key) != want:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        async def gen():
            for doc in self._docs:
                yield doc

        return gen()


class _Collection:
    def __init__(self, docs):
        self.docs, self.queries = docs, 0

    async def find_one(self, query, projection=None):
        self.queries += 1
        return next((d for d in self.docs if _matches(d, query)), None)

    def find(self, query, projection=None):
        self.queries += 1
        return _Cursor([d for d in self.docs if _matches(d, query)])


def _at(day):
    return datetime(2026, 1, day, tzinfo=timezone.utc)


@pytest.fixture
def fake_db(monkeypatch):
    calls = [{"donor_id": "d1", "dispatch_id": f"open-{n}", "status": "ringing", "distance_km": n} for n in range(1, 9)]
    calls += [
        {"donor_id": "d1", "dispatch_id": "closed", "status": "ringing"},
        {"donor_id": "d1", "dispatch_id": "decided", "status": "accepted"},
    ]
    dispatches = [
        {"_id": f"open-{n}", "hospital_id": f"H{n % 2}", "is_complete": False, "created_at": _at(n)}
        for n in range(1, 9)
    ]
    dispatches += [
        {"_id": "closed", "hospital_id": "H0", "is_complete": True, "created_at": _at(20)},
        {"_id": "decided", "hospital_id": "H0", "is_complete": False, "created_at": _at(21)},
    ]
    db = {
        mongo_repo.DONORS: _Collection([{"_id": "d1", "phone": "+919000000001"}]),
        mongo_repo.CALLS: _Collection(calls),
        mongo_repo.DISPATCHES: _Collection(dispatches),
        mongo_repo.HOSPITALS: _Collection(
            [
                {"_id": "H0", "name": "Apollo", "location": "Chennai"},
                {"_id": "H1", "name": "KMC", "location": "Manipal"},
            ]
        ),
    }
    monkeypatch.setattr(mongo_repo, "get_database", lambda: db)
    return db


@pytest.mark.asyncio
async def test_donor_requests_use_a_fixed_number_of_queries(fake_db):
    rows = await mongo_repo.db_requests_for_donor("+919000000001")

    assert [r["dispatch_id"] for r in rows] == [f"open-{n}" for n in range(8, 0, -1)]  # newest first
    assert {r["hospital_name"] for r in rows} == {"Apollo", "KMC"}
    assert rows[0]["address"] == "Chennai"  # falls back to the hospital's location
    # donor + calls + dispatches + hospitals, however many requests are open
    assert sum(c.queries for c in fake_db.values()) == 4


@pytest.mark.asyncio
async def test_unknown_donor_costs_one_query(fake_db):
    assert await mongo_repo.db_requests_for_donor("+919999999999") == []
    assert sum(c.queries for c in fake_db.values()) == 1


@pytest.mark.asyncio
async def test_active_dispatches_load_concurrently(monkeypatch):
    in_flight, peak = 0, 0

    async def ids(hospital_id):
        return ["a", "b", "gone", "c"]

    async def slow_get(dispatch_id):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return None if dispatch_id == "gone" else {"dispatch_id": dispatch_id}

    monkeypatch.setattr(store_module, "db_active_dispatch_ids", ids)
    monkeypatch.setattr(store_module, "db_get_dispatch", slow_get)
    loaded = await store_module.dispatch_store.active_for_hospital("H0")

    assert [d["dispatch_id"] for d in loaded] == ["a", "b", "c"]  # order kept, missing skipped
    assert peak == 4
