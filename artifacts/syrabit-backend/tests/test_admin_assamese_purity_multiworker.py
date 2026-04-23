"""Task #429 — multi-worker propagation integration test for the
Assamese-purity sanitiser override.

Task #422 introduced a 15s in-process refresh loop so PATCH/DELETE on
the override on one gunicorn worker eventually propagates to its
siblings. The single-worker tests in `test_admin_assamese_purity.py`
cover the loader function and one isolated tick. This file proves the
end-to-end contract:

  * Two API instances bound to the SAME mongo doc — one acting as the
    admin-facing worker (serves the PATCH/DELETE), one acting as a
    sibling worker (only runs the background refresh loop).
  * A PATCH on worker A is reflected in worker B's in-memory sanitiser
    state within the documented ~20s propagation budget.
  * The full DELETE + re-PATCH + DELETE sequence propagates within the
    same per-tick budget so no transition is silently dropped.

Worker isolation is simulated by snapshotting / restoring
`lang_sanitizer._RUNTIME_OVERRIDE` around each worker's actions, since
each gunicorn worker has its own copy of that module-level state in
production. The shared mongo doc is a stateful in-memory stub that
mirrors the subset of motor semantics the route + loader use.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────
# Shared "mongo" — both simulated workers point at the same doc.
# ──────────────────────────────────────────────────────────────────────
class _SharedMongoStub:
    """Minimal stand-in for `db.api_config` that two simulated workers
    can share. Implements only the subset of motor semantics used by
    the route handlers and loader: a single doc with `$set` / `$unset`
    updates and `find_one` projection."""

    def __init__(self) -> None:
        self._doc: dict = {}

    async def find_one(self, filter_, projection=None):
        if not self._doc:
            return None
        return dict(self._doc)

    async def update_one(self, filter_, update, upsert=False):
        for k, v in (update.get("$set") or {}).items():
            self._doc[k] = v
        for k in (update.get("$unset") or {}).keys():
            self._doc.pop(k, None)
        return None


def _shared_db():
    api_cfg = _SharedMongoStub()
    db = MagicMock()
    db.api_config = api_cfg
    # Audit / runs collections are best-effort; satisfy the calls but
    # don't track state — the propagation contract is mongo-side.
    coll = MagicMock()
    coll.insert_one = AsyncMock(return_value=None)
    coll.create_index = AsyncMock(return_value=None)
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    coll.find = MagicMock(return_value=cursor)
    db.__getitem__ = MagicMock(return_value=coll)
    return db, api_cfg


def _patch_db(db):
    """Routes do `from deps import db as _db` lazily — patch the source."""
    return patch("deps.db", db, create=True)


# ──────────────────────────────────────────────────────────────────────
# Worker isolation — snapshot/restore the in-memory override layer
# around each worker's actions so two "workers" running in the same
# test process don't trample each other's local sanitiser state.
# ──────────────────────────────────────────────────────────────────────
class _Worker:
    """One simulated gunicorn worker: owns its own snapshot of
    `lang_sanitizer._RUNTIME_OVERRIDE`. Use `activate()` to install
    this worker's snapshot as the live module state and capture any
    mutations back into the snapshot when control hands off."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._snapshot: dict | None = None
        self._active_depth = 0

    @contextlib.contextmanager
    def activate(self):
        import lang_sanitizer as _ls
        prev = _ls._RUNTIME_OVERRIDE
        _ls._RUNTIME_OVERRIDE = (
            dict(self._snapshot) if self._snapshot is not None else None
        )
        self._active_depth += 1
        try:
            yield
        finally:
            self._snapshot = (
                dict(_ls._RUNTIME_OVERRIDE)
                if _ls._RUNTIME_OVERRIDE is not None
                else None
            )
            self._active_depth -= 1
            _ls._RUNTIME_OVERRIDE = prev

    @property
    def override(self) -> dict | None:
        # While activated, the live module state IS this worker's
        # in-memory copy — read it directly so the test sees mutations
        # made by the refresh loop without waiting for context exit.
        if self._active_depth > 0:
            import lang_sanitizer as _ls
            ov = _ls._RUNTIME_OVERRIDE
            return dict(ov) if ov is not None else None
        return dict(self._snapshot) if self._snapshot is not None else None


def _make_app_client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.cms_sarvam_health import router
    from auth_deps import get_admin_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True}


@pytest.fixture(autouse=True)
def _reset_runtime_override():
    from lang_sanitizer import clear_runtime_override
    clear_runtime_override()
    yield
    clear_runtime_override()


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

# Documented propagation budget. The refresh loop runs every
# `_ASM_REFRESH_INTERVAL_SECONDS` (15s in prod) so one tick + jitter
# fits in 20s. The tests use a compressed interval to stay fast but
# pin the production constant to this same budget.
_PROPAGATION_BUDGET_SECONDS = 20.0


def test_production_refresh_interval_satisfies_propagation_budget():
    """Locks in the runbook promise: the in-process refresh interval
    must be small enough that one tick + jitter still fits the
    documented ~20s cross-worker budget. If anyone bumps it past the
    budget the runbook lies and on-call is surprised."""
    from routes.cms_sarvam_health import _ASM_REFRESH_INTERVAL_SECONDS
    assert 0 < _ASM_REFRESH_INTERVAL_SECONDS <= _PROPAGATION_BUDGET_SECONDS


def test_patch_on_worker_a_propagates_to_worker_b_within_budget(
    mock_admin, monkeypatch,
):
    """Worker A serves the PATCH (writes the persisted doc to the
    shared mongo). Worker B runs the real background refresh loop on
    a compressed interval and must observe the change within the
    documented propagation budget."""
    from routes import cms_sarvam_health as mod

    # Compress to keep wall-clock tiny. The production constant is
    # asserted separately above.
    monkeypatch.setattr(mod, "_ASM_REFRESH_INTERVAL_SECONDS", 0.05)

    db, _ = _shared_db()
    worker_a = _Worker("a")
    worker_b = _Worker("b")
    client_a = _make_app_client(mock_admin)

    async def _scenario():
        # ── Worker B fires up its background refresh loop.
        with worker_b.activate(), _patch_db(db):
            task = asyncio.create_task(mod._assamese_purity_refresh_loop())
            try:
                # ── Worker A: PATCH via HTTP.
                with worker_a.activate(), _patch_db(db):
                    r = client_a.patch(
                        "/admin/assamese-purity",
                        json={"behaviour": "off", "threshold": 0.07},
                    )
                assert r.status_code == 200, r.text

                # ── Wait for worker B's loop to observe the change.
                t0 = time.monotonic()
                deadline = t0 + 2.0  # well under the prod budget
                while time.monotonic() < deadline:
                    ov = worker_b.override
                    if ov and ov.get("behaviour") == "off":
                        return ov, time.monotonic() - t0
                    await asyncio.sleep(0.02)
                return worker_b.override, time.monotonic() - t0
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    ov, elapsed = asyncio.run(_scenario())
    assert ov is not None, "worker B never picked up worker A's PATCH"
    assert ov.get("behaviour") == "off"
    assert ov.get("threshold") == pytest.approx(0.07)
    # Sanity: even with our compressed interval we observed the change
    # well inside the production budget.
    assert elapsed < _PROPAGATION_BUDGET_SECONDS


def test_delete_then_repatch_then_delete_sequence_propagates_within_budget(
    mock_admin, monkeypatch,
):
    """The harder contract: a PATCH+DELETE+PATCH+DELETE storm on
    worker A must each propagate to worker B without any transition
    being silently coalesced or dropped. Guards against a regression
    where the refresh loop only re-applies on doc presence (and
    misses the cleared edge) or vice versa."""
    from routes import cms_sarvam_health as mod

    monkeypatch.setattr(mod, "_ASM_REFRESH_INTERVAL_SECONDS", 0.05)

    db, _ = _shared_db()
    worker_a = _Worker("a")
    worker_b = _Worker("b")
    client_a = _make_app_client(mock_admin)

    def _do_patch(behaviour: str, threshold: float):
        with worker_a.activate(), _patch_db(db):
            r = client_a.patch(
                "/admin/assamese-purity",
                json={"behaviour": behaviour, "threshold": threshold},
            )
        assert r.status_code == 200, r.text

    def _do_delete():
        with worker_a.activate(), _patch_db(db):
            r = client_a.delete("/admin/assamese-purity")
        assert r.status_code == 200, r.text

    async def _await_b(predicate, label: str):
        t0 = time.monotonic()
        deadline = t0 + 2.0
        while time.monotonic() < deadline:
            if predicate(worker_b.override):
                return time.monotonic() - t0
            await asyncio.sleep(0.02)
        raise AssertionError(
            f"worker B never observed transition `{label}`; "
            f"last override={worker_b.override}"
        )

    async def _scenario():
        elapsed_per_step: list[float] = []
        with worker_b.activate(), _patch_db(db):
            task = asyncio.create_task(mod._assamese_purity_refresh_loop())
            try:
                # 1) Initial PATCH from worker A.
                _do_patch("off", 0.07)
                elapsed_per_step.append(await _await_b(
                    lambda ov: bool(ov) and ov.get("behaviour") == "off"
                                and ov.get("threshold") == pytest.approx(0.07),
                    "patch#1 → off/0.07",
                ))

                # 2) DELETE from worker A clears worker B's override.
                _do_delete()
                elapsed_per_step.append(await _await_b(
                    lambda ov: ov is None,
                    "delete#1 → cleared",
                ))

                # 3) Re-PATCH from worker A with a different value.
                _do_patch("strip", 0.11)
                elapsed_per_step.append(await _await_b(
                    lambda ov: bool(ov) and ov.get("behaviour") == "strip"
                                and ov.get("threshold") == pytest.approx(0.11),
                    "patch#2 → strip/0.11",
                ))

                # 4) Final DELETE from worker A clears it again.
                _do_delete()
                elapsed_per_step.append(await _await_b(
                    lambda ov: ov is None,
                    "delete#2 → cleared",
                ))
                return elapsed_per_step
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    elapsed_per_step = asyncio.run(_scenario())

    # Every transition must land inside the documented per-tick budget.
    assert all(t < _PROPAGATION_BUDGET_SECONDS for t in elapsed_per_step), (
        f"per-step propagation latencies exceeded budget: {elapsed_per_step}"
    )
