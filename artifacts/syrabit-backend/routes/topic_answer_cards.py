"""
Public endpoints that feed the per-topic AI answer card on chapter
pages and the dedicated topic deep-link route. Task #914 Steps 2 + 3.

Why two endpoints (and not one chapter detail with topics inlined):
- The chapter detail (`/api/content/chapter-by-slug/...`) is hot-path
  and already heavily-cached. Stuffing a published-topics list onto
  it would either bust that cache or force every chapter consumer to
  pay for topic resolution they don't use.
- Prerender + ChapterPage both need a small, predictable shape
  (`{topics: [{id, topic_slug, title, definition, order}]}`); a
  dedicated endpoint keeps that shape stable as the chapter detail
  evolves.
- The single-topic resolver lets the deep-link route 404 fast for
  unknown / unpublished / definition-missing slugs without round-
  tripping the full topic list to the client.

Both endpoints intentionally exclude topics whose
`definition_status` is `definition_missing` — that field is stamped
by `scripts/backfill_topic_slugs.py` and gates the entire
answer-card / topic-URL surface so we never publish thin content.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from deps import db, is_mongo_available
from scripts.backfill_topic_slugs import (
    DEFINITION_STATUS_OK,
)

router = APIRouter()

# Edge cache: topics change only on admin edits, which already trigger
# a Pages rebuild — five-minute TTL with a long stale-while-revalidate
# matches the chapter-detail policy and keeps Cloudflare's edge warm.
_CACHE_HEADER = "public, max-age=300, stale-while-revalidate=3600"


def _project_topic(t: dict) -> dict[str, Any]:
    """Trim a topic doc to the fields the frontend / prerender need."""
    return {
        "id": t.get("id"),
        "topic_slug": t.get("topic_slug") or "",
        "title": t.get("title") or "",
        "definition": (t.get("definition") or "").strip(),
        "order": int(t.get("order") or 0),
    }


@router.get("/content/chapters/{chapter_id}/topics-published")
async def list_published_topics(chapter_id: str, response: Response = None) -> dict[str, Any]:
    """Topics ready for AI-citation surfaces on this chapter.

    Filters: status == published AND definition_status == ok AND
    topic_slug is non-empty. Sorted by `order` so the answer cards
    follow the chapter's intended pedagogical sequence.
    """
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")

    cursor = (
        db.topics
        .find(
            {
                "chapter_id": chapter_id,
                "status": "published",
                "definition_status": DEFINITION_STATUS_OK,
                "topic_slug": {"$exists": True, "$nin": [None, ""]},
            },
            {"_id": 0, "id": 1, "topic_slug": 1, "title": 1, "definition": 1, "order": 1},
        )
        .sort("order", 1)
    )
    rows = await cursor.to_list(200)
    topics = [_project_topic(t) for t in rows]
    if response is not None:
        response.headers["Cache-Control"] = _CACHE_HEADER
    return {"chapter_id": chapter_id, "topics": topics, "count": len(topics)}


@router.get("/content/chapters/{chapter_id}/topics/{topic_slug}")
async def get_published_topic(
    chapter_id: str, topic_slug: str, response: Response = None,
) -> dict[str, Any]:
    """Single-topic resolver for the `/.../<chapter>/topic/<slug>` route.

    Returns 404 for unknown slugs, unpublished topics, OR topics with
    `definition_status != ok` so the frontend can short-circuit to a
    clean 404 instead of rendering an empty answer card.
    """
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")

    topic = await db.topics.find_one(
        {
            "chapter_id": chapter_id,
            "topic_slug": topic_slug,
            "status": "published",
            "definition_status": DEFINITION_STATUS_OK,
        },
        {"_id": 0, "id": 1, "topic_slug": 1, "title": 1, "definition": 1, "order": 1},
    )
    if not topic:
        raise HTTPException(404, "Topic not found or not yet citable")
    if response is not None:
        response.headers["Cache-Control"] = _CACHE_HEADER
    return {"chapter_id": chapter_id, "topic": _project_topic(topic)}
