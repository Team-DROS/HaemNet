"""
WebSocket server for the Hospital Dashboard.

Route: ``/ws/dashboard``

Every connection must authenticate with the hospital's JWT in its first
message::

    {"type": "auth", "token": "<access token from /api/auth/token>"}

The server answers ``{"type": "auth_ok", "hospital_id": ...}`` and from then
on pushes only the events of dispatches that hospital owns. Previously any
unauthenticated client received every hospital's donor names and statuses.

The token travels in a message rather than the URL so it never lands in
proxy or server access logs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.schemas.models import DonorStatusUpdate

logger = logging.getLogger(__name__)

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 10
CLOSE_UNAUTHORIZED = 4401  # application close code: missing or bad token

OwnerResolver = Callable[[str], Awaitable[Optional[str]]]


async def _default_owner_resolver(dispatch_id: str) -> Optional[str]:
    """Look up which hospital created a dispatch (used after a restart)."""
    from backend.dispatch_store import dispatch_store  # local import: avoids a cycle at startup

    try:
        dispatch = await dispatch_store.get_dispatch(dispatch_id)
    except Exception as exc:  # database down: fail closed, send nothing
        logger.warning("Could not resolve owner of dispatch %s: %s", dispatch_id, exc)
        return None
    return (dispatch or {}).get("hospital_id") or None


# ── Connection Manager ────────────────────────────────────────────

class DashboardConnectionManager:
    """
    Tracks authenticated dashboard sockets per hospital and delivers each
    dispatch's events only to the hospital that owns it.
    """

    def __init__(self, owner_resolver: OwnerResolver = _default_owner_resolver) -> None:
        # hospital_id -> {websocket: optional dispatch filter}
        self._connections: Dict[str, Dict[WebSocket, Optional[str]]] = {}
        self._owners: Dict[str, str] = {}  # dispatch_id -> hospital_id
        self._resolve_owner = owner_resolver
        self._lock = asyncio.Lock()

    # Ownership ------------------------------------------------------

    def bind(self, dispatch_id: str, hospital_id: str) -> None:
        """Record who owns a dispatch. Called when the dispatch is created."""
        self._owners[dispatch_id] = hospital_id

    async def owner_of(self, dispatch_id: str) -> Optional[str]:
        owner = self._owners.get(dispatch_id)
        if owner is None:
            owner = await self._resolve_owner(dispatch_id)
            if owner:
                self._owners[dispatch_id] = owner
        return owner

    # Connections ----------------------------------------------------

    async def register(self, websocket: WebSocket, hospital_id: str, dispatch_filter: Optional[str] = None) -> None:
        async with self._lock:
            self._connections.setdefault(hospital_id, {})[websocket] = dispatch_filter
        logger.info("Dashboard WS authenticated for %s. Sockets: %d",
                    hospital_id, len(self._connections[hospital_id]))

    async def disconnect(self, websocket: WebSocket, hospital_id: Optional[str]) -> None:
        if not hospital_id:
            return
        async with self._lock:
            conns = self._connections.get(hospital_id, {})
            conns.pop(websocket, None)
            if not conns:
                self._connections.pop(hospital_id, None)
        logger.info("Dashboard WS disconnected (%s)", hospital_id)

    def connection_count(self, hospital_id: Optional[str] = None) -> int:
        if hospital_id is not None:
            return len(self._connections.get(hospital_id, {}))
        return sum(len(c) for c in self._connections.values())

    # Delivery -------------------------------------------------------

    async def _deliver(self, dispatch_id: str, payload: str) -> None:
        owner = await self.owner_of(dispatch_id)
        if not owner:
            logger.warning("Dropping WS event for dispatch %s: owner unknown", dispatch_id)
            return
        async with self._lock:
            targets = [ws for ws, only in self._connections.get(owner, {}).items()
                       if only is None or only == dispatch_id]

        dead = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                conns = self._connections.get(owner, {})
                for ws in dead:
                    conns.pop(ws, None)

    async def broadcast(self, dispatch_id: str, update: DonorStatusUpdate) -> None:
        """
        Send a donor status update to the owning hospital's dashboards.
        Stamps it with its dispatch_id and event time so a dashboard watching
        several emergencies can route each update.
        """
        update = update.model_copy(update={
            "dispatch_id": dispatch_id,
            "timestamp": update.timestamp or datetime.now(timezone.utc).isoformat(),
        })
        await self._deliver(dispatch_id, update.model_dump_json())

    async def broadcast_raw(self, dispatch_id: str, data: dict) -> None:
        """Send a raw dict payload to the owning hospital's dashboards."""
        data = {
            "dispatch_id": dispatch_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        await self._deliver(dispatch_id, json.dumps(data))


# Singleton — import and use from anywhere in the backend.
manager = DashboardConnectionManager()


async def _authenticate(websocket: WebSocket) -> Optional[str]:
    """Wait for the auth message and return the hospital ID, or None."""
    from backend.api.auth import hospital_from_token  # local import: auth imports db at module load

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        message = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(message, dict) or message.get("type") != "auth":
        return None
    return hospital_from_token(str(message.get("token") or ""))


# ── WebSocket Route ──────────────────────────────────────────────

@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket, dispatch_id: Optional[str] = None):
    """
    Hospital Dashboard WebSocket endpoint.

    Query params:
        dispatch_id: optional; only that dispatch's events are sent.

    First client message must be the auth message (see module docstring).
    Afterwards the client may send "ping" and receives {"type": "pong"}.
    """
    await websocket.accept()
    hospital_id = await _authenticate(websocket)
    if not hospital_id:
        try:
            await websocket.send_text(json.dumps({"type": "auth_error", "detail": "Sign in again"}))
            await websocket.close(code=CLOSE_UNAUTHORIZED)
        except Exception:
            pass
        return

    if dispatch_id and dispatch_id != "global" and await manager.owner_of(dispatch_id) != hospital_id:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    await manager.register(websocket, hospital_id, dispatch_id if dispatch_id not in (None, "global") else None)
    await websocket.send_text(json.dumps({"type": "auth_ok", "hospital_id": hospital_id}))
    try:
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in ("ping", "heartbeat"):
                await websocket.send_text(json.dumps({"type": "pong"}))
            else:
                logger.debug("WS received from client: %s", data[:120])
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error: %s", exc)
    finally:
        await manager.disconnect(websocket, hospital_id)
