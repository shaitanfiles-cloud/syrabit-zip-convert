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
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response

from deps import db, is_mongo_available
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
    """
    if not chapter_id:
        return None
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        return None
    subject = await db.subjects.find_one({"id": chapter.get("subject_id", "")}, {"_id": 0})
    if not subject:
        return None
    stream = None
    cls = None
    board = None
    if subject.get("stream_id"):
        stream = await db.streams.find_one({"id": subject["stream_id"]}, {"_id": 0})
    # Class-id resolution order: stream.class_id (stream-based subjects)
    # → subject.class_id (legacy / non-stream subjects). Without this
    # second branch, every non-stream subject (e.g. HSLC subjects that
    # hang off a class directly) collapses to None and the related-
    # topic graph empties out — matching the architect-flagged bug.
    class_id = (stream or {}).get("class_id") or subject.get("class_id")
    if class_id:
        cls = await db.classes.find_one({"id": class_id}, {"_id": 0})
    if cls and cls.get("board_id"):
        board = await db.boards.find_one({"id": cls["board_id"]}, {"_id": 0})

    # Defensive fallbacks — the SPA can't navigate to a chapter without
    # a board+class+subject+chapter chain, so bail rather than emit a
    # broken href.
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
    then topic `order`). This is intentionally a deterministic, cheap
    fallback for "Related across the syllabus" — no embedding lookup,
    no per-request similarity. The Vectorize-backed
    `/seo/related-by-chapter` endpoint can swap in later without
    changing this endpoint's response shape.

    `?exclude=<topic_slug>` removes a slug from `siblings` so the topic
    deep-link page doesn't link back to itself.
    """
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")

    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 12

    this_path = await _resolve_chapter_path(chapter_id)
    if this_path is None:
        # Chapter not reachable from the public site — return empty
        # rather than 404 so the SPA can still render the rest of the
        # page if a stale chapter_id lingers in a prerendered preload.
        if response is not None:
            response.headers["Cache-Control"] = _CACHE_HEADER
        return {"chapter_id": chapter_id, "siblings": [], "cross_chapter": []}

    # ── Siblings (same chapter) ──────────────────────────────────
    sibling_filter: dict[str, Any] = {
        "chapter_id": chapter_id,
        **_PUBLISHED_TOPIC_FILTER,
    }
    if exclude:
        sibling_filter["topic_slug"] = {
            **sibling_filter["topic_slug"],
            "$ne": exclude,
        }
    sibling_rows = await (
        db.topics.find(sibling_filter, _TOPIC_PROJ)
        .sort("order", 1)
        .to_list(50)
    )
    chapter_doc = await db.chapters.find_one(
        {"id": chapter_id}, {"_id": 0, "title": 1, "subject_id": 1},
    )
    chapter_title = (chapter_doc or {}).get("title") or ""
    siblings = [
        _project_graph_topic(t, this_path, chapter_title=chapter_title)
        for t in sibling_rows
    ]

    # ── Cross-chapter (same subject, other chapters) ─────────────
    cross_chapter: list[dict[str, Any]] = []
    subject_id = (chapter_doc or {}).get("subject_id")
    if subject_id:
        # Pull sibling chapters in subject order; skip the current one.
        sibling_chapters = await (
            db.chapters.find(
                {"subject_id": subject_id, "id": {"$ne": chapter_id}},
                {"_id": 0, "id": 1, "slug": 1, "title": 1, "order_index": 1},
            )
            .sort("order_index", 1)
            .to_list(50)
        )
        # Memoise hierarchy per-chapter — every sibling chapter shares
        # board/class/stream/subject with `this_path`, so we can reuse
        # `this_path` and only swap chapter_slug.
        for ch in sibling_chapters:
            if len(cross_chapter) >= limit:
                break
            ch_path = {**this_path, "chapter_slug": ch.get("slug") or ""}
            # Pull up to 2 published topics per sibling chapter so the
            # rail surfaces breadth, not just the first chapter's
            # exhaustive list.
            ch_topic_rows = await (
                db.topics.find(
                    {"chapter_id": ch["id"], **_PUBLISHED_TOPIC_FILTER},
                    _TOPIC_PROJ,
                )
                .sort("order", 1)
                .limit(2)
                .to_list(2)
            )
            for t in ch_topic_rows:
                if len(cross_chapter) >= limit:
                    break
                cross_chapter.append(
                    _project_graph_topic(t, ch_path, chapter_title=ch.get("title") or ""),
                )

    if response is not None:
        response.headers["Cache-Control"] = _CACHE_HEADER
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
