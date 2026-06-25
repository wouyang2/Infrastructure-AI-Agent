import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("data")

def ensure_dirs():
    dirs = [
        BASE / "bridge_knowledge",
        BASE / "bridge_media" / "images",
        BASE / "bridge_media" / "videos",
        BASE / "bridge_media" / "frames",
        BASE / "scheduling",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def build_standards():
    return [
        {
            "document_id": "STD-BRIDGE-SPALLING-001",
            "title": "Bridge Spalling Severity Guidance",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "spalling",
            "severity": "high",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Bridge deck spalling with loose concrete, exposed reinforcement, or active delamination "
                "should be treated as high severity when located near joints, load-bearing components, or "
                "traffic-exposed surfaces. If loose material may fall, strike vehicles, or affect traffic, "
                "temporary containment and priority repair are required. Monitoring is only appropriate when "
                "spalling is shallow, stable, and outside traffic or drainage-sensitive areas."
            ),
        },
        {
            "document_id": "STD-BRIDGE-CRACKING-001",
            "title": "Concrete Crack Severity Thresholds",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "crack",
            "severity": "medium",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Concrete cracks wider than 0.3 mm, cracks showing active growth, map cracking near drainage "
                "paths, or cracks with rust staining should be escalated beyond routine monitoring. Longitudinal "
                "or transverse cracks crossing structural elements require measurement, photo documentation, and "
                "comparison with prior inspection history."
            ),
        },
        {
            "document_id": "STD-BRIDGE-CORROSION-001",
            "title": "Steel Corrosion Severity Guidance",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "corrosion",
            "severity": "medium",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Surface corrosion on non-critical steel members may be monitored if section loss is not visible. "
                "Corrosion with flaking scale, section loss, pack rust, or staining near bearings, girders, or "
                "connection plates should be treated as medium to high severity depending on location and extent."
            ),
        },
        {
            "document_id": "STD-BRIDGE-REBAR-001",
            "title": "Exposed Reinforcement Escalation Criteria",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "exposed_rebar",
            "severity": "high",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Exposed reinforcement in bridge decks, parapets, piers, or expansion joint areas indicates loss "
                "of concrete cover and elevated corrosion risk. Exposed reinforcement should be classified as high "
                "severity when accompanied by active corrosion, loose surrounding concrete, or placement in a "
                "load-bearing or traffic-exposed component."
            ),
        },
        {
            "document_id": "STD-BRIDGE-JOINT-001",
            "title": "Expansion Joint Damage Guidance",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "joint_damage",
            "severity": "medium",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Expansion joint damage should be evaluated for water intrusion, debris accumulation, failed seals, "
                "edge spalling, vertical displacement, and vehicle impact risk. Joint damage causing water leakage "
                "onto bearings or substructure elements should be escalated because it can accelerate corrosion and "
                "concrete deterioration."
            ),
        },
        {
            "document_id": "STD-BRIDGE-LEAK-001",
            "title": "Water Leakage and Drainage Defect Guidance",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "water_leak",
            "severity": "medium",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Water leakage through deck joints, scuppers, or cracks should be documented and traced to its "
                "source. Persistent leakage that reaches bearings, steel members, reinforced concrete, or pedestrian "
                "areas should be treated as at least medium severity. Leakage with freeze-thaw damage or corrosion "
                "staining should trigger repair planning."
            ),
        },
        {
            "document_id": "STD-BRIDGE-EMERGENCY-001",
            "title": "Emergency Escalation Criteria for Bridge Defects",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "multi_defect",
            "severity": "critical",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Emergency escalation is required when a defect presents immediate risk to traffic, pedestrians, "
                "structural capacity, or falling debris. Examples include large loose concrete fragments, exposed "
                "reinforcement with active deterioration in load-bearing zones, severe joint displacement, or visible "
                "section loss in primary steel members."
            ),
        },
        {
            "document_id": "STD-BRIDGE-MONITORING-001",
            "title": "Monitoring Versus Repair Decision Rules",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "multi_defect",
            "severity": "low",
            "authority_level": "guidance",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Monitoring is acceptable for defects that are shallow, stable, outside load-critical zones, and not "
                "associated with water leakage or corrosion staining. Monitoring records must include date, location, "
                "measurements, photos, and a reinspection interval. Repair is required when defects grow, recur, or "
                "affect traffic safety."
            ),
        },
        {
            "document_id": "STD-BRIDGE-CONFIDENCE-001",
            "title": "Inspection Confidence and Evidence Limits",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "inspection_limit",
            "severity": "unknown",
            "authority_level": "guidance",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Visual inspection confidence should be reduced when images are blurred, poorly lit, partially "
                "occluded, or taken from extreme angles. Low-confidence findings should not be used as the sole basis "
                "for emergency action unless they indicate an obvious safety hazard. Follow-up inspection should be "
                "recommended when severity cannot be determined from available evidence."
            ),
        },
        {
            "document_id": "STD-BRIDGE-TRAFFIC-001",
            "title": "Traffic Exposure Considerations for Bridge Repair Priority",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "traffic_exposure",
            "severity": "medium",
            "authority_level": "policy",
            "effective_date": "2025-01-01",
            "jurisdiction": "generic",
            "text": (
                "Defects located in traffic lanes, shoulders, pedestrian paths, expansion joints, or overhead surfaces "
                "should receive higher priority because of user exposure. Even moderate physical deterioration may "
                "require priority repair if it can damage vehicles, create debris, or increase lane closure risk."
            ),
        },
    ]

def build_manuals():
    return [
        {
            "document_id": "MAN-BRIDGE-PATCH-001",
            "title": "Partial-Depth Concrete Patch Procedure",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "spalling",
            "repair_method": "partial-depth concrete patch",
            "text": (
                "Partial-depth concrete patching is appropriate for localized bridge deck or joint spalling where "
                "deterioration has not extended through the full deck depth. Work includes saw-cutting, removing "
                "loose concrete, cleaning exposed reinforcement, applying corrosion inhibitor, bonding agent, patch "
                "material, curing protection, and follow-up inspection."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-CRACK-SEAL-001",
            "title": "Concrete Crack Sealing Procedure",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "crack",
            "repair_method": "epoxy injection or routing and sealing",
            "text": (
                "Crack sealing is appropriate for stable cracks where water intrusion is the primary risk. Fine "
                "structural cracks may require epoxy injection. Wider non-structural cracks may be routed, cleaned, "
                "dried, and sealed using approved flexible sealant. Do not seal active cracks without movement "
                "assessment."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-CORROSION-001",
            "title": "Steel Corrosion Cleaning and Coating",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "corrosion",
            "repair_method": "abrasive cleaning and protective coating",
            "text": (
                "Corroded steel surfaces should be cleaned to remove loose scale and contaminants before coating. "
                "Where section loss is suspected, thickness measurement is required before selecting repair. Coating "
                "work should be scheduled in dry weather with temperature and humidity within coating specifications."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-REBAR-001",
            "title": "Exposed Rebar Concrete Restoration",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "exposed_rebar",
            "repair_method": "rebar cleaning and concrete restoration",
            "text": (
                "For exposed reinforcement, remove unsound concrete around the bar, clean corrosion products, verify "
                "remaining bar section, apply corrosion inhibitor or protective coating, restore concrete cover using "
                "approved repair mortar, and cure according to material requirements."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-JOINT-001",
            "title": "Expansion Joint Seal Replacement",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "joint_damage",
            "repair_method": "joint seal replacement",
            "text": (
                "Joint seal replacement includes removing failed seal material, cleaning the joint cavity, repairing "
                "edge spalls, installing new seal material, and verifying watertightness. Traffic control is usually "
                "required, and overnight partial closures are preferred for high-volume routes."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-LEAK-001",
            "title": "Drainage Leak Mitigation",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "water_leak",
            "repair_method": "drainage cleaning and leak sealing",
            "text": (
                "Water leakage repairs should begin with source tracing. Common actions include clearing blocked "
                "scuppers, resealing joints, repairing deck cracks, installing drip edges, and protecting affected "
                "bearings or steel surfaces from continued wetting."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-FULLDEPTH-001",
            "title": "Full-Depth Deck Repair Procedure",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "deck_deterioration",
            "repair_method": "full-depth concrete repair",
            "text": (
                "Full-depth repair is used when deterioration extends through the deck or when delamination affects "
                "structural capacity. Work requires lane closure, saw-cutting, removal through the deck depth, formwork, "
                "reinforcement repair, concrete placement, curing, and load reopening verification."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-TEMP-001",
            "title": "Temporary Containment and Make-Safe Actions",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "falling_debris",
            "repair_method": "temporary containment",
            "text": (
                "Temporary containment may include debris netting, shielding, lane restriction, shoulder closure, or "
                "removal of loose material. Make-safe actions are not permanent repairs and must be followed by a "
                "documented repair plan and reinspection."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-INSPECT-AFTER-001",
            "title": "Post-Repair Inspection Requirements",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "post_repair",
            "repair_method": "inspection",
            "text": (
                "Post-repair inspection should confirm bond condition, surface finish, curing protection, absence of "
                "new cracks, drainage performance, and traffic safety. High-severity repairs should receive follow-up "
                "inspection within 30 to 90 days."
            ),
        },
        {
            "document_id": "MAN-BRIDGE-TRAFFIC-CONTROL-001",
            "title": "Traffic Control for Bridge Maintenance",
            "source_type": "manual",
            "asset_type": "bridge",
            "defect_type": "traffic_management",
            "repair_method": "traffic control",
            "text": (
                "Bridge maintenance affecting travel lanes should use the lowest-disruption closure compatible with "
                "worker safety and repair quality. Overnight partial closures are preferred for moderate repairs. Full "
                "closures require public notice, detour planning, and permit coordination."
            ),
        },
    ]

def build_inspection_reports():
    reports = []
    templates = [
        ("BR-042", "expansion_joint", "spalling", "minor spalling near expansion joint J3, approximately 10 cm by 18 cm. No exposed reinforcement observed.", "monitoring and reinspection within 90 days"),
        ("BR-042", "expansion_joint", "spalling", "growth of prior spall near J3 with loose concrete and shallow delamination. Possible traffic exposure at lane edge.", "priority partial-depth patch"),
        ("BR-017", "girder", "corrosion", "rust staining and surface corrosion on exterior steel girder near drainage outlet. No visible section loss.", "cleaning, coating assessment, and drainage review"),
        ("BR-088", "deck", "crack", "transverse deck crack approximately 0.4 mm wide with light efflorescence.", "seal crack and monitor for recurrence"),
        ("BR-031", "parapet", "exposed_rebar", "localized concrete loss on parapet face with exposed reinforcement and rust staining.", "concrete restoration within current maintenance cycle"),
        ("BR-064", "joint", "joint_damage", "failed joint seal with debris accumulation and water leakage below deck.", "joint seal replacement and drainage cleaning"),
        ("BR-019", "pier_cap", "water_leak", "persistent leakage path and staining on pier cap below deck joint.", "trace leak source and repair joint seal"),
        ("BR-073", "deck", "normal/no_defect", "deck surface visually stable with no new cracks or spalls in sampled inspection images.", "routine inspection interval"),
        ("BR-055", "bearing_area", "corrosion", "pack rust observed near bearing plate. Access limited by debris and shadowing.", "hands-on inspection and section-loss measurement"),
        ("BR-026", "sidewalk", "crack", "longitudinal sidewalk crack with no displacement and no water staining.", "monitoring only"),
    ]

    start_date = datetime(2025, 1, 15)
    for i in range(20):
        asset_id, component, defect_type, finding, action = templates[i % len(templates)]
        date = start_date + timedelta(days=i * 17)
        severity = (
            "high" if defect_type in ["exposed_rebar"] or (defect_type == "spalling" and i % 2 == 1)
            else "medium" if defect_type in ["spalling", "corrosion", "joint_damage", "water_leak", "crack"]
            else "low"
        )
        reports.append({
            "document_id": f"INSP-{asset_id}-{date.strftime('%Y-%m')}",
            "source_type": "inspection_report",
            "asset_id": asset_id,
            "asset_type": "bridge",
            "component": component,
            "defect_type": defect_type,
            "severity": severity,
            "inspection_date": date.strftime("%Y-%m-%d"),
            "photos_referenced": f"{asset_id}_{defect_type}_{i+1:03d}.jpg",
            "recommended_action": action,
            "follow_up_result": "pending" if i > 14 else "completed or scheduled",
            "text": (
                f"{date.strftime('%Y-%m-%d')} inspection of bridge {asset_id} found {finding} "
                f"Recommended action: {action}. Severity recorded as {severity}. "
                f"Photo reference: {asset_id}_{defect_type}_{i+1:03d}.jpg."
            ),
        })
    return reports

def build_repair_records():
    records = []
    methods = {
        "spalling": ("partial-depth concrete patch", "patching concrete; corrosion inhibitor; bonding agent", "saw cutter; chipping hammer; traffic barriers"),
        "crack": ("routing and sealing", "flexible sealant; primer", "router; compressed air; sealant gun"),
        "corrosion": ("abrasive cleaning and protective coating", "zinc primer; epoxy coating", "needle scaler; containment tarp; sprayer"),
        "exposed_rebar": ("rebar cleaning and concrete restoration", "repair mortar; corrosion inhibitor; bonding agent", "chipping hammer; wire brush; forms"),
        "joint_damage": ("joint seal replacement", "joint seal; patch mortar; backer rod", "joint saw; compressor; traffic barriers"),
        "water_leak": ("drainage cleaning and leak sealing", "joint sealant; drain screens; waterproofing compound", "vacuum truck; sealant gun; lift"),
    }
    assets = ["BR-042", "BR-017", "BR-088", "BR-031", "BR-064", "BR-019", "BR-055", "BR-026", "BR-073", "BR-091"]
    components = ["expansion_joint", "deck", "girder", "parapet", "pier_cap", "bearing_area", "sidewalk"]
    defects = list(methods.keys())
    severities = ["low", "medium", "high"]
    closures = ["shoulder closure", "overnight partial closure", "single-lane closure", "short full closure"]
    disruptions = ["low", "medium", "high"]
    weather = ["clear", "light rain", "hot and dry", "cold", "windy", "humid"]
    outcomes = ["successful", "successful with monitoring", "temporary repair", "requires follow-up"]

    for i in range(30):
        defect = defects[i % len(defects)]
        method, materials, equipment = methods[defect]
        severity = severities[(i + 1) % len(severities)]
        planned = 6 + (i % 6) * 3
        actual = planned + ((i % 5) - 1)
        actual = max(actual, planned - 1)
        planned_cost = 4500 + (i % 8) * 1800 + (3000 if severity == "high" else 0)
        actual_cost = int(planned_cost * (1.05 + (i % 4) * 0.04))
        recurrence = "true" if i in [7, 18, 24] else "false"
        date = datetime(2025, 2, 1) + timedelta(days=i * 11)

        records.append({
            "repair_id": f"HIST-BRIDGE-{i+1:03d}",
            "asset_id": assets[i % len(assets)],
            "asset_type": "bridge",
            "component": components[i % len(components)],
            "defect_type": defect,
            "severity_before_repair": severity,
            "repair_method": method,
            "repair_description": (
                f"Addressed {severity}-severity {defect} on bridge component using {method}. "
                f"Work area was documented before and after repair."
            ),
            "materials_used": materials,
            "equipment_used": equipment,
            "crew_size": 3 + (i % 4),
            "planned_duration_hours": planned,
            "actual_duration_hours": actual,
            "planned_cost": planned_cost,
            "actual_cost": actual_cost,
            "traffic_disruption_level": disruptions[i % len(disruptions)],
            "closure_type": closures[i % len(closures)],
            "weather_condition": weather[i % len(weather)],
            "permit_required": "yes" if closures[i % len(closures)] in ["single-lane closure", "short full closure", "overnight partial closure"] else "no",
            "repair_outcome": outcomes[i % len(outcomes)],
            "recurrence_within_12_months": recurrence,
            "post_repair_inspection_notes": (
                "Patch stable after follow-up inspection."
                if recurrence == "false"
                else "Minor recurrence observed near edge of previous repair; follow-up recommended."
            ),
            "date_completed": date.strftime("%Y-%m-%d"),
            "rag_text": (
                f"A {date.strftime('%Y')} repair on bridge {assets[i % len(assets)]} addressed "
                f"{severity}-severity {defect} at the {components[i % len(components)]}. The crew used "
                f"{method}. Work required a {3 + (i % 4)}-person crew, {closures[i % len(closures)]}, "
                f"and {actual} actual hours. Outcome was {outcomes[i % len(outcomes)]}; recurrence within "
                f"12 months was {recurrence}."
            ),
        })
    return records

def build_image_metadata():
    defects = ["spalling", "crack", "corrosion", "exposed_rebar", "joint_damage", "water_leak", "normal/no_defect"]
    components = ["deck", "expansion_joint", "girder", "parapet", "pier_cap", "bearing_area"]
    rows = []
    for i in range(100):
        defect = defects[i % len(defects)]
        severity = "none" if defect == "normal/no_defect" else ["low", "medium", "high"][i % 3]
        rows.append({
            "image_id": f"IMG-{i+1:04d}",
            "file_path": f"bridge_media/images/files/IMG-{i+1:04d}.jpg",
            "asset_id": f"BR-{(i % 12) + 1:03d}",
            "asset_type": "bridge",
            "component": components[i % len(components)],
            "defect_type": defect,
            "severity_label": severity,
            "location_on_asset": f"{components[i % len(components)]} zone {(i % 5) + 1}",
            "confidence_label": round(0.72 + (i % 20) * 0.012, 2),
            "inspection_date": (datetime(2025, 8, 1) + timedelta(days=i % 45)).strftime("%Y-%m-%d"),
            "notes": (
                "Synthetic metadata placeholder. Image file supplied separately by user."
                if defect != "normal/no_defect"
                else "No visible defect in supplied inspection image."
            ),
        })
    return rows

def build_video_metadata():
    rows = []
    for i in range(10):
        rows.append({
            "video_id": f"VID-{i+1:03d}",
            "file_path": f"bridge_media/videos/files/VID-{i+1:03d}.mp4",
            "asset_id": f"BR-{(i % 8) + 1:03d}",
            "asset_type": "bridge",
            "component": ["expansion_joint", "deck", "girder", "pier_cap"][i % 4],
            "known_defects": ["spalling; exposed_rebar", "crack", "corrosion", "joint_damage; water_leak"][i % 4],
            "duration_seconds": 30 + i * 5,
            "sampling_interval_seconds": 5,
            "inspection_date": (datetime(2025, 9, 1) + timedelta(days=i * 3)).strftime("%Y-%m-%d"),
            "notes": "Synthetic video metadata placeholder. Video file supplied separately by user.",
        })
    return rows

def build_frame_metadata():
    rows = []
    frame_num = 1
    for v in range(10):
        video_id = f"VID-{v+1:03d}"
        for t in range(0, 30, 5):
            defect = ["spalling", "crack", "corrosion", "joint_damage", "water_leak", "normal/no_defect"][(v + t // 5) % 6]
            rows.append({
                "frame_id": f"{video_id}-F{frame_num:04d}",
                "video_id": video_id,
                "frame_path": f"bridge_media/frames/files/{video_id}_frame_{t:04d}.jpg",
                "timestamp_seconds": float(t),
                "defect_type": defect,
                "severity_label": "none" if defect == "normal/no_defect" else ["low", "medium", "high"][(v + t) % 3],
                "notes": f"Sampled frame at {t} seconds. Synthetic metadata for {defect}.",
            })
            frame_num += 1
    return rows

def build_scheduling():
    repair_windows = []
    weather_context = []
    traffic_context = []
    event_context = []
    access_context = []

    base_start = datetime(2026, 6, 18, 22, 0)
    crews = ["night maintenance crew", "concrete repair crew", "joint repair crew", "steel coating crew"]
    closure_types = ["partial closure", "single-lane closure", "shoulder closure", "short full closure"]

    for i in range(20):
        start = base_start + timedelta(days=i, hours=(i % 3))
        end = start + timedelta(hours=8)
        window_id = f"WIN-{i+1:03d}"

        disruption = [2, 3, 5, 7, 8][i % 5]
        closure = closure_types[i % len(closure_types)]

        repair_windows.append({
            "window_id": window_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "crew": crews[i % len(crews)],
            "crew_available": "false" if i in [6, 13] else "true",
            "disruption_score": disruption,
            "closure_type": closure,
            "notes": (
                "Low traffic overnight window"
                if disruption <= 3
                else "Higher disruption due to lane restrictions or daytime spillover risk"
            ),
        })

        precip = [5, 15, 35, 60, 80][i % 5]
        weather_context.append({
            "window_id": window_id,
            "condition": ["clear", "cloudy", "light rain", "storm risk", "heavy rain"][i % 5],
            "temperature_f": 62 + (i % 10) * 3,
            "precipitation_probability": precip,
            "wind_mph": 4 + (i % 8) * 2,
            "weather_risk_score": 1 if precip < 20 else 3 if precip < 50 else 7,
            "rationale": (
                "Weather suitable for concrete and coating work."
                if precip < 20
                else "Weather may affect curing, coating adhesion, or worker safety."
            ),
        })

        traffic = ["low", "medium", "high", "very high"][i % 4]
        traffic_context.append({
            "window_id": window_id,
            "traffic_level": traffic,
            "estimated_delay_minutes": [4, 9, 18, 35][i % 4],
            "traffic_risk_score": [1, 3, 6, 9][i % 4],
            "rationale": (
                "Overnight traffic expected to be low."
                if traffic == "low"
                else "Lane closure may cause measurable delay."
            ),
        })

        event_context.append({
            "window_id": window_id,
            "event_title": ["none", "minor downtown event", "stadium event", "regional festival"][i % 4],
            "event_distance_miles": [0, 3.2, 1.1, 5.5][i % 4],
            "expected_attendance": [0, 1200, 42000, 9000][i % 4],
            "event_risk_score": [0, 2, 9, 5][i % 4],
            "rationale": (
                "No known event conflict."
                if i % 4 == 0
                else "Nearby event may increase traffic demand or restrict detour options."
            ),
        })

        access_context.append({
            "window_id": window_id,
            "access_constraint": ["none", "under-bridge access limited", "rail coordination required", "lift equipment required"][i % 4],
            "access_risk_score": [0, 4, 7, 5][i % 4],
            "rationale": (
                "No unusual access constraints."
                if i % 4 == 0
                else "Access constraints may require coordination before work begins."
            ),
        })

    return repair_windows, weather_context, traffic_context, event_context, access_context

def main():
    ensure_dirs()

    standards = build_standards()
    manuals = build_manuals()
    inspection_reports = build_inspection_reports()
    repair_records = build_repair_records()
    image_metadata = build_image_metadata()
    video_metadata = build_video_metadata()
    frame_metadata = build_frame_metadata()
    repair_windows, weather_context, traffic_context, event_context, access_context = build_scheduling()

    write_jsonl(BASE / "bridge_knowledge" / "standards.jsonl", standards)
    write_jsonl(BASE / "bridge_knowledge" / "manuals.jsonl", manuals)
    write_jsonl(BASE / "bridge_knowledge" / "inspection_reports.jsonl", inspection_reports)

    repair_fields = [
        "repair_id",
        "asset_id",
        "asset_type",
        "component",
        "defect_type",
        "severity_before_repair",
        "repair_method",
        "repair_description",
        "materials_used",
        "equipment_used",
        "crew_size",
        "planned_duration_hours",
        "actual_duration_hours",
        "planned_cost",
        "actual_cost",
        "traffic_disruption_level",
        "closure_type",
        "weather_condition",
        "permit_required",
        "repair_outcome",
        "recurrence_within_12_months",
        "post_repair_inspection_notes",
        "date_completed",
        "rag_text",
    ]
    write_csv(BASE / "bridge_knowledge" / "repair_records.csv", repair_records, repair_fields)

    image_fields = [
        "image_id",
        "file_path",
        "asset_id",
        "asset_type",
        "component",
        "defect_type",
        "severity_label",
        "location_on_asset",
        "confidence_label",
        "inspection_date",
        "notes",
    ]
    write_csv(BASE / "bridge_media" / "images" / "metadata.csv", image_metadata, image_fields)

    video_fields = [
        "video_id",
        "file_path",
        "asset_id",
        "asset_type",
        "component",
        "known_defects",
        "duration_seconds",
        "sampling_interval_seconds",
        "inspection_date",
        "notes",
    ]
    write_csv(BASE / "bridge_media" / "videos" / "metadata.csv", video_metadata, video_fields)

    frame_fields = [
        "frame_id",
        "video_id",
        "frame_path",
        "timestamp_seconds",
        "defect_type",
        "severity_label",
        "notes",
    ]
    write_csv(BASE / "bridge_media" / "frames" / "metadata.csv", frame_metadata, frame_fields)

    write_csv(
        BASE / "scheduling" / "repair_windows.csv",
        repair_windows,
        ["window_id", "start", "end", "crew", "crew_available", "disruption_score", "closure_type", "notes"],
    )
    write_csv(
        BASE / "scheduling" / "weather_context.csv",
        weather_context,
        ["window_id", "condition", "temperature_f", "precipitation_probability", "wind_mph", "weather_risk_score", "rationale"],
    )
    write_csv(
        BASE / "scheduling" / "traffic_context.csv",
        traffic_context,
        ["window_id", "traffic_level", "estimated_delay_minutes", "traffic_risk_score", "rationale"],
    )
    write_csv(
        BASE / "scheduling" / "event_context.csv",
        event_context,
        ["window_id", "event_title", "event_distance_miles", "expected_attendance", "event_risk_score", "rationale"],
    )
    write_csv(
        BASE / "scheduling" / "access_context.csv",
        access_context,
        ["window_id", "access_constraint", "access_risk_score", "rationale"],
    )

    print("Synthetic bridge infrastructure dataset generated under ./data")
    print("Generated:")
    print(f"  standards: {len(standards)}")
    print(f"  manuals: {len(manuals)}")
    print(f"  inspection reports: {len(inspection_reports)}")
    print(f"  historical repair records: {len(repair_records)}")
    print(f"  image metadata rows: {len(image_metadata)}")
    print(f"  video metadata rows: {len(video_metadata)}")
    print(f"  frame metadata rows: {len(frame_metadata)}")
    print(f"  scheduling windows: {len(repair_windows)}")

if __name__ == "__main__":
    main()
