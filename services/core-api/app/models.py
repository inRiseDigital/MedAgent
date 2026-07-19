"""SQLAlchemy 2.0 declarative models for app_db (S1 subset).

IMPORTANT (10 §9): Alembic is the ONLY schema mechanism for app_db.
`Base.metadata.create_all()` is forbidden anywhere in application code — a CI
grep-guard enforces this. These models must stay in lockstep with
alembic/versions (checked by `alembic check` in CI).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QueueState(enum.Enum):
    waiting = "waiting"
    in_consultation = "in_consultation"
    done = "done"
    manual_verification = "manual_verification"


class CheckinSource(enum.Enum):
    face = "face"
    manual = "manual"


class PatientMPI(Base):
    """Master Patient Index row (02 §8) — identity/linkage state, never clinical data."""

    __tablename__ = "patients_mpi"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phn: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    nic: Mapped[str | None] = mapped_column(String(20), nullable=True)
    demographics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Opaque face-service enrolment id (05 §2) — never biometric data.
    ext_face_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    face_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sludi_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class QueueEntry(Base):
    """Arrival-queue entry (ephemeral operational state, 01 §3)."""

    __tablename__ = "queue_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients_mpi.id"), nullable=False, index=True
    )
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[QueueState] = mapped_column(
        Enum(QueueState, name="queue_state"), nullable=False, default=QueueState.waiting
    )
    arrival_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[CheckinSource] = mapped_column(
        Enum(CheckinSource, name="checkin_source"), nullable=False
    )


class AuditOutbox(Base):
    """Outbox for audit events, dispatched to the FHIR AuditEvent path (03 §5.3).

    S1: rows are written locally; the dispatcher job lands with the audit
    interceptor work. `event` payloads carry opaque IDs only — no PHI.
    """

    __tablename__ = "audit_outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
