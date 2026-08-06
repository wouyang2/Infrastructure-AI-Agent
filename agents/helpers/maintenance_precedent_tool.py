from __future__ import annotations

from typing import Any

from agents.helpers.observation_selection import select_primary_observation
from models import (
    HistoricalPrecedent,
    InspectionCase,
    Observation,
    SeverityAssessment,
)
from rag.interfaces import KnowledgeRetriever


class MaintenancePrecedentTool:
    """RAG tool for historical repair precedents and source documents."""

    def __init__(self, retriever: KnowledgeRetriever | None):
        self.retriever = retriever

    def invoke(
        self,
        *,
        inspection_case: InspectionCase,
        observations: list[Observation],
        severity: SeverityAssessment,
    ) -> dict[str, Any]:
        if not self.retriever or not severity.repair_required:
            return {"historical_precedents": [], "precedent_documents": []}

        primary = select_primary_observation(observations)
        query = (
            f"{inspection_case.asset.asset_type} {primary.defect_type} "
            f"{severity.severity} repair duration outcome disruption {primary.description}"
        )
        citations = self.retriever.search(
            query,
            source_type="repair_record",
            asset_type=inspection_case.asset.asset_type,
            defect_type=primary.defect_type if primary.defect_type != "unknown" else None,
            limit=3,
        )

        precedents: list[HistoricalPrecedent] = []
        documents: list[dict[str, Any]] = []
        for citation in citations:
            document = self.retriever.get_document(citation.document_id)
            if not document:
                continue
            documents.append(document)
            precedents.append(
                HistoricalPrecedent(
                    document_id=document["document_id"],
                    title=document["title"],
                    repair_method=document.get("repair_method", "unknown"),
                    outcome=document.get("repair_outcome", "unknown"),
                    actual_duration_hours=float(document.get("actual_duration_hours", 0)),
                    disruption=document.get("disruption", "unknown"),
                    citation=citation,
                )
            )
        return {
            "historical_precedents": precedents,
            "precedent_documents": documents,
        }
