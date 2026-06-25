from __future__ import annotations

from models import Observation


SEVERITY_RANK = {
    "none": 0,
    "low": 1,
    "moderate": 2,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

DEFECT_RANK = {
    "unknown": 0,
    "leak": 1,
    "water_leak": 1,
    "corrosion": 2,
    "crack": 3,
    "spalling": 4,
    "exposed_rebar": 5,
}


def select_primary_observation(observations: list[Observation]) -> Observation:
    if not observations:
        raise ValueError("Cannot select primary observation from an empty list.")

    return max(
        observations,
        key=lambda observation: (
            SEVERITY_RANK.get(str(observation.measurement.get("severity_label", "")), 0),
            DEFECT_RANK.get(observation.defect_type, 0),
            observation.confidence,
        ),
    )
