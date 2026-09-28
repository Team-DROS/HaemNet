"""
One-time passcodes for donor sign-in (sent by email).

A code is issued for a (phone, email) pair: the key is built by `login_key`,
so a code emailed for one pairing cannot sign in with a different one.

Codes are 6 digits, valid for 5 minutes, allow 5 guesses, and are stored
only as an HMAC (keyed with JWT_SECRET) so a memory dump does not reveal
live codes. State is in-process; see rate_limit.py for the multi-instance note.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from typing import Dict, Optional

from backend.config import settings
from backend.services.rate_limit import SlidingWindowLimiter

CODE_TTL_SECONDS = 5 * 60
MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 30

# At most 5 codes per key (phone + email) per hour, and at most 8 emails
# per address per hour however many numbers ask, so the endpoint cannot be
# used to flood someone's inbox.
_hourly = SlidingWindowLimiter(max_events=5, window_seconds=3600)
_per_email = SlidingWindowLimiter(max_events=8, window_seconds=3600)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


class OtpError(Exception):
    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class _Pending:
    digest: str
    expires_at: float
    sent_at: float
    attempts: int = 0


_pending: Dict[str, _Pending] = {}


def normalise_phone(raw: str) -> Optional[str]:
    """
    Return the number in E.164 form, or None if it is not plausible.
    Ten bare digits are treated as an Indian mobile number.
    """
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return f"+{digits}" if 10 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return None


def normalise_email(raw: str) -> Optional[str]:
    """Lower-cased address, or None if it does not look like an email."""
    email = (raw or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return None
    return email


def login_key(phone: str, email: str) -> str:
    return f"{phone}|{email}"


def check_email_quota(email: str, now: Optional[float] = None) -> None:
    """Raise OtpError when this address has received too many codes."""
    now = time.monotonic() if now is None else now
    if not _per_email.allowed(email, now):
        raise OtpError("Too many codes sent to this email. Try again later.",
                       retry_after=_per_email.retry_after(email, now))
    _per_email.hit(email, now)


def _digest(phone: str, code: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_code(phone: str, now: Optional[float] = None) -> str:
    """Create a fresh code for `phone`, enforcing resend and hourly limits."""
    now = time.monotonic() if now is None else now
    current = _pending.get(phone)
    if current and now - current.sent_at < RESEND_COOLDOWN_SECONDS:
        raise OtpError("Wait a moment before requesting another code.",
                       retry_after=int(RESEND_COOLDOWN_SECONDS - (now - current.sent_at)) + 1)
    if not _hourly.allowed(phone, now):
        raise OtpError("Too many codes requested. Try again later.", retry_after=_hourly.retry_after(phone, now))

    code = f"{secrets.randbelow(1_000_000):06d}"
    _pending[phone] = _Pending(digest=_digest(phone, code), expires_at=now + CODE_TTL_SECONDS, sent_at=now)
    _hourly.hit(phone, now)
    return code


def verify_code(phone: str, code: str, now: Optional[float] = None) -> bool:
    """Check a code. A correct code is consumed; five wrong guesses burn it."""
    now = time.monotonic() if now is None else now
    pending = _pending.get(phone)
    if pending is None or now > pending.expires_at:
        _pending.pop(phone, None)
        return False
    pending.attempts += 1
    if hmac.compare_digest(pending.digest, _digest(phone, (code or "").strip())):
        _pending.pop(phone, None)
        return True
    if pending.attempts >= MAX_ATTEMPTS:
        _pending.pop(phone, None)
    return False


def reset() -> None:
    """Forget every pending code (used by tests)."""
    _pending.clear()
    _hourly.clear()
    _per_email.clear()
