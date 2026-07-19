"""Settings for core-api, loaded from environment via pydantic-settings.

Secrets are injected at deploy time (SOPS vault, 10 §5); `.env` is for local
development only and must contain dummy values.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "core-api"
    log_level: str = "INFO"

    # Core dependencies (01 §1).
    database_url: str = Field(
        default="postgresql+asyncpg://core_api:dummy-password@localhost:5432/app_db",
        description="app_db DSN (async, asyncpg). Alembic is the only schema mechanism (10 §9).",
    )
    redis_url: str = "redis://localhost:6379/0"
    fhir_base_url: str = "http://localhost:8080/fhir"

    # AuthN (02).
    keycloak_issuer: str = "http://localhost:8081/realms/medagent"
    auth_disabled: bool = Field(
        default=False,
        description="Local bootstrapping escape hatch ONLY. Never true outside local dev.",
    )
    jwks_cache_ttl_seconds: int = 300

    # Face-service webhook (05 §3). JSON object {key_id: secret} — dual keys during rotation.
    face_webhook_hmac_keys: dict[str, str] = Field(default_factory=dict)
    face_webhook_tolerance_seconds: int = 300
    face_event_idempotency_ttl_seconds: int = 86_400  # 24 h per 05 §3
    # Threshold policy is admin configuration per facility (FR-6.2); env default for S1.
    face_confidence_threshold: float = 0.85

    # SSE ticket issuance (02 §11).
    sse_ticket_ttl_seconds: int = 30
