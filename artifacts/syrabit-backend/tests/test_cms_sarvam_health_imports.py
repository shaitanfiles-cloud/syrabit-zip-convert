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


def test_revert_endpoint_path_param_is_fastapi_path():
    """The /admin/assamese-purity/audit/{audit_id}/revert handler must
    use fastapi.Path (aliased as FastAPIPath) for its path parameter,
    not pathlib.Path. We verify by ensuring the import alias is in place
    and that the route is actually registered with the expected path.
    """
    import pathlib

    from fastapi import Path as RealFastAPIPath

    mod = importlib.import_module("routes.cms_sarvam_health")

    assert hasattr(mod, "FastAPIPath"), (
        "FastAPIPath alias missing from routes.cms_sarvam_health — fastapi.Path "
        "is shadowed by `from config import *` re-exporting pathlib.Path."
    )
    assert mod.FastAPIPath is RealFastAPIPath, (
        "FastAPIPath in cms_sarvam_health is not fastapi.Path"
    )

    routes = {getattr(r, "path", None) for r in mod.router.routes}
    assert "/admin/assamese-purity/audit/{audit_id}/revert" in routes, (
        "Revert endpoint missing from router"
    )

    # Sanity: the wildcard import did re-export pathlib.Path under the
    # bare name `Path`, so future authors must keep using FastAPIPath.
    assert mod.Path is pathlib.Path, (
        "If this fails, the wildcard shadow is gone — collapse FastAPIPath "
        "back to Path and delete this assertion."
    )
