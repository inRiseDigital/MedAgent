"""Audit outbox dispatcher (03 §5.3, NFR-8).

core-api write paths record an `audit_outbox` row in the same transaction as the
change (never lost). This dispatcher drains the outbox into FHIR `AuditEvent`
resources so the audit trail is queryable — the source of the patient access log
(FR-5.8) and the admin audit explorer (FR-6.3). Dispatch is per-row + committed
individually, so a mid-run FHIR failure never double-writes: an undispatched row
is simply retried next cycle.

NOTE: in the target design AuditEvents are written by the HAPI audit interceptor
directly (03 §5.3) and hash-chained (§5.4). Until the custom interceptor image
lands (S2), this app-side dispatcher provides the queryable trail; the schema is
compatible so the interceptor can take over without a data migration.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.fhir_client import FHIRClient
from app.models import AuditOutbox

logger = logging.getLogger(__name__)

_TYPE_SYSTEM = "https://fhir.medagent.health.lk/cs/audit-event-type"

# Tamper-evident hash chain (03 §5.4, backlog 0.2). Each AuditEvent carries an
# extension linking it to the previous: hash = SHA-256(prevHash | canonical
# fields). Altering any event's content changes its recomputed hash and breaks
# the next event's prevHash link — detectable by GET /internal/audit/verify.
AUDIT_HASH_EXT = "https://fhir.medagent.health.lk/ext/audit-hash"
_GENESIS = "GENESIS"


def _chain_basis(ae: dict[str, Any]) -> str:
    """Canonical, stable projection of the AuditEvent's meaningful content. Does
    NOT include the hash extension or HAPI-added fields (id/meta), so it is
    reproducible at verify time."""
    return json.dumps(
        {k: ae.get(k) for k in ("type", "action", "recorded", "agent", "entity", "outcome", "outcomeDesc")},
        sort_keys=True, separators=(",", ":"), default=str,
    )


def _chain_hash(prev: str, ae: dict[str, Any]) -> str:
    return hashlib.sha256(f"{prev}|{_chain_basis(ae)}".encode()).hexdigest()


def _read_hash_ext(ae: dict[str, Any]) -> dict[str, Any] | None:
    for e in ae.get("extension", []):
        if e.get("url") == AUDIT_HASH_EXT:
            out: dict[str, Any] = {}
            for x in e.get("extension", []):
                out[x["url"]] = x.get("valueString", x.get("valueInteger"))
            return out
    return None


async def _chain_head(fhir: FHIRClient) -> tuple[int, str]:
    """The (seq, hash) of the most recent chained AuditEvent, or (0, GENESIS)."""
    recent = await fhir.search("AuditEvent", {"_sort": "-_lastUpdated", "_count": "10"})
    for ae in recent:
        h = _read_hash_ext(ae)
        if h and h.get("hash"):
            return int(h.get("seq") or 0), str(h["hash"])
    return 0, _GENESIS

# Map outbox event types to FHIR AuditEvent.action (C/R/U/D/E).
_ACTION = {
    "patient_registered": "C",
    "birth_enrolment": "C",
    "immunization_recorded": "C",
    "growth_recorded": "C",
    "checkin": "C",
    "proposal_committed": "C",
    "queue_state_change": "U",
    "consent_denied": "R",
    "consent_change": "U",
    "record_exported": "E",
    "lab_state_change": "U",
    "lab_result_released": "C",
    "lab_critical_value": "R",
}


def _to_audit_event(row: AuditOutbox) -> dict[str, Any]:
    event = row.event or {}
    etype = str(event.get("type", "unknown"))
    actor = str(event.get("actor", "system"))
    action = _ACTION.get(etype, "R")

    entity_ref = (
        event.get("committed")
        or (f"Patient/{event['patient_fhir_id']}" if event.get("patient_fhir_id") else None)
    )
    ae: dict[str, Any] = {
        "resourceType": "AuditEvent",
        "type": {"system": _TYPE_SYSTEM, "code": etype},
        "action": action,
        "recorded": row.created_ts.isoformat(),
        "outcome": "0",  # success
        "agent": [{"who": {"display": actor}, "requestor": True}],
        "source": {"observer": {"display": "core-api"}},
    }
    entities: list[dict[str, Any]] = []
    if entity_ref:
        entities.append({"what": {"reference": entity_ref}})
    # Always reference the patient too, so the access log (FR-5.8) can query by subject.
    if event.get("patient_fhir_id"):
        pref = f"Patient/{event['patient_fhir_id']}"
        if pref != entity_ref:
            entities.append({"what": {"reference": pref}})
    if entities:
        ae["entity"] = entities
    # Carry the safety verdict / override so the audit is self-describing (03 §5.3).
    if event.get("rx_verdict"):
        ae.setdefault("entity", []).append(
            {"detail": [{"type": "rx_verdict", "valueString": str(event["rx_verdict"])}]}
        )
    if event.get("override_reason"):
        ae["outcomeDesc"] = f"override: {event['override_reason']}"
    return ae


async def dispatch_once(
    sessionmaker: async_sessionmaker, fhir_base_url: str, limit: int = 100
) -> int:
    """Drain up to `limit` undispatched outbox rows into FHIR AuditEvents.
    Returns the number dispatched."""
    dispatched = 0
    fhir = FHIRClient(fhir_base_url)
    try:
        async with sessionmaker() as session:
            rows = (
                await session.execute(
                    select(AuditOutbox)
                    .where(AuditOutbox.dispatched.is_(False))
                    .order_by(AuditOutbox.created_ts)
                    .limit(limit)
                )
            ).scalars().all()
            seq, prev_hash = await _chain_head(fhir) if rows else (0, _GENESIS)
            for row in rows:
                try:
                    ae = _to_audit_event(row)
                    h = _chain_hash(prev_hash, ae)
                    ae.setdefault("extension", []).append({
                        "url": AUDIT_HASH_EXT,
                        "extension": [
                            {"url": "seq", "valueInteger": seq + 1},
                            {"url": "prevHash", "valueString": prev_hash},
                            {"url": "hash", "valueString": h},
                        ],
                    })
                    await fhir.create("AuditEvent", ae)
                except Exception:  # noqa: BLE001 — leave undispatched, retry next cycle
                    logger.exception("audit dispatch failed for row %s", row.id)
                    continue
                seq, prev_hash = seq + 1, h  # advance the chain only on success
                row.dispatched = True
                await session.commit()
                dispatched += 1
    finally:
        await fhir.close()
    return dispatched


async def verify_chain(fhir_base_url: str, limit: int = 500) -> dict[str, Any]:
    """Walk the chained AuditEvents in sequence and recompute the hash chain.
    Returns whether it is intact and, if not, the seq where it first broke —
    proof the audit trail has not been altered (03 §5.4, NFR-8)."""
    fhir = FHIRClient(fhir_base_url)
    try:
        # newest-first so the chained events (created since 0.2 shipped) are in
        # the page even when the store holds many older, pre-chain events.
        events = await fhir.search("AuditEvent", {"_sort": "-_lastUpdated", "_count": str(limit)})
    finally:
        await fhir.close()

    chained = []
    for ae in events:
        ext = _read_hash_ext(ae)
        if ext and ext.get("hash"):
            chained.append((int(ext.get("seq") or 0), ext, ae))
    chained.sort(key=lambda t: t[0])

    prev = _GENESIS
    for seq, ext, ae in chained:
        recomputed = _chain_hash(str(ext.get("prevHash") or _GENESIS), ae)
        if str(ext.get("prevHash")) != prev or recomputed != str(ext.get("hash")):
            return {"events": len(chained), "intact": False, "broken_at_seq": seq}
        prev = str(ext["hash"])
    return {"events": len(chained), "intact": True, "broken_at_seq": None}
