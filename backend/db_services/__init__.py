"""
db_services — Database abstraction layer.

╔══════════════════════════════════════════════════════════════════╗
║  IMPORTANT: This module is owned by the Database Engineer.      ║
║  Backend developers MUST NOT write raw Cypher queries.          ║
║  Instead, call the async functions exported from this package.  ║
╚══════════════════════════════════════════════════════════════════╝

Real Neo4j-backed implementation. Wraps the async neo4j driver and
converts raw records into the Pydantic models the rest of the backend
(routes.py, orchestration/graph.py) already expects.

Connection settings are read from backend.config.settings (NEO4J_URI,
NEO4J_USER, NEO4J_PASSWORD in .env) — see database/README.md for how
to obtain them from AuraDB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import SessionExpired, ServiceUnavailable
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.config import settings
from backend.schemas.models import Coordinates, DonorNode

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Driver lifecycle
# -----------------------------------------------------------------------------
_driver: Optional[AsyncDriver] = None


def _get_driver() -> AsyncDriver:
    """Lazily create the shared async Neo4j driver (one per process)."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        logger.info("Neo4j async driver initialised (%s)", settings.neo4j_uri)
    return _driver


async def close() -> None:
    """Gracefully close the driver. Call this from main.py's shutdown lifespan."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
        logger.info("Neo4j async driver closed.")


# -----------------------------------------------------------------------------
# Internal: convert a Neo4j record into a DonorNode
# -----------------------------------------------------------------------------
def _record_to_donor_node(record: dict) -> DonorNode:
    """
    Convert a raw Neo4j record (dict-like) into a validated DonorNode.
    Handles the two Neo4j-specific types that don't map 1:1 to Python:
      - point()   -> Coordinates(lat, lng)
      - datetime()-> native Python datetime (or None)
    """
    location = record.get("location")
    coordinates = (
        Coordinates(lat=location.latitude, lng=location.longitude)
        if location is not None
        else Coordinates(lat=0.0, lng=0.0)
    )

    last_donated = record.get("last_donated_date")
    last_donated_native = last_donated.to_native() if last_donated is not None else None

    return DonorNode(
        id=record["id"],
        name=record["name"],
        phone=record["phone"],
        blood_group=record["blood_group"],
        language=record["language"],
        location=coordinates,
        has_app=record.get("has_app", False),
        last_donated_date=last_donated_native,
    )


# -----------------------------------------------------------------------------
# 1. FIND ELIGIBLE DONORS
#    Called by routes.py (POST /api/dispatch) and orchestration/graph.py
#    (query_donors_node). Spatial (10km) + cooldown (56-day) match.
# -----------------------------------------------------------------------------
_FIND_ELIGIBLE_DONORS_QUERY = """
MATCH (d:Donor {blood_group: $blood_group})
WHERE point.distance(
        d.location,
        point({latitude: $lat, longitude: $lng})
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
    d.location AS location,
    d.has_app AS has_app,
    d.last_donated_date AS last_donated_date
ORDER BY point.distance(d.location, point({latitude: $lat, longitude: $lng})) ASC
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def find_eligible_donors(
    blood_group: str,
    lat: float,
    lng: float,
    radius_km: float = 10.0,
    cooldown_days: int = 56,
) -> List[DonorNode]:
    """
    Query Neo4j for donors matching:
      - blood_group
      - within `radius_km` of (lat, lng)
      - last_donated_date is NULL **or** > `cooldown_days` days ago

    Returns a list of DonorNode models, closest first.
    """
    cooldown_cutoff = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).isoformat()

    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(
            _FIND_ELIGIBLE_DONORS_QUERY,
            blood_group=blood_group,
            lat=lat,
            lng=lng,
            radius_meters=radius_km * 1000,
            cooldown_cutoff=cooldown_cutoff,
        )
        records = [record.data() async for record in result]

    donors = [_record_to_donor_node(r) for r in records]
    logger.info(
        "find_eligible_donors: %d matches (blood_group=%s, radius=%skm)",
        len(donors), blood_group, radius_km,
    )
    return donors


# -----------------------------------------------------------------------------
# 2. UPDATE DONATION DATE
#    Called by routes.py (POST /api/donate) after a successful transfusion.
#    Starts the 56-day cooldown.
# -----------------------------------------------------------------------------
_UPDATE_DONATION_DATE_QUERY = """
MATCH (d:Donor {id: $donor_id})
SET d.last_donated_date = datetime($donated_at)
RETURN d.id AS id
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def update_donation_date(
    donor_id: str,
    donated_at: Optional[datetime] = None,
) -> bool:
    """
    Set `last_donated_date` on the donor node to `donated_at`
    (defaults to utcnow). Returns True on success, False if the
    donor_id didn't match any node.
    """
    ts = (donated_at or datetime.now(timezone.utc)).isoformat()

    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(
            _UPDATE_DONATION_DATE_QUERY,
            donor_id=donor_id,
            donated_at=ts,
        )
        record = await result.single()

    success = record is not None
    if success:
        logger.info("Donation logged for donor %s at %s", donor_id, ts)
    else:
        logger.warning("update_donation_date: donor %s not found", donor_id)
    return success


# -----------------------------------------------------------------------------
# 3. GET DONOR BY ID
# -----------------------------------------------------------------------------
_GET_DONOR_BY_ID_QUERY = """
MATCH (d:Donor {id: $donor_id})
RETURN
    d.id AS id,
    d.name AS name,
    d.phone AS phone,
    d.blood_group AS blood_group,
    d.language AS language,
    d.location AS location,
    d.has_app AS has_app,
    d.last_donated_date AS last_donated_date
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def get_donor_by_id(donor_id: str) -> Optional[DonorNode]:
    """
    Fetch a single donor node by its UUID.
    Returns None if not found.
    """
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_GET_DONOR_BY_ID_QUERY, donor_id=donor_id)
        record = await result.single()

    if record is None:
        return None
    return _record_to_donor_node(record.data())


# -----------------------------------------------------------------------------
# 3.5 GET DONOR BY PHONE
# -----------------------------------------------------------------------------
_GET_DONOR_BY_PHONE_QUERY = """
MATCH (d:Donor {phone: $phone})
RETURN
    d.id AS id,
    d.name AS name,
    d.phone AS phone,
    d.blood_group AS blood_group,
    d.language AS language,
    d.location AS location,
    d.has_app AS has_app,
    d.last_donated_date AS last_donated_date
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def get_donor_by_phone(phone: str) -> Optional[DonorNode]:
    """
    Fetch a single donor node by its phone number.
    Returns None if not found.
    """
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_GET_DONOR_BY_PHONE_QUERY, phone=phone)
        record = await result.single()

    if record is None:
        return None
    return _record_to_donor_node(record.data())


# -----------------------------------------------------------------------------
# 4. GET DONOR PUSH TOKEN
#    Called by orchestration/graph.py (route_donor_node) to send Expo
#    push notifications to donors with the app.
#
#    NOTE: The donor schema now supports an optional `push_token`
#    property (see database/schema.cypher). The mobile app does not
#    currently send a push token during registration — that's a
#    frontend follow-up (Expo's getExpoPushTokenAsync()) needed before
#    this will ever return a real value. Until then this correctly
#    returns None and the orchestration graph falls back to SMS.
# -----------------------------------------------------------------------------
_GET_DONOR_PUSH_TOKEN_QUERY = """
MATCH (d:Donor {id: $donor_id})
RETURN d.push_token AS push_token
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def get_donor_push_token(donor_id: str) -> Optional[str]:
    """
    Fetch the Expo push token for a donor who has the mobile app.
    Returns None if the donor has no push token registered (or the
    donor doesn't exist).
    """
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_GET_DONOR_PUSH_TOKEN_QUERY, donor_id=donor_id)
        record = await result.single()

    if record is None:
        return None
    return record.data().get("push_token")


# -----------------------------------------------------------------------------
# 5. REGISTER DONOR (app-based self-registration)
#    Not yet wired to a route — no POST /api/donor/register endpoint
#    exists in routes.py yet. Exposed here so the Backend Lead can call
#    it directly once that endpoint is built. Uses MERGE on phone so
#    re-registering with the same number updates the record instead of
#    creating a duplicate.
# -----------------------------------------------------------------------------
_REGISTER_DONOR_QUERY = """
MERGE (d:Donor {phone: $phone})
ON CREATE SET d.id = $donor_id
SET d.name              = $name,
    d.blood_group       = $blood_group,
    d.language           = $language,
    d.location            = point({latitude: $lat, longitude: $lng}),
    d.has_app             = true,
    // Never clear an existing donation date on re-registration: editing a
    // profile used to wipe it, silently lifting the 56-day cooldown.
    d.last_donated_date  = coalesce(datetime($last_donated_date), d.last_donated_date),
    d.push_token          = coalesce($push_token, d.push_token)
RETURN
    d.id AS id, d.name AS name, d.phone AS phone,
    d.blood_group AS blood_group, d.language AS language,
    d.location AS location, d.has_app AS has_app,
    d.last_donated_date AS last_donated_date
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def register_donor(
    name: str,
    phone: str,
    blood_group: str,
    language: str,
    lat: float,
    lng: float,
    last_donated_date: Optional[str] = None,
    push_token: Optional[str] = None,
) -> DonorNode:
    """
    Create or update a donor who registered via the mobile app.

    Args:
        push_token: Expo push token, if the frontend collects one at
                    registration time (optional — see note above).

    Returns the created/updated donor as a DonorNode.
    """
    donor_id = str(uuid4())

    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(
            _REGISTER_DONOR_QUERY,
            donor_id=donor_id,
            name=name,
            phone=phone,
            blood_group=blood_group,
            language=language,
            lat=lat,
            lng=lng,
            last_donated_date=last_donated_date,
            push_token=push_token,
        )
        record = await result.single()

    logger.info("Donor registered/updated: phone=%s", phone)
    return _record_to_donor_node(record.data())


# -----------------------------------------------------------------------------
# 5.5 DELETE DONOR
# -----------------------------------------------------------------------------
_DELETE_DONOR_QUERY = """
MATCH (d:Donor {phone: $phone})
DETACH DELETE d
RETURN count(d) AS deleted_count
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def delete_donor(phone: str) -> bool:
    """
    Delete a donor node by phone number.
    Returns True if a node was deleted, False otherwise.
    """
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_DELETE_DONOR_QUERY, phone=phone)
        record = await result.single()

    deleted_count = record["deleted_count"] if record else 0
    if deleted_count > 0:
        logger.info("Donor deleted: phone=%s", phone)
        return True
    return False

# -----------------------------------------------------------------------------
# 6. DISPATCH STORE INTEGRATION
# -----------------------------------------------------------------------------
_CREATE_DISPATCH_QUERY = """
MERGE (dp:Dispatch {id: $dispatch_id})
SET dp.hospital_id = $hospital_id,
    dp.blood_group = $blood_group,
    dp.lat = $lat,
    dp.lng = $lng,
    dp.units = $units,
    dp.urgency = $urgency,
    dp.address = $address,
    dp.created_at = $created_at,
    dp.is_complete = false
WITH dp
UNWIND $roster AS entry
MATCH (d:Donor {id: entry.id})
MERGE (c:CallSession {dispatch_id: $dispatch_id, donor_id: entry.id})
ON CREATE SET c.status = 'ringing'
SET c.distance_km = entry.distance_km
MERGE (dp)-[:HAS_CALL]->(c)
MERGE (c)-[:CALLED]->(d)
RETURN dp.id AS id
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((SessionExpired, ServiceUnavailable)),
    reraise=True
)
async def db_create_dispatch(
    dispatch_id: str,
    hospital_id: str,
    blood_group: str,
    lat: float,
    lng: float,
    roster: list,
    units: int = 1,
    urgency: str = "urgent",
    address: str = "",
) -> None:
    """
    Create a Dispatch and one CallSession per matched donor.

    ``roster`` is a list of ``{"id": donor_id, "distance_km": float | None}``.
    A plain list of donor-id strings is still accepted for older callers.
    """
    roster = [
        entry if isinstance(entry, dict) else {"id": entry, "distance_km": None}
        for entry in roster
    ]
    driver = _get_driver()
    created_at = datetime.now(timezone.utc).isoformat()
    async with driver.session() as session:
        await session.run(
            _CREATE_DISPATCH_QUERY,
            dispatch_id=dispatch_id,
            hospital_id=hospital_id,
            blood_group=blood_group,
            lat=lat,
            lng=lng,
            units=units,
            urgency=urgency,
            address=address or "",
            created_at=created_at,
            roster=roster,
        )

_REGISTER_CALL_SID_QUERY = """
MATCH (c:CallSession {dispatch_id: $dispatch_id, donor_id: $donor_id})
SET c.sid = $call_sid
"""

async def db_register_call_sid(call_sid: str, dispatch_id: str, donor_id: str) -> None:
    driver = _get_driver()
    async with driver.session() as session:
        await session.run(_REGISTER_CALL_SID_QUERY, call_sid=call_sid, dispatch_id=dispatch_id, donor_id=donor_id)

_GET_DISPATCH_QUERY = """
MATCH (dp:Dispatch {id: $dispatch_id})
OPTIONAL MATCH (dp)-[:HAS_CALL]->(c:CallSession)-[:CALLED]->(d:Donor)
RETURN dp.id AS dispatch_id, dp.hospital_id AS hospital_id, dp.blood_group AS blood_group,
       dp.lat AS lat, dp.lng AS lng, dp.created_at AS created_at, dp.is_complete AS is_complete,
       coalesce(dp.units, 1) AS units, coalesce(dp.urgency, 'urgent') AS urgency,
       coalesce(dp.address, '') AS address,
       collect({
           call_sid: c.sid,
           status: c.status,
           eta_minutes: c.eta_minutes,
           distance_km: c.distance_km,
           donor_id: d.id,
           name: d.name,
           phone: d.phone,
           has_app: d.has_app,
           language: d.language
       }) AS donors
"""

async def db_get_dispatch(dispatch_id: str) -> Optional[dict]:
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_GET_DISPATCH_QUERY, dispatch_id=dispatch_id)
        record = await result.single()
        if not record:
            return None
        data = record.data()
        donors_dict = {}
        for donor_entry in data.get("donors", []):
            if donor_entry.get("donor_id"):
                donors_dict[donor_entry["donor_id"]] = donor_entry
        data["donors"] = donors_dict
        return data

_GET_BY_CALL_SID_QUERY = """
MATCH (c:CallSession {sid: $call_sid})
RETURN c.dispatch_id AS dispatch_id, c.donor_id AS donor_id
"""

async def db_get_by_call_sid(call_sid: str) -> Optional[tuple[str, str]]:
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_GET_BY_CALL_SID_QUERY, call_sid=call_sid)
        record = await result.single()
        if record:
            return record["dispatch_id"], record["donor_id"]
        return None

_UPDATE_DONOR_STATUS_QUERY = """
MATCH (c:CallSession {dispatch_id: $dispatch_id, donor_id: $donor_id})
SET c.status = $status,
    c.eta_minutes = COALESCE($eta_minutes, c.eta_minutes)
RETURN c.donor_id
"""

async def db_update_donor_status(dispatch_id: str, donor_id: str, status: str, eta_minutes: Optional[int] = None) -> bool:
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_UPDATE_DONOR_STATUS_QUERY, dispatch_id=dispatch_id, donor_id=donor_id, status=status, eta_minutes=eta_minutes)
        record = await result.single()
        return record is not None

_MARK_COMPLETE_QUERY = """
MATCH (dp:Dispatch {id: $dispatch_id})
SET dp.is_complete = true
"""

async def db_mark_complete(dispatch_id: str) -> None:
    driver = _get_driver()
    async with driver.session() as session:
        await session.run(_MARK_COMPLETE_QUERY, dispatch_id=dispatch_id)

_REMOVE_DISPATCH_QUERY = """
MATCH (dp:Dispatch {id: $dispatch_id})
OPTIONAL MATCH (dp)-[:HAS_CALL]->(c:CallSession)
DETACH DELETE dp, c
"""

async def db_remove_dispatch(dispatch_id: str) -> None:
    driver = _get_driver()
    async with driver.session() as session:
        await session.run(_REMOVE_DISPATCH_QUERY, dispatch_id=dispatch_id)

_ACTIVE_COUNT_QUERY = """
MATCH (dp:Dispatch {is_complete: false})
RETURN count(dp) AS active_count
"""

async def db_active_count() -> int:
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_ACTIVE_COUNT_QUERY)
        record = await result.single()
        return record["active_count"] if record else 0

_SUMMARY_QUERY = """
MATCH (dp:Dispatch)
OPTIONAL MATCH (dp)-[:HAS_CALL]->(c:CallSession)
RETURN dp.id AS dispatch_id, count(c) AS donors, dp.is_complete AS is_complete, dp.created_at AS created_at
ORDER BY dp.created_at DESC
"""

async def db_summary() -> list[dict]:
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_SUMMARY_QUERY)
        return [record.data() async for record in result]


_ELIGIBLE_COUNTS_QUERY = """
MATCH (d:Donor)
WHERE point.distance(d.location, point({latitude: $lat, longitude: $lng})) <= $radius_meters
  AND (d.last_donated_date IS NULL OR d.last_donated_date < datetime($cooldown_cutoff))
RETURN d.blood_group AS blood_group, count(d) AS available
"""

async def db_eligible_counts_by_group(
    lat: float, lng: float, radius_km: float = 10.0, cooldown_days: int = 56,
) -> dict[str, int]:
    """
    How many donors of each blood group could be called right now within
    ``radius_km`` of a point. Uses the same eligibility rules as dispatch
    matching, so the dashboard's availability numbers match what a real
    dispatch would find.
    """
    cooldown_cutoff = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).isoformat()
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(
            _ELIGIBLE_COUNTS_QUERY, lat=lat, lng=lng,
            radius_meters=radius_km * 1000, cooldown_cutoff=cooldown_cutoff,
        )
        return {record["blood_group"]: record["available"] async for record in result}


_ACTIVE_DISPATCH_IDS_QUERY = """
MATCH (dp:Dispatch {hospital_id: $hospital_id, is_complete: false})
RETURN dp.id AS dispatch_id
ORDER BY dp.created_at DESC
LIMIT $limit
"""

async def db_active_dispatch_ids(hospital_id: str, limit: int = 20) -> list[str]:
    """Open dispatches for one hospital, newest first."""
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_ACTIVE_DISPATCH_IDS_QUERY, hospital_id=hospital_id, limit=limit)
        return [record["dispatch_id"] async for record in result]


_REQUESTS_FOR_DONOR_QUERY = """
MATCH (d:Donor {phone: $phone})<-[:CALLED]-(c:CallSession)<-[:HAS_CALL]-(dp:Dispatch {is_complete: false})
WHERE c.status IN $open_statuses
OPTIONAL MATCH (h:Hospital {id: dp.hospital_id})
RETURN dp.id AS dispatch_id,
       d.id AS donor_id,
       c.status AS status,
       c.distance_km AS distance_km,
       dp.blood_group AS blood_group,
       coalesce(dp.units, 1) AS units,
       coalesce(dp.urgency, 'urgent') AS urgency,
       dp.created_at AS created_at,
       dp.lat AS lat,
       dp.lng AS lng,
       coalesce(h.name, dp.hospital_id) AS hospital_name,
       coalesce(dp.address, h.location, '') AS address
ORDER BY dp.created_at DESC
"""

async def db_requests_for_donor(phone: str) -> list[dict]:
    """
    Open requests this donor was matched to and has not yet decided on.
    Powers the donor app's "urgent request" screen.
    """
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(
            _REQUESTS_FOR_DONOR_QUERY,
            phone=phone,
            open_statuses=["ringing", "answered", "no_answer"],
        )
        return [record.data() async for record in result]

_CREATE_HOSPITAL_QUERY = """
MERGE (h:Hospital {id: $id})
SET h.name = $name,
    h.location = $location,
    h.phone = $phone,
    h.password_hash = $password_hash
RETURN h
"""

async def db_create_hospital(id: str, name: str, location: str, phone: str, password_hash: str) -> dict:
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_CREATE_HOSPITAL_QUERY, id=id, name=name, location=location, phone=phone, password_hash=password_hash)
        record = await result.single()
        return record["h"] if record else None

_GET_HOSPITAL_QUERY = """
MATCH (h:Hospital {id: $id})
RETURN h
"""

async def db_get_hospital_by_id(id: str) -> Optional[dict]:
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(_GET_HOSPITAL_QUERY, id=id)
        record = await result.single()
        return record["h"] if record else None
