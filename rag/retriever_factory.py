from __future__ import annotations

from typing import Any

from rag.langchain_chroma_retriever import LangChainChromaRetriever
from rag.retriever import LocalRetriever


def build_retriever(
    documents: list[dict[str, Any]],
    *,
    rag_backend: str = "chroma",
    embedding_backend: str = "openai",
    embedding_model: str | None = None,
    persist_directory: str = "artifacts/chroma",
    rebuild_index: bool = False,
    parent_chunk_size: int = 1200,
    child_chunk_size: int = 450,
    child_chunk_overlap: int = 100,
    semantic_merge_threshold: float = 0.78,
):
    if rag_backend == "chroma":
        return LangChainChromaRetriever(
            documents,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            persist_directory=persist_directory,
            rebuild_index=rebuild_index,
            parent_chunk_size=parent_chunk_size,
            child_chunk_size=child_chunk_size,
            child_chunk_overlap=child_chunk_overlap,
            semantic_merge_threshold=semantic_merge_threshold,
        )
    if rag_backend == "local":
        return LocalRetriever(documents)
    raise ValueError(f"Unsupported RAG backend: {rag_backend}")
