"""
retrievers.base — the abstract retriever contract.

Every concrete retriever (Cloudflare Vectorize, Vertex AI Vector Search,
future PgVector / Qdrant / etc.) implements this surface so the
upstream consumers (`syllabus_embedder`, ingestion scripts, the
benchmark harness, admin diagnostics) are backend-agnostic.

Match shape returned by `query()` and `get_by_ids()` mirrors the
existing Vectorize JSON contract so call-sites don't have to change:

    {
        "id":       str,
        "score":    float,                  # query() only
        "metadata": dict[str, Any],         # when return_metadata
        "values":   list[float],            # when return_values
    }
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Retriever(ABC):
    """ABC every vector-retrieval backend implements."""

    #: Human-readable backend name; used in stats payload + logs.
    name: str = "abstract"

    #: Embedding dimensionality the backing index expects.
    dimensions: int = 0

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True iff this backend has every credential / endpoint
        it needs to serve traffic. Callers SHOULD short-circuit when
        this returns False — every other method is allowed (but not
        required) to return empty / no-op responses in that state."""
        raise NotImplementedError

    @abstractmethod
    async def query(
        self,
        vector: list[float],
        top_k: int = 10,
        metadata_filter: Optional[dict[str, Any]] = None,
        return_values: bool = False,
        return_metadata: bool = True,
    ) -> list[dict[str, Any]]:
        """Nearest-neighbour search. Returns up to `top_k` matches
        ordered by descending similarity. See module docstring for
        the per-match dict shape."""
        raise NotImplementedError

    @abstractmethod
    async def upsert(self, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        """Insert-or-update vectors. Each input dict carries
        `{id: str, values: list[float], metadata: dict}`. Returns
        `{"upserted": int, "errors": list[str] (optional)}`."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, ids: list[str]) -> int:
        """Delete vectors by ID. Returns the number of IDs the backend
        accepted for deletion (best-effort — some backends return a
        mutation token rather than a count)."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        """Fetch vectors by ID. Missing IDs are silently skipped."""
        raise NotImplementedError

    @abstractmethod
    async def index_info(self) -> dict[str, Any]:
        """Operational metadata (vector count, last-mutation token, …).
        Returns `{}` when unsupported / unconfigured."""
        raise NotImplementedError

    @abstractmethod
    async def index_config(self) -> dict[str, Any]:
        """Static index configuration — at minimum
        `{name, dimensions, metric}`. Returns `{}` when unsupported /
        unconfigured."""
        raise NotImplementedError

    async def close(self) -> None:
        """Release any pooled resources (HTTP clients, gRPC channels).
        Default implementation is a no-op so retrievers without long-
        lived state can ignore it."""
        return None
