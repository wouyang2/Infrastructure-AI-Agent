from __future__ import annotations

import json
from argparse import Namespace

from evals.detector_threshold_optimizer import run_threshold_optimizer


def test_threshold_optimizer_finds_per_class_thresholds(tmp_path) -> None:
    eval_json = tmp_path / "detector_eval.json"
    output_json = tmp_path / "thresholds.json"
    output_md = tmp_path / "thresholds.md"
    eval_json.write_text(
        json.dumps(
            {
                "iou_threshold": 0.5,
                "cases": [
                    {
                        "expected_boxes": [
                            {"defect_type": "spalling", "box": [0, 0, 20, 20]},
                            {"defect_type": "corrosion", "box": [50, 50, 20, 20]},
                        ],
                        "predictions": [
                            {
                                "defect_type": "spalling",
                                "confidence": 0.2,
                                "box": [0, 0, 20, 20],
                            },
                            {
                                "defect_type": "corrosion",
                                "confidence": 0.2,
                                "box": [0, 50, 20, 20],
                            },
                            {
                                "defect_type": "corrosion",
                                "confidence": 0.8,
                                "box": [50, 50, 20, 20],
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_threshold_optimizer(
        Namespace(
            detector_eval_json=str(eval_json),
            output_json=str(output_json),
            output_md=str(output_md),
            thresholds="0.1,0.5",
            iou_threshold=None,
        )
    )

    assert result["class_thresholds"] == {"corrosion": 0.5, "spalling": 0.1}
    assert result["combined"]["true_positives"] == 2
    assert result["combined"]["false_positives"] == 0
    assert result["combined"]["false_negatives"] == 0
    assert output_json.exists()
    assert output_md.exists()
