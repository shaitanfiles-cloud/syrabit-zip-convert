"""Tests for the Cloudflare per-UA crawler report (Task #315)."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import cf_bot_report  # noqa: E402
from cf_bot_report import (
    _classify_ua,
    aggregate_per_ua,
    compose_wow_diff,
    format_report_markdown,
    WOW_PACE_DELTA_THRESHOLD,
    WOW_ERROR_RATE_THRESHOLD,
)


# ── _classify_ua ────────────────────────────────────────────────────────────

def test_classify_ua_googlebot_variants():
    assert _classify_ua("Mozilla/5.0 (compatible; Googlebot/2.1)") == "Googlebot"
    assert _classify_ua("Googlebot-Image/1.0") == "Googlebot-Image"
    assert _classify_ua("Mozilla/5.0 ... AdsBot-Google ...") == "AdsBot-Google"


def test_classify_ua_other_search_bots():
    assert _classify_ua("Bingbot/2.0") == "Bingbot"
    assert _classify_ua("YandexBot/3.0") == "YandexBot"
    assert _classify_ua("DuckDuckBot/1.1") == "DuckDuckBot"
    assert _classify_ua("Baiduspider/2.0") == "Baiduspider"


def test_classify_ua_returns_none_for_human_and_unknown():
    assert _classify_ua("Mozilla/5.0 (Windows NT 10.0) Chrome/123") is None
    assert _classify_ua("") is None
    assert _classify_ua("MyCustomScraper/1.0") is None


# ── aggregate_per_ua ────────────────────────────────────────────────────────

def _bucket(ua, count, status, cache="hit", bytes_=1024):
    return {
        "count": count,
        "sum": {"edgeResponseBytes": bytes_},
        "dimensions": {
            "userAgent": ua,
            "cacheStatus": cache,
            "edgeResponseStatus": status,
        },
    }


def test_aggregate_groups_by_classified_bot():
    buckets = [
        _bucket("Googlebot/2.1", 10, 200, cache="hit"),
        _bucket("Googlebot/2.1", 2, 404, cache="miss"),
        _bucket("Bingbot/2.0", 5, 200, cache="dynamic"),
        _bucket("Mozilla/5.0 Chrome/123", 50, 200),  # human, ignored
    ]
    agg = aggregate_per_ua(buckets)
    assert agg["totals"]["bots"] == 2
    assert agg["totals"]["requests"] == 17
    assert agg["per_bot"]["Googlebot"]["requests"] == 12
    assert agg["per_bot"]["Googlebot"]["by_status"]["2xx"] == 10
    assert agg["per_bot"]["Googlebot"]["by_status"]["4xx"] == 2
    # 10 hits / 12 total = 83.3%
    assert agg["per_bot"]["Googlebot"]["hit_pct"] == 83.3
    # 2 errors / 12 total = 0.1667
    assert abs(agg["per_bot"]["Googlebot"]["error_rate"] - 0.1667) < 0.001
    assert agg["per_bot"]["Bingbot"]["requests"] == 5
    assert agg["per_bot"]["Bingbot"]["error_rate"] == 0.0


def test_aggregate_handles_empty_buckets():
    agg = aggregate_per_ua([])
    assert agg == {"totals": {"requests": 0, "bytes": 0, "bots": 0}, "per_bot": {}}


def test_aggregate_handles_malformed_status_gracefully():
    # Cloudflare can return None for status in some edge cases.
    buckets = [_bucket("Googlebot/2.1", 3, None)]
    agg = aggregate_per_ua(buckets)
    # Counts the bucket but doesn't crash; status doesn't fall into 2xx-5xx.
    assert agg["per_bot"]["Googlebot"]["requests"] == 3
    assert sum(agg["per_bot"]["Googlebot"]["by_status"].values()) == 0


# ── compose_wow_diff ────────────────────────────────────────────────────────

def _agg(per_bot: dict) -> dict:
    """Build an aggregate-shaped dict, filling derived fields."""
    out_per = {}
    for name, raw in per_bot.items():
        total = raw["requests"]
        errs = raw.get("by_status", {}).get("4xx", 0) + raw.get("by_status", {}).get("5xx", 0)
        out_per[name] = {
            "requests": total,
            "bytes": raw.get("bytes", 0),
            "by_status": raw.get("by_status", {"2xx": total, "3xx": 0, "4xx": 0, "5xx": 0}),
            "by_cache": raw.get("by_cache", {"hit": total}),
            "hit_pct": 100.0 if total else 0.0,
            "error_rate": (errs / total) if total else 0.0,
        }
    return {
        "totals": {"requests": sum(b["requests"] for b in out_per.values()),
                   "bytes": 0, "bots": len(out_per)},
        "per_bot": out_per,
    }


def test_wow_no_baseline_returns_active_list_only():
    cur = _agg({"Googlebot": {"requests": 200}, "Bingbot": {"requests": 5}})
    diff = compose_wow_diff(cur, None)
    assert diff["had_baseline"] is False
    assert diff["pace_shifts"] == []
    assert diff["error_spikes"] == []
    # Bingbot below WOW_MIN_SAMPLE (20) excluded; Googlebot included.
    names = [b["name"] for b in diff["new_bots"]]
    assert names == ["Googlebot"]


def test_wow_detects_new_bot():
    last = _agg({"Googlebot": {"requests": 200}})
    cur = _agg({"Googlebot": {"requests": 210}, "YandexBot": {"requests": 50}})
    diff = compose_wow_diff(cur, last)
    assert diff["had_baseline"] is True
    new_names = [b["name"] for b in diff["new_bots"]]
    assert new_names == ["YandexBot"]


def test_wow_detects_disappeared_bot():
    last = _agg({"Googlebot": {"requests": 200}, "Bingbot": {"requests": 80}})
    cur = _agg({"Googlebot": {"requests": 210}})
    diff = compose_wow_diff(cur, last)
    names = [b["name"] for b in diff["disappeared_bots"]]
    assert names == ["Bingbot"]


def test_wow_pace_shift_above_threshold_detected_below_ignored():
    # Googlebot doubled (+100% > 50% threshold) → shift.
    # Bingbot up 20% (< 50%) → no shift.
    last = _agg({"Googlebot": {"requests": 100}, "Bingbot": {"requests": 100}})
    cur = _agg({"Googlebot": {"requests": 200}, "Bingbot": {"requests": 120}})
    diff = compose_wow_diff(cur, last)
    shift_names = [s["name"] for s in diff["pace_shifts"]]
    assert "Googlebot" in shift_names
    assert "Bingbot" not in shift_names


def test_wow_pace_shift_ignores_low_sample():
    # Both weeks well below WOW_MIN_SAMPLE — no alert even though delta is huge.
    last = _agg({"PetalBot": {"requests": 1}})
    cur = _agg({"PetalBot": {"requests": 10}})
    diff = compose_wow_diff(cur, last)
    assert diff["pace_shifts"] == []


def test_wow_error_spike_detected():
    last = _agg({"Googlebot": {"requests": 100, "by_status": {"2xx": 99, "3xx": 0, "4xx": 1, "5xx": 0}}})
    # Jump to 10% errors → +9pp >= 5pp threshold.
    cur = _agg({"Googlebot": {"requests": 100, "by_status": {"2xx": 90, "3xx": 0, "4xx": 10, "5xx": 0}}})
    diff = compose_wow_diff(cur, last)
    spike_names = [s["name"] for s in diff["error_spikes"]]
    assert spike_names == ["Googlebot"]
    assert diff["error_spikes"][0]["delta_pp"] >= WOW_ERROR_RATE_THRESHOLD * 100


def test_wow_pace_threshold_is_inclusive_at_boundary():
    # Exactly +50% should trip the threshold (>=).
    last = _agg({"Googlebot": {"requests": 100}})
    cur = _agg({"Googlebot": {"requests": 150}})
    diff = compose_wow_diff(cur, last)
    assert any(s["name"] == "Googlebot" for s in diff["pace_shifts"])


# ── format_report_markdown ──────────────────────────────────────────────────

def test_markdown_renders_summary_and_per_bot_table():
    data = _agg({"Googlebot": {"requests": 100, "by_status": {"2xx": 95, "3xx": 0, "4xx": 5, "5xx": 0}}})
    md = format_report_markdown(
        data,
        since_iso="2026-04-09T00:00:00Z",
        until_iso="2026-04-16T00:00:00Z",
        zone_id="zone123",
        generated_at=datetime(2026, 4, 16, 4, 0, tzinfo=timezone.utc),
    )
    assert "# Search Engine Crawler Traffic — Per User-Agent" in md
    assert "zone123" in md
    assert "Googlebot" in md
    assert "## Per-crawler totals" in md
    assert "## HTTP status breakdown per crawler" in md
    # No WoW section when wow=None (caller explicitly opted out)
    assert "Week-over-week changes" not in md


def test_generate_per_ua_report_always_includes_wow_block_first_run():
    """End-to-end: even on first-ever run (prior=None), the rendered
    markdown should explicitly state there's no baseline rather than
    silently omit the WoW section."""
    fake_buckets = [_bucket("Googlebot/2.1", 50, 200)]

    async def _run():
        with patch("cf_bot_report._fetch_per_ua_buckets",
                   new=AsyncMock(return_value=fake_buckets)), \
             patch("cf_bot_report.is_configured", return_value=True), \
             patch("cf_bot_report._cfg", return_value={"zone_id": "zone123", "api_token": "t"}):
            return await cf_bot_report.generate_per_ua_report(
                prior=None,
                now=datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc),
            )

    result = asyncio.run(_run())
    assert result is not None
    assert result["wow"] is not None
    assert result["wow"]["had_baseline"] is False
    assert "## Week-over-week changes" in result["markdown"]
    assert "No prior-week baseline" in result["markdown"]


def test_generate_per_ua_report_renders_wow_when_baseline_exists():
    """End-to-end: with a prior-week baseline, the WoW section should
    surface a real signal (here: a >50% pace shift) in the markdown."""
    fake_buckets = [_bucket("Googlebot/2.1", 300, 200)]
    prior = _agg({"Googlebot": {"requests": 100}})

    async def _run():
        with patch("cf_bot_report._fetch_per_ua_buckets",
                   new=AsyncMock(return_value=fake_buckets)), \
             patch("cf_bot_report.is_configured", return_value=True), \
             patch("cf_bot_report._cfg", return_value={"zone_id": "zone123", "api_token": "t"}):
            return await cf_bot_report.generate_per_ua_report(
                prior=prior,
                now=datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc),
            )

    result = asyncio.run(_run())
    assert result is not None
    assert result["wow"]["had_baseline"] is True
    assert any(s["name"] == "Googlebot" for s in result["wow"]["pace_shifts"])
    assert "## Week-over-week changes" in result["markdown"]
    assert "Pace shifts" in result["markdown"]


def test_markdown_includes_wow_section_when_provided():
    data = _agg({"Googlebot": {"requests": 200}, "YandexBot": {"requests": 50}})
    last = _agg({"Googlebot": {"requests": 200}})
    wow = compose_wow_diff(data, last)
    md = format_report_markdown(
        data,
        since_iso="x", until_iso="y", zone_id="z",
        generated_at=datetime(2026, 4, 16, tzinfo=timezone.utc),
        wow=wow,
    )
    assert "## Week-over-week changes" in md
    assert "New crawlers this week" in md
    assert "YandexBot" in md


def test_markdown_wow_section_says_no_baseline_when_appropriate():
    data = _agg({"Googlebot": {"requests": 200}})
    wow = compose_wow_diff(data, None)
    md = format_report_markdown(
        data, since_iso="x", until_iso="y", zone_id="z",
        generated_at=datetime(2026, 4, 16, tzinfo=timezone.utc),
        wow=wow,
    )
    assert "No prior-week baseline" in md


def test_markdown_wow_section_says_no_changes_when_quiet():
    # Identical week → no notable signals.
    last = _agg({"Googlebot": {"requests": 200}})
    cur = _agg({"Googlebot": {"requests": 205}})  # < 50% delta
    wow = compose_wow_diff(cur, last)
    md = format_report_markdown(
        cur, since_iso="x", until_iso="y", zone_id="z",
        generated_at=datetime(2026, 4, 16, tzinfo=timezone.utc),
        wow=wow,
    )
    assert "No notable changes vs prior week" in md


# ── Schedule gate predicate ─────────────────────────────────────────────────

def test_should_run_cf_bot_report_only_on_monday_window():
    from routes import bot_discovery

    # Monday 2026-04-13 04:00 UTC — should run
    monday = datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc)
    assert bot_discovery._should_run_cf_bot_report_now(monday, "") is True

    # Monday 04:14 UTC — within ±15 min — should run
    assert bot_discovery._should_run_cf_bot_report_now(
        datetime(2026, 4, 13, 4, 14, tzinfo=timezone.utc), "") is True

    # Monday 04:30 UTC — outside ±15 min window
    assert bot_discovery._should_run_cf_bot_report_now(
        datetime(2026, 4, 13, 4, 30, tzinfo=timezone.utc), "") is False

    # Tuesday at the same time — wrong day
    tuesday = datetime(2026, 4, 14, 4, 0, tzinfo=timezone.utc)
    assert bot_discovery._should_run_cf_bot_report_now(tuesday, "") is False


def test_should_run_cf_bot_report_dedup_by_iso_week():
    from routes import bot_discovery

    monday = datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc)
    cur_week = bot_discovery._iso_week_tag(monday)
    # Already ran for this ISO week → should NOT re-run
    assert bot_discovery._should_run_cf_bot_report_now(monday, cur_week) is False
    # Last ran for a previous week → should run
    assert bot_discovery._should_run_cf_bot_report_now(monday, "2026-W14") is True


# ── _try_run_cf_bot_report_once integration ─────────────────────────────────

def test_try_run_skips_outside_window():
    from routes import bot_discovery

    db = MagicMock()
    db.job_locks.find_one = AsyncMock(return_value={})
    # Wednesday — outside Monday window.
    wed = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    result = asyncio.run(bot_discovery._try_run_cf_bot_report_once(db, wed))
    assert result["claimed"] is False
    assert result["stored"] is False


def test_try_run_stores_report_inside_window():
    from routes import bot_discovery

    fake_data = _agg({"Googlebot": {"requests": 50}})
    fake_result = {
        "data": fake_data,
        "wow": compose_wow_diff(fake_data, None),
        "markdown": "# stub\n",
        "since": "x", "until": "y", "zone_id": "z",
        "generated_at": "g",
    }

    db = MagicMock()
    # Pre-gate read: no prior run.
    db.job_locks.find_one = AsyncMock(return_value={})
    db.job_locks.find_one_and_update = AsyncMock(return_value=None)  # path A miss
    db.job_locks.insert_one = AsyncMock()                            # path B win

    # Reports collection: prior load returns nothing; update_one stores.
    reports_coll = MagicMock()
    reports_coll.find_one = AsyncMock(return_value=None)
    reports_coll.update_one = AsyncMock()
    db.__getitem__.return_value = reports_coll

    monday = datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc)
    with patch("cf_bot_report.generate_per_ua_report",
               new=AsyncMock(return_value=fake_result)):
        result = asyncio.run(bot_discovery._try_run_cf_bot_report_once(db, monday))

    assert result["claimed"] is True
    assert result["stored"] is True
    reports_coll.update_one.assert_awaited_once()
    args, kwargs = reports_coll.update_one.call_args
    # Filter is keyed on iso_week so re-runs upsert into the same doc.
    assert "iso_week" in args[0]


def test_write_cf_report_to_disk_creates_dated_files(tmp_path, monkeypatch):
    from routes import bot_discovery

    monkeypatch.setenv("CF_BOT_REPORT_DIR", str(tmp_path))
    now = datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc)
    raw = {"totals": {"requests": 5, "bots": 1}, "per_bot": {"Googlebot": {"requests": 5}}}
    path = bot_discovery._write_cf_report_to_disk("# hi\n", raw, now)
    assert path is not None
    md = tmp_path / "cloudflare-search-bots-per-ua-2026-04-13.md"
    sidecar = tmp_path / "cloudflare-search-bots-per-ua-2026-04-13.json"
    assert md.exists() and md.read_text() == "# hi\n"
    assert sidecar.exists()
    import json as _json
    assert _json.loads(sidecar.read_text())["totals"]["requests"] == 5


def test_write_cf_report_to_disk_returns_none_on_oserror(monkeypatch):
    from routes import bot_discovery

    # Point at a path under /proc which can't be written to as a directory.
    monkeypatch.setenv("CF_BOT_REPORT_DIR", "/proc/cf_bot_report_test_no_write")
    path = bot_discovery._write_cf_report_to_disk("x", {"totals": {}}, datetime.now(timezone.utc))
    assert path is None  # graceful no-op, did not raise


def test_try_run_writes_to_disk_after_storing(tmp_path, monkeypatch):
    from routes import bot_discovery

    monkeypatch.setenv("CF_BOT_REPORT_DIR", str(tmp_path))

    fake_data = _agg({"Googlebot": {"requests": 50}})
    fake_result = {
        "data": fake_data,
        "wow": compose_wow_diff(fake_data, None),
        "markdown": "# disk write test\n",
        "since": "x", "until": "y", "zone_id": "z", "generated_at": "g",
    }

    db = MagicMock()
    db.job_locks.find_one = AsyncMock(return_value={})
    db.job_locks.find_one_and_update = AsyncMock(return_value=None)
    db.job_locks.insert_one = AsyncMock()
    reports_coll = MagicMock()
    reports_coll.find_one = AsyncMock(return_value=None)
    reports_coll.update_one = AsyncMock()
    db.__getitem__.return_value = reports_coll

    monday = datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc)
    with patch("cf_bot_report.generate_per_ua_report",
               new=AsyncMock(return_value=fake_result)):
        result = asyncio.run(bot_discovery._try_run_cf_bot_report_once(db, monday))

    assert result["stored"] is True
    assert result["file_path"] is not None
    expected = tmp_path / "cloudflare-search-bots-per-ua-2026-04-13.md"
    assert expected.exists()
    assert expected.read_text() == "# disk write test\n"


def test_catchup_skips_when_week_already_stored():
    from routes import bot_discovery

    db = MagicMock()
    reports_coll = MagicMock()
    reports_coll.find_one = AsyncMock(return_value={"_id": "exists"})
    db.__getitem__.return_value = reports_coll

    now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
    result = asyncio.run(bot_discovery._cf_bot_report_catchup_if_missed(db, now))
    assert result == {"ran": False, "reason": "already_have_week"}


def test_catchup_runs_when_no_report_for_current_week(tmp_path, monkeypatch):
    from routes import bot_discovery

    monkeypatch.setenv("CF_BOT_REPORT_DIR", str(tmp_path))

    fake_data = _agg({"Googlebot": {"requests": 50}})
    fake_result = {
        "data": fake_data,
        "wow": compose_wow_diff(fake_data, None),
        "markdown": "# catchup\n",
        "since": "x", "until": "y", "zone_id": "z", "generated_at": "g",
    }

    db = MagicMock()
    reports_coll = MagicMock()
    # No existing doc for this week → catch-up should fire.
    reports_coll.find_one = AsyncMock(return_value=None)
    reports_coll.update_one = AsyncMock()
    db.__getitem__.return_value = reports_coll
    db.job_locks.find_one_and_update = AsyncMock(return_value=None)
    db.job_locks.insert_one = AsyncMock()  # claim wins via path B
    db.job_locks.update_one = AsyncMock()

    # Wednesday — well outside the Monday window, exactly the catch-up case.
    wed = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    with patch("cf_bot_report.generate_per_ua_report",
               new=AsyncMock(return_value=fake_result)):
        result = asyncio.run(bot_discovery._cf_bot_report_catchup_if_missed(db, wed))

    assert result["ran"] is True
    reports_coll.update_one.assert_awaited_once()
    args, _ = reports_coll.update_one.call_args
    assert args[1]["$set"]["catch_up"] is True


def test_try_run_rolls_back_marker_on_generate_failure():
    from routes import bot_discovery

    db = MagicMock()
    db.job_locks.find_one = AsyncMock(return_value={})
    db.job_locks.find_one_and_update = AsyncMock(return_value=None)
    db.job_locks.insert_one = AsyncMock()
    db.job_locks.update_one = AsyncMock()
    reports_coll = MagicMock()
    reports_coll.find_one = AsyncMock(return_value=None)
    db.__getitem__.return_value = reports_coll

    monday = datetime(2026, 4, 13, 4, 0, tzinfo=timezone.utc)
    with patch("cf_bot_report.generate_per_ua_report",
               new=AsyncMock(return_value=None)):
        result = asyncio.run(bot_discovery._try_run_cf_bot_report_once(db, monday))

    assert result["claimed"] is True
    assert result["stored"] is False
    # Roll back: marker reset so the next poll inside the window can retry.
    db.job_locks.update_one.assert_awaited_once()
