"""Tests for Plan 11 / Task #333: Bing Keyword Research pipeline.

Covers:
  * `bing_keyword_client.fetch_top_keywords` cache hit / miss / stale
    behaviour and shared-client batching.
  * `_select_chapters_for_keyword_refresh` oldest-first ordering.
  * `_try_run_bing_keyword_refresh_once` no-key short-circuit and
    successful one-shot refresh path.
  * `BotRenderMiddleware._render_chapter_fallback` meta-keywords tag
    emission with and without Bing data on the chapter doc.
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


def _make_db_with_cache(initial_doc=None):
    db = MagicMock()
    coll = MagicMock()
    coll.find_one = AsyncMock(return_value=initial_doc)
    coll.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    db.__getitem__.return_value = coll
    return db, coll


def _related_payload(items):
    return {"d": [{"Query": k, "Impressions": v} for k, v in items]}


def _keyword_payload(broad):
    return {"d": {"Keyword": "x", "Broad": broad, "Phrase": broad // 2, "Exact": broad // 4}}


# ---------------------------------------------------------------------------
# Client: fetch_top_keywords cache & API behaviour
# ---------------------------------------------------------------------------

def test_fetch_top_keywords_cache_hit_skips_api(monkeypatch):
    import bing_keyword_client as bkc
    now = datetime(2026, 4, 17, tzinfo=timezone.utc)
    fresh = now - timedelta(days=5)  # well within 30d TTL
    db, coll = _make_db_with_cache({
        "keywords": [{"keyword": "ahsec hs notes", "impressions": 9000}],
        "primary": {"Keyword": "atom", "Broad": 100},
        "cached_at": fresh,
    })

    # Any call to the network-layer would explode this test.
    async def _boom(*a, **kw):
        raise AssertionError("network must not be called on cache hit")
    monkeypatch.setattr(bkc, "_bing_get", _boom)

    res = _run(bkc.fetch_top_keywords("api-key", "Atom", db=db, now=now))
    assert res["source"] == "cache"
    assert res["cached"] is True
    assert res["keywords"][0]["keyword"] == "ahsec hs notes"
    coll.update_one.assert_not_called()


def test_fetch_top_keywords_cache_miss_calls_api_and_writes_cache(monkeypatch):
    import bing_keyword_client as bkc
    now = datetime(2026, 4, 17, tzinfo=timezone.utc)
    db, coll = _make_db_with_cache(None)

    captured = []

    async def fake_get(api_key, path, params, *, client=None):
        captured.append(path)
        if path == "GetRelatedKeywords":
            return _related_payload([("ahsec hs notes", 9000),
                                     ("class 11 atom mcq", 4000),
                                     ("ahsec hs notes", 8000)])  # dupe
        if path == "GetKeyword":
            return _keyword_payload(2200)
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(bkc, "_bing_get", fake_get)

    res = _run(bkc.fetch_top_keywords("api-key", "Atom", db=db, now=now))
    assert res["source"] == "api"
    assert res["cached"] is False
    # Sorted desc, deduped (case-insensitive).
    assert [k["keyword"] for k in res["keywords"]] == [
        "ahsec hs notes", "class 11 atom mcq",
    ]
    assert captured == ["GetRelatedKeywords", "GetKeyword"]
    coll.update_one.assert_awaited_once()
    update_doc = coll.update_one.await_args.args[1]["$set"]
    assert update_doc["seed"] == "Atom"
    assert update_doc["country"] == "IN"
    assert update_doc["language"] == "en-IN"
    assert update_doc["cached_at"] == now


def test_fetch_top_keywords_stale_cache_refreshes(monkeypatch):
    import bing_keyword_client as bkc
    now = datetime(2026, 4, 17, tzinfo=timezone.utc)
    stale = now - timedelta(days=45)  # > 30d TTL
    db, coll = _make_db_with_cache({
        "keywords": [{"keyword": "old kw", "impressions": 100}],
        "cached_at": stale,
    })

    async def fake_get(api_key, path, params, *, client=None):
        if path == "GetRelatedKeywords":
            return _related_payload([("fresh kw", 500)])
        return _keyword_payload(50)

    monkeypatch.setattr(bkc, "_bing_get", fake_get)

    res = _run(bkc.fetch_top_keywords("api-key", "atom", db=db, now=now))
    assert res["source"] == "api"
    assert res["keywords"][0]["keyword"] == "fresh kw"


def test_fetch_top_keywords_api_empty_falls_back_to_stale_cache(monkeypatch):
    import bing_keyword_client as bkc
    now = datetime(2026, 4, 17, tzinfo=timezone.utc)
    stale = now - timedelta(days=45)
    db, _ = _make_db_with_cache({
        "keywords": [{"keyword": "old kw", "impressions": 100}],
        "cached_at": stale,
    })

    async def fake_get(api_key, path, params, *, client=None):
        # API returns nothing useful — Bing outage / quota exhaustion.
        return None

    monkeypatch.setattr(bkc, "_bing_get", fake_get)

    res = _run(bkc.fetch_top_keywords("api-key", "atom", db=db, now=now))
    assert res["source"] == "cache_stale_fallback"
    assert res["keywords"][0]["keyword"] == "old kw"


def test_fetch_top_keywords_no_seed_returns_empty():
    import bing_keyword_client as bkc
    res = _run(bkc.fetch_top_keywords("api-key", "   ", db=None))
    assert res["source"] == "empty"
    assert res["keywords"] == []


def test_fetch_top_keywords_reuses_provided_client(monkeypatch):
    """Client batching: when a shared client is passed in, it is the same
    instance used for every underlying request and is NOT closed by the
    helper (so the caller can keep using it for the next seed)."""
    import bing_keyword_client as bkc
    now = datetime(2026, 4, 17, tzinfo=timezone.utc)
    db, _ = _make_db_with_cache(None)
    seen_clients = []

    async def fake_get(api_key, path, params, *, client=None):
        seen_clients.append(client)
        if path == "GetRelatedKeywords":
            return _related_payload([("kw", 1)])
        return _keyword_payload(10)

    monkeypatch.setattr(bkc, "_bing_get", fake_get)

    sentinel_client = MagicMock(name="shared-client")
    sentinel_client.aclose = AsyncMock()

    _run(bkc.fetch_top_keywords(
        "api-key", "seed-1", db=db, now=now, client=sentinel_client,
    ))
    _run(bkc.fetch_top_keywords(
        "api-key", "seed-2", db=db, now=now, client=sentinel_client,
    ))

    # Both seeds shared the exact same client instance.
    assert all(c is sentinel_client for c in seen_clients)
    # Helper must not close a client it did not own.
    sentinel_client.aclose.assert_not_called()


# ---------------------------------------------------------------------------
# Refresh task selection + leader-elected loop
# ---------------------------------------------------------------------------

def test_select_chapters_for_keyword_refresh_orders_oldest_first():
    from routes import bot_discovery as bd
    rows = [
        {"id": "ch-never", "title": "Atom", "slug": "atom", "subject_id": "s1"},
        {"id": "ch-old", "title": "Force", "slug": "force", "subject_id": "s1",
         "bing_keywords_updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ]
    db = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=rows)
    db.chapters.find.return_value = cursor

    out = _run(bd._select_chapters_for_keyword_refresh(db, 50))
    assert [c["id"] for c in out] == ["ch-never", "ch-old"]
    # Sorted ascending so missing-field rows (never refreshed) lead.
    sort_args = cursor.sort.call_args.args
    assert sort_args[0] == "bing_keywords_updated_at" and sort_args[1] == 1


def test_try_run_bing_keyword_refresh_once_no_api_key(monkeypatch):
    from routes import bot_discovery as bd
    monkeypatch.delenv("BING_WEBMASTER_API_KEY", raising=False)
    out = _run(bd._try_run_bing_keyword_refresh_once(MagicMock(), datetime(2026, 4, 17, 4, 5, tzinfo=timezone.utc)))
    assert out == {"claimed": False, "reason": "no_api_key"}


def test_try_run_bing_keyword_refresh_once_outside_window(monkeypatch):
    from routes import bot_discovery as bd
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "k")
    db = MagicMock()
    db.job_locks.find_one = AsyncMock(return_value={"last_run_date": ""})
    out = _run(bd._try_run_bing_keyword_refresh_once(
        db, datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
    ))
    assert out == {"claimed": False, "reason": "outside_window_or_dedup"}


def test_try_run_bing_keyword_refresh_once_happy_path(monkeypatch):
    from routes import bot_discovery as bd
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "k")
    now = datetime(2026, 4, 17, 4, 5, tzinfo=timezone.utc)

    db = MagicMock()
    db.job_locks.find_one = AsyncMock(return_value={"last_run_date": ""})
    # Successful CAS on the first replica.
    db.job_locks.find_one_and_update = AsyncMock(return_value={"_id": "x"})
    db.chapters.update_one = AsyncMock()

    chapters = [
        {"id": "c1", "title": "Atom", "slug": "atom"},
        {"id": "c2", "title": "Force", "slug": "force"},
    ]
    monkeypatch.setattr(
        bd, "_select_chapters_for_keyword_refresh",
        AsyncMock(return_value=chapters),
    )

    refreshed_for = []

    async def fake_fetch(api_key, seed, **kw):
        refreshed_for.append(seed)
        return {
            "seed": seed, "country": "IN", "language": "en-IN",
            "keywords": [{"keyword": f"{seed} notes", "impressions": 100}],
            "primary": None, "cached": False, "fetched_at": now.isoformat(),
            "source": "api",
        }

    import bing_keyword_client as bkc
    monkeypatch.setattr(bkc, "fetch_top_keywords", fake_fetch)

    stats_coll = MagicMock()
    stats_coll.update_one = AsyncMock()
    db.__getitem__.return_value = stats_coll

    out = _run(bd._try_run_bing_keyword_refresh_once(db, now))
    assert out["claimed"] is True
    assert out["chapters_picked"] == 2
    assert out["refreshed"] == 2
    assert refreshed_for == ["Atom", "Force"]
    # Stats doc was upserted.
    stats_coll.update_one.assert_awaited_once()


# ---------------------------------------------------------------------------
# Bot-render meta-keywords tag emission
# ---------------------------------------------------------------------------

def _install_render_stubs(monkeypatch, chapter_doc):
    """Patch the BotRenderMiddleware's `deps.db` + `is_mongo_available`
    so we can drive `_render_chapter_fallback` end-to-end in a unit
    test without touching real Mongo."""
    import sys
    deps = sys.modules.get("deps")
    deps.is_mongo_available = AsyncMock(return_value=True)
    db = MagicMock()
    db.subjects.find_one = AsyncMock(return_value={
        "id": "subj-1", "name": "Physics",
        "board_slug": "ahsec", "class_slug": "class-11",
    })
    db.chapters.find_one = AsyncMock(return_value=chapter_doc)
    deps.db = db


def test_render_chapter_fallback_emits_bing_keywords_meta(monkeypatch):
    from routes.cms_sarvam_health import BotRenderMiddleware
    _install_render_stubs(monkeypatch, {
        "title": "Atom",
        "description": "Atomic structure for class 11.",
        "content": "Atoms are made of protons, neutrons, electrons.",
        "topics": [{"title": "Bohr Model"}],
        "content_as": "",
        "bing_keywords": [
            {"keyword": "ahsec class 11 atom notes", "impressions": 9000},
            {"keyword": "class 11 atom mcq", "impressions": 4000},
            {"keyword": "  ", "impressions": 100},  # whitespace dropped
        ],
    })
    mw = BotRenderMiddleware(app=MagicMock())
    html = _run(mw._render_chapter_fallback("ahsec", "class-11", "physics", "atom"))
    assert html is not None
    line = next(
        l for l in html.splitlines()
        if l.startswith('<meta name="keywords"')
    )
    # Bing terms ship first, in impressions order, with whitespace
    # entries dropped. Static fallback follows but is not asserted here.
    assert "ahsec class 11 atom notes" in line
    assert "class 11 atom mcq" in line
    assert line.index("ahsec class 11 atom notes") < line.index("class 11 atom mcq")


def test_render_chapter_fallback_uses_static_keywords_when_no_bing_data(monkeypatch):
    """Without Bing data we still emit a `<meta name="keywords">` built
    from the chapter title + subject + board (mirrors the static
    template `ChapterPage.jsx` falls back to). Bot-render and the SPA
    must not diverge on this surface."""
    from routes.cms_sarvam_health import BotRenderMiddleware
    _install_render_stubs(monkeypatch, {
        "title": "Force",
        "description": "Forces and motion.",
        "content": "F = ma.",
        "topics": [],
        "content_as": "",
        # No bing_keywords field at all.
    })
    mw = BotRenderMiddleware(app=MagicMock())
    html = _run(mw._render_chapter_fallback("ahsec", "class-11", "physics", "force"))
    assert html is not None
    assert '<meta name="keywords"' in html
    # Static fallback must include title-derived terms and board.
    assert "Force notes" in html
    assert "AHSEC" in html


def test_render_chapter_fallback_merges_bing_and_static_terms_dedup(monkeypatch):
    """When both sources fire, Bing terms lead and static fallback fills
    in; duplicates are removed case-insensitively."""
    from routes.cms_sarvam_health import BotRenderMiddleware
    _install_render_stubs(monkeypatch, {
        "title": "Atom",
        "description": "Atomic structure.",
        "content": "...",
        "topics": [],
        "content_as": "",
        "bing_keywords": [
            {"keyword": "Atom notes", "impressions": 9000},  # collides with static
            {"keyword": "ahsec class 11 atom", "impressions": 6000},
        ],
    })
    mw = BotRenderMiddleware(app=MagicMock())
    html = _run(mw._render_chapter_fallback("ahsec", "class-11", "physics", "atom"))
    assert html is not None
    # Find the keywords meta line and inspect the value.
    line = next(
        l for l in html.splitlines()
        if l.startswith('<meta name="keywords"')
    )
    # Bing terms come first.
    assert line.index("Atom notes") < line.index("Atom MCQ")
    # Case-insensitive dedupe: "Atom notes" must appear exactly once.
    assert line.count("Atom notes") == 1


def test_refresh_chapter_preserves_existing_keywords_on_empty_bing_result(monkeypatch):
    """Fallback safety: when Bing returns no keywords (outage / quota
    exhaustion), the chapter doc must NOT have its `bing_keywords` field
    overwritten with [] and must NOT have `bing_keywords_updated_at`
    bumped — otherwise we'd defer retry by ~30 days and lose the
    previously-useful list."""
    from routes import bot_discovery as bd
    db = MagicMock()
    db.chapters.update_one = AsyncMock()

    async def fake_fetch(api_key, seed, **kw):
        return {
            "seed": seed, "country": "IN", "language": "en-IN",
            "keywords": [], "primary": None, "cached": False,
            "fetched_at": "2026-04-17T04:05:00+00:00",
            "source": "api_empty",
        }

    import bing_keyword_client as bkc
    monkeypatch.setattr(bkc, "fetch_top_keywords", fake_fetch)

    out = _run(bd._refresh_keywords_for_chapter(
        db, {"id": "ch-1", "title": "Atom"}, "k",
        now=datetime(2026, 4, 17, 4, 5, tzinfo=timezone.utc),
    ))
    assert out["ok"] is False
    assert out["skipped"] is True
    assert out["reason"] == "empty_result_preserved_existing"

    # The only write must be the no-op marker — never `bing_keywords` or
    # `bing_keywords_updated_at`.
    db.chapters.update_one.assert_awaited_once()
    update_doc = db.chapters.update_one.await_args.args[1]["$set"]
    assert "bing_keywords" not in update_doc
    assert "bing_keywords_updated_at" not in update_doc
    assert "bing_keywords_last_attempt_at" in update_doc
    assert update_doc["bing_keywords_last_attempt_source"] == "api_empty"
