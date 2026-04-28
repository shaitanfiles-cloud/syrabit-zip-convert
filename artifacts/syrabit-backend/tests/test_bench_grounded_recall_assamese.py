"""Tests for the Assamese-language nightly grounded-recall subset (Task #599).

Covers:
* ``load_cases(language='as')`` filters the fixture down to Asomiya cases
* ``run_and_alert_live`` with ``language='as'`` writes to
  ``latest_as.json``, gates against ``baseline_as.json``, and dispatches
  the Assamese-specific alert type on regression
* ``_try_run_grounded_recall_assamese_once`` runs independently of the
  global bench (separate lock id) so the two nightlies do not block
  each other on the same UTC day
* The admin endpoint ``GET /api/admin/grounded-recall/latest?language=as``
  serves the Assamese-subset latest + baseline
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _run(coro):
    return asyncio.run(coro)


# ─── Fixture filtering ───────────────────────────────────────────────────

def test_load_cases_language_filter_assamese():
    from bench.grounded_recall import load_cases
    all_cases = load_cases()
    as_cases = load_cases(language="as")
    assert 0 < len(as_cases) < len(all_cases)
    for c in as_cases:
        assert (c.context or {}).get("language") == "as"


def test_load_cases_unknown_language_returns_empty():
    from bench.grounded_recall import load_cases
    assert load_cases(language="zz") == []


# ─── Per-language baseline + latest paths ────────────────────────────────

def test_baseline_as_is_committed_and_loaded():
    from bench.grounded_recall import load_baseline
    base = load_baseline(language="as")
    assert base is not None
    assert base.get("language") == "as"
    for k in ("recall@1", "recall@3", "recall@5"):
        assert k in base["metrics"]


def test_save_report_writes_language_specific_latest(tmp_path):
    from bench.grounded_recall import (
        BenchReport, save_report, find_latest_result,
    )
    rep = BenchReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        retriever="live",
        total_cases=8,
        metrics={"recall@1": 0.9, "recall@3": 1.0, "recall@5": 1.0, "match_rate": 1.0},
        per_case=[],
        mean_citation_count=1.5,
        mean_latency_ms=120.0,
    )
    save_report(rep, results_dir=tmp_path, language="as")
    # Lang-tagged latest exists, plain latest.json does NOT (the global
    # nightly owns that file — Assamese must not stomp on it).
    assert (tmp_path / "latest_as.json").exists()
    assert not (tmp_path / "latest.json").exists()
    loaded = find_latest_result(results_dir=tmp_path, language="as")
    assert loaded["metrics"]["recall@5"] == 1.0
    # And the global lookup returns None — the two are independent.
    assert find_latest_result(results_dir=tmp_path) is None


# ─── run_and_alert_live(language='as') ───────────────────────────────────

def _fake_report(recall_5: float, *, total: int = 8, misses: int = 0, lang: str = "as"):
    from bench.grounded_recall import BenchReport
    per_case = []
    for i in range(total):
        matched = i >= misses
        per_case.append({
            "id": f"as-case-{i:02d}",
            "query": f"আজি প্ৰশ্ন {i}",
            "citations_count": 2,
            "first_match_rank": 1 if matched else None,
            "matched": matched,
            "elapsed_ms": 220,
        })
    return BenchReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        retriever="live",
        total_cases=total,
        metrics={
            "recall@1": recall_5 - 0.05 if recall_5 >= 0.05 else recall_5,
            "recall@3": recall_5,
            "recall@5": recall_5,
            "match_rate": recall_5,
        },
        per_case=per_case,
        mean_citation_count=1.5,
        mean_latency_ms=220.0,
    )


def test_run_and_alert_live_assamese_passes_gate(monkeypatch, tmp_path):
    from bench import grounded_recall as gr

    base_r5 = gr.load_baseline(language="as")["metrics"]["recall@5"]

    async def _fake_run(cases, *, retriever):
        # Sanity: the Assamese filter actually narrowed the case list.
        assert all((c.context or {}).get("language") == "as" for c in cases)
        return _fake_report(base_r5)

    monkeypatch.setattr(gr, "run_benchmark", _fake_run)
    monkeypatch.setattr(gr, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(
        gr, "save_report",
        lambda r, results_dir=None, language=None: tmp_path / f"latest_{language}.json",
    )

    dispatch = AsyncMock()
    out = _run(gr.run_and_alert_live(
        gate=0.15, dispatch=dispatch, language="as",
        alert_type=gr._GROUNDED_RECALL_AS_ALERT_TYPE,
    ))

    assert out["gate_failed"] is False
    assert out["alert_dispatched"] is False
    dispatch.assert_not_called()


def test_run_and_alert_live_assamese_dispatches_specific_alert(monkeypatch, tmp_path):
    from bench import grounded_recall as gr

    base_r5 = gr.load_baseline(language="as")["metrics"]["recall@5"]
    regressed = base_r5 - 0.50  # massive Assamese regression

    async def _fake_run(cases, *, retriever):
        return _fake_report(regressed, misses=4)

    monkeypatch.setattr(gr, "run_benchmark", _fake_run)
    monkeypatch.setattr(
        gr, "save_report",
        lambda r, results_dir=None, language=None: tmp_path / f"latest_{language}.json",
    )

    dispatch = AsyncMock(return_value={"email": {"ok": True}})
    out = _run(gr.run_and_alert_live(
        gate=0.15, dispatch=dispatch, language="as",
        alert_type=gr._GROUNDED_RECALL_AS_ALERT_TYPE,
    ))

    assert out["gate_failed"] is True
    assert out["alert_dispatched"] is True
    dispatch.assert_awaited_once()
    args, kwargs = dispatch.await_args
    # Must use the Assamese-specific alert type so on-call routing
    # can split the two nightly channels.
    assert args[0] == gr._GROUNDED_RECALL_AS_ALERT_TYPE
    assert "[as]" in args[1]  # title carries the language label
    assert "Language subset: as" in args[2]  # body, too
    snap = kwargs["threshold_snapshot"]
    assert snap["metric"] == "recall@5 [as]"


def test_run_and_alert_live_no_assamese_cases_short_circuits(monkeypatch, tmp_path):
    from bench import grounded_recall as gr

    monkeypatch.setattr(gr, "load_cases", lambda path=None, language=None: [])
    dispatch = AsyncMock()
    out = _run(gr.run_and_alert_live(
        gate=0.15, dispatch=dispatch, language="as",
    ))
    assert out["ran"] is False
    assert out["reason"] == "no_cases_for_language"
    dispatch.assert_not_called()


# ─── Independent scheduling vs global bench ──────────────────────────────

class _FakeJobLocks:
    def __init__(self, initial: dict | None = None):
        self.docs: dict = {k: dict(v) for k, v in (initial or {}).items()}

    async def find_one(self, filt, projection=None):
        doc = self.docs.get(filt.get("_id"))
        return dict(doc) if doc else None

    async def find_one_and_update(self, filt, update, upsert=False):
        _id = filt["_id"]
        doc = self.docs.get(_id)
        if not doc:
            return None
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
        if doc["_id"] in self.docs:
            raise DuplicateKeyError("duplicate")
        self.docs[doc["_id"]] = dict(doc)


class _FakeDB:
    def __init__(self, locks: _FakeJobLocks):
        self.job_locks = locks


def test_assamese_lock_is_independent_of_global(monkeypatch):
    """Running the global nightly today does NOT prevent the Assamese
    nightly from running today (and vice-versa) — separate lock id."""
    from bench import grounded_recall as gr

    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_ENABLED", "true")
    monkeypatch.setenv("GROUNDED_RECALL_AS_NIGHTLY_ENABLED", "true")
    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_HOUR_UTC", "3")

    runs: list[dict] = []

    async def _fake_run_and_alert(*, gate=None, save=True, fixture_path=None,
                                  dispatch=None, language=None,
                                  alert_type="grounded_recall_regression"):
        runs.append({"language": language, "alert_type": alert_type, "gate": gate})
        return {
            "ran": True, "gate_failed": False, "drop": 0.0,
            "alert_dispatched": False, "report": {}, "saved_to": None,
            "gate": gate or 0.05, "alert_outcomes": None,
        }

    monkeypatch.setattr(gr, "run_and_alert_live", _fake_run_and_alert)

    db = _FakeDB(_FakeJobLocks())
    now = datetime(2026, 4, 21, 3, 5, tzinfo=timezone.utc)

    a = _run(gr._try_run_grounded_recall_once(db, now_utc=now))
    b = _run(gr._try_run_grounded_recall_assamese_once(db, now_utc=now))

    assert a["ran"] is True
    assert b["ran"] is True
    assert {r["language"] for r in runs} == {None, "as"}
    as_run = next(r for r in runs if r["language"] == "as")
    assert as_run["alert_type"] == gr._GROUNDED_RECALL_AS_ALERT_TYPE
    # Assamese gets its own (more lenient) gate.
    assert as_run["gate"] == pytest.approx(gr._bench_as_gate(), abs=1e-6)

    # Same-day re-entry on the Assamese loop is deduped by its own lock.
    c = _run(gr._try_run_grounded_recall_assamese_once(db, now_utc=now))
    assert c["ran"] is False


def test_assamese_disabled_via_env(monkeypatch):
    from bench import grounded_recall as gr
    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_ENABLED", "true")
    monkeypatch.setenv("GROUNDED_RECALL_AS_NIGHTLY_ENABLED", "false")

    db = _FakeDB(_FakeJobLocks())
    now = datetime(2026, 4, 21, 3, 5, tzinfo=timezone.utc)
    out = _run(gr._try_run_grounded_recall_assamese_once(db, now_utc=now))
    assert out == {"ran": False, "reason": "disabled"}


def test_global_kill_switch_silences_assamese(monkeypatch):
    """If the operator turns the global nightly bench off, the
    Assamese subset should also stop firing — single off-switch."""
    from bench import grounded_recall as gr
    monkeypatch.setenv("GROUNDED_RECALL_NIGHTLY_ENABLED", "false")
    monkeypatch.setenv("GROUNDED_RECALL_AS_NIGHTLY_ENABLED", "true")

    db = _FakeDB(_FakeJobLocks())
    now = datetime(2026, 4, 21, 3, 5, tzinfo=timezone.utc)
    out = _run(gr._try_run_grounded_recall_assamese_once(db, now_utc=now))
    assert out == {"ran": False, "reason": "disabled"}


# ─── Admin route surfaces the Assamese subset ───────────────────────────

def test_admin_route_returns_assamese_subset(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import edu_browser as m
    from auth_deps import get_admin_user
    from bench import grounded_recall as gr

    # Default-arg binding means patching the module attribute alone
    # won't redirect ``find_latest_result``; redirect the function.
    payload_path = tmp_path
    real_find = gr.find_latest_result

    def _find(results_dir=None, *, language=None):
        return real_find(results_dir=payload_path, language=language)

    monkeypatch.setattr(gr, "find_latest_result", _find)
    payload = {
        "started_at": "2026-04-21T03:05:00+00:00",
        "retriever": "live",
        "total_cases": 8,
        "metrics": {"recall@1": 0.875, "recall@3": 1.0, "recall@5": 1.0,
                    "match_rate": 1.0},
        "mean_citation_count": 1.5,
        "mean_latency_ms": 230.0,
        "per_case": [],
    }
    (tmp_path / "latest_as.json").write_text(json.dumps(payload))

    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    async def _ok_admin():
        return {"id": "t", "email": "t@example.com"}

    app.dependency_overrides[get_admin_user] = _ok_admin
    client = TestClient(app)

    r = client.get("/api/admin/grounded-recall/latest?language=as")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["language"] == "as"
    assert body["has_results"] is True
    assert body["latest"]["metrics"]["recall@5"] == 1.0
    assert body["baseline"] is not None
    assert body["baseline"].get("language") == "as"
