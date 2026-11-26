"""
Shared fixtures. Nothing here touches Neo4j, Twilio or Sarvam: the dispatch
store and database calls are replaced with an in-memory fake per test.
"""

from __future__ import annotations

import copy
import os

os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production-0123456789")
os.environ.setdefault("APP_ENV", "development")

import pytest
from fastapi.testclient import TestClient

from backend.api import dispatches, donors
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
            "lat": 13.06,
            "lng": 80.25,
            "units": units,
            "urgency": "critical",
            "address": "Trauma Bay 2",
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

    async def mark_complete(self, dispatch_id, fulfilled=False):
        self.dispatches[dispatch_id]["is_complete"] = True
        self.dispatches[dispatch_id]["fulfilled"] = fulfilled
        self.completed.append(dispatch_id)

    async def register_call(self, call_id, dispatch_id, donor_id):
        self.registered_calls = getattr(self, "registered_calls", []) + [(call_id, dispatch_id, donor_id)]

    async def history_for_hospital(self, hospital_id, since_iso):
        self.history_since = since_iso
        return [dict(r) for r in getattr(self, "history_rows", []) if r["hospital_id"] == hospital_id]

    async def active_for_hospital(self, hospital_id):
        return [
            copy.deepcopy(d)
            for d in self.dispatches.values()
            if d["hospital_id"] == hospital_id and not d["is_complete"]
        ]

    async def requests_for_donor(self, phone):
        out = []
        for d in self.dispatches.values():
            if d["is_complete"]:
                continue
            for donor in d["donors"].values():
                if donor.get("phone") == phone and donor.get("status") in {"ringing", "answered", "no_answer"}:
                    out.append(
                        {
                            "dispatch_id": d["dispatch_id"],
                            "donor_id": donor["donor_id"],
                            "status": donor["status"],
                            "distance_km": donor.get("distance_km"),
                            "blood_group": d["blood_group"],
                            "units": d["units"],
                            "urgency": d["urgency"],
                            "created_at": d["created_at"],
                            "lat": d["lat"],
                            "lng": d["lng"],
                            "hospital_name": "Apollo Hospital",
                            "address": d["address"],
                        }
                    )
        return out


def matched_donor(lat=13.06, lng=80.25, name="Asha", blood_group="O-"):
    """A real DonorNode, as find_eligible_donors returns, for faking donor matching."""
    from uuid import uuid4

    from backend.schemas.models import DonorNode

    donor_id = uuid4()
    return DonorNode(
        id=donor_id,
        name=name,
        phone=f"+9190{donor_id.int % 10**8:08d}",
        blood_group=blood_group,
        language="tamil",
        location={"lat": lat, "lng": lng},
    )


def donor(donor_id, phone, status="ringing", distance_km=2.4, name=None):
    return {
        "donor_id": donor_id,
        "name": name or donor_id,
        "phone": phone,
        "status": status,
        "eta_minutes": None,
        "distance_km": distance_km,
        "has_app": True,
        "language": "tamil",
    }


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(dispatches, "dispatch_store", fake)
    monkeypatch.setattr(donors, "dispatch_store", fake)
    return fake


@pytest.fixture
def broadcasts(monkeypatch):
    """Capture everything the routes try to push to dashboards."""
    sent = []

    async def fake_broadcast(dispatch_id, update):
        sent.append((dispatch_id, update))

    async def fake_broadcast_raw(dispatch_id, data):
        sent.append((dispatch_id, data))

    monkeypatch.setattr(dispatches.manager, "broadcast", fake_broadcast)
    monkeypatch.setattr(dispatches.manager, "broadcast_raw", fake_broadcast_raw)
    return sent


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token({"sub": HOSPITAL, "role": "hospital"})
    return {"Authorization": f"Bearer {token}"}


def donor_headers(phone="+919000000001"):
    token = create_access_token({"sub": phone, "role": "donor"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset_limits():
    """Rate limiters and pending codes are process-wide; isolate each test."""
    from backend.api import auth

    auth._login_failures.clear()
    auth._donor_failures.clear()
    auth._donor_signups.clear()


@pytest.fixture(autouse=True)
def platform_repo(monkeypatch):
    """Hospital verification data lives in memory; email is captured, never sent."""
    from backend.api import admin, hospital_account, hospital_staff
    from backend.services import hospital_platform as hp
    from backend.services import hospital_review

    repo = hp.MemoryPlatformRepo()
    monkeypatch.setattr(hp, "repo", repo)
    repo.emails = []

    async def fake_verification(to, name, token):
        repo.emails.append(("verify", to, token))
        return True

    async def fake_decision(to, name, action, reason=""):
        repo.emails.append((action, to, reason))
        return True

    monkeypatch.setattr(hp, "send_verification_email", fake_verification)
    monkeypatch.setattr(hospital_review, "send_decision_email", fake_decision)
    for limiter in (
        admin._admin_failures,
        hospital_account._resend_limit,
        hospital_account._verify_limit,
        hospital_account._upload_limit,
        hospital_staff._staff_failures,
    ):
        limiter.clear()
    return repo


@pytest.fixture
def hospital_db(monkeypatch):
    """Minimal fake for the hospital login/registration data layer."""
    from backend.api import auth

    rows = {}

    async def fake_get(hospital_id):
        return rows.get(hospital_id)

    async def fake_create(id, name, location, phone, password_hash):
        rows[id] = {"id": id, "name": name, "location": location, "phone": phone, "password_hash": password_hash}

    monkeypatch.setattr(auth, "db_get_hospital_by_id", fake_get)
    monkeypatch.setattr(auth, "db_create_hospital", fake_create)
    return rows


@pytest.fixture
def uploads(monkeypatch, tmp_path):
    """Store uploaded documents in a temporary folder."""
    from backend.config import settings
    from backend.services import file_storage

    monkeypatch.setattr(settings, "s3_bucket", "")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    file_storage.reset_cache()
    return tmp_path


@pytest.fixture
def admin(client, monkeypatch):
    """Authorization headers for a signed-in admin."""
    import bcrypt

    from backend.config import settings

    monkeypatch.setattr(settings, "admin_username", "root")
    monkeypatch.setattr(settings, "admin_password_hash", bcrypt.hashpw(b"adminpass", bcrypt.gensalt()).decode())
    token = client.post("/api/admin/token", data={"username": "root", "password": "adminpass"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset_contact_limit():
    from backend.api import contact

    contact._per_ip.clear()


@pytest.fixture(autouse=True)
def _reset_call_quota():
    from backend.services import call_guard

    call_guard.reset_quotas()


@pytest.fixture(autouse=True)
def _reset_otp():
    from backend.api import auth
    from backend.services import otp

    otp.reset_for_tests()
    auth._otp_by_phone.clear()
    auth._otp_by_ip.clear()


@pytest.fixture(autouse=True)
def _reset_call_retries():
    from backend.services import call_retry

    call_retry.reset_for_tests()
