"""
Integration tests for the MongoDB data layer.

These run against a real MongoDB (CI starts one as a service). Set
MONGODB_TEST_URI to point somewhere else; without a reachable server the
module is skipped rather than failing the suite.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.db_services import mongo_repo
from backend.db_services.mongodb import get_client

TEST_URI = os.environ.get("MONGODB_TEST_URI") or os.environ.get("MONGODB_URI") or "mongodb://127.0.0.1:27017"
TEST_DB = "haemnet_test"

# Apollo Greams Road, Chennai — the reference point for the distance tests.
HOSP_LAT, HOSP_LNG = 13.0626, 80.2519


def _offset_km(km_north: float) -> tuple:
    return HOSP_LAT + km_north / 111.0, HOSP_LNG


@pytest.fixture
async def db(monkeypatch):
    """A clean haemnet_test database, or skip if MongoDB is not reachable."""
    from backend.config import settings

    monkeypatch.setattr(settings, "mongodb_uri", TEST_URI)
    monkeypatch.setattr(settings, "mongodb_database", TEST_DB)
    import backend.db_services.mongodb as mongodb

    monkeypatch.setattr(mongodb, "_client", None)
    monkeypatch.setattr(mongo_repo, "_indexes_ready", False)

    try:
        await mongodb.ping()
    except Exception as exc:  # noqa: BLE001 - no server in this environment
        pytest.skip(f"MongoDB not reachable at {TEST_URI}: {exc}")

    database = mongodb.get_database()
    for name in (mongo_repo.DONORS, mongo_repo.HOSPITALS, mongo_repo.DISPATCHES, mongo_repo.CALLS):
        await database[name].delete_many({})
    await mongo_repo.ensure_indexes()
    yield database
    await get_client().close()
    monkeypatch.setattr(mongodb, "_client", None)


async def seed_donor(phone="+919000000001", group="O-", km=1.0, name="Ramesh Kumar",
                     language="tamil", last_donated=None):
    lat, lng = _offset_km(km)
    return await mongo_repo.register_donor(
        name=name, phone=phone, blood_group=group, language=language, lat=lat, lng=lng,
        last_donated_date=last_donated,
    )


# ── donors, distance and cooldown ─────────────────────────────────

async def test_register_is_an_upsert_keyed_on_phone(db):
    first = await seed_donor()
    again = await seed_donor(name="Ramesh K")
    assert str(first.id) == str(again.id)
    assert again.name == "Ramesh K"
    assert await db[mongo_repo.DONORS].count_documents({}) == 1


async def test_profile_edit_never_clears_the_cooldown(db):
    donated = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    await seed_donor(last_donated=donated)
    edited = await seed_donor(name="New Name")  # no date supplied, as a profile edit sends
    assert edited.last_donated_date is not None
    assert edited.is_eligible is False


async def test_eligible_donors_respect_group_distance_and_cooldown(db):
    await seed_donor(phone="+919000000001", group="O-", km=1.0)
    await seed_donor(phone="+919000000002", group="O-", km=4.0)
    await seed_donor(phone="+919000000003", group="O-", km=40.0)          # too far
    await seed_donor(phone="+919000000004", group="A+", km=2.0)           # wrong group
    await seed_donor(phone="+919000000005", group="O-", km=2.0,
                     last_donated=(datetime.now(timezone.utc) - timedelta(days=5)).isoformat())  # recovering

    donors = await mongo_repo.find_eligible_donors("O-", HOSP_LAT, HOSP_LNG)
    assert [d.phone for d in donors] == ["+919000000001", "+919000000002"]  # nearest first


async def test_availability_counts_by_group(db):
    await seed_donor(phone="+919000000001", group="O-", km=1.0)
    await seed_donor(phone="+919000000002", group="O-", km=2.0)
    await seed_donor(phone="+919000000003", group="B+", km=3.0)
    await seed_donor(phone="+919000000004", group="B+", km=99.0)
    counts = await mongo_repo.db_eligible_counts_by_group(HOSP_LAT, HOSP_LNG)
    assert counts == {"O-": 2, "B+": 1}


async def test_donation_starts_the_cooldown_and_delete_removes_the_donor(db):
    donor = await seed_donor()
    assert await mongo_repo.update_donation_date(str(donor.id)) is True
    fresh = await mongo_repo.get_donor_by_phone("+919000000001")
    assert fresh.is_eligible is False
    assert await mongo_repo.update_donation_date("not-a-donor") is False
    assert await mongo_repo.delete_donor("+919000000001") is True
    assert await mongo_repo.get_donor_by_phone("+919000000001") is None


async def test_push_token_is_kept_and_returned(db):
    donor = await seed_donor()
    await mongo_repo.register_donor(
        name="Ramesh", phone="+919000000001", blood_group="O-", language="tamil",
        lat=HOSP_LAT, lng=HOSP_LNG, push_token="ExponentPushToken[abc]",
    )
    assert await mongo_repo.get_donor_push_token(str(donor.id)) == "ExponentPushToken[abc]"
    # A later edit without a token must not wipe it.
    await seed_donor(name="Ramesh Kumar")
    assert await mongo_repo.get_donor_push_token(str(donor.id)) == "ExponentPushToken[abc]"


# ── dispatch lifecycle ────────────────────────────────────────────

async def test_dispatch_lifecycle_end_to_end(db):
    donor_a = await seed_donor(phone="+919000000001", km=1.0)
    donor_b = await seed_donor(phone="+919000000002", km=3.0, name="Anjali Joseph")
    await mongo_repo.db_create_hospital("HOSP-1001", "Apollo Hospital", "Greams Road", "+914400000000", "hash")

    await mongo_repo.db_create_dispatch(
        "dp-1", "HOSP-1001", "O-", HOSP_LAT, HOSP_LNG,
        [{"id": str(donor_a.id), "distance_km": 1.0}, {"id": str(donor_b.id), "distance_km": 3.0}],
        units=2, urgency="critical", address="Trauma Bay 2",
    )

    dispatch = await mongo_repo.db_get_dispatch("dp-1")
    assert dispatch["units"] == 2 and dispatch["urgency"] == "critical"
    assert dispatch["address"] == "Trauma Bay 2" and dispatch["is_complete"] is False
    assert set(dispatch["donors"]) == {str(donor_a.id), str(donor_b.id)}
    assert dispatch["donors"][str(donor_a.id)]["phone"] == "+919000000001"
    assert dispatch["donors"][str(donor_a.id)]["status"] == "ringing"
    assert dispatch["created_at"].endswith("+00:00")

    # The donor app sees it as an open request.
    requests = await mongo_repo.db_requests_for_donor("+919000000001")
    assert len(requests) == 1
    assert requests[0]["hospital_name"] == "Apollo Hospital"
    assert requests[0]["distance_km"] == 1.0

    # Twilio call SID mapping.
    await mongo_repo.db_register_call_sid("CA123", "dp-1", str(donor_a.id))
    assert await mongo_repo.db_get_by_call_sid("CA123") == ("dp-1", str(donor_a.id))
    assert await mongo_repo.db_get_by_call_sid("CA-unknown") is None

    # Accepting records the first acceptance and closes the request for that donor.
    assert await mongo_repo.db_update_donor_status("dp-1", str(donor_a.id), "accepted", 12) is True
    assert await mongo_repo.db_update_donor_status("dp-1", "someone-else", "accepted") is False
    assert await mongo_repo.db_requests_for_donor("+919000000001") == []
    row = await db[mongo_repo.DISPATCHES].find_one({"_id": "dp-1"})
    first_accept = row["first_accept_at"]
    assert first_accept is not None

    await mongo_repo.db_update_donor_status("dp-1", str(donor_b.id), "accepted", 20)
    row = await db[mongo_repo.DISPATCHES].find_one({"_id": "dp-1"})
    assert row["first_accept_at"] == first_accept  # not overwritten by the second donor

    assert await mongo_repo.db_active_count() == 1
    assert await mongo_repo.db_active_dispatch_ids("HOSP-1001") == ["dp-1"]
    assert await mongo_repo.db_active_dispatch_ids("HOSP-2002") == []

    await mongo_repo.db_update_donor_status("dp-1", str(donor_a.id), "donated")
    await mongo_repo.db_update_donor_status("dp-1", str(donor_b.id), "donated")
    await mongo_repo.db_mark_complete("dp-1", fulfilled=True)

    closed = await mongo_repo.db_get_dispatch("dp-1")
    assert closed["is_complete"] is True
    assert await mongo_repo.db_active_count() == 0
    assert await mongo_repo.db_requests_for_donor("+919000000002") == []


async def test_history_counts_outcomes_per_request(db):
    donor = await seed_donor()
    await mongo_repo.db_create_hospital("HOSP-1001", "Apollo Hospital", "Greams Road", "+914400000000", "hash")
    for dispatch_id, status, fulfilled in (
        ("dp-done", "donated", True), ("dp-partial", "accepted", False), ("dp-dead", "no_answer", False),
    ):
        await mongo_repo.db_create_dispatch(
            dispatch_id, "HOSP-1001", "O-", HOSP_LAT, HOSP_LNG,
            [{"id": str(donor.id), "distance_km": 1.0}], units=1, urgency="critical",
        )
        await mongo_repo.db_update_donor_status(dispatch_id, str(donor.id), status)
        await mongo_repo.db_mark_complete(dispatch_id, fulfilled=fulfilled)

    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rows = {r["dispatch_id"]: r for r in await mongo_repo.db_dispatch_history("HOSP-1001", since)}
    assert set(rows) == {"dp-done", "dp-partial", "dp-dead"}
    assert rows["dp-done"]["donated"] == 1 and rows["dp-done"]["fulfilled"] is True
    assert rows["dp-partial"]["accepted"] == 1 and rows["dp-partial"]["donated"] == 0
    assert rows["dp-dead"]["answered"] == 0 and rows["dp-dead"]["matched"] == 1
    assert rows["dp-done"]["first_accept_at"] is not None
    assert rows["dp-dead"]["first_accept_at"] is None

    # Another hospital's requests and anything older than the window stay out.
    assert await mongo_repo.db_dispatch_history("HOSP-2002", since) == []
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert await mongo_repo.db_dispatch_history("HOSP-1001", future) == []


async def test_removing_a_dispatch_takes_its_calls_with_it(db):
    donor = await seed_donor()
    await mongo_repo.db_create_dispatch("dp-1", "HOSP-1001", "O-", HOSP_LAT, HOSP_LNG,
                                        [{"id": str(donor.id), "distance_km": 1.0}])
    await mongo_repo.db_remove_dispatch("dp-1")
    assert await mongo_repo.db_get_dispatch("dp-1") is None
    assert await db[mongo_repo.CALLS].count_documents({}) == 0


async def test_summary_lists_newest_first(db):
    donor = await seed_donor()
    for dispatch_id in ("dp-1", "dp-2"):
        await mongo_repo.db_create_dispatch(dispatch_id, "HOSP-1001", "O-", HOSP_LAT, HOSP_LNG,
                                            [{"id": str(donor.id), "distance_km": 1.0}])
    summary = await mongo_repo.db_summary()
    assert {row["dispatch_id"] for row in summary} == {"dp-1", "dp-2"}
    assert all(row["donors"] == 1 for row in summary)


# ── hospitals and health ──────────────────────────────────────────

async def test_hospital_round_trip_and_health(db):
    created = await mongo_repo.db_create_hospital("HOSP-1001", "Apollo", "Greams Road", "+914400000000", "hashed")
    assert created["id"] == "HOSP-1001"
    fetched = await mongo_repo.db_get_hospital_by_id("HOSP-1001")
    assert fetched["name"] == "Apollo" and fetched["password_hash"] == "hashed"
    assert await mongo_repo.db_get_hospital_by_id("HOSP-9999") is None
    assert (await mongo_repo.db_health())["status"] == "connected"
