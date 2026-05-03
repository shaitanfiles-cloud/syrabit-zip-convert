"""Task #700 — chapter resolution regression coverage.

Two failure modes have repeatedly surfaced as "Chapter not found" in
production even though the chapter document existed:

1. The streamSlug-bearing URL variant
   (``/{board}/{class}/{stream}/{subject}/{chapter}``) wasn't routing
   through the resolver correctly.
2. The slug-hierarchy resolver enforced ``status: "published"`` on the
   subject. If an admin flipped a subject to ``draft`` / ``unpublished``
   (or a legacy row had no status), every chapter under it 404'd even
   though the chapter content was still complete.

These tests exercise the resolver via the FastAPI router with a stubbed
Mongo so a single missing branch (or a re-introduction of the strict
status filter) fails the build.
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_async_cursor(rows):
    """Return an object that mimics motor's `find().to_list(N)`."""
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=list(rows))
    return cursor


@pytest.fixture
def chapter_app(monkeypatch):
    monkeypatch.setenv("ADMIN_JWT_SECRET", "c" * 64)

    for mod in ("config", "routes.content"):
        sys.modules.pop(mod, None)

    from tests._deps_stub import install_deps_stub
    deps = install_deps_stub(force=True, is_mongo_available_value=True)

    db = deps.db

    # Reset cached state from prior tests.
    importlib.import_module("config")
    content = importlib.import_module("routes.content")
    content._slug_hierarchy_cache.clear()
    from cache import _content_cache as _cc, _invalidate_content_cache
    _cc.clear()

    # Wire up minimal hierarchy: degree → semester-2 → mdc → biology
    board = {"id": "b1", "slug": "degree", "name": "Degree"}
    cls = {"id": "c1", "slug": "semester-2", "name": "Semester 2", "board_id": "b1"}
    stream = {"id": "st1", "slug": "mdc", "name": "MDC", "class_id": "c1"}

    db.boards.find_one = AsyncMock(return_value=board)
    db.classes.find_one = AsyncMock(return_value=cls)
    db.streams.find = MagicMock(return_value=_make_async_cursor([stream]))
    db.streams.find_one = AsyncMock(return_value=stream)

    state = {"subject_status": "published"}

    async def _subjects_find_one(query, *_a, **_kw):
        # Honour the `status` filter the resolver passes.
        status_q = query.get("status")
        published_only = status_q == "published"
        archived_excluded = (
            isinstance(status_q, dict) and status_q.get("$ne") == "archived"
        )
        if state["subject_status"] == "archived":
            return None
        if published_only and state["subject_status"] != "published":
            return None
        if not (published_only or archived_excluded or status_q is None):
            return None
        return {
            "id": "subj1",
            "slug": "biology",
            "name": "Biology",
            "stream_id": "st1",
            "status": state["subject_status"],
        }

    db.subjects.find_one = AsyncMock(side_effect=_subjects_find_one)

    chapter_doc = {
        "id": "ch1",
        "slug": "cell-structure",
        "subject_id": "subj1",
        "title": "Cell Structure",
        "content": "## Cell Structure\n\nA cell is the basic unit of life.",
        "status": "published",
    }

    async def _chapters_find_one(query, *_a, **_kw):
        if query.get("slug") == "cell-structure" and query.get("subject_id") == "subj1":
            return dict(chapter_doc)
        return None

    db.chapters.find_one = AsyncMock(side_effect=_chapters_find_one)
    db.chapters.find = MagicMock(return_value=_make_async_cursor([dict(chapter_doc)]))

    # Topic-content / pyq endpoints aren't under test — make them inert.
    db.topics = MagicMock()
    db.topics.find = MagicMock(return_value=_make_async_cursor([]))
    db.chunks = MagicMock()
    db.chunks.find = MagicMock(return_value=_make_async_cursor([]))

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(content.router, prefix="/api")
    client = TestClient(app)
    return client, state, content


def test_chapter_by_slug_happy_path(chapter_app):
    client, _state, _content = chapter_app
    res = client.get("/api/content/chapter-by-slug/degree/semester-2/biology/cell-structure")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("chapter_id") == "ch1"


def test_chapter_by_slug_with_stream_variant(chapter_app):
    """The 5-segment URL (with a streamSlug between class and subject)
    must resolve the same chapter — this branch was historically the
    silent 404 source for question-paper deep-links."""
    client, _state, _content = chapter_app
    res = client.get(
        "/api/content/chapter-by-slug/degree/semester-2/mdc/biology/cell-structure"
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("chapter_id") == "ch1"


def test_chapter_resolves_when_subject_is_draft(chapter_app):
    """Regression: an admin saving a subject as `draft` must NOT 404
    every chapter underneath it. The resolver retries with the relaxed
    status filter and surfaces the chapter content."""
    client, state, content = chapter_app
    state["subject_status"] = "draft"
    content._slug_hierarchy_cache.clear()
    res = client.get("/api/content/chapter-by-slug/degree/semester-2/biology/cell-structure")
    assert res.status_code == 200, res.text


def test_chapter_404s_when_subject_is_archived(chapter_app):
    """Archived is the explicit tombstone state — these should still 404."""
    client, state, content = chapter_app
    state["subject_status"] = "archived"
    content._slug_hierarchy_cache.clear()
    res = client.get("/api/content/chapter-by-slug/degree/semester-2/biology/cell-structure")
    assert res.status_code == 404


def test_draft_served_subjects_tracked(chapter_app):
    """Task #701 — when the resolver matches a subject via the relaxed
    status filter, that subject is recorded in the in-memory tracker so
    the admin Control Center can surface it. Publishing the subject
    (clearing the tracker entry) removes it from the list."""
    client, state, content = chapter_app
    content._DRAFT_SERVED_FALLBACK.clear()
    state["subject_status"] = "draft"
    content._slug_hierarchy_cache.clear()

    # First hit — recorded.
    res = client.get("/api/content/chapter-by-slug/degree/semester-2/biology/cell-structure")
    assert res.status_code == 200, res.text
    items = content.get_draft_served_subjects()
    assert len(items) == 1
    entry = items[0]
    assert entry["id"] == "subj1"
    assert entry["slug"] == "biology"
    assert entry["status"] == "draft"
    assert entry["count"] == 1
    assert entry["last_served_at"]

    # Second hit — count increments, no duplicate row. Clear both the
    # slug-hierarchy cache and the chapter response cache so the resolver
    # actually runs again instead of short-circuiting.
    content._slug_hierarchy_cache.clear()
    from cache import _content_cache as _cc2
    _cc2.clear()
    res = client.get("/api/content/chapter-by-slug/degree/semester-2/biology/cell-structure")
    assert res.status_code == 200
    items = content.get_draft_served_subjects()
    assert len(items) == 1
    assert items[0]["count"] == 2

    # Clearing (publish hook) removes the entry.
    assert content.clear_draft_served_subject("subj1") is True
    assert content.get_draft_served_subjects() == []
    assert content.clear_draft_served_subject("subj1") is False


def test_published_subject_not_tracked(chapter_app):
    """A normally-published subject must NOT be recorded in the
    draft-served tracker — the WARN/record path is gated behind the
    relaxed-filter retry."""
    client, state, content = chapter_app
    content._DRAFT_SERVED_FALLBACK.clear()
    state["subject_status"] = "published"
    content._slug_hierarchy_cache.clear()
    res = client.get("/api/content/chapter-by-slug/degree/semester-2/biology/cell-structure")
    assert res.status_code == 200
    assert content.get_draft_served_subjects() == []
