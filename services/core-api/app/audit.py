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

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.fhir_client import FHIRClient
from app.models import AuditOutbox

logger = logging.getLogger(__name__)

_TYPE_SYSTEM = "https://fhir.medagent.health.lk/cs/audit-event-type"

# Map outbox event types to FHIR AuditEvent.action (C/R/U/D/E).
_ACTION = {
    "patient_registered": "C",
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
            for row in rows:
                try:
                    await fhir.create("AuditEvent", _to_audit_event(row))
                except Exception:  # noqa: BLE001 — leave undispatched, retry next cycle
                    logger.exception("audit dispatch failed for row %s", row.id)
                    continue
                row.dispatched = True
                await session.commit()
                dispatched += 1
    finally:
        await fhir.close()
    return dispatched
