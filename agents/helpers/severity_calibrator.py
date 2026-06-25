from __future__ import annotations

from collections import Counter

from models import InspectionCase, Observation


SEVERITY_BY_DEFECT = {
    "unknown": "none",
    "corrosion": "moderate",
    "leak": "moderate",
    "water_leak": "moderate",
    "crack": "moderate",
    "spalling": "moderate",
    "exposed_rebar": "high",
}

REPAIR_DEFECTS = {
    "corrosion",
    "leak",
    "water_leak",
    "crack",
    "spalling",
    "exposed_rebar",
}


def calibrate_severity_from_observations(
    inspection_case: InspectionCase,
    observations: list[Observation],
) -> tuple[str, str, bool, float] | None:
    defect_observations = [
        observation
        for observation in observations
        if observation.defect_type != "unknown" and observation.confidence >= 0.2
    ]
    if not defect_observations:
        return None

    severity = max(
        (
            _observation_severity(observation, defect_observations)
            for observation in defect_observations
        ),
        key=_severity_rank,
    )
    if (
        severity == "moderate"
        and inspection_case.asset.criticality in {"critical"}
        and _has_large_defect(defect_observations)
    ):
        severity = "high"

    repair_required = any(
        observation.defect_type in REPAIR_DEFECTS
        for observation in defect_observations
    )
    urgency = _urgency(severity, inspection_case)
    confidence = _aggregate_confidence(defect_observations, severity)
    return severity, urgency, repair_required, confidence


def _observation_severity(
    observation: Observation,
    all_observations: list[Observation],
) -> str:
    defect_type = observation.defect_type
    relative_area = _relative_area(observation)
    confidence = observation.confidence

    if defect_type == "exposed_rebar":
        if _looks_like_mixed_surface_noise(observation, all_observations):
            return "moderate"
        if confidence >= 0.2 or relative_area >= 0.08:
            return "high"
        return "moderate"
    if defect_type == "spalling":
        if relative_area >= 0.08 or confidence >= 0.45:
            return "high"
        return "moderate"
    if defect_type == "crack":
        if relative_area >= 0.3 and confidence >= 0.9:
            return "high"
        return "moderate"
    if defect_type in {"corrosion", "leak", "water_leak"}:
        if relative_area >= 0.4 and confidence >= 0.9:
            return "high"
        return "moderate"
    return SEVERITY_BY_DEFECT.get(defect_type, "low")


def _looks_like_mixed_surface_noise(
    observation: Observation,
    all_observations: list[Observation],
) -> bool:
    if observation.defect_type != "exposed_rebar" or observation.confidence >= 0.5:
        return False

    defect_counts = Counter(item.defect_type for item in all_observations)
    return (
        defect_counts["exposed_rebar"] == 1
        and defect_counts["corrosion"] >= 1
        and defect_counts["spalling"] >= 1
    )


def _has_large_defect(observations: list[Observation]) -> bool:
    return any(_relative_area(observation) >= 0.2 for observation in observations)


def _relative_area(observation: Observation) -> float:
    value = observation.measurement.get("bbox_relative_area", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _urgency(severity: str, inspection_case: InspectionCase) -> str:
    if severity == "critical":
        return "emergency"
    if severity == "high":
        return "priority"
    if (
        severity == "moderate"
        and inspection_case.asset.criticality in {"high", "critical"}
    ):
        return "priority"
    if severity == "moderate":
        return "scheduled"
    return "monitor"


def _aggregate_confidence(observations: list[Observation], severity: str) -> float:
    confidence_by_defect = Counter(observation.defect_type for observation in observations)
    average_confidence = sum(observation.confidence for observation in observations) / len(
        observations
    )
    repeated_defect_bonus = 0.04 if max(confidence_by_defect.values(), default=0) > 1 else 0
    severity_bonus = 0.04 if severity in {"high", "critical"} else 0
    return round(min(0.92, average_confidence + repeated_defect_bonus + severity_bonus), 2)


def _severity_rank(severity: str) -> int:
    return {
        "none": 0,
        "low": 1,
        "moderate": 2,
        "high": 3,
        "critical": 4,
    }.get(severity, 0)
