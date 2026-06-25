from __future__ import annotations

import os
from typing import Any, Literal

from models import (
    HistoricalPrecedent,
    InspectionCase,
    MaintenancePlan,
    MaintenanceTask,
    Observation,
    SeverityAssessment,
)


LLM_FAILURE_NOTE = "LLM planning failed after retries; deterministic fallback plan used."


MAINTENANCE_PLAN_SCHEMA = {
    "title": "LLMMaintenancePlan",
    "description": "Structured maintenance plan generated from inspection evidence.",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "recommended_action": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "estimated_hours": {"type": "number"},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "name",
                    "description",
                    "estimated_hours",
                    "dependencies",
                ],
            },
        },
        "materials": {"type": "array", "items": {"type": "string"}},
        "equipment": {"type": "array", "items": {"type": "string"}},
        "permits": {"type": "array", "items": {"type": "string"}},
        "estimated_duration_hours": {"type": "number"},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "recommended_action",
        "tasks",
        "materials",
        "equipment",
        "permits",
        "estimated_duration_hours",
        "risks",
    ],
}


LLMFailureMode = Literal["fallback", "fail"]


class LLMPlanningError(RuntimeError):
    pass


class LLMMaintenancePlanGenerator:
    def __init__(
        self,
        runnable: Any | None = None,
        *,
        model: str | None = None,
        max_retries: int = 4,
        failure_mode: LLMFailureMode = "fallback",
    ):
        if max_retries <= 0:
            raise ValueError("LLM max retries must be greater than 0.")
        if failure_mode not in {"fallback", "fail"}:
            raise ValueError(f"Unsupported LLM failure mode: {failure_mode}")

        self.runnable = runnable or self._default_runnable(model)
        self.max_retries = max_retries
        self.failure_mode = failure_mode

    def generate(
        self,
        inspection_case: InspectionCase,
        observations: list[Observation],
        severity: SeverityAssessment,
        precedents: list[HistoricalPrecedent],
        deterministic_plan: MaintenancePlan,
    ) -> MaintenancePlan:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.runnable.invoke(
                    self._messages(
                        inspection_case,
                        observations,
                        severity,
                        precedents,
                        deterministic_plan,
                        attempt=attempt,
                        last_error=last_error,
                    )
                )
                payload = self._coerce_payload(response)
                return self._to_plan(payload, precedents)
            except Exception as exc:
                last_error = exc

        if self.failure_mode == "fail":
            raise LLMPlanningError(
                f"LLM maintenance planning failed after {self.max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        return self._fallback_plan(deterministic_plan, last_error)

    def _default_runnable(self, model: str | None):
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "LLM maintenance planning requires the 'langchain-openai' package."
            ) from exc

        selected_model = model or os.getenv("OPENAI_PLANNING_MODEL", "gpt-4.1-mini")
        return ChatOpenAI(model=selected_model, temperature=0).with_structured_output(
            MAINTENANCE_PLAN_SCHEMA,
            method="json_schema",
            strict=True,
        )

    def _messages(
        self,
        inspection_case: InspectionCase,
        observations: list[Observation],
        severity: SeverityAssessment,
        precedents: list[HistoricalPrecedent],
        deterministic_plan: MaintenancePlan,
        *,
        attempt: int,
        last_error: Exception | None,
    ) -> list[dict[str, str]]:
        correction = ""
        if last_error is not None:
            correction = (
                "\nPrevious attempt failed validation or execution with this error: "
                f"{last_error}. Correct the structured output."
            )

        return [
            {
                "role": "system",
                "content": (
                    "You are an infrastructure maintenance planning assistant. "
                    "Return only structured data matching the provided schema. "
                    "Do not decide severity or schedule dates. Adapt retrieved "
                    "repair precedents to the current case."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Attempt: {attempt}{correction}\n\n"
                    f"Asset: {inspection_case.asset.name} "
                    f"({inspection_case.asset.asset_type}), "
                    f"criticality={inspection_case.asset.criticality}, "
                    f"location={inspection_case.asset.location}\n"
                    f"Severity: {severity.severity}, urgency={severity.urgency}, "
                    f"repair_required={severity.repair_required}, "
                    f"rationale={severity.rationale}\n\n"
                    f"Observations:\n{self._format_observations(observations)}\n\n"
                    f"Historical repair precedents:\n"
                    f"{self._format_precedents(precedents)}\n\n"
                    f"Deterministic baseline plan:\n"
                    f"{self._format_plan(deterministic_plan)}"
                ),
            },
        ]

    def _coerce_payload(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            return response.model_dump()
        raise ValueError("LLM planner returned unsupported structured output.")

    def _to_plan(
        self,
        payload: dict[str, Any],
        precedents: list[HistoricalPrecedent],
    ) -> MaintenancePlan:
        recommended_action = self._required_string(payload, "recommended_action")
        tasks = self._tasks(payload.get("tasks"))
        estimated_duration_hours = self._positive_float(
            payload,
            "estimated_duration_hours",
        )

        return MaintenancePlan(
            recommended_action=recommended_action,
            historical_precedents=precedents,
            tasks=tasks,
            materials=self._string_list(payload, "materials"),
            equipment=self._string_list(payload, "equipment"),
            permits=self._string_list(payload, "permits"),
            estimated_duration_hours=estimated_duration_hours,
            risks=self._string_list(payload, "risks"),
        )

    def _fallback_plan(
        self,
        deterministic_plan: MaintenancePlan,
        last_error: Exception | None,
    ) -> MaintenancePlan:
        risks = list(deterministic_plan.risks)
        detail = f" Last error: {last_error}" if last_error else ""
        risks.append(f"{LLM_FAILURE_NOTE}{detail}")
        return MaintenancePlan(
            recommended_action=deterministic_plan.recommended_action,
            historical_precedents=deterministic_plan.historical_precedents,
            tasks=deterministic_plan.tasks,
            materials=deterministic_plan.materials,
            equipment=deterministic_plan.equipment,
            permits=deterministic_plan.permits,
            estimated_duration_hours=deterministic_plan.estimated_duration_hours,
            risks=risks,
        )

    def _tasks(self, raw_tasks: Any) -> list[MaintenanceTask]:
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ValueError("LLM plan must include at least one task.")

        tasks = []
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise ValueError("Each LLM plan task must be an object.")
            tasks.append(
                MaintenanceTask(
                    name=self._required_string(raw, "name"),
                    description=self._required_string(raw, "description"),
                    estimated_hours=self._positive_float(raw, "estimated_hours"),
                    dependencies=self._string_list(raw, "dependencies"),
                )
            )
        return tasks

    def _required_string(self, payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"LLM plan field '{field}' must be a non-empty string.")
        return value.strip()

    def _positive_float(self, payload: dict[str, Any], field: str) -> float:
        value = payload.get(field)
        if not isinstance(value, int | float) or float(value) <= 0:
            raise ValueError(f"LLM plan field '{field}' must be a positive number.")
        return float(value)

    def _string_list(self, payload: dict[str, Any], field: str) -> list[str]:
        value = payload.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"LLM plan field '{field}' must be a list.")
        if not all(isinstance(item, str) for item in value):
            raise ValueError(f"LLM plan field '{field}' must contain only strings.")
        return [item.strip() for item in value if item.strip()]

    def _format_observations(self, observations: list[Observation]) -> str:
        return "\n".join(
            (
                f"- {observation.defect_type}: {observation.description} "
                f"at {observation.location_on_asset} "
                f"(confidence {observation.confidence:.0%})"
            )
            for observation in observations
        )

    def _format_precedents(self, precedents: list[HistoricalPrecedent]) -> str:
        if not precedents:
            return "- No historical repair precedents were retrieved."
        return "\n".join(
            (
                f"- {precedent.title} [{precedent.document_id}]: "
                f"method={precedent.repair_method}, outcome={precedent.outcome}, "
                f"duration={precedent.actual_duration_hours:g}h, "
                f"disruption={precedent.disruption}"
            )
            for precedent in precedents
        )

    def _format_plan(self, plan: MaintenancePlan) -> str:
        tasks = "; ".join(
            f"{task.name} ({task.estimated_hours:g}h)" for task in plan.tasks
        )
        return (
            f"recommended_action={plan.recommended_action}; "
            f"duration={plan.estimated_duration_hours:g}h; "
            f"tasks={tasks}; "
            f"materials={', '.join(plan.materials) or 'none'}; "
            f"equipment={', '.join(plan.equipment) or 'none'}; "
            f"permits={', '.join(plan.permits) or 'none'}; "
            f"risks={', '.join(plan.risks) or 'none'}"
        )
