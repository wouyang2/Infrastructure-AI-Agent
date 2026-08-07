from __future__ import annotations

import base64
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api as api_module
from api import app
from runtime.rate_limiter import RateLimitResult
from storage.database import SessionLocal
from storage.media_storage import S3MediaStorage
from storage.repositories import create_inspection_run


client = TestClient(app)


class FakeS3Client:
    def __init__(self) -> None:
        self.uploads = []
        self.deleted = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploads.append((filename, bucket, key, ExtraArgs))

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"

    def delete_object(self, Bucket, Key):
        self.deleted.append((Bucket, Key))


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_serves_demo_ui() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Infrastructure AI Agent" in response.text
    assert "Run Inspection" in response.text
    assert 'id="operations-shell"' in response.text
    assert 'id="sidebar-toggle-button"' in response.text
    assert "Formal Report Preview" in response.text
    assert "Export Report" in response.text
    assert "Case Review" in response.text
    assert "Live Progress" in response.text
    assert "Current Queue" in response.text
    assert "History" in response.text
    assert "LLM polished" in response.text
    assert "Drop inspection media" in response.text
    assert "API Key" in response.text
    assert 'id="inspection-queue"' in response.text
    assert 'id="inspection-history"' in response.text
    assert 'id="clear-queue-button"' in response.text
    assert 'data-toggle-section="queue"' in response.text
    assert 'data-toggle-section="history"' in response.text
    assert 'id="media-upload"' in response.text
    assert 'name="image_path" type="hidden"' in response.text
    assert 'name="video_path" type="hidden"' in response.text
    assert 'name="video_frame_interval" type="number" min="0.1" step="0.5" value="4.6"' in response.text
    assert "Image Path" not in response.text
    assert "Video Path" not in response.text
    assert "Sample bridge images" not in response.text
    assert 'id="inspection-drawer"' in response.text
    assert 'data-tab="observations"' in response.text
    assert 'data-tab="rag"' in response.text
    assert 'data-tab="plan"' in response.text
    assert 'data-tab="schedule"' in response.text
    assert 'data-tab="activity"' in response.text
    assert 'id="overview-media"' in response.text
    assert "Visual evidence" in response.text


def test_demo_ui_supports_multiple_progress_pollers() -> None:
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "const progressPollTimers = new Map()" in response.text
    assert '"/uploads/images/multipart"' in response.text
    assert '"/uploads/videos/multipart"' in response.text
    assert "uploadBody.append(\"file\", file, file.name)" in response.text
    assert "function renderMediaGallery" in response.text
    assert "report-media-grid" in response.text
    assert "readAsDataURL" not in response.text
    assert "function validateMediaSelection" in response.text
    assert "require_media: true" in response.text
    assert "|| 4.6" in response.text
    assert "function renderInspectionQueue" in response.text
    assert "function cancelRun" in response.text
    assert "function clearActiveQueue" in response.text
    assert "function setRailSectionCollapsed" in response.text
    assert "function setSidebarCollapsed" in response.text
    assert "infra_agent_sidebar_collapsed" in response.text
    assert "infra_agent_collapsed_rail_sections" in response.text
    assert '"/cases/queue/clear"' in response.text
    assert 'runButton.textContent = "Queueing..."' in response.text
    assert "runButton.disabled = true" in response.text
    assert "runButton.disabled = false" in response.text
    assert "loadSampleImages" not in response.text


def test_demo_ui_keeps_queue_inside_sidebar() -> None:
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert ".run-rail .inspection-queue" in response.text
    assert "overflow-x: hidden" in response.text
    assert "contain: inline-size" in response.text
    assert ".run-rail .queue-row" in response.text


def test_demo_ui_pins_drawer_actions_inside_drawer() -> None:
    index_response = client.get("/")
    css_response = client.get("/static/styles.css")

    assert index_response.status_code == 200
    assert css_response.status_code == 200
    assert 'id="inspection-form" class="drawer-form-body"' in index_response.text
    assert 'id="run-button" form="inspection-form"' in index_response.text
    assert index_response.text.index("</form>") < index_response.text.index('<footer class="drawer-actions">')
    assert ".inspection-drawer" in css_response.text
    assert "--drawer-header-height" in css_response.text
    assert "--drawer-actions-height" in css_response.text
    assert "#inspection-form.drawer-form-body" in css_response.text
    assert "bottom: var(--drawer-actions-height)" in css_response.text
    assert "position: absolute" in css_response.text
    assert ".drawer-actions" in css_response.text


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


def test_api_key_auth_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)
    monkeypatch.delenv("INFRA_AGENT_API_KEY", raising=False)

    response = client.get("/cases?limit=1")

    assert response.status_code == 200


def test_api_key_auth_rejects_missing_key(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    monkeypatch.setenv("INFRA_AGENT_API_KEY", "test-secret")

    response = client.get("/cases?limit=1")

    assert response.status_code == 401
    assert "API key" in response.json()["detail"]


def test_api_key_auth_rejects_wrong_key(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    monkeypatch.setenv("INFRA_AGENT_API_KEY", "test-secret")

    response = client.get("/cases?limit=1", headers={"X-API-Key": "wrong"})

    assert response.status_code == 401


def test_api_key_auth_accepts_x_api_key(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    monkeypatch.setenv("INFRA_AGENT_API_KEY", "test-secret")

    response = client.get("/cases?limit=1", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 200


def test_api_key_auth_accepts_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    monkeypatch.setenv("INFRA_AGENT_API_KEY", "test-secret")

    response = client.get(
        "/cases?limit=1",
        headers={"Authorization": "Bearer test-secret"},
    )

    assert response.status_code == 200


def test_api_key_auth_returns_503_when_required_key_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    monkeypatch.delenv("INFRA_AGENT_API_KEY", raising=False)

    response = client.get("/cases?limit=1")

    assert response.status_code == 503
    assert "INFRA_AGENT_API_KEY" in response.json()["detail"]


def test_config_status_endpoint_reports_redacted_runtime_checks(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    monkeypatch.setenv("INFRA_AGENT_API_KEY", "test-secret")

    response = client.get(
        "/config/status",
        headers={"X-API-Key": "test-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] in {"ok", "warning", "error"}
    assert any(check["name"] == "api_auth" for check in payload["checks"])
    assert "test-secret" not in response.text


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


def test_upload_image_multipart_returns_local_artifact_path() -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(image_buffer, format="PNG")

    response = client.post(
        "/uploads/images/multipart",
        files={"file": ("bridge-upload.png", image_buffer.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_path"].startswith("artifacts/uploads/bridge-upload_")
    assert payload["file_path"].endswith(".png")
    assert payload["preview_url"].startswith("/artifacts/uploads/bridge-upload_")
    assert payload["media_id"].startswith("media_")
    assert payload["media_type"] == "image"
    assert payload["storage_backend"] == "local"
    assert payload["checksum_sha256"]


def test_upload_image_multipart_can_use_s3_storage(monkeypatch, tmp_path) -> None:
    fake_client = FakeS3Client()
    monkeypatch.setattr(
        api_module,
        "MEDIA_STORAGE",
        S3MediaStorage(
            uploads_dir=tmp_path,
            bucket="infra-agent-media-test",
            region="us-east-1",
            prefix="inspection-evidence",
            presign_expires_seconds=300,
            client=fake_client,
        ),
    )
    image_buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(image_buffer, format="PNG")

    response = client.post(
        "/uploads/images/multipart",
        files={"file": ("bridge-upload.png", image_buffer.getvalue(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["storage_backend"] == "s3"
    assert payload["file_path"].startswith("s3://infra-agent-media-test/")
    assert payload["preview_url"].startswith("https://signed.example/infra-agent-media-test/")
    assert fake_client.uploads


def test_upload_image_cleans_s3_object_when_media_record_fails(
    monkeypatch,
    tmp_path,
) -> None:
    fake_client = FakeS3Client()
    monkeypatch.setattr(
        api_module,
        "MEDIA_STORAGE",
        S3MediaStorage(
            uploads_dir=tmp_path,
            bucket="infra-agent-media-test",
            region="us-east-1",
            prefix="inspection-evidence",
            client=fake_client,
        ),
    )

    def fail_create_media(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(api_module, "create_inspection_media", fail_create_media)
    image_buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(image_buffer, format="PNG")

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/uploads/images/multipart",
            files={"file": ("bridge-upload.png", image_buffer.getvalue(), "image/png")},
        )

    assert fake_client.uploads
    _, bucket, key, _ = fake_client.uploads[0]
    assert fake_client.deleted == [(bucket, key)]


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


def test_upload_image_multipart_rejects_unsupported_extension() -> None:
    response = client.post(
        "/uploads/images/multipart",
        files={"file": ("bridge-upload.txt", b"not an image", "text/plain")},
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


def test_upload_image_multipart_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setenv("MAX_IMAGE_UPLOAD_BYTES", "3")

    response = client.post(
        "/uploads/images/multipart",
        files={"file": ("bridge-upload.png", b"abcd", "image/png")},
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


def test_upload_video_multipart_returns_local_artifact_path() -> None:
    response = client.post(
        "/uploads/videos/multipart",
        files={"file": ("bridge-walkthrough.mp4", b"fake video bytes", "video/mp4")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_path"].startswith("artifacts/uploads/bridge-walkthrough_")
    assert payload["file_path"].endswith(".mp4")
    assert payload["preview_url"].startswith("/artifacts/uploads/bridge-walkthrough_")
    assert payload["media_id"].startswith("media_")
    assert payload["media_type"] == "video"
    assert payload["storage_backend"] == "local"
    assert payload["checksum_sha256"]


def test_uploaded_media_metadata_attaches_to_inspection_run() -> None:
    image_buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(image_buffer, format="PNG")
    upload_response = client.post(
        "/uploads/images/multipart",
        files={"file": ("bridge-evidence.png", image_buffer.getvalue(), "image/png")},
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()
    run_id = f"api_media_attach_{uuid4().hex}"

    response = client.post(
        "/inspections",
        json={
            "client_run_id": run_id,
            "asset_id": "API-MEDIA-ATTACH",
            "asset_type": "bridge",
            "asset_name": "API Media Attach Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling near an expansion joint.",
            "image_paths": [uploaded["file_path"]],
            "video_paths": [],
            "require_media": True,
            "image_analyzer": "heuristic",
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
            "report_mode": "deterministic",
        },
    )
    assert response.status_code == 202

    detail_response = client.get(f"/cases/{run_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["media"][0]["media_id"] == uploaded["media_id"]
    assert detail["media"][0]["run_id"] == run_id
    assert detail["media"][0]["preview_url"] == uploaded["preview_url"]


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


def test_upload_video_multipart_rejects_unsupported_extension() -> None:
    response = client.post(
        "/uploads/videos/multipart",
        files={"file": ("bridge-walkthrough.txt", b"fake video bytes", "text/plain")},
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


def test_upload_video_multipart_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setenv("MAX_VIDEO_UPLOAD_BYTES", "3")

    response = client.post(
        "/uploads/videos/multipart",
        files={"file": ("bridge-walkthrough.mp4", b"abcd", "video/mp4")},
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

    events_response = client.get(f"/cases/{run_id}/events")
    assert events_response.status_code == 200
    durable_events = events_response.json()
    assert "queued" in [event["stage"] for event in durable_events]
    assert "report" in [event["stage"] for event in durable_events]
    assert "completed" in [event["stage"] for event in durable_events]


def test_case_progress_endpoint_includes_rq_runtime_status(monkeypatch) -> None:
    run_id = f"api_progress_rq_{uuid4().hex}"
    api_module.progress_store.start_run(run_id)
    api_module.progress_store.record_event(
        run_id,
        stage="queued",
        status="running",
        message="Inspection job queued via rq.",
        percent=0,
        metadata={"job_id": "inspection-api-progress-rq", "job_backend": "rq"},
    )
    api_module.progress_store.record_event(
        run_id,
        stage="scheduling",
        status="running",
        message="Choosing repair window.",
        percent=85,
    )

    def fake_runtime_status(*, job_backend, job_id):
        assert job_backend == "rq"
        assert job_id == "inspection-api-progress-rq"
        return {
            "job_backend": "rq",
            "job_id": job_id,
            "job_status": "scheduled",
            "job_status_message": "Inspection job is scheduled for retry by RQ.",
            "job_retries_left": 2,
        }

    monkeypatch.setattr(api_module, "fetch_runtime_job_status", fake_runtime_status)

    response = client.get(f"/cases/{run_id}/progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_stage"] == "scheduling"
    assert payload["message"] == "Inspection job is scheduled for retry by RQ."
    assert payload["job_backend"] == "rq"
    assert payload["job_id"] == "inspection-api-progress-rq"
    assert payload["job_status"] == "scheduled"
    assert payload["job_retries_left"] == 2


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


def test_create_inspection_requires_media_when_requested() -> None:
    response = client.post(
        "/inspections",
        json={
            "asset_id": "API-MEDIA-100",
            "asset_type": "bridge",
            "asset_name": "API Media Bridge",
            "location": "East approach",
            "criticality": "high",
            "notes": "Inspection found spalling with loose concrete.",
            "require_media": True,
            "embedding_backend": "fake",
            "scheduling_mode": "deterministic",
        },
    )

    assert response.status_code == 400
    assert "image or video" in response.json()["detail"].lower()


def test_cancel_case_moves_active_run_to_canceled_history() -> None:
    run_id = f"api_cancel_{uuid4().hex}"
    session = SessionLocal()
    try:
        create_inspection_run(
            session,
            request_data={
                "asset_id": "API-CANCEL-100",
                "asset_type": "bridge",
                "asset_name": "API Cancel Bridge",
                "location": "East approach",
                "criticality": "high",
                "notes": "Queued inspection waiting for operator action.",
                "image_paths": [],
                "video_paths": [],
            },
            run_id=run_id,
            status="queued",
        )
    finally:
        session.close()
    api_module.progress_store.start_run(run_id)

    response = client.patch(f"/cases/{run_id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "canceled"
    assert payload["error"] == "Inspection canceled by operator."

    progress_response = client.get(f"/cases/{run_id}/progress")
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["status"] == "canceled"
    assert progress["current_stage"] == "canceled"


def test_clear_active_queue_cancels_only_nonterminal_runs() -> None:
    active_run_id = f"api_clear_active_{uuid4().hex}"
    completed_run_id = f"api_clear_completed_{uuid4().hex}"
    session = SessionLocal()
    try:
        create_inspection_run(
            session,
            request_data={
                "asset_id": "API-CLEAR-ACTIVE",
                "asset_type": "bridge",
                "asset_name": "API Clear Active Bridge",
                "location": "East approach",
                "criticality": "high",
                "notes": "Queued inspection waiting for operator action.",
                "image_paths": [],
                "video_paths": [],
            },
            run_id=active_run_id,
            status="queued",
        )
        create_inspection_run(
            session,
            request_data={
                "asset_id": "API-CLEAR-DONE",
                "asset_type": "bridge",
                "asset_name": "API Clear Completed Bridge",
                "location": "East approach",
                "criticality": "high",
                "notes": "Completed inspection should remain untouched.",
                "image_paths": [],
                "video_paths": [],
            },
            run_id=completed_run_id,
            status="completed",
        )
    finally:
        session.close()
    api_module.progress_store.start_run(active_run_id)

    response = client.post("/cases/queue/clear")

    assert response.status_code == 200
    payload = response.json()
    assert active_run_id in payload["canceled_runs"]
    assert completed_run_id not in payload["canceled_runs"]

    active_detail = client.get(f"/cases/{active_run_id}").json()
    completed_detail = client.get(f"/cases/{completed_run_id}").json()
    assert active_detail["status"] == "canceled"
    assert completed_detail["status"] == "completed"


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

    events_response = client.get(f"/cases/{run_id}/review-events")
    assert events_response.status_code == 200
    events = events_response.json()
    assert len(events) == 1
    assert events[0]["run_id"] == run_id
    assert events[0]["previous_status"] == "not_reviewed"
    assert events[0]["new_status"] == "approved"
    assert events[0]["reviewer_notes"] == "Confirmed repair recommendation for demo."
    assert events[0]["reviewed_by"] == "engineer-demo"
    assert events[0]["created_at"]


def test_review_endpoint_rejects_missing_case() -> None:
    response = client.patch(
        "/cases/not-a-real-run/review",
        json={"review_status": "approved"},
    )

    assert response.status_code == 404


def test_review_events_endpoint_rejects_missing_case() -> None:
    response = client.get("/cases/not-a-real-run/review-events")

    assert response.status_code == 404


def test_run_events_endpoint_rejects_missing_case() -> None:
    response = client.get("/cases/not-a-real-run/events")

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
