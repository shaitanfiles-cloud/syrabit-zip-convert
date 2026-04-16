"""Tests for the IndexNow sitemap-diff edited-URL detection.

Covers `_ensure_utc` (datetime/ISO normalization) and
`_collect_edited_url_mtimes` for subjects, chapters, seo_pages, and
cms_documents.

End-to-end test of `diff_sitemap_against_submitted` confirms that an
edited library page (subject/chapter) is queued for re-submission when
its `updated_at` is newer than `last_submitted_at`, respects the dedupe
window, and is correctly batched with the existing seo_pages /
cms_documents edit path.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# _ensure_utc
# ---------------------------------------------------------------------------

def test_ensure_utc_handles_aware_datetime():
    from routes.bot_discovery import _ensure_utc
    dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert _ensure_utc(dt) == dt


def test_ensure_utc_promotes_naive_datetime_to_utc():
    from routes.bot_discovery import _ensure_utc
    naive = datetime(2026, 1, 1, 12, 0)
    out = _ensure_utc(naive)
    assert out is not None
    assert out.tzinfo is timezone.utc


def test_ensure_utc_parses_iso_string_with_offset():
    from routes.bot_discovery import _ensure_utc
    out = _ensure_utc("2026-01-01T12:00:00+00:00")
    assert out == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_ensure_utc_parses_iso_string_with_z_suffix():
    from routes.bot_discovery import _ensure_utc
    out = _ensure_utc("2026-01-01T12:00:00Z")
    assert out == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_ensure_utc_parses_naive_iso_string_as_utc():
    from routes.bot_discovery import _ensure_utc
    out = _ensure_utc("2026-01-01T12:00:00")
    assert out is not None
    assert out.tzinfo is timezone.utc


def test_ensure_utc_returns_none_for_garbage():
    from routes.bot_discovery import _ensure_utc
    assert _ensure_utc(None) is None
    assert _ensure_utc("") is None
    assert _ensure_utc("not-a-date") is None
    assert _ensure_utc(12345) is None


# ---------------------------------------------------------------------------
# Helpers for stubbing the Mongo db handle used inside bot_discovery.
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Async cursor that supports both `async for` iteration and `to_list`."""
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()

    async def to_list(self, length=None):
        if length is None:
            return list(self._docs)
        return list(self._docs)[:length]


class _FakeCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, *_args, **_kwargs):
        return _FakeCursor(self._docs)


def _patch_db(monkeypatch, *, subjects=(), chapters=(), streams=(), classes=(),
              boards=(), seo_pages=(), cms_documents=()):
    """Install a fake `db` and `is_mongo_available` on routes.bot_discovery.

    Returns the fake db so tests can inspect or extend it.
    """
    import routes.bot_discovery as bd

    fake_db = MagicMock()
    fake_db.subjects = _FakeCollection(subjects)
    fake_db.chapters = _FakeCollection(chapters)
    fake_db.streams = _FakeCollection(streams)
    fake_db.classes = _FakeCollection(classes)
    fake_db.boards = _FakeCollection(boards)
    fake_db.seo_pages = _FakeCollection(seo_pages)
    fake_db.cms_documents = _FakeCollection(cms_documents)

    # Patch the `from deps import db, is_mongo_available` calls inside
    # the helpers by replacing the names in the deps module that the
    # helpers import from. install_deps_stub() already put a stub in
    # sys.modules; just retarget its attributes.
    import deps as deps_mod

    async def _avail():
        return True

    monkeypatch.setattr(deps_mod, "db", fake_db, raising=False)
    monkeypatch.setattr(deps_mod, "is_mongo_available", _avail, raising=False)
    # Some helpers in bot_discovery captured `BASE_URL` at import time;
    # leave it alone — tests will use whatever the module already has.
    return bd, fake_db


# ---------------------------------------------------------------------------
# _collect_edited_url_mtimes — subject/chapter coverage
# ---------------------------------------------------------------------------

def _ahsec_taxonomy():
    return dict(
        boards=[{"id": "b1", "slug": "ahsec"}],
        classes=[{"id": "c1", "board_id": "b1", "slug": "class-12"}],
        streams=[{"id": "st1", "class_id": "c1"}],
    )


def test_collect_mtimes_includes_edited_subject(monkeypatch):
    tax = _ahsec_taxonomy()
    bd, _ = _patch_db(
        monkeypatch,
        subjects=[{
            "id": "sub-1", "slug": "physics", "stream_id": "st1",
            "status": "published",
            "updated_at": "2026-04-10T08:00:00+00:00",
        }],
        **tax,
    )
    url = f"{bd.BASE_URL}/ahsec/class-12/physics"
    out = _run(bd._collect_edited_url_mtimes([url]))
    assert url in out
    assert out[url] == datetime(2026, 4, 10, 8, 0, tzinfo=timezone.utc)


def test_collect_mtimes_includes_edited_chapter(monkeypatch):
    tax = _ahsec_taxonomy()
    bd, _ = _patch_db(
        monkeypatch,
        subjects=[{
            "id": "sub-1", "slug": "physics", "stream_id": "st1",
            "status": "published",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }],
        chapters=[{
            "subject_id": "sub-1", "slug": "kinematics",
            "title": "Kinematics",
            "updated_at": "2026-04-15T09:30:00+00:00",
        }],
        **tax,
    )
    chapter_url = f"{bd.BASE_URL}/ahsec/class-12/physics/kinematics"
    out = _run(bd._collect_edited_url_mtimes([chapter_url]))
    assert chapter_url in out
    assert out[chapter_url] == datetime(2026, 4, 15, 9, 30, tzinfo=timezone.utc)


def test_collect_mtimes_chapter_falls_back_to_slugified_title(monkeypatch):
    tax = _ahsec_taxonomy()
    bd, _ = _patch_db(
        monkeypatch,
        subjects=[{"id": "sub-1", "slug": "physics", "stream_id": "st1",
                   "status": "published",
                   "updated_at": "2026-01-01T00:00:00+00:00"}],
        chapters=[{
            "subject_id": "sub-1", "slug": "",
            "title": "Laws of Motion!",
            "updated_at": "2026-04-12T00:00:00+00:00",
        }],
        **tax,
    )
    expected = f"{bd.BASE_URL}/ahsec/class-12/physics/laws-of-motion"
    out = _run(bd._collect_edited_url_mtimes([expected]))
    assert expected in out


def test_collect_mtimes_skips_chapter_with_no_parent_subject(monkeypatch):
    tax = _ahsec_taxonomy()
    bd, _ = _patch_db(
        monkeypatch,
        subjects=[],  # no subjects → chapter has nowhere to attach
        chapters=[{
            "subject_id": "missing", "slug": "kinematics",
            "title": "Kinematics",
            "updated_at": "2026-04-15T09:30:00+00:00",
        }],
        **tax,
    )
    out = _run(bd._collect_edited_url_mtimes([
        f"{bd.BASE_URL}/ahsec/class-12/physics/kinematics",
    ]))
    assert out == {}


def test_collect_mtimes_omits_url_not_in_candidate_set(monkeypatch):
    tax = _ahsec_taxonomy()
    bd, _ = _patch_db(
        monkeypatch,
        subjects=[{"id": "sub-1", "slug": "physics", "stream_id": "st1",
                   "status": "published",
                   "updated_at": "2026-04-10T00:00:00+00:00"}],
        **tax,
    )
    # Caller didn't ask about the physics subject URL.
    out = _run(bd._collect_edited_url_mtimes(
        [f"{bd.BASE_URL}/somewhere/else"]
    ))
    assert out == {}


def test_collect_mtimes_skips_subject_missing_updated_at(monkeypatch):
    tax = _ahsec_taxonomy()
    bd, _ = _patch_db(
        monkeypatch,
        subjects=[{"id": "sub-1", "slug": "physics", "stream_id": "st1",
                   "status": "published"}],  # no updated_at
        **tax,
    )
    out = _run(bd._collect_edited_url_mtimes(
        [f"{bd.BASE_URL}/ahsec/class-12/physics"]
    ))
    assert out == {}


# ---------------------------------------------------------------------------
# diff_sitemap_against_submitted — end-to-end edited-library re-push
# ---------------------------------------------------------------------------

def test_diff_repushes_edited_subject(monkeypatch):
    """A subject whose updated_at is newer than its last IndexNow submission
    (and outside the dedupe window) must get queued for re-submission."""
    tax = _ahsec_taxonomy()
    bd, fake_db = _patch_db(
        monkeypatch,
        subjects=[{"id": "sub-1", "slug": "physics", "stream_id": "st1",
                   "status": "published",
                   "updated_at": "2026-04-10T00:00:00+00:00"}],
        **tax,
    )
    physics_url = f"{bd.BASE_URL}/ahsec/class-12/physics"

    # _collect_current_sitemap_urls is exercised separately; pin it here so
    # this test focuses on the edit-detection path only.
    async def _fake_sitemap():
        return [physics_url]
    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _fake_sitemap)

    # Submitted ages ago (well outside the 7-day dedupe window) and BEFORE
    # the subject was edited.
    old_submission = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_db.indexnow_submitted_urls = _FakeCollection([
        {"url": physics_url, "last_submitted_at": old_submission},
    ])
    fake_db.indexnow_sitemap_diff_log = MagicMock()
    fake_db.indexnow_sitemap_diff_log.insert_one = AsyncMock()

    queued: list[list[str]] = []
    flushed: list[str] = []
    bd.indexnow_batcher = MagicMock()
    bd.indexnow_batcher.queue = AsyncMock(side_effect=lambda urls: queued.append(list(urls)))
    bd.indexnow_batcher.flush_force = AsyncMock(side_effect=lambda source="": flushed.append(source))

    summary = _run(bd.diff_sitemap_against_submitted(source="test"))

    assert summary["edited_queued"] == 1
    assert summary["new_queued"] == 0
    assert queued == [[physics_url]]
    assert flushed == ["test"]


def test_diff_skips_edited_subject_within_dedupe_window(monkeypatch):
    """An edited subject submitted within the 7-day dedupe window must NOT
    be re-queued, even if its content was edited again."""
    tax = _ahsec_taxonomy()
    bd, fake_db = _patch_db(
        monkeypatch,
        subjects=[{"id": "sub-1", "slug": "physics", "stream_id": "st1",
                   "status": "published",
                   "updated_at": datetime.now(timezone.utc).isoformat()}],
        **tax,
    )
    physics_url = f"{bd.BASE_URL}/ahsec/class-12/physics"

    async def _fake_sitemap():
        return [physics_url]
    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _fake_sitemap)

    # Submitted 2 days ago — well INSIDE the 7-day dedupe window.
    recent_submission = datetime.now(timezone.utc) - timedelta(days=2)
    fake_db.indexnow_submitted_urls = _FakeCollection([
        {"url": physics_url, "last_submitted_at": recent_submission},
    ])
    fake_db.indexnow_sitemap_diff_log = MagicMock()
    fake_db.indexnow_sitemap_diff_log.insert_one = AsyncMock()

    queued: list[list[str]] = []
    bd.indexnow_batcher = MagicMock()
    bd.indexnow_batcher.queue = AsyncMock(side_effect=lambda urls: queued.append(list(urls)))
    bd.indexnow_batcher.flush_force = AsyncMock()

    summary = _run(bd.diff_sitemap_against_submitted(source="test"))

    assert summary["edited_queued"] == 0
    assert summary["edited_skipped_dedupe"] == 1
    assert queued == []  # nothing flushed


def test_diff_does_not_repush_unedited_subject(monkeypatch):
    """A subject whose updated_at is OLDER than last_submitted_at is up to
    date and must not be re-queued."""
    tax = _ahsec_taxonomy()
    bd, fake_db = _patch_db(
        monkeypatch,
        subjects=[{"id": "sub-1", "slug": "physics", "stream_id": "st1",
                   "status": "published",
                   "updated_at": "2026-01-01T00:00:00+00:00"}],
        **tax,
    )
    physics_url = f"{bd.BASE_URL}/ahsec/class-12/physics"

    async def _fake_sitemap():
        return [physics_url]
    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _fake_sitemap)

    # Submitted AFTER the last edit, well outside the dedupe window.
    fake_db.indexnow_submitted_urls = _FakeCollection([
        {"url": physics_url,
         "last_submitted_at": datetime(2026, 3, 1, tzinfo=timezone.utc)},
    ])
    fake_db.indexnow_sitemap_diff_log = MagicMock()
    fake_db.indexnow_sitemap_diff_log.insert_one = AsyncMock()

    queued: list[list[str]] = []
    bd.indexnow_batcher = MagicMock()
    bd.indexnow_batcher.queue = AsyncMock(side_effect=lambda urls: queued.append(list(urls)))
    bd.indexnow_batcher.flush_force = AsyncMock()

    summary = _run(bd.diff_sitemap_against_submitted(source="test"))

    assert summary["edited_queued"] == 0
    assert summary["edited_skipped_dedupe"] == 0
    assert queued == []


def test_diff_repushes_edited_chapter(monkeypatch):
    """Chapter whose updated_at is newer than its last submission gets
    re-queued, exercising the new chapter branch end-to-end."""
    tax = _ahsec_taxonomy()
    bd, fake_db = _patch_db(
        monkeypatch,
        subjects=[{"id": "sub-1", "slug": "physics", "stream_id": "st1",
                   "status": "published",
                   "updated_at": "2026-01-01T00:00:00+00:00"}],
        chapters=[{"subject_id": "sub-1", "slug": "kinematics",
                   "title": "Kinematics",
                   "updated_at": "2026-04-15T00:00:00+00:00"}],
        **tax,
    )
    chapter_url = f"{bd.BASE_URL}/ahsec/class-12/physics/kinematics"

    async def _fake_sitemap():
        return [chapter_url]
    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _fake_sitemap)

    fake_db.indexnow_submitted_urls = _FakeCollection([
        {"url": chapter_url,
         "last_submitted_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ])
    fake_db.indexnow_sitemap_diff_log = MagicMock()
    fake_db.indexnow_sitemap_diff_log.insert_one = AsyncMock()

    queued: list[list[str]] = []
    bd.indexnow_batcher = MagicMock()
    bd.indexnow_batcher.queue = AsyncMock(side_effect=lambda urls: queued.append(list(urls)))
    bd.indexnow_batcher.flush_force = AsyncMock()

    summary = _run(bd.diff_sitemap_against_submitted(source="test"))

    assert summary["edited_queued"] == 1
    assert queued == [[chapter_url]]
