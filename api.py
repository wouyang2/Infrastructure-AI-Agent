from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import mimetypes
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.helpers.pdf_report import build_inspection_pdf
from runtime.config_validation import configuration_status
from runtime.env_loader import load_dotenv_if_available
from runtime.job_status import fetch_runtime_job_status
from runtime.job_queue import build_inspection_job_queue
from runtime.progress_store import build_progress_store
from runtime.rate_limiter import build_rate_limiter
from storage.database import get_session, init_database
from storage.media_storage import build_media_storage
from storage.models import InspectionRunRecord
from storage.repositories import (
    append_inspection_run_event,
    attach_media_to_inspection_run,
    create_inspection_media,
    create_inspection_run,
    get_inspection_run,
    list_media_for_inspection_run,
    list_active_inspection_runs,
    list_inspection_review_events,
    list_inspection_run_events,
    list_inspection_runs,
    mark_inspection_canceled,
    update_inspection_review,
)

load_dotenv_if_available()

AnalyzerMode = Literal["heuristic", "metadata", "openai", "roboflow"]
VideoSamplerMode = Literal["mock", "opencv"]
RAGBackend = Literal["chroma", "local"]
EmbeddingBackend = Literal["fake", "openai"]
KnowledgeCorpus = Literal["sample", "bridge", "merged"]
LLMMode = Literal["deterministic", "llm"]
LLMFailureMode = Literal["fallback", "fail"]
RoboflowBackend = Literal["auto", "inference", "http"]
RoboflowClassMappingProfile = Literal["default", "bridge_dataset"]
ScheduleContextMode = Literal["mock", "live"]
EventProvider = Literal["mock", "ticketmaster"]


PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"
BRIDGE_IMAGE_DIR = PROJECT_ROOT / "data" / "bridge_image"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
UPLOADS_DIR = ARTIFACTS_DIR / "uploads"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_STORAGE = build_media_storage(uploads_dir=UPLOADS_DIR)
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_UPLOAD_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
DEFAULT_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_VIDEO_UPLOAD_BYTES = 250 * 1024 * 1024
UPLOAD_STREAM_CHUNK_BYTES = 1024 * 1024


class InspectionRequest(BaseModel):
    client_run_id: str | None = None
    asset_id: str = "A-100"
    asset_type: str = "bridge"
    asset_name: str = "Demo Overpass"
    location: str = "North service corridor"
    latitude: float | None = None
    longitude: float | None = None
    criticality: Literal["low", "medium", "high", "critical"] = "high"
    notes: str = (
        "Inspection found spalling near an expansion joint with loose concrete "
        "and exposed substrate. No immediate closure is in place."
    )
    image_paths: list[str] = Field(default_factory=list)
    video_paths: list[str] = Field(default_factory=list)
    require_media: bool = False
    reason: str = "routine"

    image_analyzer: AnalyzerMode = "heuristic"
    image_annotations_path: str = "data/bridge_image/annotations.csv"
    image_prompt_profile: str | None = None
    image_detail: Literal["auto", "low", "high"] | None = None
    image_tiling: Literal["none", "grid-2x2"] = "none"
    roboflow_confidence_threshold: float = 0.25
    roboflow_backend: RoboflowBackend | None = None
    roboflow_class_mapping_profile: RoboflowClassMappingProfile | None = None
    roboflow_tiling: Literal["none", "grid-2x2"] = "none"
    roboflow_class_thresholds: str | None = None
    roboflow_inference_confidence: float | None = None
    roboflow_inference_iou_threshold: float | None = None
    video_sampler: VideoSamplerMode = "mock"
    video_frame_interval: float = 4.6
    video_max_frames: int = 3

    rag_backend: RAGBackend = "chroma"
    embedding_backend: EmbeddingBackend = "openai"
    embedding_model: str | None = None
    chroma_persist_dir: str = "artifacts/chroma"
    rebuild_rag_index: bool = False
    knowledge_corpus: KnowledgeCorpus = "merged"

    severity_mode: LLMMode = "deterministic"
    planning_mode: LLMMode = "deterministic"
    scheduling_mode: LLMMode = "llm"
    schedule_context_mode: ScheduleContextMode = "mock"
    event_provider: EventProvider = "mock"
    report_mode: LLMMode = "deterministic"
    llm_max_retries: int = 4
    llm_failure_mode: LLMFailureMode = "fallback"
    checkpoint_backend: Literal["memory", "sqlite", "none"] | None = None
    checkpoint_sqlite_path: str | None = None


class InspectionResponse(BaseModel):
    run_id: str | None = None
    status: str = "completed"
    job_backend: str | None = None
    job_id: str | None = None
    progress_url: str | None = None
    case_url: str | None = None
    report: dict | None = None
    rendered_report: str | None = None


class InspectionRunSummary(BaseModel):
    run_id: str
    case_id: str | None
    status: str
    asset_id: str
    asset_type: str
    asset_name: str
    location: str
    criticality: str
    severity: str | None
    repair_required: bool | None
    recommended_action: str | None
    schedule_start: str | None
    schedule_end: str | None
    workflow_trace_id: str | None
    review_status: str
    reviewer_notes: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    created_at: str
    completed_at: str | None


class InspectionRunDetail(InspectionRunSummary):
    image_count: int
    video_count: int
    request: dict[str, Any]
    media: list[dict[str, Any]]
    report: dict[str, Any] | None
    rendered_report: str | None
    workflow_trace_path: str | None
    error: str | None


class InspectionProgressResponse(BaseModel):
    run_id: str
    status: str
    current_stage: str
    message: str
    percent: int
    started_at: str
    updated_at: str
    events: list[dict[str, Any]]
    job_backend: str | None = None
    job_id: str | None = None
    job_status: str | None = None
    job_status_message: str | None = None
    job_enqueued_at: str | None = None
    job_started_at: str | None = None
    job_ended_at: str | None = None
    job_last_heartbeat: str | None = None
    job_worker_name: str | None = None
    job_retries_left: int | None = None


class InspectionReviewRequest(BaseModel):
    review_status: Literal["not_reviewed", "approved", "rejected", "needs_revision"]
    reviewer_notes: str | None = ""
    reviewed_by: str | None = "demo_reviewer"


class InspectionCancelResponse(BaseModel):
    canceled_runs: list[str]
    count: int


class InspectionReviewEventResponse(BaseModel):
    event_id: str
    run_id: str
    previous_status: str | None
    new_status: str
    reviewer_notes: str | None
    reviewed_by: str | None
    created_at: str


class InspectionRunEventResponse(BaseModel):
    event_id: str
    run_id: str
    stage: str
    status: str
    message: str
    percent: int
    event_type: str
    attempt: int | None
    max_attempts: int | None
    retries_left: int | None
    job_id: str | None
    worker_name: str | None
    metadata: dict[str, Any]
    created_at: str


class PDFReportRequest(BaseModel):
    report: dict[str, Any]
    rendered_report: str = ""


class SampleImage(BaseModel):
    file_path: str
    preview_url: str
    defect_type: str
    severity_label: str
    annotation_id: str


class ImageUploadRequest(BaseModel):
    filename: str
    content_base64: str


class ImageUploadResponse(BaseModel):
    file_path: str
    preview_url: str
    media_id: str | None = None
    media_type: str = "image"
    content_type: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    storage_backend: str = "local"
    scan_status: str = "not_scanned"


class VideoUploadRequest(BaseModel):
    filename: str
    content_base64: str


class VideoUploadResponse(BaseModel):
    file_path: str
    preview_url: str
    media_id: str | None = None
    media_type: str = "video"
    content_type: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    storage_backend: str = "local"
    scan_status: str = "not_scanned"


app = FastAPI(
    title="Infrastructure AI Agent",
    version="0.1.0",
    description="API wrapper for the infrastructure inspection multi-agent workflow.",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount(
    "/media/bridge_image",
    StaticFiles(directory=BRIDGE_IMAGE_DIR),
    name="bridge_image_media",
)
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")
init_database()
progress_store = build_progress_store()
rate_limiter = build_rate_limiter()


def require_api_key(request: Request) -> None:
    if os.getenv("REQUIRE_API_KEY", "false").lower() not in {"1", "true", "yes"}:
        return

    expected_key = os.getenv("INFRA_AGENT_API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail="API key authentication is required but INFRA_AGENT_API_KEY is not configured.",
        )

    provided_key = request.headers.get("x-api-key")
    authorization = request.headers.get("authorization", "")
    if not provided_key and authorization.lower().startswith("bearer "):
        provided_key = authorization.split(" ", 1)[1].strip()

    if not provided_key or not hmac.compare_digest(provided_key, expected_key):
        raise HTTPException(status_code=401, detail="Valid API key required.")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _progress_with_runtime_job_status(progress: dict[str, Any]) -> dict[str, Any]:
    job_metadata = _latest_job_metadata(progress)
    if not job_metadata:
        return progress

    augmented = dict(progress)
    job_backend = job_metadata.get("job_backend")
    job_id = job_metadata.get("job_id")
    runtime_status = fetch_runtime_job_status(
        job_backend=job_backend,
        job_id=job_id,
    )
    augmented.update(
        {
            "job_backend": job_backend,
            "job_id": job_id,
        }
    )
    if runtime_status:
        augmented.update(runtime_status)
        _apply_runtime_status_message(augmented, runtime_status)
    return augmented


def _latest_job_metadata(progress: dict[str, Any]) -> dict[str, Any] | None:
    for event in reversed(progress.get("events", [])):
        metadata = event.get("metadata") or {}
        if metadata.get("job_id") or metadata.get("job_backend"):
            return metadata
    return None


def _apply_runtime_status_message(
    progress: dict[str, Any],
    runtime_status: dict[str, Any],
) -> None:
    if progress.get("status") in {"completed", "failed", "canceled"}:
        return
    job_status = runtime_status.get("job_status")
    job_status_message = runtime_status.get("job_status_message")
    if job_status in {"queued", "scheduled", "deferred", "failed", "stopped", "canceled"}:
        progress["message"] = job_status_message or progress.get("message")


@app.get("/config/status")
def config_status(
    _: None = Depends(require_api_key),
) -> dict[str, object]:
    return configuration_status()


@app.get("/cases", response_model=list[InspectionRunSummary])
def cases(
    limit: int = 25,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> list[InspectionRunSummary]:
    return [
        _inspection_run_summary(record)
        for record in list_inspection_runs(session, limit=min(max(limit, 1), 100))
    ]


@app.get("/cases/{run_id}", response_model=InspectionRunDetail)
def case_detail(
    run_id: str,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> InspectionRunDetail:
    record = get_inspection_run(session, run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Inspection run not found.")
    return _inspection_run_detail(record, session=session)


@app.get("/cases/{run_id}/progress", response_model=InspectionProgressResponse)
def case_progress(
    run_id: str,
    _: None = Depends(require_api_key),
) -> InspectionProgressResponse:
    progress = progress_store.get_progress(run_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Inspection progress not found.")
    progress = _progress_with_runtime_job_status(progress)
    return InspectionProgressResponse(**progress)


@app.patch("/cases/{run_id}/review", response_model=InspectionRunDetail)
def review_case(
    run_id: str,
    request: InspectionReviewRequest,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> InspectionRunDetail:
    try:
        record = update_inspection_review(
            session,
            run_id=run_id,
            review_status=request.review_status,
            reviewer_notes=request.reviewer_notes,
            reviewed_by=request.reviewed_by,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return _inspection_run_detail(record, session=session)


@app.get(
    "/cases/{run_id}/review-events",
    response_model=list[InspectionReviewEventResponse],
)
def case_review_events(
    run_id: str,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> list[InspectionReviewEventResponse]:
    if get_inspection_run(session, run_id) is None:
        raise HTTPException(status_code=404, detail="Inspection run not found.")
    return [
        InspectionReviewEventResponse(
            event_id=event.event_id,
            run_id=event.run_id,
            previous_status=event.previous_status,
            new_status=event.new_status,
            reviewer_notes=event.reviewer_notes,
            reviewed_by=event.reviewed_by,
            created_at=event.created_at.isoformat(),
        )
        for event in list_inspection_review_events(session, run_id=run_id)
    ]


@app.get(
    "/cases/{run_id}/events",
    response_model=list[InspectionRunEventResponse],
)
def case_run_events(
    run_id: str,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> list[InspectionRunEventResponse]:
    if get_inspection_run(session, run_id) is None:
        raise HTTPException(status_code=404, detail="Inspection run not found.")
    return [
        InspectionRunEventResponse(
            event_id=event.event_id,
            run_id=event.run_id,
            stage=event.stage,
            status=event.status,
            message=event.message,
            percent=event.percent,
            event_type=event.event_type,
            attempt=event.attempt,
            max_attempts=event.max_attempts,
            retries_left=event.retries_left,
            job_id=event.job_id,
            worker_name=event.worker_name,
            metadata=event.metadata_json,
            created_at=event.created_at.isoformat(),
        )
        for event in list_inspection_run_events(session, run_id=run_id)
    ]


@app.patch("/cases/{run_id}/cancel", response_model=InspectionRunDetail)
def cancel_case(
    run_id: str,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> InspectionRunDetail:
    try:
        record = mark_inspection_canceled(session, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    message = "Inspection canceled by operator."
    progress_store.cancel_run(run_id, message=message)
    append_inspection_run_event(
        session,
        run_id=run_id,
        stage="canceled",
        status="canceled",
        message=message,
        percent=100,
    )
    return _inspection_run_detail(record, session=session)


@app.post("/cases/queue/clear", response_model=InspectionCancelResponse)
def clear_active_queue(
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> InspectionCancelResponse:
    canceled_run_ids: list[str] = []
    for active_record in list_active_inspection_runs(session):
        record = mark_inspection_canceled(
            session,
            run_id=active_record.run_id,
            reason="Inspection canceled by queue clear.",
        )
        message = "Inspection canceled by queue clear."
        progress_store.cancel_run(record.run_id, message=message)
        append_inspection_run_event(
            session,
            run_id=record.run_id,
            stage="canceled",
            status="canceled",
            message=message,
            percent=100,
        )
        canceled_run_ids.append(record.run_id)
    return InspectionCancelResponse(
        canceled_runs=canceled_run_ids,
        count=len(canceled_run_ids),
    )


@app.get("/sample-images", response_model=list[SampleImage])
def sample_images(
    limit: int = 12,
    _: None = Depends(require_api_key),
) -> list[SampleImage]:
    representatives: list[SampleImage] = []
    overflow: list[SampleImage] = []
    seen_defects = set()
    seen_paths = set()
    seen_preview_names = set()
    annotations_path = BRIDGE_IMAGE_DIR / "annotations.csv"
    with annotations_path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            file_path = Path(row["file_path"])
            if row["file_path"] in seen_paths or file_path.name in seen_preview_names:
                continue

            sample = SampleImage(
                file_path=row["file_path"],
                preview_url=f"/media/bridge_image/{file_path.name}",
                defect_type=row["defect_type"],
                severity_label=row["severity_label"],
                annotation_id=row["annotation_id"],
            )
            seen_paths.add(row["file_path"])
            seen_preview_names.add(file_path.name)
            if row["defect_type"] not in seen_defects:
                representatives.append(sample)
                seen_defects.add(row["defect_type"])
            else:
                overflow.append(sample)

            if len(representatives) + len(overflow) >= max(limit, 5):
                break

    return [*representatives, *overflow][:limit]


@app.post("/uploads/images", response_model=ImageUploadResponse)
def upload_image(
    request: ImageUploadRequest,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> ImageUploadResponse:
    original_name = Path(request.filename).name
    extension = Path(original_name).suffix.lower()
    _validate_extension(
        extension,
        allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS,
        detail="Only JPG, PNG, and WEBP image uploads are supported.",
    )

    max_bytes = int(os.getenv("MAX_IMAGE_UPLOAD_BYTES", str(DEFAULT_MAX_IMAGE_UPLOAD_BYTES)))
    _validate_upload_size(
        request.content_base64,
        max_bytes=max_bytes,
        label="image",
    )
    try:
        image_bytes = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image content.") from exc

    return _store_image_upload(
        session=session,
        original_name=original_name,
        image_bytes=image_bytes,
        max_bytes=max_bytes,
    )


@app.post("/uploads/images/multipart", response_model=ImageUploadResponse)
async def upload_image_multipart(
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> ImageUploadResponse:
    original_name = Path(file.filename or "inspection-image").name
    extension = Path(original_name).suffix.lower()
    _validate_extension(
        extension,
        allowed_extensions=ALLOWED_UPLOAD_EXTENSIONS,
        detail="Only JPG, PNG, and WEBP image uploads are supported.",
    )
    max_bytes = int(os.getenv("MAX_IMAGE_UPLOAD_BYTES", str(DEFAULT_MAX_IMAGE_UPLOAD_BYTES)))
    output_path, output_name = await _write_upload_file(
        file,
        original_name=original_name,
        max_bytes=max_bytes,
        label="image",
    )
    try:
        _verify_image_file(output_path)
    except HTTPException:
        output_path.unlink(missing_ok=True)
        raise
    return _record_stored_upload(
        session=session,
        original_name=original_name,
        media_type="image",
        output_path=output_path,
        output_name=output_name,
        content_type=file.content_type,
    )


@app.post("/uploads/videos", response_model=VideoUploadResponse)
def upload_video(
    request: VideoUploadRequest,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> VideoUploadResponse:
    original_name = Path(request.filename).name
    extension = Path(original_name).suffix.lower()
    _validate_extension(
        extension,
        allowed_extensions=ALLOWED_VIDEO_UPLOAD_EXTENSIONS,
        detail="Only MP4, MOV, AVI, and MKV video uploads are supported.",
    )

    max_bytes = int(os.getenv("MAX_VIDEO_UPLOAD_BYTES", str(DEFAULT_MAX_VIDEO_UPLOAD_BYTES)))
    _validate_upload_size(
        request.content_base64,
        max_bytes=max_bytes,
        label="video",
    )
    try:
        video_bytes = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 video content.") from exc

    return _store_video_upload(
        session=session,
        original_name=original_name,
        video_bytes=video_bytes,
        max_bytes=max_bytes,
    )


@app.post("/uploads/videos/multipart", response_model=VideoUploadResponse)
async def upload_video_multipart(
    file: UploadFile = File(...),
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> VideoUploadResponse:
    original_name = Path(file.filename or "inspection-video").name
    extension = Path(original_name).suffix.lower()
    _validate_extension(
        extension,
        allowed_extensions=ALLOWED_VIDEO_UPLOAD_EXTENSIONS,
        detail="Only MP4, MOV, AVI, and MKV video uploads are supported.",
    )
    max_bytes = int(os.getenv("MAX_VIDEO_UPLOAD_BYTES", str(DEFAULT_MAX_VIDEO_UPLOAD_BYTES)))
    output_path, output_name = await _write_upload_file(
        file,
        original_name=original_name,
        max_bytes=max_bytes,
        label="video",
    )
    return _record_stored_upload(
        session=session,
        original_name=original_name,
        media_type="video",
        output_path=output_path,
        output_name=output_name,
        content_type=file.content_type,
    )


@app.post("/inspections", response_model=InspectionResponse, status_code=202)
def create_inspection(
    request: InspectionRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_api_key),
    session: Session = Depends(get_session),
) -> InspectionResponse:
    if request.require_media and not request.image_paths and not request.video_paths:
        raise HTTPException(
            status_code=400,
            detail="Choose an inspection image or video before running the inspection.",
        )

    actor = http_request.client.host if http_request.client else "unknown"
    rate_result = rate_limiter.check(
        f"inspections:{actor}",
        limit=int(os.getenv("INSPECTION_RATE_LIMIT", "100")),
        window_seconds=int(os.getenv("INSPECTION_RATE_WINDOW_SECONDS", "60")),
    )
    if not rate_result.allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                "Inspection rate limit exceeded. "
                f"Try again in about {rate_result.reset_seconds} seconds."
            ),
            headers={
                "Retry-After": str(rate_result.reset_seconds),
                "X-RateLimit-Limit": str(rate_result.limit),
                "X-RateLimit-Remaining": str(rate_result.remaining),
            },
        )

    request_data = request.model_dump()
    run_record = create_inspection_run(
        session,
        request_data=request_data,
        run_id=request.client_run_id,
        status="queued",
    )
    attach_media_to_inspection_run(
        session,
        run_id=run_record.run_id,
        file_paths=[
            *request_data.get("image_paths", []),
            *request_data.get("video_paths", []),
        ],
    )
    progress_store.start_run(run_record.run_id)
    dispatch = build_inspection_job_queue(
        background_tasks,
        progress_store=progress_store,
    ).enqueue_inspection(
        run_id=run_record.run_id,
        request_data=request_data,
    )
    progress_store.record_event(
        run_record.run_id,
        stage="queued",
        status="running",
        message=f"Inspection job queued via {dispatch.backend}.",
        percent=0,
        metadata={"job_id": dispatch.job_id, "job_backend": dispatch.backend},
    )
    append_inspection_run_event(
        session,
        run_id=run_record.run_id,
        stage="queued",
        status="running",
        message=f"Inspection job queued via {dispatch.backend}.",
        percent=0,
        metadata={"job_id": dispatch.job_id, "job_backend": dispatch.backend},
    )
    return InspectionResponse(
        run_id=run_record.run_id,
        status="queued",
        job_backend=dispatch.backend,
        job_id=dispatch.job_id,
        progress_url=f"/cases/{run_record.run_id}/progress",
        case_url=f"/cases/{run_record.run_id}",
    )


@app.post("/reports/pdf")
def export_report_pdf(
    request: PDFReportRequest,
    _: None = Depends(require_api_key),
) -> StreamingResponse:
    try:
        pdf_bytes = build_inspection_pdf(request.report, request.rendered_report)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    case = request.report.get("case", {})
    case_id = str(case.get("case_id") or "inspection-report")
    filename = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in case_id
    ).strip("-")
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename or "inspection-report"}.pdf"'
        },
    )


def _inspection_run_summary(record: InspectionRunRecord) -> InspectionRunSummary:
    return InspectionRunSummary(
        run_id=record.run_id,
        case_id=record.case_id,
        status=record.status,
        asset_id=record.asset_id,
        asset_type=record.asset_type,
        asset_name=record.asset_name,
        location=record.location,
        criticality=record.criticality,
        severity=record.severity,
        repair_required=record.repair_required,
        recommended_action=record.recommended_action,
        schedule_start=record.schedule_start,
        schedule_end=record.schedule_end,
        workflow_trace_id=record.workflow_trace_id,
        review_status=record.review_status,
        reviewer_notes=record.reviewer_notes,
        reviewed_by=record.reviewed_by,
        reviewed_at=record.reviewed_at.isoformat() if record.reviewed_at else None,
        created_at=record.created_at.isoformat(),
        completed_at=record.completed_at.isoformat() if record.completed_at else None,
    )


def _validate_upload_size(
    content_base64: str,
    *,
    max_bytes: int,
    label: str,
) -> None:
    estimated_size = _estimated_decoded_size(content_base64)
    if estimated_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Uploaded {label} is too large. "
                f"Limit is {_format_bytes(max_bytes)}."
            ),
        )


def _validate_decoded_upload_size(
    payload: bytes,
    *,
    max_bytes: int,
    label: str,
) -> None:
    if len(payload) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Uploaded {label} is too large. "
                f"Limit is {_format_bytes(max_bytes)}."
            ),
        )


def _validate_extension(
    extension: str,
    *,
    allowed_extensions: set[str],
    detail: str,
) -> None:
    if extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail=detail)


def _store_image_upload(
    *,
    session: Session,
    original_name: str,
    image_bytes: bytes,
    max_bytes: int,
) -> ImageUploadResponse:
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    _validate_decoded_upload_size(image_bytes, max_bytes=max_bytes, label="image")
    _verify_image_bytes(image_bytes)

    output_path, output_name = MEDIA_STORAGE.build_upload_path(original_name)
    output_path.write_bytes(image_bytes)
    return _record_stored_upload(
        session=session,
        original_name=original_name,
        media_type="image",
        output_path=output_path,
        output_name=output_name,
        content_type=_guess_content_type(original_name),
    )


def _store_video_upload(
    *,
    session: Session,
    original_name: str,
    video_bytes: bytes,
    max_bytes: int,
) -> VideoUploadResponse:
    if not video_bytes:
        raise HTTPException(status_code=400, detail="Uploaded video is empty.")
    _validate_decoded_upload_size(video_bytes, max_bytes=max_bytes, label="video")

    output_path, output_name = MEDIA_STORAGE.build_upload_path(original_name)
    output_path.write_bytes(video_bytes)
    return _record_stored_upload(
        session=session,
        original_name=original_name,
        media_type="video",
        output_path=output_path,
        output_name=output_name,
        content_type=_guess_content_type(original_name),
    )


async def _write_upload_file(
    file: UploadFile,
    *,
    original_name: str,
    max_bytes: int,
    label: str,
) -> tuple[Path, str]:
    output_path, output_name = MEDIA_STORAGE.build_upload_path(original_name)
    bytes_written = 0
    try:
        with output_path.open("wb") as stream:
            while chunk := await file.read(UPLOAD_STREAM_CHUNK_BYTES):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Uploaded {label} is too large. "
                            f"Limit is {_format_bytes(max_bytes)}."
                        ),
                    )
                stream.write(chunk)
    except HTTPException:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if bytes_written == 0:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Uploaded {label} is empty.")
    return output_path, output_name


def _record_stored_upload(
    *,
    session: Session,
    original_name: str,
    media_type: Literal["image", "video"],
    output_path: Path,
    output_name: str,
    content_type: str | None,
) -> ImageUploadResponse | VideoUploadResponse:
    checksum = _sha256_file(output_path)
    stored = MEDIA_STORAGE.store_file(
        source_path=output_path,
        output_name=output_name,
        content_type=content_type or _guess_content_type(original_name),
        media_type=media_type,
    )
    media = create_inspection_media(
        session,
        media_type=media_type,
        original_filename=original_name,
        content_type=content_type or _guess_content_type(original_name),
        size_bytes=output_path.stat().st_size,
        checksum_sha256=checksum,
        storage_backend=stored.storage_backend,
        storage_key=stored.storage_key,
        file_path=stored.file_path,
        preview_url=stored.preview_url,
        scan_status="not_scanned",
        metadata=stored.metadata,
    )
    if stored.delete_local_after_record:
        output_path.unlink(missing_ok=True)
    response_class = ImageUploadResponse if media_type == "image" else VideoUploadResponse
    return response_class(
        file_path=stored.file_path,
        preview_url=stored.preview_url,
        media_id=media.media_id,
        media_type=media.media_type,
        content_type=media.content_type,
        size_bytes=media.size_bytes,
        checksum_sha256=media.checksum_sha256,
        storage_backend=media.storage_backend,
        scan_status=media.scan_status,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(UPLOAD_STREAM_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guess_content_type(filename: str) -> str | None:
    return mimetypes.guess_type(filename)[0]


def _verify_image_bytes(image_bytes: bytes) -> None:
    try:
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.") from exc


def _verify_image_file(image_path: Path) -> None:
    try:
        from PIL import Image

        with Image.open(image_path) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.") from exc


def _estimated_decoded_size(content_base64: str) -> int:
    normalized = "".join(content_base64.split())
    padding = normalized.count("=")
    return max(0, (len(normalized) * 3 // 4) - padding)


def _format_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} bytes"


def _inspection_run_detail(
    record: InspectionRunRecord,
    *,
    session: Session,
) -> InspectionRunDetail:
    summary = _inspection_run_summary(record).model_dump()
    return InspectionRunDetail(
        **summary,
        image_count=record.image_count,
        video_count=record.video_count,
        request=record.request_json,
        media=[
            _media_record_payload(media)
            for media in list_media_for_inspection_run(session, run_id=record.run_id)
        ],
        report=record.report_json,
        rendered_report=record.rendered_report,
        workflow_trace_path=record.workflow_trace_path,
        error=record.error,
    )


def _media_record_payload(record) -> dict[str, Any]:
    return {
        "media_id": record.media_id,
        "run_id": record.run_id,
        "media_type": record.media_type,
        "original_filename": record.original_filename,
        "content_type": record.content_type,
        "size_bytes": record.size_bytes,
        "checksum_sha256": record.checksum_sha256,
        "storage_backend": record.storage_backend,
        "storage_key": record.storage_key,
        "file_path": record.file_path,
        "preview_url": record.preview_url,
        "scan_status": record.scan_status,
        "metadata": record.metadata_json,
        "created_at": record.created_at.isoformat(),
    }
