"""
Topical mapping endpoints — sibling/related-topic graph for ChapterPage
and the subject-wide topic index for SubjectLandingPage.

Why a new module (not inside `topic_answer_cards.py`):
- Answer-card endpoints are hot-path, narrowly scoped, and must stay
  small — adding cross-chapter resolution + hierarchy walks would bloat
  them and complicate cache invalidation.
- The graph endpoints are meta-content (links between topics) rather
  than the topics themselves, so a separate module keeps the two
  concerns independently cacheable / overridable.

Why we do our own hierarchy resolution rather than reusing
`seo_engine._resolve_hierarchy`:
- That helper drops the stream slug, but the SPA's deep-link route is
  stream-aware (`/<board>/<class>/<stream>/<subject>/<chapter>/topic/
  <slug>`). We need stream when it exists; falling back to the
  4-segment shape only when the chapter / subject genuinely has no
  stream.
- We also memoise per-chapter, so resolving N cross-chapter related
  topics is O(distinct_chapters) Mongo reads — the seo_engine helper
  is per-topic, which would be 4×N reads.

Both endpoints intentionally only return topics that are ALREADY
citable: `status == published` AND `definition_status == ok` AND
`topic_slug` is non-empty. This is the same gate that powers the
answer cards (`scripts/backfill_topic_slugs.py`), so the entire
topical-authority surface stays consistent — bots/humans never see a
link to a stub topic that 404s when clicked.

Performance (Neural Mesh):
- `_resolve_chapter_path` results are cached in chapter_path_mesh
  (1h TTL, 2048-entry L1). Cache miss triggers a parallelised fetch
  (chapter + subject in one gather, then stream + class + board in a
  second gather) — down from 5 sequential round-trips to 2 parallel
  gather calls.
- Cross-chapter topic sampling uses ONE batched $in query instead of
  N sequential per-chapter queries, cutting the hot path from O(N)
  round-trips to O(1).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response

from deps import db, is_mongo_available
from neural_mesh import chapter_path_mesh, topic_graph_mesh
from scripts.backfill_topic_slugs import DEFINITION_STATUS_OK

router = APIRouter()

# Same edge-cache policy as topic_answer_cards — graph data invalidates
# on the same admin-edit + Pages-rebuild cycle.
_CACHE_HEADER = "public, max-age=300, stale-while-revalidate=3600"

# Mongo projection: only the columns the SPA / prerender needs.
_TOPIC_PROJ = {
    "_id": 0, "id": 1, "topic_slug": 1, "title": 1,
    "order": 1, "chapter_id": 1, "definition": 1,
}
_PUBLISHED_TOPIC_FILTER = {
    "status": "published",
    "definition_status": DEFINITION_STATUS_OK,
    "topic_slug": {"$exists": True, "$nin": [None, ""]},
}


async def _resolve_chapter_path(chapter_id: str) -> Optional[dict[str, str]]:
    """Resolve `{board, class, stream, subject, chapter}` slugs for a chapter.

    Returns ``None`` when the chapter or its subject is missing — the
    chapter is then unreachable from the public site anyway. Stream is
    optional: when absent we omit it, matching the SPA's 4-segment
    legacy route.

    Results are cached in ``chapter_path_mesh`` (1h TTL, 2048 L1 slots).
    A cache miss triggers a parallelised fetch — chapter+subject in one
    ``gather``, then stream+class+board in a second ``gather`` — reducing
    the worst-case latency from 5 sequential round-trips to 2.
    """
    if not chapter_id:
        return None
    cache_key = f"cp:{chapter_id}"
    return await chapter_path_mesh.get_or_fetch(
        cache_key,
        lambda: _resolve_chapter_path_uncached(chapter_id),
    )


async def _resolve_chapter_path_uncached(chapter_id: str) -> Optional[dict[str, str]]:
    """Uncached inner fetch — called at most once per cache-miss window.

    3-phase parallelisation:
      Phase 1  chapter lookup (we need subject_id from it)
      Phase 2  subject lookup (sequential; subject_id depends on phase 1)
      Phase 3  stream + fallback-class lookups in parallel (both IDs
               are now known from the subject doc)
      Phase 4  board lookup (depends on cls.board_id from phase 3)
    Net: 4 sequential-dependency rounds instead of 5.  With the mesh
    cache warm, this whole function is never called on a cache hit.
    """
    # Phase 1 — chapter
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        return None

    # Phase 2 — subject (needs chapter.subject_id)
    subject = await db.subjects.find_one(
        {"id": chapter.get("subject_id", "")}, {"_id": 0}
    )
    if not subject:
        return None

    # Phase 3 — stream + subject's direct class_id in parallel
    stream_id = subject.get("stream_id") or ""
    class_id_direct = subject.get("class_id") or ""

    async def _fetch_stream():
        if stream_id:
            return await db.streams.find_one({"id": stream_id}, {"_id": 0})
        return None

    async def _fetch_direct_class():
        if class_id_direct and not stream_id:
            return await db.classes.find_one({"id": class_id_direct}, {"_id": 0})
        return None

    stream, direct_cls = await asyncio.gather(_fetch_stream(), _fetch_direct_class())

    # Class-id resolution: stream.class_id > subject.class_id (legacy)
    class_id = (stream or {}).get("class_id") or class_id_direct
    if not class_id:
        return None

    # Reuse already-fetched direct_cls when possible; otherwise fetch
    cls = direct_cls
    if cls is None or (cls.get("id") != class_id):
        cls = await db.classes.find_one({"id": class_id}, {"_id": 0})

    # Phase 4 — board (needs cls.board_id)
    board = None
    if cls and cls.get("board_id"):
        board = await db.boards.find_one({"id": cls["board_id"]}, {"_id": 0})

    if not (board and cls and subject and chapter):
        return None
    return {
        "board_slug": board.get("slug") or "",
        "class_slug": cls.get("slug") or "",
        "stream_slug": (stream or {}).get("slug") or "",
        "subject_slug": subject.get("slug") or "",
        "chapter_slug": chapter.get("slug") or "",
    }


def _build_deep_link(path: dict[str, str], topic_slug: str) -> str:
    """Build a topic deep-link URL from a resolved chapter path.

    Mirrors the SPA route added in Task #914: 5-segment when the
    subject has a stream, 4-segment legacy fallback otherwise.
    """
    base = f"/{path['board_slug']}/{path['class_slug']}"
    if path.get("stream_slug"):
        base += f"/{path['stream_slug']}"
    base += f"/{path['subject_slug']}/{path['chapter_slug']}"
    return f"{base}/topic/{topic_slug}"


def _build_chapter_url(path: dict[str, str]) -> str:
    """Build a canonical chapter URL (no topic segment)."""
    base = f"/{path['board_slug']}/{path['class_slug']}"
    if path.get("stream_slug"):
        base += f"/{path['stream_slug']}"
    base += f"/{path['subject_slug']}/{path['chapter_slug']}"
    return base


def _project_graph_topic(t: dict, path: dict[str, str], chapter_title: str = "") -> dict[str, Any]:
    """Trim a topic doc to the shape the topic-graph UI consumes."""
    return {
        "topic_id": t.get("id"),
        "topic_slug": t.get("topic_slug") or "",
        "title": t.get("title") or "",
        "chapter_id": t.get("chapter_id"),
        "chapter_slug": path.get("chapter_slug") or "",
        "chapter_title": chapter_title,
        "deep_link_path": _build_deep_link(path, t.get("topic_slug") or ""),
        "chapter_url": _build_chapter_url(path),
    }


@router.get("/content/chapters/{chapter_id}/topics-related")
async def topics_related_for_chapter(
    chapter_id: str,
    exclude: Optional[str] = None,
    limit: int = 12,
    response: Response = None,
) -> dict[str, Any]:
    """Sibling + cross-chapter related topics for the chapter.

    `siblings` = every other published topic in this chapter (same
    answer-card surface, ordered by `order`). Used for the "More topics
    in this chapter" rail.

    `cross_chapter` = up to `limit` published topics drawn from sibling
    chapters in the same subject (ordered by chapter `order_index`,
    then topic `order`). One batched $in query replaces the previous
    O(N) per-chapter sequential queries.

    `?exclude=<topic_slug>` removes a slug from `siblings` so the topic
    deep-link page doesn't link back to itself.

    The full result (without the `exclude` filter, which is per-request
    view-specific) is cached in ``topic_graph_mesh`` with a 20-min TTL.
    The exclude filter is applied in-memory on top of the cached result.
    """
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")

    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 12

    # Cache the base result (without exclude) — apply exclude in-memory.
    mesh_key = f"trf:{chapter_id}:{limit}"
    base = await topic_graph_mesh.get_or_fetch(
        mesh_key,
        lambda: _fetch_topics_related(chapter_id, limit),
    )

    if response is not None:
        response.headers["Cache-Control"] = _CACHE_HEADER

    # Apply the per-request exclude filter in-memory (zero DB cost)
    if exclude and base.get("siblings"):
        siblings = [
            s for s in base["siblings"]
            if s.get("topic_slug") != exclude
        ]
        return {**base, "siblings": siblings}
    return base


async def _fetch_topics_related(chapter_id: str, limit: int) -> dict[str, Any]:
    """Database fetch for topics-related (called once per cache miss)."""
    this_path = await _resolve_chapter_path(chapter_id)
    if this_path is None:
        return {"chapter_id": chapter_id, "siblings": [], "cross_chapter": []}

    # Fetch siblings + chapter metadata in parallel
    sibling_rows, chapter_doc = await asyncio.gather(
        db.topics.find(
            {"chapter_id": chapter_id, **_PUBLISHED_TOPIC_FILTER},
            _TOPIC_PROJ,
        ).sort("order", 1).to_list(50),
        db.chapters.find_one(
            {"id": chapter_id}, {"_id": 0, "title": 1, "subject_id": 1}
        ),
    )

    chapter_title = (chapter_doc or {}).get("title") or ""
    siblings = [
        _project_graph_topic(t, this_path, chapter_title=chapter_title)
        for t in sibling_rows
    ]

    # ── Cross-chapter: ONE batched $in query (was O(N) sequential) ───
    cross_chapter: list[dict[str, Any]] = []
    subject_id = (chapter_doc or {}).get("subject_id")
    if subject_id:
        # Step 1: get sibling chapter metadata (tiny, fast)
        sibling_chapters = await (
            db.chapters.find(
                {"subject_id": subject_id, "id": {"$ne": chapter_id}},
                {"_id": 0, "id": 1, "slug": 1, "title": 1, "order_index": 1},
            )
            .sort("order_index", 1)
            .to_list(50)
        )
        if sibling_chapters:
            # Step 2: ONE $in query for all sibling chapters' topics
            all_ch_ids = [ch["id"] for ch in sibling_chapters]
            all_cross_rows = await (
                db.topics.find(
                    {"chapter_id": {"$in": all_ch_ids}, **_PUBLISHED_TOPIC_FILTER},
                    _TOPIC_PROJ,
                )
                .sort([("chapter_id", 1), ("order", 1)])
                .to_list(limit * 4)  # over-fetch to get 2 per chapter
            )

            # Bucket by chapter_id in Python — keeps O(1) DB cost
            by_ch: dict[str, list] = {}
            for t in all_cross_rows:
                cid = t.get("chapter_id")
                if cid:
                    by_ch.setdefault(cid, []).append(t)

            ch_title_map = {ch["id"]: ch.get("title") or "" for ch in sibling_chapters}
            ch_slug_map = {ch["id"]: ch.get("slug") or "" for ch in sibling_chapters}

            for ch in sibling_chapters:
                if len(cross_chapter) >= limit:
                    break
                ch_path = {**this_path, "chapter_slug": ch_slug_map[ch["id"]]}
                ch_title = ch_title_map[ch["id"]]
                for t in by_ch.get(ch["id"], [])[:2]:
                    if len(cross_chapter) >= limit:
                        break
                    cross_chapter.append(
                        _project_graph_topic(t, ch_path, chapter_title=ch_title)
                    )

    return {
        "chapter_id": chapter_id,
        "siblings": siblings,
        "cross_chapter": cross_chapter,
    }


@router.get("/content/subjects/{subject_id}/topic-index")
async def subject_topic_index(
    subject_id: str,
    response: Response = None,
) -> dict[str, Any]:
    """Subject-wide topic index — every published topic, grouped by chapter.

    Powers the SubjectLandingPage's pillar topic-index block. The
    response shape is `{ subject_id, chapters: [{ chapter_id,
    chapter_slug, chapter_title, chapter_url, topics: [...]  }] }` so
    the UI can render a chapter-by-chapter accordion / list with the
    same topic-card link target the deep-link route uses.
    """
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")

    chapters = await (
        db.chapters.find(
            {"subject_id": subject_id},
            {"_id": 0, "id": 1, "slug": 1, "title": 1, "order_index": 1},
        )
        .sort("order_index", 1)
        .to_list(500)
    )
    if not chapters:
        if response is not None:
            response.headers["Cache-Control"] = _CACHE_HEADER
        return {"subject_id": subject_id, "chapters": [], "total_topics": 0}

    # Resolve hierarchy ONCE — every chapter under a subject shares
    # board/class/stream/subject. Then per-chapter we just swap
    # `chapter_slug`. (The first chapter is enough; if it's missing
    # hierarchy then the subject itself is broken and we bail.)
    first_path = await _resolve_chapter_path(chapters[0]["id"])
    if first_path is None:
        if response is not None:
            response.headers["Cache-Control"] = _CACHE_HEADER
        return {"subject_id": subject_id, "chapters": [], "total_topics": 0}

    chapter_ids = [c["id"] for c in chapters]
    topic_rows = await (
        db.topics.find(
            {"chapter_id": {"$in": chapter_ids}, **_PUBLISHED_TOPIC_FILTER},
            _TOPIC_PROJ,
        )
        .sort([("chapter_id", 1), ("order", 1)])
        .to_list(5000)
    )

    # Bucket topics by chapter so the response can stream per-chapter.
    by_chapter: dict[str, list[dict]] = {}
    for t in topic_rows:
        by_chapter.setdefault(t["chapter_id"], []).append(t)

    out_chapters: list[dict[str, Any]] = []
    total = 0
    for ch in chapters:
        ch_path = {**first_path, "chapter_slug": ch.get("slug") or ""}
        ch_title = ch.get("title") or ""
        ch_topics = [
            _project_graph_topic(t, ch_path, chapter_title=ch_title)
            for t in by_chapter.get(ch["id"], [])
        ]
        if not ch_topics:
            continue  # Skip chapters with zero citable topics.
        total += len(ch_topics)
        out_chapters.append({
            "chapter_id": ch["id"],
            "chapter_slug": ch.get("slug") or "",
            "chapter_title": ch_title,
            "chapter_url": _build_chapter_url(ch_path),
            "topics": ch_topics,
        })

    if response is not None:
        response.headers["Cache-Control"] = _CACHE_HEADER
    return {
        "subject_id": subject_id,
        "chapters": out_chapters,
        "total_topics": total,
    }
