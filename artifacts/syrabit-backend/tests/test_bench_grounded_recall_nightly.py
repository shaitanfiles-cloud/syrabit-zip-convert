"""Unit tests for the nightly grounded-recall scheduler + alerting (Task #587).

Covers the helper used by both the in-process loop and the standalone CLI:

* gate-pass path: no alert is dispatched, results are still saved
* gate-fail path: ``_dispatch_alert`` is called with a body that includes
  the metric delta and the miss list (the two diagnostics the runbook
  promises on-call admins)
* scheduling window: the loop only fires inside the configured ±30 min
  window and never twice for the same UTC day
* cross-replica dedup: only the replica that wins the atomic
  ``db.job_locks`` CAS actually runs the bench
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _fake_report(recall_5: float, *, misses: int = 0):
    """Build a minimal BenchReport whose recall@5 the test controls."""
    from bench.grounded_recall import BenchReport
    per_case = []
    for i in range(20):
        matched = i >= misses  # first ``misses`` cases miss
        per_case.append({
            "id": f"case-{i:02d}",
            "query": f"sample query {i}",
            "citations_count": 3,
            "first_match_rank": 1 if matched else None,
            "matched": matched,
            "elapsed_ms": 12,
        })
    return BenchReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        retriever="live",
        total_cases=20,
        metrics={
            "recall@1": recall_5 - 0.05,
            "recall@3": recall_5,
            "recall@5": recall_5,
            "match_rate": recall_5,
        },
        per_case=per_case,
        mean_citation_count=3.0,
        mean_latency_ms=12.0,
    )


# ─── run_and_alert_live ──────────────────────────────────────────────────

def test_run_and_alert_live_passes_gate_does_not_alert(monkeypatch, tmp_path):
    """When recall@5 is at-or-above baseline, no alert should fire."""
    from bench import grounded_recall as gr

    # Baseline is committed; report at baseline → drop 0.0, gate passes.
    baseline = gr.load_baseline()
    assert baseline is not None
    base_r5 = baseline["metrics"]["recall@5"]

    async def _fake_run(cases, *, retriever):
        assert retriever == "live"
        return _fake_report(base_r5)

    monkeypatch.setattr(gr, "run_benchmark", _fake_run)
    monkeypatch.setattr(gr, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(gr, "save_report",
                        lambda r, results_dir=None, language=None: tmp_path / "latest.json")

    dispatch = AsyncMock()
    out = _run(gr.run_and_alert_live(gate=0.05, dispatch=dispatch))

    assert out["gate_failed"] is False
    assert out["alert_dispatched"] is False
    dispatch.assert_not_called()


def test_run_and_alert_live_fails_gate_dispatches_alert(monkeypatch, tmp_path):
    """When recall@5 drops more than the gate, fire one alert with the
    metric delta and the list of miss IDs in the body."""
    from bench import grounded_recall as gr

    baseline = gr.load_baseline()
    base_r5 = baseline["metrics"]["recall@5"]
    regressed = base_r5 - 0.20  # well past the 0.05 gate

    async def _fake_run(cases, *, retriever):
        return _fake_report(regressed, misses=4)

    monkeypatch.setattr(gr, "run_benchmark", _fake_run)
    monkeypatch.setattr(gr, "save_report",
                        lambda r, results_dir=None, language=None: tmp_path / "latest.json")

    dispatch = AsyncMock(return_value={"email": {"ok": True}})
    out = _run(gr.run_and_alert_live(gate=0.05, dispatch=dispatch))

    assert out["gate_failed"] is True
    assert out["drop"] == pytest.approx(0.20, abs=1e-4)
    assert out["alert_dispatched"] is True
    dispatch.assert_awaited_once()

    args, kwargs = dispatch.await_args
    alert_type, title, body = args[0], args[1], args[2]
    assert alert_type == "grounded_recall_regression"
    assert "recall@5" in title
    # Metric delta — current and baseline both surfaced.
    assert "recall@5" in body
    assert f"{base_r5:.4f}" in body
    # Miss list is included so admins can triage immediately.
    assert "Misses" in body
    assert "case-00" in body
    # Threshold snapshot drives the rich Slack/email card.
    snap = kwargs["threshold_snapshot"]
    assert snap["metric"] == "recall@5"
    assert snap["actual"] == pytest.approx(round(regressed, 4), abs=1e-4)


def test_run_and_alert_live_does_not_alert_when_baseline_missing(monkeypatch, tmp_path):
    """If baseline.json can't be loaded we must not page admins on what
    might just be a missing fixture (would be alert-spam on first deploy)."""
    from bench import grounded_recall as gr

    async def _fake_run(cases, *, retriever):
        return _fake_report(0.10)  # would be a huge drop if baseline existed

    monkeypatch.setattr(gr, "run_benchmark", _fake_run)
    monkeypatch.setattr(gr, "load_baseline", lambda path=None, language=None: None)
    monkeypatch.setattr(gr, "save_report",
                        lambda r, results_dir=None, language=None: tmp_path / "latest.json")

    dispatch = AsyncMock()
    out = _run(gr.run_and_alert_live(gate=0.05, dispatch=dispatch))

    assert out["gate_failed"] is False
    assert out["alert_dispatched"] is False
    dispatch.assert_not_called()


# ─── Scheduling window + dedup ───────────────────────────────────────────

def test_should_run_only_inside_window_and_once_per_day(monkeypatch):
    from bench import grounded_recall as gr

    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_ENABLED", "true")
    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_HOUR_UTC", "3")

    in_window = datetime(2026, 4, 21, 3, 10, tzinfo=timezone.utc)
    out_of_window = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    assert gr._should_run_grounded_recall_now(in_window, last_run_tag="") is True
    # Same day's tag means we already ran today — must not re-fire.
    assert gr._should_run_grounded_recall_now(
        in_window, last_run_tag=gr._bench_run_tag(in_window)
    ) is False
    # Outside the ±30min window: never fire.
    assert gr._should_run_grounded_recall_now(out_of_window, last_run_tag="") is False


def test_should_run_disabled_via_env(monkeypatch):
    from bench import grounded_recall as gr
    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_ENABLED", "false")
    in_window = datetime(2026, 4, 21, 3, 10, tzinfo=timezone.utc)
    assert gr._should_run_grounded_recall_now(in_window, last_run_tag="") is False


class _FakeJobLocks:
    """In-memory stand-in for ``db.job_locks`` used to exercise the
    cross-replica CAS without spinning up a real Mongo."""

    def __init__(self, initial: dict | None = None):
        # ``initial`` is a {_id: doc} mapping mirroring how
        # ``db.job_locks`` is keyed in production.
        self.docs: dict = {k: dict(v) for k, v in (initial or {}).items()}
        self.insert_calls = 0

    async def find_one(self, filt, projection=None):
        doc = self.docs.get(filt.get("_id"))
        return dict(doc) if doc else None

    async def find_one_and_update(self, filt, update, upsert=False):
        _id = filt["_id"]
        doc = self.docs.get(_id)
        if not doc:
            return None
        # Honour the {"$ne": cur_tag} predicate.
        for key, cond in filt.items():
            if key == "_id":
                continue
            if isinstance(cond, dict) and "$ne" in cond:
                if doc.get(key) == cond["$ne"]:
                    return None
        prev = dict(doc)
        doc.update(update.get("$set", {}))
        return prev

    async def insert_one(self, doc):
        from pymongo.errors import DuplicateKeyError
        self.insert_calls += 1
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("duplicate")
        self.docs[doc["_id"]] = dict(doc)


class _FakeDB:
    def __init__(self, locks: _FakeJobLocks):
        self.job_locks = locks


def test_cross_replica_dedup_only_one_winner(monkeypatch, tmp_path):
    """Two replicas race on the same UTC day — exactly one runs the
    bench; the loser short-circuits with reason='lost_race'."""
    from bench import grounded_recall as gr

    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_ENABLED", "true")
    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_HOUR_UTC", "3")

    runs = {"count": 0}

    async def _fake_run_and_alert(*, gate=None, save=True, fixture_path=None,
                                  dispatch=None, language=None,
                                  alert_type="grounded_recall_regression"):
        runs["count"] += 1
        return {"ran": True, "gate_failed": False, "drop": 0.0,
                "alert_dispatched": False, "report": {}, "saved_to": None,
                "gate": gate or 0.05, "alert_outcomes": None}

    monkeypatch.setattr(gr, "run_and_alert_live", _fake_run_and_alert)

    locks = _FakeJobLocks()
    db = _FakeDB(locks)
    now = datetime(2026, 4, 21, 3, 5, tzinfo=timezone.utc)

    # Replica A wins the bootstrap insert.
    a = _run(gr._try_run_grounded_recall_once(db, now_utc=now))
    # Replica B reads the freshly-written tag and short-circuits before
    # racing on the CAS — the dedup window covers the whole UTC day.
    b = _run(gr._try_run_grounded_recall_once(db, now_utc=now))

    assert a["ran"] is True
    assert b["ran"] is False
    assert b["reason"] in ("outside_window_or_dedup", "lost_race")
    assert runs["count"] == 1
    # Next UTC day → A wins again via the CAS path (not bootstrap).
    next_day = datetime(2026, 4, 22, 3, 5, tzinfo=timezone.utc)
    c = _run(gr._try_run_grounded_recall_once(db, now_utc=next_day))
    assert c["ran"] is True
    assert runs["count"] == 2

    # Direct CAS race: two replicas both observe the same "old" tag and
    # try to claim the same day. Exactly one wins.
    locks2 = _FakeJobLocks(initial={
        gr._GROUNDED_RECALL_LOCK_ID: {
            "_id": gr._GROUNDED_RECALL_LOCK_ID,
            gr._GROUNDED_RECALL_LAST_RUN_KEY: "2026-04-20",
        },
    })
    db2 = _FakeDB(locks2)
    win = _run(gr._claim_grounded_recall_slot(db2, "2026-04-21"))
    lose = _run(gr._claim_grounded_recall_slot(db2, "2026-04-21"))
    assert win is True and lose is False


def test_try_run_skips_outside_window(monkeypatch):
    from bench import grounded_recall as gr

    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_ENABLED", "true")
    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_HOUR_UTC", "3")

    called = {"n": 0}

    async def _fake_run_and_alert(**_kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr(gr, "run_and_alert_live", _fake_run_and_alert)

    db = _FakeDB(_FakeJobLocks())
    out = _run(gr._try_run_grounded_recall_once(
        db, now_utc=datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    ))
    assert out == {"ran": False, "reason": "outside_window_or_dedup"}
    assert called["n"] == 0
