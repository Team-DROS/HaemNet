"""Liveness and readiness probes."""

from __future__ import annotations

import httpx
from fastapi import APIRouter

from backend.config import settings
from backend.db_services import db_health
from backend.services import redis_client
from backend.services.file_storage import get_storage, persistent

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health_check():
    """Liveness and readiness probe, whichever data layer is configured."""
    health = await db_health()
    status = health["status"]
    return {
        "status": "healthy" if status == "connected" else "degraded",
        "service": "blood-dispatch-backend",
        "database": health["backend"],
        "database_status": status,
        # Kept so older dashboards that read this field keep working.
        health["backend"]: status,
    }


@router.get("/health/deep")
async def deep_health_check():
    """Readiness with outbound checks: database, Sarvam, Redis and document storage."""
    health = await db_health()
    checks: dict[str, bool] = {"database": health["status"] == "connected"}
    if settings.sarvam_configured:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(settings.sarvam_base_url)  # any HTTP answer means reachable
            checks["sarvam"] = True
        except httpx.HTTPError:
            checks["sarvam"] = False
    checks["twilio_configured"] = settings.twilio_configured
    redis_ok = await redis_client.ping()
    if redis_ok is not None:
        checks["redis"] = redis_ok
    checks["storage"] = await get_storage().check()
    checks["storage_persistent"] = persistent()
    healthy = checks["database"] and checks.get("sarvam", True) and checks.get("redis", True) and checks["storage"]
    return {"status": "healthy" if healthy else "degraded", "checks": checks}
