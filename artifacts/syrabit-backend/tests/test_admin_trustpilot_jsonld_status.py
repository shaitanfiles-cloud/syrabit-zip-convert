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

import asyncio
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
    fake_find = AsyncMock(return_value=None)
    fake_dispatch = AsyncMock()
    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                    clear=False), \
         patch.object(mod, "_maybe_dispatch_jsonld_alerts", fake_dispatch), \
         patch.object(mod.db, "api_config", create=True) as mock_coll:
        mock_coll.replace_one = fake_replace
        mock_coll.find_one = fake_find
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
    fake_find = AsyncMock(return_value=None)
    fake_dispatch = AsyncMock()
    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                    clear=False), \
         patch.object(mod, "_maybe_dispatch_jsonld_alerts", fake_dispatch), \
         patch.object(mod.db, "api_config", create=True) as mock_coll:
        mock_coll.replace_one = fake_replace
        mock_coll.find_one = fake_find
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
    # Task #753 — failing URLs are recorded in the dedup ledger so the
    # next ingest can tell which URLs have already been paged on.
    assert doc["alertedFailedUrls"] == ["/about"]


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


# ─── Task #753 — regression / recovery alert dispatch ──────────────────────

def test_dispatch_pages_on_first_pass_to_fail_flip():
    async def _inner():
        """A URL that was passing in the prior report and is now failing
        must trigger exactly one regression alert listing that URL."""
        from routes import admin_trustpilot_jsonld_status as mod

        prior_doc = {
            "alertedFailedUrls": [],
            "results": [
                {"url": "/", "pass": True}, {"url": "/about", "pass": True},
            ],
        }
        new_doc = {
            "results": [
                {"url": "/", "pass": True, "ratingValue": 4.7, "reviewCount": 312},
                {"url": "/about", "pass": False,
                 "reason": "AggregateRating present but invalid"},
            ],
            "runUrl": "https://github.com/x/y/actions/runs/1",
        }
        fake_reg = AsyncMock()
        fake_rec = AsyncMock()
        with patch.object(mod, "_send_jsonld_regression_alert", fake_reg), \
             patch.object(mod, "_send_jsonld_recovery_alert", fake_rec):
            await mod._maybe_dispatch_jsonld_alerts(prior_doc, new_doc)

        fake_reg.assert_awaited_once()
        failing_rows, passed_doc = fake_reg.call_args.args
        assert [r["url"] for r in failing_rows] == ["/about"]
        assert passed_doc is new_doc
        fake_rec.assert_not_awaited()
    asyncio.run(_inner())
def test_dispatch_dedupes_same_url_until_recovery():
    async def _inner():
        """A URL that was already alerted on in the prior failing streak
        must NOT page again while it remains failing."""
        from routes import admin_trustpilot_jsonld_status as mod

        prior_doc = {
            "alertedFailedUrls": ["/about"],
            "results": [
                {"url": "/", "pass": True}, {"url": "/about", "pass": False},
            ],
        }
        new_doc = {
            "results": [
                {"url": "/", "pass": True},
                {"url": "/about", "pass": False, "reason": "still missing"},
            ],
            "runUrl": None,
        }
        fake_reg = AsyncMock()
        fake_rec = AsyncMock()
        with patch.object(mod, "_send_jsonld_regression_alert", fake_reg), \
             patch.object(mod, "_send_jsonld_recovery_alert", fake_rec):
            await mod._maybe_dispatch_jsonld_alerts(prior_doc, new_doc)

        fake_reg.assert_not_awaited()
        fake_rec.assert_not_awaited()
    asyncio.run(_inner())
def test_dispatch_pages_on_newly_failing_url_only():
    async def _inner():
        """When a fresh URL fails alongside one we've already alerted on,
        the regression email lists only the new one (the old URL is still
        in the dedup ledger)."""
        from routes import admin_trustpilot_jsonld_status as mod

        prior_doc = {
            "alertedFailedUrls": ["/about"],
            "results": [{"url": "/about", "pass": False}],
        }
        new_doc = {
            "results": [
                {"url": "/about", "pass": False, "reason": "still missing"},
                {"url": "/faq", "pass": False, "reason": "newly broken"},
            ],
            "runUrl": None,
        }
        fake_reg = AsyncMock()
        fake_rec = AsyncMock()
        with patch.object(mod, "_send_jsonld_regression_alert", fake_reg), \
             patch.object(mod, "_send_jsonld_recovery_alert", fake_rec):
            await mod._maybe_dispatch_jsonld_alerts(prior_doc, new_doc)

        fake_reg.assert_awaited_once()
        failing_rows, _ = fake_reg.call_args.args
        assert [r["url"] for r in failing_rows] == ["/faq"]
        fake_rec.assert_not_awaited()
    asyncio.run(_inner())
def test_dispatch_emits_recovery_when_all_urls_return_to_pass():
    async def _inner():
        """When every previously-alerted URL is now passing again, fire
        exactly one recovery email and no regression email."""
        from routes import admin_trustpilot_jsonld_status as mod

        prior_doc = {
            "alertedFailedUrls": ["/about", "/faq"],
            "results": [
                {"url": "/about", "pass": False}, {"url": "/faq", "pass": False},
            ],
        }
        new_doc = {
            "results": [
                {"url": "/", "pass": True},
                {"url": "/about", "pass": True},
                {"url": "/faq", "pass": True},
            ],
            "runUrl": "https://github.com/x/y/actions/runs/2",
        }
        fake_reg = AsyncMock()
        fake_rec = AsyncMock()
        with patch.object(mod, "_send_jsonld_regression_alert", fake_reg), \
             patch.object(mod, "_send_jsonld_recovery_alert", fake_rec):
            await mod._maybe_dispatch_jsonld_alerts(prior_doc, new_doc)

        fake_reg.assert_not_awaited()
        fake_rec.assert_awaited_once()
        (passed_doc,) = fake_rec.call_args.args
        assert passed_doc is new_doc
    asyncio.run(_inner())
def test_dispatch_silent_when_steady_state_pass():
    async def _inner():
        """Healthy → healthy is a no-op (no prior failures, no new ones)."""
        from routes import admin_trustpilot_jsonld_status as mod

        prior_doc = {"alertedFailedUrls": [], "results": [{"url": "/", "pass": True}]}
        new_doc = {"results": [{"url": "/", "pass": True}], "runUrl": None}

        fake_reg = AsyncMock()
        fake_rec = AsyncMock()
        with patch.object(mod, "_send_jsonld_regression_alert", fake_reg), \
             patch.object(mod, "_send_jsonld_recovery_alert", fake_rec):
            await mod._maybe_dispatch_jsonld_alerts(prior_doc, new_doc)

        fake_reg.assert_not_awaited()
        fake_rec.assert_not_awaited()
    asyncio.run(_inner())
def test_regression_email_includes_failing_urls_rating_and_run_link():
    async def _inner():
        """The regression notification body must surface the failing URL
        list, ratingValue/reviewCount when present, and the GH Actions
        run URL so ops can jump to the full log."""
        from routes import admin_trustpilot_jsonld_status as mod

        captured: dict = {}

        async def _fake_emit(*, title, message, kind, run_url, urls):
            captured.update(
                title=title, message=message, kind=kind,
                run_url=run_url, urls=list(urls),
            )

        failing_rows = [
            {"url": "/about", "pass": False,
             "ratingValue": 4.7, "reviewCount": 312,
             "reason": "AggregateRating present but invalid"},
        ]
        new_doc = {"runUrl": "https://github.com/x/y/actions/runs/9"}

        with patch.object(mod, "_emit_jsonld_alert", _fake_emit):
            await mod._send_jsonld_regression_alert(failing_rows, new_doc)

        assert captured["kind"] == "regression"
        assert captured["urls"] == ["/about"]
        assert "/about" in captured["message"]
        assert "ratingValue=4.7" in captured["message"]
        assert "reviewCount=312" in captured["message"]
        assert "actions/runs/9" in captured["message"]
        assert captured["run_url"] == "https://github.com/x/y/actions/runs/9"
    asyncio.run(_inner())
def test_recovery_email_includes_run_link_when_present():
    async def _inner():
        from routes import admin_trustpilot_jsonld_status as mod

        captured: dict = {}

        async def _fake_emit(*, title, message, kind, run_url, urls):
            captured.update(title=title, message=message, kind=kind,
                            run_url=run_url, urls=list(urls))

        new_doc = {"runUrl": "https://github.com/x/y/actions/runs/10"}
        with patch.object(mod, "_emit_jsonld_alert", _fake_emit):
            await mod._send_jsonld_recovery_alert(new_doc)

        assert captured["kind"] == "recovery"
        assert captured["urls"] == []
        assert "recovered" in captured["title"].lower() or "recover" in captured["title"].lower()
        assert "actions/runs/10" in captured["message"]
    asyncio.run(_inner())
def test_alert_dispatch_failure_does_not_break_ingest(authed_client):
    async def _inner():
        """If the alert fan-out raises, the ingest endpoint still returns
        200 and persists the doc — the alert is best-effort."""
        from routes import admin_trustpilot_jsonld_status as mod

        fake_replace = AsyncMock()
        fake_find = AsyncMock(return_value=None)
        boom = AsyncMock(side_effect=RuntimeError("smtp down"))
        with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                        clear=False), \
             patch.object(mod, "_maybe_dispatch_jsonld_alerts", boom), \
             patch.object(mod.db, "api_config", create=True) as mock_coll:
            mock_coll.replace_one = fake_replace
            mock_coll.find_one = fake_find
            res = authed_client.post(
                "/admin/trustpilot-jsonld/report",
                json={"results": _FAILING_RESULTS, "target": "remote"},
                headers={"X-Trustpilot-Refresh-Secret": "expected-secret"},
            )
        assert res.status_code == 200
        fake_replace.assert_awaited_once()
        boom.assert_awaited_once()
    asyncio.run(_inner())
