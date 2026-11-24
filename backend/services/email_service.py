"""Outgoing email for hospital verification and review decisions.

Uses SMTP when SMTP_HOST and SMTP_FROM are set. Otherwise nothing is sent and
a warning says so. Message bodies are never logged because they contain
single-use links.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from backend.config import settings

logger = logging.getLogger(__name__)


def _send_sync(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send one email. Returns False (never raises) when it could not be sent."""
    if not settings.smtp_configured:
        logger.warning("Email not sent (SMTP is not configured): %s", subject)
        return False
    try:
        await asyncio.to_thread(_send_sync, to, subject, body)
        return True
    except Exception as exc:  # network or auth failure must not break sign-up
        logger.error("Email send failed (%s): %s", subject, type(exc).__name__)
        return False


async def send_verification_email(to: str, hospital_name: str, token: str) -> bool:
    link = f"{settings.dashboard_url.rstrip('/')}/verify-email?token={token}"
    return await send_email(
        to,
        "Verify your hospital email for HaemNet",
        f"Hello,\n\nPlease confirm this address for {hospital_name} on HaemNet:\n{link}\n\n"
        "The link works once and expires in 48 hours. If you did not register, ignore this email.\n",
    )


async def send_decision_email(to: str, hospital_name: str, action: str, reason: str = "") -> bool:
    if action == "approve":
        subject, text = (
            "Your hospital is approved on HaemNet",
            (f"{hospital_name} has been approved. You can now sign in and send blood requests."),
        )
    elif action == "reject":
        subject, text = (
            "Your HaemNet registration was not approved",
            (
                f"We could not approve {hospital_name}.\nReason: {reason}\n"
                "You can fix the details, upload new documents and write to us to be reviewed again."
            ),
        )
    elif action == "suspend":
        subject, text = (
            "Your HaemNet account is suspended",
            (f"The account for {hospital_name} is suspended and cannot send requests.\nReason: {reason}"),
        )
    else:
        subject, text = "Your HaemNet account is active again", (f"The account for {hospital_name} is active again.")
    return await send_email(to, subject, text + "\n")
