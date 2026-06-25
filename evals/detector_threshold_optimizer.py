from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.roboflow_detector_eval import _classification_metrics, _match_boxes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find per-class confidence thresholds from a detector eval JSON."
    )
    parser.add_argument(
        "--detector-eval-json",
        default="artifacts/evals/roboflow_detector_eval_validation_limit20_sdkconf01.json",
    )
    parser.add_argument("--output-json", default="artifacts/evals/detector_thresholds.json")
    parser.add_argument("--output-md", default="artifacts/evals/detector_thresholds.md")
    parser.add_argument("--thresholds", default="0.1,0.2,0.25,0.3,0.4,0.5,0.6,0.75")
    parser.add_argument("--iou-threshold", type=float, default=None)
    return parser


def run_threshold_optimizer(args: argparse.Namespace) -> dict[str, Any]:
    detector_eval = json.loads(Path(args.detector_eval_json).read_text(encoding="utf-8"))
    thresholds = _parse_thresholds(args.thresholds)
    iou_threshold = (
        args.iou_threshold
        if args.iou_threshold is not None
        else float(detector_eval["iou_threshold"])
    )
    classes = sorted(
        {
            item["defect_type"]
            for case in detector_eval["cases"]
            for item in [*case["expected_boxes"], *case["predictions"]]
        }
    )
    per_class = {
        defect_type: _best_threshold_for_class(
            detector_eval["cases"],
            defect_type,
            thresholds,
            iou_threshold,
        )
        for defect_type in classes
    }
    class_thresholds = {
        defect_type: metrics["best_threshold"]
        for defect_type, metrics in per_class.items()
    }
    combined = _score_with_class_thresholds(
        detector_eval["cases"],
        class_thresholds,
        iou_threshold,
    )
    result = {
        "source_eval": str(args.detector_eval_json),
        "thresholds": thresholds,
        "iou_threshold": iou_threshold,
        "class_thresholds": class_thresholds,
        "per_class": per_class,
        "combined": combined,
    }
    _write_json(Path(args.output_json), result)
    _write_markdown(Path(args.output_md), result)
    return result


def _best_threshold_for_class(
    cases: list[dict[str, Any]],
    defect_type: str,
    thresholds: list[float],
    iou_threshold: float,
) -> dict[str, Any]:
    scored = {}
    for threshold in thresholds:
        class_cases = []
        for case in cases:
            class_cases.append(
                {
                    "expected_boxes": [
                        expected
                        for expected in case["expected_boxes"]
                        if expected["defect_type"] == defect_type
                    ],
                    "predictions": [
                        prediction
                        for prediction in case["predictions"]
                        if prediction["defect_type"] == defect_type
                        and prediction["confidence"] >= threshold
                    ],
                }
            )
        scored[str(threshold)] = _score_cases(class_cases, iou_threshold)
    best_threshold, best_metrics = max(
        scored.items(),
        key=lambda item: (
            item[1]["f1"],
            item[1]["recall"],
            item[1]["precision"],
        ),
    )
    return {
        "best_threshold": float(best_threshold),
        "best_metrics": best_metrics,
        "metrics_by_threshold": scored,
    }


def _score_with_class_thresholds(
    cases: list[dict[str, Any]],
    class_thresholds: dict[str, float],
    iou_threshold: float,
) -> dict[str, Any]:
    filtered_cases = []
    for case in cases:
        filtered_cases.append(
            {
                "expected_boxes": case["expected_boxes"],
                "predictions": [
                    prediction
                    for prediction in case["predictions"]
                    if prediction["confidence"]
                    >= class_thresholds.get(prediction["defect_type"], 1.0)
                ],
            }
        )
    return _score_cases(filtered_cases, iou_threshold)


def _score_cases(cases: list[dict[str, Any]], iou_threshold: float) -> dict[str, Any]:
    totals = {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
    for case in cases:
        scores, _ = _match_boxes(
            case["expected_boxes"],
            case["predictions"],
            iou_threshold,
        )
        for key in totals:
            totals[key] += scores[key]
    return {**totals, **_classification_metrics(**totals)}


def _parse_thresholds(value: str) -> list[float]:
    thresholds = [float(item.strip()) for item in value.split(",") if item.strip()]
    if not thresholds:
        raise ValueError("At least one threshold is required.")
    return sorted(set(thresholds))


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Detector Threshold Optimizer",
        "",
        f"Source eval: {result['source_eval']}",
        f"IoU threshold: {result['iou_threshold']}",
        "",
        "## Combined",
        "",
    ]
    combined = result["combined"]
    for key in ["precision", "recall", "f1", "true_positives", "false_positives", "false_negatives"]:
        lines.append(f"- {key}: {combined[key]}")
    lines.extend(
        [
            "",
            "## Per-Class Thresholds",
            "",
            "| Class | Threshold | Precision | Recall | F1 | TP | FP | FN |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for defect_type, metrics in result["per_class"].items():
        best = metrics["best_metrics"]
        lines.append(
            f"| {defect_type} | {metrics['best_threshold']} | {best['precision']} | "
            f"{best['recall']} | {best['f1']} | {best['true_positives']} | "
            f"{best['false_positives']} | {best['false_negatives']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    result = run_threshold_optimizer(build_parser().parse_args())
    print(
        json.dumps(
            {
                "class_thresholds": result["class_thresholds"],
                "combined": result["combined"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
