"""Admin panel API: review hospital registrations, open their documents, record decisions."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from backend.api.auth import ROLE_ADMIN, create_access_token, get_current_admin
from backend.api.dependencies import load_hospital, require_platform
from backend.config import settings
from backend.services import hospital_documents, hospital_review
from backend.services import hospital_platform as hp
from backend.services.errors import UnauthorizedError
from backend.services.passwords import verify_password
from backend.services.rate_limit import Limiter, enforce

router = APIRouter(prefix="/api/admin", tags=["admin"])

_admin_failures = Limiter("admin_login", max_events=10, window_seconds=15 * 60)
ADMIN_TOKEN_HOURS = 8


@router.post("/token")
async def admin_login(form: OAuth2PasswordRequestForm = Depends()):
    if not settings.admin_configured:
        raise HTTPException(status_code=503, detail="Admin sign-in is not configured")
    key = form.username.strip().lower()
    await enforce(_admin_failures, key, "Too many failed attempts. Try again in a few minutes.")
    valid = form.username == settings.admin_username and verify_password(form.password, settings.admin_password_hash)
    if not valid:
        raise UnauthorizedError("Incorrect username or password")
    await _admin_failures.reset(key)
    token = create_access_token(
        {"sub": settings.admin_username, "role": ROLE_ADMIN},
        expires_delta=timedelta(hours=ADMIN_TOKEN_HOURS),
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/hospitals", dependencies=[Depends(require_platform)])
async def list_hospitals(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: str = Depends(get_current_admin),
):
    if status and status not in hp.STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(hp.STATUSES)}")
    rows, total = await hp.repo.list(status, limit, offset)
    return {"hospitals": [hp.admin_summary(h) for h in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/hospitals/{hospital_id}", dependencies=[Depends(require_platform)])
async def hospital_detail(hospital_id: str, admin: str = Depends(get_current_admin)):
    hospital = await load_hospital(hospital_id)
    return {**hp.admin_summary(hospital), "audit": await hp.repo.audit_for(hospital_id)}


@router.get("/hospitals/{hospital_id}/documents/{doc_id}", dependencies=[Depends(require_platform)])
async def hospital_document(hospital_id: str, doc_id: str, admin: str = Depends(get_current_admin)):
    doc, content = await hospital_documents.read_document(hospital_id, doc_id)
    extension = doc["key"].rsplit(".", 1)[-1]
    return Response(
        content=content,
        media_type=doc["content_type"],
        headers={
            "Content-Disposition": f'inline; filename="{doc["id"]}.{extension}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


class Decision(BaseModel):
    action: str  # approve | reject | suspend | reinstate
    reason: str = Field(default="", max_length=500)


@router.post("/hospitals/{hospital_id}/decision", dependencies=[Depends(require_platform)])
async def decide(hospital_id: str, payload: Decision, admin: str = Depends(get_current_admin)):
    new_status = await hospital_review.decide(hospital_id, payload.action, payload.reason, admin)
    return {"id": hospital_id, "status": new_status}
