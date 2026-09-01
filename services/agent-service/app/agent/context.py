"""Grounded-context builder (04 §2, plan P1.1).

Pre-loads a compact, CITED snapshot of the patient's record and the deterministic
safety brief, so the agent starts grounded in the chart instead of depending on
the model to choose the right read tools. Reuses core-api's existing, sanctioned
endpoints (`/patients/{phn}/summary`, `/patients/{phn}/brief`) with the caller's
bearer — the same consent/authz path the rest of the platform uses — rather than
re-implementing summarisation or hitting FHIR directly.

The result is injected into the worker's system prompt. It is best-effort: if the
record can't be loaded (no token, core-api down, PHN is a raw FHIR id), we return
an empty string and the agent falls back to on-demand tool calls.

Fail-closed care-relationship enforcement (the authz decision gate) is layered on
in Phase 2 (the supervisor ingress), where the care-relationship data is seeded
and verified — enabling it here would deny every request in the current phase.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Keep the injected block bounded so it never crowds out the conversation.
_MAX = {"problems": 10, "medications": 12, "allergies": 12, "vitals": 6, "results": 6, "flags": 8}


async def _get(client: httpx.AsyncClient, url: str, bearer: str) -> dict[str, Any] | None:
    try:
        resp = await client.get(url, headers={"authorization": bearer, "accept": "application/json"})
        if resp.status_code == 200:
            return resp.json()
        logger.info("context fetch %s -> %s", url, resp.status_code)
    except Exception as exc:  # noqa: BLE001 — grounding is best-effort
        logger.info("context fetch %s failed: %s", url, exc)
    return None


def _render(summary: dict[str, Any], brief: dict[str, Any] | None) -> str:
    p = summary.get("patient", {})
    lines: list[str] = []
    lines.append(
        "CURRENT PATIENT CONTEXT (pre-loaded from the record — treat as authoritative "
        "for what it lists, and reuse these [source: …] citations when you use a fact; "
        "call the tools for anything not shown here):"
    )
    who = ", ".join(
        x for x in [p.get("name"), p.get("gender"), f"DOB {p.get('birthDate')}" if p.get("birthDate") else None]
        if x
    )
    lines.append(f"- Patient: {who or 'unknown'} (PHN {p.get('phn', '?')}).")

    flags = (brief or {}).get("flags") or []
    if flags:
        rendered = "; ".join(
            f"{f.get('text', '')}" + (f" [source: {f['cite']}]" if f.get("cite") else "")
            for f in flags[: _MAX["flags"]]
        )
        lines.append(f"- SAFETY FLAGS (deterministic): {rendered}.")

    def _items(key: str, label: str, fmt) -> None:  # noqa: ANN001
        rows = summary.get(key) or []
        if not rows:
            return
        rendered = "; ".join(fmt(r) for r in rows[: _MAX[key]])
        lines.append(f"- {label}: {rendered}.")

    _items("problems", "Active problems", lambda r: f"{r.get('text', '?')} [source: {r.get('ref', '')}]")
    _items("medications", "Active medications", lambda r: f"{r.get('text', '?')} [source: {r.get('ref', '')}]")
    _items(
        "allergies",
        "Allergies",
        lambda r: f"{r.get('text', '?')} ({r.get('criticality', 'unknown')}) [source: {r.get('ref', '')}]",
    )
    _items(
        "vitals",
        "Recent vitals",
        lambda r: f"{r.get('text', '?')} {r.get('value', '')}{r.get('unit', '')}".strip(),
    )
    _items(
        "results",
        "Recent results",
        lambda r: f"{r.get('text', '?')}"
        + (" (CRITICAL)" if r.get("critical") else "")
        + f" [source: {r.get('ref', '')}]",
    )
    # Appointments are in the summary and often asked about ("when's my next
    # visit?") — including them here lets the agent answer from context instead of
    # spending a get_appointments round-trip.
    appts = [a for a in (summary.get("appointments") or []) if a.get("start")]
    if appts:
        rendered = "; ".join(
            f"{a.get('start')}" + (f" ({a['status']})" if a.get("status") else "")
            for a in appts[: _MAX.get("appointments", 6)]
        )
        lines.append(f"- Appointments: {rendered}.")
    return "\n".join(lines)


async def build_patient_context(core_api_base_url: str, bearer: str | None, phn: str) -> str:
    """Return a compact cited context block for `phn`, or "" if unavailable.

    `bearer` is the caller's Authorization header value ("Bearer <jwt>"); without
    it we cannot make a consent-checked read, so we skip grounding (the agent still
    works via tools).
    """
    if not bearer or not phn:
        return ""
    base = core_api_base_url.rstrip("/")
    summary_url = f"{base}/api/v1/patients/{phn}/summary"
    brief_url = f"{base}/api/v1/patients/{phn}/brief"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            summary, brief = await asyncio.gather(
                _get(client, summary_url, bearer),
                _get(client, brief_url, bearer),
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("context build failed: %s", exc)
        return ""
    if not summary:
        return ""
    return _render(summary, brief)
