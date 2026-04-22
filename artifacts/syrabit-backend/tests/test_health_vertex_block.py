"""Task #691 — verify the cached Vertex/Gemini probe is folded into
the human-readable ``/health`` endpoint.

Two layers, mirroring the strategy used by ``test_healthz_ai_endpoint.py``:

1. **Helper contract** — ``_vertex_block_for_health()`` is the small,
   pure helper the ``/health`` route now consumes. We exercise it
   directly across the four cache states (no probe yet, healthy,
   stale, unhealthy) and assert both the returned block shape and the
   ``ok`` flag that decides whether ``/health → status`` flips to
   ``degraded``.

2. **Wiring** — AST assertion that ``_health_inner`` actually calls
   ``_vertex_block_for_health()`` and includes the resulting block
   under ``dependencies.vertex``. We do not import the route module
   (it pulls in mongo / redis / vertex_services / gunicorn config),
   matching the pattern used by the existing periodic-probe tests.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import types

import pytest


BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
ROUTE_PY = BACKEND_DIR / "routes" / "cms_sarvam_health.py"


# ---------------------------------------------------------------------------
# Direct helper test (loads only the helper, not the full module)
# ---------------------------------------------------------------------------

def _load_helper():
    """Extract ``_vertex_block_for_health`` from the route source and
    exec it with only ``vertex_health_cache`` available — avoids
    importing the full route module (which boots vertex_services,
    mongo, etc.).
    """
    src = ROUTE_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_vertex_block_for_health":
            fn_src = ast.get_source_segment(src, node)
            ns: dict = {}
            exec(compile(fn_src, str(ROUTE_PY), "exec"), ns)
            return ns["_vertex_block_for_health"]
    pytest.fail("_vertex_block_for_health not found in route source")


@pytest.fixture
def helper():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import vertex_health_cache
    vertex_health_cache.reset()
    yield _load_helper()
    vertex_health_cache.reset()


def test_block_unknown_when_no_probe_run(helper):
    """No probe has run yet → block reports ``unknown`` and the
    aggregate ``ok`` flag stays True so a fresh rollout doesn't flap
    the page yellow before the first probe interval completes.
    """
    block, ok = helper()
    assert block["status"] == "unknown"
    assert ok is True


def test_block_ok_when_cached_probe_healthy(helper):
    import vertex_health_cache
    vertex_health_cache.record(
        True, auth_mode="byok", via_cf_gateway=True, source="periodic"
    )
    block, ok = helper()
    assert block["status"] == "ok"
    assert block["auth_mode"] == "byok"
    assert block["via_cf_gateway"] is True
    assert block["consecutive_failures"] == 0
    assert block.get("reason") in (None, "")  # healthy → no reason
    assert ok is True


def test_block_unhealthy_drags_aggregate_to_degraded(helper):
    """Done-looks-like requirement: ``unhealthy`` flips the aggregate
    ``status`` to ``degraded``, the same way Mongo / Postgres outages
    do (helper returns ``ok=False``).
    """
    import vertex_health_cache
    vertex_health_cache.record(
        False,
        reason="embeddings=False generation=True",
        auth_mode="byok",
        via_cf_gateway=True,
        source="periodic",
        consecutive_failures=3,
    )
    block, ok = helper()
    assert block["status"] == "unhealthy"
    assert block["reason"] == "embeddings=False generation=True"
    assert block["consecutive_failures"] == 3
    assert ok is False, "unhealthy vertex must flip aggregate /health to degraded"


def test_block_stale_drags_aggregate_to_degraded(helper):
    """If the periodic re-probe stops writing, the cache flips to
    ``stale`` past the TTL — that must also flip /health to degraded.
    """
    import vertex_health_cache
    vertex_health_cache.record(True, source="startup")
    snap = vertex_health_cache.snapshot()
    # Force a stale read by mutating the timestamp far into the past.
    # Using the public API: re-record with an old ts.
    vertex_health_cache.record(
        True, source="startup", ts=snap["last_check_ts"] - 10**9
    )
    block, ok = helper()
    assert block["status"] == "stale"
    assert ok is False


# ---------------------------------------------------------------------------
# Wiring assertion — _health_inner must use the block + ok flag
# ---------------------------------------------------------------------------

def test_health_inner_includes_vertex_block_and_uses_flag():
    src = ROUTE_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_health_inner":
            body = ast.unparse(node)
            assert "_vertex_block_for_health(" in body, (
                "/health must call _vertex_block_for_health() so the cached "
                "Vertex/Gemini probe is surfaced in the dependencies block."
            )
            assert '"vertex": vertex_block' in body or "'vertex': vertex_block" in body, (
                "/health response must include a 'vertex' key under dependencies."
            )
            assert "vertex_ok" in body and "and vertex_ok" in body, (
                "vertex_ok must be folded into the critical_ok aggregate so "
                "an unhealthy/stale Vertex flips /health → status to 'degraded'."
            )
            return
    pytest.fail("_health_inner not found in cms_sarvam_health.py")
