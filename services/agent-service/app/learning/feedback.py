"""Feedback capture for the governed continuous-learning loop (BUILD-PLAN
"Continuous learning & self-improvement").

Captures PHI-FREE learning signals — clinician answer ratings, proposal outcomes
(accepted / rejected / overridden), and refusals — into a bounded Redis list.
These feed offline analysis (analyze.py) that produces DRIFT METRICS and
HUMAN-REVIEWED candidate eval cases.

GOVERNANCE (hard rules, enforced here and in analyze.py):
- Signals are structured and PHI-free: no patient names, no free-text notes,
  no record content. A patient is referenced only by an opaque short hash.
- Capture NEVER changes system behaviour. Learning is offline, human-reviewed,
  and every resulting change must pass the eval gate. The deterministic
  Rx-safety engine and its dataset are never touched by this pipeline.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from redis.asyncio import Redis

FEEDBACK_KEY = "agent:learning:feedback"
MAX_EVENTS = 5000  # bounded — this is a rolling signal buffer, not a record store


class FeedbackEvent(BaseModel):
    kind: Literal["answer_rating", "proposal_outcome", "refusal"]
    turn_id: str | None = None
    question_ref: str | None = Field(
        default=None, description="Opaque question hash (set server-side); never raw text."
    )
    rating: Literal["up", "down"] | None = None
    proposed_drug: str | None = None  # a drug name is not PHI
    verdict: str | None = None
    outcome: Literal["accepted", "rejected", "overridden"] | None = None
    model: str | None = None
    # Optional opaque patient hash — set server-side from a ref; never the raw PHN.
    subject_hash: str | None = None


def hash_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    return hashlib.sha256(ref.encode("utf-8")).hexdigest()[:12]


async def capture(redis: Redis, event: FeedbackEvent) -> None:
    record: dict[str, Any] = event.model_dump(exclude_none=True)
    record["ts"] = datetime.now(timezone.utc).isoformat()
    await redis.lpush(FEEDBACK_KEY, json.dumps(record))
    await redis.ltrim(FEEDBACK_KEY, 0, MAX_EVENTS - 1)


async def read_all(redis: Redis) -> list[dict[str, Any]]:
    raw = await redis.lrange(FEEDBACK_KEY, 0, -1)
    out: list[dict[str, Any]] = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (ValueError, TypeError):
            continue
    return out
