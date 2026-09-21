"""
Small geographic helpers shared by the dispatch graph and the API routes.
"""

from __future__ import annotations

import math
from typing import Optional

EARTH_RADIUS_KM = 6371.0088

# Average door-to-door speed for an urban trip in an Indian metro, used only
# when the donor has not told the AI an ETA themselves. Deliberately
# conservative so the hospital is not promised an arrival that won't happen.
_URBAN_AVG_SPEED_KMH = 18.0
_PREP_MINUTES = 5


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_eta_minutes(distance_km: Optional[float]) -> Optional[int]:
    """Rough travel-time estimate from straight-line distance, or None."""
    if distance_km is None:
        return None
    # Straight-line distance understates road distance by roughly 30%.
    road_km = distance_km * 1.3
    return int(math.ceil(_PREP_MINUTES + road_km / _URBAN_AVG_SPEED_KMH * 60))
