"""MongoDB connection lifecycle for the Neo4j migration.

This module intentionally contains no domain queries yet. It provides one
shared async client and a single place to configure connectivity while the
existing Neo4j repository remains the active implementation.
"""

from __future__ import annotations

import logging
from typing import Optional

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from backend.config import settings

logger = logging.getLogger(__name__)
_client: Optional[AsyncMongoClient] = None


def get_client() -> AsyncMongoClient:
    """Return the process-wide MongoDB client, creating it lazily."""
    global _client
    if _client is None:
        _client = AsyncMongoClient(settings.mongodb_uri, appname="haemnet-backend")
        logger.info("MongoDB client initialized")
    return _client


def get_database() -> AsyncDatabase:
    """Return the configured application database."""
    return get_client()[settings.mongodb_database]


async def ping() -> None:
    """Verify MongoDB connectivity."""
    await get_database().command("ping")


async def close() -> None:
    """Close the shared client during application shutdown."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("MongoDB client closed")
