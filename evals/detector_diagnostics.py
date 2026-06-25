from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


GT_COLOR = (40, 190, 40)
PRED_COLOR = (230, 80, 60)
MISS_COLOR = (245, 150, 20)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create visual diagnostics from a detector eval JSON file."
    )
    parser.add_argument(
        "--detector-eval-json",
        default="artifacts/evals/roboflow_detector_eval_limit5_bridge_mapping.json",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/evals/detector_diagnostics",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=None,
        help="Prediction threshold to visualize. Defaults to eval best_threshold.",
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=None,
        help="IoU threshold for matching. Defaults to eval iou_threshold.",
    )
    parser.add_argument(
        "--defect-type",
        default=None,
        help="Optional defect class to export, for example spalling.",
    )
    parser.add_argument(
        "--crop-padding",
        type=int,
        default=64,
        help="Pixels around missed ground-truth boxes in crop outputs.",
    )
    return parser


def run_detector_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    eval_path = Path(args.detector_eval_json)
    result = json.loads(eval_path.read_text(encoding="utf-8"))
    threshold = (
        args.confidence_threshold
        if args.confidence_threshold is not None
        else float(result["best_threshold"])
    )
    iou_threshold = (
        args.iou_threshold
        if args.iou_threshold is not None
        else float(result["iou_threshold"])
    )
    output_dir = Path(args.output_dir)
    overlay_dir = output_dir / "overlays"
    crop_dir = output_dir / "missed_crops"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError(
            "Detector diagnostics require Pillow. Install requirements and retry."
        ) from exc

    cases = []
    summary = {
        "case_count": 0,
        "missed_count": 0,
        "false_positive_count": 0,
        "overlay_count": 0,
        "crop_count": 0,
    }
    for case in result["cases"]:
        image_path = Path(case["file_path"])
        if not image_path.exists():
            continue
        expected_boxes = _filter_defect(case["expected_boxes"], args.defect_type)
        predictions = [
            prediction
            for prediction in _filter_defect(case["predictions"], args.defect_type)
            if prediction["confidence"] >= threshold
        ]
        matches = _match_boxes(expected_boxes, predictions, iou_threshold)
        missed = [
            expected
            for index, expected in enumerate(expected_boxes)
            if index not in matches["matched_expected"]
        ]
        false_positives = [
            prediction
            for index, prediction in enumerate(predictions)
            if index not in matches["matched_predictions"]
        ]
        if not missed and not false_positives:
            continue

        with Image.open(image_path) as image:
            rgb_image = image.convert("RGB")
            overlay = rgb_image.copy()
            draw = ImageDraw.Draw(overlay)
            _draw_expected(draw, expected_boxes, missed)
            _draw_predictions(draw, predictions, false_positives)
            overlay_path = overlay_dir / f"{_safe_name(case['image_id'])}_overlay.jpg"
            overlay.save(overlay_path, quality=92)

            crop_paths = []
            for index, expected in enumerate(missed, start=1):
                crop_path = (
                    crop_dir
                    / expected["defect_type"]
                    / f"{_safe_name(case['image_id'])}_{index:03}_{_safe_name(expected.get('annotation_id') or 'annotation')}.jpg"
                )
                crop_path.parent.mkdir(parents=True, exist_ok=True)
                crop = rgb_image.crop(
                    _padded_crop_box(
                        expected["box"],
                        rgb_image.size,
                        padding=args.crop_padding,
                    )
                )
                crop.save(crop_path, quality=92)
                crop_paths.append(str(crop_path))

        case_result = {
            "image_id": case["image_id"],
            "file_path": case["file_path"],
            "overlay_path": str(overlay_path),
            "missed": missed,
            "false_positives": false_positives,
            "missed_crop_paths": crop_paths,
        }
        cases.append(case_result)
        summary["case_count"] += 1
        summary["missed_count"] += len(missed)
        summary["false_positive_count"] += len(false_positives)
        summary["overlay_count"] += 1
        summary["crop_count"] += len(crop_paths)

    diagnostic = {
        "source_eval": str(eval_path),
        "output_dir": str(output_dir),
        "confidence_threshold": threshold,
        "iou_threshold": iou_threshold,
        "defect_type": args.defect_type,
        "summary": summary,
        "cases": cases,
    }
    _write_json(output_dir / "diagnostics.json", diagnostic)
    _write_markdown(output_dir / "diagnostics.md", diagnostic)
    return diagnostic


def _filter_defect(items: list[dict[str, Any]], defect_type: str | None) -> list[dict[str, Any]]:
    if defect_type is None:
        return items
    return [item for item in items if item["defect_type"] == defect_type]


def _match_boxes(
    expected_boxes: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    iou_threshold: float,
) -> dict[str, set[int]]:
    matched_expected: set[int] = set()
    matched_predictions: set[int] = set()
    for prediction_index, prediction in sorted(
        enumerate(predictions),
        key=lambda item: item[1]["confidence"],
        reverse=True,
    ):
        best_index = None
        best_iou = 0.0
        for expected_index, expected in enumerate(expected_boxes):
            if expected_index in matched_expected:
                continue
            if expected["defect_type"] != prediction["defect_type"]:
                continue
            overlap = _iou(expected["box"], prediction["box"])
            if overlap > best_iou:
                best_iou = overlap
                best_index = expected_index
        if best_index is not None and best_iou >= iou_threshold:
            matched_expected.add(best_index)
            matched_predictions.add(prediction_index)
    return {
        "matched_expected": matched_expected,
        "matched_predictions": matched_predictions,
    }


def _draw_expected(draw, expected_boxes: list[dict[str, Any]], missed: list[dict[str, Any]]) -> None:
    missed_ids = {id(item) for item in missed}
    for expected in expected_boxes:
        color = MISS_COLOR if id(expected) in missed_ids else GT_COLOR
        _draw_box(draw, expected["box"], color, f"GT {expected['defect_type']}")


def _draw_predictions(draw, predictions: list[dict[str, Any]], false_positives: list[dict[str, Any]]) -> None:
    false_positive_ids = {id(item) for item in false_positives}
    for prediction in predictions:
        label = f"P {prediction['defect_type']} {prediction['confidence']:.2f}"
        color = PRED_COLOR if id(prediction) in false_positive_ids else GT_COLOR
        _draw_box(draw, prediction["box"], color, label)


def _draw_box(
    draw,
    box: list[int] | tuple[int, int, int, int],
    color: tuple[int, int, int],
    label: str,
) -> None:
    x, y, width, height = [int(value) for value in box]
    draw.rectangle((x, y, x + width, y + height), outline=color, width=5)
    draw.rectangle((x, max(0, y - 22), x + max(140, len(label) * 9), y), fill=color)
    draw.text((x + 4, max(0, y - 20)), label, fill=(255, 255, 255))


def _padded_crop_box(
    box: list[int] | tuple[int, int, int, int],
    image_size: tuple[int, int],
    *,
    padding: int,
) -> tuple[int, int, int, int]:
    x, y, width, height = [int(value) for value in box]
    image_width, image_height = image_size
    return (
        max(0, x - padding),
        max(0, y - padding),
        min(image_width, x + width + padding),
        min(image_height, y + height + padding),
    )


def _iou(
    left: list[int] | tuple[int, int, int, int],
    right: list[int] | tuple[int, int, int, int],
) -> float:
    left_x, left_y, left_width, left_height = [int(value) for value in left]
    right_x, right_y, right_width, right_height = [int(value) for value in right]
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


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    summary = result["summary"]
    lines = [
        "# Detector Diagnostics",
        "",
        f"Source eval: {result['source_eval']}",
        f"Confidence threshold: {result['confidence_threshold']}",
        f"IoU threshold: {result['iou_threshold']}",
        f"Defect type: {result['defect_type'] or 'all'}",
        "",
        "## Summary",
        "",
        f"- Cases with diagnostics: {summary['case_count']}",
        f"- Missed boxes: {summary['missed_count']}",
        f"- False positives: {summary['false_positive_count']}",
        f"- Overlays: {summary['overlay_count']}",
        f"- Missed crops: {summary['crop_count']}",
        "",
        "## Cases",
        "",
    ]
    if not result["cases"]:
        lines.append("No missed detections or false positives for the selected filters.")
    for case in result["cases"]:
        lines.append(
            f"- {case['image_id']}: missed {len(case['missed'])}, "
            f"false positives {len(case['false_positives'])}, overlay `{case['overlay_path']}`"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def main() -> None:
    result = run_detector_diagnostics(build_parser().parse_args())
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
