from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


Criticality = Literal["low", "medium", "high", "critical"]
Severity = Literal["none", "low", "moderate", "high", "critical"]
Urgency = Literal["monitor", "scheduled", "priority", "emergency"]
EvidenceModality = Literal["text", "image", "video", "video_frame", "sensor", "record"]


@dataclass
class Asset:
    asset_id: str
    asset_type: str
    name: str
    location: str
    criticality: Criticality
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    source_id: str
    source_type: str
    content: str
    modality: EvidenceModality = "text"
    file_path: str | None = None
    frame_timestamp_seconds: float | None = None


@dataclass
class MediaReference:
    file_path: str
    frame_timestamp_seconds: float | None = None
    bounding_box: tuple[int, int, int, int] | None = None


@dataclass
class InspectionCase:
    case_id: str
    asset: Asset
    reason: str
    evidence: list[Evidence]
    constraints: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Observation:
    observation_id: str
    source_id: str
    source_modality: EvidenceModality
    defect_type: str
    description: str
    location_on_asset: str
    media_reference: MediaReference | None = None
    measurement: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7


@dataclass
class Citation:
    document_id: str
    title: str
    source_type: str
    excerpt: str
    score: float


@dataclass
class SeverityAssessment:
    severity: Severity
    repair_required: bool
    urgency: Urgency
    rationale: str
    confidence: float
    citations: list[Citation] = field(default_factory=list)


@dataclass
class MaintenanceTask:
    name: str
    description: str
    estimated_hours: float
    dependencies: list[str] = field(default_factory=list)


@dataclass
class HistoricalPrecedent:
    document_id: str
    title: str
    repair_method: str
    outcome: str
    actual_duration_hours: float
    disruption: str
    citation: Citation


@dataclass
class MaintenancePlan:
    recommended_action: str
    historical_precedents: list[HistoricalPrecedent]
    tasks: list[MaintenanceTask]
    materials: list[str]
    equipment: list[str]
    permits: list[str]
    estimated_duration_hours: float
    risks: list[str]


@dataclass
class WeatherContext:
    window_start: str
    condition: str
    risk_score: int
    rationale: str


@dataclass
class TrafficContext:
    window_start: str
    impact: str
    risk_score: int
    rationale: str


@dataclass
class EventContext:
    window_start: str
    title: str
    risk_score: int
    rationale: str


@dataclass
class SchedulingContext:
    weather: list[WeatherContext]
    traffic: list[TrafficContext]
    events: list[EventContext]
    access_risk_score: int = 0


@dataclass
class RepairWindow:
    start: datetime
    end: datetime


@dataclass
class RepairSchedule:
    recommended_window: RepairWindow
    disruption_score: int
    context_risk_score: int
    total_score: int
    constraints_satisfied: list[str]
    tradeoffs: list[str]
    context_summary: list[str] = field(default_factory=list)


@dataclass
class InspectionReport:
    case: InspectionCase
    observations: list[Observation]
    severity: SeverityAssessment
    maintenance_plan: MaintenancePlan
    schedule: RepairSchedule | None = None
    annotated_media_paths: list[str] = field(default_factory=list)
    rendered_report: str | None = None
    workflow_trace_id: str | None = None
    workflow_trace_path: str | None = None
