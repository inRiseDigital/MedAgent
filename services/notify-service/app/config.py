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
    # Split-horizon (02): public issuer validated in `iss`; internal URL for JWKS fetch.
    keycloak_issuer: str = "https://localhost/auth/realms/medagent"
    keycloak_internal_url: str = "http://keycloak:8080/auth/realms/medagent"
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

    # Reminders (FR-15.1/5.4): scan FHIR for upcoming appointments and notify.
    fhir_base_url: str = "http://fhir:8080/fhir"
    reminder_interval_seconds: int = 3600  # scan cadence
    reminder_lookahead_days: int = 120  # notify for booked appointments within this window
    reminder_quiet_start_hour: int = 20  # 20:00–08:00 local quiet hours (agents/08)
    reminder_quiet_end_hour: int = 8
    reminders_enabled: bool = False  # off by default; the scheduled loop opts in per env
