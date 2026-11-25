"""
Expo Push Notification service.

Sends push notifications to donors who have the native mobile app
installed (``has_app: true``).  Used by the routing logic after a
donor verbally accepts via the AI voice call.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Lazily initialise the shared httpx client for Expo push."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=15.0,
            headers={"Content-Type": "application/json"},
        )
    return _client


async def send_push_notification(
    expo_token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    channel_id: str = "emergency-requests",
) -> Dict[str, Any]:
    """
    Send a push notification to a single Expo device.

    Parameters
    ----------
    expo_token : str
        The Expo push token (``ExponentPushToken[...]``).
    title : str
        Notification title.
    body : str
        Notification body text.
    data : dict, optional
        Custom data payload (e.g. dispatch_id, hospital coordinates).

    Returns
    -------
    dict   Expo's push receipt response.
    """
    client = await _get_client()
    payload = {
        "to": expo_token,
        "title": title,
        "body": body,
        "sound": "default",
        "priority": "high",
        "data": data or {},
        # Android channel the donor app creates at start-up (high importance, sound).
        "channelId": channel_id,
    }

    try:
        resp = await client.post(settings.expo_push_url, json=payload)
        resp.raise_for_status()
        result = resp.json()
        # Never log the token itself: it addresses one donor's phone.
        logger.info("Push notification sent to token ending %s", expo_token[-4:].rstrip("]"))
        return result
    except httpx.HTTPStatusError as exc:
        logger.error("Expo push error: %s", exc.response.text)
        raise
    except httpx.RequestError as exc:
        logger.error("Expo push network error: %s", exc)
        raise


async def send_dispatch_notification(
    expo_token: str,
    dispatch_id: str,
    hospital_id: str,
    blood_group: str,
    hospital_lat: float,
    hospital_lng: float,
) -> Dict[str, Any]:
    """
    Convenience wrapper to send a dispatch acceptance notification
    to a donor's mobile app with all the context needed to open
    the map route.
    """
    return await send_push_notification(
        expo_token=expo_token,
        title="Thank you for saying yes",
        body="The hospital knows you are coming. Open HaemNet for directions.",
        data={
            "type": "dispatch_accepted",
            "dispatch_id": dispatch_id,
            "hospital_id": hospital_id,
            "blood_group": blood_group,
            "hospital_lat": hospital_lat,
            "hospital_lng": hospital_lng,
        },
    )


async def close() -> None:
    """Gracefully close the httpx client."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
