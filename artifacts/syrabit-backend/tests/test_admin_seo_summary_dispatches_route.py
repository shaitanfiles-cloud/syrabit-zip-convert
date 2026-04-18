"""Task #474 — admin route tests for /admin/seo/daily-summary-dispatches."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "sub": "admin-1"}


@pytest.fixture
def app_client_authed(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.admin_notifications import router

    app = FastAPI()
    app.include_router(router)
    from auth_deps import get_admin_user
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


@pytest.fixture
def app_client_no_auth():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from routes.admin_notifications import router

    app = FastAPI()
    app.include_router(router)
    from auth_deps import get_admin_user

    def _deny():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides = {get_admin_user: _deny}
    return TestClient(app)


def test_dispatches_endpoint_requires_admin_auth(app_client_no_auth):
    res = app_client_no_auth.get("/admin/seo/daily-summary-dispatches")
    assert res.status_code in (401, 403)


def test_dispatches_endpoint_returns_rows_from_engine(app_client_authed):
    """Endpoint must forward whatever ``get_recent_seo_summary_dispatches``
    returns under a ``dispatches`` key, including per-admin error details so
    the UI can render the inline failure list."""
    fake_rows = [
        {
            "at": "2026-04-18T10:00:00+00:00",
            "job_id": "sched-1",
            "sent": 1,
            "failed": 1,
            "total_recipients": 2,
            "suppressed_quiet_hours": 1,
            "opted_out": 0,
            "no_email": 0,
            "total_admins": 3,
            "errors": [{"admin_id": "a2", "email": "bad@x.com",
                        "error": "RuntimeError: smtp boom"}],
            "reason": None,
        }
    ]
    fake = AsyncMock(return_value=fake_rows)
    with patch("seo_engine.get_recent_seo_summary_dispatches", fake):
        res = app_client_authed.get("/admin/seo/daily-summary-dispatches?limit=5")
    assert res.status_code == 200
    body = res.json()
    assert "dispatches" in body
    assert body["dispatches"] == fake_rows
    fake.assert_awaited_once()
    # The route must forward the limit query param so admins can widen the
    # window without the engine making the call again with a stale default.
    assert fake.await_args.kwargs.get("limit") == 5 or fake.await_args.args == (5,)


def test_dispatches_endpoint_returns_empty_list_when_no_history(app_client_authed):
    """The engine helper swallows Mongo failures and returns ``[]`` so the
    admin notifications panel can render an empty-state message instead of
    crashing the modal. The endpoint must pass that through verbatim."""
    fake_empty = AsyncMock(return_value=[])
    with patch("seo_engine.get_recent_seo_summary_dispatches", fake_empty):
        res = app_client_authed.get("/admin/seo/daily-summary-dispatches")
    assert res.status_code == 200
    assert res.json() == {"dispatches": []}
