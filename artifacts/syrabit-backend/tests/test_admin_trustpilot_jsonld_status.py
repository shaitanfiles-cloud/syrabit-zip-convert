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
# ─── Task #754 — 30-day history append + GET /history ────────────────────


def test_post_report_appends_to_history_collection(authed_client):
    """Each ingest should also insert one row into the TTL'd history
    collection so the dashboard can render a 30-day pass-rate sparkline."""
    async def _inner():
        from routes import admin_trustpilot_jsonld_status as mod

        fake_replace = AsyncMock()
        fake_find = AsyncMock(return_value=None)
        fake_dispatch = AsyncMock()
        fake_insert = AsyncMock()
        with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                        clear=False), \
             patch.object(mod, "_maybe_dispatch_jsonld_alerts", fake_dispatch), \
             patch.object(mod.db, "api_config", create=True) as mock_cfg, \
             patch.object(mod.db, mod._RUNS_COLLECTION, create=True) as mock_runs:
            mock_cfg.replace_one = fake_replace
            mock_cfg.find_one = fake_find
            mock_runs.insert_one = fake_insert
            res = authed_client.post(
                "/admin/trustpilot-jsonld/report",
                json={
                    "results": _FAILING_RESULTS,
                    "target": "remote",
                    "origin": "https://syrabit.ai",
                    "totalUrls": 2, "passed": 1, "failed": 1, "ok": False,
                    "runUrl": "https://github.com/x/y/actions/runs/3",
                },
                headers={"X-Trustpilot-Refresh-Secret": "expected-secret"},
            )

        assert res.status_code == 200
        fake_insert.assert_awaited_once()
        run_doc = fake_insert.call_args.args[0]
        # Real BSON datetime is required so Mongo's TTL monitor sweeps it.
        from datetime import datetime as _dt
        assert isinstance(run_doc["ts"], _dt)
        assert run_doc["totalUrls"] == 2
        assert run_doc["passed"] == 1
        assert run_doc["failed"] == 1
        assert run_doc["ok"] is False
        assert run_doc["target"] == "remote"
        assert run_doc["origin"] == "https://syrabit.ai"
        assert run_doc["runUrl"] == "https://github.com/x/y/actions/runs/3"
        # avgRatingValue averages only numeric ratings — the failing row
        # has no ratingValue so it's excluded.
        assert run_doc["avgRatingValue"] == pytest.approx(4.7)
    asyncio.run(_inner())


def test_history_append_failure_does_not_break_ingest(authed_client):
    """A blip on the history collection (e.g. transient mongo error) must
    never fail the verifier webhook — the latest doc is the source of
    truth for the tile, and losing one sparkline point is acceptable."""
    async def _inner():
        from routes import admin_trustpilot_jsonld_status as mod

        fake_replace = AsyncMock()
        fake_find = AsyncMock(return_value=None)
        fake_dispatch = AsyncMock()
        boom = AsyncMock(side_effect=RuntimeError("mongo down"))
        with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                        clear=False), \
             patch.object(mod, "_maybe_dispatch_jsonld_alerts", fake_dispatch), \
             patch.object(mod.db, "api_config", create=True) as mock_cfg, \
             patch.object(mod.db, mod._RUNS_COLLECTION, create=True) as mock_runs:
            mock_cfg.replace_one = fake_replace
            mock_cfg.find_one = fake_find
            mock_runs.insert_one = boom
            res = authed_client.post(
                "/admin/trustpilot-jsonld/report",
                json={"results": _PASSING_RESULTS, "target": "remote",
                      "totalUrls": 2, "passed": 2, "failed": 0, "ok": True},
                headers={"X-Trustpilot-Refresh-Secret": "expected-secret"},
            )
        assert res.status_code == 200
        fake_replace.assert_awaited_once()
    asyncio.run(_inner())


def test_get_history_requires_admin_auth(deny_client):
    res = deny_client.get("/admin/trustpilot-jsonld/history")
    assert res.status_code in (401, 403)


def test_get_history_returns_chronological_pass_rate_points(authed_client):
    """The history endpoint must return rows oldest-first with a
    pre-computed ``passRate`` so the front-end can plot directly without
    having to do float maths in JSX."""
    from datetime import datetime as _dt, timezone as _tz
    from routes import admin_trustpilot_jsonld_status as mod

    # Cursor is queried sort=ts DESC so a high-frequency-rerun day keeps
    # the most recent 200 rows; the endpoint reverses in-memory before
    # returning so the response is chronological (oldest first).
    rows = [
        {"ts": _dt(2026, 4, 2, tzinfo=_tz.utc), "totalUrls": 4,
         "passed": 3, "failed": 1, "ok": False, "avgRatingValue": 4.6},
        {"ts": _dt(2026, 4, 1, tzinfo=_tz.utc), "totalUrls": 4,
         "passed": 4, "failed": 0, "ok": True, "avgRatingValue": 4.7},
    ]

    class _Cursor:
        def __init__(self, items):
            self._items = items
        def sort(self, *a, **kw):
            return self
        def limit(self, *a, **kw):
            return self
        def __aiter__(self):
            self._iter = iter(self._items)
            return self
        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration

    with patch.object(mod.db, mod._RUNS_COLLECTION, create=True) as mock_runs:
        mock_runs.find.return_value = _Cursor(rows)
        res = authed_client.get("/admin/trustpilot-jsonld/history")

    assert res.status_code == 200
    body = res.json()
    assert body["ttlDays"] == 30
    pts = body["points"]
    assert len(pts) == 2
    assert pts[0]["passRate"] == pytest.approx(1.0)
    assert pts[1]["passRate"] == pytest.approx(0.75)
    assert pts[0]["ok"] is True
    assert pts[1]["ok"] is False
    # ts is serialised as ISO so the front-end can parse with new Date().
    assert pts[0]["ts"].startswith("2026-04-01")


# ─── Task #761 — per-URL N-day streak alert ───────────────────────────────


def test_streak_below_threshold_does_not_page():
    """Second consecutive fail (streak=2, threshold=3) must NOT page."""
    from routes import admin_trustpilot_jsonld_status as mod

    prior_doc = {
        "urlFailureStreaks": {"/about": 1},
        "alertedStreaks": [],
        "alertedFailedUrls": ["/about"],
    }
    new_results = [
        {"url": "/", "pass": True},
        {"url": "/about", "pass": False, "reason": "still missing"},
    ]
    new_streaks, new_alerted, newly = mod._compute_url_failure_streaks(
        prior_doc, new_results,
    )
    assert new_streaks == {"/about": 2}
    assert new_alerted == []
    assert newly == []


def test_streak_at_threshold_pages_exactly_once():
    """Third consecutive fail (streak=3) must produce one newly-streaking
    row so the caller fires exactly one streak alert."""
    from routes import admin_trustpilot_jsonld_status as mod

    prior_doc = {
        "urlFailureStreaks": {"/about": 2},
        "alertedStreaks": [],
        "alertedFailedUrls": ["/about"],
    }
    new_results = [
        {"url": "/", "pass": True},
        {"url": "/about", "pass": False, "reason": "still missing"},
    ]
    new_streaks, new_alerted, newly = mod._compute_url_failure_streaks(
        prior_doc, new_results,
    )
    assert new_streaks == {"/about": 3}
    assert new_alerted == ["/about"]
    assert [r["url"] for r in newly] == ["/about"]
    assert newly[0]["streak"] == 3


def test_streak_already_alerted_dedupes_further_fails():
    """Fourth and subsequent consecutive fails must NOT re-page — the
    dedup ledger carries the URL forward until it passes."""
    from routes import admin_trustpilot_jsonld_status as mod

    prior_doc = {
        "urlFailureStreaks": {"/about": 3},
        "alertedStreaks": ["/about"],
        "alertedFailedUrls": ["/about"],
    }
    new_results = [
        {"url": "/about", "pass": False, "reason": "still missing"},
    ]
    new_streaks, new_alerted, newly = mod._compute_url_failure_streaks(
        prior_doc, new_results,
    )
    assert new_streaks == {"/about": 4}
    # Still alerted (dedup ledger retained), but nothing NEW to page on.
    assert new_alerted == ["/about"]
    assert newly == []


def test_streak_resets_on_pass_and_repages_next_3_fail_streak():
    """A URL that flips back to pass must lose both its streak counter
    AND its dedup flag, so the next 3-fail streak re-pages ops."""
    from routes import admin_trustpilot_jsonld_status as mod

    # Day N: URL had a 4-fail streak, was alerted.
    prior_doc = {
        "urlFailureStreaks": {"/about": 4},
        "alertedStreaks": ["/about"],
        "alertedFailedUrls": ["/about"],
    }
    # Day N+1: passes.
    new_streaks, new_alerted, newly = mod._compute_url_failure_streaks(
        prior_doc, [{"url": "/about", "pass": True}],
    )
    assert new_streaks == {}
    assert new_alerted == []
    assert newly == []

    # Day N+2, N+3, N+4: three fails in a row → re-page.
    prior = {"urlFailureStreaks": new_streaks, "alertedStreaks": new_alerted}
    for expected_streak in (1, 2, 3):
        new_streaks, new_alerted, newly = mod._compute_url_failure_streaks(
            prior, [{"url": "/about", "pass": False}],
        )
        assert new_streaks == {"/about": expected_streak}
        prior = {"urlFailureStreaks": new_streaks,
                 "alertedStreaks": new_alerted}
    assert [r["url"] for r in newly] == ["/about"]
    assert newly[0]["streak"] == 3


def test_streak_alert_only_fires_for_urls_crossing_threshold():
    """With a mix of URLs — one first-time fail, one hitting streak=3 —
    only the streak=3 URL should appear in newly_streaking_rows."""
    from routes import admin_trustpilot_jsonld_status as mod

    prior_doc = {
        "urlFailureStreaks": {"/about": 2},
        "alertedStreaks": [],
        "alertedFailedUrls": ["/about"],
    }
    new_results = [
        {"url": "/about", "pass": False, "reason": "still missing"},
        {"url": "/faq", "pass": False, "reason": "just broke"},
        {"url": "/", "pass": True},
    ]
    new_streaks, new_alerted, newly = mod._compute_url_failure_streaks(
        prior_doc, new_results,
    )
    assert new_streaks == {"/about": 3, "/faq": 1}
    assert new_alerted == ["/about"]
    assert [r["url"] for r in newly] == ["/about"]


def test_streak_counts_duplicate_url_rows_in_single_payload():
    """If a malformed verifier payload lists the same URL twice in one
    run, each failing row increments the streak — the dict semantics
    guarantee only one canonical counter ends up on the doc, and the
    final value reflects the LAST row the verifier emitted for that
    URL. This locks in the behaviour so a future verifier refactor
    that de-dupes its own input can't silently shift the streak."""
    from routes import admin_trustpilot_jsonld_status as mod

    prior_doc = {"urlFailureStreaks": {"/about": 2}, "alertedStreaks": []}
    # Same URL listed twice: both fail.
    new_results = [
        {"url": "/about", "pass": False, "reason": "first row"},
        {"url": "/about", "pass": False, "reason": "second row"},
    ]
    new_streaks, new_alerted, newly = mod._compute_url_failure_streaks(
        prior_doc, new_results,
    )
    # Counter advances exactly once per ingest regardless of duplicate
    # rows (the helper takes the prior streak ONCE, then reuses the
    # already-written value for subsequent rows of the same URL).
    assert new_streaks == {"/about": 3}
    # Dedup ledger must also carry only one entry and `newly_streaking`
    # must emit exactly one row (no duplicate alerts for the same
    # threshold crossing).
    assert new_alerted == ["/about"]
    assert [r["url"] for r in newly] == ["/about"]
    assert len(newly) == 1


def test_streak_alert_body_surfaces_url_streak_and_run_link():
    """The streak alert message must list the failing URL, its streak
    count, and deep-link to the latest GH Actions run."""
    async def _inner():
        from routes import admin_trustpilot_jsonld_status as mod

        captured: dict = {}

        async def _fake_emit(*, title, message, kind, run_url, urls):
            captured.update(title=title, message=message, kind=kind,
                            run_url=run_url, urls=list(urls))

        streaking_rows = [
            {"url": "/about", "pass": False, "streak": 3,
             "reason": "AggregateRating missing"},
        ]
        new_doc = {"runUrl": "https://github.com/x/y/actions/runs/42"}
        with patch.object(mod, "_emit_jsonld_alert", _fake_emit):
            await mod._send_jsonld_streak_alert(streaking_rows, new_doc)

        assert captured["kind"] == "streak"
        assert captured["urls"] == ["/about"]
        assert "3+ runs in a row" in captured["title"]
        assert "/about" in captured["message"]
        assert "streak: 3" in captured["message"]
        assert "actions/runs/42" in captured["message"]
        assert captured["run_url"] == "https://github.com/x/y/actions/runs/42"
    asyncio.run(_inner())


def test_ingest_fires_streak_alert_when_url_hits_threshold(authed_client):
    """End-to-end: POST an ingest where the prior doc shows a 2-fail
    streak and the new run is a 3rd fail → the streak alert fires."""
    async def _inner():
        from routes import admin_trustpilot_jsonld_status as mod

        prior_doc = {
            "_id": mod._DOC_ID,
            "alertedFailedUrls": ["/about"],
            "urlFailureStreaks": {"/about": 2},
            "alertedStreaks": [],
            "results": [{"url": "/about", "pass": False}],
        }
        fake_replace = AsyncMock()
        fake_find = AsyncMock(return_value=prior_doc)
        fake_streak = AsyncMock()
        with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected-secret"},
                        clear=False), \
             patch.object(mod, "_maybe_dispatch_jsonld_alerts", AsyncMock()), \
             patch.object(mod, "_append_trustpilot_jsonld_run", AsyncMock()), \
             patch.object(mod, "_send_jsonld_streak_alert", fake_streak), \
             patch.object(mod.db, "api_config", create=True) as mock_coll:
            mock_coll.replace_one = fake_replace
            mock_coll.find_one = fake_find
            res = authed_client.post(
                "/admin/trustpilot-jsonld/report",
                json={
                    "results": [{"url": "/about", "pass": False,
                                 "reason": "still missing"}],
                    "target": "remote",
                },
                headers={"X-Trustpilot-Refresh-Secret": "expected-secret"},
            )
        assert res.status_code == 200
        fake_streak.assert_awaited_once()
        rows, stored = fake_streak.call_args.args
        assert [r["url"] for r in rows] == ["/about"]
        assert rows[0]["streak"] == 3
        # The persisted doc carries the new streak ledger for next run.
        persisted = fake_replace.call_args.args[1]
        assert persisted["urlFailureStreaks"] == {"/about": 3}
        assert persisted["alertedStreaks"] == ["/about"]
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
