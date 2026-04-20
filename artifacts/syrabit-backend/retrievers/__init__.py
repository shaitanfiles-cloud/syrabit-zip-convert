"""
retrievers — pluggable vector-retrieval backend for Syrabit RAG.

Two implementations live behind a tiny ABC (`base.Retriever`):

  * VectorizeRetriever — Cloudflare Vectorize (production today, default)
  * VertexVectorSearchRetriever — Google Vertex AI Vector Search (A/B candidate)

Selection happens via `factory.get_retriever()` which inspects (in order):

  1. The runtime override set through the admin UI / API
     (db.settings document `id="retriever_config"`, field `active`).
  2. The `RAG_RETRIEVER` environment variable (`vectorize` | `vertex`).
  3. Default: `vectorize`.

Callers (currently `syllabus_embedder.py`, `routes/admin_advanced.py`,
`scripts/ingest_vertex_index.py`, `bench/retriever_bench.py`) MUST go
through `get_retriever()` rather than importing `vectorize_client`
directly so the swap is single-pointed.
"""

from .base import Retriever
from .factory import (
    get_retriever,
    get_retriever_by_name,
    list_available_retrievers,
    invalidate_retriever_cache,
    get_active_retriever_name,
    set_active_retriever,
    DEFAULT_RETRIEVER,
)

__all__ = [
    "Retriever",
    "get_retriever",
    "get_retriever_by_name",
    "list_available_retrievers",
    "invalidate_retriever_cache",
    "get_active_retriever_name",
    "set_active_retriever",
    "DEFAULT_RETRIEVER",
]
