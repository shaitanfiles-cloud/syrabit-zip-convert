"""Schema-drift guard for `cloudflare_client.get_verified_bot_traffic_cf`
(Audit #12).

The weekly bot-traffic email, the absent-bot alerting, the WoW
prior-week diff, and the Mongo persistence in `cf_bot_report.py` ALL
unpack the dict returned by `get_verified_bot_traffic_cf`. If a
refactor accidentally drops a key (or Cloudflare changes their GraphQL
schema), every downstream consumer silently degrades — alerts stop
firing, the WoW table fills with `None`, and the Monday email loses
the bot_5xx column.

These tests pin the contract by:
  * mocking `_graphql_query` with a realistic CF response shape,
  * asserting the returned dict has EXACTLY the keys promised by
    `VERIFIED_BOT_TRAFFIC_KEYS`,
  * asserting types for each key,
  * asserting that schema drift on the input side (missing `viewer`,
    missing `count`, malformed dimensions) returns `None` instead of
    raising — so a Cloudflare API-side change degrades to "skip this
    week" rather than crashing the cron.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

import cloudflare_client as cc
from cloudflare_client import (
    VERIFIED_BOT_TRAFFIC_KEYS,
    get_verified_bot_traffic_cf,
)


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _good_cf_response() -> dict:
    """A realistic Cloudflare GraphQL response shape."""
    return {
        "viewer": {
            "zones": [
                {
                    "categories": [
                        {"count": 4200, "dimensions": {
                            "verifiedBotCategory": "Search Engine Crawler"}},
                        {"count": 850, "dimensions": {
                            "verifiedBotCategory": "AI Crawler"}},
                        {"count": 30, "dimensions": {
                            "verifiedBotCategory": "Aggregator"}},
                    ],
                    "bot_5xx": [{"count": 12}],
                }
            ]
        }
    }


def _call(monkeypatch, response):
    """Run get_verified_bot_traffic_cf with the given _graphql_query stub
    and the env vars Cloudflare needs to consider itself 'configured'."""
    monkeypatch.setenv("CF_ANALYTICS_API_TOKEN", "x")
    monkeypatch.setenv("CF_ZONE_ID", "z")
    # `is_configured` reads via _cfg() which reads env at call-time, so
    # setting env vars inside the test is sufficient — no module reload.
    since = datetime(2026, 4, 13, tzinfo=timezone.utc)
    until = datetime(2026, 4, 20, tzinfo=timezone.utc)
    with patch.object(cc, "_graphql_query",
                      new=AsyncMock(return_value=response)):
        return asyncio.run(get_verified_bot_traffic_cf(since, until))


# ── Happy-path contract ──────────────────────────────────────────────────────

def test_returns_exactly_the_documented_keys(monkeypatch):
    """Schema-drift guard: the returned dict must have EXACTLY the keys
    listed in VERIFIED_BOT_TRAFFIC_KEYS — no more, no fewer.

    Adding a new key here without updating downstream consumers (weekly
    email, alerting, WoW diff, Mongo persist) is a silent regression.
    Update VERIFIED_BOT_TRAFFIC_KEYS *and* every consumer in the same
    change, then update this test.
    """
    out = _call(monkeypatch, _good_cf_response())
    assert out is not None, "function returned None for a well-formed response"
    assert set(out.keys()) == set(VERIFIED_BOT_TRAFFIC_KEYS), (
        f"Schema drift: returned keys {sorted(out.keys())} != "
        f"contract {sorted(VERIFIED_BOT_TRAFFIC_KEYS)}. Update both "
        f"VERIFIED_BOT_TRAFFIC_KEYS and every downstream consumer."
    )


def test_returned_value_types_match_contract(monkeypatch):
    out = _call(monkeypatch, _good_cf_response())
    assert isinstance(out["by_category"], dict)
    assert all(isinstance(k, str) and isinstance(v, int)
               for k, v in out["by_category"].items())
    assert isinstance(out["bot_total"], int)
    assert isinstance(out["bot_5xx"], int)
    assert isinstance(out["window_start"], str)
    assert isinstance(out["window_end"], str)
    assert out["source"] == "cloudflare"


def test_window_strings_are_iso8601_utc(monkeypatch):
    out = _call(monkeypatch, _good_cf_response())
    # CF wants `2026-04-13T00:00:00Z` exactly. Anything else risks
    # silent timezone drift in the cross-check.
    assert out["window_start"].endswith("Z")
    assert out["window_end"].endswith("Z")
    assert out["window_start"] == "2026-04-13T00:00:00Z"
    assert out["window_end"] == "2026-04-20T00:00:00Z"


def test_aggregates_categories_and_total_correctly(monkeypatch):
    out = _call(monkeypatch, _good_cf_response())
    assert out["by_category"] == {
        "Search Engine Crawler": 4200,
        "AI Crawler": 850,
        "Aggregator": 30,
    }
    assert out["bot_total"] == 4200 + 850 + 30
    assert out["bot_5xx"] == 12


def test_naive_datetimes_are_treated_as_utc(monkeypatch):
    """Regression guard: a caller passing tz-naive datetimes should not
    silently drop timezone info — the function normalizes to UTC."""
    monkeypatch.setenv("CF_ANALYTICS_API_TOKEN", "x")
    monkeypatch.setenv("CF_ZONE_ID", "z")
    since = datetime(2026, 4, 13)  # naive
    until = datetime(2026, 4, 20)  # naive
    with patch.object(cc, "_graphql_query",
                      new=AsyncMock(return_value=_good_cf_response())):
        out = asyncio.run(get_verified_bot_traffic_cf(since, until))
    assert out is not None
    assert out["window_start"] == "2026-04-13T00:00:00Z"


# ── Cloudflare-side schema-drift handling ────────────────────────────────────

def test_returns_none_when_graphql_query_fails(monkeypatch):
    """`_graphql_query` returns None on auth/network failure — propagate
    cleanly so the caller can fire its fallback admin alert."""
    out = _call(monkeypatch, None)
    assert out is None


def test_returns_none_when_zones_array_empty(monkeypatch):
    """Cloudflare returns `{viewer: {zones: []}}` when the zone tag is
    unknown — must not raise."""
    out = _call(monkeypatch, {"viewer": {"zones": []}})
    assert out is None


def test_handles_missing_viewer_key_gracefully(monkeypatch):
    """If Cloudflare ever changes the top-level shape, degrade to None
    rather than crash the weekly cron."""
    out = _call(monkeypatch, {"unexpected": "shape"})
    assert out is None


def test_handles_missing_dimensions_in_row(monkeypatch):
    """A row without `dimensions` (CF schema drift) must skip the row,
    not crash. Other rows continue to count."""
    response = {"viewer": {"zones": [{
        "categories": [
            {"count": 100},  # no dimensions key
            {"count": 50, "dimensions": {
                "verifiedBotCategory": "Search Engine Crawler"}},
        ],
        "bot_5xx": [{"count": 0}],
    }]}}
    out = _call(monkeypatch, response)
    assert out is not None
    # The dimensionless row is dropped; only the well-formed row counts.
    assert out["by_category"] == {"Search Engine Crawler": 50}
    assert out["bot_total"] == 50


def test_handles_empty_verifiedbotcategory_string(monkeypatch):
    """CF returns rows with `verifiedBotCategory: ""` for unverified
    bots when the filter widens. They must be excluded from by_category
    AND from bot_total."""
    response = {"viewer": {"zones": [{
        "categories": [
            {"count": 999, "dimensions": {"verifiedBotCategory": ""}},
            {"count": 100, "dimensions": {
                "verifiedBotCategory": "AI Crawler"}},
        ],
        "bot_5xx": [],
    }]}}
    out = _call(monkeypatch, response)
    assert out is not None
    assert out["by_category"] == {"AI Crawler": 100}
    assert out["bot_total"] == 100  # NOT 1099 — empty category excluded


def test_handles_missing_bot_5xx_block(monkeypatch):
    """`bot_5xx` defaults to 0 when CF returns an empty array (no 5xxs
    in the window) — never None and never raises."""
    response = {"viewer": {"zones": [{
        "categories": [
            {"count": 100, "dimensions": {
                "verifiedBotCategory": "Search Engine Crawler"}},
        ],
        "bot_5xx": [],
    }]}}
    out = _call(monkeypatch, response)
    assert out is not None
    assert out["bot_5xx"] == 0
    assert isinstance(out["bot_5xx"], int)


def test_returns_none_when_cloudflare_not_configured(monkeypatch):
    """No token → return None immediately, don't even attempt the query."""
    monkeypatch.delenv("CF_ANALYTICS_API_TOKEN", raising=False)
    monkeypatch.delenv("CF_ZONE_ID", raising=False)
    since = datetime(2026, 4, 13, tzinfo=timezone.utc)
    until = datetime(2026, 4, 20, tzinfo=timezone.utc)
    # `_graphql_query` should NOT be called when not configured — patch
    # it to raise so we'd see if the early-return guard regresses.
    with patch.object(cc, "_graphql_query",
                      new=AsyncMock(side_effect=AssertionError(
                          "should not call _graphql_query when unconfigured"))):
        out = asyncio.run(get_verified_bot_traffic_cf(since, until))
    assert out is None
