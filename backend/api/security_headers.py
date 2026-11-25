"""
Baseline HTTP security headers for every API response.

The API serves JSON, TwiML and the interactive docs, never HTML pages of its
own, so it can safely forbid framing and MIME sniffing. HSTS is only sent
outside development, where the API is always behind HTTPS.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.config import settings

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
HSTS = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.app_env.lower() in {"production", "staging"}:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response
