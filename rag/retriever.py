from __future__ import annotations

import re
from collections import Counter
from typing import Any

from models import Citation


DEFECT_FILTER_ALIASES = {
    "leak": {"leak", "water_leak"},
    "water_leak": {"leak", "water_leak"},
}


class LocalRetriever:
    def __init__(self, documents: list[dict[str, Any]]):
        self.documents = documents

    def search(
        self,
        query: str,
        *,
        source_type: str | None = None,
        asset_type: str | None = None,
        defect_type: str | None = None,
        limit: int = 3,
    ) -> list[Citation]:
        query_terms = self._tokenize(query)
        scored: list[tuple[float, dict[str, Any]]] = []

        for document in self.documents:
            if source_type and document.get("source_type") != source_type:
                continue
            if asset_type and document.get("asset_type") not in {asset_type, "generic"}:
                continue
            if defect_type and document.get("defect_type") not in _defect_filter_values(defect_type):
                continue

            score = self._score(query_terms, document)
            if score > 0:
                scored.append((score, document))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            Citation(
                document_id=document["document_id"],
                title=document["title"],
                source_type=document["source_type"],
                excerpt=document["content"],
                score=round(score, 3),
            )
            for score, document in scored[:limit]
        ]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return next(
            (
                document
                for document in self.documents
                if document["document_id"] == document_id
            ),
            None,
        )

    def _score(self, query_terms: list[str], document: dict[str, Any]) -> float:
        text = " ".join(
            str(document.get(field, ""))
            for field in (
                "title",
                "source_type",
                "asset_type",
                "defect_type",
                "repair_method",
                "severity",
                "repair_outcome",
                "content",
            )
        )
        doc_terms = Counter(self._tokenize(text))
        overlap = sum(doc_terms[term] for term in query_terms)

        metadata_boost = 0.0
        for field in ("asset_type", "defect_type", "severity", "source_type"):
            if str(document.get(field, "")).lower() in query_terms:
                metadata_boost += 1.0

        return overlap + metadata_boost

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())


def _defect_filter_values(defect_type: str) -> set[str]:
    return DEFECT_FILTER_ALIASES.get(defect_type, {defect_type})
