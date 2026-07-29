from __future__ import annotations

from uuid import uuid4

from storage.database import SessionLocal
from storage.repositories import (
    create_inspection_run,
    mark_inspection_completed,
    mark_inspection_failed,
    mark_inspection_running,
)


def test_completed_inspection_record_is_not_downgraded_by_retry() -> None:
    session = SessionLocal()
    run_id = f"idempotency_{uuid4().hex}"
    try:
        create_inspection_run(
            session,
            run_id=run_id,
            status="queued",
            request_data={
                "asset_id": "IDEMPOTENT-1",
                "asset_type": "bridge",
                "asset_name": "Idempotent Bridge",
                "location": "Retry corridor",
                "criticality": "high",
                "image_paths": [],
                "video_paths": [],
            },
        )
        completed = mark_inspection_completed(
            session,
            run_id=run_id,
            report_json=_completed_report(),
            rendered_report="completed report",
        )

        running_retry = mark_inspection_running(session, run_id=run_id)
        failed_retry = mark_inspection_failed(
            session,
            run_id=run_id,
            error="late retry failure",
        )

        assert completed.status == "completed"
        assert running_retry.status == "completed"
        assert failed_retry.status == "completed"
        assert failed_retry.error is None
        assert failed_retry.rendered_report == "completed report"
    finally:
        session.close()


def _completed_report() -> dict:
    return {
        "case": {"case_id": "CASE-IDEMPOTENT-1"},
        "severity": {"severity": "moderate", "repair_required": True},
        "maintenance_plan": {"recommended_action": "patch concrete"},
        "schedule": {
            "recommended_window": {
                "start": "2026-07-25T08:00:00",
                "end": "2026-07-25T12:00:00",
            }
        },
        "workflow_trace_id": "trace-1",
        "workflow_trace_path": "artifacts/traces/trace-1.json",
    }
