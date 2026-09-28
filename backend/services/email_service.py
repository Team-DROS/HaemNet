"""
Email delivery for donor sign-in codes.

Two providers, picked from configuration (see Settings.email_provider):

* brevo  HTTPS API (https://api.brevo.com/v3/smtp/email). Used in production:
         Render free instances block outbound SMTP ports 25, 465 and 587, but
         HTTPS works. Free plan: 300 emails a day, sender address verified
         once in the Brevo dashboard.
* smtp   Plain SMTP with STARTTLS (for example Gmail with an App Password).
         Handy locally; it will not work from a free Render instance.

The code itself is never logged. Recipient addresses are logged masked.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

_client: Optional[httpx.AsyncClient] = None


class EmailError(Exception):
    """The provider refused or could not be reached."""


def mask_email(email: str) -> str:
    """u***@gmail.com: enough for the donor to recognise, not to harvest."""
    local, _, domain = (email or "").partition("@")
    if not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    return _client


async def _send_brevo(to: str, subject: str, text: str, html: str) -> None:
    client = await _get_client()
    payload = {
        "sender": {"email": settings.email_from, "name": settings.email_from_name},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
        "htmlContent": html,
    }
    try:
        resp = await client.post(
            BREVO_URL,
            json=payload,
            headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise EmailError(f"Brevo unreachable: {exc.__class__.__name__}") from exc
    if resp.status_code >= 300:
        # Brevo's error body names the problem (unverified sender, bad key)
        # and never echoes the key, so it is safe to log.
        raise EmailError(f"Brevo HTTP {resp.status_code}: {resp.text[:200]}")


def _send_smtp_blocking(to: str, subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    msg["From"] = f"{settings.email_from_name} <{settings.email_from}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def send_email(to: str, subject: str, text: str, html: str) -> None:
    provider = settings.email_provider
    if provider == "brevo":
        await _send_brevo(to, subject, text, html)
    elif provider == "smtp":
        try:
            await asyncio.to_thread(_send_smtp_blocking, to, subject, text, html)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailError(f"SMTP failed: {exc.__class__.__name__}") from exc
    else:
        raise EmailError("Email is not configured")
    logger.info("Email sent to %s via %s", mask_email(to), provider)


async def send_sign_in_code(to: str, code: str, minutes: int) -> None:
    subject = f"{code} is your HaemNet sign-in code"
    text = (
        f"Your HaemNet sign-in code is {code}.\n\n"
        f"It expires in {minutes} minutes. Do not share it with anyone: "
        "HaemNet staff and hospitals will never ask for it.\n\n"
        "If you did not try to sign in, you can ignore this email."
    )
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:420px">'
        '<p>Your HaemNet sign-in code is</p>'
        f'<p style="font-size:28px;font-weight:bold;letter-spacing:6px">{code}</p>'
        f"<p>It expires in {minutes} minutes. Do not share it with anyone: "
        "HaemNet staff and hospitals will never ask for it.</p>"
        '<p style="color:#666">If you did not try to sign in, you can ignore this email.</p>'
        "</div>"
    )
    await send_email(to, subject, text, html)


async def close() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
