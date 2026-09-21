"""
WebSocket server for the Hospital Dashboard.

Route: ``/ws/dashboard``

Maintains a set of active WebSocket connections and broadcasts
real-time donor call status updates (DonorStatusUpdate payloads)
to all connected hospital clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.schemas.models import DonorStatusUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Connection Manager ────────────────────────────────────────────

class DashboardConnectionManager:
    """
    Manages WebSocket connections for the hospital dashboard.
    Supports multiple concurrent hospital sessions.
    """

    def __init__(self) -> None:
        # dispatch_id → set of active websocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, dispatch_id: str = "global") -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            if dispatch_id not in self._connections:
                self._connections[dispatch_id] = set()
            self._connections[dispatch_id].add(websocket)
        logger.info(
            "Dashboard WS connected (dispatch=%s). Active: %d",
            dispatch_id,
            len(self._connections.get(dispatch_id, set())),
        )

    async def disconnect(self, websocket: WebSocket, dispatch_id: str = "global") -> None:
        """Remove a WebSocket connection from the registry."""
        async with self._lock:
            conns = self._connections.get(dispatch_id, set())
            conns.discard(websocket)
            if not conns:
                self._connections.pop(dispatch_id, None)
        logger.info("Dashboard WS disconnected (dispatch=%s)", dispatch_id)

    async def broadcast(self, dispatch_id: str, update: DonorStatusUpdate) -> None:
        """
        Send a status update to all clients watching a dispatch.

        Stamps the message with its dispatch_id and event time so dashboards
        watching several emergencies can route each update correctly.
        """
        update = update.model_copy(update={
            "dispatch_id": dispatch_id,
            "timestamp": update.timestamp or datetime.now(timezone.utc).isoformat(),
        })
        payload = update.model_dump_json()
        async with self._lock:
            conns = self._connections.get(dispatch_id, set()).copy()
            conns.update(self._connections.get("global", set()))

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        # Prune dead connections
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.get(dispatch_id, set()).discard(ws)
                    self._connections.get("global", set()).discard(ws)

    async def broadcast_raw(self, dispatch_id: str, data: dict) -> None:
        """Send a raw dict payload to all watchers of a dispatch."""
        data = {
            "dispatch_id": dispatch_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        payload = json.dumps(data)
        async with self._lock:
            conns = self._connections.get(dispatch_id, set()).copy()
            conns.update(self._connections.get("global", set()))

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.get(dispatch_id, set()).discard(ws)
                    self._connections.get("global", set()).discard(ws)


# Singleton — import and use from anywhere in the backend.
manager = DashboardConnectionManager()


# ── WebSocket Route ──────────────────────────────────────────────

@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket, dispatch_id: str = "global"):
    """
    Hospital Dashboard WebSocket endpoint.

    Query params:
        dispatch_id — optional; scopes updates to a single dispatch.

    The server pushes ``DonorStatusUpdate`` JSON messages.
    The client may send heartbeat / ping messages which are acknowledged.
    """
    await manager.connect(websocket, dispatch_id)
    try:
        while True:
            # Keep the connection alive; handle client messages.
            data = await websocket.receive_text()
            # Echo heartbeats / pings
            if data.strip().lower() in ("ping", "heartbeat"):
                await websocket.send_text(json.dumps({"type": "pong"}))
            else:
                logger.debug("WS received from client: %s", data[:120])
    except WebSocketDisconnect:
        await manager.disconnect(websocket, dispatch_id)
    except Exception as exc:
        logger.error("WS error: %s", exc)
        await manager.disconnect(websocket, dispatch_id)
