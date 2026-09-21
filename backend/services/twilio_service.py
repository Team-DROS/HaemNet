"""
Twilio telephony service.

Manages outbound call initiation, webhook handling, and SMS dispatch
via the Twilio API. All I/O is async (httpx).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from backend.config import settings
from backend.schemas.models import DonorNode

logger = logging.getLogger(__name__)

# Reuse a single async client across calls for connection pooling.
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Lazily initialise the shared httpx client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url="https://api.twilio.com/2010-04-01",
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=30.0,
        )
    return _client


async def initiate_call(
    donor: DonorNode,
    dispatch_id: str,
    callback_url: str,
) -> Dict[str, Any]:
    """
    Place a single outbound call to `donor.phone` via Twilio.
    """
    client = await _get_client()
    
    twiml_url = f"{settings.server_base_url}/api/twilio/twiml?dispatch_id={dispatch_id}&donor_id={donor.id}"
    status_cb = f"{settings.server_base_url}/api/twilio/status-callback?dispatch_id={dispatch_id}&donor_id={donor.id}"

    payload = {
        "To": donor.phone,
        "From": settings.twilio_phone_number,
        "Url": twiml_url,
        "StatusCallback": status_cb,
        # Ask for the answered event too, so the dashboard can show pickup
        # separately from the final outcome. httpx sends a list as repeated
        # form fields, which is what Twilio expects.
        "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
    }

    try:
        resp = await client.post(
            f"/Accounts/{settings.twilio_account_sid}/Calls.json",
            data=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("Call initiated to %s — SID %s", donor.phone, data.get("sid"))
        return data
    except httpx.HTTPStatusError as exc:
        logger.error("Twilio API error for %s: %s", donor.phone, exc.response.text)
        raise
    except httpx.RequestError as exc:
        logger.error("Network error calling %s: %s", donor.phone, exc)
        raise


async def initiate_bulk_calls(
    donors: List[DonorNode],
    dispatch_id: str,
    callback_url: str,
) -> List[Dict[str, Any]]:
    import asyncio

    tasks = [
        initiate_call(donor, dispatch_id, callback_url)
        for donor in donors
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes: List[Dict[str, Any]] = []
    for donor, result in zip(donors, results):
        if isinstance(result, Exception):
            logger.error("Failed to call donor %s: %s", donor.id, result)
        else:
            successes.append(result)
    return successes


async def send_sms(phone: str, message: str) -> Dict[str, Any]:
    client = await _get_client()
    payload = {
        "From": settings.twilio_phone_number,
        "To": phone,
        "Body": message,
    }

    try:
        resp = await client.post(
            f"/Accounts/{settings.twilio_account_sid}/Messages.json",
            data=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("SMS sent to %s", phone)
        return data
    except httpx.HTTPStatusError as exc:
        logger.error("Twilio SMS error for %s: %s", phone, exc.response.text)
        raise


async def close() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
