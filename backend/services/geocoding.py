"""
OpenStreetMap (Nominatim) Geocoding Service.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


async def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """
    Convert a text address into GPS coordinates using Nominatim.

    Args:
        address: The text address (e.g. "MG Road, Bangalore, India")

    Returns:
        A tuple of (latitude, longitude) on success, or None if failed.
    """
    if not address or not address.strip():
        return None

    # Nominatim requires a descriptive User-Agent
    headers = {"User-Agent": "HaemNetApp/1.0 (contact@hackahazard.com)"}

    query = urllib.parse.quote(address)
    url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()

            if data and len(data) > 0:
                lat = float(data[0]["lat"])
                lng = float(data[0]["lon"])
                logger.info("Geocoded '%s' to (%s, %s)", address, lat, lng)
                return lat, lng
            logger.warning("No coordinates found for address: '%s'", address)
            return None
    except Exception as exc:
        logger.error("Failed to geocode address '%s': %s", address, exc)
        return None
