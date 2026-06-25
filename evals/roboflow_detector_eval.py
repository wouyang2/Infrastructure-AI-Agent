from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agents.helpers.image_analyzer import ImageAnalyzer, build_image_analyzer


DEFECT_ALIASES = {
    "corrosion_staining": "corrosion",
    "stain": "corrosion",
    "rust": "corrosion",
    "corrosion staining": "corrosion",
    "efflorescence": "leak",
    "water_leak": "leak",
    "water leak": "leak",
    "exposed-bar": "exposed_rebar",
    "exposed bar": "exposed_rebar",
    "rebar exposure": "exposed_rebar",
    "rebar exposed": "exposed_rebar",
    "normal/no_defect": "unknown",
    "normal": "unknown",
    "none": "unknown",
    "no_defect": "unknown",
    "no defect": "unknown",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate raw bridge defect detector outputs against annotations."
    )
    parser.add_argument("--metadata-csv", default="data/bridge_image/metadata.csv")
    parser.add_argument("--annotations-csv", default="data/bridge_image/annotations.csv")
    parser.add_argument("--output-json", default="artifacts/evals/roboflow_detector_eval.json")
    parser.add_argument("--output-md", default="artifacts/evals/roboflow_detector_eval.md")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--image-analyzer",
        choices=["metadata", "heuristic", "openai", "roboflow"],
        default="roboflow",
    )
    parser.add_argument(
        "--thresholds",
        default="0.1,0.25,0.5,0.75",
        help="Comma-separated confidence thresholds to score.",
    )
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    parser.add_argument(
        "--roboflow-backend",
        choices=["auto", "inference", "http"],
        default=None,
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
        help=(
            "Model-level Roboflow confidence. Defaults to the lowest eval threshold "
            "so threshold sweeps can see low-confidence predictions."
        ),
    )
    parser.add_argument(
        "--roboflow-inference-iou-threshold",
        type=float,
        default=None,
        help="Model-level Roboflow NMS IoU threshold. Defaults to 0.3.",
    )
    parser.add_argument(
        "--image-prompt-profile",
        default=None,
        help="OpenAI image prompt profile used when --image-analyzer openai is selected.",
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
    )
    return parser


def run_detector_eval(
    args: argparse.Namespace,
    *,
    image_analyzer: ImageAnalyzer | None = None,
) -> dict[str, Any]:
    thresholds = _parse_thresholds(args.thresholds)
    analyzer = image_analyzer or build_image_analyzer(
        args.image_analyzer,
        annotations_path=args.annotations_csv,
        image_prompt_profile=getattr(args, "image_prompt_profile", None),
        image_detail=getattr(args, "image_detail", None),
        image_tiling=getattr(args, "image_tiling", "none"),
        roboflow_confidence_threshold=min(thresholds),
        roboflow_backend=getattr(args, "roboflow_backend", None),
        roboflow_class_mapping_profile=getattr(
            args,
            "roboflow_class_mapping_profile",
            None,
        ),
        roboflow_tiling=getattr(args, "roboflow_tiling", "none"),
        roboflow_class_thresholds=getattr(args, "roboflow_class_thresholds", None),
        roboflow_inference_confidence=(
            getattr(args, "roboflow_inference_confidence", None) or min(thresholds)
        ),
        roboflow_inference_iou_threshold=getattr(
            args,
            "roboflow_inference_iou_threshold",
            None,
        ),
    )
    metadata_rows = _load_metadata_rows(
        Path(args.metadata_csv),
        offset=getattr(args, "offset", 0),
        limit=args.limit,
    )
    annotations_by_image = _load_annotations(Path(args.annotations_csv))

    cases = []
    for row in metadata_rows:
        image_id = row["image_id"]
        expected_boxes = annotations_by_image.get(image_id, [])
        findings = analyzer.analyze(row["file_path"], row.get("asset_type", "bridge"))
        predictions = [_prediction_from_finding(finding) for finding in findings]
        predictions = [prediction for prediction in predictions if prediction is not None]
        cases.append(
            {
                "image_id": image_id,
                "file_path": row["file_path"],
                "expected_boxes": expected_boxes,
                "predictions": predictions,
            }
        )

    threshold_metrics = {
        str(threshold): _score_cases(cases, threshold, args.iou_threshold)
        for threshold in thresholds
    }
    best_threshold = _best_threshold(threshold_metrics)
    result = {
        "image_analyzer": args.image_analyzer,
        "roboflow_class_mapping_profile": getattr(
            args,
            "roboflow_class_mapping_profile",
            None,
        ),
        "roboflow_tiling": getattr(args, "roboflow_tiling", "none"),
        "roboflow_class_thresholds": getattr(args, "roboflow_class_thresholds", None),
        "roboflow_inference_confidence": (
            getattr(args, "roboflow_inference_confidence", None) or min(thresholds)
        ),
        "roboflow_inference_iou_threshold": getattr(
            args,
            "roboflow_inference_iou_threshold",
            None,
        ),
        "thresholds": thresholds,
        "iou_threshold": args.iou_threshold,
        "case_count": len(cases),
        "offset": getattr(args, "offset", 0),
        "annotation_count": sum(len(case["expected_boxes"]) for case in cases),
        "prediction_count": sum(len(case["predictions"]) for case in cases),
        "best_threshold": best_threshold,
        "metrics_by_threshold": threshold_metrics,
        "cases": cases,
    }
    _write_json(Path(args.output_json), result)
    _write_markdown(Path(args.output_md), result)
    return result


def _parse_thresholds(value: str | list[float]) -> list[float]:
    if isinstance(value, list):
        thresholds = [float(item) for item in value]
    else:
        thresholds = [float(item.strip()) for item in value.split(",") if item.strip()]
    if not thresholds:
        raise ValueError("At least one confidence threshold is required.")
    for threshold in thresholds:
        if threshold < 0 or threshold > 1:
            raise ValueError("Confidence thresholds must be between 0 and 1.")
    return sorted(set(thresholds))


def _load_metadata_rows(
    path: Path,
    *,
    offset: int = 0,
    limit: int | None,
) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if offset < 0:
        raise ValueError("Offset must be zero or greater.")
    rows = rows[offset:]
    if limit is not None:
        return rows[:limit]
    return rows


def _load_annotations(path: Path) -> dict[str, list[dict[str, Any]]]:
    annotations: dict[str, list[dict[str, Any]]] = {}
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            box = _box_from_row(row)
            defect_type = _normalize_defect(row.get("defect_type", "unknown"))
            if not box or defect_type == "unknown":
                continue
            annotations.setdefault(row["image_id"], []).append(
                {
                    "annotation_id": row.get("annotation_id"),
                    "defect_type": defect_type,
                    "box": box,
                    "severity_label": row.get("severity_label"),
                }
            )
    return annotations


def _prediction_from_finding(finding) -> dict[str, Any] | None:
    defect_type = _normalize_defect(finding.defect_type)
    if defect_type == "unknown" or not finding.bounding_box:
        return None
    return {
        "defect_type": defect_type,
        "confidence": round(float(finding.confidence), 6),
        "box": tuple(int(value) for value in finding.bounding_box),
        "description": finding.description,
    }


def _box_from_row(row: dict[str, str]) -> tuple[int, int, int, int] | None:
    try:
        return (
            round(float(row["x"])),
            round(float(row["y"])),
            round(float(row["width"])),
            round(float(row["height"])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_defect(defect_type: str) -> str:
    normalized = defect_type.strip().lower().replace("_", " ").replace("-", " ")
    if normalized in {"crack", "spalling", "corrosion", "leak", "exposed rebar", "unknown"}:
        return "exposed_rebar" if normalized == "exposed rebar" else normalized
    return DEFECT_ALIASES.get(normalized, defect_type.strip().lower())


def _score_cases(
    cases: list[dict[str, Any]],
    confidence_threshold: float,
    iou_threshold: float,
) -> dict[str, Any]:
    totals = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    per_class: dict[str, dict[str, int]] = {}
    scored_cases = []

    for case in cases:
        predictions = [
            prediction
            for prediction in case["predictions"]
            if prediction["confidence"] >= confidence_threshold
        ]
        case_score, class_scores = _match_boxes(
            case["expected_boxes"],
            predictions,
            iou_threshold,
        )
        for key in totals:
            totals[key] += case_score[key]
        for defect_type, scores in class_scores.items():
            class_total = per_class.setdefault(
                defect_type,
                {"true_positives": 0, "false_positives": 0, "false_negatives": 0},
            )
            for key, value in scores.items():
                class_total[key] += value
        scored_cases.append(
            {
                "image_id": case["image_id"],
                "expected_count": len(case["expected_boxes"]),
                "prediction_count": len(predictions),
                **case_score,
            }
        )

    return {
        **totals,
        **_classification_metrics(**totals),
        "per_class": {
            defect_type: {
                **scores,
                **_classification_metrics(**scores),
            }
            for defect_type, scores in sorted(per_class.items())
        },
        "cases": scored_cases,
    }


def _match_boxes(
    expected_boxes: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    iou_threshold: float,
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    matched_expected: set[int] = set()
    scores = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    per_class: dict[str, dict[str, int]] = {}

    for prediction in sorted(predictions, key=lambda item: item["confidence"], reverse=True):
        best_index = None
        best_iou = 0.0
        for index, expected in enumerate(expected_boxes):
            if index in matched_expected:
                continue
            if expected["defect_type"] != prediction["defect_type"]:
                continue
            overlap = _iou(expected["box"], prediction["box"])
            if overlap > best_iou:
                best_iou = overlap
                best_index = index

        if best_index is not None and best_iou >= iou_threshold:
            matched_expected.add(best_index)
            _increment(scores, per_class, prediction["defect_type"], "true_positives")
        else:
            _increment(scores, per_class, prediction["defect_type"], "false_positives")

    for index, expected in enumerate(expected_boxes):
        if index not in matched_expected:
            _increment(scores, per_class, expected["defect_type"], "false_negatives")

    return scores, per_class


def _increment(
    totals: dict[str, int],
    per_class: dict[str, dict[str, int]],
    defect_type: str,
    key: str,
) -> None:
    totals[key] += 1
    class_scores = per_class.setdefault(
        defect_type,
        {"true_positives": 0, "false_positives": 0, "false_negatives": 0},
    )
    class_scores[key] += 1


def _iou(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> float:
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    intersection_x1 = max(left_x, right_x)
    intersection_y1 = max(left_y, right_y)
    intersection_x2 = min(left_x + left_width, right_x + right_width)
    intersection_y2 = min(left_y + left_height, right_y + right_height)
    intersection_width = max(0, intersection_x2 - intersection_x1)
    intersection_height = max(0, intersection_y2 - intersection_y1)
    intersection_area = intersection_width * intersection_height
    union_area = left_width * left_height + right_width * right_height - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def _classification_metrics(
    true_positives: int,
    false_positives: int,
    false_negatives: int,
) -> dict[str, float]:
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def _best_threshold(metrics_by_threshold: dict[str, dict[str, Any]]) -> float:
    threshold, _ = max(
        metrics_by_threshold.items(),
        key=lambda item: (item[1]["f1"], item[1]["recall"], item[1]["precision"]),
    )
    return float(threshold)


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Roboflow Detector Eval",
        "",
        f"Image analyzer: {result['image_analyzer']}",
        f"Roboflow class mapping profile: {result.get('roboflow_class_mapping_profile') or 'default'}",
        f"Roboflow tiling: {result.get('roboflow_tiling', 'none')}",
        f"Roboflow class thresholds: {result.get('roboflow_class_thresholds') or 'none'}",
        f"Roboflow inference confidence: {result.get('roboflow_inference_confidence')}",
        f"Roboflow inference IoU threshold: {result.get('roboflow_inference_iou_threshold') or 'default'}",
        f"Cases: {result['case_count']}",
        f"Offset: {result.get('offset', 0)}",
        f"Annotations: {result['annotation_count']}",
        f"Predictions: {result['prediction_count']}",
        f"IoU threshold: {result['iou_threshold']}",
        f"Best threshold: {result['best_threshold']}",
        "",
        "## Threshold Metrics",
        "",
        "| Threshold | Precision | Recall | F1 | TP | FP | FN |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for threshold, metrics in result["metrics_by_threshold"].items():
        lines.append(
            f"| {threshold} | {metrics['precision']} | {metrics['recall']} | "
            f"{metrics['f1']} | {metrics['true_positives']} | "
            f"{metrics['false_positives']} | {metrics['false_negatives']} |"
        )

    best = result["metrics_by_threshold"][str(result["best_threshold"])]
    lines.extend(
        [
            "",
            "## Per-Class Metrics",
            "",
            "| Defect | Precision | Recall | F1 | TP | FP | FN |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for defect_type, metrics in best["per_class"].items():
        lines.append(
            f"| {defect_type} | {metrics['precision']} | {metrics['recall']} | "
            f"{metrics['f1']} | {metrics['true_positives']} | "
            f"{metrics['false_positives']} | {metrics['false_negatives']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _json_default(value: Any) -> Any:
    try:
        return asdict(value)
    except TypeError:
        if isinstance(value, tuple):
            return list(value)
        return str(value)


def main() -> None:
    result = run_detector_eval(build_parser().parse_args())
    print(
        json.dumps(
            {
                "case_count": result["case_count"],
                "best_threshold": result["best_threshold"],
                "best_metrics": result["metrics_by_threshold"][
                    str(result["best_threshold"])
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
