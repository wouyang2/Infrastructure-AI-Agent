from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.evidence_agent import EvidenceAgent
from agents.helpers.image_analyzer import build_image_analyzer
from agents.helpers.report_artifacts import AnnotatedImageArtifactGenerator
from agents.helpers.video_sampler import build_video_frame_sampler
from agents.intake_agent import IntakeAgent
from agents.maintenance_planning_agent import MaintenancePlanningAgent
from agents.report_agent import ReportAgent
from agents.helpers.schedule_context_collector import build_schedule_context_collector
from agents.scheduling_agent import SchedulingAgent
from agents.severity_agent import SeverityAgent
from data.knowledge_corpus import load_knowledge_documents
from data.sample_knowledge import (
    MOCK_REPAIR_WINDOWS,
    MOCK_SCHEDULING_CONTEXT,
)
from models import (
    InspectionCase,
    InspectionReport,
    MaintenancePlan,
    Observation,
    RepairSchedule,
    SchedulingContext,
    SeverityAssessment,
)
from rag.retriever_factory import build_retriever


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


class InspectionGraphState(TypedDict, total=False):
    input: dict[str, Any]
    inspection_case: InspectionCase
    observations: list[Observation]
    severity_assessment: SeverityAssessment
    maintenance_plan: MaintenancePlan
    scheduling_context: SchedulingContext
    repair_schedule: RepairSchedule
    report: InspectionReport
    rendered_report: str


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
):
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
    evidence_agent = EvidenceAgent(
        build_image_analyzer(
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
        ),
        build_video_frame_sampler(
            video_sampler_mode,
            interval_seconds=video_frame_interval_seconds,
            max_frames=video_max_frames,
        ),
    )
    severity_agent = SeverityAgent(
        retriever,
        severity_mode=severity_mode,  # type: ignore[arg-type]
        rationale_generator=severity_rationale_generator,
        llm_max_retries=llm_max_retries,
        llm_failure_mode=llm_failure_mode,  # type: ignore[arg-type]
    )
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
    scheduling_agent = SchedulingAgent(
        repair_windows,
        retriever,
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

    graph = StateGraph(InspectionGraphState)

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

    def evidence_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "observations": evidence_agent.extract_observations(
                state["inspection_case"]
            )
        }

    def severity_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "severity_assessment": severity_agent.assess(
                state["inspection_case"],
                state["observations"],
            )
        }

    def maintenance_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "maintenance_plan": planning_agent.create_plan(
                state["inspection_case"],
                state["observations"],
                state["severity_assessment"],
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
        return {
            "scheduling_context": context_collector.collect(
                state["inspection_case"],
                repair_windows,
            )
        }

    def scheduling_node(state: InspectionGraphState) -> InspectionGraphState:
        return {
            "repair_schedule": scheduling_agent.schedule(
                state["inspection_case"],
                state["severity_assessment"],
                state["maintenance_plan"],
                state["scheduling_context"],
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
        report.annotated_media_paths = artifact_generator.generate(report)
        rendered_report = report_agent.render(report)
        report.rendered_report = rendered_report
        return {
            "report": report,
            "rendered_report": rendered_report,
        }

    graph.add_node("intake", intake_node)
    graph.add_node("evidence", evidence_node)
    graph.add_node("severity", severity_node)
    graph.add_node("maintenance_planning", maintenance_node)
    graph.add_node("monitoring_plan", monitoring_node)
    graph.add_node("schedule_context", schedule_context_node)
    graph.add_node("scheduling", scheduling_node)
    graph.add_node("report", report_node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "evidence")
    graph.add_edge("evidence", "severity")
    graph.add_conditional_edges(
        "severity",
        lambda state: (
            "repair_required"
            if state["severity_assessment"].repair_required
            else "monitor_only"
        ),
        {
            "repair_required": "maintenance_planning",
            "monitor_only": "monitoring_plan",
        },
    )
    graph.add_edge("maintenance_planning", "schedule_context")
    graph.add_edge("monitoring_plan", "report")
    graph.add_edge("schedule_context", "scheduling")
    graph.add_edge("scheduling", "report")
    graph.add_edge("report", END)

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
    )
    result = graph.invoke({"input": input_values})
    return result["report"]
