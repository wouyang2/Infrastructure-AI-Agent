KNOWLEDGE_DOCUMENTS = [
    {
        "document_id": "STD-GEN-001",
        "title": "General Infrastructure Inspection Severity Guide",
        "source_type": "standard",
        "asset_type": "generic",
        "defect_type": "crack",
        "severity": "moderate",
        "authority_level": "policy",
        "content": (
            "Cracking with active water intrusion, exposed reinforcement, widening, "
            "or rapid progression should be treated as at least moderate severity. "
            "High criticality assets should be prioritized when similar defects are found."
        ),
    },
    {
        "document_id": "STD-GEN-002",
        "title": "Temporary Repair and Monitoring Guidance",
        "source_type": "standard",
        "asset_type": "generic",
        "defect_type": "spalling",
        "severity": "high",
        "authority_level": "policy",
        "content": (
            "Spalling with loose material or exposed structural substrate requires prompt "
            "stabilization, removal of loose material, and a permanent repair plan. "
            "Temporary containment is acceptable only when paired with follow-up inspection."
        ),
    },
    {
        "document_id": "HIST-ROAD-014",
        "title": "Arterial Road Deck Crack Injection Repair",
        "source_type": "repair_record",
        "asset_type": "road",
        "defect_type": "crack",
        "repair_method": "epoxy injection and surface sealing",
        "severity": "moderate",
        "repair_outcome": "successful",
        "actual_duration_hours": 9,
        "disruption": "single-lane closure overnight",
        "content": (
            "A 2024 repair addressed longitudinal cracking with minor water intrusion. "
            "The crew used epoxy injection, surface sealing, and a one-night single-lane "
            "closure. Post-repair inspection after six months found no recurrence."
        ),
    },
    {
        "document_id": "HIST-BRIDGE-022",
        "title": "Bridge Joint Spall Patch and Traffic Control",
        "source_type": "repair_record",
        "asset_type": "bridge",
        "defect_type": "spalling",
        "repair_method": "partial-depth concrete patch",
        "severity": "high",
        "repair_outcome": "successful with monitoring",
        "actual_duration_hours": 16,
        "disruption": "two overnight partial closures",
        "content": (
            "A 2025 bridge joint repair removed loose concrete, cleaned exposed steel, "
            "installed corrosion inhibitor, and placed a partial-depth patch. Work took "
            "two overnight closures and required a follow-up inspection after 30 days."
        ),
    },
    {
        "document_id": "HIST-BUILDING-006",
        "title": "Mechanical Room Pipe Leak Repair",
        "source_type": "repair_record",
        "asset_type": "building",
        "defect_type": "leak",
        "repair_method": "section isolation and pipe replacement",
        "severity": "moderate",
        "repair_outcome": "successful",
        "actual_duration_hours": 6,
        "disruption": "off-hours water shutdown",
        "content": (
            "A mechanical room leak was repaired by isolating the affected section, "
            "replacing the damaged pipe, pressure testing, and restoring service during "
            "an off-hours window. Occupant disruption was low."
        ),
    },
]


MOCK_REPAIR_WINDOWS = [
    {
        "start": "2026-06-18T22:00:00",
        "end": "2026-06-19T06:00:00",
        "crew": "night maintenance crew",
        "disruption_score": 2,
        "notes": "low traffic and low occupancy window",
    },
    {
        "start": "2026-06-19T09:00:00",
        "end": "2026-06-19T17:00:00",
        "crew": "day maintenance crew",
        "disruption_score": 7,
        "notes": "faster crew access but higher user disruption",
    },
    {
        "start": "2026-06-20T23:00:00",
        "end": "2026-06-21T07:00:00",
        "crew": "weekend night crew",
        "disruption_score": 1,
        "notes": "lowest disruption but delayed start",
    },
]


MOCK_SCHEDULING_CONTEXT = {
    "weather": {
        "2026-06-18T22:00:00": {
            "condition": "clear",
            "risk_score": 0,
            "rationale": "Clear overnight conditions are suitable for exterior work.",
        },
        "2026-06-19T09:00:00": {
            "condition": "heavy rain",
            "risk_score": 5,
            "rationale": "Rain increases surface-preparation risk and may delay curing.",
        },
        "2026-06-20T23:00:00": {
            "condition": "light wind",
            "risk_score": 1,
            "rationale": "Minor weather risk, acceptable for planned work.",
        },
    },
    "traffic": {
        "2026-06-18T22:00:00": {
            "impact": "low",
            "risk_score": 1,
            "rationale": "Low overnight traffic supports a partial closure.",
        },
        "2026-06-19T09:00:00": {
            "impact": "high",
            "risk_score": 4,
            "rationale": "Morning traffic would create major disruption.",
        },
        "2026-06-20T23:00:00": {
            "impact": "very low",
            "risk_score": 0,
            "rationale": "Weekend night traffic is expected to be minimal.",
        },
    },
    "events": {
        "2026-06-18T22:00:00": {
            "title": "No known nearby event",
            "risk_score": 0,
            "rationale": "No event conflicts found in mock city feed.",
        },
        "2026-06-19T09:00:00": {
            "title": "Downtown utility advisory",
            "risk_score": 2,
            "rationale": "Nearby work could complicate access routes.",
        },
        "2026-06-20T23:00:00": {
            "title": "Stadium event egress",
            "risk_score": 3,
            "rationale": "Late event traffic may affect crews and detours.",
        },
    },
    "access_risk_score": 1,
}
