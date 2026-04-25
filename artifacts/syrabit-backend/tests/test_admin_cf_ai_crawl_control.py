"""Tests for the admin CF AI Crawl Control card.

Covers:
- The pure helpers in ``cf_bot_report`` (``is_ai_bot``, ``aggregate_daily_series``,
  and the ``fetch_admin_summary`` glue) so the AI vs search-engine split is
  reproducible without hitting Cloudflare.
- The admin route (``/admin/analytics/cf-ai-crawl-control``) so the
  empty-state and happy-path JSON shapes the frontend depends on are
  pinned down.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import cf_bot_report  # noqa: E402
from cf_bot_report import (  # noqa: E402
    aggregate_daily_series,
    fetch_admin_summary,
    is_ai_bot,
)


# ── Pure helpers ────────────────────────────────────────────────────────────

def test_is_ai_bot_known_ai_crawlers():
    assert is_ai_bot("GPTBot")
    assert is_ai_bot("ClaudeBot")
    assert is_ai_bot("PerplexityBot")
    assert is_ai_bot("Meta-ExternalAgent")
    assert is_ai_bot("Google-Extended")
    assert is_ai_bot("Applebot-Extended")
    assert is_ai_bot("OAI-SearchBot")
    assert is_ai_bot("ChatGPT-User")


def test_is_ai_bot_search_engine_crawlers():
    assert not is_ai_bot("Googlebot")
    assert not is_ai_bot("Bingbot")
    assert not is_ai_bot("Applebot")  # NOT Applebot-Extended
    assert not is_ai_bot("DuckDuckBot")
    assert not is_ai_bot("YandexBot")


def test_is_ai_bot_unknown_returns_false():
    assert not is_ai_bot("")
    assert not is_ai_bot("RandomBot")


def test_aggregate_daily_series_top_n_and_other_collapse():
    # 6 distinct bots over 2 dates; top_n=3 should keep top 3 and roll the
    # remaining 3 into "Other".
    buckets = [
        {"count": 100, "dimensions": {"date": "2026-04-19", "userAgent": "Googlebot/2.1"}},
        {"count": 50, "dimensions": {"date": "2026-04-19", "userAgent": "GPTBot/1.0"}},
        {"count": 30, "dimensions": {"date": "2026-04-19", "userAgent": "Bingbot/2.0"}},
        {"count": 10, "dimensions": {"date": "2026-04-19", "userAgent": "ClaudeBot"}},
        {"count": 5, "dimensions": {"date": "2026-04-19", "userAgent": "PerplexityBot"}},
        {"count": 2, "dimensions": {"date": "2026-04-19", "userAgent": "Applebot/0.1"}},
        {"count": 200, "dimensions": {"date": "2026-04-20", "userAgent": "Googlebot/2.1"}},
        {"count": 80, "dimensions": {"date": "2026-04-20", "userAgent": "GPTBot/1.0"}},
        {"count": 1, "dimensions": {"date": "2026-04-20", "userAgent": "ClaudeBot"}},
    ]
    out = aggregate_daily_series(buckets, top_n=3)
    assert out["top_bots"] == ["Googlebot", "GPTBot", "Bingbot"]
    rows = out["rows"]
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-04-19"
    assert rows[0]["Googlebot"] == 100
    assert rows[0]["GPTBot"] == 50
    assert rows[0]["Bingbot"] == 30
    # ClaudeBot (10) + PerplexityBot (5) + Applebot (2) collapse into Other
    assert rows[0]["Other"] == 17
    assert rows[1]["date"] == "2026-04-20"
    assert rows[1]["Googlebot"] == 200
    assert rows[1]["GPTBot"] == 80
    # ClaudeBot rolls into Other on day 2
    assert rows[1]["Other"] == 1


def test_aggregate_daily_series_skips_unclassified_and_undated():
    buckets = [
        {"count": 100, "dimensions": {"date": "2026-04-19", "userAgent": "TotallyRandom/1.0"}},
        {"count": 50, "dimensions": {"date": "", "userAgent": "Googlebot/2.1"}},
        {"count": 25, "dimensions": {"date": "2026-04-19", "userAgent": "Googlebot/2.1"}},
    ]
    out = aggregate_daily_series(buckets, top_n=5)
    assert out["top_bots"] == ["Googlebot"]
    assert out["rows"] == [{"date": "2026-04-19", "Googlebot": 25}]


def test_aggregate_daily_series_empty_input():
    out = aggregate_daily_series([], top_n=5)
    assert out == {"top_bots": [], "rows": []}


# ── fetch_admin_summary glue ────────────────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_fetch_admin_summary_returns_none_when_unconfigured():
    with patch.object(cf_bot_report, "is_configured", return_value=False):
        out = _run(fetch_admin_summary(days=7))
    assert out is None


def test_fetch_admin_summary_happy_path_splits_ai_vs_search():
    cfg = {"zone_id": "zone-test", "api_token": "tok"}
    per_ua_buckets = [
        {"count": 100, "sum": {"edgeResponseBytes": 5000},
         "dimensions": {"userAgent": "Googlebot/2.1", "cacheStatus": "hit", "edgeResponseStatus": 200}},
        {"count": 30, "sum": {"edgeResponseBytes": 1500},
         "dimensions": {"userAgent": "GPTBot/1.0", "cacheStatus": "miss", "edgeResponseStatus": 200}},
        {"count": 5, "sum": {"edgeResponseBytes": 200},
         "dimensions": {"userAgent": "ClaudeBot", "cacheStatus": "miss", "edgeResponseStatus": 404}},
    ]
    daily_buckets = [
        {"count": 100, "dimensions": {"date": "2026-04-25", "userAgent": "Googlebot/2.1"}},
        {"count": 30, "dimensions": {"date": "2026-04-25", "userAgent": "GPTBot/1.0"}},
        {"count": 5, "dimensions": {"date": "2026-04-25", "userAgent": "ClaudeBot"}},
    ]
    with patch.object(cf_bot_report, "is_configured", return_value=True), \
         patch.object(cf_bot_report, "_cfg", return_value=cfg), \
         patch.object(cf_bot_report, "_fetch_per_ua_buckets", new=AsyncMock(return_value=per_ua_buckets)), \
         patch.object(cf_bot_report, "_fetch_per_ua_daily_series", new=AsyncMock(return_value=daily_buckets)):
        out = _run(fetch_admin_summary(days=7))
    assert out is not None
    assert out["source"] == "cloudflare"
    assert out["period_days"] == 7
    assert out["zone_id"] == "zone-test"
    assert out["totals"]["requests"] == 135
    assert out["totals"]["bots"] == 3
    # AI split: GPTBot + ClaudeBot
    assert out["ai_totals"]["requests"] == 35
    assert out["ai_totals"]["bots"] == 2
    # Search split: Googlebot only
    assert out["search_totals"]["requests"] == 100
    assert out["search_totals"]["bots"] == 1
    # per_bot sorted desc by requests
    assert [b["name"] for b in out["per_bot"]] == ["Googlebot", "GPTBot", "ClaudeBot"]
    assert out["per_bot"][0]["category"] == "search"
    assert out["per_bot"][1]["category"] == "ai"
    # ClaudeBot had a 404 → error_rate 1.0
    claude = next(b for b in out["per_bot"] if b["name"] == "ClaudeBot")
    assert claude["error_rate"] == 1.0
    # Daily series populated
    assert "Googlebot" in out["daily_series"]["top_bots"]
    assert out["daily_series"]["rows"][0]["date"] == "2026-04-25"


def test_fetch_admin_summary_returns_none_when_per_ua_fetch_fails():
    cfg = {"zone_id": "zone-test", "api_token": "tok"}
    with patch.object(cf_bot_report, "is_configured", return_value=True), \
         patch.object(cf_bot_report, "_cfg", return_value=cfg), \
         patch.object(cf_bot_report, "_fetch_per_ua_buckets", new=AsyncMock(return_value=None)):
        out = _run(fetch_admin_summary(days=7))
    assert out is None


def test_fetch_admin_summary_tolerates_daily_series_failure():
    """Per-bot summary should still render when only the daily-series
    secondary query fails (e.g. transient timeout)."""
    cfg = {"zone_id": "zone-test", "api_token": "tok"}
    per_ua_buckets = [
        {"count": 10, "sum": {"edgeResponseBytes": 500},
         "dimensions": {"userAgent": "Googlebot/2.1", "cacheStatus": "hit", "edgeResponseStatus": 200}},
    ]
    with patch.object(cf_bot_report, "is_configured", return_value=True), \
         patch.object(cf_bot_report, "_cfg", return_value=cfg), \
         patch.object(cf_bot_report, "_fetch_per_ua_buckets", new=AsyncMock(return_value=per_ua_buckets)), \
         patch.object(cf_bot_report, "_fetch_per_ua_daily_series", new=AsyncMock(return_value=None)):
        out = _run(fetch_admin_summary(days=7))
    assert out is not None
    assert out["totals"]["requests"] == 10
    assert out["daily_series"] == {"top_bots": [], "rows": []}


# ── Admin route (FastAPI integration) ───────────────────────────────────────

@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True}


@pytest.fixture
def app_client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.bot_discovery import router

    app = FastAPI()
    app.include_router(router)
    from auth_deps import get_admin_user
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


def test_admin_route_unavailable_when_cf_returns_none(app_client):
    with patch("cf_bot_report.fetch_admin_summary",
               new=AsyncMock(return_value=None)):
        r = app_client.get("/admin/analytics/cf-ai-crawl-control?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "Cloudflare analytics" in body["reason"]
    assert body["period_days"] == 7
    assert body["totals"] == {"requests": 0, "bytes": 0, "bots": 0}
    assert body["per_bot"] == []
    assert body["daily_series"] == {"top_bots": [], "rows": []}


def test_admin_route_happy_path_returns_summary(app_client):
    summary = {
        "totals": {"requests": 200, "bytes": 1000, "bots": 2},
        "ai_totals": {"requests": 50, "bots": 1},
        "search_totals": {"requests": 150, "bots": 1},
        "per_bot": [
            {"name": "Googlebot", "requests": 150, "bytes": 800, "category": "search",
             "hit_pct": 80.0, "error_rate": 0.01},
            {"name": "GPTBot", "requests": 50, "bytes": 200, "category": "ai",
             "hit_pct": 60.0, "error_rate": 0.0},
        ],
        "daily_series": {"top_bots": ["Googlebot", "GPTBot"],
                         "rows": [{"date": "2026-04-25", "Googlebot": 150, "GPTBot": 50}]},
        "since": "2026-04-18T00:00:00Z",
        "until": "2026-04-25T00:00:00Z",
        "zone_id": "zone-test",
        "period_days": 7,
        "source": "cloudflare",
    }
    with patch("cf_bot_report.fetch_admin_summary",
               new=AsyncMock(return_value=summary)):
        r = app_client.get("/admin/analytics/cf-ai-crawl-control?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["totals"]["requests"] == 200
    assert body["per_bot"][0]["name"] == "Googlebot"
    assert body["daily_series"]["top_bots"] == ["Googlebot", "GPTBot"]


def test_admin_route_swallows_unexpected_exception(app_client):
    """A raised exception inside fetch_admin_summary should still surface
    as a graceful empty-state, not a 500 — the card is non-critical."""
    with patch("cf_bot_report.fetch_admin_summary",
               new=AsyncMock(side_effect=RuntimeError("boom"))):
        r = app_client.get("/admin/analytics/cf-ai-crawl-control?days=7")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_admin_route_rejects_out_of_range_days(app_client):
    with patch("cf_bot_report.fetch_admin_summary",
               new=AsyncMock(return_value=None)):
        r_zero = app_client.get("/admin/analytics/cf-ai-crawl-control?days=0")
        r_huge = app_client.get("/admin/analytics/cf-ai-crawl-control?days=400")
    assert r_zero.status_code == 422
    assert r_huge.status_code == 422
