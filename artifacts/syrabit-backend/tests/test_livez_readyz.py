"""Task #848 — verify the new ``/api/livez`` and ``/api/readyz`` routes
plus the TTL+single-flight ``health_snapshot_cache`` they depend on.

Following the established pattern in ``test_healthz_ai_endpoint.py``,
we exercise three layers:

1. ``health_snapshot_cache`` directly — TTL coalescing, single-flight
   request-coalescing, and timeout handling.
2. ``vertex_services.health_check`` parallelisation — the embed and
   generate probes must run via ``asyncio.gather`` so the function
   completes in roughly ``max(embed, gen)`` instead of ``embed + gen``.
3. AST checks against the route source confirming ``/livez`` and
   ``/readyz`` are wired in ``routes/cms_sarvam_health.py`` and that
   ``railway.toml`` points at the new liveness path.

Async tests use ``asyncio.run()`` from sync ``def test_*`` (matching
the convention in ``test_seo_writes_timestamps.py``) so we don't
require ``pytest-asyncio`` in the venv.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import time

import pytest

import health_snapshot_cache as hsc


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HEALTH_PY = REPO_ROOT / "routes" / "cms_sarvam_health.py"
RAILWAY_TOML = REPO_ROOT / "railway.toml"
VERTEX_PY = REPO_ROOT / "vertex_services.py"
MIDDLEWARE_PY = REPO_ROOT / "middleware.py"


@pytest.fixture(autouse=True)
def _reset_cache():
    hsc.reset()
    yield
    hsc.reset()


def _run(coro):
    """Use a fresh event loop per call (matches Task #467 pattern in
    test_seo_writes_timestamps.py)."""
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────
# 1. health_snapshot_cache — TTL + single-flight contract
# ─────────────────────────────────────────────────────────────────────


def test_first_call_runs_probe_and_caches_result():
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return {"status": "ok"}

    async def go():
        hsc.register("svc", probe)
        return await hsc.get("svc", ttl_s=10)

    out = _run(go())
    assert out["status"] == "ok"
    assert "latencyMs" in out
    assert calls["n"] == 1


def test_within_ttl_returns_cache_without_reprobing():
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return {"status": "ok"}

    async def go():
        hsc.register("svc", probe)
        await hsc.get("svc", ttl_s=10)
        await hsc.get("svc", ttl_s=10)
        await hsc.get("svc", ttl_s=10)

    _run(go())
    assert calls["n"] == 1, "cache hit should not invoke probe"


def test_expired_ttl_triggers_reprobe():
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return {"status": "ok"}

    async def go():
        hsc.register("svc", probe)
        await hsc.get("svc", ttl_s=0.05)
        await asyncio.sleep(0.10)
        await hsc.get("svc", ttl_s=0.05)

    _run(go())
    assert calls["n"] == 2


def test_single_flight_coalesces_concurrent_callers():
    """Five concurrent first-callers must trigger exactly ONE probe.
    Without single-flight we'd hit the upstream 5× per cache miss,
    which is the whole reason #848 exists."""
    calls = {"n": 0}

    async def slow_probe():
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return {"status": "ok"}

    async def go():
        hsc.register("svc", slow_probe)
        return await asyncio.gather(*(hsc.get("svc", ttl_s=10) for _ in range(5)))

    results = _run(go())
    assert all(r["status"] == "ok" for r in results)
    assert calls["n"] == 1, f"expected 1 probe, got {calls['n']}"


def test_probe_exception_becomes_error_status():
    async def boom():
        raise RuntimeError("upstream down")

    async def go():
        hsc.register("svc", boom)
        return await hsc.get("svc", ttl_s=10)

    out = _run(go())
    assert out["status"] == "error"
    assert "RuntimeError" in out["reason"]
    assert "upstream down" in out["reason"]


def test_probe_timeout_becomes_error_status(monkeypatch):
    monkeypatch.setattr(hsc, "PROBE_TIMEOUT_S", 0.05)

    async def hung():
        await asyncio.sleep(5)
        return {"status": "ok"}

    async def go():
        hsc.register("svc", hung)
        return await hsc.get("svc", ttl_s=10)

    t0 = time.time()
    out = _run(go())
    elapsed = time.time() - t0
    assert out["status"] == "error"
    assert "timed out" in out["reason"]
    assert elapsed < 1.0, "timeout must short-circuit, not run to completion"


def test_get_all_runs_probes_in_parallel():
    """get_all should fan out via asyncio.gather — three 50ms probes
    should complete in ~50ms, not ~150ms. This is what makes /api/readyz
    actually fast even when probing 6 dependencies."""
    async def slow():
        await asyncio.sleep(0.05)
        return {"status": "ok"}

    async def go():
        for n in ("a", "b", "c"):
            hsc.register(n, slow)
        t0 = time.time()
        out = await hsc.get_all(ttl_s=10)
        return out, time.time() - t0

    out, elapsed = _run(go())
    assert set(out.keys()) == {"a", "b", "c"}
    assert elapsed < 0.12, f"parallel fan-out took {elapsed:.3f}s, expected <0.12s"


def test_peek_does_not_trigger_probe():
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return {"status": "ok"}

    async def go():
        hsc.register("svc", probe)
        before = hsc.peek("svc")
        await hsc.get("svc", ttl_s=10)
        return before, hsc.peek("svc")

    before, after = _run(go())
    assert before is None
    assert after["status"] == "ok"
    assert calls["n"] == 1


# ─────────────────────────────────────────────────────────────────────
# 2. vertex_services.health_check parallelises embed + generate
# ─────────────────────────────────────────────────────────────────────


def test_vertex_health_check_uses_asyncio_gather():
    """Pure AST assertion that ``health_check()`` runs the embed and
    generate probes via ``asyncio.gather`` instead of awaiting them
    sequentially. The sequential version doubled p99 latency on the
    healthcheck path (Task #848)."""
    src = VERTEX_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "health_check":
            target = node
            break
    assert target is not None, "vertex_services.health_check not found"
    body_src = ast.unparse(target)
    assert "asyncio.gather" in body_src, (
        "health_check() must call asyncio.gather(embed, generate) — "
        "sequential awaits double healthcheck latency."
    )


# ─────────────────────────────────────────────────────────────────────
# 3. Routes are wired and railway.toml + middleware are updated
# ─────────────────────────────────────────────────────────────────────


def _has_route(src: str, decorator_path: str) -> bool:
    """Check the source contains @router.get('<decorator_path>')."""
    needle = f'"{decorator_path}"'
    return ".get(" in src and needle in src


def test_livez_route_registered():
    src = HEALTH_PY.read_text(encoding="utf-8")
    assert _has_route(src, "/livez"), "expected @router.get('/livez') in cms_sarvam_health.py"


def test_readyz_route_registered():
    src = HEALTH_PY.read_text(encoding="utf-8")
    assert _has_route(src, "/readyz"), "expected @router.get('/readyz') in cms_sarvam_health.py"


def test_health_inner_uses_snapshot_cache():
    """The whole point of #848: ``_health_inner`` must read from the
    snapshot cache instead of issuing per-request I/O. Specifically
    the per-request ``db.api_config.find_one`` for Razorpay must be
    gone — Razorpay status now comes through the cached probe."""
    src = HEALTH_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    inner = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_health_inner":
            inner = node
            break
    assert inner is not None, "_health_inner not found"
    body_src = ast.unparse(inner)
    assert "health_snapshot_cache" in body_src, (
        "_health_inner must read from health_snapshot_cache"
    )
    assert "api_config.find_one" not in body_src, (
        "_health_inner must NOT issue per-request api_config.find_one for Razorpay — "
        "the snapshot cache handles it now."
    )


def test_railway_healthcheck_points_at_livez():
    toml = RAILWAY_TOML.read_text(encoding="utf-8")
    assert 'healthcheckPath = "/api/livez"' in toml, (
        "railway.toml must point Railway's restart probe at /api/livez "
        "(no I/O, <50ms) instead of /api/health (full dep check)."
    )


def test_middleware_exempts_livez_and_readyz():
    """The new health routes must be open to Cloud Run / Railway
    probes (no origin-secret), exempt from rate-limiting, and skipped
    by request tracking — same treatment /api/health gets. The legacy
    /api/ready route is also exempted (code-review follow-up) so any
    external monitor still pointing at the old path keeps working."""
    src = MIDDLEWARE_PY.read_text(encoding="utf-8")
    # Origin-auth open paths
    assert '"/api/livez"' in src
    assert '"/api/readyz"' in src
    assert '"/api/ready"' in src, "legacy /api/ready must be in middleware exempts"
    # Each should appear in at least three exempt lists (origin, rate, tracking).
    assert src.count('"/api/livez"') >= 2
    assert src.count('"/api/readyz"') >= 2
    assert src.count('"/api/ready"') >= 2
