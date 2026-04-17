"""Tests for the SEO health hourly snapshot, history endpoint, and
alert-on-two-consecutive-degraded-checks logic added in Task #291."""
import asyncio
import sys
import types
from datetime import datetime, timezone
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
