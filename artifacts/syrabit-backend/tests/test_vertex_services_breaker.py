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
