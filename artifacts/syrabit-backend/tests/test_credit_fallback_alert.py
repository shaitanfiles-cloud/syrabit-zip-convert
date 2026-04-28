"""Task #769 — credit-deduct fallback observability.

Verifies:
1. ``record_credit_fallback`` increments the rolling window and
   ``get_credit_fallback_stats`` reports per-path totals + a sane
   per-minute rate.
2. Events older than the configured window are evicted.
3. ``atomic_deduct_credit`` records ``"redis"`` when the Postgres
   path is unavailable and the Redis Lua path succeeds.
4. ``atomic_deduct_credit`` records ``"supabase"`` when Postgres
   is unavailable AND no Redis client is configured (last resort).
5. Both events fire when the Postgres path is unavailable, the
   Redis path raises, and execution cascades to Supabase.
6. Invalid paths are silently ignored (defensive guard).

Each test snapshots ``_credit_fallback_window`` so the tests don't
contaminate each other or other tests in the suite.
"""
from __future__ import annotations

import asyncio
import time
import importlib

import pytest


@pytest.fixture
def metrics_mod(monkeypatch):
    import metrics as m
    saved = list(m._credit_fallback_window)
    m._credit_fallback_window.clear()
    yield m
    m._credit_fallback_window.clear()
    m._credit_fallback_window.extend(saved)


def test_record_and_stats_basic(metrics_mod):
    m = metrics_mod
    for _ in range(3):
        m.record_credit_fallback("redis")
    for _ in range(2):
        m.record_credit_fallback("supabase")
    s = m.get_credit_fallback_stats(300)
    assert s["total"] == 5
    assert s["by_path"]["redis"] == 3
    assert s["by_path"]["supabase"] == 2
    assert s["window_seconds"] == 300
    # 5 events / 5 min = 1.0/min
    assert s["rate_per_min"] == 1.0


def test_record_invalid_path_ignored(metrics_mod):
    m = metrics_mod
    m.record_credit_fallback("mongo")
    m.record_credit_fallback("")
    m.record_credit_fallback(None)  # type: ignore[arg-type]
    assert m.get_credit_fallback_stats(300)["total"] == 0


def test_window_eviction(metrics_mod):
    m = metrics_mod
    # Manually inject an event older than the rolling window.
    old_ts = time.time() - (m._CREDIT_FALLBACK_WINDOW_SECONDS + 60)
    m._credit_fallback_window.append((old_ts, "redis"))
    # A new event triggers the trim.
    m.record_credit_fallback("redis")
    # Only the fresh event should remain.
    assert len(m._credit_fallback_window) == 1
    assert m._credit_fallback_window[0][1] == "redis"
    assert m._credit_fallback_window[0][0] > old_ts


def test_stats_window_filter(metrics_mod):
    m = metrics_mod
    # Inject an event 4 min ago (inside 5-min window, outside 1-min).
    m._credit_fallback_window.append((time.time() - 240, "redis"))
    m.record_credit_fallback("supabase")  # now
    five_min = m.get_credit_fallback_stats(300)
    one_min = m.get_credit_fallback_stats(60)
    assert five_min["total"] == 2
    assert one_min["total"] == 1
    assert one_min["by_path"]["supabase"] == 1


# ── End-to-end through atomic_deduct_credit ─────────────────────────────


class _FakeRedisOK:
    """Minimal Redis stand-in whose Lua eval always returns
    ``current_used + 1`` (i.e. one slot consumed, still under limit)."""

    def __init__(self):
        self.calls = 0
        self.last_seed = None
        self.last_limit = None

    def eval(self, _script, _numkeys, _key, seed, limit, _ttl):
        self.calls += 1
        self.last_seed = int(seed)
        self.last_limit = int(limit)
        return int(seed) + 1


class _FakeRedisRaises:
    """Redis stand-in whose Lua eval always raises — exercises the
    cascade from PG → Redis → Supabase last-resort."""

    def eval(self, *_args, **_kwargs):
        raise RuntimeError("simulated redis outage")


@pytest.fixture
def deduct_env(monkeypatch, metrics_mod):
    """Force `atomic_deduct_credit` past the Postgres branch by
    nulling out `pg_pool`, and stub the Supabase update + read paths
    so the function can complete without a real DB. Returns a
    namespace with knobs for each test to flip."""
    import db_ops
    import deps

    monkeypatch.setattr(deps, "pg_pool", None, raising=False)
    monkeypatch.setattr(db_ops._deps_mod, "pg_pool", None, raising=False)

    async def _fake_get_user(_uid):
        return {"credits_used": 10}

    async def _fake_update_user(_uid, _updates):
        return None

    monkeypatch.setattr(db_ops, "supa_get_user_by_id", _fake_get_user)
    monkeypatch.setattr(db_ops, "supa_update_user", _fake_update_user)

    class _Env:
        def use_redis(self, client):
            monkeypatch.setattr(db_ops, "redis_client", client, raising=False)

    env = _Env()
    env.use_redis(None)  # default: no redis
    return env


def test_atomic_deduct_records_redis_path(metrics_mod, deduct_env):
    import db_ops
    deduct_env.use_redis(_FakeRedisOK())
    ok = asyncio.run(
        db_ops.atomic_deduct_credit("u1", current_used=10, current_limit=30)
    )
    assert ok is True
    s = metrics_mod.get_credit_fallback_stats(300)
    assert s["by_path"]["redis"] == 1
    assert s["by_path"]["supabase"] == 0


def test_atomic_deduct_records_supabase_path_when_no_redis(metrics_mod, deduct_env):
    import db_ops
    deduct_env.use_redis(None)
    ok = asyncio.run(
        db_ops.atomic_deduct_credit("u2", current_used=10, current_limit=30)
    )
    assert ok is True
    s = metrics_mod.get_credit_fallback_stats(300)
    assert s["by_path"]["redis"] == 0
    assert s["by_path"]["supabase"] == 1


def test_atomic_deduct_records_both_when_redis_fails(metrics_mod, deduct_env):
    import db_ops
    deduct_env.use_redis(_FakeRedisRaises())
    ok = asyncio.run(
        db_ops.atomic_deduct_credit("u3", current_used=10, current_limit=30)
    )
    assert ok is True
    s = metrics_mod.get_credit_fallback_stats(300)
    # Redis was attempted (and recorded) before raising; then Supabase
    # last-resort ran and recorded its own event.
    assert s["by_path"]["redis"] == 1
    assert s["by_path"]["supabase"] == 1


def test_atomic_deduct_supabase_path_respects_limit(metrics_mod, deduct_env):
    """When already at limit, Supabase last-resort returns False but
    we still record the fallback event — the request DID exercise the
    degraded path, even if the deduction itself was rejected."""
    import db_ops
    deduct_env.use_redis(None)
    ok = asyncio.run(
        db_ops.atomic_deduct_credit("u4", current_used=30, current_limit=30)
    )
    assert ok is False
    s = metrics_mod.get_credit_fallback_stats(300)
    assert s["by_path"]["supabase"] == 1
