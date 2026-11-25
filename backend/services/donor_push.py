"""Push alerts for donors who have the app, and the rules for their Expo push tokens.

The automated call is always the primary channel. A push only puts the request on the
donor's screen sooner, so every function here is best-effort: a failed push is logged
and never stops a dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Mapping, Optional

from backend.config import settings
from backend.db_services import db_set_donor_push_token, get_donor_push_token
from backend.services.errors import InvalidInputError
from backend.services.push_service import send_push_notification

logger = logging.getLogger(__name__)

# Expo issues tokens shaped like ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx].
_EXPO_TOKEN = re.compile(r"^(?:ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]{8,200}\]$")


def is_expo_push_token(token: str) -> bool:
    return bool(_EXPO_TOKEN.match(token or ""))


def clean_push_token(token: Optional[str]) -> Optional[str]:
    """The token to store, or None to forget it. Rejects anything that is not an Expo token."""
    if token is None or not token.strip():
        return None
    token = token.strip()
    if not is_expo_push_token(token):
        raise InvalidInputError("That is not an Expo push token")
    return token


async def save_push_token(phone: str, token: Optional[str]) -> bool:
    """Store (or forget) this donor's push token. False if the donor has no profile yet."""
    return await db_set_donor_push_token(phone, clean_push_token(token))


def request_alert(blood_group: str, units: int, urgency: str, distance_km: Optional[float]) -> Dict[str, str]:
    """Title and body for a new-request alert. No hospital or patient details on the lock screen."""
    where = f"{distance_km:.1f} km from you" if distance_km is not None else "near you"
    title = f"{'Critical' if urgency == 'critical' else 'Urgent'}: {blood_group} blood needed"
    unit_text = f"{units} unit{'' if units == 1 else 's'}"
    return {"title": title, "body": f"A hospital {where} needs {unit_text}. Open HaemNet to answer."}


def device_not_registered(receipt: Mapping[str, Any]) -> bool:
    """True when Expo says the app was uninstalled or the token expired."""
    data = receipt.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, Mapping) or data.get("status") != "error":
        return False
    details = data.get("details") or {}
    return isinstance(details, Mapping) and details.get("error") == "DeviceNotRegistered"


async def _alert_one(dispatch_id: str, donor_id: str, donor: Mapping[str, Any], request: Mapping[str, Any]) -> bool:
    try:
        token = await get_donor_push_token(donor_id)
        if not token:
            return False
        message = request_alert(request["blood_group"], request["units"], request["urgency"], donor.get("distance_km"))
        receipt = await send_push_notification(
            expo_token=token,
            title=message["title"],
            body=message["body"],
            data={"type": "new_request", "dispatch_id": dispatch_id},
        )
        if device_not_registered(receipt):
            phone = donor.get("phone")
            if phone:
                await db_set_donor_push_token(str(phone), None)
            logger.info("Forgot an expired push token for donor %s", donor_id)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - a push must never break a dispatch
        logger.warning("Request alert to donor %s failed: %s", donor_id, type(exc).__name__)
        return False


async def alert_donors_of_request(
    dispatch_id: str,
    donors: Mapping[str, Mapping[str, Any]],
    blood_group: str,
    units: int,
    urgency: str,
) -> int:
    """Push a new-request alert to every matched donor who has the app. Returns how many were sent."""
    if not settings.push_request_alerts:
        return 0
    request = {"blood_group": blood_group, "units": units, "urgency": urgency}
    targets = [(donor_id, donor) for donor_id, donor in donors.items() if donor.get("has_app")]
    if not targets:
        return 0
    results = await asyncio.gather(*(_alert_one(dispatch_id, i, d, request) for i, d in targets))
    sent = sum(1 for ok in results if ok)
    logger.info("Sent %d of %d request alerts for dispatch %s", sent, len(targets), dispatch_id)
    return sent
