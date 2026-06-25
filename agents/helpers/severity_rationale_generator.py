from __future__ import annotations

import os
from typing import Any, Literal

from models import Citation, InspectionCase, Observation, SeverityAssessment


LLM_SEVERITY_FAILURE_NOTE = (
    "LLM severity rationale failed after retries; deterministic rationale used."
)


SEVERITY_RATIONALE_SCHEMA = {
    "title": "LLMSeverityRationale",
    "description": "Explanation for a deterministic infrastructure severity assessment.",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "rationale": {"type": "string"},
        "missing_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["rationale", "missing_evidence"],
}


LLMFailureMode = Literal["fallback", "fail"]


class LLMSeverityRationaleError(RuntimeError):
    pass


class LLMSeverityRationaleGenerator:
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
        assessment: SeverityAssessment,
        deterministic_rationale: str,
    ) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.runnable.invoke(
                    self._messages(
                        inspection_case,
                        observations,
                        assessment,
                        deterministic_rationale,
                        attempt=attempt,
                        last_error=last_error,
                    )
                )
                payload = self._coerce_payload(response)
                return self._to_rationale(payload)
            except Exception as exc:
                last_error = exc

        if self.failure_mode == "fail":
            raise LLMSeverityRationaleError(
                f"LLM severity rationale failed after {self.max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        detail = f" Last error: {last_error}" if last_error else ""
        return f"{deterministic_rationale} {LLM_SEVERITY_FAILURE_NOTE}{detail}"

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
                "LLM severity rationale requires the 'langchain-openai' package."
            ) from exc

        selected_model = model or os.getenv("OPENAI_SEVERITY_MODEL", "gpt-4.1-mini")
        return ChatOpenAI(model=selected_model, temperature=0).with_structured_output(
            SEVERITY_RATIONALE_SCHEMA,
            method="json_schema",
            strict=True,
        )

    def _messages(
        self,
        inspection_case: InspectionCase,
        observations: list[Observation],
        assessment: SeverityAssessment,
        deterministic_rationale: str,
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
                    "You explain infrastructure severity assessments. The severity, "
                    "urgency, repair_required flag, confidence, and citations are "
                    "already decided by deterministic rules. Do not change them. "
                    "Write a concise, cited rationale and identify missing evidence."
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
                    f"Deterministic severity: {assessment.severity}, "
                    f"urgency={assessment.urgency}, "
                    f"repair_required={assessment.repair_required}, "
                    f"confidence={assessment.confidence:.0%}\n"
                    f"Deterministic rationale: {deterministic_rationale}\n\n"
                    f"Observations:\n{self._format_observations(observations)}\n\n"
                    f"Citations:\n{self._format_citations(assessment.citations)}"
                ),
            },
        ]

    def _coerce_payload(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            return response.model_dump()
        raise ValueError("LLM severity rationale returned unsupported output.")

    def _to_rationale(self, payload: dict[str, Any]) -> str:
        rationale = payload.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("LLM severity rationale must include a non-empty rationale.")

        missing_evidence = payload.get("missing_evidence", [])
        if not isinstance(missing_evidence, list) or not all(
            isinstance(item, str) for item in missing_evidence
        ):
            raise ValueError("LLM severity missing_evidence must be a string list.")

        missing = [item.strip() for item in missing_evidence if item.strip()]
        if not missing:
            return rationale.strip()
        return f"{rationale.strip()} Missing evidence: {', '.join(missing)}."

    def _format_observations(self, observations: list[Observation]) -> str:
        return "\n".join(
            (
                f"- {observation.defect_type}: {observation.description} "
                f"at {observation.location_on_asset} "
                f"(confidence {observation.confidence:.0%})"
            )
            for observation in observations
        )

    def _format_citations(self, citations: list[Citation]) -> str:
        if not citations:
            return "- No policy citations were retrieved."
        return "\n".join(
            (
                f"- {citation.title} [{citation.document_id}]: "
                f"{citation.excerpt}"
            )
            for citation in citations
        )
