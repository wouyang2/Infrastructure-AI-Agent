"""Add inspection media metadata table.

Revision ID: 20260805_0004
Revises: 20260804_0003
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260805_0004"
down_revision: str | None = "20260804_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspection_media",
        sa.Column("media_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("preview_url", sa.String(length=512), nullable=False),
        sa.Column("scan_status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["inspection_runs.run_id"]),
        sa.PrimaryKeyConstraint("media_id"),
    )
    op.create_index("ix_inspection_media_checksum_sha256", "inspection_media", ["checksum_sha256"])
    op.create_index("ix_inspection_media_created_at", "inspection_media", ["created_at"])
    op.create_index("ix_inspection_media_file_path", "inspection_media", ["file_path"])
    op.create_index("ix_inspection_media_media_type", "inspection_media", ["media_type"])
    op.create_index("ix_inspection_media_run_id", "inspection_media", ["run_id"])
    op.create_index("ix_inspection_media_scan_status", "inspection_media", ["scan_status"])
    op.create_index("ix_inspection_media_storage_backend", "inspection_media", ["storage_backend"])
    op.create_index("ix_inspection_media_storage_key", "inspection_media", ["storage_key"])


def downgrade() -> None:
    op.drop_index("ix_inspection_media_storage_key", table_name="inspection_media")
    op.drop_index("ix_inspection_media_storage_backend", table_name="inspection_media")
    op.drop_index("ix_inspection_media_scan_status", table_name="inspection_media")
    op.drop_index("ix_inspection_media_run_id", table_name="inspection_media")
    op.drop_index("ix_inspection_media_media_type", table_name="inspection_media")
    op.drop_index("ix_inspection_media_file_path", table_name="inspection_media")
    op.drop_index("ix_inspection_media_created_at", table_name="inspection_media")
    op.drop_index("ix_inspection_media_checksum_sha256", table_name="inspection_media")
    op.drop_table("inspection_media")
