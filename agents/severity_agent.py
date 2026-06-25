from __future__ import annotations

from typing import Literal

from agents.helpers.observation_selection import SEVERITY_RANK, select_primary_observation
from agents.helpers.severity_calibrator import calibrate_severity_from_observations
from agents.helpers.severity_rationale_generator import LLMSeverityRationaleGenerator
from models import Citation, InspectionCase, Observation, SeverityAssessment
from rag.interfaces import KnowledgeRetriever


SeverityMode = Literal["deterministic", "llm"]
LLMFailureMode = Literal["fallback", "fail"]


class SeverityAgent:
    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        severity_mode: SeverityMode = "deterministic",
        rationale_generator: LLMSeverityRationaleGenerator | None = None,
        llm_max_retries: int = 4,
        llm_failure_mode: LLMFailureMode = "fallback",
    ):
        self.retriever = retriever
        self.severity_mode = severity_mode
        self.rationale_generator = rationale_generator
        self.llm_max_retries = llm_max_retries
        self.llm_failure_mode = llm_failure_mode

        if severity_mode not in {"deterministic", "llm"}:
            raise ValueError(f"Unsupported severity mode: {severity_mode}")

    def assess(
        self,
        inspection_case: InspectionCase,
        observations: list[Observation],
    ) -> SeverityAssessment:
        primary = select_primary_observation(observations)
        query = self._build_query(inspection_case, primary)
        citations = []
        if primary.defect_type != "unknown":
            citations = self.retriever.search(
                query,
                source_type="standard",
                asset_type=inspection_case.asset.asset_type,
                defect_type=primary.defect_type,
                limit=2,
            )

        text = " ".join(
            [evidence.content.lower() for evidence in inspection_case.evidence]
            + [observation.description.lower() for observation in observations]
        )
        severity = "none"
        urgency = "monitor"
        repair_required = False
        confidence = 0.62

        labeled_severity = self._highest_labeled_severity(observations)
        calibrated = calibrate_severity_from_observations(inspection_case, observations)
        if labeled_severity == "none":
            pass
        elif labeled_severity in {"critical", "high"}:
            severity = "high"
            urgency = "priority"
            repair_required = True
            confidence = 0.82
        elif labeled_severity in {"moderate", "medium"}:
            severity = "moderate"
            urgency = "scheduled"
            repair_required = True
            confidence = 0.8
        elif labeled_severity == "low":
            severity = "low"
            confidence = 0.72
        elif calibrated is not None:
            severity, urgency, repair_required, confidence = calibrated
        elif any(term in text for term in ("exposed", "loose", "rapid", "widening")):
            severity = "high"
            urgency = "priority"
            repair_required = True
            confidence = 0.78
        elif any(
            term in text
            for term in (
                "water",
                "intrusion",
                "leak",
                "spalling",
                "crack",
                "corrosion",
                "rust",
                "staining",
            )
        ):
            severity = "moderate"
            urgency = "scheduled"
            repair_required = True
            confidence = 0.72

        if inspection_case.asset.criticality in {"high", "critical"} and severity == "moderate":
            urgency = "priority"

        deterministic_rationale = self._rationale(primary, citations, repair_required)
        assessment = SeverityAssessment(
            severity=severity,  # type: ignore[arg-type]
            repair_required=repair_required,
            urgency=urgency,  # type: ignore[arg-type]
            rationale=deterministic_rationale,
            confidence=confidence,
            citations=citations,
        )

        if self.severity_mode == "deterministic":
            return assessment

        generator = self.rationale_generator or LLMSeverityRationaleGenerator(
            max_retries=self.llm_max_retries,
            failure_mode=self.llm_failure_mode,
        )
        return SeverityAssessment(
            severity=assessment.severity,
            repair_required=assessment.repair_required,
            urgency=assessment.urgency,
            rationale=generator.generate(
                inspection_case,
                observations,
                assessment,
                deterministic_rationale,
            ),
            confidence=assessment.confidence,
            citations=assessment.citations,
        )

    def _build_query(
        self,
        inspection_case: InspectionCase,
        observation: Observation,
    ) -> str:
        return (
            f"{inspection_case.asset.asset_type} {observation.defect_type} "
            f"{inspection_case.asset.criticality} {observation.description}"
        )

    def _highest_labeled_severity(
        self,
        observations: list[Observation],
    ) -> str | None:
        labels = [
            str(observation.measurement.get("severity_label", "")).lower()
            for observation in observations
            if observation.measurement.get("severity_label")
            and self._is_trusted_labeled_severity(observation)
        ]
        if not labels:
            return None
        return max(labels, key=lambda label: SEVERITY_RANK.get(label, 0))

    def _is_trusted_labeled_severity(self, observation: Observation) -> bool:
        source = str(observation.measurement.get("severity_label_source", ""))
        label = str(observation.measurement.get("severity_label", "")).lower()
        if label == "none":
            return True
        return source not in {"RoboflowImageAnalyzer"}

    def _rationale(
        self,
        observation: Observation,
        citations: list[Citation],
        repair_required: bool,
    ) -> str:
        decision = "Repair is recommended" if repair_required else "Monitoring is recommended"
        if not citations:
            return f"{decision} based on observed {observation.defect_type} and limited policy matches."

        titles = ", ".join(citation.title for citation in citations)
        return f"{decision} based on observed {observation.defect_type} and retrieved guidance: {titles}."
