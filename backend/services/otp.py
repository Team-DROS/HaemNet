"""One-time codes that prove a donor owns a phone number.

A 6-digit code is sent by SMS through the telephony provider. Only a keyed hash of the code is
stored (never the code), it expires after OTP_TTL_SECONDS, works once, and at most OTP_MAX_ATTEMPTS
wrong guesses are allowed. Codes live in Redis when REDIS_URL is set; otherwise in process memory,
which only works on a single instance. The code is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from backend.config import settings
from backend.services import redis_client
from backend.services.errors import RateLimitedError, ServiceUnavailableError
from backend.services.rate_limit import Limiter
from backend.services.telephony import get_telephony

logger = logging.getLogger(__name__)

_memory: dict[str, tuple[str, float]] = {}  # phone -> (code digest, expires at)
_guesses = Limiter("otp_guesses", max_events=1, window_seconds=600)


def _now() -> float:
    return time.monotonic()


def _digest(phone: str, code: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _key(phone: str) -> str:
    return f"otp:{phone}"


async def _store(phone: str, digest: str) -> None:
    client = redis_client.get_redis()
    if client is None:
        _memory[phone] = (digest, _now() + settings.otp_ttl_seconds)
        return
    await client.set(_key(phone), digest, ex=settings.otp_ttl_seconds)


async def _load(phone: str) -> str | None:
    client = redis_client.get_redis()
    if client is None:
        entry = _memory.get(phone)
        if entry is None or entry[1] < _now():
            _memory.pop(phone, None)
            return None
        return entry[0]
    return await client.get(_key(phone))


async def _forget(phone: str) -> None:
    client = redis_client.get_redis()
    if client is None:
        _memory.pop(phone, None)
    else:
        await client.delete(_key(phone))


def generate_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


async def send_code(phone: str) -> None:
    """Create a fresh code (replacing any earlier one) and text it to the phone."""
    code = generate_code()
    try:
        await _store(phone, _digest(phone, code))
        await get_telephony().send_sms(
            phone, f"Your HaemNet verification code is {code}. It expires in {settings.otp_ttl_seconds // 60} minutes."
        )
    except Exception as exc:
        await _safe_forget(phone)
        logger.error("Could not send a verification code: %s", type(exc).__name__)
        raise ServiceUnavailableError("Could not send a verification code right now. Please try again.") from exc


async def _safe_forget(phone: str) -> None:
    try:
        await _forget(phone)
    except Exception:
        logger.debug("Could not clear a verification code", exc_info=True)


async def check_code(phone: str, code: str) -> bool:
    """True if `code` is the live code for this phone. A correct code is used up.

    Guesses are counted atomically, so a burst of simultaneous attempts cannot exceed the limit.
    """
    _guesses.max_events = settings.otp_max_attempts
    if not await _guesses.try_acquire(phone):
        raise RateLimitedError(
            "Too many wrong codes. Request a new code and try again.", await _guesses.retry_after(phone)
        )
    try:
        expected = await _load(phone)
    except Exception as exc:
        logger.error("Could not read a verification code: %s", type(exc).__name__)
        raise ServiceUnavailableError("Could not check the code right now. Please try again.") from exc
    if expected is None or not hmac.compare_digest(expected, _digest(phone, code.strip())):
        return False
    await _forget(phone)
    await _guesses.reset(phone)
    return True


def reset_for_tests() -> None:
    _memory.clear()
    _guesses.clear()
