"""Task #516 — alert when the Vectorize auth circuit breaker trips.

The breaker in ``vectorize_client`` already short-circuits requests when
CLOUDFLARE_API_TOKEN is invalid, but historically only emitted a single
WARNING line. These tests pin the new behaviour:

  * The first time the breaker trips it dispatches a
    ``vectorize_auth_breaker_tripped`` alert via ``metrics._dispatch_alert``.
  * Subsequent trips inside the 24h debounce window do NOT re-dispatch.
  * The first success after a tripped breaker dispatches a
    ``vectorize_auth_recovered`` alert and clears the debounce so a
    fresh outage pages immediately.
  * The alert body carries the index name, rotation hint, and a Railway
    log pointer so on-call has actionable context without leaving Slack.
"""
from __future__ import annotations

import asyncio

import pytest

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import vectorize_client as vc  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_breaker_state():
    """Each test starts with a clean breaker + debounce so dispatch is
    deterministic regardless of test ordering."""
    vc._auth_fail_count = 0
    vc._auth_breaker_until = 0.0
    vc._auth_breaker_logged = False
    vc._last_trip_alert_at = 0.0
    yield
    vc._auth_fail_count = 0
    vc._auth_breaker_until = 0.0
    vc._auth_breaker_logged = False
    vc._last_trip_alert_at = 0.0


def _drive(coro):
    """Run a coroutine on a fresh event loop so ``asyncio.get_running_loop``
    inside ``_schedule_alert`` actually finds one. We then drain pending
    tasks so the fire-and-forget dispatch coroutine completes before we
    inspect the captured calls."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(coro)
        # Let any tasks scheduled via loop.create_task finish.
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    finally:
        loop.close()


def test_breaker_trip_dispatches_alert(monkeypatch):
    captured = []

    async def _fake_dispatch(alert_type, title, body, **kwargs):
        captured.append({"type": alert_type, "title": title, "body": body, "kwargs": kwargs})
        return {}

    # Patch the lazy-imported symbol by injecting a stub `metrics` module.
    import sys
    import types
    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = _fake_dispatch
    monkeypatch.setitem(sys.modules, "metrics", fake_metrics)

    async def _trip():
        # Three consecutive failures opens the breaker (THRESHOLD=3).
        for _ in range(vc.AUTH_BREAKER_THRESHOLD):
            vc._record_auth_failure()
        # Yield so the scheduled task gets to run.
        await asyncio.sleep(0)

    _drive(_trip())

    assert len(captured) == 1, f"expected exactly one trip alert, got {captured}"
    alert = captured[0]
    assert alert["type"] == "vectorize_auth_breaker_tripped"
    assert vc.VECTORIZE_INDEX_NAME in alert["title"]
    # Body must guide the operator to the actual fix.
    assert "CLOUDFLARE_API_TOKEN" in alert["body"]
    assert "Vectorize:Edit" in alert["body"]
    assert "verify_vectorize_token" in alert["body"]
    assert "Logs:" in alert["body"]
    # We force=True so we don't get swallowed by the global cooldown.
    assert alert["kwargs"].get("force") is True


def test_repeated_trips_within_debounce_window_dispatch_once(monkeypatch):
    captured = []

    async def _fake_dispatch(alert_type, *_a, **_kw):
        captured.append(alert_type)
        return {}

    import sys
    import types
    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = _fake_dispatch
    monkeypatch.setitem(sys.modules, "metrics", fake_metrics)

    async def _trip_twice():
        for _ in range(vc.AUTH_BREAKER_THRESHOLD):
            vc._record_auth_failure()
        await asyncio.sleep(0)
        # Force the breaker to be re-armable (cooldown elapsed) but keep
        # the 24h debounce window in effect — simulating a sustained
        # outage where the breaker reopens every 5 min.
        vc._auth_breaker_until = 0.0
        vc._auth_breaker_logged = False
        for _ in range(vc.AUTH_BREAKER_THRESHOLD):
            vc._record_auth_failure()
        await asyncio.sleep(0)

    _drive(_trip_twice())

    assert captured == ["vectorize_auth_breaker_tripped"], (
        f"sustained outage must not spam channels; got {captured}"
    )


def test_recovery_after_trip_dispatches_recovered_alert(monkeypatch):
    captured = []

    async def _fake_dispatch(alert_type, title, body, **_kw):
        captured.append((alert_type, title, body))
        return {}

    import sys
    import types
    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = _fake_dispatch
    monkeypatch.setitem(sys.modules, "metrics", fake_metrics)

    async def _trip_then_recover():
        for _ in range(vc.AUTH_BREAKER_THRESHOLD):
            vc._record_auth_failure()
        await asyncio.sleep(0)
        # Operator rotated the token, next call succeeds.
        vc._record_success()
        await asyncio.sleep(0)

    _drive(_trip_then_recover())

    types_seen = [c[0] for c in captured]
    assert types_seen == ["vectorize_auth_breaker_tripped", "vectorize_auth_recovered"], (
        f"expected trip then recover, got {types_seen}"
    )
    # Recovery clears the debounce so a fresh outage pages immediately.
    assert vc._last_trip_alert_at == 0.0


def test_success_without_prior_trip_does_not_dispatch(monkeypatch):
    captured = []

    async def _fake_dispatch(alert_type, *_a, **_kw):
        captured.append(alert_type)
        return {}

    import sys
    import types
    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = _fake_dispatch
    monkeypatch.setitem(sys.modules, "metrics", fake_metrics)

    async def _just_succeed():
        vc._record_success()
        await asyncio.sleep(0)

    _drive(_just_succeed())

    assert captured == [], (
        f"healthy heartbeat must not page on-call; got {captured}"
    )


def test_railway_log_hint_uses_explicit_url_when_set(monkeypatch):
    monkeypatch.setenv("RAILWAY_LOGS_URL", "https://railway.app/project/abc/logs?q=vectorize")
    hint = vc._railway_log_hint()
    assert "https://railway.app/project/abc/logs?q=vectorize" in hint


def test_railway_log_hint_falls_back_to_service_metadata(monkeypatch):
    monkeypatch.delenv("RAILWAY_LOGS_URL", raising=False)
    monkeypatch.setenv("RAILWAY_PROJECT_NAME", "syrabit")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "syrabit-backend")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    hint = vc._railway_log_hint()
    assert "syrabit" in hint
    assert "syrabit-backend" in hint
    assert "production" in hint


def test_schedule_alert_outside_event_loop_is_noop(monkeypatch):
    """Calling the breaker helpers from sync code must never crash even
    when no loop is running — we just drop the alert silently and let the
    WARNING log line carry the forensic record."""
    called = {"n": 0}

    async def _fake_dispatch(*_a, **_kw):
        called["n"] += 1

    import sys
    import types
    fake_metrics = types.ModuleType("metrics")
    fake_metrics._dispatch_alert = _fake_dispatch
    monkeypatch.setitem(sys.modules, "metrics", fake_metrics)

    # No running loop here — must not raise.
    vc._schedule_alert("vectorize_auth_breaker_tripped", "x", "y")
    assert called["n"] == 0
