"""A hospital's right to see and delete its own data (DPDP Act)."""

from __future__ import annotations

import logging

from backend.services import hospital_platform as hp
from backend.services.errors import InvalidInputError, NotFoundError, ServiceUnavailableError
from backend.services.file_storage import get_storage
from backend.services.hospital_staff import public_staff

logger = logging.getLogger(__name__)


async def export_account(hospital_id: str) -> dict:
    """Everything held about this hospital's account. Never password hashes, tokens or file paths."""
    hospital = await hp.repo.get(hospital_id)
    if not hospital:
        raise NotFoundError("Hospital not found")
    profile = hp.hospital_profile(hospital)
    profile["registered_at"] = hospital.get("registered_at")
    profile["staff"] = [public_staff(m) for m in hospital.get("staff", [])]
    return {"exported_at": hp.now_iso(), "hospital": profile, "audit": await hp.repo.audit_for(hospital_id)}


async def delete_account(hospital_id: str, confirm_id: str) -> None:
    """Permanently delete the hospital, its staff logins and uploaded documents.

    The caller must type the hospital ID. Past dispatch records are kept for audit and safety and are no
    longer linked to a login. If the documents cannot be removed the account is kept, so a retry is possible.
    """
    if confirm_id.strip().upper() != hospital_id:
        raise InvalidInputError("Type your hospital ID to confirm deletion")
    if not await hp.repo.get(hospital_id):
        raise NotFoundError("Hospital not found")
    try:
        await get_storage().delete_prefix(hospital_id)
    except Exception as exc:
        logger.error("Document deletion failed for %s: %s", hospital_id, type(exc).__name__)
        raise ServiceUnavailableError("Could not delete your documents right now. Please try again.") from exc
    await hp.record(hospital_id, "hospital", "account_deleted")
    await hp.repo.delete(hospital_id)
    logger.info("Hospital %s deleted its account", hospital_id)
