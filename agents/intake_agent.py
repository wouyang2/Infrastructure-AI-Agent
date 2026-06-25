from __future__ import annotations

from models import Asset, Evidence, InspectionCase


class IntakeAgent:
    def create_case(
        self,
        *,
        asset_id: str,
        asset_type: str,
        asset_name: str,
        location: str,
        criticality: str,
        inspection_notes: str,
        image_paths: list[str] | None = None,
        video_paths: list[str] | None = None,
        asset_metadata: dict | None = None,
        reason: str = "routine",
    ) -> InspectionCase:
        asset = Asset(
            asset_id=asset_id,
            asset_type=asset_type,
            name=asset_name,
            location=location,
            criticality=criticality,  # type: ignore[arg-type]
            metadata=asset_metadata or {},
        )
        evidence = [
            Evidence(
                source_id="EV-001",
                source_type="inspection_notes",
                content=inspection_notes,
                modality="text",
            )
        ]
        next_index = 2
        for image_path in image_paths or []:
            evidence.append(
                Evidence(
                    source_id=f"EV-{next_index:03}",
                    source_type="inspection_image",
                    content=f"Inspection image: {image_path}",
                    modality="image",
                    file_path=image_path,
                )
            )
            next_index += 1
        for video_path in video_paths or []:
            evidence.append(
                Evidence(
                    source_id=f"EV-{next_index:03}",
                    source_type="inspection_video",
                    content=f"Inspection video: {video_path}",
                    modality="video",
                    file_path=video_path,
                )
            )
            next_index += 1
        return InspectionCase(
            case_id=f"CASE-{asset_id}",
            asset=asset,
            reason=reason,
            evidence=evidence,
        )
