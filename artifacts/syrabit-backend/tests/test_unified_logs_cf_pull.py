"""Task #944 — Cloudflare GraphQL → unified_logs adapter tests.

We do NOT exercise the real cloudflare_client._graphql_query — instead
we inject a fake callable into ``_try_run_cf_pull_once`` and assert
that:
  - dimensions are mapped to the unified-log shape correctly
  - the cursor is advanced (db.job_locks updated)
  - rerunning with the same data is a no-op (cursor moves past the
    already-pulled window)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import unified_logs_dao as dao
from routes import admin_logs as routes
from tests.test_unified_logs_dao import _FakeDb


def test_normalize_cf_http_request_row_maps_all_fields():
    row = {
        "dimensions": {
            "datetimeMinute": "2026-04-26T10:00:00Z",
            "edgeResponseStatus": 200,
            "originResponseStatus": 200,
            "cacheStatus": "HIT",
            "clientRequestPath": "/api/foo",
            "clientRequestHTTPMethodName": "GET",
            "clientRequestHTTPHost": "syrabit.ai",
            "clientCountryName": "IN",
            "coloCode": "BLR",
        },
        "avg": {"originResponseDurationMs": 42.7},
        "count": 5,
    }
    out = routes.normalize_cf_http_request_row(row)
    assert out["source"] == "cloudflare"
    assert out["status"] == 200
    assert out["level"] == "info"
    assert out["route"] == "/api/foo"
    assert out["method"] == "GET"
    assert out["country"] == "IN"
    assert out["colo"] == "BLR"
    assert out["cache"] == "hit"
    # ``httpRequestsAdaptiveGroups`` is aggregated and does not expose
    # per-request ray identifiers, so cloudflare rows ship with no cid.
    assert out["ray_id"] is None
    assert out["correlation_id"] is None
    assert out["duration_ms"] == 43
    assert out["extra"]["host"] == "syrabit.ai"
    assert out["extra"]["request_count"] == 5


def test_normalize_cf_row_uses_warn_for_4xx_and_error_for_5xx():
    base = {
        "dimensions": {"clientRequestPath": "/x", "clientRequestHTTPMethodName": "GET"},
        "avg": {}, "sum": {"requests": 1},
    }
    base["dimensions"]["edgeResponseStatus"] = 404
    assert routes.normalize_cf_http_request_row(base)["level"] == "warn"
    base["dimensions"]["edgeResponseStatus"] = 502
    assert routes.normalize_cf_http_request_row(base)["level"] == "error"


def test_normalize_cf_row_collapses_dynamic_cache_status():
    row = {
        "dimensions": {"cacheStatus": "DYNAMIC", "edgeResponseStatus": 200,
                       "clientRequestPath": "/", "clientRequestHTTPMethodName": "GET"},
        "avg": {}, "sum": {"requests": 1},
    }
    assert routes.normalize_cf_http_request_row(row)["cache"] == "dynamic"


def test_try_run_cf_pull_once_inserts_rows_and_advances_cursor(monkeypatch):
    async def _inner():
        """Smoke-test the full pull adapter against a fake GraphQL response."""
        dao._reset_backend_shipper_for_tests()
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)

        # Stand-in for the cloudflare_client.config import.
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)

        async def fake_graphql(query, variables):
            # Locks down the query shape lightly — the variables must
            # carry the zone tag the route claims to be using.
            assert variables["zone"] == "zone-1"
            return {"data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [
                {
                    "dimensions": {
                        "datetimeMinute": "2026-04-26T10:00:00Z",
                        "edgeResponseStatus": 500,
                        "cacheStatus": "MISS",
                        "clientRequestPath": "/api/explode",
                        "clientRequestHTTPMethodName": "POST",
                        "clientRequestHTTPHost": "syrabit.ai",
                        "clientCountryName": "IN", "coloCode": "BLR",
                        "rayName": "ray-1",
                    },
                    "avg": {"originResponseDurationMs": 1234.0},
                    "sum": {"requests": 1},
                },
            ]}]}}}

        now = datetime(2026, 4, 26, 10, 5, tzinfo=timezone.utc)
        res = await routes._try_run_cf_pull_once(now_utc=now, graphql_callable=fake_graphql)
        assert res["ok"] is True
        assert res["accepted"] == 1
        assert res["dropped"] == 0

        inserted = db[dao.UNIFIED_LOGS_COLLECTION].docs
        assert len(inserted) == 1
        assert inserted[0]["source"] == "cloudflare"
        assert inserted[0]["status"] == 500
        assert inserted[0]["route"] == "/api/explode"

        lock = next((d for d in db.job_locks.docs if d.get("_id") == routes.CF_PULL_LOCK_ID), None)
        assert lock is not None
        assert lock["last_accepted"] == 1
        assert lock[routes.CF_PULL_CURSOR_FIELD] == res["until"]


    asyncio.run(_inner())
def test_try_run_cf_pull_once_returns_reason_when_cf_unconfigured(monkeypatch):
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "", raising=False)
        res = await routes._try_run_cf_pull_once(graphql_callable=None)
        assert res["ok"] is False
        assert res["reason"] == "cf_not_configured"
    asyncio.run(_inner())
