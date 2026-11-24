"""Staff accounts under a hospital: the owner login manages them, each member signs in separately.

A member is `admin` (can manage staff) or `staff` (can raise and follow requests). Removing a member
takes effect at once because every staff request re-checks that the account is still active.
"""

from __future__ import annotations

import uuid

from backend.services import hospital_platform as hp
from backend.services.errors import ConflictError, InvalidInputError, NotFoundError, UnauthorizedError
from backend.services.passwords import get_password_hash, verify_password

MAX_STAFF = 20
ROLES = ("admin", "staff")


def public_staff(member: dict) -> dict:
    """A staff record without its password hash."""
    return {k: member.get(k) for k in ("id", "name", "email", "role", "active", "created_at")}


def _active(staff: list[dict]) -> list[dict]:
    return [m for m in staff if m.get("active", True)]


async def _hospital(hospital_id: str) -> dict:
    hospital = await hp.repo.get(hospital_id)
    if not hospital:
        raise NotFoundError("Hospital not found")
    return hospital


async def list_staff(hospital_id: str) -> list[dict]:
    hospital = await _hospital(hospital_id)
    return [public_staff(m) for m in _active(hospital.get("staff", []))]


async def add_staff(hospital_id: str, name: str, email: str, role: str, password: str) -> dict:
    email = email.strip().lower()
    if not hp.valid_email(email):
        raise InvalidInputError("Enter a valid email address")
    if role not in ROLES:
        raise InvalidInputError(f"role must be one of: {', '.join(ROLES)}")
    hospital = await _hospital(hospital_id)
    staff = list(hospital.get("staff", []))
    if len(_active(staff)) >= MAX_STAFF:
        raise ConflictError(f"A hospital can have at most {MAX_STAFF} staff accounts")
    if any(m["email"] == email for m in _active(staff)):
        raise ConflictError("This email already has a staff account")
    member = {
        "id": f"STF-{uuid.uuid4().hex[:8]}", "name": name.strip(), "email": email, "role": role,
        "password_hash": get_password_hash(password), "active": True, "created_at": hp.now_iso(),
    }
    await hp.repo.update(hospital_id, {"staff": [*staff, member]})
    await hp.record(hospital_id, "hospital", "staff_added", f"{email} ({role})")
    return public_staff(member)


async def remove_staff(hospital_id: str, staff_id: str) -> None:
    hospital = await _hospital(hospital_id)
    staff = list(hospital.get("staff", []))
    member = next((m for m in _active(staff) if m["id"] == staff_id), None)
    if member is None:
        raise NotFoundError("Staff account not found")
    member["active"] = False
    await hp.repo.update(hospital_id, {"staff": staff})
    await hp.record(hospital_id, "hospital", "staff_removed", member["email"])


async def authenticate(hospital_id: str, email: str, password: str) -> tuple[dict, dict]:
    """The hospital and staff member for valid credentials, else UnauthorizedError."""
    hospital = await hp.repo.get(hospital_id)
    member = next((m for m in _active((hospital or {}).get("staff", [])) if m["email"] == email), None)
    if member is None or not verify_password(password, member["password_hash"]):
        raise UnauthorizedError("Incorrect hospital ID, email or password")
    return hospital, member
