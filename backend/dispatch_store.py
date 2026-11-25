"""
Dispatch state store.

Tracks every dispatch and maps Twilio call SIDs back to (dispatch_id, donor_id)
pairs. All state lives in the configured database (MongoDB by default), never in
process memory, so any backend instance can answer a webhook for a dispatch that
another instance started.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.db_services import (
    db_active_count,
    db_active_dispatch_ids,
    db_create_dispatch,
    db_dispatch_history,
    db_get_by_call_sid,
    db_get_dispatch,
    db_mark_complete,
    db_register_call_sid,
    db_remove_dispatch,
    db_requests_for_donor,
    db_summary,
    db_update_donor_status,
)
from backend.schemas.models import CallStatus

logger = logging.getLogger(__name__)


class DispatchStore:
    """
    Stateless store for active dispatch sessions.
    Proxies all operations to the configured database.
    """

    _instance: Optional[DispatchStore] = None

    def __new__(cls) -> DispatchStore:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ── Registration ──────────────────────────────────────────────

    async def register_dispatch(
        self,
        dispatch_id: str,
        donors: Dict[str, Dict[str, Any]],
        hospital_id: str = "",
        blood_group: str = "",
        lat: float = 0.0,
        lng: float = 0.0,
        units: int = 1,
        urgency: str = "urgent",
        address: str = "",
    ) -> None:
        """Register a new dispatch and its donor roster."""
        roster = [{"id": donor_id, "distance_km": (data or {}).get("distance_km")} for donor_id, data in donors.items()]
        await db_create_dispatch(
            dispatch_id,
            hospital_id,
            blood_group,
            lat,
            lng,
            roster,
            units=units,
            urgency=urgency,
            address=address,
        )
        logger.info("Dispatch %s registered with %d donors", dispatch_id, len(donors))

    async def register_call(self, call_sid: str, dispatch_id: str, donor_id: str) -> None:
        """Map a Twilio call SID to a dispatch + donor pair."""
        await db_register_call_sid(call_sid, dispatch_id, donor_id)
        logger.debug(
            "Call SID %s registered → dispatch=%s donor=%s",
            call_sid,
            dispatch_id,
            donor_id,
        )

    # ── Lookups ───────────────────────────────────────────────────

    async def get_dispatch(self, dispatch_id: str) -> Optional[Dict[str, Any]]:
        """Return the full dispatch state, or None."""
        return await db_get_dispatch(dispatch_id)

    async def get_by_call_sid(self, call_sid: str) -> Optional[Tuple[str, str]]:
        """Look up (dispatch_id, donor_id) from a Twilio call SID."""
        return await db_get_by_call_sid(call_sid)

    async def get_donor(self, dispatch_id: str, donor_id: str) -> Optional[Dict[str, Any]]:
        """Return a single donor's state within a dispatch."""
        dispatch = await self.get_dispatch(dispatch_id)
        if dispatch:
            return dispatch.get("donors", {}).get(donor_id)
        return None

    # ── Updates ───────────────────────────────────────────────────

    async def update_donor_status(
        self,
        dispatch_id: str,
        donor_id: str,
        status: CallStatus,
        eta_minutes: Optional[int] = None,
        *,
        only_from: tuple[str, ...] | None = None,
        call_sid: str = "",
    ) -> bool:
        """
        Update a donor's call status within a dispatch.
        Returns True if the update was applied.
        """
        if only_from is None and not call_sid:
            success = await db_update_donor_status(dispatch_id, donor_id, status.value, eta_minutes)
        else:
            success = await db_update_donor_status(
                dispatch_id, donor_id, status.value, eta_minutes, only_from=only_from, call_sid=call_sid
            )
        if success:
            logger.info(
                "Donor %s in dispatch %s → %s",
                donor_id,
                dispatch_id,
                status.value,
            )
        else:
            logger.warning(
                "update_donor_status: failed for donor %s in dispatch %s",
                donor_id,
                dispatch_id,
            )
        return success

    async def mark_complete(self, dispatch_id: str, fulfilled: bool = False) -> None:
        """Close a dispatch. `fulfilled` records that every unit was donated."""
        await db_mark_complete(dispatch_id, fulfilled=fulfilled)
        logger.info("Dispatch %s marked complete (fulfilled=%s)", dispatch_id, fulfilled)

    # ── Cleanup ───────────────────────────────────────────────────

    async def remove_dispatch(self, dispatch_id: str) -> None:
        """Remove a finished dispatch and all its CallSession nodes."""
        await db_remove_dispatch(dispatch_id)
        logger.info("Dispatch %s removed", dispatch_id)

    # ── Diagnostics ───────────────────────────────────────────────

    async def active_count(self) -> int:
        """Return the number of active dispatches."""
        return await db_active_count()

    async def summary(self) -> List[Dict[str, Any]]:
        """Return a compact summary of all active dispatches."""
        return await db_summary()

    async def active_for_hospital(self, hospital_id: str) -> List[Dict[str, Any]]:
        """Full state of every open dispatch belonging to a hospital, newest first."""
        dispatches = []
        for dispatch_id in await db_active_dispatch_ids(hospital_id):
            dispatch = await self.get_dispatch(dispatch_id)
            if dispatch:
                dispatches.append(dispatch)
        return dispatches

    async def history_for_hospital(self, hospital_id: str, since_iso: str) -> List[Dict[str, Any]]:
        """Closed and open dispatches since a point in time, newest first."""
        return await db_dispatch_history(hospital_id, since_iso)

    async def requests_for_donor(self, phone: str) -> List[Dict[str, Any]]:
        """Open requests a donor has been matched to and not yet answered."""
        return await db_requests_for_donor(phone)


# Singleton instance — import this everywhere.
dispatch_store = DispatchStore()
