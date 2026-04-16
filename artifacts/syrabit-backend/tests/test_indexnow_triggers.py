"""Tests for IndexNow scheduling helpers in admin_content."""
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
    # Allow scheduled tasks to run
    for _ in range(10):
        await asyncio.sleep(0)


def test_subject_indexnow_schedules_correct_path():
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)
        from routes.admin_content import _schedule_indexnow_for_subject

        _schedule_indexnow_for_subject({
            "board_slug": "ahsec",
            "class_slug": "class-12",
            "slug": "physics",
        })
        await _drain()

        assert queued == [["/ahsec/class-12/physics"]]
        assert flush_calls == ["admin_subject_update"]

    asyncio.run(run())


def test_subject_indexnow_skipped_when_fields_missing():
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)
        from routes.admin_content import _schedule_indexnow_for_subject

        _schedule_indexnow_for_subject({"board_slug": "ahsec", "slug": ""})
        await _drain()

        assert queued == []
        assert flush_calls == []

    asyncio.run(run())


def test_chapter_indexnow_schedules_correct_path():
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)

        fake_db = MagicMock()
        fake_db.subjects.find_one = AsyncMock(return_value={
            "board_slug": "seba",
            "class_slug": "class-10",
            "slug": "maths",
        })
        sys.modules["deps"].db = fake_db

        from routes.admin_content import _schedule_indexnow_for_chapter
        _schedule_indexnow_for_chapter({
            "subject_id": "subj-123",
            "slug": "algebra",
        })
        await _drain()

        assert queued == [["/seba/class-10/maths/algebra"]]
        assert flush_calls == ["admin_chapter_update"]

    asyncio.run(run())


def test_chapter_indexnow_no_subject_match():
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)

        fake_db = MagicMock()
        fake_db.subjects.find_one = AsyncMock(return_value=None)
        sys.modules["deps"].db = fake_db

        from routes.admin_content import _schedule_indexnow_for_chapter
        _schedule_indexnow_for_chapter({
            "subject_id": "missing",
            "slug": "algebra",
        })
        await _drain()

        assert queued == []
        assert flush_calls == []

    asyncio.run(run())


def test_chapter_indexnow_skipped_when_fields_missing():
    async def run():
        fake, queued, flush_calls = _make_fake_batcher()
        _install_batcher(fake)
        from routes.admin_content import _schedule_indexnow_for_chapter

        _schedule_indexnow_for_chapter({"subject_id": "", "slug": "algebra"})
        await _drain()

        assert queued == []
        assert flush_calls == []

    asyncio.run(run())
