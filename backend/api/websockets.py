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

from backend.api.auth import hospital_from_token  # local import: auth imports db at module load
from backend.dispatch_store import dispatch_store  # local import: avoids a cycle at startup
from backend.schemas.models import DonorStatusUpdate
from backend.services import redis_client

logger = logging.getLogger(__name__)

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 10
CLOSE_UNAUTHORIZED = 4401  # application close code: missing or bad token
SEND_TIMEOUT_SECONDS = 5  # a dashboard socket slower than this is treated as dead

OwnerResolver = Callable[[str], Awaitable[Optional[str]]]


async def _default_owner_resolver(dispatch_id: str) -> Optional[str]:
    """Look up which hospital created a dispatch (used after a restart)."""

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
        self._pubsub_task: Optional[asyncio.Task] = None
        self._pubsub_ready = False

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
        logger.info("Dashboard WS authenticated for %s. Sockets: %d", hospital_id, len(self._connections[hospital_id]))

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
            targets = [
                ws for ws, only in self._connections.get(owner, {}).items() if only is None or only == dispatch_id
            ]

        # Send to every socket at once, each with a time limit. Sequential
        # sends let one tab on a poor connection delay everyone else, and the
        # Redis subscriber awaits this for every event on the instance, so a
        # stalled socket held up all hospitals' live feeds.
        results = await asyncio.gather(
            *(asyncio.wait_for(ws.send_text(payload), timeout=SEND_TIMEOUT_SECONDS) for ws in targets),
            return_exceptions=True,
        )
        dead = [ws for ws, result in zip(targets, results, strict=True) if isinstance(result, BaseException)]
        if dead:
            async with self._lock:
                conns = self._connections.get(owner, {})
                for ws in dead:
                    conns.pop(ws, None)

    # Fan-out across instances --------------------------------------
    #
    # A Twilio callback can land on a different instance than the hospital's
    # dashboard socket. With Redis, every event is published to one channel and
    # each instance delivers it to its own sockets. If Redis is not configured,
    # or this instance's subscriber is not up yet, the event is delivered
    # locally only.

    PUBSUB_CHANNEL = "haemnet:dashboard-events"

    async def _emit(self, dispatch_id: str, payload: str) -> None:

        client = redis_client.get_redis()
        if client is not None and self._pubsub_ready:
            try:
                await client.publish(self.PUBSUB_CHANNEL, json.dumps({"d": dispatch_id, "p": payload}))
                return
            except Exception as exc:
                logger.warning("Redis publish failed (%s); delivering locally", type(exc).__name__)
        await self._deliver(dispatch_id, payload)

    async def start_pubsub(self) -> None:
        """Begin delivering events published by any instance. No-op without Redis."""

        if redis_client.get_redis() is None or self._pubsub_task is not None:
            return
        ready = asyncio.Event()
        self._pubsub_task = asyncio.create_task(self._pubsub_loop(ready))
        try:
            await asyncio.wait_for(ready.wait(), timeout=3)
        except TimeoutError:
            logger.warning("Redis subscriber is not ready yet; events are local until it connects")

    async def stop_pubsub(self) -> None:
        task, self._pubsub_task = self._pubsub_task, None
        self._pubsub_ready = False
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _pubsub_loop(self, ready: asyncio.Event) -> None:

        delay = 1.0
        while True:
            pubsub = None
            try:
                pubsub = redis_client.get_redis().pubsub()
                await pubsub.subscribe(self.PUBSUB_CHANNEL)
                self._pubsub_ready = True
                ready.set()
                delay = 1.0
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        event = json.loads(message["data"])
                        await self._deliver(event["d"], event["p"])
                    except Exception as exc:  # one bad event must not stop the feed
                        logger.warning("Dropped a malformed dashboard event (%s)", type(exc).__name__)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Redis subscriber lost (%s); retrying in %.0fs", type(exc).__name__, delay)
            finally:
                self._pubsub_ready = False
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        logger.debug("Closing the Redis subscription failed", exc_info=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def broadcast(self, dispatch_id: str, update: DonorStatusUpdate) -> None:
        """
        Send a donor status update to the owning hospital's dashboards.
        Stamps it with its dispatch_id and event time so a dashboard watching
        several emergencies can route each update.
        """
        update = update.model_copy(
            update={
                "dispatch_id": dispatch_id,
                "timestamp": update.timestamp or datetime.now(timezone.utc).isoformat(),
            }
        )
        await self._emit(dispatch_id, update.model_dump_json())

    async def broadcast_raw(self, dispatch_id: str, data: dict) -> None:
        """Send a raw dict payload to the owning hospital's dashboards."""
        data = {
            "dispatch_id": dispatch_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        await self._emit(dispatch_id, json.dumps(data))


# Singleton — import and use from anywhere in the backend.
manager = DashboardConnectionManager()


async def _authenticate(websocket: WebSocket) -> Optional[str]:
    """Wait for the auth message and return the hospital ID, or None."""

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        message = json.loads(raw)
    except (TimeoutError, json.JSONDecodeError, TypeError):
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
        except Exception:  # the client may already be gone; nothing else to do
            logger.debug("Could not tell the client its sign-in failed", exc_info=True)
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
