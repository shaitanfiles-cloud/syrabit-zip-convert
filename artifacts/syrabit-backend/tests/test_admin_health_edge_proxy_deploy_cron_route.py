"""Task #882 — admin route tests for /admin/health/edge-proxy-deploy/cron.

Locks down the GitHub-Actions-driven cron pill that surfaces the
unattended `edge-proxy-deploy` workflow's latest run on AdminHealth.
The wrapper component reads the `status` field to drive the colour
mapping, so the precise mapping (failure → silent / red, >7d → degraded
/ amber, otherwise → healthy / green, missing config → not_configured)
must be an enforced contract, not a code-review-time check.
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "sub": "admin-1"}


@pytest.fixture
def app_client_authed(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.admin_health import router
    from auth_deps import get_admin_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


@pytest.fixture
def app_client_no_auth():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from routes.admin_health import router
    from auth_deps import get_admin_user

    app = FastAPI()
    app.include_router(router)

    def _deny():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides = {get_admin_user: _deny}
    return TestClient(app)


def _mock_response(status_code: int, json_payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_payload)
    return resp


class _FakeAsyncClient:
    """Minimal stand-in for httpx.AsyncClient (matches the shape used
    by routes/admin_ci_status.py's tests so the two suites stay in
    lockstep on how GitHub is mocked)."""

    def __init__(self, response_or_exc):
        self._response_or_exc = response_or_exc
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        self.calls.append(url)
        if isinstance(self._response_or_exc, Exception):
            raise self._response_or_exc
        return self._response_or_exc


def _iso_ago(seconds: int) -> str:
    """Build a Z-suffixed ISO timestamp `seconds` ago (matches GitHub)."""
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(*, conclusion, age_seconds, status="completed"):
    return {
        "id": 12345,
        "name": "Edge proxy deploy",
        "status": status,
        "conclusion": conclusion,
        "html_url": "https://github.com/x/y/actions/runs/12345",
        "head_branch": "master",
        "head_sha": "deadbee" + "f" * 33,
        "event": "push",
        "run_number": 7,
        "updated_at": _iso_ago(age_seconds),
        "actor": {"login": "ci-bot"},
    }


def test_route_requires_admin_auth(app_client_no_auth):
    res = app_client_no_auth.get("/admin/health/edge-proxy-deploy/cron")
    assert res.status_code in (401, 403)


def test_returns_not_configured_when_repo_missing(app_client_authed):
    """Missing GITHUB_REPO must surface ``status: not_configured`` /
    ``configured: false`` so the dashboard can render the gray "set
    me up" pill instead of going blank."""
    with patch.dict(os.environ, {"GITHUB_REPO": ""}, clear=False):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["status"] == "not_configured"
    assert body["conclusion"] is None
    assert body["html_url"] is None
    assert body["lastRunUrl"] is None
    # Even unconfigured we still hand the UI a deterministic
    # workflowUrl so the always-on "Runs" link in the pill points
    # somewhere sensible.
    assert "edge-proxy-deploy.yml" in body["workflowUrl"]


def test_returns_healthy_on_recent_success(app_client_authed):
    """A `success` conclusion within the 7-day window maps to
    ``status: healthy`` (green)."""
    fake = _FakeAsyncClient(
        _mock_response(200, {"workflow_runs": [_run(conclusion="success", age_seconds=3600)]})
    )
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["status"] == "healthy"
    assert body["conclusion"] == "success"
    assert body["html_url"] == "https://github.com/x/y/actions/runs/12345"
    # lastRunUrl mirrors html_url so the wrapper's "Last run"
    # deep-link convention works without GitHub-specific knowledge.
    assert body["lastRunUrl"] == body["html_url"]
    assert body["error"] is None
    # Sanity-check the URL we actually called.
    assert fake.calls == [
        "https://api.github.com/repos/x/y/actions/workflows/"
        "edge-proxy-deploy.yml/runs?per_page=1"
    ]


def test_returns_silent_on_failure(app_client_authed):
    """A `failure` conclusion must always map to red (``status:
    silent``), regardless of how recent it is — an unfixed CI break
    is still a CI break."""
    fake = _FakeAsyncClient(
        _mock_response(200, {"workflow_runs": [_run(conclusion="failure", age_seconds=600)]})
    )
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["status"] == "silent"
    assert body["conclusion"] == "failure"


def test_failure_beats_stale(app_client_authed):
    """An old failure stays red, not amber. The colour-precedence
    test: failure wins over the stale-run check so on-call sees the
    most actionable signal first."""
    fake = _FakeAsyncClient(
        _mock_response(
            200,
            {"workflow_runs": [_run(conclusion="failure", age_seconds=14 * 86400)]},
        )
    )
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["status"] == "silent"
    # ageSeconds is still surfaced so the wrapper can show the
    # "X days ago" caption — only the colour mapping changes.
    assert body["ageSeconds"] is not None and body["ageSeconds"] > 7 * 86400


def test_returns_degraded_on_stale_success(app_client_authed):
    """A successful run older than 7 days (the spec threshold) should
    surface as amber (``status: degraded``) — a hint that the
    workflow trigger may have stopped firing."""
    fake = _FakeAsyncClient(
        _mock_response(
            200,
            {"workflow_runs": [_run(conclusion="success", age_seconds=8 * 86400)]},
        )
    )
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["status"] == "degraded"
    assert body["conclusion"] == "success"


def test_in_progress_is_healthy_with_runstatus_surfaced(app_client_authed):
    """Mid-deploy: GitHub returns status="in_progress" with a null
    conclusion. The pill should still render green (no failure) and
    expose runStatus so the wrapper can label the caption."""
    fake = _FakeAsyncClient(
        _mock_response(
            200,
            {"workflow_runs": [_run(conclusion=None, age_seconds=30, status="in_progress")]},
        )
    )
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["status"] == "healthy"
    assert body["conclusion"] is None
    assert body["runStatus"] == "in_progress"


def test_returns_never_observed_when_no_runs(app_client_authed):
    """Brand-new workflow with zero runs: gray pill, never-observed
    status — the workflow exists, it just hasn't fired yet."""
    fake = _FakeAsyncClient(_mock_response(200, {"workflow_runs": []}))
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["status"] == "never_observed"
    assert body["conclusion"] is None
    assert body["lastRunUrl"] is None


def test_returns_never_observed_on_404(app_client_authed):
    """A 404 from GitHub means the workflow file isn't on this branch
    (e.g. just renamed). Treat this as never_observed (gray) rather
    than red — it's a config issue, not a CI regression."""
    fake = _FakeAsyncClient(_mock_response(404, {}))
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["status"] == "never_observed"
    assert body["error"] is None


def test_surfaces_unknown_on_github_error(app_client_authed):
    """A non-200 (and non-404) GitHub response should surface
    ``status: unknown`` plus a string ``error`` so the dashboard can
    render "status temporarily unavailable" instead of going blank
    or silently going red."""
    fake = _FakeAsyncClient(_mock_response(503, {}))
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["status"] == "unknown"
    assert body["error"] and "503" in body["error"]


def test_surfaces_unknown_on_network_failure(app_client_authed):
    """A raised exception on the GitHub call (DNS / TLS / timeout)
    must NOT 500 the route — it surfaces ``status: unknown`` plus
    an ``error`` field, mirroring the admin_ci_status defensive
    contract so the dashboard tile stays renderable."""
    import httpx  # noqa: F401 — import for readability

    fake = _FakeAsyncClient(RuntimeError("boom"))
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unknown"
    assert body["error"] and "RuntimeError" in body["error"]


def test_token_is_attached_when_set(app_client_authed):
    """A configured GITHUB_TOKEN should be forwarded as a Bearer
    Authorization header. Required for private repos; harmless on
    public ones. Verified by introspecting the headers passed to
    httpx.AsyncClient."""
    captured = {}

    class _SpyAsyncClient(_FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(_mock_response(200, {"workflow_runs": []}))
            captured["headers"] = kwargs.get("headers", {})

    with patch.dict(
        os.environ, {"GITHUB_REPO": "x/y", "GITHUB_TOKEN": "secret-pat"}, clear=False
    ), patch("routes.admin_health.httpx.AsyncClient", _SpyAsyncClient):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    assert res.status_code == 200
    assert captured["headers"].get("Authorization") == "Bearer secret-pat"


# ─── Task #964 — slackConfigured surfaces on the cron health endpoint ─────

_EDGE_PROXY_SLACK_ENV = "EDGE_PROXY_DEPLOY_SLACK_WEBHOOK"


def test_slack_configured_true_when_webhook_env_set(app_client_authed):
    """When ``EDGE_PROXY_DEPLOY_SLACK_WEBHOOK`` is set, the endpoint
    must surface ``slackConfigured: True`` and the env var name so
    the AdminHealth pill can render the "Slack ✓" badge. The webhook
    URL itself must NOT appear in the response — admin-readable JSON
    surfaces should never leak it."""
    fake = _FakeAsyncClient(_mock_response(200, {"workflow_runs": [
        _run(conclusion="success", age_seconds=3600),
    ]}))
    secret_url = "https://hooks.slack.example.com/services/T0/B0/edge-secret"
    with patch.dict(
        os.environ,
        {"GITHUB_REPO": "x/y", _EDGE_PROXY_SLACK_ENV: secret_url},
        clear=False,
    ), patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    assert res.status_code == 200
    body = res.json()
    assert body["slackConfigured"] is True
    assert body["slackWebhookEnv"] == _EDGE_PROXY_SLACK_ENV
    import json
    assert "edge-secret" not in json.dumps(body)


def test_slack_configured_false_when_webhook_env_unset(monkeypatch, app_client_authed):
    """When the Slack webhook env var is unset OR whitespace-only,
    the endpoint must surface ``slackConfigured: False`` so the
    AdminHealth pill renders the neutral "Slack ✗" badge that tells
    the admin which env var to set."""
    fake = _FakeAsyncClient(_mock_response(200, {"workflow_runs": [
        _run(conclusion="success", age_seconds=3600),
    ]}))
    monkeypatch.delenv(_EDGE_PROXY_SLACK_ENV, raising=False)
    with patch.dict(os.environ, {"GITHUB_REPO": "x/y"}, clear=False), \
            patch("routes.admin_health.httpx.AsyncClient", return_value=fake):
        res = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    body = res.json()
    assert body["slackConfigured"] is False
    assert body["slackWebhookEnv"] == _EDGE_PROXY_SLACK_ENV

    # Whitespace-only is not configured — guards against stray spaces
    # in deploy templates looking like coverage.
    fake2 = _FakeAsyncClient(_mock_response(200, {"workflow_runs": [
        _run(conclusion="success", age_seconds=3600),
    ]}))
    with patch.dict(
        os.environ,
        {"GITHUB_REPO": "x/y", _EDGE_PROXY_SLACK_ENV: "   "},
        clear=False,
    ), patch("routes.admin_health.httpx.AsyncClient", return_value=fake2):
        res2 = app_client_authed.get("/admin/health/edge-proxy-deploy/cron")
    assert res2.json()["slackConfigured"] is False
