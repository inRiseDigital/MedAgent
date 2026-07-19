"""Test fixtures for notify-service (no real Redis)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.deps import get_redis
from app.main import create_app


class FakeRedis:
    """In-memory stand-in for the redis.asyncio client subset we use."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def ping(self) -> bool:
        return True


@pytest.fixture()
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture()
def app(fake_redis: FakeRedis) -> FastAPI:
    application = create_app(Settings(auth_disabled=True))
    application.dependency_overrides[get_redis] = lambda: fake_redis
    return application
