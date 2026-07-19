"""SSE stream endpoint with single-use ticket redemption (02 §11).

Flow: core-api issues an opaque 128-bit ticket (Redis, 30 s TTL) against the
caller's Bearer token; the browser opens `GET /notify/stream?ticket=...`;
redemption is an atomic GETDEL so a replayed ticket gets 401. The stream is
bound to the channels the ticket was scoped to (facility routing key stored
with the ticket by core-api), emits heartbeat comments every 15 s, and closes
after the 15-min max age so clients reconnect with a fresh ticket.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from redis.asyncio import Redis
from sse_starlette.sse import EventSourceResponse

from app.config import Settings
from app.deps import get_redis, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notify", tags=["stream"])

TICKET_KEY_TEMPLATE = "sse:ticket:{ticket}"


@router.get("/stream")
async def stream(
    request: Request,
    ticket: Annotated[str, Query(min_length=16, max_length=128)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EventSourceResponse:
    # Single-use redemption: atomic GETDEL — a missing or already-used ticket is 401.
    raw = await redis.getdel(TICKET_KEY_TEMPLATE.format(ticket=ticket))
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or already-used ticket",
        )

    try:
        scope: dict[str, Any] = json.loads(raw)
        channels: list[str] = list(scope["channels"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed ticket"
        ) from exc
    if not channels:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no channels scoped")

    # Never log ticket values; the gateway additionally scrubs the query param (02 §11).
    logger.info("sse stream opened", extra={"channel_count": len(channels)})

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        deadline = time.monotonic() + settings.sse_max_age_seconds
        pubsub = redis.pubsub()
        await pubsub.subscribe(*channels)
        try:
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield {"event": "message", "data": data}
            # Max age reached: tell the client to reconnect with a fresh ticket.
            yield {"event": "reconnect", "data": json.dumps({"reason": "max_age"})}
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.aclose()
            logger.info("sse stream closed")

    # sse-starlette's `ping` emits comment heartbeats on the given interval (15 s).
    return EventSourceResponse(event_source(), ping=settings.sse_heartbeat_seconds)
