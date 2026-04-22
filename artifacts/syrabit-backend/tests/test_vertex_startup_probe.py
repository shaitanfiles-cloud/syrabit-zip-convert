"""Task #667 — verify the Gemini startup self-check hook.

Two guarantees:

1. **Registration**: the lifespan in ``server.py`` schedules
   ``_vertex_startup_probe`` as a background task on boot, so the probe
   actually runs after every Railway deploy.
2. **Failure path**: when ``vertex_services.health_check()`` reports
   ``embeddings`` or ``generation`` as ``False``, the probe emits exactly
   one ``ERROR`` log line containing the upstream failure reason — that
   line is what the on-call sees in deploy logs before any user-facing
   502.

To avoid importing ``server.py`` (which calls ``sys.exit(1)`` on missing
prod env vars and pulls in Mongo/Vertex/CF clients), we extract the
``_vertex_startup_probe`` function via ``ast`` and exec it in an isolated
namespace with stubbed ``vertex_services`` and ``logger`` symbols. The
hook-registration check is a pure source-level assertion against the
``lifespan`` function body.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import pathlib
import textwrap
from typing import Any

import pytest


SERVER_PY = pathlib.Path(__file__).resolve().parent.parent / "server.py"


def _server_module_ast() -> ast.Module:
    return ast.parse(SERVER_PY.read_text(encoding="utf-8"))


def _find_function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"async function {name!r} not found in server.py")


def _extract_probe_callable():
    """Return the live ``_vertex_startup_probe`` coroutine function and
    the stub-logger / stub-vertex_services it closes over, so a test can
    assert against captured log records.
    """
    tree = _server_module_ast()
    fn_node = _find_function(tree, "_vertex_startup_probe")

    src = textwrap.dedent(ast.get_source_segment(SERVER_PY.read_text(encoding="utf-8"), fn_node))

    stub_logger = logging.getLogger("syrabit.test.vertex_startup_probe")
    stub_logger.handlers.clear()
    stub_logger.setLevel(logging.DEBUG)
    stub_logger.propagate = False

    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):  # noqa: D401
            captured.append(record)

    stub_logger.addHandler(_Capture())

    namespace: dict[str, Any] = {"logger": stub_logger, "asyncio": asyncio}
    exec(compile(src, str(SERVER_PY), "exec"), namespace)
    return namespace["_vertex_startup_probe"], captured, namespace


# ---------------------------------------------------------------------------
# 1. Hook registration
# ---------------------------------------------------------------------------

def test_lifespan_schedules_vertex_startup_probe():
    """The ``lifespan`` body must contain
    ``asyncio.create_task(_vertex_startup_probe())`` — otherwise a
    deploy with broken Gemini credentials would stay silent until the
    first user-facing 502.
    """
    tree = _server_module_ast()
    lifespan = _find_function(tree, "lifespan")
    src = ast.unparse(lifespan)
    assert "asyncio.create_task(_vertex_startup_probe())" in src, (
        "Expected lifespan() to schedule _vertex_startup_probe as a "
        "background task; without it the boot self-check never runs."
    )


def test_vertex_startup_probe_is_defined_as_async():
    tree = _server_module_ast()
    fn = _find_function(tree, "_vertex_startup_probe")
    assert isinstance(fn, ast.AsyncFunctionDef)


# ---------------------------------------------------------------------------
# 2. Failure path logs at ERROR
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def test_probe_logs_error_when_embeddings_fail(monkeypatch):
    probe, captured, ns = _extract_probe_callable()

    class _StubVertex:
        @staticmethod
        async def health_check():
            return {
                "ok": False,
                "auth_mode": "byok",
                "via_cf_gateway": True,
                "embeddings": False,   # <- broken
                "generation": True,
                "reason": None,
            }

    import sys
    monkeypatch.setitem(sys.modules, "vertex_services", _StubVertex)

    _run(probe())

    errors = [r for r in captured if r.levelno == logging.ERROR]
    assert errors, "Expected an ERROR log when embeddings probe fails"
    assert "STARTUP-PROBE" in errors[0].getMessage()
    assert "embeddings=False" in errors[0].getMessage()


def test_probe_logs_error_when_generation_fails(monkeypatch):
    probe, captured, ns = _extract_probe_callable()

    class _StubVertex:
        @staticmethod
        async def health_check():
            return {
                "ok": False,
                "auth_mode": "service_account",
                "via_cf_gateway": False,
                "embeddings": True,
                "generation": False,   # <- broken
                "reason": None,
            }

    import sys
    monkeypatch.setitem(sys.modules, "vertex_services", _StubVertex)

    _run(probe())

    errors = [r for r in captured if r.levelno == logging.ERROR]
    assert errors, "Expected an ERROR log when generation probe fails"
    assert "generation=False" in errors[0].getMessage()


def test_probe_logs_error_with_reason_when_no_credential(monkeypatch):
    probe, captured, ns = _extract_probe_callable()

    class _StubVertex:
        @staticmethod
        async def health_check():
            return {
                "ok": False,
                "auth_mode": "none",
                "reason": "No credential available (set VERTEX_SERVICE_ACCOUNT, GEMINI_API_KEY, or CF AI Gateway BYOK).",
            }

    import sys
    monkeypatch.setitem(sys.modules, "vertex_services", _StubVertex)

    _run(probe())

    errors = [r for r in captured if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "No credential available" in errors[0].getMessage()


def test_probe_does_not_log_error_when_healthy(monkeypatch):
    probe, captured, ns = _extract_probe_callable()

    class _StubVertex:
        @staticmethod
        async def health_check():
            return {
                "ok": True,
                "auth_mode": "byok",
                "via_cf_gateway": True,
                "embeddings": True,
                "generation": True,
            }

    import sys
    monkeypatch.setitem(sys.modules, "vertex_services", _StubVertex)

    _run(probe())

    errors = [r for r in captured if r.levelno == logging.ERROR]
    assert not errors, f"Healthy probe must not log ERROR, got: {[r.getMessage() for r in errors]}"


def test_probe_logs_error_on_timeout(monkeypatch):
    """A hanging upstream must not stall the probe — the 5s
    ``asyncio.wait_for`` guard must trip and emit a single ERROR line so
    the deploy log surfaces the unreachable Gemini quickly.
    """
    probe, captured, ns = _extract_probe_callable()

    class _StubVertex:
        @staticmethod
        async def health_check():
            await asyncio.sleep(60)  # never returns within the 5s budget
            return {"embeddings": True, "generation": True}

    import sys
    monkeypatch.setitem(sys.modules, "vertex_services", _StubVertex)

    # Patch wait_for to use a short fake timeout so the test stays fast,
    # while still exercising the real TimeoutError branch.
    real_wait_for = asyncio.wait_for

    async def _fast_wait_for(coro, timeout):  # noqa: ARG001
        return await real_wait_for(coro, timeout=0.05)

    monkeypatch.setattr(asyncio, "wait_for", _fast_wait_for)

    _run(probe())

    errors = [r for r in captured if r.levelno == logging.ERROR]
    assert errors, "Expected an ERROR log on probe timeout"
    assert "timed out" in errors[0].getMessage().lower()


def test_probe_swallows_exceptions_and_logs_error(monkeypatch):
    """A raising health_check (e.g. network blow-up) must not crash the
    background task — it must log a single ERROR and return cleanly so
    the rest of the API stays up.
    """
    probe, captured, ns = _extract_probe_callable()

    class _StubVertex:
        @staticmethod
        async def health_check():
            raise RuntimeError("boom: AI Gateway TLS handshake failed")

    import sys
    monkeypatch.setitem(sys.modules, "vertex_services", _StubVertex)

    _run(probe())  # must not raise

    errors = [r for r in captured if r.levelno == logging.ERROR]
    assert errors
    assert "boom" in errors[0].getMessage()
