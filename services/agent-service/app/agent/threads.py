"""Server-owned conversation threads (P2 / H0-S1).

A durable, server-side transcript of a conversation, keyed by conversation_id, in
the Redis we already run — no LangGraph checkpointer dependency. When the client
sends a conversation_id, the server is the source of truth for the history: the
turn is built from the stored thread + the newest user message, so the thread
survives a page reload and the client can stop re-sending the whole conversation.

PHI note: this stores conversation text (which is about the patient), exactly like
the chat itself does in transit — it lives in the same trust boundary as the rest
of the record data, is scoped per conversation, and expires. It is NOT long-term
semantic memory (that is app/agent/memory.py, preferences only).
"""

from __future__ import annotations

import json
import re
from typing import Any

# The key is namespaced by the VERIFIED owner (sub + patient fhir id), never by the
# request body alone. `owner` is a collision-safe composite the caller derives from
# the authenticated principal; `cid` is the client-supplied conversation id.
_KEY = "agent:thread:{owner}:{cid}"
_MAX_TURNS = 40  # keep the window bounded (user+assistant messages)
_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# Chars that would let a crafted id break out of its namespace: the ':' segment
# separator, Redis glob wildcards, and any whitespace. Collapse them to '_' so no
# id part can inject an extra segment or a wildcard and reach another owner's key.
_UNSAFE = re.compile(r"[:*?\[\]\s]+")


def _sanitize(part: str | None) -> str:
    """Neutralise one key fragment so it can't cross a namespace boundary."""
    return _UNSAFE.sub("_", str(part or "").strip()) or "_"


def _thread_key(sub: str | None, patient_fhir_id: str | None, conversation_id: str | None) -> str:
    """Build the fully owner-scoped Redis key. Each fragment is sanitized, so the key
    always has exactly `agent:thread:<sub>:<fhir>:<cid>` — an unambiguous, per-owner
    namespace. Two callers with different subs (or different patients) can never
    resolve to the same key even with an identical conversation_id."""
    owner = f"{_sanitize(sub)}:{_sanitize(patient_fhir_id)}"
    return _KEY.format(owner=owner, cid=_sanitize(conversation_id))


async def load_thread(
    redis: Any, sub: str | None, patient_fhir_id: str | None, conversation_id: str | None
) -> list[dict[str, str]]:
    """Return the stored [{role, content}] history for a conversation, oldest first.

    Ownership binding (BOLA fix): the thread is keyed by the VERIFIED caller identity
    (`sub` + `patient_fhir_id`) as well as the conversation_id. A random
    conversation_id is not authorization — supplying someone else's raw id resolves
    to a DIFFERENT (empty) key, never their history. Privilege derives from the
    server-verified principal, never from the request body.

    Best-effort: empty list if no id, no redis, or on any error."""
    if not redis or not conversation_id:
        return []
    try:
        rows = await redis.lrange(_thread_key(sub, patient_fhir_id, conversation_id), -_MAX_TURNS, -1)
    except Exception:  # noqa: BLE001 — threads are best-effort, never break a turn
        return []
    out: list[dict[str, str]] = []
    for r in rows:
        try:
            obj = json.loads(r)
            if isinstance(obj, dict) and obj.get("role") in ("user", "assistant") and obj.get("content"):
                out.append({"role": obj["role"], "content": str(obj["content"])})
        except Exception:  # noqa: BLE001
            continue
    return out


async def append_turn(
    redis: Any,
    sub: str | None,
    patient_fhir_id: str | None,
    conversation_id: str | None,
    user_text: str,
    assistant_text: str,
) -> None:
    """Append the completed (user, assistant) exchange to the thread (capped, TTL'd).
    Owner-scoped exactly like load_thread — writes land only under the caller's own
    sub+patient namespace, so one user can never append to another's thread.
    Best-effort — a storage hiccup must never fail the response the user already got."""
    if not redis or not conversation_id:
        return
    user_text = (user_text or "").strip()
    assistant_text = (assistant_text or "").strip()
    if not user_text and not assistant_text:
        return
    try:
        key = _thread_key(sub, patient_fhir_id, conversation_id)
        # Individual awaits (matching app/agent/memory.py) — no pipeline, to keep the
        # async Redis usage identical to the proven path.
        if user_text:
            await redis.rpush(key, json.dumps({"role": "user", "content": user_text[:8000]}))
        if assistant_text:
            await redis.rpush(key, json.dumps({"role": "assistant", "content": assistant_text[:8000]}))
        await redis.ltrim(key, -_MAX_TURNS, -1)
        await redis.expire(key, _TTL_SECONDS)
    except Exception:  # noqa: BLE001
        return
