"""
LangGraph-based call orchestration engine.

Implements a StateGraph that manages the lifecycle of every outbound
donor call during an emergency dispatch:

    INITIATE  →  RINGING  →  ANSWERED  →  ACCEPTED / DECLINED
                                       →  ROUTE_DONOR

Each donor is tracked independently inside a shared dispatch state.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from backend.schemas.models import CallStatus, DonorNode, DonorStatusUpdate

logger = logging.getLogger(__name__)


# ── Dispatch State (shared across all nodes) ─────────────────────

class DonorCallState(BaseModel):
    """Tracks an individual donor's call within the dispatch."""
    donor_id: str
    name: str
    phone: str
    has_app: bool = False
    language: str = "english"
    status: CallStatus = CallStatus.RINGING
    eta_minutes: Optional[int] = None
    twilio_call_sid: Optional[str] = None
    distance_km: Optional[float] = None


class DispatchState(BaseModel):
    """
    The root state object for a single emergency dispatch.
    LangGraph passes this through every node in the graph.
    """
    dispatch_id: str = Field(default_factory=lambda: str(uuid4()))
    hospital_id: str = ""
    blood_group: str = ""
    urgency: str = "urgent"
    units: int = 1
    address: str = ""
    lat: float = 0.0
    lng: float = 0.0
    donors: Dict[str, DonorCallState] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_complete: bool = False
    updates: List[Dict[str, Any]] = Field(default_factory=list)


# ── Graph Nodes ───────────────────────────────────────────────────

async def query_donors_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Query the database for eligible donors and populate the state.
    """
    from backend.db_services import find_eligible_donors
    from backend.services.geo import haversine_km

    donors: List[DonorNode] = await find_eligible_donors(
        blood_group=state["blood_group"],
        lat=state["lat"],
        lng=state["lng"],
    )

    donor_states = {}
    for d in donors:
        distance = haversine_km(state["lat"], state["lng"], d.location.lat, d.location.lng)
        donor_states[str(d.id)] = DonorCallState(
            donor_id=str(d.id),
            name=d.name,
            phone=d.phone,
            has_app=d.has_app,
            language=d.language.value,
            status=CallStatus.RINGING,
            distance_km=round(distance, 2),
        ).model_dump()

    logger.info("Matched %d eligible donors for dispatch %s", len(donors), state.get("dispatch_id"))
    return {**state, "donors": donor_states}


async def initiate_calls_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fire concurrent outbound calls to all matched donors via Twilio.

    1. Registers the dispatch in the in-memory store.
    2. Calls each donor concurrently via Twilio.
    3. Maps each Twilio call SID back to (dispatch_id, donor_id).
    4. Emits RINGING updates for the WebSocket dashboard.
    """
    from backend.config import settings
    from backend.dispatch_store import dispatch_store
    from backend.schemas.models import DonorNode
    from backend.services.twilio_service import initiate_call

    dispatch_id = state.get("dispatch_id", "")
    donors = state.get("donors", {})
    if not donors:
        logger.warning("No donors to call for dispatch %s", dispatch_id)
        return {"is_complete": True}

    # Register the dispatch in the store so webhooks can find it.
    await dispatch_store.register_dispatch(
        dispatch_id=dispatch_id,
        donors=donors,
        hospital_id=state.get("hospital_id", ""),
        blood_group=state.get("blood_group", ""),
        lat=state.get("lat", 0.0),
        lng=state.get("lng", 0.0),
        units=state.get("units", 1),
        urgency=state.get("urgency", "urgent"),
        address=state.get("address", ""),
    )

    # Build the callback URL that Twilio will POST status updates to.
    callback_url = f"{settings.server_base_url}/api/twilio/status-callback"

    updates: List[Dict[str, Any]] = []
    call_tasks = []

    for donor_id, donor_data in donors.items():
        # Reconstruct a minimal DonorNode for the Twilio service.
        donor_node = DonorNode(
            id=donor_id,
            name=donor_data["name"],
            phone=donor_data["phone"],
            blood_group=state.get("blood_group", ""),
            language=donor_data.get("language", "english"),
            location={"lat": state.get("lat", 0), "lng": state.get("lng", 0)},
        )
        call_tasks.append(
            _initiate_single_call(donor_node, dispatch_id, donor_id, callback_url)
        )

        # Emit a RINGING update for the dashboard. This is the only update
        # that carries distance and language; later ones only change status.
        update = DonorStatusUpdate(
            donor_id=donor_id,
            name=donor_data["name"],
            status=CallStatus.RINGING,
            eta_minutes=None,
            distance_km=donor_data.get("distance_km"),
            language=donor_data.get("language"),
        ).model_dump()
        updates.append(update)

    # Execute all calls concurrently.
    await asyncio.gather(*call_tasks, return_exceptions=True)

    logger.info("Initiated %d calls for dispatch %s", len(donors), dispatch_id)
    return {**state, "updates": updates}


async def _initiate_single_call(
    donor_node: "DonorNode",
    dispatch_id: str,
    donor_id: str,
    callback_url: str,
) -> None:
    """
    Initiate a single Twilio call and register the call SID in the store.
    Errors are logged but do not crash the dispatch.
    """
    from backend.dispatch_store import dispatch_store
    from backend.services.twilio_service import initiate_call

    try:
        result = await initiate_call(donor_node, dispatch_id, callback_url)
        call_sid = result.get("sid", "")
        if call_sid:
            await dispatch_store.register_call(call_sid, dispatch_id, donor_id)
    except Exception as exc:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
        logger.error(
            "Failed to initiate call for donor %s in dispatch %s: %s",
            donor_id, dispatch_id, exc,
        )
        # Mark as declined so the dashboard shows failure.
        await dispatch_store.update_donor_status(
            dispatch_id, donor_id, CallStatus.DECLINED,
        )


async def route_donor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-acceptance routing: send push notification (native path)
    or SMS with web-tracking link (fallback path).
    """
    from backend.db_services import get_donor_push_token
    from backend.services.twilio_service import send_sms
    from backend.services.push_service import send_dispatch_notification

    dispatch_id = state.get("dispatch_id", "")
    donors = state.get("donors", {})
    updates: List[Dict[str, Any]] = []

    for donor_id, donor_data in donors.items():
        if donor_data.get("status") != CallStatus.ACCEPTED:
            continue

        if donor_data.get("has_app"):
            # Native path — send Expo push notification with map route data.
            try:
                push_token = await get_donor_push_token(donor_id)
                if push_token:
                    await send_dispatch_notification(
                        expo_token=push_token,
                        dispatch_id=dispatch_id,
                        hospital_id=state.get("hospital_id", ""),
                        blood_group=state.get("blood_group", ""),
                        hospital_lat=state.get("lat", 0.0),
                        hospital_lng=state.get("lng", 0.0),
                    )
                    logger.info("Donor %s sent push notification", donor_id)
                else:
                    logger.warning(
                        "Donor %s has_app=true but no push token — falling back to SMS",
                        donor_id,
                    )
                    # Fall through to SMS.
                    await _send_sms_fallback(donor_data, dispatch_id, donor_id, state.get("lat", 0.0), state.get("lng", 0.0))
            except Exception as exc:
                import sentry_sdk
                sentry_sdk.capture_exception(exc)
                logger.error("Push notification failed for donor %s: %s", donor_id, exc)
                # Fall through to SMS on push failure.
                await _send_sms_fallback(donor_data, dispatch_id, donor_id, state.get("lat", 0.0), state.get("lng", 0.0))
        else:
            # Fallback — SMS with tracking link.
            await _send_sms_fallback(donor_data, dispatch_id, donor_id, state.get("lat", 0.0), state.get("lng", 0.0))

        update = DonorStatusUpdate(
            donor_id=donor_id,
            name=donor_data["name"],
            status=CallStatus.EN_ROUTE,
            eta_minutes=donor_data.get("eta_minutes"),
        ).model_dump()
        updates.append(update)

    return {**state, "updates": state.get("updates", []) + updates, "is_complete": True}


async def _send_sms_fallback(
    donor_data: Dict[str, Any], dispatch_id: str, donor_id: str, lat: float, lng: float
) -> None:
    """Send an SMS with a tracking link as a fallback routing path."""
    from backend.services.twilio_service import send_sms

    tracking_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    await send_sms(
        phone=donor_data["phone"],
        message=f"Thank you for accepting! Navigate to the hospital: {tracking_url}",
    )
    logger.info("Donor %s sent SMS tracking link", donor_id)


def should_route(state: Dict[str, Any]) -> str:
    """Conditional edge: only route if at least one donor accepted."""
    donors = state.get("donors", {})
    has_accepted = any(
        d.get("status") == CallStatus.ACCEPTED
        for d in donors.values()
    )
    return "route" if has_accepted else "end"


# ── Build the Graph ──────────────────────────────────────────────

def build_dispatch_graph() -> StateGraph:
    """
    Construct and compile the LangGraph StateGraph for emergency
    dispatch orchestration.

    Flow:
        query_donors → initiate_calls → [conditional] → route_donor → END
                                                      → END
    """
    graph = StateGraph(state_schema=dict)

    # Register nodes
    graph.add_node("query_donors", query_donors_node)
    graph.add_node("initiate_calls", initiate_calls_node)
    graph.add_node("route_donor", route_donor_node)

    # Define edges
    graph.set_entry_point("query_donors")
    graph.add_edge("query_donors", "initiate_calls")
    graph.add_conditional_edges(
        "initiate_calls",
        should_route,
        {"route": "route_donor", "end": END},
    )
    graph.add_edge("route_donor", END)

    return graph.compile()

# Pre-compiled graph — import this from routes.
dispatch_graph = build_dispatch_graph()
