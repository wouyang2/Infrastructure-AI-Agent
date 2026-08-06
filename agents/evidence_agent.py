from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.helpers.image_analyzer import HeuristicImageAnalyzer, ImageAnalyzer, ImageFinding
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

    def extract_observations(
        self,
        inspection_case: InspectionCase,
        visual_analysis_results: list[dict[str, Any]] | None = None,
    ) -> list[Observation]:
        observations: list[Observation] = []
        visual_results = visual_analysis_results or []

        for evidence in inspection_case.evidence:
            if evidence.modality == "image":
                image_results = self._visual_results_for_source(
                    visual_results,
                    source_id=evidence.source_id,
                    source_modality="image",
                )
                if image_results:
                    observations.extend(
                        self._observations_from_visual_results(
                            evidence,
                            image_results,
                            start_index=len(observations) + 1,
                        )
                    )
                else:
                    observations.extend(
                        self._extract_image_observations(
                            evidence,
                            inspection_case,
                            start_index=len(observations) + 1,
                        )
                    )
                continue

            if evidence.modality == "video":
                video_results = self._visual_results_for_source(
                    visual_results,
                    source_id=evidence.source_id,
                    source_modality="video_frame",
                )
                if video_results:
                    observations.extend(
                        self._observations_from_visual_results(
                            evidence,
                            video_results,
                            start_index=len(observations) + 1,
                        )
                    )
                else:
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

    def _visual_results_for_source(
        self,
        visual_analysis_results: list[dict[str, Any]],
        *,
        source_id: str,
        source_modality: str,
    ) -> list[dict[str, Any]]:
        return [
            result
            for result in visual_analysis_results
            if result.get("source_id") == source_id
            and result.get("source_modality") == source_modality
        ]

    def _observations_from_visual_results(
        self,
        evidence: Evidence,
        visual_results: list[dict[str, Any]],
        *,
        start_index: int,
    ) -> list[Observation]:
        observations: list[Observation] = []
        for result in visual_results:
            analyzed_image_path = str(result.get("analyzed_image_path") or "")
            source_modality = result.get("source_modality", evidence.modality)
            media_file_path = str(result.get("source_file_path") or evidence.file_path or "")
            frame_timestamp_seconds = result.get("frame_timestamp_seconds")
            for finding_payload in result.get("findings", []):
                finding = self._finding_from_payload(finding_payload)
                description = finding.description
                if source_modality == "video_frame" and frame_timestamp_seconds is not None:
                    description = (
                        f"{description} "
                        f"Sampled from video at {float(frame_timestamp_seconds):g}s."
                    )
                observations.append(
                    Observation(
                        observation_id=f"OBS-{start_index + len(observations):03}",
                        source_id=evidence.source_id,
                        source_modality=source_modality,
                        defect_type=finding.defect_type,
                        description=description,
                        location_on_asset=finding.location_on_asset,
                        media_reference=MediaReference(
                            file_path=media_file_path,
                            frame_timestamp_seconds=frame_timestamp_seconds,
                            bounding_box=finding.bounding_box,
                        ),
                        measurement=self._finding_measurement(
                            finding,
                            analyzed_image_path or media_file_path,
                        ),
                        confidence=finding.confidence,
                    )
                )
        return observations

    def _finding_from_payload(self, payload: dict[str, Any]) -> ImageFinding:
        bounding_box = payload.get("bounding_box")
        if bounding_box is not None:
            bounding_box = tuple(bounding_box)
        return ImageFinding(
            defect_type=str(payload.get("defect_type", "unknown")),
            description=str(payload.get("description", "")),
            location_on_asset=str(
                payload.get("location_on_asset", "visible area in image")
            ),
            confidence=float(payload.get("confidence", 0.0)),
            bounding_box=bounding_box,
            severity_label=payload.get("severity_label"),
        )

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
