"""Delayed retry jobs on MongoDB call records; a dispatch deletion also removes its jobs."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument

from backend.db_services.mongo_repo import CALLS
from backend.db_services.mongodb import get_database


def _now():
    return datetime.now(timezone.utc)


async def enqueue(dispatch_id: str, donor_id: str, sid: str, delay: int, limit: int) -> bool:
    now = _now()
    result = await get_database()[CALLS].update_one(
        {
            "dispatch_id": dispatch_id,
            "donor_id": donor_id,
            "status": {"$in": ["ringing", "answered", "no_answer"]},
            "call_sid": {"$in": [None, sid]},
            "retry_source": {"$ne": sid},
            "retry_due": {"$exists": False},
            "$or": [{"retry_count": {"$lt": limit}}, {"retry_count": {"$exists": False}}],
        },
        {
            "$push": {"status_history": {"status": "no_answer", "at": now}},
            "$inc": {"retry_count": 1},
            "$set": {
                "status": "no_answer",
                "call_sid": sid,
                "retry_source": sid,
                "retry_due": now + timedelta(seconds=delay),
            },
        },
    )
    return bool(result.modified_count)


async def claim_due():
    """Lease a due job. A crashed worker's lease becomes eligible again after 30 seconds."""
    now = _now()
    lease_until = now + timedelta(seconds=30)
    return await get_database()[CALLS].find_one_and_update(
        {"retry_due": {"$lte": now}},
        {"$set": {"retry_due": lease_until, "retry_lease": uuid4().hex}},
        sort=[("retry_due", 1)],
        return_document=ReturnDocument.AFTER,
    )


async def finish(job, *, dial: bool) -> bool:
    """Consume only our current lease. Reserve the dial before contacting the provider."""
    query = {"_id": job["_id"], "retry_lease": job["retry_lease"], "retry_source": job["retry_source"]}
    changes: dict[str, Any] = {"$unset": {"retry_due": "", "retry_lease": ""}}
    if dial:
        query.update({"status": "no_answer", "call_sid": job["retry_source"]})
        changes["$set"] = {"status": "ringing", "call_sid": None}
        changes["$push"] = {"status_history": {"status": "ringing", "at": _now()}}
    result = await get_database()[CALLS].update_one(query, changes)
    return bool(result.modified_count)
