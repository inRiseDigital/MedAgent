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

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.fhir_client import FHIRClient
from app.models import AuditChainHead, AuditOutbox

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
    "referral_created": "C",
    "referral_state_change": "U",
    "waitlist_add": "C",
    "appointment_booked": "U",
    "econsult_created": "C",
    "econsult_started": "U",
    "econsult_completed": "U",
    "imaging_reported": "C",
    "imaging_urgent_flag": "R",
    "notifiable_disease_reported": "C",
    "notifiable_disease_alert": "R",
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


# Serialise the whole dispatch across the process (background loop) AND the
# manual /internal/audit/dispatch endpoint AND any extra uvicorn workers. Without
# this, two dispatchers can both read the same chain head and mint duplicate
# sequence numbers — forking the hash chain (03 §5.4). A Postgres session-level
# advisory lock is process- and worker-safe; if another dispatcher holds it we
# skip this cycle and the pending rows are simply retried next time.
_DISPATCH_LOCK_KEY = 0x4155_4454  # "AUDT"


async def dispatch_once(
    sessionmaker: async_sessionmaker, fhir_base_url: str, limit: int = 100
) -> int:
    """Drain up to `limit` undispatched outbox rows into FHIR AuditEvents.
    Returns the number dispatched (0 if another dispatcher holds the lock)."""
    dispatched = 0
    fhir = FHIRClient(fhir_base_url)
    try:
        # The lock is held on its OWN session/connection that never commits until
        # unlock — the drain session commits per row, which would otherwise return
        # the lock-holding connection to the pool and drop the (session-level) lock.
        async with sessionmaker() as lock_session:
            got = (
                await lock_session.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": _DISPATCH_LOCK_KEY}
                )
            ).scalar()
            if not got:
                logger.debug("audit dispatch skipped — another dispatcher holds the lock")
                return 0
            try:
                async with sessionmaker() as work_session:
                    dispatched = await _drain(work_session, fhir, limit)
            finally:
                await lock_session.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _DISPATCH_LOCK_KEY}
                )
                await lock_session.rollback()  # end the lock txn; connection resets
    finally:
        await fhir.close()
    return dispatched


async def _drain(session: Any, fhir: FHIRClient, limit: int) -> int:
    """Chain-and-write pending outbox rows. Caller must hold the dispatch lock.

    The chain head is read from the `audit_chain_head` row (Postgres, read-your-
    writes) — never from a FHIR search — and advanced in the SAME transaction that
    marks each row dispatched, so a stale search index can never cause a duplicate
    sequence number.
    """
    dispatched = 0
    rows = (
        await session.execute(
            select(AuditOutbox)
            .where(AuditOutbox.dispatched.is_(False))
            .order_by(AuditOutbox.created_ts)
            .limit(limit)
        )
    ).scalars().all()
    if not rows:
        return 0
    head = (
        await session.execute(select(AuditChainHead).where(AuditChainHead.id == 1))
    ).scalar_one_or_none()
    if head is None:  # defensive — the migration seeds this row
        head = AuditChainHead(id=1, seq=0, hash=_GENESIS)
        session.add(head)
        await session.flush()
    seq, prev_hash = head.seq, head.hash
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
        head.seq, head.hash = seq, prev_hash  # persisted atomically with the row below
        row.dispatched = True
        await session.commit()
        dispatched += 1
    return dispatched


async def verify_chain(fhir_base_url: str, limit: int = 5000) -> dict[str, Any]:
    """Walk the chained AuditEvents in sequence and recompute the hash chain.
    Returns whether it is intact and, if not, the seq where it first broke —
    proof the audit trail has not been altered (03 §5.4, NFR-8).

    Robustness (learned the hard way): this must never report `intact: true` when
    it simply could not read the chain. We fetch a plain page (no dependency on a
    `_sort` param, which can silently return nothing on a cold search index) and
    compare against the server's own count; a shortfall yields `intact: null` with
    a reason rather than a false pass. We also explicitly flag duplicate sequence
    numbers — the exact signature of a fork from concurrent dispatch.
    """
    fhir = FHIRClient(fhir_base_url)
    try:
        total = await _audit_count(fhir)
        # Plain search, high _count — no reliance on a (possibly cold) sort index.
        events = await fhir.search("AuditEvent", {"_count": str(limit)})
    finally:
        await fhir.close()
    return evaluate_chain(events, total)


def evaluate_chain(events: list[dict[str, Any]], total: int) -> dict[str, Any]:
    """Pure chain evaluation over the fetched AuditEvents (unit-testable, no I/O).

    Never reports intact=true when it could not read the chain (false-pass guard),
    flags duplicate sequence numbers (fork), recomputes each hash + prevHash link,
    and flags a truncated read (intact=null)."""
    # False-pass guard: the store reports events but we retrieved none → a read
    # problem, not an empty/intact chain.
    if total > 0 and not events:
        return {"events": 0, "total": total, "intact": None,
                "error": "could not read AuditEvents (retrieved 0 of %d)" % total}

    chained = []
    for ae in events:
        ext = _read_hash_ext(ae)
        if ext and ext.get("hash"):
            chained.append((int(ext.get("seq") or 0), ext, ae))
    chained.sort(key=lambda t: t[0])

    # Duplicate seq = a fork (two dispatchers minted the same seq). Detect it
    # explicitly rather than relying on the linkage check downstream.
    seqs = [s for s, _, _ in chained]
    dup = next((s for s in seqs if seqs.count(s) > 1), None)
    if dup is not None:
        return {"events": len(chained), "total": total, "intact": False,
                "broken_at_seq": dup, "error": f"duplicate sequence {dup} (chain fork)"}

    # If we couldn't page the whole store, we can't vouch for the tail.
    truncated = len(events) < total

    prev = _GENESIS
    for seq, ext, ae in chained:
        recomputed = _chain_hash(str(ext.get("prevHash") or _GENESIS), ae)
        if str(ext.get("prevHash")) != prev or recomputed != str(ext.get("hash")):
            return {"events": len(chained), "total": total, "intact": False, "broken_at_seq": seq}
        prev = str(ext["hash"])
    out: dict[str, Any] = {"events": len(chained), "total": total,
                           "intact": (None if truncated else True), "broken_at_seq": None}
    if truncated:
        out["error"] = f"verified {len(events)} of {total} events; tail not read"
    return out


async def _audit_count(fhir: FHIRClient) -> int:
    """Server-reported total AuditEvent count (via _summary=count)."""
    try:
        resp = await fhir._get("/AuditEvent", params={"_summary": "count"}, token=None)
        return int(resp.json().get("total") or 0)
    except Exception:  # noqa: BLE001 — count is a guard, not the source of truth
        return 0
