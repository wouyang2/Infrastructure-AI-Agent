from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
import os
from typing import Any, TypedDict

from fastapi.encoders import jsonable_encoder
from langgraph.graph import END, START, StateGraph

from agents.evidence_agent import EvidenceAgent
from agents.helpers.image_analyzer import ImageFinding, build_image_analyzer
from agents.helpers.maintenance_precedent_tool import MaintenancePrecedentTool
from agents.helpers.report_artifacts import AnnotatedImageArtifactGenerator
from agents.helpers.workflow_trace import WorkflowTrace, time_ms
from agents.helpers.video_sampler import build_video_frame_sampler
from agents.intake_agent import IntakeAgent
from agents.maintenance_planning_agent import MaintenancePlanningAgent
from agents.report_agent import ReportAgent
from agents.helpers.schedule_context_collector import build_schedule_context_collector
from agents.helpers.scheduling_precedent_tool import SchedulingPrecedentTool
from agents.helpers.severity_guidance_tool import SeverityGuidanceTool
from agents.scheduling_agent import SchedulingAgent
from agents.severity_agent import SeverityAgent
from data.knowledge_corpus import load_knowledge_documents
from data.sample_knowledge import (
    MOCK_REPAIR_WINDOWS,
    MOCK_SCHEDULING_CONTEXT,
)
from models import (
    Asset,
    Citation,
    Evidence,
    EventContext,
    HistoricalPrecedent,
    InspectionCase,
    InspectionReport,
    MaintenancePlan,
    MaintenanceTask,
    MediaReference,
    Observation,
    RepairSchedule,
    RepairWindow,
    SchedulingContext,
    SeverityAssessment,
    TrafficContext,
    WeatherContext,
)
from rag.retriever_factory import build_retriever
from runtime.checkpoints import get_checkpointer
from runtime.env_loader import load_dotenv_if_available as _load_dotenv_if_available
from runtime.tool_idempotency import run_json_tool_once, stable_json_hash
from storage.database import SessionLocal, init_database
from storage.media_resolver import build_media_resolver
from storage.repositories import get_inspection_run, mark_inspection_completed


ProgressCallback = Any


NODE_PROGRESS = {
    "intake": 10,
    "video_frame_tool": 17,
    "image_analysis_tool": 22,
    "evidence": 25,
    "severity_guidance_tool": 32,
    "severity": 40,
    "maintenance_precedent_tool": 48,
    "maintenance_planning": 55,
    "monitoring_plan": 65,
    "schedule_context": 70,
    "schedule_precedent_tool": 78,
    "scheduling": 85,
    "report": 90,
    "annotated_artifact_tool": 93,
    "report_render_tool": 95,
    "persist_report_tool": 98,
}


def _roll_repair_windows_forward(
    repair_windows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now()
    parsed_starts = [
        datetime.fromisoformat(str(window["start"]))
        for window in repair_windows
    ]
    if any(start >= now for start in parsed_starts):
        return [dict(window) for window in repair_windows]

    earliest_start = min(parsed_starts)
    days_to_roll = (now.date() - earliest_start.date()).days + 1
    delta = timedelta(days=days_to_roll)
    rolled_windows = []
    for window in repair_windows:
        rolled = dict(window)
        rolled["start"] = (
            datetime.fromisoformat(str(window["start"])) + delta
        ).isoformat()
        rolled["end"] = (
            datetime.fromisoformat(str(window["end"])) + delta
        ).isoformat()
        rolled_windows.append(rolled)
    return rolled_windows


def _scheduling_context_to_json(context: SchedulingContext) -> dict[str, Any]:
    return jsonable_encoder(asdict(context))


def _scheduling_context_from_json(payload: dict[str, Any]) -> SchedulingContext:
    return SchedulingContext(
        weather=[
            WeatherContext(**item)
            for item in payload.get("weather", [])
        ],
        traffic=[
            TrafficContext(**item)
            for item in payload.get("traffic", [])
        ],
        events=[
            EventContext(**item)
            for item in payload.get("events", [])
        ],
        access_risk_score=int(payload.get("access_risk_score", 0)),
    )


def _citations_to_json(citations: list[Citation]) -> list[dict[str, Any]]:
    return jsonable_encoder([asdict(citation) for citation in citations])


def _citations_from_json(payload: list[dict[str, Any]]) -> list[Citation]:
    return [Citation(**item) for item in payload]


def _historical_precedents_to_json(
    precedents: list[HistoricalPrecedent],
) -> list[dict[str, Any]]:
    return jsonable_encoder([asdict(precedent) for precedent in precedents])


def _historical_precedents_from_json(
    payload: list[dict[str, Any]],
) -> list[HistoricalPrecedent]:
    return [
        HistoricalPrecedent(
            document_id=item["document_id"],
            title=item["title"],
            repair_method=item["repair_method"],
            outcome=item["outcome"],
            actual_duration_hours=float(item["actual_duration_hours"]),
            disruption=item["disruption"],
            citation=Citation(**item["citation"]),
        )
        for item in payload
    ]


def _report_to_tool_input(report: InspectionReport) -> dict[str, Any]:
    payload = jsonable_encoder(asdict(report))
    payload.get("case", {}).pop("created_at", None)
    payload.pop("workflow_trace_id", None)
    payload.pop("workflow_trace_path", None)
    return {"report": payload}


def _image_findings_to_json(findings: list[ImageFinding]) -> list[dict[str, Any]]:
    return [asdict(finding) for finding in findings]


def _inspection_case_to_json(inspection_case: InspectionCase) -> dict[str, Any]:
    return jsonable_encoder(asdict(inspection_case))


def _inspection_case_from_json(payload: dict[str, Any]) -> InspectionCase:
    return InspectionCase(
        case_id=payload["case_id"],
        asset=Asset(**payload["asset"]),
        reason=payload["reason"],
        evidence=[Evidence(**item) for item in payload.get("evidence", [])],
        constraints=payload.get("constraints", {}),
        created_at=_datetime_from_json(payload.get("created_at")),
    )


def _observations_to_json(observations: list[Observation]) -> list[dict[str, Any]]:
    return jsonable_encoder([asdict(observation) for observation in observations])


def _observations_from_json(payload: list[dict[str, Any]]) -> list[Observation]:
    observations = []
    for item in payload:
        media_payload = item.get("media_reference")
        if media_payload and media_payload.get("bounding_box") is not None:
            media_payload = dict(media_payload)
            media_payload["bounding_box"] = tuple(media_payload["bounding_box"])
        observations.append(
            Observation(
                observation_id=item["observation_id"],
                source_id=item["source_id"],
                source_modality=item["source_modality"],
                defect_type=item["defect_type"],
                description=item["description"],
                location_on_asset=item["location_on_asset"],
                media_reference=MediaReference(**media_payload) if media_payload else None,
                measurement=item.get("measurement", {}),
                confidence=float(item.get("confidence", 0.0)),
            )
        )
    return observations


def _severity_assessment_to_json(severity: SeverityAssessment) -> dict[str, Any]:
    return jsonable_encoder(asdict(severity))


def _severity_assessment_from_json(payload: dict[str, Any]) -> SeverityAssessment:
    return SeverityAssessment(
        severity=payload["severity"],
        repair_required=bool(payload["repair_required"]),
        urgency=payload["urgency"],
        rationale=payload["rationale"],
        confidence=float(payload["confidence"]),
        citations=_citations_from_json(payload.get("citations", [])),
    )


def _maintenance_plan_to_json(plan: MaintenancePlan) -> dict[str, Any]:
    return jsonable_encoder(asdict(plan))


def _maintenance_plan_from_json(payload: dict[str, Any]) -> MaintenancePlan:
    return MaintenancePlan(
        recommended_action=payload["recommended_action"],
        historical_precedents=_historical_precedents_from_json(
            payload.get("historical_precedents", [])
        ),
        tasks=[MaintenanceTask(**item) for item in payload.get("tasks", [])],
        materials=list(payload.get("materials", [])),
        equipment=list(payload.get("equipment", [])),
        permits=list(payload.get("permits", [])),
        estimated_duration_hours=float(payload["estimated_duration_hours"]),
        risks=list(payload.get("risks", [])),
    )


def _repair_schedule_to_json(schedule: RepairSchedule | None) -> dict[str, Any] | None:
    if schedule is None:
        return None
    return jsonable_encoder(asdict(schedule))


def _repair_schedule_from_json(payload: dict[str, Any] | None) -> RepairSchedule | None:
    if payload is None:
        return None
    window = payload["recommended_window"]
    return RepairSchedule(
        recommended_window=RepairWindow(
            start=_datetime_from_json(window["start"]),
            end=_datetime_from_json(window["end"]),
        ),
        disruption_score=int(payload["disruption_score"]),
        context_risk_score=int(payload["context_risk_score"]),
        total_score=int(payload["total_score"]),
        constraints_satisfied=list(payload.get("constraints_satisfied", [])),
        tradeoffs=list(payload.get("tradeoffs", [])),
        context_summary=list(payload.get("context_summary", [])),
    )


def _report_to_json(report: InspectionReport) -> dict[str, Any]:
    return jsonable_encoder(asdict(report))


def _report_from_json(payload: dict[str, Any]) -> InspectionReport:
    return InspectionReport(
        case=_inspection_case_from_json(payload["case"]),
        observations=_observations_from_json(payload.get("observations", [])),
        severity=_severity_assessment_from_json(payload["severity"]),
        maintenance_plan=_maintenance_plan_from_json(payload["maintenance_plan"]),
        schedule=_repair_schedule_from_json(payload.get("schedule")),
        annotated_media_paths=list(payload.get("annotated_media_paths", [])),
        rendered_report=payload.get("rendered_report"),
        workflow_trace_id=payload.get("workflow_trace_id"),
        workflow_trace_path=payload.get("workflow_trace_path"),
    )


def _datetime_from_json(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _rehydrate_checkpoint_state(state: InspectionGraphState) -> InspectionGraphState:
    hydrated = dict(state)
    if isinstance(hydrated.get("inspection_case"), dict):
        hydrated["inspection_case"] = _inspection_case_from_json(hydrated["inspection_case"])
    if isinstance(hydrated.get("observations"), list) and hydrated["observations"] and isinstance(hydrated["observations"][0], dict):
        hydrated["observations"] = _observations_from_json(hydrated["observations"])
    if isinstance(hydrated.get("severity_guidance_citations"), list) and hydrated["severity_guidance_citations"] and isinstance(hydrated["severity_guidance_citations"][0], dict):
        hydrated["severity_guidance_citations"] = _citations_from_json(hydrated["severity_guidance_citations"])
    if isinstance(hydrated.get("severity_assessment"), dict):
        hydrated["severity_assessment"] = _severity_assessment_from_json(hydrated["severity_assessment"])
    if isinstance(hydrated.get("historical_precedents"), list) and hydrated["historical_precedents"] and isinstance(hydrated["historical_precedents"][0], dict):
        hydrated["historical_precedents"] = _historical_precedents_from_json(hydrated["historical_precedents"])
    if isinstance(hydrated.get("maintenance_plan"), dict):
        hydrated["maintenance_plan"] = _maintenance_plan_from_json(hydrated["maintenance_plan"])
    if isinstance(hydrated.get("scheduling_context"), dict):
        hydrated["scheduling_context"] = _scheduling_context_from_json(hydrated["scheduling_context"])
    if isinstance(hydrated.get("repair_schedule"), dict):
        hydrated["repair_schedule"] = _repair_schedule_from_json(hydrated["repair_schedule"])
    if isinstance(hydrated.get("report"), dict):
        hydrated["report"] = _report_from_json(hydrated["report"])
    return hydrated


def _serialize_checkpoint_delta(output: InspectionGraphState) -> InspectionGraphState:
    serialized: dict[str, Any] = {}
    for key, value in output.items():
        if key == "inspection_case" and isinstance(value, InspectionCase):
            serialized[key] = _inspection_case_to_json(value)
        elif key == "observations" and isinstance(value, list) and _list_contains_dataclasses(value):
            serialized[key] = _observations_to_json(value)
        elif key == "severity_guidance_citations" and isinstance(value, list) and _list_contains_dataclasses(value):
            serialized[key] = _citations_to_json(value)
        elif key == "severity_assessment" and isinstance(value, SeverityAssessment):
            serialized[key] = _severity_assessment_to_json(value)
        elif key == "historical_precedents" and isinstance(value, list) and _list_contains_dataclasses(value):
            serialized[key] = _historical_precedents_to_json(value)
        elif key == "maintenance_plan" and isinstance(value, MaintenancePlan):
            serialized[key] = _maintenance_plan_to_json(value)
        elif key == "scheduling_context" and isinstance(value, SchedulingContext):
            serialized[key] = _scheduling_context_to_json(value)
        elif key == "repair_schedule" and isinstance(value, RepairSchedule):
            serialized[key] = _repair_schedule_to_json(value)
        elif key == "report" and isinstance(value, InspectionReport):
            serialized[key] = _report_to_json(value)
        else:
            serialized[key] = jsonable_encoder(value)
    return serialized


def _list_contains_dataclasses(value: list[Any]) -> bool:
    return bool(value) and is_dataclass(value[0])


class InspectionGraphState(TypedDict, total=False):
    input: dict[str, Any]
    inspection_case: InspectionCase
    video_frame_samples: list[dict[str, Any]]
    visual_analysis_results: list[dict[str, Any]]
    observations: list[Observation]
    severity_guidance_citations: list[Citation]
    severity_assessment: SeverityAssessment
    historical_precedents: list[HistoricalPrecedent]
    precedent_documents: list[dict[str, Any]]
    maintenance_plan: MaintenancePlan
    scheduling_context: SchedulingContext
    scheduling_precedents: list[dict[str, Any]]
    repair_schedule: RepairSchedule
    report: InspectionReport
    annotated_media_paths: list[str]
    rendered_report: str
    persist_report_result: dict[str, Any]
    workflow_trace_path: str


def build_inspection_graph(
    image_analyzer_mode: str = "heuristic",
    *,
    image_annotations_path: str = "data/bridge_image/annotations.csv",
    image_prompt_profile: str | None = None,
    image_detail: str | None = None,
    image_tiling: str = "none",
    roboflow_confidence_threshold: float = 0.25,
    roboflow_backend: str | None = None,
    roboflow_class_mapping_profile: str | None = None,
    roboflow_tiling: str = "none",
    roboflow_class_thresholds: dict[str, float] | str | None = None,
    roboflow_inference_confidence: float | None = None,
    roboflow_inference_iou_threshold: float | None = None,
    vision_verifier: str = "none",
    verification_confidence_threshold: float = 0.55,
    verifier_prompt_profile: str | None = None,
    video_sampler_mode: str = "mock",
    video_frame_interval_seconds: float = 5.0,
    video_max_frames: int = 3,
    severity_mode: str = "deterministic",
    severity_rationale_generator: Any | None = None,
    planning_mode: str = "deterministic",
    planning_generator: Any | None = None,
    scheduling_mode: str = "llm",
    schedule_generator: Any | None = None,
    schedule_context_mode: str = "mock",
    event_provider: str = "mock",
    report_mode: str = "deterministic",
    report_generator: Any | None = None,
    llm_max_retries: int = 4,
    llm_failure_mode: str = "fallback",
    rag_backend: str = "chroma",
    embedding_backend: str = "openai",
    embedding_model: str | None = None,
    chroma_persist_dir: str = "artifacts/chroma",
    rebuild_rag_index: bool = False,
    knowledge_corpus: str = "merged",
    trace_output_dir: str = "artifacts/traces",
    enable_workflow_trace: bool = True,
    enable_memory_checkpoint: bool = True,
    checkpoint_backend: str | None = None,
    checkpoint_sqlite_path: str | None = None,
    progress_callback: ProgressCallback | None = None,
):
    _load_dotenv_if_available()

    repair_windows = (
        _roll_repair_windows_forward(MOCK_REPAIR_WINDOWS)
        if schedule_context_mode == "live"
        else MOCK_REPAIR_WINDOWS
    )
    knowledge_documents = load_knowledge_documents(knowledge_corpus)  # type: ignore[arg-type]
    retriever = build_retriever(
        knowledge_documents,
        rag_backend=rag_backend,
        embedding_backend=embedding_backend,
        embedding_model=embedding_model,
        persist_directory=chroma_persist_dir,
        rebuild_index=rebuild_rag_index,
    )

    intake_agent = IntakeAgent()
    image_analyzer = build_image_analyzer(
        image_analyzer_mode,
        annotations_path=image_annotations_path,
        image_prompt_profile=image_prompt_profile,
        image_detail=image_detail,
        image_tiling=image_tiling,
        roboflow_confidence_threshold=roboflow_confidence_threshold,
        roboflow_backend=roboflow_backend,
        roboflow_class_mapping_profile=roboflow_class_mapping_profile,
        roboflow_tiling=roboflow_tiling,
        roboflow_class_thresholds=roboflow_class_thresholds,
        roboflow_inference_confidence=roboflow_inference_confidence,
        roboflow_inference_iou_threshold=roboflow_inference_iou_threshold,
        vision_verifier=vision_verifier,
        verification_confidence_threshold=verification_confidence_threshold,
        verifier_prompt_profile=verifier_prompt_profile,
    )
    media_resolver = build_media_resolver()
    video_frame_sampler = build_video_frame_sampler(
        video_sampler_mode,
        interval_seconds=video_frame_interval_seconds,
        max_frames=video_max_frames,
    )
    evidence_agent = EvidenceAgent(image_analyzer, video_frame_sampler)
    severity_agent = SeverityAgent(
        retriever,
        severity_mode=severity_mode,  # type: ignore[arg-type]
        rationale_generator=severity_rationale_generator,
        llm_max_retries=llm_max_retries,
        llm_failure_mode=llm_failure_mode,  # type: ignore[arg-type]
    )
    severity_guidance_tool = SeverityGuidanceTool(retriever)
    maintenance_precedent_tool = MaintenancePrecedentTool(retriever)
    planning_agent = MaintenancePlanningAgent(
        retriever,
        planning_mode=planning_mode,  # type: ignore[arg-type]
        planning_generator=planning_generator,
        llm_max_retries=llm_max_retries,
        llm_failure_mode=llm_failure_mode,  # type: ignore[arg-type]
    )
    context_collector = build_schedule_context_collector(
        schedule_context_mode,
        MOCK_SCHEDULING_CONTEXT,
        event_provider=event_provider,
    )
    scheduling_precedent_tool = SchedulingPrecedentTool(retriever)
    scheduling_agent = SchedulingAgent(
        repair_windows,
        scheduling_mode=scheduling_mode,  # type: ignore[arg-type]
        schedule_generator=schedule_generator,
        llm_max_retries=llm_max_retries,
        llm_failure_mode=llm_failure_mode,  # type: ignore[arg-type]
    )
    report_agent = ReportAgent(
        report_mode=report_mode,  # type: ignore[arg-type]
        report_generator=report_generator,
        llm_max_retries=llm_max_retries,
        llm_failure_mode=llm_failure_mode,  # type: ignore[arg-type]
    )
    artifact_generator = AnnotatedImageArtifactGenerator()
    workflow_trace = WorkflowTrace(output_dir=trace_output_dir) if enable_workflow_trace else None
    

    graph = StateGraph(InspectionGraphState)

    def traced_node(name: str, node):
        if workflow_trace is None and progress_callback is None and not enable_memory_checkpoint:
            return node

        def wrapped(state: InspectionGraphState) -> InspectionGraphState:
            node_state = _rehydrate_checkpoint_state(state)
            _record_progress(
                progress_callback,
                stage=name,
                status="running",
                message=f"{name.replace('_', ' ').title()} started.",
                percent=max(NODE_PROGRESS.get(name, 0) - 5, 1),
            )
            started_at = time_ms()
            try:
                output = node(node_state)
            except Exception as exc:
                duration_ms = time_ms() - started_at
                if workflow_trace is not None:
                    workflow_trace.record_node(
                        node_name=name,
                        status="error",
                        duration_ms=duration_ms,
                        error=str(exc),
                    )
                _record_progress(
                    progress_callback,
                    stage=name,
                    status="failed",
                    message=f"{name.replace('_', ' ').title()} failed: {exc}",
                    percent=NODE_PROGRESS.get(name, 100),
                    metadata={"duration_ms": round(duration_ms, 3)},
                )
                raise

            duration_ms = time_ms() - started_at
            output_keys = sorted(output.keys())
            if workflow_trace is not None:
                workflow_trace.record_node(
                    node_name=name,
                    status="ok",
                    duration_ms=duration_ms,
                    output_keys=output_keys,
                )
            _record_progress(
                progress_callback,
                stage=name,
                status="running",
                message=f"{name.replace('_', ' ').title()} completed.",
                percent=NODE_PROGRESS.get(name, 95),
                metadata={
                    "duration_ms": round(duration_ms, 3),
                    "output_keys": output_keys,
                },
            )
            if name == "persist_report_tool" and "report" in output:
                report = output["report"]
                if workflow_trace is not None:
                    trace_path = workflow_trace.write(
                        case_id=report.case.case_id,
                        repair_required=report.severity.repair_required,
                        severity=report.severity.severity,
                    )
                    report.workflow_trace_id = workflow_trace.trace_id
                    report.workflow_trace_path = trace_path
                    output["workflow_trace_path"] = trace_path
            return _serialize_checkpoint_delta(output)

        return wrapped

    def intake_node(state: InspectionGraphState) -> InspectionGraphState:
        values = state["input"]
        inspection_case = intake_agent.create_case(
            asset_id=values["asset_id"],
            asset_type=values["asset_type"],
            asset_name=values["asset_name"],
            location=values["location"],
            criticality=values["criticality"],
            inspection_notes=values["notes"],
            image_paths=values.get("image_paths", []),
            video_paths=values.get("video_paths", []),
            asset_metadata=values.get("asset_metadata", {}),
            reason=values["reason"],
        )
        return {"inspection_case": inspection_case}

    def video_frame_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["inspection_case"].case_id
        )
        video_evidence = [
            {
                "source_id": evidence.source_id,
                "file_path": evidence.file_path,
            }
            for evidence in state["inspection_case"].evidence
            if evidence.modality == "video" and evidence.file_path
        ]
        tool_input = {
            "case_id": state["inspection_case"].case_id,
            "video_sampler_mode": video_sampler_mode,
            "video_frame_interval_seconds": video_frame_interval_seconds,
            "video_max_frames": video_max_frames,
            "video_evidence": video_evidence,
        }
        idempotency_key = (
            f"{run_id}:video_frame_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            samples = []
            for evidence in state["inspection_case"].evidence:
                if evidence.modality != "video" or not evidence.file_path:
                    continue
                resolved_video = media_resolver.resolve(evidence.file_path)
                for frame in video_frame_sampler.sample(resolved_video.local_path):
                    samples.append(
                        {
                            "source_id": evidence.source_id,
                            "video_path": evidence.file_path,
                            "resolved_video_path": resolved_video.local_path,
                            "image_path": frame.image_path,
                            "timestamp_seconds": frame.timestamp_seconds,
                        }
                    )
            return {"video_frame_samples": samples}

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="video_frame_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        return {"video_frame_samples": output["video_frame_samples"]}

    def image_analysis_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["inspection_case"].case_id
        )
        image_evidence = [
            {
                "source_id": evidence.source_id,
                "file_path": evidence.file_path,
            }
            for evidence in state["inspection_case"].evidence
            if evidence.modality == "image" and evidence.file_path
        ]
        tool_input = {
            "case_id": state["inspection_case"].case_id,
            "asset_type": state["inspection_case"].asset.asset_type,
            "image_analyzer_mode": image_analyzer_mode,
            "image_annotations_path": image_annotations_path,
            "image_prompt_profile": image_prompt_profile,
            "image_detail": image_detail,
            "image_tiling": image_tiling,
            "roboflow_confidence_threshold": roboflow_confidence_threshold,
            "roboflow_backend": roboflow_backend,
            "roboflow_class_mapping_profile": roboflow_class_mapping_profile,
            "roboflow_tiling": roboflow_tiling,
            "roboflow_class_thresholds": roboflow_class_thresholds,
            "roboflow_inference_confidence": roboflow_inference_confidence,
            "roboflow_inference_iou_threshold": roboflow_inference_iou_threshold,
            "vision_verifier": vision_verifier,
            "verification_confidence_threshold": verification_confidence_threshold,
            "verifier_prompt_profile": verifier_prompt_profile,
            "image_evidence": image_evidence,
            "video_frame_samples": state.get("video_frame_samples", []),
        }
        idempotency_key = (
            f"{run_id}:image_analysis_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            results = []
            for evidence in state["inspection_case"].evidence:
                if evidence.modality != "image" or not evidence.file_path:
                    continue
                resolved_image = media_resolver.resolve(evidence.file_path)
                results.append(
                    {
                        "source_id": evidence.source_id,
                        "source_modality": "image",
                        "source_file_path": evidence.file_path,
                        "analyzed_image_path": resolved_image.local_path,
                        "frame_timestamp_seconds": evidence.frame_timestamp_seconds,
                        "findings": _image_findings_to_json(
                            image_analyzer.analyze(
                                resolved_image.local_path,
                                state["inspection_case"].asset.asset_type,
                            )
                        ),
                    }
                )

            for frame in state.get("video_frame_samples", []):
                results.append(
                    {
                        "source_id": frame["source_id"],
                        "source_modality": "video_frame",
                        "source_file_path": frame["video_path"],
                        "analyzed_image_path": frame["image_path"],
                        "frame_timestamp_seconds": frame["timestamp_seconds"],
                        "findings": _image_findings_to_json(
                            image_analyzer.analyze(
                                frame["image_path"],
                                state["inspection_case"].asset.asset_type,
                            )
                        ),
                    }
                )
            return {"visual_analysis_results": results}

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="image_analysis_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        return {"visual_analysis_results": output["visual_analysis_results"]}

    def evidence_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "observations": evidence_agent.extract_observations(
                state["inspection_case"],
                state.get("visual_analysis_results", []),
            )
        }

    def severity_guidance_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["inspection_case"].case_id
        )
        tool_input = {
            "case_id": state["inspection_case"].case_id,
            "asset_id": state["inspection_case"].asset.asset_id,
            "asset_type": state["inspection_case"].asset.asset_type,
            "criticality": state["inspection_case"].asset.criticality,
            "observations": [
                {
                    "observation_id": observation.observation_id,
                    "defect_type": observation.defect_type,
                    "description": observation.description,
                    "confidence": observation.confidence,
                }
                for observation in state["observations"]
            ],
        }
        idempotency_key = (
            f"{run_id}:severity_guidance_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            return {
                "severity_guidance_citations": _citations_to_json(
                    severity_guidance_tool.invoke(
                        inspection_case=state["inspection_case"],
                        observations=state["observations"],
                    )
                )
            }

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="severity_guidance_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        return {
            "severity_guidance_citations": _citations_from_json(
                output["severity_guidance_citations"]
            )
        }

    def severity_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "severity_assessment": severity_agent.assess(
                state["inspection_case"],
                state["observations"],
                state.get("severity_guidance_citations", []),
            )
        }

    def maintenance_precedent_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["inspection_case"].case_id
        )
        tool_input = {
            "case_id": state["inspection_case"].case_id,
            "asset_id": state["inspection_case"].asset.asset_id,
            "asset_type": state["inspection_case"].asset.asset_type,
            "severity": state["severity_assessment"].severity,
            "repair_required": state["severity_assessment"].repair_required,
            "observations": [
                {
                    "observation_id": observation.observation_id,
                    "defect_type": observation.defect_type,
                    "description": observation.description,
                    "confidence": observation.confidence,
                }
                for observation in state["observations"]
            ],
        }
        idempotency_key = (
            f"{run_id}:maintenance_precedent_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            payload = maintenance_precedent_tool.invoke(
                inspection_case=state["inspection_case"],
                observations=state["observations"],
                severity=state["severity_assessment"],
            )
            return {
                "historical_precedents": _historical_precedents_to_json(
                    payload["historical_precedents"]
                ),
                "precedent_documents": payload["precedent_documents"],
            }

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="maintenance_precedent_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        return {
            "historical_precedents": _historical_precedents_from_json(
                output["historical_precedents"]
            ),
            "precedent_documents": output["precedent_documents"],
        }

    def maintenance_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "maintenance_plan": planning_agent.create_plan(
                state["inspection_case"],
                state["observations"],
                state["severity_assessment"],
                state.get("historical_precedents", []),
                state.get("precedent_documents", []),
            )
        }

    def monitoring_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "maintenance_plan": planning_agent.create_plan(
                state["inspection_case"],
                state["observations"],
                state["severity_assessment"],
            )
        }

    def schedule_context_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["inspection_case"].case_id
        )
        tool_input = {
            "case_id": state["inspection_case"].case_id,
            "asset_id": state["inspection_case"].asset.asset_id,
            "asset_type": state["inspection_case"].asset.asset_type,
            "asset_metadata": state["inspection_case"].asset.metadata,
            "schedule_context_mode": schedule_context_mode,
            "event_provider": event_provider,
            "repair_windows": repair_windows,
        }
        idempotency_key = (
            f"{run_id}:schedule_context_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            context = context_collector.collect(
                state["inspection_case"],
                repair_windows,
            )
            return {"scheduling_context": _scheduling_context_to_json(context)}

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="schedule_context_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        return {
            "scheduling_context": _scheduling_context_from_json(
                output["scheduling_context"]
            )
        }

    def schedule_precedent_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["inspection_case"].case_id
        )
        tool_input = {
            "case_id": state["inspection_case"].case_id,
            "asset_id": state["inspection_case"].asset.asset_id,
            "asset_type": state["inspection_case"].asset.asset_type,
            "severity": state["severity_assessment"].severity,
            "recommended_action": state["maintenance_plan"].recommended_action,
            "estimated_duration_hours": state["maintenance_plan"].estimated_duration_hours,
            "permits": state["maintenance_plan"].permits,
            "equipment": state["maintenance_plan"].equipment,
        }
        idempotency_key = (
            f"{run_id}:schedule_precedent_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            return {
                "scheduling_precedents": scheduling_precedent_tool.invoke(
                    inspection_case=state["inspection_case"],
                    severity=state["severity_assessment"],
                    maintenance_plan=state["maintenance_plan"],
                )
            }

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="schedule_precedent_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        return {
            "scheduling_precedents": output["scheduling_precedents"]
        }

    def scheduling_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "repair_schedule": scheduling_agent.schedule(
                state["inspection_case"],
                state["severity_assessment"],
                state["maintenance_plan"],
                state["scheduling_context"],
                state.get("scheduling_precedents", []),
            )
        }

    def report_node(state: InspectionGraphState) -> InspectionGraphState:
        report = InspectionReport(
            case=state["inspection_case"],
            observations=state["observations"],
            severity=state["severity_assessment"],
            maintenance_plan=state["maintenance_plan"],
            schedule=state.get("repair_schedule"),
        )
        return {
            "report": report,
        }

    def annotated_artifact_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["report"].case.case_id
        )
        report = state["report"]
        tool_input = _report_to_tool_input(report)
        idempotency_key = (
            f"{run_id}:annotated_artifact_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            return {"annotated_media_paths": artifact_generator.generate(report)}

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="annotated_artifact_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        report.annotated_media_paths = list(output["annotated_media_paths"])
        return {
            "report": report,
            "annotated_media_paths": report.annotated_media_paths,
        }

    def report_render_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["report"].case.case_id
        )
        report = state["report"]
        tool_input = _report_to_tool_input(report)
        idempotency_key = (
            f"{run_id}:report_render_tool:"
            f"{stable_json_hash(tool_input)[:16]}"
        )

        def run_tool() -> dict[str, Any]:
            return {"rendered_report": report_agent.render(report)}

        init_database()
        session = SessionLocal()
        try:
            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="report_render_tool",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        rendered_report = str(output["rendered_report"])
        report.rendered_report = rendered_report
        return {
            "report": report,
            "rendered_report": rendered_report,
        }

    def persist_report_tool_node(state: InspectionGraphState) -> InspectionGraphState:
        input_values = state.get("input", {})
        run_id = (
            input_values.get("client_run_id")
            or input_values.get("run_id")
            or state["report"].case.case_id
        )
        report = state["report"]
        if workflow_trace is not None:
            trace_path = workflow_trace.write(
                case_id=report.case.case_id,
                repair_required=report.severity.repair_required,
                severity=report.severity.severity,
            )
            report.workflow_trace_id = workflow_trace.trace_id
            report.workflow_trace_path = trace_path

        report_payload = jsonable_encoder(asdict(report))
        rendered_report = report.rendered_report or state.get("rendered_report", "")
        tool_input = {
            "run_id": run_id,
            "case_id": report_payload["case"]["case_id"],
            "report_content_hash": stable_json_hash(_report_to_tool_input(report)),
        }
        idempotency_key = f"{run_id}:persist_inspection_report:v1"

        init_database()
        session = SessionLocal()
        try:
            existing = get_inspection_run(session, str(run_id))
            if existing is None:
                return {
                    "report": report,
                    "persist_report_result": {
                        "run_id": str(run_id),
                        "status": "skipped",
                        "reason": "inspection_run_not_found",
                        "case_id": report_payload["case"]["case_id"],
                    },
                }

            def run_tool() -> dict[str, Any]:
                record = mark_inspection_completed(
                    session,
                    run_id=str(run_id),
                    report_json=report_payload,
                    rendered_report=rendered_report,
                )
                return {
                    "run_id": record.run_id,
                    "status": record.status,
                    "case_id": record.case_id,
                }

            output = run_json_tool_once(
                session,
                run_id=str(run_id),
                tool_name="persist_inspection_report",
                idempotency_key=idempotency_key,
                input_json=tool_input,
                tool_fn=run_tool,
            )
        finally:
            session.close()

        return {
            "report": report,
            "persist_report_result": output,
        }

    graph.add_node("intake", traced_node("intake", intake_node))
    graph.add_node("video_frame_tool", traced_node("video_frame_tool", video_frame_tool_node))
    graph.add_node("image_analysis_tool", traced_node("image_analysis_tool", image_analysis_tool_node))
    graph.add_node("evidence", traced_node("evidence", evidence_node))
    graph.add_node("severity_guidance_tool", traced_node("severity_guidance_tool", severity_guidance_tool_node))
    graph.add_node("severity", traced_node("severity", severity_node))
    graph.add_node("maintenance_precedent_tool", traced_node("maintenance_precedent_tool", maintenance_precedent_tool_node))
    graph.add_node("maintenance_planning", traced_node("maintenance_planning", maintenance_node))
    graph.add_node("monitoring_plan", traced_node("monitoring_plan", monitoring_node))
    graph.add_node("schedule_context", traced_node("schedule_context", schedule_context_node))
    graph.add_node("schedule_precedent_tool", traced_node("schedule_precedent_tool", schedule_precedent_tool_node))
    graph.add_node("scheduling", traced_node("scheduling", scheduling_node))
    graph.add_node("report", traced_node("report", report_node))
    graph.add_node("annotated_artifact_tool", traced_node("annotated_artifact_tool", annotated_artifact_tool_node))
    graph.add_node("report_render_tool", traced_node("report_render_tool", report_render_tool_node))
    graph.add_node("persist_report_tool", traced_node("persist_report_tool", persist_report_tool_node))

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "video_frame_tool")
    graph.add_edge("video_frame_tool", "image_analysis_tool")
    graph.add_edge("image_analysis_tool", "evidence")
    graph.add_edge("evidence", "severity_guidance_tool")
    graph.add_edge("severity_guidance_tool", "severity")
    graph.add_conditional_edges(
        "severity",
        lambda state: (
            "repair_required"
            if _rehydrate_checkpoint_state(state)["severity_assessment"].repair_required
            else "monitor_only"
        ),
        {
            "repair_required": "maintenance_precedent_tool",
            "monitor_only": "monitoring_plan",
        },
    )
    graph.add_edge("maintenance_precedent_tool", "maintenance_planning")
    graph.add_edge("maintenance_planning", "schedule_context")
    graph.add_edge("monitoring_plan", "report")
    graph.add_edge("schedule_context", "schedule_precedent_tool")
    graph.add_edge("schedule_precedent_tool", "scheduling")
    graph.add_edge("scheduling", "report")
    graph.add_edge("report", "annotated_artifact_tool")
    graph.add_edge("annotated_artifact_tool", "report_render_tool")
    graph.add_edge("report_render_tool", "persist_report_tool")
    graph.add_edge("persist_report_tool", END)

    if enable_memory_checkpoint:
        return graph.compile(
            checkpointer=get_checkpointer(
                backend=checkpoint_backend,
                sqlite_path=checkpoint_sqlite_path,
            )
        )
    return graph.compile()


def run_inspection_graph(
    input_values: dict[str, Any],
    *,
    image_analyzer_mode: str = "heuristic",
    image_annotations_path: str = "data/bridge_image/annotations.csv",
    image_prompt_profile: str | None = None,
    image_detail: str | None = None,
    image_tiling: str = "none",
    roboflow_confidence_threshold: float = 0.25,
    roboflow_backend: str | None = None,
    roboflow_class_mapping_profile: str | None = None,
    roboflow_tiling: str = "none",
    roboflow_class_thresholds: dict[str, float] | str | None = None,
    roboflow_inference_confidence: float | None = None,
    roboflow_inference_iou_threshold: float | None = None,
    vision_verifier: str = "none",
    verification_confidence_threshold: float = 0.55,
    verifier_prompt_profile: str | None = None,
    video_sampler_mode: str = "mock",
    video_frame_interval_seconds: float = 5.0,
    video_max_frames: int = 3,
    severity_mode: str = "deterministic",
    severity_rationale_generator: Any | None = None,
    planning_mode: str = "deterministic",
    planning_generator: Any | None = None,
    scheduling_mode: str = "llm",
    schedule_generator: Any | None = None,
    schedule_context_mode: str = "mock",
    event_provider: str = "mock",
    report_mode: str = "deterministic",
    report_generator: Any | None = None,
    llm_max_retries: int = 4,
    llm_failure_mode: str = "fallback",
    rag_backend: str = "chroma",
    embedding_backend: str = "openai",
    embedding_model: str | None = None,
    chroma_persist_dir: str = "artifacts/chroma",
    rebuild_rag_index: bool = False,
    knowledge_corpus: str = "merged",
    trace_output_dir: str = "artifacts/traces",
    enable_workflow_trace: bool = True,
    enable_memory_checkpoint: bool = True,
    checkpoint_backend: str | None = None,
    checkpoint_sqlite_path: str | None = None,
    checkpoint_thread_id: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> InspectionReport:
    graph = build_inspection_graph(
        image_analyzer_mode=image_analyzer_mode,
        image_annotations_path=image_annotations_path,
        image_prompt_profile=image_prompt_profile,
        image_detail=image_detail,
        image_tiling=image_tiling,
        roboflow_confidence_threshold=roboflow_confidence_threshold,
        roboflow_backend=roboflow_backend,
        roboflow_class_mapping_profile=roboflow_class_mapping_profile,
        roboflow_tiling=roboflow_tiling,
        roboflow_class_thresholds=roboflow_class_thresholds,
        roboflow_inference_confidence=roboflow_inference_confidence,
        roboflow_inference_iou_threshold=roboflow_inference_iou_threshold,
        vision_verifier=vision_verifier,
        verification_confidence_threshold=verification_confidence_threshold,
        verifier_prompt_profile=verifier_prompt_profile,
        video_sampler_mode=video_sampler_mode,
        video_frame_interval_seconds=video_frame_interval_seconds,
        video_max_frames=video_max_frames,
        severity_mode=severity_mode,
        severity_rationale_generator=severity_rationale_generator,
        planning_mode=planning_mode,
        planning_generator=planning_generator,
        scheduling_mode=scheduling_mode,
        schedule_generator=schedule_generator,
        schedule_context_mode=schedule_context_mode,
        event_provider=event_provider,
        report_mode=report_mode,
        report_generator=report_generator,
        llm_max_retries=llm_max_retries,
        llm_failure_mode=llm_failure_mode,
        rag_backend=rag_backend,
        embedding_backend=embedding_backend,
        embedding_model=embedding_model,
        chroma_persist_dir=chroma_persist_dir,
        rebuild_rag_index=rebuild_rag_index,
        knowledge_corpus=knowledge_corpus,
        trace_output_dir=trace_output_dir,
        enable_workflow_trace=enable_workflow_trace,
        enable_memory_checkpoint=enable_memory_checkpoint,
        checkpoint_backend=checkpoint_backend,
        checkpoint_sqlite_path=checkpoint_sqlite_path,
        progress_callback=progress_callback,
    )
    config = None
    if enable_memory_checkpoint:
        config = {
            "configurable": {
                "thread_id": checkpoint_thread_id or input_values.get("asset_id", "inspection-run"),
            }
        }
    result = _invoke_graph_with_checkpoint_resume(
        graph,
        input_values,
        config=config,
        progress_callback=progress_callback,
    )
    report = result["report"]
    return _report_from_json(report) if isinstance(report, dict) else report


def _invoke_graph_with_checkpoint_resume(
    graph: Any,
    input_values: dict[str, Any],
    *,
    config: dict[str, Any] | None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    if config is not None:
        snapshot = graph.get_state(config)
        if snapshot.next:
            _record_progress(
                progress_callback,
                stage="checkpoint_resume",
                status="running",
                message="Resuming inspection graph from checkpoint.",
                percent=2,
                metadata={"next_nodes": list(snapshot.next)},
            )
            return graph.invoke(None, config=config, durability="sync")

    if config is not None:
        return graph.invoke({"input": input_values}, config=config, durability="sync")
    return graph.invoke({"input": input_values}, config=config)


def _record_progress(
    callback: ProgressCallback | None,
    *,
    stage: str,
    status: str,
    message: str,
    percent: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    callback(
        stage=stage,
        status=status,
        message=message,
        percent=percent,
        metadata=metadata,
    )
