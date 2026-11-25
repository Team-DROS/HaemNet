"""
Twilio webhook authentication.

Twilio signs every webhook with HMAC-SHA1 over the full URL it requested
plus the POSTed form fields, keyed by the account auth token, and sends the
result in the X-Twilio-Signature header. Without this check anyone who
knows a dispatch ID could POST to /api/twilio/gather and mark a donor as
accepted.

The URL is rebuilt from SERVER_BASE_URL rather than from the incoming
request, because behind a TLS-terminating proxy (Render, Docker) the app
sees an internal http:// address that Twilio never signed.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from twilio.request_validator import RequestValidator

from backend.config import settings

logger = logging.getLogger(__name__)


def signed_url(request: Request) -> str:
    """The public URL Twilio called, as it appears in the signature."""
    url = settings.server_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    return url


async def verify_twilio_request(request: Request) -> None:
    """FastAPI dependency: reject webhooks that Twilio did not sign."""
    if not settings.twilio_signature_required:
        return
    if not settings.twilio_auth_token:
        logger.error("Twilio webhook received but TWILIO_AUTH_TOKEN is not set")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook not accepted")

    params: dict = {}
    if request.method == "POST":
        form = await request.form()  # Starlette caches this for the endpoint's Form() params
        params = {key: value for key, value in form.items()}

    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(settings.twilio_auth_token)
    if not signature or not validator.validate(signed_url(request), params, signature):
        logger.warning("Rejected unsigned or forged Twilio webhook to %s", request.url.path)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")
