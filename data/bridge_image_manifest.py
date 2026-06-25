from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


IMAGE_METADATA_FIELDS = [
    "image_id",
    "file_path",
    "asset_id",
    "asset_type",
    "component",
    "defect_types",
    "primary_defect_type",
    "severity_label",
    "location_on_asset",
    "annotation_count",
    "has_annotations",
    "coco_image_id",
    "width",
    "height",
    "notes",
]

ANNOTATION_FIELDS = [
    "annotation_id",
    "image_id",
    "file_path",
    "asset_id",
    "asset_type",
    "component",
    "defect_type",
    "severity_label",
    "x",
    "y",
    "width",
    "height",
    "area",
    "coco_image_id",
    "coco_annotation_id",
]

DEFECT_TYPE_MAP = {
    "crack": "crack",
    "crack-spalling-efflorescenc-3qkp": "unknown",
    "corrosion": "corrosion",
    "efflorescence": "leak",
    "exposed-bar": "exposed_rebar",
    "rebar exposure": "exposed_rebar",
    "spalling": "spalling",
    "stain": "corrosion_staining",
}

DEFECT_PRIORITY = {
    "exposed_rebar": 0,
    "spalling": 1,
    "crack": 2,
    "corrosion": 3,
    "corrosion_staining": 3,
    "leak": 4,
    "unknown": 99,
}

SEVERITY_BY_DEFECT = {
    "exposed_rebar": "high",
    "spalling": "high",
    "crack": "moderate",
    "corrosion": "moderate",
    "corrosion_staining": "moderate",
    "leak": "moderate",
    "unknown": "none",
}


def build_bridge_image_manifest(
    coco_path: Path,
    *,
    image_root: Path,
    asset_id: str = "BR-REAL-IMAGE",
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    data = json.loads(coco_path.read_text(encoding="utf-8"))
    categories = {
        category["id"]: _normalize_defect_type(category["name"])
        for category in data.get("categories", [])
    }
    annotations_by_image: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for annotation in data.get("annotations", []):
        annotations_by_image[int(annotation["image_id"])].append(annotation)

    image_rows = []
    annotation_rows = []
    for image in sorted(data.get("images", []), key=lambda item: int(item["id"])):
        coco_image_id = int(image["id"])
        file_path = image_root / image["file_name"]
        image_annotations = annotations_by_image.get(coco_image_id, [])
        defect_types = sorted(
            {
                categories.get(int(annotation["category_id"]), "unknown")
                for annotation in image_annotations
            },
            key=lambda defect_type: DEFECT_PRIORITY.get(defect_type, 99),
        )
        primary_defect = defect_types[0] if defect_types else "unknown"
        severity_label = _severity_for(defect_types)
        image_id = f"REAL-BRIDGE-IMG-{coco_image_id:04d}"

        image_rows.append(
            {
                "image_id": image_id,
                "file_path": str(file_path),
                "asset_id": asset_id,
                "asset_type": "bridge",
                "component": "bridge_surface",
                "defect_types": "; ".join(defect_types) if defect_types else "none",
                "primary_defect_type": primary_defect,
                "severity_label": severity_label,
                "location_on_asset": "visible bridge surface",
                "annotation_count": str(len(image_annotations)),
                "has_annotations": str(bool(image_annotations)).lower(),
                "coco_image_id": str(coco_image_id),
                "width": str(image.get("width", "")),
                "height": str(image.get("height", "")),
                "notes": "Real annotated bridge image converted from COCO annotations.",
            }
        )

        for index, annotation in enumerate(image_annotations, start=1):
            defect_type = categories.get(int(annotation["category_id"]), "unknown")
            x, y, width, height = annotation.get("bbox", [0, 0, 0, 0])
            annotation_rows.append(
                {
                    "annotation_id": f"{image_id}-ANN-{index:03d}",
                    "image_id": image_id,
                    "file_path": str(file_path),
                    "asset_id": asset_id,
                    "asset_type": "bridge",
                    "component": "bridge_surface",
                    "defect_type": defect_type,
                    "severity_label": SEVERITY_BY_DEFECT.get(defect_type, "none"),
                    "x": _number(x),
                    "y": _number(y),
                    "width": _number(width),
                    "height": _number(height),
                    "area": _number(annotation.get("area", 0)),
                    "coco_image_id": str(coco_image_id),
                    "coco_annotation_id": str(annotation.get("id", "")),
                }
            )

    return image_rows, annotation_rows


def write_bridge_image_manifest(
    coco_path: Path = Path("data/bridge_image/_annotations.coco.json"),
    *,
    image_root: Path = Path("data/bridge_image"),
    metadata_path: Path = Path("data/bridge_image/metadata.csv"),
    annotations_path: Path = Path("data/bridge_image/annotations.csv"),
) -> None:
    image_rows, annotation_rows = build_bridge_image_manifest(
        coco_path,
        image_root=image_root,
    )
    _write_csv(metadata_path, IMAGE_METADATA_FIELDS, image_rows)
    _write_csv(annotations_path, ANNOTATION_FIELDS, annotation_rows)


def _normalize_defect_type(category_name: str) -> str:
    return DEFECT_TYPE_MAP.get(category_name.strip().lower(), "unknown")


def _severity_for(defect_types: list[str]) -> str:
    if any(defect_type in {"exposed_rebar", "spalling"} for defect_type in defect_types):
        return "high"
    if any(
        defect_type in {"crack", "corrosion", "corrosion_staining", "leak"}
        for defect_type in defect_types
    ):
        return "moderate"
    return "none"


def _number(value: Any) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    write_bridge_image_manifest()
