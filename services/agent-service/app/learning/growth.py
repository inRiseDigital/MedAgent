"""Auto eval-set growth — recurring failure signals become candidate golden cases.

This is the "self-improvement" half of the governed learning loop. It reads the
PHI-free feedback buffer (app/learning/feedback.py), finds *recurring* failure
patterns, and writes each one as a **candidate GOLDEN EVAL CASE** in the exact
shape evals/run.py consumes (id / class / seed_version / input / expected /
grader), marked ``status: needs_review`` with provenance (source signal, first/
last timestamp, and how many times it recurred).

Patterns mined:
- repeated clinician thumbs-down on the same hashed question  -> class ``summary_qa``
- repeated agent refusals on the same hashed question         -> class ``refusal``
- repeated rejected/overridden safety proposals for a drug    -> class ``rx_safety_review``

GOVERNANCE — enforced in code and preserved on purpose:
- Candidates are ONLY ever written under evals/candidates/ (a hard path guard).
  They are NEVER written to evals/golden/, the Rx-safety engine, its dataset, or
  any prompt. Nothing in this module can change clinical, safety, or runtime
  behaviour.
- A candidate is a *proposal for a human*. Promotion into the golden set is a
  human PR that must pass the eval gate (evals/run.py). Until a person moves it
  to evals/golden/, it grades nothing.
- ``rx_safety_review`` is a NON-GATED class on purpose: run.py does not grade it,
  so this loop can never auto-inject a drug-safety verdict into the 100% gate. A
  pharmacist authors the real ``rx_safety`` case + a clinician-reviewed dataset PR.
- PHI-free throughout: raw question text is never stored (only a sha256 prefix),
  so fields a grader needs (the question, the seed patient) are emitted as the
  ``REVIEW_REQUIRED`` sentinel for the reviewer to restore from the turn.

Run offline / scheduled:
    python -m app.learning.growth [--min-count N] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[2]
CANDIDATES_DIR = SERVICE_ROOT / "evals" / "candidates"

# "Recurring" = at least this many matching signals. A one-off is noise; repeats
# are a pattern worth a reviewer's time. Configurable via --min-count.
DEFAULT_MIN_COUNT = 2
SEED_VERSION = "v0"
# Sentinel for a field a human reviewer must supply before promotion (we do not
# store raw question text or patient references — PHI-free by construction).
REVIEW = "REVIEW_REQUIRED"

_HEADER = (
    "# GENERATED CANDIDATE — governed learning loop (auto eval-set growth).\n"
    "# status: needs_review. A HUMAN promotes this into evals/golden/ via a PR\n"
    "# that must pass the eval gate before it grades anything. This file NEVER\n"
    "# alters runtime, prompts, or the Rx-safety engine/dataset. Fields marked\n"
    f"# {REVIEW} must be completed by the reviewer (raw question text is hashed,\n"
    "# so it is not stored here — reconstruct it from the turn / question_ref).\n"
)


def _slug(text: str) -> str:
    """Filesystem-safe, deterministic slug (also the dedup key)."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "unknown"


@dataclass
class Candidate:
    """One deduped, review-ready candidate golden case."""

    stem: str  # filename stem == case id == dedup key
    case: dict[str, Any]


@dataclass
class GrowthResult:
    """Outcome of a growth pass — what was added vs. left untouched."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)  # recurring count refreshed
    skipped: list[str] = field(default_factory=list)  # already human-reviewed; never clobbered

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "counts": {
                "created": len(self.created),
                "updated": len(self.updated),
                "skipped": len(self.skipped),
            },
        }


def _timespan(events: list[dict[str, Any]]) -> tuple[str, str]:
    ts = sorted(str(e.get("ts", "")) for e in events)
    return ts[0], ts[-1]


def mine_patterns(
    events: list[dict[str, Any]], min_count: int = DEFAULT_MIN_COUNT
) -> list[Candidate]:
    """Group failure signals into recurring patterns and build candidate cases.

    Only patterns seen >= ``min_count`` times are emitted, so a single stray
    signal never becomes a candidate. Grouping is on PHI-free keys only (hashed
    question refs, drug names, verdicts).
    """
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        kind = e.get("kind")
        if kind == "answer_rating" and e.get("rating") == "down":
            groups[("summary_qa", str(e.get("question_ref") or "unknown"))].append(e)
        elif kind == "refusal":
            groups[("refusal", str(e.get("question_ref") or "unknown"))].append(e)
        elif kind == "proposal_outcome" and e.get("outcome") in ("rejected", "overridden"):
            groups[
                (
                    "rx_safety_review",
                    str(e.get("proposed_drug") or "unknown"),
                    str(e.get("verdict") or "unknown"),
                    str(e.get("outcome")),
                )
            ].append(e)

    candidates: list[Candidate] = []
    for key, evs in groups.items():
        if len(evs) < min_count:
            continue
        first_seen, last_seen = _timespan(evs)
        provenance = {"signal_count": len(evs), "first_seen": first_seen, "last_seen": last_seen}
        candidates.append(_build_candidate(key, evs, provenance))
    return candidates


def _build_candidate(
    key: tuple[str, ...], evs: list[dict[str, Any]], provenance: dict[str, Any]
) -> Candidate:
    cls = key[0]
    if cls == "summary_qa":
        qref = key[1]
        stem = f"cand-summary-qa-{_slug(qref)}"
        case = {
            "id": stem,
            "class": "summary_qa",
            "status": "needs_review",
            "seed_version": SEED_VERSION,
            "provenance": {"source": "clinician_thumbs_down", "question_ref": qref, **provenance},
            "input": {"patient_ref": REVIEW, "question": REVIEW},
            "expected": {"refusal": False, "citations": {"required": True}},
            "grader": "llm_rubric",
            "review_note": (
                "Clinicians repeatedly rated this answer poor. Reconstruct the question "
                "from the turn, confirm the expected answer, then move to evals/golden/."
            ),
        }
    elif cls == "refusal":
        qref = key[1]
        stem = f"cand-refusal-{_slug(qref)}"
        case = {
            "id": stem,
            "class": "refusal",
            "status": "needs_review",
            "seed_version": SEED_VERSION,
            "provenance": {"source": "agent_refusal", "question_ref": qref, **provenance},
            "input": {"question": REVIEW},
            "expected": {"refusal": True},
            "grader": "exact",
            "review_note": (
                "The agent repeatedly refused this ask. Decide: correct safety refusal "
                "(keep expected.refusal true and promote) or over-refusal gap (fix the "
                "behaviour via the normal gated path, then add the answered case)."
            ),
        }
    else:  # rx_safety_review — NON-GATED on purpose (see module docstring)
        drug, verdict, outcome = key[1], key[2], key[3]
        stem = f"cand-rx-safety-review-{_slug(drug)}-{_slug(outcome)}"
        case = {
            "id": stem,
            "class": "rx_safety_review",
            "status": "needs_review",
            "seed_version": SEED_VERSION,
            "provenance": {"source": f"proposal_{outcome}", **provenance},
            "input": {"proposed_drug": drug, "current_meds": REVIEW, "allergies": REVIEW},
            "expected": {"engine_verdict": verdict, "clinician_action": outcome},
            "grader": "manual_clinician_review",
            "review_note": (
                "Clinicians repeatedly disagreed with the engine here. Pharmacist review "
                "ONLY. The engine/dataset is NEVER auto-modified; any change is a "
                "clinician-reviewed PR that must pass the eval gate. To lock in a corrected "
                "verdict, author a real rx_safety case in evals/golden/."
            ),
        }
    return Candidate(stem=stem, case=case)


def _assert_under_candidates(target: Path) -> Path:
    """HARD GOVERNANCE GUARD: candidates may only be written under evals/candidates/."""
    target = target.resolve()
    root = CANDIDATES_DIR.resolve()
    if target != root and root not in target.parents:
        raise ValueError(
            "GOVERNANCE: eval candidates may only be written under evals/candidates/ "
            f"(refused: {target})"
        )
    return target


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


def _dump_yaml(path: Path, case: dict[str, Any]) -> None:
    body = yaml.safe_dump(case, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path.write_text(_HEADER + body, encoding="utf-8")


def grow_eval_set(
    events: list[dict[str, Any]],
    out_dir: Path | None = None,
    min_count: int = DEFAULT_MIN_COUNT,
) -> GrowthResult:
    """Turn recurring failure signals into review-ready candidate golden cases.

    Idempotent + deduped: each pattern maps to a deterministic filename. A new
    pattern is *created*; a pattern already queued (still ``needs_review``) has
    only its recurrence count/last_seen *updated*; a candidate a human has
    already touched (status changed / promoted) is *skipped* and never clobbered.

    GOVERNANCE: writes ONLY under evals/candidates/ (guarded); never the golden
    set, the engine, its dataset, or a prompt.
    """
    target = _assert_under_candidates(out_dir or CANDIDATES_DIR)
    target.mkdir(parents=True, exist_ok=True)

    result = GrowthResult()
    for cand in mine_patterns(events, min_count=min_count):
        path = target / f"{cand.stem}.yaml"
        if path.exists():
            existing = _load_yaml(path)
            if not existing or existing.get("status") != "needs_review":
                # A reviewer has already acted on this candidate — do not overwrite.
                result.skipped.append(str(path))
                continue
            # Dedup: same pattern already queued — refresh recurrence provenance only,
            # preserving any reviewer edits to the case body.
            prov = existing.setdefault("provenance", {})
            prov["signal_count"] = cand.case["provenance"]["signal_count"]
            prov["last_seen"] = cand.case["provenance"]["last_seen"]
            _dump_yaml(path, existing)
            result.updated.append(str(path))
        else:
            _dump_yaml(path, cand.case)
            result.created.append(str(path))
    return result


async def _load_events() -> list[dict[str, Any]]:
    """Read the PHI-free feedback buffer via the configured (ACL-real) Redis URL."""
    from redis.asyncio import Redis

    from app.config import Settings
    from app.learning.feedback import read_all

    redis = Redis.from_url(Settings().redis_url, decode_responses=True)
    try:
        return await read_all(redis)
    finally:
        await redis.aclose()


def main(argv: list[str] | None = None) -> int:
    """Offline / scheduled entrypoint. Reads feedback, writes candidate cases."""
    import asyncio
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-count",
        type=int,
        default=DEFAULT_MIN_COUNT,
        help=f"min recurrences for a pattern to become a candidate (default {DEFAULT_MIN_COUNT})",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="override candidate dir (still guarded to evals/candidates/)",
    )
    args = parser.parse_args(argv)

    events = asyncio.run(_load_events())
    result = grow_eval_set(
        events,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        min_count=args.min_count,
    )
    print(
        json.dumps(
            {"events_scanned": len(events), "min_count": args.min_count, **result.as_dict()},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
