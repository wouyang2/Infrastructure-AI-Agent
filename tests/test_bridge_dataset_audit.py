from __future__ import annotations

from argparse import Namespace

from evals.bridge_dataset_audit import run_bridge_dataset_audit


def test_bridge_dataset_audit_reports_class_geometry_and_contact_sheets(tmp_path) -> None:
    image_path = tmp_path / "bridge.jpg"
    _write_image(image_path)
    metadata_csv = tmp_path / "metadata.csv"
    annotations_csv = tmp_path / "annotations.csv"
    metadata_csv.write_text(
        "\n".join(
            [
                "image_id,file_path,asset_id,asset_type,component,defect_types,primary_defect_type,severity_label,location_on_asset,annotation_count,has_annotations,coco_image_id,width,height,notes",
                f"IMG-001,{image_path},BR-EVAL,bridge,deck,spalling,spalling,high,deck,2,true,1,100,80,test",
                "IMG-002,missing.jpg,BR-EVAL,bridge,deck,none,unknown,none,deck,0,false,2,100,80,test",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    annotations_csv.write_text(
        "\n".join(
            [
                "annotation_id,image_id,file_path,asset_id,asset_type,component,defect_type,severity_label,x,y,width,height,area,coco_image_id,coco_annotation_id",
                f"ANN-001,IMG-001,{image_path},BR-EVAL,bridge,deck,spalling,high,0,10,20,20,400,1,1",
                f"ANN-002,IMG-001,{image_path},BR-EVAL,bridge,deck,crack,moderate,50,50,5,5,25,1,2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_bridge_dataset_audit(
        Namespace(
            metadata_csv=str(metadata_csv),
            annotations_csv=str(annotations_csv),
            output_dir=str(tmp_path / "audit"),
            max_contact_sheet_items=8,
            crop_padding=4,
        )
    )

    assert result["image_count"] == 2
    assert result["annotation_count"] == 2
    assert result["image_level"]["no_defect_image_count"] == 1
    assert result["image_level"]["multi_defect_image_count"] == 1
    assert result["class_metrics"]["spalling"]["annotation_count"] == 1
    assert result["class_metrics"]["spalling"]["edge_touching_count"] == 1
    assert result["class_metrics"]["crack"]["small_box_count"] == 1
    assert result["contact_sheets"]["spalling"].endswith("spalling_contact_sheet.jpg")
    assert (tmp_path / "audit" / "audit.json").exists()
    assert (tmp_path / "audit" / "audit.md").exists()


def _write_image(path) -> None:
    from PIL import Image

    Image.new("RGB", (100, 80), color="gray").save(path)
