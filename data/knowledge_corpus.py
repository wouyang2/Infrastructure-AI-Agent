from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Literal

from data.sample_knowledge import KNOWLEDGE_DOCUMENTS


KnowledgeCorpusMode = Literal["sample", "bridge", "merged"]

BRIDGE_KNOWLEDGE_DIR = Path("data/bridge_knowledge")


def load_knowledge_documents(
    mode: KnowledgeCorpusMode = "merged",
    *,
    bridge_knowledge_dir: Path = BRIDGE_KNOWLEDGE_DIR,
) -> list[dict[str, Any]]:
    if mode == "sample":
        return list(KNOWLEDGE_DOCUMENTS)
    if mode == "bridge":
        return _dedupe_documents(load_bridge_knowledge_documents(bridge_knowledge_dir))
    if mode == "merged":
        return _dedupe_documents(
            list(KNOWLEDGE_DOCUMENTS)
            + load_bridge_knowledge_documents(bridge_knowledge_dir)
        )
    raise ValueError(f"Unsupported knowledge corpus mode: {mode}")


def load_bridge_knowledge_documents(
    bridge_knowledge_dir: Path = BRIDGE_KNOWLEDGE_DIR,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    documents.extend(_load_jsonl_documents(bridge_knowledge_dir / "standards.jsonl"))
    documents.extend(_load_jsonl_documents(bridge_knowledge_dir / "manuals.jsonl"))
    documents.extend(
        _load_jsonl_documents(bridge_knowledge_dir / "inspection_reports.jsonl")
    )
    documents.extend(_load_repair_record_documents(bridge_knowledge_dir / "repair_records.csv"))
    documents.extend(
        _load_scheduling_record_documents(bridge_knowledge_dir / "scheduling_records.csv")
    )
    return documents


def _dedupe_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for document in documents:
        document_id = document["document_id"]
        if document_id in seen:
            continue
        seen.add(document_id)
        deduped.append(document)
    return deduped


def _load_jsonl_documents(path: Path) -> list[dict[str, Any]]:
    documents = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            document = dict(row)
            document["content"] = document.pop("text")
            document.setdefault("title", document["document_id"])
            documents.append(document)
    return documents


def _load_repair_record_documents(path: Path) -> list[dict[str, Any]]:
    documents = []
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            documents.append(
                {
                    "document_id": row["repair_id"],
                    "title": _repair_record_title(row),
                    "source_type": "repair_record",
                    "asset_id": row["asset_id"],
                    "asset_type": row["asset_type"],
                    "component": row["component"],
                    "defect_type": row["defect_type"],
                    "severity": row["severity_before_repair"],
                    "repair_method": row["repair_method"],
                    "repair_outcome": row["repair_outcome"],
                    "actual_duration_hours": _number(row["actual_duration_hours"]),
                    "planned_duration_hours": _number(row["planned_duration_hours"]),
                    "planned_cost": _number(row["planned_cost"]),
                    "actual_cost": _number(row["actual_cost"]),
                    "materials_used": row["materials_used"],
                    "equipment_used": row["equipment_used"],
                    "crew_size": _number(row["crew_size"]),
                    "closure_type": row["closure_type"],
                    "traffic_disruption_level": row["traffic_disruption_level"],
                    "weather_condition": row["weather_condition"],
                    "permit_required": row["permit_required"],
                    "recurrence_within_12_months": row["recurrence_within_12_months"],
                    "date_completed": row["date_completed"],
                    "disruption": _disruption(row),
                    "content": row["rag_text"],
                }
            )
    return documents


def _load_scheduling_record_documents(path: Path) -> list[dict[str, Any]]:
    documents = []
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            documents.append(
                {
                    "document_id": row["schedule_id"],
                    "title": _scheduling_record_title(row),
                    "source_type": "schedule_record",
                    "asset_type": row["asset_type"],
                    "defect_type": row["defect_type"],
                    "severity": row["severity"],
                    "repair_method": row["repair_method"],
                    "preferred_window_type": row["preferred_window_type"],
                    "preferred_crew_type": row["preferred_crew_type"],
                    "preferred_closure_type": row["preferred_closure_type"],
                    "planned_duration_hours": _number(row["planned_duration_hours"]),
                    "actual_duration_hours": _number(row["actual_duration_hours"]),
                    "context_conditions": row["context_conditions"],
                    "schedule_outcome": row["schedule_outcome"],
                    "disruption_outcome": row["disruption_outcome"],
                    "lessons_learned": row["lessons_learned"],
                    "content": row["rag_text"],
                }
            )
    return documents


def _repair_record_title(row: dict[str, str]) -> str:
    defect = row["defect_type"].replace("_", " ")
    method = row["repair_method"]
    asset = row["asset_id"]
    return f"{asset} {defect.title()} Repair Using {method}"


def _scheduling_record_title(row: dict[str, str]) -> str:
    defect = row["defect_type"].replace("_", " ")
    method = row["repair_method"]
    return f"{row['asset_type'].title()} {defect.title()} Scheduling Case for {method}"


def _disruption(row: dict[str, str]) -> str:
    return f"{row['traffic_disruption_level']} disruption, {row['closure_type']}"


def _number(value: str) -> float | int:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number
