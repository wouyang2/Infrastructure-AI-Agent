from __future__ import annotations

from typing import Literal

from agents.helpers.maintenance_plan_generator import LLMMaintenancePlanGenerator
from agents.helpers.observation_selection import select_primary_observation
from models import (
    HistoricalPrecedent,
    InspectionCase,
    MaintenancePlan,
    MaintenanceTask,
    Observation,
    SeverityAssessment,
)
from rag.interfaces import KnowledgeRetriever


PlanningMode = Literal["deterministic", "llm"]
LLMFailureMode = Literal["fallback", "fail"]


class MaintenancePlanningAgent:
    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        planning_mode: PlanningMode = "deterministic",
        planning_generator: LLMMaintenancePlanGenerator | None = None,
        llm_max_retries: int = 4,
        llm_failure_mode: LLMFailureMode = "fallback",
    ):
        self.retriever = retriever
        self.planning_mode = planning_mode
        self.planning_generator = planning_generator
        self.llm_max_retries = llm_max_retries
        self.llm_failure_mode = llm_failure_mode

        if planning_mode not in {"deterministic", "llm"}:
            raise ValueError(f"Unsupported planning mode: {planning_mode}")

    def create_plan(
        self,
        inspection_case: InspectionCase,
        observations: list[Observation],
        severity: SeverityAssessment,
    ) -> MaintenancePlan:
        if not severity.repair_required:
            return self._create_monitoring_plan()

        primary = select_primary_observation(observations)
        precedents = self._retrieve_historical_precedents(
            inspection_case,
            primary,
            severity,
        )
        deterministic_plan = self._create_repair_plan(
            inspection_case,
            primary,
            precedents,
        )

        if self.planning_mode == "deterministic":
            return deterministic_plan

        generator = self.planning_generator or LLMMaintenancePlanGenerator(
            max_retries=self.llm_max_retries,
            failure_mode=self.llm_failure_mode,
        )
        return generator.generate(
            inspection_case,
            observations,
            severity,
            precedents,
            deterministic_plan,
        )

    def _create_monitoring_plan(self) -> MaintenancePlan:
        return MaintenancePlan(
            recommended_action="Continue monitoring and schedule follow-up inspection.",
            historical_precedents=[],
            tasks=[
                MaintenanceTask(
                    name="Follow-up inspection",
                    description="Reinspect the observed condition and compare against current notes.",
                    estimated_hours=2,
                )
            ],
            materials=[],
            equipment=["inspection kit"],
            permits=[],
            estimated_duration_hours=2,
            risks=["Condition may progress before the follow-up inspection."],
        )

    def _create_repair_plan(
        self,
        inspection_case: InspectionCase,
        primary: Observation,
        precedents: list[HistoricalPrecedent],
    ) -> MaintenancePlan:
        precedent_documents = self._precedent_documents(precedents)
        repair_method = self._choose_repair_method(primary.defect_type, precedents)
        tasks = self._build_tasks(primary.defect_type, repair_method)
        estimated_duration = self._estimate_duration(tasks, precedents)

        return MaintenancePlan(
            recommended_action=repair_method,
            historical_precedents=precedents,
            tasks=tasks,
            materials=self._materials_for(primary.defect_type, precedent_documents),
            equipment=self._equipment_for(precedent_documents),
            permits=self._permits_for(inspection_case, precedent_documents),
            estimated_duration_hours=estimated_duration,
            risks=self._risks_for(precedent_documents),
        )

    def _retrieve_historical_precedents(
        self,
        inspection_case: InspectionCase,
        observation: Observation,
        severity: SeverityAssessment,
    ) -> list[HistoricalPrecedent]:
        query = (
            f"{inspection_case.asset.asset_type} {observation.defect_type} "
            f"{severity.severity} repair duration outcome disruption {observation.description}"
        )
        citations = self.retriever.search(
            query,
            source_type="repair_record",
            asset_type=inspection_case.asset.asset_type,
            defect_type=observation.defect_type if observation.defect_type != "unknown" else None,
            limit=3,
        )

        precedents: list[HistoricalPrecedent] = []
        for citation in citations:
            document = self.retriever.get_document(citation.document_id)
            if not document:
                continue
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
        return precedents

    def _choose_repair_method(
        self,
        defect_type: str,
        precedents: list[HistoricalPrecedent],
    ) -> str:
        successful = [
            precedent
            for precedent in precedents
            if "successful" in precedent.outcome.lower()
        ]
        if successful:
            return successful[0].repair_method

        fallback_methods = {
            "crack": "seal crack and monitor for recurrence",
            "spalling": "remove loose material and patch damaged area",
            "exposed_rebar": "clean exposed reinforcement and restore concrete cover",
            "leak": "isolate affected section and repair leak source",
            "corrosion": "clean corrosion, protect substrate, and monitor",
        }
        return fallback_methods.get(defect_type, "perform targeted repair after field verification")

    def _build_tasks(self, defect_type: str, repair_method: str) -> list[MaintenanceTask]:
        return [
            MaintenanceTask(
                name="Prepare work area",
                description="Set up access, safety controls, and temporary protection.",
                estimated_hours=1.5,
            ),
            MaintenanceTask(
                name="Perform repair",
                description=f"Apply selected method: {repair_method}.",
                estimated_hours=5.0 if defect_type != "spalling" else 8.0,
                dependencies=["Prepare work area"],
            ),
            MaintenanceTask(
                name="Verify repair",
                description="Inspect completed work and document remaining risk.",
                estimated_hours=1.5,
                dependencies=["Perform repair"],
            ),
        ]

    def _estimate_duration(
        self,
        tasks: list[MaintenanceTask],
        precedents: list[HistoricalPrecedent],
    ) -> float:
        if precedents:
            return round(
                sum(precedent.actual_duration_hours for precedent in precedents)
                / len(precedents),
                1,
            )
        return sum(task.estimated_hours for task in tasks)

    def _precedent_documents(
        self,
        precedents: list[HistoricalPrecedent],
    ) -> list[dict]:
        documents = []
        for precedent in precedents:
            document = self.retriever.get_document(precedent.document_id)
            if document:
                documents.append(document)
        return documents

    def _materials_for(
        self,
        defect_type: str,
        precedent_documents: list[dict],
    ) -> list[str]:
        precedent_materials = self._split_record_items(
            document.get("materials_used", "")
            for document in precedent_documents
        )
        if precedent_materials:
            return precedent_materials

        materials = {
            "crack": ["sealant", "epoxy injection material", "surface cleaner"],
            "spalling": ["patching concrete", "corrosion inhibitor", "bonding agent"],
            "exposed_rebar": ["repair mortar", "corrosion inhibitor", "bonding agent"],
            "leak": ["replacement section", "valves", "pipe fittings"],
            "corrosion": ["coating system", "abrasive pads", "corrosion inhibitor"],
        }
        return materials.get(defect_type, ["field-selected repair materials"])

    def _equipment_for(self, precedent_documents: list[dict]) -> list[str]:
        equipment = self._split_record_items(
            document.get("equipment_used", "")
            for document in precedent_documents
        )
        default_equipment = ["basic access equipment", "safety barriers", "inspection tools"]
        return self._dedupe([*equipment, *default_equipment])

    def _permits_for(
        self,
        inspection_case: InspectionCase,
        precedent_documents: list[dict],
    ) -> list[str]:
        permits = []
        precedent_requires_permit = any(
            str(document.get("permit_required", "")).lower() == "yes"
            for document in precedent_documents
        )
        if precedent_requires_permit or inspection_case.asset.asset_type in {"road", "bridge"}:
            permits.append("work zone permit")
        if any(
            "full closure" in str(document.get("closure_type", "")).lower()
            for document in precedent_documents
        ):
            permits.append("closure coordination approval")
        return permits

    def _risks_for(self, precedent_documents: list[dict]) -> list[str]:
        risks = [
            "Hidden damage may increase scope after surface preparation.",
            "Weather or access limits may shift the repair window.",
        ]
        if any(
            str(document.get("recurrence_within_12_months", "")).lower() == "true"
            for document in precedent_documents
        ):
            risks.append("Similar historical repairs had recurrence within 12 months.")
        if any(
            "temporary" in str(document.get("repair_outcome", "")).lower()
            or "follow-up" in str(document.get("repair_outcome", "")).lower()
            for document in precedent_documents
        ):
            risks.append("Some comparable repairs required follow-up or temporary mitigation.")
        if self._historical_duration_overrun(precedent_documents):
            risks.append("Comparable repair records show duration overrun risk.")
        return risks

    def _historical_duration_overrun(self, precedent_documents: list[dict]) -> bool:
        for document in precedent_documents:
            planned = self._optional_float(document.get("planned_duration_hours"))
            actual = self._optional_float(document.get("actual_duration_hours"))
            if planned and actual and actual > planned * 1.15:
                return True
        return False

    def _split_record_items(self, values) -> list[str]:
        items = []
        for value in values:
            if not value:
                continue
            items.extend(part.strip() for part in str(value).split(";") if part.strip())
        return self._dedupe(items)

    def _dedupe(self, values: list[str]) -> list[str]:
        deduped = []
        seen = set()
        for value in values:
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped

    def _optional_float(self, value) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
