from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

from agents.helpers.image_analyzer import (
    HeuristicImageAnalyzer,
    ImageFinding,
    MetadataImageAnalyzer,
    OpenAIImageAnalyzer,
    RoboflowImageAnalyzer,
    VerifiedImageAnalyzer,
    build_image_analyzer,
)
from agents.helpers.maintenance_plan_generator import (
    LLMPlanningError,
    LLM_FAILURE_NOTE,
    LLMMaintenancePlanGenerator,
)
from agents.helpers.report_generator import (
    LLMReportError,
    LLM_REPORT_FAILURE_NOTE,
    LLMReportGenerator,
)
from agents.helpers.schedule_context_collector import (
    OpenWeatherContextTool,
    MockCityEventContextTool,
    MockScheduleContextCollector,
    MockTrafficContextTool,
    MockWeatherContextTool,
    TicketmasterEventContextTool,
    TomTomTrafficContextTool,
    build_schedule_context_collector,
)
from agents.helpers.schedule_generator import (
    LLM_SCHEDULING_FAILURE_NOTE,
    LLMScheduleGenerator,
    LLMSchedulingError,
)
from agents.helpers.severity_rationale_generator import (
    LLMSeverityRationaleError,
    LLM_SEVERITY_FAILURE_NOTE,
    LLMSeverityRationaleGenerator,
)
from agents.helpers.video_sampler import OpenCVVideoFrameSampler
from agents.maintenance_planning_agent import MaintenancePlanningAgent
from agents.scheduling_agent import SchedulingAgent
from agents.severity_agent import SeverityAgent
from main import build_parser, run_pipeline
from models import (
    Asset,
    Citation,
    Evidence,
    EventContext,
    InspectionCase,
    MaintenancePlan,
    Observation,
    SchedulingContext,
    SeverityAssessment,
    TrafficContext,
    WeatherContext,
)
from workflows.inspection_graph import _roll_repair_windows_forward, run_inspection_graph


def _parse_args(args: list[str]):
    if "--embedding-backend" not in args:
        args = [*args, "--embedding-backend", "fake"]
    if "--scheduling-mode" not in args:
        args = [*args, "--scheduling-mode", "deterministic"]
    return build_parser().parse_args(args)


def _run_test_graph(input_values, **kwargs):
    kwargs.setdefault("embedding_backend", "fake")
    kwargs.setdefault("scheduling_mode", "deterministic")
    return run_inspection_graph(input_values, **kwargs)


def test_heuristic_image_analyzer_is_default() -> None:
    args = build_parser().parse_args([])

    assert args.image_analyzer == "heuristic"
    assert args.video_sampler == "mock"
    assert args.image_annotations == "data/bridge_image/annotations.csv"
    assert args.image_prompt_profile is None
    assert args.image_detail is None
    assert args.image_tiling == "none"
    assert args.roboflow_confidence_threshold == 0.25
    assert args.roboflow_backend is None
    assert args.roboflow_class_mapping_profile is None
    assert args.roboflow_tiling == "none"
    assert args.roboflow_class_thresholds is None
    assert args.roboflow_inference_confidence is None
    assert args.roboflow_inference_iou_threshold is None
    assert args.vision_verifier == "none"
    assert args.verification_confidence_threshold == 0.55
    assert args.verifier_prompt_profile is None
    assert args.video_frame_interval == 5.0
    assert args.video_max_frames == 3
    assert isinstance(build_image_analyzer(args.image_analyzer), HeuristicImageAnalyzer)
    assert args.rag_backend == "chroma"
    assert args.embedding_backend == "openai"
    assert args.embedding_model is None
    assert args.chroma_persist_dir == "artifacts/chroma"
    assert args.rebuild_rag_index is False
    assert args.knowledge_corpus == "merged"
    assert args.severity_mode == "deterministic"
    assert args.planning_mode == "deterministic"
    assert args.scheduling_mode == "llm"
    assert args.schedule_context_mode == "mock"
    assert args.event_provider == "mock"
    assert args.latitude is None
    assert args.longitude is None
    assert args.report_mode == "deterministic"
    assert args.llm_max_retries == 4
    assert args.llm_failure_mode == "fallback"


def test_workflow_trace_is_written(tmp_path) -> None:
    report = _run_test_graph(
        {
            "asset_id": "TRACE-001",
            "asset_type": "bridge",
            "asset_name": "Trace Bridge",
            "location": "Trace corridor",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "video_paths": [],
            "reason": "trace_test",
        },
        trace_output_dir=str(tmp_path),
    )

    assert report.workflow_trace_id
    assert report.workflow_trace_path
    trace_path = Path(report.workflow_trace_path)
    assert trace_path.exists()

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["case_id"] == "CASE-TRACE-001"
    assert trace["severity"] == report.severity.severity
    assert trace["repair_required"] is True
    assert [event["node"] for event in trace["events"]] == [
        "intake",
        "evidence",
        "severity",
        "maintenance_planning",
        "schedule_context",
        "scheduling",
        "report",
    ]
    assert all(event["status"] == "ok" for event in trace["events"])


def test_metadata_image_analyzer_options_parse() -> None:
    args = _parse_args(
        [
            "--image-analyzer",
            "metadata",
            "--image-annotations",
            "data/bridge_image/annotations.csv",
        ]
    )

    analyzer = build_image_analyzer(
        args.image_analyzer,
        annotations_path=args.image_annotations,
    )

    assert args.image_analyzer == "metadata"
    assert isinstance(analyzer, MetadataImageAnalyzer)


def test_openai_image_prompt_profile_options_parse() -> None:
    args = _parse_args(
        [
            "--image-analyzer",
            "openai",
            "--image-prompt-profile",
            "bridge_defect_v1",
            "--image-detail",
            "high",
            "--image-tiling",
            "grid-2x2",
            "--roboflow-class-thresholds",
            "spalling=0.1,corrosion=0.75",
            "--roboflow-inference-confidence",
            "0.1",
            "--roboflow-inference-iou-threshold",
            "0.4",
        ]
    )

    assert args.image_analyzer == "openai"
    assert args.image_prompt_profile == "bridge_defect_v1"
    assert args.image_detail == "high"
    assert args.image_tiling == "grid-2x2"


def test_roboflow_image_analyzer_options_parse() -> None:
    args = _parse_args(
        [
            "--image-analyzer",
            "roboflow",
            "--roboflow-confidence-threshold",
            "0.55",
            "--roboflow-backend",
            "inference",
            "--roboflow-class-mapping-profile",
            "bridge_dataset",
            "--roboflow-tiling",
            "grid-2x2",
            "--roboflow-class-thresholds",
            "spalling=0.1,corrosion=0.75",
            "--roboflow-inference-confidence",
            "0.1",
            "--roboflow-inference-iou-threshold",
            "0.4",
        ]
    )

    analyzer = build_image_analyzer(
        args.image_analyzer,
        roboflow_confidence_threshold=args.roboflow_confidence_threshold,
        roboflow_backend=args.roboflow_backend,
        roboflow_class_mapping_profile=args.roboflow_class_mapping_profile,
        roboflow_tiling=args.roboflow_tiling,
        roboflow_class_thresholds=args.roboflow_class_thresholds,
        roboflow_inference_confidence=args.roboflow_inference_confidence,
        roboflow_inference_iou_threshold=args.roboflow_inference_iou_threshold,
    )

    assert args.image_analyzer == "roboflow"
    assert args.roboflow_confidence_threshold == 0.55
    assert args.roboflow_backend == "inference"
    assert args.roboflow_class_mapping_profile == "bridge_dataset"
    assert args.roboflow_tiling == "grid-2x2"
    assert args.roboflow_class_thresholds == "spalling=0.1,corrosion=0.75"
    assert args.roboflow_inference_confidence == 0.1
    assert args.roboflow_inference_iou_threshold == 0.4
    assert isinstance(analyzer, RoboflowImageAnalyzer)
    assert analyzer.backend == "inference"
    assert analyzer.class_mapping_profile == "bridge_dataset"
    assert analyzer.tiling == "grid-2x2"
    assert analyzer.class_confidence_thresholds == {
        "corrosion": 0.75,
        "spalling": 0.1,
    }
    assert analyzer.inference_confidence == 0.1
    assert analyzer.inference_iou_threshold == 0.4


def test_vision_verifier_options_parse() -> None:
    args = _parse_args(
        [
            "--vision-verifier",
            "openai",
            "--verification-confidence-threshold",
            "0.7",
            "--verifier-prompt-profile",
            "bridge_defect_v2_strict",
        ]
    )

    assert args.vision_verifier == "openai"
    assert args.verification_confidence_threshold == 0.7
    assert args.verifier_prompt_profile == "bridge_defect_v2_strict"


def test_opencv_video_sampler_options_parse() -> None:
    args = _parse_args(
        [
            "--video-sampler",
            "opencv",
            "--video-frame-interval",
            "1.5",
            "--video-max-frames",
            "4",
        ]
    )

    assert args.video_sampler == "opencv"
    assert args.video_frame_interval == 1.5
    assert args.video_max_frames == 4


def test_llm_planning_options_parse() -> None:
    args = _parse_args(
        [
            "--planning-mode",
            "llm",
            "--llm-max-retries",
            "2",
            "--llm-failure-mode",
            "fail",
        ]
    )

    assert args.planning_mode == "llm"
    assert args.llm_max_retries == 2
    assert args.llm_failure_mode == "fail"


def test_scheduling_mode_options_parse() -> None:
    args = _parse_args(["--scheduling-mode", "deterministic"])

    assert args.scheduling_mode == "deterministic"


def test_live_schedule_context_options_parse() -> None:
    args = _parse_args(
        [
            "--schedule-context-mode",
            "live",
            "--event-provider",
            "ticketmaster",
            "--latitude",
            "40.75",
            "--longitude",
            "-73.99",
        ]
    )

    assert args.schedule_context_mode == "live"
    assert args.event_provider == "ticketmaster"
    assert args.latitude == 40.75
    assert args.longitude == -73.99


def test_live_repair_windows_roll_forward_when_fixture_is_stale() -> None:
    windows = [
        {
            "start": "2026-06-18T22:00:00",
            "end": "2026-06-19T06:00:00",
            "crew": "night maintenance crew",
            "disruption_score": 2,
        },
        {
            "start": "2026-06-20T23:00:00",
            "end": "2026-06-21T07:00:00",
            "crew": "weekend night crew",
            "disruption_score": 1,
        },
    ]

    rolled = _roll_repair_windows_forward(
        windows,
        now=datetime.fromisoformat("2026-06-24T12:00:00"),
    )

    assert rolled[0]["start"] == "2026-06-25T22:00:00"
    assert rolled[0]["end"] == "2026-06-26T06:00:00"
    assert rolled[1]["start"] == "2026-06-27T23:00:00"
    assert rolled[1]["end"] == "2026-06-28T07:00:00"
    assert rolled[1]["crew"] == "weekend night crew"


def test_llm_severity_options_parse() -> None:
    args = _parse_args(["--severity-mode", "llm"])

    assert args.severity_mode == "llm"


def test_llm_report_options_parse() -> None:
    args = _parse_args(["--report-mode", "llm"])

    assert args.report_mode == "llm"


def test_none_severity_label_prevents_negated_defect_escalation() -> None:
    class FakeRetriever:
        def search(self, *args, **kwargs):
            return []

        def get_document(self, document_id):
            return None

    inspection_case = InspectionCase(
        case_id="CASE-NONE-001",
        asset=Asset(
            asset_id="BR-NONE",
            asset_type="bridge",
            name="No Defect Bridge",
            location="Test span",
            criticality="high",
        ),
        reason="vision_regression",
        evidence=[
            Evidence(
                source_id="EV-001",
                source_type="inspection_image",
                content="No visible defects detected.",
                modality="image",
                file_path="bridge.jpg",
            )
        ],
    )
    observations = [
        Observation(
            observation_id="OBS-001",
            source_id="EV-001",
            source_modality="image",
            defect_type="unknown",
            description=(
                "No visible defects detected. No clear cracks, spalling, "
                "exposed rebar, corrosion, or leaks."
            ),
            location_on_asset="visible bridge surface",
            measurement={"severity_label": "none"},
            confidence=0.95,
        )
    ]

    assessment = SeverityAgent(FakeRetriever()).assess(inspection_case, observations)

    assert assessment.severity == "none"
    assert assessment.repair_required is False


def test_image_observation_records_box_area_measurements(tmp_path) -> None:
    from PIL import Image

    image_path = tmp_path / "bridge_spalling.jpg"
    Image.new("RGB", (100, 50), color="white").save(image_path)

    class BoxAnalyzer:
        def analyze(self, image_path, asset_type):
            from agents.helpers.image_analyzer import ImageFinding

            return [
                ImageFinding(
                    defect_type="spalling",
                    description="Detector found concrete spalling.",
                    location_on_asset="girder face",
                    confidence=0.8,
                    bounding_box=(10, 5, 20, 10),
                    severity_label="high",
                )
            ]

    report = _run_test_graph(
        {
            "asset_id": "A-BOX",
            "asset_type": "bridge",
            "asset_name": "Box Metadata Bridge",
            "location": "North span",
            "criticality": "medium",
            "notes": "Image submitted for review.",
            "image_paths": [str(image_path)],
            "reason": "routine",
        },
        image_analyzer_mode="heuristic",
    )

    # Use the public EvidenceAgent behavior directly with the fake analyzer to keep
    # this test focused on measurement extraction.
    from agents.evidence_agent import EvidenceAgent

    observations = EvidenceAgent(image_analyzer=BoxAnalyzer()).extract_observations(
        report.case
    )

    assert observations[0].measurement["bbox_area"] == 200
    assert observations[0].measurement["image_width"] == 100
    assert observations[0].measurement["image_height"] == 50
    assert observations[0].measurement["bbox_relative_area"] == 0.04
    assert observations[0].measurement["severity_label_source"] == "BoxAnalyzer"


def test_roboflow_default_severity_is_calibrated_from_box_size() -> None:
    class FakeRetriever:
        def search(self, *args, **kwargs):
            return []

        def get_document(self, document_id):
            return None

    inspection_case = InspectionCase(
        case_id="CASE-CAL-001",
        asset=Asset(
            asset_id="BR-CAL",
            asset_type="bridge",
            name="Calibrated Bridge",
            location="Test span",
            criticality="medium",
        ),
        reason="detector_regression",
        evidence=[
            Evidence(
                source_id="EV-001",
                source_type="inspection_image",
                content="Detector found a small spalling region.",
                modality="image",
                file_path="bridge.jpg",
            )
        ],
    )
    observations = [
        Observation(
            observation_id="OBS-001",
            source_id="EV-001",
            source_modality="image",
            defect_type="spalling",
            description="Roboflow model detected low-confidence spalling.",
            location_on_asset="girder face",
            measurement={
                "severity_label": "high",
                "severity_label_source": "RoboflowImageAnalyzer",
                "bbox_relative_area": 0.01,
            },
            confidence=0.35,
        )
    ]

    assessment = SeverityAgent(FakeRetriever()).assess(inspection_case, observations)

    assert assessment.severity == "moderate"
    assert assessment.urgency == "scheduled"
    assert assessment.repair_required is True


def test_roboflow_crack_stays_moderate_despite_high_confidence() -> None:
    class FakeRetriever:
        def search(self, *args, **kwargs):
            return []

        def get_document(self, document_id):
            return None

    inspection_case = InspectionCase(
        case_id="CASE-CRACK-CAL",
        asset=Asset(
            asset_id="BR-CRACK-CAL",
            asset_type="bridge",
            name="Crack Calibration Bridge",
            location="Test span",
            criticality="medium",
        ),
        reason="detector_regression",
        evidence=[],
    )
    observations = [
        Observation(
            observation_id="OBS-001",
            source_id="EV-001",
            source_modality="image",
            defect_type="crack",
            description="Roboflow model detected crack.",
            location_on_asset="deck",
            measurement={
                "severity_label": "moderate",
                "severity_label_source": "RoboflowImageAnalyzer",
                "bbox_relative_area": 0.18,
            },
            confidence=0.85,
        )
    ]

    assessment = SeverityAgent(FakeRetriever()).assess(inspection_case, observations)

    assert assessment.severity == "moderate"


def test_roboflow_low_confidence_extra_rebar_does_not_escalate_corrosion() -> None:
    class FakeRetriever:
        def search(self, *args, **kwargs):
            return []

        def get_document(self, document_id):
            return None

    inspection_case = InspectionCase(
        case_id="CASE-CORR-CAL",
        asset=Asset(
            asset_id="BR-CORR-CAL",
            asset_type="bridge",
            name="Corrosion Calibration Bridge",
            location="Test span",
            criticality="medium",
        ),
        reason="detector_regression",
        evidence=[],
    )
    observations = [
        Observation(
            observation_id="OBS-001",
            source_id="EV-001",
            source_modality="image",
            defect_type="corrosion",
            description="Roboflow model detected corrosion.",
            location_on_asset="girder",
            measurement={"severity_label_source": "RoboflowImageAnalyzer"},
            confidence=0.67,
        ),
        Observation(
            observation_id="OBS-002",
            source_id="EV-001",
            source_modality="image",
            defect_type="exposed_rebar",
            description="Low-confidence extra exposed rebar detection.",
            location_on_asset="girder",
            measurement={
                "severity_label": "high",
                "severity_label_source": "RoboflowImageAnalyzer",
                "bbox_relative_area": 0.03,
            },
            confidence=0.47,
        ),
        Observation(
            observation_id="OBS-003",
            source_id="EV-001",
            source_modality="image",
            defect_type="spalling",
            description="Low-confidence extra spalling detection.",
            location_on_asset="girder",
            measurement={
                "severity_label": "high",
                "severity_label_source": "RoboflowImageAnalyzer",
                "bbox_relative_area": 0.02,
            },
            confidence=0.39,
        ),
    ]

    assessment = SeverityAgent(FakeRetriever()).assess(inspection_case, observations)

    assert assessment.severity == "moderate"


def test_roboflow_low_confidence_rebar_can_drive_high_severity() -> None:
    class FakeRetriever:
        def search(self, *args, **kwargs):
            return []

        def get_document(self, document_id):
            return None

    inspection_case = InspectionCase(
        case_id="CASE-REBAR-CAL",
        asset=Asset(
            asset_id="BR-REBAR-CAL",
            asset_type="bridge",
            name="Rebar Calibration Bridge",
            location="Test span",
            criticality="medium",
        ),
        reason="detector_regression",
        evidence=[],
    )
    observations = [
        Observation(
            observation_id="OBS-001",
            source_id="EV-001",
            source_modality="image",
            defect_type="corrosion",
            description="Roboflow model detected corrosion near exposed rebar.",
            location_on_asset="girder",
            measurement={"severity_label_source": "RoboflowImageAnalyzer"},
            confidence=0.64,
        ),
        Observation(
            observation_id="OBS-002",
            source_id="EV-001",
            source_modality="image",
            defect_type="exposed_rebar",
            description="Roboflow model detected exposed rebar.",
            location_on_asset="girder",
            measurement={
                "severity_label": "high",
                "severity_label_source": "RoboflowImageAnalyzer",
                "bbox_relative_area": 0.03,
            },
            confidence=0.26,
        ),
    ]

    assessment = SeverityAgent(FakeRetriever()).assess(inspection_case, observations)

    assert assessment.severity == "high"


def test_roboflow_spalling_can_be_high_at_moderate_confidence() -> None:
    class FakeRetriever:
        def search(self, *args, **kwargs):
            return []

        def get_document(self, document_id):
            return None

    inspection_case = InspectionCase(
        case_id="CASE-SPALL-CAL",
        asset=Asset(
            asset_id="BR-SPALL-CAL",
            asset_type="bridge",
            name="Spalling Calibration Bridge",
            location="Test span",
            criticality="medium",
        ),
        reason="detector_regression",
        evidence=[],
    )
    observations = [
        Observation(
            observation_id="OBS-001",
            source_id="EV-001",
            source_modality="image",
            defect_type="spalling",
            description="Roboflow model detected spalling.",
            location_on_asset="deck edge",
            measurement={
                "severity_label": "high",
                "severity_label_source": "RoboflowImageAnalyzer",
                "bbox_relative_area": 0.01,
            },
            confidence=0.46,
        )
    ]

    assessment = SeverityAgent(FakeRetriever()).assess(inspection_case, observations)

    assert assessment.severity == "high"


def test_default_pipeline_uses_historical_repair_precedent() -> None:
    args = _parse_args([])

    report = run_pipeline(args)

    assert report.severity.repair_required is True
    assert report.severity.severity == "high"
    _assert_bridge_spalling_precedent(report)
    assert report.maintenance_plan.recommended_action == "partial-depth concrete patch"
    assert report.rendered_report is not None


def test_pipeline_can_use_local_retriever_fallback() -> None:
    args = _parse_args(["--rag-backend", "local"])

    report = run_pipeline(args)

    assert report.severity.repair_required is True
    _assert_bridge_spalling_precedent(report)


def test_road_crack_retrieves_road_crack_repair_history() -> None:
    args = _parse_args(
        [
            "--asset-type",
            "road",
            "--asset-name",
            "Arterial Segment 7",
            "--criticality",
            "medium",
            "--notes",
            "Longitudinal crack with water intrusion along the travel lane.",
        ]
    )

    report = run_pipeline(args)

    assert report.severity.repair_required is True
    assert (
        report.maintenance_plan.historical_precedents[0].document_id
        == "HIST-ROAD-014"
    )
    assert (
        report.maintenance_plan.recommended_action
        == "epoxy injection and surface sealing"
    )


def test_maintenance_plan_uses_repair_record_resources_and_risks() -> None:
    class FakeRetriever:
        document = {
            "document_id": "HIST-BRIDGE-999",
            "title": "Bridge Spalling Repair",
            "source_type": "repair_record",
            "asset_type": "bridge",
            "defect_type": "spalling",
            "repair_method": "partial-depth concrete patch",
            "repair_outcome": "successful with monitoring",
            "actual_duration_hours": 14,
            "planned_duration_hours": 10,
            "materials_used": "patching concrete; corrosion inhibitor; bonding agent",
            "equipment_used": "saw cutter; chipping hammer; traffic barriers",
            "permit_required": "yes",
            "closure_type": "short full closure",
            "recurrence_within_12_months": "true",
            "disruption": "medium disruption, short full closure",
        }

        def search(self, *args, **kwargs):
            return [
                Citation(
                    document_id=self.document["document_id"],
                    title=self.document["title"],
                    source_type="repair_record",
                    excerpt="Comparable bridge spalling repair record.",
                    score=0.95,
                )
            ]

        def get_document(self, document_id):
            if document_id == self.document["document_id"]:
                return self.document
            return None

    inspection_case = InspectionCase(
        case_id="CASE-PLAN-001",
        asset=Asset(
            asset_id="BR-PLAN",
            asset_type="bridge",
            name="Planning Bridge",
            location="North span",
            criticality="high",
        ),
        reason="planning_regression",
        evidence=[
            Evidence(
                source_id="EV-001",
                source_type="inspection_image",
                content="Spalling detected on bridge girder.",
                modality="image",
            )
        ],
    )
    observations = [
        Observation(
            observation_id="OBS-001",
            source_id="EV-001",
            source_modality="image",
            defect_type="spalling",
            description="Concrete spalling with rough exposed substrate.",
            location_on_asset="girder face",
            confidence=0.8,
        )
    ]
    severity = SeverityAssessment(
        severity="high",
        repair_required=True,
        urgency="priority",
        rationale="Repair recommended.",
        confidence=0.8,
    )

    plan = MaintenancePlanningAgent(FakeRetriever()).create_plan(
        inspection_case,
        observations,
        severity,
    )

    assert plan.recommended_action == "partial-depth concrete patch"
    assert plan.materials == [
        "patching concrete",
        "corrosion inhibitor",
        "bonding agent",
    ]
    assert "saw cutter" in plan.equipment
    assert "closure coordination approval" in plan.permits
    assert plan.estimated_duration_hours == 14
    assert any("recurrence" in risk for risk in plan.risks)
    assert any("duration overrun" in risk for risk in plan.risks)


def test_image_input_creates_media_observation_and_repair_plan() -> None:
    args = _parse_args(
        [
            "--asset-type",
            "bridge",
            "--asset-name",
            "Inspection Image Demo",
            "--notes",
            "Field team uploaded inspection imagery for review.",
            "--image",
            "samples/bridge_spalling_joint.jpg",
        ]
    )

    report = run_pipeline(args)

    image_observations = [
        observation
        for observation in report.observations
        if observation.source_modality == "image"
    ]
    assert image_observations
    assert image_observations[0].defect_type == "spalling"
    assert image_observations[0].media_reference is not None
    assert (
        image_observations[0].media_reference.file_path
        == "samples/bridge_spalling_joint.jpg"
    )
    assert report.severity.repair_required is True
    _assert_bridge_spalling_precedent(report)
    assert report.schedule.context_summary


def test_video_input_creates_frame_observations_and_repair_plan() -> None:
    args = _parse_args(
        [
            "--asset-type",
            "bridge",
            "--asset-name",
            "Inspection Video Demo",
            "--notes",
            "Field team uploaded inspection video for review.",
            "--video",
            "samples/bridge_spalling_walkthrough.mp4",
        ]
    )

    report = run_pipeline(args)

    video_observations = [
        observation
        for observation in report.observations
        if observation.source_modality == "video_frame"
    ]
    assert len(video_observations) == 3
    assert video_observations[0].defect_type == "spalling"
    assert video_observations[0].media_reference is not None
    assert (
        video_observations[0].media_reference.file_path
        == "samples/bridge_spalling_walkthrough.mp4"
    )
    assert video_observations[1].media_reference is not None
    assert video_observations[1].media_reference.frame_timestamp_seconds == 5.0
    assert report.severity.repair_required is True
    _assert_bridge_spalling_precedent(report)


def test_opencv_video_sampler_extracts_timestamped_frames(tmp_path) -> None:
    video_path = _create_tiny_video(tmp_path / "bridge_spalling_test.avi")
    output_dir = tmp_path / "frames"

    samples = OpenCVVideoFrameSampler(
        output_dir=str(output_dir),
        interval_seconds=1,
        max_frames=2,
    ).sample(str(video_path))

    assert len(samples) == 2
    assert samples[0].timestamp_seconds == 0.0
    assert samples[1].timestamp_seconds == 1.0
    assert Path(samples[0].image_path).exists()
    assert Path(samples[1].image_path).exists()
    assert Path(samples[0].image_path).name == "bridge_spalling_test_frame_000_00000000.jpg"
    assert Path(samples[1].image_path).name == "bridge_spalling_test_frame_001_00001000.jpg"


def test_opencv_video_pipeline_creates_frame_observations(tmp_path) -> None:
    video_path = _create_tiny_video(tmp_path / "bridge_spalling_walkthrough.avi")
    args = _parse_args(
        [
            "--asset-type",
            "bridge",
            "--asset-name",
            "OpenCV Video Demo",
            "--notes",
            "Field team uploaded inspection video for OpenCV sampling.",
            "--video",
            str(video_path),
            "--video-sampler",
            "opencv",
            "--video-frame-interval",
            "1",
            "--video-max-frames",
            "2",
        ]
    )

    report = run_pipeline(args)

    video_observations = [
        observation
        for observation in report.observations
        if observation.source_modality == "video_frame"
    ]
    assert len(video_observations) == 2
    assert video_observations[0].defect_type == "spalling"
    assert video_observations[0].media_reference is not None
    assert video_observations[0].media_reference.file_path == str(video_path)
    assert video_observations[1].media_reference is not None
    assert video_observations[1].media_reference.frame_timestamp_seconds == 1.0
    assert report.severity.repair_required is True
    _assert_bridge_spalling_precedent(report)


def test_langgraph_workflow_runs_full_inspection() -> None:
    report = _run_test_graph(
        {
            "asset_id": "A-200",
            "asset_type": "bridge",
            "asset_name": "Graph Demo Bridge",
            "location": "South approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        }
    )

    assert report.case.case_id == "CASE-A-200"
    assert report.observations[0].defect_type == "spalling"
    assert report.severity.repair_required is True
    assert report.maintenance_plan.recommended_action == "partial-depth concrete patch"
    assert report.maintenance_plan.historical_precedents
    assert report.schedule.context_summary


def test_llm_severity_mode_uses_mocked_rationale() -> None:
    generator = LLMSeverityRationaleGenerator(
        runnable=FakePlanningRunnable([_llm_severity_payload()]),
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-207",
            "asset_type": "bridge",
            "asset_name": "LLM Severity Bridge",
            "location": "East span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        severity_mode="llm",
        severity_rationale_generator=generator,
    )

    assert report.severity.severity == "high"
    assert report.severity.repair_required is True
    assert "LLM-cited severity rationale" in report.severity.rationale
    assert "Missing evidence:" in report.severity.rationale


def test_llm_severity_retries_after_invalid_output() -> None:
    runnable = FakePlanningRunnable(
        [
            {"rationale": ""},
            _llm_severity_payload("Retry severity rationale"),
        ]
    )
    generator = LLMSeverityRationaleGenerator(
        runnable=runnable,
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-208",
            "asset_type": "bridge",
            "asset_name": "Retry Severity Bridge",
            "location": "East span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        severity_mode="llm",
        severity_rationale_generator=generator,
    )

    assert runnable.calls == 2
    assert "Retry severity rationale" in report.severity.rationale


def test_llm_severity_fallback_after_retry_exhaustion() -> None:
    generator = LLMSeverityRationaleGenerator(
        runnable=FakePlanningRunnable([RuntimeError("severity model unavailable")]),
        max_retries=2,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-209",
            "asset_type": "bridge",
            "asset_name": "Fallback Severity Bridge",
            "location": "East span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        severity_mode="llm",
        severity_rationale_generator=generator,
    )

    assert report.severity.repair_required is True
    assert LLM_SEVERITY_FAILURE_NOTE in report.severity.rationale


def test_llm_severity_fail_mode_raises_after_retry_exhaustion() -> None:
    generator = LLMSeverityRationaleGenerator(
        runnable=FakePlanningRunnable([RuntimeError("severity model unavailable")]),
        max_retries=2,
        failure_mode="fail",
    )

    with pytest.raises(LLMSeverityRationaleError, match="failed after 2 attempts"):
        _run_test_graph(
            {
                "asset_id": "A-210",
                "asset_type": "bridge",
                "asset_name": "Fail Severity Bridge",
                "location": "East span",
                "criticality": "high",
                "notes": "Inspection found spalling with loose concrete.",
                "image_paths": [],
                "reason": "routine",
            },
            severity_mode="llm",
            severity_rationale_generator=generator,
        )


def test_llm_severity_keeps_scheduling_deterministic() -> None:
    generator = LLMSeverityRationaleGenerator(
        runnable=FakePlanningRunnable([_llm_severity_payload()]),
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-211",
            "asset_type": "bridge",
            "asset_name": "Schedule Severity Bridge",
            "location": "East span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        severity_mode="llm",
        severity_rationale_generator=generator,
    )

    assert report.severity.severity == "high"
    assert report.schedule is not None
    assert report.schedule.recommended_window.start.isoformat() == "2026-06-18T22:00:00"


def test_llm_planning_mode_uses_mocked_structured_plan() -> None:
    generator = LLMMaintenancePlanGenerator(
        runnable=FakePlanningRunnable([_llm_plan_payload()]),
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-202",
            "asset_type": "bridge",
            "asset_name": "LLM Planning Bridge",
            "location": "West span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        planning_mode="llm",
        planning_generator=generator,
    )

    assert report.maintenance_plan.recommended_action == "LLM-guided patch plan"
    assert report.maintenance_plan.tasks[0].name == "Confirm repair limits"
    assert report.maintenance_plan.materials == ["rapid-set patching concrete"]
    _assert_bridge_spalling_precedent(report)


def test_llm_planning_retries_after_invalid_output() -> None:
    runnable = FakePlanningRunnable(
        [
            {"recommended_action": ""},
            _llm_plan_payload(recommended_action="Retry success plan"),
        ]
    )
    generator = LLMMaintenancePlanGenerator(
        runnable=runnable,
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-203",
            "asset_type": "bridge",
            "asset_name": "Retry Bridge",
            "location": "West span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        planning_mode="llm",
        planning_generator=generator,
    )

    assert runnable.calls == 2
    assert report.maintenance_plan.recommended_action == "Retry success plan"


def test_llm_planning_fallback_after_retry_exhaustion() -> None:
    generator = LLMMaintenancePlanGenerator(
        runnable=FakePlanningRunnable([RuntimeError("planner unavailable")]),
        max_retries=2,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-204",
            "asset_type": "bridge",
            "asset_name": "Fallback Bridge",
            "location": "West span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        planning_mode="llm",
        planning_generator=generator,
    )

    assert report.maintenance_plan.recommended_action == "partial-depth concrete patch"
    assert any(LLM_FAILURE_NOTE in risk for risk in report.maintenance_plan.risks)


def test_llm_planning_fail_mode_raises_after_retry_exhaustion() -> None:
    generator = LLMMaintenancePlanGenerator(
        runnable=FakePlanningRunnable([RuntimeError("planner unavailable")]),
        max_retries=2,
        failure_mode="fail",
    )

    with pytest.raises(LLMPlanningError, match="failed after 2 attempts"):
        _run_test_graph(
            {
                "asset_id": "A-205",
                "asset_type": "bridge",
                "asset_name": "Fail Bridge",
                "location": "West span",
                "criticality": "high",
                "notes": "Inspection found spalling with loose concrete.",
                "image_paths": [],
                "reason": "routine",
            },
            planning_mode="llm",
            planning_generator=generator,
        )


def test_llm_planning_keeps_schedule_selection_deterministic() -> None:
    generator = LLMMaintenancePlanGenerator(
        runnable=FakePlanningRunnable([_llm_plan_payload()]),
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-206",
            "asset_type": "bridge",
            "asset_name": "Schedule Bridge",
            "location": "West span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        planning_mode="llm",
        planning_generator=generator,
    )

    assert report.schedule is not None
    assert report.schedule.recommended_window.start.isoformat() == "2026-06-18T22:00:00"
    _assert_bridge_spalling_precedent(report)


def test_llm_report_mode_uses_mocked_markdown() -> None:
    generator = LLMReportGenerator(
        runnable=FakePlanningRunnable(
            [{"markdown_report": "# Polished Inspection Report\n\nLLM report body."}]
        ),
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-212",
            "asset_type": "bridge",
            "asset_name": "LLM Report Bridge",
            "location": "North span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        report_mode="llm",
        report_generator=generator,
    )

    assert report.rendered_report == "# Polished Inspection Report\n\nLLM report body."
    assert report.severity.repair_required is True
    assert report.maintenance_plan.recommended_action == "partial-depth concrete patch"


def test_llm_report_retries_after_invalid_output() -> None:
    runnable = FakePlanningRunnable(
        [
            {"markdown_report": ""},
            {"markdown_report": "# Retry Report\n\nRecovered."},
        ]
    )
    generator = LLMReportGenerator(
        runnable=runnable,
        max_retries=4,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-213",
            "asset_type": "bridge",
            "asset_name": "Retry Report Bridge",
            "location": "North span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        report_mode="llm",
        report_generator=generator,
    )

    assert runnable.calls == 2
    assert report.rendered_report == "# Retry Report\n\nRecovered."


def test_llm_report_fallback_after_retry_exhaustion() -> None:
    generator = LLMReportGenerator(
        runnable=FakePlanningRunnable([RuntimeError("report model unavailable")]),
        max_retries=2,
        failure_mode="fallback",
    )

    report = _run_test_graph(
        {
            "asset_id": "A-214",
            "asset_type": "bridge",
            "asset_name": "Fallback Report Bridge",
            "location": "North span",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "image_paths": [],
            "reason": "routine",
        },
        report_mode="llm",
        report_generator=generator,
    )

    assert report.rendered_report is not None
    assert "# Infrastructure Inspection Report" in report.rendered_report
    assert LLM_REPORT_FAILURE_NOTE in report.rendered_report


def test_llm_report_fail_mode_raises_after_retry_exhaustion() -> None:
    generator = LLMReportGenerator(
        runnable=FakePlanningRunnable([RuntimeError("report model unavailable")]),
        max_retries=2,
        failure_mode="fail",
    )

    with pytest.raises(LLMReportError, match="failed after 2 attempts"):
        _run_test_graph(
            {
                "asset_id": "A-215",
                "asset_type": "bridge",
                "asset_name": "Fail Report Bridge",
                "location": "North span",
                "criticality": "high",
                "notes": "Inspection found spalling with loose concrete.",
                "image_paths": [],
                "reason": "routine",
            },
            report_mode="llm",
            report_generator=generator,
        )


def test_langgraph_skips_repair_scheduling_when_monitoring_only() -> None:
    report = _run_test_graph(
        {
            "asset_id": "A-201",
            "asset_type": "bridge",
            "asset_name": "Monitoring Demo Bridge",
            "location": "North approach",
            "criticality": "medium",
            "notes": "Routine visual check found no visible distress or access issues.",
            "image_paths": [],
            "reason": "routine",
        }
    )

    assert report.severity.repair_required is False
    assert report.severity.urgency == "monitor"
    assert report.severity.citations == []
    assert report.maintenance_plan.recommended_action == (
        "Continue monitoring and schedule follow-up inspection."
    )
    assert report.maintenance_plan.historical_precedents == []
    assert report.schedule is None


def test_openai_image_analyzer_uses_mocked_client(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class FakeResponse:
        content = (
            '{"findings":[{"defect_type":"crack","description":"Visible crack",'
            '"location_on_asset":"deck edge","confidence":0.81,'
            '"bounding_box":[1,2,3,4]}]}'
        )

    class FakeClient:
        def invoke(self, messages):
            return FakeResponse()

    findings = OpenAIImageAnalyzer(client=FakeClient(), model="test-model").analyze(
        str(image_path),
        "bridge",
    )

    assert findings[0].defect_type == "crack"
    assert findings[0].confidence == 0.81
    assert findings[0].bounding_box == (1, 2, 3, 4)


def test_openai_image_analyzer_parses_severity_label(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class FakeResponse:
        content = (
            '{"findings":[{"defect_type":"spalling","severity_label":"High",'
            '"description":"Broken concrete cover",'
            '"location_on_asset":"girder underside","confidence":0.84}]}'
        )

    class FakeClient:
        def invoke(self, messages):
            return FakeResponse()

    findings = OpenAIImageAnalyzer(client=FakeClient(), model="test-model").analyze(
        str(image_path),
        "bridge",
    )

    assert findings[0].defect_type == "spalling"
    assert findings[0].severity_label == "high"


def test_openai_image_analyzer_parses_text_confidence(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class FakeResponse:
        content = (
            '{"findings":[{"defect_type":"crack","severity_label":"moderate",'
            '"description":"Linear fracture",'
            '"location_on_asset":"deck","confidence":"high"}]}'
        )

    class FakeClient:
        def invoke(self, messages):
            return FakeResponse()

    findings = OpenAIImageAnalyzer(client=FakeClient(), model="test-model").analyze(
        str(image_path),
        "bridge",
    )

    assert findings[0].confidence == 0.8


def test_openai_image_analyzer_uses_bridge_prompt_profile(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class FakeResponse:
        content = '{"findings":[]}'

    class FakeClient:
        def __init__(self):
            self.messages = None

        def invoke(self, messages):
            self.messages = messages
            return FakeResponse()

    fake_client = FakeClient()
    OpenAIImageAnalyzer(
        client=fake_client,
        model="test-model",
        prompt_profile="bridge_defect_v1",
    ).analyze(str(image_path), "bridge")

    prompt = fake_client.messages[0]["content"][0]["text"]
    image_url = fake_client.messages[0]["content"][1]["image_url"]
    assert "bridge defect assessor" in prompt
    assert "severity_label" in prompt
    assert "exposed_rebar" in prompt
    assert image_url["detail"] == "high"


def test_openai_image_analyzer_can_send_grid_crops(tmp_path) -> None:
    from PIL import Image

    image_path = tmp_path / "bridge.jpg"
    Image.new("RGB", (20, 20), color="gray").save(image_path)

    class FakeResponse:
        content = '{"findings":[]}'

    class FakeClient:
        def __init__(self):
            self.messages = None

        def invoke(self, messages):
            self.messages = messages
            return FakeResponse()

    fake_client = FakeClient()
    OpenAIImageAnalyzer(
        client=fake_client,
        model="test-model",
        image_tiling="grid-2x2",
    ).analyze(str(image_path), "bridge")

    content = fake_client.messages[0]["content"]
    image_parts = [part for part in content if part["type"] == "image_url"]
    text = " ".join(part["text"] for part in content if part["type"] == "text")

    assert len(image_parts) == 5
    assert "quadrant crops" in text
    assert "top-left" in text


def test_verified_image_analyzer_adds_openai_spalling_for_ambiguous_crack(
    tmp_path,
) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class BaseAnalyzer:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="crack",
                    description="Detector found a crack-like concrete defect.",
                    location_on_asset="girder underside",
                    confidence=0.62,
                    severity_label="moderate",
                )
            ]

    class Verifier:
        calls = 0

        def analyze(self, image_path, asset_type):
            self.calls += 1
            return [
                ImageFinding(
                    defect_type="spalling",
                    description="Verifier sees missing concrete cover.",
                    location_on_asset="girder underside",
                    confidence=0.76,
                    severity_label="high",
                )
            ]

    verifier = Verifier()
    findings = VerifiedImageAnalyzer(BaseAnalyzer(), verifier).analyze(
        str(image_path),
        "bridge",
    )

    assert verifier.calls == 1
    assert findings[0].defect_type == "spalling"
    assert findings[0].severity_label == "high"
    assert all(finding.defect_type != "crack" for finding in findings)


def test_verified_image_analyzer_upgrades_concrete_loss_spalling_to_high(
    tmp_path,
) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class BaseAnalyzer:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="unknown",
                    description="Detector found no confident defect.",
                    location_on_asset="visible area",
                    confidence=0.3,
                )
            ]

    class Verifier:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="spalling",
                    description="Concrete cover is missing with broken concrete edges.",
                    location_on_asset="girder",
                    confidence=0.85,
                    severity_label="moderate",
                )
            ]

    findings = VerifiedImageAnalyzer(BaseAnalyzer(), Verifier()).analyze(
        str(image_path),
        "bridge",
    )

    assert findings[0].defect_type == "spalling"
    assert findings[0].severity_label == "high"


def test_verified_image_analyzer_keeps_base_when_verifier_is_uncertain(
    tmp_path,
) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class BaseAnalyzer:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="crack",
                    description="Detector found a crack.",
                    location_on_asset="deck",
                    confidence=0.61,
                )
            ]

    class Verifier:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="spalling",
                    description="Verifier is unsure.",
                    location_on_asset="deck",
                    confidence=0.4,
                )
            ]

    findings = VerifiedImageAnalyzer(BaseAnalyzer(), Verifier()).analyze(
        str(image_path),
        "bridge",
    )

    assert [finding.defect_type for finding in findings] == ["crack"]


def test_verified_image_analyzer_rejects_spalling_without_concrete_loss_evidence(
    tmp_path,
) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class BaseAnalyzer:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="crack",
                    description="Detector found a crack-like mark.",
                    location_on_asset="deck",
                    confidence=0.62,
                )
            ]

    class Verifier:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="spalling",
                    description="Surface texture and discoloration near a line.",
                    location_on_asset="deck",
                    confidence=0.9,
                    severity_label="high",
                )
            ]

    findings = VerifiedImageAnalyzer(BaseAnalyzer(), Verifier()).analyze(
        str(image_path),
        "bridge",
    )

    assert [finding.defect_type for finding in findings] == ["crack"]


def test_verified_image_analyzer_skips_clear_detector_result(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class BaseAnalyzer:
        def analyze(self, image_path, asset_type):
            return [
                ImageFinding(
                    defect_type="corrosion",
                    description="Detector found corrosion.",
                    location_on_asset="beam",
                    confidence=0.88,
                )
            ]

    class Verifier:
        calls = 0

        def analyze(self, image_path, asset_type):
            self.calls += 1
            return []

    verifier = Verifier()
    findings = VerifiedImageAnalyzer(BaseAnalyzer(), verifier).analyze(
        str(image_path),
        "bridge",
    )

    assert verifier.calls == 0
    assert [finding.defect_type for finding in findings] == ["corrosion"]


def test_roboflow_image_analyzer_maps_predictions_to_findings(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    def fake_client(image_path):
        return {
            "predictions": [
                {
                    "class": "exposed_rebar_high",
                    "confidence": 0.91,
                    "x": 100,
                    "y": 80,
                    "width": 40,
                    "height": 20,
                },
                {
                    "class": "stain",
                    "confidence": 0.8,
                    "bounding_box": [1, 2, 3, 4],
                },
                {
                    "class": "Efflorescence",
                    "confidence": 0.77,
                    "bounding_box": [4, 5, 6, 7],
                },
                {
                    "class": "crack",
                    "confidence": 0.2,
                    "x": 10,
                    "y": 10,
                    "width": 5,
                    "height": 5,
                },
            ]
        }

    findings = RoboflowImageAnalyzer(
        client=fake_client,
        confidence_threshold=0.5,
    ).analyze(str(image_path), "bridge")

    assert len(findings) == 3
    assert findings[0].defect_type == "exposed_rebar"
    assert findings[0].severity_label == "high"
    assert findings[0].confidence == 0.91
    assert findings[0].bounding_box == (80, 70, 40, 20)
    assert findings[1].defect_type == "corrosion"
    assert findings[1].severity_label == "moderate"
    assert findings[1].bounding_box == (1, 2, 3, 4)
    assert findings[2].defect_type == "leak"
    assert findings[2].severity_label == "moderate"
    assert findings[2].bounding_box == (4, 5, 6, 7)


def test_roboflow_image_analyzer_supports_bridge_dataset_mapping_profile(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    findings = RoboflowImageAnalyzer(
        client=lambda image_path: {
            "predictions": [
                {
                    "class": "Efflorescence",
                    "confidence": 0.77,
                    "bounding_box": [4, 5, 6, 7],
                }
            ]
        },
        confidence_threshold=0.5,
        class_mapping_profile="bridge_dataset",
    ).analyze(str(image_path), "bridge")

    assert findings[0].defect_type == "corrosion"
    assert findings[0].severity_label == "moderate"


def test_roboflow_image_analyzer_applies_class_specific_thresholds(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    findings = RoboflowImageAnalyzer(
        client=lambda image_path: {
            "predictions": [
                {
                    "class": "spalling",
                    "confidence": 0.2,
                    "bounding_box": [1, 2, 3, 4],
                },
                {
                    "class": "stain",
                    "confidence": 0.6,
                    "bounding_box": [5, 6, 7, 8],
                },
            ]
        },
        confidence_threshold=0.5,
        class_confidence_thresholds={"spalling": 0.1, "corrosion": 0.75},
    ).analyze(str(image_path), "bridge")

    assert [finding.defect_type for finding in findings] == ["spalling"]
    assert findings[0].confidence == 0.2


def test_roboflow_image_analyzer_passes_sdk_confidence_controls(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class FakeModel:
        def __init__(self):
            self.kwargs = None

        def infer(self, **kwargs):
            self.kwargs = kwargs
            return {"predictions": []}

    fake_model = FakeModel()
    import sys
    import types

    monkeypatch.setitem(
        sys.modules,
        "inference",
        types.SimpleNamespace(get_model=lambda model_id: fake_model),
    )
    analyzer = RoboflowImageAnalyzer(
        model_id="bridge-defects/1",
        backend="inference",
        confidence_threshold=0.25,
        inference_confidence=0.1,
        inference_iou_threshold=0.45,
    )
    analyzer.analyze(str(image_path), "bridge")

    assert fake_model.kwargs["confidence"] == 0.1
    assert fake_model.kwargs["iou_threshold"] == 0.45


def test_roboflow_image_analyzer_tiling_offsets_crop_boxes(tmp_path) -> None:
    from PIL import Image

    image_path = tmp_path / "bridge.jpg"
    Image.new("RGB", (100, 80), color="gray").save(image_path)
    calls = []

    def fake_client(image_path):
        calls.append(Path(image_path).name)
        if "_tile_2" in Path(image_path).name:
            return {
                "predictions": [
                    {
                        "class": "spalling",
                        "confidence": 0.8,
                        "x": 20,
                        "y": 20,
                        "width": 10,
                        "height": 8,
                    }
                ]
            }
        return {"predictions": []}

    findings = RoboflowImageAnalyzer(
        client=fake_client,
        confidence_threshold=0.5,
        tiling="grid-2x2",
    ).analyze(str(image_path), "bridge")

    assert len(calls) == 5
    assert findings[0].defect_type == "spalling"
    assert findings[0].bounding_box == (65, 16, 10, 8)
    assert "top-right tile" in findings[0].description


def test_roboflow_image_analyzer_tiling_deduplicates_overlapping_boxes(tmp_path) -> None:
    from PIL import Image

    image_path = tmp_path / "bridge.jpg"
    Image.new("RGB", (100, 80), color="gray").save(image_path)

    def fake_client(image_path):
        name = Path(image_path).name
        if "_tile_" not in name:
            return {
                "predictions": [
                    {
                        "class": "crack",
                        "confidence": 0.7,
                        "bounding_box": [10, 10, 20, 20],
                    }
                ]
            }
        if "_tile_1" in name:
            return {
                "predictions": [
                    {
                        "class": "crack",
                        "confidence": 0.9,
                        "bounding_box": [12, 12, 20, 20],
                    }
                ]
            }
        return {"predictions": []}

    findings = RoboflowImageAnalyzer(
        client=fake_client,
        confidence_threshold=0.5,
        tiling="grid-2x2",
    ).analyze(str(image_path), "bridge")

    assert len(findings) == 1
    assert findings[0].confidence == 0.9
    assert findings[0].bounding_box == (12, 12, 20, 20)


def test_roboflow_image_analyzer_returns_unknown_when_no_predictions(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    findings = RoboflowImageAnalyzer(
        client=lambda image_path: {"predictions": []},
        confidence_threshold=0.5,
    ).analyze(str(image_path), "bridge")

    assert findings[0].defect_type == "unknown"
    assert findings[0].severity_label == "none"


def test_roboflow_image_analyzer_maps_sdk_prediction_objects(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class Prediction:
        class_name = "Rebar exposure"
        confidence = 0.82
        x = 50
        y = 60
        width = 20
        height = 10

    findings = RoboflowImageAnalyzer(
        client=lambda image_path: [Prediction()],
        confidence_threshold=0.5,
    ).analyze(str(image_path), "bridge")

    assert findings[0].defect_type == "exposed_rebar"
    assert findings[0].severity_label == "high"
    assert findings[0].bounding_box == (40, 55, 20, 10)


def test_roboflow_image_analyzer_maps_sdk_response_objects(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class Prediction:
        class_name = "Spalling"
        confidence = 0.83
        x = 40
        y = 50
        width = 20
        height = 10

    class Response:
        predictions = [Prediction()]

    findings = RoboflowImageAnalyzer(
        client=lambda image_path: [Response()],
        confidence_threshold=0.5,
    ).analyze(str(image_path), "bridge")

    assert findings[0].defect_type == "spalling"
    assert findings[0].severity_label == "high"
    assert findings[0].bounding_box == (30, 45, 20, 10)


def test_roboflow_endpoint_accepts_model_id_with_embedded_version() -> None:
    analyzer = RoboflowImageAnalyzer(
        api_key="test-key",
        model_id="bridge-defects/3",
        model_version="3",
        api_url=None,
        client=lambda image_path: {"predictions": []},
    )

    endpoint = analyzer._endpoint()

    assert "bridge-defects/3" in endpoint
    assert "bridge-defects/3/3" not in endpoint


def test_roboflow_endpoint_normalizes_universe_project_url() -> None:
    analyzer = RoboflowImageAnalyzer(
        api_key="test-key",
        model_id="damage-detection-final-5x17w/2",
        api_url="https://universe.roboflow.com/damage-detection-xttk4/damage-detection-final-5x17w",
        client=lambda image_path: {"predictions": []},
    )

    endpoint = analyzer._endpoint()
    endpoints = analyzer._candidate_endpoints()

    assert endpoint.startswith("https://detect.roboflow.com/damage-detection-final-5x17w/2")
    assert any(
        "damage-detection-xttk4/damage-detection-final-5x17w/2" in candidate
        for candidate in endpoints
    )


def test_roboflow_endpoint_expands_bare_serverless_url() -> None:
    analyzer = RoboflowImageAnalyzer(
        api_key="test-key",
        model_id="damage-detection-final-5x17w/2",
        api_url="https://serverless.roboflow.com",
        client=lambda image_path: {"predictions": []},
    )

    assert analyzer._endpoint().startswith(
        "https://serverless.roboflow.com/damage-detection-final-5x17w/2"
    )


def test_openai_image_analyzer_parses_fenced_json(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class FakeResponse:
        content = (
            "```json\n"
            '{"findings":[{"defect_type":"spalling","description":"Visible spall",'
            '"location_on_asset":"joint","confidence":0.77}]}\n'
            "```"
        )

    class FakeClient:
        def invoke(self, messages):
            return FakeResponse()

    findings = OpenAIImageAnalyzer(client=FakeClient(), model="test-model").analyze(
        str(image_path),
        "bridge",
    )

    assert findings[0].defect_type == "spalling"
    assert findings[0].confidence == 0.77


def test_openai_image_analyzer_normalizes_freeform_defect_labels(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    image_path.write_bytes(b"fake image bytes")

    class FakeResponse:
        content = (
            '{"findings":[{"defect_type":"Concrete Staining",'
            '"description":"Surface discoloration",'
            '"location_on_asset":"deck","confidence":0.7}]}'
        )

    class FakeClient:
        def invoke(self, messages):
            return FakeResponse()

    findings = OpenAIImageAnalyzer(client=FakeClient(), model="test-model").analyze(
        str(image_path),
        "bridge",
    )

    assert findings[0].defect_type == "corrosion"


def test_metadata_image_analyzer_reads_real_annotations() -> None:
    row = _first_annotation_row("spalling")
    analyzer = MetadataImageAnalyzer("data/bridge_image/annotations.csv")

    findings = analyzer.analyze(row["file_path"], "bridge")

    spalling_findings = [
        finding for finding in findings if finding.defect_type == "spalling"
    ]
    assert spalling_findings
    assert spalling_findings[0].confidence == 0.95
    assert spalling_findings[0].bounding_box is not None
    assert "Metadata annotation" in spalling_findings[0].description


def test_metadata_image_analyzer_matches_by_basename() -> None:
    row = _first_annotation_row("spalling")
    analyzer = MetadataImageAnalyzer("data/bridge_image/annotations.csv")

    findings = analyzer.analyze(Path(row["file_path"]).name, "bridge")

    assert any(finding.defect_type == "spalling" for finding in findings)


def test_pipeline_can_use_real_bridge_image_annotations() -> None:
    row = _first_annotation_row("spalling")

    report = _run_test_graph(
        {
            "asset_id": "BR-REAL-IMAGE",
            "asset_type": "bridge",
            "asset_name": "Annotated Bridge Image",
            "location": "Real image dataset",
            "criticality": "high",
            "notes": "Real annotated bridge image submitted for inspection.",
            "image_paths": [row["file_path"]],
            "video_paths": [],
            "reason": "dataset_test",
        },
        image_analyzer_mode="metadata",
    )

    assert any(
        observation.defect_type == "spalling"
        and observation.media_reference
        and observation.media_reference.bounding_box
        for observation in report.observations
    )
    assert report.severity.repair_required is True
    assert report.maintenance_plan.historical_precedents


def test_real_bridge_image_report_includes_annotated_artifact() -> None:
    row = _first_annotation_row("spalling")

    report = _run_test_graph(
        {
            "asset_id": "BR-ANNOTATED-ARTIFACT",
            "asset_type": "bridge",
            "asset_name": "Annotated Artifact Bridge",
            "location": "Real image dataset",
            "criticality": "high",
            "notes": "Real annotated bridge image submitted for visual artifact generation.",
            "image_paths": [row["file_path"]],
            "video_paths": [],
            "reason": "artifact_test",
        },
        image_analyzer_mode="metadata",
    )

    assert report.annotated_media_paths
    assert Path(report.annotated_media_paths[0]).exists()
    assert report.rendered_report is not None
    assert "## Executive Summary" in report.rendered_report
    assert "## Evidence Traceability" in report.rendered_report
    assert "Risks:" in report.rendered_report
    assert "## Visual Evidence" in report.rendered_report
    assert report.annotated_media_paths[0] in report.rendered_report


def test_scheduler_context_changes_selected_window() -> None:
    windows = [
        {
            "start": "2026-06-18T22:00:00",
            "end": "2026-06-19T06:00:00",
            "crew": "night maintenance crew",
            "disruption_score": 1,
            "notes": "normally best window",
        },
        {
            "start": "2026-06-19T22:00:00",
            "end": "2026-06-20T06:00:00",
            "crew": "alternate night crew",
            "disruption_score": 2,
            "notes": "slightly higher disruption",
        },
    ]
    context = SchedulingContext(
        weather=[
            WeatherContext("2026-06-18T22:00:00", "storm", 8, "Unsafe storm risk."),
            WeatherContext("2026-06-19T22:00:00", "clear", 0, "Good conditions."),
        ],
        traffic=[
            TrafficContext("2026-06-18T22:00:00", "low", 0, "Low traffic."),
            TrafficContext("2026-06-19T22:00:00", "low", 0, "Low traffic."),
        ],
        events=[
            EventContext("2026-06-18T22:00:00", "No event", 0, "No conflict."),
            EventContext("2026-06-19T22:00:00", "No event", 0, "No conflict."),
        ],
    )
    severity = SeverityAssessment(
        severity="moderate",
        repair_required=True,
        urgency="scheduled",
        rationale="test",
        confidence=0.8,
    )
    plan = MaintenancePlan(
        recommended_action="test repair",
        historical_precedents=[],
        tasks=[],
        materials=[],
        equipment=[],
        permits=[],
        estimated_duration_hours=4,
        risks=[],
    )

    schedule = SchedulingAgent(windows, scheduling_mode="deterministic").schedule(None, severity, plan, context)  # type: ignore[arg-type]

    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"
    assert schedule.context_risk_score == 0


def test_scheduler_prefers_window_that_fits_repair_duration() -> None:
    windows = [
        {
            "start": "2026-06-18T22:00:00",
            "end": "2026-06-19T00:00:00",
            "crew": "concrete repair crew",
            "crew_available": "true",
            "disruption_score": 1,
            "closure_type": "single-lane closure",
            "notes": "short low-disruption window",
        },
        {
            "start": "2026-06-19T22:00:00",
            "end": "2026-06-20T06:00:00",
            "crew": "concrete repair crew",
            "crew_available": "true",
            "disruption_score": 4,
            "closure_type": "single-lane closure",
            "notes": "longer repair window",
        },
    ]
    context = SchedulingContext(weather=[], traffic=[], events=[])
    severity = SeverityAssessment(
        severity="moderate",
        repair_required=True,
        urgency="scheduled",
        rationale="test",
        confidence=0.8,
    )
    plan = MaintenancePlan(
        recommended_action="partial-depth concrete patch",
        historical_precedents=[],
        tasks=[],
        materials=["patching concrete"],
        equipment=[],
        permits=["work zone permit"],
        estimated_duration_hours=6,
        risks=[],
    )

    schedule = SchedulingAgent(windows, scheduling_mode="deterministic").schedule(None, severity, plan, context)  # type: ignore[arg-type]

    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"
    assert any("fits estimated work duration" in item for item in schedule.constraints_satisfied)


def test_scheduler_penalizes_unavailable_crew() -> None:
    windows = [
        {
            "start": "2026-06-18T22:00:00",
            "end": "2026-06-19T06:00:00",
            "crew": "concrete repair crew",
            "crew_available": "false",
            "disruption_score": 1,
            "closure_type": "single-lane closure",
            "notes": "best window but crew unavailable",
        },
        {
            "start": "2026-06-19T22:00:00",
            "end": "2026-06-20T06:00:00",
            "crew": "concrete repair crew",
            "crew_available": "true",
            "disruption_score": 5,
            "closure_type": "single-lane closure",
            "notes": "available crew",
        },
    ]
    context = SchedulingContext(weather=[], traffic=[], events=[])
    severity = SeverityAssessment(
        severity="moderate",
        repair_required=True,
        urgency="scheduled",
        rationale="test",
        confidence=0.8,
    )
    plan = MaintenancePlan(
        recommended_action="partial-depth concrete patch",
        historical_precedents=[],
        tasks=[],
        materials=["patching concrete"],
        equipment=[],
        permits=["work zone permit"],
        estimated_duration_hours=4,
        risks=[],
    )

    schedule = SchedulingAgent(windows, scheduling_mode="deterministic").schedule(None, severity, plan, context)  # type: ignore[arg-type]

    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"
    assert "crew is available" in schedule.constraints_satisfied


def test_scheduler_uses_rag_scheduling_precedents() -> None:
    class FakeRetriever:
        document = {
            "document_id": "SCHED-BRIDGE-001",
            "title": "Bridge Spalling Scheduling Case",
            "source_type": "schedule_record",
            "asset_type": "bridge",
            "defect_type": "spalling",
            "preferred_window_type": "overnight",
            "preferred_crew_type": "concrete",
            "preferred_closure_type": "single-lane closure",
            "schedule_outcome": "successful",
            "lessons_learned": "Concrete patching worked best overnight.",
        }

        def search(self, *args, **kwargs):
            assert kwargs["source_type"] == "schedule_record"
            assert kwargs["asset_type"] == "bridge"
            assert kwargs["defect_type"] == "spalling"
            assert kwargs["limit"] == 8
            return [
                Citation(
                    document_id=self.document["document_id"],
                    title=self.document["title"],
                    source_type="schedule_record",
                    excerpt="Overnight concrete repair case.",
                    score=0.9,
                )
            ]

        def get_document(self, document_id):
            if document_id == self.document["document_id"]:
                return self.document
            return None

    windows = [
        {
            "start": "2026-06-18T09:00:00",
            "end": "2026-06-18T17:00:00",
            "crew": "day maintenance crew",
            "crew_available": "true",
            "disruption_score": 1,
            "closure_type": "partial closure",
            "notes": "slightly lower disruption before RAG precedent",
        },
        {
            "start": "2026-06-19T22:00:00",
            "end": "2026-06-20T06:00:00",
            "crew": "concrete repair crew",
            "crew_available": "true",
            "disruption_score": 2,
            "closure_type": "single-lane closure",
            "notes": "matches scheduling precedent",
        },
    ]
    context = SchedulingContext(weather=[], traffic=[], events=[])
    severity = SeverityAssessment(
        severity="moderate",
        repair_required=True,
        urgency="scheduled",
        rationale="test",
        confidence=0.8,
    )
    plan = MaintenancePlan(
        recommended_action="partial-depth concrete patch",
        historical_precedents=[],
        tasks=[],
        materials=["patching concrete"],
        equipment=[],
        permits=["work zone permit"],
        estimated_duration_hours=4,
        risks=[],
    )
    inspection_case = InspectionCase(
        case_id="CASE-SCHED-RAG",
        asset=Asset(
            asset_id="BR-SCHED",
            asset_type="bridge",
            name="Scheduling RAG Bridge",
            location="North span",
            criticality="medium",
        ),
        reason="scheduler_rag_test",
        evidence=[],
    )

    schedule = SchedulingAgent(
        windows,
        FakeRetriever(),
        scheduling_mode="deterministic",
    ).schedule(
        inspection_case,
        severity,
        plan,
        context,
    )

    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"
    assert any("Scheduling precedent" in item for item in schedule.context_summary)
    assert any("Scheduling RAG precedent" in item for item in schedule.tradeoffs)


def test_scheduler_reranks_scheduling_rag_precedents_by_relevance() -> None:
    class FakeRetriever:
        documents = {
            "SCHED-BRIDGE-CRACK": {
                "document_id": "SCHED-BRIDGE-CRACK",
                "title": "Bridge Crack Scheduling Case",
                "source_type": "schedule_record",
                "asset_type": "bridge",
                "defect_type": "crack",
                "severity": "moderate",
                "repair_method": "routing and sealing",
                "preferred_window_type": "daytime",
                "preferred_crew_type": "joint",
                "preferred_closure_type": "partial closure",
                "planned_duration_hours": 4,
                "schedule_outcome": "successful",
                "disruption_outcome": "low disruption",
                "lessons_learned": "Crack sealing fit a short daytime lane closure.",
            },
            "SCHED-BRIDGE-SPALLING": {
                "document_id": "SCHED-BRIDGE-SPALLING",
                "title": "Bridge Spalling Scheduling Case",
                "source_type": "schedule_record",
                "asset_type": "bridge",
                "defect_type": "spalling",
                "severity": "high",
                "repair_method": "partial-depth concrete patch",
                "preferred_window_type": "overnight",
                "preferred_crew_type": "concrete",
                "preferred_closure_type": "single-lane closure",
                "planned_duration_hours": 6,
                "schedule_outcome": "successful",
                "disruption_outcome": "low disruption",
                "lessons_learned": "Spalling patching worked best overnight with concrete crew.",
            },
        }

        def search(self, *args, **kwargs):
            assert kwargs["defect_type"] == "spalling"
            return [
                Citation(
                    document_id="SCHED-BRIDGE-CRACK",
                    title="Bridge Crack Scheduling Case",
                    source_type="schedule_record",
                    excerpt="Crack case.",
                    score=0.1,
                ),
                Citation(
                    document_id="SCHED-BRIDGE-SPALLING",
                    title="Bridge Spalling Scheduling Case",
                    source_type="schedule_record",
                    excerpt="Spalling case.",
                    score=0.2,
                ),
            ]

        def get_document(self, document_id):
            return self.documents.get(document_id)

    windows = [
        {
            "start": "2026-06-18T09:00:00",
            "end": "2026-06-18T17:00:00",
            "crew": "day joint crew",
            "crew_available": "true",
            "disruption_score": 1,
            "closure_type": "partial closure",
            "notes": "matches unrelated crack precedent",
        },
        {
            "start": "2026-06-19T22:00:00",
            "end": "2026-06-20T06:00:00",
            "crew": "concrete repair crew",
            "crew_available": "true",
            "disruption_score": 2,
            "closure_type": "single-lane closure",
            "notes": "matches spalling precedent",
        },
    ]
    severity = SeverityAssessment(
        severity="high",
        repair_required=True,
        urgency="scheduled",
        rationale="test",
        confidence=0.8,
    )
    plan = MaintenancePlan(
        recommended_action="partial-depth concrete patch",
        historical_precedents=[],
        tasks=[],
        materials=["patching concrete"],
        equipment=[],
        permits=["work zone permit"],
        estimated_duration_hours=6,
        risks=[],
    )
    inspection_case = InspectionCase(
        case_id="CASE-SCHED-RERANK",
        asset=Asset(
            asset_id="BR-SCHED",
            asset_type="bridge",
            name="Scheduling RAG Bridge",
            location="North span",
            criticality="medium",
        ),
        reason="scheduler_rag_test",
        evidence=[],
    )

    schedule = SchedulingAgent(
        windows,
        FakeRetriever(),
        scheduling_mode="deterministic",
    ).schedule(
        inspection_case,
        severity,
        plan,
        SchedulingContext(weather=[], traffic=[], events=[]),
    )

    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"
    assert schedule.context_summary[0].startswith(
        "Scheduling precedent: SCHED-BRIDGE-SPALLING"
    )
    assert any("Spalling patching" in item for item in schedule.tradeoffs)


def test_llm_scheduler_selects_valid_candidate_window() -> None:
    runnable = FakePlanningRunnable(
        [
            _llm_schedule_payload(
                "2026-06-19T22:00:00",
                "2026-06-20T06:00:00",
                rationale="LLM chose lower real-world disruption despite higher base score.",
            )
        ]
    )
    schedule = _run_llm_scheduler(runnable)

    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"
    assert schedule.total_score == 3
    assert any("LLM scheduling rationale" in item for item in schedule.tradeoffs)
    assert any("Mitigation:" in item for item in schedule.tradeoffs)


def test_llm_scheduler_retries_after_invalid_window() -> None:
    runnable = FakePlanningRunnable(
        [
            _llm_schedule_payload("2026-06-18T22:00:00", "2026-06-19T06:00:00"),
            _llm_schedule_payload("2026-06-19T22:00:00", "2026-06-20T06:00:00"),
        ]
    )

    schedule = _run_llm_scheduler(runnable)

    assert runnable.calls == 2
    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"


def test_llm_scheduler_fallback_after_retry_exhaustion() -> None:
    runnable = FakePlanningRunnable([RuntimeError("scheduler model unavailable")])

    schedule = _run_llm_scheduler(runnable, max_retries=2)

    assert schedule.recommended_window.start.isoformat() == "2026-06-19T22:00:00"
    assert any(LLM_SCHEDULING_FAILURE_NOTE in item for item in schedule.tradeoffs)


def test_llm_scheduler_fail_mode_raises_after_retry_exhaustion() -> None:
    runnable = FakePlanningRunnable([RuntimeError("scheduler model unavailable")])

    with pytest.raises(LLMSchedulingError, match="failed after 2 attempts"):
        _run_llm_scheduler(runnable, max_retries=2, failure_mode="fail")


def test_mock_schedule_context_collector_uses_weather_traffic_and_event_tools() -> None:
    windows = [
        {
            "start": "2026-06-18T22:00:00",
            "end": "2026-06-19T06:00:00",
            "crew": "night maintenance crew",
            "disruption_score": 1,
            "notes": "normally best window",
        }
    ]
    collector = MockScheduleContextCollector(
        weather_tool=MockWeatherContextTool(
            {
                "2026-06-18T22:00:00": {
                    "condition": "storm",
                    "risk_score": 8,
                    "rationale": "Storm blocks exterior repair.",
                }
            }
        ),
        traffic_tool=MockTrafficContextTool(
            {
                "2026-06-18T22:00:00": {
                    "impact": "high",
                    "risk_score": 4,
                    "rationale": "Heavy traffic complicates closure.",
                }
            }
        ),
        event_tool=MockCityEventContextTool(
            {
                "2026-06-18T22:00:00": {
                    "title": "Stadium egress",
                    "risk_score": 3,
                    "rationale": "Nearby event conflicts with detours.",
                }
            }
        ),
    )

    context = collector.collect(None, windows)  # type: ignore[arg-type]

    assert context.weather[0].condition == "storm"
    assert context.weather[0].risk_score == 8
    assert context.traffic[0].impact == "high"
    assert context.traffic[0].risk_score == 4
    assert context.events[0].title == "Stadium egress"
    assert context.events[0].risk_score == 3


def test_openweather_context_tool_maps_forecast_payload() -> None:
    case = InspectionCase(
        case_id="CASE-LIVE",
        asset=Asset(
            asset_id="A-LIVE",
            asset_type="bridge",
            name="Live Bridge",
            location="Downtown",
            criticality="high",
            metadata={"latitude": 40.75, "longitude": -73.99},
        ),
        reason="routine",
        evidence=[],
    )
    window = {
        "start": "2026-06-18T22:00:00",
        "end": "2026-06-19T06:00:00",
    }

    def fake_get(url: str) -> dict:
        assert "lat=40.75" in url
        assert "lon=-73.99" in url
        assert "appid=test-key" in url
        return {
            "list": [
                {
                    "dt": 1781816400,
                    "weather": [{"main": "Rain"}],
                    "pop": 0.8,
                    "wind": {"speed": 9},
                }
            ]
        }

    context = OpenWeatherContextTool(api_key="test-key", http_get=fake_get).collect(
        case,
        window,
    )

    assert context.window_start == "2026-06-18T22:00:00"
    assert context.condition == "Rain"
    assert context.risk_score == 9
    assert "OpenWeather forecast" in context.rationale


def test_openweather_context_tool_accepts_open_weather_env_alias(monkeypatch) -> None:
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.setenv("OPEN_WEATHER_API_KEY", "alias-key")

    tool = OpenWeatherContextTool()

    assert tool.api_key == "alias-key"


def test_tomtom_context_tool_maps_flow_payload() -> None:
    case = InspectionCase(
        case_id="CASE-LIVE",
        asset=Asset(
            asset_id="A-LIVE",
            asset_type="bridge",
            name="Live Bridge",
            location="Downtown",
            criticality="high",
            metadata={"latitude": 40.75, "longitude": -73.99},
        ),
        reason="routine",
        evidence=[],
    )
    window = {
        "start": "2026-06-18T22:00:00",
        "end": "2026-06-19T06:00:00",
    }

    def fake_get(url: str) -> dict:
        assert "point=40.75%2C-73.99" in url
        assert "key=test-key" in url
        return {
            "flowSegmentData": {
                "currentSpeed": 20,
                "freeFlowSpeed": 80,
                "currentTravelTime": 200,
                "freeFlowTravelTime": 80,
                "roadClosure": False,
            }
        }

    context = TomTomTrafficContextTool(api_key="test-key", http_get=fake_get).collect(
        case,
        window,
    )

    assert context.window_start == "2026-06-18T22:00:00"
    assert context.impact == "severe"
    assert context.risk_score == 8
    assert "TomTom traffic flow" in context.rationale


def test_ticketmaster_context_tool_maps_nearby_events() -> None:
    case = InspectionCase(
        case_id="CASE-LIVE",
        asset=Asset(
            asset_id="A-LIVE",
            asset_type="bridge",
            name="Live Bridge",
            location="Downtown",
            criticality="high",
            metadata={"latitude": 40.75, "longitude": -73.99},
        ),
        reason="routine",
        evidence=[],
    )
    window = {
        "start": "2026-06-18T22:00:00",
        "end": "2026-06-19T06:00:00",
    }

    def fake_get(url: str) -> dict:
        assert "apikey=test-key" in url
        assert "latlong=40.75%2C-73.99" in url
        assert "startDateTime=2026-06-18T22%3A00%3A00Z" in url
        return {
            "_embedded": {
                "events": [
                    {"name": "Arena Concert"},
                    {"name": "Late Game"},
                ]
            }
        }

    context = TicketmasterEventContextTool(api_key="test-key", http_get=fake_get).collect(
        case,
        window,
    )

    assert context.window_start == "2026-06-18T22:00:00"
    assert context.title == "Arena Concert"
    assert context.risk_score == 4
    assert "Arena Concert" in context.rationale


def test_schedule_context_factory_can_build_live_collector() -> None:
    collector = build_schedule_context_collector(
        "live",
        event_provider="ticketmaster",
    )

    assert isinstance(collector.weather_tool, OpenWeatherContextTool)
    assert isinstance(collector.traffic_tool, TomTomTrafficContextTool)
    assert isinstance(collector.event_tool, TicketmasterEventContextTool)


def _first_annotation_row(defect_type: str) -> dict[str, str]:
    with Path("data/bridge_image/annotations.csv").open(
        newline="",
        encoding="utf-8",
    ) as file:
        for row in csv.DictReader(file):
            if row["defect_type"] == defect_type:
                return row
    raise AssertionError(f"No annotation row found for {defect_type}.")


def _assert_bridge_spalling_precedent(report) -> None:
    assert report.maintenance_plan.historical_precedents
    precedent = report.maintenance_plan.historical_precedents[0]
    assert precedent.document_id.startswith("HIST-BRIDGE-")
    assert precedent.repair_method == "partial-depth concrete patch"


def _create_tiny_video(video_path: Path) -> Path:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")

    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(video_path), fourcc, 2.0, (32, 32))
    if not writer.isOpened():
        pytest.skip("OpenCV video writer is unavailable in this environment.")

    try:
        for index in range(6):
            frame = np.full((32, 32, 3), index * 20, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()

    return video_path


def _run_llm_scheduler(
    runnable,
    *,
    max_retries: int = 4,
    failure_mode: str = "fallback",
):
    windows = [
        {
            "start": "2026-06-18T22:00:00",
            "end": "2026-06-19T06:00:00",
            "crew": "concrete repair crew",
            "crew_available": "false",
            "disruption_score": 1,
            "closure_type": "single-lane closure",
            "notes": "low disruption but crew unavailable",
        },
        {
            "start": "2026-06-19T22:00:00",
            "end": "2026-06-20T06:00:00",
            "crew": "concrete repair crew",
            "crew_available": "true",
            "disruption_score": 3,
            "closure_type": "single-lane closure",
            "notes": "available overnight concrete crew",
        },
    ]
    context = SchedulingContext(weather=[], traffic=[], events=[])
    severity = SeverityAssessment(
        severity="moderate",
        repair_required=True,
        urgency="scheduled",
        rationale="test",
        confidence=0.8,
    )
    plan = MaintenancePlan(
        recommended_action="partial-depth concrete patch",
        historical_precedents=[],
        tasks=[],
        materials=["patching concrete"],
        equipment=[],
        permits=["work zone permit"],
        estimated_duration_hours=4,
        risks=[],
    )
    inspection_case = InspectionCase(
        case_id="CASE-LLM-SCHED",
        asset=Asset(
            asset_id="BR-LLM-SCHED",
            asset_type="bridge",
            name="LLM Scheduling Bridge",
            location="North span",
            criticality="medium",
        ),
        reason="llm_scheduler_test",
        evidence=[],
    )
    generator = LLMScheduleGenerator(
        runnable=runnable,
        max_retries=max_retries,
        failure_mode=failure_mode,  # type: ignore[arg-type]
    )

    return SchedulingAgent(
        windows,
        scheduling_mode="llm",
        schedule_generator=generator,
    ).schedule(
        inspection_case,
        severity,
        plan,
        context,
    )


class FakePlanningRunnable:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def invoke(self, messages):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


def _llm_plan_payload(recommended_action: str = "LLM-guided patch plan"):
    return {
        "recommended_action": recommended_action,
        "tasks": [
            {
                "name": "Confirm repair limits",
                "description": "Mark spalled concrete limits and verify substrate condition.",
                "estimated_hours": 2,
                "dependencies": [],
            },
            {
                "name": "Patch and cure",
                "description": "Remove loose material, apply inhibitor, patch, and protect cure.",
                "estimated_hours": 10,
                "dependencies": ["Confirm repair limits"],
            },
        ],
        "materials": ["rapid-set patching concrete"],
        "equipment": ["access platform", "safety barriers"],
        "permits": ["work zone permit"],
        "estimated_duration_hours": 12,
        "risks": ["Repair limits may expand after sounding."],
    }


def _llm_severity_payload(rationale: str = "LLM-cited severity rationale"):
    return {
        "rationale": rationale,
        "missing_evidence": ["measured defect dimensions", "recent comparison photos"],
    }


def _llm_schedule_payload(
    selected_window_start: str,
    selected_window_end: str,
    *,
    rationale: str = "LLM selected the best feasible repair window.",
):
    return {
        "selected_window_start": selected_window_start,
        "selected_window_end": selected_window_end,
        "rationale": rationale,
        "staging_required": False,
        "disruption_mitigation_steps": [
            "Notify affected users before lane restrictions begin.",
        ],
        "risks": ["Crew handoff may delay setup."],
        "rejected_window_reasons": [
            "Lower-scoring alternative had weaker real-time feasibility.",
        ],
    }
