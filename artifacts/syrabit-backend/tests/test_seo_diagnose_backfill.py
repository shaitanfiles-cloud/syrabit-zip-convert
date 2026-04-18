"""Task #460 — integration tests for the Task #457 admin SEO endpoints.

Covers:
  * GET  /seo/diagnose-topics  — per-topic blocker report (status,
                                 hierarchy, coverage, last_error from
                                 recent run logs, summary aggregation
                                 over ALL topics even when items list
                                 is truncated by ``limit``).
  * POST /seo/backfill-notes   — one-shot notes backfill that registers
                                 a job in the in-memory tracker and
                                 enqueues ``_auto_run_bg`` on the
                                 BackgroundTasks queue.

Both handlers are exercised by calling them directly with a mocked
``_db`` rather than spinning up a TestClient — the auth dependency and
BackgroundTasks plumbing are FastAPI machinery already covered by
framework tests; what matters here is the per-topic logic, the summary
aggregation, and the job-bookkeeping contract that the admin UI
depends on.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi import BackgroundTasks

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import seo_engine  # noqa: E402
from seo_engine import (  # noqa: E402
    PAGE_TYPES,
    _seo_jobs,
    backfill_notes,
    diagnose_topics,
)


def _run(coro):
    """Robust against test ordering that may have closed the default
    event loop (some upstream tests do). asyncio.run creates a fresh
    loop for every call."""
    return asyncio.run(coro)


# ─── Fake Mongo plumbing ────────────────────────────────────────────────────


class _FakeCursor:
    """Minimal motor-like async cursor supporting .sort().limit().to_list().

    `.limit(n)` actually truncates so tests can verify pagination/log
    cap semantics — a no-op limit would silently mask regressions in
    code that relies on the cursor honouring the cap (e.g. the
    20-most-recent log lookup in /seo/diagnose-topics)."""

    def __init__(self, items):
        self._items = list(items)
        self._limit: int | None = None

    def sort(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._limit = int(n) if n is not None else None
        return self

    async def to_list(self, n):
        cap = min(x for x in (self._limit, n) if x is not None) \
            if (self._limit is not None or n is not None) else None
        return list(self._items if cap is None else self._items[:cap])


def _make_fake_db(*, topics, chapters, subjects, seo_pages, recent_logs=None):
    """Build a MagicMock DB whose collections behave like motor's
    AsyncIOMotorCollection for the queries diagnose-topics issues."""
    db = MagicMock()

    # topics.find({}) → cursor over ALL topics
    db.topics.find = MagicMock(return_value=_FakeCursor(topics))

    # chapters/subjects/seo_pages: lookups by id
    chapter_by_id = {c["id"]: c for c in chapters}
    subject_by_id = {s["id"]: s for s in subjects}

    async def _chapters_find_one(query, _proj=None):
        return chapter_by_id.get(query.get("id"))

    async def _subjects_find_one(query, _proj=None):
        return subject_by_id.get(query.get("id"))

    db.chapters.find_one = AsyncMock(side_effect=_chapters_find_one)
    db.subjects.find_one = AsyncMock(side_effect=_subjects_find_one)

    pages_by_topic: dict[str, list[dict]] = {}
    for p in seo_pages:
        pages_by_topic.setdefault(p["topic_id"], []).append(p)

    def _seo_pages_find(query, _proj=None):
        return _FakeCursor(pages_by_topic.get(query.get("topic_id", ""), []))

    db.seo_pages.find = MagicMock(side_effect=_seo_pages_find)

    # seo_generation_log.find({...}).sort(...).limit(...).to_list(...)
    db.seo_generation_log.find = MagicMock(
        return_value=_FakeCursor(recent_logs or [])
    )
    return db


# ─── /seo/diagnose-topics ───────────────────────────────────────────────────


def test_diagnose_topics_returns_empty_when_db_uninitialised():
    seo_engine._db = None
    res = _run(diagnose_topics(limit=10, only_blocked=True, _admin={"id": "a"}))
    assert res == {"items": [], "summary": {}}


def test_diagnose_topics_summary_classifies_blocked_ready_and_covered():
    """Three topics: one blocked (no chapter), one ready (has hierarchy
    but no pages), one fully covered (has every PAGE_TYPES page)."""
    topics = [
        {"id": "t-blocked", "title": "Orphan Topic", "chapter_id": "missing"},
        {"id": "t-ready", "title": "Ready Topic", "chapter_id": "c1",
         "status": "draft"},
        {"id": "t-covered", "title": "Covered Topic", "chapter_id": "c1",
         "status": "published"},
    ]
    chapters = [{"id": "c1", "subject_id": "s1", "title": "Ch1"}]
    subjects = [{"id": "s1", "name": "Physics", "slug": "physics"}]
    # Cover every PAGE_TYPES page for t-covered so it counts as fully_covered.
    seo_pages = [
        {"topic_id": "t-covered", "page_type": pt, "status": "published"}
        for pt in PAGE_TYPES
    ]
    seo_engine._db = _make_fake_db(
        topics=topics, chapters=chapters, subjects=subjects,
        seo_pages=seo_pages,
    )

    res = _run(diagnose_topics(limit=50, only_blocked=False,
                               _admin={"id": "a"}))
    s = res["summary"]
    assert s["total"] == 3
    # One missing-chapter blocker + one fully-covered (also a blocker)
    assert s["blocked"] == 2
    assert s["ready"] == 1
    assert s["fully_covered"] == 1
    # Reasons map aggregates blocker labels
    assert s["reasons"].get("missing chapter") == 1
    assert s["reasons"].get("all page types already generated") == 1


def test_diagnose_topics_only_blocked_filters_items_but_summary_covers_all():
    """Regression: the summary must reflect ALL topics even though the
    items list is filtered by only_blocked / truncated by limit. The
    admin diagnostics panel relies on this invariant."""
    topics = [
        {"id": f"t{i}", "title": f"T{i}", "chapter_id": "c1",
         "status": "published"}
        for i in range(5)
    ]
    # First topic is blocked (status=archived); the rest are ready.
    topics[0]["status"] = "archived"
    chapters = [{"id": "c1", "subject_id": "s1", "title": "Ch1"}]
    subjects = [{"id": "s1", "name": "Physics", "slug": "physics"}]
    seo_engine._db = _make_fake_db(
        topics=topics, chapters=chapters, subjects=subjects, seo_pages=[],
    )

    res = _run(diagnose_topics(limit=50, only_blocked=True,
                               _admin={"id": "a"}))
    # Only the archived topic appears in items
    assert len(res["items"]) == 1
    assert res["items"][0]["topic_id"] == "t0"
    assert any(b.startswith("status=archived") for b in res["items"][0]["blockers"])
    # …but the summary saw all 5 topics and counted 4 ready + 1 blocked
    assert res["summary"]["total"] == 5
    assert res["summary"]["blocked"] == 1
    assert res["summary"]["ready"] == 4


def test_diagnose_topics_summary_covers_all_topics_when_items_truncated_by_limit():
    """Critical admin-UI invariant (called out in the docstring of the
    handler): when the items list is truncated by the ``limit`` query
    parameter, the summary counters must STILL reflect every topic in
    the database, not just the ones surfaced in items. A regression
    that computed the summary inside the truncation loop would silently
    under-report blockers."""
    topics = [
        {"id": f"t{i}", "title": f"T{i}", "chapter_id": "missing-chapter"}
        for i in range(7)
    ]  # All 7 are blocked (missing chapter)
    seo_engine._db = _make_fake_db(
        topics=topics, chapters=[], subjects=[], seo_pages=[],
    )

    res = _run(diagnose_topics(limit=2, only_blocked=True,
                               _admin={"id": "a"}))
    # Items truncated to 2 even though 7 topics qualify…
    assert len(res["items"]) == 2
    # …but summary saw all 7 and counted every one as blocked.
    assert res["summary"]["total"] == 7
    assert res["summary"]["blocked"] == 7
    assert res["summary"]["ready"] == 0
    assert res["summary"]["reasons"].get("missing chapter") == 7


def test_diagnose_topics_attaches_last_error_from_recent_run_logs():
    """When a recent seo_generation_log entry contains a failed/skipped
    outcome for the topic, diagnose-topics must surface it as
    last_error so the admin sees the actionable failure context."""
    topics = [{"id": "t1", "title": "Atoms", "chapter_id": "missing"}]
    recent_logs = [
        {
            "job_id": "job-abc",
            "completed_at": "2026-04-18T10:00:00Z",
            "outcomes": [
                {"topic_id": "t1", "status": "failed",
                 "reason": "llm_timeout", "page_type": "notes",
                 "ts": "2026-04-18T09:59:00Z"},
                # Successful outcome must NOT overwrite a failure
                {"topic_id": "t1", "status": "ok", "page_type": "mcqs",
                 "reason": "", "ts": "2026-04-18T09:58:00Z"},
            ],
        }
    ]
    seo_engine._db = _make_fake_db(
        topics=topics, chapters=[], subjects=[], seo_pages=[],
        recent_logs=recent_logs,
    )

    res = _run(diagnose_topics(limit=50, only_blocked=True,
                               _admin={"id": "a"}))
    assert len(res["items"]) == 1
    item = res["items"][0]
    assert item["last_error"] is not None
    assert item["last_error"]["status"] == "failed"
    assert item["last_error"]["reason"] == "llm_timeout"
    assert item["last_error"]["page_type"] == "notes"
    assert item["last_error"]["job_id"] == "job-abc"


def test_diagnose_topics_last_error_keeps_first_failure_seen_per_topic():
    """The handler iterates recent_logs (already ordered most-recent
    first by .sort('completed_at', -1)) and outcomes within each log,
    keeping the FIRST failed/skipped outcome it encounters per topic.
    Subsequent failures or any successful outcomes for the same topic
    must NOT overwrite it. Guards the 'most recent error wins' UX."""
    topics = [{"id": "t1", "title": "Atoms", "chapter_id": "missing"}]
    recent_logs = [
        # Most recent log (sort -1 puts this first)
        {
            "job_id": "job-newest",
            "completed_at": "2026-04-18T12:00:00Z",
            "outcomes": [
                {"topic_id": "t1", "status": "skipped",
                 "reason": "no_hierarchy", "page_type": "notes",
                 "ts": "2026-04-18T11:59:00Z"},
            ],
        },
        # Older log — its failure must NOT overwrite the newer one
        {
            "job_id": "job-older",
            "completed_at": "2026-04-17T12:00:00Z",
            "outcomes": [
                {"topic_id": "t1", "status": "failed",
                 "reason": "llm_timeout", "page_type": "mcqs",
                 "ts": "2026-04-17T11:59:00Z"},
            ],
        },
    ]
    seo_engine._db = _make_fake_db(
        topics=topics, chapters=[], subjects=[], seo_pages=[],
        recent_logs=recent_logs,
    )
    res = _run(diagnose_topics(limit=10, only_blocked=True,
                               _admin={"id": "a"}))
    err = res["items"][0]["last_error"]
    # Newest log's outcome wins.
    assert err["job_id"] == "job-newest"
    assert err["status"] == "skipped"
    assert err["reason"] == "no_hierarchy"


def test_diagnose_topics_marks_each_pagetype_in_coverage_map():
    """The coverage map is the shape the admin UI iterates over to draw
    the per-page-type checkmarks; every PAGE_TYPES key must be present
    and only the truly-existing types should be True."""
    topics = [{"id": "t1", "title": "Cells", "chapter_id": "c1",
               "status": "published"}]
    chapters = [{"id": "c1", "subject_id": "s1", "title": "Ch1"}]
    subjects = [{"id": "s1", "name": "Bio", "slug": "bio"}]
    seo_pages = [
        {"topic_id": "t1", "page_type": "notes", "status": "published"},
        {"topic_id": "t1", "page_type": "mcqs", "status": "draft"},
    ]
    seo_engine._db = _make_fake_db(
        topics=topics, chapters=chapters, subjects=subjects,
        seo_pages=seo_pages,
    )
    res = _run(diagnose_topics(limit=50, only_blocked=False,
                               _admin={"id": "a"}))
    item = res["items"][0]
    assert item["hierarchy_resolved"] is True
    assert item["has_existing_page"] is True
    assert item["page_count"] == 2
    cov = item["coverage"]
    assert set(cov.keys()) == set(PAGE_TYPES)
    assert cov["notes"] is True and cov["mcqs"] is True
    assert all(cov[pt] is False for pt in PAGE_TYPES
               if pt not in ("notes", "mcqs"))


# ─── /seo/backfill-notes ────────────────────────────────────────────────────


def test_backfill_notes_registers_job_and_enqueues_background_task():
    """Endpoint must: (a) return a job_id, (b) seed _seo_jobs with a
    queued record tagged kind='backfill-notes' / page_types=['notes'],
    (c) enqueue exactly one BackgroundTasks entry calling _auto_run_bg
    with the new job_id and ['notes']."""
    # Replace the long-running pipeline with a noop so even if the
    # background task ever fires (it shouldn't here) it cannot blow up.
    original = seo_engine._auto_run_bg
    seo_engine._auto_run_bg = AsyncMock()
    try:
        bg = BackgroundTasks()
        res = _run(backfill_notes(background_tasks=bg, _admin={"id": "a"}))

        assert res["status"] == "queued"
        assert res["message"] == "Notes backfill started"
        jid = res["job_id"]
        assert jid.startswith("job-")

        # In-memory job ledger
        assert jid in _seo_jobs
        job = _seo_jobs[jid]
        assert job["status"] == "queued"
        assert job["kind"] == "backfill-notes"
        assert job["page_types"] == ["notes"]
        assert job["total"] == 0 and job["done"] == 0
        assert job["finished_at"] is None
        assert job["started_at"]

        # Exactly one background task scheduled, bound to _auto_run_bg
        # with the freshly minted job_id and the notes-only page list.
        assert len(bg.tasks) == 1
        task = bg.tasks[0]
        assert task.func is seo_engine._auto_run_bg
        assert task.args == (jid, ["notes"])
    finally:
        seo_engine._auto_run_bg = original
        _seo_jobs.pop(res["job_id"], None)


def test_backfill_notes_each_call_produces_unique_job_id():
    original = seo_engine._auto_run_bg
    seo_engine._auto_run_bg = AsyncMock()
    created = []
    try:
        for _ in range(3):
            bg = BackgroundTasks()
            r = _run(backfill_notes(background_tasks=bg,
                                    _admin={"id": "a"}))
            created.append(r["job_id"])
        assert len(set(created)) == 3, "job_ids must be unique"
    finally:
        seo_engine._auto_run_bg = original
        for jid in created:
            _seo_jobs.pop(jid, None)
