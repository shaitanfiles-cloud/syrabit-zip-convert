"""Read-only peek of the per-device daily credit counter.

The chat composer (Task #796) renders "X / 30 free messages left
today" by polling the ``/user/credits`` endpoint, which in turn calls
:func:`db_ops.peek_device_credit_used`. The whole point of the peek
is that it must NEVER charge a credit — otherwise simply opening the
chat page (or the credits-effect re-running on auth-state changes)
would silently burn one of the student's free messages, which would
destroy trust the moment they noticed the count tick down without
sending anything.

These tests pin down the read-only contract and the resilience to
missing tokens / Redis outages, so future refactors can't quietly
turn the helper into a side-effecting one.
"""
import fakeredis

import db_ops


def _set_fake_redis(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    return fake


def test_peek_returns_zero_when_counter_unseeded(monkeypatch):
    """A brand-new device that has never sent a message must read as
    0 used (==> 30 remaining in the caller). Falsely returning the
    daily_limit here would render "0 left" on the very first page
    load, scaring students into thinking they're already capped."""
    _set_fake_redis(monkeypatch)
    assert db_ops.peek_device_credit_used("a" * 32) == 0


def test_peek_matches_atomic_deduct_count(monkeypatch):
    """After N successful atomic deducts the peek must report
    exactly N — anything else and the UI would either show stale
    "messages left" or, worse, accuse the student of using messages
    they never sent."""
    _set_fake_redis(monkeypatch)
    token = "abcdef0123456789" * 2
    for _ in range(7):
        assert db_ops.atomic_deduct_device_credit(token, daily_limit=30) is True
    assert db_ops.peek_device_credit_used(token) == 7


def test_peek_does_not_charge_a_credit(monkeypatch):
    """The whole point of a peek: a million peeks back-to-back must
    leave the counter exactly where atomic_deduct left it. Any
    increment here would silently consume the student's free quota
    every time the chat composer mounts."""
    _set_fake_redis(monkeypatch)
    token = "feedface" * 4
    for _ in range(3):
        db_ops.atomic_deduct_device_credit(token, daily_limit=30)
    for _ in range(50):
        assert db_ops.peek_device_credit_used(token) == 3
    # And the next deduct still works — the peek did not move the
    # cursor, so we should be at 4 after one more charge.
    assert db_ops.atomic_deduct_device_credit(token, daily_limit=30) is True
    assert db_ops.peek_device_credit_used(token) == 4


def test_peek_returns_zero_when_redis_unavailable(monkeypatch):
    """When Redis is down the peek must fall back to the optimistic
    "fresh quota" view rather than show "0 left". Otherwise a Redis
    blip would visually rate-limit every anonymous student on the
    site even though the server-side enforcement (also Redis-backed)
    would itself be open."""
    monkeypatch.setattr(db_ops, "redis_client", None, raising=False)
    assert db_ops.peek_device_credit_used("anything") == 0


def test_peek_rejects_empty_token(monkeypatch):
    """A request with no device cookie has no token to peek; the
    helper must short-circuit to 0 instead of building a key like
    ``device_daily_credits::<date>`` that could collide across
    requests."""
    _set_fake_redis(monkeypatch)
    assert db_ops.peek_device_credit_used("") == 0
    assert db_ops.peek_device_credit_used(None) == 0  # type: ignore[arg-type]


def test_peek_caps_at_daily_limit_via_endpoint_clamp(monkeypatch):
    """The Redis counter itself can grow past the daily_limit if a
    legacy value is loaded from a backup or a race somewhere wins;
    the peek helper just reports the raw value (the endpoint clamps
    for display). Locking this in so the helper stays the source of
    truth and any clamping is the caller's responsibility — keeps
    the helper composable for non-UI callers (admin dashboards,
    abuse triage, etc.) that genuinely want the raw count."""
    fake = _set_fake_redis(monkeypatch)
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake.set(f"device_daily_credits:overflowtoken:{today_str}", 99)
    assert db_ops.peek_device_credit_used("overflowtoken") == 99
