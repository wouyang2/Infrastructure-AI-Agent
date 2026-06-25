from __future__ import annotations

from typing import Literal

from agents.helpers.report_generator import LLMReportGenerator
from models import InspectionReport


ReportMode = Literal["deterministic", "llm"]
LLMFailureMode = Literal["fallback", "fail"]


class ReportAgent:
    def __init__(
        self,
        *,
        report_mode: ReportMode = "deterministic",
        report_generator: LLMReportGenerator | None = None,
        llm_max_retries: int = 4,
        llm_failure_mode: LLMFailureMode = "fallback",
    ):
        self.report_mode = report_mode
        self.report_generator = report_generator
        self.llm_max_retries = llm_max_retries
        self.llm_failure_mode = llm_failure_mode

        if report_mode not in {"deterministic", "llm"}:
            raise ValueError(f"Unsupported report mode: {report_mode}")

    def render(self, report: InspectionReport) -> str:
        deterministic_report = self._render_deterministic(report)
        if self.report_mode == "deterministic":
            return deterministic_report

        generator = self.report_generator or LLMReportGenerator(
            max_retries=self.llm_max_retries,
            failure_mode=self.llm_failure_mode,
        )
        return generator.generate(deterministic_report)

    def _render_deterministic(self, report: InspectionReport) -> str:
        lines = [
            "# Infrastructure Inspection Report",
            "",
            f"Case: {report.case.case_id}",
            f"Asset: {report.case.asset.name} ({report.case.asset.asset_type})",
            f"Location: {report.case.asset.location}",
            f"Criticality: {report.case.asset.criticality}",
            "",
            "## Executive Summary",
            f"- Severity: {report.severity.severity}",
            f"- Urgency: {report.severity.urgency}",
            f"- Repair required: {'yes' if report.severity.repair_required else 'no'}",
            f"- Recommended action: {report.maintenance_plan.recommended_action}",
            f"- Estimated duration: {report.maintenance_plan.estimated_duration_hours:g} hours",
            f"- Schedule: {self._schedule_summary(report)}",
            "",
            "## Observations",
        ]

        for observation in report.observations:
            media = ""
            if observation.media_reference:
                media = f" source={observation.media_reference.file_path}"
                if observation.media_reference.frame_timestamp_seconds is not None:
                    media += (
                        " timestamp="
                        f"{observation.media_reference.frame_timestamp_seconds:g}s"
                    )
            lines.append(
                f"- {observation.observation_id}: "
                f"{observation.defect_type} [{observation.source_modality}]: "
                f"{observation.description}{media} "
                f"(confidence {observation.confidence:.0%})"
            )

        lines.extend(["", "## Evidence Traceability"])
        for observation in report.observations:
            lines.append(self._observation_trace_line(observation))

        if report.annotated_media_paths:
            lines.extend(["", "## Visual Evidence"])
            for path in report.annotated_media_paths:
                lines.append(f"- Annotated image: {path}")

        lines.extend(
            [
                "",
                "## Severity",
                f"Severity: {report.severity.severity}",
                f"Urgency: {report.severity.urgency}",
                f"Repair required: {'yes' if report.severity.repair_required else 'no'}",
                f"Confidence: {report.severity.confidence:.0%}",
                f"Rationale: {report.severity.rationale}",
                "",
                "## Retrieved Guidance",
            ]
        )

        if report.severity.citations:
            for citation in report.severity.citations:
                lines.append(f"- {citation.title} [{citation.document_id}]")
        else:
            lines.append("- No standards matched strongly enough.")

        lines.extend(
            [
                "",
                "## Maintenance Plan",
                f"Recommended action: {report.maintenance_plan.recommended_action}",
                f"Estimated duration: {report.maintenance_plan.estimated_duration_hours} hours",
                "",
                "Historical precedents used:",
            ]
        )

        if report.maintenance_plan.historical_precedents:
            for precedent in report.maintenance_plan.historical_precedents:
                lines.append(
                    f"- {precedent.title} [{precedent.document_id}]: "
                    f"{precedent.repair_method}, {precedent.actual_duration_hours:g}h, "
                    f"{precedent.outcome}, disruption: {precedent.disruption}"
                )
        else:
            lines.append("- No similar historical repairs found.")

        lines.append("")
        lines.append("Tasks:")
        for task in report.maintenance_plan.tasks:
            lines.append(f"- {task.name}: {task.description} ({task.estimated_hours:g}h)")

        lines.extend(
            [
                "",
                f"Materials: {', '.join(report.maintenance_plan.materials) or 'none'}",
                f"Equipment: {', '.join(report.maintenance_plan.equipment) or 'none'}",
                f"Permits: {', '.join(report.maintenance_plan.permits) or 'none'}",
                "",
                "Risks:",
            ]
        )

        for risk in report.maintenance_plan.risks:
            lines.append(f"- {risk}")

        lines.extend(
            [
                "",
                "## Schedule",
            ]
        )

        if report.schedule is None:
            lines.append("No repair window required. Continue with the monitoring plan.")
            return "\n".join(lines)

        lines.extend(
            [
                (
                    "Recommended window: "
                    f"{report.schedule.recommended_window.start.isoformat()} to "
                    f"{report.schedule.recommended_window.end.isoformat()}"
                ),
                f"Disruption score: {report.schedule.disruption_score}",
                f"Context risk score: {report.schedule.context_risk_score}",
                f"Total schedule score: {report.schedule.total_score}",
                "Scheduling context:",
            ]
        )

        for item in report.schedule.context_summary:
            lines.append(f"- {item}")

        lines.extend(
            [
                "Tradeoffs:",
            ]
        )

        for tradeoff in report.schedule.tradeoffs:
            lines.append(f"- {tradeoff}")

        return "\n".join(lines)

    def _schedule_summary(self, report: InspectionReport) -> str:
        if report.schedule is None:
            return "no repair window required"
        return (
            f"{report.schedule.recommended_window.start.isoformat()} to "
            f"{report.schedule.recommended_window.end.isoformat()}"
        )

    def _observation_trace_line(self, observation) -> str:
        parts = [
            f"- {observation.observation_id}",
            f"source={observation.source_id}",
            f"modality={observation.source_modality}",
            f"defect={observation.defect_type}",
            f"confidence={observation.confidence:.0%}",
        ]
        severity_label = observation.measurement.get("severity_label")
        if severity_label:
            parts.append(f"severity_label={severity_label}")
        relative_area = observation.measurement.get("bbox_relative_area")
        if relative_area is not None:
            parts.append(f"bbox_relative_area={relative_area}")
        if observation.media_reference and observation.media_reference.bounding_box:
            parts.append(f"bbox={observation.media_reference.bounding_box}")
        return "; ".join(parts)
