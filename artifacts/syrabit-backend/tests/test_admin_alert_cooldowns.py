"""Tests for the admin alert-cooldowns visibility endpoints (Task #987).

Covers:
- GET /admin/alerts/cooldowns lists rows from db.alert_dispatch_log
  with computed cooldown_expires_at + seconds_until_expires + active.
- only_active=true filters out rows whose cooldown has already lapsed.
- DELETE /admin/alerts/cooldowns/{dedup_key} removes a row and clears
  the in-memory cooldown mirror in metrics.
"""
import time as _time_mod
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import metrics as _metrics_mod


@pytest.fixture(autouse=True)
def _reset_metrics_globals():
    _metrics_mod._alert_last_fired.clear()
    yield
    _metrics_mod._alert_last_fired.clear()


class _AsyncCursorMock:
    def __init__(self, docs):
        self._docs = list(docs)
        self.sort_args = None
        self.limit_arg = None

    def sort(self, *a, **kw):
        self.sort_args = (a, kw)
        return self

    def limit(self, n):
        self.limit_arg = n
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "admin@test.com", "is_admin": True}


@pytest.fixture
def app_client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.admin_notifications import router
    from auth_deps import get_admin_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_admin_user] = lambda: mock_admin
    return TestClient(app)


class TestGetAlertCooldowns:
    def test_lists_rows_with_computed_fields(self, app_client):
        now = _time_mod.time()
        fired = datetime.now(timezone.utc) - timedelta(minutes=30)
        docs = [{
            "dedup_key": "high_error_rate",
            "alert_type": "high_error_rate",
            "ts": now - 1800,
            "fired_at": fired,
        }]
        mock_log = MagicMock()
        mock_log.find = MagicMock(return_value=_AsyncCursorMock(docs))
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.get("/admin/alerts/cooldowns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["active_count"] == 1
        assert data["cooldown_window_seconds"] == 6 * 3600
        row = data["cooldowns"][0]
        assert row["dedup_key"] == "high_error_rate"
        assert row["alert_type"] == "high_error_rate"
        assert row["fired_at"] is not None
        assert row["cooldown_expires_at"] is not None
        # Roughly 5h30m left in the 6h window
        assert 19000 < row["seconds_until_expires"] < 20000
        assert row["active"] is True

    def test_marks_expired_rows_as_inactive(self, app_client):
        now = _time_mod.time()
        # ts well past the 6h cooldown window
        old_ts = now - (7 * 3600)
        docs = [{
            "dedup_key": "high_latency",
            "alert_type": "high_latency",
            "ts": old_ts,
            "fired_at": datetime.now(timezone.utc) - timedelta(hours=7),
        }]
        mock_log = MagicMock()
        mock_log.find = MagicMock(return_value=_AsyncCursorMock(docs))
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.get("/admin/alerts/cooldowns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_count"] == 0
        assert data["cooldowns"][0]["active"] is False
        assert data["cooldowns"][0]["seconds_until_expires"] == 0

    def test_only_active_filters_query(self, app_client):
        mock_log = MagicMock()
        mock_log.find = MagicMock(return_value=_AsyncCursorMock([]))
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.get("/admin/alerts/cooldowns?only_active=true")
        assert resp.status_code == 200
        call_args = mock_log.find.call_args
        query = call_args[0][0]
        assert "ts" in query
        assert "$gte" in query["ts"]

    def test_no_only_active_passes_empty_query(self, app_client):
        mock_log = MagicMock()
        mock_log.find = MagicMock(return_value=_AsyncCursorMock([]))
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.get("/admin/alerts/cooldowns")
        assert resp.status_code == 200
        call_args = mock_log.find.call_args
        assert call_args[0][0] == {}

    def test_sorted_desc_by_ts(self, app_client):
        cursor = _AsyncCursorMock([])
        mock_log = MagicMock()
        mock_log.find = MagicMock(return_value=cursor)
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.get("/admin/alerts/cooldowns")
        assert resp.status_code == 200
        assert cursor.sort_args is not None
        sort_args, _ = cursor.sort_args
        assert sort_args == ("ts", -1)

    def test_limit_param_propagates(self, app_client):
        cursor = _AsyncCursorMock([])
        mock_log = MagicMock()
        mock_log.find = MagicMock(return_value=cursor)
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.get("/admin/alerts/cooldowns?limit=42")
        assert resp.status_code == 200
        assert cursor.limit_arg == 42

    def test_handles_string_fired_at(self, app_client):
        now = _time_mod.time()
        docs = [{
            "dedup_key": "spoofed_bot_surge|host=example.com",
            "alert_type": "spoofed_bot_surge",
            "ts": now - 60,
            "fired_at": "2026-04-27T10:00:00+00:00",
        }]
        mock_log = MagicMock()
        mock_log.find = MagicMock(return_value=_AsyncCursorMock(docs))
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.get("/admin/alerts/cooldowns")
        assert resp.status_code == 200
        row = resp.json()["cooldowns"][0]
        assert row["fired_at"] == "2026-04-27T10:00:00+00:00"


class TestReleaseAlertCooldown:
    def test_release_existing_dedup_key(self, app_client):
        # Pre-populate the in-memory mirror so we can verify it's cleared.
        _metrics_mod._alert_last_fired["high_error_rate"] = _time_mod.time()
        mock_result = MagicMock(deleted_count=1)
        mock_log = MagicMock()
        mock_log.delete_one = AsyncMock(return_value=mock_result)
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.delete("/admin/alerts/cooldowns/high_error_rate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["dedup_key"] == "high_error_rate"
        assert body["released_by"] == "admin@test.com"
        mock_log.delete_one.assert_awaited_once_with({"dedup_key": "high_error_rate"})
        # In-memory cooldown mirror should be cleared so the next dispatch
        # in this worker isn't blocked by the 30-min in-process backstop.
        assert "high_error_rate" not in _metrics_mod._alert_last_fired

    def test_release_strips_target_suffix_for_in_memory_mirror(self, app_client):
        _metrics_mod._alert_last_fired["endpoint_down"] = _time_mod.time()
        mock_result = MagicMock(deleted_count=1)
        mock_log = MagicMock()
        mock_log.delete_one = AsyncMock(return_value=mock_result)
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.delete("/admin/alerts/cooldowns/endpoint_down|endpoint=https://example.com/cms")
        assert resp.status_code == 200
        # The in-memory mirror is keyed by alert_type only, so we strip
        # everything after the first "|" before clearing.
        assert "endpoint_down" not in _metrics_mod._alert_last_fired

    def test_release_missing_returns_404(self, app_client):
        mock_result = MagicMock(deleted_count=0)
        mock_log = MagicMock()
        mock_log.delete_one = AsyncMock(return_value=mock_result)
        with patch("routes.admin_notifications.db", MagicMock(alert_dispatch_log=mock_log)):
            resp = app_client.delete("/admin/alerts/cooldowns/never_existed")
        assert resp.status_code == 404
