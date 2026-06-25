from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from models import InspectionReport, Observation


DEFECT_COLORS = {
    "exposed_rebar": (40, 40, 230),
    "spalling": (0, 140, 255),
    "crack": (40, 190, 40),
    "corrosion": (190, 90, 20),
    "unknown": (160, 160, 160),
}


class AnnotatedImageArtifactGenerator:
    def __init__(self, output_dir: str = "artifacts/annotated_images"):
        self.output_dir = Path(output_dir)

    def generate(self, report: InspectionReport) -> list[str]:
        grouped = self._group_image_observations(report.observations)
        if not grouped:
            return []

        try:
            import cv2
        except ImportError:
            return []

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_paths = []
        for image_path, observations in grouped.items():
            image = cv2.imread(str(image_path))
            if image is None:
                continue

            for observation in observations:
                box = observation.media_reference.bounding_box  # type: ignore[union-attr]
                if box is None:
                    continue
                x, y, width, height = box
                color = DEFECT_COLORS.get(observation.defect_type, DEFECT_COLORS["unknown"])
                cv2.rectangle(image, (x, y), (x + width, y + height), color, 4)
                label = f"{observation.defect_type} {observation.confidence:.0%}"
                cv2.putText(
                    image,
                    label,
                    (x, max(y - 12, 24)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    color,
                    2,
                    cv2.LINE_AA,
                )

            output_path = self.output_dir / self._artifact_name(report, image_path)
            cv2.imwrite(str(output_path), image)
            output_paths.append(str(output_path))

        return output_paths

    def _group_image_observations(
        self,
        observations: list[Observation],
    ) -> dict[Path, list[Observation]]:
        grouped: dict[Path, list[Observation]] = defaultdict(list)
        for observation in observations:
            reference = observation.media_reference
            if (
                observation.source_modality != "image"
                or reference is None
                or reference.bounding_box is None
            ):
                continue
            image_path = Path(reference.file_path)
            if image_path.exists():
                grouped[image_path].append(observation)
        return grouped

    def _artifact_name(self, report: InspectionReport, image_path: Path) -> str:
        case_id = _safe_name(report.case.case_id)
        stem = _safe_name(image_path.stem)
        return f"{case_id}_{stem}_annotated.jpg"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
