"""Shared helpers for tests of hospital sign-up, staff, documents and admin review."""

from backend.api import auth

PDF = b"%PDF-1.4 test file"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

SIGNUP = {
    "name": "Apollo",
    "location": "Chennai",
    "phone": "+919876543210",
    "password": "pw12345",
    "official_email": "Admin@Apollo.example",
    "contact_person": "Dr Rao",
    "hfr_id": "IN123",
}
STAFF = {"name": "Nurse Devi", "email": "Devi@Apollo.example", "role": "staff", "password": "staffpass1"}


def signup(client, platform_repo, hospital_db, **overrides):
    """Register a hospital through the API. Returns (hospital ID, owner auth headers)."""
    res = client.post("/api/auth/register", json={**SIGNUP, **overrides})
    assert res.status_code == 200, res.text
    hospital_id = res.json()["id"]
    # the fake auth table and the platform table are separate stores in tests
    hospital_db[hospital_id].update(platform_repo.hospitals[hospital_id])
    hospital_db[hospital_id]["id"] = hospital_id
    token = auth.create_access_token({"sub": hospital_id, "role": "hospital"})
    return hospital_id, {"Authorization": f"Bearer {token}"}


def verify(client, platform_repo):
    """Follow the most recent verification email's link."""
    token = [e for e in platform_repo.emails if e[0] == "verify"][-1][2]
    return client.post("/api/hospitals/verify-email", json={"token": token})


def upload(client, headers, data=PDF, name="licence.pdf", kind="hfr_certificate"):
    return client.post(
        "/api/hospitals/me/documents",
        headers=headers,
        data={"kind": kind},
        files={"file": (name, data, "application/octet-stream")},
    )


def add_staff(client, headers, **overrides):
    return client.post("/api/hospitals/me/staff", headers=headers, json={**STAFF, **overrides})


def staff_login(client, hospital_id, email="devi@apollo.example", password="staffpass1"):
    return client.post("/api/auth/staff-token", json={"hospital_id": hospital_id, "email": email, "password": password})
