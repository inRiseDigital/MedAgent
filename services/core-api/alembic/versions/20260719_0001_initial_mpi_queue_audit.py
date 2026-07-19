"""initial: patients_mpi, queue_entries, audit_outbox

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-19

S1 baseline for app_db (10 §9: Alembic is the only schema mechanism; no
create_all exists anywhere in application code). Downgrade path provided per
the last-5-revisions rule.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

queue_state = sa.Enum(
    "waiting", "in_consultation", "done", "manual_verification", name="queue_state"
)
checkin_source = sa.Enum("face", "manual", name="checkin_source")


def upgrade() -> None:
    op.create_table(
        "patients_mpi",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("phn", sa.String(length=11), nullable=False),
        sa.Column("nic", sa.String(length=20), nullable=True),
        sa.Column(
            "demographics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ext_face_id", sa.String(length=128), nullable=True),
        sa.Column("face_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sludi_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("phn", name="uq_patients_mpi_phn"),
        sa.UniqueConstraint("ext_face_id", name="uq_patients_mpi_ext_face_id"),
    )
    op.create_index("ix_patients_mpi_phn", "patients_mpi", ["phn"])

    op.create_table(
        "queue_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients_mpi.id", name="fk_queue_entries_patient_id"),
            nullable=False,
        ),
        sa.Column("facility_id", sa.String(length=64), nullable=False),
        sa.Column("state", queue_state, nullable=False, server_default="waiting"),
        sa.Column(
            "arrival_ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source", checkin_source, nullable=False),
    )
    op.create_index("ix_queue_entries_patient_id", "queue_entries", ["patient_id"])
    op.create_index("ix_queue_entries_facility_id", "queue_entries", ["facility_id"])

    op.create_table(
        "audit_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("dispatched", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("audit_outbox")
    op.drop_index("ix_queue_entries_facility_id", table_name="queue_entries")
    op.drop_index("ix_queue_entries_patient_id", table_name="queue_entries")
    op.drop_table("queue_entries")
    op.drop_index("ix_patients_mpi_phn", table_name="patients_mpi")
    op.drop_table("patients_mpi")
    bind = op.get_bind()
    queue_state.drop(bind, checkfirst=True)
    checkin_source.drop(bind, checkfirst=True)
