"""Placing a call to one donor through the telephony provider. Shared by the first attempt and retries."""

from __future__ import annotations

import logging
from typing import Any

from backend.config import settings
from backend.dispatch_store import dispatch_store
from backend.schemas.models import CallStatus, DonorNode
from backend.services.call_pacer import wait_for_slot
from backend.services.error_reporting import report_exception
from backend.services.telephony import get_telephony

logger = logging.getLogger(__name__)


def status_callback_url() -> str:
    """Where the provider posts call status changes."""
    return f"{settings.server_base_url}/api/twilio/status-callback"


def donor_node_for_call(
    donor_id: str, donor_data: dict[str, Any], blood_group: str, lat: float, lng: float
) -> DonorNode:
    """A minimal donor record for the telephony provider, built from a dispatch's donor entry."""
    return DonorNode(
        id=donor_id,
        name=donor_data["name"],
        phone=donor_data["phone"],
        blood_group=blood_group,
        language=donor_data.get("language", "english"),
        location={"lat": lat, "lng": lng},
    )


async def place_call(donor_node: DonorNode, dispatch_id: str, donor_id: str, *, slot_reserved: bool = False) -> bool:
    """Start the call and remember its ID so webhooks can find the donor. Returns whether it started.

    Failures are logged and reported but never raised, so one bad number cannot stop a dispatch.
    A donor who could not be reached is shown as "no answer", not as having declined.
    """
    try:
        if not slot_reserved:
            await wait_for_slot()
        call_id = await get_telephony().start_call(donor_node, dispatch_id, status_callback_url())
        if call_id:
            await dispatch_store.register_call(call_id, dispatch_id, donor_id)
        return True
    except Exception as exc:
        report_exception(exc)
        logger.error("Failed to initiate call for donor %s in dispatch %s: %s", donor_id, dispatch_id, exc)
        await dispatch_store.update_donor_status(dispatch_id, donor_id, CallStatus.NO_ANSWER)
        return False
