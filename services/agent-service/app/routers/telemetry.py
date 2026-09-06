"""GET /telemetry — aggregate latency/cost ops metrics (S4).
GET /quality — PHI-free drift / quality-monitoring snapshot (governed learning loop).

Both read the PHI-FREE stores and return aggregate summaries only; no PHI is
stored or returned. Auth-guarded like the chat router.

/telemetry returns the raw latency/cost aggregate (totals, by path/provider,
latency percentiles, token totals) behind the ops dashboard.

/quality trends the proxies for eval-pass-rate (thumbs-down / reject / override /
refusal rates, a citation-coverage proxy, latency p50/p95, token cost) and scores
each against a configurable Settings threshold, so a regression reads as
``degraded``. It is OBSERVATION ONLY — the thresholds gate a dashboard label,
never clinical/safety behaviour, prompts, or the eval gate.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.agent.telemetry import summarize
from app.auth import Principal, require_user
from app.learning.analyze import analyze
from app.learning.feedback import read_all
from app.learning.quality import build_quality_snapshot

router = APIRouter(tags=["telemetry"])


@router.get("/telemetry")
async def telemetry(
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict:
    # Aggregate ops metrics only — no PHI. Best-effort store returns a well-formed
    # empty summary if Redis is unavailable, so this never errors on infra.
    return await summarize(request.app.state.redis)


@router.get("/quality")
async def quality(
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict:
    # PHI-free drift snapshot. Reuses the existing feedback + telemetry stores;
    # no new infra. build_quality_snapshot is a pure scorer (thresholds from
    # Settings) — nothing here can alter clinical/safety behaviour.
    redis = request.app.state.redis
    settings = request.app.state.settings
    feedback_metrics = analyze(await read_all(redis))
    telemetry_summary = await summarize(redis)
    return build_quality_snapshot(feedback_metrics, telemetry_summary, settings)
