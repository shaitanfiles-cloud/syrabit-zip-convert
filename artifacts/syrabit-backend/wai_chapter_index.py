"""
Workers AI Chapter Index
========================
Uses @cf/baai/bge-small-en-v1.5 (384-dim, 1M ctx) to embed
Assam Board chapter metadata and perform fast cosine-similarity
topic→chapter matching within a given subject.

Design
------
* Lazy, per-subject initialisation.  On first query for a subject,
  we build the embedding index for its chapters (~200ms for a 20-chapter
  subject) and cache it in Redis for 24 h.  The in-process dict keeps
  the index hot between requests.
* Cold-start (first ever call): the index build starts in the background
  (asyncio.create_task) and classify() returns None immediately.  The
  very next request reuses the cached index.
* The Workers AI REST endpoint accepts a text batch in a single call,
  so embedding 20 chapters costs one round-trip (~150-300ms).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger("wai_chapter_index")

_EMBED_MODEL = "@cf/baai/bge-small-en-v1.5"
_SIM_HIGH = 0.72   # confident match (shown in animation + used for RAG boost)
_SIM_LOW  = 0.55   # acceptable match (shown in animation only)
_INDEX_TTL_S = 3600

_index:    dict[str, list[dict]] = {}  # subject_id → list[entry]
_index_ts: dict[str, float]      = {}
_build_tasks: dict[str, asyncio.Task] = {}  # prevent concurrent rebuilds
_lock = asyncio.Lock()


# ─── credentials ─────────────────────────────────────────────────────────────

def _account_id() -> str:
    return os.getenv("CF_AI_GATEWAY_ACCOUNT_ID", "")

def _token() -> str:
    return (
        os.getenv("CLOUDFLARE_API_TOKEN") or
        os.getenv("CF_API_TOKEN") or
        os.getenv("CF_PAGES_API_TOKEN") or ""
    )

def is_configured() -> bool:
    return bool(_account_id() and _token())


# ─── Workers AI call ─────────────────────────────────────────────────────────

async def _embed_batch(texts: list[str]) -> list[list[float]]:
    acct  = _account_id()
    token = _token()
    url   = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{_EMBED_MODEL}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            url,
            json={"text": texts},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
        )
        r.raise_for_status()
        data = r.json()
    if not data.get("success"):
        raise ValueError(f"Workers AI embed error: {data.get('errors', [])}")
    return data["result"]["data"]


# ─── index build ─────────────────────────────────────────────────────────────

def _chapter_text(ch: dict) -> str:
    parts = [ch.get("title", "")]
    if ch.get("description"):
        parts.append(ch["description"][:300])
    topics = ch.get("topics") or []
    if isinstance(topics, list) and topics:
        parts.append("Topics: " + ", ".join(str(t) for t in topics[:12]))
    return ". ".join(p for p in parts if p)[:600]


async def _build(subject_id: str) -> list[dict]:
    from deps import db
    chapters = await asyncio.wait_for(
        db.chapters.find(
            {"subject_id": subject_id},
            {"_id": 0, "id": 1, "title": 1, "description": 1,
             "chapter_number": 1, "order_index": 1, "slug": 1, "topics": 1},
        ).sort("order_index", 1).to_list(200),
        timeout=6.0,
    )
    if not chapters:
        return []

    texts = [_chapter_text(ch) for ch in chapters]
    embeddings = await asyncio.wait_for(_embed_batch(texts), timeout=15.0)
    if len(embeddings) != len(chapters):
        logger.warning("wai_chapter_index: embed/chapter count mismatch for %s", subject_id)
        return []

    entries = []
    for ch, emb in zip(chapters, embeddings):
        entries.append({
            "chapter_id":     ch["id"],
            "title":          ch.get("title", ""),
            "slug":           ch.get("slug", ""),
            "chapter_number": ch.get("chapter_number") or ch.get("order_index") or 0,
            "embedding":      emb,
        })
    logger.info("wai_chapter_index: built %d-entry index for %s", len(entries), subject_id)
    return entries


async def _persist_to_redis(subject_id: str, entries: list[dict]) -> None:
    try:
        from deps import redis_client as _rc
        if _rc and entries:
            key = f"wai:cidx:{subject_id}"
            await _rc.setex(key, 86400, json.dumps(entries))
    except Exception as e:
        logger.debug("wai_chapter_index: Redis persist failed: %s", e)


async def _load_from_redis(subject_id: str) -> Optional[list[dict]]:
    try:
        from deps import redis_client as _rc
        if not _rc:
            return None
        key = f"wai:cidx:{subject_id}"
        raw = await _rc.get(key)
        if raw:
            entries = json.loads(raw)
            logger.info("wai_chapter_index: Redis HIT — %d entries for %s", len(entries), subject_id)
            return entries
    except Exception as e:
        logger.debug("wai_chapter_index: Redis load failed: %s", e)
    return None


async def _ensure_index(subject_id: str) -> list[dict]:
    """Return cached index if fresh; otherwise build/restore it."""
    now = time.monotonic()

    # Hot in-process cache
    if subject_id in _index and (now - _index_ts.get(subject_id, 0)) < _INDEX_TTL_S:
        return _index[subject_id]

    async with _lock:
        # Re-check after acquiring lock (another coroutine may have built it)
        if subject_id in _index and (now - _index_ts.get(subject_id, 0)) < _INDEX_TTL_S:
            return _index[subject_id]

        # Try Redis
        entries = await _load_from_redis(subject_id)
        if entries is not None:
            _index[subject_id]    = entries
            _index_ts[subject_id] = now
            return entries

        # Must build — do it in the background and return empty list now
        # so the calling request is never blocked by a cold-start build.
        if subject_id not in _build_tasks or _build_tasks[subject_id].done():
            async def _bg_build():
                try:
                    built = await _build(subject_id)
                    async with _lock:
                        _index[subject_id]    = built
                        _index_ts[subject_id] = time.monotonic()
                    asyncio.create_task(_persist_to_redis(subject_id, built))
                except Exception as exc:
                    logger.warning("wai_chapter_index: background build failed for %s: %s", subject_id, exc)
                    async with _lock:
                        _index[subject_id]    = []
                        _index_ts[subject_id] = time.monotonic()
            _build_tasks[subject_id] = asyncio.create_task(_bg_build())
            logger.info("wai_chapter_index: cold-start — bg build launched for %s", subject_id)

        _index[subject_id]    = []
        _index_ts[subject_id] = now
        return []


# ─── cosine similarity ────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if (na * nb) else 0.0


# ─── public API ──────────────────────────────────────────────────────────────

async def classify(
    query: str,
    subject_id: str,
    *,
    timeout_s: float = 3.5,
) -> Optional[dict]:
    """
    Return the best-matching chapter for *query* within *subject_id*, or None.

    Result keys
    -----------
    chapter_id      str
    chapter_title   str
    chapter_number  int
    slug            str
    similarity      float   (0–1)
    confident       bool    (similarity ≥ _SIM_HIGH)
    """
    if not is_configured():
        return None

    t0 = time.monotonic()

    try:
        # Allow half the budget for index fetch, half for query embed
        half = timeout_s / 2

        index = await asyncio.wait_for(_ensure_index(subject_id), timeout=half)
        if not index:
            return None

        remaining = max(0.5, timeout_s - (time.monotonic() - t0))
        q_embs = await asyncio.wait_for(_embed_batch([query[:600]]), timeout=remaining)
        if not q_embs:
            return None
        q = q_embs[0]

        best, best_sim = None, -1.0
        for entry in index:
            s = _cosine(q, entry["embedding"])
            if s > best_sim:
                best_sim = s
                best = entry

        elapsed_ms = (time.monotonic() - t0) * 1000
        if best and best_sim >= _SIM_LOW:
            logger.info(
                "wai_chapter_index: MATCH '%s' (sim=%.3f, %.0fms) for '%s'",
                best["title"], best_sim, elapsed_ms, query[:45],
            )
            return {
                "chapter_id":     best["chapter_id"],
                "chapter_title":  best["title"],
                "chapter_number": best["chapter_number"],
                "slug":           best["slug"],
                "similarity":     round(best_sim, 4),
                "confident":      best_sim >= _SIM_HIGH,
            }

        logger.info(
            "wai_chapter_index: no match (best_sim=%.3f, %.0fms) for '%s'",
            best_sim, elapsed_ms, query[:45],
        )
        return None

    except asyncio.TimeoutError:
        logger.info("wai_chapter_index: classify timeout (%.0fms) for '%s'", timeout_s * 1000, query[:45])
        return None
    except Exception as exc:
        logger.warning("wai_chapter_index: classify error: %s", exc)
        return None


async def warm_subject(subject_id: str) -> None:
    """Fire-and-forget: pre-warm a subject's index at startup."""
    if not subject_id or not is_configured():
        return
    asyncio.create_task(_ensure_index(subject_id))
