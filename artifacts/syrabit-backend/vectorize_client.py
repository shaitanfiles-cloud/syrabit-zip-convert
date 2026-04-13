"""
Cloudflare Vectorize Client
============================
Async wrapper around the official Cloudflare Python SDK for upserting,
querying, and managing vectors in the `syllabus-index` Vectorize index.

Environment variables required:
  CLOUDFLARE_API_TOKEN  — API token with Vectorize read/write permissions
  CLOUDFLARE_ACCOUNT_ID — Cloudflare account ID

Setup (run once):
  wrangler vectorize create syllabus-index --dimensions=768 --metric=cosine
"""

import json
import os
import logging
from typing import Optional

logger = logging.getLogger("vectorize_client")

VECTORIZE_INDEX_NAME = "syllabus-index"
VECTORIZE_DIMENSIONS = 768
VECTORIZE_BATCH_SIZE = 20

_cf_client = None


def _get_cf_client():
    global _cf_client
    if _cf_client is None:
        from cloudflare import AsyncCloudflare
        token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("CLOUDFLARE_API_TOKEN must be set")
        _cf_client = AsyncCloudflare(api_token=token)
    return _cf_client


def _account_id() -> str:
    aid = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not aid:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID must be set")
    return aid


def is_configured() -> bool:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    return bool(token and account)


async def upsert_vectors(vectors: list[dict]) -> dict:
    """Upsert vectors to Vectorize. Each dict must have: id, values, metadata.

    The SDK upsert method accepts ndjson as a string body.
    We batch internally at VECTORIZE_BATCH_SIZE.
    """
    cf = _get_cf_client()
    account_id = _account_id()

    total_upserted = 0
    errors = []

    for i in range(0, len(vectors), VECTORIZE_BATCH_SIZE):
        batch = vectors[i : i + VECTORIZE_BATCH_SIZE]
        ndjson_lines = []
        for v in batch:
            ndjson_lines.append(json.dumps({
                "id": v["id"],
                "values": v["values"],
                "metadata": v.get("metadata", {}),
            }))
        ndjson_body = "\n".join(ndjson_lines)

        try:
            result = await cf.vectorize.indexes.upsert(
                index_name=VECTORIZE_INDEX_NAME,
                account_id=account_id,
                body=ndjson_body,
            )
            total_upserted += len(batch)
        except Exception as exc:
            logger.warning(f"Vectorize upsert batch failed: {exc}")
            errors.append(f"batch {i // VECTORIZE_BATCH_SIZE}: {exc}")

    result_dict = {"upserted": total_upserted}
    if errors:
        result_dict["errors"] = errors
    return result_dict


async def query_vectors(
    vector: list[float],
    top_k: int = 10,
    metadata_filter: Optional[dict] = None,
    return_values: bool = False,
    return_metadata: bool = True,
) -> list[dict]:
    """Query Vectorize for nearest neighbors. Returns list of {id, score, metadata}."""
    cf = _get_cf_client()
    account_id = _account_id()

    try:
        kwargs = {
            "index_name": VECTORIZE_INDEX_NAME,
            "account_id": account_id,
            "vector": vector,
            "top_k": top_k,
            "return_values": return_values,
            "return_metadata": "all" if return_metadata else "none",
        }
        if metadata_filter:
            kwargs["filter"] = metadata_filter

        result = await cf.vectorize.indexes.query(**kwargs)
        if result is None:
            return []

        matches = []
        for m in (result.matches or []):
            entry = {"id": m.id, "score": m.score}
            if hasattr(m, "metadata") and m.metadata:
                entry["metadata"] = dict(m.metadata) if not isinstance(m.metadata, dict) else m.metadata
            if hasattr(m, "values") and m.values:
                entry["values"] = list(m.values)
            matches.append(entry)
        return matches
    except Exception as exc:
        logger.warning(f"Vectorize query exception: {exc}")
        return []


async def delete_vectors(ids: list[str]) -> int:
    """Delete vectors by ID. Returns count of IDs submitted for deletion."""
    if not ids:
        return 0
    cf = _get_cf_client()
    account_id = _account_id()

    deleted = 0
    for i in range(0, len(ids), 1000):
        batch = ids[i : i + 1000]
        try:
            await cf.vectorize.indexes.delete_by_ids(
                index_name=VECTORIZE_INDEX_NAME,
                account_id=account_id,
                ids=batch,
            )
            deleted += len(batch)
        except Exception as exc:
            logger.warning(f"Vectorize delete exception: {exc}")

    return deleted


async def get_vectors_by_ids(ids: list[str]) -> list[dict]:
    """Retrieve vectors by their IDs."""
    if not ids:
        return []
    cf = _get_cf_client()
    account_id = _account_id()

    try:
        result = await cf.vectorize.indexes.get_by_ids(
            index_name=VECTORIZE_INDEX_NAME,
            account_id=account_id,
            ids=ids,
        )
        if result is None:
            return []
        raw_list = result if isinstance(result, list) else [result]
        normalized = []
        for item in raw_list:
            if isinstance(item, dict):
                normalized.append(item)
            elif hasattr(item, "id"):
                entry = {"id": item.id}
                if hasattr(item, "values") and item.values:
                    entry["values"] = list(item.values)
                if hasattr(item, "metadata") and item.metadata:
                    entry["metadata"] = dict(item.metadata) if not isinstance(item.metadata, dict) else item.metadata
                normalized.append(entry)
        return normalized
    except Exception as exc:
        logger.warning(f"Vectorize get_by_ids exception: {exc}")
        return []


async def get_index_info() -> dict:
    """Get index metadata (dimensions, vector count, etc.)."""
    cf = _get_cf_client()
    account_id = _account_id()

    try:
        info = await cf.vectorize.indexes.info(
            index_name=VECTORIZE_INDEX_NAME,
            account_id=account_id,
        )
        if info is None:
            return {}
        return {
            "dimensions": info.dimensions,
            "vector_count": info.vector_count,
            "processed_up_to_mutation": info.processed_up_to_mutation,
            "processed_up_to_datetime": str(info.processed_up_to_datetime) if info.processed_up_to_datetime else None,
        }
    except Exception as exc:
        logger.warning(f"Vectorize index info exception: {exc}")
        return {}


async def get_index_config() -> dict:
    """Get index configuration (name, dimensions, metric)."""
    cf = _get_cf_client()
    account_id = _account_id()

    try:
        result = await cf.vectorize.indexes.get(
            index_name=VECTORIZE_INDEX_NAME,
            account_id=account_id,
        )
        if result is None:
            return {}
        return {
            "name": result.name if hasattr(result, "name") else VECTORIZE_INDEX_NAME,
            "dimensions": result.config.dimensions if hasattr(result, "config") and result.config else VECTORIZE_DIMENSIONS,
            "metric": result.config.metric if hasattr(result, "config") and result.config else "cosine",
        }
    except Exception as exc:
        logger.warning(f"Vectorize index config exception: {exc}")
        return {}


async def close():
    global _cf_client
    if _cf_client is not None:
        try:
            await _cf_client.close()
        except Exception:
            pass
        _cf_client = None
