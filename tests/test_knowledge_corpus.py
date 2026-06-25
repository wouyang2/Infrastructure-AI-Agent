from __future__ import annotations

from data.knowledge_corpus import (
    load_bridge_knowledge_documents,
    load_knowledge_documents,
)


def test_bridge_knowledge_loader_normalizes_jsonl_and_csv_documents() -> None:
    documents = load_bridge_knowledge_documents()

    document_ids = {document["document_id"] for document in documents}
    assert "STD-BRIDGE-SPALLING-001" in document_ids
    assert "MAN-BRIDGE-PATCH-001" in document_ids
    assert "INSP-BR-042-2025-01" in document_ids
    assert "HIST-BRIDGE-001" in document_ids
    assert all("content" in document for document in documents)


def test_bridge_repair_records_keep_planning_fields() -> None:
    documents = load_bridge_knowledge_documents()
    repair = next(
        document for document in documents if document["document_id"] == "HIST-BRIDGE-001"
    )

    assert repair["source_type"] == "repair_record"
    assert repair["asset_type"] == "bridge"
    assert repair["defect_type"] == "spalling"
    assert repair["repair_method"] == "partial-depth concrete patch"
    assert repair["repair_outcome"] == "successful"
    assert repair["actual_duration_hours"] == 5
    assert repair["disruption"] == "low disruption, shoulder closure"


def test_bridge_scheduling_records_are_loaded_for_rag() -> None:
    documents = load_bridge_knowledge_documents()
    schedule = next(
        document
        for document in documents
        if document["document_id"] == "SCHED-BRIDGE-001"
    )

    assert schedule["source_type"] == "schedule_record"
    assert schedule["asset_type"] == "bridge"
    assert schedule["defect_type"] == "spalling"
    assert schedule["preferred_window_type"] == "overnight"
    assert schedule["preferred_crew_type"] == "concrete"
    assert schedule["preferred_closure_type"] == "single-lane closure"
    assert schedule["disruption_outcome"] == "low disruption"


def test_merged_knowledge_corpus_has_unique_document_ids() -> None:
    documents = load_knowledge_documents("merged")
    document_ids = [document["document_id"] for document in documents]

    assert len(document_ids) == len(set(document_ids))
    assert "STD-GEN-002" in set(document_ids)
    assert "STD-BRIDGE-SPALLING-001" in set(document_ids)
