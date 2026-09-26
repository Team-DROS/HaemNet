"""Production configuration guard rails."""

import pytest
from pydantic import ValidationError

from backend.config import Settings

ATLAS = "mongodb+srv://user:pass@cluster0.example.mongodb.net/"
SECRET = "a" * 64


def make(**overrides):
    values = {"app_env": "production", "jwt_secret": SECRET, "mongodb_uri": ATLAS, "db_backend": "mongodb"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_starts_without_twilio_or_sarvam():
    settings = make(twilio_account_sid="", twilio_auth_token="", sarvam_api_key="")
    assert settings.twilio_configured is False
    assert settings.sarvam_configured is False


def test_production_rejects_a_local_database():
    with pytest.raises(ValidationError, match="localhost"):
        make(mongodb_uri="mongodb://localhost:27017")


def test_production_rejects_placeholder_or_missing_secret():
    with pytest.raises(ValidationError, match="placeholder"):
        make(jwt_secret="change-me")
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        make(jwt_secret="  ")


def test_development_allows_local_everything():
    settings = make(app_env="development", mongodb_uri="mongodb://localhost:27017")
    assert settings.db_backend == "mongodb"


def test_twilio_counts_as_configured_only_when_complete():
    assert make(twilio_account_sid="AC1", twilio_auth_token="t", twilio_phone_number="").twilio_configured is False
    assert make(twilio_account_sid="AC1", twilio_auth_token="t", twilio_phone_number="+1202").twilio_configured is True
