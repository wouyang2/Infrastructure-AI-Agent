from __future__ import annotations

import base64
import binascii
import csv
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.helpers.pdf_report import build_inspection_pdf
from workflows.inspection_graph import run_inspection_graph


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


class InspectionRequest(BaseModel):
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
    report: dict
    rendered_report: str


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


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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

    try:
        image_bytes = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 image content.") from exc

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")

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

    try:
        video_bytes = base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 video content.") from exc

    if not video_bytes:
        raise HTTPException(status_code=400, detail="Uploaded video is empty.")

    output_name = f"{Path(original_name).stem[:60]}_{uuid4().hex[:10]}{extension}"
    output_path = UPLOADS_DIR / output_name
    output_path.write_bytes(video_bytes)
    return VideoUploadResponse(
        file_path=str(Path("artifacts") / "uploads" / output_name),
        preview_url=f"/artifacts/uploads/{output_name}",
    )


@app.post("/inspections", response_model=InspectionResponse)
def create_inspection(request: InspectionRequest) -> InspectionResponse:
    asset_metadata: dict[str, Any] = {
        key: value
        for key, value in {
            "latitude": request.latitude,
            "longitude": request.longitude,
        }.items()
        if value is not None
    }
    report = run_inspection_graph(
        {
            "asset_id": request.asset_id,
            "asset_type": request.asset_type,
            "asset_name": request.asset_name,
            "location": request.location,
            "criticality": request.criticality,
            "asset_metadata": asset_metadata,
            "notes": request.notes,
            "image_paths": request.image_paths,
            "video_paths": request.video_paths,
            "reason": request.reason,
        },
        image_analyzer_mode=request.image_analyzer,
        image_annotations_path=request.image_annotations_path,
        image_prompt_profile=request.image_prompt_profile,
        image_detail=request.image_detail,
        image_tiling=request.image_tiling,
        roboflow_confidence_threshold=request.roboflow_confidence_threshold,
        roboflow_backend=request.roboflow_backend,
        roboflow_class_mapping_profile=request.roboflow_class_mapping_profile,
        roboflow_tiling=request.roboflow_tiling,
        roboflow_class_thresholds=request.roboflow_class_thresholds,
        roboflow_inference_confidence=request.roboflow_inference_confidence,
        roboflow_inference_iou_threshold=request.roboflow_inference_iou_threshold,
        video_sampler_mode=request.video_sampler,
        video_frame_interval_seconds=request.video_frame_interval,
        video_max_frames=request.video_max_frames,
        severity_mode=request.severity_mode,
        planning_mode=request.planning_mode,
        scheduling_mode=request.scheduling_mode,
        schedule_context_mode=request.schedule_context_mode,
        event_provider=request.event_provider,
        report_mode=request.report_mode,
        llm_max_retries=request.llm_max_retries,
        llm_failure_mode=request.llm_failure_mode,
        rag_backend=request.rag_backend,
        embedding_backend=request.embedding_backend,
        embedding_model=request.embedding_model,
        chroma_persist_dir=request.chroma_persist_dir,
        rebuild_rag_index=request.rebuild_rag_index,
        knowledge_corpus=request.knowledge_corpus,
    )
    rendered_report = report.rendered_report or ""
    return InspectionResponse(
        report=asdict(report),
        rendered_report=rendered_report,
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
