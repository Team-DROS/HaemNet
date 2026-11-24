"""
FastAPI application entry point for the AI Blood Dispatch Network.

Start the server:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.admin import router as admin_router
from backend.api.auth import donor_router as donor_auth_router
from backend.api.auth import router as auth_router
from backend.api.callbacks import router as callback_router
from backend.api.contact import router as contact_router
from backend.api.dispatches import router as dispatches_router
from backend.api.donors import router as donors_router
from backend.api.errors import register_error_handlers
from backend.api.health import router as health_router
from backend.api.hospital_account import router as hospital_account_router
from backend.api.hospital_staff import router as hospital_staff_router
from backend.api.websockets import router as ws_router
from backend.config import settings
from backend.hardening import SecurityMiddleware
from backend.observability import RequestIdMiddleware, configure_logging

# ── Logging ───────────────────────────────────────────────────────

configure_logging(
    logging.DEBUG if settings.app_env == "development" else logging.INFO,
    settings.log_format.lower(),
)
logger = logging.getLogger(__name__)


# ── Sentry Setup ──────────────────────────────────────────────────
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )
    logger.info("Sentry initialized")
else:
    logger.warning("SENTRY_DSN not set. Sentry is disabled.")


# ── Lifespan (startup / shutdown) ─────────────────────────────────


def _warn_if_uvloop() -> None:
    """
    PyMongo's async client does not work on uvloop: server selection never
    completes and every request hangs. uvicorn picks uvloop by default when
    it is installed, so run it with `--loop asyncio` (the Dockerfile does).
    """
    if settings.db_backend != "mongodb":
        return
    try:
        loop_module = type(asyncio.get_running_loop()).__module__
    except RuntimeError:
        return
    if "uvloop" in loop_module:
        logger.error(
            "Running on uvloop with the MongoDB backend: requests will hang. Start the server with `--loop asyncio`."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage resources that need setup/teardown around the app's
    lifecycle (e.g. HTTP clients, DB connections).
    """
    logger.info(
        "🚀  Blood Dispatch Backend starting up (env=%s, database=%s)",
        settings.app_env,
        settings.db_backend,
    )
    _warn_if_uvloop()
    logger.info(
        "Voice interpretation mode=%s model=%s",
        settings.voice_intent_mode,
        settings.voice_intent_model if settings.voice_intent_mode == "ai" else "keywords",
    )
    if settings.app_env.lower() in {"production", "staging"} and not settings.s3_bucket:
        logger.warning(
            "S3_BUCKET is not set: hospital documents are stored on local disk and are lost "
            "on hosts with an ephemeral disk (for example Render free). Set S3_BUCKET for production."
        )
    if not settings.twilio_configured:
        logger.warning("Twilio is not configured: AI voice calls are disabled.")
    if not settings.sarvam_configured:
        logger.warning("Sarvam AI is not configured: the voice agent cannot speak or listen.")
    try:
        from backend.db_services import ensure_indexes

        await ensure_indexes()
    except Exception as exc:  # the app still starts; /api/health reports the problem
        logger.error("Could not prepare database indexes: %s", exc)
    from backend.api.websockets import manager as ws_manager

    await ws_manager.start_pubsub()
    yield
    await ws_manager.stop_pubsub()
    # Shutdown — close service clients.
    from backend.db_services import close as close_db
    from backend.db_services.mongodb import close as close_mongodb
    from backend.services.push_service import close as close_push
    from backend.services.redis_client import close as close_redis
    from backend.services.sarvam_service import close as close_sarvam
    from backend.services.twilio_service import close as close_twilio

    await close_redis()
    await close_twilio()
    await close_sarvam()
    await close_push()
    await close_db()
    await close_mongodb()
    logger.info("🛑  Blood Dispatch Backend shut down cleanly.")


# ── App Factory ───────────────────────────────────────────────────

app = FastAPI(
    title="AI Blood Dispatch Network",
    description=(
        "Real-time, AI-orchestrated emergency blood dispatch system. "
        "Queries the donor database for eligible donors, orchestrates "
        "concurrent multilingual AI voice calls, and streams live status "
        "updates to hospital dashboards via WebSocket."
    ),
    version="0.1.0",
    lifespan=lifespan,
    # Interactive API docs list every endpoint; keep them off in production.
    docs_url=None if settings.app_env.lower() == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.app_env.lower() == "production" else "/openapi.json",
)

register_error_handlers(app)

app.add_middleware(SecurityMiddleware)
app.add_middleware(RequestIdMiddleware)

# ── CORS ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount Routers ─────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(dispatches_router)
app.include_router(donors_router)
app.include_router(ws_router)
app.include_router(callback_router)
app.include_router(auth_router)
app.include_router(donor_auth_router)
app.include_router(hospital_account_router)
app.include_router(hospital_staff_router)
app.include_router(admin_router)
app.include_router(contact_router)


# ── Root ──────────────────────────────────────────────────────────


@app.get("/", tags=["meta"])
async def root():
    """API root — service identification."""
    return {
        "service": "AI Blood Dispatch Network",
        "version": "0.1.0",
        "docs": None if settings.app_env.lower() == "production" else "/docs",
        "health": "/api/health",
        "voice_intent_mode": settings.voice_intent_mode,
        "voice_intent_model": settings.voice_intent_model if settings.voice_intent_mode == "ai" else None,
    }
