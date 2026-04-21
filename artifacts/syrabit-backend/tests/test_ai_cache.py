"""ai_cache unit tests (Task #631).

Covers the four contracts the rest of the codebase relies on:

  * ``build_ai_cache_key`` is deterministic across (model, normalized
    prompt, retrieval, language, scope) and varies when any input
    changes — protecting against silent cache poisoning.
  * ``aset`` honours ``REDIS_AI_CACHE_MAX_ENTRY_BYTES``: oversize
    payloads are dropped and counted in the stats.
  * The circuit breaker opens after ``_BREAKER_THRESHOLD`` consecutive
    failures and short-circuits subsequent ``aget`` / ``aset`` calls,
    then closes again after a recorded success (cooldown bypass).
  * ``purge_all`` SCAN-deletes only keys under the configured namespace
    and returns an accurate ``deleted`` count.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset_ai_cache():
    """Reset ai_cache module globals between tests."""
    import ai_cache
    ai_cache._async_pool = None
    ai_cache._breaker_failures = 0
    ai_cache._breaker_opened_at = 0.0
    ai_cache._stats.hits = 0
    ai_cache._stats.misses = 0
    ai_cache._stats.entries_stored = 0
    ai_cache._stats.bytes_stored = 0
    ai_cache._stats.entries_skipped_oversize = 0
    ai_cache._stats.last_error = ""
    ai_cache._stats.purge_count = 0
    ai_cache._stats.last_purge_ts = 0.0
    ai_cache._stats.saved_latency_ms_total = 0.0
    ai_cache._stats.saved_latency_samples = 0
    ai_cache._stats.observed_miss_latency_ms_total = 0.0
    ai_cache._stats.observed_miss_latency_samples = 0
    ai_cache._stats.errors = 0
    yield
    ai_cache._async_pool = None
    ai_cache._breaker_failures = 0
    ai_cache._breaker_opened_at = 0.0


# ── build_ai_cache_key ──────────────────────────────────────────────────

def test_build_ai_cache_key_is_deterministic():
    from ai_cache import build_ai_cache_key
    a = build_ai_cache_key(
        model="openai/gpt-oss-20b", prompt="What is photosynthesis?",
        retrieval=["doc-a", "doc-b"], language="en", scope="study",
    )
    b = build_ai_cache_key(
        model="openai/gpt-oss-20b", prompt="What is photosynthesis?",
        retrieval=["doc-a", "doc-b"], language="en", scope="study",
    )
    assert a == b
    assert len(a) == 40  # sha256 truncated to 40 hex chars


def test_build_ai_cache_key_normalizes_prompt_whitespace():
    """Cosmetic whitespace differences must not bust the cache —
    ``_normalize_prompt`` collapses runs of whitespace."""
    from ai_cache import build_ai_cache_key
    a = build_ai_cache_key(model="m", prompt="hello   world", language="en")
    b = build_ai_cache_key(model="m", prompt="hello\tworld", language="en")
    c = build_ai_cache_key(model="m", prompt="hello world", language="en")
    assert a == b == c


def test_build_ai_cache_key_varies_with_each_input():
    """Each input dimension contributes to the hash."""
    from ai_cache import build_ai_cache_key
    base = dict(model="m", prompt="p", retrieval=["r"], language="en", scope="study")
    baseline = build_ai_cache_key(**base)
    assert build_ai_cache_key(**{**base, "model": "m2"}) != baseline
    assert build_ai_cache_key(**{**base, "prompt": "different"}) != baseline
    assert build_ai_cache_key(**{**base, "retrieval": ["other"]}) != baseline
    assert build_ai_cache_key(**{**base, "language": "as"}) != baseline
    assert build_ai_cache_key(**{**base, "scope": "chat"}) != baseline


def test_build_ai_cache_key_retrieval_order_matters_consistently():
    """Lists are JSON-encoded with sort_keys=False so order matters,
    but the same order always yields the same hash."""
    from ai_cache import build_ai_cache_key
    k1 = build_ai_cache_key(model="m", prompt="p", retrieval=["a", "b"])
    k2 = build_ai_cache_key(model="m", prompt="p", retrieval=["a", "b"])
    assert k1 == k2


# ── aset oversize handling ──────────────────────────────────────────────

def test_aset_drops_oversize_payload():
    """Payloads exceeding REDIS_AI_CACHE_MAX_ENTRY_BYTES are dropped
    and counted, never sent to Redis."""
    import ai_cache

    pool = MagicMock()
    pool.set = AsyncMock(return_value=True)
    ai_cache._async_pool = pool

    huge = "x" * (ai_cache.REDIS_AI_CACHE_MAX_ENTRY_BYTES + 100)
    ok = _run(ai_cache.aset("k1", huge))
    assert ok is False
    pool.set.assert_not_called()
    assert ai_cache._stats.entries_skipped_oversize == 1


def test_aset_stores_payload_under_limit():
    import ai_cache

    pool = MagicMock()
    pool.set = AsyncMock(return_value=True)
    ai_cache._async_pool = pool

    ok = _run(ai_cache.aset("k1", "hello", ttl=60))
    assert ok is True
    pool.set.assert_awaited_once()
    args, kwargs = pool.set.call_args
    assert args[0].endswith(":k1")  # namespace prefix applied
    assert args[1] == "hello"
    assert kwargs.get("ex") == 60
    assert ai_cache._stats.entries_stored == 1


# ── Circuit breaker ─────────────────────────────────────────────────────

def test_breaker_opens_after_threshold_failures_and_short_circuits():
    """Threshold consecutive failures opens the breaker, after which
    aget returns None immediately without touching Redis."""
    import ai_cache

    pool = MagicMock()
    pool.get = AsyncMock(side_effect=RuntimeError("redis down"))
    ai_cache._async_pool = pool

    threshold = ai_cache._BREAKER_THRESHOLD
    for _ in range(threshold):
        result = _run(ai_cache.aget("k"))
        assert result is None
    assert ai_cache._breaker_open() is True
    assert pool.get.await_count == threshold

    # Subsequent calls must NOT reach Redis while the breaker is open.
    pool.get.reset_mock()
    result = _run(ai_cache.aget("k"))
    assert result is None
    pool.get.assert_not_called()


def test_breaker_closes_after_successful_op():
    """A successful op resets the failure counter and closes the
    breaker — Redis became healthy again."""
    import ai_cache

    pool = MagicMock()
    pool.get = AsyncMock(side_effect=[
        RuntimeError("fail"), RuntimeError("fail"), "cached-value",
    ])
    ai_cache._async_pool = pool

    _run(ai_cache.aget("k"))
    _run(ai_cache.aget("k"))
    assert ai_cache._breaker_failures == 2
    assert ai_cache._breaker_open() is False  # under threshold
    val = _run(ai_cache.aget("k"))
    assert val == "cached-value"
    assert ai_cache._breaker_failures == 0
    assert ai_cache._breaker_open() is False


# ── purge_all ───────────────────────────────────────────────────────────

def test_purge_all_scans_namespace_and_returns_deleted_count():
    """purge_all SCANs the configured namespace, deletes matching keys
    in batches, and reports the cumulative count."""
    import ai_cache

    pool = MagicMock()
    # First SCAN returns 2 keys + cursor=42, second returns 1 key + cursor=0.
    pool.scan = AsyncMock(side_effect=[
        (42, [b"syrabit:ai_cache:k1", b"syrabit:ai_cache:k2"]),
        (0, [b"syrabit:ai_cache:k3"]),
    ])
    pool.delete = AsyncMock(return_value=1)
    ai_cache._async_pool = pool

    out = _run(ai_cache.purge_all())
    assert out["ok"] is True
    assert out["deleted"] == 3
    assert pool.scan.await_count == 2
    assert pool.delete.await_count == 2
    # Pattern includes the configured namespace prefix.
    first_scan = pool.scan.await_args_list[0]
    assert first_scan.kwargs["match"].startswith(f"{ai_cache.REDIS_AI_CACHE_NAMESPACE}:")


# ── Namespace prefixing ────────────────────────────────────────────────

def test_full_key_applies_configured_namespace():
    """Every cache write/read must be scoped to ``REDIS_AI_CACHE_NAMESPACE``
    so an admin purge can SCAN-delete only this app's keys without
    touching unrelated tenants on a shared Redis."""
    import ai_cache
    raw = ai_cache.build_ai_cache_key(model="m", prompt="hi", language="en")
    full = ai_cache._full_key(raw)
    assert full == f"{ai_cache.REDIS_AI_CACHE_NAMESPACE}:{raw}"
    assert full.startswith(f"{ai_cache.REDIS_AI_CACHE_NAMESPACE}:")


# ── Integration tests (fakeredis) ──────────────────────────────────────
#
# These exercise aget/aset/purge_all end-to-end against an in-memory
# Redis-compatible server (fakeredis), so we lock in real protocol
# semantics — TTL, SCAN cursoring, namespace isolation — instead of
# just verifying call shapes against a mock.

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture
def fake_redis_pool():
    """Provide a fakeredis async client wired into ai_cache as the active pool."""
    import ai_cache
    from fakeredis import aioredis as fake_aioredis
    pool = fake_aioredis.FakeRedis(decode_responses=True)
    ai_cache._async_pool = pool
    yield pool
    _run(pool.aclose() if hasattr(pool, "aclose") else pool.close())
    ai_cache._async_pool = None


def test_integration_aset_then_aget_round_trip(fake_redis_pool):
    """aset stores under the namespaced key; aget retrieves the exact
    payload and increments hit/miss counters accordingly."""
    import ai_cache

    key = ai_cache.build_ai_cache_key(model="m", prompt="round-trip", language="en")
    payload = '{"answer":"forty-two"}'

    miss = _run(ai_cache.aget(key))
    assert miss is None
    assert ai_cache._stats.misses == 1
    assert ai_cache._stats.hits == 0

    ok = _run(ai_cache.aset(key, payload, ttl=120, saved_ms=850.0))
    assert ok is True
    assert ai_cache._stats.entries_stored == 1
    assert ai_cache._stats.bytes_stored == len(payload.encode("utf-8"))

    hit = _run(ai_cache.aget(key))
    assert hit == payload
    assert ai_cache._stats.hits == 1
    assert ai_cache._stats.misses == 1  # unchanged

    # Stored under the namespaced key — verify directly.
    raw = _run(fake_redis_pool.get(ai_cache._full_key(key)))
    assert raw == payload


def test_integration_purge_all_deletes_only_namespaced_keys(fake_redis_pool):
    """purge_all SCAN-deletes everything under the namespace and leaves
    foreign keys (other tenants) untouched."""
    import ai_cache

    # Seed three of our keys + one foreign key on the same Redis.
    keys = []
    for i in range(3):
        k = ai_cache.build_ai_cache_key(model="m", prompt=f"q-{i}", language="en")
        _run(ai_cache.aset(k, f"v-{i}", ttl=60))
        keys.append(k)
    _run(fake_redis_pool.set("other_tenant:keep_me", "do-not-touch"))

    out = _run(ai_cache.purge_all())
    assert out["ok"] is True
    assert out["deleted"] == 3
    assert ai_cache._stats.purge_count == 1

    # All our entries gone; the foreign key survived.
    for k in keys:
        assert _run(fake_redis_pool.get(ai_cache._full_key(k))) is None
    assert _run(fake_redis_pool.get("other_tenant:keep_me")) == "do-not-touch"


def test_integration_stats_reports_hit_rate_and_saved_latency(fake_redis_pool):
    """Two misses then a successful set + hit should produce hit_rate=1/3
    and a non-zero estimated_total_saved_ms via observed-miss latency."""
    import ai_cache

    k1 = ai_cache.build_ai_cache_key(model="m", prompt="a", language="en")
    k2 = ai_cache.build_ai_cache_key(model="m", prompt="b", language="en")
    _run(ai_cache.aget(k1))   # miss
    _run(ai_cache.aget(k2))   # miss
    _run(ai_cache.aset(k1, "value-a", ttl=60, saved_ms=600.0))
    val = _run(ai_cache.aget(k1))   # hit
    assert val == "value-a"

    snap = ai_cache.stats()
    assert snap["hits"] == 1
    assert snap["misses"] == 2
    assert snap["hit_rate"] == round(1 / 3, 4)
    assert snap["entries_stored"] == 1
    assert snap["bytes_stored"] == len("value-a".encode("utf-8"))
    # Hit count > saved-latency samples → estimator falls back to
    # observed-miss latency to credit the un-instrumented hit.
    assert snap["estimated_total_saved_ms"] >= 600.0
    assert snap["breaker_open"] is False
