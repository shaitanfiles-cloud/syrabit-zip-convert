"""End-to-end style tests verifying that admin subject/chapter CRUD endpoints
fire IndexNow notifications. Calls the actual route handler functions with
mocked DB and a recording IndexNow batcher.
"""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock


def _install_stubs():
    if "deps" not in sys.modules:
        deps = types.ModuleType("deps")
        deps.db = MagicMock()
        deps.is_mongo_available = AsyncMock(return_value=False)
        sys.modules["deps"] = deps


_install_stubs()


def _make_fake_batcher():
    queued: list[list[str]] = []
    flush_calls: list[str] = []

    fake = MagicMock()

    async def _queue(paths):
        queued.append(list(paths))

    async def _flush(source: str = ""):
        flush_calls.append(source)

    fake.queue_raw_paths = AsyncMock(side_effect=_queue)
    fake.flush = AsyncMock(side_effect=_flush)
    return fake, queued, flush_calls


def _install_batcher(fake):
    from routes import bot_discovery
    bot_discovery.indexnow_batcher = fake


async def _drain():
    for _ in range(15):
        await asyncio.sleep(0)


def test_admin_patch_subject_endpoint_fires_indexnow():
    """Calling PATCH /admin/content/subjects/{id} should trigger IndexNow
    with the subject's full path (board/class/subject)."""
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)

        from routes import admin_content

        fake_db = MagicMock()
        fake_db.subjects.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )
        fake_db.subjects.find_one = AsyncMock(return_value={
            "board_slug": "ahsec",
            "class_slug": "class-12",
            "slug": "physics",
        })
        admin_content.db = fake_db
        admin_content._invalidate_content_cache = lambda *a, **kw: None
        admin_content._schedule_d1_sync_fire = lambda *a, **kw: None

        result = await admin_content.admin_patch_subject(
            "subj-id-1",
            {"name": "Physics Updated"},
            admin={"id": "admin"},
        )
        await _drain()

        assert result == {"message": "Subject updated"}
        fake_db.subjects.update_one.assert_awaited_once()
        assert queued == [["/ahsec/class-12/physics"]]
        assert flush_calls == ["admin_subject_update"]

    asyncio.run(run())


def test_admin_patch_subject_404_does_not_fire_indexnow():
    """If the subject doesn't exist (HTTP 404), no IndexNow call should be made."""
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)

        from fastapi import HTTPException
        from routes import admin_content

        fake_db = MagicMock()
        fake_db.subjects.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0)
        )
        fake_db.subjects.find_one = AsyncMock()
        admin_content.db = fake_db
        admin_content._invalidate_content_cache = lambda *a, **kw: None
        admin_content._schedule_d1_sync_fire = lambda *a, **kw: None

        try:
            await admin_content.admin_patch_subject(
                "missing", {"name": "X"}, admin={"id": "admin"}
            )
            raised = False
        except HTTPException as exc:
            raised = exc.status_code == 404
        await _drain()

        assert raised is True
        assert queued == []
        assert flush_calls == []

    asyncio.run(run())


def test_admin_update_chapter_endpoint_fires_indexnow():
    """Calling PATCH /admin/content/chapters/{id} should trigger IndexNow
    with the chapter's full path (board/class/subject/chapter)."""
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)

        from routes import admin_content

        fake_db = MagicMock()
        fake_db.chapters.update_one = AsyncMock(
            return_value=MagicMock(matched_count=1)
        )
        # Chapter find_one used twice: once for slug-dup check (skipped — no slug
        # in payload), once for indexnow at line 1813.
        fake_db.chapters.find_one = AsyncMock(return_value={
            "subject_id": "subj-1",
            "slug": "algebra",
        })
        # Subject lookup performed inside _schedule_indexnow_for_chapter
        fake_db.subjects.find_one = AsyncMock(return_value={
            "board_slug": "seba",
            "class_slug": "class-10",
            "slug": "maths",
        })
        admin_content.db = fake_db
        admin_content._invalidate_content_cache = lambda *a, **kw: None
        admin_content._schedule_d1_sync_fire = lambda *a, **kw: None
        # Ensure the deps stub also serves the same DB for the chapter helper
        sys.modules["deps"].db = fake_db

        result = await admin_content.admin_update_chapter(
            "chap-id-1",
            {"description": "Updated description"},
            admin={"id": "admin"},
        )
        await _drain()

        assert result.get("message") == "Chapter updated"
        fake_db.chapters.update_one.assert_awaited_once()
        assert queued == [["/seba/class-10/maths/algebra"]]
        assert flush_calls == ["admin_chapter_update"]

    asyncio.run(run())


def test_admin_update_chapter_404_does_not_fire_indexnow():
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)

        from fastapi import HTTPException
        from routes import admin_content

        fake_db = MagicMock()
        fake_db.chapters.update_one = AsyncMock(
            return_value=MagicMock(matched_count=0)
        )
        fake_db.chapters.find_one = AsyncMock()
        admin_content.db = fake_db
        admin_content._invalidate_content_cache = lambda *a, **kw: None
        admin_content._schedule_d1_sync_fire = lambda *a, **kw: None

        try:
            await admin_content.admin_update_chapter(
                "missing", {"description": "x"}, admin={"id": "admin"}
            )
            raised = False
        except HTTPException as exc:
            raised = exc.status_code == 404
        await _drain()

        assert raised is True
        assert queued == []
        assert flush_calls == []

    asyncio.run(run())
