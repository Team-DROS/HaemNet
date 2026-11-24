"""Licence and registration documents a hospital uploads for review."""

from __future__ import annotations

import logging
import uuid

from backend.config import settings
from backend.services import hospital_platform as hp
from backend.services.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaError,
)
from backend.services.file_storage import get_storage

logger = logging.getLogger(__name__)


def max_upload_bytes() -> int:
    return settings.max_upload_mb * 1024 * 1024


async def store_document(hospital_id: str, kind: str, filename: str | None, data: bytes) -> dict:
    """Validate and store one document, returning its public description.

    The type is decided from the file's own signature (PDF, JPG or PNG), never from the name the client gave.
    """
    if kind not in hp.DOC_KINDS:
        raise InvalidInputError(f"kind must be one of: {', '.join(hp.DOC_KINDS)}")
    hospital = await hp.repo.get(hospital_id)
    if not hospital:
        raise NotFoundError("Hospital not found")
    if len(hospital.get("documents", [])) >= hp.MAX_DOCS:
        raise ConflictError(f"You can upload at most {hp.MAX_DOCS} documents")
    if len(data) > max_upload_bytes():
        raise PayloadTooLargeError(f"File is larger than {settings.max_upload_mb} MB")
    if not data:
        raise InvalidInputError("The file is empty")
    detected = hp.detect_file_type(data)
    if detected is None:
        raise UnsupportedMediaError("Only PDF, JPG or PNG files are accepted")
    ext, mime = detected

    try:
        key = await get_storage().save(hospital_id, ext, data, mime)
    except Exception as exc:
        logger.error("Document storage failed for %s: %s", hospital_id, type(exc).__name__)
        raise ServiceUnavailableError("Could not store the file right now. Please try again.") from exc

    document = {
        "id": uuid.uuid4().hex, "kind": kind, "key": key, "content_type": mime, "size": len(data),
        "filename": (filename or f"document.{ext}")[:120], "uploaded_at": hp.now_iso(),
    }
    await hp.repo.push_document(hospital_id, document)
    await hp.record(hospital_id, "hospital", "document_uploaded", kind)
    return hp.public_document(document)


async def read_document(hospital_id: str, doc_id: str) -> tuple[dict, bytes]:
    """A stored document's metadata and bytes, or NotFoundError."""
    hospital = await hp.repo.get(hospital_id)
    if not hospital:
        raise NotFoundError("Hospital not found")
    doc = next((d for d in hospital.get("documents", []) if d["id"] == doc_id), None)
    try:
        content = await get_storage().load(doc["key"]) if doc else None
    except Exception as exc:
        logger.error("Document read failed for %s: %s", hospital_id, type(exc).__name__)
        raise ServiceUnavailableError("Could not read the file right now. Please try again.") from exc
    if doc is None or content is None:
        raise NotFoundError("Document not found")
    return doc, content
