"""
db_services/mongo_repo — MongoDB implementation of the data layer.

Same function names, arguments and return shapes as the Neo4j repository, so
routes, the dispatch store and the orchestration graph work unchanged; the
active backend is chosen by `DB_BACKEND` (see db_services/__init__.py).

Collections
-----------
donors      _id = donor UUID. `location` is GeoJSON Point [lng, lat] with a
            2dsphere index, so "eligible donors within 10 km" is one $geoNear
            stage instead of a scan.
hospitals   _id = hospital ID (HOSP-1234).
dispatches  _id = dispatch UUID. Holds units, urgency, address, first
            acceptance, close time and whether every unit was donated.
calls       _id = "<dispatch_id>:<donor_id>", one per donor dialled, carrying
            the call status, ETA, distance and Twilio call SID.

Timestamps are stored as UTC datetimes and returned as ISO strings, which is
what the Neo4j layer returned and what the apps parse.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pymongo import ASCENDING, GEOSPHERE, ReturnDocument

from backend.db_services.mongodb import close as close_client, get_database, ping
from backend.schemas.models import Coordinates, DonorNode

logger = logging.getLogger(__name__)

DONORS = "donors"
HOSPITALS = "hospitals"
DISPATCHES = "dispatches"
CALLS = "calls"

# Statuses that mean the donor said yes, and the wider set that means the
# donor engaged at all. Shared with the history aggregation.
ACCEPT_STATUSES = ["accepted", "en_route", "completed", "donated"]
ANSWERED_STATUSES = ["answered", "declined", *ACCEPT_STATUSES]
OPEN_CALL_STATUSES = ["ringing", "answered", "no_answer"]

_indexes_ready = False


# ── helpers ───────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """MongoDB returns naive datetimes (always UTC); make that explicit."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    return str(value)


def _parse_time(value) -> Optional[datetime]:
    """Accept a datetime or an ISO string (with or without a zone)."""
    if value is None or isinstance(value, datetime):
        return _as_utc(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return _as_utc(parsed)


def _call_id(dispatch_id: str, donor_id: str) -> str:
    return f"{dispatch_id}:{donor_id}"


def _doc_to_donor_node(doc: Dict[str, Any]) -> DonorNode:
    coordinates = (doc.get("location") or {}).get("coordinates") or [0.0, 0.0]
    return DonorNode(
        id=doc["_id"],
        name=doc["name"],
        phone=doc["phone"],
        blood_group=doc["blood_group"],
        language=doc.get("language") or "english",
        location=Coordinates(lat=coordinates[1], lng=coordinates[0]),
        has_app=doc.get("has_app", False),
        last_donated_date=_as_utc(doc.get("last_donated_date")),
    )


def _point(lat: float, lng: float) -> Dict[str, Any]:
    return {"type": "Point", "coordinates": [float(lng), float(lat)]}


async def ensure_indexes() -> None:
    """Create the indexes the queries rely on. Safe to call repeatedly."""
    global _indexes_ready
    if _indexes_ready:
        return
    db = get_database()
    await db[DONORS].create_index([("location", GEOSPHERE)])
    await db[DONORS].create_index([("phone", ASCENDING)], unique=True)
    await db[DONORS].create_index([("blood_group", ASCENDING)])
    await db[DISPATCHES].create_index([("hospital_id", ASCENDING), ("created_at", ASCENDING)])
    await db[DISPATCHES].create_index([("is_complete", ASCENDING)])
    await db[CALLS].create_index([("dispatch_id", ASCENDING)])
    await db[CALLS].create_index([("donor_id", ASCENDING)])
    await db[CALLS].create_index([("call_sid", ASCENDING)], sparse=True)
    _indexes_ready = True
    logger.info("MongoDB indexes ensured on %s", get_database().name)


async def close() -> None:
    """Close the shared client (called from the app's shutdown hook)."""
    global _indexes_ready
    _indexes_ready = False
    await close_client()


async def db_health() -> Dict[str, str]:
    """Liveness probe for /api/health."""
    try:
        await ping()
        return {"backend": "mongodb", "status": "connected"}
    except Exception as exc:  # noqa: BLE001 - reported, not raised, to the probe
        logger.error("MongoDB health check failed: %s", exc)
        return {"backend": "mongodb", "status": f"disconnected: {exc}"}


# ── donors ────────────────────────────────────────────────────────

async def find_eligible_donors(
    blood_group: str,
    lat: float,
    lng: float,
    radius_km: float = 10.0,
    cooldown_days: int = 56,
) -> List[DonorNode]:
    """
    Donors of this blood group within `radius_km`, who are not inside the
    56-day recovery window, closest first.
    """
    cutoff = _now() - timedelta(days=cooldown_days)
    db = get_database()
    pipeline = [
        {"$geoNear": {
            "near": _point(lat, lng),
            "distanceField": "distance_m",
            "maxDistance": radius_km * 1000,
            "spherical": True,
            "query": {
                "blood_group": blood_group,
                "$or": [{"last_donated_date": None}, {"last_donated_date": {"$lt": cutoff}}],
            },
        }},
    ]
    cursor = await db[DONORS].aggregate(pipeline)
    donors = [_doc_to_donor_node(doc) async for doc in cursor]
    logger.info(
        "find_eligible_donors: %d matches (blood_group=%s, radius=%skm)",
        len(donors), blood_group, radius_km,
    )
    return donors


async def db_eligible_counts_by_group(
    lat: float, lng: float, radius_km: float = 10.0, cooldown_days: int = 56,
) -> Dict[str, int]:
    """How many donors of each blood group could be called right now."""
    cutoff = _now() - timedelta(days=cooldown_days)
    db = get_database()
    pipeline = [
        {"$geoNear": {
            "near": _point(lat, lng),
            "distanceField": "distance_m",
            "maxDistance": radius_km * 1000,
            "spherical": True,
            "query": {"$or": [{"last_donated_date": None}, {"last_donated_date": {"$lt": cutoff}}]},
        }},
        {"$group": {"_id": "$blood_group", "available": {"$sum": 1}}},
    ]
    cursor = await db[DONORS].aggregate(pipeline)
    return {doc["_id"]: doc["available"] async for doc in cursor}


async def get_donor_by_id(donor_id: str) -> Optional[DonorNode]:
    doc = await get_database()[DONORS].find_one({"_id": donor_id})
    return _doc_to_donor_node(doc) if doc else None


async def get_donor_by_phone(phone: str) -> Optional[DonorNode]:
    doc = await get_database()[DONORS].find_one({"phone": phone})
    return _doc_to_donor_node(doc) if doc else None


async def get_donor_push_token(donor_id: str) -> Optional[str]:
    doc = await get_database()[DONORS].find_one({"_id": donor_id}, {"push_token": 1})
    return (doc or {}).get("push_token")


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
    Create or update the donor with this phone number.

    Editing a profile must never clear `last_donated_date`: that silently
    lifted the 56-day cooldown, so the field is only written when a new value
    is supplied.
    """
    update: Dict[str, Any] = {
        "$set": {
            "name": name,
            "blood_group": blood_group,
            "language": language,
            "location": _point(lat, lng),
            "has_app": True,
            "updated_at": _now(),
        },
        "$setOnInsert": {"_id": str(uuid4()), "phone": phone, "created_at": _now()},
    }
    donated = _parse_time(last_donated_date)
    if donated is not None:
        update["$set"]["last_donated_date"] = donated
    if push_token:
        update["$set"]["push_token"] = push_token

    doc = await get_database()[DONORS].find_one_and_update(
        {"phone": phone}, update, upsert=True, return_document=ReturnDocument.AFTER,
    )
    logger.info("Donor registered/updated: phone=%s", phone)
    return _doc_to_donor_node(doc)


async def update_donation_date(donor_id: str, donated_at: Optional[datetime] = None) -> bool:
    """Start the donor's 56-day cooldown. False if no such donor."""
    ts = _as_utc(donated_at) or _now()
    result = await get_database()[DONORS].update_one(
        {"_id": donor_id}, {"$set": {"last_donated_date": ts}},
    )
    if result.matched_count:
        logger.info("Donation logged for donor %s at %s", donor_id, ts.isoformat())
        return True
    logger.warning("update_donation_date: donor %s not found", donor_id)
    return False


async def delete_donor(phone: str) -> bool:
    result = await get_database()[DONORS].delete_one({"phone": phone})
    if result.deleted_count:
        logger.info("Donor deleted: phone=%s", phone)
        return True
    return False


# ── dispatches and call sessions ──────────────────────────────────

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
    """Record a dispatch and one call session per rostered donor."""
    db = get_database()
    await db[DISPATCHES].update_one(
        {"_id": dispatch_id},
        {"$set": {
            "hospital_id": hospital_id, "blood_group": blood_group,
            "lat": lat, "lng": lng, "units": units, "urgency": urgency,
            "address": address, "is_complete": False,
        },
         "$setOnInsert": {"created_at": _now(), "fulfilled": False}},
        upsert=True,
    )
    entries = [
        entry if isinstance(entry, dict) else {"id": entry, "distance_km": None}
        for entry in roster
    ]
    for entry in entries:
        donor_id = entry["id"]
        await db[CALLS].update_one(
            {"_id": _call_id(dispatch_id, donor_id)},
            {"$set": {"distance_km": entry.get("distance_km")},
             "$setOnInsert": {
                 "dispatch_id": dispatch_id, "donor_id": donor_id,
                 "status": "ringing", "eta_minutes": None, "call_sid": None,
                 "created_at": _now(),
             }},
            upsert=True,
        )


async def db_register_call_sid(call_sid: str, dispatch_id: str, donor_id: str) -> None:
    await get_database()[CALLS].update_one(
        {"_id": _call_id(dispatch_id, donor_id)}, {"$set": {"call_sid": call_sid}},
    )


async def db_get_dispatch(dispatch_id: str) -> Optional[dict]:
    db = get_database()
    dispatch = await db[DISPATCHES].find_one({"_id": dispatch_id})
    if not dispatch:
        return None

    calls = [c async for c in db[CALLS].find({"dispatch_id": dispatch_id})]
    donor_ids = [c["donor_id"] for c in calls]
    donors_by_id = {
        d["_id"]: d async for d in db[DONORS].find({"_id": {"$in": donor_ids}})
    }

    donors: Dict[str, Dict[str, Any]] = {}
    for call in calls:
        donor = donors_by_id.get(call["donor_id"], {})
        donors[call["donor_id"]] = {
            "call_sid": call.get("call_sid"),
            "status": call.get("status"),
            "eta_minutes": call.get("eta_minutes"),
            "distance_km": call.get("distance_km"),
            "donor_id": call["donor_id"],
            "name": donor.get("name"),
            "phone": donor.get("phone"),
            "has_app": donor.get("has_app"),
            "language": donor.get("language"),
        }

    return {
        "dispatch_id": dispatch["_id"],
        "hospital_id": dispatch.get("hospital_id"),
        "blood_group": dispatch.get("blood_group"),
        "lat": dispatch.get("lat"),
        "lng": dispatch.get("lng"),
        "created_at": _iso(dispatch.get("created_at")),
        "is_complete": bool(dispatch.get("is_complete")),
        "units": dispatch.get("units") or 1,
        "urgency": dispatch.get("urgency") or "urgent",
        "address": dispatch.get("address") or "",
        "donors": donors,
    }


async def db_get_by_call_sid(call_sid: str) -> Optional[tuple[str, str]]:
    call = await get_database()[CALLS].find_one({"call_sid": call_sid})
    if not call:
        return None
    return call["dispatch_id"], call["donor_id"]


async def db_update_donor_status(
    dispatch_id: str, donor_id: str, status: str, eta_minutes: Optional[int] = None,
) -> bool:
    """Move one donor's call along. Records the dispatch's first acceptance."""
    db = get_database()
    changes: Dict[str, Any] = {"status": status, "updated_at": _now()}
    if eta_minutes is not None:
        changes["eta_minutes"] = eta_minutes
    result = await db[CALLS].update_one({"_id": _call_id(dispatch_id, donor_id)}, {"$set": changes})
    if not result.matched_count:
        return False

    if status in ACCEPT_STATUSES:
        # {field: None} also matches documents where the field is absent.
        await db[DISPATCHES].update_one(
            {"_id": dispatch_id, "first_accept_at": None},
            {"$set": {"first_accept_at": _now()}},
        )
    return True


async def db_mark_complete(dispatch_id: str, fulfilled: bool = False) -> None:
    """Close a dispatch. `fulfilled` records that every unit was donated."""
    db = get_database()
    changes: Dict[str, Any] = {"is_complete": True}
    if fulfilled:
        changes["fulfilled"] = True
    await db[DISPATCHES].update_one({"_id": dispatch_id}, {"$set": changes})
    await db[DISPATCHES].update_one(
        {"_id": dispatch_id, "closed_at": None}, {"$set": {"closed_at": _now()}},
    )


async def db_remove_dispatch(dispatch_id: str) -> None:
    db = get_database()
    await db[CALLS].delete_many({"dispatch_id": dispatch_id})
    await db[DISPATCHES].delete_one({"_id": dispatch_id})


async def db_active_count() -> int:
    return await get_database()[DISPATCHES].count_documents({"is_complete": False})


async def db_summary() -> List[dict]:
    db = get_database()
    rows = []
    async for dispatch in db[DISPATCHES].find().sort("created_at", -1):
        rows.append({
            "dispatch_id": dispatch["_id"],
            "donors": await db[CALLS].count_documents({"dispatch_id": dispatch["_id"]}),
            "is_complete": bool(dispatch.get("is_complete")),
            "created_at": _iso(dispatch.get("created_at")),
        })
    return rows


async def db_active_dispatch_ids(hospital_id: str, limit: int = 20) -> List[str]:
    cursor = get_database()[DISPATCHES].find(
        {"hospital_id": hospital_id, "is_complete": False}, {"_id": 1},
    ).sort("created_at", -1).limit(limit)
    return [doc["_id"] async for doc in cursor]


async def db_dispatch_history(hospital_id: str, since_iso: str, limit: int = 500) -> List[dict]:
    """Every dispatch this hospital raised since `since_iso`, with outcomes."""
    since = _parse_time(since_iso)
    db = get_database()
    query: Dict[str, Any] = {"hospital_id": hospital_id}
    if since is not None:
        query["created_at"] = {"$gte": since}

    rows = []
    cursor = db[DISPATCHES].find(query).sort("created_at", -1).limit(limit)
    async for dispatch in cursor:
        statuses = [c.get("status") async for c in db[CALLS].find(
            {"dispatch_id": dispatch["_id"]}, {"status": 1},
        )]
        rows.append({
            "dispatch_id": dispatch["_id"],
            "blood_group": dispatch.get("blood_group"),
            "units": dispatch.get("units") or 1,
            "urgency": dispatch.get("urgency") or "urgent",
            "created_at": _iso(dispatch.get("created_at")),
            "first_accept_at": _iso(dispatch.get("first_accept_at")),
            "closed_at": _iso(dispatch.get("closed_at")),
            "is_complete": bool(dispatch.get("is_complete")),
            "fulfilled": bool(dispatch.get("fulfilled")),
            "matched": len(statuses),
            "answered": sum(1 for s in statuses if s in ANSWERED_STATUSES),
            "accepted": sum(1 for s in statuses if s in ACCEPT_STATUSES),
            "donated": sum(1 for s in statuses if s == "donated"),
        })
    return rows


async def db_requests_for_donor(phone: str) -> List[dict]:
    """Open requests this donor was matched to and has not yet decided on."""
    db = get_database()
    donor = await db[DONORS].find_one({"phone": phone}, {"_id": 1})
    if not donor:
        return []

    rows = []
    calls = db[CALLS].find({"donor_id": donor["_id"], "status": {"$in": OPEN_CALL_STATUSES}})
    async for call in calls:
        dispatch = await db[DISPATCHES].find_one({"_id": call["dispatch_id"], "is_complete": False})
        if not dispatch:
            continue
        hospital = await db[HOSPITALS].find_one({"_id": dispatch.get("hospital_id")}, {"name": 1, "location": 1})
        rows.append({
            "dispatch_id": dispatch["_id"],
            "donor_id": donor["_id"],
            "status": call.get("status"),
            "distance_km": call.get("distance_km"),
            "blood_group": dispatch.get("blood_group"),
            "units": dispatch.get("units") or 1,
            "urgency": dispatch.get("urgency") or "urgent",
            "created_at": _iso(dispatch.get("created_at")),
            "lat": dispatch.get("lat"),
            "lng": dispatch.get("lng"),
            "hospital_name": (hospital or {}).get("name") or dispatch.get("hospital_id"),
            "address": dispatch.get("address") or (hospital or {}).get("location") or "",
        })
    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return rows


# ── hospitals ─────────────────────────────────────────────────────

def _hospital_out(doc: Optional[Dict[str, Any]]) -> Optional[dict]:
    if not doc:
        return None
    out = dict(doc)
    out["id"] = out.pop("_id")
    return out


async def db_create_hospital(id: str, name: str, location: str, phone: str, password_hash: str) -> dict:
    doc = await get_database()[HOSPITALS].find_one_and_update(
        {"_id": id},
        {"$set": {"name": name, "location": location, "phone": phone, "password_hash": password_hash}},
        upsert=True, return_document=ReturnDocument.AFTER,
    )
    return _hospital_out(doc)


async def db_get_hospital_by_id(id: str) -> Optional[dict]:
    return _hospital_out(await get_database()[HOSPITALS].find_one({"_id": id}))
