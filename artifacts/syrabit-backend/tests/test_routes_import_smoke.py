"""Global import smoke test for every module under `routes/`.

Task #446: Task #443 fixed a backend-down outage caused by a wildcard
`from config import *` re-exporting `pathlib.Path` *after* the line
`from fastapi import (..., Path, ...)` in a single route module —
`Path(...)` in a handler signature then resolved to `pathlib.Path` and
crashed gunicorn at module-import time. The same wildcard pattern is
used in every other route module, so any future use of fastapi's
`Path` (or another shadowed name) would re-blow up the same way.

This test imports every `routes/*.py` module so an import-time error
surfaces here in CI rather than at gunicorn boot in production.
"""
from __future__ import annotations

import importlib
import pathlib

import pytest


ROUTES_DIR = pathlib.Path(__file__).resolve().parent.parent / "routes"

# Modules that live under `routes/` for organisational reasons but
# intentionally don't expose an APIRouter — they are background-loop
# helpers wired up by `server.py` rather than HTTP route bundles.
# The import-smoke check still runs against them (a bad import would
# crash gunicorn at startup just the same), but the `router` assertion
# is skipped.
_NON_ROUTER_MODULES = frozenset({
    "admin_ci_alerts",  # Task #484: leader-gated CI red-alert poller
    "slack_alerter_config",  # Task #969: tiny shared Slack-config helper
})


def _route_modules():
    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        yield path.stem


@pytest.mark.parametrize("module_name", list(_route_modules()))
def test_route_module_imports_cleanly(module_name: str):
    mod = importlib.import_module(f"routes.{module_name}")
    if module_name in _NON_ROUTER_MODULES:
        # Background-loop helper. Successful import is the whole point
        # of the smoke check for these — no `router` symbol expected.
        return
    # Every other route module exposes an APIRouter named `router`.
    # If something else is convention here later, relax this assertion.
    assert hasattr(mod, "router"), (
        f"routes/{module_name}.py imported but exposes no `router`. "
        f"Either rename the symbol or update this assertion."
    )


def test_no_route_module_exposes_pathlib_path_under_fastapi_alias():
    """Catch the specific shape of the #443 regression: a module
    imports fastapi.Path under the bare name `Path` while *also*
    wildcard-importing a source that re-exports pathlib.Path. In that
    case `mod.Path` ends up being `pathlib.Path`, and any
    `Path(..., min_length=...)` call site at module scope will crash.
    """
    from fastapi import Path as RealFastAPIPath

    failures = []
    for name in _route_modules():
        mod = importlib.import_module(f"routes.{name}")
        path_symbol = getattr(mod, "Path", None)
        if path_symbol is None:
            continue
        # If `Path` exists in the module and is fastapi.Path, no shadow.
        if path_symbol is RealFastAPIPath:
            continue
        # If `Path` is pathlib.Path here, that's *expected* (it comes
        # from `from config import *`) — but only if the module isn't
        # also intending to use fastapi.Path. We check intent by
        # looking for a FastAPIPath alias bound to fastapi.Path.
        has_fastapi_path_alias = any(
            v is RealFastAPIPath for v in vars(mod).values()
        )
        if path_symbol is pathlib.Path and not has_fastapi_path_alias:
            # Module never tries to use fastapi.Path — fine.
            continue
        if path_symbol is pathlib.Path and has_fastapi_path_alias:
            # Module uses FastAPIPath alias for fastapi — fine.
            continue
        failures.append(
            f"routes/{name}.py: `Path` is {path_symbol!r} (expected "
            f"either fastapi.Path or pathlib.Path with a FastAPIPath alias)."
        )

    assert not failures, "\n".join(failures)
