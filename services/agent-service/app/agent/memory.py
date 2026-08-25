"""Long-term conversational memory (P2).

Durable, PHI-light notes the agent chooses to remember about a record/conversation
and recalls across sessions — preferences and recurring context, NOT clinical
decisions. Stored in Redis, keyed by patient_id (the record in view); the FHIR
record remains the source of truth for anything clinical.

Examples of good memories: "prefers simple, plain-language explanations",
"usually asks in Sinhala", "anxious about needles", "following up on weight".
Never store diagnoses/results as memory — cite those from the record instead.
"""

from __future__ import annotations

from typing import Any

_KEY = "agent:memory:{pid}"
_MAX = 40
_TTL_SECONDS = 60 * 60 * 24 * 180  # 180 days


async def recall(redis: Any, patient_id: str) -> list[str]:
    """Return remembered notes for this record (most-recent last), best-effort."""
    if not redis or not patient_id:
        return []
    try:
        return list(await redis.lrange(_KEY.format(pid=patient_id), 0, _MAX))
    except Exception:  # noqa: BLE001 — memory is best-effort, never breaks a turn
        return []


async def remember(redis: Any, patient_id: str, fact: str) -> bool:
    """Persist a short note (deduped, capped, TTL'd). Returns True if stored."""
    note = (fact or "").strip()[:200]
    if not redis or not patient_id or not note:
        return False
    try:
        key = _KEY.format(pid=patient_id)
        await redis.lrem(key, 0, note)  # dedup
        await redis.rpush(key, note)
        await redis.ltrim(key, -_MAX, -1)  # cap
        await redis.expire(key, _TTL_SECONDS)
        return True
    except Exception:  # noqa: BLE001
        return False


def render_memory_block(notes: list[str]) -> str:
    """Render remembered notes as a prompt block, or "" if none."""
    if not notes:
        return ""
    lines = "\n".join(f"- {n}" for n in notes[-12:])
    return (
        "WHAT YOU REMEMBER FROM BEFORE (use naturally; these are preferences/context, "
        "not clinical facts — cite clinical facts from the record):\n" + lines
    )
