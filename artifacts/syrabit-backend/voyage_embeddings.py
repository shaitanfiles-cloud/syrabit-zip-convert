"""
Voyage AI Embeddings Client
============================
Async HTTP wrapper around the Voyage AI embeddings API.

Why Voyage (over Gemini's gemini-embedding-001):
  * voyage-multilingual-2 natively understands Hindi, Bengali, Assamese, Bodo
    in the same vector space as English — critical for AHSEC/SEBA students
    querying in vernacular languages.
  * 1024 dimensions, 32K context window, top-tier MTEB scores.
  * input_type distinction (document vs. query) materially improves retrieval
    quality — Gemini's API doesn't expose this knob cleanly.
  * Stable rate limits (~300 RPM on the basic plan, no 429-storming).

Auth: VOYAGE_API_KEY environment variable (already wired in config.py).

Public surface:
  - DIMENSIONS              (int)  — dimensionality of returned vectors
  - DEFAULT_MODEL           (str)
  - is_configured()         (bool) — True when VOYAGE_API_KEY is set
  - embed_one(text, ...)    -> Optional[List[float]]
  - embed_batch(texts, ...) -> List[Optional[List[float]]]

Errors are caught and logged; callers receive None / [] so the broader
embedding pipeline can fall back to Gemini gracefully.
"""

import os
import asyncio
import logging
from typing import List, Optional

import httpx

logger = logging.getLogger("voyage_embeddings")

API_URL = "https://api.voyageai.com/v1/embeddings"
DEFAULT_MODEL = "voyage-multilingual-2"
DIMENSIONS = 1024
MAX_BATCH = 128
MAX_INPUT_CHARS = 30000

_TASK_TYPE_MAP = {
    "RETRIEVAL_DOCUMENT": "document",
    "RETRIEVAL_QUERY":    "query",
    "SEMANTIC_SIMILARITY": "document",
    "CLASSIFICATION":     "document",
    "CLUSTERING":         "document",
    "document":           "document",
    "query":              "query",
}

_http_client: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=15.0,
            http2=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


def is_configured() -> bool:
    return bool(os.environ.get("VOYAGE_API_KEY", "").strip())


def _normalize_input_type(task_type: str) -> Optional[str]:
    if not task_type:
        return None
    return _TASK_TYPE_MAP.get(task_type, "document")


async def embed_one(text: str, task_type: str = "RETRIEVAL_DOCUMENT",
                    model: str = DEFAULT_MODEL) -> Optional[List[float]]:
    """Embed a single string. Returns None on failure (so callers can fall back)."""
    if not text or not is_configured():
        return None
    vecs = await embed_batch([text], task_type=task_type, model=model)
    return vecs[0] if vecs else None


async def embed_batch(texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT",
                      model: str = DEFAULT_MODEL) -> List[Optional[List[float]]]:
    """Embed a list of strings. Always returns a list of the same length;
    individual entries are None when an item fails or is empty."""
    if not is_configured() or not texts:
        return [None] * len(texts)

    api_key = os.environ["VOYAGE_API_KEY"].strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    input_type = _normalize_input_type(task_type)

    out: List[Optional[List[float]]] = [None] * len(texts)
    client = _client()

    for chunk_start in range(0, len(texts), MAX_BATCH):
        chunk = texts[chunk_start: chunk_start + MAX_BATCH]
        non_empty_idx: List[int] = []
        cleaned: List[str] = []
        for offset, t in enumerate(chunk):
            if t and t.strip():
                non_empty_idx.append(offset)
                cleaned.append(t.strip()[:MAX_INPUT_CHARS])
        if not cleaned:
            continue

        body = {
            "input": cleaned,
            "model": model,
            "truncation": True,
        }
        if input_type:
            body["input_type"] = input_type

        try:
            resp = await client.post(API_URL, headers=headers, json=body)
            if resp.status_code == 401:
                logger.error("Voyage 401 — VOYAGE_API_KEY invalid or revoked. Falling back to Gemini for the rest of the call.")
                return out
            if resp.status_code == 429:
                logger.warning("Voyage 429 rate-limited. Backing off and falling back to Gemini for this batch.")
                continue
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("data", []):
                idx = item.get("index", 0)
                if 0 <= idx < len(non_empty_idx):
                    abs_idx = chunk_start + non_empty_idx[idx]
                    out[abs_idx] = item.get("embedding")
        except httpx.HTTPError as exc:
            logger.warning(f"Voyage embed batch failed (chunk @ {chunk_start}): {type(exc).__name__}: {exc}")
            continue
        except Exception as exc:
            logger.warning(f"Voyage embed unexpected error (chunk @ {chunk_start}): {exc}")
            continue

    return out


async def aclose():
    global _http_client
    if _http_client is not None:
        try:
            await _http_client.aclose()
        except Exception:
            pass
        _http_client = None
