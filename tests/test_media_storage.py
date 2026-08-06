from __future__ import annotations

from pathlib import Path

from storage.media_storage import LocalMediaStorage, S3MediaStorage, build_media_storage


class FakeS3Client:
    def __init__(self) -> None:
        self.uploads = []
        self.presigned = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.uploads.append(
            {
                "filename": filename,
                "bucket": bucket,
                "key": key,
                "extra_args": ExtraArgs,
            }
        )

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned.append(
            {
                "operation": operation,
                "params": Params,
                "expires_in": ExpiresIn,
            }
        )
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


def test_local_media_storage_uses_artifact_paths(tmp_path) -> None:
    storage = LocalMediaStorage(uploads_dir=tmp_path)
    output_path, output_name = storage.build_upload_path("bridge crack.png")

    output_path.write_bytes(b"image")
    stored = storage.store_file(
        source_path=output_path,
        output_name=output_name,
        content_type="image/png",
        media_type="image",
    )

    assert output_path.parent == tmp_path
    assert output_name.startswith("bridge crack_")
    assert stored.storage_backend == "local"
    assert stored.file_path.startswith("artifacts/uploads/bridge crack_")
    assert stored.preview_url.startswith("/artifacts/uploads/bridge crack_")
    assert stored.delete_local_after_record is False


def test_s3_media_storage_uploads_and_returns_presigned_preview(tmp_path) -> None:
    source_path = tmp_path / "bridge.png"
    source_path.write_bytes(b"image")
    client = FakeS3Client()
    storage = S3MediaStorage(
        uploads_dir=tmp_path,
        bucket="infra-agent-media-dev",
        region="us-east-1",
        prefix="inspections",
        presign_expires_seconds=600,
        client=client,
    )

    stored = storage.store_file(
        source_path=source_path,
        output_name="bridge.png",
        content_type="image/png",
        media_type="image",
    )

    assert client.uploads == [
        {
            "filename": str(source_path),
            "bucket": "infra-agent-media-dev",
            "key": "inspections/image/bridge.png",
            "extra_args": {"ContentType": "image/png"},
        }
    ]
    assert client.presigned[0]["operation"] == "get_object"
    assert client.presigned[0]["params"] == {
        "Bucket": "infra-agent-media-dev",
        "Key": "inspections/image/bridge.png",
    }
    assert stored.storage_backend == "s3"
    assert stored.storage_key == "inspections/image/bridge.png"
    assert stored.file_path == "s3://infra-agent-media-dev/inspections/image/bridge.png"
    assert stored.preview_url.startswith("https://signed.example/")
    assert stored.metadata["bucket"] == "infra-agent-media-dev"
    assert stored.metadata["region"] == "us-east-1"


def test_build_media_storage_uses_s3_when_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MEDIA_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AWS_S3_MEDIA_BUCKET", "infra-agent-media-dev")
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setenv("AWS_S3_MEDIA_PREFIX", "test-prefix")
    monkeypatch.setenv("AWS_S3_PRESIGN_EXPIRES_SECONDS", "120")

    storage = build_media_storage(uploads_dir=tmp_path)

    assert isinstance(storage, S3MediaStorage)
    assert storage.bucket == "infra-agent-media-dev"
    assert storage.region == "us-east-2"
    assert storage.prefix == "test-prefix"
    assert storage.presign_expires_seconds == 120


def test_build_media_storage_defaults_to_local(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MEDIA_STORAGE_BACKEND", raising=False)

    storage = build_media_storage(uploads_dir=tmp_path)

    assert isinstance(storage, LocalMediaStorage)
