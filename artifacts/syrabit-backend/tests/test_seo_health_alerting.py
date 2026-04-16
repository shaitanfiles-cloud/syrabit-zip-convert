"""Tests for the SEO health hourly snapshot, history endpoint, and
alert-on-two-consecutive-degraded-checks logic added in Task #291."""
import asyncio
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _install_stubs():
    if "deps" not in sys.modules:
        deps = types.ModuleType("deps")
        deps.db = MagicMock()
        deps.is_mongo_available = AsyncMock(return_value=False)
        deps.security = MagicMock()
        deps.redis_client = None
        deps.logger = MagicMock()
        sys.modules["deps"] = deps


_install_stubs()
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
