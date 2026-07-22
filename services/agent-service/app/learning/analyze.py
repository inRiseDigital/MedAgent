"""Offline analysis of captured feedback (governed learning loop).

Two outputs, both human-facing — NEITHER changes runtime behaviour:
1. DRIFT / QUALITY METRICS — thumbs-down rate, proposal reject/override rates,
   refusal count — surfaced at /api/v1/feedback/metrics and (later) the eval
   dashboard.
2. CANDIDATE EVAL CASES — failures and clinician disagreements become *candidate*
   golden cases written to evals/candidates/, marked `status: needs_review`. A
   human promotes a candidate into the golden set; only then does the eval gate
   grade it. Promotion of any change (prompt/tool/dataset) must pass the gate.

GOVERNANCE (enforced): candidates are only ever written under evals/candidates/.
This module NEVER writes to app/rxsafety/data (the deterministic engine dataset)
or to prompts. The Rx-safety engine is changed only by clinician-reviewed PRs.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parents[2]
CANDIDATES_DIR = SERVICE_ROOT / "evals" / "candidates"


def analyze(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute drift/quality metrics from feedback events."""
    kinds = Counter(e.get("kind") for e in events)
    ratings = Counter(e.get("rating") for e in events if e.get("kind") == "answer_rating")
    outcomes = Counter(e.get("outcome") for e in events if e.get("kind") == "proposal_outcome")

    n_rated = ratings["up"] + ratings["down"]
    n_outcomes = sum(outcomes.values())
    return {
        "total_events": len(events),
        "by_kind": dict(kinds),
        "answer_ratings": {
            "up": ratings["up"],
            "down": ratings["down"],
            "thumbs_down_rate": round(ratings["down"] / n_rated, 3) if n_rated else None,
        },
        "proposal_outcomes": {
            "accepted": outcomes["accepted"],
            "rejected": outcomes["rejected"],
            "overridden": outcomes["overridden"],
            "reject_rate": round(outcomes["rejected"] / n_outcomes, 3) if n_outcomes else None,
            "override_rate": round(outcomes["overridden"] / n_outcomes, 3) if n_outcomes else None,
        },
        "refusals": kinds["refusal"],
    }


def generate_candidates(events: list[dict[str, Any]], out_dir: Path | None = None) -> list[str]:
    """Write candidate eval cases for human review. Returns the paths written.

    HARD GUARD: candidates are only ever written under evals/candidates/.
    """
    target = (out_dir or CANDIDATES_DIR).resolve()
    if CANDIDATES_DIR.resolve() not in [target, *target.parents] and target != CANDIDATES_DIR.resolve():
        raise ValueError("candidates may only be written under evals/candidates/ (governance)")
    target.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for i, e in enumerate(events):
        candidate: dict[str, Any] | None = None
        if e.get("kind") == "answer_rating" and e.get("rating") == "down":
            candidate = {
                "status": "needs_review",
                "source": "clinician thumbs-down",
                "class": "summary_qa",
                "turn_id": e.get("turn_id"),
                "question_ref": e.get("question_ref"),
                "note": "A clinician rated this answer poor — review the turn and, if a real gap, add a graded golden case.",
            }
        elif e.get("kind") == "proposal_outcome" and e.get("outcome") in ("rejected", "overridden"):
            candidate = {
                "status": "needs_review",
                "source": f"proposal {e.get('outcome')}",
                "class": "rx_safety_review",
                "proposed_drug": e.get("proposed_drug"),
                "engine_verdict": e.get("verdict"),
                "note": ("Clinician disagreed with the engine verdict. Review the DDI/allergy "
                         "dataset with a pharmacist; changes are PR-only and must pass the gate. "
                         "The engine is NEVER auto-modified."),
            }
        if candidate is None:
            continue
        key = f"cand_{e.get('kind')}_{e.get('turn_id') or e.get('proposed_drug') or i}".replace("/", "_")
        path = target / f"{key}.json"
        path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
        written.append(str(path))
    return written


async def _main() -> None:
    import os

    from redis.asyncio import Redis

    from app.learning.feedback import read_all

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
    try:
        events = await read_all(redis)
        metrics = analyze(events)
        print(json.dumps(metrics, indent=2))
        cands = generate_candidates(events)
        print(f"\n{len(cands)} candidate(s) written for review:")
        for c in cands:
            print(f"  - {c}")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
