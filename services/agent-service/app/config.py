"""Settings for agent-service, loaded from environment via pydantic-settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "agent-service"
    log_level: str = "INFO"

    # LangGraph Postgres checkpointer lives in app_db (04 §1); its tables are
    # created via Alembic revisions in core-api's tree (10 §9 rule 4), never here.
    database_url: str = Field(
        default="postgresql://agent_service:dummy-password@localhost:5432/app_db",
        description="app_db DSN for the LangGraph checkpointer (plain DSN).",
    )
    redis_url: str = "redis://localhost:6379/0"

    # All clinical reads/writes go through FHIR via core-api's decision-checked
    # path (04 §1) — these are the S3 wiring targets.
    fhir_base_url: str = "http://localhost:8080/fhir"
    core_api_base_url: str = "http://localhost:8001"

    # AuthN (02).
    keycloak_issuer: str = "http://localhost:8081/realms/medagent"
    auth_disabled: bool = Field(
        default=False,
        description="Local bootstrapping escape hatch ONLY. Never true outside local dev.",
    )
    jwks_cache_ttl_seconds: int = 300

    # Anthropic (04 §4): pinned model ID, low clinical temperature. The pin is
    # verified against the API at startup from S3 (replacing the prototype's
    # unpinned model string).
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_temperature: float = 0.2
