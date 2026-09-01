"""Per-turn telemetry store (S4).

A lightweight, PHI-FREE record of the shape of each chat turn — the raw material
behind a latency/cost dashboard. We store ONLY operational fields (path taken,
audience, latency, tokens, provider, and outcome flags); never a patient id, the
question, or any record text. Kept in a capped Redis list; both write and read
are best-effort and never break a turn.
"""

from __future__ import annotations

import json
import time
from typing import Any

_KEY = "agent:telemetry:turns"
_MAX = 1000  # keep the last N turns — a rolling window, not an audit log


async def record_turn(
    redis: Any,
    *,
    path: str,
    audience: str,
    ms: int,
    provider: str,
    tokens: int = 0,
    streamed: bool = True,
    timed_out: bool = False,
    errored: bool = False,
) -> None:
    """Append a compact, PHI-FREE turn record to a capped Redis list.

    Best-effort: if redis is None or anything fails, do nothing (never raise) —
    telemetry must never affect the response it is measuring.
    """
    if not redis:
        return
    try:
        # Only operational fields — nothing that could identify a patient or leak text.
        blob = json.dumps(
            {
                "ts": int(time.time()),
                "path": path,
                "audience": audience,
                "ms": int(ms),
                "provider": provider,
                "tokens": int(tokens),
                "streamed": bool(streamed),
                "timed_out": bool(timed_out),
                "errored": bool(errored),
            }
        )
        await redis.rpush(_KEY, blob)
        await redis.ltrim(_KEY, -_MAX, -1)  # cap the window
    except Exception:  # noqa: BLE001 — telemetry is best-effort, never breaks a turn
        return


def _percentile(values: list[int], pct: float) -> int:
    """Nearest-rank percentile from a sorted list (no numpy). `values` must be sorted."""
    if not values:
        return 0
    # Nearest-rank: rank = ceil(pct/100 * N), clamped to [1, N]; index is rank-1.
    rank = int(-(-pct * len(values) // 100))  # ceil without importing math
    idx = min(max(rank, 1), len(values)) - 1
    return values[idx]


def _empty_summary() -> dict[str, Any]:
    """A well-formed, all-zero summary — returned when there is nothing to aggregate."""
    return {
        "total": 0,
        "by_path": {},
        "by_provider": {},
        "latency_ms": {"p50": 0, "p95": 0, "max": 0},
        "tokens": {"total": 0, "avg": 0.0},
        "streamed": 0,
        "timed_out": 0,
        "errored": 0,
    }


async def summarize(redis: Any, limit: int = 1000) -> dict:
    """Aggregate recent turns: totals, by-path, by-provider, latency p50/p95/max,
    token totals+avg, and streamed/timed_out/errored counts.

    Safe defaults if empty or redis unavailable — always a well-formed dict.
    """
    if not redis:
        return _empty_summary()
    try:
        # Read the tail window (LRANGE over the last `limit` entries).
        rows = list(await redis.lrange(_KEY, -limit, -1))
    except Exception:  # noqa: BLE001 — best-effort read
        return _empty_summary()

    by_path: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    latencies: list[int] = []
    tokens_total = 0
    streamed = timed_out = errored = 0
    total = 0

    for raw in rows:
        try:
            rec = json.loads(raw)
        except Exception:  # noqa: BLE001 — skip a corrupt row, keep aggregating
            continue
        if not isinstance(rec, dict):
            continue
        total += 1
        by_path[rec.get("path", "?")] = by_path.get(rec.get("path", "?"), 0) + 1
        by_provider[rec.get("provider", "?")] = by_provider.get(rec.get("provider", "?"), 0) + 1
        latencies.append(int(rec.get("ms", 0) or 0))
        tokens_total += int(rec.get("tokens", 0) or 0)
        if rec.get("streamed"):
            streamed += 1
        if rec.get("timed_out"):
            timed_out += 1
        if rec.get("errored"):
            errored += 1

    if not total:
        return _empty_summary()

    latencies.sort()
    return {
        "total": total,
        "by_path": by_path,
        "by_provider": by_provider,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": latencies[-1],
        },
        "tokens": {"total": tokens_total, "avg": round(tokens_total / total, 1)},
        "streamed": streamed,
        "timed_out": timed_out,
        "errored": errored,
    }
