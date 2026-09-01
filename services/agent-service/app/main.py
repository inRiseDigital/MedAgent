"""agent-service application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.auth import JWKSCache
from app.config import Settings
from app.logging_config import configure_logging
from app.routers import chat, feedback, rx_safety, vision
from app.telemetry import configure_telemetry

API_V1_PREFIX = "/api/v1"

logger = logging.getLogger("agent-service")


def _plain_dsn(url: str) -> str:
    """Normalise SQLAlchemy-style DSNs (postgresql+asyncpg://) for asyncpg."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _verify_model_config(settings: Settings) -> None:
    """Startup model-pin check (04 §4). NON-FATAL by design — an LLM outage must
    never stop the service (readyz stays up; chat degrades to the graceful floor).
    Surfaces a misconfiguration (unknown mode, missing key, unpinned model) as a
    clear boot-time log so it is caught before it silently degrades every turn."""
    mode = settings.agent_llm_mode
    if mode == "live":
        if not settings.anthropic_model:
            logger.error("model-pin: agent_llm_mode=live but anthropic_model is empty (unpinned)")
        elif not settings.anthropic_api_key:
            logger.warning(
                "model-pin: live mode with no ANTHROPIC_API_KEY — chat degrades to the "
                "graceful fallback until a key is provided")
        else:
            logger.info("model-pin: live mode, pinned model=%s temp=%s",
                        settings.anthropic_model, settings.anthropic_temperature)
    elif mode == "openai":
        if not settings.llm_openai_api_key:
            logger.warning("model-pin: openai mode with no llm_openai_api_key — chat degrades")
        else:
            logger.info("model-pin: openai-compatible mode, model=%s base=%s",
                        settings.llm_openai_model, settings.llm_openai_base_url)
    elif mode == "stub":
        logger.info("model-pin: stub mode (deterministic offline model, no API calls)")
    else:
        logger.error("model-pin: unknown agent_llm_mode=%r (expected live|openai|stub)", mode)


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
        _verify_model_config(settings)
        # TODO(S3): LangGraph Postgres checkpointer over app_db (tables created
        # via Alembic in core-api's tree, 10 §9 rule 4).
        try:
            yield
        finally:
            await app.state.redis.aclose()

    app = FastAPI(title="MedAgent agent-service", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.include_router(chat.router, prefix=API_V1_PREFIX)
    app.include_router(vision.router, prefix=API_V1_PREFIX)
    app.include_router(rx_safety.router, prefix=API_V1_PREFIX)
    app.include_router(feedback.router, prefix=API_V1_PREFIX)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness: 200 whenever the process is up (10 §1)."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        """Readiness: checks app_db (checkpointer home) + Redis; 503 with
        failing dependency names. An Anthropic outage is NOT a readiness
        failure — chat degrades, the service stays up (04 §7)."""
        failing: list[str] = []
        try:
            conn = await asyncpg.connect(_plain_dsn(settings.database_url), timeout=2)
            try:
                await conn.fetchval("SELECT 1")
            finally:
                await conn.close()
        except Exception:  # noqa: BLE001 - any failure means not ready
            failing.append("postgres")
        try:
            await app.state.redis.ping()
        except Exception:  # noqa: BLE001
            failing.append("redis")

        if failing:
            return JSONResponse(status_code=503, content={"status": "unready", "failing": failing})
        return JSONResponse(content={"status": "ready", "failing": []})

    configure_telemetry(app)
    return app


app = create_app()
