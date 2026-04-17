"""Smoke tests guarding against import-time regressions in the
cms_sarvam_health route module.

Task #443: a wildcard `from config import *` re-exported `pathlib.Path`,
which shadowed the `Path` symbol from `fastapi`. The new revert handler
introduced in #431 used `Path(..., min_length=...)` and crashed at
*module import time* (so gunicorn never started). These tests fail loudly
if anyone shadows fastapi's Path again, or if the module otherwise stops
importing cleanly.
"""
from __future__ import annotations

import importlib


def test_cms_sarvam_health_imports_cleanly():
    mod = importlib.import_module("routes.cms_sarvam_health")
    assert hasattr(mod, "router"), "cms_sarvam_health must expose `router`"


def test_revert_endpoint_uses_fastapi_path_and_is_registered():
    """The /admin/assamese-purity/audit/{audit_id}/revert handler must
    use fastapi.Path for its path parameter, not pathlib.Path. We verify
    by checking that *some* fastapi.Path-bound symbol exists in the
    module namespace and that the route is actually registered.

    We deliberately do NOT assert anything about the bare `Path` name in
    this module: today it's shadowed by `from config import *` to
    pathlib.Path, but a future cleanup of that wildcard import is a
    legitimate refactor and shouldn't break this guard.
    """
    from fastapi import Path as RealFastAPIPath

    mod = importlib.import_module("routes.cms_sarvam_health")

    # At least one symbol in the module must be bound to fastapi.Path,
    # otherwise the revert handler can't possibly be using it.
    fastapi_path_aliases = [
        name for name, val in vars(mod).items() if val is RealFastAPIPath
    ]
    assert fastapi_path_aliases, (
        "No symbol in routes.cms_sarvam_health is bound to fastapi.Path. "
        "If you removed the FastAPIPath alias, make sure fastapi's Path "
        "is no longer shadowed by `from config import *` (pathlib.Path)."
    )

    routes = {getattr(r, "path", None) for r in mod.router.routes}
    assert "/admin/assamese-purity/audit/{audit_id}/revert" in routes, (
        "Revert endpoint missing from router"
    )
