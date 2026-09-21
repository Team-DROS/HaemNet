"""
Shared fixtures. Nothing here touches Neo4j, Twilio or Sarvam: the dispatch
store and database calls are replaced with an in-memory fake per test.
"""

from __future__ import annotations

import copy
import os

os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("APP_ENV", "development")

import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.api.auth import create_access_token
from backend.main import app

HOSPITAL = "HOSP-1001"


class FakeStore:
    """In-memory stand-in for DispatchStore with the same async interface."""

    def __init__(self):
        self.dispatches: dict = {}
        self.completed: list = []

    def add(self, dispatch_id="dp-1", hospital_id=HOSPITAL, units=1, donors=None, **extra):
        self.dispatches[dispatch_id] = {
            "dispatch_id": dispatch_id,
            "hospital_id": hospital_id,
            "blood_group": "O-",
            "lat": 13.06, "lng": 80.25,
            "units": units, "urgency": "critical", "address": "Trauma Bay 2",
            "created_at": "2026-09-18T12:40:41",
            "is_complete": False,
            "donors": {d["donor_id"]: dict(d) for d in (donors or [])},
            **extra,
        }
        return self.dispatches[dispatch_id]

    async def get_dispatch(self, dispatch_id):
        d = self.dispatches.get(dispatch_id)
        return copy.deepcopy(d) if d else None

    async def get_donor(self, dispatch_id, donor_id):
        d = self.dispatches.get(dispatch_id)
        return copy.deepcopy(d["donors"].get(donor_id)) if d else None

    async def update_donor_status(self, dispatch_id, donor_id, status, eta_minutes=None):
        donor = self.dispatches[dispatch_id]["donors"][donor_id]
        donor["status"] = getattr(status, "value", status)
        if eta_minutes is not None:
            donor["eta_minutes"] = eta_minutes
        return True

    async def mark_complete(self, dispatch_id):
        self.dispatches[dispatch_id]["is_complete"] = True
        self.completed.append(dispatch_id)

    async def active_for_hospital(self, hospital_id):
        return [copy.deepcopy(d) for d in self.dispatches.values()
                if d["hospital_id"] == hospital_id and not d["is_complete"]]

    async def requests_for_donor(self, phone):
        out = []
        for d in self.dispatches.values():
            if d["is_complete"]:
                continue
            for donor in d["donors"].values():
                if donor.get("phone") == phone and donor.get("status") in {"ringing", "answered", "no_answer"}:
                    out.append({
                        "dispatch_id": d["dispatch_id"], "donor_id": donor["donor_id"],
                        "status": donor["status"], "distance_km": donor.get("distance_km"),
                        "blood_group": d["blood_group"], "units": d["units"],
                        "urgency": d["urgency"], "created_at": d["created_at"],
                        "lat": d["lat"], "lng": d["lng"],
                        "hospital_name": "Apollo Hospital", "address": d["address"],
                    })
        return out


def donor(donor_id, phone, status="ringing", distance_km=2.4, name=None):
    return {
        "donor_id": donor_id, "name": name or donor_id, "phone": phone,
        "status": status, "eta_minutes": None, "distance_km": distance_km,
        "has_app": True, "language": "tamil",
    }


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(routes, "dispatch_store", fake)
    return fake


@pytest.fixture
def broadcasts(monkeypatch):
    """Capture everything the routes try to push to dashboards."""
    sent = []

    async def fake_broadcast(dispatch_id, update):
        sent.append((dispatch_id, update))

    async def fake_broadcast_raw(dispatch_id, data):
        sent.append((dispatch_id, data))

    monkeypatch.setattr(routes.manager, "broadcast", fake_broadcast)
    monkeypatch.setattr(routes.manager, "broadcast_raw", fake_broadcast_raw)
    return sent


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token({"sub": HOSPITAL})
    return {"Authorization": f"Bearer {token}"}
