"""Task #678 — verify the ``/healthz/ai`` endpoint flips between
200 and 503 based on the cached Vertex/Gemini probe result.

We exercise two layers:

1. ``vertex_health_cache.healthz_ai_response()`` directly — proves the
   200/503 + body shape contract that Railway's healthcheck depends on.
2. The route source in ``server.py`` — pure AST assertion that the
   ``/healthz/ai`` route is actually wired and delegates to the cache
   helper. We do not import ``server.py`` (it boots Mongo / Vertex /
   CF clients and ``sys.exit``s on missing prod env vars), matching
   the pattern in ``test_vertex_startup_probe.py``.
"""
from __future__ import annotations

import ast
import pathlib
import time

import pytest

import vertex_health_cache


SERVER_PY = pathlib.Path(__file__).resolve().parent.parent / "server.py"


@pytest.fixture(autouse=True)
def _reset_cache():
    vertex_health_cache.reset()
    yield
    vertex_health_cache.reset()


# ---------------------------------------------------------------------------
# 1. Response helper contract
# ---------------------------------------------------------------------------


def test_returns_503_when_no_probe_has_run_yet():
    """Until the startup probe completes, Railway must not consider the
    rollout healthy — otherwise a fresh deploy with broken Gemini would
    silently start serving traffic.
    """
    code, body = vertex_health_cache.healthz_ai_response()
    assert code == 503
    assert body["status"] == "unknown"


def test_returns_200_after_healthy_probe():
    vertex_health_cache.record(
        True, auth_mode="byok", via_cf_gateway=True, source="startup"
    )
    code, body = vertex_health_cache.healthz_ai_response()
    assert code == 200
    assert body["status"] == "ok"
    assert body["auth_mode"] == "byok"
    assert body["via_cf_gateway"] is True
    assert body["source"] == "startup"
    assert "age_s" in body and body["age_s"] >= 0
    assert "ttl_s" in body and body["ttl_s"] > 0


def test_flips_200_to_503_when_cached_probe_goes_unhealthy():
    """Done-looks-like requirement: the endpoint must flip 200 → 503
    when the cached probe result becomes unhealthy. Same cache, just a
    failing record overwriting a previously healthy one — exactly what
    the periodic re-probe does in production when Gemini breaks.
    """
    # First a healthy probe — endpoint is 200.
    vertex_health_cache.record(
        True, auth_mode="byok", via_cf_gateway=True, source="startup"
    )
    code_ok, _ = vertex_health_cache.healthz_ai_response()
    assert code_ok == 200

    # Then an unhealthy probe overwrites the cache.
    vertex_health_cache.record(
        False,
        reason="embeddings=False generation=True auth_mode='byok'",
        auth_mode="byok",
        via_cf_gateway=True,
        source="periodic",
    )
    code_bad, body_bad = vertex_health_cache.healthz_ai_response()
    assert code_bad == 503
    assert body_bad["status"] == "unhealthy"
    assert "embeddings=False" in body_bad["reason"]


def test_returns_503_when_cached_probe_is_stale():
    """If the periodic re-probe stops writing for any reason (stuck
    task, deadlocked worker), the cached "ok" must not lie forever.
    Past TTL the endpoint flips 503 so Railway notices.
    """
    vertex_health_cache.record(True, source="startup")
    snap = vertex_health_cache.snapshot()
    last_ts = snap["last_check_ts"]

    code, body = vertex_health_cache.healthz_ai_response(
        now=last_ts + 9999.0, ttl_s=60
    )
    assert code == 503
    assert body["status"] == "stale"
    assert body["age_s"] >= 60


def test_returns_503_when_unhealthy_even_within_ttl():
    vertex_health_cache.record(
        False, reason="vertex health_check raised: timeout", source="periodic"
    )
    code, body = vertex_health_cache.healthz_ai_response()
    assert code == 503
    assert body["status"] == "unhealthy"
    assert "timeout" in body["reason"]


# ---------------------------------------------------------------------------
# 2. Route is wired in server.py
# ---------------------------------------------------------------------------


def test_server_py_registers_healthz_ai_route():
    """The route must be defined on ``app`` and delegate to
    ``vertex_health_cache.healthz_ai_response`` — without that wiring
    the module-level cache is never read by Railway.
    """
    src = SERVER_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)

    found_route = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            # Looking for @app.get("/healthz/ai")
            func = deco.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Name)
                and func.value.id == "app"
                and deco.args
                and isinstance(deco.args[0], ast.Constant)
                and deco.args[0].value == "/healthz/ai"
            ):
                found_route = True
                body_src = ast.unparse(node)
                assert "vertex_health_cache" in body_src, (
                    "/healthz/ai handler must read from vertex_health_cache"
                )
                assert "healthz_ai_response" in body_src, (
                    "/healthz/ai handler must call healthz_ai_response()"
                )
    assert found_route, "Expected @app.get('/healthz/ai') route in server.py"


def test_startup_probe_writes_to_cache():
    """Probe source must call ``vertex_health_cache.record(...)`` so
    the endpoint has fresh data to serve.
    """
    src = SERVER_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_vertex_startup_probe":
            body = ast.unparse(node)
            assert "vertex_health_cache.record(" in body
            return
    pytest.fail("_vertex_startup_probe not found in server.py")


def test_periodic_probe_writes_to_cache():
    src = SERVER_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_vertex_periodic_probe_loop":
            body = ast.unparse(node)
            assert "vertex_health_cache.record(" in body
            return
    pytest.fail("_vertex_periodic_probe_loop not found in server.py")
