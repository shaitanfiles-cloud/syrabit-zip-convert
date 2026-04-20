"""
retrievers.vectorize — Cloudflare Vectorize adapter.

Wraps the existing module-level `vectorize_client` so the rest of the
codebase can call it through the `Retriever` ABC instead of via
top-level functions. The wrapper is intentionally thin — every method
is a one-line delegation — because the production module already
ships with the auth-failure circuit breaker, alerting, batching, and
retry logic we want to preserve.
"""

from __future__ import annotations

from typing import Any, Optional

import vectorize_client  # noqa: F401  — module-level state matters

from .base import Retriever


class VectorizeRetriever(Retriever):
    name = "vectorize"

    @property
    def dimensions(self) -> int:  # type: ignore[override]
        return vectorize_client.VECTORIZE_DIMENSIONS

    def is_configured(self) -> bool:
        return vectorize_client.is_configured()

    async def query(
        self,
        vector: list[float],
        top_k: int = 10,
        metadata_filter: Optional[dict[str, Any]] = None,
        return_values: bool = False,
        return_metadata: bool = True,
    ) -> list[dict[str, Any]]:
        return await vectorize_client.query_vectors(
            vector=vector,
            top_k=top_k,
            metadata_filter=metadata_filter,
            return_values=return_values,
            return_metadata=return_metadata,
        )

    async def upsert(self, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        return await vectorize_client.upsert_vectors(vectors)

    async def delete(self, ids: list[str]) -> int:
        return await vectorize_client.delete_vectors(ids)

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        return await vectorize_client.get_vectors_by_ids(ids)

    async def index_info(self) -> dict[str, Any]:
        return await vectorize_client.get_index_info()

    async def index_config(self) -> dict[str, Any]:
        cfg = await vectorize_client.get_index_config()
        # Always surface the canonical name so callers don't have to
        # remember to read it from the module global.
        if cfg and "name" not in cfg:
            cfg = {**cfg, "name": vectorize_client.VECTORIZE_INDEX_NAME}
        elif not cfg:
            cfg = {
                "name": vectorize_client.VECTORIZE_INDEX_NAME,
                "dimensions": vectorize_client.VECTORIZE_DIMENSIONS,
                "metric": "cosine",
            }
        return cfg

    async def close(self) -> None:
        await vectorize_client.close()
