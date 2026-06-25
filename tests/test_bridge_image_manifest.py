from __future__ import annotations

import csv
import json
from pathlib import Path

from data.bridge_image_manifest import build_bridge_image_manifest


def test_bridge_image_manifest_converts_real_coco_annotations() -> None:
    coco = json.loads(Path("data/bridge_image/_annotations.coco.json").read_text())
    metadata_rows, annotation_rows = build_bridge_image_manifest(
        Path("data/bridge_image/_annotations.coco.json"),
        image_root=Path("data/bridge_image"),
    )

    assert len(metadata_rows) == len(coco["images"])
    assert len(annotation_rows) == len(coco["annotations"])
    assert all(Path(row["file_path"]).exists() for row in metadata_rows)
    assert {
        row["defect_type"] for row in annotation_rows
    } == {"crack", "spalling", "exposed_rebar", "corrosion", "leak"}
    assert any(row["primary_defect_type"] == "spalling" for row in metadata_rows)
    assert any(row["primary_defect_type"] == "exposed_rebar" for row in metadata_rows)
    assert any(row["severity_label"] == "high" for row in metadata_rows)
    assert any(row["severity_label"] == "moderate" for row in metadata_rows)


def test_generated_bridge_image_csvs_match_coco_counts() -> None:
    coco = json.loads(Path("data/bridge_image/_annotations.coco.json").read_text())

    with Path("data/bridge_image/metadata.csv").open(newline="", encoding="utf-8") as file:
        metadata_rows = list(csv.DictReader(file))
    with Path("data/bridge_image/annotations.csv").open(newline="", encoding="utf-8") as file:
        annotation_rows = list(csv.DictReader(file))

    assert len(metadata_rows) == len(coco["images"])
    assert len(annotation_rows) == len(coco["annotations"])
    assert all(row["asset_type"] == "bridge" for row in metadata_rows)
    assert all(row["component"] == "bridge_surface" for row in metadata_rows)
