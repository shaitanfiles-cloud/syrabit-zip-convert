"""
providers.voyage — Voyage AI embeddings and reranking (direct API).

Calls api.voyageai.com/v1 directly. Cloudflare AI Gateway does not support
Voyage AI as a named provider (returns code:2008 "Invalid provider"), so all
requests bypass the gateway and go straight to Voyage AI.

API format (OpenAI-style):
  POST https://api.voyageai.com/v1/embeddings
  POST https://api.voyageai.com/v1/rerank
  Authorization: Bearer <MONGODB_MODEL_API_KEY>

To get a valid key: https://dash.voyageai.com → API Keys (key looks like pa-...)

Embedding models (1024-dim — matches our Atlas Vector Search index):
  voyage-3-large        — best quality, multilingual, general purpose
  voyage-3              — balanced quality/speed
  voyage-3-lite         — fastest, lightest

Reranking models:
  rerank-2              — highest quality reranker
  rerank-2-lite         — fast, efficient reranker (default)

Configuration:
  MONGODB_MODEL_API_KEY   — Voyage AI API key from dash.voyageai.com (required)
  VOYAGE_BASE_URL         — override endpoint (default: https://api.voyageai.com/v1)
  VOYAGE_EMBED_MODEL      — embedding model (default: voyage-3-large)
  VOYAGE_RERANK_MODEL     — reranking model (default: rerank-2-lite)
  VOYAGE_EMBED_DIMS       — expected output dimensions (default: 1024)
  VOYAGE_TIMEOUT_S        — HTTP timeout in seconds (default: 15)
  VOYAGE_RERANK_TOP_K     — how many top results to keep after rerank (default: 5)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, List, Optional

import httpx

logger = logging.getLogger("providers.voyage")

_API_KEY      = (
    os.environ.get("VOYAGE_API_KEY", "").strip()
    or os.environ.get("MONGODB_MODEL_API_KEY", "").strip()
)
_EMBED_MODEL  = os.environ.get("VOYAGE_EMBED_MODEL",  "voyage-3-large").strip() or "voyage-3-large"
_RERANK_MODEL = os.environ.get("VOYAGE_RERANK_MODEL", "rerank-2-lite").strip()  or "rerank-2-lite"
_EMBED_DIMS   = int(os.environ.get("VOYAGE_EMBED_DIMS", "1024") or "1024")
_TIMEOUT      = float(os.environ.get("VOYAGE_TIMEOUT_S", "15") or "15")
_RERANK_TOP_K = int(os.environ.get("VOYAGE_RERANK_TOP_K", "5") or "5")

# ── Base URL: explicit override → direct voyageai.com ────────────────────────
# Note: Cloudflare AI Gateway does not support Voyage AI as a named provider
# (returns code:2008 "Invalid provider"). All calls go direct to voyageai.com.
_EXPLICIT_BASE = os.environ.get("VOYAGE_BASE_URL", "").strip().rstrip("/")
_CF_GW_TOKEN   = os.environ.get("CF_AI_GATEWAY_TOKEN", "").strip()
_via_gateway   = False

_BASE_URL = _EXPLICIT_BASE if _EXPLICIT_BASE else "https://api.voyageai.com/v1"

ENABLED: bool = bool(_API_KEY)

_key_source = (
    "VOYAGE_API_KEY" if os.environ.get("VOYAGE_API_KEY", "").strip()
    else "MONGODB_MODEL_API_KEY" if os.environ.get("MONGODB_MODEL_API_KEY", "").strip()
    else None
)

if ENABLED:
    logger.info(
        "Voyage AI ready — embed=%s rerank=%s dims=%d base=%s (key from %s)",
        _EMBED_MODEL, _RERANK_MODEL, _EMBED_DIMS, _BASE_URL, _key_source,
    )
else:
    logger.info(
        "Voyage AI disabled (VOYAGE_API_KEY / MONGODB_MODEL_API_KEY not set) — "
        "using Workers AI embeddings and CF reranker"
    )


def _headers() -> dict:
    h: dict = {"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"}
    if _via_gateway and _CF_GW_TOKEN:
        h["cf-aig-authorization"] = f"Bearer {_CF_GW_TOKEN}"
    return h


# ── Shared async client (module-level, reused across requests) ──────────────
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers=_headers(),
            timeout=httpx.Timeout(_TIMEOUT),
            http2=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


# ── Embeddings ───────────────────────────────────────────────────────────────

async def embed(
    texts: List[str],
    *,
    input_type: str = "document",  # "query" | "document"
    model: Optional[str] = None,
) -> List[List[float]]:
    """Return a list of embedding vectors, one per input text.

    ``input_type`` should be ``"query"`` for user questions and
    ``"document"`` for content being indexed — Voyage AI uses this hint
    to apply query/document asymmetric fine-tuning.

    Returns an empty list on error so callers can fall back gracefully.
    """
    if not ENABLED:
        return []
    if not texts:
        return []

    mdl = model or _EMBED_MODEL
    t0 = time.perf_counter()
    try:
        client = _get_client()
        response = await client.post(
            "/embeddings",
            json={"model": mdl, "input": texts, "input_type": input_type},
        )
        response.raise_for_status()
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
        latency = round((time.perf_counter() - t0) * 1000)
        logger.debug("Voyage embed: %d texts, model=%s, %dms", len(texts), mdl, latency)
        return vectors
    except Exception as exc:
        logger.warning("Voyage embed failed (non-fatal): %s", exc)
        return []


async def embed_query(text: str, model: Optional[str] = None) -> List[float]:
    """Embed a single query string. Returns [] on error."""
    results = await embed([text], input_type="query", model=model)
    return results[0] if results else []


# ── Reranking ────────────────────────────────────────────────────────────────

async def rerank(
    query: str,
    documents: List[str],
    *,
    top_k: Optional[int] = None,
    model: Optional[str] = None,
    return_documents: bool = False,
) -> List[dict]:
    """Rerank ``documents`` by relevance to ``query``.

    Returns a list of dicts ordered by descending relevance:
      [{"index": int, "relevance_score": float, "document": str (if return_documents)}, ...]

    Returns [] on error so callers fall back to the original ordering.
    """
    if not ENABLED:
        return []
    if not documents or not query:
        return []

    mdl = model or _RERANK_MODEL
    k = top_k if top_k is not None else min(_RERANK_TOP_K, len(documents))
    t0 = time.perf_counter()
    try:
        client = _get_client()
        payload: dict[str, Any] = {
            "model": mdl,
            "query": query,
            "documents": documents,
            "top_k": k,
            "return_documents": return_documents,
        }
        response = await client.post("/rerank", json=payload)
        response.raise_for_status()
        data = response.json()
        results = data.get("data", [])
        latency = round((time.perf_counter() - t0) * 1000)
        logger.debug(
            "Voyage rerank: %d docs → top %d, model=%s, %dms",
            len(documents), k, mdl, latency,
        )
        return results
    except Exception as exc:
        logger.warning("Voyage rerank failed (non-fatal, using original order): %s", exc)
        return []


async def rerank_items(
    query: str,
    items: List[Any],
    text_fn,
    *,
    top_k: Optional[int] = None,
    model: Optional[str] = None,
) -> List[Any]:
    """Rerank a list of arbitrary items using a text extractor.

    ``text_fn(item) -> str`` extracts the text to score against ``query``.
    Falls back to the original list if Voyage AI is unavailable or errors.

    Example:
        reranked = await rerank_items(query, chapters, lambda c: c["content"])
    """
    if not ENABLED or not items:
        return items

    texts = [text_fn(item) for item in items]
    ranked = await rerank(query, texts, top_k=top_k or len(items), model=model)

    if not ranked:
        return items[:top_k] if top_k else items

    reranked = [items[r["index"]] for r in ranked if r["index"] < len(items)]
    if top_k:
        reranked = reranked[:top_k]
    return reranked


# ── Health ───────────────────────────────────────────────────────────────────

async def health_check() -> dict:
    if not ENABLED:
        return {"ok": False, "reason": "MONGODB_MODEL_API_KEY not set"}
    t0 = time.perf_counter()
    try:
        vectors = await embed(["health check"], input_type="query")
        if not vectors or len(vectors[0]) != _EMBED_DIMS:
            return {"ok": False, "reason": f"unexpected dims: {len(vectors[0]) if vectors else 0}"}
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "model": _EMBED_MODEL,
            "dims": len(vectors[0]),
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
