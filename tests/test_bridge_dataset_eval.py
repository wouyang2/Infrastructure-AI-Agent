from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from evals.bridge_dataset_eval import _score_case, run_bridge_dataset_eval


def test_bridge_dataset_eval_runs_with_fake_embeddings(tmp_path) -> None:
    metadata_csv = tmp_path / "metadata.csv"
    annotations_csv = tmp_path / "annotations.csv"
    output_json = tmp_path / "eval.json"
    output_md = tmp_path / "eval.md"
    case_review_md = tmp_path / "case_review.md"

    metadata_csv.write_text(
        "\n".join(
            [
                "image_id,file_path,asset_id,asset_type,component,defect_types,primary_defect_type,severity_label,location_on_asset,annotation_count,has_annotations,coco_image_id,width,height,notes",
                "IMG-001,data/bridge_image/example.jpg,BR-EVAL,bridge,bridge_surface,spalling,spalling,high,visible bridge surface,1,true,1,100,100,Eval test image.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    annotations_csv.write_text(
        "\n".join(
            [
                "annotation_id,image_id,file_path,asset_id,asset_type,component,defect_type,severity_label,x,y,width,height,area,coco_image_id,coco_annotation_id",
                "ANN-001,IMG-001,data/bridge_image/example.jpg,BR-EVAL,bridge,bridge_surface,spalling,high,1,2,3,4,12,1,1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_bridge_dataset_eval(
        Namespace(
            metadata_csv=str(metadata_csv),
            annotations_csv=str(annotations_csv),
            output_json=str(output_json),
            output_md=str(output_md),
            case_review_md=str(case_review_md),
            case_review_limit=25,
            case_review_include_passing=3,
            limit=None,
            image_analyzer="metadata",
            image_prompt_profile=None,
            image_detail=None,
            image_tiling="none",
            roboflow_confidence_threshold=0.25,
            roboflow_backend=None,
            roboflow_class_mapping_profile=None,
            roboflow_tiling="none",
            roboflow_class_thresholds=None,
            roboflow_inference_confidence=None,
            roboflow_inference_iou_threshold=None,
            embedding_backend="fake",
            embedding_model=None,
            chroma_persist_dir=str(tmp_path / "chroma"),
            rebuild_rag_index=True,
            knowledge_corpus="bridge",
        )
    )

    assert result["case_count"] == 1
    assert result["metrics"]["defect_accuracy"] == 1.0
    assert result["metrics_by_defect"]["spalling"]["case_count"] == 1
    assert result["metrics_by_defect"]["spalling"]["repair_precedent_hit_rate"] == 1.0
    assert result["metrics"]["schedule_generation_rate"] == 1.0
    assert result["metrics"]["report_generation_rate"] == 1.0
    assert result["failure_summary"]["primary_stage_counts"]["pass"] == 1
    assert result["cases"][0]["primary_failure_stage"] == "pass"
    assert result["cases"][0]["failure_reasons"] == []
    assert result["cases"][0]["schedule_generated"] is True
    assert result["cases"][0]["report_generated"] is True
    assert output_json.exists()
    assert output_md.exists()
    assert case_review_md.exists()
    review = case_review_md.read_text(encoding="utf-8")
    assert "# Bridge Pipeline Case Review" in review
    assert "## Passing Case Samples" in review
    assert "## Metrics By Defect" in review
    assert "IMG-001" in review


def test_bridge_dataset_eval_can_measure_non_metadata_analyzer(tmp_path) -> None:
    metadata_csv = tmp_path / "metadata.csv"
    annotations_csv = tmp_path / "annotations.csv"
    output_json = tmp_path / "heuristic_eval.json"
    output_md = tmp_path / "heuristic_eval.md"
    case_review_md = tmp_path / "heuristic_case_review.md"

    metadata_csv.write_text(
        "\n".join(
            [
                "image_id,file_path,asset_id,asset_type,component,defect_types,primary_defect_type,severity_label,location_on_asset,annotation_count,has_annotations,coco_image_id,width,height,notes",
                "IMG-001,/tmp/bridge_spalling_sample.jpg,BR-EVAL,bridge,bridge_surface,spalling,spalling,high,visible bridge surface,1,true,1,100,100,Heuristic eval image.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    annotations_csv.write_text(
        "annotation_id,image_id,file_path,asset_id,asset_type,component,defect_type,severity_label,x,y,width,height,area,coco_image_id,coco_annotation_id\n",
        encoding="utf-8",
    )

    result = run_bridge_dataset_eval(
        Namespace(
            metadata_csv=str(metadata_csv),
            annotations_csv=str(annotations_csv),
            output_json=str(output_json),
            output_md=str(output_md),
            case_review_md=str(case_review_md),
            case_review_limit=25,
            case_review_include_passing=1,
            limit=None,
            image_analyzer="heuristic",
            image_prompt_profile="bridge_defect_v1",
            image_detail="high",
            image_tiling="grid-2x2",
            roboflow_confidence_threshold=0.55,
            roboflow_backend="inference",
            roboflow_class_mapping_profile="bridge_dataset",
            roboflow_tiling="grid-2x2",
            roboflow_class_thresholds="spalling=0.1,corrosion=0.75",
            roboflow_inference_confidence=0.1,
            roboflow_inference_iou_threshold=0.4,
            embedding_backend="fake",
            embedding_model=None,
            chroma_persist_dir=str(tmp_path / "chroma"),
            rebuild_rag_index=True,
            knowledge_corpus="bridge",
        )
    )

    assert result["image_analyzer"] == "heuristic"
    assert result["image_prompt_profile"] == "bridge_defect_v1"
    assert result["image_detail"] == "high"
    assert result["image_tiling"] == "grid-2x2"
    assert result["roboflow_confidence_threshold"] == 0.55
    assert result["roboflow_backend"] == "inference"
    assert result["roboflow_class_mapping_profile"] == "bridge_dataset"
    assert result["roboflow_tiling"] == "grid-2x2"
    assert result["roboflow_class_thresholds"] == "spalling=0.1,corrosion=0.75"
    assert result["roboflow_inference_confidence"] == 0.1
    assert result["roboflow_inference_iou_threshold"] == 0.4
    assert result["case_count"] == 1
    assert result["metrics"]["defect_accuracy"] == 1.0
    assert result["metrics_by_defect"]["spalling"]["defect_accuracy"] == 1.0
    assert "failure_summary" in result
    markdown = output_md.read_text(encoding="utf-8")
    assert "Image analyzer: heuristic" in markdown
    assert "Image prompt profile: bridge_defect_v1" in markdown
    assert "Image detail: high" in markdown
    assert "Image tiling: grid-2x2" in markdown
    assert "Roboflow confidence threshold: 0.55" in markdown
    assert "Roboflow backend: inference" in markdown
    assert "Roboflow class mapping profile: bridge_dataset" in markdown
    assert "Roboflow tiling: grid-2x2" in markdown
    assert "Roboflow class thresholds: spalling=0.1,corrosion=0.75" in markdown
    assert "Roboflow inference confidence: 0.1" in markdown
    assert "Roboflow inference IoU threshold: 0.4" in markdown
    assert "## Metrics By Defect" in markdown
    assert "## Failure Attribution" in markdown


def test_bridge_dataset_eval_reviewed_taxonomy_accepts_crack_like_spalling() -> None:
    row = {
        "image_id": "REAL-BRIDGE-IMG-0010",
        "file_path": "data/bridge_image/example.jpg",
        "primary_defect_type": "spalling",
        "severity_label": "high",
    }
    report = SimpleNamespace(
        observations=[
            SimpleNamespace(
                defect_type="crack",
                measurement={"severity_label": "moderate"},
                confidence=0.9,
                location_on_asset="surface",
                description="Clear linear fracture.",
            )
        ],
        severity=SimpleNamespace(
            severity="high",
            repair_required=True,
            citations=[
                SimpleNamespace(
                    document_id="STD-BRIDGE-CRACKING-001",
                    title="Bridge Crack Standard",
                    excerpt="crack repair standard",
                )
            ],
        ),
        maintenance_plan=SimpleNamespace(
            historical_precedents=[
                SimpleNamespace(
                    document_id="HIST-BRIDGE-CRACK-001",
                    title="Bridge crack repair",
                    repair_method="routing and sealing",
                    citation=SimpleNamespace(excerpt="crack repair precedent"),
                )
            ],
            recommended_action="routing and sealing",
            estimated_duration_hours=4,
            materials=[],
            equipment=[],
            permits=[],
            risks=[],
        ),
        schedule=SimpleNamespace(
            context_summary=[],
            tradeoffs=[],
            recommended_window=SimpleNamespace(
                start=SimpleNamespace(isoformat=lambda: "2026-06-18T22:00:00"),
                end=SimpleNamespace(isoformat=lambda: "2026-06-19T06:00:00"),
            ),
            total_score=1,
        ),
        rendered_report="report",
    )

    reviewed_case = _score_case(row, report, use_reviewed_taxonomy=True)
    strict_case = _score_case(row, report, use_reviewed_taxonomy=False)

    assert reviewed_case["acceptable_defects"] == ["crack", "spalling"]
    assert reviewed_case["acceptable_severities"] == ["high", "moderate"]
    assert reviewed_case["reviewed_taxonomy_applied"] is True
    assert reviewed_case["defect_match"] is True
    assert reviewed_case["severity_match"] is True
    assert reviewed_case["standard_retrieval_hit"] is True
    assert reviewed_case["repair_precedent_hit"] is True
    assert strict_case["defect_match"] is False
