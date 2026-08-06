from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from storage.database import normalize_database_url
from storage.migrate import upgrade


def test_normalize_database_url_accepts_common_postgres_forms() -> None:
    assert (
        normalize_database_url("postgres://user:pass@localhost:5432/db")
        == "postgresql+psycopg://user:pass@localhost:5432/db"
    )
    assert (
        normalize_database_url("postgresql://user:pass@localhost:5432/db")
        == "postgresql+psycopg://user:pass@localhost:5432/db"
    )
    assert (
        normalize_database_url("postgresql+psycopg://user:pass@localhost:5432/db")
        == "postgresql+psycopg://user:pass@localhost:5432/db"
    )


def test_alembic_initial_schema_upgrade_creates_persistence_tables(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "migration_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    upgrade("head")

    engine = create_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)

    assert "inspection_runs" in inspector.get_table_names()
    assert "tool_runs" in inspector.get_table_names()
    assert "inspection_review_events" in inspector.get_table_names()
    assert "inspection_run_events" in inspector.get_table_names()
    assert "inspection_media" in inspector.get_table_names()

    inspection_columns = {
        column["name"] for column in inspector.get_columns("inspection_runs")
    }
    tool_run_columns = {
        column["name"] for column in inspector.get_columns("tool_runs")
    }
    assert {
        "run_id",
        "status",
        "request_json",
        "report_json",
        "review_status",
        "workflow_trace_id",
    }.issubset(inspection_columns)
    assert {
        "idempotency_key",
        "run_id",
        "tool_name",
        "input_hash",
        "output_json",
    }.issubset(tool_run_columns)

    review_event_columns = {
        column["name"] for column in inspector.get_columns("inspection_review_events")
    }
    assert {
        "event_id",
        "run_id",
        "previous_status",
        "new_status",
        "reviewer_notes",
        "reviewed_by",
        "created_at",
    }.issubset(review_event_columns)

    run_event_columns = {
        column["name"] for column in inspector.get_columns("inspection_run_events")
    }
    assert {
        "event_id",
        "run_id",
        "stage",
        "status",
        "message",
        "percent",
        "event_type",
        "attempt",
        "max_attempts",
        "retries_left",
        "job_id",
        "worker_name",
        "metadata_json",
        "created_at",
    }.issubset(run_event_columns)

    media_columns = {
        column["name"] for column in inspector.get_columns("inspection_media")
    }
    assert {
        "media_id",
        "run_id",
        "media_type",
        "original_filename",
        "content_type",
        "size_bytes",
        "checksum_sha256",
        "storage_backend",
        "storage_key",
        "file_path",
        "preview_url",
        "scan_status",
        "metadata_json",
        "created_at",
    }.issubset(media_columns)

    with engine.connect() as connection:
        version = connection.execute(
            text("select version_num from alembic_version")
        ).scalar_one()
    assert version == "20260805_0004"
