"""Settings for notify-service (stateless: Redis only, no database — 01 §1)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "notify-service"
    log_level: str = "INFO"

    redis_url: str = "redis://localhost:6379/0"

    # AuthN (02). notify-service is bearer-only: it never logs users in.
    keycloak_issuer: str = "http://localhost:8081/realms/medagent"
    auth_disabled: bool = Field(
        default=False,
        description="Local bootstrapping escape hatch ONLY. Never true outside local dev.",
    )
    jwks_cache_ttl_seconds: int = 300

    # SSE ticket + stream behaviour (02 §11). notify-service owns the whole
    # ticket lifecycle: issuance (ticket.py) mints a single-use opaque ticket
    # with this TTL; redemption (stream.py) opens the stream, heartbeats every
    # 15 s, and closes after a 15-min max age (client reconnects with a fresh
    # ticket).
    sse_ticket_ttl_seconds: int = 30
    sse_heartbeat_seconds: int = 15
    sse_max_age_seconds: int = 900

    # Email adapter — mailpit in dev (10 §2.1).
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "noreply@medagent.local"
