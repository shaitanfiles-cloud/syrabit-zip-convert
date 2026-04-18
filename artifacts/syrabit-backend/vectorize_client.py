"""
Cloudflare Vectorize Client
============================
Async wrapper around the official Cloudflare Python SDK for upserting,
querying, and managing vectors in the `syllabus-index` Vectorize index.

Environment variables required:
  CLOUDFLARE_API_TOKEN  — API token with Vectorize read/write permissions
  CLOUDFLARE_ACCOUNT_ID — Cloudflare account ID

Setup (run once):
  wrangler vectorize create syllabus-index-v2 --dimensions=1024 --metric=cosine
  wrangler vectorize create-metadata-index syllabus-index-v2 --property-name=subject_id --type=string
  wrangler vectorize create-metadata-index syllabus-index-v2 --property-name=chapter_id --type=string
  wrangler vectorize create-metadata-index syllabus-index-v2 --property-name=level --type=string
  wrangler vectorize create-metadata-index syllabus-index-v2 --property-name=board --type=string

Index name is overridable via VECTORIZE_INDEX_NAME env var (rollback: set to
"syllabus-index" to use the legacy 768-dim Gemini index).
"""

import json
import os
import logging
import time
from typing import Optional

logger = logging.getLogger("vectorize_client")

VECTORIZE_INDEX_NAME = os.environ.get("VECTORIZE_INDEX_NAME", "syllabus-index-v2").strip() or "syllabus-index-v2"
VECTORIZE_DIMENSIONS = 1024
VECTORIZE_BATCH_SIZE = 20

# ── Auth-failure circuit breaker ─────────────────────────────────────────────
# When the Cloudflare API token is invalid or missing the Vectorize scope, the
# API returns HTTP 401 on every call. Without backoff this blows up the logs
# (one 401 per upsert + one per get_by_ids every ~10s from the embedder loop)
# and burns CF rate-limit budget. Once we see a few consecutive 401s we
# short-circuit *all* outgoing calls for AUTH_BREAKER_COOLDOWN seconds, log
# a single WARNING summarising the breaker state, and silently return empty
# results. The breaker auto-resets after the cooldown so a fixed token starts
# working again without a process restart.
AUTH_BREAKER_THRESHOLD = 3
AUTH_BREAKER_COOLDOWN = 300.0  # 5 minutes
_auth_fail_count = 0
_auth_breaker_until = 0.0
_auth_breaker_logged = False


def _record_auth_failure() -> None:
    global _auth_fail_count, _auth_breaker_until, _auth_breaker_logged
    _auth_fail_count += 1
    if _auth_fail_count >= AUTH_BREAKER_THRESHOLD and time.monotonic() >= _auth_breaker_until:
        _auth_breaker_until = time.monotonic() + AUTH_BREAKER_COOLDOWN
        if not _auth_breaker_logged:
            logger.warning(
                "Vectorize auth-failure circuit breaker tripped after %d consecutive 401s "
                "— suppressing all calls for %.0fs. Check CLOUDFLARE_API_TOKEN scope (needs Vectorize:Edit).",
                _auth_fail_count, AUTH_BREAKER_COOLDOWN,
            )
            _auth_breaker_logged = True


def _record_success() -> None:
    global _auth_fail_count, _auth_breaker_until, _auth_breaker_logged
    if _auth_fail_count or _auth_breaker_until or _auth_breaker_logged:
        logger.info("Vectorize auth recovered — resetting circuit breaker.")
    _auth_fail_count = 0
    _auth_breaker_until = 0.0
    _auth_breaker_logged = False


def _breaker_open() -> bool:
    return time.monotonic() < _auth_breaker_until


def _is_auth_error(exc: Exception) -> bool:
    msg = str(exc)
    return "401" in msg or "Authentication error" in msg or "Unauthorized" in msg


def auth_breaker_status() -> dict:
    """Expose breaker state for /admin diagnostics."""
    remaining = max(0.0, _auth_breaker_until - time.monotonic())
    return {
        "open": remaining > 0,
        "consecutive_failures": _auth_fail_count,
        "cooldown_seconds_remaining": int(remaining),
        "threshold": AUTH_BREAKER_THRESHOLD,
        "cooldown_total_seconds": int(AUTH_BREAKER_COOLDOWN),
    }


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

    Uses the Cloudflare REST API directly since the Python SDK has ndjson
    encoding issues. We batch internally at VECTORIZE_BATCH_SIZE.
    """
    import httpx

    if _breaker_open():
        return {"upserted": 0, "errors": ["auth_breaker_open"]}

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = _account_id()

    total_upserted = 0
    errors = []

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/vectorize/v2/indexes/{VECTORIZE_INDEX_NAME}/upsert"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-ndjson",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(vectors), VECTORIZE_BATCH_SIZE):
            batch = vectors[i : i + VECTORIZE_BATCH_SIZE]
            ndjson_lines = []
            for v in batch:
                ndjson_lines.append(json.dumps({
                    "id": v["id"],
                    "values": v["values"],
                    "metadata": v.get("metadata", {}),
                }, ensure_ascii=False))
            ndjson_body = "\n".join(ndjson_lines)

            try:
                resp = await client.post(url, content=ndjson_body.encode("utf-8"), headers=headers)
                resp.raise_for_status()
                total_upserted += len(batch)
                _record_success()
            except Exception as exc:
                if _is_auth_error(exc):
                    _record_auth_failure()
                    if _breaker_open():
                        # Don't keep retrying remaining batches once tripped.
                        errors.append("auth_breaker_open")
                        break
                else:
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
    if _breaker_open():
        return []
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
        _record_success()
        return matches
    except Exception as exc:
        if _is_auth_error(exc):
            _record_auth_failure()
        else:
            logger.warning(f"Vectorize query exception: {exc}")
        return []


async def delete_vectors(ids: list[str]) -> int:
    """Delete vectors by ID. Returns count of IDs submitted for deletion."""
    if not ids:
        return 0
    if _breaker_open():
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
            _record_success()
        except Exception as exc:
            if _is_auth_error(exc):
                _record_auth_failure()
                if _breaker_open():
                    break
            else:
                logger.warning(f"Vectorize delete exception: {exc}")

    return deleted


async def get_vectors_by_ids(ids: list[str]) -> list[dict]:
    """Retrieve vectors by their IDs. Batches at 20 IDs per call (CF limit)."""
    if not ids:
        return []
    if _breaker_open():
        return []
    cf = _get_cf_client()
    account_id = _account_id()

    _BATCH = 20
    normalized = []
    for i in range(0, len(ids), _BATCH):
        batch_ids = ids[i : i + _BATCH]
        try:
            result = await cf.vectorize.indexes.get_by_ids(
                index_name=VECTORIZE_INDEX_NAME,
                account_id=account_id,
                ids=batch_ids,
            )
            _record_success()
            if result is None:
                continue
            raw_list = result if isinstance(result, list) else [result]
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
        except Exception as exc:
            if _is_auth_error(exc):
                _record_auth_failure()
                if _breaker_open():
                    break
            else:
                logger.warning(f"Vectorize get_by_ids exception: {exc}")
    return normalized


async def get_index_info() -> dict:
    """Get index metadata (dimensions, vector count, etc.)."""
    if _breaker_open():
        return {}
    cf = _get_cf_client()
    account_id = _account_id()

    try:
        info = await cf.vectorize.indexes.info(
            index_name=VECTORIZE_INDEX_NAME,
            account_id=account_id,
        )
        _record_success()
        if info is None:
            return {}
        return {
            "dimensions": info.dimensions,
            "vector_count": info.vector_count,
            "processed_up_to_mutation": info.processed_up_to_mutation,
            "processed_up_to_datetime": str(info.processed_up_to_datetime) if info.processed_up_to_datetime else None,
        }
    except Exception as exc:
        if _is_auth_error(exc):
            _record_auth_failure()
        else:
            logger.warning(f"Vectorize index info exception: {exc}")
        return {}


async def get_index_config() -> dict:
    """Get index configuration (name, dimensions, metric)."""
    if _breaker_open():
        return {}
    cf = _get_cf_client()
    account_id = _account_id()

    try:
        result = await cf.vectorize.indexes.get(
            index_name=VECTORIZE_INDEX_NAME,
            account_id=account_id,
        )
        _record_success()
        if result is None:
            return {}
        return {
            "name": result.name if hasattr(result, "name") else VECTORIZE_INDEX_NAME,
            "dimensions": result.config.dimensions if hasattr(result, "config") and result.config else VECTORIZE_DIMENSIONS,
            "metric": result.config.metric if hasattr(result, "config") and result.config else "cosine",
        }
    except Exception as exc:
        if _is_auth_error(exc):
            _record_auth_failure()
        else:
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
