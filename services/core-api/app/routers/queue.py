"""Arrival queue: current queue, manual check-in, state transitions (FR-2.1, 02 §7)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_user
from app.deps import get_redis, get_session
from app.events import publish_checkin
from app.models import AuditOutbox, CheckinSource, PatientMPI, QueueEntry, QueueState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/queue", tags=["queue"])


class QueueEntryOut(BaseModel):
    id: UUID
    patient_id: UUID
    facility_id: str
    state: QueueState
    arrival_ts: datetime
    source: CheckinSource


class QueueRowOut(QueueEntryOut):
    """Enriched queue row for the doctor workspace (06 §3): adds server-assigned
    arrival sequence and minimal patient display fields. Display-only demographic
    data — opening the clinical record still requires a care-relationship grant
    (02 §7)."""

    sequence: int
    display_name: str
    phn_fragment: str
    needs_manual_verification: bool


class ManualCheckinRequest(BaseModel):
    patient_id: UUID
    facility_id: str


class StateChangeRequest(BaseModel):
    state: QueueState


def _to_out(row: QueueEntry) -> QueueEntryOut:
    return QueueEntryOut(
        id=row.id,
        patient_id=row.patient_id,
        facility_id=row.facility_id,
        state=row.state,
        arrival_ts=row.arrival_ts,
        source=row.source,
    )


def _phn_fragment(phn: str) -> str:
    """Last four digits only — enough to disambiguate at a glance without
    exposing the full identifier in the queue view (06 §3)."""
    return f"…{phn[-4:]}" if len(phn) >= 4 else phn


@router.get("", response_model=list[QueueRowOut])
async def current_queue(
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    facility_id: Annotated[str, Query(min_length=1)],
    include_done: Annotated[bool, Query()] = False,
) -> list[QueueRowOut]:
    """Current queue for a facility in arrival order, with server-assigned
    sequence and patient display fields (06 §3). TODO(S3): day rollover."""
    query = (
        select(QueueEntry, PatientMPI)
        .join(PatientMPI, PatientMPI.id == QueueEntry.patient_id)
        .where(QueueEntry.facility_id == facility_id)
        .order_by(QueueEntry.arrival_ts)
    )
    if not include_done:
        query = query.where(QueueEntry.state != QueueState.done)
    rows = (await session.execute(query)).all()
    return [
        QueueRowOut(
            id=entry.id,
            patient_id=entry.patient_id,
            facility_id=entry.facility_id,
            state=entry.state,
            arrival_ts=entry.arrival_ts,
            source=entry.source,
            sequence=index + 1,
            display_name=str(patient.demographics.get("name", "Unknown")),
            phn_fragment=_phn_fragment(patient.phn),
            needs_manual_verification=entry.state == QueueState.manual_verification,
        )
        for index, (entry, patient) in enumerate(rows)
    ]


@router.post("/check-in", status_code=status.HTTP_201_CREATED, response_model=QueueEntryOut)
async def manual_check_in(
    body: ManualCheckinRequest,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> QueueEntryOut:
    """Manual check-in after receptionist identity confirmation (FR-1.5/2.4).

    Check-in is the authorisation event that creates the queue-based
    care-relationship grant (02 §7.1) — grant materialisation lands with the
    authz decision service.
    """
    patient = (
        await session.execute(select(PatientMPI).where(PatientMPI.id == body.patient_id))
    ).scalar_one_or_none()
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown patient")

    entry = QueueEntry(
        patient_id=patient.id,
        facility_id=body.facility_id,
        state=QueueState.waiting,
        source=CheckinSource.manual,
    )
    session.add(entry)
    await session.flush()
    session.add(
        AuditOutbox(
            event={
                "type": "checkin",
                "source": "manual",
                "actor": principal.subject,
                "patient_id": str(patient.id),
                "queue_entry_id": str(entry.id),
                "facility_id": body.facility_id,
            }
        )
    )
    await publish_checkin(
        redis,
        body.facility_id,
        {
            "type": "checkin",
            "queue_entry_id": str(entry.id),
            "patient_id": str(patient.id),
            "facility_id": body.facility_id,
            "source": "manual",
        },
    )
    logger.info(
        "manual check-in",
        extra={"queue_entry_id": str(entry.id), "facility_id": body.facility_id},
    )
    return _to_out(entry)


@router.post("/{entry_id}/state", response_model=QueueEntryOut)
async def change_state(
    entry_id: UUID,
    body: StateChangeRequest,
    principal: Annotated[Principal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueueEntryOut:
    """Transition a queue entry (waiting → in_consultation → done, or
    manual_verification → waiting after identity confirmation).

    TODO(S3): enforce a transition matrix + emit authz-cache invalidation
    events (02 §7.4). S1 accepts any target state.
    """
    entry = (
        await session.execute(select(QueueEntry).where(QueueEntry.id == entry_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown queue entry")

    previous = entry.state
    entry.state = body.state
    session.add(
        AuditOutbox(
            event={
                "type": "queue_state_change",
                "actor": principal.subject,
                "queue_entry_id": str(entry.id),
                "from": previous.value,
                "to": body.state.value,
            }
        )
    )
    return _to_out(entry)
