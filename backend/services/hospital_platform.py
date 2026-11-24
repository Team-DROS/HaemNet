"""Hospital verification platform: statuses, profile, documents, audit log.

Status lifecycle: pending -> approved | rejected; approved -> suspended ->
approved. Only approved hospitals can send dispatches (each one places real
calls). A hospital record with no `status` is a legacy or demo hospital that
existed before verification and counts as approved.

Storage is MongoDB (the default data layer). With DB_BACKEND=neo4j the
verification endpoints answer 501 and registration keeps the old behaviour.
Licence files are stored privately through `file_storage`: local disk by default,
or an S3 or R2 bucket when S3_BUCKET is set (needed on hosts that wipe the disk).
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.services.email_service import send_verification_email
from backend.services.errors import BadRequestError

logger = logging.getLogger(__name__)

PENDING, APPROVED, REJECTED, SUSPENDED = "pending", "approved", "rejected", "suspended"
STATUSES = (PENDING, APPROVED, REJECTED, SUSPENDED)
DOC_KINDS = ("hfr_certificate", "establishment_registration", "blood_centre_licence", "other")
MAX_DOCS = 8
VERIFY_TOKEN_HOURS = 48

# Allowed uploads, checked by file signature, never by the client's claim.
_SIGNATURES = (
    (b"%PDF-", "pdf", "application/pdf"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value or "")) and len(value) <= 254


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HospitalNotApproved(Exception):  # noqa: N818  (a domain condition, not a fault)
    """The hospital exists but may not place calls yet. `status` says why."""

    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


def hospital_status(hospital: Optional[dict]) -> str:
    """Status of a hospital record; missing status means a legacy approved one."""
    return (hospital or {}).get("status") or APPROVED


def detect_file_type(data: bytes) -> Optional[tuple]:
    for magic, ext, mime in _SIGNATURES:
        if data.startswith(magic):
            return ext, mime
    return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_verification_token() -> tuple[str, str, str]:
    """(plain token for the email, hash to store, expiry ISO time)."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=VERIFY_TOKEN_HOURS)).isoformat()
    return token, hash_token(token), expires


# ── file storage ──────────────────────────────────────────────────
# Documents go through backend.services.file_storage (local disk or S3/R2).

from backend.services.file_storage import LocalStorage, get_storage  # noqa: E402,F401

# ── repositories ──────────────────────────────────────────────────

class MongoPlatformRepo:
    def _col(self):
        from backend.db_services.mongodb import get_database
        return get_database()["hospitals"]

    @staticmethod
    def _out(doc):
        if not doc:
            return None
        out = dict(doc)
        out["id"] = out.pop("_id")
        return out

    async def get(self, hospital_id: str) -> Optional[dict]:
        return self._out(await self._col().find_one({"_id": hospital_id}))

    async def update(self, hospital_id: str, fields: Dict[str, Any]) -> None:
        await self._col().update_one({"_id": hospital_id}, {"$set": fields})

    async def push_document(self, hospital_id: str, document: dict) -> None:
        await self._col().update_one({"_id": hospital_id}, {"$push": {"documents": document}})

    async def find_by_token_hash(self, token_hash: str) -> Optional[dict]:
        return self._out(await self._col().find_one({"email_verification_hash": token_hash}))

    async def list(self, status: Optional[str], limit: int = 50, offset: int = 0) -> tuple[List[dict], int]:
        query = {"status": status} if status else {}
        total = await self._col().count_documents(query)
        cursor = self._col().find(query).sort("registered_at", -1).skip(offset).limit(limit)
        return [self._out(d) async for d in cursor], total

    async def delete(self, hospital_id: str) -> None:
        await self._col().delete_one({"_id": hospital_id})

    async def add_audit(self, entry: dict) -> None:
        from backend.db_services.mongodb import get_database
        await get_database()["hospital_audit"].insert_one(dict(entry))

    async def audit_for(self, hospital_id: str) -> List[dict]:
        from backend.db_services.mongodb import get_database
        cursor = get_database()["hospital_audit"].find({"hospital_id": hospital_id}, {"_id": 0}).sort("at", -1).limit(100)
        return [d async for d in cursor]


class MemoryPlatformRepo:
    """In-memory stand-in used by the tests."""

    def __init__(self):
        self.hospitals: Dict[str, dict] = {}
        self.audit: List[dict] = []

    async def get(self, hospital_id):
        h = self.hospitals.get(hospital_id)
        return dict(h) if h else None

    async def update(self, hospital_id, fields):
        self.hospitals.setdefault(hospital_id, {"id": hospital_id}).update(fields)

    async def push_document(self, hospital_id, document):
        self.hospitals.setdefault(hospital_id, {"id": hospital_id}).setdefault("documents", []).append(document)

    async def find_by_token_hash(self, token_hash):
        for h in self.hospitals.values():
            if h.get("email_verification_hash") == token_hash:
                return dict(h)
        return None

    async def list(self, status, limit=50, offset=0):
        rows = [dict(h) for h in self.hospitals.values() if not status or h.get("status") == status]
        rows = sorted(rows, key=lambda h: h.get("registered_at") or "", reverse=True)
        return rows[offset:offset + limit], len(rows)

    async def delete(self, hospital_id):
        self.hospitals.pop(hospital_id, None)

    async def add_audit(self, entry):
        self.audit.append(dict(entry))

    async def audit_for(self, hospital_id):
        return [e for e in reversed(self.audit) if e["hospital_id"] == hospital_id]


repo: Any = MongoPlatformRepo()


def platform_available() -> bool:
    return settings.db_backend == "mongodb"


async def assert_approved(hospital_id: str) -> None:
    """Raise HospitalNotApproved unless this hospital may send requests (each one places real calls)."""
    if not platform_available():
        return
    status = hospital_status(await repo.get(hospital_id))
    if status != APPROVED:
        raise HospitalNotApproved(status)


async def audit(hospital_id: str, actor: str, action: str, detail: str = "") -> None:
    """Best-effort audit entry. A logging problem must never block an emergency request."""
    if not platform_available():
        return
    try:
        await repo.add_audit({"hospital_id": hospital_id, "actor": actor, "action": action, "reason": detail, "at": now_iso()})
    except Exception as exc:
        logger.error("Audit write failed for %s (%s): %s", hospital_id, action, type(exc).__name__)


# ── public (client-safe) shapes ───────────────────────────────────

def public_document(doc: dict) -> dict:
    return {k: doc.get(k) for k in ("id", "kind", "filename", "content_type", "size", "uploaded_at")}


def hospital_profile(h: dict) -> dict:
    """What a hospital may see about itself. Never the hash, token or file paths."""
    return {
        "id": h.get("id"), "name": h.get("name"), "location": h.get("location"), "phone": h.get("phone"),
        "status": hospital_status(h),
        "email_verified": bool(h.get("email_verified", True)),
        "official_email": h.get("official_email"),
        "contact_person": h.get("contact_person"),
        "hfr_id": h.get("hfr_id"), "registration_number": h.get("registration_number"),
        "blood_centre_licence": h.get("blood_centre_licence"),
        "decision_reason": h.get("decision_reason"),
        "documents": [public_document(d) for d in h.get("documents", [])],
    }


def admin_summary(h: dict) -> dict:
    p = hospital_profile(h)
    p["registered_at"] = h.get("registered_at")
    p["decided_at"] = h.get("decided_at")
    return p


# ── registration and email verification ───────────────────────────

async def record(hospital_id: str, actor: str, action: str, detail: str = "") -> None:
    """Write an audit entry. Failures propagate: account changes must not go unrecorded."""
    await repo.add_audit({"hospital_id": hospital_id, "actor": actor, "action": action, "reason": detail, "at": now_iso()})


async def register_pending(hospital_id: str, name: str, profile: dict) -> None:
    """Mark a freshly created hospital as pending review and email it the verification link."""
    if not platform_available():
        return
    token, token_hash, expires = new_verification_token()
    await repo.update(hospital_id, {
        "status": PENDING, "email_verified": False, "registered_at": now_iso(),
        "email_verification_hash": token_hash, "email_verification_expires": expires,
        "documents": [], **profile,
    })
    await record(hospital_id, "hospital", "registered")
    await send_verification_email(profile["official_email"], name, token)


async def verify_email(token: str) -> None:
    """Confirm the official email from the link's token. Raises InvalidInputError if it is bad or expired."""
    hospital = await repo.find_by_token_hash(hash_token(token))
    expires = (hospital or {}).get("email_verification_expires") or ""
    if not hospital or expires < now_iso():
        raise BadRequestError("This verification link is invalid or has expired. Request a new one.")
    await repo.update(hospital["id"], {
        "email_verified": True, "email_verification_hash": None, "email_verification_expires": None,
    })
    await record(hospital["id"], "hospital", "email_verified")


async def resend_verification(hospital: dict) -> bool:
    """Issue a fresh link. Returns whether the email could be sent."""
    token, token_hash, expires = new_verification_token()
    await repo.update(hospital["id"], {"email_verification_hash": token_hash, "email_verification_expires": expires})
    return await send_verification_email(hospital["official_email"], hospital.get("name", ""), token)
