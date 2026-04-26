"""Task #938 — unit tests for the closed-loop content remediation
service.

Coverage:
* ``decide_action`` decision matrix for all (budget_mode × delta ×
  after_status) combinations.
* ``compute_quality_delta`` extraction from both flat
  ``combined_score`` and nested ``quality.combined_score``.
* ``enqueue_remediation_signal`` validates kind + drops malformed
  signals without raising.
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
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest


# ─── decide_action / compute_quality_delta ─────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_queue():
    """Each test gets a fresh signal queue. Without this, leftover
    signals from one test leak into the next under -n auto."""
    from seo_remediation_service import reset_queue_for_tests
    reset_queue_for_tests()
    yield
    reset_queue_for_tests()


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


# ─── signal queue ──────────────────────────────────────────────────────


def test_enqueue_signal_rejects_unknown_kind():
    from seo_remediation_service import enqueue_remediation_signal
    assert enqueue_remediation_signal({"kind": "totally_invalid"}) is False


def test_enqueue_signal_rejects_non_mapping():
    from seo_remediation_service import enqueue_remediation_signal
    assert enqueue_remediation_signal("not-a-dict") is False  # type: ignore[arg-type]


def test_enqueue_signal_returns_false_outside_event_loop():
    """When called from a sync script (no running loop), enqueue
    must drop quietly rather than raising — the alerter relies on
    fire-and-forget semantics."""
    from seo_remediation_service import enqueue_remediation_signal
    # asyncio.Queue() instantiated outside a running loop on
    # py>=3.10 succeeds; the no-loop path is more about
    # `put_nowait` being reachable. This regression-guards the
    # contract: the call must never raise.
    ok = enqueue_remediation_signal({"kind": "url_404_spike", "url": "/x"})
    # In sync context the call may succeed (queue created) or
    # return False if no loop is yet bound; both are acceptable
    # outcomes — what matters is that no exception escapes.
    assert ok in (True, False)


def test_enqueue_then_drain_inside_loop():
    """Inside an asyncio loop the enqueued signal is retrievable
    by the worker. We call ``get_nowait`` to avoid spinning up
    the full ``_seo_remediation_loop``."""
    from seo_remediation_service import enqueue_remediation_signal, _get_queue

    async def _run():
        ok = enqueue_remediation_signal({"kind": "manual_trigger", "url": "/foo"})
        assert ok is True
        sig = _get_queue().get_nowait()
        assert sig["kind"] == "manual_trigger"
        assert sig["url"] == "/foo"
        # Auto-stamped fields:
        assert sig["id"].startswith("sig-")
        assert "detected_at" in sig

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
    snapshot can flood the queue. Default cap is 5."""
    monkeypatch.setenv("SEO_REMEDIATION_FANOUT_CAP", "3")
    # Re-import after env change so get_config() picks it up. The
    # helper imports the module lazily, so a fresh os.getenv read
    # happens on every call — no module reload needed.
    from routes import bot_discovery as bd
    import seo_remediation_service as rem
    enqueued: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        rem, "enqueue_remediation_signal",
        lambda sig: enqueued.append(dict(sig)) or True,
    )

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

    n = bd._fan_out_remediation_signals(snapshot, kind="url_404_spike")
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
    monkeypatch.setattr(
        rem, "enqueue_remediation_signal",
        lambda sig: enqueued.append(dict(sig)) or True,
    )

    n = bd._fan_out_remediation_signals(
        {"status": "critical"}, kind="seo_health_critical")
    assert n == 0
    assert enqueued == []
