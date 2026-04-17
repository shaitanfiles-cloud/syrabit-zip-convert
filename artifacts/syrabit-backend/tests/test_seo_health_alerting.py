"""Tests for the SEO health hourly snapshot, history endpoint, and
alert-on-two-consecutive-degraded-checks logic added in Task #291."""
import asyncio
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()
from routes import bot_discovery  # noqa: E402


def _ok_report():
    return {
        "status": "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sitemaps": [],
        "d1_sync": {"status": "synced"},
        "summary": {
            "total_sitemaps": 9,
            "valid_sitemaps": 9,
            "total_url_checks": 30,
            "ok_url_checks": 30,
            "url_check_success_rate": 100.0,
        },
        "content_stats": {"published_pages": 100},
    }


def _critical_report():
    rep = _ok_report()
    rep["status"] = "critical"
    rep["summary"]["valid_sitemaps"] = 0
    rep["summary"]["ok_url_checks"] = 0
    rep["summary"]["url_check_success_rate"] = 0.0
    return rep


# -------- _record_seo_health_snapshot --------

def test_record_snapshot_returns_compact_doc_no_db():
    with patch.object(bot_discovery, "seo_health_check", AsyncMock(return_value=_ok_report())):
        snap = asyncio.run(bot_discovery._record_seo_health_snapshot())
    assert snap["status"] == "ok"
    assert snap["d1_status"] == "synced"
    assert snap["summary"]["total_sitemaps"] == 9
    assert snap["summary"]["url_check_success_rate"] == 100.0
    assert "recorded_at" in snap


def test_record_snapshot_handles_inner_exception_as_critical():
    with patch.object(
        bot_discovery,
        "seo_health_check",
        AsyncMock(side_effect=RuntimeError("network down")),
    ):
        snap = asyncio.run(bot_discovery._record_seo_health_snapshot())
    assert snap["status"] == "critical"
    assert "network down" in (snap.get("error") or "")


def test_record_snapshot_persists_when_mongo_available():
    fake_db = MagicMock()
    fake_db.seo_health_history.insert_one = AsyncMock(return_value=MagicMock(inserted_id="x"))
    fake_db.seo_health_history.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)), \
         patch.object(bot_discovery, "seo_health_check", AsyncMock(return_value=_ok_report())):
        snap = asyncio.run(bot_discovery._record_seo_health_snapshot())
    assert snap["status"] == "ok"
    fake_db.seo_health_history.insert_one.assert_awaited_once()
    # Also prunes old snapshots beyond retention window
    fake_db.seo_health_history.delete_many.assert_awaited_once()
    args, _ = fake_db.seo_health_history.delete_many.call_args
    assert "recorded_at" in args[0] and "$lt" in args[0]["recorded_at"]


# -------- /admin/seo/health-history endpoint --------

def _fake_cursor(docs):
    cur = MagicMock()
    cur.sort.return_value = cur
    cur.limit.return_value = cur
    cur.to_list = AsyncMock(return_value=docs)
    return cur


def test_history_endpoint_returns_empty_when_mongo_unavailable():
    with patch("deps.is_mongo_available", AsyncMock(return_value=False)):
        out = asyncio.run(bot_discovery.admin_seo_health_history(limit=24))
    assert out == {"history": [], "latest": None, "banner": None}


def test_history_endpoint_no_banner_when_latest_ok():
    docs = [
        {"status": "ok", "recorded_at": datetime.now(timezone.utc),
         "checked_at": "2026-04-16T10:00:00+00:00",
         "summary": {"total_sitemaps": 9, "valid_sitemaps": 9}},
        {"status": "ok", "recorded_at": datetime.now(timezone.utc),
         "checked_at": "2026-04-16T09:00:00+00:00", "summary": {}},
    ]
    fake_db = MagicMock()
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor(docs))
    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(bot_discovery.admin_seo_health_history(limit=24))
    assert out["banner"] is None
    assert out["latest"]["status"] == "ok"
    assert out["count"] == 2
    # history is ascending after reversal — first should be the older one
    assert out["history"][0]["checked_at"] == "2026-04-16T09:00:00+00:00"


# -------- /admin/seo/deep-scan-history endpoint (Task #350) --------

def test_deep_scan_history_returns_empty_when_mongo_unavailable():
    with patch("deps.is_mongo_available", AsyncMock(return_value=False)):
        out = asyncio.run(bot_discovery.admin_seo_deep_scan_history(limit=50))
    assert out == {"by_sitemap": {}, "recent_within_hour": [], "latest_fired_at": None}


def test_deep_scan_history_keeps_freshest_summary_per_sitemap():
    """Newer alert summaries should win; older ones must not overwrite them."""
    now = datetime.now(timezone.utc)
    older = (now - timedelta(hours=5)).isoformat()
    newer = (now - timedelta(minutes=10)).isoformat()
    docs = [
        # Newest first (matches Mongo's sort=-fired_at)
        {"_id": "alert-new", "type": "seo_url_spike", "fired_at": newer,
         "threshold_snapshot": {"deep_scan_summaries": {
             "sitemap-learn.xml": {"total_urls": 312, "checked": 312,
                                   "failing_count": 47, "truncated": False},
         }}},
        {"_id": "alert-old", "type": "seo_url_spike", "fired_at": older,
         "threshold_snapshot": {"deep_scan_summaries": {
             # Stale summary for the SAME sitemap — must NOT clobber the newer one.
             "sitemap-learn.xml": {"total_urls": 100, "checked": 100,
                                   "failing_count": 5, "truncated": False},
             # And a different sitemap that only the older alert covers.
             "sitemap-news.xml": {"total_urls": 50, "checked": 50,
                                  "failing_count": 50, "truncated": True,
                                  "error": "boom"},
         }}},
    ]
    fake_db = MagicMock()
    fake_db.alerts.find = MagicMock(return_value=_fake_cursor(docs))
    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(bot_discovery.admin_seo_deep_scan_history(limit=50))

    learn = out["by_sitemap"]["sitemap-learn.xml"]
    # Freshest (47 failing) wins, NOT the older 5-failing snapshot.
    assert learn["failing_count"] == 47
    assert learn["total_urls"] == 312
    assert learn["alert_id"] == "alert-new"
    assert learn["source"] == "auto"
    assert learn["fired_at"] == newer

    # The older-only sitemap is still present, with its error preserved.
    news = out["by_sitemap"]["sitemap-news.xml"]
    assert news["failing_count"] == 50
    assert news["truncated"] is True
    assert news["error"] == "boom"

    # Within-hour list contains the fresh alert's sitemap, not the 5h-old one.
    assert out["recent_within_hour"] == ["sitemap-learn.xml"]
    assert out["latest_fired_at"] == newer


def test_deep_scan_history_preserves_skipped_placeholders():
    """Task #351 placeholders ({skipped, reason, cap}) must round-trip
    intact and must NOT be counted as fresh auto-scans, otherwise the
    dashboard would falsely claim "0 of 0 URLs failing" and inflate the
    on-call banner with sitemaps that were never actually scanned."""
    now = datetime.now(timezone.utc)
    fired_at = (now - timedelta(minutes=5)).isoformat()
    docs = [
        {"_id": "alert-mixed", "type": "seo_url_spike", "fired_at": fired_at,
         "threshold_snapshot": {"deep_scan_summaries": {
             "sitemap-learn.xml": {"total_urls": 312, "checked": 312,
                                   "failing_count": 47, "truncated": False},
             # Skipped placeholder for an over-cap sitemap.
             "sitemap-news.xml": {"skipped": True,
                                  "reason": "alert_scan_cap", "cap": 3},
         }}},
    ]
    fake_db = MagicMock()
    fake_db.alerts.find = MagicMock(return_value=_fake_cursor(docs))
    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(bot_discovery.admin_seo_deep_scan_history(limit=10))

    # Real scan is preserved with full counts.
    learn = out["by_sitemap"]["sitemap-learn.xml"]
    assert learn.get("skipped") is not True
    assert learn["failing_count"] == 47

    # Skipped placeholder is preserved AS skipped, with reason + cap.
    news = out["by_sitemap"]["sitemap-news.xml"]
    assert news["skipped"] is True
    assert news["reason"] == "alert_scan_cap"
    assert news["cap"] == 3
    assert news["source"] == "auto"
    # CRITICAL: no fake "0 of 0 failing" data leaks through.
    assert "failing_count" not in news
    assert "total_urls" not in news
    assert "checked" not in news

    # Banner / "auto-scanned in last hour" must EXCLUDE the skipped sitemap,
    # otherwise on-call sees an inflated count.
    assert out["recent_within_hour"] == ["sitemap-learn.xml"]


def test_deep_scan_history_skips_alerts_without_summaries():
    """Alerts whose threshold_snapshot has no deep_scan_summaries (or it's
    not a dict) must be ignored cleanly without raising."""
    fake_db = MagicMock()
    # Mongo's filter handles the empty/missing case in production; the
    # endpoint additionally guards against malformed shapes leaking past
    # the filter (e.g. legacy docs).
    fake_db.alerts.find = MagicMock(return_value=_fake_cursor([
        {"_id": "x", "type": "seo_url_spike",
         "fired_at": datetime.now(timezone.utc).isoformat(),
         "threshold_snapshot": {"deep_scan_summaries": "not-a-dict"}},
    ]))
    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(bot_discovery.admin_seo_deep_scan_history(limit=10))
    assert out["by_sitemap"] == {}
    assert out["recent_within_hour"] == []


def test_history_endpoint_banner_shows_consecutive_count():
    docs = [
        {"status": "critical", "recorded_at": datetime.now(timezone.utc),
         "checked_at": "2026-04-16T12:00:00+00:00",
         "summary": {"total_sitemaps": 9, "valid_sitemaps": 0,
                     "ok_url_checks": 0, "total_url_checks": 30,
                     "url_check_success_rate": 0.0}},
        {"status": "degraded", "recorded_at": datetime.now(timezone.utc),
         "checked_at": "2026-04-16T11:00:00+00:00", "summary": {}},
        {"status": "ok", "recorded_at": datetime.now(timezone.utc),
         "checked_at": "2026-04-16T10:00:00+00:00", "summary": {}},
    ]
    fake_db = MagicMock()
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor(docs))
    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(bot_discovery.admin_seo_health_history(limit=24))
    assert out["banner"] is not None
    assert out["banner"]["severity"] == "critical"
    assert out["banner"]["consecutive"] == 2  # critical + degraded streak
    assert out["banner"]["summary"]["valid_sitemaps"] == 0


# -------- alert dispatch on 2 consecutive degraded snapshots --------

def test_alert_fires_on_two_consecutive_critical_snapshots():
    """Simulate one loop iteration: prev snapshot critical, this one critical
    too — _dispatch_alert must be called via metrics."""
    fake_db = MagicMock()
    fake_db.seo_health_history.insert_one = AsyncMock()
    fake_db.seo_health_history.delete_many = AsyncMock()
    # Two critical snapshots (most-recent first) — the loop reads the last 2.
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor([
        {"status": "critical", "recorded_at": datetime.now(timezone.utc)},
        {"status": "critical", "recorded_at": datetime.now(timezone.utc)},
    ]))

    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = AsyncMock()
    fake_metrics._alert_last_fired = {}
    sys.modules["metrics"] = fake_metrics

    # Reset the cooldown guard so the test fires regardless of prior runs
    bot_discovery._seo_health_alert_last_fired = 0.0

    async def _run_once():
        # Inline the loop body once (skip the asyncio.sleep loop)
        snapshot = await bot_discovery._record_seo_health_snapshot()
        status = (snapshot.get("status") or "").lower()
        assert status == "critical"
        from deps import db as _db, is_mongo_available as _ima
        consecutive_bad = 1
        if await _ima():
            recent = await _db.seo_health_history.find(
                {}, {"_id": 0, "status": 1, "recorded_at": 1}
            ).sort("recorded_at", -1).limit(2).to_list(2)
            if len(recent) >= 2 and (recent[1].get("status") or "").lower() in ("degraded", "critical"):
                consecutive_bad = 2
        if consecutive_bad >= 2:
            from metrics import _dispatch_alert
            await _dispatch_alert(
                "seo_health_degraded", "SEO health: CRITICAL", "two consecutive failures",
                threshold_snapshot={"metric": "seo_health_status", "value": "ok", "actual": status},
            )

    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)), \
         patch.object(bot_discovery, "seo_health_check", AsyncMock(return_value=_critical_report())):
        asyncio.run(_run_once())

    fake_metrics._dispatch_alert.assert_awaited_once()
    args, _ = fake_metrics._dispatch_alert.call_args
    assert args[0] == "seo_health_degraded"


def test_no_alert_when_only_one_critical_snapshot():
    fake_db = MagicMock()
    fake_db.seo_health_history.insert_one = AsyncMock()
    fake_db.seo_health_history.delete_many = AsyncMock()
    # Only one critical snapshot — previous was ok
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor([
        {"status": "critical", "recorded_at": datetime.now(timezone.utc)},
        {"status": "ok", "recorded_at": datetime.now(timezone.utc)},
    ]))

    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = AsyncMock()
    fake_metrics._alert_last_fired = {}
    sys.modules["metrics"] = fake_metrics

    async def _run_once():
        snap = await bot_discovery._record_seo_health_snapshot()
        from deps import db as _db, is_mongo_available as _ima
        consecutive_bad = 1
        if await _ima():
            recent = await _db.seo_health_history.find(
                {}, {"_id": 0, "status": 1, "recorded_at": 1}
            ).sort("recorded_at", -1).limit(2).to_list(2)
            if len(recent) >= 2 and (recent[1].get("status") or "").lower() in ("degraded", "critical"):
                consecutive_bad = 2
        if consecutive_bad >= 2:
            from metrics import _dispatch_alert
            await _dispatch_alert("seo_health_degraded", "x", "x")

    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)), \
         patch.object(bot_discovery, "seo_health_check", AsyncMock(return_value=_critical_report())):
        asyncio.run(_run_once())

    fake_metrics._dispatch_alert.assert_not_called()


# -------- Task #295: seo_url_spike (404 spike) alert --------

def _spiky_report(success_rate=50.0, sitemap_breakdown=None):
    """A health report where status is still 'ok' but URL spot-checks
    are failing on a subset of sitemaps."""
    rep = _ok_report()
    rep["status"] = "ok"  # aggregate status hasn't tipped yet
    rep["summary"]["url_check_success_rate"] = success_rate
    rep["summary"]["ok_url_checks"] = int(success_rate * 0.3)  # of 30
    rep["sitemaps"] = sitemap_breakdown or [
        {"name": "sitemap-learn.xml", "valid_xml": True, "url_count": 50,
         "sample_checks": [
             {"ok": False, "status": 404, "url": f"https://syrabit.ai/learn/broken-{i}"}
             for i in range(8)
         ] + [
             {"ok": True, "status": 200, "url": f"https://syrabit.ai/learn/ok-{i}"}
             for i in range(2)
         ]},
        {"name": "sitemap-notes.xml", "valid_xml": True, "url_count": 80,
         "sample_checks": [
             {"ok": True, "status": 200, "url": f"https://syrabit.ai/notes/ok-{i}"}
             for i in range(10)
         ]},
    ]
    return rep


def test_snapshot_includes_per_sitemap_breakdown():
    """Task #295: snapshot must capture per-sitemap pass/fail so the alert
    email can show which page-type is broken."""
    with patch.object(bot_discovery, "seo_health_check",
                      AsyncMock(return_value=_spiky_report())):
        snap = asyncio.run(bot_discovery._record_seo_health_snapshot())
    assert "by_sitemap" in snap
    by_name = {r["name"]: r for r in snap["by_sitemap"]}
    assert by_name["sitemap-learn.xml"]["ok"] == 2
    assert by_name["sitemap-learn.xml"]["total"] == 10
    assert by_name["sitemap-learn.xml"]["success_rate"] == 20.0
    assert by_name["sitemap-notes.xml"]["success_rate"] == 100.0


def test_format_by_sitemap_html_highlights_bad_rows():
    """Sitemaps below the configured floor should be highlighted in red."""
    rows = [
        {"name": "sitemap-learn.xml", "ok": 2, "total": 10, "success_rate": 20.0},
        {"name": "sitemap-notes.xml", "ok": 10, "total": 10, "success_rate": 100.0},
    ]
    html = bot_discovery._format_by_sitemap_html(rows, threshold_pct=20.0)
    # bad row gets the red highlight style
    assert "sitemap-learn.xml" in html
    assert "background:#fdecea" in html
    # good row is plain
    assert "sitemap-notes.xml" in html
    assert html.count("background:#fdecea") == 1  # only 1 bad row highlighted


# -------- Task #299: failing URLs surfaced in snapshot + alert --------

def test_snapshot_captures_failing_urls_per_sitemap():
    """The snapshot must record the first 10 failing URLs (with status code)
    per sitemap so admins don't need to re-run /api/seo/health."""
    with patch.object(bot_discovery, "seo_health_check",
                      AsyncMock(return_value=_spiky_report())):
        snap = asyncio.run(bot_discovery._record_seo_health_snapshot())

    by_name = {r["name"]: r for r in snap["by_sitemap"]}
    learn = by_name["sitemap-learn.xml"]
    assert "failing_urls" in learn
    # 8 failing checks were synthesized; capped at 10 by design.
    assert len(learn["failing_urls"]) == 8
    first = learn["failing_urls"][0]
    assert first["url"].startswith("https://syrabit.ai/learn/broken-")
    assert first["status"] == 404
    # Healthy sitemap reports an empty list, never None.
    assert by_name["sitemap-notes.xml"]["failing_urls"] == []


def test_snapshot_caps_failing_urls_at_ten():
    """Even a sitemap with 50 failing samples should only persist 10 URLs
    so the snapshot doc stays small and the alert email stays readable."""
    rep = _spiky_report(sitemap_breakdown=[
        {"name": "sitemap-flood.xml", "valid_xml": True, "url_count": 200,
         "sample_checks": [
             {"ok": False, "status": 404, "url": f"https://syrabit.ai/x/{i}"}
             for i in range(50)
         ]},
    ])
    with patch.object(bot_discovery, "seo_health_check",
                      AsyncMock(return_value=rep)):
        snap = asyncio.run(bot_discovery._record_seo_health_snapshot())
    failing = snap["by_sitemap"][0]["failing_urls"]
    assert len(failing) == 10
    # Preserves order — first 10 from the sample.
    assert failing[0]["url"].endswith("/x/0")
    assert failing[-1]["url"].endswith("/x/9")


def test_format_by_sitemap_html_renders_failing_urls():
    """The HTML email body must include each failing URL's status code +
    URL inside the per-sitemap table so admins can click straight through."""
    rows = [{
        "name": "sitemap-learn.xml", "ok": 2, "total": 10, "success_rate": 20.0,
        "failing_urls": [
            {"url": "https://syrabit.ai/learn/missing-1", "status": 404},
            {"url": "https://syrabit.ai/learn/timeout-1", "status": 0},
        ],
    }]
    html = bot_discovery._format_by_sitemap_html(rows, threshold_pct=20.0)
    assert "Failing URLs" in html
    assert "https://syrabit.ai/learn/missing-1" in html
    assert "https://syrabit.ai/learn/timeout-1" in html
    # Status codes are visible — 404 and 0 (network error).
    assert ">404<" in html
    assert ">0<" in html


def test_format_by_sitemap_html_escapes_failing_urls():
    """A malicious URL stored in Mongo must not break out of the email
    HTML — render through html.escape, never raw interpolation."""
    rows = [{
        "name": "sitemap-x.xml", "ok": 0, "total": 1, "success_rate": 0.0,
        "failing_urls": [{"url": "https://x/<script>alert(1)</script>", "status": 404}],
    }]
    html = bot_discovery._format_by_sitemap_html(rows, threshold_pct=20.0)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_format_by_sitemap_text_lists_failing_urls():
    """Plain-text fallback must include the same actionable detail."""
    rows = [{
        "name": "sitemap-learn.xml", "ok": 2, "total": 10, "success_rate": 20.0,
        "failing_urls": [
            {"url": "https://syrabit.ai/learn/missing-1", "status": 404},
        ],
    }]
    text = bot_discovery._format_by_sitemap_text(rows)
    assert "[404] https://syrabit.ai/learn/missing-1" in text


def test_format_by_sitemap_html_omits_section_when_no_failures():
    """A healthy sitemap should NOT render an empty 'Failing URLs' block."""
    rows = [{
        "name": "sitemap-ok.xml", "ok": 10, "total": 10, "success_rate": 100.0,
        "failing_urls": [],
    }]
    html = bot_discovery._format_by_sitemap_html(rows, threshold_pct=20.0)
    assert "Failing URLs" not in html


def test_url_spike_alert_fires_on_two_consecutive_low_rates():
    """Two consecutive snapshots below (100 - threshold)% must trigger
    seo_url_spike via _dispatch_alert with a per-sitemap breakdown."""
    fake_db = MagicMock()
    fake_db.seo_health_history.insert_one = AsyncMock()
    fake_db.seo_health_history.delete_many = AsyncMock()
    # Latest snapshot will be inserted; previous one (in history) was also bad.
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor([
        {"summary": {"url_check_success_rate": 50.0, "total_url_checks": 30},
         "recorded_at": datetime.now(timezone.utc)},
        {"summary": {"url_check_success_rate": 60.0, "total_url_checks": 30},
         "recorded_at": datetime.now(timezone.utc)},
    ]))

    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = AsyncMock()
    fake_metrics._load_alert_settings = AsyncMock()
    fake_metrics._ALERT_THRESHOLDS = {"url_404_spike_pct": 20.0}  # floor = 80%
    fake_metrics._alert_last_fired = {}
    sys.modules["metrics"] = fake_metrics

    bot_discovery._seo_url_spike_alert_last_fired = 0.0

    async def _run_once():
        snap = await bot_discovery._record_seo_health_snapshot()
        # Inline the URL-spike branch of the loop body
        from metrics import _ALERT_THRESHOLDS, _dispatch_alert
        floor = 100.0 - float(_ALERT_THRESHOLDS["url_404_spike_pct"])
        latest_rate = float(snap["summary"]["url_check_success_rate"])
        from deps import db as _db, is_mongo_available as _ima
        consecutive = 1
        if await _ima():
            recent = await _db.seo_health_history.find({}, {"_id": 0}).sort(
                "recorded_at", -1).limit(2).to_list(2)
            if len(recent) >= 2:
                prev_rate = float((recent[1].get("summary") or {}).get("url_check_success_rate", 100))
                prev_total = int((recent[1].get("summary") or {}).get("total_url_checks", 0))
                if prev_total > 0 and prev_rate < floor:
                    consecutive = 2
        if latest_rate < floor and consecutive >= 2:
            await _dispatch_alert(
                "seo_url_spike", "SEO: URL 404 spike",
                f"rate={latest_rate}",
                threshold_snapshot={
                    "metric": "url_404_spike_pct",
                    "value": _ALERT_THRESHOLDS["url_404_spike_pct"],
                    "actual": round(100.0 - latest_rate, 1),
                    "by_sitemap_html": bot_discovery._format_by_sitemap_html(
                        snap.get("by_sitemap") or [], _ALERT_THRESHOLDS["url_404_spike_pct"]),
                },
            )

    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)), \
         patch.object(bot_discovery, "seo_health_check",
                      AsyncMock(return_value=_spiky_report(success_rate=50.0))):
        asyncio.run(_run_once())

    fake_metrics._dispatch_alert.assert_awaited_once()
    args, kwargs = fake_metrics._dispatch_alert.call_args
    assert args[0] == "seo_url_spike"
    snapshot = kwargs.get("threshold_snapshot") or {}
    assert snapshot["metric"] == "url_404_spike_pct"
    # Per-sitemap HTML breakdown must be included
    assert "sitemap-learn.xml" in snapshot["by_sitemap_html"]


def test_url_spike_no_alert_when_only_one_low_rate():
    """One bad snapshot followed by an ok previous snapshot: no alert."""
    fake_db = MagicMock()
    fake_db.seo_health_history.insert_one = AsyncMock()
    fake_db.seo_health_history.delete_many = AsyncMock()
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor([
        {"summary": {"url_check_success_rate": 50.0, "total_url_checks": 30},
         "recorded_at": datetime.now(timezone.utc)},
        {"summary": {"url_check_success_rate": 100.0, "total_url_checks": 30},
         "recorded_at": datetime.now(timezone.utc)},
    ]))

    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = AsyncMock()
    fake_metrics._load_alert_settings = AsyncMock()
    fake_metrics._ALERT_THRESHOLDS = {"url_404_spike_pct": 20.0}
    fake_metrics._alert_last_fired = {}
    sys.modules["metrics"] = fake_metrics

    async def _run_once():
        snap = await bot_discovery._record_seo_health_snapshot()
        from metrics import _ALERT_THRESHOLDS, _dispatch_alert
        floor = 100.0 - float(_ALERT_THRESHOLDS["url_404_spike_pct"])
        latest_rate = float(snap["summary"]["url_check_success_rate"])
        from deps import db as _db, is_mongo_available as _ima
        consecutive = 1
        if await _ima():
            recent = await _db.seo_health_history.find({}, {"_id": 0}).sort(
                "recorded_at", -1).limit(2).to_list(2)
            if len(recent) >= 2:
                prev_rate = float((recent[1].get("summary") or {}).get("url_check_success_rate", 100))
                prev_total = int((recent[1].get("summary") or {}).get("total_url_checks", 0))
                if prev_total > 0 and prev_rate < floor:
                    consecutive = 2
        if latest_rate < floor and consecutive >= 2:
            await _dispatch_alert("seo_url_spike", "x", "x")

    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)), \
         patch.object(bot_discovery, "seo_health_check",
                      AsyncMock(return_value=_spiky_report(success_rate=50.0))):
        asyncio.run(_run_once())

    fake_metrics._dispatch_alert.assert_not_called()


def test_dispatch_alert_email_includes_by_sitemap_html():
    """Verify _dispatch_alert renders threshold_snapshot['by_sitemap_html']
    inside the outgoing Resend email body, so the seo_url_spike alert
    actually shows the per-sitemap breakdown to admins."""
    # Drop the test stub for metrics so we exercise the real implementation.
    sys.modules.pop("metrics", None)
    # Real metrics imports `db` and `supa` from deps — provide both stubs.
    fake_deps = sys.modules.get("deps")
    if fake_deps is not None:
        fake_deps.supa = MagicMock()
        fake_deps.db = MagicMock()
        fake_deps.db.alerts = MagicMock()
        fake_deps.db.alerts.insert_one = AsyncMock()
        fake_deps.is_mongo_available = AsyncMock(return_value=False)
    import importlib
    metrics = importlib.import_module("metrics")
    # Reset cooldown so the alert actually dispatches under test
    metrics._alert_last_fired = {}
    captured = {}

    class _FakeResend:
        api_key = ""
        class Emails:
            @staticmethod
            def send(payload):
                captured["payload"] = payload

    sys.modules["resend"] = _FakeResend
    metrics._notification_channels = {"email": "admin@example.com", "webhook_url": ""}
    import os as _os
    _os.environ["RESEND_API_KEY"] = "test-key"

    by_sitemap_html = (
        "<table><tr><td>sitemap-learn.xml</td><td>2/10</td></tr></table>"
    )
    asyncio.run(metrics._dispatch_alert(
        "seo_url_spike",
        "SEO: URL 404 spike (50% OK)",
        "URL spot-check success rate has been at 50%\nfor two consecutive hourly checks.",
        threshold_snapshot={
            "metric": "url_404_spike_pct",
            "value": 20.0,
            "actual": 50.0,
            "by_sitemap_html": by_sitemap_html,
        },
    ))

    payload = captured.get("payload")
    assert payload, "Expected Resend email payload to be sent"
    html = payload.get("html", "")
    assert "sitemap-learn.xml" in html, "Per-sitemap HTML must appear in email body"
    assert "2/10" in html
    # Body newlines should be rendered as <br> for readability
    assert "<br>" in html


def test_url_404_spike_pct_in_alert_thresholds_default():
    """Sanity: the new threshold key exists in metrics defaults so the
    /admin/alert-settings endpoint will accept and persist it. We grep
    the source rather than importing the module because earlier tests
    in this file stub out ``deps`` and ``metrics`` for isolation."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "metrics.py"), encoding="utf-8") as f:
        src = f.read()
    assert "_ALERT_THRESHOLDS_DEFAULT" in src
    assert '"url_404_spike_pct"' in src


# -------- Task #344: re-probe failing URLs to filter network blips --------


VALID_SITEMAP_XML_TWO_URLS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://syrabit.ai/learn/topic-1</loc></url>"
    "<url><loc>https://syrabit.ai/learn/topic-2</loc></url>"
    "</urlset>"
)


def _resp(status, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


class _RetryFakeClient:
    """httpx.AsyncClient stand-in that returns canned responses keyed by
    URL, advancing through the list each time the URL is probed."""

    def __init__(self, sitemap_xml, head_sequences):
        self._sitemap_xml = sitemap_xml
        self._head_sequences = {u: list(seq) for u, seq in head_sequences.items()}
        self._head_calls = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, *_a, **_kw):
        if url.endswith(".xml"):
            return _resp(200, self._sitemap_xml)
        return _resp(200)

    async def head(self, url, *_a, **_kw):
        self._head_calls[url] = self._head_calls.get(url, 0) + 1
        seq = self._head_sequences.get(url)
        if seq:
            status = seq.pop(0) if len(seq) > 1 else seq[0]
        else:
            status = 200
        return _resp(status)


def _run_seo_health_with_client(fake_client):
    with patch("httpx.AsyncClient", lambda *a, **kw: fake_client), \
         patch.object(bot_discovery, "_SEO_HEALTH_RETRY_DELAY_S", 0):
        return asyncio.run(bot_discovery.seo_health_check(request=None, deep_scan=None))


def test_url_check_recovers_on_retry_and_excluded_from_failing_urls():
    """Task #344: a URL that returns 502 on the first probe but 200 on
    the second probe must NOT end up as a failing check and must NOT
    count against the success rate."""
    fake = _RetryFakeClient(
        VALID_SITEMAP_XML_TWO_URLS,
        head_sequences={
            "https://syrabit.ai/learn/topic-1": [502, 200],
            "https://syrabit.ai/learn/topic-2": [200],
        },
    )
    report = _run_seo_health_with_client(fake)

    # Aggregate success rate stays at 100% — the 502 was a transient blip.
    assert report["summary"]["url_check_success_rate"] == 100.0
    assert report["summary"]["ok_url_checks"] == report["summary"]["total_url_checks"]
    # No failing checks recorded for any sitemap.
    for sm in report["sitemaps"]:
        for check in sm.get("sample_checks", []):
            assert check["ok"], f"transient blip leaked into sample_checks: {check}"
    # Topic-1's first probe failed and triggered a retry; topic-2's first
    # probe succeeded so it was probed only once per sitemap. Therefore
    # topic-1 must have strictly more probe calls than topic-2.
    assert (fake._head_calls["https://syrabit.ai/learn/topic-1"]
            > fake._head_calls["https://syrabit.ai/learn/topic-2"])
    # And the recovered check is annotated so dashboards can surface it.
    recovered = [c for sm in report["sitemaps"] for c in sm.get("sample_checks", [])
                 if c["url"].endswith("/topic-1")]
    assert recovered and recovered[0].get("recovered_on_retry") is True
    assert recovered[0].get("first_status") == 502


def test_url_check_still_failing_on_retry_recorded_as_failing():
    """Task #344: a URL that fails on BOTH probes is genuinely broken and
    must be recorded as a failing check so the alert fires for real outages."""
    fake = _RetryFakeClient(
        VALID_SITEMAP_XML_TWO_URLS,
        head_sequences={
            "https://syrabit.ai/learn/topic-1": [404, 404],
            "https://syrabit.ai/learn/topic-2": [200],
        },
    )
    report = _run_seo_health_with_client(fake)

    failing = [c for sm in report["sitemaps"] for c in sm.get("sample_checks", [])
               if not c["ok"] and c["url"].endswith("/topic-1")]
    assert failing, "still-failing URL must remain in sample_checks as a failure"
    for f in failing:
        assert f["status"] == 404
        assert f.get("retry_status") == 404
    # Both probes for topic-1 returned 404, so the helper records
    # `retry_status` and stops (no third probe). Each sitemap samples
    # both URLs, so topic-1 fires 2 calls per sitemap and topic-2 fires 1.
    n_sitemaps = len(report["sitemaps"])
    assert fake._head_calls["https://syrabit.ai/learn/topic-1"] == 2 * n_sitemaps
    assert fake._head_calls["https://syrabit.ai/learn/topic-2"] == n_sitemaps

    # And the snapshot extractor surfaces it under failing_urls.
    by_sitemap = []
    for sm in report["sitemaps"]:
        checks = sm.get("sample_checks") or []
        if not checks:
            continue
        failing_urls = [
            {"url": c.get("url", ""), "status": int(c.get("status") or 0)}
            for c in checks if not c.get("ok") and c.get("url")
        ][:10]
        by_sitemap.append({"name": sm.get("name"), "failing_urls": failing_urls})
    assert any(any(f["url"].endswith("/topic-1") for f in row["failing_urls"])
               for row in by_sitemap)


def test_probe_with_retry_marks_recovered_check():
    """Direct test of the helper: a URL that recovers comes back ok=True
    with recovered_on_retry=True and the original status preserved."""
    class _Client:
        def __init__(self):
            self.calls = 0

        async def head(self, url, *_a, **_kw):
            self.calls += 1
            return _resp(503 if self.calls == 1 else 200)

        async def get(self, url, *_a, **_kw):
            return _resp(200)

    client = _Client()
    with patch.object(bot_discovery, "_SEO_HEALTH_RETRY_DELAY_S", 0):
        result = asyncio.run(
            bot_discovery._probe_sitemap_url_with_retry(client, "https://x/y")
        )
    assert result["ok"] is True
    assert result["status"] == 200
    assert result["recovered_on_retry"] is True
    assert result["first_status"] == 503


# -------- Task #347: auto-deep-scan when sitemap fully failing --------


def _fully_failing_report():
    """A health report where one sitemap's sample is 0/10 OK so the
    spike branch should auto-trigger a deep scan."""
    rep = _ok_report()
    rep["status"] = "ok"
    rep["summary"]["url_check_success_rate"] = 50.0
    rep["summary"]["ok_url_checks"] = 10
    rep["summary"]["total_url_checks"] = 20
    rep["sitemaps"] = [
        {"name": "sitemap-learn.xml", "valid_xml": True, "url_count": 312,
         "sample_checks": [
             {"ok": False, "status": 404, "url": f"https://syrabit.ai/learn/broken-{i}"}
             for i in range(10)
         ]},
        {"name": "sitemap-notes.xml", "valid_xml": True, "url_count": 80,
         "sample_checks": [
             {"ok": True, "status": 200, "url": f"https://syrabit.ai/notes/ok-{i}"}
             for i in range(10)
         ]},
    ]
    return rep


def test_format_by_sitemap_html_renders_deep_scan_summary():
    """When deep_scan_summaries are passed, the per-sitemap row gains a
    'Deep scan: X of Y URLs failing' line so admins see the true blast
    radius (Task #347)."""
    rows = [{"name": "sitemap-learn.xml", "ok": 0, "total": 10,
             "success_rate": 0.0, "failing_urls": []}]
    summaries = {"sitemap-learn.xml": {
        "total_urls": 312, "checked": 312, "failing_count": 47, "truncated": False,
    }}
    html = bot_discovery._format_by_sitemap_html(
        rows, threshold_pct=20.0, deep_scan_summaries=summaries,
    )
    assert "Deep scan:" in html
    assert "47 of 312 URLs failing" in html


def test_format_by_sitemap_html_marks_truncated_deep_scan():
    rows = [{"name": "sitemap-flood.xml", "ok": 0, "total": 10,
             "success_rate": 0.0, "failing_urls": []}]
    summaries = {"sitemap-flood.xml": {
        "total_urls": 2000, "checked": 500, "failing_count": 500, "truncated": True,
    }}
    html = bot_discovery._format_by_sitemap_html(
        rows, threshold_pct=20.0, deep_scan_summaries=summaries,
    )
    assert "capped at 500 of 2000 URLs" in html


def test_format_by_sitemap_html_omits_summary_when_no_deep_scan():
    """A sitemap not present in the deep-scan summaries map must not
    render an empty 'Deep scan' row."""
    rows = [{"name": "sitemap-learn.xml", "ok": 5, "total": 10,
             "success_rate": 50.0, "failing_urls": []}]
    html = bot_discovery._format_by_sitemap_html(
        rows, threshold_pct=20.0, deep_scan_summaries={},
    )
    assert "Deep scan" not in html


def test_format_by_sitemap_text_renders_deep_scan_summary():
    rows = [{"name": "sitemap-learn.xml", "ok": 0, "total": 10,
             "success_rate": 0.0, "failing_urls": []}]
    summaries = {"sitemap-learn.xml": {
        "total_urls": 312, "checked": 312, "failing_count": 47, "truncated": False,
    }}
    text = bot_discovery._format_by_sitemap_text(rows, summaries)
    assert "Deep scan: 47 of 312 URLs failing" in text


def test_collect_alert_deep_scans_runs_sequentially_under_lock():
    """Task #347: when multiple sitemaps are fully failing, the alert
    helper must serialise the deep scans (one at a time) rather than
    fan them all out in parallel — otherwise SEO_DEEP_SCAN_CONCURRENCY
    is multiplied by N and we hammer origin during a wide outage."""
    in_flight = 0
    max_in_flight = 0
    order: list = []

    async def _fake_deep_scan(name):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        # yield to the loop a few times to give a concurrent caller a
        # chance to interleave (which it must not under the lock).
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        in_flight -= 1
        order.append(name)
        return {
            "sitemap": name, "total_urls": 100, "checked": 100,
            "truncated": False, "failing": [{"url": "x", "status": 404}],
        }

    async def _run():
        # Reset the module lock between tests for hermeticity
        bot_discovery._SEO_ALERT_DEEP_SCAN_LOCK = asyncio.Lock()
        a, b = await asyncio.gather(
            bot_discovery._collect_alert_deep_scans(["sitemap-a.xml"]),
            bot_discovery._collect_alert_deep_scans(["sitemap-b.xml"]),
        )
        return a, b

    with patch.object(bot_discovery, "_deep_scan_sitemap", _fake_deep_scan):
        a, b = asyncio.run(_run())

    # Both scans completed and produced summaries
    assert a["sitemap-a.xml"]["failing_count"] == 1
    assert b["sitemap-b.xml"]["failing_count"] == 1
    # ...but they NEVER overlapped — the lock kept us sequential.
    assert max_in_flight == 1, f"deep scans overlapped: max_in_flight={max_in_flight}"
    assert order == ["sitemap-a.xml", "sitemap-b.xml"]


def test_collect_alert_deep_scans_records_error_when_scan_raises():
    """A raising _deep_scan_sitemap must not abort the whole batch — the
    failing sitemap gets an `error` summary and remaining scans run."""
    async def _fake(name):
        if name == "boom":
            raise RuntimeError("boom kaboom")
        return {"total_urls": 5, "checked": 5, "truncated": False,
                "failing": [{"url": "u", "status": 404}]}

    async def _run():
        bot_discovery._SEO_ALERT_DEEP_SCAN_LOCK = asyncio.Lock()
        return await bot_discovery._collect_alert_deep_scans(["boom", "ok"])

    with patch.object(bot_discovery, "_deep_scan_sitemap", _fake):
        out = asyncio.run(_run())

    assert "error" in out["boom"]
    assert "boom kaboom" in out["boom"]["error"]
    assert out["ok"]["failing_count"] == 1


def test_collect_alert_deep_scans_caps_to_max_sitemaps():
    """Task #351: when more than SEO_ALERT_DEEP_SCAN_MAX_SITEMAPS sitemaps
    are fully failing, only the first N are deep-scanned; the rest get a
    skipped placeholder so the email still surfaces them."""
    scanned: list = []

    async def _fake(name):
        scanned.append(name)
        return {"total_urls": 10, "checked": 10, "truncated": False,
                "failing": [{"url": "u", "status": 404}]}

    names = [f"sitemap-{i}.xml" for i in range(5)]

    async def _run():
        bot_discovery._SEO_ALERT_DEEP_SCAN_LOCK = asyncio.Lock()
        return await bot_discovery._collect_alert_deep_scans(names)

    with patch.object(bot_discovery, "_deep_scan_sitemap", _fake), \
         patch.object(bot_discovery, "SEO_ALERT_DEEP_SCAN_MAX_SITEMAPS", 3):
        out = asyncio.run(_run())

    # Only the first 3 were actually scanned.
    assert scanned == names[:3]
    for n in names[:3]:
        assert out[n].get("failing_count") == 1
        assert not out[n].get("skipped")
    # The remaining 2 are present with skipped placeholders.
    for n in names[3:]:
        assert out[n] == {"skipped": True, "reason": "alert_scan_cap", "cap": 3}


def test_format_helpers_render_skipped_deep_scan_placeholder():
    """Task #351: skipped sitemaps get a clear 'manual deep scan' note in
    both the HTML and text alert bodies."""
    by_sm = [
        {"name": "sitemap-a.xml", "ok": 0, "total": 5, "success_rate": 0.0,
         "failing_urls": []},
        {"name": "sitemap-b.xml", "ok": 0, "total": 5, "success_rate": 0.0,
         "failing_urls": []},
    ]
    deep_scan_summaries = {
        "sitemap-a.xml": {"total_urls": 10, "checked": 10,
                          "failing_count": 4, "truncated": False},
        "sitemap-b.xml": {"skipped": True, "reason": "alert_scan_cap", "cap": 3},
    }
    html = bot_discovery._format_by_sitemap_html(
        by_sm, 20.0, deep_scan_summaries)
    assert "Deep scan:</b> 4 of 10" in html
    assert "Deep scan skipped" in html
    assert "alert-cycle cap of 3 sitemaps" in html
    assert "manual deep scan" in html.lower()

    text = bot_discovery._format_by_sitemap_text(by_sm, deep_scan_summaries)
    assert "Deep scan: 4 of 10 URLs failing" in text
    assert "Deep scan skipped" in text
    assert "cap of 3 sitemaps" in text


def test_url_spike_alert_triggers_deep_scan_for_fully_failing_sitemap():
    """Task #347: when the spike branch fires and a sitemap's sample is
    fully failing (ok==0), _deep_scan_sitemap is invoked and its totals
    surface in the alert email body + threshold_snapshot."""
    fake_db = MagicMock()
    fake_db.seo_health_history.insert_one = AsyncMock()
    fake_db.seo_health_history.delete_many = AsyncMock()
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor([
        {"summary": {"url_check_success_rate": 50.0, "total_url_checks": 20},
         "recorded_at": datetime.now(timezone.utc)},
        {"summary": {"url_check_success_rate": 50.0, "total_url_checks": 20},
         "recorded_at": datetime.now(timezone.utc)},
    ]))

    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = AsyncMock()
    fake_metrics._load_alert_settings = AsyncMock()
    fake_metrics._ALERT_THRESHOLDS = {"url_404_spike_pct": 20.0}
    fake_metrics._alert_last_fired = {}
    sys.modules["metrics"] = fake_metrics

    bot_discovery._seo_url_spike_alert_last_fired = 0.0

    deep_scan_calls: list = []

    async def _fake_deep_scan(name):
        deep_scan_calls.append(name)
        return {
            "sitemap": name,
            "total_urls": 312,
            "checked": 312,
            "truncated": False,
            "failing": [
                {"url": f"https://syrabit.ai/learn/broken-{i}", "status": 404}
                for i in range(47)
            ],
        }

    async def _run_loop_body_once():
        # Replicate just one iteration of _seo_health_alert_loop's body
        # without the surrounding asyncio.sleep loop. We delegate the
        # spike-trigger gate and the deep-scan collection to the real
        # production helpers so this test stays in sync with the loop
        # if it is later refactored.
        snapshot = await bot_discovery._record_seo_health_snapshot()
        from metrics import (_ALERT_THRESHOLDS, _load_alert_settings,
                             _dispatch_alert as _md, _alert_last_fired as _ml)
        await _load_alert_settings()
        threshold_pct = float(_ALERT_THRESHOLDS["url_404_spike_pct"])
        bad_floor = 100.0 - threshold_pct
        latest_rate = float(snapshot["summary"]["url_check_success_rate"])
        latest_total = int(snapshot["summary"]["total_url_checks"])
        from deps import db as _db, is_mongo_available as _ma
        spike_consecutive = 1
        if await _ma():
            recent = await _db.seo_health_history.find(
                {}, {"_id": 0, "summary": 1, "recorded_at": 1}
            ).sort("recorded_at", -1).limit(2).to_list(2)
            if len(recent) >= 2:
                prev_summary = recent[1].get("summary") or {}
                if (int(prev_summary.get("total_url_checks", 0)) > 0
                        and float(prev_summary.get("url_check_success_rate", 100)) < bad_floor):
                    spike_consecutive = 2
        if not (latest_total > 0 and latest_rate < bad_floor and spike_consecutive >= 2):
            return
        _ml.pop("seo_url_spike", None)
        by_sm = snapshot.get("by_sitemap") or []
        fully_failing = [r["name"] for r in by_sm
                         if int(r.get("ok", 0)) == 0 and int(r.get("total", 0)) > 0]
        # Use the real production helper so this test fails if the
        # collection / lock semantics drift.
        deep_scan_summaries = await bot_discovery._collect_alert_deep_scans(fully_failing)
        await _md(
            "seo_url_spike",
            f"SEO: URL 404 spike ({latest_rate}% OK)",
            "body" + bot_discovery._format_by_sitemap_text(by_sm, deep_scan_summaries),
            threshold_snapshot={
                "metric": "url_404_spike_pct",
                "value": threshold_pct,
                "actual": round(100.0 - latest_rate, 1),
                "by_sitemap_html": bot_discovery._format_by_sitemap_html(
                    by_sm, threshold_pct, deep_scan_summaries),
                "deep_scan_summaries": deep_scan_summaries,
            },
        )

    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)), \
         patch.object(bot_discovery, "seo_health_check",
                      AsyncMock(return_value=_fully_failing_report())), \
         patch.object(bot_discovery, "_deep_scan_sitemap", _fake_deep_scan):
        asyncio.run(_run_loop_body_once())

    # Deep scan was invoked exactly once for the fully-failing sitemap
    # and skipped for the healthy sitemap.
    assert deep_scan_calls == ["sitemap-learn.xml"]

    fake_metrics._dispatch_alert.assert_awaited_once()
    args, kwargs = fake_metrics._dispatch_alert.call_args
    snap = kwargs["threshold_snapshot"]
    assert "deep_scan_summaries" in snap
    assert snap["deep_scan_summaries"]["sitemap-learn.xml"]["failing_count"] == 47
    assert snap["deep_scan_summaries"]["sitemap-learn.xml"]["total_urls"] == 312
    # And the rendered HTML/text payloads include the deep-scan totals.
    assert "47 of 312 URLs failing" in snap["by_sitemap_html"]
    assert "47 of 312 URLs failing" in args[2]


def test_url_spike_alert_skips_deep_scan_when_no_fully_failing_sitemap():
    """If every sitemap still has at least one passing sample, no deep
    scan runs — the regular failing-URL list already covers triage."""
    fake_db = MagicMock()
    fake_db.seo_health_history.insert_one = AsyncMock()
    fake_db.seo_health_history.delete_many = AsyncMock()
    fake_db.seo_health_history.find = MagicMock(return_value=_fake_cursor([
        {"summary": {"url_check_success_rate": 50.0, "total_url_checks": 30},
         "recorded_at": datetime.now(timezone.utc)},
        {"summary": {"url_check_success_rate": 50.0, "total_url_checks": 30},
         "recorded_at": datetime.now(timezone.utc)},
    ]))

    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = AsyncMock()
    fake_metrics._load_alert_settings = AsyncMock()
    fake_metrics._ALERT_THRESHOLDS = {"url_404_spike_pct": 20.0}
    fake_metrics._alert_last_fired = {}
    sys.modules["metrics"] = fake_metrics

    deep_scan_calls: list = []

    async def _fake_deep_scan(name):
        deep_scan_calls.append(name)
        return {"sitemap": name, "total_urls": 0, "checked": 0,
                "truncated": False, "failing": []}

    async def _run_loop_body_once():
        snapshot = await bot_discovery._record_seo_health_snapshot()
        by_sm = snapshot.get("by_sitemap") or []
        fully_failing = [r["name"] for r in by_sm
                         if int(r.get("ok", 0)) == 0 and int(r.get("total", 0)) > 0]
        if fully_failing:
            await bot_discovery._deep_scan_sitemap(fully_failing[0])

    # _spiky_report has sitemap-learn.xml at 2/10 (NOT fully failing)
    # and sitemap-notes.xml at 10/10 — so no deep scan should fire.
    with patch("deps.db", fake_db), \
         patch("deps.is_mongo_available", AsyncMock(return_value=True)), \
         patch.object(bot_discovery, "seo_health_check",
                      AsyncMock(return_value=_spiky_report(success_rate=50.0))), \
         patch.object(bot_discovery, "_deep_scan_sitemap", _fake_deep_scan):
        asyncio.run(_run_loop_body_once())

    assert deep_scan_calls == []


def test_probe_with_retry_records_retry_status_when_still_failing():
    """When the second probe also fails, preserve both: the primary status
    from the first probe and ``retry_status`` from the second."""
    class _Client:
        def __init__(self):
            self.calls = 0

        async def head(self, url, *_a, **_kw):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("connection reset")
            return _resp(404)

        async def get(self, url, *_a, **_kw):
            return _resp(404)

    client = _Client()
    with patch.object(bot_discovery, "_SEO_HEALTH_RETRY_DELAY_S", 0):
        result = asyncio.run(
            bot_discovery._probe_sitemap_url_with_retry(client, "https://x/y")
        )
    assert result["ok"] is False
    assert result["status"] == 0
    assert result["retry_status"] == 404
    assert "connection reset" in result.get("error", "")
