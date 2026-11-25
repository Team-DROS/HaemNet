"""Security headers, body limits, safe errors and the dispatch audit trail."""

import pytest
from fastapi.testclient import TestClient

from backend.api import dispatches, health
from backend.config import settings
from backend.main import app
from backend.services import dispatching as planning
from backend.tests.conftest import HOSPITAL, matched_donor

BODY = {
    "hospital_id": HOSPITAL,
    "blood_group": "O-",
    "urgency": "critical",
    "coordinates": {"lat": 13.06, "lng": 80.25},
    "units": 2,
}


def test_security_headers_on_every_response(client):
    res = client.get("/api/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in res.headers["content-security-policy"]


def test_hsts_only_over_https_or_in_production(client, monkeypatch):
    assert "strict-transport-security" not in client.get("/api/health").headers
    monkeypatch.setattr(settings, "app_env", "production")
    assert "max-age=31536000" in client.get("/api/health").headers["strict-transport-security"]


def test_oversized_json_is_rejected_before_it_is_read(client, monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_kb", 1)
    res = client.post("/api/contact", content=b"x" * 2048, headers={"content-type": "application/json"})
    assert res.status_code == 413 and res.json() == {"detail": "Request body too large"}
    assert res.headers["x-content-type-options"] == "nosniff"  # headers still applied


def test_uploads_have_their_own_larger_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_kb", 1)
    res = client.post(
        "/api/hospitals/me/documents", content=b"x" * 4096, headers={"content-type": "multipart/form-data; boundary=x"}
    )
    assert res.status_code != 413  # got past the size check (later rejected as a malformed form)


def test_unhandled_errors_return_a_request_id_and_no_internals(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("secret database password in message")

    monkeypatch.setattr(health, "db_health", boom)
    res = TestClient(app, raise_server_exceptions=False).get("/api/health")
    body = res.json()
    assert res.status_code == 500 and "secret" not in res.text
    assert body["request_id"] == res.headers["x-request-id"]


def test_docs_are_hidden_in_production(monkeypatch):
    from backend.main import create_app

    monkeypatch.setattr(settings, "app_env", "production")
    production = create_app()
    assert production.docs_url is None and production.openapi_url is None
    assert TestClient(production).get("/").json()["docs"] is None

    monkeypatch.setattr(settings, "app_env", "development")
    assert create_app().docs_url == "/docs"


# ── dispatch audit trail ──────────────────────────────────────────


@pytest.fixture
def dispatching(monkeypatch):
    async def fake_find(**kwargs):
        return [matched_donor(13.06, 80.25)]

    async def fake_run(dispatch_id, state):
        pass

    monkeypatch.setattr(planning, "find_eligible_donors", fake_find)
    monkeypatch.setattr(dispatches, "run_dispatch_graph", fake_run)


def test_dispatch_is_audited_with_the_owner(client, auth_headers, dispatching, platform_repo):
    assert client.post("/api/dispatch", headers=auth_headers, json=BODY).status_code == 200
    entry = platform_repo.audit[-1]
    assert entry["hospital_id"] == HOSPITAL and entry["actor"] == "owner" and entry["action"] == "dispatch_created"
    assert "O- x2 critical matched=1" in entry["reason"]


def test_dispatch_is_audited_with_the_staff_member(client, dispatching, platform_repo):
    from backend.api import auth

    token = auth.create_access_token({"sub": HOSPITAL, "role": "hospital", "staff_id": "STF-1", "staff_role": "staff"})
    platform_repo.hospitals[HOSPITAL] = {"id": HOSPITAL, "staff": [{"id": "STF-1", "active": True, "email": "a@b.co"}]}
    client.post("/api/dispatch", headers={"Authorization": f"Bearer {token}"}, json=BODY)
    assert platform_repo.audit[-1]["actor"] == "STF-1"


def test_audit_failure_never_blocks_an_emergency_request(client, auth_headers, dispatching, platform_repo, monkeypatch):
    async def broken(entry):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(platform_repo, "add_audit", broken)
    assert client.post("/api/dispatch", headers=auth_headers, json=BODY).status_code == 200


def test_closing_a_dispatch_is_audited(client, auth_headers, store, broadcasts, platform_repo):
    store.add("dp-1")
    assert client.post("/api/dispatches/dp-1/close", headers=auth_headers).status_code == 200
    assert platform_repo.audit[-1]["action"] == "dispatch_closed" and platform_repo.audit[-1]["reason"] == "dp-1"


def test_error_reporting_never_raises(monkeypatch):
    import sentry_sdk

    from backend.services.error_reporting import report_exception

    def broken(exc):
        raise TypeError("cannot pickle 'FrameLocalsProxy' object")

    monkeypatch.setattr(sentry_sdk, "capture_exception", broken)
    report_exception(RuntimeError("original problem"))  # must not raise
