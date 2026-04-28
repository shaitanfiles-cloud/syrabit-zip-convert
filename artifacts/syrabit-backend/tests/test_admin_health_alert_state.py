"""Task #902 — admin alert-state endpoint contract tests.

Locks down the JSON shape returned by the three alert-state lock-doc
endpoints surfaced to the AdminHealth dashboard:

* ``/admin/health/edge-proxy-deploy/cron/alert-state``
  (Task #893 alerter, ``last_state`` ∈ {``broken``, ``healthy``})
* ``/admin/health/cf-waf-drift/cron/alert-state``
  (Task #831 alerter, ``last_state`` ∈ {``silent``, ``healthy``})
* ``/admin/health/trustpilot/refresh-cron/alert-state``
  (Task #751 alerter, ``last_state`` ∈ {``silent``, ``healthy``})

The shared shaping helper (``_build_alert_state_response``) handles
both label conventions via ``broken_state_label``; these tests pin
that contract per endpoint so a future refactor can't silently break
the dashboard's "in debounce" caption rendering.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "sub": "admin-1"}


def _build_app(routers, mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user

    app = FastAPI()
    for r in routers:
        app.include_router(r)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


@pytest.fixture
def edge_proxy_client(mock_admin):
    from routes.admin_health import router
    return _build_app([router], mock_admin)


@pytest.fixture
def cf_waf_drift_client(mock_admin):
    from routes.admin_cf_waf_drift_cron_alerts import router
    return _build_app([router], mock_admin)


@pytest.fixture
def trustpilot_client(mock_admin):
    from routes.admin_trustpilot_cron_alerts import router
    return _build_app([router], mock_admin)


class _FakeJobLocks:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, query, projection=None, sort=None):
        if not self._doc:
            return None
        if "_id" in query and self._doc.get("_id") != query["_id"]:
            return None
        return dict(self._doc)


class _FakeDb:
    def __init__(self, doc):
        self.job_locks = _FakeJobLocks(doc)


def _patch_mongo(doc, available=True):
    """Patch ``deps.db`` and ``deps.is_mongo_available`` for the
    duration of the test. Returns a context manager."""
    import deps
    if available:
        availability = AsyncMock(return_value=True)
    else:
        availability = AsyncMock(return_value=False)
    return patch.multiple(
        deps,
        db=_FakeDb(doc),
        is_mongo_available=availability,
    )


def _iso_ago(seconds: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(seconds=seconds)
    ).isoformat()


# ─── /admin/health/edge-proxy-deploy/cron/alert-state ──────────────────────

def test_edge_proxy_alert_state_returns_present_false_when_no_doc(edge_proxy_client):
    """No lock doc yet (alerter has never fired) → ``present: False``
    plus the static realertIntervalSeconds. The dashboard renders no
    alert caption in this state."""
    with _patch_mongo(None):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-state"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["present"] is False
    assert body["lastState"] is None
    assert body["lastAlertAt"] is None
    assert body["lastAlertAgeSeconds"] is None
    assert body["inDebounce"] is False
    assert body["debounceRemainingSeconds"] is None
    # 24h debounce — the alerter's _CRON_REALERT_INTERVAL_S default.
    assert body["realertIntervalSeconds"] == 24 * 3600


def test_edge_proxy_alert_state_returns_present_false_when_mongo_down(edge_proxy_client):
    """Mongo unavailable → defensive ``present: False`` rather than a
    500. The pill above already renders without Mongo, so the alert
    caption must too."""
    with _patch_mongo({"_id": "anything"}, available=False):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-state"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["present"] is False


def test_edge_proxy_alert_state_in_debounce(edge_proxy_client):
    """Recently paged on a `broken` state → ``inDebounce: True`` and
    a positive ``debounceRemainingSeconds`` so the dashboard renders
    the "in debounce ~Yh remaining" caption suffix."""
    doc = {
        "_id": "edge_proxy_deploy_cron_alert_state",
        "last_state": "broken",
        "last_kind": "failed",
        "last_alert_at": _iso_ago(2 * 3600),
        "last_html_url": "https://github.com/x/y/actions/runs/12345",
        "last_run_id": 12345,
        "last_run_url": "https://github.com/x/y/actions/runs/12345",
        "last_workflow_url": (
            "https://github.com/x/y/actions/workflows/edge-proxy-deploy.yml"
        ),
        "last_conclusion": "failure",
        "last_age_seconds": 600,
        "last_pill_status": "silent",
    }
    with _patch_mongo(doc):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-state"
        )
    body = res.json()
    assert body["present"] is True
    assert body["lastState"] == "broken"
    assert body["lastKind"] == "failed"
    assert body["lastConclusion"] == "failure"
    assert body["lastHtmlUrl"] == "https://github.com/x/y/actions/runs/12345"
    assert body["lastRunId"] == 12345
    # ~2h paged ago, 24h interval → in debounce, ~22h remaining.
    assert body["lastAlertAgeSeconds"] is not None
    assert body["lastAlertAgeSeconds"] >= 2 * 3600 - 5
    assert body["inDebounce"] is True
    assert body["debounceRemainingSeconds"] is not None
    assert 21 * 3600 < body["debounceRemainingSeconds"] <= 22 * 3600


def test_edge_proxy_alert_state_past_debounce(edge_proxy_client):
    """Last page was >24h ago on a still-broken state → the alerter
    is past the debounce window and the next poll can re-page, so
    ``inDebounce: False`` even though ``last_state == broken``. The
    dashboard renders a plain "last paged Xh ago" caption (no
    debounce suffix) in this state."""
    doc = {
        "_id": "edge_proxy_deploy_cron_alert_state",
        "last_state": "broken",
        "last_kind": "failed",
        "last_alert_at": _iso_ago(30 * 3600),
        "last_pill_status": "silent",
    }
    with _patch_mongo(doc):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-state"
        )
    body = res.json()
    assert body["present"] is True
    assert body["lastState"] == "broken"
    assert body["inDebounce"] is False
    assert body["debounceRemainingSeconds"] is None
    # Age is still surfaced for the "last paged 30h ago" caption.
    assert body["lastAlertAgeSeconds"] >= 30 * 3600 - 5


def test_edge_proxy_alert_state_after_recovery_is_not_in_debounce(edge_proxy_client):
    """A recovery alert (``last_state == healthy``) is never in
    debounce — the debounce window only suppresses re-pages on the
    BROKEN side."""
    doc = {
        "_id": "edge_proxy_deploy_cron_alert_state",
        "last_state": "healthy",
        "last_kind": None,
        "last_alert_at": _iso_ago(60),
        "last_pill_status": "healthy",
    }
    with _patch_mongo(doc):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-state"
        )
    body = res.json()
    assert body["present"] is True
    assert body["lastState"] == "healthy"
    assert body["inDebounce"] is False


# ─── /admin/health/cf-waf-drift/cron/alert-state ───────────────────────────
#
# The cf-waf-drift alerter writes ``last_state="silent"`` rather than
# ``"broken"``; the helper's ``broken_state_label="silent"`` argument
# handles that. These two tests pin both halves of that contract.

def test_cf_waf_drift_alert_state_silent_is_in_debounce(cf_waf_drift_client):
    """``last_state="silent"`` (cf-waf-drift's broken-side label)
    inside the 24h debounce window must still set ``inDebounce: True``."""
    doc = {
        "_id": "cf_waf_drift_cron_alert_state",
        "last_state": "silent",
        "last_alert_at": _iso_ago(3 * 3600),
        "last_heartbeat_ts": 1700000000.0,
        "last_status": "drift",
        "last_run_url": "https://github.com/x/y/actions/runs/9",
    }
    with _patch_mongo(doc):
        res = cf_waf_drift_client.get(
            "/admin/health/cf-waf-drift/cron/alert-state"
        )
    body = res.json()
    assert body["present"] is True
    assert body["lastState"] == "silent"
    assert body["inDebounce"] is True
    assert body["realertIntervalSeconds"] == 24 * 3600


def test_cf_waf_drift_alert_state_returns_present_false_when_no_doc(cf_waf_drift_client):
    with _patch_mongo(None):
        res = cf_waf_drift_client.get(
            "/admin/health/cf-waf-drift/cron/alert-state"
        )
    body = res.json()
    assert body["present"] is False
    assert body["realertIntervalSeconds"] == 24 * 3600


# ─── /admin/health/trustpilot/refresh-cron/alert-state ─────────────────────

def test_trustpilot_refresh_alert_state_silent_is_in_debounce(trustpilot_client):
    doc = {
        "_id": "trustpilot_refresh_cron_alert_state",
        "last_state": "silent",
        "last_alert_at": _iso_ago(1 * 3600),
        "last_heartbeat_ts": 1700000000.0,
        "last_status": "failure",
    }
    with _patch_mongo(doc):
        res = trustpilot_client.get(
            "/admin/health/trustpilot/refresh-cron/alert-state"
        )
    body = res.json()
    assert body["present"] is True
    assert body["lastState"] == "silent"
    assert body["inDebounce"] is True
    assert body["realertIntervalSeconds"] == 24 * 3600


def test_trustpilot_refresh_alert_state_returns_present_false_when_no_doc(trustpilot_client):
    with _patch_mongo(None):
        res = trustpilot_client.get(
            "/admin/health/trustpilot/refresh-cron/alert-state"
        )
    assert res.status_code == 200
    assert res.json()["present"] is False


# ─── Auth gate ─────────────────────────────────────────────────────────────

def test_alert_state_endpoints_require_admin_auth(mock_admin):
    """All three endpoints route through ``get_admin_user`` so an
    unauthenticated request must 401/403. Verified via a deny-only
    dependency override matching the convention from
    ``test_admin_health_edge_proxy_deploy_cron_route.py``."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user
    from routes.admin_health import router as edge_router
    from routes.admin_cf_waf_drift_cron_alerts import router as cf_router
    from routes.admin_trustpilot_cron_alerts import router as tp_router

    app = FastAPI()
    app.include_router(edge_router)
    app.include_router(cf_router)
    app.include_router(tp_router)

    def _deny():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides = {get_admin_user: _deny}
    client = TestClient(app)
    for path in [
        "/admin/health/edge-proxy-deploy/cron/alert-state",
        "/admin/health/cf-waf-drift/cron/alert-state",
        "/admin/health/trustpilot/refresh-cron/alert-state",
    ]:
        res = client.get(path)
        assert res.status_code in (401, 403), path
