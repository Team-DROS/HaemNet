"""A hospital's own account: profile, email verification, documents, data export and deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from backend.api.auth import get_current_hospital, get_current_hospital_admin
from backend.api.dependencies import load_hospital, require_platform
from backend.services import hospital_account, hospital_documents
from backend.services import hospital_platform as hp
from backend.services.rate_limit import Limiter, enforce

router = APIRouter(prefix="/api/hospitals", tags=["hospital-account"], dependencies=[Depends(require_platform)])

_resend_limit = Limiter("verify_resend", max_events=3, window_seconds=3600)
_verify_limit = Limiter("verify_email", max_events=20, window_seconds=3600)
_upload_limit = Limiter("doc_upload", max_events=20, window_seconds=3600)


@router.get("/me")
async def my_profile(hospital_id: str = Depends(get_current_hospital)):
    return hp.hospital_profile(await load_hospital(hospital_id))


class VerifyEmail(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/verify-email")
async def verify_email(payload: VerifyEmail):
    """Public: the link in the email posts its token here."""
    await enforce(_verify_limit, "global", "Too many attempts. Try again later.")
    await hp.verify_email(payload.token)
    return {"verified": True}


@router.post("/resend-verification")
async def resend_verification(hospital_id: str = Depends(get_current_hospital)):
    hospital = await load_hospital(hospital_id)
    if hospital.get("email_verified", True):
        return {"sent": False, "detail": "Email is already verified"}
    await enforce(_resend_limit, hospital_id, "Too many requests. Try again in an hour.")
    return {"sent": await hp.resend_verification(hospital)}


@router.post("/me/documents")
async def upload_document(
    kind: str = Form(...),
    file: UploadFile = File(...),
    hospital_id: str = Depends(get_current_hospital),
):
    await enforce(_upload_limit, hospital_id, "Too many uploads. Try again later.")
    # Read one byte past the limit so an oversized file is detected without loading all of it.
    data = await file.read(hospital_documents.max_upload_bytes() + 1)
    return await hospital_documents.store_document(hospital_id, kind, file.filename, data)


@router.get("/me/export")
async def export_my_data(hospital_id: str = Depends(get_current_hospital_admin)):
    """Everything we hold about this hospital's account, as JSON. Never secrets."""
    return await hospital_account.export_account(hospital_id)


class DeleteAccount(BaseModel):
    confirm_id: str


@router.post("/me/delete")
async def delete_my_account(payload: DeleteAccount, hospital_id: str = Depends(get_current_hospital_admin)):
    """Permanently delete this hospital, its staff logins and uploaded documents."""
    await hospital_account.delete_account(hospital_id, payload.confirm_id)
    return {"deleted": hospital_id}
