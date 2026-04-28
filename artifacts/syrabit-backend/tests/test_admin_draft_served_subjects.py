"""Task #701 — admin endpoint + publish-clear integration coverage.

Verifies that:
  - GET /admin/content/draft-served-subjects returns the entries recorded by
    the resolver via the cross-worker tracker.
  - PATCH /admin/content/subjects/{id} with status="published" clears the
    matching tracker entry (single-source-of-truth across requests).
  - The bulk-status endpoint clears entries on bulk publish.
  - Non-publish updates do NOT clear the entry.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _reset_tracker(content):
    content._DRAFT_SERVED_FALLBACK.clear()
    rc = content._draft_served_redis()
    if rc is not None:
        try:
            rc.delete(content._DRAFT_SERVED_REDIS_KEY)
        except Exception:
            pass


_PATCHED_ATTRS = (
    "db",
    "_invalidate_content_cache",
    "_schedule_d1_sync_fire",
    "_schedule_indexnow_for_subject",
    "_schedule_prerender_refresh",
)


def _snapshot(mod):
    return {a: getattr(mod, a, None) for a in _PATCHED_ATTRS}


def _restore(mod, snap):
    for a, v in snap.items():
        setattr(mod, a, v)


def test_admin_endpoint_lists_recorded_entries():
    async def run():
        from routes import content, admin_content
        _reset_tracker(content)

        content._record_draft_served({
            "id": "subj-A", "slug": "biology", "name": "Biology", "status": "draft",
        })
        content._record_draft_served({
            "id": "subj-B", "slug": "physics", "name": "Physics", "status": "unpublished",
        })

        res = await admin_content.admin_draft_served_subjects(admin={"id": "admin"})
        assert res["total"] == 2
        ids = {it["id"] for it in res["items"]}
        assert ids == {"subj-A", "subj-B"}

    asyncio.run(run())


def test_publish_patch_clears_tracker_entry():
    from routes import admin_content
    _orig = _snapshot(admin_content)
    async def run():
        from routes import content, admin_content
        _reset_tracker(content)

        content._record_draft_served({
            "id": "subj-A", "slug": "biology", "name": "Biology", "status": "draft",
        })
        assert any(it["id"] == "subj-A" for it in content.get_draft_served_subjects())

        fake_db = MagicMock()
        fake_db.subjects.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        fake_db.subjects.find_one = AsyncMock(return_value={
            "board_slug": "ahsec", "class_slug": "class-12", "slug": "biology",
        })
        admin_content.db = fake_db
        admin_content._invalidate_content_cache = lambda *a, **kw: None
        admin_content._schedule_d1_sync_fire = lambda *a, **kw: None
        admin_content._schedule_indexnow_for_subject = lambda *a, **kw: None
        admin_content._schedule_prerender_refresh = lambda *a, **kw: None

        await admin_content.admin_patch_subject(
            "subj-A", {"status": "published"}, admin={"id": "admin"},
        )

        items = content.get_draft_served_subjects()
        assert all(it["id"] != "subj-A" for it in items)

    try:
        asyncio.run(run())
    finally:
        _restore(admin_content, _orig)


def test_non_publish_patch_does_not_clear_tracker():
    from routes import admin_content
    _orig = _snapshot(admin_content)
    async def run():
        from routes import content, admin_content
        _reset_tracker(content)

        content._record_draft_served({
            "id": "subj-A", "slug": "biology", "name": "Biology", "status": "draft",
        })

        fake_db = MagicMock()
        fake_db.subjects.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        fake_db.subjects.find_one = AsyncMock(return_value={
            "board_slug": "ahsec", "class_slug": "class-12", "slug": "biology",
        })
        admin_content.db = fake_db
        admin_content._invalidate_content_cache = lambda *a, **kw: None
        admin_content._schedule_d1_sync_fire = lambda *a, **kw: None
        admin_content._schedule_indexnow_for_subject = lambda *a, **kw: None
        admin_content._schedule_prerender_refresh = lambda *a, **kw: None

        # A name-only edit must NOT silently clear the drift entry.
        await admin_content.admin_patch_subject(
            "subj-A", {"name": "Biology v2"}, admin={"id": "admin"},
        )

        items = content.get_draft_served_subjects()
        assert any(it["id"] == "subj-A" for it in items)

    try:
        asyncio.run(run())
    finally:
        _restore(admin_content, _orig)


def test_bulk_publish_clears_tracker_entries():
    from routes import admin_content
    _orig = _snapshot(admin_content)
    async def run():
        from routes import content, admin_content
        _reset_tracker(content)

        for sid in ("subj-A", "subj-B", "subj-C"):
            content._record_draft_served({"id": sid, "slug": sid, "name": sid, "status": "draft"})

        fake_db = MagicMock()
        fake_db.subjects.update_many = AsyncMock(
            return_value=MagicMock(matched_count=2, modified_count=2)
        )

        async def _empty_aiter(*_a, **_kw):
            if False:
                yield None
        fake_db.subjects.find = MagicMock(side_effect=lambda *a, **kw: _empty_aiter())

        admin_content.db = fake_db
        admin_content._invalidate_content_cache = lambda *a, **kw: None
        admin_content._schedule_d1_sync_fire = lambda *a, **kw: None
        admin_content._schedule_indexnow_for_subject = lambda *a, **kw: None
        admin_content._schedule_prerender_refresh = lambda *a, **kw: None

        await admin_content.admin_bulk_status_update(
            {"scope": "subjects", "ids": ["subj-A", "subj-B"], "status": "published"},
            admin={"id": "admin"},
        )

        items = content.get_draft_served_subjects()
        ids = {it["id"] for it in items}
        # Only subj-C remains; A and B were bulk-published.
        assert ids == {"subj-C"}

    try:
        asyncio.run(run())
    finally:
        _restore(admin_content, _orig)
