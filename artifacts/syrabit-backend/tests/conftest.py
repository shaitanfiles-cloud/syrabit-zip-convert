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


_DEPS_KEY = "deps"
_SNAPSHOT_ATTRS = ("db", "is_mongo_available", "supa")


@pytest.fixture(autouse=True)
def _reset_test_stub_state():
    """Snapshot/restore ``sys.modules['deps']`` around every test so
    one test's pollution cannot bleed into another.

    Three layers of protection, in order:

    1. **Module identity in ``sys.modules``.** If a test deletes
       ``sys.modules['deps']``, swaps it for a different module
       object, or installs the stub when no module was present
       before, we restore the *exact same module object* (or absence
       thereof) that existed pre-test. This is the canonical fix for
       the cross-test contamination pattern Task #469 targets.

    2. **Module-attribute identity.** Even within the same module
       object, tests like ``test_bing_keyword_pipeline.py`` reassign
       ``deps.db = MagicMock()`` directly (without ``monkeypatch``).
       We snapshot the key stub attributes and restore them.

    3. **Mock call history.** Call counts / args accumulate across
       the session, making ``assert_called_once``-style assertions
       brittle. We call ``reset_mock(return_value=False,
       side_effect=False)`` on the (restored) ``db`` to clear history
       while preserving any ``side_effect`` / ``return_value``
       deliberately set by the next test.

    Only touches the stub installed by ``tests._deps_stub``
    (recognised via the ``_is_syrabit_test_stub`` marker). The real
    ``deps`` module — if a test happens to be running with production
    deps loaded — is left completely alone (no reset, no attribute
    overwrite).
    """
    # --- Pre-test snapshot ---
    deps_present_pre = _DEPS_KEY in sys.modules
    deps_module_pre = sys.modules.get(_DEPS_KEY)
    is_stub_pre = bool(getattr(deps_module_pre, "_is_syrabit_test_stub", False))
    attr_snapshot = None
    if is_stub_pre:
        attr_snapshot = {
            attr: getattr(deps_module_pre, attr, None)
            for attr in _SNAPSHOT_ATTRS
        }

    yield

    # --- Post-test restore ---

    # 1. Restore module identity in sys.modules.
    deps_module_post = sys.modules.get(_DEPS_KEY)
    if deps_module_post is not deps_module_pre:
        if deps_present_pre:
            sys.modules[_DEPS_KEY] = deps_module_pre  # type: ignore[assignment]
        else:
            sys.modules.pop(_DEPS_KEY, None)

    # 2. Only touch our stub. The real production module is off-limits.
    deps_now = sys.modules.get(_DEPS_KEY)
    if deps_now is None or not getattr(deps_now, "_is_syrabit_test_stub", False):
        return

    # 3. Restore attributes a test may have reassigned on the stub.
    if attr_snapshot is not None:
        for attr, original in attr_snapshot.items():
            if original is None:
                continue
            if getattr(deps_now, attr, None) is not original:
                try:
                    setattr(deps_now, attr, original)
                except Exception:
                    pass

    # 4. Clear accumulated call history on the (restored) db mock.
    db = getattr(deps_now, "db", None)
    if db is None:
        return
    try:
        db.reset_mock(return_value=False, side_effect=False)
    except Exception:
        # MagicMock subclasses occasionally raise on reset_mock when a
        # test has replaced an attribute with a non-Mock value
        # (e.g. db.foo = "literal"). Don't fail other tests on that —
        # the stub still satisfies the _MotorDbMock awaitability
        # contract for subsequent tests.
        pass
