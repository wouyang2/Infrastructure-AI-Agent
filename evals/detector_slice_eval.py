from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze detector recall by annotation slices such as edge-touching boxes."
    )
    parser.add_argument(
        "--detector-eval-json",
        default="artifacts/evals/roboflow_detector_eval_limit5_bridge_mapping.json",
    )
    parser.add_argument("--metadata-csv", default="data/bridge_image/metadata.csv")
    parser.add_argument("--output-json", default="artifacts/evals/detector_slice_eval.json")
    parser.add_argument("--output-md", default="artifacts/evals/detector_slice_eval.md")
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=None,
        help="Prediction threshold to analyze. Defaults to eval best_threshold.",
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=None,
        help="IoU threshold for matching. Defaults to eval iou_threshold.",
    )
    parser.add_argument(
        "--edge-tolerance",
        type=float,
        default=2.0,
        help="Pixels from image border considered edge-touching.",
    )
    parser.add_argument(
        "--small-area-ratio",
        type=float,
        default=0.01,
        help="Box area/image area threshold for small-box slice.",
    )
    return parser


def run_detector_slice_eval(args: argparse.Namespace) -> dict[str, Any]:
    detector_eval = json.loads(Path(args.detector_eval_json).read_text(encoding="utf-8"))
    metadata_by_image = _load_metadata(Path(args.metadata_csv))
    confidence_threshold = (
        args.confidence_threshold
        if args.confidence_threshold is not None
        else float(detector_eval["best_threshold"])
    )
    iou_threshold = (
        args.iou_threshold
        if args.iou_threshold is not None
        else float(detector_eval["iou_threshold"])
    )

    slice_records: dict[str, list[bool]] = {
        "edge_touching": [],
        "non_edge": [],
        "small_box": [],
        "large_box": [],
    }
    class_records: dict[str, list[bool]] = {}
    class_slice_records: dict[str, dict[str, list[bool]]] = {}
    cases = []

    for case in detector_eval["cases"]:
        metadata = metadata_by_image.get(case["image_id"], {})
        image_width = _float(metadata.get("width")) or 0.0
        image_height = _float(metadata.get("height")) or 0.0
        predictions = [
            prediction
            for prediction in case["predictions"]
            if prediction["confidence"] >= confidence_threshold
        ]
        matched_expected = _matched_expected_indices(
            case["expected_boxes"],
            predictions,
            iou_threshold,
        )
        expected_details = []
        for index, expected in enumerate(case["expected_boxes"]):
            edge_touching = _touches_edge(
                expected["box"],
                image_width,
                image_height,
                tolerance=args.edge_tolerance,
            )
            area_ratio = _area_ratio(expected["box"], image_width, image_height)
            small_box = area_ratio < args.small_area_ratio
            matched = index in matched_expected
            defect_type = expected["defect_type"]

            slice_records["edge_touching" if edge_touching else "non_edge"].append(matched)
            slice_records["small_box" if small_box else "large_box"].append(matched)
            class_records.setdefault(defect_type, []).append(matched)
            defect_slices = class_slice_records.setdefault(
                defect_type,
                {
                    "edge_touching": [],
                    "non_edge": [],
                    "small_box": [],
                    "large_box": [],
                },
            )
            defect_slices["edge_touching" if edge_touching else "non_edge"].append(matched)
            defect_slices["small_box" if small_box else "large_box"].append(matched)

            expected_details.append(
                {
                    "annotation_id": expected.get("annotation_id"),
                    "defect_type": defect_type,
                    "matched": matched,
                    "edge_touching": edge_touching,
                    "small_box": small_box,
                    "area_ratio": round(area_ratio, 6),
                }
            )
        cases.append(
            {
                "image_id": case["image_id"],
                "file_path": case["file_path"],
                "expected": expected_details,
            }
        )

    result = {
        "source_eval": str(args.detector_eval_json),
        "metadata_csv": str(args.metadata_csv),
        "confidence_threshold": confidence_threshold,
        "iou_threshold": iou_threshold,
        "edge_tolerance": args.edge_tolerance,
        "small_area_ratio": args.small_area_ratio,
        "slices": {name: _recall(values) for name, values in slice_records.items()},
        "classes": {name: _recall(values) for name, values in sorted(class_records.items())},
        "class_slices": {
            defect_type: {
                slice_name: _recall(values)
                for slice_name, values in slices.items()
            }
            for defect_type, slices in sorted(class_slice_records.items())
        },
        "cases": cases,
    }
    _write_json(Path(args.output_json), result)
    _write_markdown(Path(args.output_md), result)
    return result


def _load_metadata(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return {row["image_id"]: row for row in csv.DictReader(file)}


def _matched_expected_indices(
    expected_boxes: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    iou_threshold: float,
) -> set[int]:
    matched_expected: set[int] = set()
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
    return matched_expected


def _touches_edge(
    box: list[int] | tuple[int, int, int, int],
    image_width: float,
    image_height: float,
    *,
    tolerance: float,
) -> bool:
    x, y, width, height = [float(value) for value in box]
    return (
        x <= tolerance
        or y <= tolerance
        or x + width >= image_width - tolerance
        or y + height >= image_height - tolerance
    )


def _area_ratio(
    box: list[int] | tuple[int, int, int, int],
    image_width: float,
    image_height: float,
) -> float:
    if image_width <= 0 or image_height <= 0:
        return 0.0
    _, _, width, height = [float(value) for value in box]
    return (width * height) / (image_width * image_height)


def _iou(
    left: list[int] | tuple[int, int, int, int],
    right: list[int] | tuple[int, int, int, int],
) -> float:
    left_x, left_y, left_width, left_height = [float(value) for value in left]
    right_x, right_y, right_width, right_height = [float(value) for value in right]
    intersection_x1 = max(left_x, right_x)
    intersection_y1 = max(left_y, right_y)
    intersection_x2 = min(left_x + left_width, right_x + right_width)
    intersection_y2 = min(left_y + left_height, right_y + right_height)
    intersection_width = max(0.0, intersection_x2 - intersection_x1)
    intersection_height = max(0.0, intersection_y2 - intersection_y1)
    intersection_area = intersection_width * intersection_height
    union_area = left_width * left_height + right_width * right_height - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def _recall(values: list[bool]) -> dict[str, float | int]:
    total = len(values)
    matched = sum(1 for value in values if value)
    return {
        "matched": matched,
        "total": total,
        "recall": round(matched / total, 3) if total else 0.0,
    }


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except ValueError:
        return None


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Detector Slice Eval",
        "",
        f"Source eval: {result['source_eval']}",
        f"Confidence threshold: {result['confidence_threshold']}",
        f"IoU threshold: {result['iou_threshold']}",
        "",
        "## Annotation Slices",
        "",
        "| Slice | Matched | Total | Recall |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, metrics in result["slices"].items():
        lines.append(
            f"| {name} | {metrics['matched']} | {metrics['total']} | {metrics['recall']} |"
        )
    lines.extend(
        [
            "",
            "## Classes",
            "",
            "| Class | Matched | Total | Recall |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for name, metrics in result["classes"].items():
        lines.append(
            f"| {name} | {metrics['matched']} | {metrics['total']} | {metrics['recall']} |"
        )
    lines.extend(
        [
            "",
            "## Class Slices",
            "",
            "| Class | Slice | Matched | Total | Recall |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for defect_type, slices in result["class_slices"].items():
        for name, metrics in slices.items():
            if metrics["total"]:
                lines.append(
                    f"| {defect_type} | {name} | {metrics['matched']} | "
                    f"{metrics['total']} | {metrics['recall']} |"
                )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    result = run_detector_slice_eval(build_parser().parse_args())
    print(json.dumps({"slices": result["slices"], "classes": result["classes"]}, indent=2))


if __name__ == "__main__":
    main()
