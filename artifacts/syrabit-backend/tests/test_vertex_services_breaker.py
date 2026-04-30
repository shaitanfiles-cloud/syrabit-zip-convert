"""Tests for `vertex_services._record_response` 4xx classification
(Task #831 architect feedback).

The breaker must distinguish "upstream is broken" from "the user's
payload is broken". Critical because:
  - The current Vertex outage manifests as HTTP 400 with a body of
    "API key expired" — that MUST open the breaker (it's an infra
    failure even though the status code is 400).
  - A single user submitting an oversized image must NOT open the
    breaker for everyone else (HTTP 413 / plain 400 from validation).

These tests use a stub Response object to exercise the classifier
without making real HTTP calls.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class _StubResponse:
    """Minimal stand-in for httpx.Response — only `.status_code` and
    `.text` are read by `_record_response`."""

    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


@pytest.fixture(autouse=True)
def _reset_breaker(monkeypatch):
    """Force-close the module-level breaker before/after each test so
    state from one test never leaks into the next."""
    import vertex_services
    vertex_services._breaker.force_close()
    yield
    vertex_services._breaker.force_close()


def _failures(vertex_services) -> int:
    return vertex_services._breaker.snapshot()["consecutive_failures"]


def test_2xx_records_success():
    import vertex_services
    # Pre-bias the breaker with one failure so we can confirm success
    # resets the counter.
    vertex_services._breaker.record_failure("priming")
    assert _failures(vertex_services) == 1

    ok = vertex_services._record_response(_StubResponse(200), "embed_test")
    assert ok is True
    assert _failures(vertex_services) == 0


def test_400_with_api_key_marker_counts_as_infra_failure():
    """The current outage symptom: 400 + body containing 'API key'.
    This must open the breaker (it's the whole reason the breaker exists)."""
    import vertex_services
    body = '{"error":{"code":400,"message":"API key expired. Please renew."}}'
    ok = vertex_services._record_response(_StubResponse(400, body), "embed_test")
    assert ok is False
    assert _failures(vertex_services) == 1


def test_400_with_quota_marker_counts_as_infra_failure():
    import vertex_services
    body = '{"error":{"message":"Quota exceeded for project."}}'
    ok = vertex_services._record_response(_StubResponse(400, body), "embed_test")
    assert ok is False
    assert _failures(vertex_services) == 1


def test_400_without_infra_marker_does_NOT_count():
    """Plain 400 with a generic 'invalid argument' message must NOT
    open the breaker — that's user-payload error territory."""
    import vertex_services
    body = '{"error":{"message":"Field foo.bar is required"}}'
    ok = vertex_services._record_response(_StubResponse(400, body), "analyze_image")
    assert ok is False
    assert _failures(vertex_services) == 0  # not penalised


def test_413_payload_too_large_does_NOT_count():
    """A user submitting a 50MB image must not punish the breaker."""
    import vertex_services
    ok = vertex_services._record_response(_StubResponse(413, "too large"), "analyze_image")
    assert ok is False
    assert _failures(vertex_services) == 0


def test_422_unprocessable_does_NOT_count():
    import vertex_services
    ok = vertex_services._record_response(_StubResponse(422, "bad mime"), "analyze_image")
    assert ok is False
    assert _failures(vertex_services) == 0


def test_401_unauthorized_counts_as_infra_failure():
    import vertex_services
    ok = vertex_services._record_response(_StubResponse(401, "no auth"), "embed_test")
    assert ok is False
    assert _failures(vertex_services) == 1


def test_429_rate_limit_counts_as_infra_failure():
    import vertex_services
    ok = vertex_services._record_response(_StubResponse(429, "slow down"), "embed_test")
    assert ok is False
    assert _failures(vertex_services) == 1


def test_503_service_unavailable_counts_as_infra_failure():
    import vertex_services
    ok = vertex_services._record_response(_StubResponse(503, "upstream down"), "embed_test")
    assert ok is False
    assert _failures(vertex_services) == 1


def test_no_response_counts_as_infra_failure():
    """When `_post_embed_with_retry` exhausts retries on a transient
    error and returns None, the breaker must still see the failure."""
    import vertex_services
    ok = vertex_services._record_response(None, "embed_test")
    assert ok is False
    assert _failures(vertex_services) == 1


def test_unknown_4xx_does_NOT_count():
    """A status we don't recognise (e.g. 418 teapot) is logged but not
    penalised — better to under-open than to flap the breaker on a
    spec we don't understand."""
    import vertex_services
    ok = vertex_services._record_response(_StubResponse(418, "teapot"), "embed_test")
    assert ok is False
    assert _failures(vertex_services) == 0


def test_breaker_opens_after_threshold_infra_failures():
    """End-to-end: 5 consecutive infra-classified failures (the default
    threshold) must open the module-level breaker."""
    import vertex_services
    threshold = vertex_services._BREAKER_THRESHOLD
    for i in range(threshold):
        vertex_services._record_response(
            _StubResponse(400, "API key expired"), "embed_test",
        )
    snap = vertex_services.breaker_snapshot()
    assert snap["state"] == "open"
    assert snap["consecutive_failures"] >= threshold


def test_breaker_does_NOT_open_on_user_4xx_storm():
    """A user spamming oversized images must NOT trip the breaker."""
    import vertex_services
    for _ in range(20):  # well over the threshold
        vertex_services._record_response(_StubResponse(413, "too large"), "analyze_image")
        vertex_services._record_response(_StubResponse(400, "missing field"), "analyze_image")
    snap = vertex_services.breaker_snapshot()
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 0


# ── Workers AI embed 429 cooldown tests ───────────────────────────────────────


@pytest.fixture(autouse=False)
def _reset_embed_state():
    """Reset embed 429 state before and after each embed cooldown test."""
    import vertex_services
    vertex_services._reset_embed_429()
    yield
    vertex_services._reset_embed_429()


def test_cooldown_activates_after_threshold(_reset_embed_state):
    """After _EMBED_429_THRESHOLD calls to _track_embed_429, the cooldown
    must be active."""
    import vertex_services
    threshold = vertex_services._EMBED_429_THRESHOLD
    assert not vertex_services.is_embed_cooldown_active()
    for _ in range(threshold):
        vertex_services._track_embed_429()
    assert vertex_services.is_embed_cooldown_active()


def test_cooldown_not_active_below_threshold(_reset_embed_state):
    """Fewer than _EMBED_429_THRESHOLD hits must NOT activate the cooldown."""
    import vertex_services
    threshold = vertex_services._EMBED_429_THRESHOLD
    for _ in range(threshold - 1):
        vertex_services._track_embed_429()
    assert not vertex_services.is_embed_cooldown_active()


def test_get_embed_429_burst_returns_correct_count(_reset_embed_state):
    """get_embed_429_burst returns the number of recent 429 hits recorded."""
    import vertex_services
    assert vertex_services.get_embed_429_burst() == 0
    vertex_services._track_embed_429()
    vertex_services._track_embed_429()
    assert vertex_services.get_embed_429_burst() == 2


def test_get_embed_429_burst_returns_zero_after_reset(_reset_embed_state):
    """get_embed_429_burst must return 0 immediately after _reset_embed_429."""
    import vertex_services
    threshold = vertex_services._EMBED_429_THRESHOLD
    for _ in range(threshold):
        vertex_services._track_embed_429()
    assert vertex_services.get_embed_429_burst() == threshold
    vertex_services._reset_embed_429()
    assert vertex_services.get_embed_429_burst() == 0


def test_reset_clears_cooldown(_reset_embed_state):
    """_reset_embed_429 must deactivate an active cooldown."""
    import vertex_services
    threshold = vertex_services._EMBED_429_THRESHOLD
    for _ in range(threshold):
        vertex_services._track_embed_429()
    assert vertex_services.is_embed_cooldown_active()
    vertex_services._reset_embed_429()
    assert not vertex_services.is_embed_cooldown_active()


@pytest.mark.asyncio
async def test_workers_ai_primary_embed_skips_network_when_cooldown_active(_reset_embed_state, monkeypatch):
    """When the cooldown is active, _workers_ai_primary_embed must return None
    without making any network call."""
    import vertex_services

    call_count = {"n": 0}

    async def _fake_embed(text, model_key=None):
        call_count["n"] += 1
        return [0.1] * 1024

    import sys
    fake_module = type(sys)("providers.cloudflare_ai")
    fake_module.embed_one = _fake_embed
    monkeypatch.setitem(sys.modules, "providers.cloudflare_ai", fake_module)

    threshold = vertex_services._EMBED_429_THRESHOLD
    for _ in range(threshold):
        vertex_services._track_embed_429()
    assert vertex_services.is_embed_cooldown_active()

    result = await vertex_services._workers_ai_primary_embed("hello world")
    assert result is None
    assert call_count["n"] == 0, "No HTTP call should be made during cooldown"


@pytest.mark.asyncio
async def test_workers_ai_primary_embed_allowed_after_reset(_reset_embed_state, monkeypatch):
    """After _reset_embed_429, _workers_ai_primary_embed must proceed to the
    network (and return the vector on success)."""
    import vertex_services

    _EMBED_DIMENSIONS = vertex_services._EMBED_DIMENSIONS
    fake_vec = [0.1] * _EMBED_DIMENSIONS

    async def _fake_embed(text, model_key=None):
        return fake_vec

    import sys
    fake_module = type(sys)("providers.cloudflare_ai")
    fake_module.embed_one = _fake_embed
    monkeypatch.setitem(sys.modules, "providers.cloudflare_ai", fake_module)

    threshold = vertex_services._EMBED_429_THRESHOLD
    for _ in range(threshold):
        vertex_services._track_embed_429()
    vertex_services._reset_embed_429()
    assert not vertex_services.is_embed_cooldown_active()

    result = await vertex_services._workers_ai_primary_embed("hello world")
    assert result == fake_vec


# ── Sliding-window expiry tests ───────────────────────────────────────────────


def test_stale_timestamps_are_pruned_and_do_not_count(_reset_embed_state, monkeypatch):
    """Timestamps older than _EMBED_429_COOLDOWN_S must be dropped by
    _track_embed_429 so they no longer contribute to the burst count."""
    import vertex_services

    threshold = vertex_services._EMBED_429_THRESHOLD
    cooldown_s = vertex_services._EMBED_429_COOLDOWN_S
    base_time = 1_000_000.0

    # Record (threshold - 1) hits at t=base_time — below the activation threshold.
    monkeypatch.setattr(vertex_services.time, "time", lambda: base_time)
    for _ in range(threshold - 1):
        vertex_services._track_embed_429()

    assert vertex_services.get_embed_429_burst() == threshold - 1
    assert not vertex_services.is_embed_cooldown_active()

    # Advance the clock past the full cooldown window so every prior hit is stale.
    future_time = base_time + cooldown_s + 1
    monkeypatch.setattr(vertex_services.time, "time", lambda: future_time)

    # Record one new hit — _track_embed_429 must prune all old timestamps.
    vertex_services._track_embed_429()

    # Only the single fresh hit should remain in the window.
    assert vertex_services.get_embed_429_burst() == 1
    assert len(vertex_services._embed_429_timestamps) == 1


def test_expired_sub_threshold_hits_do_not_activate_cooldown_on_new_hit(
    _reset_embed_state, monkeypatch
):
    """Previously accumulated 429s that fall below the threshold but outside the
    window must NOT activate the cooldown when new hits arrive in a fresh window
    (even if the combined old+new count would cross the threshold)."""
    import vertex_services

    threshold = vertex_services._EMBED_429_THRESHOLD
    cooldown_s = vertex_services._EMBED_429_COOLDOWN_S
    base_time = 2_000_000.0

    # Record (threshold - 1) hits — just below the activation threshold.
    monkeypatch.setattr(vertex_services.time, "time", lambda: base_time)
    for _ in range(threshold - 1):
        vertex_services._track_embed_429()

    assert not vertex_services.is_embed_cooldown_active()

    # Advance the clock so all previous hits are outside the sliding window.
    future_time = base_time + cooldown_s + 1
    monkeypatch.setattr(vertex_services.time, "time", lambda: future_time)

    # One new hit in the fresh window — still below threshold on its own.
    vertex_services._track_embed_429()

    # Old timestamps have been pruned; only 1 fresh hit exists — cooldown must
    # NOT be active because the new window count (1) is below the threshold.
    assert not vertex_services.is_embed_cooldown_active()
    assert vertex_services.get_embed_429_burst(window_seconds=cooldown_s) == 1
