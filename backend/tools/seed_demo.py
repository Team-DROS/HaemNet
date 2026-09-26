"""
Seed a HaemNet database with one hospital and a spread of nearby donors.

For demos and for smoke-testing a fresh deployment. It writes through the
normal data layer, so it works against MongoDB or Neo4j, whichever
DB_BACKEND points at.

    python -m backend.tools.seed_demo --hospital-id HOSP-1001 --password demo1234

Options:
    --donors N         how many donors to create (default 96)
    --lat / --lng      centre point (default Apollo Greams Road, Chennai)
    --radius-km R      donors are spread inside this radius (default 9.5)
    --wipe             delete the seeded donors first (by phone prefix)

Every seeded donor's phone starts with +9190000, which is a reserved test
range in this script: nothing real is ever called. Use it only on a
development or demo database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
from datetime import datetime, timedelta, timezone

from backend.api.auth import get_password_hash
from backend.config import settings
from backend.db_services import (
    close,
    db_create_hospital,
    db_eligible_counts_by_group,
    delete_donor,
    ensure_indexes,
    register_donor,
)

logging.basicConfig(level=logging.WARNING)

NAMES = [
    "Ramesh Kumar", "Anjali Joseph", "Suresh Pillai", "Divya Varma", "Vignesh Menon",
    "Karthik Subramaniam", "Fathima Rasheed", "Priya Nadar", "Arjun Nair", "Meera Iyer",
    "Sanjay Rao", "Lakshmi Narayan", "Deepak Sharma", "Kavya Reddy", "Harish Babu",
    "Nisha Thomas", "Rahul Verma", "Shalini Gopal", "Mohan Das", "Aisha Khan",
]
GROUPS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
LANGUAGES = ["english", "hindi", "tamil"]
PHONE_PREFIX = "+9190000"


def _offset(lat: float, lng: float, km: float, bearing_deg: float) -> tuple:
    bearing = math.radians(bearing_deg)
    return (
        lat + (km * math.cos(bearing)) / 111.0,
        lng + (km * math.sin(bearing)) / (111.0 * math.cos(math.radians(lat))),
    )


async def seed(args) -> None:
    random.seed(args.seed)
    await ensure_indexes()

    if args.wipe:
        for i in range(1, args.donors + 1):
            await delete_donor(f"{PHONE_PREFIX}{i:05d}")
        print(f"Removed up to {args.donors} previously seeded donors.")

    await db_create_hospital(
        id=args.hospital_id,
        name=args.hospital_name,
        location=args.hospital_address,
        phone=args.hospital_phone,
        password_hash=get_password_hash(args.password),
    )
    print(f"Hospital {args.hospital_id} ready (password: {args.password}).")

    created = 0
    for i in range(args.donors):
        # A quarter of the donors are O-, the group emergencies need most.
        group = "O-" if i % 4 == 0 else random.choice(GROUPS)
        lat, lng = _offset(args.lat, args.lng, random.uniform(0.4, args.radius_km), random.uniform(0, 360))
        last_donated = None
        if i % 7 == 3:  # a few are inside the 56-day recovery window
            last_donated = (datetime.now(timezone.utc) - timedelta(days=random.randint(5, 40))).isoformat()
        await register_donor(
            name=NAMES[i % len(NAMES)],
            phone=f"{PHONE_PREFIX}{i + 1:05d}",
            blood_group=group,
            language=random.choice(LANGUAGES),
            lat=lat, lng=lng,
            last_donated_date=last_donated,
        )
        created += 1

    counts = await db_eligible_counts_by_group(args.lat, args.lng)
    print(f"Seeded {created} donors into {settings.db_backend}.")
    print("Eligible right now within 10 km:",
          ", ".join(f"{group} {counts.get(group, 0)}" for group in GROUPS))
    await close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo hospital and donors")
    parser.add_argument("--hospital-id", default="HOSP-1001")
    parser.add_argument("--hospital-name", default="Apollo Hospital")
    parser.add_argument("--hospital-address", default="Greams Road, Chennai")
    parser.add_argument("--hospital-phone", default="+914428290200")
    parser.add_argument("--password", default="demo1234")
    parser.add_argument("--donors", type=int, default=96)
    parser.add_argument("--lat", type=float, default=13.0626)
    parser.add_argument("--lng", type=float, default=80.2519)
    parser.add_argument("--radius-km", type=float, default=9.5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--wipe", action="store_true")
    args = parser.parse_args()

    if settings.app_env.lower() == "production":
        raise SystemExit("Refusing to seed demo data into a production environment.")
    asyncio.run(seed(args))


if __name__ == "__main__":
    main()
