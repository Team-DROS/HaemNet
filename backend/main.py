"""
FastAPI application entry point for the AI Blood Dispatch Network.

Start the server:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
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
from backend.api.websockets import manager as ws_manager
from backend.api.websockets import router as ws_router
from backend.config import settings
from backend.db_services import close as close_database
from backend.db_services import ensure_indexes
from backend.db_services.mongodb import close as close_mongodb
from backend.hardening import SecurityMiddleware
from backend.observability import RequestIdMiddleware, configure_logging
from backend.services.call_retry import run_worker as run_retry_worker
from backend.services.push_service import close as close_push
from backend.services.redis_client import close as close_redis
from backend.services.sarvam_service import close as close_sarvam
from backend.services.telephony import get_telephony

logger = logging.getLogger(__name__)

SERVICE_NAME = "AI Blood Dispatch Network"
SERVICE_VERSION = "0.1.0"


def _is_production() -> bool:
    return settings.app_env.lower() == "production"


# ── Startup and shutdown steps ────────────────────────────────────


def _configure_sentry() -> None:
    if not settings.sentry_dsn:
        logger.warning("SENTRY_DSN not set. Sentry is disabled.")
        return
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=settings.sentry_traces_sample_rate)
    logger.info("Sentry initialized")


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


def _log_startup_configuration() -> None:
    """Say what is and is not configured, so a misconfigured deploy is obvious from the logs."""
    logger.info("Starting up (env=%s, database=%s)", settings.app_env, settings.db_backend)
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


async def _prepare_database() -> None:
    try:
        await ensure_indexes()
    except Exception as exc:  # the app still starts; /api/health reports the problem
        logger.error("Could not prepare database indexes: %s", exc)


async def _close_clients() -> None:
    await close_redis()
    await get_telephony().close()
    await close_sarvam()
    await close_push()
    await close_database()
    await close_mongodb()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Set up resources before serving and release them on shutdown."""
    get_telephony()  # fail at startup, not on the first emergency, if TELEPHONY_PROVIDER is misspelt
    _log_startup_configuration()
    _warn_if_uvloop()
    await _prepare_database()
    await ws_manager.start_pubsub()
    stopped = asyncio.Event()
    worker = (
        asyncio.create_task(run_retry_worker(ws_manager.broadcast, stopped))
        if settings.db_backend == "mongodb" and settings.call_max_retries > 0
        else None
    )
    try:
        yield
    finally:
        stopped.set()
        if worker:
            await worker
        await ws_manager.stop_pubsub()
        await _close_clients()
    logger.info("Shut down cleanly.")


# ── App factory ───────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build the application. Settings are read when this is called."""
    configure_logging(logging.DEBUG if settings.app_env == "development" else logging.INFO, settings.log_format.lower())
    _configure_sentry()

    application = FastAPI(
        title=SERVICE_NAME,
        description=(
            "Real-time, AI-orchestrated emergency blood dispatch system. "
            "Finds eligible donors, orchestrates concurrent multilingual AI voice calls, "
            "and streams live status updates to hospital dashboards via WebSocket."
        ),
        version=SERVICE_VERSION,
        lifespan=lifespan,
        # Interactive API docs list every endpoint; keep them off in production.
        docs_url=None if _is_production() else "/docs",
        redoc_url=None,
        openapi_url=None if _is_production() else "/openapi.json",
    )

    register_error_handlers(application)

    # Added innermost first: a request meets CORS, then request IDs, then security headers and size limits.
    application.add_middleware(SecurityMiddleware)
    application.add_middleware(RequestIdMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        health_router,
        dispatches_router,
        donors_router,
        ws_router,
        callback_router,
        auth_router,
        donor_auth_router,
        hospital_account_router,
        hospital_staff_router,
        admin_router,
        contact_router,
    ):
        application.include_router(router)

    @application.get("/", tags=["meta"])
    async def root() -> dict:
        """Service identification."""
        return {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "docs": None if _is_production() else "/docs",
            "health": "/api/health",
            "voice_intent_mode": settings.voice_intent_mode,
            "voice_intent_model": settings.voice_intent_model if settings.voice_intent_mode == "ai" else None,
        }

    return application


app = create_app()
