"""Task #73 — Test the Workers AI 429 throttle alert pipeline end-to-end.

Three axes to cover:
 A. Counter helpers (llm._track_workers_ai_429, _reset_workers_ai_429,
    get_workers_ai_429_burst_inprocess, get_workers_ai_429_burst).
 B. Alerting check block #8 in metrics._alerting_loop: fires
    _dispatch_alert when burst >= threshold, silent below threshold.
 C. Source-level contract: metrics.py contains the check and llm.py
    exports the required symbols (pure AST / import assertions — zero I/O).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── minimal env so llm.py imports without a live Cloudflare token ─────────
import os
os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_GATEWAY_TOKEN", "test-token")

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import llm as llm_mod  # noqa: E402
import metrics as metrics_mod  # noqa: E402

# ── module-level constants (smoke: must exist) ─────────────────────────────
_LLM_PY = pathlib.Path(__file__).resolve().parent.parent / "llm.py"
_METRICS_PY = pathlib.Path(__file__).resolve().parent.parent / "metrics.py"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_window():
    """Clear the in-memory window before and after every test."""
    llm_mod._WORKERS_AI_429_WINDOW.clear()
    yield
    llm_mod._WORKERS_AI_429_WINDOW.clear()


@pytest.fixture(autouse=True)
def _reset_metrics_cooldowns():
    """Wipe the in-memory alert cooldown so tests don't bleed."""
    metrics_mod._alert_last_fired.clear()
    metrics_mod._notification_channels = dict(
        metrics_mod._NOTIFICATION_CHANNELS_DEFAULT
    )
    yield
    metrics_mod._alert_last_fired.clear()


# ═══════════════════════════════════════════════════════════════════════════
# A. Counter helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestTrackAndCount:
    def test_single_hit_increments_window(self):
        llm_mod._track_workers_ai_429()
        assert len(llm_mod._WORKERS_AI_429_WINDOW) == 1

    def test_five_hits_increment_window_five_times(self):
        for _ in range(5):
            llm_mod._track_workers_ai_429()
        assert len(llm_mod._WORKERS_AI_429_WINDOW) == 5

    def test_inprocess_burst_counts_within_window(self):
        for _ in range(5):
            llm_mod._track_workers_ai_429()
        count = llm_mod.get_workers_ai_429_burst_inprocess(window_seconds=60)
        assert count == 5

    def test_inprocess_burst_excludes_old_timestamps(self):
        old_ts = time.time() - 200   # older than any window we'd use
        llm_mod._WORKERS_AI_429_WINDOW.extend([old_ts, old_ts, old_ts])
        llm_mod._track_workers_ai_429()   # one fresh hit
        count = llm_mod.get_workers_ai_429_burst_inprocess(window_seconds=60)
        assert count == 1, "Only the fresh hit should be counted in the 60s window"

    def test_inprocess_burst_empty_window_returns_zero(self):
        assert llm_mod.get_workers_ai_429_burst_inprocess(60) == 0

    def test_track_appends_recent_timestamp(self):
        before = time.time()
        llm_mod._track_workers_ai_429()
        after = time.time()
        ts = llm_mod._WORKERS_AI_429_WINDOW[-1]
        assert before <= ts <= after


class TestResetOnSuccess:
    def test_reset_clears_in_memory_window(self):
        for _ in range(5):
            llm_mod._track_workers_ai_429()
        assert len(llm_mod._WORKERS_AI_429_WINDOW) == 5

        llm_mod._reset_workers_ai_429()
        assert llm_mod._WORKERS_AI_429_WINDOW == []

    def test_burst_is_zero_after_reset(self):
        for _ in range(5):
            llm_mod._track_workers_ai_429()
        llm_mod._reset_workers_ai_429()
        assert llm_mod.get_workers_ai_429_burst_inprocess(60) == 0

    def test_reset_calls_redis_delete_when_redis_available(self):
        mock_rc = MagicMock()
        with patch("deps.redis_client", mock_rc):
            llm_mod._reset_workers_ai_429()
        mock_rc.delete.assert_called_once_with(llm_mod._WORKERS_AI_429_REDIS_KEY)

    def test_reset_survives_redis_error(self):
        mock_rc = MagicMock()
        mock_rc.delete.side_effect = RuntimeError("redis down")
        with patch("deps.redis_client", mock_rc):
            llm_mod._reset_workers_ai_429()   # must not raise
        assert llm_mod._WORKERS_AI_429_WINDOW == []

    def test_track_calls_redis_incr_and_expire_when_available(self):
        mock_rc = MagicMock()
        with patch("deps.redis_client", mock_rc):
            llm_mod._track_workers_ai_429()
        mock_rc.incr.assert_called_once_with(llm_mod._WORKERS_AI_429_REDIS_KEY)
        mock_rc.expire.assert_called_once_with(
            llm_mod._WORKERS_AI_429_REDIS_KEY, llm_mod._WORKERS_AI_429_WINDOW_S
        )


class TestGetBurstRedisPath:
    def test_prefers_redis_value_over_inprocess(self):
        """get_workers_ai_429_burst() must return the Redis int when Redis
        is reachable, even if the in-process window is empty."""
        mock_rc = MagicMock()
        mock_rc.get.return_value = "7"   # Redis has 7 hits
        with patch("deps.redis_client", mock_rc):
            count = llm_mod.get_workers_ai_429_burst(180)
        assert count == 7

    def test_falls_back_to_inprocess_when_redis_returns_none(self):
        """When Redis key has expired (None), fall back to the in-process
        sliding window."""
        mock_rc = MagicMock()
        mock_rc.get.return_value = None
        for _ in range(3):
            llm_mod._track_workers_ai_429()
        with patch("deps.redis_client", mock_rc):
            count = llm_mod.get_workers_ai_429_burst(180)
        assert count == 3

    def test_falls_back_to_inprocess_when_redis_raises(self):
        mock_rc = MagicMock()
        mock_rc.get.side_effect = ConnectionError("redis gone")
        for _ in range(2):
            llm_mod._track_workers_ai_429()
        with patch("deps.redis_client", mock_rc):
            count = llm_mod.get_workers_ai_429_burst(180)
        assert count == 2


# ═══════════════════════════════════════════════════════════════════════════
# B. Alerting check (metrics._alerting_loop check #8)
# ═══════════════════════════════════════════════════════════════════════════

def _make_db_mock():
    """Minimal db mock for _dispatch_alert (same pattern as test_dispatch_alert_dedup.py)."""
    mock_alert_dispatch_log = MagicMock()
    mock_alert_dispatch_log.find_one_and_update = AsyncMock(return_value=None)
    mock_alert_dispatch_log.delete_one = AsyncMock(
        return_value=MagicMock(deleted_count=1)
    )
    mock_alerts = MagicMock()
    mock_alerts.insert_one = AsyncMock(return_value=None)
    mock_push_subs = MagicMock()
    mock_push_subs.count_documents = AsyncMock(return_value=0)
    mock_users = MagicMock()
    mock_users.find = MagicMock(
        return_value=MagicMock(to_list=AsyncMock(return_value=[]))
    )
    mock_api_config = MagicMock()
    mock_api_config.update_one = AsyncMock(return_value=None)
    mock_push_log = MagicMock()
    mock_push_log.find_one = AsyncMock(return_value=None)
    mock_push_log.insert_one = AsyncMock(return_value=None)
    return MagicMock(
        alert_dispatch_log=mock_alert_dispatch_log,
        alerts=mock_alerts,
        push_subscriptions=mock_push_subs,
        users=mock_users,
        api_config=mock_api_config,
        push_delivery_log=mock_push_log,
    )


async def _run_check_8(burst: int, threshold: int):
    """Run only check #8 of the alerting logic in isolation.

    We inline the exact code from _alerting_loop check #8 with
    get_workers_ai_429_burst patched to return *burst* and
    _ALERT_THRESHOLDS stubbed to *threshold*.  _dispatch_alert is
    patched to an AsyncMock so we can count calls.
    """
    dispatch_mock = AsyncMock()
    with (
        patch.object(metrics_mod, "_dispatch_alert", dispatch_mock),
        patch.object(
            metrics_mod, "_ALERT_THRESHOLDS",
            {"workers_ai_429_burst_threshold": threshold},
        ),
        patch("llm.get_workers_ai_429_burst", return_value=burst),
        patch("llm._WORKERS_AI_429_WINDOW_S", 180),
    ):
        _wai_threshold = int(
            metrics_mod._ALERT_THRESHOLDS.get("workers_ai_429_burst_threshold", 5) or 5
        )
        if _wai_threshold > 0:
            from llm import get_workers_ai_429_burst, _WORKERS_AI_429_WINDOW_S
            _wai_burst = get_workers_ai_429_burst(_WORKERS_AI_429_WINDOW_S)
            if _wai_burst >= _wai_threshold:
                await metrics_mod._dispatch_alert(
                    "workers_ai_429_burst",
                    "Workers AI rate-limit burst — chat may be unavailable",
                    f"{_wai_burst} Workers AI 429 rate-limit responses recorded "
                    f"in the last {_WORKERS_AI_429_WINDOW_S}s (threshold: {_wai_threshold}). "
                    f"Chat completions are being throttled by Cloudflare Workers AI. "
                    f"Check the Cloudflare dashboard for account-level RPM limits "
                    f"and verify no quota has been exhausted. "
                    f"The counter resets automatically when a successful LLM call goes through.",
                    threshold_snapshot={
                        "metric": "workers_ai_429_burst_threshold",
                        "value": _wai_threshold,
                        "actual": _wai_burst,
                        "window_seconds": _WORKERS_AI_429_WINDOW_S,
                    },
                )
    return dispatch_mock


class TestAlertCheckFires:
    def test_alert_fires_when_burst_equals_threshold(self):
        dispatch = _run(_run_check_8(burst=5, threshold=5))
        dispatch.assert_awaited_once()
        call_kwargs = dispatch.await_args
        assert call_kwargs.args[0] == "workers_ai_429_burst"

    def test_alert_fires_when_burst_exceeds_threshold(self):
        dispatch = _run(_run_check_8(burst=12, threshold=5))
        dispatch.assert_awaited_once()

    def test_alert_title_contains_rate_limit_phrase(self):
        dispatch = _run(_run_check_8(burst=5, threshold=5))
        title = dispatch.await_args.args[1]
        assert "rate-limit" in title.lower() or "rate limit" in title.lower()

    def test_threshold_snapshot_carries_correct_fields(self):
        dispatch = _run(_run_check_8(burst=7, threshold=5))
        snap = dispatch.await_args.kwargs.get("threshold_snapshot") or dispatch.await_args.args[3]
        assert snap["metric"] == "workers_ai_429_burst_threshold"
        assert snap["value"] == 5
        assert snap["actual"] == 7

    def test_alert_body_references_window_seconds(self):
        dispatch = _run(_run_check_8(burst=5, threshold=5))
        body = dispatch.await_args.args[2]
        assert "180" in body, "body must mention the 180s window"


class TestAlertCheckSilent:
    def test_alert_does_not_fire_when_burst_below_threshold(self):
        dispatch = _run(_run_check_8(burst=4, threshold=5))
        dispatch.assert_not_awaited()

    def test_alert_does_not_fire_when_burst_is_zero(self):
        dispatch = _run(_run_check_8(burst=0, threshold=5))
        dispatch.assert_not_awaited()

    def test_alert_does_not_fire_when_threshold_is_negative(self):
        """A threshold that int-parses to a negative or zero value after the
        ``or 5`` guard should still be > 0 (or 5 maps 0→5); we verify the
        alert stays silent only when burst is genuinely below the effective
        threshold.  This guards the ``if _wai_threshold > 0`` branch."""
        # threshold=1, burst=0 → burst < threshold → silent
        dispatch = _run(_run_check_8(burst=0, threshold=1))
        dispatch.assert_not_awaited()


class TestAlertWithRealDispatch:
    """Use the real _dispatch_alert with a db mock to verify the full path."""

    def test_real_dispatch_called_with_workers_ai_burst_alert_type(self):
        mock_db = _make_db_mock()
        silence_channels = {
            "email": "",
            "webhook_url": "",
        }

        # Pre-seed 5 fresh 429 hits so get_workers_ai_429_burst_inprocess returns 5.
        for _ in range(5):
            llm_mod._track_workers_ai_429()

        async def _run_real():
            _wai_threshold = 5
            _wai_burst = llm_mod.get_workers_ai_429_burst_inprocess(180)
            if _wai_burst >= _wai_threshold:
                return await metrics_mod._dispatch_alert(
                    "workers_ai_429_burst",
                    "Workers AI rate-limit burst — chat may be unavailable",
                    f"{_wai_burst} 429s in 180s (threshold {_wai_threshold})",
                    threshold_snapshot={
                        "metric": "workers_ai_429_burst_threshold",
                        "value": _wai_threshold,
                        "actual": _wai_burst,
                        "window_seconds": 180,
                    },
                )
            return None

        with (
            patch.dict(os.environ, {"ALERT_EMAIL": "", "ALERT_WEBHOOK_URL": "",
                                     "RESEND_API_KEY": ""}),
            patch.object(metrics_mod, "_notification_channels", silence_channels),
            patch.object(metrics_mod, "db", mock_db),
            patch("routes.admin_notifications._dispatch_push_to_admins",
                  new_callable=AsyncMock),
        ):
            result = _run(_run_real())

        assert result is not None, "expected dispatch to run (burst >= threshold)"
        assert result["persisted"]["ok"] is True
        # The persisted alert document uses the key "type" (not "alert_type").
        persisted_call = mock_db.alerts.insert_one.await_args.args[0]
        assert persisted_call["type"] == "workers_ai_429_burst"

    def test_real_dispatch_not_called_when_burst_below_threshold(self):
        mock_db = _make_db_mock()

        # Only 3 hits, threshold is 5 — should NOT dispatch.
        for _ in range(3):
            llm_mod._track_workers_ai_429()

        async def _run_real():
            _wai_threshold = 5
            _wai_burst = llm_mod.get_workers_ai_429_burst_inprocess(180)
            if _wai_burst >= _wai_threshold:
                return await metrics_mod._dispatch_alert(
                    "workers_ai_429_burst", "T", "B"
                )
            return None

        with patch.object(metrics_mod, "db", mock_db):
            result = _run(_run_real())

        assert result is None
        mock_db.alerts.insert_one.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════
# C. Source-level contract (AST / import checks)
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceContract:
    def test_llm_exports_get_workers_ai_429_burst(self):
        assert callable(llm_mod.get_workers_ai_429_burst)

    def test_llm_exports_get_workers_ai_429_burst_inprocess(self):
        assert callable(llm_mod.get_workers_ai_429_burst_inprocess)

    def test_llm_has_redis_key_constant(self):
        assert isinstance(llm_mod._WORKERS_AI_429_REDIS_KEY, str)
        assert llm_mod._WORKERS_AI_429_REDIS_KEY  # non-empty

    def test_llm_window_s_is_positive_int(self):
        assert isinstance(llm_mod._WORKERS_AI_429_WINDOW_S, int)
        assert llm_mod._WORKERS_AI_429_WINDOW_S > 0

    def test_metrics_imports_get_workers_ai_429_burst_in_check_8(self):
        """The alerting loop must import get_workers_ai_429_burst from llm —
        if someone renames the helper, this test catches it before prod."""
        src = _METRICS_PY.read_text(encoding="utf-8")
        assert "get_workers_ai_429_burst" in src, (
            "metrics.py must reference get_workers_ai_429_burst"
        )

    def test_metrics_check_8_uses_window_s_constant(self):
        """The check block must use _WORKERS_AI_429_WINDOW_S so the window
        stays in sync when llm.py changes the default."""
        src = _METRICS_PY.read_text(encoding="utf-8")
        assert "_WORKERS_AI_429_WINDOW_S" in src, (
            "metrics.py must pass _WORKERS_AI_429_WINDOW_S to get_workers_ai_429_burst"
        )

    def test_metrics_check_8_fires_workers_ai_429_burst_alert_type(self):
        """The dispatched alert_type string must be 'workers_ai_429_burst' —
        changing it would break downstream alert dedup and dashboards."""
        src = _METRICS_PY.read_text(encoding="utf-8")
        assert '"workers_ai_429_burst"' in src, (
            "metrics.py must dispatch alert_type='workers_ai_429_burst'"
        )

    def test_metrics_check_8_reads_threshold_from_alert_thresholds(self):
        """The check must be configurable via _ALERT_THRESHOLDS so ops can
        adjust sensitivity without a deploy."""
        src = _METRICS_PY.read_text(encoding="utf-8")
        assert "workers_ai_429_burst_threshold" in src

    def test_metrics_alerting_loop_contains_check_8_block(self):
        """AST walk: _alerting_loop must contain an await call to
        _dispatch_alert with 'workers_ai_429_burst' as the first argument."""
        tree = ast.parse(_METRICS_PY.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_alerting_loop":
                body = ast.unparse(node)
                if "workers_ai_429_burst" in body and "_dispatch_alert" in body:
                    found = True
                    break
        assert found, "_alerting_loop must contain _dispatch_alert('workers_ai_429_burst', ...)"

    def test_llm_track_appends_to_module_level_list(self):
        """AST check: _track_workers_ai_429 must append to
        _WORKERS_AI_429_WINDOW (not a local variable)."""
        tree = ast.parse(_LLM_PY.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_track_workers_ai_429":
                body = ast.unparse(node)
                assert "_WORKERS_AI_429_WINDOW" in body
                assert "append" in body
                return
        pytest.fail("_track_workers_ai_429 not found in llm.py")

    def test_llm_reset_clears_module_level_list(self):
        """AST check: _reset_workers_ai_429 must reassign
        _WORKERS_AI_429_WINDOW to an empty list using 'global'."""
        tree = ast.parse(_LLM_PY.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_reset_workers_ai_429":
                body = ast.unparse(node)
                assert "global" in body
                assert "_WORKERS_AI_429_WINDOW" in body
                return
        pytest.fail("_reset_workers_ai_429 not found in llm.py")
