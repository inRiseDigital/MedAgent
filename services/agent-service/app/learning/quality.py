"""Drift / quality monitoring — a PHI-free health snapshot of the agent.

Builds the payload behind GET /api/v1/quality. It trends the *proxies* for
eval-pass-rate that we can observe cheaply from the two existing PHI-free stores
(no new infra, no PHI):

- feedback buffer (app/learning/feedback.py): thumbs-down / reject / override /
  refusal signals.
- turn telemetry (app/agent/telemetry.py): latency p50/p95, tokens, error/timeout
  counts.

Each metric is scored against a configurable threshold from Settings and gets a
simple status — ``ok`` / ``watch`` / ``degraded`` (or ``no_data``) — so a
regression reads as ``degraded`` at a glance. The overall status is the worst of
the thresholded metrics.

GOVERNANCE: this is observation only. The thresholds gate a DASHBOARD STATUS,
never behaviour — nothing here can change clinical output, the Rx-safety engine,
prompts, or the eval gate. Values are aggregate and PHI-free (questions stay
hashed upstream; only counts/latencies/tokens are read here).

NOTE on citation coverage: we do not store per-turn citation counts, so this is a
PROXY — the share of turns that reached a full grounded answer (not errored, not
timed out). A turn that errors or times out returns the safety floor with no
citations. True citation faithfulness is measured by the live eval grader.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Fraction of a "max" threshold at which a metric flips ok -> watch (early warning).
_WATCH_FRACTION = 0.8


def _round(value: float | int | None, ndigits: int = 3) -> float | int | None:
    if value is None:
        return None
    return round(value, ndigits)


def _status_max(value: float | None, threshold: float, warn_fraction: float = _WATCH_FRACTION) -> str:
    """Status for a 'lower is better' metric (value must stay <= threshold)."""
    if value is None:
        return "no_data"
    if value > threshold:
        return "degraded"
    if value >= threshold * warn_fraction:
        return "watch"
    return "ok"


def _status_min(value: float | None, threshold: float) -> str:
    """Status for a 'higher is better' metric (value must stay >= threshold)."""
    if value is None:
        return "no_data"
    if value < threshold:
        return "degraded"
    # within 1 - (1 - fraction) band above the floor -> watch
    if value < threshold + (1.0 - threshold) * (1.0 - _WATCH_FRACTION):
        return "watch"
    return "ok"


def _metric(value: Any, threshold: float | int | None, direction: str, status: str) -> dict[str, Any]:
    return {"value": value, "threshold": threshold, "direction": direction, "status": status}


def _worst(statuses: list[str]) -> str:
    order = ["degraded", "watch", "ok"]
    for level in order:
        if level in statuses:
            return level
    return "no_data"  # every metric lacked data


def build_quality_snapshot(
    feedback_metrics: dict[str, Any],
    telemetry: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    """Combine feedback + telemetry aggregates into a scored drift snapshot.

    Pure function (no I/O) so it is trivially testable: the router passes in the
    already-computed ``analyze(events)`` and ``summarize(redis)`` dicts.
    """
    ratings = feedback_metrics.get("answer_ratings", {}) or {}
    proposals = feedback_metrics.get("proposal_outcomes", {}) or {}
    total_events = feedback_metrics.get("total_events", 0) or 0
    refusals = feedback_metrics.get("refusals", 0) or 0

    thumbs_down = ratings.get("thumbs_down_rate")
    reject = proposals.get("reject_rate")
    override = proposals.get("override_rate")
    # Refusal rate proxy: share of captured feedback signals that were refusals.
    refusal_rate = round(refusals / total_events, 3) if total_events else None

    total_turns = telemetry.get("total", 0) or 0
    latency = telemetry.get("latency_ms", {}) or {}
    tokens = telemetry.get("tokens", {}) or {}
    p50 = latency.get("p50")
    p95 = latency.get("p95")
    tokens_avg = tokens.get("avg")
    errored = telemetry.get("errored", 0) or 0
    timed_out = telemetry.get("timed_out", 0) or 0
    bad = errored + timed_out
    error_rate = round(bad / total_turns, 3) if total_turns else None
    citation_coverage = round((total_turns - bad) / total_turns, 3) if total_turns else None

    metrics = {
        # --- clinician feedback proxies (feedback buffer) ---
        "thumbs_down_rate": _metric(
            _round(thumbs_down), settings.quality_thumbs_down_rate_max, "max",
            _status_max(thumbs_down, settings.quality_thumbs_down_rate_max),
        ),
        "reject_rate": _metric(
            _round(reject), settings.quality_reject_rate_max, "max",
            _status_max(reject, settings.quality_reject_rate_max),
        ),
        "override_rate": _metric(
            _round(override), settings.quality_override_rate_max, "max",
            _status_max(override, settings.quality_override_rate_max),
        ),
        "refusal_rate": _metric(
            refusal_rate, settings.quality_refusal_rate_max, "max",
            _status_max(refusal_rate, settings.quality_refusal_rate_max),
        ),
        # --- grounding / ops proxies (turn telemetry) ---
        "citation_coverage": _metric(
            citation_coverage, settings.quality_citation_coverage_min, "min",
            _status_min(citation_coverage, settings.quality_citation_coverage_min),
        ),
        "latency_p95_ms": _metric(
            p95, settings.quality_latency_p95_ms_max, "max",
            _status_max(p95, settings.quality_latency_p95_ms_max),
        ),
        "error_rate": _metric(
            error_rate, settings.quality_error_rate_max, "max",
            _status_max(error_rate, settings.quality_error_rate_max),
        ),
        "tokens_avg": _metric(
            tokens_avg, settings.quality_tokens_avg_max, "max",
            _status_max(tokens_avg, settings.quality_tokens_avg_max),
        ),
        # informational (no threshold) — trend context, never gates status
        "latency_p50_ms": _metric(p50, None, "info", "info"),
    }

    thresholded = [m["status"] for m in metrics.values() if m["threshold"] is not None]
    overall = _worst(thresholded)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "window": {"feedback_events": total_events, "telemetry_turns": total_turns},
        "metrics": metrics,
        "governance": (
            "PHI-free drift proxies for a dashboard only. Thresholds gate the status "
            "label, NEVER clinical/safety behaviour, prompts, or the eval gate."
        ),
    }
