"""Task #768 — concurrency regression for ``atomic_deduct_ip_credit``.

The per-IP daily quota uses the same Lua-based atomic check-and-increment
as the user credit ledger (Task #765). This test fires 50 concurrent
deductions at one IP whose limit is 30 and asserts:

  * exactly 30 calls return True
  * the Redis counter ends at exactly 30 (never above)

Each deduction runs on its own OS thread and starts behind a barrier,
simulating multiple uvicorn workers hitting the shared Redis at once
rather than the cooperative single-loop interleaving of asyncio.gather.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import db_ops  # noqa: E402

fakeredis = pytest.importorskip("fakeredis")


def test_atomic_deduct_ip_credit_never_exceeds_limit(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)

    ip = "203.0.113.42"
    limit = 30
    n_workers = 50

    barrier = threading.Barrier(n_workers)

    def _one_call(_i: int) -> bool:
        barrier.wait()
        return db_ops.atomic_deduct_ip_credit(ip, daily_limit=limit)

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        results = list(ex.map(_one_call, range(n_workers)))

    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if r is False)

    assert successes == limit, (
        f"expected exactly {limit} successful deductions, got {successes}"
    )
    assert failures == n_workers - limit

    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    final = int(fake.get(f"ip_daily_credits:{ip}:{today_str}"))
    assert final == limit, f"redis counter overshot the limit: {final}"


def test_atomic_deduct_ip_credit_fails_closed_without_redis(monkeypatch):
    monkeypatch.setattr(db_ops, "redis_client", None, raising=False)
    assert db_ops.atomic_deduct_ip_credit("198.51.100.1", daily_limit=30) is False


def test_atomic_deduct_ip_credit_rejects_empty_ip(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    assert db_ops.atomic_deduct_ip_credit("", daily_limit=30) is False


# ─── Task #793: identical concurrency guarantee, device-keyed counter ────
# ``atomic_deduct_device_credit`` reuses ``_REDIS_DEDUCT_LUA`` so the
# correctness already proven above for the IP variant should hold; this
# test pins it down so a future refactor that swaps the implementation
# (e.g. to a non-atomic INCR/DECR pair) immediately fails CI rather
# than silently letting two students on the same shared NAT each get
# bursts above the 30/day cap.

def test_atomic_deduct_device_credit_never_exceeds_limit(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)

    token_id = "deadbeef" * 4  # 32 hex chars — same shape as device_token.device_token_id()
    limit = 30
    n_workers = 50

    barrier = threading.Barrier(n_workers)

    def _one_call(_i: int) -> bool:
        barrier.wait()
        return db_ops.atomic_deduct_device_credit(token_id, daily_limit=limit)

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        results = list(ex.map(_one_call, range(n_workers)))

    successes = sum(1 for r in results if r is True)
    assert successes == limit, (
        f"expected exactly {limit} successful device-deductions, got {successes}"
    )

    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    final = int(fake.get(f"device_daily_credits:{token_id}:{today_str}"))
    assert final == limit, f"device counter overshot the limit: {final}"


def test_atomic_deduct_device_credit_fails_closed_without_redis(monkeypatch):
    monkeypatch.setattr(db_ops, "redis_client", None, raising=False)
    assert db_ops.atomic_deduct_device_credit("abc", daily_limit=30) is False


def test_atomic_deduct_device_credit_rejects_empty_token(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    assert db_ops.atomic_deduct_device_credit("", daily_limit=30) is False


def test_atomic_deduct_device_credit_isolates_keyspace_from_ip(monkeypatch):
    """Sanity-check: device counters must live in their own keyspace
    so an exhausted device does not also block the same id when used
    as an IP elsewhere (and vice versa). Guards against a refactor
    that accidentally collapses both helpers onto the same key."""
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    same = "abcdef0123456789"

    # Drain the device counter completely.
    for _ in range(30):
        assert db_ops.atomic_deduct_device_credit(same, daily_limit=30) is True
    assert db_ops.atomic_deduct_device_credit(same, daily_limit=30) is False

    # The IP-namespaced counter for that exact same string must be
    # untouched and able to take its own 30 charges.
    for _ in range(30):
        assert db_ops.atomic_deduct_ip_credit(same, daily_limit=30) is True
    assert db_ops.atomic_deduct_ip_credit(same, daily_limit=30) is False
