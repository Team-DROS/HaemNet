"""
Pydantic models that enforce the strict JSON data-contracts
defined in the System Architecture Manifest.

Every payload flowing between frontend ↔ backend ↔ telephony
MUST be validated through one of these schemas.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────

class Urgency(str, Enum):
    """Allowed urgency levels for a dispatch request."""
    ROUTINE = "routine"
    URGENT = "urgent"
    CRITICAL = "critical"


class CallStatus(str, Enum):
    """
    Possible states a donor can be in during a dispatch, in lifecycle order:

        ringing -> answered -> accepted -> en_route -> donated
                           \\-> declined
        ringing -> no_answer

    ``completed`` is kept for backward compatibility with older clients and
    means the same as ``en_route`` (the donor has been sent directions).
    """
    RINGING = "ringing"
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EN_ROUTE = "en_route"
    DONATED = "donated"
    COMPLETED = "completed"


# States after which telephony events (answered / no-answer) must not
# overwrite the donor's status. Twilio webhooks can arrive late.
TERMINAL_OR_DECIDED = {
    CallStatus.ACCEPTED,
    CallStatus.DECLINED,
    CallStatus.EN_ROUTE,
    CallStatus.DONATED,
    CallStatus.COMPLETED,
}


class DonorLanguage(str, Enum):
    """Languages supported for AI voice conversations."""
    TAMIL = "tamil"
    HINDI = "hindi"
    ENGLISH = "english"


def normalise_language(value: Optional[str]) -> str:
    """
    Map any stored or submitted language onto one the voice pipeline supports.

    Donors registered through older app builds could pick languages the voice
    pipeline has no prompts for (e.g. Telugu). Rejecting those records would
    make ``find_eligible_donors`` fail and break every dispatch in the area,
    so unsupported values fall back to English instead.
    """
    lang = (value or "").strip().lower()
    if lang in {l.value for l in DonorLanguage}:
        return lang
    if lang:
        logger.warning("Unsupported donor language %r; using english", value)
    return DonorLanguage.ENGLISH.value


# ── Request / Response Schemas ────────────────────────────────────

class Coordinates(BaseModel):
    """Geographic coordinates of the requesting hospital."""
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class DispatchRequest(BaseModel):
    """
    Trigger Payload (Frontend → Backend).
    Sent by the Hospital Web App to initiate an emergency dispatch.
    """
    hospital_id: str = Field(..., min_length=1, description="Unique hospital identifier")
    blood_group: str = Field(..., min_length=1, description="Required blood group, e.g. 'O-'")
    urgency: Urgency = Field(..., description="Urgency level of the request")
    coordinates: Coordinates
    address: Optional[str] = Field(None, description="Text address of the hospital")
    patient_name: Optional[str] = Field(None, description="Name of the patient")
    units: int = Field(1, ge=1, le=20, description="Units of blood required")


class DispatchResponse(BaseModel):
    """Acknowledgement returned after a dispatch is successfully queued."""
    dispatch_id: str = Field(..., description="Unique ID for this dispatch session")
    donors_matched: int = Field(..., ge=0, description="Number of eligible donors found")
    message: str = Field(default="Dispatch initiated")
    created_at: Optional[str] = Field(None, description="UTC ISO timestamp the dispatch was created")


class DonorStatusUpdate(BaseModel):
    """
    WebSocket Update Payload (Backend → Frontend).
    Streamed to the Hospital Dashboard in real-time as calls progress.

    ``dispatch_id`` and ``timestamp`` are filled in by the connection manager
    at broadcast time, so every message says which emergency it belongs to.
    ``distance_km`` and ``language`` are sent with the first (ringing) update;
    later updates may omit them and clients should keep the earlier values.
    """
    donor_id: str = Field(..., description="Unique donor identifier")
    name: str = Field(..., description="Donor display name")
    status: CallStatus = Field(..., description="Current call status")
    eta_minutes: Optional[int] = Field(None, ge=0, description="Estimated arrival time in minutes")
    dispatch_id: Optional[str] = Field(None, description="Dispatch this update belongs to")
    distance_km: Optional[float] = Field(None, ge=0, description="Donor distance from the hospital")
    language: Optional[str] = Field(None, description="Language the AI speaks with this donor")
    timestamp: Optional[str] = Field(None, description="UTC ISO time the event happened")


# ── Internal Domain Models ────────────────────────────────────────

class DonorNode(BaseModel):
    """
    Mirrors the Donor Node properties stored in Neo4j.
    Used internally — never exposed directly to the frontend.
    """
    id: UUID
    name: str
    phone: str
    blood_group: str
    language: DonorLanguage
    location: Coordinates
    has_app: bool = False
    last_donated_date: Optional[datetime] = None

    @field_validator("language", mode="before")
    @classmethod
    def _coerce_language(cls, v):
        return normalise_language(v.value if isinstance(v, DonorLanguage) else v)

    @property
    def is_eligible(self) -> bool:
        """Check the 56-day (8-week) medical cooldown rule."""
        if self.last_donated_date is None:
            return True
        last = self.last_donated_date
        if last.tzinfo is None:  # Neo4j datetimes are aware; older payloads may be naive UTC
            last = last.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last
        return delta.days > 56


class DonationLog(BaseModel):
    """Payload sent when hospital staff logs a successful donation."""
    donor_id: str = Field(..., description="Donor whose donation is being recorded")
    hospital_id: str = Field(..., description="Hospital where the donation occurred")
    notes: Optional[str] = Field(None, description="Optional clinical notes")
    dispatch_id: Optional[str] = Field(
        None, description="Dispatch the donation fulfils; lets the request auto-close"
    )


class DonorResponse(BaseModel):
    """A donor accepting or declining a request from the mobile app."""
    dispatch_id: str = Field(..., min_length=1)
    phone: Optional[str] = Field(None, description="Optional; the signed-in donor's phone is used")
    accept: bool


class DonorRegistration(BaseModel):
    """Payload from mobile app to register/update a donor."""
    name: str = Field(..., description="Donor's full name")
    phone: str = Field(..., description="Donor's phone number")
    blood_group: str = Field(..., description="Blood group (e.g. O+)")
    language: str = Field(default="english", description="Preferred language for AI voice")
    lat: float = Field(..., description="Latitude")
    lng: float = Field(..., description="Longitude")
