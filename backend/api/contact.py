"""Public contact form: bot check, rate limit, then an email to the support inbox."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.config import settings
from backend.services import hospital_platform as hp
from backend.services.email_service import send_email
from backend.services.rate_limit import Limiter
from backend.services.turnstile import require_human

router = APIRouter(tags=["contact"])

_per_ip = Limiter("contact_ip", max_events=5, window_seconds=3600)


class ContactMessage(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    message: str = Field(min_length=5, max_length=3000)
    turnstile_token: Optional[str] = None


def _clean(value: str) -> str:
    """No line breaks in header-like values."""
    return " ".join(value.split())


@router.post("/api/contact")
async def contact(payload: ContactMessage, request: Request):
    ip = request.client.host if request.client else "unknown"
    if not await _per_ip.allowed(ip):
        raise HTTPException(status_code=429, detail="Too many messages. Try again later.")
    if not hp.valid_email(payload.email.strip()):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    await require_human(payload.turnstile_token, ip)
    if not (settings.contact_to and settings.smtp_configured):
        raise HTTPException(status_code=503, detail="The contact form is not available. Please email us directly.")
    await _per_ip.hit(ip)
    body = f"From: {_clean(payload.name)} <{_clean(payload.email)}>\n\n{payload.message}\n"
    sent = await send_email(settings.contact_to, f"HaemNet contact: {_clean(payload.name)[:60]}", body)
    if not sent:
        raise HTTPException(status_code=503, detail="Could not send your message. Please email us directly.")
    return {"sent": True}
