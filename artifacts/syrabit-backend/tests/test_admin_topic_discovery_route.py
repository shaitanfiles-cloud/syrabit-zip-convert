"""Task #937 — admin route contract tests for topic-discovery endpoints.

Locks down camelCase JSON shapes returned by the four endpoints the
``TopicDiscoveryTab`` consumes:

    GET  /admin/seo/topic-discovery/runs
    GET  /admin/seo/topic-discovery/candidates
    POST /admin/seo/topic-discovery/run-now
    POST /admin/seo/topic-discovery/{candidate_id}/override

Mirrors the patch-based fake-db pattern in
``test_admin_health_alert_history.py`` so a future shared helper change
can be validated against both at once.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest


# ─── auth + app fixtures ───────────────────────────────────────────────


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "sub": "admin-1"}


@pytest.fixture
def client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user
    from routes.admin_topic_discovery import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


# ─── fake mongo ────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._skip = 0
        self._limit = None

    def sort(self, *_a, **_kw):
        return self

    def skip(self, n):
        self._skip = int(n)
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    def __aiter__(self):
        end = self._skip + (self._limit or len(self._docs))
        sliced = self._docs[self._skip:end]

        async def _gen():
            for d in sliced:
                yield d
        return _gen()


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.last_query = None
        self.update_calls: List[Dict[str, Any]] = []

    def find(self, q, _proj=None):
        self.last_query = q
        out = []
        for d in self.docs:
            if _matches(d, q):
                out.append(d)
        return _FakeCursor(out)

    async def find_one(self, q, _proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def count_documents(self, q):
        return sum(1 for d in self.docs if _matches(d, q))

    async def update_one(self, q, update, upsert=False):
        self.update_calls.append({"q": q, "update": update, "upsert": upsert})
        sets = update.get("$set") or {}
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(sets)
                return
        if upsert:
            self.docs.append({**q, **sets})


def _matches(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
    for k, v in q.items():
        if k == "$or":
            if not any(_matches(doc, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict):
            if "$ne" in v and doc.get(k) == v["$ne"]:
                return False
            if "$exists" in v and (k in doc) != bool(v["$exists"]):
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _FakeDb:
    def __init__(self, mapping=None):
        self._map: Dict[str, _FakeColl] = dict(mapping or {})

    def __getitem__(self, name):
        return self._map.setdefault(name, _FakeColl())


def _patch_db(db):
    """Patch ``deps.db`` AND ``routes.admin_topic_discovery.db`` because
    the route imports the symbol at module load time."""
    import deps
    import routes.admin_topic_discovery as route_mod
    return patch.multiple(
        "routes.admin_topic_discovery", db=db,
    ), patch.multiple(deps, db=db)


# ─── /runs ─────────────────────────────────────────────────────────────


def test_runs_returns_empty_when_no_history(client):
    db = _FakeDb()
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.get("/admin/seo/topic-discovery/runs")
    assert r.status_code == 200
    assert r.json() == {"runs": []}


def test_runs_shapes_camel_case_and_filters_daily_locks(client):
    import topic_discovery_service as tds
    started = datetime.now(timezone.utc) - timedelta(hours=1)
    finished = started + timedelta(seconds=42)
    docs = [
        {"id": "run_a", "started_at": started, "finished_at": finished,
         "elapsed_seconds": 42.1,
         "config_snapshot": {"auto_publish_threshold": 80, "draft_threshold": 55},
         "totals": {"raw": 5, "deduped": 4, "auto_published": 1,
                    "drafted": 2, "rejected": 1, "error": 0},
         "remaining_after_run": {"auto_publish": 9, "draft": 48}},
        # Daily lock — must be filtered out.
        {"id": "daily_2026-04-26", "kind": "daily_lock",
         "claimed_at": datetime.now(timezone.utc)},
    ]
    db = _FakeDb({tds.RUNS_COLLECTION: _FakeColl(docs)})
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.get("/admin/seo/topic-discovery/runs")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 1
    row = runs[0]
    assert row["id"] == "run_a"
    assert row["startedAt"].endswith("+00:00") or "T" in row["startedAt"]
    assert row["totals"]["auto_published"] == 1
    assert row["remainingAfterRun"]["auto_publish"] == 9
    assert row["configSnapshot"]["auto_publish_threshold"] == 80


def test_runs_clamps_limit(client):
    db = _FakeDb()
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.get("/admin/seo/topic-discovery/runs?limit=9999")
    assert r.status_code == 422  # FastAPI Query(le=100) enforces upper bound


# ─── /candidates ───────────────────────────────────────────────────────


def _cand(cid, *, decision="rejected", run_id="run_a", query=None,
          enqueued=None, admin_decision=None):
    return {
        "id": cid,
        "run_id": run_id,
        "query": query or f"query for {cid}",
        "sources": ["gsc_near_miss", "trending"],
        "signals": {"gsc_near_miss": {"impressions": 500}},
        "score": {"intent_fit": 70, "syllabus_alignment": 75,
                  "difficulty": 60, "aeo_readability": 80,
                  "total": 72, "reason": "fits well"},
        "decision": decision,
        "decision_reason": "test reason",
        "enqueued_topic": enqueued,
        "created_at": datetime.now(timezone.utc),
        "admin_decision": admin_decision,
    }


def test_candidates_lists_all_when_no_filter(client):
    import topic_discovery_service as tds
    docs = [_cand("c1", decision="auto_published"),
            _cand("c2", decision="drafted"),
            _cand("c3", decision="rejected")]
    db = _FakeDb({tds.CANDIDATES_COLLECTION: _FakeColl(docs)})
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.get("/admin/seo/topic-discovery/candidates")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert {c["id"] for c in body["candidates"]} == {"c1", "c2", "c3"}
    # camelCase shape
    sample = body["candidates"][0]
    assert "decisionReason" in sample
    assert "enqueuedTopic" in sample
    assert "createdAt" in sample
    assert sample["score"]["total"] == 72


def test_candidates_filters_by_decision(client):
    import topic_discovery_service as tds
    docs = [_cand("c1", decision="auto_published"),
            _cand("c2", decision="drafted")]
    db = _FakeDb({tds.CANDIDATES_COLLECTION: _FakeColl(docs)})
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.get("/admin/seo/topic-discovery/candidates?decision=drafted")
    body = r.json()
    assert body["total"] == 1
    assert body["candidates"][0]["id"] == "c2"


def test_candidates_filters_by_run_id(client):
    import topic_discovery_service as tds
    docs = [_cand("c1", run_id="run_a"),
            _cand("c2", run_id="run_b")]
    db = _FakeDb({tds.CANDIDATES_COLLECTION: _FakeColl(docs)})
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.get("/admin/seo/topic-discovery/candidates?run_id=run_b")
    body = r.json()
    assert body["total"] == 1
    assert body["candidates"][0]["runId"] == "run_b"


def test_candidates_rejects_invalid_decision(client):
    db = _FakeDb()
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.get("/admin/seo/topic-discovery/candidates?decision=banana")
    assert r.status_code == 422


# ─── /run-now ──────────────────────────────────────────────────────────


def test_run_now_invokes_orchestrator_and_returns_summary(client):
    fake_summary = {
        "id": "run_x",
        "started_at": datetime.now(timezone.utc),
        "finished_at": datetime.now(timezone.utc),
        "elapsed_seconds": 1.5,
        "config_snapshot": {"auto_publish_threshold": 80},
        "totals": {"raw": 3, "deduped": 3, "auto_published": 1,
                   "drafted": 1, "rejected": 1, "error": 0},
        "remaining_after_run": {"auto_publish": 9, "draft": 49},
    }
    db = _FakeDb()
    p1, p2 = _patch_db(db)
    fake_run = AsyncMock(return_value=fake_summary)
    with p1, p2, patch(
        "topic_discovery_service.run_topic_discovery_once", fake_run,
    ):
        r = client.post("/admin/seo/topic-discovery/run-now")
    assert r.status_code == 200
    assert r.json()["id"] == "run_x"
    assert r.json()["totals"]["auto_published"] == 1
    fake_run.assert_awaited_once()


def test_run_now_500s_on_orchestrator_failure(client):
    db = _FakeDb()
    p1, p2 = _patch_db(db)
    fake_run = AsyncMock(side_effect=RuntimeError("boom"))
    with p1, p2, patch(
        "topic_discovery_service.run_topic_discovery_once", fake_run,
    ):
        r = client.post("/admin/seo/topic-discovery/run-now")
    assert r.status_code == 500


# ─── /override ─────────────────────────────────────────────────────────


def test_override_rejects_unknown_decision(client):
    db = _FakeDb()
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.post(
            "/admin/seo/topic-discovery/cand_1/override",
            json={"decision": "banana", "reason": "x"},
        )
    assert r.status_code == 400


def test_override_404s_when_candidate_missing(client):
    import topic_discovery_service as tds
    db = _FakeDb({tds.CANDIDATES_COLLECTION: _FakeColl([])})
    p1, p2 = _patch_db(db)
    with p1, p2:
        r = client.post(
            "/admin/seo/topic-discovery/missing/override",
            json={"decision": "rejected", "reason": "n/a"},
        )
    assert r.status_code == 404


def test_override_promote_persists_admin_fields(client):
    import topic_discovery_service as tds
    docs = [_cand("c1", decision="rejected")]
    db = _FakeDb({tds.CANDIDATES_COLLECTION: _FakeColl(docs)})
    p1, p2 = _patch_db(db)
    fake_upsert = AsyncMock()
    with p1, p2, patch("seo_writes.upsert_seo_topic", fake_upsert):
        r = client.post(
            "/admin/seo/topic-discovery/c1/override",
            json={"decision": "auto_published", "reason": "manual promote"},
        )
    assert r.status_code == 200
    body = r.json()["candidate"]
    assert body["decision"] == "auto_published"
    assert body["adminDecision"] == "auto_published"
    assert body["adminReason"] == "manual promote"
    assert body["adminId"] == "admin-1"
    fake_upsert.assert_awaited_once()


def test_override_reject_does_not_enqueue(client):
    import topic_discovery_service as tds
    docs = [_cand("c1", decision="drafted")]
    db = _FakeDb({tds.CANDIDATES_COLLECTION: _FakeColl(docs)})
    p1, p2 = _patch_db(db)
    fake_upsert = AsyncMock()
    with p1, p2, patch("seo_writes.upsert_seo_topic", fake_upsert):
        r = client.post(
            "/admin/seo/topic-discovery/c1/override",
            json={"decision": "rejected", "reason": "off-topic"},
        )
    assert r.status_code == 200
    body = r.json()["candidate"]
    assert body["decision"] == "rejected"
    assert body["adminDecision"] == "rejected"
    fake_upsert.assert_not_called()
