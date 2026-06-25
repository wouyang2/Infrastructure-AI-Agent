from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from models import Citation
from rag.chunking import ChildChunk, build_hierarchical_chunks
from rag.fake_embeddings import DeterministicFakeEmbeddings


DEFECT_FILTER_ALIASES = {
    "leak": {"leak", "water_leak"},
    "water_leak": {"leak", "water_leak"},
}


class LangChainChromaRetriever:
    def __init__(
        self,
        documents: list[dict[str, Any]],
        *,
        embedding_backend: str = "openai",
        embedding_model: str | None = None,
        collection_name: str | None = None,
        persist_directory: str = "artifacts/chroma",
        rebuild_index: bool = False,
        parent_chunk_size: int = 1200,
        child_chunk_size: int = 450,
        child_chunk_overlap: int = 100,
        semantic_merge_threshold: float = 0.78,
    ):
        self.documents = documents
        self.documents_by_id = {
            document["document_id"]: document for document in documents
        }
        self.embedding_backend = embedding_backend
        self.embedding_model = embedding_model or os.getenv(
            "OPENAI_EMBEDDING_MODEL",
            "text-embedding-3-small",
        )
        self.persist_directory = persist_directory
        self.rebuild_index = rebuild_index
        self.parent_chunk_size = parent_chunk_size
        self.child_chunk_size = child_chunk_size
        self.child_chunk_overlap = child_chunk_overlap
        self.semantic_merge_threshold = semantic_merge_threshold
        self.collection_name = collection_name or self._stable_collection_name()
        self.parent_chunks, self.child_chunks = build_hierarchical_chunks(
            documents,
            parent_chunk_size=parent_chunk_size,
            child_chunk_size=child_chunk_size,
            child_chunk_overlap=child_chunk_overlap,
        )
        self.child_chunks_by_id = {chunk.child_id: chunk for chunk in self.child_chunks}
        self.child_chunks_by_parent: dict[str, list[ChildChunk]] = {}
        for chunk in self.child_chunks:
            self.child_chunks_by_parent.setdefault(chunk.parent_id, []).append(chunk)
        self._embedding_cache: dict[str, list[float]] = {}
        self.embeddings = self._build_embeddings()
        self.vector_store = self._build_vector_store()

    def search(
        self,
        query: str,
        *,
        source_type: str | None = None,
        asset_type: str | None = None,
        defect_type: str | None = None,
        limit: int = 3,
    ) -> list[Citation]:
        where = self._metadata_filter(
            source_type=source_type,
            asset_type=asset_type,
            defect_type=defect_type,
        )
        raw_limit = max(limit * 8, limit)
        results = self.vector_store.similarity_search_with_score(
            query,
            k=raw_limit,
            filter=where,
        )

        citations: list[Citation] = []
        seen_documents = set()
        for document, score in results:
            metadata = document.metadata
            if asset_type and metadata.get("asset_type") not in {asset_type, "generic"}:
                continue
            if defect_type and metadata.get("defect_type") not in _defect_filter_values(defect_type):
                continue

            document_id = str(metadata["document_id"])
            if document_id in seen_documents:
                continue

            citations.append(
                Citation(
                    document_id=document_id,
                    title=str(metadata["title"]),
                    source_type=str(metadata["source_type"]),
                    excerpt=self._merged_excerpt(document),
                    score=round(float(score), 3),
                )
            )
            seen_documents.add(document_id)
            if len(citations) >= limit:
                break

        return citations

    def _metadata_filter(
        self,
        *,
        source_type: str | None,
        asset_type: str | None,
        defect_type: str | None,
    ) -> dict[str, Any] | None:
        filters: list[dict[str, Any]] = []
        if source_type:
            filters.append({"source_type": source_type})
        if asset_type:
            filters.append({"asset_type": {"$in": [asset_type, "generic"]}})
        if defect_type:
            filters.append({"defect_type": {"$in": sorted(_defect_filter_values(defect_type))}})
        if not filters:
            return None
        if len(filters) == 1:
            return filters[0]
        return {"$and": filters}

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.documents_by_id.get(document_id)

    def _build_vector_store(self):
        try:
            from langchain_chroma import Chroma
        except ImportError as exc:
            raise RuntimeError(
                "LangChain Chroma RAG requires 'langchain-chroma' and 'chromadb'. "
                "Install requirements before using the default Chroma retriever."
            ) from exc

        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
        vector_store = Chroma(
            collection_name=self.collection_name,
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory,
        )
        if self.rebuild_index:
            vector_store.delete_collection()
            vector_store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=self.persist_directory,
            )

        if vector_store._collection.count() == 0:
            vector_store.add_documents(
                self._to_langchain_documents(),
                ids=[chunk.child_id for chunk in self.child_chunks],
            )

        return vector_store

    def _build_embeddings(self):
        if self.embedding_backend == "fake":
            return DeterministicFakeEmbeddings()

        if self.embedding_backend == "openai":
            try:
                from dotenv import load_dotenv

                load_dotenv()
            except ImportError:
                pass

            try:
                from langchain_openai import OpenAIEmbeddings
            except ImportError as exc:
                raise RuntimeError(
                    "OpenAI embeddings require the 'langchain-openai' package."
                ) from exc
            return OpenAIEmbeddings(model=self.embedding_model)

        raise ValueError(f"Unsupported embedding backend: {self.embedding_backend}")

    def _to_langchain_documents(self) -> list[Document]:
        return [
            Document(
                page_content=chunk.text,
                metadata=chunk.metadata,
            )
            for chunk in self.child_chunks
        ]

    def _merged_excerpt(self, hit_document: Document) -> str:
        child_id = str(hit_document.metadata.get("child_id", ""))
        hit_chunk = self.child_chunks_by_id.get(child_id)
        if not hit_chunk:
            return hit_document.page_content

        hit_embedding = self._embedding_for_child(hit_chunk)
        merged = [hit_chunk]
        for sibling in self.child_chunks_by_parent.get(hit_chunk.parent_id, []):
            if sibling.child_id == hit_chunk.child_id:
                continue
            similarity = _cosine_similarity(
                hit_embedding,
                self._embedding_for_child(sibling),
            )
            if similarity >= self.semantic_merge_threshold:
                merged.append(sibling)

        merged.sort(key=lambda chunk: chunk.chunk_index)
        return " ".join(chunk.text for chunk in merged)

    def _embedding_for_child(self, child: ChildChunk) -> list[float]:
        if child.child_id in self._embedding_cache:
            return self._embedding_cache[child.child_id]

        result = self.vector_store._collection.get(
            ids=[child.child_id],
            include=["embeddings"],
        )
        embeddings = result.get("embeddings")
        if embeddings is not None and len(embeddings) > 0:
            embedding = embeddings[0]
            if hasattr(embedding, "tolist"):
                embedding = embedding.tolist()
            self._embedding_cache[child.child_id] = list(embedding)
            return self._embedding_cache[child.child_id]

        self._embedding_cache[child.child_id] = self.embeddings.embed_query(child.text)
        return self._embedding_cache[child.child_id]

    def _stable_collection_name(self) -> str:
        corpus_fingerprint = hashlib.sha256(
            "|".join(document["document_id"] for document in self.documents).encode(
                "utf-8"
            )
        ).hexdigest()[:12]
        raw_name = (
            f"infra_{self.embedding_backend}_{self.embedding_model}_"
            f"p{self.parent_chunk_size}_c{self.child_chunk_size}_"
            f"o{self.child_chunk_overlap}_{corpus_fingerprint}"
        )
        return re.sub(r"[^a-zA-Z0-9._-]", "_", raw_name)[:63]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _defect_filter_values(defect_type: str) -> set[str]:
    return DEFECT_FILTER_ALIASES.get(defect_type, {defect_type})
