"""Backend test configuration.

Task #469 — autouse fixture that resets the synthetic ``deps`` stub
between tests so call-history mutations cannot bleed across files.

The stub itself (see ``tests/_deps_stub.py``) now uses ``_MotorDbMock`` /
``_MotorCollectionMock`` so every call to ``await db.<coll>.<method>(...)``
returns an ``AsyncMock`` coroutine regardless of which test ran first.
What this fixture adds on top is the call-history reset: even though the
mock structure is robust, ``mock.call_args`` and ``mock.call_count``
would otherwise accumulate across the whole pytest session, making
``assert_called_once`` style assertions brittle.

Production ``deps`` (the real module, when imported) is intentionally
left alone — we recognise the stub by the ``_is_syrabit_test_stub``
marker.
"""
import os
import sys

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture(autouse=True)
def _reset_test_stub_state():
    """Snapshot/restore the synthetic ``deps`` stub around every test
    so one test's mutations cannot bleed into another.

    Two things are protected:

    1. **Module-attribute identity.** Some tests (e.g.
       ``test_bing_keyword_pipeline.py``) reassign ``deps.db = MagicMock()``
       directly instead of using ``monkeypatch.setattr`` — that mutation
       persists for the rest of the pytest session and breaks anything
       later that relied on the stub's ``_MotorDbMock`` ``await``-able
       behaviour. We snapshot ``deps.db`` (and ``deps.is_mongo_available``)
       before each test and restore them after.

    2. **Mock call history.** Even if no test reassigns ``deps.db``, its
       ``call_args`` / ``call_count`` accumulate across the session,
       making ``assert_called_once``-style assertions brittle. We call
       ``reset_mock(return_value=False, side_effect=False)`` after each
       test to clear history but preserve any ``side_effect`` /
       ``return_value`` a test has deliberately set.

    Only touches the stub installed by ``tests._deps_stub`` (recognised
    via the ``_is_syrabit_test_stub`` marker). The real ``deps`` module
    — if a test happens to be running with production deps loaded — is
    left completely alone.
    """
    deps_pre = sys.modules.get("deps")
    snapshot = None
    if deps_pre is not None and getattr(deps_pre, "_is_syrabit_test_stub", False):
        snapshot = {
            "db": getattr(deps_pre, "db", None),
            "is_mongo_available": getattr(deps_pre, "is_mongo_available", None),
        }

    yield

    deps_post = sys.modules.get("deps")
    if deps_post is None or not getattr(deps_post, "_is_syrabit_test_stub", False):
        return

    # 1. Restore module attributes if the test reassigned them.
    if snapshot is not None:
        for attr, original in snapshot.items():
            if getattr(deps_post, attr, None) is not original and original is not None:
                try:
                    setattr(deps_post, attr, original)
                except Exception:
                    pass

    # 2. Clear accumulated call history on the (restored) db mock.
    db = getattr(deps_post, "db", None)
    if db is None:
        return
    try:
        db.reset_mock(return_value=False, side_effect=False)
    except Exception:
        # MagicMock subclasses occasionally raise on reset_mock when a
        # test has replaced an attribute with a non-Mock value
        # (e.g. db.foo = "literal"). Don't fail other tests on that —
        # the stub will still be functional for awaiting motor methods
        # because of the _MotorDbMock subclass guarantees.
        pass
