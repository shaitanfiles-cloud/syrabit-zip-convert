"""Tests for alert threshold save/load flow.

Covers:
- GET /admin/alert-settings
- PUT /admin/alert-settings (valid + invalid inputs)
- _load_alert_settings reads db-stored notification_channels
- _dispatch_alert uses db-stored email/webhook_url with env var fallback
- Validation rejects invalid email and webhook URL formats
"""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import metrics as _metrics_mod


@pytest.fixture(autouse=True)
def _reset_metrics_globals():
    """Reset metrics globals before each test."""
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
    return asyncio.get_event_loop().run_until_complete(coro)


class TestLoadAlertSettings:
    def test_loads_defaults_when_no_config(self):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._ALERT_THRESHOLDS == _metrics_mod._ALERT_THRESHOLDS_DEFAULT
        assert _metrics_mod._alert_expiration == _metrics_mod._ALERT_EXPIRATION_DEFAULT
        assert _metrics_mod._notification_channels == _metrics_mod._NOTIFICATION_CHANNELS_DEFAULT

    def test_loads_stored_thresholds(self):
        cfg = {
            "alert_settings": {
                "thresholds": {"latency_p95_ms": 5000, "error_rate_pct": 10.0},
                "expiration": {},
                "notification_channels": {},
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._ALERT_THRESHOLDS["latency_p95_ms"] == 5000
        assert _metrics_mod._ALERT_THRESHOLDS["error_rate_pct"] == 10.0
        assert _metrics_mod._ALERT_THRESHOLDS["fallback_rate_pct"] == _metrics_mod._ALERT_THRESHOLDS_DEFAULT["fallback_rate_pct"]

    def test_loads_notification_channels_from_db(self):
        cfg = {
            "alert_settings": {
                "thresholds": {},
                "expiration": {},
                "notification_channels": {
                    "email": "admin@example.com",
                    "webhook_url": "https://hooks.slack.com/abc",
                },
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._notification_channels["email"] == "admin@example.com"
        assert _metrics_mod._notification_channels["webhook_url"] == "https://hooks.slack.com/abc"

    def test_loads_expiration_settings(self):
        cfg = {
            "alert_settings": {
                "thresholds": {},
                "expiration": {"enabled": True, "days": 14},
                "notification_channels": {},
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._alert_expiration["enabled"] is True
        assert _metrics_mod._alert_expiration["days"] == 14

    def test_ignores_invalid_threshold_values(self):
        cfg = {
            "alert_settings": {
                "thresholds": {"latency_p95_ms": "not-a-number", "error_rate_pct": 3.0},
                "expiration": {},
                "notification_channels": {},
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._ALERT_THRESHOLDS["latency_p95_ms"] == _metrics_mod._ALERT_THRESHOLDS_DEFAULT["latency_p95_ms"]
        assert _metrics_mod._ALERT_THRESHOLDS["error_rate_pct"] == 3.0

    def test_ignores_unknown_threshold_keys(self):
        cfg = {
            "alert_settings": {
                "thresholds": {"unknown_key": 999},
                "expiration": {},
                "notification_channels": {},
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert "unknown_key" not in _metrics_mod._ALERT_THRESHOLDS

    def test_strips_whitespace_from_channels(self):
        cfg = {
            "alert_settings": {
                "thresholds": {},
                "expiration": {},
                "notification_channels": {
                    "email": "  admin@example.com  ",
                    "webhook_url": "  https://hooks.slack.com/x  ",
                },
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._notification_channels["email"] == "admin@example.com"
        assert _metrics_mod._notification_channels["webhook_url"] == "https://hooks.slack.com/x"

    def test_survives_db_exception(self):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(side_effect=Exception("DB down"))
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._ALERT_THRESHOLDS == _metrics_mod._ALERT_THRESHOLDS_DEFAULT

    def test_expiration_days_clamped_to_minimum_1(self):
        cfg = {
            "alert_settings": {
                "thresholds": {},
                "expiration": {"days": -5},
                "notification_channels": {},
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._alert_expiration["days"] >= 1


class TestDispatchAlert:
    def test_uses_db_stored_email_over_env(self):
        _metrics_mod._notification_channels["email"] = "db-admin@example.com"
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock()
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        with patch.dict(os.environ, {"ALERT_EMAIL": "env-admin@example.com", "RESEND_API_KEY": "re_test_key"}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch.dict("sys.modules", {"resend": mock_resend}), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("test_alert", "Test Title", "Test body"))
        call_args = mock_resend.Emails.send.call_args[0][0]
        assert call_args["to"] == ["db-admin@example.com"]

    def test_falls_back_to_env_email_when_db_empty(self):
        _metrics_mod._notification_channels["email"] = ""
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock()
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        with patch.dict(os.environ, {"ALERT_EMAIL": "env-fallback@example.com", "RESEND_API_KEY": "re_test_key"}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch.dict("sys.modules", {"resend": mock_resend}), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("test_env_fallback", "Title", "Body"))
        call_args = mock_resend.Emails.send.call_args[0][0]
        assert call_args["to"] == ["env-fallback@example.com"]

    def test_uses_db_stored_webhook_url(self):
        _metrics_mod._notification_channels["webhook_url"] = "https://hooks.slack.com/db-webhook"
        _metrics_mod._notification_channels["email"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": "https://env-webhook.com", "RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("test_webhook", "Webhook Title", "Webhook body"))
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/db-webhook"

    def test_falls_back_to_env_webhook_when_db_empty(self):
        _metrics_mod._notification_channels["webhook_url"] = ""
        _metrics_mod._notification_channels["email"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": "https://env-fallback-webhook.com", "RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("test_webhook_env", "Title", "Body"))
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://env-fallback-webhook.com"

    def test_respects_cooldown(self):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("cooldown_test", "Title 1", "Body 1"))
            _run(_metrics_mod._dispatch_alert("cooldown_test", "Title 2", "Body 2"))
        assert mock_alerts.insert_one.await_count == 1

    def test_email_includes_threshold_snapshot(self):
        _metrics_mod._notification_channels["email"] = "admin@example.com"
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock()
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        snapshot = {"metric": "error_rate_pct", "value": 5, "actual": 12.3}
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch.dict("sys.modules", {"resend": mock_resend}), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("thresh_email", "Rate spike", "Body", threshold_snapshot=snapshot))
        call_args = mock_resend.Emails.send.call_args[0][0]
        html = call_args["html"]
        assert "error_rate_pct" in html
        assert "12.3" in html
        assert "5" in html
        assert "<table" in html

    def test_email_omits_threshold_table_when_no_snapshot(self):
        _metrics_mod._notification_channels["email"] = "admin@example.com"
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock()
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch.dict("sys.modules", {"resend": mock_resend}), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("no_thresh_email", "Title", "Body"))
        call_args = mock_resend.Emails.send.call_args[0][0]
        assert "<table" not in call_args["html"]

    def test_webhook_includes_threshold_snapshot(self):
        _metrics_mod._notification_channels["webhook_url"] = "https://hooks.slack.com/test"
        _metrics_mod._notification_channels["email"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        snapshot = {"metric": "latency_p95_ms", "value": 3000, "actual": 5500}
        with patch.dict(os.environ, {"RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("thresh_webhook", "Latency spike", "Body", threshold_snapshot=snapshot))
        payload = mock_client.post.call_args[1]["json"]
        assert payload["threshold_snapshot"] == snapshot
        assert "latency_p95_ms" in payload["text"]
        assert "5500" in payload["text"]

    def test_webhook_omits_threshold_when_no_snapshot(self):
        _metrics_mod._notification_channels["webhook_url"] = "https://hooks.slack.com/test"
        _metrics_mod._notification_channels["email"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("no_thresh_wh", "Title", "Body"))
        payload = mock_client.post.call_args[1]["json"]
        assert "threshold_snapshot" not in payload

    def test_no_email_or_webhook_still_persists_alert(self):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        with patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert("persist_test", "Title", "Body"))
        mock_alerts.insert_one.assert_awaited_once()
        doc = mock_alerts.insert_one.call_args[0][0]
        assert doc["type"] == "persist_test"
        assert doc["title"] == "Title"
        assert doc["acknowledged"] is False


class TestPutAlertSettingsValidation:
    @pytest.fixture
    def mock_admin(self):
        return {"id": "admin-123", "email": "admin@test.com", "is_admin": True}

    @pytest.fixture
    def app_client(self, mock_admin):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.admin_notifications import router

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides = {}

        from auth_deps import get_admin_user
        app.dependency_overrides[get_admin_user] = lambda: mock_admin

        return TestClient(app)

    def test_put_valid_settings(self, app_client):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value={})
        mock_collection.replace_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 3000},
                "expiration": {"enabled": True, "days": 30},
                "notification_channels": {
                    "email": "alerts@example.com",
                    "webhook_url": "https://hooks.slack.com/test",
                },
            })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        saved = mock_collection.replace_one.call_args[0][1]
        assert saved["alert_settings"]["thresholds"]["latency_p95_ms"] == 3000
        assert saved["alert_settings"]["notification_channels"]["email"] == "alerts@example.com"
        assert saved["alert_settings"]["notification_channels"]["webhook_url"] == "https://hooks.slack.com/test"
        assert saved["alert_settings"]["expiration"]["enabled"] is True
        assert saved["alert_settings"]["expiration"]["days"] == 30

    def test_rejects_invalid_email(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "thresholds": {},
            "notification_channels": {"email": "not-an-email"},
        })
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    def test_rejects_invalid_webhook_url(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "thresholds": {},
            "notification_channels": {"webhook_url": "ftp://invalid.com/hook"},
        })
        assert resp.status_code == 400
        assert "webhook" in resp.json()["detail"].lower()

    def test_rejects_negative_threshold(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "thresholds": {"latency_p95_ms": -100},
        })
        assert resp.status_code == 400
        assert "threshold" in resp.json()["detail"].lower()

    def test_rejects_zero_threshold_for_non_zero_allowed(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "thresholds": {"latency_p95_ms": 0},
        })
        assert resp.status_code == 400

    def test_allows_zero_for_auto_block_threshold(self, app_client):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value={})
        mock_collection.replace_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.put("/admin/alert-settings", json={
                "thresholds": {"auto_block_threshold": 0},
            })
        assert resp.status_code == 200

    def test_rejects_non_numeric_threshold(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "thresholds": {"latency_p95_ms": "abc"},
        })
        assert resp.status_code == 400

    def test_rejects_expiration_days_out_of_range(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "expiration": {"days": 0},
        })
        assert resp.status_code == 400

        resp = app_client.put("/admin/alert-settings", json={
            "expiration": {"days": 400},
        })
        assert resp.status_code == 400

    def test_rejects_non_bool_expiration_enabled(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "expiration": {"enabled": "yes"},
        })
        assert resp.status_code == 400

    def test_accepts_empty_email_and_webhook(self, app_client):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value={})
        mock_collection.replace_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.put("/admin/alert-settings", json={
                "notification_channels": {"email": "", "webhook_url": ""},
            })
        assert resp.status_code == 200

    def test_accepts_http_webhook_url(self, app_client):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value={})
        mock_collection.replace_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.put("/admin/alert-settings", json={
                "notification_channels": {"webhook_url": "http://internal.hook/alert"},
            })
        assert resp.status_code == 200


class TestGetAlertSettings:
    @pytest.fixture
    def mock_admin(self):
        return {"id": "admin-123", "email": "admin@test.com", "is_admin": True}

    @pytest.fixture
    def app_client(self, mock_admin):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routes.admin_notifications import router

        app = FastAPI()
        app.include_router(router)
        from auth_deps import get_admin_user
        app.dependency_overrides[get_admin_user] = lambda: mock_admin
        return TestClient(app)

    def test_get_returns_defaults_with_structure(self, app_client):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.get("/admin/alert-settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "thresholds" in data
        assert "expiration" in data
        assert "notification_channels" in data
        assert "defaults" in data
        assert data["defaults"]["thresholds"] == _metrics_mod._ALERT_THRESHOLDS_DEFAULT

    def test_get_returns_stored_channels(self, app_client):
        cfg = {
            "alert_settings": {
                "thresholds": {},
                "expiration": {},
                "notification_channels": {
                    "email": "stored@example.com",
                    "webhook_url": "https://stored-hook.com/x",
                },
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.get("/admin/alert-settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["notification_channels"]["email"] == "stored@example.com"
        assert data["notification_channels"]["webhook_url"] == "https://stored-hook.com/x"


class _InMemoryCollection:
    def __init__(self):
        self._store = None

    async def find_one(self, query=None, projection=None):
        return dict(self._store) if self._store else None

    async def replace_one(self, query, doc, upsert=False):
        self._store = dict(doc)


class TestAlertSettingsRoundTrip:
    @pytest.fixture
    def mock_admin(self):
        return {"id": "admin-rt", "email": "admin@rt.test", "is_admin": True}

    @pytest.fixture
    def in_memory_db(self):
        coll = _InMemoryCollection()
        fake_db = MagicMock()
        fake_db.api_config = coll
        return fake_db

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

    def test_put_then_get_reflects_saved_values(self, app_client, in_memory_db):
        with patch.object(_metrics_mod, "db", in_memory_db), \
             patch("routes.admin_notifications.db", in_memory_db):
            put_resp = app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 4000, "error_rate_pct": 8.5},
                "expiration": {"enabled": True, "days": 14},
                "notification_channels": {
                    "email": "roundtrip@example.com",
                    "webhook_url": "https://hooks.test/rt",
                },
            })
            assert put_resp.status_code == 200

            get_resp = app_client.get("/admin/alert-settings")
            assert get_resp.status_code == 200
            data = get_resp.json()

        assert data["thresholds"]["latency_p95_ms"] == 4000
        assert data["thresholds"]["error_rate_pct"] == 8.5
        assert data["expiration"]["enabled"] is True
        assert data["expiration"]["days"] == 14
        assert data["notification_channels"]["email"] == "roundtrip@example.com"
        assert data["notification_channels"]["webhook_url"] == "https://hooks.test/rt"

    def test_overwrite_existing_settings(self, app_client, in_memory_db):
        with patch.object(_metrics_mod, "db", in_memory_db), \
             patch("routes.admin_notifications.db", in_memory_db):
            app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 2000},
                "notification_channels": {"email": "first@example.com"},
            })

            app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 9000, "error_rate_pct": 15.0},
                "notification_channels": {"email": "second@example.com", "webhook_url": "https://hooks.test/v2"},
            })

            get_resp = app_client.get("/admin/alert-settings")
            data = get_resp.json()

        assert data["thresholds"]["latency_p95_ms"] == 9000
        assert data["thresholds"]["error_rate_pct"] == 15.0
        assert data["notification_channels"]["email"] == "second@example.com"
        assert data["notification_channels"]["webhook_url"] == "https://hooks.test/v2"

    def test_load_alert_settings_reads_persisted_data(self, in_memory_db, app_client):
        with patch.object(_metrics_mod, "db", in_memory_db), \
             patch("routes.admin_notifications.db", in_memory_db):
            app_client.put("/admin/alert-settings", json={
                "thresholds": {"error_rate_pct": 12.0},
                "expiration": {"enabled": False},
                "notification_channels": {"email": "load-test@example.com"},
            })

        _metrics_mod._ALERT_THRESHOLDS = dict(_metrics_mod._ALERT_THRESHOLDS_DEFAULT)
        _metrics_mod._alert_expiration = dict(_metrics_mod._ALERT_EXPIRATION_DEFAULT)
        _metrics_mod._notification_channels = dict(_metrics_mod._NOTIFICATION_CHANNELS_DEFAULT)

        with patch.object(_metrics_mod, "db", in_memory_db):
            _run(_metrics_mod._load_alert_settings())

        assert _metrics_mod._ALERT_THRESHOLDS["error_rate_pct"] == 12.0
        assert _metrics_mod._alert_expiration["enabled"] is False
        assert _metrics_mod._notification_channels["email"] == "load-test@example.com"

    def test_empty_db_returns_defaults(self, app_client, in_memory_db):
        with patch.object(_metrics_mod, "db", in_memory_db), \
             patch("routes.admin_notifications.db", in_memory_db):
            get_resp = app_client.get("/admin/alert-settings")
            data = get_resp.json()

        assert data["thresholds"] == data["defaults"]["thresholds"]
