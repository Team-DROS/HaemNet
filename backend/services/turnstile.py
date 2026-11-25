"""Cloudflare Turnstile bot check for public forms.

Disabled (always passes) when TURNSTILE_SECRET is empty so development and
tests need no keys. When enabled, a missing or rejected token fails the form.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import HTTPException

from backend.config import settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_token(token: Optional[str], remote_ip: Optional[str] = None) -> bool:
    if not settings.turnstile_secret:
        return True
    if not token:
        return False
    data = {"secret": settings.turnstile_secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(VERIFY_URL, data=data)
            return bool(resp.json().get("success"))
    except Exception as exc:  # fail closed: if we cannot check, do not let the form through
        logger.error("Turnstile check failed: %s", type(exc).__name__)
        return False


async def require_human(token: Optional[str], remote_ip: Optional[str] = None) -> None:
    if not await verify_token(token, remote_ip):
        raise HTTPException(status_code=400, detail="Please complete the spam check and try again.")
