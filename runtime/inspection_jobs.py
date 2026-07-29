from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi.encoders import jsonable_encoder

from runtime.progress_store import build_progress_store
from runtime.tool_idempotency import run_json_tool_once
from storage.database import SessionLocal
from storage.repositories import (
    mark_inspection_completed,
    mark_inspection_failed,
    mark_inspection_running,
)
from workflows.inspection_graph import run_inspection_graph


def execute_inspection_run(
    run_id: str,
    request_data: dict[str, Any],
    progress_store_override: Any | None = None,
) -> None:
    """Run one inspection job.

    This function is intentionally importable by an RQ worker. Keep it outside
    api.py so the queue worker does not need to import the FastAPI app object.
    """
    session = SessionLocal()
    progress_store = progress_store_override or build_progress_store()
    try:
        try:
            run_record = mark_inspection_running(session, run_id=run_id)
            if run_record.status == "completed" and run_record.report_json is not None:
                progress_store.complete_run(
                    run_id,
                    message="Inspection was already completed.",
                )
                return
            report = run_inspection_graph(
                {
                    "asset_id": request_data["asset_id"],
                    "asset_type": request_data["asset_type"],
                    "asset_name": request_data["asset_name"],
                    "location": request_data["location"],
                    "criticality": request_data["criticality"],
                    "asset_metadata": {
                        key: value
                        for key, value in {
                            "latitude": request_data.get("latitude"),
                            "longitude": request_data.get("longitude"),
                        }.items()
                        if value is not None
                    },
                    "notes": request_data["notes"],
                    "image_paths": request_data.get("image_paths", []),
                    "video_paths": request_data.get("video_paths", []),
                    "reason": request_data["reason"],
                },
                image_analyzer_mode=request_data["image_analyzer"],
                image_annotations_path=request_data["image_annotations_path"],
                image_prompt_profile=request_data.get("image_prompt_profile"),
                image_detail=request_data.get("image_detail"),
                image_tiling=request_data["image_tiling"],
                roboflow_confidence_threshold=request_data["roboflow_confidence_threshold"],
                roboflow_backend=request_data.get("roboflow_backend"),
                roboflow_class_mapping_profile=request_data.get("roboflow_class_mapping_profile"),
                roboflow_tiling=request_data["roboflow_tiling"],
                roboflow_class_thresholds=request_data.get("roboflow_class_thresholds"),
                roboflow_inference_confidence=request_data.get("roboflow_inference_confidence"),
                roboflow_inference_iou_threshold=request_data.get("roboflow_inference_iou_threshold"),
                video_sampler_mode=request_data["video_sampler"],
                video_frame_interval_seconds=request_data["video_frame_interval"],
                video_max_frames=request_data["video_max_frames"],
                severity_mode=request_data["severity_mode"],
                planning_mode=request_data["planning_mode"],
                scheduling_mode=request_data["scheduling_mode"],
                schedule_context_mode=request_data["schedule_context_mode"],
                event_provider=request_data["event_provider"],
                report_mode=request_data["report_mode"],
                llm_max_retries=request_data["llm_max_retries"],
                llm_failure_mode=request_data["llm_failure_mode"],
                rag_backend=request_data["rag_backend"],
                embedding_backend=request_data["embedding_backend"],
                embedding_model=request_data.get("embedding_model"),
                chroma_persist_dir=request_data["chroma_persist_dir"],
                rebuild_rag_index=request_data["rebuild_rag_index"],
                knowledge_corpus=request_data["knowledge_corpus"],
                checkpoint_thread_id=run_id,
                progress_callback=lambda **event: progress_store.record_event(run_id, **event),
            )
        except Exception as exc:
            mark_inspection_failed(session, run_id=run_id, error=str(exc))
            progress_store.fail_run(run_id, message=str(exc))
            raise

        rendered_report = report.rendered_report or ""
        report_payload = jsonable_encoder(asdict(report))
        run_json_tool_once(
            session,
            run_id=run_id,
            tool_name="persist_inspection_report",
            idempotency_key=f"{run_id}:persist_inspection_report:v1",
            input_json={
                "run_id": run_id,
                "case_id": report_payload["case"]["case_id"],
                "workflow_trace_id": report_payload.get("workflow_trace_id"),
            },
            tool_fn=lambda: _persist_inspection_report(
                session=session,
                run_id=run_id,
                report_payload=report_payload,
                rendered_report=rendered_report,
            ),
        )
        progress_store.complete_run(run_id)
    finally:
        session.close()


def _persist_inspection_report(
    *,
    session: Any,
    run_id: str,
    report_payload: dict[str, Any],
    rendered_report: str,
) -> dict[str, Any]:
    record = mark_inspection_completed(
        session,
        run_id=run_id,
        report_json=report_payload,
        rendered_report=rendered_report,
    )
    return {
        "run_id": record.run_id,
        "status": record.status,
        "case_id": record.case_id,
    }
