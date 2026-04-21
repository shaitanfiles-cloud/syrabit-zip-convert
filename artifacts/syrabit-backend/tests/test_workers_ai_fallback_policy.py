"""Tests for Workers AI fallback policy (Task #636).

The policy module is the gatekeeper that decides whether a primary
provider failure should fan out to Cloudflare Workers AI or surface
straight to the caller. Getting this wrong silently masks real bugs
(if we fall back on 4xx) or burns availability budget on transient
issues (if we don't fall back on 429/5xx) — so the rules are tested
exhaustively rather than relying on integration testing alone.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

# Ensure the secret is set so is_enabled() returns True for the
# capability-toggle tests. The actual edge URL is never reached because
# the runner is fully mocked.
os.environ.setdefault("WORKERS_AI_FALLBACK_SECRET", "test-secret")
os.environ.setdefault("WORKERS_AI_FALLBACK_ENABLED", "1")

from providers import workers_ai as wai  # noqa: E402


# ─── should_fallback() truth table ────────────────────────────────────────
@pytest.mark.parametrize("err", [
    asyncio.TimeoutError(),
    TimeoutError("upstream"),
    httpx.ConnectError("network down"),
    httpx.ReadTimeout("slow"),
])
def test_retryable_errors_trigger_fallback(err):
    assert wai.should_fallback(err) is True


def _fake_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://x.test")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"http {code}", request=req, response=resp)


@pytest.mark.parametrize("code", [500, 502, 503, 504, 429, 408])
def test_retryable_status_codes_trigger_fallback(code):
    assert wai.should_fallback(_fake_status_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_bad_input_4xx_never_triggers_fallback(code):
    """Most-important property: a 4xx (except 429) is the same bad input
    regardless of provider. Falling back hides the bug."""
    assert wai.should_fallback(_fake_status_error(code)) is False


def test_cancelled_error_does_not_trigger_fallback():
    assert wai.should_fallback(asyncio.CancelledError()) is False


def test_unknown_exception_is_conservative():
    """An unrecognised exception class is NOT retried. We'd rather
    surface a 503 than burn the fallback quota on a permanent failure
    we don't understand yet."""
    class WeirdException(Exception):
        pass
    assert wai.should_fallback(WeirdException("???")) is False


def test_quota_keyword_is_treated_as_retryable():
    class ResourceQuotaExceeded(Exception):
        pass
    assert wai.should_fallback(ResourceQuotaExceeded("limit")) is True


# ─── classify_primary_error() ─────────────────────────────────────────────
def test_classify_timeout():
    assert wai.classify_primary_error(asyncio.TimeoutError()) == "timeout"
    assert wai.classify_primary_error(httpx.ReadTimeout("slow")) == "timeout"


def test_classify_status():
    assert wai.classify_primary_error(_fake_status_error(503)) == "http_503"


def test_classify_network():
    assert wai.classify_primary_error(httpx.ConnectError("x")) == "network"


# ─── kill switch ──────────────────────────────────────────────────────────
def test_kill_switch_blocks_capability(monkeypatch):
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "1")
    monkeypatch.setenv("WORKERS_AI_FALLBACK_SECRET", "test-secret")
    wai.set_enabled("chat", False)
    try:
        assert wai.is_enabled("chat") is False
        # Other capabilities unaffected.
        assert wai.is_enabled("embed") is True
    finally:
        wai.set_enabled("chat", True)


def test_global_disable_blocks_everything(monkeypatch):
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "0")
    assert wai.is_enabled("chat") is False
    assert wai.is_enabled("tts") is False


def test_missing_secret_blocks_everything(monkeypatch):
    monkeypatch.delenv("WORKERS_AI_FALLBACK_SECRET", raising=False)
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "1")
    assert wai.is_enabled("chat") is False


# ─── attempt_fallback() integration with the runner ───────────────────────
# Tests are sync and drive the coroutine via asyncio.run() so we don't
# depend on pytest-asyncio being installed in the env.
def test_attempt_fallback_skips_on_non_retryable(monkeypatch):
    monkeypatch.setenv("WORKERS_AI_FALLBACK_SECRET", "test-secret")
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "1")
    runner = MagicMock()
    err = _fake_status_error(400)
    ok, val, label = asyncio.run(wai.attempt_fallback("chat", err, 50, runner))
    assert ok is False and val is None and label == ""
    runner.assert_not_called()  # The whole point — we did not burn quota.


def test_attempt_fallback_records_success(monkeypatch):
    monkeypatch.setenv("WORKERS_AI_FALLBACK_SECRET", "test-secret")
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "1")
    wai.set_enabled("chat", True)

    async def runner():
        return "fallback-answer"

    err = _fake_status_error(503)
    ok, val, label = asyncio.run(wai.attempt_fallback("chat", err, 100, runner))
    assert ok is True
    assert val == "fallback-answer"
    assert label == "workers-ai"
    snap = wai.snapshot()["capabilities"]["chat"]
    assert snap["last_outcome"] == "ok"
    assert snap["successes_24h"] >= 1


def test_attempt_fallback_records_failure(monkeypatch):
    monkeypatch.setenv("WORKERS_AI_FALLBACK_SECRET", "test-secret")
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "1")
    wai.set_enabled("embed", True)

    async def runner():
        raise RuntimeError("workers ai exploded")

    err = _fake_status_error(500)
    ok, val, label = asyncio.run(wai.attempt_fallback("embed", err, 200, runner))
    assert ok is False
    assert val is None
    assert label == ""
    snap = wai.snapshot()["capabilities"]["embed"]
    assert snap["last_outcome"] == "error"
    assert snap["failures_24h"] >= 1
