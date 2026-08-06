from __future__ import annotations

from typing import Any

from models import InspectionCase, MaintenancePlan, SeverityAssessment
from rag.interfaces import KnowledgeRetriever


class SchedulingPrecedentTool:
    """RAG tool for schedule precedent lookup.

    The scheduling agent should consume these records, not own the retrieval.
    Keeping this as a separate callable makes the graph boundary explicit and
    gives us a natural place to add SQL/Redis idempotency later.
    """

    def __init__(self, retriever: KnowledgeRetriever | None):
        self.retriever = retriever

    def invoke(
        self,
        *,
        inspection_case: InspectionCase,
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
    ) -> list[dict[str, Any]]:
        if not self.retriever:
            return []

        defect_type = infer_scheduling_defect_type(severity, maintenance_plan)
        query = (
            f"{inspection_case.asset.asset_type} {severity.severity} "
            f"{defect_type or ''} "
            f"{maintenance_plan.recommended_action} "
            f"{maintenance_plan.estimated_duration_hours:g} hours "
            f"{' '.join(maintenance_plan.permits)} "
            f"{' '.join(maintenance_plan.equipment)} scheduling disruption "
            "crew closure weather traffic event access"
        )
        citations = self.retriever.search(
            query,
            source_type="schedule_record",
            asset_type=inspection_case.asset.asset_type,
            defect_type=defect_type,
            limit=8,
        )
        documents = []
        for citation in citations:
            document = self.retriever.get_document(citation.document_id)
            if document:
                documents.append(document)
        return sorted(
            documents,
            key=lambda document: scheduling_precedent_match_score(
                document,
                inspection_case,
                severity,
                maintenance_plan,
                defect_type,
            ),
            reverse=True,
        )[:3]


def infer_scheduling_defect_type(
    severity: SeverityAssessment,
    maintenance_plan: MaintenancePlan,
) -> str | None:
    text = " ".join(
        [
            maintenance_plan.recommended_action,
            *maintenance_plan.materials,
            *maintenance_plan.equipment,
            *maintenance_plan.permits,
            *[
                precedent.repair_method
                for precedent in maintenance_plan.historical_precedents
            ],
            *[
                f"{citation.document_id} {citation.title} {citation.excerpt}"
                for citation in severity.citations
            ],
        ]
    ).lower()
    if any(term in text for term in ("spall", "patching concrete", "partial-depth")):
        return "spalling"
    if any(term in text for term in ("rebar", "reinforcement", "exposed steel")):
        return "exposed_rebar"
    if any(term in text for term in ("corrosion", "coating", "rust", "steel")):
        return "corrosion"
    if any(term in text for term in ("crack", "routing", "sealing", "sealant")):
        return "crack"
    if "efflorescence" in text:
        return "efflorescence"
    return None


def scheduling_precedent_match_score(
    precedent: dict[str, Any],
    inspection_case: InspectionCase,
    severity: SeverityAssessment,
    maintenance_plan: MaintenancePlan,
    defect_type: str | None,
) -> int:
    score = 0
    if precedent.get("asset_type") == inspection_case.asset.asset_type:
        score += 8
    if defect_type and precedent.get("defect_type") == defect_type:
        score += 10
    if precedent.get("severity") == severity.severity:
        score += 4

    repair_method = str(precedent.get("repair_method", "")).lower()
    recommended_action = maintenance_plan.recommended_action.lower()
    if repair_method and (
        repair_method == recommended_action
        or repair_method in recommended_action
        or recommended_action in repair_method
    ):
        score += 8

    required_crew = required_crew_for_plan(maintenance_plan)
    preferred_crew = str(precedent.get("preferred_crew_type", "")).lower()
    if required_crew and preferred_crew == required_crew:
        score += 4

    planned_duration = precedent.get("planned_duration_hours")
    if isinstance(planned_duration, (int, float)):
        duration_gap = abs(
            float(planned_duration) - maintenance_plan.estimated_duration_hours
        )
        if duration_gap <= 2:
            score += 3
        elif duration_gap <= 6:
            score += 1

    outcome = str(precedent.get("schedule_outcome", "")).lower()
    disruption = str(precedent.get("disruption_outcome", "")).lower()
    if "successful" in outcome:
        score += 3
    if "low" in disruption:
        score += 2
    if "delayed" in outcome or "high" in disruption:
        score -= 3
    return score


def required_crew_for_plan(maintenance_plan: MaintenancePlan) -> str | None:
    text = " ".join(
        [
            maintenance_plan.recommended_action,
            *maintenance_plan.materials,
            *maintenance_plan.equipment,
        ]
    ).lower()
    if any(term in text for term in ("concrete", "patch", "mortar")):
        return "concrete"
    if any(term in text for term in ("coating", "corrosion", "steel", "rebar")):
        return "steel"
    if any(term in text for term in ("joint", "sealant", "sealing")):
        return "joint"
    return None
