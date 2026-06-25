from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from workflows.inspection_graph import run_inspection_graph


DEFECT_ALIASES = {
    "corrosion_staining": "corrosion",
    "normal/no_defect": "unknown",
    "none": "unknown",
}

DEFECT_TERMS = {
    "crack": ["crack", "cracking"],
    "spalling": ["spalling", "spall"],
    "exposed_rebar": ["exposed_rebar", "exposed rebar", "exposed reinforcement", "rebar"],
    "corrosion": ["corrosion", "corroded", "rust", "staining", "steel corrosion"],
    "leak": ["leak", "water leak", "water intrusion", "seepage"],
    "water_leak": ["leak", "water leak", "water intrusion", "seepage"],
}

REVIEWED_ACCEPTABLE_DEFECTS = {
    # Visual QA: these annotations are labeled as spalling, but the marked region
    # is predominantly a linear crack with little/no visible concrete loss.
    "REAL-BRIDGE-IMG-0010": {"spalling", "crack"},
    "REAL-BRIDGE-IMG-0028": {"spalling", "crack"},
    "REAL-BRIDGE-IMG-0033": {"spalling", "crack"},
    "REAL-BRIDGE-IMG-0034": {"spalling", "crack"},
    "REAL-BRIDGE-IMG-0058": {"spalling", "crack"},
    "REAL-BRIDGE-IMG-0066": {"spalling", "crack"},
    "REAL-BRIDGE-IMG-0076": {"spalling", "crack"},
}

REVIEWED_ACCEPTABLE_SEVERITIES = {
    image_id: {"high", "moderate"}
    for image_id in REVIEWED_ACCEPTABLE_DEFECTS
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the bridge image dataset.")
    parser.add_argument("--metadata-csv", default="data/bridge_image/metadata.csv")
    parser.add_argument("--annotations-csv", default="data/bridge_image/annotations.csv")
    parser.add_argument("--output-json", default="artifacts/evals/bridge_dataset_eval.json")
    parser.add_argument("--output-md", default="artifacts/evals/bridge_dataset_eval.md")
    parser.add_argument(
        "--case-review-md",
        default="artifacts/evals/bridge_case_review.md",
        help="Markdown case-review artifact for failed cases and sampled passing cases.",
    )
    parser.add_argument(
        "--case-review-limit",
        type=int,
        default=25,
        help="Maximum failed cases to include in the case-review artifact.",
    )
    parser.add_argument(
        "--case-review-include-passing",
        type=int,
        default=3,
        help="Number of passing cases to include as comparison examples.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--image-analyzer",
        choices=["metadata", "heuristic", "openai", "roboflow"],
        default="metadata",
        help=(
            "Image analyzer to evaluate. Metadata is the annotation-assisted baseline; "
            "OpenAI/Roboflow/heuristic measure inference against metadata ground truth."
        ),
    )
    parser.add_argument(
        "--image-prompt-profile",
        default=None,
        help=(
            "OpenAI image prompt profile used when --image-analyzer openai is selected."
        ),
    )
    parser.add_argument(
        "--image-detail",
        choices=["auto", "low", "high"],
        default=None,
        help="OpenAI image detail setting used when --image-analyzer openai is selected.",
    )
    parser.add_argument(
        "--image-tiling",
        choices=["none", "grid-2x2"],
        default="none",
        help="Optional OpenAI image tiling mode for large inspection images.",
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
        help="Roboflow label normalization profile.",
    )
    parser.add_argument(
        "--roboflow-tiling",
        choices=["none", "grid-2x2"],
        default="none",
        help="Optional Roboflow crop tiling mode.",
    )
    parser.add_argument(
        "--roboflow-class-thresholds",
        default=None,
        help="Comma-separated per-defect Roboflow thresholds.",
    )
    parser.add_argument(
        "--roboflow-inference-confidence",
        type=float,
        default=None,
        help="Model-level Roboflow confidence passed to the inference backend.",
    )
    parser.add_argument(
        "--roboflow-inference-iou-threshold",
        type=float,
        default=None,
        help="Model-level Roboflow NMS IoU threshold.",
    )
    parser.add_argument(
        "--vision-verifier",
        choices=["none", "openai"],
        default="none",
        help="Optional second-pass verifier for ambiguous image detections.",
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
        help="OpenAI prompt profile used by --vision-verifier openai.",
    )
    parser.add_argument("--embedding-backend", choices=["fake", "openai"], default="openai")
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--chroma-persist-dir", default="artifacts/chroma")
    parser.add_argument("--rebuild-rag-index", action="store_true")
    parser.add_argument(
        "--knowledge-corpus",
        choices=["sample", "bridge", "merged"],
        default="bridge",
    )
    parser.add_argument(
        "--scheduling-mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Scheduling strategy for eval runs. Defaults to deterministic for offline repeatability.",
    )
    parser.add_argument(
        "--strict-defect-labels",
        action="store_true",
        help="Disable reviewed acceptable-label aliases and score only raw dataset labels.",
    )
    return parser


def run_bridge_dataset_eval(args: argparse.Namespace) -> dict[str, Any]:
    rows = _load_metadata_rows(Path(args.metadata_csv), limit=args.limit)
    cases = []
    for row in rows:
        report = run_inspection_graph(
            {
                "asset_id": row["asset_id"],
                "asset_type": row["asset_type"],
                "asset_name": row["image_id"],
                "location": row["location_on_asset"],
                "criticality": "high" if row["severity_label"] == "high" else "medium",
                "notes": row["notes"],
                "image_paths": [row["file_path"]],
                "video_paths": [],
                "reason": "dataset_eval",
            },
            image_analyzer_mode=args.image_analyzer,
            image_annotations_path=args.annotations_csv,
            image_prompt_profile=args.image_prompt_profile,
            image_detail=args.image_detail,
            image_tiling=args.image_tiling,
            roboflow_confidence_threshold=args.roboflow_confidence_threshold,
            roboflow_backend=args.roboflow_backend,
            roboflow_class_mapping_profile=getattr(
                args,
                "roboflow_class_mapping_profile",
                None,
            ),
            roboflow_tiling=getattr(args, "roboflow_tiling", "none"),
            roboflow_class_thresholds=getattr(
                args,
                "roboflow_class_thresholds",
                None,
            ),
            roboflow_inference_confidence=getattr(
                args,
                "roboflow_inference_confidence",
                None,
            ),
            roboflow_inference_iou_threshold=getattr(
                args,
                "roboflow_inference_iou_threshold",
                None,
            ),
            vision_verifier=getattr(args, "vision_verifier", "none"),
            verification_confidence_threshold=getattr(
                args,
                "verification_confidence_threshold",
                0.55,
            ),
            verifier_prompt_profile=getattr(args, "verifier_prompt_profile", None),
            scheduling_mode=getattr(args, "scheduling_mode", "deterministic"),
            rag_backend="chroma",
            embedding_backend=args.embedding_backend,
            embedding_model=args.embedding_model,
            chroma_persist_dir=args.chroma_persist_dir,
            rebuild_rag_index=args.rebuild_rag_index and not cases,
            knowledge_corpus=args.knowledge_corpus,
        )
        cases.append(
            _score_case(
                row,
                report,
                use_reviewed_taxonomy=not getattr(
                    args,
                    "strict_defect_labels",
                    False,
                ),
            )
        )

    result = {
        "image_analyzer": args.image_analyzer,
        "image_prompt_profile": args.image_prompt_profile,
        "image_detail": args.image_detail,
        "image_tiling": args.image_tiling,
        "roboflow_confidence_threshold": args.roboflow_confidence_threshold,
        "roboflow_backend": args.roboflow_backend,
        "roboflow_class_mapping_profile": getattr(
            args,
            "roboflow_class_mapping_profile",
            None,
        ),
        "roboflow_tiling": getattr(args, "roboflow_tiling", "none"),
        "roboflow_class_thresholds": getattr(
            args,
            "roboflow_class_thresholds",
            None,
        ),
        "roboflow_inference_confidence": getattr(
            args,
            "roboflow_inference_confidence",
            None,
        ),
        "roboflow_inference_iou_threshold": getattr(
            args,
            "roboflow_inference_iou_threshold",
            None,
        ),
        "vision_verifier": getattr(args, "vision_verifier", "none"),
        "verification_confidence_threshold": getattr(
            args,
            "verification_confidence_threshold",
            0.55,
        ),
        "verifier_prompt_profile": getattr(args, "verifier_prompt_profile", None),
        "strict_defect_labels": getattr(args, "strict_defect_labels", False),
        "reviewed_taxonomy_enabled": not getattr(
            args,
            "strict_defect_labels",
            False,
        ),
        "case_count": len(cases),
        "metrics": _metrics(cases),
        "metrics_by_defect": _metrics_by_defect(cases),
        "failure_summary": _failure_summary(cases),
        "cases": cases,
    }
    _write_json(Path(args.output_json), result)
    _write_markdown(Path(args.output_md), result)
    _write_case_review_markdown(
        Path(getattr(args, "case_review_md", "artifacts/evals/bridge_case_review.md")),
        result,
        failed_limit=getattr(args, "case_review_limit", 25),
        passing_limit=getattr(args, "case_review_include_passing", 3),
    )
    return result


def _load_metadata_rows(path: Path, *, limit: int | None) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if limit is not None:
        return rows[:limit]
    return rows


def _score_case(
    row: dict[str, str],
    report,
    *,
    use_reviewed_taxonomy: bool = True,
) -> dict[str, Any]:
    expected_defect = _normalize_defect(row["primary_defect_type"])
    acceptable_defects = _acceptable_defects(
        row["image_id"],
        expected_defect,
        use_reviewed_taxonomy=use_reviewed_taxonomy,
    )
    observed_defects = {_normalize_defect(observation.defect_type) for observation in report.observations}
    expected_severity = row["severity_label"]
    acceptable_severities = _acceptable_severities(
        row["image_id"],
        expected_severity,
        use_reviewed_taxonomy=use_reviewed_taxonomy,
    )
    expected_repair_required = expected_severity in {"moderate", "high", "critical"}
    standard_hits = [
        citation.document_id
        for citation in report.severity.citations
        if any(_citation_matches(citation, defect) for defect in acceptable_defects)
    ]
    repair_hits = [
        precedent.document_id
        for precedent in report.maintenance_plan.historical_precedents
        if _text_matches_defect(
            " ".join(
                [
                    precedent.document_id,
                    precedent.title,
                    precedent.repair_method,
                    precedent.citation.excerpt,
                ]
            ),
            acceptable_defects,
        )
    ]

    case = {
        "image_id": row["image_id"],
        "file_path": row["file_path"],
        "expected_defect": expected_defect,
        "acceptable_defects": sorted(acceptable_defects),
        "reviewed_taxonomy_applied": acceptable_defects != {expected_defect},
        "observed_defects": sorted(observed_defects),
        "observations": [
            {
                "defect_type": observation.defect_type,
                "severity_label": observation.measurement.get("severity_label"),
                "confidence": observation.confidence,
                "location_on_asset": observation.location_on_asset,
                "description": observation.description,
            }
            for observation in report.observations
        ],
        "expected_severity": expected_severity,
        "acceptable_severities": sorted(acceptable_severities),
        "predicted_severity": report.severity.severity,
        "expected_repair_required": expected_repair_required,
        "predicted_repair_required": report.severity.repair_required,
        "defect_match": bool(acceptable_defects & observed_defects),
        "severity_match": report.severity.severity in acceptable_severities,
        "repair_required_match": expected_repair_required == report.severity.repair_required,
        "standard_retrieval_hit": bool(standard_hits) or expected_defect == "unknown",
        "repair_precedent_hit": bool(repair_hits) or not expected_repair_required,
        "standard_citation_ids": [citation.document_id for citation in report.severity.citations],
        "repair_precedent_ids": [
            precedent.document_id
            for precedent in report.maintenance_plan.historical_precedents
        ],
        "maintenance_action": report.maintenance_plan.recommended_action,
        "maintenance_duration_hours": report.maintenance_plan.estimated_duration_hours,
        "maintenance_materials": report.maintenance_plan.materials,
        "maintenance_equipment": report.maintenance_plan.equipment,
        "maintenance_permits": report.maintenance_plan.permits,
        "maintenance_risks": report.maintenance_plan.risks,
        "schedule_context_summary": (
            report.schedule.context_summary
            if report.schedule
            else []
        ),
        "schedule_tradeoffs": (
            report.schedule.tradeoffs
            if report.schedule
            else []
        ),
        "schedule_generated": report.schedule is not None,
        "schedule_window": (
            {
                "start": report.schedule.recommended_window.start.isoformat(),
                "end": report.schedule.recommended_window.end.isoformat(),
                "total_score": report.schedule.total_score,
            }
            if report.schedule
            else None
        ),
        "report_generated": bool(report.rendered_report),
        "citation_count": len(report.severity.citations)
        + len(report.maintenance_plan.historical_precedents),
    }
    case["failure_reasons"] = _failure_reasons(case)
    case["primary_failure_stage"] = _primary_failure_stage(case["failure_reasons"])
    return case


def _metrics(cases: list[dict[str, Any]]) -> dict[str, float]:
    if not cases:
        return {
            "defect_accuracy": 0.0,
            "severity_accuracy": 0.0,
            "repair_required_accuracy": 0.0,
            "standard_retrieval_hit_rate": 0.0,
            "repair_precedent_hit_rate": 0.0,
            "schedule_generation_rate": 0.0,
            "report_generation_rate": 0.0,
            "average_retrieved_citations_per_case": 0.0,
        }
    return {
        "defect_accuracy": _rate(cases, "defect_match"),
        "severity_accuracy": _rate(cases, "severity_match"),
        "repair_required_accuracy": _rate(cases, "repair_required_match"),
        "standard_retrieval_hit_rate": _rate(cases, "standard_retrieval_hit"),
        "repair_precedent_hit_rate": _rate(cases, "repair_precedent_hit"),
        "schedule_generation_rate": _rate(
            [
                case
                for case in cases
                if case["expected_repair_required"]
            ],
            "schedule_generated",
        ),
        "report_generation_rate": _rate(cases, "report_generated"),
        "average_retrieved_citations_per_case": round(
            sum(case["citation_count"] for case in cases) / len(cases),
            3,
        ),
    }


def _metrics_by_defect(cases: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    defect_types = sorted({case["expected_defect"] for case in cases})
    metrics: dict[str, dict[str, float | int]] = {}
    for defect_type in defect_types:
        defect_cases = [
            case
            for case in cases
            if case["expected_defect"] == defect_type
        ]
        metrics[defect_type] = {
            "case_count": len(defect_cases),
            "defect_accuracy": _rate(defect_cases, "defect_match"),
            "severity_accuracy": _rate(defect_cases, "severity_match"),
            "repair_required_accuracy": _rate(defect_cases, "repair_required_match"),
            "standard_retrieval_hit_rate": _rate(defect_cases, "standard_retrieval_hit"),
            "repair_precedent_hit_rate": _rate(defect_cases, "repair_precedent_hit"),
            "schedule_generation_rate": _rate(
                [
                    case
                    for case in defect_cases
                    if case["expected_repair_required"]
                ],
                "schedule_generated",
            ),
            "report_generation_rate": _rate(defect_cases, "report_generated"),
            "average_retrieved_citations_per_case": round(
                sum(case["citation_count"] for case in defect_cases) / len(defect_cases),
                3,
            )
            if defect_cases
            else 0.0,
        }
    return metrics


def _rate(cases: list[dict[str, Any]], field: str) -> float:
    if not cases:
        return 0.0
    return round(sum(1 for case in cases if case[field]) / len(cases), 3)


def _failure_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    stages = [
        "pass",
        "vision",
        "severity",
        "repair_decision",
        "standards_rag",
        "repair_rag",
        "scheduling",
        "report",
    ]
    counts = {stage: 0 for stage in stages}
    reason_counts: dict[str, int] = {}
    for case in cases:
        counts[case["primary_failure_stage"]] = (
            counts.get(case["primary_failure_stage"], 0) + 1
        )
        for reason in case["failure_reasons"]:
            reason_counts[reason["stage"]] = reason_counts.get(reason["stage"], 0) + 1
    return {
        "primary_stage_counts": counts,
        "reason_counts": reason_counts,
    }


def _failure_reasons(case: dict[str, Any]) -> list[dict[str, str]]:
    reasons = []
    if not case["defect_match"]:
        expected = case["expected_defect"]
        acceptable = case.get("acceptable_defects", [expected])
        expected_text = (
            expected
            if acceptable == [expected]
            else f"{expected} (acceptable: {acceptable})"
        )
        reasons.append(
            {
                "stage": "vision",
                "reason": (
                    f"Expected {expected_text} but observed "
                    f"{case['observed_defects']}."
                ),
            }
        )
    if case["defect_match"] and not case["severity_match"]:
        expected = case["expected_severity"]
        acceptable = case.get("acceptable_severities", [expected])
        expected_text = (
            expected
            if acceptable == [expected]
            else f"{expected} (acceptable: {acceptable})"
        )
        reasons.append(
            {
                "stage": "severity",
                "reason": (
                    f"Expected severity {expected_text} but predicted "
                    f"{case['predicted_severity']}."
                ),
            }
        )
    if not case["repair_required_match"]:
        reasons.append(
            {
                "stage": "repair_decision",
                "reason": (
                    f"Expected repair_required={case['expected_repair_required']} "
                    f"but predicted {case['predicted_repair_required']}."
                ),
            }
        )
    if case["defect_match"] and not case["standard_retrieval_hit"]:
        reasons.append(
            {
                "stage": "standards_rag",
                "reason": (
                    f"No standard citation matched expected defect "
                    f"{case['expected_defect']}."
                ),
            }
        )
    if case["expected_repair_required"] and case["defect_match"] and not case["repair_precedent_hit"]:
        reasons.append(
            {
                "stage": "repair_rag",
                "reason": (
                    f"No repair precedent matched expected defect "
                    f"{case['expected_defect']}."
                ),
            }
        )
    if case["expected_repair_required"] and not case["schedule_generated"]:
        reasons.append(
            {
                "stage": "scheduling",
                "reason": "Repair was expected, but no schedule was generated.",
            }
        )
    if not case["report_generated"]:
        reasons.append(
            {
                "stage": "report",
                "reason": "No rendered report was produced.",
            }
        )
    return reasons


def _primary_failure_stage(failure_reasons: list[dict[str, str]]) -> str:
    if not failure_reasons:
        return "pass"
    order = [
        "vision",
        "severity",
        "repair_decision",
        "standards_rag",
        "repair_rag",
        "scheduling",
        "report",
    ]
    stages = {reason["stage"] for reason in failure_reasons}
    return next(stage for stage in order if stage in stages)


def _normalize_defect(defect_type: str) -> str:
    return DEFECT_ALIASES.get(defect_type, defect_type)


def _acceptable_defects(
    image_id: str,
    expected_defect: str,
    *,
    use_reviewed_taxonomy: bool,
) -> set[str]:
    if not use_reviewed_taxonomy:
        return {expected_defect}
    return REVIEWED_ACCEPTABLE_DEFECTS.get(image_id, {expected_defect})


def _acceptable_severities(
    image_id: str,
    expected_severity: str,
    *,
    use_reviewed_taxonomy: bool,
) -> set[str]:
    if not use_reviewed_taxonomy:
        return {expected_severity}
    return REVIEWED_ACCEPTABLE_SEVERITIES.get(image_id, {expected_severity})


def _citation_matches(citation, expected_defect: str) -> bool:
    text = f"{citation.document_id} {citation.title} {citation.excerpt}"
    return _text_matches_defect(text, expected_defect)


def _text_matches_defect(text: str, expected_defect: str | set[str]) -> bool:
    if isinstance(expected_defect, set):
        return any(_text_matches_defect(text, defect) for defect in expected_defect)

    normalized = text.lower().replace("-", "_")
    terms = DEFECT_TERMS.get(
        expected_defect,
        [expected_defect, expected_defect.replace("_", " ")],
    )
    return any(term.lower().replace("-", "_") in normalized for term in terms)


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics = result["metrics"]
    lines = [
        "# Bridge Dataset Eval",
        "",
        f"Cases: {result['case_count']}",
        f"Image analyzer: {result.get('image_analyzer', 'metadata')}",
        f"Image prompt profile: {result.get('image_prompt_profile') or 'default'}",
        f"Image detail: {result.get('image_detail') or 'default'}",
        f"Image tiling: {result.get('image_tiling', 'none')}",
        f"Roboflow confidence threshold: {result.get('roboflow_confidence_threshold', 0.25)}",
        f"Roboflow backend: {result.get('roboflow_backend') or 'default'}",
        f"Roboflow class mapping profile: {result.get('roboflow_class_mapping_profile') or 'default'}",
        f"Roboflow tiling: {result.get('roboflow_tiling', 'none')}",
        f"Roboflow class thresholds: {result.get('roboflow_class_thresholds') or 'none'}",
        f"Roboflow inference confidence: {result.get('roboflow_inference_confidence') or 'default'}",
        f"Roboflow inference IoU threshold: {result.get('roboflow_inference_iou_threshold') or 'default'}",
        f"Vision verifier: {result.get('vision_verifier', 'none')}",
        f"Verification confidence threshold: {result.get('verification_confidence_threshold', 0.55)}",
        f"Verifier prompt profile: {result.get('verifier_prompt_profile') or 'default'}",
        f"Reviewed taxonomy enabled: {result.get('reviewed_taxonomy_enabled', False)}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Metrics By Defect", ""])
    _append_metrics_by_defect_table(lines, result["metrics_by_defect"])
    lines.extend(["", "## Failure Attribution", ""])
    lines.extend(
        [
            "| Primary Stage | Count |",
            "| --- | ---: |",
        ]
    )
    for stage, count in result["failure_summary"]["primary_stage_counts"].items():
        lines.append(f"| {stage} | {count} |")

    lines.extend(["", "## Failed Cases", ""])
    failed_cases = [
        case
        for case in result["cases"]
        if case["primary_failure_stage"] != "pass"
    ][:25]
    if not failed_cases:
        lines.append("No failed cases in the displayed criteria.")
    for case in failed_cases:
        lines.append(
            f"- {case['image_id']}: expected {case['expected_defect']} / "
            f"{case['expected_severity']}, observed {case['observed_defects']} / "
            f"{case['predicted_severity']}; primary_stage="
            f"{case['primary_failure_stage']}"
        )
        for reason in case["failure_reasons"]:
            lines.append(f"  - {reason['stage']}: {reason['reason']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_case_review_markdown(
    path: Path,
    result: dict[str, Any],
    *,
    failed_limit: int,
    passing_limit: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    failed_cases = [
        case
        for case in result["cases"]
        if case["primary_failure_stage"] != "pass"
    ][: max(0, failed_limit)]
    passing_cases = [
        case
        for case in result["cases"]
        if case["primary_failure_stage"] == "pass"
    ][: max(0, passing_limit)]

    lines = [
        "# Bridge Pipeline Case Review",
        "",
        f"Cases evaluated: {result['case_count']}",
        f"Image analyzer: {result.get('image_analyzer', 'metadata')}",
        f"Vision verifier: {result.get('vision_verifier', 'none')}",
        f"Reviewed taxonomy enabled: {result.get('reviewed_taxonomy_enabled', False)}",
        "",
        "## Metrics",
        "",
    ]
    for key, value in result["metrics"].items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Metrics By Defect", ""])
    _append_metrics_by_defect_table(lines, result["metrics_by_defect"])

    lines.extend(["", "## Failure Summary", ""])
    for stage, count in result["failure_summary"]["primary_stage_counts"].items():
        lines.append(f"- {stage}: {count}")

    lines.extend(["", "## Failed Case Review", ""])
    if not failed_cases:
        lines.append("No failed cases selected for review.")
    for case in failed_cases:
        _append_case_review(lines, case)

    lines.extend(["", "## Passing Case Samples", ""])
    if not passing_cases:
        lines.append("No passing cases selected for review.")
    for case in passing_cases:
        _append_case_review(lines, case)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_metrics_by_defect_table(
    lines: list[str],
    metrics_by_defect: dict[str, dict[str, float | int]],
) -> None:
    lines.extend(
        [
            "| Defect | Cases | Defect Acc. | Severity Acc. | Repair Decision Acc. | Standard Hit | Repair Hit | Schedule Rate | Report Rate | Avg Citations |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for defect_type, metrics in metrics_by_defect.items():
        lines.append(
            f"| {defect_type} | {metrics['case_count']} | "
            f"{metrics['defect_accuracy']} | "
            f"{metrics['severity_accuracy']} | "
            f"{metrics['repair_required_accuracy']} | "
            f"{metrics['standard_retrieval_hit_rate']} | "
            f"{metrics['repair_precedent_hit_rate']} | "
            f"{metrics['schedule_generation_rate']} | "
            f"{metrics['report_generation_rate']} | "
            f"{metrics['average_retrieved_citations_per_case']} |"
        )


def _append_case_review(lines: list[str], case: dict[str, Any]) -> None:
    lines.extend(
        [
            f"### {case['image_id']}",
            "",
            f"- File: {case['file_path']}",
            f"- Primary stage: {case['primary_failure_stage']}",
            f"- Expected: {case['expected_defect']} / {case['expected_severity']}",
            (
                f"- Predicted: {case['observed_defects']} / "
                f"{case['predicted_severity']}"
            ),
            (
                f"- Repair required: expected={case['expected_repair_required']}, "
                f"predicted={case['predicted_repair_required']}"
            ),
            "",
            "Observations:",
        ]
    )
    for observation in case["observations"]:
        lines.append(
            "- "
            f"{observation['defect_type']} "
            f"(confidence {observation['confidence']:.0%}, "
            f"severity_label={observation.get('severity_label') or 'none'}): "
            f"{observation['description']}"
        )

    lines.extend(
        [
            "",
            "RAG:",
            f"- Standards: {', '.join(case['standard_citation_ids']) or 'none'}",
            f"- Repair precedents: {', '.join(case['repair_precedent_ids']) or 'none'}",
            "",
            "Maintenance:",
            f"- Action: {case['maintenance_action']}",
            f"- Duration: {case['maintenance_duration_hours']:g}h",
            f"- Materials: {', '.join(case['maintenance_materials']) or 'none'}",
            f"- Equipment: {', '.join(case['maintenance_equipment']) or 'none'}",
            f"- Permits: {', '.join(case['maintenance_permits']) or 'none'}",
            "",
            "Schedule:",
        ]
    )
    if case["schedule_window"]:
        window = case["schedule_window"]
        lines.append(
            f"- Window: {window['start']} to {window['end']} "
            f"(score {window['total_score']})"
        )
    else:
        lines.append("- Window: none")

    if case["schedule_context_summary"]:
        for item in case["schedule_context_summary"]:
            lines.append(f"- Context: {item}")
    if case["schedule_tradeoffs"]:
        for item in case["schedule_tradeoffs"]:
            lines.append(f"- Tradeoff: {item}")

    if case["failure_reasons"]:
        lines.extend(["", "Failure reasons:"])
        for reason in case["failure_reasons"]:
            lines.append(f"- {reason['stage']}: {reason['reason']}")

    if case["maintenance_risks"]:
        lines.extend(["", "Maintenance risks:"])
        for risk in case["maintenance_risks"]:
            lines.append(f"- {risk}")

    lines.append("")


def _json_default(value: Any) -> Any:
    try:
        return asdict(value)
    except TypeError:
        return str(value)


def main() -> None:
    result = run_bridge_dataset_eval(build_parser().parse_args())
    print(json.dumps({"case_count": result["case_count"], "metrics": result["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
