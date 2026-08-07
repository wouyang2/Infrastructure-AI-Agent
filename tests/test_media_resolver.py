from __future__ import annotations

from pathlib import Path

import pytest

from storage.media_resolver import LocalAndS3MediaResolver


class FakeS3DownloadClient:
    def __init__(self) -> None:
        self.downloads = []

    def download_file(self, bucket, key, filename):
        self.downloads.append({"bucket": bucket, "key": key, "filename": filename})
        Path(filename).write_bytes(b"downloaded")


def test_media_resolver_leaves_local_paths_unchanged(tmp_path) -> None:
    resolver = LocalAndS3MediaResolver(cache_dir=tmp_path)

    resolved = resolver.resolve("artifacts/uploads/bridge.png")

    assert resolved.original_path == "artifacts/uploads/bridge.png"
    assert resolved.local_path == "artifacts/uploads/bridge.png"
    assert resolved.storage_backend == "local"
    assert resolved.storage_key is None
    assert resolved.bucket is None


def test_media_resolver_downloads_s3_uri_to_cache(tmp_path) -> None:
    client = FakeS3DownloadClient()
    resolver = LocalAndS3MediaResolver(cache_dir=tmp_path, client=client)

    resolved = resolver.resolve("s3://infra-bucket/inspection-media/image/bridge.png")

    assert resolved.original_path == "s3://infra-bucket/inspection-media/image/bridge.png"
    assert resolved.storage_backend == "s3"
    assert resolved.storage_key == "inspection-media/image/bridge.png"
    assert resolved.bucket == "infra-bucket"
    assert Path(resolved.local_path).exists()
    assert Path(resolved.local_path).read_bytes() == b"downloaded"
    assert client.downloads == [
        {
            "bucket": "infra-bucket",
            "key": "inspection-media/image/bridge.png",
            "filename": resolved.local_path,
        }
    ]


def test_media_resolver_reuses_cached_s3_download(tmp_path) -> None:
    client = FakeS3DownloadClient()
    resolver = LocalAndS3MediaResolver(cache_dir=tmp_path, client=client)

    first = resolver.resolve("s3://infra-bucket/inspection-media/image/bridge.png")
    second = resolver.resolve("s3://infra-bucket/inspection-media/image/bridge.png")

    assert first.local_path == second.local_path
    assert len(client.downloads) == 1


def test_media_resolver_rejects_invalid_s3_uri(tmp_path) -> None:
    resolver = LocalAndS3MediaResolver(cache_dir=tmp_path)

    with pytest.raises(ValueError, match="Invalid S3 media URI"):
        resolver.resolve("s3://infra-bucket")
