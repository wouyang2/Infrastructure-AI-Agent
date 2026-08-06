"""Initial inspection persistence schema.

Revision ID: 20260804_0001
Revises:
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260804_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspection_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("asset_id", sa.String(length=128), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("asset_name", sa.String(length=255), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("criticality", sa.String(length=32), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("video_count", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=True),
        sa.Column("repair_required", sa.Boolean(), nullable=True),
        sa.Column("recommended_action", sa.String(length=255), nullable=True),
        sa.Column("schedule_start", sa.String(length=64), nullable=True),
        sa.Column("schedule_end", sa.String(length=64), nullable=True),
        sa.Column("workflow_trace_id", sa.String(length=128), nullable=True),
        sa.Column("workflow_trace_path", sa.String(length=512), nullable=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("rendered_report", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_inspection_runs_asset_id", "inspection_runs", ["asset_id"])
    op.create_index("ix_inspection_runs_asset_type", "inspection_runs", ["asset_type"])
    op.create_index("ix_inspection_runs_case_id", "inspection_runs", ["case_id"])
    op.create_index("ix_inspection_runs_created_at", "inspection_runs", ["created_at"])
    op.create_index("ix_inspection_runs_review_status", "inspection_runs", ["review_status"])
    op.create_index("ix_inspection_runs_severity", "inspection_runs", ["severity"])
    op.create_index("ix_inspection_runs_status", "inspection_runs", ["status"])
    op.create_index(
        "ix_inspection_runs_workflow_trace_id",
        "inspection_runs",
        ["workflow_trace_id"],
    )

    op.create_table(
        "tool_runs",
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    op.create_index("ix_tool_runs_created_at", "tool_runs", ["created_at"])
    op.create_index("ix_tool_runs_input_hash", "tool_runs", ["input_hash"])
    op.create_index("ix_tool_runs_run_id", "tool_runs", ["run_id"])
    op.create_index("ix_tool_runs_status", "tool_runs", ["status"])
    op.create_index("ix_tool_runs_tool_name", "tool_runs", ["tool_name"])


def downgrade() -> None:
    op.drop_index("ix_tool_runs_tool_name", table_name="tool_runs")
    op.drop_index("ix_tool_runs_status", table_name="tool_runs")
    op.drop_index("ix_tool_runs_run_id", table_name="tool_runs")
    op.drop_index("ix_tool_runs_input_hash", table_name="tool_runs")
    op.drop_index("ix_tool_runs_created_at", table_name="tool_runs")
    op.drop_table("tool_runs")

    op.drop_index("ix_inspection_runs_workflow_trace_id", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_status", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_severity", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_review_status", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_created_at", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_case_id", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_asset_type", table_name="inspection_runs")
    op.drop_index("ix_inspection_runs_asset_id", table_name="inspection_runs")
    op.drop_table("inspection_runs")
