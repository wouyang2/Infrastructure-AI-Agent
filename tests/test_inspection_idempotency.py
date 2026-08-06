from __future__ import annotations

from uuid import uuid4

from storage.database import SessionLocal
from storage.repositories import (
    append_inspection_run_event,
    create_inspection_run,
    list_inspection_run_events,
    list_inspection_review_events,
    mark_inspection_completed,
    mark_inspection_failed,
    mark_inspection_running,
    update_inspection_review,
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


def test_review_updates_append_audit_events() -> None:
    session = SessionLocal()
    run_id = f"review_audit_{uuid4().hex}"
    try:
        create_inspection_run(
            session,
            run_id=run_id,
            status="queued",
            request_data={
                "asset_id": "REVIEW-AUDIT-1",
                "asset_type": "bridge",
                "asset_name": "Review Audit Bridge",
                "location": "Review corridor",
                "criticality": "high",
                "image_paths": [],
                "video_paths": [],
            },
        )
        mark_inspection_completed(
            session,
            run_id=run_id,
            report_json=_completed_report(),
            rendered_report="completed report",
        )

        update_inspection_review(
            session,
            run_id=run_id,
            review_status="approved",
            reviewer_notes="Looks correct.",
            reviewed_by="engineer-a",
        )
        update_inspection_review(
            session,
            run_id=run_id,
            review_status="needs_revision",
            reviewer_notes="Add closure detail.",
            reviewed_by="engineer-b",
        )

        events = list_inspection_review_events(session, run_id=run_id)

        assert [event.previous_status for event in events] == [
            "not_reviewed",
            "approved",
        ]
        assert [event.new_status for event in events] == [
            "approved",
            "needs_revision",
        ]
        assert events[0].reviewed_by == "engineer-a"
        assert events[1].reviewer_notes == "Add closure detail."
    finally:
        session.close()


def test_run_events_capture_retry_metadata() -> None:
    session = SessionLocal()
    run_id = f"run_event_{uuid4().hex}"
    try:
        create_inspection_run(
            session,
            run_id=run_id,
            status="failed",
            request_data={
                "asset_id": "RUN-EVENT-1",
                "asset_type": "bridge",
                "asset_name": "Run Event Bridge",
                "location": "Run event corridor",
                "criticality": "high",
                "image_paths": [],
                "video_paths": [],
            },
        )

        append_inspection_run_event(
            session,
            run_id=run_id,
            stage="job_attempt",
            status="running",
            message="Inspection job attempt 2 of 4.",
            percent=1,
            metadata={
                "job_id": "inspection-run-event",
                "attempt": 2,
                "max_attempts": 4,
                "retries_left": 2,
                "worker_name": "worker-a",
            },
        )

        events = list_inspection_run_events(session, run_id=run_id)

        assert len(events) == 1
        assert events[0].event_type == "job_attempt"
        assert events[0].attempt == 2
        assert events[0].max_attempts == 4
        assert events[0].retries_left == 2
        assert events[0].job_id == "inspection-run-event"
        assert events[0].worker_name == "worker-a"
        assert events[0].metadata_json["attempt"] == 2
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
