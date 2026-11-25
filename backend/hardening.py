"""API hardening: security headers and a request size limit.

Unexpected errors become a safe 500 with the request ID in `observability.RequestIdMiddleware`."""

from __future__ import annotations

import json
import logging

from backend.config import settings

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/api/hospitals/me/documents"
_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]


class SecurityMiddleware:
    """Adds standard security headers and rejects oversized bodies before they are read.

    Uploads get MAX_UPLOAD_MB (plus form overhead); every other request is limited to
    MAX_REQUEST_BODY_KB. The check uses Content-Length; reverse proxies should also cap bodies.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        limit = (
            (settings.max_upload_mb * 1024 * 1024 + 64 * 1024)
            if scope["path"] == UPLOAD_PATH
            else settings.max_request_body_kb * 1024
        )
        try:
            length = int(headers.get(b"content-length", b"0") or 0)
        except ValueError:
            length = 0
        secure = scope.get("scheme") == "https" or settings.app_env.lower() in {"production", "staging"}

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [h for h in _HEADERS if h[0] not in existing]
                if secure and b"strict-transport-security" not in existing:
                    extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        if length > limit:
            body = json.dumps({"detail": "Request body too large"}).encode()
            await send_with_headers(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send_with_headers({"type": "http.response.body", "body": body})
        else:
            await self.app(scope, receive, send_with_headers)
