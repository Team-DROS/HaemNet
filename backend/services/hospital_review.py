"""Admin review of hospital registrations: approve, reject, suspend, reinstate."""

from __future__ import annotations

import logging

from backend.services import hospital_platform as hp
from backend.services.email_service import send_decision_email
from backend.services.errors import ConflictError, InvalidInputError, NotFoundError

logger = logging.getLogger(__name__)

# action -> (statuses it may start from, resulting status)
TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "approve": ({hp.PENDING, hp.REJECTED}, hp.APPROVED),
    "reject": ({hp.PENDING}, hp.REJECTED),
    "suspend": ({hp.APPROVED}, hp.SUSPENDED),
    "reinstate": ({hp.SUSPENDED}, hp.APPROVED),
}


async def decide(hospital_id: str, action: str, reason: str, actor: str) -> str:
    """Apply an admin decision and return the hospital's new status.

    Rejecting or suspending needs a reason, and approval needs a verified email.
    The hospital is emailed and the decision is written to the audit trail.
    """
    rule = TRANSITIONS.get(action)
    if rule is None:
        raise InvalidInputError(f"action must be one of: {', '.join(TRANSITIONS)}")
    allowed_from, new_status = rule

    hospital = await hp.repo.get(hospital_id)
    if not hospital:
        raise NotFoundError("Hospital not found")
    current = hp.hospital_status(hospital)
    if current not in allowed_from:
        raise ConflictError(f"Cannot {action} a hospital that is {current}")

    reason = reason.strip()
    if action in ("reject", "suspend") and not reason:
        raise InvalidInputError("A reason is required")
    if action == "approve" and not hospital.get("email_verified", True):
        raise ConflictError("The hospital has not verified its official email yet")

    await hp.repo.update(hospital_id, {"status": new_status, "decision_reason": reason or None, "decided_at": hp.now_iso()})
    await hp.record(hospital_id, actor, action, reason)
    logger.info("Hospital %s: %s -> %s by admin", hospital_id, current, new_status)
    if hospital.get("official_email"):
        await send_decision_email(hospital["official_email"], hospital.get("name", ""), action, reason)
    return new_status
