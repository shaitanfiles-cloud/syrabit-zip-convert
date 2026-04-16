"""Tests for alert auto-expiration, acknowledgment, and listing.

Covers:
- _auto_expire_alerts respects enabled/disabled and day threshold
- PATCH /admin/alerts/{id}/acknowledge
- PATCH /admin/alerts/acknowledge-all
- GET /admin/alerts with filtering
"""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

import pytest

import metrics as _metrics_mod


@pytest.fixture(autouse=True)
def _reset_metrics_globals():
    _metrics_mod._ALERT_THRESHOLDS = dict(_metrics_mod._ALERT_THRESHOLDS_DEFAULT)
    _metrics_mod._alert_expiration = dict(_metrics_mod._ALERT_EXPIRATION_DEFAULT)
    _metrics_mod._notification_channels = dict(_metrics_mod._NOTIFICATION_CHANNELS_DEFAULT)
    _metrics_mod._alert_last_fired.clear()
    yield
    _metrics_mod._ALERT_THRESHOLDS = dict(_metrics_mod._ALERT_THRESHOLDS_DEFAULT)
    _metrics_mod._alert_expiration = dict(_metrics_mod._ALERT_EXPIRATION_DEFAULT)
    _metrics_mod._notification_channels = dict(_metrics_mod._NOTIFICATION_CHANNELS_DEFAULT)
    _metrics_mod._alert_last_fired.clear()


def _run(coro):
    # asyncio.get_event_loop() raises RuntimeError on Python 3.11+ when there
    # is no running loop in the current thread (which is the case after an
    # earlier test in the suite consumed/closed the implicit one). Make and
    # tear down a fresh loop per call so the helper is order-independent.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAutoExpireAlerts:
    def test_skips_when_disabled(self):
        _metrics_mod._alert_expiration = {"enabled": False, "days": 7}
        mock_alerts = MagicMock()
        mock_alerts.update_many = AsyncMock()
        with patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)):
            _run(_metrics_mod._auto_expire_alerts())
        mock_alerts.update_many.assert_not_called()

    def test_skips_when_enabled_missing(self):
        _metrics_mod._alert_expiration = {"days": 7}
        mock_alerts = MagicMock()
        mock_alerts.update_many = AsyncMock()
        with patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)):
            _run(_metrics_mod._auto_expire_alerts())
        mock_alerts.update_many.assert_not_called()

    def test_expires_old_alerts(self):
        _metrics_mod._alert_expiration = {"enabled": True, "days": 3}
        mock_result = MagicMock(modified_count=5)
        mock_alerts = MagicMock()
        mock_alerts.update_many = AsyncMock(return_value=mock_result)
        with patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)):
            _run(_metrics_mod._auto_expire_alerts())
        mock_alerts.update_many.assert_called_once()
        call_args = mock_alerts.update_many.call_args
        query = call_args[0][0]
        update = call_args[0][1]
        assert query["acknowledged"] is False
        assert "$lt" in query["fired_at"]
        assert update["$set"]["acknowledged"] is True
        assert update["$set"]["acknowledged_by"] == "auto-expiration"

    def test_uses_configured_days(self):
        _metrics_mod._alert_expiration = {"enabled": True, "days": 14}
        mock_result = MagicMock(modified_count=0)
        mock_alerts = MagicMock()
        mock_alerts.update_many = AsyncMock(return_value=mock_result)
        with patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)):
            _run(_metrics_mod._auto_expire_alerts())
        call_args = mock_alerts.update_many.call_args
        cutoff_str = call_args[0][0]["fired_at"]["$lt"]
        cutoff = datetime.fromisoformat(cutoff_str)
        expected_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        assert abs((cutoff - expected_cutoff).total_seconds()) < 5

    def test_defaults_to_7_days(self):
        _metrics_mod._alert_expiration = {"enabled": True}
        mock_result = MagicMock(modified_count=0)
        mock_alerts = MagicMock()
        mock_alerts.update_many = AsyncMock(return_value=mock_result)
        with patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)):
            _run(_metrics_mod._auto_expire_alerts())
        call_args = mock_alerts.update_many.call_args
        cutoff_str = call_args[0][0]["fired_at"]["$lt"]
        cutoff = datetime.fromisoformat(cutoff_str)
        expected_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        assert abs((cutoff - expected_cutoff).total_seconds()) < 5

    def test_survives_db_exception(self):
        _metrics_mod._alert_expiration = {"enabled": True, "days": 7}
        mock_alerts = MagicMock()
        mock_alerts.update_many = AsyncMock(side_effect=Exception("db down"))
        with patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)):
            _run(_metrics_mod._auto_expire_alerts())


class _AsyncCursorMock:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class TestAcknowledgeAlert:
    @pytest.fixture
    def mock_admin(self):
        return {"id": "admin-1", "email": "admin@test.com", "is_admin": True}

    @pytest.fixture
    def app_client(self, mock_admin):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.admin_notifications import router
        from auth_deps import get_admin_user

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_admin_user] = lambda: mock_admin
        return TestClient(app)

    def test_acknowledge_existing_alert(self, app_client):
        alert_id = str(ObjectId())
        mock_result = MagicMock(matched_count=1)
        mock_alerts = MagicMock()
        mock_alerts.update_one = AsyncMock(return_value=mock_result)
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.patch(f"/admin/alerts/{alert_id}/acknowledge")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        call_args = mock_alerts.update_one.call_args
        assert call_args[0][1]["$set"]["acknowledged"] is True
        assert call_args[0][1]["$set"]["acknowledged_by"] == "admin@test.com"

    def test_acknowledge_nonexistent_alert(self, app_client):
        alert_id = str(ObjectId())
        mock_result = MagicMock(matched_count=0)
        mock_alerts = MagicMock()
        mock_alerts.update_one = AsyncMock(return_value=mock_result)
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.patch(f"/admin/alerts/{alert_id}/acknowledge")
        assert resp.status_code == 404

    def test_acknowledge_invalid_id(self, app_client):
        with patch("routes.admin_notifications.db", MagicMock()):
            resp = app_client.patch("/admin/alerts/not-a-valid-oid/acknowledge")
        assert resp.status_code == 400

    def test_acknowledge_all(self, app_client):
        mock_result = MagicMock(modified_count=3)
        mock_alerts = MagicMock()
        mock_alerts.update_many = AsyncMock(return_value=mock_result)
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.patch("/admin/alerts/acknowledge-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["modified"] == 3


class TestGetAlerts:
    @pytest.fixture
    def mock_admin(self):
        return {"id": "admin-1", "email": "admin@test.com", "is_admin": True}

    @pytest.fixture
    def app_client(self, mock_admin):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.admin_notifications import router
        from auth_deps import get_admin_user

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_admin_user] = lambda: mock_admin
        return TestClient(app)

    def test_list_alerts_returns_results(self, app_client):
        oid = ObjectId()
        docs = [{"_id": oid, "alert_type": "high_error_rate", "title": "Test", "acknowledged": False, "fired_at": "2026-01-01T00:00:00+00:00"}]
        mock_alerts = MagicMock()
        mock_alerts.find = MagicMock(return_value=_AsyncCursorMock(docs))
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.get("/admin/alerts")
        assert resp.status_code == 200
        data = resp.json()
        alerts = data if isinstance(data, list) else data.get("alerts", data)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "high_error_rate"
        assert alerts[0]["_id"] == str(oid)

    def test_filter_acknowledged_true(self, app_client):
        mock_alerts = MagicMock()
        mock_alerts.find = MagicMock(return_value=_AsyncCursorMock([]))
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.get("/admin/alerts?acknowledged=true")
        assert resp.status_code == 200
        call_args = mock_alerts.find.call_args
        assert call_args[0][0]["acknowledged"] is True

    def test_filter_acknowledged_false(self, app_client):
        mock_alerts = MagicMock()
        mock_alerts.find = MagicMock(return_value=_AsyncCursorMock([]))
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.get("/admin/alerts?acknowledged=false")
        assert resp.status_code == 200
        call_args = mock_alerts.find.call_args
        assert call_args[0][0]["acknowledged"] is False

    def test_no_filter_returns_all(self, app_client):
        mock_alerts = MagicMock()
        mock_alerts.find = MagicMock(return_value=_AsyncCursorMock([]))
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.get("/admin/alerts")
        assert resp.status_code == 200
        call_args = mock_alerts.find.call_args
        assert call_args[0][0] == {}

    def test_limit_param(self, app_client):
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=_AsyncCursorMock([]))
        mock_alerts = MagicMock()
        mock_alerts.find = MagicMock(return_value=mock_cursor)
        with patch("routes.admin_notifications.db", MagicMock(alerts=mock_alerts)):
            resp = app_client.get("/admin/alerts?limit=10")
        assert resp.status_code == 200
        mock_cursor.limit.assert_called_once_with(10)
