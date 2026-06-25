from __future__ import annotations

from math import ceil
from datetime import datetime
from typing import Any, Literal

from agents.helpers.schedule_generator import LLMScheduleGenerator
from models import (
    InspectionCase,
    MaintenancePlan,
    RepairSchedule,
    RepairWindow,
    SchedulingContext,
    SeverityAssessment,
)
from rag.interfaces import KnowledgeRetriever


SchedulingMode = Literal["deterministic", "llm"]
LLMFailureMode = Literal["fallback", "fail"]


class SchedulingAgent:
    def __init__(
        self,
        repair_windows: list[dict[str, Any]],
        retriever: KnowledgeRetriever | None = None,
        *,
        scheduling_mode: SchedulingMode = "llm",
        schedule_generator: LLMScheduleGenerator | None = None,
        llm_max_retries: int = 4,
        llm_failure_mode: LLMFailureMode = "fallback",
    ):
        self.repair_windows = repair_windows
        self.retriever = retriever
        self.scheduling_mode = scheduling_mode
        self.schedule_generator = schedule_generator
        self.llm_max_retries = llm_max_retries
        self.llm_failure_mode = llm_failure_mode

        if scheduling_mode not in {"deterministic", "llm"}:
            raise ValueError(f"Unsupported scheduling mode: {scheduling_mode}")

    def schedule(
        self,
        inspection_case: InspectionCase,
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
        scheduling_context: SchedulingContext,
    ) -> RepairSchedule:
        scheduling_precedents = self._retrieve_scheduling_precedents(
            inspection_case,
            severity,
            maintenance_plan,
        )
        ranked_windows = self._ranked_windows(
            severity,
            maintenance_plan,
            scheduling_context,
            scheduling_precedents,
        )
        deterministic_schedule = self._deterministic_schedule(
            ranked_windows,
            severity,
            maintenance_plan,
            scheduling_context,
            scheduling_precedents,
        )

        if self.scheduling_mode == "deterministic":
            return deterministic_schedule

        generator = self.schedule_generator or LLMScheduleGenerator(
            max_retries=self.llm_max_retries,
            failure_mode=self.llm_failure_mode,
        )
        return generator.generate(
            inspection_case,
            severity,
            maintenance_plan,
            scheduling_context,
            ranked_windows,
            scheduling_precedents,
            deterministic_schedule,
        )

    def _ranked_windows(
        self,
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
        scheduling_context: SchedulingContext,
        scheduling_precedents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ranked_windows = sorted(
            self.repair_windows,
            key=lambda window: self._window_score(
                window,
                severity,
                maintenance_plan,
                scheduling_context,
                scheduling_precedents,
            ),
        )
        return [
            {
                **window,
                "score": self._window_score(
                    window,
                    severity,
                    maintenance_plan,
                    scheduling_context,
                    scheduling_precedents,
                ),
                "context_risk_score": self._context_risk(window, scheduling_context),
                "duration_hours": self._window_duration_hours(window),
            }
            for window in ranked_windows
        ]

    def _deterministic_schedule(
        self,
        ranked_windows: list[dict[str, Any]],
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
        scheduling_context: SchedulingContext,
        scheduling_precedents: list[dict[str, Any]],
    ) -> RepairSchedule:
        selected = ranked_windows[0]
        context_risk = self._context_risk(selected, scheduling_context)
        total_score = int(selected["score"])

        constraints = [
            f"selected {selected['crew']}",
            selected["notes"],
        ]
        constraints.extend(self._resource_constraints(selected, maintenance_plan))
        tradeoffs = []
        if severity.urgency in {"priority", "emergency"}:
            tradeoffs.append("Prioritized earlier repair over absolute lowest disruption.")
        else:
            tradeoffs.append("Selected low-disruption window because urgency allows scheduling flexibility.")
        tradeoffs.extend(self._resource_tradeoffs(selected, maintenance_plan))
        tradeoffs.extend(self._precedent_tradeoffs(selected, scheduling_precedents))

        return RepairSchedule(
            recommended_window=RepairWindow(
                start=datetime.fromisoformat(selected["start"]),
                end=datetime.fromisoformat(selected["end"]),
            ),
            disruption_score=selected["disruption_score"],
            context_risk_score=context_risk,
            total_score=total_score,
            constraints_satisfied=constraints,
            tradeoffs=tradeoffs,
            context_summary=[
                *self._context_summary(selected, scheduling_context),
                *self._precedent_summary(scheduling_precedents),
            ],
        )

    def _window_score(
        self,
        window: dict[str, Any],
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
        scheduling_context: SchedulingContext,
        scheduling_precedents: list[dict[str, Any]],
    ) -> int:
        disruption = int(window["disruption_score"])
        context_risk = self._context_risk(window, scheduling_context)
        score = (
            disruption
            + context_risk
            + self._resource_penalty(window, maintenance_plan)
            + self._precedent_penalty(window, scheduling_precedents)
        )
        if severity.urgency in {"priority", "emergency"}:
            start = datetime.fromisoformat(window["start"])
            hours_from_reference = (start - datetime(2026, 6, 18)).total_seconds() / 3600
            score += int(hours_from_reference / 8)
        return score

    def _retrieve_scheduling_precedents(
        self,
        inspection_case: InspectionCase,
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
    ) -> list[dict[str, Any]]:
        if not self.retriever:
            return []

        defect_type = self._infer_defect_type(severity, maintenance_plan)
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
            key=lambda document: self._scheduling_precedent_match_score(
                document,
                inspection_case,
                severity,
                maintenance_plan,
                defect_type,
            ),
            reverse=True,
        )[:3]

    def _infer_defect_type(
        self,
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

    def _scheduling_precedent_match_score(
        self,
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

        required_crew = self._required_crew(maintenance_plan)
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

    def _resource_penalty(
        self,
        window: dict[str, Any],
        maintenance_plan: MaintenancePlan,
    ) -> int:
        penalty = 0
        if str(window.get("crew_available", "true")).lower() == "false":
            penalty += 1000

        duration_gap = maintenance_plan.estimated_duration_hours - self._window_duration_hours(window)
        if duration_gap > 0:
            penalty += 200 + ceil(duration_gap) * 20

        required_crew = self._required_crew(maintenance_plan)
        if required_crew and required_crew not in str(window.get("crew", "")).lower():
            penalty += 4

        closure_type = str(window.get("closure_type", "")).lower()
        permits = {permit.lower() for permit in maintenance_plan.permits}
        if "closure coordination approval" in permits and "full closure" not in closure_type:
            penalty += 4
        if "full closure" in closure_type and "closure coordination approval" not in permits:
            penalty += 6
        return penalty

    def _precedent_penalty(
        self,
        window: dict[str, Any],
        scheduling_precedents: list[dict[str, Any]],
    ) -> int:
        if not scheduling_precedents:
            return 0

        penalty = 0
        closure_type = str(window.get("closure_type", "")).lower()
        crew = str(window.get("crew", "")).lower()
        start = datetime.fromisoformat(window["start"])
        is_overnight = start.hour >= 20 or start.hour <= 5

        for precedent in scheduling_precedents:
            if "successful" not in str(precedent.get("schedule_outcome", "")).lower():
                continue
            preferred_closure = str(precedent.get("preferred_closure_type", "")).lower()
            preferred_crew = str(precedent.get("preferred_crew_type", "")).lower()
            preferred_window = str(precedent.get("preferred_window_type", "")).lower()
            if preferred_closure and preferred_closure not in closure_type:
                penalty += 2
            if preferred_crew and preferred_crew not in crew:
                penalty += 2
            if preferred_window == "overnight" and not is_overnight:
                penalty += 2
        return penalty

    def _resource_constraints(
        self,
        window: dict[str, Any],
        maintenance_plan: MaintenancePlan,
    ) -> list[str]:
        constraints = []
        duration = self._window_duration_hours(window)
        if maintenance_plan.estimated_duration_hours <= duration:
            constraints.append(
                f"fits estimated work duration of {maintenance_plan.estimated_duration_hours:g} hours"
            )
        else:
            constraints.append(
                f"estimated duration of {maintenance_plan.estimated_duration_hours:g} hours exceeds {duration:g}-hour window"
            )

        if str(window.get("crew_available", "true")).lower() == "true":
            constraints.append("crew is available")
        else:
            constraints.append("crew availability is not confirmed")

        closure_type = window.get("closure_type")
        if closure_type:
            constraints.append(f"closure type: {closure_type}")
        return constraints

    def _resource_tradeoffs(
        self,
        window: dict[str, Any],
        maintenance_plan: MaintenancePlan,
    ) -> list[str]:
        tradeoffs = []
        required_crew = self._required_crew(maintenance_plan)
        if required_crew and required_crew not in str(window.get("crew", "")).lower():
            tradeoffs.append(
                f"Selected crew is not the ideal {required_crew} crew for this repair method."
            )

        duration_gap = maintenance_plan.estimated_duration_hours - self._window_duration_hours(window)
        if duration_gap > 0:
            tradeoffs.append(
                "Repair may need staging across multiple windows because estimated duration exceeds the selected window."
            )

        closure_type = str(window.get("closure_type", "")).lower()
        permits = {permit.lower() for permit in maintenance_plan.permits}
        if "closure coordination approval" in permits and "full closure" not in closure_type:
            tradeoffs.append(
                "Plan references closure coordination, but selected window uses a lower-impact closure."
            )
        return tradeoffs

    def _precedent_tradeoffs(
        self,
        window: dict[str, Any],
        scheduling_precedents: list[dict[str, Any]],
    ) -> list[str]:
        if not scheduling_precedents:
            return []
        lessons = [
            str(precedent.get("lessons_learned", "")).strip()
            for precedent in scheduling_precedents[:2]
            if precedent.get("lessons_learned")
        ]
        if not lessons:
            return []
        return [
            "Scheduling RAG precedent considered: " + " ".join(lessons)
        ]

    def _window_duration_hours(self, window: dict[str, Any]) -> float:
        start = datetime.fromisoformat(window["start"])
        end = datetime.fromisoformat(window["end"])
        return (end - start).total_seconds() / 3600

    def _required_crew(self, maintenance_plan: MaintenancePlan) -> str | None:
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

    def _context_risk(
        self,
        window: dict[str, Any],
        scheduling_context: SchedulingContext,
    ) -> int:
        start = window["start"]
        weather = next(
            (item for item in scheduling_context.weather if item.window_start == start),
            None,
        )
        traffic = next(
            (item for item in scheduling_context.traffic if item.window_start == start),
            None,
        )
        event = next(
            (item for item in scheduling_context.events if item.window_start == start),
            None,
        )
        return (
            (weather.risk_score if weather else 0)
            + (traffic.risk_score if traffic else 0)
            + (event.risk_score if event else 0)
            + scheduling_context.access_risk_score
        )

    def _context_summary(
        self,
        window: dict[str, Any],
        scheduling_context: SchedulingContext,
    ) -> list[str]:
        start = window["start"]
        summary = []

        weather = next(
            (item for item in scheduling_context.weather if item.window_start == start),
            None,
        )
        traffic = next(
            (item for item in scheduling_context.traffic if item.window_start == start),
            None,
        )
        event = next(
            (item for item in scheduling_context.events if item.window_start == start),
            None,
        )

        if weather:
            summary.append(f"Weather: {weather.condition}. {weather.rationale}")
        if traffic:
            summary.append(f"Traffic: {traffic.impact}. {traffic.rationale}")
        if event:
            summary.append(f"City context: {event.title}. {event.rationale}")
        if scheduling_context.access_risk_score:
            summary.append(
                f"Access risk score: {scheduling_context.access_risk_score}"
            )
        return summary

    def _precedent_summary(
        self,
        scheduling_precedents: list[dict[str, Any]],
    ) -> list[str]:
        return [
            (
                f"Scheduling precedent: {precedent['document_id']} "
                f"preferred {precedent.get('preferred_window_type', 'unknown')} "
                f"{precedent.get('preferred_closure_type', 'closure')} with "
                f"{precedent.get('preferred_crew_type', 'unspecified')} crew."
            )
            for precedent in scheduling_precedents[:2]
        ]
