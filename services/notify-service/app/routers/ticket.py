"""SSE ticket issuance (02 §11).

Native EventSource cannot set an Authorization header, so streams are opened
with a **single-use, short-lived, opaque ticket**. Per 02 §11 the whole ticket
lifecycle lives in notify-service: this endpoint issues the ticket against the
caller's Bearer token (audience `notify-service`), authorises the requested
channels against the caller's role/facility, and stores an opaque 128-bit
reference in Redis with a 30 s TTL; `stream.py` redeems it with an atomic
GETDEL (replay -> 401).

The ticket is deliberately an opaque Redis reference, not a signed JWT: nothing
to parse, nothing to leak claims from, revocation for free.
"""

from __future__ import annotations

import json
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.auth import Principal, require_user
from app.config import Settings
from app.deps import get_redis, get_settings

router = APIRouter(prefix="/notify", tags=["sse"])

TICKET_KEY_TEMPLATE = "sse:ticket:{ticket}"

# Channel naming convention shared with core-api's publisher (app/events.py):
# per-facility check-in stream and per-user personal stream.
_USER_CHANNEL = "events:user:{sub}"
_CHECKIN_CHANNEL = "events:checkin:{facility_id}"

# Roles permitted to subscribe to a facility-wide check-in channel (02 §11 step 2).
_FACILITY_STREAM_ROLES = frozenset({"doctor", "nurse", "receptionist", "admin"})


class TicketRequest(BaseModel):
    facility_id: str | None = Field(
        default=None,
        description="Staff callers: facility whose check-in channel to stream.",
    )


class TicketResponse(BaseModel):
    ticket: str
    expires_in: int


@router.post("/ticket", status_code=status.HTTP_201_CREATED, response_model=TicketResponse)
async def create_sse_ticket(
    body: TicketRequest,
    principal: Annotated[Principal, Depends(require_user)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TicketResponse:
    """Issue a single-use opaque SSE ticket scoped to the caller's channels.

    Every caller may stream their own personal channel; only facility-staff
    roles may additionally stream a facility check-in channel, and only when
    they request one. A patient requesting a facility_id simply does not get
    that channel scoped onto the ticket.

    TODO(S2): scope the facility channel against the caller's *own* facility
    claim rather than any requested facility, once staff carry a facility
    attribute in the token (02 §11 step 2).
    """
    channels: list[str] = [_USER_CHANNEL.format(sub=principal.subject)]
    if body.facility_id and any(principal.has_role(r) for r in _FACILITY_STREAM_ROLES):
        channels.append(_CHECKIN_CHANNEL.format(facility_id=body.facility_id))

    ticket = secrets.token_hex(16)  # 128-bit opaque random reference
    await redis.set(
        TICKET_KEY_TEMPLATE.format(ticket=ticket),
        json.dumps(
            {
                "sub": principal.subject,
                "channels": channels,
                "session_id": str(principal.claims.get("sid", "")),
            }
        ),
        ex=settings.sse_ticket_ttl_seconds,
        nx=True,
    )
    return TicketResponse(ticket=ticket, expires_in=settings.sse_ticket_ttl_seconds)
