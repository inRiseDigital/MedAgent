"""Feedback + drift-metrics API for the governed learning loop.

POST /api/v1/feedback         — capture a PHI-free learning signal
GET  /api/v1/feedback/metrics — drift/quality metrics (thumbs-down, reject/override rates)

Capture never changes behaviour; analysis is offline and human-reviewed (see
app/learning/analyze.py). Raw question text is hashed server-side and never stored.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth import Principal, require_user
from app.learning.analyze import analyze
from app.learning.feedback import FeedbackEvent, capture, hash_ref, read_all

router = APIRouter(prefix="/feedback", tags=["learning"])


class FeedbackIn(BaseModel):
    kind: Literal["answer_rating", "proposal_outcome", "refusal"]
    turn_id: str | None = None
    rating: Literal["up", "down"] | None = None
    question: str | None = None  # hashed server-side, never stored raw
    subject_ref: str | None = None  # hashed server-side (opaque)
    proposed_drug: str | None = None
    verdict: str | None = None
    outcome: Literal["accepted", "rejected", "overridden"] | None = None
    model: str | None = None


@router.post("", status_code=202)
async def submit_feedback(
    body: FeedbackIn,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict[str, str]:
    event = FeedbackEvent(
        kind=body.kind,
        turn_id=body.turn_id,
        rating=body.rating,
        question_ref=hash_ref(body.question),
        subject_hash=hash_ref(body.subject_ref),
        proposed_drug=body.proposed_drug,
        verdict=body.verdict,
        outcome=body.outcome,
        model=body.model,
    )
    await capture(request.app.state.redis, event)
    return {"status": "captured"}


@router.get("/metrics")
async def metrics(
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict:
    events = await read_all(request.app.state.redis)
    return analyze(events)
