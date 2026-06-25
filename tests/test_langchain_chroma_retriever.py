from __future__ import annotations

from uuid import uuid4

import pytest

from data.knowledge_corpus import load_knowledge_documents
from data.sample_knowledge import KNOWLEDGE_DOCUMENTS
from rag.chunking import build_hierarchical_chunks
from rag.langchain_chroma_retriever import LangChainChromaRetriever
from rag.retriever import LocalRetriever
from rag.retriever_factory import build_retriever


pytest.importorskip("langchain_chroma")


def build_test_retriever() -> LangChainChromaRetriever:
    return LangChainChromaRetriever(
        KNOWLEDGE_DOCUMENTS,
        embedding_backend="fake",
        collection_name=f"test_infrastructure_knowledge_{uuid4().hex}",
    )


def test_policy_retrieval_returns_bridge_spalling_standard() -> None:
    retriever = build_test_retriever()

    citations = retriever.search(
        "bridge spalling loose concrete exposed substrate",
        source_type="standard",
        asset_type="bridge",
        defect_type="spalling",
    )

    assert citations
    assert citations[0].document_id == "STD-GEN-002"


def test_historical_repair_retrieval_returns_bridge_spalling_record() -> None:
    retriever = build_test_retriever()

    citations = retriever.search(
        "bridge spalling partial closure concrete patch",
        source_type="repair_record",
        asset_type="bridge",
        defect_type="spalling",
    )

    assert citations
    assert citations[0].document_id == "HIST-BRIDGE-022"


def test_road_crack_retrieval_returns_road_repair_record() -> None:
    retriever = build_test_retriever()

    citations = retriever.search(
        "road longitudinal crack water intrusion sealing",
        source_type="repair_record",
        asset_type="road",
        defect_type="crack",
    )

    assert citations
    assert citations[0].document_id == "HIST-ROAD-014"


def test_metadata_filter_excludes_unrelated_asset_and_defect_records() -> None:
    retriever = build_test_retriever()

    citations = retriever.search(
        "bridge spalling concrete patch",
        source_type="repair_record",
        asset_type="road",
        defect_type="crack",
    )

    assert citations
    assert all(citation.document_id != "HIST-BRIDGE-022" for citation in citations)
    assert citations[0].document_id == "HIST-ROAD-014"


def test_retriever_factory_can_build_chroma_with_fake_embeddings() -> None:
    retriever = build_retriever(KNOWLEDGE_DOCUMENTS, embedding_backend="fake")

    assert isinstance(retriever, LangChainChromaRetriever)
    assert retriever.embedding_backend == "fake"


def test_retriever_factory_can_build_local_fallback() -> None:
    retriever = build_retriever(KNOWLEDGE_DOCUMENTS, rag_backend="local")

    assert isinstance(retriever, LocalRetriever)


def test_hierarchical_chunking_creates_parent_and_overlapping_children() -> None:
    documents = [
        {
            "document_id": "DOC-001",
            "title": "Chunk Test",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "spalling",
            "content": "A" * 500,
        }
    ]

    parents, children = build_hierarchical_chunks(
        documents,
        parent_chunk_size=300,
        child_chunk_size=120,
        child_chunk_overlap=20,
    )

    assert len(parents) == 2
    assert len(children) >= 4
    assert children[0].metadata["parent_id"] == parents[0].parent_id
    assert children[0].text[-20:] == children[1].text[:20]


def test_semantic_merge_includes_similar_sibling_chunks(tmp_path) -> None:
    documents = [
        {
            "document_id": "DOC-MERGE",
            "title": "Merge Test",
            "source_type": "standard",
            "asset_type": "bridge",
            "defect_type": "spalling",
            "content": (
                "spalling concrete patch repair " * 20
                + "spalling concrete patch repair " * 20
            ),
        }
    ]
    retriever = LangChainChromaRetriever(
        documents,
        embedding_backend="fake",
        collection_name=f"test_merge_{uuid4().hex}",
        persist_directory=str(tmp_path),
        parent_chunk_size=1200,
        child_chunk_size=160,
        child_chunk_overlap=20,
        semantic_merge_threshold=0.5,
    )

    citations = retriever.search(
        "spalling concrete patch",
        source_type="standard",
        asset_type="bridge",
        defect_type="spalling",
        limit=1,
    )

    assert citations
    assert len(citations[0].excerpt) > 160


def test_persistent_chroma_reloads_without_rebuild(tmp_path) -> None:
    collection_name = f"test_persist_{uuid4().hex}"
    first = LangChainChromaRetriever(
        KNOWLEDGE_DOCUMENTS,
        embedding_backend="fake",
        collection_name=collection_name,
        persist_directory=str(tmp_path),
        rebuild_index=True,
    )
    first_count = first.vector_store._collection.count()

    second = LangChainChromaRetriever(
        KNOWLEDGE_DOCUMENTS,
        embedding_backend="fake",
        collection_name=collection_name,
        persist_directory=str(tmp_path),
        rebuild_index=False,
    )

    assert first_count > 0
    assert second.vector_store._collection.count() == first_count


def test_rebuild_flag_replaces_existing_collection(tmp_path) -> None:
    collection_name = f"test_rebuild_{uuid4().hex}"
    first = LangChainChromaRetriever(
        KNOWLEDGE_DOCUMENTS[:1],
        embedding_backend="fake",
        collection_name=collection_name,
        persist_directory=str(tmp_path),
        rebuild_index=True,
    )
    first_count = first.vector_store._collection.count()

    second = LangChainChromaRetriever(
        KNOWLEDGE_DOCUMENTS,
        embedding_backend="fake",
        collection_name=collection_name,
        persist_directory=str(tmp_path),
        rebuild_index=True,
    )

    assert second.vector_store._collection.count() > first_count


def test_bridge_corpus_retrieves_bridge_spalling_standard_and_repair(tmp_path) -> None:
    retriever = LangChainChromaRetriever(
        load_knowledge_documents("bridge"),
        embedding_backend="fake",
        collection_name=f"test_bridge_corpus_{uuid4().hex}",
        persist_directory=str(tmp_path),
    )

    standards = retriever.search(
        "bridge spalling loose concrete exposed reinforcement",
        source_type="standard",
        asset_type="bridge",
        defect_type="spalling",
    )
    repairs = retriever.search(
        "bridge spalling partial-depth concrete patch repair",
        source_type="repair_record",
        asset_type="bridge",
        defect_type="spalling",
    )

    assert standards
    assert standards[0].document_id == "STD-BRIDGE-SPALLING-001"
    assert repairs
    assert repairs[0].document_id.startswith("HIST-BRIDGE-")


def test_bridge_corpus_retrieves_water_leak_docs_for_leak_queries(tmp_path) -> None:
    retriever = LangChainChromaRetriever(
        load_knowledge_documents("bridge"),
        embedding_backend="fake",
        collection_name=f"test_bridge_leak_alias_{uuid4().hex}",
        persist_directory=str(tmp_path),
    )

    standards = retriever.search(
        "bridge leak water seepage drainage repair",
        source_type="standard",
        asset_type="bridge",
        defect_type="leak",
    )
    repairs = retriever.search(
        "bridge leak drainage cleaning leak sealing repair",
        source_type="repair_record",
        asset_type="bridge",
        defect_type="leak",
    )

    assert standards
    assert standards[0].document_id == "STD-BRIDGE-LEAK-001"
    assert repairs
    assert repairs[0].document_id.startswith("HIST-BRIDGE-")
    assert retriever.get_document(repairs[0].document_id)["defect_type"] == "water_leak"
