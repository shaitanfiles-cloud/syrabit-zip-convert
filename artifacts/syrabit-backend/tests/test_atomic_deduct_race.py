"""Task #765 — concurrency regression for ``atomic_deduct_credit``'s Redis
fallback.

When Postgres is unavailable, ``atomic_deduct_credit`` falls back to a
Redis-backed counter. Pre-fix, the fallback issued SETNX + INCR + a
compensating DECR as three independent commands, so two concurrent
callers could both step past the limit before either rolled back.

This test fires 50 concurrent deductions at a user whose limit is 30
and asserts:
  * exactly 30 calls return True
  * the Redis counter ends at exactly 30 (never above)
  * the user record was never written with credits_used_today > 30

Each deduction runs on its own OS thread with its own asyncio event
loop and starts behind a barrier, simulating multiple uvicorn workers
hitting the shared Redis simultaneously rather than the cooperative
single-loop interleaving of ``asyncio.gather``.
"""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import deps  # noqa: E402
import db_ops  # noqa: E402

fakeredis = pytest.importorskip("fakeredis")


def test_atomic_deduct_redis_fallback_never_exceeds_limit(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)

    # Force the Redis fallback path: no PG, no supa, just Redis.
    monkeypatch.setattr(deps, "pg_pool", None, raising=False)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)

    uid = "race-user-1"
    limit = 30
    n_workers = 50

    writes: list[int] = []
    writes_lock = threading.Lock()

    async def fake_get_user(_uid):
        return {"credits_used": 0}

    async def fake_update_user(_uid, updates):
        if "credits_used_today" in updates:
            with writes_lock:
                writes.append(int(updates["credits_used_today"]))

    monkeypatch.setattr(db_ops, "supa_get_user_by_id", fake_get_user)
    monkeypatch.setattr(db_ops, "supa_update_user", fake_update_user)

    barrier = threading.Barrier(n_workers)

    def _one_call(_i: int) -> bool:
        # Wait until every worker is ready, then race for the same slot.
        barrier.wait()
        return asyncio.run(
            db_ops.atomic_deduct_credit(uid, current_used=0, current_limit=limit)
        )

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        results = list(ex.map(_one_call, range(n_workers)))

    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if r is False)

    assert successes == limit, (
        f"expected exactly {limit} successful deductions, got {successes}"
    )
    assert failures == 50 - limit

    # The Redis counter must never have exceeded the limit.
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    final = int(fake.get(f"daily_credits:{uid}:{today_str}"))
    assert final == limit, f"redis counter overshot the limit: {final}"

    # No write to the user record should ever record an over-limit value.
    assert writes, "expected at least one write to the user record"
    assert max(writes) <= limit, (
        f"user record was written with over-limit value: max={max(writes)}"
    )
