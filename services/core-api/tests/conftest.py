"""Test fixtures: app with dependency overrides (no real Postgres/Redis)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.deps import get_redis, get_session
from app.main import create_app

TEST_HMAC_KEYS = {"key-test-1": "unit-test-secret"}


class FakeResult:
    def __init__(self, value: Any = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return []


class FakeSession:
    """Minimal AsyncSession stand-in: every lookup misses; writes are collected."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    async def execute(self, *_args: Any, **_kwargs: Any) -> FakeResult:
        return FakeResult(None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:  # pragma: no cover - trivial
        pass

    async def commit(self) -> None:  # pragma: no cover - trivial
        pass

    async def rollback(self) -> None:  # pragma: no cover - trivial
        pass


class FakeRedis:
    """In-memory stand-in for the redis.asyncio client subset we use."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    async def set(
        self, key: str, value: str, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    async def ping(self) -> bool:
        return True


@pytest.fixture()
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture()
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture()
def app(fake_redis: FakeRedis, fake_session: FakeSession) -> FastAPI:
    settings = Settings(
        auth_disabled=True,
        face_webhook_hmac_keys=TEST_HMAC_KEYS,
    )
    application = create_app(settings)
    application.dependency_overrides[get_redis] = lambda: fake_redis
    application.dependency_overrides[get_session] = lambda: fake_session
    return application
