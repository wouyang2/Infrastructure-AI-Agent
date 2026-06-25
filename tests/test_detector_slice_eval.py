from __future__ import annotations

import json
from argparse import Namespace

from evals.detector_slice_eval import run_detector_slice_eval


def test_detector_slice_eval_reports_edge_and_class_recall(tmp_path) -> None:
    metadata_csv = tmp_path / "metadata.csv"
    detector_json = tmp_path / "detector_eval.json"
    output_json = tmp_path / "slice_eval.json"
    output_md = tmp_path / "slice_eval.md"
    metadata_csv.write_text(
        "\n".join(
            [
                "image_id,file_path,asset_id,asset_type,component,defect_types,primary_defect_type,severity_label,location_on_asset,annotation_count,has_annotations,coco_image_id,width,height,notes",
                "IMG-001,bridge.jpg,BR-EVAL,bridge,deck,spalling,spalling,high,deck,2,true,1,100,80,test",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    detector_json.write_text(
        json.dumps(
            {
                "best_threshold": 0.25,
                "iou_threshold": 0.5,
                "cases": [
                    {
                        "image_id": "IMG-001",
                        "file_path": "bridge.jpg",
                        "expected_boxes": [
                            {
                                "annotation_id": "ANN-001",
                                "defect_type": "spalling",
                                "box": [0, 10, 20, 20],
                            },
                            {
                                "annotation_id": "ANN-002",
                                "defect_type": "spalling",
                                "box": [50, 40, 20, 20],
                            },
                        ],
                        "predictions": [
                            {
                                "defect_type": "spalling",
                                "confidence": 0.8,
                                "box": [51, 41, 18, 18],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_detector_slice_eval(
        Namespace(
            detector_eval_json=str(detector_json),
            metadata_csv=str(metadata_csv),
            output_json=str(output_json),
            output_md=str(output_md),
            confidence_threshold=None,
            iou_threshold=None,
            edge_tolerance=2.0,
            small_area_ratio=0.01,
        )
    )

    assert result["slices"]["edge_touching"] == {
        "matched": 0,
        "total": 1,
        "recall": 0.0,
    }
    assert result["slices"]["non_edge"] == {
        "matched": 1,
        "total": 1,
        "recall": 1.0,
    }
    assert result["classes"]["spalling"] == {
        "matched": 1,
        "total": 2,
        "recall": 0.5,
    }
    assert output_json.exists()
    assert output_md.exists()
