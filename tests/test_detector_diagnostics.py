from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from evals.detector_diagnostics import run_detector_diagnostics


def test_detector_diagnostics_writes_overlays_and_missed_crops(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    _write_image(image_path)
    eval_json = tmp_path / "detector_eval.json"
    eval_json.write_text(
        json.dumps(
            {
                "best_threshold": 0.25,
                "iou_threshold": 0.5,
                "cases": [
                    {
                        "image_id": "IMG-001",
                        "file_path": str(image_path),
                        "expected_boxes": [
                            {
                                "annotation_id": "ANN-001",
                                "defect_type": "spalling",
                                "box": [20, 20, 40, 30],
                                "severity_label": "high",
                            }
                        ],
                        "predictions": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_detector_diagnostics(
        Namespace(
            detector_eval_json=str(eval_json),
            output_dir=str(tmp_path / "diagnostics"),
            confidence_threshold=None,
            iou_threshold=None,
            defect_type="spalling",
            crop_padding=8,
        )
    )

    assert result["summary"]["case_count"] == 1
    assert result["summary"]["missed_count"] == 1
    assert result["summary"]["crop_count"] == 1
    assert Path(result["cases"][0]["overlay_path"]).exists()
    assert Path(result["cases"][0]["missed_crop_paths"][0]).exists()
    assert (tmp_path / "diagnostics" / "diagnostics.json").exists()
    assert (tmp_path / "diagnostics" / "diagnostics.md").exists()


def test_detector_diagnostics_skips_matched_boxes(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    _write_image(image_path)
    eval_json = tmp_path / "detector_eval.json"
    eval_json.write_text(
        json.dumps(
            {
                "best_threshold": 0.25,
                "iou_threshold": 0.5,
                "cases": [
                    {
                        "image_id": "IMG-001",
                        "file_path": str(image_path),
                        "expected_boxes": [
                            {
                                "annotation_id": "ANN-001",
                                "defect_type": "spalling",
                                "box": [20, 20, 40, 30],
                                "severity_label": "high",
                            }
                        ],
                        "predictions": [
                            {
                                "defect_type": "spalling",
                                "confidence": 0.8,
                                "box": [21, 21, 38, 28],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_detector_diagnostics(
        Namespace(
            detector_eval_json=str(eval_json),
            output_dir=str(tmp_path / "diagnostics"),
            confidence_threshold=None,
            iou_threshold=None,
            defect_type="spalling",
            crop_padding=8,
        )
    )

    assert result["summary"]["case_count"] == 0
    assert result["summary"]["missed_count"] == 0
    assert result["summary"]["crop_count"] == 0


def _write_image(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (120, 100), color="gray").save(path)
