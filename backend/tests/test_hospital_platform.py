"""Hospital sign-up, email verification, document upload, admin review and the dispatch gate."""

import bcrypt
import pytest

from backend.api import auth
from backend.api import hospital_platform as api
from backend.config import settings
from backend.services import hospital_platform as hp

PDF = b"%PDF-1.4 test file"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

SIGNUP = {
    "name": "Apollo", "location": "Chennai", "phone": "+919876543210", "password": "pw12345",
    "official_email": "Admin@Apollo.example", "contact_person": "Dr Rao", "hfr_id": "IN123",
}


@pytest.fixture(autouse=True)
def hospital_db(monkeypatch):
    """Minimal fake for the hospital login/registration data layer."""
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
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    return tmp_path


@pytest.fixture
def admin(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "root")
    monkeypatch.setattr(settings, "admin_password_hash", bcrypt.hashpw(b"adminpass", bcrypt.gensalt()).decode())
    token = client.post("/api/admin/token", data={"username": "root", "password": "adminpass"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def signup(client, platform_repo, hospital_db, **overrides):
    body = {**SIGNUP, **overrides}
    res = client.post("/api/auth/register", json=body)
    assert res.status_code == 200, res.text
    hospital_id = res.json()["id"]
    # the fake auth table and the platform table are separate stores in tests
    hospital_db[hospital_id].update(platform_repo.hospitals[hospital_id])
    hospital_db[hospital_id]["id"] = hospital_id
    token = auth.create_access_token({"sub": hospital_id, "role": "hospital"})
    return hospital_id, {"Authorization": f"Bearer {token}"}


def verify(client, platform_repo):
    token = [e for e in platform_repo.emails if e[0] == "verify"][-1][2]
    return client.post("/api/hospitals/verify-email", json={"token": token})


# ── sign-up ───────────────────────────────────────────────────────

def test_signup_creates_pending_unverified_hospital_and_sends_email(client, platform_repo, hospital_db):
    hid, _ = signup(client, platform_repo, hospital_db)
    h = platform_repo.hospitals[hid]
    assert h["status"] == "pending" and h["email_verified"] is False
    assert h["official_email"] == "admin@apollo.example"
    assert platform_repo.emails[0][:2] == ("verify", "admin@apollo.example")
    assert "email_verification_hash" in h and platform_repo.emails[0][2] not in str(h)


@pytest.mark.parametrize("field,value", [
    ("official_email", "not-an-email"), ("contact_person", " "), ("hfr_id", ""),
])
def test_signup_requires_verification_details(client, field, value):
    body = {**SIGNUP, field: value}
    if field == "hfr_id":
        body["registration_number"] = ""
    assert client.post("/api/auth/register", json=body).status_code == 422


def test_login_reports_status(client, platform_repo, hospital_db):
    hid, _ = signup(client, platform_repo, hospital_db)
    hospital_db[hid]["password_hash"] = auth.get_password_hash("pw12345")
    res = client.post("/api/auth/token", data={"username": hid, "password": "pw12345"})
    assert res.json()["user"]["status"] == "pending"
    assert "password_hash" not in res.json()["user"]


# ── email verification ────────────────────────────────────────────

def test_verify_email_works_once(client, platform_repo, hospital_db):
    hid, _ = signup(client, platform_repo, hospital_db)
    assert verify(client, platform_repo).json() == {"verified": True}
    assert platform_repo.hospitals[hid]["email_verified"] is True
    assert verify(client, platform_repo).status_code == 400


def test_verify_rejects_bad_and_expired_tokens(client, platform_repo, hospital_db):
    hid, _ = signup(client, platform_repo, hospital_db)
    assert client.post("/api/hospitals/verify-email", json={"token": "x" * 40}).status_code == 400
    platform_repo.hospitals[hid]["email_verification_expires"] = "2000-01-01T00:00:00+00:00"
    assert verify(client, platform_repo).status_code == 400


def test_resend_verification_issues_new_token_and_is_limited(client, platform_repo, hospital_db):
    hid, headers = signup(client, platform_repo, hospital_db)
    first = platform_repo.emails[0][2]
    assert client.post("/api/hospitals/resend-verification", headers=headers).json()["sent"] is True
    assert platform_repo.emails[-1][2] != first
    assert client.post("/api/hospitals/resend-verification", headers=headers).status_code == 200
    assert client.post("/api/hospitals/resend-verification", headers=headers).status_code == 200
    assert client.post("/api/hospitals/resend-verification", headers=headers).status_code == 429


# ── documents ─────────────────────────────────────────────────────

def upload(client, headers, data=PDF, name="licence.pdf", kind="hfr_certificate"):
    return client.post("/api/hospitals/me/documents", headers=headers, data={"kind": kind},
                       files={"file": (name, data, "application/octet-stream")})


def test_upload_accepts_pdf_and_png_and_lists_them(client, platform_repo, hospital_db, uploads):
    hid, headers = signup(client, platform_repo, hospital_db)
    assert upload(client, headers).status_code == 200
    assert upload(client, headers, PNG, "scan.png", "blood_centre_licence").status_code == 200
    profile = client.get("/api/hospitals/me", headers=headers).json()
    assert [d["content_type"] for d in profile["documents"]] == ["application/pdf", "image/png"]
    assert "key" not in profile["documents"][0]


def test_upload_rejects_wrong_type_even_with_pdf_name(client, platform_repo, hospital_db, uploads):
    _, headers = signup(client, platform_repo, hospital_db)
    assert upload(client, headers, b"<script>alert(1)</script>", "licence.pdf").status_code == 415


def test_upload_rejects_empty_oversize_and_bad_kind(client, platform_repo, hospital_db, uploads, monkeypatch):
    _, headers = signup(client, platform_repo, hospital_db)
    assert upload(client, headers, b"").status_code == 422
    assert upload(client, headers, kind="selfie").status_code == 422
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    assert upload(client, headers, PDF).status_code == 413


def test_upload_requires_hospital_sign_in(client):
    res = client.post("/api/hospitals/me/documents", data={"kind": "other"}, files={"file": ("a.pdf", PDF)})
    assert res.status_code == 401


# ── admin ─────────────────────────────────────────────────────────

def test_admin_endpoints_need_admin_token(client, platform_repo, hospital_db):
    hid, headers = signup(client, platform_repo, hospital_db)
    assert client.get("/api/admin/hospitals").status_code == 401
    assert client.get("/api/admin/hospitals", headers=headers).status_code == 401  # hospital token is not enough
    donor = {"Authorization": "Bearer " + auth.create_access_token({"sub": "+919000000001", "role": "donor"})}
    assert client.get("/api/admin/hospitals", headers=donor).status_code == 401


def test_admin_login_disabled_without_config_and_rejects_bad_password(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "")
    assert client.post("/api/admin/token", data={"username": "a", "password": "b"}).status_code == 503
    monkeypatch.setattr(settings, "admin_username", "root")
    monkeypatch.setattr(settings, "admin_password_hash", bcrypt.hashpw(b"right", bcrypt.gensalt()).decode())
    assert client.post("/api/admin/token", data={"username": "root", "password": "wrong"}).status_code == 401


def test_admin_login_locks_after_repeated_failures(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "root")
    monkeypatch.setattr(settings, "admin_password_hash", bcrypt.hashpw(b"right", bcrypt.gensalt()).decode())
    for _ in range(10):
        client.post("/api/admin/token", data={"username": "root", "password": "wrong"})
    assert client.post("/api/admin/token", data={"username": "root", "password": "right"}).status_code == 429


def test_admin_lists_filters_and_shows_detail_with_audit(client, platform_repo, hospital_db, admin):
    hid, _ = signup(client, platform_repo, hospital_db)
    assert [h["id"] for h in client.get("/api/admin/hospitals?status=pending", headers=admin).json()["hospitals"]] == [hid]
    assert client.get("/api/admin/hospitals?status=approved", headers=admin).json()["hospitals"] == []
    assert client.get("/api/admin/hospitals?status=bogus", headers=admin).status_code == 422
    detail = client.get(f"/api/admin/hospitals/{hid}", headers=admin).json()
    assert detail["audit"][0]["action"] == "registered"
    assert "email_verification_hash" not in detail


def test_approval_needs_verified_email(client, platform_repo, hospital_db, admin):
    hid, _ = signup(client, platform_repo, hospital_db)
    res = client.post(f"/api/admin/hospitals/{hid}/decision", json={"action": "approve"}, headers=admin)
    assert res.status_code == 409
    verify(client, platform_repo)
    res = client.post(f"/api/admin/hospitals/{hid}/decision", json={"action": "approve"}, headers=admin)
    assert res.json() == {"id": hid, "status": "approved"}
    assert platform_repo.emails[-1][0] == "approve"
    assert platform_repo.audit[-1]["actor"] == "root"


def test_reject_and_suspend_need_a_reason_and_valid_transitions(client, platform_repo, hospital_db, admin):
    hid, _ = signup(client, platform_repo, hospital_db)
    url = f"/api/admin/hospitals/{hid}/decision"
    assert client.post(url, json={"action": "reject"}, headers=admin).status_code == 422
    assert client.post(url, json={"action": "suspend", "reason": "x"}, headers=admin).status_code == 409  # not approved yet
    assert client.post(url, json={"action": "explode"}, headers=admin).status_code == 422
    res = client.post(url, json={"action": "reject", "reason": "Licence unreadable"}, headers=admin)
    assert res.json()["status"] == "rejected"
    assert platform_repo.hospitals[hid]["decision_reason"] == "Licence unreadable"
    assert client.post(url, json={"action": "reject", "reason": "again"}, headers=admin).status_code == 409


def test_suspend_and_reinstate_round_trip(client, platform_repo, hospital_db, admin):
    hid, _ = signup(client, platform_repo, hospital_db)
    verify(client, platform_repo)
    url = f"/api/admin/hospitals/{hid}/decision"
    client.post(url, json={"action": "approve"}, headers=admin)
    assert client.post(url, json={"action": "suspend", "reason": "Misuse"}, headers=admin).json()["status"] == "suspended"
    assert client.post(url, json={"action": "reinstate"}, headers=admin).json()["status"] == "approved"
    assert [e["action"] for e in platform_repo.audit] == ["registered", "email_verified", "approve", "suspend", "reinstate"]


def test_admin_can_download_document_but_hospital_cannot(client, platform_repo, hospital_db, admin, uploads):
    hid, headers = signup(client, platform_repo, hospital_db)
    doc = upload(client, headers).json()
    url = f"/api/admin/hospitals/{hid}/documents/{doc['id']}"
    res = client.get(url, headers=admin)
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["content-type"] == "application/pdf"
    assert client.get(url, headers=headers).status_code == 401
    assert client.get(url).status_code == 401
    assert client.get(f"/api/admin/hospitals/{hid}/documents/nope", headers=admin).status_code == 404


def test_document_path_cannot_escape_upload_folder(uploads):
    storage = hp.LocalStorage(str(uploads))
    (uploads.parent / "secret.txt").write_text("x")
    assert storage.path("../secret.txt") is None


# ── dispatch gate ─────────────────────────────────────────────────

DISPATCH = {"hospital_id": "HOSP-1001", "blood_group": "O-", "units": 1, "urgency": "critical",
            "address": "Chennai", "coordinates": {"lat": 13.0, "lng": 80.2}}


@pytest.mark.parametrize("status", ["pending", "rejected", "suspended"])
def test_unapproved_hospital_cannot_dispatch(client, platform_repo, auth_headers, status):
    platform_repo.hospitals["HOSP-1001"] = {"id": "HOSP-1001", "status": status}
    res = client.post("/api/dispatch", json=DISPATCH, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == f"hospital_{status}"


@pytest.mark.asyncio
async def test_approved_and_legacy_hospitals_pass_the_gate(platform_repo):
    platform_repo.hospitals["HOSP-1001"] = {"id": "HOSP-1001", "status": "approved"}
    await api.ensure_hospital_approved("HOSP-1001")
    await api.ensure_hospital_approved("HOSP-LEGACY")  # no record or no status: legacy approved
    platform_repo.hospitals["HOSP-2"] = {"id": "HOSP-2", "name": "Old hospital"}
    await api.ensure_hospital_approved("HOSP-2")
