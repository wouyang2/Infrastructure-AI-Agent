from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit bridge image annotations for class balance and box geometry."
    )
    parser.add_argument("--metadata-csv", default="data/bridge_image/metadata.csv")
    parser.add_argument("--annotations-csv", default="data/bridge_image/annotations.csv")
    parser.add_argument("--output-dir", default="artifacts/evals/bridge_dataset_audit")
    parser.add_argument("--max-contact-sheet-items", type=int, default=24)
    parser.add_argument("--crop-padding", type=int, default=48)
    return parser


def run_bridge_dataset_audit(args: argparse.Namespace) -> dict[str, Any]:
    metadata_rows = _load_csv(Path(args.metadata_csv))
    annotation_rows = _load_csv(Path(args.annotations_csv))
    metadata_by_image_id = {row["image_id"]: row for row in metadata_rows}
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    annotations_by_defect: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in annotation_rows:
        image = metadata_by_image_id.get(row["image_id"])
        if not image:
            continue
        record = _annotation_record(row, image)
        annotations_by_defect[record["defect_type"]].append(record)

    class_metrics = {
        defect_type: _class_metrics(records)
        for defect_type, records in sorted(annotations_by_defect.items())
    }
    image_level = _image_level_metrics(metadata_rows, annotation_rows)
    contact_sheets = _write_contact_sheets(
        annotations_by_defect,
        output_dir / "contact_sheets",
        max_items=args.max_contact_sheet_items,
        crop_padding=args.crop_padding,
    )
    result = {
        "metadata_csv": str(args.metadata_csv),
        "annotations_csv": str(args.annotations_csv),
        "image_count": len(metadata_rows),
        "annotated_image_count": sum(
            1 for row in metadata_rows if row.get("has_annotations") == "true"
        ),
        "annotation_count": len(annotation_rows),
        "image_level": image_level,
        "class_metrics": class_metrics,
        "contact_sheets": contact_sheets,
    }
    _write_json(output_dir / "audit.json", result)
    _write_markdown(output_dir / "audit.md", result)
    return result


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def _annotation_record(row: dict[str, str], image: dict[str, str]) -> dict[str, Any]:
    image_width = _float(image.get("width")) or 0.0
    image_height = _float(image.get("height")) or 0.0
    x = _float(row.get("x")) or 0.0
    y = _float(row.get("y")) or 0.0
    width = _float(row.get("width")) or 0.0
    height = _float(row.get("height")) or 0.0
    image_area = image_width * image_height
    area = width * height
    return {
        "annotation_id": row["annotation_id"],
        "image_id": row["image_id"],
        "file_path": row["file_path"],
        "defect_type": row["defect_type"],
        "box": [round(x), round(y), round(width), round(height)],
        "image_width": image_width,
        "image_height": image_height,
        "area_ratio": area / image_area if image_area else 0.0,
        "width_ratio": width / image_width if image_width else 0.0,
        "height_ratio": height / image_height if image_height else 0.0,
        "aspect_ratio": width / height if height else 0.0,
        "touches_edge": _touches_edge(x, y, width, height, image_width, image_height),
    }


def _class_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    image_ids = {record["image_id"] for record in records}
    area_ratios = [record["area_ratio"] for record in records]
    width_ratios = [record["width_ratio"] for record in records]
    height_ratios = [record["height_ratio"] for record in records]
    aspect_ratios = [record["aspect_ratio"] for record in records]
    edge_count = sum(1 for record in records if record["touches_edge"])
    small_count = sum(1 for record in records if record["area_ratio"] < 0.01)
    return {
        "annotation_count": len(records),
        "image_count": len(image_ids),
        "edge_touching_count": edge_count,
        "edge_touching_rate": _round(edge_count / len(records) if records else 0.0),
        "small_box_count": small_count,
        "small_box_rate": _round(small_count / len(records) if records else 0.0),
        "area_ratio": _distribution(area_ratios),
        "width_ratio": _distribution(width_ratios),
        "height_ratio": _distribution(height_ratios),
        "aspect_ratio": _distribution(aspect_ratios),
    }


def _image_level_metrics(
    metadata_rows: list[dict[str, str]],
    annotation_rows: list[dict[str, str]],
) -> dict[str, Any]:
    annotations_by_image: dict[str, list[str]] = defaultdict(list)
    for row in annotation_rows:
        annotations_by_image[row["image_id"]].append(row["defect_type"])
    multi_defect_images = 0
    no_defect_images = 0
    for row in metadata_rows:
        defects = set(annotations_by_image.get(row["image_id"], []))
        if not defects:
            no_defect_images += 1
        if len(defects) > 1:
            multi_defect_images += 1
    return {
        "no_defect_image_count": no_defect_images,
        "multi_defect_image_count": multi_defect_images,
        "multi_defect_image_rate": _round(
            multi_defect_images / len(metadata_rows) if metadata_rows else 0.0
        ),
    }


def _write_contact_sheets(
    annotations_by_defect: dict[str, list[dict[str, Any]]],
    output_dir: Path,
    *,
    max_items: int,
    crop_padding: int,
) -> dict[str, str]:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    sheets = {}
    for defect_type, records in sorted(annotations_by_defect.items()):
        crops = []
        for record in _sample_records(records, max_items):
            path = Path(record["file_path"])
            if not path.exists():
                continue
            with Image.open(path) as image:
                rgb_image = image.convert("RGB")
                crop = rgb_image.crop(
                    _padded_crop_box(
                        record["box"],
                        rgb_image.size,
                        padding=crop_padding,
                    )
                )
                crop.thumbnail((220, 180))
                tile = Image.new("RGB", (240, 220), color=(245, 245, 245))
                tile.paste(crop, ((240 - crop.width) // 2, 10))
                draw = ImageDraw.Draw(tile)
                draw.text((10, 195), record["image_id"], fill=(20, 20, 20))
                crops.append(tile)
        if not crops:
            continue
        columns = 4
        rows = math.ceil(len(crops) / columns)
        sheet = Image.new("RGB", (columns * 240, rows * 220), color=(255, 255, 255))
        for index, tile in enumerate(crops):
            x = (index % columns) * 240
            y = (index // columns) * 220
            sheet.paste(tile, (x, y))
        output_path = output_dir / f"{_safe_name(defect_type)}_contact_sheet.jpg"
        sheet.save(output_path, quality=92)
        sheets[defect_type] = str(output_path)
    return sheets


def _sample_records(records: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    if len(records) <= max_items:
        return records
    step = len(records) / max_items
    return [records[math.floor(index * step)] for index in range(max_items)]


def _padded_crop_box(
    box: list[int],
    image_size: tuple[int, int],
    *,
    padding: int,
) -> tuple[int, int, int, int]:
    x, y, width, height = box
    image_width, image_height = image_size
    return (
        max(0, x - padding),
        max(0, y - padding),
        min(image_width, x + width + padding),
        min(image_height, y + height + padding),
    )


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "median": 0.0, "mean": 0.0, "max": 0.0}
    return {
        "min": _round(min(values)),
        "median": _round(median(values)),
        "mean": _round(sum(values) / len(values)),
        "max": _round(max(values)),
    }


def _touches_edge(
    x: float,
    y: float,
    width: float,
    height: float,
    image_width: float,
    image_height: float,
) -> bool:
    tolerance = 2.0
    return (
        x <= tolerance
        or y <= tolerance
        or x + width >= image_width - tolerance
        or y + height >= image_height - tolerance
    )


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except ValueError:
        return None


def _round(value: float) -> float:
    return round(value, 4)


def _write_json(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Bridge Dataset Audit",
        "",
        f"Images: {result['image_count']}",
        f"Annotated images: {result['annotated_image_count']}",
        f"Annotations: {result['annotation_count']}",
        "",
        "## Image-Level",
        "",
        f"- No-defect images: {result['image_level']['no_defect_image_count']}",
        f"- Multi-defect images: {result['image_level']['multi_defect_image_count']}",
        f"- Multi-defect image rate: {result['image_level']['multi_defect_image_rate']}",
        "",
        "## Classes",
        "",
        "| Defect | Boxes | Images | Edge Rate | Small Box Rate | Median Area Ratio | Contact Sheet |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for defect_type, metrics in result["class_metrics"].items():
        sheet = result["contact_sheets"].get(defect_type, "")
        lines.append(
            f"| {defect_type} | {metrics['annotation_count']} | "
            f"{metrics['image_count']} | {metrics['edge_touching_rate']} | "
            f"{metrics['small_box_rate']} | {metrics['area_ratio']['median']} | "
            f"`{sheet}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def main() -> None:
    result = run_bridge_dataset_audit(build_parser().parse_args())
    print(
        json.dumps(
            {
                "image_count": result["image_count"],
                "annotation_count": result["annotation_count"],
                "class_metrics": {
                    defect_type: {
                        "annotation_count": metrics["annotation_count"],
                        "image_count": metrics["image_count"],
                        "edge_touching_rate": metrics["edge_touching_rate"],
                        "small_box_rate": metrics["small_box_rate"],
                    }
                    for defect_type, metrics in result["class_metrics"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
