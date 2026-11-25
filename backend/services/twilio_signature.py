"""Verify that webhook requests really come from Twilio (X-Twilio-Signature).

Without this, anyone who finds the callback URLs could POST a fake "accepted"
or "declined" for a donor. The signed URL is built from SERVER_BASE_URL because
behind a proxy the request's own host and scheme are not what Twilio called.

With no TWILIO_AUTH_TOKEN the check is skipped in development and fails closed
in staging and production.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, WebSocket
from twilio.request_validator import RequestValidator

from backend.config import settings

logger = logging.getLogger(__name__)


async def verify_twilio_request(request: Request) -> None:
    if not settings.twilio_auth_token:
        if settings.app_env.lower() in {"production", "staging"}:
            logger.error("Twilio webhook rejected: TWILIO_AUTH_TOKEN is not set")
            raise HTTPException(status_code=403, detail="Webhook verification is not configured")
        return

    signature = request.headers.get("X-Twilio-Signature", "")
    url = settings.server_base_url.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    params = {}
    if request.method == "POST":
        params = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}

    if not signature or not RequestValidator(settings.twilio_auth_token).validate(url, params, signature):
        logger.warning("Twilio webhook rejected: bad signature for %s", request.url.path)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


def verify_twilio_stream(websocket: WebSocket) -> bool:
    """Twilio signs the public upgrade URL. The proxy's internal host is irrelevant."""
    if not settings.twilio_auth_token:
        return settings.app_env.lower() not in {"production", "staging"}
    signature = websocket.headers.get("x-twilio-signature", "")
    if not signature:
        return False
    url = settings.server_base_url.rstrip("/") + websocket.url.path
    validator = RequestValidator(settings.twilio_auth_token)
    # Twilio's Voice WebSocket signing can include a trailing slash.
    return any(
        validator.validate(candidate, {}, signature)
        for base in (url, url.replace("http", "ws", 1))
        for candidate in (base, base.rstrip("/") + "/")
    )
