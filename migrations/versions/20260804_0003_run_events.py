"""Add durable inspection run event log.

Revision ID: 20260804_0003
Revises: 20260804_0002
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260804_0003"
down_revision: str | None = "20260804_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspection_run_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("retries_left", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.String(length=255), nullable=True),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["inspection_runs.run_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_inspection_run_events_created_at",
        "inspection_run_events",
        ["created_at"],
    )
    op.create_index(
        "ix_inspection_run_events_event_type",
        "inspection_run_events",
        ["event_type"],
    )
    op.create_index(
        "ix_inspection_run_events_job_id",
        "inspection_run_events",
        ["job_id"],
    )
    op.create_index(
        "ix_inspection_run_events_run_id",
        "inspection_run_events",
        ["run_id"],
    )
    op.create_index(
        "ix_inspection_run_events_stage",
        "inspection_run_events",
        ["stage"],
    )
    op.create_index(
        "ix_inspection_run_events_status",
        "inspection_run_events",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_inspection_run_events_status", table_name="inspection_run_events")
    op.drop_index("ix_inspection_run_events_stage", table_name="inspection_run_events")
    op.drop_index("ix_inspection_run_events_run_id", table_name="inspection_run_events")
    op.drop_index("ix_inspection_run_events_job_id", table_name="inspection_run_events")
    op.drop_index("ix_inspection_run_events_event_type", table_name="inspection_run_events")
    op.drop_index("ix_inspection_run_events_created_at", table_name="inspection_run_events")
    op.drop_table("inspection_run_events")
