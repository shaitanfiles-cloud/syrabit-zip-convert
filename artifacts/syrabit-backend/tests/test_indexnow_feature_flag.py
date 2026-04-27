"""Task #986 — IndexNow feature flag (`INDEXNOW_ENABLED`).

When the flag is off (e.g. dev/preview environments where outbound to
api.indexnow.org / www.bing.com/indexnow / yandex.com/indexnow is
blocked), `push_indexnow` must:
  * not touch the network,
  * not mutate `_EndpointHealth` (so admin "Last success" doesn't lie),
  * return `{}` so `IndexNowBatcher._do_push` does not queue retries.

The endpoint-down alert loop must also skip a pass entirely when the
flag is off, so we never emit "endpoint_down / Last success: never"
alerts in environments that legitimately can't reach those endpoints.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reset_health_state(bd):
    bd._endpoint_health.clear()
    bd._INDEXNOW_DISABLED_LOG_ONCE = False


def test_push_indexnow_short_circuits_when_disabled(monkeypatch):
    from routes import bot_discovery as bd

    _reset_health_state(bd)
    monkeypatch.setenv("INDEXNOW_ENABLED", "0")

    sentinel_post = AsyncMock()
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = sentinel_post

    with patch("httpx.AsyncClient", return_value=fake_client):
        result = _run(bd.push_indexnow(["https://syrabit.ai/foo"], source="unit_test"))

    assert result == {}, "disabled push must return empty dict, not False per endpoint"
    sentinel_post.assert_not_called()
    for ep in bd.INDEXNOW_ENDPOINTS:
        h = bd._get_health(ep)
        assert h.last_success_time is None
        assert h.last_failure_time is None
        assert h.consecutive_failures == 0
        assert h.total_failures == 0
        assert h.total_successes == 0


def test_push_indexnow_runs_normally_when_enabled(monkeypatch):
    from routes import bot_discovery as bd

    _reset_health_state(bd)
    monkeypatch.setenv("INDEXNOW_ENABLED", "1")

    fake_resp = MagicMock(status_code=200)
    sentinel_post = AsyncMock(return_value=fake_resp)
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = sentinel_post

    with patch("httpx.AsyncClient", return_value=fake_client):
        result = _run(bd.push_indexnow(["https://syrabit.ai/foo"], source="unit_test"))

    assert sentinel_post.await_count == len(bd.INDEXNOW_ENDPOINTS)
    assert all(result.get(ep) for ep in bd.INDEXNOW_ENDPOINTS)
    for ep in bd.INDEXNOW_ENDPOINTS:
        h = bd._get_health(ep)
        assert h.last_success_time is not None, f"{ep} should have recorded success"
        assert h.total_successes == 1


def test_alert_loop_skips_when_disabled(monkeypatch):
    """When the flag is off the alert loop must not iterate / dispatch — even
    if a stale dead-lettered health record exists in memory."""
    from routes import bot_discovery as bd

    _reset_health_state(bd)
    monkeypatch.setenv("INDEXNOW_ENABLED", "0")

    ep = "https://api.indexnow.org/indexnow"
    h = bd._get_health(ep)
    h.consecutive_failures = bd._DEAD_LETTER_THRESHOLD
    h.last_failure_time = 1.0  # ancient (1970) → would normally trip the threshold
    h.last_success_time = None

    dispatch = AsyncMock()
    sleep_calls: list[float] = []
    cancel_after = {"n": 0}

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)
        cancel_after["n"] += 1
        if cancel_after["n"] >= 2:
            raise asyncio.CancelledError()

    fake_metrics = MagicMock()
    fake_metrics._dispatch_alert = dispatch
    fake_metrics._alert_last_fired = {}
    fake_metrics._ALERT_THRESHOLDS = {
        "endpoint_down_minutes": 60, "endpoint_down_check_minutes": 15,
    }

    with patch("asyncio.sleep", side_effect=fake_sleep), \
         patch.dict("sys.modules", {"metrics": fake_metrics}):
        try:
            _run(bd._endpoint_health_alert_loop())
        except asyncio.CancelledError:
            pass

    dispatch.assert_not_called()


def test_alert_loop_dispatches_when_enabled(monkeypatch):
    """Sanity check: with the flag on, the same stale dead-lettered state
    *does* fire an endpoint_down alert — so the disabled-skip really is the
    differentiator."""
    from routes import bot_discovery as bd

    _reset_health_state(bd)
    monkeypatch.setenv("INDEXNOW_ENABLED", "1")
    bd._endpoint_alert_last_fired.clear()

    ep = "https://api.indexnow.org/indexnow"
    h = bd._get_health(ep)
    h.consecutive_failures = bd._DEAD_LETTER_THRESHOLD
    h.last_failure_time = 1.0
    h.last_success_time = None

    dispatch = AsyncMock()
    cancel_after = {"n": 0}

    async def fake_sleep(seconds: float):
        cancel_after["n"] += 1
        if cancel_after["n"] >= 2:
            raise asyncio.CancelledError()

    fake_metrics = MagicMock()
    fake_metrics._dispatch_alert = dispatch
    fake_metrics._alert_last_fired = {}
    fake_metrics._ALERT_THRESHOLDS = {
        "endpoint_down_minutes": 60, "endpoint_down_check_minutes": 15,
    }

    with patch("asyncio.sleep", side_effect=fake_sleep), \
         patch.dict("sys.modules", {"metrics": fake_metrics}):
        try:
            _run(bd._endpoint_health_alert_loop())
        except asyncio.CancelledError:
            pass

    assert dispatch.await_count >= 1
    args, kwargs = dispatch.await_args
    assert args[0] == "endpoint_down"
    assert ep in args[2]
    assert "Last success: never" in args[2]


def test_to_dict_surfaces_enabled_flag(monkeypatch):
    from routes import bot_discovery as bd
    _reset_health_state(bd)

    monkeypatch.setenv("INDEXNOW_ENABLED", "0")
    info_off = bd._get_health("https://api.indexnow.org/indexnow").to_dict()
    assert info_off["enabled"] is False
    assert "last_success_time" in info_off
    assert "last_failure_time" in info_off

    monkeypatch.setenv("INDEXNOW_ENABLED", "1")
    info_on = bd._get_health("https://api.indexnow.org/indexnow").to_dict()
    assert info_on["enabled"] is True
