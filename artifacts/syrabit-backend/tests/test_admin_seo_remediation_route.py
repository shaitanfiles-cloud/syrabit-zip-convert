"""Task #938 — admin route contract tests for the closed-loop
content remediation endpoints.

Locks down camelCase JSON shapes returned by the four endpoints
the ``RemediationTab`` consumes:

    GET  /admin/seo/remediation/status
    GET  /admin/seo/remediation/history
    POST /admin/seo/remediation/{rec_id}/promote
    POST /admin/seo/remediation/trigger
    POST /admin/seo/remediation/circuit/reset

Mirrors the patch-based fake-db pattern in
``test_admin_topic_discovery_route.py`` so a future shared helper
change can be validated against both at once.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ─── auth + app fixtures ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_queue():
    """Pre-Mongo-queue tests reset an in-process asyncio queue.
    The durable Mongo-backed queue is now per-test thanks to the
    ``_FakeDb()`` instance constructed in each test, so this
    fixture is a no-op kept for forward-compat with any future
    module-level state we might re-introduce."""
    yield


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "username": "ops", "sub": "admin-1"}


@pytest.fixture
def client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user
    from routes.admin_seo_remediation import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


# ─── fake mongo (cursor + collection) ──────────────────────────────────


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
        self.docs = list(docs or [])
        self.last_query = None
        self.update_calls: List[Dict[str, Any]] = []

    def find(self, q, _proj=None):
        self.last_query = q
        out = [d for d in self.docs if _matches(d, q)]
        return _FakeCursor(out)

    async def find_one(self, q, _proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_one(self, q, update, upsert=False):
        self.update_calls.append({"q": q, "update": update, "upsert": upsert})
        sets = update.get("$set") or {}
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(sets)
                return
        if upsert:
            self.docs.append({**q, **sets})

    async def update_many(self, q, update):
        sets = update.get("$set") or {}
        n = 0
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(sets)
                n += 1
        return type("R", (), {"modified_count": n})()

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("_id")})()

    async def find_one_and_update(self, q, update, projection=None,
                                  return_document=None, **_kw):
        """Mimic motor's atomic find_and_update — returns the
        pre-update doc (default behaviour) on match, None otherwise."""
        sets = update.get("$set") or {}
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                pre = dict(d)
                d.update(sets)
                return pre
        return None


def _matches(doc, q):
    for k, v in q.items():
        if isinstance(v, dict):
            if "$gte" in v and not (str(doc.get(k, "")) >= str(v["$gte"])):
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _FakeDb:
    """Tiny container exposing the four collections the route reads."""
    def __init__(self):
        self.seo_remediation_history = _FakeColl()
        self.seo_remediation_budget = _FakeColl()
        self.seo_remediation_circuit = _FakeColl()
        self.seo_remediation_signals = _FakeColl()
        self.seo_pages = _FakeColl()


def _patch_db(db):
    """Patch the routes-module ``db`` symbol AND the bound ``db`` on
    the seo_remediation_service helpers (status/promote both
    delegate into the service)."""
    return [
        patch("routes.admin_seo_remediation.db", db),
    ]


def _enter(patches):
    return [p.__enter__() for p in patches]


def _exit(patches):
    for p in patches:
        p.__exit__(None, None, None)


# ─── /status ───────────────────────────────────────────────────────────


def test_status_returns_budget_circuit_and_config(client):
    db = _FakeDb()
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.get("/admin/seo/remediation/status")
    finally:
        _exit(patches)
    assert r.status_code == 200
    body = r.json()
    assert "enabled" in body
    assert "budget" in body
    assert body["budget"]["auto_used"] == 0
    assert body["budget"]["draft_used"] == 0
    assert body["budget"]["auto_cap"] >= 1
    assert "circuit" in body
    assert body["circuit"]["is_open"] is False
    assert "config" in body
    assert body["config"]["minImprovementDelta"] >= 0
    assert body["config"]["fanoutCapPerEvent"] >= 1


# ─── /history ──────────────────────────────────────────────────────────


def _hist_row(rec_id, *, action="auto_republished", at=None,
              page_id="p1", topic_title="Photosynthesis",
              page_type="notes", before=70, after=82, promoted=False):
    at = at or datetime.now(timezone.utc).isoformat()
    return {
        "id": rec_id,
        "signal_id": f"sig-{rec_id}",
        "signal_kind": "url_404_spike",
        "signal_url": "/board/x/biology/photosynthesis",
        "signal_details": {"sitemap": "main"},
        "detected_at": at,
        "attempted_at": at,
        "promoted_at": at if promoted else None,
        "page_id": page_id,
        "topic_id": "t1",
        "topic_title": topic_title,
        "page_type": page_type,
        "topic_slug": "photosynthesis",
        "subject_slug": "biology",
        "before_status": "published",
        "after_status": "published",
        "scores": {"before": before, "after": after, "delta": after - before},
        "action": action,
        "reason": "test",
        "error": None,
    }


def test_history_returns_camelcase_shape(client):
    db = _FakeDb()
    db.seo_remediation_history.docs = [
        _hist_row("r1", action="auto_republished", before=60, after=80),
        _hist_row("r2", action="drafted", before=70, after=72),
        _hist_row("r3", action="skipped_no_improvement",
                  before=80, after=70),
    ]
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.get("/admin/seo/remediation/history")
    finally:
        _exit(patches)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["windowDays"] == 7
    sample = body["items"][0]
    # camelCase keys present + score breakdown is flattened.
    assert "attemptedAt" in sample
    assert "signalKind" in sample
    assert "topicTitle" in sample
    assert "scoreBefore" in sample
    assert "scoreAfter" in sample
    assert "scoreDelta" in sample
    assert sample["signalDetails"] == {"sitemap": "main"}


def test_history_filters_by_action(client):
    db = _FakeDb()
    db.seo_remediation_history.docs = [
        _hist_row("r1", action="auto_republished"),
        _hist_row("r2", action="drafted"),
    ]
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.get("/admin/seo/remediation/history?action=drafted")
    finally:
        _exit(patches)
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "r2"


def test_history_rejects_unknown_action(client):
    db = _FakeDb()
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.get("/admin/seo/remediation/history?action=nope")
    finally:
        _exit(patches)
    assert r.status_code == 400


def test_history_clamps_days_window(client):
    db = _FakeDb()
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.get("/admin/seo/remediation/history?days=999")
    finally:
        _exit(patches)
    # Query() le=30 enforces the upper bound.
    assert r.status_code == 422


# ─── /promote ──────────────────────────────────────────────────────────


def test_promote_publishes_drafted_attempt(client):
    db = _FakeDb()
    db.seo_remediation_history.docs = [
        _hist_row("r1", action="drafted"),
    ]
    db.seo_pages.docs = [
        {"id": "p1", "status": "draft", "in_sitemap": False, "title": "X"},
    ]
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post("/admin/seo/remediation/r1/promote")
    finally:
        _exit(patches)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert "promoted_at" in body
    # Page flipped to published + in_sitemap.
    page = db.seo_pages.docs[0]
    assert page["status"] == "published"
    assert page["in_sitemap"] is True
    # History row stamped with promoted_at + promoted_by.
    rec = db.seo_remediation_history.docs[0]
    assert rec["promoted_at"]
    assert rec["promoted_by"] == "ops"


def test_promote_404s_when_record_missing(client):
    db = _FakeDb()
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post("/admin/seo/remediation/missing/promote")
    finally:
        _exit(patches)
    assert r.status_code == 404


def test_promote_400s_when_action_was_not_drafted(client):
    db = _FakeDb()
    db.seo_remediation_history.docs = [
        _hist_row("r1", action="auto_republished"),
    ]
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post("/admin/seo/remediation/r1/promote")
    finally:
        _exit(patches)
    assert r.status_code == 400


def test_promote_409s_when_already_promoted(client):
    db = _FakeDb()
    db.seo_remediation_history.docs = [
        _hist_row("r1", action="drafted", promoted=True),
    ]
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post("/admin/seo/remediation/r1/promote")
    finally:
        _exit(patches)
    assert r.status_code == 409


def test_promote_409s_when_page_no_longer_draft(client):
    """Race condition: someone else published the page after the
    remediation worker filed the draft. Refusing to re-publish
    avoids stomping a manual edit."""
    db = _FakeDb()
    db.seo_remediation_history.docs = [_hist_row("r1", action="drafted")]
    db.seo_pages.docs = [{"id": "p1", "status": "published"}]
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post("/admin/seo/remediation/r1/promote")
    finally:
        _exit(patches)
    assert r.status_code == 409


# ─── /trigger ──────────────────────────────────────────────────────────


def test_trigger_enqueues_signal_and_returns_id(client):
    db = _FakeDb()
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post(
            "/admin/seo/remediation/trigger",
            json={"url": "/board/x/biology/photosynthesis"},
        )
    finally:
        _exit(patches)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["enqueued"] is True
    assert body["signal_id"]
    # The trigger persisted a single PENDING signal to the durable
    # Mongo queue so the leader's poller can pick it up — verify
    # the admin context (URL + triggered_by) is carried through.
    docs = db.seo_remediation_signals.docs
    assert len(docs) == 1
    sig_doc = docs[0]
    assert sig_doc["status"] == "pending"
    assert sig_doc["kind"] == "manual_trigger"
    assert sig_doc["url"] == "/board/x/biology/photosynthesis"
    assert sig_doc["payload"]["details"]["triggered_by"] == "ops"
    assert sig_doc["_id"] == body["signal_id"]


def test_trigger_400s_when_no_target(client):
    db = _FakeDb()
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post("/admin/seo/remediation/trigger", json={})
    finally:
        _exit(patches)
    assert r.status_code == 400


# ─── /circuit/reset ────────────────────────────────────────────────────


def test_circuit_reset_clears_state(client):
    db = _FakeDb()
    # Prime the circuit doc as if a trip had occurred.
    db.seo_remediation_circuit.docs = [{
        "_id": "state",
        "disabled_until": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "recent_attempts": [{"action": "drafted"}, {"action": "drafted"}],
    }]
    patches = _patch_db(db)
    _enter(patches)
    try:
        r = client.post("/admin/seo/remediation/circuit/reset")
    finally:
        _exit(patches)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "reset_at" in body
    # Reset cleared disabled_until + drained recent_attempts.
    doc = db.seo_remediation_circuit.docs[0]
    assert doc.get("disabled_until") is None
    assert doc.get("recent_attempts") == []
