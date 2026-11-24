"""
db_services/queries.py
=======================
Handoff file from the Data & DevOps Engineer to the Backend Lead.

WHY THIS FILE EXISTS:
The backend team should never need to write or edit Cypher directly.
Every function here does ONE thing, takes plain Python arguments, and
returns plain Python data (dicts/lists) — no Neo4j-specific objects leak
out of this module.

USAGE (from backend/ code):
    from backend.db_services.queries import find_eligible_donors, log_donation

    donors = find_eligible_donors(
        driver=neo4j_driver,
        blood_group="O-",
        hospital_lat=13.0827,
        hospital_lng=80.2707,
    )

SETUP:
    Backend is responsible for creating the neo4j.Driver instance (usually
    once, at app startup) and passing it into these functions. See
    database/README.md for how to obtain AuraDB connection credentials.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from neo4j import Driver

# -----------------------------------------------------------------------------
# 1. SPATIAL + COOLDOWN MATCH
#    Core query for the emergency dispatch flow (POST /api/dispatch).
#    Finds donors who are:
#      - the correct blood group
#      - within `radius_km` of the hospital's coordinates
#      - NOT donated in the last `cooldown_days` days (or never donated)
# -----------------------------------------------------------------------------
_FIND_ELIGIBLE_DONORS_QUERY = """
MATCH (d:Donor {blood_group: $blood_group})
WHERE point.distance(
        d.location,
        point({latitude: $hospital_lat, longitude: $hospital_lng})
      ) <= $radius_meters
  AND (
        d.last_donated_date IS NULL
        OR d.last_donated_date < datetime($cooldown_cutoff)
      )
RETURN
    d.id AS id,
    d.name AS name,
    d.phone AS phone,
    d.blood_group AS blood_group,
    d.language AS language,
    d.has_app AS has_app,
    point.distance(
        d.location,
        point({latitude: $hospital_lat, longitude: $hospital_lng})
    ) AS distance_meters
ORDER BY distance_meters ASC
"""


def find_eligible_donors(
    driver: Driver,
    blood_group: str,
    hospital_lat: float,
    hospital_lng: float,
    radius_km: float = 10.0,
    cooldown_days: int = 56,
) -> list[dict]:
    """
    Find all donors eligible for an emergency dispatch.

    Args:
        driver: an active neo4j.Driver (created by the backend at startup)
        blood_group: e.g. "O-", "AB+"
        hospital_lat / hospital_lng: coordinates of the requesting hospital
        radius_km: spatial search radius (defaults to the 10km spec)
        cooldown_days: medical cooldown window (defaults to the 56-day spec)

    Returns:
        List of donor dicts, closest first. Each dict matches the
        WebSocket update payload shape from the architecture manifest
        (id, name, phone, blood_group, language, has_app) plus distance_meters.
    """
    cooldown_cutoff = _days_ago_iso(cooldown_days)

    with driver.session() as session:
        result = session.run(
            _FIND_ELIGIBLE_DONORS_QUERY,
            blood_group=blood_group,
            hospital_lat=hospital_lat,
            hospital_lng=hospital_lng,
            radius_meters=radius_km * 1000,
            cooldown_cutoff=cooldown_cutoff,
        )
        return [record.data() for record in result]


# -----------------------------------------------------------------------------
# 2. LOG DONATION (starts the 56-day cooldown)
#    Called when hospital staff clicks "Log Donation" after a transfusion.
# -----------------------------------------------------------------------------
_LOG_DONATION_QUERY = """
MATCH (d:Donor {id: $donor_id})
SET d.last_donated_date = datetime($donation_timestamp)
RETURN d.id AS id, d.last_donated_date AS last_donated_date
"""


def log_donation(
    driver: Driver,
    donor_id: str,
    donation_timestamp: Optional[str] = None,
) -> Optional[dict]:
    """
    Record that a donor just donated. Sets last_donated_date to now
    (or a provided ISO timestamp), which excludes them from
    find_eligible_donors() for the next 56 days.

    Returns the updated {id, last_donated_date} dict, or None if the
    donor_id didn't match any node.
    """
    ts = donation_timestamp or datetime.now(timezone.utc).isoformat()

    with driver.session() as session:
        result = session.run(
            _LOG_DONATION_QUERY,
            donor_id=donor_id,
            donation_timestamp=ts,
        )
        record = result.single()
        return record.data() if record else None


# -----------------------------------------------------------------------------
# 3. GET SINGLE DONOR (used for the has_app routing check post-acceptance)
# -----------------------------------------------------------------------------
_GET_DONOR_QUERY = """
MATCH (d:Donor {id: $donor_id})
RETURN d.id AS id, d.name AS name, d.phone AS phone,
       d.has_app AS has_app, d.language AS language
"""


def get_donor(driver: Driver, donor_id: str) -> Optional[dict]:
    """Fetch a single donor's routing-relevant fields by id."""
    with driver.session() as session:
        result = session.run(_GET_DONOR_QUERY, donor_id=donor_id)
        record = result.single()
        return record.data() if record else None


# -----------------------------------------------------------------------------
# 4. REGISTER DONOR (app-based self-registration)
#    Called when a donor signs up via the mobile app. Uses MERGE on phone
#    so a re-registration with the same number updates the record rather
#    than creating a duplicate. UUID is generated server-side.
# -----------------------------------------------------------------------------
_REGISTER_DONOR_QUERY = """
MERGE (d:Donor {phone: $phone})
ON CREATE SET d.id = $donor_id
SET d.name            = $name,
    d.blood_group     = $blood_group,
    d.language        = $language,
    d.location        = point({latitude: $lat, longitude: $lng}),
    d.has_app         = true,
    d.last_donated_date = $last_donated_date
RETURN d.id AS id, d.name AS name, d.phone AS phone
"""


def register_donor(
    driver: Driver,
    name: str,
    phone: str,
    blood_group: str,
    language: str,
    lat: float,
    lng: float,
    last_donated_date: Optional[str] = None,
) -> dict:
    """
    Create or update a donor who registered via the mobile app.

    Uses MERGE on phone so calling this twice with the same number updates
    the existing node instead of creating a duplicate. A UUID is generated
    server-side on first creation; subsequent calls preserve the original id.

    Args:
        driver: an active neo4j.Driver (created by the backend at startup)
        name: donor's full name
        phone: unique mobile number used as the merge key
        blood_group: e.g. "O-", "AB+"
        language: preferred notification language, e.g. "en", "ta"
        lat / lng: donor's registered location coordinates
        last_donated_date: optional ISO-8601 date string; stored as null if
                           not provided (meaning the donor is immediately
                           eligible for dispatch)

    Returns:
        Dict with {id, name, phone} of the created or updated donor.
    """
    donor_id = str(uuid.uuid4())

    with driver.session() as session:
        result = session.run(
            _REGISTER_DONOR_QUERY,
            donor_id=donor_id,
            name=name,
            phone=phone,
            blood_group=blood_group,
            language=language,
            lat=lat,
            lng=lng,
            last_donated_date=last_donated_date,
        )
        record = result.single()
        return record.data()


# -----------------------------------------------------------------------------
# Internal helper
# -----------------------------------------------------------------------------
def _days_ago_iso(days: int) -> str:
    """Return an ISO-8601 timestamp `days` days before now (UTC)."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.isoformat()
