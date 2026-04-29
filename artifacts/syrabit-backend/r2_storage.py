"""
Cloudflare R2 Object Storage — async helpers.

R2 is S3-compatible, so we use boto3 with a custom endpoint URL.
All boto3 operations are synchronous; they run in a thread-pool executor
so they don't block the FastAPI event loop.

Required env vars:
  R2_ACCESS_KEY_ID      — from CF Dashboard → R2 → Manage R2 API Tokens
  R2_SECRET_ACCESS_KEY  — paired secret
  R2_BUCKET_NAME        — bucket (default: syrabit-media)
  CF_AI_GATEWAY_ACCOUNT_ID — CF account ID (auto-builds endpoint URL)
  R2_PUBLIC_URL         — optional public-read URL base (e.g. https://media.syrabit.ai)

Usage:
  from r2_storage import r2_upload, r2_delete, r2_presign, r2_public_url

  url = await r2_upload(key="images/abc.png", data=raw_bytes, content_type="image/png")
  await r2_delete("images/abc.png")
  signed = await r2_presign("pdfs/doc.pdf", expires=3600)
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


# ── lazy boto3 client ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_r2_client():
    """Return a cached boto3 S3 client pointed at R2. Raises if not configured."""
    from config import R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL, R2_ENABLED
    if not R2_ENABLED:
        raise RuntimeError(
            "R2 not configured — set R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
            "and CF_AI_GATEWAY_ACCOUNT_ID (or R2_ENDPOINT_URL)"
        )
    import boto3
    from botocore.config import Config
    client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )
    return client


def _is_r2_ready() -> bool:
    from config import R2_ENABLED
    return R2_ENABLED


# ── ensure bucket exists ──────────────────────────────────────────────────────

_bucket_ensured = False

def _ensure_bucket_sync(bucket: str) -> None:
    global _bucket_ensured
    if _bucket_ensured:
        return
    client = _get_r2_client()
    try:
        client.head_bucket(Bucket=bucket)
        _bucket_ensured = True
    except Exception:
        try:
            client.create_bucket(Bucket=bucket)
            logger.info(f"r2: created bucket '{bucket}'")
            _bucket_ensured = True
        except Exception as exc:
            if "BucketAlreadyOwnedByYou" in str(exc) or "BucketAlreadyExists" in str(exc):
                _bucket_ensured = True
            else:
                raise


async def ensure_bucket() -> None:
    """Create the R2 bucket if it doesn't exist yet."""
    if not _is_r2_ready():
        return
    from config import R2_BUCKET_NAME
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _ensure_bucket_sync, R2_BUCKET_NAME)


# ── upload ────────────────────────────────────────────────────────────────────

def _upload_sync(key: str, data: bytes, content_type: str, bucket: str,
                  cache_control: str, metadata: dict) -> str:
    _ensure_bucket_sync(bucket)
    client = _get_r2_client()
    extra: dict = {"ContentType": content_type}
    if cache_control:
        extra["CacheControl"] = cache_control
    if metadata:
        extra["Metadata"] = {k: str(v) for k, v in metadata.items()}
    client.put_object(Bucket=bucket, Key=key, Body=data, **extra)
    return key


async def r2_upload(
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    cache_control: str = "public, max-age=31536000, immutable",
    metadata: Optional[dict] = None,
    bucket: Optional[str] = None,
) -> str:
    """
    Upload ``data`` to R2 at ``key``.
    Returns the public URL if R2_PUBLIC_URL is set, otherwise the key.
    Raises RuntimeError if R2 is not configured.
    """
    from config import R2_BUCKET_NAME, R2_PUBLIC_URL
    _bucket = bucket or R2_BUCKET_NAME
    loop = asyncio.get_event_loop()
    t0 = time.monotonic()
    await loop.run_in_executor(
        None,
        _upload_sync,
        key, data, content_type, _bucket, cache_control, metadata or {},
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    logger.info(f"r2: uploaded {key} ({len(data)} bytes) in {elapsed}ms")
    return r2_public_url(key, bucket=_bucket)


# ── delete ────────────────────────────────────────────────────────────────────

def _delete_sync(key: str, bucket: str) -> None:
    client = _get_r2_client()
    client.delete_object(Bucket=bucket, Key=key)


async def r2_delete(key: str, bucket: Optional[str] = None) -> None:
    """Delete an object from R2. Silent no-op if key doesn't exist."""
    if not _is_r2_ready():
        return
    from config import R2_BUCKET_NAME
    _bucket = bucket or R2_BUCKET_NAME
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _delete_sync, key, _bucket)
        logger.info(f"r2: deleted {key}")
    except Exception as exc:
        logger.warning(f"r2: delete failed for {key}: {exc}")


# ── presigned URL ─────────────────────────────────────────────────────────────

def _presign_sync(key: str, bucket: str, expires: int) -> str:
    client = _get_r2_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires,
    )


async def r2_presign(key: str, expires: int = 3600, bucket: Optional[str] = None) -> str:
    """Generate a time-limited presigned GET URL (for private objects)."""
    from config import R2_BUCKET_NAME
    _bucket = bucket or R2_BUCKET_NAME
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _presign_sync, key, _bucket, expires)


# ── public URL helper ─────────────────────────────────────────────────────────

def r2_public_url(key: str, bucket: Optional[str] = None) -> str:
    """
    Return the public-facing URL for an R2 object.
    Uses R2_PUBLIC_URL if set (e.g. https://media.syrabit.ai),
    otherwise falls back to the R2 endpoint URL pattern.
    """
    from config import R2_PUBLIC_URL, R2_ENDPOINT_URL, R2_BUCKET_NAME
    _bucket = bucket or R2_BUCKET_NAME
    if R2_PUBLIC_URL:
        return f"{R2_PUBLIC_URL}/{key}"
    if R2_ENDPOINT_URL:
        return f"{R2_ENDPOINT_URL}/{_bucket}/{key}"
    return key


# ── list objects ──────────────────────────────────────────────────────────────

def _list_sync(prefix: str, bucket: str, max_keys: int) -> list[dict]:
    client = _get_r2_client()
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=max_keys)
    return [
        {
            "key": obj["Key"],
            "size": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
            "url": r2_public_url(obj["Key"], bucket),
        }
        for obj in resp.get("Contents", [])
    ]


async def r2_list(prefix: str = "", max_keys: int = 1000, bucket: Optional[str] = None) -> list[dict]:
    """List objects in R2 under a prefix. Returns list of {key, size, last_modified, url}."""
    if not _is_r2_ready():
        return []
    from config import R2_BUCKET_NAME
    _bucket = bucket or R2_BUCKET_NAME
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list_sync, prefix, _bucket, max_keys)


# ── download ──────────────────────────────────────────────────────────────────

def _download_sync(key: str, bucket: str) -> bytes:
    client = _get_r2_client()
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


async def r2_download(key: str, bucket: Optional[str] = None) -> bytes:
    """Download and return the raw bytes of an R2 object."""
    from config import R2_BUCKET_NAME
    _bucket = bucket or R2_BUCKET_NAME
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_sync, key, _bucket)


# ── key helpers ───────────────────────────────────────────────────────────────

def make_key(folder: str, filename: str) -> str:
    """Sanitize filename and build a deterministic key under ``folder``."""
    import uuid, re
    safe = re.sub(r"[^\w.\-]", "_", filename)
    uid = uuid.uuid4().hex[:8]
    return f"{folder}/{uid}_{safe}"


def content_type_for(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


# ── health check ──────────────────────────────────────────────────────────────

async def r2_health() -> dict:
    """Quick connectivity check — list up to 1 object."""
    if not _is_r2_ready():
        return {"ok": False, "reason": "R2 not configured"}
    try:
        from config import R2_BUCKET_NAME, R2_ENDPOINT_URL, R2_PUBLIC_URL
        items = await r2_list(max_keys=1)
        return {
            "ok": True,
            "bucket": R2_BUCKET_NAME,
            "endpoint": R2_ENDPOINT_URL,
            "public_url": R2_PUBLIC_URL or "(none — using endpoint URL)",
            "sample_count": len(items),
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
