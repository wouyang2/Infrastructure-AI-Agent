from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoFrameSample:
    video_path: str
    image_path: str
    timestamp_seconds: float


class VideoFrameSampler:
    def sample(self, video_path: str) -> list[VideoFrameSample]:
        raise NotImplementedError


class MockVideoFrameSampler(VideoFrameSampler):
    def __init__(self, timestamps_seconds: list[float] | None = None):
        self.timestamps_seconds = timestamps_seconds or [0.0, 5.0, 10.0]

    def sample(self, video_path: str) -> list[VideoFrameSample]:
        path = Path(video_path)
        return [
            VideoFrameSample(
                video_path=video_path,
                image_path=f"{path.stem}_frame_{int(timestamp):04d}{path.suffix}",
                timestamp_seconds=timestamp,
            )
            for timestamp in self.timestamps_seconds
        ]


class OpenCVVideoFrameSampler(VideoFrameSampler):
    def __init__(
        self,
        output_dir: str = "artifacts/video_frames",
        interval_seconds: float = 5.0,
        max_frames: int = 3,
        image_extension: str = ".jpg",
    ):
        if interval_seconds <= 0:
            raise ValueError("Video frame interval must be greater than 0.")
        if max_frames <= 0:
            raise ValueError("Video max frames must be greater than 0.")

        self.output_dir = Path(output_dir)
        self.interval_seconds = interval_seconds
        self.max_frames = max_frames
        self.image_extension = (
            image_extension if image_extension.startswith(".") else f".{image_extension}"
        )

    def sample(self, video_path: str) -> list[VideoFrameSample]:
        cv2 = self._cv2()
        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            raise ValueError(f"Could not open video for frame sampling: {video_path}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamps = self._sample_timestamps(capture)
        samples: list[VideoFrameSample] = []

        try:
            for index, timestamp in enumerate(timestamps):
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                ok, frame = capture.read()
                if not ok:
                    continue

                output_path = self._frame_path(video_path, index, timestamp)
                if not cv2.imwrite(str(output_path), frame):
                    continue

                samples.append(
                    VideoFrameSample(
                        video_path=video_path,
                        image_path=str(output_path),
                        timestamp_seconds=timestamp,
                    )
                )
        finally:
            capture.release()

        if not samples:
            raise ValueError(f"No readable frames were extracted from video: {video_path}")

        return samples

    def _sample_timestamps(self, capture) -> list[float]:
        fps = float(capture.get(self._cv2().CAP_PROP_FPS) or 0)
        frame_count = float(capture.get(self._cv2().CAP_PROP_FRAME_COUNT) or 0)
        duration_seconds = frame_count / fps if fps > 0 and frame_count > 0 else None

        timestamps: list[float] = []
        for index in range(self.max_frames):
            timestamp = index * self.interval_seconds
            if duration_seconds is not None and timestamp > duration_seconds:
                break
            timestamps.append(float(timestamp))

        return timestamps or [0.0]

    def _frame_path(self, video_path: str, index: int, timestamp_seconds: float) -> Path:
        timestamp_ms = int(round(timestamp_seconds * 1000))
        video_stem = Path(video_path).stem
        return self.output_dir / (
            f"{video_stem}_frame_{index:03}_{timestamp_ms:08}"
            f"{self.image_extension}"
        )

    def _cv2(self):
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV video sampling requires 'opencv-python'. "
                "Install requirements before using '--video-sampler opencv'."
            ) from exc
        return cv2


def build_video_frame_sampler(
    mode: str,
    *,
    interval_seconds: float = 5.0,
    max_frames: int = 3,
) -> VideoFrameSampler:
    if mode == "mock":
        return MockVideoFrameSampler()
    if mode == "opencv":
        return OpenCVVideoFrameSampler(
            interval_seconds=interval_seconds,
            max_frames=max_frames,
        )
    raise ValueError(f"Unsupported video sampler mode: {mode}")
