"""Add inspection review event audit table.

Revision ID: 20260804_0002
Revises: 20260804_0001
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260804_0002"
down_revision: str | None = "20260804_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspection_review_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["inspection_runs.run_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_inspection_review_events_created_at",
        "inspection_review_events",
        ["created_at"],
    )
    op.create_index(
        "ix_inspection_review_events_new_status",
        "inspection_review_events",
        ["new_status"],
    )
    op.create_index(
        "ix_inspection_review_events_reviewed_by",
        "inspection_review_events",
        ["reviewed_by"],
    )
    op.create_index(
        "ix_inspection_review_events_run_id",
        "inspection_review_events",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inspection_review_events_run_id",
        table_name="inspection_review_events",
    )
    op.drop_index(
        "ix_inspection_review_events_reviewed_by",
        table_name="inspection_review_events",
    )
    op.drop_index(
        "ix_inspection_review_events_new_status",
        table_name="inspection_review_events",
    )
    op.drop_index(
        "ix_inspection_review_events_created_at",
        table_name="inspection_review_events",
    )
    op.drop_table("inspection_review_events")
