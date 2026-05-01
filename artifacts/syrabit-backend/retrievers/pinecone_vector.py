"""
retrievers.pinecone_vector — Pinecone serverless vector store adapter.

Replaces MongoDB Atlas $vectorSearch for chunk semantic retrieval.
Uses Pinecone's REST API directly (no SDK needed) for both index
management (control plane) and vector queries (data plane).

Architecture
------------
* Vector IDs: MongoDB chunk `_id` (str) → Pinecone vector ID.
* Metadata stored per vector: subject_id, chapter_id, board_id,
  chapter_title, topic_name, embedding_model.
* Metadata filters use Pinecone's `$eq` syntax (compatible with the
  existing Atlas `$eq` semantics used by callers).
* numCandidates equivalent: Pinecone's HNSW/IVF indexes are ANN —
  top_k is the only tuning knob needed.

Environment variables
---------------------
  PINECONE_KEY         Pinecone API key for index operations.
                       Falls back to PINECONE_API_KEY if not set.
  PINECONE_INDEX       Index name (default: "syrabit-ahsec").
  PINECONE_INDEX_DIMS  Embedding dimensions (default: 1024).
  PINECONE_INDEX_METRIC  Similarity metric (default: "cosine").

Index creation (runs once via ensure_pinecone_index())
------------------------------------------------------
  Serverless spec: AWS us-east-1, 1024-dim, cosine.
  Safe to call every boot — no-op if the index already exists.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

import httpx

from .base import Retriever

logger = logging.getLogger("retrievers.pinecone_vector")

# ── Config ────────────────────────────────────────────────────────────────────
_API_KEY = (
    os.environ.get("PINECONE_KEY", "").strip()
    or os.environ.get("PINECONE_API_KEY", "").strip()
)
_INDEX_NAME = os.environ.get("PINECONE_INDEX", "syrabit-ahsec").strip() or "syrabit-ahsec"
_DIMENSIONS  = int(os.environ.get("PINECONE_INDEX_DIMS", "1024") or "1024")
_METRIC      = os.environ.get("PINECONE_INDEX_METRIC", "cosine").strip() or "cosine"

_CONTROL_BASE = "https://api.pinecone.io"
_API_VERSION  = "2024-10"
_TIMEOUT      = 12.0

# Cached index host (fetched once after ensure_pinecone_index)
_INDEX_HOST: Optional[str] = None

# ── Shared HTTP helpers ────────────────────────────────────────────────────────

def _ctrl_headers() -> dict:
    return {
        "Api-Key": _API_KEY,
        "Content-Type": "application/json",
        "X-Pinecone-API-Version": _API_VERSION,
    }


async def _get_index_host() -> Optional[str]:
    """Describe the index and return its host URL. Cached after first call."""
    global _INDEX_HOST
    if _INDEX_HOST:
        return _INDEX_HOST
    if not _API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_CONTROL_BASE}/indexes/{_INDEX_NAME}",
                headers=_ctrl_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                host = data.get("host", "")
                if host:
                    if not host.startswith("https://"):
                        host = f"https://{host}"
                    _INDEX_HOST = host
                    logger.info(
                        "[pinecone_vector] Index '%s' host resolved: %s",
                        _INDEX_NAME, _INDEX_HOST,
                    )
                    return _INDEX_HOST
            logger.warning(
                "[pinecone_vector] describe index HTTP %d: %s",
                resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        logger.warning("[pinecone_vector] _get_index_host failed: %s", exc)
    return None


def _data_headers() -> dict:
    return {
        "Api-Key": _API_KEY,
        "Content-Type": "application/json",
        "X-Pinecone-API-Version": _API_VERSION,
    }


# ── Retriever class ────────────────────────────────────────────────────────────

class PineconeVectorRetriever(Retriever):
    """Pinecone serverless–backed retriever (REST data-plane API)."""

    name = "pinecone_vector"

    @property
    def dimensions(self) -> int:
        return _DIMENSIONS

    def is_configured(self) -> bool:
        return bool(_API_KEY)

    async def query(
        self,
        vector: list[float],
        top_k: int = 10,
        metadata_filter: Optional[dict[str, Any]] = None,
        return_values: bool = False,
        return_metadata: bool = True,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            logger.warning("PineconeVectorRetriever: not configured — returning empty")
            return []

        host = await _get_index_host()
        if not host:
            logger.warning("PineconeVectorRetriever: index host unknown — returning empty")
            return []

        payload: dict[str, Any] = {
            "vector": vector,
            "topK": top_k,
            "includeMetadata": return_metadata,
            "includeValues": return_values,
        }
        if metadata_filter:
            payload["filter"] = metadata_filter

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{host}/query",
                    json=payload,
                    headers=_data_headers(),
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.error("PineconeVectorRetriever.query failed: %s", exc)
            return []

        data = resp.json()
        matches = data.get("matches") or []
        logger.debug(
            "[pinecone_vector] query top_k=%d → %d matches in %.0fms",
            top_k, len(matches), (time.perf_counter() - t0) * 1000,
        )

        results = []
        for m in matches:
            entry: dict[str, Any] = {
                "id": m.get("id", ""),
                "score": float(m.get("score", 0.0)),
                "metadata": m.get("metadata") or {},
            }
            if return_values:
                entry["values"] = m.get("values", [])
            results.append(entry)
        return results

    async def upsert(self, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        """Upsert vectors to Pinecone.

        Each input dict must match:
          { "id": str, "values": list[float], "metadata": dict }
        """
        if not vectors:
            return {"upserted": 0}
        if not self.is_configured():
            return {"upserted": 0, "errors": ["not configured"]}

        host = await _get_index_host()
        if not host:
            return {"upserted": 0, "errors": ["index host unknown"]}

        # Pinecone upsert batches up to 100 vectors per request
        batch_size = 100
        total_upserted = 0
        errors = []

        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            payload = {
                "vectors": [
                    {
                        "id": v["id"],
                        "values": v.get("values", []),
                        **({"metadata": v["metadata"]} if v.get("metadata") else {}),
                    }
                    for v in batch
                ]
            }
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.post(
                        f"{host}/vectors/upsert",
                        json=payload,
                        headers=_data_headers(),
                    )
                    resp.raise_for_status()
                data = resp.json()
                total_upserted += int(data.get("upsertedCount", len(batch)))
            except Exception as exc:
                msg = str(exc)[:200]
                logger.error("PineconeVectorRetriever.upsert batch failed: %s", msg)
                errors.append(msg)

        result: dict[str, Any] = {"upserted": total_upserted}
        if errors:
            result["errors"] = errors
        return result

    async def delete(self, ids: list[str]) -> int:
        if not ids:
            return 0
        if not self.is_configured():
            return 0

        host = await _get_index_host()
        if not host:
            return 0

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    f"{host}/vectors/delete",
                    json={"ids": ids},
                    headers=_data_headers(),
                )
                resp.raise_for_status()
            return len(ids)
        except Exception as exc:
            logger.error("PineconeVectorRetriever.delete failed: %s", exc)
            return 0

    async def index_info(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"error": "not configured"}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    f"{_CONTROL_BASE}/indexes/{_INDEX_NAME}",
                    headers=_ctrl_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "backend": "pinecone_serverless",
                        "index_name": _INDEX_NAME,
                        "dimensions": _DIMENSIONS,
                        "metric": _METRIC,
                        "host": data.get("host", ""),
                        "status": data.get("status", {}),
                    }
                return {"error": f"HTTP {resp.status_code}: {resp.text[:100]}"}
        except Exception as exc:
            return {"error": str(exc)}

    async def index_config(self) -> dict[str, Any]:
        return {
            "name": _INDEX_NAME,
            "dimensions": _DIMENSIONS,
            "metric": _METRIC,
            "backend": "pinecone_serverless",
        }

    async def close(self) -> None:
        pass


# ── Index bootstrap helper ─────────────────────────────────────────────────────

async def ensure_pinecone_index() -> dict[str, Any]:
    """Create the Pinecone serverless index if it does not already exist.

    Spec: AWS us-east-1, 1024-dim, cosine, serverless.
    Safe to call on every boot — silently skips if already exists.
    Returns a status dict for logging / admin diagnostics.
    """
    global _INDEX_HOST

    if not _API_KEY:
        return {"ok": False, "reason": "PINECONE_KEY not set"}

    # Check if index already exists
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_CONTROL_BASE}/indexes/{_INDEX_NAME}",
                headers=_ctrl_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                host = data.get("host", "")
                if host and not host.startswith("https://"):
                    host = f"https://{host}"
                _INDEX_HOST = host or None
                logger.info(
                    "Pinecone index '%s' already exists (host=%s)",
                    _INDEX_NAME, _INDEX_HOST,
                )
                return {
                    "ok": True,
                    "created": False,
                    "index": _INDEX_NAME,
                    "note": "already exists",
                    "host": _INDEX_HOST,
                }
    except Exception as exc:
        logger.warning("ensure_pinecone_index: describe failed: %s", exc)

    # Create the index
    payload = {
        "name": _INDEX_NAME,
        "dimension": _DIMENSIONS,
        "metric": _METRIC,
        "spec": {
            "serverless": {
                "cloud": "aws",
                "region": "us-east-1",
            }
        },
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_CONTROL_BASE}/indexes",
                json=payload,
                headers=_ctrl_headers(),
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                host = data.get("host", "")
                if host and not host.startswith("https://"):
                    host = f"https://{host}"
                _INDEX_HOST = host or None
                logger.info(
                    "Pinecone index '%s' created (host=%s)",
                    _INDEX_NAME, _INDEX_HOST,
                )
                return {
                    "ok": True,
                    "created": True,
                    "index": _INDEX_NAME,
                    "host": _INDEX_HOST,
                }
            elif resp.status_code == 409:
                logger.info("Pinecone index '%s' already exists (409) — skipping", _INDEX_NAME)
                return {"ok": True, "created": False, "index": _INDEX_NAME, "note": "already exists"}
            else:
                msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning("ensure_pinecone_index create failed: %s", msg)
                return {"ok": False, "reason": msg}
    except Exception as exc:
        msg = str(exc)
        logger.warning("ensure_pinecone_index failed (non-fatal): %s", msg)
        return {"ok": False, "reason": msg}
