from __future__ import annotations

from typing import Any, Protocol

from models import Citation


class KnowledgeRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        source_type: str | None = None,
        asset_type: str | None = None,
        defect_type: str | None = None,
        limit: int = 3,
    ) -> list[Citation]:
        ...

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        ...
