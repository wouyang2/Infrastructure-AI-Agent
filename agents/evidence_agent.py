from __future__ import annotations

from pathlib import Path

from agents.helpers.image_analyzer import HeuristicImageAnalyzer, ImageAnalyzer
from agents.helpers.video_sampler import MockVideoFrameSampler, VideoFrameSampler
from models import Evidence, InspectionCase, MediaReference, Observation


class EvidenceAgent:
    DEFECT_KEYWORDS = {
        "crack": ["crack", "cracking", "fracture"],
        "spalling": ["spall", "spalling", "loose concrete", "delamination"],
        "leak": ["leak", "water intrusion", "seepage", "drip"],
        "corrosion": ["corrosion", "rust", "oxidation"],
    }

    def __init__(
        self,
        image_analyzer: ImageAnalyzer | None = None,
        video_frame_sampler: VideoFrameSampler | None = None,
    ):
        self.image_analyzer = image_analyzer or HeuristicImageAnalyzer()
        self.video_frame_sampler = video_frame_sampler or MockVideoFrameSampler()

    def extract_observations(self, inspection_case: InspectionCase) -> list[Observation]:
        observations: list[Observation] = []

        for evidence in inspection_case.evidence:
            if evidence.modality == "image":
                observations.extend(
                    self._extract_image_observations(
                        evidence,
                        inspection_case,
                        start_index=len(observations) + 1,
                    )
                )
                continue

            if evidence.modality == "video":
                observations.extend(
                    self._extract_video_observations(
                        evidence,
                        inspection_case,
                        start_index=len(observations) + 1,
                    )
                )
                continue

            observations.extend(
                self._extract_text_observations(
                    evidence,
                    start_index=len(observations) + 1,
                )
            )

        if observations:
            return observations

        return [
            Observation(
                observation_id="OBS-001",
                source_id=inspection_case.evidence[0].source_id,
                source_modality=inspection_case.evidence[0].modality,
                defect_type="unknown",
                description=inspection_case.evidence[0].content,
                location_on_asset="unspecified",
                confidence=0.4,
            )
        ]

    def _extract_text_observations(
        self,
        evidence: Evidence,
        *,
        start_index: int,
    ) -> list[Observation]:
        observations: list[Observation] = []
        text = evidence.content.lower()
        for defect_type, keywords in self.DEFECT_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                observations.append(
                    Observation(
                        observation_id=f"OBS-{start_index + len(observations):03}",
                        source_id=evidence.source_id,
                        source_modality=evidence.modality,
                        defect_type=defect_type,
                        description=evidence.content,
                        location_on_asset="unspecified",
                        confidence=0.75,
                    )
                )
        return observations

    def _extract_image_observations(
        self,
        evidence: Evidence,
        inspection_case: InspectionCase,
        *,
        start_index: int,
    ) -> list[Observation]:
        if not evidence.file_path:
            return []

        findings = self.image_analyzer.analyze(
            evidence.file_path,
            inspection_case.asset.asset_type,
        )
        return [
            Observation(
                observation_id=f"OBS-{start_index + index:03}",
                source_id=evidence.source_id,
                source_modality="image",
                defect_type=finding.defect_type,
                description=finding.description,
                location_on_asset=finding.location_on_asset,
                media_reference=MediaReference(
                    file_path=evidence.file_path,
                    frame_timestamp_seconds=evidence.frame_timestamp_seconds,
                    bounding_box=finding.bounding_box,
                ),
                measurement=self._finding_measurement(finding, evidence.file_path),
                confidence=finding.confidence,
            )
            for index, finding in enumerate(findings)
        ]

    def _extract_video_observations(
        self,
        evidence: Evidence,
        inspection_case: InspectionCase,
        *,
        start_index: int,
    ) -> list[Observation]:
        if not evidence.file_path:
            return []

        observations: list[Observation] = []
        for frame in self.video_frame_sampler.sample(evidence.file_path):
            findings = self.image_analyzer.analyze(
                frame.image_path,
                inspection_case.asset.asset_type,
            )
            for finding in findings:
                observations.append(
                    Observation(
                        observation_id=f"OBS-{start_index + len(observations):03}",
                        source_id=evidence.source_id,
                        source_modality="video_frame",
                        defect_type=finding.defect_type,
                        description=(
                            f"{finding.description} "
                            f"Sampled from video at {frame.timestamp_seconds:g}s."
                        ),
                        location_on_asset=finding.location_on_asset,
                        media_reference=MediaReference(
                            file_path=evidence.file_path,
                            frame_timestamp_seconds=frame.timestamp_seconds,
                            bounding_box=finding.bounding_box,
                        ),
                        measurement=self._finding_measurement(finding, frame.image_path),
                        confidence=finding.confidence,
                    )
                )
        return observations

    def _finding_measurement(self, finding, analyzed_image_path: str) -> dict[str, str | float | int]:
        measurement: dict[str, str | float | int] = {}
        if finding.severity_label:
            measurement["severity_label"] = finding.severity_label
            measurement["severity_label_source"] = type(self.image_analyzer).__name__
        if finding.bounding_box:
            _, _, width, height = finding.bounding_box
            area = max(0, width) * max(0, height)
            measurement["bbox_area"] = area
            image_size = self._image_size(analyzed_image_path)
            if image_size:
                image_width, image_height = image_size
                measurement["image_width"] = image_width
                measurement["image_height"] = image_height
                image_area = image_width * image_height
                if image_area:
                    measurement["bbox_relative_area"] = round(area / image_area, 6)
        return measurement

    def _image_size(self, image_path: str) -> tuple[int, int] | None:
        if not Path(image_path).exists():
            return None
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            with Image.open(image_path) as image:
                return image.size
        except OSError:
            return None
