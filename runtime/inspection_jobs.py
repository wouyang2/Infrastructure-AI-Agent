from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from runtime.crash_settings import CrashSimulationSettings, load_crash_simulation_settings
from runtime.env_loader import load_dotenv_if_available
from runtime.progress_store import build_progress_store
from storage.database import SessionLocal
from storage.repositories import (
    append_inspection_run_event,
    mark_inspection_failed,
    mark_inspection_running,
)
from workflows.inspection_graph import run_inspection_graph

_HARD_EXIT = os._exit


def execute_inspection_run(
    run_id: str,
    request_data: dict[str, Any],
    progress_store_override: Any | None = None,
) -> None:
    """Run one inspection job.

    This function is intentionally importable by an RQ worker. Keep it outside
    api.py so the queue worker does not need to import the FastAPI app object.
    """
    load_dotenv_if_available()
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
                _append_run_event(
                    run_id,
                    stage="completed",
                    status="completed",
                    message="Inspection was already completed.",
                    percent=100,
                )
                return
            if run_record.status == "canceled":
                progress_store.cancel_run(
                    run_id,
                    message="Inspection was canceled before execution.",
                )
                _append_run_event(
                    run_id,
                    stage="canceled",
                    status="canceled",
                    message="Inspection was canceled before execution.",
                    percent=100,
                )
                return
            retry_metadata = _current_rq_retry_metadata()
            if retry_metadata is not None:
                progress_store.record_event(
                    run_id,
                    stage="job_attempt",
                    status="running",
                    message=(
                        "Inspection job attempt "
                        f"{retry_metadata['attempt']} of {retry_metadata['max_attempts']}."
                    ),
                    percent=1,
                    metadata=retry_metadata,
                )
                _append_run_event(
                    run_id,
                    stage="job_attempt",
                    status="running",
                    message=(
                        "Inspection job attempt "
                        f"{retry_metadata['attempt']} of {retry_metadata['max_attempts']}."
                    ),
                    percent=1,
                    metadata=retry_metadata,
                )
            run_inspection_graph(
                {
                    "client_run_id": run_id,
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
                checkpoint_backend=request_data.get("checkpoint_backend"),
                checkpoint_sqlite_path=request_data.get("checkpoint_sqlite_path"),
                checkpoint_thread_id=run_id,
                progress_callback=_progress_callback_for_run(run_id, progress_store),
            )
            session.expire_all()
            if getattr(run_record, "status", None) == "canceled":
                progress_store.cancel_run(
                    run_id,
                    message="Inspection was canceled before final persistence.",
                )
                _append_run_event(
                    run_id,
                    stage="canceled",
                    status="canceled",
                    message="Inspection was canceled before final persistence.",
                    percent=100,
                )
                return
        except Exception as exc:
            mark_inspection_failed(session, run_id=run_id, error=str(exc))
            progress_store.fail_run(run_id, message=str(exc))
            _append_run_event(
                run_id,
                stage="failed",
                status="failed",
                message=str(exc),
                percent=100,
            )
            raise

        progress_store.complete_run(run_id)
        _append_run_event(
            run_id,
            stage="completed",
            status="completed",
            message="Inspection completed.",
            percent=100,
        )
    finally:
        session.close()


def _current_rq_retry_metadata() -> dict[str, Any] | None:
    try:
        from rq import get_current_job
    except ImportError:
        return None

    job = get_current_job()
    if job is None:
        return None

    retry = getattr(job, "retry", None)
    configured_max_retries = int(os.getenv("RQ_INSPECTION_RETRY_MAX_ATTEMPTS", "0"))
    max_retries = max(
        configured_max_retries,
        int(getattr(retry, "max", 0) or 0),
    )
    max_attempts = max_retries + 1
    retries_left = int(getattr(job, "retries_left", max_retries) or 0)
    attempt = max(1, max_attempts - retries_left)
    metadata = {
        "job_id": getattr(job, "id", None),
        "attempt": attempt,
        "max_attempts": max_attempts,
        "retries_left": retries_left,
    }
    worker_name = getattr(job, "worker_name", None)
    if worker_name is not None:
        metadata["worker_name"] = worker_name
    return metadata


def _progress_callback_for_run(run_id: str, progress_store: Any):
    def callback(**event: Any) -> None:
        progress_store.record_event(run_id, **event)
        _append_run_event(run_id, **event)
        _maybe_simulate_configured_crash(run_id, event)

    return callback


def _append_run_event(run_id: str, **event: Any) -> None:
    session = SessionLocal()
    try:
        append_inspection_run_event(
            session,
            run_id=run_id,
            stage=event["stage"],
            status=event["status"],
            message=event["message"],
            percent=event["percent"],
            metadata=event.get("metadata", {}),
        )
    except Exception:
        return
    finally:
        session.close()


def _maybe_simulate_configured_crash(run_id: str, event: dict[str, Any]) -> None:
    settings = load_crash_simulation_settings()
    if settings.mode == "disabled":
        return
    if settings.mode == "hard":
        _maybe_simulate_hard_crash(run_id, event, settings)
        return
    if settings.mode == "retryable":
        _maybe_simulate_retryable_crash(run_id, event, settings)
        return


def _maybe_simulate_hard_crash(
    run_id: str,
    event: dict[str, Any],
    settings: CrashSimulationSettings,
) -> None:
    if not settings.stage or event.get("stage") != settings.stage:
        return
    if event.get("status") != settings.status:
        return

    marker_dir = Path(settings.marker_dir)
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / (
        f"{_safe_marker_name(run_id)}_{_safe_marker_name(settings.stage)}_hard.marker"
    )
    if marker_path.exists():
        return

    marker_path.write_text("hard-crashed-once\n", encoding="utf-8")
    _HARD_EXIT(settings.hard_exit_code)


def _maybe_simulate_retryable_crash(
    run_id: str,
    event: dict[str, Any],
    settings: CrashSimulationSettings,
) -> None:
    if not settings.stage or event.get("stage") != settings.stage:
        return
    if event.get("status") != settings.status:
        return

    marker_dir = Path(settings.marker_dir)
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / (
        f"{_safe_marker_name(run_id)}_{_safe_marker_name(settings.stage)}.marker"
    )
    if marker_path.exists():
        return

    marker_path.write_text("crashed-once\n", encoding="utf-8")
    raise RuntimeError(
        "Simulated retryable inspection crash after "
        f"stage '{settings.stage}' for run '{run_id}'."
    )


def _safe_marker_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)
