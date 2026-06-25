from __future__ import annotations

import argparse

from agents.report_agent import ReportAgent
from models import InspectionReport
from workflows.inspection_graph import run_inspection_graph


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the infrastructure inspection multi-agent prototype."
    )
    parser.add_argument("--asset-id", default="A-100")
    parser.add_argument("--asset-type", default="bridge")
    parser.add_argument("--asset-name", default="Demo Overpass")
    parser.add_argument("--location", default="North service corridor")
    parser.add_argument(
        "--latitude",
        type=float,
        default=None,
        help="Asset latitude used by live weather, traffic, and event context tools.",
    )
    parser.add_argument(
        "--longitude",
        type=float,
        default=None,
        help="Asset longitude used by live weather, traffic, and event context tools.",
    )
    parser.add_argument(
        "--criticality",
        choices=["low", "medium", "high", "critical"],
        default="high",
    )
    parser.add_argument(
        "--notes",
        default=(
            "Inspection found spalling near an expansion joint with loose concrete "
            "and exposed substrate. No immediate closure is in place."
        ),
    )
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Path to an inspection image. Can be provided multiple times.",
    )
    parser.add_argument(
        "--video",
        action="append",
        default=[],
        help="Path to an inspection video. Can be provided multiple times.",
    )
    parser.add_argument(
        "--image-analyzer",
        choices=["heuristic", "metadata", "openai", "roboflow"],
        default="heuristic",
        help="Image analyzer backend. Defaults to offline heuristic mode.",
    )
    parser.add_argument(
        "--image-annotations",
        default="data/bridge_image/annotations.csv",
        help="CSV annotation path used by --image-analyzer metadata.",
    )
    parser.add_argument(
        "--image-prompt-profile",
        default=None,
        help=(
            "OpenAI image prompt profile. Defaults to OPENAI_IMAGE_PROMPT_PROFILE "
            "or bridge_defect_v1."
        ),
    )
    parser.add_argument(
        "--image-detail",
        choices=["auto", "low", "high"],
        default=None,
        help="OpenAI image detail setting. Defaults to OPENAI_IMAGE_DETAIL or high.",
    )
    parser.add_argument(
        "--image-tiling",
        choices=["none", "grid-2x2"],
        default="none",
        help="Optional OpenAI image tiling mode. grid-2x2 sends full image plus quadrant crops.",
    )
    parser.add_argument(
        "--roboflow-confidence-threshold",
        type=float,
        default=0.25,
        help="Minimum Roboflow prediction confidence to convert into an observation.",
    )
    parser.add_argument(
        "--roboflow-backend",
        choices=["auto", "inference", "http"],
        default=None,
        help="Roboflow inference backend. Defaults to ROBOFLOW_BACKEND or auto.",
    )
    parser.add_argument(
        "--roboflow-class-mapping-profile",
        choices=["default", "bridge_dataset"],
        default=None,
        help=(
            "Roboflow label normalization profile. bridge_dataset maps labels to "
            "the local bridge annotation taxonomy."
        ),
    )
    parser.add_argument(
        "--roboflow-tiling",
        choices=["none", "grid-2x2"],
        default="none",
        help="Optional Roboflow crop tiling mode. grid-2x2 runs full image plus quadrant crops.",
    )
    parser.add_argument(
        "--roboflow-class-thresholds",
        default=None,
        help=(
            "Comma-separated per-defect thresholds, for example "
            "'spalling=0.1,exposed_rebar=0.1,corrosion=0.75'."
        ),
    )
    parser.add_argument(
        "--roboflow-inference-confidence",
        type=float,
        default=None,
        help=(
            "Model-level Roboflow confidence passed to the inference backend. "
            "Defaults to the observation confidence threshold."
        ),
    )
    parser.add_argument(
        "--roboflow-inference-iou-threshold",
        type=float,
        default=None,
        help="Model-level Roboflow NMS IoU threshold. Defaults to 0.3.",
    )
    parser.add_argument(
        "--vision-verifier",
        choices=["none", "openai"],
        default="none",
        help=(
            "Optional second-pass vision verifier for ambiguous detector results. "
            "Use openai to verify low-confidence or crack/spalling-ambiguous images."
        ),
    )
    parser.add_argument(
        "--verification-confidence-threshold",
        type=float,
        default=0.55,
        help="Minimum verifier confidence required to add a verified image finding.",
    )
    parser.add_argument(
        "--verifier-prompt-profile",
        default=None,
        help=(
            "OpenAI prompt profile for --vision-verifier openai. Defaults to "
            "bridge_defect_v2_strict."
        ),
    )
    parser.add_argument(
        "--video-sampler",
        choices=["mock", "opencv"],
        default="mock",
        help="Video frame sampler backend. Defaults to deterministic mock sampling.",
    )
    parser.add_argument(
        "--video-frame-interval",
        type=float,
        default=5.0,
        help="Seconds between sampled video frames when using OpenCV sampling.",
    )
    parser.add_argument(
        "--video-max-frames",
        type=int,
        default=3,
        help="Maximum number of frames to sample from each video.",
    )
    parser.add_argument(
        "--rag-backend",
        choices=["chroma", "local"],
        default="chroma",
        help="Knowledge retrieval backend. Defaults to LangChain Chroma.",
    )
    parser.add_argument(
        "--embedding-backend",
        choices=["fake", "openai"],
        default="openai",
        help="Embedding backend for Chroma RAG. Defaults to OpenAI embeddings.",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help=(
            "OpenAI embedding model. Defaults to OPENAI_EMBEDDING_MODEL "
            "or text-embedding-3-small."
        ),
    )
    parser.add_argument(
        "--chroma-persist-dir",
        default="artifacts/chroma",
        help="Persistent Chroma database directory.",
    )
    parser.add_argument(
        "--rebuild-rag-index",
        action="store_true",
        help="Rebuild the persistent Chroma collection before running.",
    )
    parser.add_argument(
        "--knowledge-corpus",
        choices=["sample", "bridge", "merged"],
        default="merged",
        help="Knowledge corpus for RAG. Defaults to sample docs plus bridge dataset.",
    )
    parser.add_argument(
        "--planning-mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Maintenance planning strategy. Defaults to deterministic mode.",
    )
    parser.add_argument(
        "--scheduling-mode",
        choices=["deterministic", "llm"],
        default="llm",
        help="Repair scheduling strategy. Defaults to LLM-assisted mode with deterministic validation.",
    )
    parser.add_argument(
        "--schedule-context-mode",
        choices=["mock", "live"],
        default="mock",
        help=(
            "Scheduling context source. mock uses deterministic fixtures; live uses "
            "OpenWeather and TomTom, plus the selected event provider."
        ),
    )
    parser.add_argument(
        "--event-provider",
        choices=["mock", "ticketmaster"],
        default="mock",
        help="City event provider for scheduling context. Defaults to deterministic mock data.",
    )
    parser.add_argument(
        "--severity-mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Severity rationale strategy. Deterministic rules still decide severity.",
    )
    parser.add_argument(
        "--report-mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Final report rendering strategy. Defaults to deterministic mode.",
    )
    parser.add_argument(
        "--llm-max-retries",
        type=int,
        default=4,
        help="Maximum LLM planning attempts before fallback or failure.",
    )
    parser.add_argument(
        "--llm-failure-mode",
        choices=["fallback", "fail"],
        default="fallback",
        help="How LLM planning behaves after retries are exhausted.",
    )
    parser.add_argument("--reason", default="routine")
    return parser


def run_pipeline(args: argparse.Namespace) -> InspectionReport:
    asset_metadata = {
        key: value
        for key, value in {
            "latitude": args.latitude,
            "longitude": args.longitude,
        }.items()
        if value is not None
    }
    return run_inspection_graph(
        {
            "asset_id": args.asset_id,
            "asset_type": args.asset_type,
            "asset_name": args.asset_name,
            "location": args.location,
            "criticality": args.criticality,
            "asset_metadata": asset_metadata,
            "notes": args.notes,
            "image_paths": args.image,
            "video_paths": args.video,
            "reason": args.reason,
        },
        image_analyzer_mode=args.image_analyzer,
        image_annotations_path=args.image_annotations,
        image_prompt_profile=args.image_prompt_profile,
        image_detail=args.image_detail,
        image_tiling=args.image_tiling,
        roboflow_confidence_threshold=args.roboflow_confidence_threshold,
        roboflow_backend=args.roboflow_backend,
        roboflow_class_mapping_profile=args.roboflow_class_mapping_profile,
        roboflow_tiling=args.roboflow_tiling,
        roboflow_class_thresholds=args.roboflow_class_thresholds,
        roboflow_inference_confidence=args.roboflow_inference_confidence,
        roboflow_inference_iou_threshold=args.roboflow_inference_iou_threshold,
        vision_verifier=args.vision_verifier,
        verification_confidence_threshold=args.verification_confidence_threshold,
        verifier_prompt_profile=args.verifier_prompt_profile,
        video_sampler_mode=args.video_sampler,
        video_frame_interval_seconds=args.video_frame_interval,
        video_max_frames=args.video_max_frames,
        severity_mode=args.severity_mode,
        planning_mode=args.planning_mode,
        scheduling_mode=args.scheduling_mode,
        schedule_context_mode=args.schedule_context_mode,
        event_provider=args.event_provider,
        report_mode=args.report_mode,
        llm_max_retries=args.llm_max_retries,
        llm_failure_mode=args.llm_failure_mode,
        rag_backend=args.rag_backend,
        embedding_backend=args.embedding_backend,
        embedding_model=args.embedding_model,
        chroma_persist_dir=args.chroma_persist_dir,
        rebuild_rag_index=args.rebuild_rag_index,
        knowledge_corpus=args.knowledge_corpus,
    )


def main() -> None:
    parser = build_parser()
    report = run_pipeline(parser.parse_args())
    print(report.rendered_report or ReportAgent().render(report))


if __name__ == "__main__":
    main()
