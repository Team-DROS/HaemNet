"""
Centralised application settings loaded from environment variables.

Uses pydantic-settings so every value can be overridden via a `.env`
file sitting next to this module or via real env vars in production.
"""

from __future__ import annotations

import json
from typing import List
from pydantic import field_validator, model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All external configuration the backend needs at runtime."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Neo4j AuraDB ──────────────────────────────────────────────
    neo4j_uri: str = "neo4j+s://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── MongoDB (default data store) ─────────────────────────────
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "haemnet"

    # Which data layer to use: "mongodb" (default) or "neo4j".
    db_backend: str = "mongodb"

    # ── Twilio Telephony ────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    
    sentry_dsn: str = ""

    # ── Sarvam AI (STT / TTS) ────────────────────────────────────
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"

    # ── App Settings ─────────────────────────────────────────────
    app_env: str = "development"
    jwt_secret: str
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:19006", "http://localhost:8081"]
    server_base_url: str = "http://localhost:8000"

    # ── Expo Push Notifications ──────────────────────────────────
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"

    # ── Twilio Audio Streaming ───────────────────────────────────
    twilio_audio_ws_path: str = "/ws/twilio/audio-stream"

    # pydantic-settings doesn't auto-parse JSON lists from env vars,
    # so we accept a raw string and coerce it ourselves.
    @field_validator("db_backend", mode="before")
    @classmethod
    def parse_db_backend(cls, v: str) -> str:
        value = (v or "mongodb").strip().lower()
        if value not in {"mongodb", "neo4j"}:
            raise ValueError('DB_BACKEND must be "mongodb" or "neo4j"')
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | List[str]) -> List[str]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except json.JSONDecodeError as exc:
                raise ValueError("CORS_ORIGINS must be a JSON array") from exc
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise ValueError("CORS_ORIGINS must be a JSON array of strings")
            return parsed
        return v

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        """
        Reject configuration that would be insecure or broken outside development.

        Only the essentials are mandatory: a real JWT secret and a reachable,
        non-local database. Twilio and Sarvam are optional so the dashboard can
        go live before the telephony account exists; without them AI calls and
        SMS sign-in codes are disabled and the app says so at startup and in
        `python -m backend.tools.check_config`.
        """
        if self.app_env.lower() in {"production", "staging"}:
            required = {
                "JWT_SECRET": self.jwt_secret,
                **({"MONGODB_URI": self.mongodb_uri}
                   if self.db_backend == "mongodb" else
                   {"NEO4J_PASSWORD": self.neo4j_password}),
            }
            missing = [name for name, value in required.items() if not (value or "").strip()]
            if missing:
                raise ValueError(
                    f"Missing required production configuration: {', '.join(missing)}"
                )
            if self.jwt_secret in {"change-me", "secret", "your-secret-key", "replace-with-a-long-random-secret"}:
                raise ValueError("JWT_SECRET must be changed from its placeholder value")
            if self.db_backend == "mongodb" and any(
                host in self.mongodb_uri for host in ("localhost", "127.0.0.1")
            ):
                raise ValueError("MONGODB_URI points at localhost; use the Atlas connection string in production")
        return self

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_phone_number)

    @property
    def sarvam_configured(self) -> bool:
        return bool(self.sarvam_api_key)


# Singleton instance — import this everywhere.
settings = Settings()
