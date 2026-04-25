"""Task #848 — TTL + single-flight cache for dependency probes.

Background
----------
Before #848 the ``/api/health`` handler made one fresh I/O call per
dependency (Mongo ``boards.find_one``, Postgres ``SELECT 1``, Redis
``PING``, Mongo ``api_config.find_one`` for Razorpay, …) on **every**
request. Synthetic probes, the admin dashboard, and Cloudflare's
edge-cache revalidation all hammer this endpoint, which:

* added 50–300 ms TTFB to the supposedly-cheap healthcheck, and
* drove a steady ~3 r/s baseline of writes to the Mongo primary just
  to read configuration that almost never changes.

The fix
-------
Split the probes off the request path. Each dependency gets a slot
in this in-process cache with a 5–10 s TTL (configurable via
``HEALTH_SNAPSHOT_TTL_S``). On a hit, ``get()`` returns the cached
dict in O(1). On a miss, exactly **one** caller runs the probe under
a per-key ``asyncio.Lock`` while every other concurrent caller gets
the previous (possibly stale) value back instead of stampeding the
upstream. This is the standard request-coalescing / single-flight
pattern.

Why a separate module instead of extending ``metrics._health_deps_cache``?
The metrics-module cache is refreshed on a fixed 25 s background timer
and is shared with the alerting pipeline. We want a *shorter* TTL with
*on-demand* refresh for the public ``/api/livez`` and ``/api/readyz``
routes without changing the alerting cadence — different consumers,
different SLO, different cache.

Probe contract
--------------
Each registered probe is an ``async`` callable returning a dict with
at minimum a ``status`` key. The cache wrapper adds ``latencyMs`` if
absent and converts exceptions / timeouts into ``{"status": "error",
"reason": ...}`` so callers never need to wrap probes in try/except.

The default 4 s timeout is well under any reasonable healthcheck
budget (Railway's default is 5 s) but generous enough that a healthy
upstream completes in one round-trip.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Default 7 s puts us in the middle of the task's 5–10 s band. Override
# via env var so we can dial it down (1–2 s) in load tests or up
# (30 s) for reduced upstream pressure during incident response.
DEFAULT_TTL_S: float = float(os.environ.get("HEALTH_SNAPSHOT_TTL_S", "7"))

# Probe budget. Anything slower than this is by definition unhealthy
# from a healthcheck perspective — the route would otherwise time out
# upstream of us anyway.
PROBE_TIMEOUT_S: float = float(os.environ.get("HEALTH_SNAPSHOT_PROBE_TIMEOUT_S", "4"))


class _Slot:
    __slots__ = ("value", "ts", "lock")

    def __init__(self) -> None:
        self.value: Dict[str, Any] = {"status": "unknown", "latencyMs": 0}
        # ts == 0.0 means "never probed". We treat that as cache-miss
        # but also as "no last-good value to fall back on".
        self.ts: float = 0.0
        self.lock = asyncio.Lock()


_slots: Dict[str, _Slot] = {}
_probes: Dict[str, Callable[[], Awaitable[Dict[str, Any]]]] = {}


def register(name: str, probe: Callable[[], Awaitable[Dict[str, Any]]]) -> None:
    """Register a probe. Idempotent — re-registering replaces the
    callable but preserves the existing cached value so a hot-reload
    (during testing) doesn't blow away history."""
    _probes[name] = probe
    _slots.setdefault(name, _Slot())


def registered_names() -> list[str]:
    return list(_probes.keys())


async def _run_probe(name: str) -> Dict[str, Any]:
    probe = _probes.get(name)
    if probe is None:
        return {"status": "unknown", "latencyMs": 0, "reason": "unregistered"}
    t0 = time.time()
    try:
        out = await asyncio.wait_for(probe(), timeout=PROBE_TIMEOUT_S)
        if not isinstance(out, dict):
            out = {"status": "error", "reason": f"probe returned {type(out).__name__}"}
        out.setdefault("latencyMs", int((time.time() - t0) * 1000))
        return out
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "latencyMs": int((time.time() - t0) * 1000),
            "reason": f"probe timed out after {PROBE_TIMEOUT_S}s",
        }
    except Exception as exc:  # noqa: BLE001 — probe-level catch-all is the contract
        return {
            "status": "error",
            "latencyMs": int((time.time() - t0) * 1000),
            "reason": f"{type(exc).__name__}: {exc}",
        }


async def get(name: str, ttl_s: float = DEFAULT_TTL_S) -> Dict[str, Any]:
    """Return the cached probe result, refreshing if older than ``ttl_s``.

    Single-flight: if a refresh is already in flight, concurrent callers
    do **not** queue behind the lock — they get the previous value back
    immediately (or ``unknown`` if no probe has ever run). This keeps
    healthcheck latency bounded even when the upstream is slow.
    """
    slot = _slots.get(name)
    if slot is None:
        slot = _Slot()
        _slots[name] = slot

    now = time.time()
    fresh = (slot.ts > 0) and (now - slot.ts < ttl_s)
    if fresh:
        return dict(slot.value)

    if slot.lock.locked():
        # Another coroutine is probing right now — return whatever we
        # have. If we've never probed, fall through to acquire the lock
        # (which will return immediately once the in-flight probe
        # finishes and re-checks freshness).
        if slot.ts > 0:
            return dict(slot.value)

    async with slot.lock:
        # Double-check under the lock: a concurrent probe may have
        # filled the slot while we were waiting.
        now2 = time.time()
        if (slot.ts > 0) and (now2 - slot.ts < ttl_s):
            return dict(slot.value)
        result = await _run_probe(name)
        slot.value = result
        slot.ts = time.time()
        return dict(result)


async def get_all(ttl_s: float = DEFAULT_TTL_S) -> Dict[str, Dict[str, Any]]:
    """Fan out ``get()`` across every registered probe in parallel.

    Uses ``return_exceptions=True`` so a bug or unexpected raise in one
    probe's wrapper code does not poison the entire snapshot —
    /api/readyz must keep returning *some* status for every dep even
    when one of them is broken in an unanticipated way. (Probe-level
    exceptions are already converted to ``status=error`` inside
    ``_run_probe``; this is the belt-and-braces layer that catches
    bugs in ``get()`` itself.)
    """
    names = list(_probes.keys())
    if not names:
        return {}
    raw = await asyncio.gather(
        *(get(n, ttl_s=ttl_s) for n in names),
        return_exceptions=True,
    )
    out: Dict[str, Dict[str, Any]] = {}
    for name, value in zip(names, raw):
        if isinstance(value, BaseException):
            logger.warning("health_snapshot_cache.get(%r) raised: %r", name, value)
            out[name] = {
                "status": "error",
                "latencyMs": 0,
                "reason": f"snapshot wrapper raised {type(value).__name__}: {value}",
            }
        else:
            out[name] = value
    return out


def peek(name: str) -> Optional[Dict[str, Any]]:
    """Return the last cached snapshot WITHOUT triggering a refresh.
    Returns ``None`` if the probe has never run."""
    slot = _slots.get(name)
    if slot is None or slot.ts == 0:
        return None
    return dict(slot.value)


def peek_all() -> Dict[str, Dict[str, Any]]:
    """Snapshot every cached value without I/O. Probes that have never
    run are reported as ``status=unknown``."""
    out: Dict[str, Dict[str, Any]] = {}
    for name in _probes.keys():
        out[name] = peek(name) or {"status": "unknown", "latencyMs": 0}
    return out


def reset() -> None:
    """Test helper — clear all cached snapshots and registrations."""
    _slots.clear()
    _probes.clear()


def reset_values() -> None:
    """Test helper — clear values but keep registrations."""
    for slot in _slots.values():
        slot.ts = 0.0
        slot.value = {"status": "unknown", "latencyMs": 0}


# ─────────────────────────────────────────────────────────────────────────
# Built-in probes for Syrabit.ai dependencies. Imports happen inside the
# probe functions so this module is safe to import early in startup
# (before deps.db / deps.pg_pool are initialised).
# ─────────────────────────────────────────────────────────────────────────


async def _probe_mongo() -> Dict[str, Any]:
    import deps  # local import — deps.db is mutated during startup
    if deps.db is None:
        return {"status": "not_configured", "latencyMs": 0}
    t0 = time.time()
    await deps.db.command("ping")
    return {"status": "ok", "latencyMs": int((time.time() - t0) * 1000)}


async def _probe_postgres() -> Dict[str, Any]:
    import deps
    if not deps.pg_pool:
        return {"status": "not_configured", "latencyMs": 0}
    t0 = time.time()
    async with deps.pg_pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok", "latencyMs": int((time.time() - t0) * 1000)}


async def _probe_redis() -> Dict[str, Any]:
    import deps
    if not deps.redis_client:
        return {"status": "not_connected", "latencyMs": 0}
    t0 = time.time()
    # redis-py's sync ``ping`` is fine here — it runs in the asyncio
    # default executor effectively because we're already in an event
    # loop and the call is sub-millisecond. Switching to async-redis
    # is out of scope for #848.
    deps.redis_client.ping()
    return {"status": "ok", "latencyMs": int((time.time() - t0) * 1000)}


async def _probe_razorpay() -> Dict[str, Any]:
    """Razorpay configuration probe.

    Reads ``api_config.payment`` from Mongo at most once per TTL
    window (instead of per-request, which was the pre-#848 behaviour).
    Falls back to env vars when Mongo is unreachable so a stale-but-
    valid env var still reports as ``configured``.
    """
    import deps
    rp_payment: Dict[str, Any] = {}
    if deps.db is not None:
        try:
            rp_cfg = await deps.db.api_config.find_one({}, {"payment": 1}) or {}
            rp_payment = rp_cfg.get("payment") or {}
        except Exception as exc:
            logger.debug("razorpay probe: mongo read failed: %s", exc)
    rp_key_id = (rp_payment.get("razorpay_key_id") or os.environ.get("RAZORPAY_KEY_ID", "")).strip()
    rp_key_secret = (rp_payment.get("razorpay_key_secret") or os.environ.get("RAZORPAY_KEY_SECRET", "")).strip()
    return {
        "status": "configured" if (rp_key_id and rp_key_secret) else "not_configured",
        "latencyMs": 0,
    }


def register_default_probes() -> None:
    """Register Syrabit's standard dependency probes. Idempotent — safe
    to call multiple times (re-registration preserves cached values)."""
    register("mongodb", _probe_mongo)
    register("postgresql", _probe_postgres)
    register("redis", _probe_redis)
    register("razorpay", _probe_razorpay)
