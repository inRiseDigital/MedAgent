"""core-api application factory.

NOTE (10 §9): no `create_all` anywhere — Alembic is the only schema mechanism
for app_db (`alembic upgrade head` runs as a deploy step before rollout).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import JWKSCache
from app.config import Settings
from app.logging_config import configure_logging
from app.routers import authz, face_events, patients, queue
from app.telemetry import configure_telemetry

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.service_name, settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Engine/client construction is lazy — no connections are opened here,
        # so the process starts even while dependencies are still coming up
        # (readiness is what gates traffic).
        app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
        app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.jwks = JWKSCache(settings.keycloak_issuer, settings.jwks_cache_ttl_seconds)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(
        title="MedAgent core-api",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.include_router(patients.router, prefix=API_V1_PREFIX)
    app.include_router(queue.router, prefix=API_V1_PREFIX)
    app.include_router(face_events.router, prefix=API_V1_PREFIX)
    # SSE ticket issuance lives in notify-service (02 §11) — it owns the full
    # ticket lifecycle (issue + redeem) since it holds the Redis pub/sub and the
    # channel routing. core-api does not issue SSE tickets.
    #
    # Care-relationship decision service for the HAPI authz interceptor
    # (02 §7.2, 03 §5.1). Mounted at /internal/* — NOT /api/v1 and never routed
    # through the public gateway; reachable only on the internal service network.
    app.include_router(authz.router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness: 200 whenever the process is up (10 §1)."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        """Readiness: checks Postgres + Redis; 503 with failing dependency names."""
        failing: list[str] = []
        try:
            async with app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
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
