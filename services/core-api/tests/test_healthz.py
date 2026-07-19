"""Liveness endpoint via httpx ASGI transport (no lifespan, no dependencies)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI


async def test_healthz_returns_200(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
