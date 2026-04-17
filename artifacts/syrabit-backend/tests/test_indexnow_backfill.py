"""Tests for the IndexNow full URL backfill (Task #334).

Covers:
- `_validate_backfill_url` for the absolute/host/whitespace/length rules
- `_collect_all_backfill_urls` dedupe + skip-reason aggregation, and that
  the homepage `/` is always included
- `_run_indexnow_backfill` end-to-end: chunking at 10k, per-endpoint
  status aggregation, succeeded vs failed accounting when at least one
  endpoint accepts the chunk vs all endpoints fail, and final state
  transitions (running → done, exception → error)
- The 409 single-flight guard on the POST endpoint
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _patch_mongo_ok(monkeypatch):
    """Stub deps.is_mongo_available → True and provide a MagicMock db so the
    DB-backed lock claim path can be exercised without a real Mongo."""
    import deps as deps_mod
    monkeypatch.setattr(deps_mod, "is_mongo_available", AsyncMock(return_value=True))
    fake_db = MagicMock()
    fake_db.job_locks.insert_one = AsyncMock()
    fake_db.job_locks.find_one_and_update = AsyncMock(return_value={"_id": "x"})
    fake_db.job_locks.update_one = AsyncMock()
    monkeypatch.setattr(deps_mod, "db", fake_db)
    return fake_db


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# _validate_backfill_url
# ---------------------------------------------------------------------------

def test_validate_url_accepts_canonical_https():
    from routes.bot_discovery import _validate_backfill_url
    assert _validate_backfill_url("https://syrabit.ai/") is None
    assert _validate_backfill_url("https://syrabit.ai/ahsec/class-12/physics") is None
    assert _validate_backfill_url("https://syrabit.ai/learn/study-tips") is None


def test_validate_url_rejects_empty_and_non_string():
    from routes.bot_discovery import _validate_backfill_url
    assert _validate_backfill_url("") == "empty"
    assert _validate_backfill_url("   ") == "empty"
    assert _validate_backfill_url(None) == "empty"  # type: ignore[arg-type]
    assert _validate_backfill_url(123) == "empty"   # type: ignore[arg-type]


def test_validate_url_rejects_relative_and_wrong_scheme():
    from routes.bot_discovery import _validate_backfill_url
    assert _validate_backfill_url("/learn/foo") == "not_absolute"
    assert _validate_backfill_url("ftp://syrabit.ai/x") == "not_absolute"


def test_validate_url_rejects_other_hosts():
    from routes.bot_discovery import _validate_backfill_url
    assert _validate_backfill_url("https://www.syrabit.ai/x") == "wrong_host"
    assert _validate_backfill_url("https://evil.com/x") == "wrong_host"
    assert _validate_backfill_url("https://api.syrabit.ai/x") == "wrong_host"


def test_validate_url_rejects_whitespace_and_control_chars():
    from routes.bot_discovery import _validate_backfill_url
    assert _validate_backfill_url("https://syrabit.ai/foo bar") == "invalid_chars"
    assert _validate_backfill_url("https://syrabit.ai/foo\nbar") == "invalid_chars"
    assert _validate_backfill_url("https://syrabit.ai/foo\x01bar") == "invalid_chars"


def test_validate_url_rejects_too_long():
    from routes.bot_discovery import _validate_backfill_url
    long = "https://syrabit.ai/" + ("a" * 2050)
    assert _validate_backfill_url(long) == "too_long"


# ---------------------------------------------------------------------------
# _collect_all_backfill_urls
# ---------------------------------------------------------------------------

def test_collect_all_backfill_dedupes_and_includes_homepage(monkeypatch):
    from routes import bot_discovery as bd

    async def _fake_sitemap():
        return [
            "https://syrabit.ai/library",
            "https://syrabit.ai/library",  # dup
            "https://syrabit.ai/ahsec/class-12/physics",
            "https://syrabit.ai/",  # dup of explicitly-added homepage
        ]
    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _fake_sitemap)

    urls, skip = _run(bd._collect_all_backfill_urls())
    assert "https://syrabit.ai/" in urls
    # No duplicates
    assert len(urls) == len(set(urls))
    assert sorted(urls) == [
        "https://syrabit.ai/",
        "https://syrabit.ai/ahsec/class-12/physics",
        "https://syrabit.ai/library",
    ]
    assert skip == {}


def test_collect_all_backfill_aggregates_skip_reasons(monkeypatch):
    from routes import bot_discovery as bd

    async def _fake_sitemap():
        return [
            "https://syrabit.ai/ok",
            "/relative-path",
            "https://www.syrabit.ai/wronghost",
            "https://syrabit.ai/foo bar",
            "",
        ]
    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _fake_sitemap)

    urls, skip = _run(bd._collect_all_backfill_urls())
    # /ok and / (homepage) should pass.
    assert sorted(urls) == ["https://syrabit.ai/", "https://syrabit.ai/ok"]
    assert skip.get("not_absolute") == 1
    assert skip.get("wrong_host") == 1
    assert skip.get("invalid_chars") == 1
    assert skip.get("empty") == 1


# ---------------------------------------------------------------------------
# _run_indexnow_backfill — end-to-end with stubbed push_indexnow
# ---------------------------------------------------------------------------

def test_run_backfill_chunks_and_aggregates(monkeypatch):
    _patch_mongo_ok(monkeypatch)
    from routes import bot_discovery as bd

    # 25_001 URLs → 3 chunks of 10000, 10000, 5001 (well, _BACKFILL_CHUNK_SIZE
    # is 10000; 25001 → 10000 + 10000 + 5001).
    fake_urls = [f"https://syrabit.ai/p/{i}" for i in range(25001)]

    async def _fake_collect():
        return list(fake_urls), {}
    monkeypatch.setattr(bd, "_collect_all_backfill_urls", _fake_collect)

    chunk_sizes_seen: list[int] = []

    async def _fake_push(urls, source="auto", target_endpoints=None):
        chunk_sizes_seen.append(len(urls))
        # First chunk: bing succeeds, others fail. Second: all fail. Third:
        # all succeed.
        idx = len(chunk_sizes_seen)
        if idx == 1:
            return {
                "https://api.indexnow.org/indexnow": False,
                "https://www.bing.com/indexnow": True,
                "https://yandex.com/indexnow": False,
            }
        if idx == 2:
            return {ep: False for ep in bd.INDEXNOW_ENDPOINTS}
        return {ep: True for ep in bd.INDEXNOW_ENDPOINTS}

    monkeypatch.setattr(bd, "push_indexnow", _fake_push)

    bd._reset_backfill_state("test-run")
    _run(bd._run_indexnow_backfill("test-run"))

    s = bd._backfill_state
    assert s["status"] == "done"
    assert s["discovered"] == 25001
    assert s["chunks_total"] == 3
    assert s["chunks_done"] == 3
    assert chunk_sizes_seen == [10000, 10000, 5001]

    # All URLs were attempted.
    assert s["submitted"] == 25001
    # Chunk 1 (10000) and chunk 3 (5001) had ≥1 endpoint accept.
    assert s["succeeded"] == 15001
    # Chunk 2 (10000) had every endpoint fail.
    assert s["failed"] == 10000

    ep = s["endpoint_status"]
    bing = ep["https://www.bing.com/indexnow"]
    assert bing["success_chunks"] == 2  # chunks 1 + 3
    assert bing["failed_chunks"] == 1
    yandex = ep["https://yandex.com/indexnow"]
    assert yandex["success_chunks"] == 1  # chunk 3 only
    assert yandex["failed_chunks"] == 2
    assert s["finished_at"] is not None
    assert s["error"] is None


def test_run_backfill_handles_empty_catalog(monkeypatch):
    _patch_mongo_ok(monkeypatch)
    from routes import bot_discovery as bd

    async def _fake_collect():
        return [], {"empty": 0}
    monkeypatch.setattr(bd, "_collect_all_backfill_urls", _fake_collect)

    push_mock = AsyncMock()
    monkeypatch.setattr(bd, "push_indexnow", push_mock)

    bd._reset_backfill_state("empty-run")
    _run(bd._run_indexnow_backfill("empty-run"))

    assert bd._backfill_state["status"] == "done"
    assert bd._backfill_state["discovered"] == 0
    assert bd._backfill_state["chunks_total"] == 0
    assert push_mock.await_count == 0


def test_run_backfill_records_per_chunk_failure_without_aborting(monkeypatch):
    """If push_indexnow raises mid-run, the worker logs the exception,
    counts the chunk as fully failed at every endpoint, and continues with
    subsequent chunks instead of aborting the entire backfill."""
    _patch_mongo_ok(monkeypatch)
    from routes import bot_discovery as bd

    fake_urls = [f"https://syrabit.ai/p/{i}" for i in range(15000)]

    async def _fake_collect():
        return list(fake_urls), {}
    monkeypatch.setattr(bd, "_collect_all_backfill_urls", _fake_collect)

    call_count = {"n": 0}

    async def _flaky_push(urls, source="auto", target_endpoints=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient network error")
        return {ep: True for ep in bd.INDEXNOW_ENDPOINTS}

    monkeypatch.setattr(bd, "push_indexnow", _flaky_push)

    bd._reset_backfill_state("flaky-run")
    _run(bd._run_indexnow_backfill("flaky-run"))

    s = bd._backfill_state
    assert s["status"] == "done"
    assert s["chunks_total"] == 2
    assert s["chunks_done"] == 2
    assert s["submitted"] == 15000
    # Chunk 1 (10000 URLs) failed at all endpoints; chunk 2 (5000) succeeded.
    assert s["succeeded"] == 5000
    assert s["failed"] == 10000
    # Every endpoint should have 1 failed_chunks (chunk 1) + 1 success_chunks
    # (chunk 2).
    for ep, slot in s["endpoint_status"].items():
        assert slot["failed_chunks"] == 1, ep
        assert slot["success_chunks"] == 1, ep


def test_run_backfill_marks_error_when_collector_raises(monkeypatch):
    _patch_mongo_ok(monkeypatch)
    from routes import bot_discovery as bd

    async def _broken_collect():
        raise RuntimeError("mongo went away")
    monkeypatch.setattr(bd, "_collect_all_backfill_urls", _broken_collect)

    bd._reset_backfill_state("broken-run")
    _run(bd._run_indexnow_backfill("broken-run"))

    s = bd._backfill_state
    assert s["status"] == "error"
    assert "mongo went away" in (s["error"] or "")
    assert s["finished_at"] is not None


# ---------------------------------------------------------------------------
# Endpoint guard — concurrent runs are rejected with 409.
# ---------------------------------------------------------------------------

def test_admin_endpoint_rejects_concurrent_run(monkeypatch):
    _patch_mongo_ok(monkeypatch)
    from fastapi import BackgroundTasks
    from fastapi import HTTPException
    from routes import bot_discovery as bd

    async def _stuck_run(_run_id):
        await asyncio.sleep(60)  # never completes during test

    # We don't actually run the background task; just simulate state.
    monkeypatch.setattr(bd, "_run_indexnow_backfill", _stuck_run)

    async def _drive():
        bg = BackgroundTasks()
        first = await bd.admin_indexnow_backfill_all(bg, admin={"id": "admin"})
        assert first["status"] == "started"
        # State should be "running" now.
        assert bd._backfill_state["status"] == "running"
        # Second call must 409.
        try:
            await bd.admin_indexnow_backfill_all(bg, admin={"id": "admin"})
        except HTTPException as e:
            assert e.status_code == 409
            return True
        return False

    assert _run(_drive()) is True

    # Restore idle state so other tests don't see "running".
    bd._backfill_state["status"] = "idle"


def test_admin_endpoint_returns_503_when_mongo_unavailable(monkeypatch):
    """Operators must NOT be told a backfill started when Mongo is down —
    we'd otherwise enumerate an empty catalog and silently mark the run
    as `done`."""
    import deps as deps_mod
    from fastapi import BackgroundTasks
    from fastapi import HTTPException
    from routes import bot_discovery as bd

    monkeypatch.setattr(deps_mod, "is_mongo_available", AsyncMock(return_value=False))

    async def _drive():
        try:
            await bd.admin_indexnow_backfill_all(BackgroundTasks(), admin={"id": "a"})
        except HTTPException as e:
            return e.status_code
        return None

    assert _run(_drive()) == 503


def test_admin_endpoint_409_when_db_lock_already_held(monkeypatch):
    """Even if the in-memory state says idle (because we're a fresh worker
    that just booted), the DB lock claim must reject us with 409 if a
    sibling worker / replica already owns the lock."""
    import deps as deps_mod
    from fastapi import BackgroundTasks
    from fastapi import HTTPException
    from pymongo.errors import DuplicateKeyError
    from routes import bot_discovery as bd

    monkeypatch.setattr(deps_mod, "is_mongo_available", AsyncMock(return_value=True))
    fake_db = MagicMock()
    fake_db.job_locks.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))
    # Steal attempt fails (existing holder is fresh + still running).
    fake_db.job_locks.find_one_and_update = AsyncMock(return_value=None)
    monkeypatch.setattr(deps_mod, "db", fake_db)

    bd._backfill_state["status"] = "idle"

    async def _drive():
        try:
            await bd.admin_indexnow_backfill_all(BackgroundTasks(), admin={"id": "a"})
        except HTTPException as e:
            return e.status_code
        return None

    assert _run(_drive()) == 409


def test_run_backfill_marks_error_when_mongo_unavailable_mid_run(monkeypatch):
    """Defence-in-depth: if Mongo went away between the POST endpoint check
    and the background worker actually starting, the worker itself sets
    status=error rather than reporting a successful zero-URL push."""
    import deps as deps_mod
    from routes import bot_discovery as bd

    monkeypatch.setattr(deps_mod, "is_mongo_available", AsyncMock(return_value=False))

    bd._reset_backfill_state("ghost-run")
    _run(bd._run_indexnow_backfill("ghost-run"))

    s = bd._backfill_state
    assert s["status"] == "error"
    assert "MongoDB" in (s["error"] or "")
    assert s["finished_at"] is not None


def test_claim_backfill_lock_steals_stale_holder(monkeypatch):
    """A holder whose claimed_at is older than _BACKFILL_STALE_AFTER (e.g.
    the previous worker crashed mid-run) must be steal-able so the
    catalog isn't permanently locked out."""
    import deps as deps_mod
    from pymongo.errors import DuplicateKeyError
    from routes import bot_discovery as bd

    monkeypatch.setattr(deps_mod, "is_mongo_available", AsyncMock(return_value=True))
    fake_db = MagicMock()
    fake_db.job_locks.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))
    fake_db.job_locks.find_one_and_update = AsyncMock(
        return_value={"_id": bd._BACKFILL_LOCK_ID, "owner_run_id": "old"}
    )
    monkeypatch.setattr(deps_mod, "db", fake_db)

    won = _run(bd._claim_backfill_lock("new-run"))
    assert won is True
    # The CAS filter must include both the not-running and the stale
    # cutoff branches so a stuck "running" doc still becomes stealable.
    args, _ = fake_db.job_locks.find_one_and_update.await_args
    flt = args[0]
    or_branches = flt.get("$or", [])
    keys = {next(iter(b.keys())) for b in or_branches}
    assert "status" in keys and "claimed_at" in keys


def test_admin_progress_endpoint_returns_state_snapshot():
    from routes import bot_discovery as bd

    bd._backfill_state["status"] = "done"
    bd._backfill_state["discovered"] = 42
    out = _run(bd.admin_indexnow_backfill_progress(admin={"id": "admin"}))
    assert out["progress"]["status"] == "done"
    assert out["progress"]["discovered"] == 42
    # Returned payload must be a snapshot copy, not the same dict reference.
    out["progress"]["status"] = "tampered"
    assert bd._backfill_state["status"] == "done"
