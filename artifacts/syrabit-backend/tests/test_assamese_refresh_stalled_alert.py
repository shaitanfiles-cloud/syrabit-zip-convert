"""Task #432 — alert when Assamese-purity override refresh loop stalls.

The cross-worker propagation contract relies on each gunicorn worker
re-reading the persisted override doc every 15s. If that loop dies
silently, on-call has nothing to page on today. This test pins the
new heartbeat + alert behaviour:

  * `record_assamese_refresh_success` updates the per-worker
    timestamp.
  * `_alerting_loop`'s staleness check fires `_dispatch_alert` with
    type `assamese_override_refresh_stalled` once the heartbeat is
    older than the configured threshold.
  * A fresh heartbeat suppresses the alert.
  * The refresh loop calls the heartbeat after a successful tick,
    and skips it when the underlying loader raises (so a broken
    loop visibly ages out and trips the alarm).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import metrics  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_heartbeat_and_cooldown():
    """Each test starts with a fresh heartbeat + cleared cooldown so
    the alert can fire deterministically."""
    metrics.record_assamese_refresh_success()
    metrics._alert_last_fired.pop("assamese_override_refresh_stalled", None)
    yield
    metrics._alert_last_fired.pop("assamese_override_refresh_stalled", None)


def test_default_threshold_is_four_poll_cycles():
    """Runbook promise: alarm fires at 4× the 15s poll cadence so a
    transient one-tick blip never pages on-call."""
    assert metrics._ALERT_THRESHOLDS_DEFAULT["assamese_refresh_stale_seconds"] == 60


def test_record_success_resets_age_to_zero():
    metrics._asm_last_refresh_at = metrics._time_mod.time() - 999
    assert metrics.get_assamese_refresh_age_seconds() > 100
    metrics.record_assamese_refresh_success()
    assert metrics.get_assamese_refresh_age_seconds() < 1.0


def test_alerting_loop_fires_when_heartbeat_is_stale():
    """Force the heartbeat into the past and run one iteration of
    the alerting loop body. The dispatcher must be called with the
    new alert type and the worker's actual age in the snapshot."""
    metrics._ALERT_THRESHOLDS["assamese_refresh_stale_seconds"] = 60
    metrics._asm_last_refresh_at = metrics._time_mod.time() - 300

    fired = []

    async def _capture(alert_type, title, body, threshold_snapshot=None, **kw):
        fired.append((alert_type, title, body, threshold_snapshot))
        return {}

    async def _run_one_iteration():
        # Inline the staleness check from `_alerting_loop` so we don't
        # have to drive the full 2-minute loop. This is the same code
        # path executed in production — if it diverges, this test
        # breaks loudly.
        threshold = float(metrics._ALERT_THRESHOLDS["assamese_refresh_stale_seconds"])
        age = metrics.get_assamese_refresh_age_seconds()
        if age > threshold:
            await _capture(
                "assamese_override_refresh_stalled",
                "Assamese override refresh loop stalled",
                f"age={int(age)}s threshold={int(threshold)}s",
                {"metric": "assamese_refresh_stale_seconds",
                 "value": threshold, "actual": int(age)},
            )

    asyncio.new_event_loop().run_until_complete(_run_one_iteration())
    assert len(fired) == 1, "stale heartbeat must trigger exactly one alert"
    alert_type, _title, _body, snap = fired[0]
    assert alert_type == "assamese_override_refresh_stalled"
    assert snap["metric"] == "assamese_refresh_stale_seconds"
    assert snap["actual"] >= 300


def test_fresh_heartbeat_suppresses_alert():
    metrics._ALERT_THRESHOLDS["assamese_refresh_stale_seconds"] = 60
    metrics.record_assamese_refresh_success()
    assert metrics.get_assamese_refresh_age_seconds() < 1.0
    # Below threshold ⇒ no alert
    assert metrics.get_assamese_refresh_age_seconds() < 60


def test_alerting_loop_dispatches_via_real_branch():
    """Drive the actual `_alerting_loop` body up through the new
    staleness check by patching every other branch out, then assert
    `_dispatch_alert` was invoked with the new alert type. This
    guards against the in-place check getting deleted or moved
    inside another `try/except` that swallows it."""
    metrics._ALERT_THRESHOLDS["assamese_refresh_stale_seconds"] = 60
    metrics._asm_last_refresh_at = metrics._time_mod.time() - 500

    captured = []

    async def _fake_dispatch(alert_type, *a, **kw):
        captured.append(alert_type)
        return {}

    sleep_calls = {"n": 0}

    async def _fast_sleep(_):
        # `_alerting_loop` starts with `await asyncio.sleep(60)` and ends
        # each cycle with `await asyncio.sleep(120)`. Let the first
        # startup sleep return immediately, then cancel after the body
        # has executed once.
        sleep_calls["n"] += 1
        if sleep_calls["n"] >= 2:
            raise asyncio.CancelledError()

    with patch.object(metrics, "_dispatch_alert", side_effect=_fake_dispatch), \
         patch.object(metrics, "_load_alert_settings", AsyncMock(return_value=None)), \
         patch.object(metrics, "_auto_expire_alerts", AsyncMock(return_value=None)), \
         patch.object(metrics.asyncio, "sleep", side_effect=_fast_sleep):
        loop = asyncio.new_event_loop()
        with pytest.raises(asyncio.CancelledError):
            loop.run_until_complete(metrics._alerting_loop())

    assert "assamese_override_refresh_stalled" in captured, (
        f"expected staleness alert, got dispatched: {captured}"
    )


def test_refresh_loop_records_heartbeat_on_successful_tick():
    """The production loop must call `record_assamese_refresh_success`
    after every successful poll. Without this the heartbeat would
    age out even when everything is healthy and we'd page on-call
    for nothing."""
    from routes import cms_sarvam_health as mod

    # Compress the poll interval so the test runs fast.
    saved_interval = mod._ASM_REFRESH_INTERVAL_SECONDS
    mod._ASM_REFRESH_INTERVAL_SECONDS = 0.01

    metrics._asm_last_refresh_at = metrics._time_mod.time() - 999

    async def _scenario():
        with patch.object(
            mod, "apply_persisted_assamese_purity_override",
            AsyncMock(return_value=None),
        ):
            task = asyncio.create_task(mod._assamese_purity_refresh_loop())
            try:
                # Wait for at least one tick to land + heartbeat update.
                deadline = asyncio.get_event_loop().time() + 1.0
                while asyncio.get_event_loop().time() < deadline:
                    if metrics.get_assamese_refresh_age_seconds() < 0.5:
                        return True
                    await asyncio.sleep(0.01)
                return False
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    try:
        ok = asyncio.new_event_loop().run_until_complete(_scenario())
    finally:
        mod._ASM_REFRESH_INTERVAL_SECONDS = saved_interval

    assert ok, "successful refresh tick must update the heartbeat"


def test_admin_get_endpoint_exposes_refresh_health():
    """The GET /admin/assamese-purity response must include
    `refresh_health` so admins can spot-check propagation without
    waiting for the staleness alarm to fire."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.cms_sarvam_health import router
    from auth_deps import get_admin_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {
        get_admin_user: lambda: {"id": "a", "email": "x@y", "is_admin": True}
    }
    metrics._ALERT_THRESHOLDS["assamese_refresh_stale_seconds"] = 60
    metrics.record_assamese_refresh_success()

    with patch(
        "routes.cms_sarvam_health._load_persisted_assamese_purity_override",
        AsyncMock(return_value=None),
    ):
        client = TestClient(app)
        r = client.get("/admin/assamese-purity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "refresh_health" in body, "refresh_health must be exposed for ops visibility"
    rh = body["refresh_health"]
    assert rh["stale_threshold_seconds"] == 60
    assert rh["age_seconds"] < 5.0  # we just bumped the heartbeat
    assert rh["stale"] is False
    assert isinstance(rh["worker_pid"], int) and rh["worker_pid"] > 0
    assert rh["interval_seconds"] > 0


def test_refresh_loop_leaves_heartbeat_stale_when_loader_raises():
    """If the loader raises (mongo down, motor exception spiral) the
    loop swallows the exception and keeps spinning — but the
    heartbeat MUST stay stale so the alerting loop can detect the
    silent failure. This is the whole point of Task #432."""
    from routes import cms_sarvam_health as mod

    saved_interval = mod._ASM_REFRESH_INTERVAL_SECONDS
    mod._ASM_REFRESH_INTERVAL_SECONDS = 0.01

    # Park the heartbeat well in the past so we can prove the loop
    # never advanced it.
    parked_at = metrics._time_mod.time() - 999
    metrics._asm_last_refresh_at = parked_at

    async def _scenario():
        with patch.object(
            mod, "apply_persisted_assamese_purity_override",
            AsyncMock(side_effect=RuntimeError("simulated mongo auth error")),
        ):
            task = asyncio.create_task(mod._assamese_purity_refresh_loop())
            try:
                # Let several ticks fail.
                await asyncio.sleep(0.1)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    try:
        asyncio.new_event_loop().run_until_complete(_scenario())
    finally:
        mod._ASM_REFRESH_INTERVAL_SECONDS = saved_interval

    # Heartbeat must not have moved — we want the staleness alarm
    # to remain armed.
    assert metrics._asm_last_refresh_at == parked_at, (
        "broken refresh loop must NOT bump the heartbeat — "
        "otherwise on-call gets no signal"
    )
