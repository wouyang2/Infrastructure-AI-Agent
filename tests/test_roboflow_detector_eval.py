from __future__ import annotations

from argparse import Namespace

from agents.helpers.image_analyzer import ImageAnalyzer, ImageFinding
from evals.roboflow_detector_eval import run_detector_eval


class FakeDetector(ImageAnalyzer):
    def __init__(self, findings_by_path: dict[str, list[ImageFinding]]):
        self.findings_by_path = findings_by_path

    def analyze(self, image_path: str, asset_type: str) -> list[ImageFinding]:
        return self.findings_by_path.get(image_path, [])


def test_detector_eval_scores_box_matches_and_false_positives(tmp_path) -> None:
    metadata_csv, annotations_csv = _write_eval_csvs(tmp_path)

    result = run_detector_eval(
        _args(tmp_path, metadata_csv, annotations_csv, thresholds="0.25"),
        image_analyzer=FakeDetector(
            {
                "spalling.jpg": [
                    ImageFinding(
                        defect_type="spalling",
                        description="matched spall",
                        location_on_asset="deck",
                        confidence=0.9,
                        bounding_box=(12, 12, 18, 18),
                    )
                ],
                "normal.jpg": [
                    ImageFinding(
                        defect_type="corrosion",
                        description="false stain",
                        location_on_asset="deck",
                        confidence=0.8,
                        bounding_box=(50, 50, 10, 10),
                    )
                ],
            }
        ),
    )

    metrics = result["metrics_by_threshold"]["0.25"]
    assert metrics["true_positives"] == 1
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 0
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 1.0
    assert result["prediction_count"] == 2
    assert (tmp_path / "detector_eval.json").exists()
    assert (tmp_path / "detector_eval.md").exists()


def test_detector_eval_threshold_sweep_filters_low_confidence_predictions(tmp_path) -> None:
    metadata_csv, annotations_csv = _write_eval_csvs(tmp_path)

    result = run_detector_eval(
        _args(tmp_path, metadata_csv, annotations_csv, thresholds="0.25,0.75"),
        image_analyzer=FakeDetector(
            {
                "spalling.jpg": [
                    ImageFinding(
                        defect_type="spalling",
                        description="low confidence spall",
                        location_on_asset="deck",
                        confidence=0.6,
                        bounding_box=(10, 10, 20, 20),
                    )
                ]
            }
        ),
    )

    assert result["metrics_by_threshold"]["0.25"]["true_positives"] == 1
    assert result["metrics_by_threshold"]["0.25"]["false_negatives"] == 0
    assert result["metrics_by_threshold"]["0.75"]["true_positives"] == 0
    assert result["metrics_by_threshold"]["0.75"]["false_negatives"] == 1


def test_detector_eval_supports_metadata_offset(tmp_path) -> None:
    metadata_csv, annotations_csv = _write_eval_csvs(tmp_path)

    result = run_detector_eval(
        _args(tmp_path, metadata_csv, annotations_csv, thresholds="0.25", offset=1),
        image_analyzer=FakeDetector(
            {
                "normal.jpg": [
                    ImageFinding(
                        defect_type="corrosion",
                        description="false stain",
                        location_on_asset="deck",
                        confidence=0.8,
                        bounding_box=(50, 50, 10, 10),
                    )
                ]
            }
        ),
    )

    assert result["offset"] == 1
    assert result["case_count"] == 1
    assert result["cases"][0]["image_id"] == "IMG-002"


def test_detector_eval_ignores_findings_without_boxes(tmp_path) -> None:
    metadata_csv, annotations_csv = _write_eval_csvs(tmp_path)

    result = run_detector_eval(
        _args(tmp_path, metadata_csv, annotations_csv, thresholds="0.25"),
        image_analyzer=FakeDetector(
            {
                "spalling.jpg": [
                    ImageFinding(
                        defect_type="spalling",
                        description="classification only",
                        location_on_asset="deck",
                        confidence=0.9,
                        bounding_box=None,
                    )
                ]
            }
        ),
    )

    metrics = result["metrics_by_threshold"]["0.25"]
    assert result["prediction_count"] == 0
    assert metrics["true_positives"] == 0
    assert metrics["false_negatives"] == 1


def _write_eval_csvs(tmp_path):
    metadata_csv = tmp_path / "metadata.csv"
    annotations_csv = tmp_path / "annotations.csv"
    metadata_csv.write_text(
        "\n".join(
            [
                "image_id,file_path,asset_id,asset_type,component,defect_types,primary_defect_type,severity_label,location_on_asset,annotation_count,has_annotations,coco_image_id,width,height,notes",
                "IMG-001,spalling.jpg,BR-EVAL,bridge,deck,spalling,spalling,high,deck,1,true,1,100,100,spall",
                "IMG-002,normal.jpg,BR-EVAL,bridge,deck,none,unknown,none,deck,0,false,2,100,100,normal",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    annotations_csv.write_text(
        "\n".join(
            [
                "annotation_id,image_id,file_path,asset_id,asset_type,component,defect_type,severity_label,x,y,width,height,area,coco_image_id,coco_annotation_id",
                "ANN-001,IMG-001,spalling.jpg,BR-EVAL,bridge,deck,spalling,high,10,10,20,20,400,1,1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return metadata_csv, annotations_csv


def _args(
    tmp_path,
    metadata_csv,
    annotations_csv,
    *,
    thresholds: str,
    offset: int = 0,
) -> Namespace:
    return Namespace(
        metadata_csv=str(metadata_csv),
        annotations_csv=str(annotations_csv),
        output_json=str(tmp_path / "detector_eval.json"),
        output_md=str(tmp_path / "detector_eval.md"),
        offset=offset,
        limit=None,
        image_analyzer="roboflow",
        thresholds=thresholds,
        iou_threshold=0.5,
        roboflow_backend="inference",
        roboflow_class_mapping_profile=None,
        roboflow_tiling="none",
        roboflow_class_thresholds=None,
        roboflow_inference_confidence=None,
        roboflow_inference_iou_threshold=None,
        image_prompt_profile=None,
        image_detail=None,
        image_tiling="none",
    )
