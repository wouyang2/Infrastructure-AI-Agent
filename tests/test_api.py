from __future__ import annotations

import base64
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

import api as api_module
from api import app
from runtime.rate_limiter import RateLimitResult


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
    assert "Case Review" in response.text
    assert "Live Progress" in response.text
    assert "LLM polished" in response.text
    assert "Drop inspection media" in response.text
    assert 'id="media-upload"' in response.text
    assert 'name="image_path" type="hidden"' in response.text
    assert 'name="video_path" type="hidden"' in response.text
    assert "Image Path" not in response.text
    assert "Video Path" not in response.text


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


def test_upload_image_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setenv("MAX_IMAGE_UPLOAD_BYTES", "3")

    response = client.post(
        "/uploads/images",
        json={
            "filename": "bridge-upload.png",
            "content_base64": base64.b64encode(b"abcd").decode(),
        },
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_upload_video_returns_local_artifact_path() -> None:
    response = client.post(
        "/uploads/videos",
        json={
            "filename": "bridge-walkthrough.mp4",
            "content_base64": base64.b64encode(b"fake video bytes").decode(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_path"].startswith("artifacts/uploads/bridge-walkthrough_")
    assert payload["file_path"].endswith(".mp4")
    assert payload["preview_url"].startswith("/artifacts/uploads/bridge-walkthrough_")


def test_upload_video_rejects_unsupported_extension() -> None:
    response = client.post(
        "/uploads/videos",
        json={
            "filename": "bridge-walkthrough.txt",
            "content_base64": base64.b64encode(b"fake video bytes").decode(),
        },
    )

    assert response.status_code == 400
    assert "Only MP4, MOV, AVI, and MKV" in response.json()["detail"]


def test_upload_video_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setenv("MAX_VIDEO_UPLOAD_BYTES", "3")

    response = client.post(
        "/uploads/videos",
        json={
            "filename": "bridge-walkthrough.mp4",
            "content_base64": base64.b64encode(b"abcd").decode(),
        },
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_create_inspection_returns_report() -> None:
    run_id = f"api_create_{uuid4().hex}"
    response = client.post(
        "/inspections",
        json={
            "client_run_id": run_id,
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

    assert response.status_code == 202
    payload = response.json()
    assert payload["run_id"] == run_id
    assert payload["status"] == "queued"
    assert payload["progress_url"] == f"/cases/{run_id}/progress"
    assert payload["case_url"] == f"/cases/{run_id}"
    assert payload["report"] is None

    detail_response = client.get(f"/cases/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "completed"
    assert detail["case_id"] == "CASE-API-100"
    assert detail["report"]["case"]["case_id"] == "CASE-API-100"
    assert detail["report"]["severity"]["repair_required"] is True
    assert (
        detail["report"]["maintenance_plan"]["recommended_action"]
        == "partial-depth concrete patch"
    )
    assert detail["report"]["schedule"] is not None
    assert "# Infrastructure Inspection Report" in detail["rendered_report"]
    assert detail["severity"] == detail["report"]["severity"]["severity"]
    assert detail["report"]["case"]["case_id"] == "CASE-API-100"


def test_cases_endpoint_lists_persisted_inspections() -> None:
    inspection_response = client.post(
        "/inspections",
        json={
            "asset_id": "API-LIST-100",
            "asset_type": "bridge",
            "asset_name": "API List Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )
    assert inspection_response.status_code == 202
    run_id = inspection_response.json()["run_id"]

    response = client.get("/cases?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert any(item["run_id"] == run_id for item in payload)


def test_case_progress_endpoint_returns_workflow_progress() -> None:
    run_id = f"api_progress_{uuid4().hex}"
    inspection_response = client.post(
        "/inspections",
        json={
            "client_run_id": run_id,
            "asset_id": "API-PROGRESS-100",
            "asset_type": "bridge",
            "asset_name": "API Progress Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )
    assert inspection_response.status_code == 202

    response = client.get(f"/cases/{run_id}/progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["current_stage"] == "completed"
    assert payload["percent"] == 100
    assert "queued" in [event["stage"] for event in payload["events"]]
    assert "report" in [event["stage"] for event in payload["events"]]


def test_create_inspection_returns_429_when_rate_limited(monkeypatch) -> None:
    class DenyLimiter:
        def check(self, key, *, limit, window_seconds):
            return RateLimitResult(
                allowed=False,
                key=key,
                limit=1,
                count=2,
                remaining=0,
                reset_seconds=12,
            )

    monkeypatch.setattr(api_module, "rate_limiter", DenyLimiter())

    response = client.post(
        "/inspections",
        json={
            "asset_id": "API-LIMIT-100",
            "asset_type": "bridge",
            "asset_name": "API Limited Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "12"
    assert "rate limit exceeded" in response.json()["detail"].lower()


def test_review_endpoint_updates_completed_case() -> None:
    inspection_response = client.post(
        "/inspections",
        json={
            "asset_id": "API-REVIEW-100",
            "asset_type": "bridge",
            "asset_name": "API Review Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )
    assert inspection_response.status_code == 202
    run_id = inspection_response.json()["run_id"]

    response = client.patch(
        f"/cases/{run_id}/review",
        json={
            "review_status": "approved",
            "reviewer_notes": "Confirmed repair recommendation for demo.",
            "reviewed_by": "engineer-demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == "approved"
    assert payload["reviewer_notes"] == "Confirmed repair recommendation for demo."
    assert payload["reviewed_by"] == "engineer-demo"
    assert payload["reviewed_at"]


def test_review_endpoint_rejects_missing_case() -> None:
    response = client.patch(
        "/cases/not-a-real-run/review",
        json={"review_status": "approved"},
    )

    assert response.status_code == 404


def test_case_detail_returns_404_for_missing_run() -> None:
    response = client.get("/cases/not-a-real-run")

    assert response.status_code == 404


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
    assert inspection_response.status_code == 202
    run_id = inspection_response.json()["run_id"]
    detail_response = client.get(f"/cases/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()

    response = client.post(
        "/reports/pdf",
        json={
            "report": detail["report"],
            "rendered_report": detail["rendered_report"],
        },
    )

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

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    detail_response = client.get(f"/cases/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["report"]["severity"]["repair_required"] is False
    assert detail["report"]["schedule"] is None
    assert "No repair window required" in detail["rendered_report"]


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

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    detail_response = client.get(f"/cases/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["report"]["case"]["asset"]["metadata"] == {
        "latitude": 40.7505,
        "longitude": -73.9934,
    }
    assert detail["report"]["schedule"] is not None
