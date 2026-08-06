from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from storage.models import (
    InspectionMediaRecord,
    InspectionReviewEventRecord,
    InspectionRunEventRecord,
    InspectionRunRecord,
    ToolRunRecord,
)


VALID_REVIEW_STATUSES = {
    "not_reviewed",
    "approved",
    "rejected",
    "needs_revision",
}

TERMINAL_INSPECTION_STATUSES = {"completed", "failed", "canceled"}


def create_inspection_run(
    session: Session,
    *,
    request_data: dict[str, Any],
    run_id: str | None = None,
    status: str = "running",
) -> InspectionRunRecord:
    record = InspectionRunRecord(
        run_id=run_id or uuid4().hex,
        case_id=None,
        status=status,
        asset_id=request_data["asset_id"],
        asset_type=request_data["asset_type"],
        asset_name=request_data["asset_name"],
        location=request_data["location"],
        criticality=request_data["criticality"],
        image_count=len(request_data.get("image_paths", [])),
        video_count=len(request_data.get("video_paths", [])),
        severity=None,
        repair_required=None,
        recommended_action=None,
        schedule_start=None,
        schedule_end=None,
        workflow_trace_id=None,
        workflow_trace_path=None,
        request_json=request_data,
        report_json=None,
        rendered_report=None,
        error=None,
        review_status="not_reviewed",
        reviewer_notes=None,
        reviewed_by=None,
        reviewed_at=None,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def create_inspection_media(
    session: Session,
    *,
    media_type: str,
    original_filename: str,
    content_type: str | None,
    size_bytes: int,
    checksum_sha256: str,
    storage_backend: str,
    storage_key: str,
    file_path: str,
    preview_url: str,
    scan_status: str = "not_scanned",
    run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> InspectionMediaRecord:
    record = InspectionMediaRecord(
        media_id=f"media_{uuid4().hex}",
        run_id=run_id,
        media_type=media_type,
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256,
        storage_backend=storage_backend,
        storage_key=storage_key,
        file_path=file_path,
        preview_url=preview_url,
        scan_status=scan_status,
        metadata_json=metadata or {},
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def attach_media_to_inspection_run(
    session: Session,
    *,
    run_id: str,
    file_paths: list[str],
) -> list[InspectionMediaRecord]:
    if not file_paths:
        return []
    statement = select(InspectionMediaRecord).where(
        InspectionMediaRecord.file_path.in_(file_paths)
    )
    records = list(session.scalars(statement))
    for record in records:
        if record.run_id is None:
            record.run_id = run_id
    session.commit()
    for record in records:
        session.refresh(record)
    return records


def list_media_for_inspection_run(
    session: Session,
    *,
    run_id: str,
) -> list[InspectionMediaRecord]:
    statement = (
        select(InspectionMediaRecord)
        .where(InspectionMediaRecord.run_id == run_id)
        .order_by(InspectionMediaRecord.created_at)
    )
    return list(session.scalars(statement))


def mark_inspection_running(
    session: Session,
    *,
    run_id: str,
) -> InspectionRunRecord:
    record = get_inspection_run(session, run_id)
    if record is None:
        raise ValueError(f"Inspection run not found: {run_id}")
    if record.status == "completed" and record.report_json is not None:
        return record
    if record.status == "canceled":
        return record

    record.status = "running"
    record.error = None
    session.commit()
    session.refresh(record)
    return record


def mark_inspection_completed(
    session: Session,
    *,
    run_id: str,
    report_json: dict[str, Any],
    rendered_report: str,
) -> InspectionRunRecord:
    record = get_inspection_run(session, run_id)
    if record is None:
        raise ValueError(f"Inspection run not found: {run_id}")
    if record.status == "completed" and record.report_json is not None:
        return record
    if record.status == "canceled":
        return record

    schedule = report_json.get("schedule") or {}
    recommended_window = schedule.get("recommended_window") or {}
    record.status = "completed"
    record.case_id = report_json["case"]["case_id"]
    record.severity = report_json["severity"]["severity"]
    record.repair_required = report_json["severity"]["repair_required"]
    record.recommended_action = report_json["maintenance_plan"]["recommended_action"]
    record.schedule_start = recommended_window.get("start")
    record.schedule_end = recommended_window.get("end")
    record.workflow_trace_id = report_json.get("workflow_trace_id")
    record.workflow_trace_path = report_json.get("workflow_trace_path")
    record.report_json = report_json
    record.rendered_report = rendered_report
    record.error = None
    record.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(record)
    return record


def mark_inspection_failed(
    session: Session,
    *,
    run_id: str,
    error: str,
) -> InspectionRunRecord:
    record = get_inspection_run(session, run_id)
    if record is None:
        raise ValueError(f"Inspection run not found: {run_id}")
    if record.status == "completed" and record.report_json is not None:
        return record
    if record.status == "canceled":
        return record

    record.status = "failed"
    record.error = error
    record.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(record)
    return record


def mark_inspection_canceled(
    session: Session,
    *,
    run_id: str,
    reason: str = "Inspection canceled by operator.",
) -> InspectionRunRecord:
    record = get_inspection_run(session, run_id)
    if record is None:
        raise ValueError(f"Inspection run not found: {run_id}")
    if record.status in TERMINAL_INSPECTION_STATUSES:
        return record

    record.status = "canceled"
    record.error = reason
    record.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(record)
    return record


def get_inspection_run(
    session: Session,
    run_id: str,
) -> InspectionRunRecord | None:
    return session.get(InspectionRunRecord, run_id)


def update_inspection_review(
    session: Session,
    *,
    run_id: str,
    review_status: str,
    reviewer_notes: str | None = None,
    reviewed_by: str | None = None,
) -> InspectionRunRecord:
    if review_status not in VALID_REVIEW_STATUSES:
        allowed = ", ".join(sorted(VALID_REVIEW_STATUSES))
        raise ValueError(f"Unsupported review status: {review_status}. Use one of: {allowed}.")

    record = get_inspection_run(session, run_id)
    if record is None:
        raise ValueError(f"Inspection run not found: {run_id}")
    if record.status != "completed":
        raise ValueError("Only completed inspection runs can be reviewed.")

    previous_status = record.review_status
    record.review_status = review_status
    record.reviewer_notes = reviewer_notes
    record.reviewed_by = reviewed_by
    record.reviewed_at = datetime.now(UTC)
    session.add(
        InspectionReviewEventRecord(
            event_id=uuid4().hex,
            run_id=run_id,
            previous_status=previous_status,
            new_status=review_status,
            reviewer_notes=reviewer_notes,
            reviewed_by=reviewed_by,
        )
    )
    session.commit()
    session.refresh(record)
    return record


def list_inspection_review_events(
    session: Session,
    *,
    run_id: str,
) -> list[InspectionReviewEventRecord]:
    statement = (
        select(InspectionReviewEventRecord)
        .where(InspectionReviewEventRecord.run_id == run_id)
        .order_by(InspectionReviewEventRecord.created_at)
    )
    return list(session.scalars(statement))


def append_inspection_run_event(
    session: Session,
    *,
    run_id: str,
    stage: str,
    status: str,
    message: str,
    percent: int,
    metadata: dict[str, Any] | None = None,
) -> InspectionRunEventRecord | None:
    if get_inspection_run(session, run_id) is None:
        return None

    metadata = metadata or {}
    record = InspectionRunEventRecord(
        event_id=uuid4().hex,
        run_id=run_id,
        stage=stage,
        status=status,
        message=message,
        percent=max(0, min(100, int(percent))),
        event_type=_inspection_event_type(stage, status),
        attempt=_optional_int(metadata.get("attempt")),
        max_attempts=_optional_int(metadata.get("max_attempts")),
        retries_left=_optional_int(metadata.get("retries_left")),
        job_id=_optional_str(metadata.get("job_id")),
        worker_name=_optional_str(metadata.get("worker_name")),
        metadata_json=metadata,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def list_inspection_run_events(
    session: Session,
    *,
    run_id: str,
) -> list[InspectionRunEventRecord]:
    statement = (
        select(InspectionRunEventRecord)
        .where(InspectionRunEventRecord.run_id == run_id)
        .order_by(InspectionRunEventRecord.created_at)
    )
    return list(session.scalars(statement))


def list_inspection_runs(
    session: Session,
    *,
    limit: int = 25,
) -> list[InspectionRunRecord]:
    statement = (
        select(InspectionRunRecord)
        .order_by(desc(InspectionRunRecord.created_at))
        .limit(limit)
    )
    return list(session.scalars(statement))


def list_active_inspection_runs(session: Session) -> list[InspectionRunRecord]:
    statement = (
        select(InspectionRunRecord)
        .where(InspectionRunRecord.status.not_in(TERMINAL_INSPECTION_STATUSES))
        .order_by(desc(InspectionRunRecord.created_at))
    )
    return list(session.scalars(statement))


def _inspection_event_type(stage: str, status: str) -> str:
    if stage == "job_attempt":
        return "job_attempt"
    if stage == "checkpoint_resume":
        return "checkpoint_resume"
    if status == "failed" or stage == "failed":
        return "failure"
    if status == "completed" or stage == "completed":
        return "completion"
    if stage.endswith("_tool"):
        return "tool"
    return "workflow"


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def get_tool_run(
    session: Session,
    idempotency_key: str,
) -> ToolRunRecord | None:
    return session.get(ToolRunRecord, idempotency_key)


def start_tool_run(
    session: Session,
    *,
    idempotency_key: str,
    run_id: str,
    tool_name: str,
    input_hash: str,
    input_json: dict[str, Any],
) -> ToolRunRecord:
    existing = get_tool_run(session, idempotency_key)
    if existing is not None:
        return existing

    record = ToolRunRecord(
        idempotency_key=idempotency_key,
        run_id=run_id,
        tool_name=tool_name,
        status="running",
        input_hash=input_hash,
        input_json=input_json,
        output_json=None,
        error=None,
        completed_at=None,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def complete_tool_run(
    session: Session,
    *,
    idempotency_key: str,
    output_json: dict[str, Any],
) -> ToolRunRecord:
    record = get_tool_run(session, idempotency_key)
    if record is None:
        raise ValueError(f"Tool run not found: {idempotency_key}")
    if record.status == "completed" and record.output_json is not None:
        return record

    record.status = "completed"
    record.output_json = output_json
    record.error = None
    record.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(record)
    return record


def fail_tool_run(
    session: Session,
    *,
    idempotency_key: str,
    error: str,
) -> ToolRunRecord:
    record = get_tool_run(session, idempotency_key)
    if record is None:
        raise ValueError(f"Tool run not found: {idempotency_key}")
    if record.status == "completed" and record.output_json is not None:
        return record

    record.status = "failed"
    record.error = error
    record.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(record)
    return record
