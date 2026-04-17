"""Shared test helper: install a fully-populated stub `deps` module.

The backend's `deps` module exports many top-level names (db, redis_client,
security, logger, supa, pg_pool, pwd_ctx, is_mongo_available,
mark_mongo_down, sarvam_*, _assert_not_cms_context, …) and pulling in the
real one at test-collection time triggers Mongo/Redis/Postgres connection
attempts.

Several test files therefore install a *stub* `deps` module via
`sys.modules["deps"] = stub_module` before importing the code under test.
The historical implementations only set `db` and `is_mongo_available`, so
when pytest later collected another test file whose import chain ran
`from deps import security, redis_client, logger ...` (via auth_deps),
the import failed with `cannot import name 'security' from 'deps'
(unknown location)` — sys.modules pollution from the first test broke
collection for everyone after it.

This helper centralises the stub and ensures it carries every name any
production module is known to import from `deps`. Call once at module
import time of a test that does not want the real deps.
"""
from __future__ import annotations

import logging
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock


def install_deps_stub(*, force: bool = False, db: Any = None,
                      is_mongo_available_value: bool = False) -> types.ModuleType:
    """Install a stub `deps` module covering every name the backend imports.

    Parameters
    ----------
    force:
        If True, replace any existing `deps` entry (real or stub). Default
        False — leave whatever is already loaded alone (so a test that ran
        first wins, just like the historical pattern).
    db:
        Optional MagicMock-style stand-in for `deps.db`. If None a fresh
        MagicMock is created.
    is_mongo_available_value:
        Return value for the async `is_mongo_available()` callable.

    Returns
    -------
    The stub module that was installed (or the pre-existing module if
    `force` was False and one already lived in sys.modules).
    """
    if "deps" in sys.modules and not force:
        return sys.modules["deps"]

    deps = types.ModuleType("deps")

    # Core mongo handle + availability probe
    deps.db = db if db is not None else MagicMock()
    deps.is_mongo_available = AsyncMock(return_value=is_mongo_available_value)
    deps.mark_mongo_down = MagicMock()

    # Redis / auth / supa surface — every name some production module
    # currently does `from deps import X`. Anything missing here will
    # surface as a collection-time ImportError in pytest.
    deps.redis_client = None
    deps.supa = None
    deps.pg_pool = None
    deps.pwd_ctx = MagicMock()

    try:
        from fastapi.security import HTTPBearer  # local import keeps stub light
        deps.security = HTTPBearer(auto_error=False)
    except Exception:
        deps.security = MagicMock()

    deps.logger = logging.getLogger("tests.deps_stub")

    # Sarvam clients — present so `from deps import sarvam_*` imports work.
    deps.sarvam_client = None
    deps.sarvam_translate_client = None
    deps.sarvam_llm_client = None
    deps.sarvam_client_direct = None
    deps.sarvam_llm_client_direct = None

    # Misc helpers production code occasionally pulls.
    def _noop_assert_not_cms_context(*_a, **_kw):
        return None

    deps._assert_not_cms_context = _noop_assert_not_cms_context
    deps._cms_request_ctx = None
    deps._init_pg_pool = AsyncMock()
    deps._sarvam_headers = lambda *a, **kw: {}
    deps._sarvam_timeout = None
    deps._sarvam_llm_timeout = None
    deps._sarvam_pool_limits = None

    # Supabase client factory — admin_monetization imports `_create_supa`
    # explicitly (used by /admin/supabase/test and /admin/supabase/apply).
    deps._create_supa = MagicMock()

    sys.modules["deps"] = deps
    return deps
