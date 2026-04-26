"""Task #940 — admin route contract tests for the Entity SEO panel.

Locks down the camelCase JSON shape of the three endpoints:

    GET  /admin/seo/entity/status
    GET  /admin/seo/entity/history
    POST /admin/seo/entity/refresh
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "username": "ops", "sub": "admin-1"}


@pytest.fixture
def client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user
    from routes.admin_entity_seo import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


# ─── tiny fake mongo ──────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._limit = None

    def sort(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    async def to_list(self, n):
        end = min(self._limit or len(self._docs), int(n))
        return self._docs[:end]


class _FakeColl:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    def find(self, _q=None, *_a, **_kw):
        return _FakeCursor(self.docs)

    async def find_one(self, q=None, sort=None, *_a, **_kw):
        if not self.docs:
            return None
        if sort:
            key, direction = sort[0]
            return sorted(self.docs, key=lambda d: d.get(key) or 0,
                          reverse=(direction < 0))[0]
        return self.docs[0]

    async def update_one(self, q, update, upsert=False):
        # Naive merge — sufficient for the route under test.
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                if "$set" in update:
                    d.update(update["$set"])
                return None
        if upsert:
            new = dict(q)
            if "$set" in update:
                new.update(update["$set"])
            self.docs.append(new)


class _FakeDb:
    def __init__(self):
        self.entity_seo_health = _FakeColl()
        self.job_locks = _FakeColl()

    def __getitem__(self, name):
        return getattr(self, name)


def _snap(week, status="ok", regressions=None):
    return {
        "iso_week": week,
        "generated_at": datetime(2026, 4, 27, 4, 30, tzinfo=timezone.utc),
        "aggregate_status": status,
        "signals": {
            "wikidata":  {"status": "ok", "summary": "wd", "fields": {"qid": "Q1", "claim_count": 5, "present_claims": ["P31"], "missing_claims": []}},
            "wikipedia": {"status": "ok", "summary": "wp", "fields": {}},
            "crunchbase":{"status": "ok", "summary": "cb", "fields": {}},
            "sameas":    {"status": "ok", "summary": "sa", "fields": {"total": 7, "broken": []}},
            "google_kg": {"status": "ok", "summary": "kg", "fields": {}},
        },
        "drift": {
            "had_baseline": True,
            "regressions": regressions or [],
            "improvements": [],
            "summary_deltas": {
                "wikidata_claims":  {"current": 5, "previous": 5, "delta": 0},
                "wikidata_missing": {"current": 0, "previous": 0, "delta": 0},
                "sameas_broken":    {"current": 0, "previous": 0, "delta": 0},
            },
        },
        "missing_claims": [],
        "summary": {"wikidata_claims": 5, "wikidata_missing": 0, "sameas_broken": 0},
    }


# ─── /status ──────────────────────────────────────────────────────────


def test_status_returns_camelcase_payload(client):
    db = _FakeDb()
    db.entity_seo_health.docs = [_snap("2026-W17"), _snap("2026-W16")]

    with patch("routes.admin_entity_seo.db", db), \
         patch("routes.admin_entity_seo.is_mongo_available", return_value=True):
        r = client.get("/admin/seo/entity/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["snapshot"]["aggregate_status"] == "ok"
    assert "summaryDeltas" in body["drift"]
    assert "regressions" in body["drift"]
    # The dataclass-style snapshot still uses snake-case keys for the
    # signal payloads (those are persisted shape, not API shape) —
    # the panel reads those directly.
    assert "signals" in body["snapshot"]


def test_status_handles_empty_collection(client):
    db = _FakeDb()
    with patch("routes.admin_entity_seo.db", db), \
         patch("routes.admin_entity_seo.is_mongo_available", return_value=True):
        r = client.get("/admin/seo/entity/status")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot"] is None
    # Even with no snapshot the missing-claims list is fully populated
    # so the admin can immediately start filing — the deep-links are
    # generated against the no-QID fallback.
    assert len(body["missingClaims"]) > 0
    for c in body["missingClaims"]:
        assert c["edit_url"].startswith("https://www.wikidata.org/wiki/")


def test_status_503_when_mongo_unavailable(client):
    with patch("routes.admin_entity_seo.is_mongo_available", return_value=False):
        r = client.get("/admin/seo/entity/status")
    assert r.status_code == 503


# ─── /history ─────────────────────────────────────────────────────────


def test_history_returns_recent_snapshots(client):
    db = _FakeDb()
    db.entity_seo_health.docs = [_snap("2026-W17"), _snap("2026-W16", regressions=[
        {"name": "wikidata", "from": "ok", "to": "missing", "summary": "s"},
    ])]
    with patch("routes.admin_entity_seo.db", db), \
         patch("routes.admin_entity_seo.is_mongo_available", return_value=True):
        r = client.get("/admin/seo/entity/history?limit=5")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    for it in items:
        assert "isoWeek" in it
        assert "aggregateStatus" in it
        assert "summary" in it
    # The week with regressions surfaces its count for the chart.
    assert any(i["regressionCount"] == 1 for i in items)


# ─── /refresh ─────────────────────────────────────────────────────────


def test_refresh_invokes_collector_and_returns_status(client):
    db = _FakeDb()
    db.entity_seo_health.docs = [_snap("2026-W17")]

    async def _fake_run(_db, _now, *, force=False):
        return {"claimed": True, "stored": True, "iso_week": "2026-W17",
                "aggregate_status": "ok", "regression_count": 0, "paged": False}

    with patch("routes.admin_entity_seo.db", db), \
         patch("routes.admin_entity_seo.is_mongo_available", return_value=True), \
         patch("routes.admin_entity_seo.esh._try_run_entity_seo_once", new=_fake_run):
        r = client.post("/admin/seo/entity/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["refresh"]["stored"] is True
    assert body["refresh"]["regression_count"] == 0
    assert "snapshot" in body
