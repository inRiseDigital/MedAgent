"""Ticket redemption behaviour: missing/used tickets are rejected with 401 (02 §11)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import FakeRedis


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_stream_rejects_unknown_ticket(app: FastAPI) -> None:
    async with _client(app) as client:
        resp = await client.get("/notify/stream", params={"ticket": "0" * 32})
    assert resp.status_code == 401


async def test_ticket_is_single_use_at_redis_level(fake_redis: FakeRedis) -> None:
    fake_redis.store["sse:ticket:abc"] = '{"sub":"u1","channels":["events:checkin:f1"]}'
    first = await fake_redis.getdel("sse:ticket:abc")
    second = await fake_redis.getdel("sse:ticket:abc")
    assert first is not None
    assert second is None  # replay redeems nothing → endpoint returns 401


async def test_stream_rejects_ticket_with_no_channels(
    app: FastAPI, fake_redis: FakeRedis
) -> None:
    fake_redis.store["sse:ticket:" + "1" * 32] = '{"sub":"u1","channels":[]}'
    async with _client(app) as client:
        resp = await client.get("/notify/stream", params={"ticket": "1" * 32})
    assert resp.status_code == 401
