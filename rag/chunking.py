from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParentChunk:
    parent_id: str
    document_id: str
    text: str
    chunk_index: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ChildChunk:
    child_id: str
    parent_id: str
    document_id: str
    text: str
    chunk_index: int
    metadata: dict[str, Any]


def build_hierarchical_chunks(
    documents: list[dict[str, Any]],
    *,
    parent_chunk_size: int = 1200,
    child_chunk_size: int = 450,
    child_chunk_overlap: int = 100,
) -> tuple[list[ParentChunk], list[ChildChunk]]:
    if parent_chunk_size <= 0:
        raise ValueError("parent_chunk_size must be greater than 0.")
    if child_chunk_size <= 0:
        raise ValueError("child_chunk_size must be greater than 0.")
    if child_chunk_overlap < 0 or child_chunk_overlap >= child_chunk_size:
        raise ValueError("child_chunk_overlap must be smaller than child_chunk_size.")

    parent_chunks: list[ParentChunk] = []
    child_chunks: list[ChildChunk] = []
    for document in documents:
        document_id = str(document["document_id"])
        metadata = _base_metadata(document)
        for parent_index, parent_text in enumerate(
            _sliding_chunks(
                str(document["content"]),
                chunk_size=parent_chunk_size,
                overlap=0,
            )
        ):
            parent_id = f"{document_id}::parent::{parent_index:03}"
            parent = ParentChunk(
                parent_id=parent_id,
                document_id=document_id,
                text=parent_text,
                chunk_index=parent_index,
                metadata={
                    **metadata,
                    "parent_id": parent_id,
                    "parent_chunk_index": parent_index,
                },
            )
            parent_chunks.append(parent)

            for child_index, child_text in enumerate(
                _sliding_chunks(
                    parent_text,
                    chunk_size=child_chunk_size,
                    overlap=child_chunk_overlap,
                )
            ):
                child_id = f"{parent_id}::child::{child_index:03}"
                child_chunks.append(
                    ChildChunk(
                        child_id=child_id,
                        parent_id=parent_id,
                        document_id=document_id,
                        text=child_text,
                        chunk_index=child_index,
                        metadata={
                            **metadata,
                            "parent_id": parent_id,
                            "child_id": child_id,
                            "chunk_index": child_index,
                        },
                    )
                )

    return parent_chunks, child_chunks


def _sliding_chunks(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return [""]
    if len(normalized) <= chunk_size:
        return [normalized]

    chunks = []
    start = 0
    step = chunk_size - overlap
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end].strip())
        if end == len(normalized):
            break
        start += step
    return chunks


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _base_metadata(document: dict[str, Any]) -> dict[str, Any]:
    metadata_fields = (
        "document_id",
        "title",
        "source_type",
        "asset_type",
        "defect_type",
        "severity",
        "repair_method",
        "repair_outcome",
        "actual_duration_hours",
        "disruption",
        "authority_level",
    )
    return {
        field: document[field]
        for field in metadata_fields
        if field in document and document[field] is not None
    }
