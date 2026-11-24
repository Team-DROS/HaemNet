"""Hospital sign-up follow-up (email verification, documents) and the admin review API."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from backend.api.auth import (
    ROLE_ADMIN, ROLE_HOSPITAL, create_access_token, get_current_admin, get_current_hospital,
    get_current_hospital_admin, get_password_hash, public_hospital, verify_password,
)
from backend.config import settings
from backend.services import hospital_platform as hp
from backend.services.email_service import send_decision_email, send_verification_email
from backend.services.rate_limit import SlidingWindowLimiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["hospital-platform"])

_admin_failures = SlidingWindowLimiter(max_events=10, window_seconds=15 * 60)
_resend_limit = SlidingWindowLimiter(max_events=3, window_seconds=3600)
_verify_limit = SlidingWindowLimiter(max_events=20, window_seconds=3600)
_upload_limit = SlidingWindowLimiter(max_events=20, window_seconds=3600)
_staff_failures = SlidingWindowLimiter(max_events=10, window_seconds=15 * 60)
MAX_STAFF = 20
STAFF_ROLES = ("admin", "staff")


def _require_platform() -> None:
    if not hp.platform_available():
        raise HTTPException(status_code=501, detail="Hospital verification needs the MongoDB data layer")


async def _load(hospital_id: str) -> dict:
    hospital = await hp.repo.get(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return hospital


async def ensure_hospital_approved(hospital_id: str) -> None:
    """403 unless the hospital is approved. Used before anything that places calls."""
    status = hp.hospital_status(await hp.repo.get(hospital_id)) if hp.platform_available() else hp.APPROVED
    if status != hp.APPROVED:
        raise HTTPException(status_code=403, detail={
            "code": f"hospital_{status}",
            "message": "Your hospital is not approved to send requests yet." if status == hp.PENDING
            else f"Your hospital account is {status}. Contact HaemNet support.",
        })


async def begin_registration(hospital_id: str, name: str, profile: dict) -> None:
    """Mark a freshly created hospital as pending and email the verification link."""
    if not hp.platform_available():
        return
    token, token_hash, expires = hp.new_verification_token()
    await hp.repo.update(hospital_id, {
        "status": hp.PENDING, "email_verified": False, "registered_at": hp.now_iso(),
        "email_verification_hash": token_hash, "email_verification_expires": expires,
        "documents": [], **profile,
    })
    await hp.repo.add_audit({"hospital_id": hospital_id, "actor": "hospital", "action": "registered", "reason": "", "at": hp.now_iso()})
    await send_verification_email(profile["official_email"], name, token)


# ── hospital: profile, email verification, documents ──────────────

@router.get("/api/hospitals/me")
async def my_profile(hospital_id: str = Depends(get_current_hospital)):
    _require_platform()
    return hp.hospital_profile(await _load(hospital_id))


class VerifyEmail(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/api/hospitals/verify-email")
async def verify_email(payload: VerifyEmail):
    """Public: the link in the email posts its token here."""
    _require_platform()
    if not _verify_limit.allowed("global"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    _verify_limit.hit("global")
    hospital = await hp.repo.find_by_token_hash(hp.hash_token(payload.token))
    expires = (hospital or {}).get("email_verification_expires") or ""
    if not hospital or expires < hp.now_iso():
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired. Request a new one.")
    await hp.repo.update(hospital["id"], {"email_verified": True, "email_verification_hash": None, "email_verification_expires": None})
    await hp.repo.add_audit({"hospital_id": hospital["id"], "actor": "hospital", "action": "email_verified", "reason": "", "at": hp.now_iso()})
    return {"verified": True}


@router.post("/api/hospitals/resend-verification")
async def resend_verification(hospital_id: str = Depends(get_current_hospital)):
    _require_platform()
    hospital = await _load(hospital_id)
    if hospital.get("email_verified", True):
        return {"sent": False, "detail": "Email is already verified"}
    if not _resend_limit.allowed(hospital_id):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in an hour.")
    _resend_limit.hit(hospital_id)
    token, token_hash, expires = hp.new_verification_token()
    await hp.repo.update(hospital_id, {"email_verification_hash": token_hash, "email_verification_expires": expires})
    sent = await send_verification_email(hospital["official_email"], hospital.get("name", ""), token)
    return {"sent": sent}


@router.post("/api/hospitals/me/documents")
async def upload_document(
    kind: str = Form(...),
    file: UploadFile = File(...),
    hospital_id: str = Depends(get_current_hospital),
):
    _require_platform()
    if kind not in hp.DOC_KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of: {', '.join(hp.DOC_KINDS)}")
    if not _upload_limit.allowed(hospital_id):
        raise HTTPException(status_code=429, detail="Too many uploads. Try again later.")
    _upload_limit.hit(hospital_id)
    hospital = await _load(hospital_id)
    if len(hospital.get("documents", [])) >= hp.MAX_DOCS:
        raise HTTPException(status_code=409, detail=f"You can upload at most {hp.MAX_DOCS} documents")

    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"File is larger than {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty")
    detected = hp.detect_file_type(data)
    if not detected:
        raise HTTPException(status_code=415, detail="Only PDF, JPG or PNG files are accepted")
    ext, mime = detected

    doc_id = uuid.uuid4().hex
    key = hp.get_storage().save(hospital_id, ext, data)
    document = {
        "id": doc_id, "kind": kind, "key": key, "content_type": mime, "size": len(data),
        "filename": (file.filename or f"document.{ext}")[:120], "uploaded_at": hp.now_iso(),
    }
    await hp.repo.push_document(hospital_id, document)
    await hp.repo.add_audit({"hospital_id": hospital_id, "actor": "hospital", "action": "document_uploaded", "reason": kind, "at": hp.now_iso()})
    return hp.public_document(document)


# ── admin ─────────────────────────────────────────────────────────

@router.post("/api/admin/token")
async def admin_login(form: OAuth2PasswordRequestForm = Depends()):
    if not settings.admin_configured:
        raise HTTPException(status_code=503, detail="Admin sign-in is not configured")
    key = form.username.strip().lower()
    if not _admin_failures.allowed(key):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in a few minutes.",
                            headers={"Retry-After": str(_admin_failures.retry_after(key))})
    ok = form.username == settings.admin_username and verify_password(form.password, settings.admin_password_hash)
    if not ok:
        _admin_failures.hit(key)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    _admin_failures.reset(key)
    token = create_access_token({"sub": settings.admin_username, "role": ROLE_ADMIN}, expires_delta=timedelta(hours=8))
    return {"access_token": token, "token_type": "bearer"}


@router.get("/api/admin/hospitals")
async def admin_list(status: Optional[str] = None, admin: str = Depends(get_current_admin)):
    _require_platform()
    if status and status not in hp.STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(hp.STATUSES)}")
    rows = await hp.repo.list(status)
    return {"hospitals": [hp.admin_summary(h) for h in rows]}


@router.get("/api/admin/hospitals/{hospital_id}")
async def admin_detail(hospital_id: str, admin: str = Depends(get_current_admin)):
    _require_platform()
    hospital = await _load(hospital_id)
    return {**hp.admin_summary(hospital), "audit": await hp.repo.audit_for(hospital_id)}


@router.get("/api/admin/hospitals/{hospital_id}/documents/{doc_id}")
async def admin_document(hospital_id: str, doc_id: str, admin: str = Depends(get_current_admin)):
    _require_platform()
    hospital = await _load(hospital_id)
    doc = next((d for d in hospital.get("documents", []) if d["id"] == doc_id), None)
    path = hp.get_storage().path(doc["key"]) if doc else None
    if not doc or not path:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(path, media_type=doc["content_type"],
                        headers={"Content-Disposition": f'inline; filename="{doc["id"]}.{doc["key"].rsplit(".", 1)[-1]}"',
                                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


class Decision(BaseModel):
    action: str  # approve | reject | suspend | reinstate
    reason: str = Field(default="", max_length=500)


# action -> (statuses it may start from, resulting status)
_TRANSITIONS = {
    "approve": ({hp.PENDING, hp.REJECTED}, hp.APPROVED),
    "reject": ({hp.PENDING}, hp.REJECTED),
    "suspend": ({hp.APPROVED}, hp.SUSPENDED),
    "reinstate": ({hp.SUSPENDED}, hp.APPROVED),
}


@router.post("/api/admin/hospitals/{hospital_id}/decision")
async def admin_decide(hospital_id: str, payload: Decision, admin: str = Depends(get_current_admin)):
    _require_platform()
    rule = _TRANSITIONS.get(payload.action)
    if not rule:
        raise HTTPException(status_code=422, detail=f"action must be one of: {', '.join(_TRANSITIONS)}")
    allowed_from, new_status = rule
    hospital = await _load(hospital_id)
    current = hp.hospital_status(hospital)
    if current not in allowed_from:
        raise HTTPException(status_code=409, detail=f"Cannot {payload.action} a hospital that is {current}")
    reason = payload.reason.strip()
    if payload.action in ("reject", "suspend") and not reason:
        raise HTTPException(status_code=422, detail="A reason is required")
    if payload.action == "approve" and not hospital.get("email_verified", True):
        raise HTTPException(status_code=409, detail="The hospital has not verified its official email yet")

    await hp.repo.update(hospital_id, {"status": new_status, "decision_reason": reason or None, "decided_at": hp.now_iso()})
    await hp.repo.add_audit({"hospital_id": hospital_id, "actor": admin, "action": payload.action, "reason": reason, "at": hp.now_iso()})
    logger.info("Hospital %s: %s -> %s by admin", hospital_id, current, new_status)
    if hospital.get("official_email"):
        await send_decision_email(hospital["official_email"], hospital.get("name", ""), payload.action, reason)
    return {"id": hospital_id, "status": new_status}


# ── staff accounts ────────────────────────────────────────────────
#
# The hospital's own sign-in (hospital ID + password) is the owner account and
# can always manage staff. Each staff member signs in with hospital ID, their
# email and their own password, and is either `admin` (can manage staff) or
# `staff` (can raise and follow requests). Removing a member takes effect
# immediately because every staff request re-checks the account.

def _public_staff(m: dict) -> dict:
    return {k: m.get(k) for k in ("id", "name", "email", "role", "active", "created_at")}


class StaffCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    role: str = "staff"
    password: str = Field(min_length=8, max_length=72)


class StaffLogin(BaseModel):
    hospital_id: str
    email: str
    password: str


@router.get("/api/hospitals/me/staff")
async def list_staff(hospital_id: str = Depends(get_current_hospital_admin)):
    _require_platform()
    hospital = await _load(hospital_id)
    return {"staff": [_public_staff(m) for m in hospital.get("staff", []) if m.get("active", True)]}


@router.post("/api/hospitals/me/staff")
async def add_staff(payload: StaffCreate, hospital_id: str = Depends(get_current_hospital_admin)):
    _require_platform()
    email = payload.email.strip().lower()
    if not hp.valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if payload.role not in STAFF_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of: {', '.join(STAFF_ROLES)}")
    hospital = await _load(hospital_id)
    staff = list(hospital.get("staff", []))
    if len([m for m in staff if m.get("active", True)]) >= MAX_STAFF:
        raise HTTPException(status_code=409, detail=f"A hospital can have at most {MAX_STAFF} staff accounts")
    if any(m["email"] == email and m.get("active", True) for m in staff):
        raise HTTPException(status_code=409, detail="This email already has a staff account")
    member = {"id": f"STF-{uuid.uuid4().hex[:8]}", "name": payload.name.strip(), "email": email, "role": payload.role,
              "password_hash": get_password_hash(payload.password), "active": True, "created_at": hp.now_iso()}
    await hp.repo.update(hospital_id, {"staff": staff + [member]})
    await hp.repo.add_audit({"hospital_id": hospital_id, "actor": "hospital", "action": "staff_added", "reason": f"{email} ({payload.role})", "at": hp.now_iso()})
    return _public_staff(member)


@router.delete("/api/hospitals/me/staff/{staff_id}")
async def remove_staff(staff_id: str, hospital_id: str = Depends(get_current_hospital_admin)):
    _require_platform()
    hospital = await _load(hospital_id)
    staff = list(hospital.get("staff", []))
    member = next((m for m in staff if m["id"] == staff_id and m.get("active", True)), None)
    if not member:
        raise HTTPException(status_code=404, detail="Staff account not found")
    member["active"] = False
    await hp.repo.update(hospital_id, {"staff": staff})
    await hp.repo.add_audit({"hospital_id": hospital_id, "actor": "hospital", "action": "staff_removed", "reason": member["email"], "at": hp.now_iso()})
    return {"removed": staff_id}


@router.post("/api/auth/staff-token")
async def staff_login(payload: StaffLogin):
    _require_platform()
    hospital_id = payload.hospital_id.strip().upper()
    email = payload.email.strip().lower()
    key = f"{hospital_id}:{email}"
    if not _staff_failures.allowed(key):
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Try again in a few minutes.",
                            headers={"Retry-After": str(_staff_failures.retry_after(key))})
    hospital = await hp.repo.get(hospital_id)
    member = next((m for m in (hospital or {}).get("staff", []) if m["email"] == email and m.get("active", True)), None)
    if not member or not verify_password(payload.password, member["password_hash"]):
        _staff_failures.hit(key)
        raise HTTPException(status_code=401, detail="Incorrect hospital ID, email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    _staff_failures.reset(key)
    token = create_access_token(
        {"sub": hospital_id, "role": ROLE_HOSPITAL, "staff_id": member["id"], "staff_role": member["role"]},
        expires_delta=timedelta(hours=24))
    user = public_hospital(hospital)
    user["staff"] = {"id": member["id"], "name": member["name"], "role": member["role"]}
    return {"access_token": token, "token_type": "bearer", "user": user}
