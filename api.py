from __future__ import annotations

import base64
import binascii
import csv
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.helpers.pdf_report import build_inspection_pdf
from runtime.job_queue import build_inspection_job_queue
from runtime.progress_store import build_progress_store
from runtime.rate_limiter import build_rate_limiter
from storage.database import get_session, init_database
from storage.models import InspectionRunRecord
from storage.repositories import (
    create_inspection_run,
    get_inspection_run,
    list_inspection_runs,
    update_inspection_review,
)


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
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_UPLOAD_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
DEFAULT_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_VIDEO_UPLOAD_BYTES = 250 * 1024 * 1024


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
    video_frame_interval: float = 5.0
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


class InspectionReviewRequest(BaseModel):
    review_status: Literal["not_reviewed", "approved", "rejected", "needs_revision"]
    reviewer_notes: str | None = ""
    reviewed_by: str | None = "demo_reviewer"


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


class VideoUploadRequest(BaseModel):
    filename: str
    content_base64: str


class VideoUploadResponse(BaseModel):
    file_path: str
    preview_url: str


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


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/cases", response_model=list[InspectionRunSummary])
def cases(
    limit: int = 25,
    session: Session = Depends(get_session),
) -> list[InspectionRunSummary]:
    return [
        _inspection_run_summary(record)
        for record in list_inspection_runs(session, limit=min(max(limit, 1), 100))
    ]


@app.get("/cases/{run_id}", response_model=InspectionRunDetail)
def case_detail(
    run_id: str,
    session: Session = Depends(get_session),
) -> InspectionRunDetail:
    record = get_inspection_run(session, run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Inspection run not found.")
    return _inspection_run_detail(record)


@app.get("/cases/{run_id}/progress", response_model=InspectionProgressResponse)
def case_progress(run_id: str) -> InspectionProgressResponse:
    progress = progress_store.get_progress(run_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Inspection progress not found.")
    return InspectionProgressResponse(**progress)


@app.patch("/cases/{run_id}/review", response_model=InspectionRunDetail)
def review_case(
    run_id: str,
    request: InspectionReviewRequest,
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
    return _inspection_run_detail(record)


@app.get("/sample-images", response_model=list[SampleImage])
def sample_images(limit: int = 12) -> list[SampleImage]:
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
def upload_image(request: ImageUploadRequest) -> ImageUploadResponse:
    original_name = Path(request.filename).name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
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

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    _validate_decoded_upload_size(image_bytes, max_bytes=max_bytes, label="image")

    try:
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.") from exc

    output_name = f"{Path(original_name).stem[:60]}_{uuid4().hex[:10]}{extension}"
    output_path = UPLOADS_DIR / output_name
    output_path.write_bytes(image_bytes)
    return ImageUploadResponse(
        file_path=str(Path("artifacts") / "uploads" / output_name),
        preview_url=f"/artifacts/uploads/{output_name}",
    )


@app.post("/uploads/videos", response_model=VideoUploadResponse)
def upload_video(request: VideoUploadRequest) -> VideoUploadResponse:
    original_name = Path(request.filename).name
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_VIDEO_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
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

    if not video_bytes:
        raise HTTPException(status_code=400, detail="Uploaded video is empty.")
    _validate_decoded_upload_size(video_bytes, max_bytes=max_bytes, label="video")

    output_name = f"{Path(original_name).stem[:60]}_{uuid4().hex[:10]}{extension}"
    output_path = UPLOADS_DIR / output_name
    output_path.write_bytes(video_bytes)
    return VideoUploadResponse(
        file_path=str(Path("artifacts") / "uploads" / output_name),
        preview_url=f"/artifacts/uploads/{output_name}",
    )


@app.post("/inspections", response_model=InspectionResponse, status_code=202)
def create_inspection(
    request: InspectionRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> InspectionResponse:
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
    return InspectionResponse(
        run_id=run_record.run_id,
        status="queued",
        job_backend=dispatch.backend,
        job_id=dispatch.job_id,
        progress_url=f"/cases/{run_record.run_id}/progress",
        case_url=f"/cases/{run_record.run_id}",
    )


@app.post("/reports/pdf")
def export_report_pdf(request: PDFReportRequest) -> StreamingResponse:
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


def _inspection_run_detail(record: InspectionRunRecord) -> InspectionRunDetail:
    summary = _inspection_run_summary(record).model_dump()
    return InspectionRunDetail(
        **summary,
        image_count=record.image_count,
        video_count=record.video_count,
        request=record.request_json,
        report=record.report_json,
        rendered_report=record.rendered_report,
        workflow_trace_path=record.workflow_trace_path,
        error=record.error,
    )
