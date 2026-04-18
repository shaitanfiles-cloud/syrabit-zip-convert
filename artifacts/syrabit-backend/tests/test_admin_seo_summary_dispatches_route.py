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


def test_dispatches_endpoint_default_limit_is_ten(app_client_authed):
    """When the admin UI omits ``?limit=`` the route must call the engine
    helper with the documented default of 10 — the AdminDashboard relies on
    this to render the ~10 most recent rows in the prefs modal."""
    fake = AsyncMock(return_value=[])
    with patch("seo_engine.get_recent_seo_summary_dispatches", fake):
        res = app_client_authed.get("/admin/seo/daily-summary-dispatches")
    assert res.status_code == 200
    fake.assert_awaited_once()
    forwarded = fake.await_args.kwargs.get("limit")
    if forwarded is None and fake.await_args.args:
        forwarded = fake.await_args.args[0]
    assert forwarded == 10


def test_dispatches_endpoint_forwards_custom_limit(app_client_authed):
    """A non-default limit query param must reach the engine helper unmodified
    so admins can widen/narrow the window from the URL without the route
    silently capping it."""
    fake = AsyncMock(return_value=[])
    with patch("seo_engine.get_recent_seo_summary_dispatches", fake):
        res = app_client_authed.get("/admin/seo/daily-summary-dispatches?limit=25")
    assert res.status_code == 200
    forwarded = fake.await_args.kwargs.get("limit")
    if forwarded is None and fake.await_args.args:
        forwarded = fake.await_args.args[0]
    assert forwarded == 25


def test_dispatches_endpoint_returns_iso_timestamps_through_helper():
    """End-to-end: feed the real ``get_recent_seo_summary_dispatches`` a fake
    Mongo cursor of rows whose ``at`` is a ``datetime`` and assert the helper
    serializes it to an ISO string before the route hands it to the UI. This
    locks in the timestamp contract the AdminDashboard renders against — a
    silent regression here would crash the prefs modal."""
    import datetime as _dt
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.admin_notifications import router
    from auth_deps import get_admin_user
    import seo_engine

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {
        get_admin_user: lambda: {"id": "a", "sub": "a", "is_admin": True}
    }
    client = TestClient(app)

    rows = [
        {"at": _dt.datetime(2026, 4, 18, 10, 0, 0,
                            tzinfo=_dt.timezone.utc),
         "sent": 2, "failed": 0, "total_recipients": 2,
         "suppressed_quiet_hours": 0, "opted_out": 0, "no_email": 0,
         "total_admins": 2, "errors": [], "reason": None},
    ]

    class _Cursor:
        def __init__(self, docs):
            self._docs = [dict(d) for d in docs]
        def sort(self, *_a, **_k): return self
        def limit(self, *_a, **_k): return self
        def __aiter__(self):
            self._i = 0
            return self
        async def __anext__(self):
            if self._i >= len(self._docs):
                raise StopAsyncIteration
            d = self._docs[self._i]
            self._i += 1
            return d

    class _Coll:
        def find(self, *_a, **_k):
            return _Cursor(rows)

    class _DB:
        def __getitem__(self, _name):
            return _Coll()

    with patch.object(seo_engine, "_db", _DB()):
        res = client.get("/admin/seo/daily-summary-dispatches?limit=5")

    assert res.status_code == 200
    body = res.json()
    assert "dispatches" in body and len(body["dispatches"]) == 1
    at = body["dispatches"][0]["at"]
    assert isinstance(at, str)
    # ISO 8601 — the AdminDashboard parses this with `new Date(...)`.
    assert at.startswith("2026-04-18T10:00:00")


def test_dispatches_helper_clamps_limit_between_1_and_50():
    """The engine helper clamps wildly-large or non-positive ``limit`` values
    to the documented [1, 50] range so a malformed admin URL can't ask Mongo
    for an unbounded scan. The route forwards the raw value, so this guard
    must live in the helper."""
    import seo_engine

    captured = {}

    class _Cursor:
        def sort(self, *_a, **_k): return self
        def limit(self, n, *_a, **_k):
            captured["limit"] = n
            return self
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    class _Coll:
        def find(self, *_a, **_k): return _Cursor()

    class _DB:
        def __getitem__(self, _n): return _Coll()

    import asyncio
    # NOTE: ``asyncio.get_event_loop()`` raises ``RuntimeError: There is
    # no current event loop in thread 'MainThread'`` on Python 3.11+
    # when no loop is running and the auto-create-on-demand behaviour
    # has been removed. ``asyncio.run()`` creates a fresh loop per call,
    # which is what we want here — each clamp assertion is independent.
    with patch.object(seo_engine, "_db", _DB()):
        asyncio.run(seo_engine.get_recent_seo_summary_dispatches(limit=9999))
        assert captured["limit"] == 50
        # Negative limits are floored to 1 so a malformed URL can't ask Mongo
        # for a reverse/unbounded scan.
        asyncio.run(seo_engine.get_recent_seo_summary_dispatches(limit=-5))
        assert captured["limit"] == 1
        # ``limit=0`` falls back to the documented default (10) via the
        # ``limit or 10`` guard rather than being clamped to 1.
        asyncio.run(seo_engine.get_recent_seo_summary_dispatches(limit=0))
        assert captured["limit"] == 10
        asyncio.run(seo_engine.get_recent_seo_summary_dispatches(limit=20))
        assert captured["limit"] == 20
