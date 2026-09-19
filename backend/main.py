"""
FastAPI application entry point for the AI Blood Dispatch Network.

Start the server:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import sentry_sdk
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth import router as auth_router
from backend.api.callbacks import router as callback_router
from backend.api.routes import router as api_router
from backend.api.websockets import router as ws_router
from backend.config import settings

# ── Logging ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.app_env == "development" else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage resources that need setup/teardown around the app's
    lifecycle (e.g. HTTP clients, DB connections).
    """
    logger.info("🚀  Blood Dispatch Backend starting up (env=%s)", settings.app_env)
    yield
    # Shutdown — close service clients.
    from backend.db_services import close as close_db
    from backend.db_services.mongodb import close as close_mongodb
    from backend.services.twilio_service import close as close_twilio
    from backend.services.push_service import close as close_push
    from backend.services.sarvam_service import close as close_sarvam

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
)

# ── CORS ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount Routers ─────────────────────────────────────────────────
app.include_router(api_router)
app.include_router(ws_router)
app.include_router(callback_router)
app.include_router(auth_router)


# ── Root ──────────────────────────────────────────────────────────

@app.get("/", tags=["meta"])
async def root():
    """API root — service identification."""
    return {
        "service": "AI Blood Dispatch Network",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/health",
    }
