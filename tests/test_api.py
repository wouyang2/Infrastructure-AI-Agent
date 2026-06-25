from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from api import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_serves_demo_ui() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Infrastructure AI Agent" in response.text
    assert "Run Inspection" in response.text
    assert "Formal Report Preview" in response.text
    assert "Export Report" in response.text
    assert "LLM polished" in response.text


def test_sample_images_endpoint_returns_preview_paths() -> None:
    response = client.get("/sample-images?limit=3")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3
    assert payload[0]["file_path"].startswith("data/bridge_image/")
    assert payload[0]["preview_url"].startswith("/media/bridge_image/")
    assert payload[0]["defect_type"]


def test_sample_images_endpoint_deduplicates_thumbnails() -> None:
    response = client.get("/sample-images?limit=10")

    assert response.status_code == 200
    payload = response.json()
    file_paths = [item["file_path"] for item in payload]
    preview_urls = [item["preview_url"] for item in payload]
    assert len(file_paths) == len(set(file_paths))
    assert len(preview_urls) == len(set(preview_urls))


def test_upload_image_returns_local_artifact_path() -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(image_buffer, format="PNG")
    tiny_png = base64.b64encode(image_buffer.getvalue()).decode()

    response = client.post(
        "/uploads/images",
        json={
            "filename": "bridge-upload.png",
            "content_base64": tiny_png,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_path"].startswith("artifacts/uploads/bridge-upload_")
    assert payload["file_path"].endswith(".png")
    assert payload["preview_url"].startswith("/artifacts/uploads/bridge-upload_")


def test_upload_image_rejects_unsupported_extension() -> None:
    response = client.post(
        "/uploads/images",
        json={
            "filename": "bridge-upload.txt",
            "content_base64": base64.b64encode(b"not an image").decode(),
        },
    )

    assert response.status_code == 400
    assert "Only JPG, PNG, and WEBP" in response.json()["detail"]


def test_create_inspection_returns_report() -> None:
    response = client.post(
        "/inspections",
        json={
            "asset_id": "API-100",
            "asset_type": "bridge",
            "asset_name": "API Demo Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["case"]["case_id"] == "CASE-API-100"
    assert payload["report"]["severity"]["repair_required"] is True
    assert (
        payload["report"]["maintenance_plan"]["recommended_action"]
        == "partial-depth concrete patch"
    )
    assert payload["report"]["schedule"] is not None
    assert "# Infrastructure Inspection Report" in payload["rendered_report"]


def test_export_report_pdf_returns_pdf() -> None:
    inspection_response = client.post(
        "/inspections",
        json={
            "asset_id": "API-PDF-100",
            "asset_type": "bridge",
            "asset_name": "API PDF Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )
    assert inspection_response.status_code == 200

    response = client.post("/reports/pdf", json=inspection_response.json())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "CASE-API-PDF-100.pdf" in response.headers["content-disposition"]


def test_create_inspection_monitoring_only_skips_schedule() -> None:
    response = client.post(
        "/inspections",
        json={
            "asset_id": "API-101",
            "asset_type": "bridge",
            "asset_name": "API Monitoring Bridge",
            "location": "North approach",
            "criticality": "medium",
            "notes": "Routine visual check found no visible distress or access issues.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["severity"]["repair_required"] is False
    assert payload["report"]["schedule"] is None
    assert "No repair window required" in payload["rendered_report"]


def test_create_inspection_accepts_live_scheduling_context_fields() -> None:
    response = client.post(
        "/inspections",
        json={
            "asset_id": "API-102",
            "asset_type": "bridge",
            "asset_name": "API Live Context Bridge",
            "location": "Midtown corridor",
            "latitude": 40.7505,
            "longitude": -73.9934,
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
            "schedule_context_mode": "mock",
            "event_provider": "mock",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["case"]["asset"]["metadata"] == {
        "latitude": 40.7505,
        "longitude": -73.9934,
    }
    assert payload["report"]["schedule"] is not None
