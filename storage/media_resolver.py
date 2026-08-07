from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class ResolvedMedia:
    original_path: str
    local_path: str
    storage_backend: str
    storage_key: str | None = None
    bucket: str | None = None


class MediaResolver:
    def resolve(self, media_path: str) -> ResolvedMedia:
        raise NotImplementedError


class LocalAndS3MediaResolver(MediaResolver):
    def __init__(
        self,
        *,
        cache_dir: Path | str = "artifacts/resolved_media",
        region: str | None = None,
        endpoint_url: str | None = None,
        client=None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.region = region
        self.endpoint_url = endpoint_url
        self._client = client

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError(
                    "S3 media resolution requires boto3. Install project requirements first."
                ) from exc
            client_kwargs = {}
            if self.region:
                client_kwargs["region_name"] = self.region
            if self.endpoint_url:
                client_kwargs["endpoint_url"] = self.endpoint_url
            self._client = boto3.client("s3", **client_kwargs)
        return self._client

    def resolve(self, media_path: str) -> ResolvedMedia:
        if not media_path.startswith("s3://"):
            return ResolvedMedia(
                original_path=media_path,
                local_path=media_path,
                storage_backend="local",
            )

        bucket, key = _parse_s3_uri(media_path)
        local_path = self._cached_path(bucket=bucket, key=key)
        if not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(bucket, key, str(local_path))

        return ResolvedMedia(
            original_path=media_path,
            local_path=str(local_path),
            storage_backend="s3",
            storage_key=key,
            bucket=bucket,
        )

    def _cached_path(self, *, bucket: str, key: str) -> Path:
        suffix = Path(key).suffix
        stem = Path(key).stem[:80] or "media"
        digest = hashlib.sha256(f"{bucket}/{key}".encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{stem}_{digest}{suffix}"


def build_media_resolver() -> MediaResolver:
    return LocalAndS3MediaResolver(
        cache_dir=os.getenv("MEDIA_RESOLVER_CACHE_DIR", "artifacts/resolved_media"),
        region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
    )


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Invalid S3 media URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")
