"""Tests for the scheduled SEO auto-publish loop (Task #458)."""
import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()
import seo_engine  # noqa: E402


# ── window / dedup logic ────────────────────────────────────────────────────

def _at(year, month, day, hour, minute=0, weekday=None):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_should_run_inside_window_with_new_tag(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_FREQUENCY", "daily")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    now = _at(2026, 4, 18, 2, 10)  # +10min from target
    assert seo_engine._should_run_seo_auto_publish_now(now, "") is True
    assert seo_engine._should_run_seo_auto_publish_now(now, "2026-04-17") is True


def test_should_not_run_when_already_done_today(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    now = _at(2026, 4, 18, 2, 5)
    assert seo_engine._should_run_seo_auto_publish_now(now, "2026-04-18") is False


def test_should_not_run_outside_window(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    now = _at(2026, 4, 18, 5, 0)  # +3h from target
    assert seo_engine._should_run_seo_auto_publish_now(now, "") is False


def test_should_not_run_when_disabled(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "false")
    now = _at(2026, 4, 18, 2, 5)
    assert seo_engine._should_run_seo_auto_publish_now(now, "") is False


def test_weekly_only_on_target_weekday(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_FREQUENCY", "weekly")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_WEEKDAY", "0")  # Monday
    # 2026-04-20 is a Monday
    monday = _at(2026, 4, 20, 2, 5)
    tuesday = _at(2026, 4, 21, 2, 5)
    assert seo_engine._should_run_seo_auto_publish_now(monday, "") is True
    assert seo_engine._should_run_seo_auto_publish_now(tuesday, "") is False


def test_run_tag_format(monkeypatch):
    now = _at(2026, 4, 20, 2, 0)
    assert seo_engine._seo_auto_publish_run_tag(now, "daily") == "2026-04-20"
    assert seo_engine._seo_auto_publish_run_tag(now, "weekly") == "2026-W17"


def test_page_types_default_and_override(monkeypatch):
    monkeypatch.delenv("SEO_AUTO_PUBLISH_PAGE_TYPES", raising=False)
    assert seo_engine._seo_auto_publish_page_types() == list(seo_engine.AUTO_PAGE_TYPES)
    monkeypatch.setenv("SEO_AUTO_PUBLISH_PAGE_TYPES", "notes, mcqs ,definition,bogus")
    assert seo_engine._seo_auto_publish_page_types() == ["notes", "mcqs", "definition"]
    monkeypatch.setenv("SEO_AUTO_PUBLISH_PAGE_TYPES", "bogus,more-bogus")
    assert seo_engine._seo_auto_publish_page_types() == list(seo_engine.AUTO_PAGE_TYPES)


# ── _try_run_seo_auto_publish_once ──────────────────────────────────────────

def _make_db_with_marker(last_tag: str):
    db = MagicMock()
    db.job_locks = MagicMock()
    db.job_locks.find_one = AsyncMock(
        return_value={seo_engine._SEO_AUTO_PUBLISH_LAST_RUN_KEY: last_tag} if last_tag else None
    )
    db.job_locks.find_one_and_update = AsyncMock(return_value={"_id": "x"})
    db.job_locks.insert_one = AsyncMock(return_value=None)
    return db


def test_try_run_skips_outside_window(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    db = _make_db_with_marker("")
    now = _at(2026, 4, 18, 12, 0)
    res = asyncio.run(seo_engine._try_run_seo_auto_publish_once(db, now))
    assert res["ran"] is False
    assert res["reason"] == "outside_window_or_dedup"
    db.job_locks.find_one_and_update.assert_not_called()


def test_try_run_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "false")
    db = _make_db_with_marker("")
    now = _at(2026, 4, 18, 2, 5)
    res = asyncio.run(seo_engine._try_run_seo_auto_publish_once(db, now))
    assert res["ran"] is False
    assert res["reason"] == "disabled"


def test_try_run_claims_and_dispatches(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_FREQUENCY", "daily")
    db = _make_db_with_marker("")
    now = _at(2026, 4, 18, 2, 5)

    fake_auto_run = AsyncMock(return_value=None)
    with patch.object(seo_engine, "_auto_run_bg", fake_auto_run):
        res = asyncio.run(seo_engine._try_run_seo_auto_publish_once(db, now))

    assert res["ran"] is True
    assert res["tag"] == "2026-04-18"
    assert res["page_types"] == list(seo_engine.AUTO_PAGE_TYPES)
    assert res["job_id"].startswith("job-sched-")
    db.job_locks.find_one_and_update.assert_awaited_once()
    # Job is registered in the in-memory tracker so admin polling endpoints
    # can surface live progress.
    assert res["job_id"] in seo_engine._seo_jobs
    job = seo_engine._seo_jobs[res["job_id"]]
    assert job["trigger"] == "scheduler"
    assert job["schedule_tag"] == "2026-04-18"


def test_try_run_loses_race_when_cas_fails(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    db = _make_db_with_marker("")
    db.job_locks.find_one_and_update = AsyncMock(return_value=None)
    # Bootstrap insert also collides → DuplicateKeyError
    from pymongo.errors import DuplicateKeyError
    db.job_locks.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))
    now = _at(2026, 4, 18, 2, 5)

    fake_auto_run = AsyncMock(return_value=None)
    with patch.object(seo_engine, "_auto_run_bg", fake_auto_run):
        res = asyncio.run(seo_engine._try_run_seo_auto_publish_once(db, now))

    assert res["ran"] is False
    assert res["reason"] == "lost_race"
    fake_auto_run.assert_not_called()


def test_try_run_skips_when_marker_already_today(monkeypatch):
    monkeypatch.setenv("SEO_AUTO_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("SEO_AUTO_PUBLISH_HOUR_UTC", "2")
    db = _make_db_with_marker("2026-04-18")
    now = _at(2026, 4, 18, 2, 10)
    res = asyncio.run(seo_engine._try_run_seo_auto_publish_once(db, now))
    assert res["ran"] is False
    assert res["reason"] == "outside_window_or_dedup"
    db.job_locks.find_one_and_update.assert_not_called()
