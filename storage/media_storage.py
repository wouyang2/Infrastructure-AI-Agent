from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class StoredMedia:
    storage_backend: str
    storage_key: str
    file_path: str
    preview_url: str
    metadata: dict[str, str]
    delete_local_after_record: bool = False


class LocalMediaStorage:
    def __init__(
        self,
        *,
        uploads_dir: Path,
        artifact_root: str = "artifacts/uploads",
    ) -> None:
        self.uploads_dir = uploads_dir
        self.artifact_root = artifact_root

    def build_upload_path(self, original_name: str) -> tuple[Path, str]:
        output_name = _build_upload_name(original_name)
        return self.uploads_dir / output_name, output_name

    def store_file(
        self,
        *,
        source_path: Path,
        output_name: str,
        content_type: str | None,
        media_type: str,
    ) -> StoredMedia:
        file_path = str(Path(self.artifact_root) / output_name)
        return StoredMedia(
            storage_backend="local",
            storage_key=file_path,
            file_path=file_path,
            preview_url=f"/artifacts/uploads/{output_name}",
            metadata={
                "upload_source": "api",
                "storage_note": "Local artifact storage.",
            },
            delete_local_after_record=False,
        )


class S3MediaStorage(LocalMediaStorage):
    def __init__(
        self,
        *,
        uploads_dir: Path,
        bucket: str,
        region: str | None = None,
        prefix: str = "inspection-media",
        endpoint_url: str | None = None,
        presign_expires_seconds: int = 900,
        client=None,
    ) -> None:
        super().__init__(uploads_dir=uploads_dir)
        self.bucket = bucket
        self.region = region
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url
        self.presign_expires_seconds = presign_expires_seconds
        self._client = client

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    "MEDIA_STORAGE_BACKEND=s3 requires boto3. Install project requirements first."
                ) from exc
            client_kwargs = {}
            if self.region:
                client_kwargs["region_name"] = self.region
            if self.endpoint_url:
                client_kwargs["endpoint_url"] = self.endpoint_url
            self._client = boto3.client("s3", **client_kwargs)
        return self._client

    def store_file(
        self,
        *,
        source_path: Path,
        output_name: str,
        content_type: str | None,
        media_type: str,
    ) -> StoredMedia:
        storage_key = self._object_key(output_name, media_type=media_type)
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        if extra_args:
            self.client.upload_file(
                str(source_path),
                self.bucket,
                storage_key,
                ExtraArgs=extra_args,
            )
        else:
            self.client.upload_file(str(source_path), self.bucket, storage_key)
        preview_url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": storage_key},
            ExpiresIn=self.presign_expires_seconds,
        )
        return StoredMedia(
            storage_backend="s3",
            storage_key=storage_key,
            file_path=f"s3://{self.bucket}/{storage_key}",
            preview_url=preview_url,
            metadata={
                "upload_source": "api",
                "bucket": self.bucket,
                "region": self.region or "",
                "endpoint_url": self.endpoint_url or "",
                "presign_expires_seconds": str(self.presign_expires_seconds),
            },
            delete_local_after_record=_delete_local_after_s3_upload(),
        )

    def _object_key(self, output_name: str, *, media_type: str) -> str:
        parts = [
            self.prefix,
            media_type,
            output_name,
        ]
        return "/".join(part.strip("/") for part in parts if part.strip("/"))


def build_media_storage(*, uploads_dir: Path):
    backend = os.getenv("MEDIA_STORAGE_BACKEND", "local").strip().lower()
    if backend == "local":
        return LocalMediaStorage(uploads_dir=uploads_dir)
    if backend == "s3":
        bucket = os.getenv("AWS_S3_MEDIA_BUCKET")
        if not bucket:
            raise RuntimeError("MEDIA_STORAGE_BACKEND=s3 requires AWS_S3_MEDIA_BUCKET.")
        return S3MediaStorage(
            uploads_dir=uploads_dir,
            bucket=bucket,
            region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            prefix=os.getenv("AWS_S3_MEDIA_PREFIX", "inspection-media"),
            endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
            presign_expires_seconds=int(os.getenv("AWS_S3_PRESIGN_EXPIRES_SECONDS", "900")),
        )
    raise RuntimeError(f"Unsupported MEDIA_STORAGE_BACKEND: {backend}. Use local or s3.")


def _build_upload_name(original_name: str) -> str:
    safe_name = Path(original_name).name
    stem = Path(safe_name).stem[:60] or "upload"
    extension = Path(safe_name).suffix.lower()
    return f"{stem}_{uuid4().hex[:10]}{extension}"


def _delete_local_after_s3_upload() -> bool:
    return os.getenv("AWS_S3_DELETE_LOCAL_AFTER_UPLOAD", "false").lower() in {
        "1",
        "true",
        "yes",
    }
