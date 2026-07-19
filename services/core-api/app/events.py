"""Redis pub/sub publisher utilities (01 §4.1, ADR A-3).

All cross-service events flow over Redis pub/sub; notify-service fans out to
SSE. Channel naming: `events:checkin:{facility_id}` for arrival-queue events.
Payloads carry opaque IDs only — no PHI beyond what the receiving UI is
authorised to render (queue views resolve display data via authorised APIs).
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

CHECKIN_CHANNEL_TEMPLATE = "events:checkin:{facility_id}"


def checkin_channel(facility_id: str) -> str:
    return CHECKIN_CHANNEL_TEMPLATE.format(facility_id=facility_id)


async def publish_event(redis: Redis, channel: str, payload: dict[str, Any]) -> None:
    await redis.publish(channel, json.dumps(payload, default=str))


async def publish_checkin(redis: Redis, facility_id: str, payload: dict[str, Any]) -> None:
    """Publish a check-in event for a facility's live queue views."""
    await publish_event(redis, checkin_channel(facility_id), payload)
