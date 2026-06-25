from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal

from models import (
    InspectionCase,
    MaintenancePlan,
    RepairSchedule,
    RepairWindow,
    SchedulingContext,
    SeverityAssessment,
)


LLM_SCHEDULING_FAILURE_NOTE = (
    "LLM scheduling failed validation or execution; deterministic fallback window used."
)

SCHEDULE_SELECTION_SCHEMA = {
    "title": "LLMScheduleSelection",
    "description": "Structured repair-window selection from candidate windows.",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected_window_start": {"type": "string"},
        "selected_window_end": {"type": "string"},
        "rationale": {"type": "string"},
        "staging_required": {"type": "boolean"},
        "disruption_mitigation_steps": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rejected_window_reasons": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "selected_window_start",
        "selected_window_end",
        "rationale",
        "staging_required",
        "disruption_mitigation_steps",
        "risks",
        "rejected_window_reasons",
    ],
}


LLMFailureMode = Literal["fallback", "fail"]


class LLMSchedulingError(RuntimeError):
    pass


class LLMScheduleGenerator:
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
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
        scheduling_context: SchedulingContext,
        candidate_windows: list[dict[str, Any]],
        scheduling_precedents: list[dict[str, Any]],
        deterministic_schedule: RepairSchedule,
    ) -> RepairSchedule:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.runnable.invoke(
                    self._messages(
                        inspection_case,
                        severity,
                        maintenance_plan,
                        scheduling_context,
                        candidate_windows,
                        scheduling_precedents,
                        deterministic_schedule,
                        attempt=attempt,
                        last_error=last_error,
                    )
                )
                payload = self._coerce_payload(response)
                return self._to_schedule(
                    payload,
                    maintenance_plan,
                    candidate_windows,
                    deterministic_schedule,
                )
            except Exception as exc:
                last_error = exc

        if self.failure_mode == "fail":
            raise LLMSchedulingError(
                f"LLM scheduling failed after {self.max_retries} attempts: {last_error}"
            ) from last_error

        return self._fallback_schedule(deterministic_schedule, last_error)

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
                "LLM scheduling requires the 'langchain-openai' package."
            ) from exc

        selected_model = model or os.getenv("OPENAI_SCHEDULING_MODEL", "gpt-4.1-mini")
        return ChatOpenAI(model=selected_model, temperature=0).with_structured_output(
            SCHEDULE_SELECTION_SCHEMA,
            method="json_schema",
            strict=True,
        )

    def _messages(
        self,
        inspection_case: InspectionCase,
        severity: SeverityAssessment,
        maintenance_plan: MaintenancePlan,
        scheduling_context: SchedulingContext,
        candidate_windows: list[dict[str, Any]],
        scheduling_precedents: list[dict[str, Any]],
        deterministic_schedule: RepairSchedule,
        *,
        attempt: int,
        last_error: Exception | None,
    ) -> list[dict[str, str]]:
        correction = ""
        if last_error is not None:
            correction = (
                "\nPrevious attempt failed validation or execution with this error: "
                f"{last_error}. Choose a valid candidate window and correct the output."
            )

        return [
            {
                "role": "system",
                "content": (
                    "You are an infrastructure repair scheduling assistant. "
                    "Select exactly one candidate repair window. Prefer feasible, "
                    "low-disruption windows, but account for urgency, weather, traffic, "
                    "events, crew fit, closure requirements, historical scheduling "
                    "precedents, and whether staging across windows is needed. Return "
                    "only structured data matching the schema."
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
                    f"repair_required={severity.repair_required}\n"
                    f"Maintenance plan: action={maintenance_plan.recommended_action}; "
                    f"duration={maintenance_plan.estimated_duration_hours:g}h; "
                    f"materials={', '.join(maintenance_plan.materials) or 'none'}; "
                    f"equipment={', '.join(maintenance_plan.equipment) or 'none'}; "
                    f"permits={', '.join(maintenance_plan.permits) or 'none'}\n\n"
                    f"Deterministic fallback window: "
                    f"{deterministic_schedule.recommended_window.start.isoformat()} "
                    f"to {deterministic_schedule.recommended_window.end.isoformat()} "
                    f"(score={deterministic_schedule.total_score})\n\n"
                    f"Candidate windows:\n{self._format_windows(candidate_windows)}\n\n"
                    f"Scheduling context:\n{self._format_context(scheduling_context)}\n\n"
                    f"Historical scheduling precedents:\n"
                    f"{self._format_precedents(scheduling_precedents)}"
                ),
            },
        ]

    def _coerce_payload(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            return response.model_dump()
        raise ValueError("LLM scheduler returned unsupported structured output.")

    def _to_schedule(
        self,
        payload: dict[str, Any],
        maintenance_plan: MaintenancePlan,
        candidate_windows: list[dict[str, Any]],
        deterministic_schedule: RepairSchedule,
    ) -> RepairSchedule:
        selected = self._selected_window(payload, candidate_windows, maintenance_plan)
        tradeoffs = [
            *deterministic_schedule.tradeoffs,
            f"LLM scheduling rationale: {self._required_string(payload, 'rationale')}",
            *[
                f"Mitigation: {item}"
                for item in self._string_list(payload, "disruption_mitigation_steps")
            ],
            *[
                f"Rejected window: {item}"
                for item in self._string_list(payload, "rejected_window_reasons")
            ],
        ]
        risks = [f"LLM scheduling risk: {item}" for item in self._string_list(payload, "risks")]
        if bool(payload.get("staging_required")):
            tradeoffs.append("LLM recommends staging repair activity across windows.")

        return RepairSchedule(
            recommended_window=RepairWindow(
                start=datetime.fromisoformat(selected["start"]),
                end=datetime.fromisoformat(selected["end"]),
            ),
            disruption_score=int(selected["disruption_score"]),
            context_risk_score=int(selected.get("context_risk_score", 0)),
            total_score=int(selected.get("score", deterministic_schedule.total_score)),
            constraints_satisfied=deterministic_schedule.constraints_satisfied,
            tradeoffs=[*tradeoffs, *risks],
            context_summary=deterministic_schedule.context_summary,
        )

    def _selected_window(
        self,
        payload: dict[str, Any],
        candidate_windows: list[dict[str, Any]],
        maintenance_plan: MaintenancePlan,
    ) -> dict[str, Any]:
        start = self._required_string(payload, "selected_window_start")
        end = self._required_string(payload, "selected_window_end")
        for window in candidate_windows:
            if window["start"] == start and window["end"] == end:
                self._validate_window(window, maintenance_plan, bool(payload["staging_required"]))
                return window
        raise ValueError("LLM selected a window that is not in the candidate list.")

    def _validate_window(
        self,
        window: dict[str, Any],
        maintenance_plan: MaintenancePlan,
        staging_required: bool,
    ) -> None:
        if str(window.get("crew_available", "true")).lower() == "false":
            raise ValueError("LLM selected a window with unavailable crew.")
        duration = (
            datetime.fromisoformat(window["end"]) - datetime.fromisoformat(window["start"])
        ).total_seconds() / 3600
        if maintenance_plan.estimated_duration_hours > duration and not staging_required:
            raise ValueError(
                "LLM selected a window shorter than the estimated repair duration "
                "without marking staging_required."
            )

    def _fallback_schedule(
        self,
        deterministic_schedule: RepairSchedule,
        last_error: Exception | None,
    ) -> RepairSchedule:
        detail = f" Last error: {last_error}" if last_error else ""
        return RepairSchedule(
            recommended_window=deterministic_schedule.recommended_window,
            disruption_score=deterministic_schedule.disruption_score,
            context_risk_score=deterministic_schedule.context_risk_score,
            total_score=deterministic_schedule.total_score,
            constraints_satisfied=deterministic_schedule.constraints_satisfied,
            tradeoffs=[
                *deterministic_schedule.tradeoffs,
                f"{LLM_SCHEDULING_FAILURE_NOTE}{detail}",
            ],
            context_summary=deterministic_schedule.context_summary,
        )

    def _required_string(self, payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"LLM schedule field '{field}' must be a non-empty string.")
        return value.strip()

    def _string_list(self, payload: dict[str, Any], field: str) -> list[str]:
        value = payload.get(field, [])
        if not isinstance(value, list):
            raise ValueError(f"LLM schedule field '{field}' must be a list.")
        if not all(isinstance(item, str) for item in value):
            raise ValueError(f"LLM schedule field '{field}' must contain only strings.")
        return [item.strip() for item in value if item.strip()]

    def _format_windows(self, candidate_windows: list[dict[str, Any]]) -> str:
        return "\n".join(
            (
                f"- {window['start']} to {window['end']}: "
                f"crew={window.get('crew', 'unknown')}, "
                f"available={window.get('crew_available', 'true')}, "
                f"closure={window.get('closure_type', 'unknown')}, "
                f"disruption={window.get('disruption_score', 'unknown')}, "
                f"score={window.get('score', 'unscored')}, "
                f"notes={window.get('notes', '')}"
            )
            for window in candidate_windows
        )

    def _format_context(self, context: SchedulingContext) -> str:
        rows = []
        for item in context.weather:
            rows.append(
                f"- Weather {item.window_start}: {item.condition}, "
                f"risk={item.risk_score}, {item.rationale}"
            )
        for item in context.traffic:
            rows.append(
                f"- Traffic {item.window_start}: {item.impact}, "
                f"risk={item.risk_score}, {item.rationale}"
            )
        for item in context.events:
            rows.append(
                f"- Event {item.window_start}: {item.title}, "
                f"risk={item.risk_score}, {item.rationale}"
            )
        if context.access_risk_score:
            rows.append(f"- Access risk score: {context.access_risk_score}")
        return "\n".join(rows) or "- No context risks were provided."

    def _format_precedents(self, precedents: list[dict[str, Any]]) -> str:
        if not precedents:
            return "- No scheduling precedents retrieved."
        return "\n".join(
            (
                f"- {precedent['document_id']}: "
                f"window={precedent.get('preferred_window_type', 'unknown')}, "
                f"crew={precedent.get('preferred_crew_type', 'unknown')}, "
                f"closure={precedent.get('preferred_closure_type', 'unknown')}, "
                f"outcome={precedent.get('schedule_outcome', 'unknown')}, "
                f"lesson={precedent.get('lessons_learned', '')}"
            )
            for precedent in precedents
        )
