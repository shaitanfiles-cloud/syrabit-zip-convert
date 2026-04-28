"""Circuit breaker unit tests (Task #831).

Covers the CLOSED → OPEN → HALF_OPEN → CLOSED state machine that
replaces the legacy `_GEMINI_FORBIDDEN` permanent-disable global. The
breaker is the foundation of the gemini fallback resilience work, so
these tests pin its behaviour explicitly:

  1. Starts CLOSED and allows calls.
  2. Opens after `failure_threshold` consecutive failures.
  3. Stays OPEN until the cooldown elapses, then transitions to HALF_OPEN.
  4. HALF_OPEN allows exactly one probe; success closes, failure re-opens.
  5. record_success() resets the failure counter and closes the breaker.
  6. Hooks fire on OPEN / CLOSE transitions.
  7. force_close / force_open work for operator overrides.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vertex_breaker import CircuitBreaker  # noqa: E402


def test_starts_closed_and_allows():
    b = CircuitBreaker(name="t", failure_threshold=3, cooldown_s=10)
    assert b.state == "closed"
    assert b.allow() is True
    assert b.snapshot()["consecutive_failures"] == 0


def test_opens_after_threshold():
    b = CircuitBreaker(name="t", failure_threshold=3, cooldown_s=10)
    b.record_failure("net")
    assert b.state == "closed"
    assert b.allow() is True
    b.record_failure("net")
    assert b.state == "closed"
    b.record_failure("net")
    assert b.state == "open"
    # Subsequent allow() calls within the cooldown deny.
    assert b.allow() is False
    assert b.allow() is False


def test_record_success_resets_counter_and_closes():
    b = CircuitBreaker(name="t", failure_threshold=3, cooldown_s=10)
    b.record_failure("a")
    b.record_failure("a")
    assert b.snapshot()["consecutive_failures"] == 2
    b.record_success()
    assert b.state == "closed"
    assert b.snapshot()["consecutive_failures"] == 0
    # Now N more failures should be needed again to re-open.
    b.record_failure("b")
    b.record_failure("b")
    assert b.state == "closed"


def test_half_open_after_cooldown_then_closes_on_success():
    b = CircuitBreaker(name="t", failure_threshold=2, cooldown_s=0.2)
    b.record_failure("a")
    b.record_failure("a")
    assert b.state == "open"
    assert b.allow() is False
    time.sleep(0.25)
    # Cooldown elapsed → next allow() moves to HALF_OPEN and grants 1 probe.
    assert b.allow() is True
    assert b.state == "half_open"
    # Parallel allow() while HALF_OPEN must be denied — only one probe.
    assert b.allow() is False
    # Probe succeeds → CLOSED.
    b.record_success()
    assert b.state == "closed"
    assert b.allow() is True


def test_half_open_failure_reopens_with_fresh_cooldown():
    b = CircuitBreaker(name="t", failure_threshold=1, cooldown_s=0.2)
    b.record_failure("first")
    assert b.state == "open"
    time.sleep(0.25)
    assert b.allow() is True  # HALF_OPEN probe granted
    # Probe fails → re-OPEN with fresh cooldown, NOT immediately re-half-open.
    b.record_failure("probe-failed")
    assert b.state == "open"
    assert b.allow() is False
    time.sleep(0.25)
    assert b.allow() is True  # cooldown elapsed again


def test_open_close_hooks_fire_once():
    opens = []
    closes = []

    def _on_open(reason):
        opens.append(reason)

    def _on_close():
        closes.append("closed")

    b = CircuitBreaker(
        name="hooks", failure_threshold=2, cooldown_s=10,
        on_open=_on_open, on_close=_on_close,
    )
    b.record_failure("x")
    assert opens == []  # under threshold
    b.record_failure("y")
    assert opens == ["y"]  # opened
    # Subsequent failures while OPEN do NOT re-fire on_open.
    b.record_failure("z")
    assert opens == ["y"]
    # Success while OPEN closes once and fires on_close.
    b.record_success()
    assert closes == ["closed"]
    # Repeated success() does not re-fire on_close.
    b.record_success()
    assert closes == ["closed"]


def test_force_close_overrides_open_state():
    b = CircuitBreaker(name="t", failure_threshold=1, cooldown_s=600)
    b.record_failure("oops")
    assert b.state == "open"
    b.force_close()
    assert b.state == "closed"
    assert b.allow() is True
    assert b.snapshot()["consecutive_failures"] == 0


def test_force_open_blocks_traffic():
    b = CircuitBreaker(name="t", failure_threshold=10, cooldown_s=0.1)
    assert b.allow() is True
    b.force_open(reason="maintenance")
    assert b.state == "open"
    assert b.allow() is False
    snap = b.snapshot()
    assert snap["last_reason"] == "maintenance"
    assert snap["state"] == "open"


def test_threshold_clamps_to_minimum_one():
    """A misconfigured threshold of 0 (or negative) must not divide-by-zero
    or open immediately on construction; the constructor clamps to >= 1."""
    b = CircuitBreaker(name="t", failure_threshold=0, cooldown_s=10)
    # Threshold should be clamped to 1, so a single failure opens it.
    assert b.state == "closed"
    b.record_failure("one")
    assert b.state == "open"


def test_snapshot_includes_remaining_cooldown():
    b = CircuitBreaker(name="t", failure_threshold=1, cooldown_s=5)
    b.record_failure("x")
    snap = b.snapshot()
    assert snap["state"] == "open"
    assert 0 < snap["cooldown_remaining_s"] <= 5
    assert snap["cooldown_s"] == 5
    assert snap["last_reason"] == "x"


def test_half_open_lease_expires_then_reopens():
    """Architect feedback (Task #831): if a probe is granted but never
    reports an outcome (caller cancelled, exception swallowed, etc),
    the breaker would otherwise sit in HALF_OPEN forever. The lease
    bound is the cooldown duration: after that, the next allow() call
    detects the abandoned probe and re-OPENs with a fresh cooldown."""
    b = CircuitBreaker(name="t", failure_threshold=1, cooldown_s=0.2)
    b.record_failure("opening")
    assert b.state == "open"

    # Wait out the initial cooldown — granting the probe.
    time.sleep(0.25)
    assert b.allow() is True
    assert b.state == "half_open"
    # The probe is "in flight" — second allow() denies (one-probe rule).
    assert b.allow() is False

    # Simulate the probe never reporting back (caller cancelled). After
    # another cooldown elapses, the next allow() should detect the
    # abandoned probe and re-OPEN.
    time.sleep(0.25)
    assert b.allow() is False  # this call observed expiry → re-OPEN
    assert b.state == "open"
    assert b.snapshot()["last_reason"] == "half_open_lease_expired"

    # Now the fresh cooldown elapses → another probe is granted.
    time.sleep(0.25)
    assert b.allow() is True
    assert b.state == "half_open"
    # And success this time closes for good.
    b.record_success()
    assert b.state == "closed"
