from __future__ import annotations

import os
from typing import Any, Literal


LLM_REPORT_FAILURE_NOTE = (
    "LLM report rendering failed after retries; deterministic report used."
)


REPORT_SCHEMA = {
    "title": "LLMInspectionReport",
    "description": "A polished plain-text infrastructure inspection report narrative.",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "markdown_report": {
            "type": "string",
            "description": (
                "Document-ready prose. Do not include Markdown syntax such as #, "
                "**, bullet markers, tables, or horizontal rules."
            ),
        },
    },
    "required": ["markdown_report"],
}


LLMFailureMode = Literal["fallback", "fail"]


class LLMReportError(RuntimeError):
    pass


class LLMReportGenerator:
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

    def generate(self, deterministic_report: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.runnable.invoke(
                    self._messages(
                        deterministic_report,
                        attempt=attempt,
                        last_error=last_error,
                    )
                )
                payload = self._coerce_payload(response)
                return self._to_report(payload)
            except Exception as exc:
                last_error = exc

        if self.failure_mode == "fail":
            raise LLMReportError(
                f"LLM report rendering failed after {self.max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        detail = f" Last error: {last_error}" if last_error else ""
        return f"{deterministic_report}\n\n> {LLM_REPORT_FAILURE_NOTE}{detail}"

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
                "LLM report rendering requires the 'langchain-openai' package."
            ) from exc

        selected_model = model or os.getenv("OPENAI_REPORT_MODEL", "gpt-4.1-mini")
        return ChatOpenAI(model=selected_model, temperature=0).with_structured_output(
            REPORT_SCHEMA,
            method="json_schema",
            strict=True,
        )

    def _messages(
        self,
        deterministic_report: str,
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
                    "You polish infrastructure inspection reports. Preserve every "
                    "factual value, citation ID, severity, schedule window, score, "
                    "task, material, permit, and risk from the deterministic source. "
                    "Do not invent facts, citations, costs, or dates. Return plain "
                    "document-ready prose only. Do not use Markdown headings, bold "
                    "markers, bullets, tables, or horizontal rules."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Attempt: {attempt}{correction}\n\n"
                    "Polish this deterministic report into formal report prose for "
                    "a maintenance supervisor. Keep it concise, traceable, and "
                    "suitable for placement inside a formatted PDF-style report.\n\n"
                    f"{deterministic_report}"
                ),
            },
        ]

    def _coerce_payload(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            return response.model_dump()
        raise ValueError("LLM report renderer returned unsupported output.")

    def _to_report(self, payload: dict[str, Any]) -> str:
        report = payload.get("markdown_report")
        if not isinstance(report, str) or not report.strip():
            raise ValueError("LLM report renderer must return non-empty Markdown.")
        return report.strip()
