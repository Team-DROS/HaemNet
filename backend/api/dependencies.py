"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from backend.api.auth import get_current_hospital
from backend.services import hospital_platform as hp


async def approved_hospital(hospital_id: str = Depends(get_current_hospital)) -> str:
    """The signed-in hospital's ID, or 403 unless it is approved to send requests."""
    try:
        await hp.assert_approved(hospital_id)
    except hp.HospitalNotApproved as exc:
        raise HTTPException(status_code=403, detail={
            "code": f"hospital_{exc.status}",
            "message": "Your hospital is not approved to send requests yet." if exc.status == hp.PENDING
            else f"Your hospital account is {exc.status}. Contact HaemNet support.",
        }) from exc
    return hospital_id


async def require_platform() -> None:
    """Hospital verification needs the MongoDB data layer; answer 501 on the Neo4j one."""
    if not hp.platform_available():
        raise HTTPException(status_code=501, detail="Hospital verification needs the MongoDB data layer")


async def load_hospital(hospital_id: str) -> dict:
    """The hospital record, or 404."""
    hospital = await hp.repo.get(hospital_id)
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return hospital
