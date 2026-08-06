from __future__ import annotations

from agents.helpers.observation_selection import select_primary_observation
from models import Citation, InspectionCase, Observation
from rag.interfaces import KnowledgeRetriever


class SeverityGuidanceTool:
    """RAG tool for severity standards and policy guidance."""

    def __init__(self, retriever: KnowledgeRetriever | None):
        self.retriever = retriever

    def invoke(
        self,
        *,
        inspection_case: InspectionCase,
        observations: list[Observation],
    ) -> list[Citation]:
        if not self.retriever:
            return []

        primary = select_primary_observation(observations)
        if primary.defect_type == "unknown":
            return []

        return self.retriever.search(
            build_severity_guidance_query(inspection_case, primary),
            source_type="standard",
            asset_type=inspection_case.asset.asset_type,
            defect_type=primary.defect_type,
            limit=2,
        )


def build_severity_guidance_query(
    inspection_case: InspectionCase,
    observation: Observation,
) -> str:
    return (
        f"{inspection_case.asset.asset_type} {observation.defect_type} "
        f"{inspection_case.asset.criticality} {observation.description}"
    )
