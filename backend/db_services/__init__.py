"""
db_services — the data layer the rest of the backend talks to.

╔══════════════════════════════════════════════════════════════════╗
║  Backend code never writes Cypher or Mongo queries directly.     ║
║  It calls the functions exported here.                           ║
╚══════════════════════════════════════════════════════════════════╝

Two implementations provide the same functions:

* `mongo_repo`  — MongoDB (default). Geospatial matching uses a 2dsphere
                  index; see that module for the collection layout.
* `neo4j_repo`  — the original Neo4j/AuraDB implementation, kept working so
                  an existing deployment can stay on it.

Pick one with `DB_BACKEND=mongodb` or `DB_BACKEND=neo4j` (see config.py).
Because the surface is identical, routes, the dispatch store, auth and the
orchestration graph are unaware of which one is running.
"""

from __future__ import annotations

import logging

from backend.config import settings

logger = logging.getLogger(__name__)

if settings.db_backend == "neo4j":
    from backend.db_services.neo4j_repo import (  # noqa: F401
        close,
        db_active_count,
        db_active_dispatch_ids,
        db_create_dispatch,
        db_create_hospital,
        db_dispatch_history,
        db_eligible_counts_by_group,
        db_get_by_call_sid,
        db_get_dispatch,
        db_get_hospital_by_id,
        db_health,
        db_mark_complete,
        db_register_call_sid,
        db_remove_dispatch,
        db_requests_for_donor,
        db_summary,
        db_update_donor_status,
        delete_donor,
        ensure_indexes,
        find_eligible_donors,
        get_donor_by_id,
        get_donor_by_phone,
        get_donor_push_token,
        register_donor,
        update_donation_date,
    )
else:
    from backend.db_services.mongo_repo import (  # noqa: F401
        close,
        db_active_count,
        db_active_dispatch_ids,
        db_create_dispatch,
        db_create_hospital,
        db_dispatch_history,
        db_eligible_counts_by_group,
        db_get_by_call_sid,
        db_get_dispatch,
        db_get_hospital_by_id,
        db_health,
        db_mark_complete,
        db_register_call_sid,
        db_remove_dispatch,
        db_requests_for_donor,
        db_summary,
        db_update_donor_status,
        delete_donor,
        ensure_indexes,
        find_eligible_donors,
        get_donor_by_id,
        get_donor_by_phone,
        get_donor_push_token,
        register_donor,
        update_donation_date,
    )

logger.info("Data layer: %s", settings.db_backend)

__all__ = [
    "close", "ensure_indexes", "db_health",
    "find_eligible_donors", "db_eligible_counts_by_group",
    "get_donor_by_id", "get_donor_by_phone", "get_donor_push_token",
    "register_donor", "update_donation_date", "delete_donor",
    "db_create_dispatch", "db_register_call_sid", "db_get_dispatch", "db_get_by_call_sid",
    "db_update_donor_status", "db_mark_complete", "db_remove_dispatch",
    "db_active_count", "db_summary", "db_active_dispatch_ids",
    "db_dispatch_history", "db_requests_for_donor",
    "db_create_hospital", "db_get_hospital_by_id",
]
