"""GET /telemetry — aggregate latency/cost ops metrics (S4).

Reads the PHI-FREE per-turn telemetry store and returns a summary (totals, by
path/provider, latency percentiles, token totals) — the data behind a
latency/cost dashboard. Aggregate operational metrics ONLY; no PHI is stored or
returned. Auth-guarded like the chat router.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.agent.telemetry import summarize
from app.auth import Principal, require_user

router = APIRouter(tags=["telemetry"])


@router.get("/telemetry")
async def telemetry(
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict:
    # Aggregate ops metrics only — no PHI. Best-effort store returns a well-formed
    # empty summary if Redis is unavailable, so this never errors on infra.
    return await summarize(request.app.state.redis)
