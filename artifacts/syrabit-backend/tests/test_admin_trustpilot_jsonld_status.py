"""Task #750 — admin route tests for the Trustpilot JSON-LD verifier
report ingest + read endpoints.

Coverage:
* POST is fail-closed when ``TRUSTPILOT_REFRESH_SECRET`` isn't set;
* POST rejects missing / wrong secret with 401;
* POST persists a normalised report to the api_config doc;
* POST tolerates a verifier payload missing aggregate counters
  (derives them from ``results``);
* GET requires admin auth;
* GET returns ``configured: false`` when nothing has been ingested yet;
* GET returns the most recent report when one exists.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "sub": "admin-1"}


def _client(authed: bool, mock_admin: dict | None = None):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from routes.admin_trustpilot_jsonld_status import router

    app = FastAPI()
    app.include_router(router)
    from auth_deps import get_admin_user
    if authed:
        app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    else:
        def _deny():
            raise HTTPException(status_code=401, detail="Not authenticated")
        app.dependency_overrides = {get_admin_user: _deny}
    return TestClient(app)


@pytest.fixture
def authed_client(mock_admin):
    return _client(True, mock_admin)


@pytest.fixture
def deny_client():
    return _client(False)


# ─── Sample payloads ───────────────────────────────────────────────────────

_PASSING_RESULTS = [
    {"url": "/", "pass": True, "status": 200, "ratingValue": 4.7, "reviewCount": 312},
    {"url": "/faq", "pass": True, "status": 200, "ratingValue": 4.7, "reviewCount": 312},
]

_FAILING_RESULTS = [
    {"url": "/", "pass": True, "status": 200, "ratingValue": 4.7, "reviewCount": 312},
    {"url": "/about", "pass": False, "status": 200,
     "reason": "AggregateRating present but invalid: ratingValue invalid (null)"},
]


# ─── POST /admin/trustpilot-jsonld/report ──────────────────────────────────

def test_post_report_fails_closed_when_secret_not_configured(authed_client):
    """No secret env var → 503 (NOT 401), so a forgotten-secret deploy
    fails loudly rather than silently accepting anonymous writes."""
    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": ""}, clear=False):
        res = authed_client.post(
            "/admin/trustpilot-jsonld/report",
            json={"results": _PASSING_RESULTS, "ok": True,
                  "passed": 2, "failed": 0, "totalUrls": 2},
            headers={"X-Trustpilot-Refresh-Secret": "anything"},
        )
    assert res.status_code == 503
    assert res.json()["detail"] == "trustpilot_refresh_secret_not_configured"


def test_post_report_rejects_wrong_secret(authed_client):
    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                    clear=False):
        res = authed_client.post(
            "/admin/trustpilot-jsonld/report",
            json={"results": _PASSING_RESULTS, "ok": True,
                  "passed": 2, "failed": 0, "totalUrls": 2},
            headers={"X-Trustpilot-Refresh-Secret": "wrong"},
        )
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid_refresh_secret"


def test_post_report_rejects_missing_secret_header(authed_client):
    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                    clear=False):
        res = authed_client.post(
            "/admin/trustpilot-jsonld/report",
            json={"results": _PASSING_RESULTS, "ok": True,
                  "passed": 2, "failed": 0, "totalUrls": 2},
        )
    assert res.status_code == 401


def test_post_report_persists_normalised_doc(authed_client):
    """Happy path: secret matches → upsert on api_config with the canonical
    report shape the GET endpoint serves to the dashboard."""
    from routes import admin_trustpilot_jsonld_status as mod

    fake_replace = AsyncMock()
    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                    clear=False), \
         patch.object(mod.db, "api_config", create=True) as mock_coll:
        mock_coll.replace_one = fake_replace
        res = authed_client.post(
            "/admin/trustpilot-jsonld/report",
            json={
                "schemaVersion": 1,
                "generatedAt": "2026-04-23T06:00:00Z",
                "target": "remote",
                "origin": "https://syrabit.ai",
                "totalUrls": 2,
                "passed": 1,
                "failed": 1,
                "ok": False,
                "results": _FAILING_RESULTS,
                "runUrl": "https://github.com/x/y/actions/runs/1",
            },
            headers={"X-Trustpilot-Refresh-Secret": "expected-secret"},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["passed"] == 1
    assert body["failed"] == 1

    fake_replace.assert_awaited_once()
    args, kwargs = fake_replace.call_args
    selector, doc = args[0], args[1]
    assert selector == {"_id": mod._DOC_ID}
    assert kwargs.get("upsert") is True
    assert doc["_id"] == mod._DOC_ID
    assert doc["ok"] is False
    assert doc["passed"] == 1
    assert doc["failed"] == 1
    assert doc["totalUrls"] == 2
    assert doc["origin"] == "https://syrabit.ai"
    assert doc["target"] == "remote"
    assert doc["runUrl"] == "https://github.com/x/y/actions/runs/1"
    assert doc["generatedAt"] == "2026-04-23T06:00:00Z"
    assert doc["ingestedAt"]  # always set
    # Per-URL rows are normalised: pass=bool, reason truncated, etc.
    urls = {r["url"]: r for r in doc["results"]}
    assert urls["/"]["pass"] is True
    assert urls["/"]["ratingValue"] == 4.7
    assert urls["/"]["reviewCount"] == 312
    assert urls["/about"]["pass"] is False
    assert "ratingValue invalid" in urls["/about"]["reason"]


def test_post_report_derives_counters_when_payload_omits_them(authed_client):
    """If a future verifier version drops ``passed``/``failed``/``ok``,
    derive them from the per-URL list so we never store a contradictory
    summary that lights the tile green when URLs failed."""
    from routes import admin_trustpilot_jsonld_status as mod

    fake_replace = AsyncMock()
    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                    clear=False), \
         patch.object(mod.db, "api_config", create=True) as mock_coll:
        mock_coll.replace_one = fake_replace
        res = authed_client.post(
            "/admin/trustpilot-jsonld/report",
            json={"results": _FAILING_RESULTS, "target": "remote"},
            headers={"X-Trustpilot-Refresh-Secret": "expected-secret"},
        )

    assert res.status_code == 200
    doc = fake_replace.call_args.args[1]
    assert doc["totalUrls"] == 2
    assert doc["failed"] == 1
    assert doc["passed"] == 1
    assert doc["ok"] is False


# ─── GET /admin/trustpilot-jsonld/report ───────────────────────────────────

def test_get_report_requires_admin_auth(deny_client):
    res = deny_client.get("/admin/trustpilot-jsonld/report")
    assert res.status_code in (401, 403)


def test_get_report_returns_unconfigured_when_no_doc(authed_client):
    from routes import admin_trustpilot_jsonld_status as mod

    fake_find = AsyncMock(return_value=None)
    with patch.object(mod.db, "api_config", create=True) as mock_coll:
        mock_coll.find_one = fake_find
        res = authed_client.get("/admin/trustpilot-jsonld/report")
    assert res.status_code == 200
    body = res.json()
    assert body == {"configured": False, "report": None}


def test_get_report_returns_latest_doc(authed_client):
    from routes import admin_trustpilot_jsonld_status as mod

    stored = {
        "_id": mod._DOC_ID,
        "schemaVersion": 1,
        "generatedAt": "2026-04-23T06:00:00Z",
        "ingestedAt": "2026-04-23T06:00:05Z",
        "target": "remote",
        "origin": "https://syrabit.ai",
        "totalUrls": 2,
        "passed": 1,
        "failed": 1,
        "ok": False,
        "results": _FAILING_RESULTS,
        "runUrl": None,
    }
    fake_find = AsyncMock(return_value=dict(stored))
    with patch.object(mod.db, "api_config", create=True) as mock_coll:
        mock_coll.find_one = fake_find
        res = authed_client.get("/admin/trustpilot-jsonld/report")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    rep = body["report"]
    # _id stripped before serving.
    assert "_id" not in rep
    assert rep["failed"] == 1
    assert rep["passed"] == 1
    assert rep["ok"] is False
    assert len(rep["results"]) == 2
