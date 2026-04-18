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

Task #469 hardening
-------------------
The stub `db` is no longer a bare ``MagicMock``. Bare MagicMocks
auto-create child mocks of type ``MagicMock`` for any attribute, which
means a call like ``await db.indic_sanitize_runs.insert_one({...})``
raises ``TypeError: object MagicMock can't be used in 'await'
expression`` because the return value is a non-awaitable MagicMock. This
is exactly what caused two ``test_ai_chat_indic_route.py`` failures in
Task #467 — a polluting earlier test had let production code call an
async motor method on the stub, the resulting MagicMock got cached on
the collection, and every later test inherited it.

We replace the bare ``MagicMock`` with ``_MotorDbMock``, a MagicMock
subclass whose attribute access yields ``_MotorCollectionMock``
instances. ``_MotorCollectionMock`` is itself a MagicMock subclass that
returns ``AsyncMock`` for any name in ``_ASYNC_MOTOR_METHODS`` (the
canonical list of motor.AsyncIOMotorCollection async APIs we use).
Result: ``await db.<anything>.insert_one(...)`` always works, no matter
what ordering pytest collects tests in.

The stub also exposes a ``_is_syrabit_test_stub = True`` marker so the
conftest autouse fixture can recognise the stub (versus the real
``deps`` module that production may have imported) and reset its mock
call history between tests without disturbing real state.
"""
from __future__ import annotations

import logging
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock


# Async APIs on motor.motor_asyncio.AsyncIOMotorCollection that we
# actually exercise from production code. Anything in this set is
# returned as an AsyncMock by `_MotorCollectionMock` so that
# `await db.<anycoll>.<method>(...)` always works regardless of test
# ordering. Add new motor methods here if production starts using them.
_ASYNC_MOTOR_METHODS = frozenset({
    "insert_one", "insert_many",
    "update_one", "update_many",
    "delete_one", "delete_many",
    "find_one", "find_one_and_update", "find_one_and_delete",
    "find_one_and_replace", "replace_one",
    "count_documents", "estimated_document_count",
    "create_index", "create_indexes",
    "drop", "drop_index", "drop_indexes",
    "bulk_write", "distinct", "rename",
})

# Async APIs on motor.motor_asyncio.AsyncIOMotorDatabase itself
# (not on collections).
_ASYNC_MOTOR_DB_METHODS = frozenset({
    "command", "list_collection_names", "drop_collection",
    "create_collection",
})


class _MotorCollectionMock(MagicMock):
    """Auto-generates ``AsyncMock`` children for known motor coroutines
    so ``await db.<coll>.insert_one(...)`` is always valid."""

    def _get_child_mock(self, /, **kw):
        name = kw.get("name") or ""
        if name in _ASYNC_MOTOR_METHODS:
            return AsyncMock(**kw)
        return MagicMock(**kw)


class _MotorDbMock(MagicMock):
    """Stub for ``deps.db`` (motor.AsyncIOMotorDatabase).

    * ``db.<anything>``  →  ``_MotorCollectionMock`` (so its async methods
      auto-resolve to ``AsyncMock``).
    * ``db.command(...)``, ``db.list_collection_names()`` etc are also
      ``AsyncMock`` so awaiting them works.
    * ``db["collname"]`` (subscript access used by some routes) returns
      a ``_MotorCollectionMock`` too.
    """

    def _get_child_mock(self, /, **kw):
        name = kw.get("name") or ""
        if name in _ASYNC_MOTOR_DB_METHODS:
            return AsyncMock(**kw)
        # Default child of the db is a collection.
        return _MotorCollectionMock(**kw)

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        # MagicMock auto-creates ``__getitem__`` as its own bare child
        # MagicMock. We can't override the dunder by defining it in the
        # class body (MagicMock's metaclass intercepts magic-method
        # lookup at the instance level), but we *can* attach a
        # ``side_effect`` that routes subscript access through normal
        # attribute lookup so the ``_get_child_mock`` hook above kicks
        # in and ``db["coll"].insert_one(...)`` is awaitable.
        self.__getitem__.side_effect = lambda key: getattr(self, str(key))


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
        `_MotorDbMock` is created.
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

    # Task #469: marker so the conftest autouse fixture can recognise
    # the synthetic deps and reset its mock call history between tests
    # without touching the real production module.
    deps._is_syrabit_test_stub = True

    # Core mongo handle + availability probe
    deps.db = db if db is not None else _MotorDbMock()
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
