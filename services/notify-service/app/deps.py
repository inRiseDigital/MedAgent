"""Shared FastAPI dependencies (app.state-backed, override-friendly in tests)."""

from __future__ import annotations

from fastapi import Request
from redis.asyncio import Redis

from app.config import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis
