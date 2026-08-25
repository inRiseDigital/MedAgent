"""Care-relationship authorisation decision service (02 §7.2, 03 §5.1).

The HAPI FHIR AuthzInterceptor answers "does this actor hold a role/scope that
may touch this resource type" locally; it defers the *care-relationship*
question — "may this actor access THIS patient right now" — to this endpoint,
fronted by a shared Redis decision cache (`authz:{actor}:{patient}`, TTL 60 s).
Fixing the prototype flaw where any doctor could read every record.

Contract (internal — never exposed through the public gateway route):

    GET /internal/authz/decision?actor=<sub>&patient=<phn>&purpose=<TREAT|BTG>

    -> 200 {permit, purpose_of_use, reason, ttl}

The same decision is written to `authz:{actor}:{patient}` so the interceptor's
cache lookup and this service never disagree.

S1 scope: the care relationship is approximated by a **queue-based grant** — a
patient with an active check-in (waiting / in_consultation) is accessible to
on-duty clinicians at the hospital. Per-actor scoping (the actor's own facility
and assigned patients) and **encounter-based** grants (FHIR Encounter) land in
S2 (02 §7). Break-glass (purpose=BTG) is fail-closed here: the automated grant
flow is Phase B, so S1 returns permit=false and the pilot uses the audited
manual-override procedure (02 §6, 08 §8).
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.deps import get_redis, get_session
from app.models import PatientMPI, QueueEntry, QueueState

router = APIRouter(prefix="/internal/authz", tags=["authz-internal"])

DECISION_CACHE_KEY = "authz:{actor}:{patient}"
DECISION_TTL_SECONDS = 60

_ACTIVE_STATES = (QueueState.waiting, QueueState.in_consultation)


class Decision(BaseModel):
    permit: bool
    purpose_of_use: Literal["TREAT", "BTG"]
    reason: str
    ttl: int = DECISION_TTL_SECONDS


async def _evaluate(patient_phn: str, session: AsyncSession) -> Decision:
    """Queue-based grant (S1). TODO(S2): per-actor facility scoping + Encounter grants."""
    stmt = (
        select(QueueEntry.id)
        .join(PatientMPI, PatientMPI.id == QueueEntry.patient_id)
        .where(PatientMPI.phn == patient_phn)
        .where(QueueEntry.state.in_(_ACTIVE_STATES))
        .limit(1)
    )
    has_active = (await session.execute(stmt)).first() is not None
    if has_active:
        return Decision(permit=True, purpose_of_use="TREAT", reason="queue-grant")
    return Decision(
        permit=False,
        purpose_of_use="TREAT",
        reason="no-active-care-relationship",
    )


async def require_care_relationship(
    phn: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Route dependency (P3.2/B3): a clinician may only read a patient-scoped
    record when a care relationship exists (the S1 queue-grant). Closes the
    prototype flaw where any doctor could read every record.

    Patient (and guardian) self-access is always allowed — the patient portal
    only ever reaches the session's own PHN through the BFF, so there is no
    cross-patient exposure to gate there. Dev auth-disabled short-circuits.
    """
    if request.app.state.settings.auth_disabled:
        return
    if principal.has_role("patient"):
        return  # self-scoped by the session-bound BFF
    decision = await _evaluate(phn, session)
    if not decision.permit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no active care relationship for this patient",
        )


@router.get("/decision", response_model=Decision)
async def decision(
    redis: Annotated[Redis, Depends(get_redis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[str, Query(min_length=1, description="Keycloak subject of the caller")],
    patient: Annotated[str, Query(min_length=1, description="Patient PHN (S1)")],
    purpose: Annotated[Literal["TREAT", "BTG"], Query()] = "TREAT",
) -> Decision:
    # Break-glass is fail-closed in S1 — the automated grant flow is Phase B.
    if purpose == "BTG":
        result = Decision(
            permit=False,
            purpose_of_use="BTG",
            reason="break-glass-automated-flow-is-phase-b; use audited manual override (02 §6)",
        )
        # Not cached: break-glass decisions must never be served from cache.
        return result

    result = await _evaluate(patient, session)

    # Populate the shared decision cache the interceptor reads first.
    await redis.set(
        DECISION_CACHE_KEY.format(actor=actor, patient=patient),
        json.dumps(result.model_dump()),
        ex=DECISION_TTL_SECONDS,
    )
    return result
