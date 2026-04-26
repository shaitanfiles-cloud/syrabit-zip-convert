"""Task #938 — unit tests for the closed-loop content remediation
service.

Coverage:
* ``decide_action`` decision matrix for all (budget_mode × delta ×
  after_status) combinations.
* ``compute_quality_delta`` extraction from both flat
  ``combined_score`` and nested ``quality.combined_score``.
* ``enqueue_remediation_signal`` validates kind + persists to the
  durable Mongo signals collection without raising.
* ``_claim_next_signal`` atomically claims the oldest pending
  signal (multi-replica safety regression).
* ``_expire_stale_signals`` auto-fails signals stuck in PENDING
  beyond the staleness window.
* Per-day budget cap clamps after caps are hit.
* Circuit breaker trips at the configured ratio over the
  configured window, and ``reset_circuit`` clears it.
* Snapshot revert path on no-improvement (``_remediate_one``).
* Fan-out helper in ``routes.bot_discovery`` honours the
  per-event cap and only fires for the documented kinds.

The tests use the same fake-Mongo pattern as
``test_admin_topic_discovery_route.py`` so the assertions stay
hermetic and order-independent under pytest -n.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest


def _page(combined: int, status: str = "published") -> dict:
    return {"id": "p1", "combined_score": combined, "status": status}


def test_compute_quality_delta_uses_flat_score():
    from seo_remediation_service import compute_quality_delta
    d = compute_quality_delta({"combined_score": 70}, {"combined_score": 80})
    assert d == {"before": 70, "after": 80, "delta": 10}


def test_compute_quality_delta_falls_back_to_nested_quality():
    from seo_remediation_service import compute_quality_delta
    d = compute_quality_delta(
        {"quality": {"combined_score": 50}},
        {"combined_score": 55},
    )
    assert d["before"] == 50
    assert d["after"] == 55
    assert d["delta"] == 5


def test_compute_quality_delta_handles_missing_docs():
    from seo_remediation_service import compute_quality_delta
    assert compute_quality_delta(None, None) == {"before": 0, "after": 0, "delta": 0}
    # Garbage scores → 0 (safe default).
    d = compute_quality_delta({"combined_score": "oops"}, {"combined_score": None})
    assert d == {"before": 0, "after": 0, "delta": 0}


def test_decide_action_over_budget_always_skips():
    from seo_remediation_service import decide_action, ACTION_SKIPPED_OVER_BUDGET
    out = decide_action(before=_page(50), after=_page(90),
                        budget_mode="over_budget")
    assert out["action"] == ACTION_SKIPPED_OVER_BUDGET


def test_decide_action_draft_only_files_when_not_worse():
    from seo_remediation_service import decide_action, ACTION_DRAFTED
    out = decide_action(before=_page(60), after=_page(60, status="published"),
                        budget_mode="draft_only")
    assert out["action"] == ACTION_DRAFTED


def test_decide_action_draft_only_skips_when_regresses_significantly():
    from seo_remediation_service import decide_action, ACTION_SKIPPED_NO_IMPROVEMENT
    out = decide_action(before=_page(80), after=_page(70),
                        budget_mode="draft_only")
    assert out["action"] == ACTION_SKIPPED_NO_IMPROVEMENT


def test_decide_action_auto_ok_drafts_when_seo_engine_drafted():
    from seo_remediation_service import decide_action, ACTION_DRAFTED
    out = decide_action(before=_page(60), after=_page(70, status="draft"),
                        budget_mode="auto_republish_ok")
    assert out["action"] == ACTION_DRAFTED


def test_decide_action_auto_ok_skips_when_engine_drafted_and_regressed():
    from seo_remediation_service import decide_action, ACTION_SKIPPED_NO_IMPROVEMENT
    out = decide_action(before=_page(80), after=_page(60, status="draft"),
                        budget_mode="auto_republish_ok")
    assert out["action"] == ACTION_SKIPPED_NO_IMPROVEMENT


def test_decide_action_auto_ok_publishes_on_clear_win():
    from seo_remediation_service import decide_action, ACTION_AUTO_REPUBLISHED
    out = decide_action(before=_page(60), after=_page(70, status="published"),
                        budget_mode="auto_republish_ok",
                        config={"min_improvement_delta": 2})
    assert out["action"] == ACTION_AUTO_REPUBLISHED
    assert out["delta"]["delta"] == 10


def test_decide_action_auto_ok_drafts_on_marginal_improvement():
    from seo_remediation_service import decide_action, ACTION_DRAFTED
    # delta = +1 < min_improvement_delta (2) → draft for review.
    out = decide_action(before=_page(70), after=_page(71, status="published"),
                        budget_mode="auto_republish_ok",
                        config={"min_improvement_delta": 2})
    assert out["action"] == ACTION_DRAFTED


def test_decide_action_auto_ok_skips_on_regression():
    from seo_remediation_service import decide_action, ACTION_SKIPPED_NO_IMPROVEMENT
    out = decide_action(before=_page(80), after=_page(60, status="published"),
                        budget_mode="auto_republish_ok",
                        config={"min_improvement_delta": 2})
    assert out["action"] == ACTION_SKIPPED_NO_IMPROVEMENT


# ─── signal queue (Mongo-backed) ───────────────────────────────────────


class _FakeSignalsColl:
    """Minimal fake for ``db.seo_remediation_signals`` covering
    ``insert_one``, ``find_one_and_update`` (oldest-pending claim),
    ``update_many`` (stale sweep), and ``update_one`` (mark done).
    Mirrors motor's API surface, returning duck-typed result
    objects with ``modified_count`` so the production code reads
    cleanly without a special-case for tests."""

    class _UpdateResult:
        def __init__(self, modified_count: int = 0):
            self.modified_count = modified_count

    def __init__(self):
        self.docs: List[Dict[str, Any]] = []

    @staticmethod
    def _matches(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
        for k, v in q.items():
            if isinstance(v, dict) and "$lt" in v:
                if not (doc.get(k) is not None and doc.get(k) < v["$lt"]):
                    return False
            elif doc.get(k) != v:
                return False
        return True

    @staticmethod
    def _apply_update(doc: Dict[str, Any], update: Dict[str, Any]) -> None:
        for field, val in (update.get("$set") or {}).items():
            doc[field] = val
        for field, val in (update.get("$inc") or {}).items():
            doc[field] = int(doc.get(field, 0)) + int(val)

    async def insert_one(self, doc: Dict[str, Any]) -> None:
        if any(d.get("_id") == doc.get("_id") for d in self.docs):
            raise RuntimeError("duplicate _id")  # mimic Mongo's DuplicateKeyError
        self.docs.append(dict(doc))

    async def find_one_and_update(self, q, update, sort=None, **_kw):
        candidates = [d for d in self.docs if self._matches(d, q)]
        if sort:
            for field, direction in reversed(sort):
                candidates.sort(
                    key=lambda d: d.get(field) or "",
                    reverse=(direction == -1),
                )
        if not candidates:
            return None
        target = candidates[0]
        self._apply_update(target, update)
        return dict(target)

    async def update_many(self, q, update):
        n = 0
        for d in self.docs:
            if self._matches(d, q):
                self._apply_update(d, update)
                n += 1
        return self._UpdateResult(modified_count=n)

    async def update_one(self, q, update):
        for d in self.docs:
            if self._matches(d, q):
                self._apply_update(d, update)
                return self._UpdateResult(modified_count=1)
        return self._UpdateResult(modified_count=0)


class _DbWithSignals:
    """Standalone fake DB exposing only the signals collection so
    these tests don't drag in budget / circuit / pages stubs."""
    def __init__(self):
        self.seo_remediation_signals = _FakeSignalsColl()


def test_enqueue_signal_rejects_unknown_kind():
    from seo_remediation_service import enqueue_remediation_signal

    async def _run():
        db = _DbWithSignals()
        sid = await enqueue_remediation_signal(db, {"kind": "totally_invalid"})
        assert sid is None
        assert db.seo_remediation_signals.docs == []

    asyncio.run(_run())


def test_enqueue_signal_rejects_kinds_no_longer_in_scope():
    """#938 explicitly lists URL spike + health degraded/critical
    + manual trigger. Earlier drafts of VALID_SIGNAL_KINDS
    included ``orphan_page`` and ``sitemap_regression`` for which
    no producer exists; the contract must reject them so the
    alerter can never quietly enqueue an unsupported kind."""
    from seo_remediation_service import enqueue_remediation_signal

    async def _run():
        db = _DbWithSignals()
        for kind in ("orphan_page", "sitemap_regression"):
            sid = await enqueue_remediation_signal(db, {"kind": kind, "url": "/x"})
            assert sid is None, f"expected reject for {kind}"
        assert db.seo_remediation_signals.docs == []

    asyncio.run(_run())


def test_enqueue_signal_rejects_non_mapping():
    from seo_remediation_service import enqueue_remediation_signal

    async def _run():
        db = _DbWithSignals()
        sid = await enqueue_remediation_signal(db, "not-a-dict")  # type: ignore[arg-type]
        assert sid is None

    asyncio.run(_run())


def test_enqueue_persists_durable_pending_doc():
    """Producers and consumers may run on different replicas. The
    contract is that ``enqueue_remediation_signal`` writes a
    ``status='pending'`` doc to ``seo_remediation_signals`` so any
    leader's poller can see it via ``find_one_and_update``."""
    from seo_remediation_service import (
        enqueue_remediation_signal, SIGNAL_STATUS_PENDING,
    )

    async def _run():
        db = _DbWithSignals()
        sid = await enqueue_remediation_signal(
            db, {"kind": "manual_trigger", "url": "/foo"})
        assert sid and sid.startswith("sig-")
        docs = db.seo_remediation_signals.docs
        assert len(docs) == 1
        d = docs[0]
        assert d["status"] == SIGNAL_STATUS_PENDING
        assert d["kind"] == "manual_trigger"
        assert d["url"] == "/foo"
        assert d["payload"]["url"] == "/foo"
        assert d["payload"]["id"] == sid
        assert "detected_at" in d["payload"]
        assert d["created_at"]
        assert d["claimed_at"] is None

    asyncio.run(_run())


def test_claim_next_signal_returns_oldest_pending_and_marks_claimed():
    """Multi-replica safety: ``_claim_next_signal`` must atomically
    move PENDING → CLAIMED and return the same doc to exactly one
    caller. We simulate two pollers racing by calling claim twice
    after enqueueing two signals — each gets a distinct doc, neither
    returns None mid-queue."""
    from seo_remediation_service import (
        enqueue_remediation_signal, _claim_next_signal,
        SIGNAL_STATUS_CLAIMED,
    )

    async def _run():
        db = _DbWithSignals()
        # Older signal first so the FIFO ordering is observable.
        s1 = await enqueue_remediation_signal(
            db, {"kind": "manual_trigger", "url": "/old"})
        # Force a small lexicographic gap so created_at sorts predictably.
        await asyncio.sleep(0)
        s2 = await enqueue_remediation_signal(
            db, {"kind": "url_404_spike", "url": "/new"})
        # Patch the second doc's created_at to a strictly-larger value
        # (the fake clock collapses microseconds in fast tests).
        for d in db.seo_remediation_signals.docs:
            if d["_id"] == s2:
                d["created_at"] = "9999-12-31T23:59:59+00:00"

        first = await _claim_next_signal(db)
        second = await _claim_next_signal(db)
        third = await _claim_next_signal(db)

        assert first is not None and first["_id"] == s1
        assert second is not None and second["_id"] == s2
        assert third is None  # queue drained
        # Both flipped to CLAIMED with attempts incremented.
        for d in db.seo_remediation_signals.docs:
            assert d["status"] == SIGNAL_STATUS_CLAIMED
            assert d["attempts"] == 1
            assert d["claimed_at"] is not None

    asyncio.run(_run())


def test_expire_stale_signals_fails_pending_older_than_window():
    """Stale-sweep regression: an alert fired a week ago shouldn't
    suddenly remediate when the leader recovers from an outage."""
    from seo_remediation_service import (
        enqueue_remediation_signal, _expire_stale_signals,
        SIGNAL_STALE_HOURS, SIGNAL_STATUS_FAILED, SIGNAL_STATUS_PENDING,
    )

    async def _run():
        db = _DbWithSignals()
        fresh_id = await enqueue_remediation_signal(
            db, {"kind": "manual_trigger", "url": "/fresh"})
        stale_id = await enqueue_remediation_signal(
            db, {"kind": "url_404_spike", "url": "/stale"})
        # Backdate the stale one beyond the window.
        old = (datetime.now(timezone.utc)
               - timedelta(hours=SIGNAL_STALE_HOURS + 1)).isoformat()
        for d in db.seo_remediation_signals.docs:
            if d["_id"] == stale_id:
                d["created_at"] = old

        n = await _expire_stale_signals(db)
        assert n == 1

        by_id = {d["_id"]: d for d in db.seo_remediation_signals.docs}
        assert by_id[fresh_id]["status"] == SIGNAL_STATUS_PENDING
        assert by_id[stale_id]["status"] == SIGNAL_STATUS_FAILED
        assert by_id[stale_id]["fail_reason"].startswith("expired")

    asyncio.run(_run())


# ─── budget cap ────────────────────────────────────────────────────────


class _FakeBudgetColl:
    """Minimal fake for ``db.seo_remediation_budget`` exercising
    the find_one + upsert+$inc path used by the service."""
    def __init__(self):
        self.docs: Dict[str, Dict[str, Any]] = {}

    async def find_one(self, q):
        return self.docs.get(q.get("_id"))

    async def update_one(self, q, update, upsert=False):
        key = q.get("_id")
        doc = self.docs.setdefault(key, {"_id": key})
        for field, delta in (update.get("$inc") or {}).items():
            doc[field] = int(doc.get(field, 0)) + int(delta)
        for field, val in (update.get("$setOnInsert") or {}).items():
            doc.setdefault(field, val)
        for field, val in (update.get("$set") or {}).items():
            doc[field] = val


class _FakeDb:
    def __init__(self):
        self.seo_remediation_budget = _FakeBudgetColl()
        self.seo_remediation_circuit = _FakeCircuitColl()


class _FakeCircuitColl:
    def __init__(self):
        self.doc: Dict[str, Any] = {}

    async def find_one(self, q):
        if not self.doc:
            return None
        return dict(self.doc)

    async def update_one(self, _q, update, upsert=False):
        # $push with $each + $slice
        push = update.get("$push") or {}
        for field, spec in push.items():
            current = self.doc.get(field) or []
            each = spec.get("$each") if isinstance(spec, dict) else [spec]
            slice_n = spec.get("$slice") if isinstance(spec, dict) else None
            current = current + list(each or [])
            if slice_n is not None:
                if slice_n < 0:
                    current = current[slice_n:]
                else:
                    current = current[:slice_n]
            self.doc[field] = current
        for field, val in (update.get("$set") or {}).items():
            self.doc[field] = val


def test_peek_budget_mode_progresses_through_modes(monkeypatch):
    from seo_remediation_service import (
        _peek_budget_mode, _record_budget_consumption,
        ACTION_AUTO_REPUBLISHED, ACTION_DRAFTED,
    )
    monkeypatch.setenv("SEO_REMEDIATION_AUTOPUBLISH_PER_DAY", "2")
    monkeypatch.setenv("SEO_REMEDIATION_DRAFT_PER_DAY", "3")

    async def _run():
        db = _FakeDb()
        # Fresh day → auto_republish_ok.
        assert await _peek_budget_mode(db) == "auto_republish_ok"
        await _record_budget_consumption(db, ACTION_AUTO_REPUBLISHED)
        await _record_budget_consumption(db, ACTION_AUTO_REPUBLISHED)
        # Auto cap exhausted → draft_only.
        assert await _peek_budget_mode(db) == "draft_only"
        await _record_budget_consumption(db, ACTION_DRAFTED)
        await _record_budget_consumption(db, ACTION_DRAFTED)
        await _record_budget_consumption(db, ACTION_DRAFTED)
        # Both caps exhausted → over_budget.
        assert await _peek_budget_mode(db) == "over_budget"

    asyncio.run(_run())


def test_record_budget_ignores_skip_actions(monkeypatch):
    from seo_remediation_service import (
        _record_budget_consumption, get_budget_status,
        ACTION_SKIPPED_NO_IMPROVEMENT, ACTION_FAILED,
    )

    async def _run():
        db = _FakeDb()
        await _record_budget_consumption(db, ACTION_SKIPPED_NO_IMPROVEMENT)
        await _record_budget_consumption(db, ACTION_FAILED)
        s = await get_budget_status(db)
        assert s["auto_used"] == 0
        assert s["draft_used"] == 0

    asyncio.run(_run())


# ─── circuit breaker ───────────────────────────────────────────────────


def test_circuit_trips_when_drafted_ratio_crosses_threshold(monkeypatch):
    from seo_remediation_service import (
        _record_attempt_in_circuit, _is_circuit_open,
        ACTION_DRAFTED, ACTION_AUTO_REPUBLISHED,
    )
    monkeypatch.setenv("SEO_REMEDIATION_CIRCUIT_WINDOW", "4")
    monkeypatch.setenv("SEO_REMEDIATION_CIRCUIT_RATIO", "0.5")
    monkeypatch.setenv("SEO_REMEDIATION_CIRCUIT_COOLDOWN_H", "24")

    async def _run():
        db = _FakeDb()
        # 1 auto + 1 drafted → under ratio → not open yet.
        await _record_attempt_in_circuit(db, ACTION_AUTO_REPUBLISHED)
        await _record_attempt_in_circuit(db, ACTION_DRAFTED)
        assert not await _is_circuit_open(db)
        # Two more drafts → 3/4 = 75% → trips.
        await _record_attempt_in_circuit(db, ACTION_DRAFTED)
        await _record_attempt_in_circuit(db, ACTION_DRAFTED)
        assert await _is_circuit_open(db)

    asyncio.run(_run())


def test_circuit_does_not_trip_below_window(monkeypatch):
    from seo_remediation_service import (
        _record_attempt_in_circuit, _is_circuit_open, ACTION_DRAFTED,
    )
    monkeypatch.setenv("SEO_REMEDIATION_CIRCUIT_WINDOW", "10")

    async def _run():
        db = _FakeDb()
        # Only 3 attempts logged → window not full → can't trip.
        for _ in range(3):
            await _record_attempt_in_circuit(db, ACTION_DRAFTED)
        assert not await _is_circuit_open(db)

    asyncio.run(_run())


def test_reset_circuit_clears_cooldown_and_history(monkeypatch):
    from seo_remediation_service import (
        _record_attempt_in_circuit, reset_circuit, get_circuit_status,
        ACTION_DRAFTED,
    )
    monkeypatch.setenv("SEO_REMEDIATION_CIRCUIT_WINDOW", "2")
    monkeypatch.setenv("SEO_REMEDIATION_CIRCUIT_RATIO", "0.5")

    async def _run():
        db = _FakeDb()
        await _record_attempt_in_circuit(db, ACTION_DRAFTED)
        await _record_attempt_in_circuit(db, ACTION_DRAFTED)
        s = await get_circuit_status(db)
        assert s["is_open"]
        await reset_circuit(db)
        s2 = await get_circuit_status(db)
        assert not s2["is_open"]
        assert s2["recent_total"] == 0

    asyncio.run(_run())


# ─── _remediate_one revert path ────────────────────────────────────────


class _FakePagesColl:
    def __init__(self, page):
        self.page = dict(page)
        self.upserts: List[Dict[str, Any]] = []

    async def find_one(self, q, _proj=None):
        if not self.page:
            return None
        if all(self.page.get(k) == v for k, v in q.items()):
            return dict(self.page)
        return None


class _FakeHistoryColl:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    async def insert_one(self, doc):
        self.rows.append(dict(doc))

    async def update_one(self, _q, _update, **_kw):
        pass


def test_remediate_one_reverts_when_new_content_regresses(monkeypatch):
    """Simulates the full flow: signal → page lookup → snapshot
    → seo_engine produces a worse draft → decision says SKIP →
    seo_writes.upsert_seo_page is called with the snapshot."""
    from seo_remediation_service import _remediate_one, ACTION_SKIPPED_NO_IMPROVEMENT

    snapshot = {"id": "p1", "combined_score": 80, "status": "published",
                "title": "Before", "topic_id": "t1", "page_type": "notes"}
    after = {"id": "p1", "combined_score": 60, "status": "published",
             "title": "After"}

    db = _FakeDb()
    db.seo_pages = _FakePagesColl(snapshot)
    db.seo_remediation_history = _FakeHistoryColl()
    db.topics = _StubTopicColl()

    upsert_calls: List[Dict[str, Any]] = []

    async def _fake_upsert(_db, q, doc):
        upsert_calls.append({"q": dict(q), "doc": dict(doc)})

    async def _fake_resolve_hierarchy(_topic):
        return {"topic": {"id": "t1", "title": "Topic 1"}}

    async def _fake_generate(_topic, _page_type, _hier):
        return after  # regressed

    async def _run():
        with patch("seo_writes.upsert_seo_page", side_effect=_fake_upsert), \
             patch("seo_engine._resolve_hierarchy", side_effect=_fake_resolve_hierarchy), \
             patch("seo_engine._generate_single_page", side_effect=_fake_generate):
            res = await _remediate_one(db, {"id": "sig-1", "kind": "manual_trigger",
                                            "page_id": "p1"})
        assert res["action"] == ACTION_SKIPPED_NO_IMPROVEMENT
        # Snapshot was restored — upsert_seo_page called with the
        # original `snapshot` doc.
        assert upsert_calls, "expected snapshot revert call"
        last = upsert_calls[-1]
        assert last["q"] == {"id": "p1"}
        assert last["doc"]["combined_score"] == 80
        assert last["doc"]["title"] == "Before"

    asyncio.run(_run())


class _StubTopicColl:
    async def find_one(self, *_a, **_kw):
        return {"id": "t1", "title": "Topic 1"}


# ─── fan-out cap in routes.bot_discovery ───────────────────────────────


def test_fan_out_remediation_signals_caps_at_event_limit(monkeypatch):
    """The alerter helper must cap how many URLs from a single
    snapshot can flood the queue. Default cap is 5; we tighten
    to 3 here so the test is fast and unambiguous.

    The helper is now ``async`` (it awaits the durable Mongo
    enqueue), so we patch ``enqueue_remediation_signal`` with an
    AsyncMock that records each invocation."""
    monkeypatch.setenv("SEO_REMEDIATION_FANOUT_CAP", "3")
    from routes import bot_discovery as bd
    import seo_remediation_service as rem

    enqueued: List[Dict[str, Any]] = []

    async def _fake_enqueue(_db, sig):
        enqueued.append(dict(sig))
        return f"sig-{len(enqueued)}"
    monkeypatch.setattr(rem, "enqueue_remediation_signal", _fake_enqueue)

    snapshot = {
        "by_sitemap": [
            {
                "name": "main",
                "failing_urls": [
                    {"url": f"/topic-{i}", "status": 404} for i in range(10)
                ],
            },
        ],
        "status": "critical",
        "summary": {"url_check_success_rate": 60.0},
    }

    async def _run():
        return await bd._fan_out_remediation_signals(
            db=object(), snapshot=snapshot, kind="url_404_spike")

    n = asyncio.run(_run())
    assert n == 3
    assert len(enqueued) == 3
    assert all(s["kind"] == "url_404_spike" for s in enqueued)
    assert enqueued[0]["url"] == "/topic-0"
    # Per-event details are propagated.
    assert enqueued[0]["details"]["sitemap"] == "main"
    assert enqueued[0]["details"]["status"] == 404
    assert enqueued[0]["details"]["snapshot_status"] == "critical"


def test_fan_out_remediation_signals_handles_missing_failing_urls(monkeypatch):
    """A snapshot with no by_sitemap entries (or no failing_urls
    inside them) must enqueue zero and not crash. The alerter
    contract is fire-and-forget; we never want a remediation
    plumbing bug to break on-call paging."""
    monkeypatch.setenv("SEO_REMEDIATION_FANOUT_CAP", "5")
    from routes import bot_discovery as bd
    import seo_remediation_service as rem

    enqueued: List[Dict[str, Any]] = []

    async def _fake_enqueue(_db, sig):
        enqueued.append(dict(sig))
        return f"sig-{len(enqueued)}"
    monkeypatch.setattr(rem, "enqueue_remediation_signal", _fake_enqueue)

    async def _run():
        return await bd._fan_out_remediation_signals(
            db=object(), snapshot={"status": "critical"},
            kind="seo_health_critical")

    n = asyncio.run(_run())
    assert n == 0
    assert enqueued == []


def test_fan_out_remediation_signals_swallows_enqueue_errors(monkeypatch):
    """If Mongo is wedged, the alerter must keep paging on-call.
    A raised enqueue should be logged and counted as zero — never
    bubble up to the alerter dispatch path."""
    monkeypatch.setenv("SEO_REMEDIATION_FANOUT_CAP", "5")
    from routes import bot_discovery as bd
    import seo_remediation_service as rem

    async def _boom(_db, _sig):
        raise RuntimeError("mongo down")
    monkeypatch.setattr(rem, "enqueue_remediation_signal", _boom)

    snapshot = {
        "by_sitemap": [{"name": "main",
                        "failing_urls": [{"url": "/x", "status": 404}]}],
        "status": "critical",
    }

    async def _run():
        return await bd._fan_out_remediation_signals(
            db=object(), snapshot=snapshot, kind="url_404_spike")

    n = asyncio.run(_run())
    assert n == 0
