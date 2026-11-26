"""
Centralised application settings loaded from environment variables.

Uses pydantic-settings so every value can be overridden via a `.env`
file sitting next to this module or via real env vars in production.
"""

from __future__ import annotations

import json
from typing import List, Literal

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
    # Fail fast instead of hanging 30 seconds when MongoDB is unreachable.
    mongodb_server_selection_timeout_ms: int = 5000
    mongodb_max_pool_size: int = 100

    # Which data layer to use: "mongodb" (default) or "neo4j".
    db_backend: str = "mongodb"

    # ── Twilio Telephony ────────────────────────────────────────
    # Which telephony provider places calls and sends SMS (see backend/services/telephony.py).
    telephony_provider: str = "twilio"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    sentry_dsn: str = ""
    # Share of requests traced by Sentry (0 to 1). Tracing every request is costly at scale.
    sentry_traces_sample_rate: float = 0.1

    # ── Sarvam AI (STT / TTS) ────────────────────────────────────
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    # Roll out explicitly; legacy preserves the original keyword pipeline.
    voice_intent_mode: Literal["legacy", "ai"] = "legacy"
    voice_intent_model: str = "sarvam-105b"

    # ── App Settings ─────────────────────────────────────────────
    app_env: str = "development"
    # "text" (default) or "json" for one JSON object per log line
    log_format: str = "text"
    jwt_secret: str
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:19006", "http://localhost:8081"]
    server_base_url: str = "http://localhost:8000"

    # ── Redis (shared limits and live-update fan-out across instances) ──
    # Empty keeps everything in process memory (fine for a single instance).
    redis_url: str = ""

    # ── Outbound call pacing ─────────────────────────────────────
    # Twilio starts calls from API requests; firing 50 at once can trigger 429s.
    # This spaces call starts per backend instance (divide by instance count).
    twilio_calls_per_second: float = 10.0
    max_request_body_kb: int = 256

    # ── Retrying calls that were not answered ────────────────────
    # A busy line or no answer is retried this many times, this long after the first attempt.
    # 0 turns retries off. Retries are scheduled in the instance that received the status callback
    # and are lost if it restarts in the meantime.
    call_max_retries: int = 1
    call_retry_delay_seconds: int = 180

    # ── Call cost guards ─────────────────────────────────────────
    # Most donors called for one request, and most requests per hospital per day.
    max_donors_per_dispatch: int = 50
    max_dispatches_per_hospital_day: int = 30

    # ── Donor phone verification (one-time code by SMS) ──────────
    # When true, creating a donor account needs a verified phone number. Keep false until the
    # donor app sends the code (POST /api/donor/auth/otp/request and /verify).
    donor_otp_required: bool = False
    otp_ttl_seconds: int = 600
    otp_max_attempts: int = 5

    # ── Hospital platform (verification, admin, uploads, email) ──
    # Admin sign-in is disabled until both values are set. Generate the hash with
    # python -c "import bcrypt;print(bcrypt.hashpw(b'PASSWORD', bcrypt.gensalt()).decode())"
    admin_username: str = ""
    admin_password_hash: str = ""
    dashboard_url: str = "http://localhost:8081"
    upload_dir: str = "uploads"
    # Private S3 or Cloudflare R2 bucket for licence documents. When S3_BUCKET is set it
    # replaces local disk. For R2 set S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
    # and S3_REGION=auto. Leave the keys empty on AWS to use the instance role.
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = "hospital-documents/"
    max_upload_mb: int = 5
    # Brevo HTTPS API works where outbound SMTP is blocked.
    brevo_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    # Cloudflare Turnstile secret. Empty disables the bot check (development).
    turnstile_secret: str = ""
    # Where contact form messages are delivered.
    contact_to: str = ""

    # ── Expo Push Notifications ──────────────────────────────────
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    # Also alert donors who have the app when a request first goes out, alongside the call.
    # The call stays the primary channel; a push only brings the request up on screen sooner.
    push_request_alerts: bool = True

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
    def validate_runtime_configuration(self) -> Settings:
        """
        Reject configuration that would be insecure or broken outside development.

        Only the essentials are mandatory: a real JWT secret and a reachable,
        non-local database. Twilio and Sarvam are optional so the dashboard
        can go live before those accounts exist; without them AI calls are
        disabled and the app says so at startup and in
        `python -m backend.tools.check_config`.
        """
        if self.app_env.lower() in {"production", "staging"}:
            required = {
                "JWT_SECRET": self.jwt_secret,
                **(
                    {"MONGODB_URI": self.mongodb_uri}
                    if self.db_backend == "mongodb"
                    else {"NEO4J_PASSWORD": self.neo4j_password}
                ),
            }
            missing = [name for name, value in required.items() if not (value or "").strip()]
            if missing:
                raise ValueError(f"Missing required production configuration: {', '.join(missing)}")
            if self.jwt_secret in {"change-me", "secret", "your-secret-key", "replace-with-a-long-random-secret"}:
                raise ValueError("JWT_SECRET must be changed from its placeholder value")
            if len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be at least 32 characters in staging and production")
            if self.db_backend == "mongodb" and any(host in self.mongodb_uri for host in ("localhost", "127.0.0.1")):
                raise ValueError("MONGODB_URI points at localhost; use the Atlas connection string in production")
        return self

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def email_configured(self) -> bool:
        return bool((self.brevo_api_key and self.smtp_from) or self.smtp_configured)

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_username and self.admin_password_hash)

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_phone_number)

    @property
    def sarvam_configured(self) -> bool:
        return bool(self.sarvam_api_key)


# Singleton instance — import this everywhere.
settings = Settings()
