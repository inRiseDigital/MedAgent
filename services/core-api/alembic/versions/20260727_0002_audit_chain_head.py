"""audit_chain_head: strongly-consistent head of the audit hash chain

Revision ID: 0002_audit_chain_head
Revises: 0001_initial
Create Date: 2026-07-27

The tamper-evident audit hash chain (03 §5.4) previously derived its head by
searching FHIR AuditEvent (`_sort=-_lastUpdated`). HAPI's search index is
eventually-consistent, so a dispatcher could read a stale head and re-mint a
sequence number — forking the chain (observed: duplicate seq). This table holds
the head (single row id=1) in Postgres, which is read-your-writes; combined with
the dispatch advisory lock, sequence assignment is exact.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_audit_chain_head"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_head",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("hash", sa.String(), nullable=False, server_default=sa.text("'GENESIS'")),
        sa.Column(
            "updated_ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # Seed the single head row so the dispatcher never has to special-case a
    # missing row.
    op.execute("INSERT INTO audit_chain_head (id, seq, hash) VALUES (1, 0, 'GENESIS')")


def downgrade() -> None:
    op.drop_table("audit_chain_head")
