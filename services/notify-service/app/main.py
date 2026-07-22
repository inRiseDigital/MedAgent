"""notify-service application factory — stateless fan-out over Redis (01 §1)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.adapters import LoggingPushAdapter, LoggingSmsAdapter, SmtpEmailAdapter
from app.auth import JWKSCache
from app.config import Settings
from app.logging_config import configure_logging
from app.notify.reminders import run_reminders
from app.routers import notify, stream, ticket
from app.telemetry import configure_telemetry

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.service_name, settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.jwks = JWKSCache(
            settings.keycloak_internal_url or settings.keycloak_issuer,
            settings.jwks_cache_ttl_seconds,
        )
        # Adapter stubs (real SMS gateway / web push land in S5).
        app.state.sms_adapter = LoggingSmsAdapter()
        app.state.push_adapter = LoggingPushAdapter()
        app.state.email_adapter = SmtpEmailAdapter(
            settings.smtp_host, settings.smtp_port, settings.smtp_from
        )

        async def _reminder_loop() -> None:
            while True:
                await asyncio.sleep(settings.reminder_interval_seconds)
                try:
                    await run_reminders(settings, app.state)
                except Exception:  # noqa: BLE001 — never let the loop die
                    logger.exception("reminder loop error")

        reminder_task = (
            asyncio.create_task(_reminder_loop()) if settings.reminders_enabled else None
        )
        try:
            yield
        finally:
            if reminder_task:
                reminder_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reminder_task
            await app.state.redis.aclose()

    app = FastAPI(title="MedAgent notify-service", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.include_router(ticket.router)
    app.include_router(stream.router)
    app.include_router(notify.router)
    app.include_router(notify.internal_router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness: 200 whenever the process is up (10 §1)."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        """Readiness: Redis is the only dependency (stateless service)."""
        failing: list[str] = []
        try:
            await app.state.redis.ping()
        except Exception:  # noqa: BLE001 - any failure means not ready
            failing.append("redis")

        if failing:
            return JSONResponse(status_code=503, content={"status": "unready", "failing": failing})
        return JSONResponse(content={"status": "ready", "failing": []})

    configure_telemetry(app)
    return app


app = create_app()
