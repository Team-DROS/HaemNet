"""Pure logic: geography, language handling, schemas, Twilio status mapping."""

from backend.api.callbacks import map_twilio_status
from backend.db_services import _REGISTER_DONOR_QUERY
from backend.schemas.models import (
    CallStatus,
    DonorLanguage,
    DonorNode,
    DonorStatusUpdate,
    normalise_language,
)
from backend.services.geo import estimate_eta_minutes, haversine_km


# ── geo ───────────────────────────────────────────────────────────

def test_haversine_one_degree_of_latitude():
    assert abs(haversine_km(13.0, 80.0, 14.0, 80.0) - 111.19) < 0.1


def test_haversine_same_point_is_zero():
    assert haversine_km(13.08, 80.27, 13.08, 80.27) == 0


def test_eta_estimate_grows_with_distance_and_handles_missing():
    assert estimate_eta_minutes(None) is None
    near, far = estimate_eta_minutes(1.0), estimate_eta_minutes(8.0)
    assert near < far
    assert near >= 5  # always includes preparation time


# ── language ──────────────────────────────────────────────────────

def test_supported_languages_pass_through_case_insensitively():
    assert normalise_language("Tamil") == "tamil"
    assert normalise_language("HINDI") == "hindi"


def test_unsupported_language_falls_back_to_english():
    assert normalise_language("telugu") == "english"
    assert normalise_language("") == "english"
    assert normalise_language(None) == "english"


def test_donor_with_unsupported_language_does_not_break_matching():
    # Older app builds let donors pick Telugu; this used to raise and fail
    # the whole dispatch for every donor in the area.
    node = DonorNode(
        id="6f1c7d2e-0b1a-4c9e-9f3a-2d4e5f6a7b8c", name="R", phone="+911234567890",
        blood_group="O-", language="telugu", location={"lat": 13, "lng": 80},
    )
    assert node.language == DonorLanguage.ENGLISH


# ── schemas ───────────────────────────────────────────────────────

def test_status_update_new_fields_are_optional():
    update = DonorStatusUpdate(donor_id="d1", name="R", status=CallStatus.RINGING)
    body = update.model_dump()
    assert body["dispatch_id"] is None and body["distance_km"] is None


def test_lifecycle_statuses_exist():
    for value in ["ringing", "answered", "no_answer", "accepted", "declined", "en_route", "donated"]:
        CallStatus(value)


# ── Twilio mapping ────────────────────────────────────────────────

def test_answered_and_no_answer_are_distinguished_from_decline():
    assert map_twilio_status("in-progress", "ringing") == CallStatus.ANSWERED
    assert map_twilio_status("no-answer", "ringing") == CallStatus.NO_ANSWER
    assert map_twilio_status("busy", "ringing") == CallStatus.NO_ANSWER
    assert map_twilio_status("failed", "ringing") == CallStatus.DECLINED


def test_unknown_twilio_status_is_ignored_not_declined():
    assert map_twilio_status("something-new", "ringing") is None
    assert map_twilio_status("ringing", "ringing") is None


def test_late_webhook_never_overwrites_a_decision():
    assert map_twilio_status("in-progress", "accepted") is None
    assert map_twilio_status("no-answer", "en_route") is None
    assert map_twilio_status("in-progress", "declined") is None


# ── cooldown regression ───────────────────────────────────────────

def test_reregistration_preserves_last_donation_date():
    # Editing a donor profile used to SET last_donated_date = null, lifting
    # the 56-day cooldown. The query must keep the existing value.
    assert "coalesce(datetime($last_donated_date), d.last_donated_date)" in _REGISTER_DONOR_QUERY
