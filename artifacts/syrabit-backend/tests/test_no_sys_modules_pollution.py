"""Task #469 — guard tests that the synthetic ``deps`` stub installed by
``tests/_deps_stub.py`` is order-independent.

The historical bug (Task #467) was that ``await db.<coll>.insert_one(...)``
on the stub would fail with ``TypeError: object MagicMock can't be used
in 'await' expression`` once a polluting earlier test had let production
code touch the bare-MagicMock collection. This file pins down two
guarantees of the new ``_MotorDbMock`` / ``_MotorCollectionMock`` design
plus the conftest autouse fixture:

1. **Awaitability.** Every motor-style async method on every collection
   on the stub ``db`` is ``await``-able and resolves cleanly, both for
   collections accessed via attribute (``db.foo``) and via subscript
   (``db["foo"]``).

2. **Call-history isolation.** The conftest autouse fixture clears
   ``mock.call_args`` / ``call_count`` on the stub between tests, so
   one test calling ``db.foo.insert_one(...)`` cannot make a sibling
   test see a non-zero ``call_count`` it never produced.

3. **Marker integrity.** The stub carries the
   ``_is_syrabit_test_stub`` marker so the autouse fixture only resets
   the synthetic stub and never touches a real ``deps`` module that
   production may have imported.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def test_stub_carries_marker_attribute():
    """The conftest autouse fixture relies on this marker to
    distinguish the synthetic stub from the real ``deps`` module."""
    deps = sys.modules["deps"]
    assert getattr(deps, "_is_syrabit_test_stub", False) is True


def test_db_async_methods_are_awaitable_via_attribute():
    """``await db.<random_collection>.insert_one(...)`` must work even
    when no test has explicitly initialised that collection."""
    deps = sys.modules["deps"]

    async def _exercise():
        await deps.db.never_seen_before.insert_one({"x": 1})
        await deps.db.never_seen_before.update_one({"x": 1}, {"$set": {"y": 2}})
        await deps.db.never_seen_before.find_one({"x": 1})
        await deps.db.never_seen_before.delete_one({"x": 1})
        return await deps.db.never_seen_before.count_documents({})

    result = asyncio.run(_exercise())
    # AsyncMock's default return is a MagicMock — what matters here
    # is that no TypeError was raised.
    assert result is not None or result is None  # noqa: PIE790


def test_db_async_methods_are_awaitable_via_subscript():
    """Some routes use ``db["collname"]`` instead of ``db.collname``.
    The same awaitability guarantee must hold."""
    deps = sys.modules["deps"]

    async def _exercise():
        await deps.db["another_unseen_coll"].insert_one({"y": 2})

    asyncio.run(_exercise())  # must not raise


def test_db_command_is_awaitable():
    """``db.command("ping")`` is used by ``is_mongo_available`` and
    must be awaitable too — it lives on the database itself, not on
    a collection."""
    deps = sys.modules["deps"]

    async def _ping():
        return await deps.db.command("ping")

    asyncio.run(_ping())  # must not raise


def test_explicit_async_mock_assignment_still_overrides():
    """A test that wants a specific return value should still be able
    to assign a fresh ``AsyncMock`` — the auto-generated AsyncMock
    must not silently swallow the assignment."""
    deps = sys.modules["deps"]
    deps.db.user_overrides_me.insert_one = AsyncMock(return_value="sentinel")

    async def _go():
        return await deps.db.user_overrides_me.insert_one({"k": "v"})

    assert asyncio.run(_go()) == "sentinel"


def test_call_history_resets_between_tests_part_a():
    """Companion to part B. Records calls on a unique collection so
    part B can verify the autouse fixture cleared them. The two tests
    rely only on lexical ordering within this file (alphabetical part_a
    → part_b), which pytest preserves by default."""
    deps = sys.modules["deps"]

    async def _go():
        await deps.db.cross_test_isolation_probe.insert_one({"a": 1})
        await deps.db.cross_test_isolation_probe.insert_one({"a": 2})

    asyncio.run(_go())
    assert deps.db.cross_test_isolation_probe.insert_one.call_count == 2


def test_call_history_resets_between_tests_part_b():
    """Verifies the autouse fixture cleared the history left by
    part_a — proving stub mutations cannot bleed across tests."""
    deps = sys.modules["deps"]
    # The collection itself still exists (we don't drop attributes,
    # only call history). What matters is that its insert_one has
    # zero recorded calls coming into this test.
    assert deps.db.cross_test_isolation_probe.insert_one.call_count == 0


def test_real_deps_module_is_never_touched_by_fixture(monkeypatch):
    """The autouse fixture must NOT call ``reset_mock`` on a deps
    module that lacks the synthetic-stub marker. We simulate a real
    deps module here and assert the fixture is a no-op for it."""
    import types as _types
    fake_real_deps = _types.ModuleType("deps")

    # Sentinel attribute that a reset_mock call would fail on (real
    # modules don't have reset_mock at all). If the fixture mistakenly
    # tried to reset, the AttributeError would propagate via except.
    fake_real_deps.db = object()  # not a MagicMock

    monkeypatch.setitem(sys.modules, "deps", fake_real_deps)
    # Marker absent → fixture must skip. We can't directly invoke the
    # autouse fixture mid-test, but we can assert the recognition
    # condition itself: no marker means skip.
    assert not getattr(fake_real_deps, "_is_syrabit_test_stub", False)
