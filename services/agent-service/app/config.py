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
    # Split-horizon (02): public issuer validated in `iss`; internal URL for JWKS fetch.
    keycloak_issuer: str = "https://localhost/auth/realms/medagent"
    keycloak_internal_url: str = "http://keycloak:8080/auth/realms/medagent"
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

    # LLM mode: "live" (real Claude), "stub" (deterministic offline model — no API
    # calls), or "openai" (any OpenAI-compatible provider — Groq / OpenRouter /
    # Cerebras / Together — for a free key when the Anthropic quota is capped).
    # Stub mode lets the chat be demoed when the provider is unavailable.
    agent_llm_mode: str = "live"

    # OpenAI-compatible fallback provider (used when agent_llm_mode == "openai").
    # The model MUST support tool/function calling (the agent is a ReAct+tools
    # graph). Example (Groq): base_url=https://api.groq.com/openai/v1,
    # model=llama-3.3-70b-versatile.
    llm_openai_base_url: str = "https://api.groq.com/openai/v1"
    llm_openai_api_key: str = ""
    llm_openai_model: str = "llama-3.3-70b-versatile"
