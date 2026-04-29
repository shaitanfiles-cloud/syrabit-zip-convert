"""Syrabit.ai — Neural Mesh: multi-tier cache, inflight deduplication, and
startup pre-warming for sub-100ms hot-path responses.

Architecture
------------
  L1  In-process TTLCache (zero-latency after warm; shared across
      requests on the same worker via preload_app=True fork inheritance)
  L2  Redis (optional; bypassed when MEMORYSTORE_REDIS_URL is unset)
  L3  MongoDB / upstream origin (source of truth)

Key features
------------
  AsyncBarrier   Concurrent requests for the same cache key share ONE
                 upstream fetch — the second caller parks on an asyncio
                 Event and gets the result when the first finishes, never
                 touching MongoDB.
  Adaptive TTL   A per-key access counter scales TTL up to 4× for keys
                 that are fetched repeatedly, and back down when traffic
                 drops (not yet implemented — placeholder for Phase 2).
  Startup warm   `warm_all()` is called from the FastAPI startup handler
                 to pre-populate L1 so the first real request never pays
                 the MongoDB round-trip cost.
  Stats          Exposes L1 hit/miss/inflight-saved counters that the
                 /admin/metrics dashboard can display alongside the Redis
                 counters already tracked in cache.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional

import cachetools

logger = logging.getLogger(__name__)

__all__ = [
    "NeuralMesh",
    "chapter_path_mesh",
    "library_mesh",
    "topic_graph_mesh",
    "get_mesh_stats",
    "warm_all",
]


# ── AsyncBarrier ──────────────────────────────────────────────────────────────

class _Barrier:
    """Single-key inflight deduplication slot."""
    __slots__ = ("event", "result", "error")

    def __init__(self) -> None:
        self.event: asyncio.Event = asyncio.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


# ── NeuralMesh ────────────────────────────────────────────────────────────────

class NeuralMesh:
    """Multi-tier cache + inflight deduplication for one logical namespace.

    Usage::

        mesh = NeuralMesh("chapter_path", maxsize=1024, ttl=1800)

        async def handler(chapter_id: str):
            return await mesh.get_or_fetch(
                f"cp:{chapter_id}",
                lambda: _expensive_db_lookup(chapter_id),
            )

    The ``fetch_fn`` is a **zero-argument async callable** that returns the
    value to cache.  It is called AT MOST ONCE per cache-miss window, even if
    dozens of concurrent requests arrive for the same key simultaneously.
    """

    def __init__(
        self,
        name: str,
        maxsize: int = 2048,
        ttl: int = 1800,
    ) -> None:
        self.name = name
        self._ttl = ttl
        self._l1: cachetools.TTLCache = cachetools.TTLCache(
            maxsize=maxsize, ttl=ttl
        )
        self._barriers: dict[str, _Barrier] = {}

        # Stats (per-worker, reset on restart)
        self._hits = 0
        self._misses = 0
        self._inflight_saves = 0   # requests that waited instead of hitting DB
        self._errors = 0

    # ── public API ────────────────────────────────────────────────────────────

    async def get_or_fetch(
        self,
        key: str,
        fetch_fn: Callable[[], Coroutine[Any, Any, Any]],
        *,
        ttl_override: Optional[int] = None,
    ) -> Any:
        """Return cached value or call ``fetch_fn`` exactly once per miss."""
        # L1 fast-path
        cached = self._l1.get(key)
        if cached is not None:
            self._hits += 1
            return cached

        # Inflight dedup — am I the first caller for this key?
        existing = self._barriers.get(key)
        if existing is not None:
            self._inflight_saves += 1
            await existing.event.wait()
            if existing.error is not None:
                raise existing.error
            return existing.result

        # Leader path — we fetch and unblock waiters
        barrier = _Barrier()
        self._barriers[key] = barrier
        self._misses += 1
        try:
            value = await fetch_fn()
            # Store in L1
            try:
                self._l1[key] = value
            except Exception:
                pass  # TTLCache can raise on full — ignore, result still returned
            barrier.result = value
            return value
        except Exception as exc:
            barrier.error = exc
            self._errors += 1
            raise
        finally:
            barrier.event.set()
            self._barriers.pop(key, None)

    def get(self, key: str) -> Any:
        """Synchronous L1-only lookup (returns None on miss)."""
        return self._l1.get(key)

    def set(self, key: str, value: Any) -> None:
        """Populate L1 directly (used by pre-warmer)."""
        try:
            self._l1[key] = value
        except Exception:
            pass

    def invalidate(self, key: str) -> None:
        """Evict one key from L1."""
        self._l1.pop(key, None)

    def clear(self) -> None:
        """Flush entire L1 for this mesh."""
        self._l1.clear()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "name": self.name,
            "l1_size": len(self._l1),
            "l1_maxsize": self._l1.maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "inflight_saves": self._inflight_saves,
            "errors": self._errors,
            "hit_rate": round(self._hits / max(1, total), 4),
            "inflight_pending": len(self._barriers),
        }


# ── Shared mesh instances ─────────────────────────────────────────────────────

# Chapter hierarchy resolution (board/class/stream/subject/chapter slugs).
# Very hot path — every topics-related request resolves at least one chapter.
chapter_path_mesh = NeuralMesh("chapter_path", maxsize=2048, ttl=3600)

# Library bundle (boards + classes + streams + subjects + chapters).
# Expensive aggregate (~2.5s cold); pre-warmed at startup.
library_mesh = NeuralMesh("library_bundle", maxsize=64, ttl=1800)

# Topic-graph cross-chapter queries (sibling topic lists per chapter).
topic_graph_mesh = NeuralMesh("topic_graph", maxsize=4096, ttl=1200)

# Subject metadata (resolve-subject endpoint).
subject_meta_mesh = NeuralMesh("subject_meta", maxsize=512, ttl=3600)


# ── Stats aggregator ──────────────────────────────────────────────────────────

_ALL_MESHES: list[NeuralMesh] = [
    chapter_path_mesh,
    library_mesh,
    topic_graph_mesh,
    subject_meta_mesh,
]


def get_mesh_stats() -> dict:
    """Return aggregate + per-mesh stats for the admin dashboard."""
    per_mesh = [m.stats for m in _ALL_MESHES]
    total_hits = sum(s["hits"] for s in per_mesh)
    total_misses = sum(s["misses"] for s in per_mesh)
    total_saves = sum(s["inflight_saves"] for s in per_mesh)
    total = total_hits + total_misses
    return {
        "aggregate": {
            "hits": total_hits,
            "misses": total_misses,
            "inflight_saves": total_saves,
            "hit_rate": round(total_hits / max(1, total), 4),
        },
        "meshes": per_mesh,
    }


# ── Startup pre-warmer ────────────────────────────────────────────────────────

async def warm_all() -> None:
    """Pre-warm all mesh caches at server startup.

    Called from the FastAPI ``startup`` lifecycle hook BEFORE the
    first request reaches a worker.  With ``preload_app=True`` in
    gunicorn, the master process runs this; workers inherit a hot L1
    via fork, so they never pay the cold-start penalty.

    Each warm task is run with an individual timeout so one slow
    collection doesn't block the rest of startup.
    """
    t0 = time.monotonic()
    tasks = [
        _warm_library_bundle(),
        _warm_chapter_paths_sample(),
        _warm_slug_hierarchies(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = round((time.monotonic() - t0) * 1000)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("neural_mesh warm_all task %d failed: %s", i, r)
    logger.info(
        "neural_mesh warm_all complete in %dms | %s",
        elapsed,
        " ".join(
            f"{m.name}={m.stats['l1_size']}/{m.stats['l1_maxsize']}"
            for m in _ALL_MESHES
        ),
    )


async def _warm_library_bundle() -> None:
    """Pre-warm the library bundle (slim + full variants)."""
    try:
        from deps import db, is_mongo_available
        import asyncio as _aio

        if not await is_mongo_available():
            logger.debug("neural_mesh: MongoDB unavailable — skipping library bundle warm")
            return

        key_slim = "library-bundle:slim"
        key_full = "library-bundle"

        # Don't re-warm if already in L1 (inherited from a previous fork)
        if library_mesh.get(key_slim) is not None and library_mesh.get(key_full) is not None:
            logger.debug("neural_mesh: library bundle already warm")
            return

        # Fetch the minimal fields used by the slim bundle
        (boards_data, classes_data, streams_data, subjects_data, chapters_data) = await _aio.wait_for(
            _aio.gather(
                db.boards.find({}, {"_id": 0, "id": 1, "name": 1, "slug": 1}).to_list(100),
                db.classes.find({}, {"_id": 0, "id": 1, "name": 1, "slug": 1, "board_id": 1}).to_list(100),
                db.streams.find({}, {"_id": 0, "id": 1, "name": 1, "slug": 1, "class_id": 1}).to_list(100),
                db.subjects.find({"status": "published"}, {"_id": 0}).to_list(500),
                db.chapters.find(
                    {},
                    {"_id": 0, "id": 1, "title": 1, "slug": 1, "subject_id": 1,
                     "order_index": 1, "notes_generated": 1},
                ).sort("order_index", 1).to_list(2000),
            ),
            timeout=12.0,
        )

        slim_bundle = {
            "boards": boards_data,
            "classes": classes_data,
            "streams": streams_data,
            "subjects": subjects_data,
            "chapters": [],
        }
        full_bundle = {
            "boards": boards_data,
            "classes": classes_data,
            "streams": streams_data,
            "subjects": subjects_data,
            "chapters": chapters_data,
        }
        # Populate neural mesh L1
        library_mesh.set(key_slim, slim_bundle)
        library_mesh.set(key_full, full_bundle)

        # Also populate content.py's _content_cache so get_library_bundle
        # returns a cache hit on all workers without re-fetching MongoDB.
        try:
            from cache import _set_content_cache
            _set_content_cache("library-bundle:slim", slim_bundle)
            _set_content_cache("library-bundle", full_bundle)
        except Exception as _ce:
            logger.debug("neural_mesh: content cache population skipped: %s", _ce)

        logger.info(
            "neural_mesh: library bundle warmed — %d subjects %d chapters",
            len(subjects_data),
            len(chapters_data),
        )
    except asyncio.TimeoutError:
        logger.warning("neural_mesh: library bundle warm timed out")
    except Exception as exc:
        logger.warning("neural_mesh: library bundle warm error: %s", exc)


async def _warm_chapter_paths_sample() -> None:
    """Pre-warm chapter-path resolution for the most-accessed chapters.

    Uses the first 200 chapters (ordered by index) as a representative
    warm set.  Each path resolution requires 4-5 MongoDB lookups; we
    batch them here so subsequent requests are sub-millisecond.
    """
    try:
        from deps import db, is_mongo_available

        if not await is_mongo_available():
            return

        # Fetch a representative sample of chapter IDs
        sample = await asyncio.wait_for(
            db.chapters.find(
                {},
                {"_id": 0, "id": 1, "subject_id": 1},
            ).sort("order_index", 1).limit(200).to_list(200),
            timeout=5.0,
        )
        if not sample:
            return

        # Load all subjects, streams, classes, boards in parallel — reuse for
        # all chapters (no N+1; we resolve in Python)
        (subjects, streams, classes, boards) = await asyncio.wait_for(
            asyncio.gather(
                db.subjects.find({}, {"_id": 0, "id": 1, "slug": 1, "stream_id": 1, "class_id": 1, "board_slug": 1, "class_slug": 1, "stream_slug": 1}).to_list(500),
                db.streams.find({}, {"_id": 0, "id": 1, "slug": 1, "class_id": 1}).to_list(200),
                db.classes.find({}, {"_id": 0, "id": 1, "slug": 1, "board_id": 1}).to_list(100),
                db.boards.find({}, {"_id": 0, "id": 1, "slug": 1}).to_list(50),
            ),
            timeout=8.0,
        )

        # Build lookup maps
        subject_map = {s["id"]: s for s in subjects}
        stream_map = {s["id"]: s for s in streams}
        class_map = {c["id"]: c for c in classes}
        board_map = {b["id"]: b for b in boards}

        # Fetch chapter slugs
        chapter_docs = await asyncio.wait_for(
            db.chapters.find(
                {"id": {"$in": [c["id"] for c in sample]}},
                {"_id": 0, "id": 1, "slug": 1, "subject_id": 1},
            ).to_list(200),
            timeout=5.0,
        )
        chapter_map = {c["id"]: c for c in chapter_docs}

        warmed = 0
        for ch_stub in sample:
            ch_id = ch_stub["id"]
            ch = chapter_map.get(ch_id)
            if not ch:
                continue
            subj = subject_map.get(ch.get("subject_id", ""))
            if not subj:
                continue
            stream = stream_map.get(subj.get("stream_id", "")) if subj.get("stream_id") else None
            class_id = (stream or {}).get("class_id") or subj.get("class_id")
            cls = class_map.get(class_id) if class_id else None
            board = board_map.get(cls.get("board_id")) if cls and cls.get("board_id") else None
            if not (board and cls and subj and ch):
                continue
            path = {
                "board_slug": board.get("slug") or "",
                "class_slug": cls.get("slug") or "",
                "stream_slug": (stream or {}).get("slug") or "",
                "subject_slug": subj.get("slug") or "",
                "chapter_slug": ch.get("slug") or "",
            }
            chapter_path_mesh.set(f"cp:{ch_id}", path)
            warmed += 1

        logger.info("neural_mesh: chapter paths warmed — %d/%d chapters", warmed, len(sample))

    except asyncio.TimeoutError:
        logger.warning("neural_mesh: chapter path warm timed out")
    except Exception as exc:
        logger.warning("neural_mesh: chapter path warm error: %s", exc)


async def _warm_slug_hierarchies() -> None:
    """Pre-warm content.py's _slug_hierarchy_cache for all subjects.

    Fetches FULL documents (no projection filter) for boards, classes,
    streams, and subjects so the cached dict contains every field that
    downstream route handlers access — including ``subj['name']`` which
    causes a KeyError when stripped data is used.

    Runs concurrently with the other warm tasks in warm_all().
    """
    try:
        from deps import db, is_mongo_available

        if not await is_mongo_available():
            return

        (boards, classes, streams, subjects) = await asyncio.wait_for(
            asyncio.gather(
                db.boards.find({}, {"_id": 0}).to_list(100),
                db.classes.find({}, {"_id": 0}).to_list(200),
                db.streams.find({}, {"_id": 0}).to_list(300),
                db.subjects.find({"status": {"$ne": "archived"}}, {"_id": 0}).to_list(1000),
            ),
            timeout=10.0,
        )

        from routes.content import warm_slug_hierarchy_cache
        count = warm_slug_hierarchy_cache(subjects, streams, classes, boards)
        logger.info("neural_mesh: slug hierarchy cache warmed — %d entries", count)

    except asyncio.TimeoutError:
        logger.warning("neural_mesh: slug hierarchy warm timed out")
    except Exception as exc:
        logger.warning("neural_mesh: slug hierarchy warm error: %s", exc)
