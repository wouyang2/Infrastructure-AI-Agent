from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image

from storage.media_storage import build_media_storage


def main() -> None:
    if os.getenv("MEDIA_STORAGE_BACKEND") != "s3":
        raise SystemExit(
            "Set MEDIA_STORAGE_BACKEND=s3 plus AWS_S3_MEDIA_BUCKET/AWS_REGION before running."
        )

    uploads_dir = Path("artifacts") / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    storage = build_media_storage(uploads_dir=uploads_dir)
    output_path, output_name = storage.build_upload_path("aws-smoke.png")
    image_bytes = BytesIO()
    Image.new("RGB", (2, 2), color=(255, 255, 255)).save(image_bytes, format="PNG")
    output_path.write_bytes(image_bytes.getvalue())

    stored = storage.store_file(
        source_path=output_path,
        output_name=output_name,
        content_type="image/png",
        media_type="image",
    )

    print("Uploaded media through configured backend.")
    print(f"storage_backend={stored.storage_backend}")
    print(f"storage_key={stored.storage_key}")
    print(f"file_path={stored.file_path}")
    print(f"preview_url={stored.preview_url[:120]}...")


if __name__ == "__main__":
    main()
