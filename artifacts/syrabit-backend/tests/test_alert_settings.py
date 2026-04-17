"""Tests for alert threshold save/load flow.

Covers:
- GET /admin/alert-settings
- PUT /admin/alert-settings (valid + invalid inputs)
- _load_alert_settings reads db-stored notification_channels
- _dispatch_alert uses db-stored email/webhook_url with env var fallback
- Validation rejects invalid email and webhook URL formats
"""
import asyncio
import contextlib
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
    # asyncio.get_event_loop() raises RuntimeError on Python 3.11+ when there
    # is no running loop in the current thread. Make and tear down a fresh
    # loop per call so the helper is order-independent.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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

    def test_seo_alert_uses_slack_block_payload(self):
        _metrics_mod._notification_channels["webhook_url"] = "https://hooks.slack.com/seo"
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["seo_slack_enabled"] = True
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        snapshot = {
            "metric": "seo_health_status", "value": "ok", "actual": "critical",
            "valid_sitemaps": 3, "total_sitemaps": 5, "url_check_success_rate": 62.5,
        }
        with patch.dict(os.environ, {"RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert(
                "seo_health_degraded", "SEO health: CRITICAL",
                "Two consecutive failures.", threshold_snapshot=snapshot,
            ))
        assert mock_client.post.await_count == 1
        sent_url = mock_client.post.call_args[0][0]
        payload = mock_client.post.call_args.kwargs["json"]
        assert sent_url == "https://hooks.slack.com/seo"
        # Slack Block Kit payload with severity + counts + dashboard button
        assert "blocks" in payload and isinstance(payload["blocks"], list)
        assert payload["alert_type"] == "seo_health_degraded"
        text = payload["text"]
        assert "CRITICAL" in text
        assert "3 / 5" in text or "3 /" in text
        assert _metrics_mod._SEO_DASHBOARD_URL in text
        # Dashboard link button
        actions = [b for b in payload["blocks"] if b.get("type") == "actions"]
        assert actions, "expected actions block with dashboard button"
        assert actions[0]["elements"][0]["url"] == _metrics_mod._SEO_DASHBOARD_URL

    def test_seo_slack_toggle_disables_webhook_for_seo_alerts(self):
        _metrics_mod._notification_channels["webhook_url"] = "https://hooks.slack.com/seo"
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["seo_slack_enabled"] = False
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock):
            _run(_metrics_mod._dispatch_alert(
                "seo_health_degraded", "SEO health: DEGRADED", "body",
                threshold_snapshot={"metric": "seo_health_status", "value": "ok", "actual": "degraded"},
            ))
            # But non-SEO alerts still post
            _metrics_mod._alert_last_fired.clear()
            _run(_metrics_mod._dispatch_alert("high_error_rate", "Spike", "body"))
        assert mock_client.post.await_count == 1
        assert mock_client.post.call_args[0][0] == "https://hooks.slack.com/seo"
        assert mock_client.post.call_args.kwargs["json"]["alert_type"] == "high_error_rate"

    def test_load_alert_settings_parses_seo_slack_toggle(self):
        cfg = {
            "alert_settings": {
                "thresholds": {},
                "expiration": {},
                "notification_channels": {
                    "email": "a@b.com", "webhook_url": "https://x",
                    "seo_slack_enabled": False,
                },
            }
        }
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=cfg)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)):
            _run(_metrics_mod._load_alert_settings())
        assert _metrics_mod._notification_channels["seo_slack_enabled"] is False

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

    def test_put_persists_seo_slack_toggle(self, app_client):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value={})
        mock_collection.replace_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.put("/admin/alert-settings", json={
                "thresholds": {},
                "notification_channels": {
                    "webhook_url": "https://hooks.slack.com/seo",
                    "seo_slack_enabled": False,
                },
            })
        assert resp.status_code == 200
        saved = mock_collection.replace_one.call_args[0][1]
        assert saved["alert_settings"]["notification_channels"]["seo_slack_enabled"] is False

    def test_put_persists_hydrate_slack_toggle(self, app_client):
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value={})
        mock_collection.replace_one = AsyncMock(return_value=None)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.put("/admin/alert-settings", json={
                "thresholds": {},
                "notification_channels": {
                    "webhook_url": "https://hooks.slack.com/hyd",
                    "hydrate_slack_enabled": False,
                },
            })
        assert resp.status_code == 200
        saved = mock_collection.replace_one.call_args[0][1]
        assert saved["alert_settings"]["notification_channels"]["hydrate_slack_enabled"] is False

    def test_put_round_trips_hydrate_slack_toggle_into_runtime(self, app_client):
        """Save hydrate_slack_enabled=False, then GET — and verify
        _load_alert_settings actually pushes the value into the
        in-memory _notification_channels used by _dispatch_alert.
        """
        stored = {}
        async def _find_one(*a, **kw):
            return dict(stored) if stored else None
        async def _replace_one(filt, doc, upsert=False):
            stored.clear()
            stored.update(doc)
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(side_effect=_find_one)
        mock_collection.replace_one = AsyncMock(side_effect=_replace_one)
        with patch.object(_metrics_mod, "db", MagicMock(api_config=mock_collection)), \
             patch("routes.admin_notifications.db", MagicMock(api_config=mock_collection)):
            resp = app_client.put("/admin/alert-settings", json={
                "thresholds": {},
                "notification_channels": {"hydrate_slack_enabled": False},
            })
            assert resp.status_code == 200
            assert _metrics_mod._notification_channels["hydrate_slack_enabled"] is False
            get_resp = app_client.get("/admin/alert-settings")
            assert get_resp.status_code == 200
            data = get_resp.json()
            assert data["notification_channels"]["hydrate_slack_enabled"] is False

    def test_rejects_invalid_hydrate_slack_toggle(self, app_client):
        resp = app_client.put("/admin/alert-settings", json={
            "thresholds": {},
            "notification_channels": {"hydrate_slack_enabled": "yes"},
        })
        assert resp.status_code == 400
        assert "hydrate_slack_enabled" in resp.json()["detail"]

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


class TestAlertSettingsRoundTrip:
    @pytest.fixture
    def mock_admin(self):
        return {"id": "admin-rt", "email": "admin@rt.test", "is_admin": True}

    @pytest.fixture
    def mongo_db(self):
        from mongomock_motor import AsyncMongoMockClient
        client = AsyncMongoMockClient()
        return client["test_alert_settings"]

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

    def test_put_then_get_reflects_saved_values(self, app_client, mongo_db):
        with patch.object(_metrics_mod, "db", mongo_db), \
             patch("routes.admin_notifications.db", mongo_db):
            put_resp = app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 4000, "error_rate_pct": 8.5},
                "expiration": {"enabled": True, "days": 14},
                "notification_channels": {
                    "email": "roundtrip@example.com",
                    "webhook_url": "https://hooks.test/rt",
                },
            })
            assert put_resp.status_code == 200

            doc = _run(mongo_db.api_config.find_one({}))
            assert doc is not None
            assert doc["alert_settings"]["thresholds"]["latency_p95_ms"] == 4000

            get_resp = app_client.get("/admin/alert-settings")
            assert get_resp.status_code == 200
            data = get_resp.json()

        assert data["thresholds"]["latency_p95_ms"] == 4000
        assert data["thresholds"]["error_rate_pct"] == 8.5
        assert data["expiration"]["enabled"] is True
        assert data["expiration"]["days"] == 14
        assert data["notification_channels"]["email"] == "roundtrip@example.com"
        assert data["notification_channels"]["webhook_url"] == "https://hooks.test/rt"

    def test_overwrite_existing_settings(self, app_client, mongo_db):
        with patch.object(_metrics_mod, "db", mongo_db), \
             patch("routes.admin_notifications.db", mongo_db):
            app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 2000},
                "expiration": {"enabled": True, "days": 30},
                "notification_channels": {"email": "first@example.com"},
            })

            app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 9000, "error_rate_pct": 15.0},
                "expiration": {"enabled": False, "days": 7},
                "notification_channels": {"email": "second@example.com", "webhook_url": "https://hooks.test/v2"},
            })

            doc = _run(mongo_db.api_config.find_one({}))
            assert doc["alert_settings"]["thresholds"]["latency_p95_ms"] == 9000

            get_resp = app_client.get("/admin/alert-settings")
            data = get_resp.json()

        assert data["thresholds"]["latency_p95_ms"] == 9000
        assert data["thresholds"]["error_rate_pct"] == 15.0
        assert data["expiration"]["enabled"] is False
        assert data["expiration"]["days"] == 7
        assert data["notification_channels"]["email"] == "second@example.com"
        assert data["notification_channels"]["webhook_url"] == "https://hooks.test/v2"

    def test_load_alert_settings_reads_persisted_data(self, mongo_db, app_client):
        with patch.object(_metrics_mod, "db", mongo_db), \
             patch("routes.admin_notifications.db", mongo_db):
            app_client.put("/admin/alert-settings", json={
                "thresholds": {"error_rate_pct": 12.0},
                "expiration": {"enabled": False},
                "notification_channels": {"email": "load-test@example.com"},
            })

        _metrics_mod._ALERT_THRESHOLDS = dict(_metrics_mod._ALERT_THRESHOLDS_DEFAULT)
        _metrics_mod._alert_expiration = dict(_metrics_mod._ALERT_EXPIRATION_DEFAULT)
        _metrics_mod._notification_channels = dict(_metrics_mod._NOTIFICATION_CHANNELS_DEFAULT)

        with patch.object(_metrics_mod, "db", mongo_db):
            _run(_metrics_mod._load_alert_settings())

        assert _metrics_mod._ALERT_THRESHOLDS["error_rate_pct"] == 12.0
        assert _metrics_mod._alert_expiration["enabled"] is False
        assert _metrics_mod._notification_channels["email"] == "load-test@example.com"

    def test_empty_db_returns_defaults(self, app_client, mongo_db):
        with patch.object(_metrics_mod, "db", mongo_db), \
             patch("routes.admin_notifications.db", mongo_db):
            get_resp = app_client.get("/admin/alert-settings")
            data = get_resp.json()

        assert data["thresholds"] == data["defaults"]["thresholds"]

    def test_db_document_shape_after_put(self, app_client, mongo_db):
        with patch.object(_metrics_mod, "db", mongo_db), \
             patch("routes.admin_notifications.db", mongo_db):
            app_client.put("/admin/alert-settings", json={
                "thresholds": {"latency_p95_ms": 5000},
                "expiration": {"enabled": True, "days": 7},
                "notification_channels": {"email": "shape@test.com"},
            })

            doc = _run(mongo_db.api_config.find_one({}, {"_id": 0}))

        assert "alert_settings" in doc
        settings = doc["alert_settings"]
        assert isinstance(settings["thresholds"], dict)
        assert isinstance(settings["expiration"], dict)
        assert isinstance(settings["notification_channels"], dict)
        assert settings["thresholds"]["latency_p95_ms"] == 5000
        assert settings["expiration"]["enabled"] is True
        assert settings["expiration"]["days"] == 7
        assert settings["notification_channels"]["email"] == "shape@test.com"


class TestDispatchAlertWithMongomock:
    @pytest.fixture
    def mongo_db(self):
        from mongomock_motor import AsyncMongoMockClient
        client = AsyncMongoMockClient()
        return client["test_dispatch"]

    def _dispatch(self, mongo_db, alert_type, title, body, threshold_snapshot=None, extra_patches=None):
        patches = [
            patch.object(_metrics_mod, "db", mongo_db),
            patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock),
        ]
        if extra_patches:
            patches.extend(extra_patches)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            _run(_metrics_mod._dispatch_alert(alert_type, title, body, threshold_snapshot=threshold_snapshot))

    def test_persist_alert_document_shape(self, mongo_db):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        with patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}):
            self._dispatch(mongo_db, "shape_test", "Alert Title", "Alert body text")

        doc = _run(mongo_db.alerts.find_one({"type": "shape_test"}))
        assert doc is not None
        assert doc["type"] == "shape_test"
        assert doc["title"] == "Alert Title"
        assert doc["body"] == "Alert body text"
        assert doc["acknowledged"] is False
        assert "fired_at" in doc
        assert "threshold_snapshot" not in doc

    def test_persist_with_threshold_snapshot(self, mongo_db):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        snapshot = {"metric": "error_rate_pct", "value": 5, "actual": 12.3}
        with patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}):
            self._dispatch(mongo_db, "thresh_persist", "Rate spike", "High errors", threshold_snapshot=snapshot)

        doc = _run(mongo_db.alerts.find_one({"type": "thresh_persist"}))
        assert doc is not None
        assert doc["threshold_snapshot"] == snapshot
        assert doc["threshold_snapshot"]["metric"] == "error_rate_pct"
        assert isinstance(doc["threshold_snapshot"]["value"], (int, float))
        assert isinstance(doc["threshold_snapshot"]["actual"], (int, float))

    def test_email_dispatch_persists_to_mongo(self, mongo_db):
        _metrics_mod._notification_channels["email"] = "admin@example.com"
        mock_resend = MagicMock()
        mock_resend.Emails.send = MagicMock()
        snapshot = {"metric": "latency_p95_ms", "value": 3000, "actual": 5500}
        with patch.dict(os.environ, {"RESEND_API_KEY": "re_test_key"}):
            self._dispatch(
                mongo_db, "email_persist", "Latency spike", "p95 is high",
                threshold_snapshot=snapshot,
                extra_patches=[patch.dict("sys.modules", {"resend": mock_resend})],
            )

        mock_resend.Emails.send.assert_called_once()

        doc = _run(mongo_db.alerts.find_one({"type": "email_persist"}))
        assert doc is not None
        assert doc["title"] == "Latency spike"
        assert doc["threshold_snapshot"]["metric"] == "latency_p95_ms"
        assert doc["threshold_snapshot"]["actual"] == 5500
        assert doc["acknowledged"] is False

    def test_webhook_dispatch_persists_to_mongo(self, mongo_db):
        _metrics_mod._notification_channels["webhook_url"] = "https://hooks.test/dispatch"
        _metrics_mod._notification_channels["email"] = ""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        snapshot = {"metric": "spoof_rpm", "value": 50, "actual": 120}
        with patch.dict(os.environ, {"RESEND_API_KEY": ""}):
            self._dispatch(
                mongo_db, "webhook_persist", "Spoof surge", "High spoof rate",
                threshold_snapshot=snapshot,
                extra_patches=[patch("httpx.AsyncClient", return_value=mock_client)],
            )

        mock_client.post.assert_awaited_once()

        doc = _run(mongo_db.alerts.find_one({"type": "webhook_persist"}))
        assert doc is not None
        assert doc["title"] == "Spoof surge"
        assert doc["threshold_snapshot"] == snapshot
        assert doc["acknowledged"] is False
        assert "fired_at" in doc

    def test_cooldown_prevents_second_persist(self, mongo_db):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        with patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}):
            self._dispatch(mongo_db, "cooldown_mongo", "First", "Body 1")
            self._dispatch(mongo_db, "cooldown_mongo", "Second", "Body 2")

        count = _run(mongo_db.alerts.count_documents({"type": "cooldown_mongo"}))
        assert count == 1
        doc = _run(mongo_db.alerts.find_one({"type": "cooldown_mongo"}))
        assert doc["title"] == "First"

    def test_multiple_alert_types_stored_independently(self, mongo_db):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        with patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}):
            self._dispatch(mongo_db, "type_a", "Alert A", "Body A")
            self._dispatch(mongo_db, "type_b", "Alert B", "Body B")

        count = _run(mongo_db.alerts.count_documents({}))
        assert count == 2
        doc_a = _run(mongo_db.alerts.find_one({"type": "type_a"}))
        doc_b = _run(mongo_db.alerts.find_one({"type": "type_b"}))
        assert doc_a["title"] == "Alert A"
        assert doc_b["title"] == "Alert B"


class TestPushNotificationThresholdContext:
    def test_push_body_includes_threshold_when_snapshot_present(self):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        snapshot = {"metric": "error_rate_pct", "value": 5, "actual": 12.3}
        with patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock) as mock_push:
            _run(_metrics_mod._dispatch_alert("push_thresh", "Rate spike", "High errors", threshold_snapshot=snapshot))
        mock_push.assert_called_once()
        payload = mock_push.call_args[0][0]
        assert "error_rate_pct" in payload["body"]
        assert "12.3" in payload["body"]
        assert "5" in payload["body"]
        assert "High errors" in payload["body"]

    def test_push_body_plain_when_no_snapshot(self):
        _metrics_mod._notification_channels["email"] = ""
        _metrics_mod._notification_channels["webhook_url"] = ""
        mock_alerts = MagicMock()
        mock_alerts.insert_one = AsyncMock(return_value=None)
        with patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "", "RESEND_API_KEY": ""}), \
             patch.object(_metrics_mod, "db", MagicMock(alerts=mock_alerts)), \
             patch("routes.admin_notifications._dispatch_push_to_admins", new_callable=AsyncMock) as mock_push:
            _run(_metrics_mod._dispatch_alert("push_plain", "Title", "Plain body"))
        mock_push.assert_called_once()
        payload = mock_push.call_args[0][0]
        assert payload["body"] == "Plain body"


class TestCollectionSizeSnapshot:

    def test_snapshot_records_to_db(self):
        from routes.admin_advanced import _record_collection_size_snapshot
        mock_col = MagicMock()
        mock_col.count_documents = AsyncMock(return_value=42000)
        mock_history = MagicMock()
        mock_history.update_one = AsyncMock(return_value=None)
        mock_db = MagicMock(bot_spoof_attempts=mock_col, collection_size_history=mock_history)
        import routes.admin_advanced as _adv_mod
        with patch.object(_adv_mod, "db", mock_db):
            _run(_record_collection_size_snapshot())
        mock_history.update_one.assert_called_once()
        call_args = mock_history.update_one.call_args
        assert call_args[0][0]["collection"] == "bot_spoof_attempts"
        assert call_args[0][1]["$set"]["size"] == 42000
        assert call_args[1].get("upsert") is True

    def test_snapshot_is_idempotent_same_day(self):
        from routes.admin_advanced import _record_collection_size_snapshot
        mock_col = MagicMock()
        mock_col.count_documents = AsyncMock(return_value=100)
        mock_history = MagicMock()
        mock_history.update_one = AsyncMock(return_value=None)
        mock_db = MagicMock(bot_spoof_attempts=mock_col, collection_size_history=mock_history)
        import routes.admin_advanced as _adv_mod
        with patch.object(_adv_mod, "db", mock_db):
            _run(_record_collection_size_snapshot())
            _run(_record_collection_size_snapshot())
        assert mock_history.update_one.call_count == 2
        d1 = mock_history.update_one.call_args_list[0][0][0]["date"]
        d2 = mock_history.update_one.call_args_list[1][0][0]["date"]
        assert d1 == d2
