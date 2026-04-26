"""Task #939 — admin route contract tests for the internal-linker.

Locks down the camelCase JSON shape of the seven endpoints the
``LinksTab`` "Pending suggestions" panel consumes:

    GET  /admin/seo/internal-links/status
    GET  /admin/seo/internal-links/pending
    GET  /admin/seo/internal-links/history
    POST /admin/seo/internal-links/{id}/approve
    POST /admin/seo/internal-links/{id}/reject
    POST /admin/seo/internal-links/{id}/revert
    POST /admin/seo/internal-links/trigger
"""
from __future__ import annotations

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
    from routes.admin_seo_internal_linker import router

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


def _matches(d, q):
    for k, v in q.items():
        if isinstance(v, dict):
            if "$in" in v and d.get(k) not in v["$in"]:
                return False
            if "$gte" in v and (d.get(k) is None or d.get(k) < v["$gte"]):
                return False
            if "$exists" in v:
                if v["$exists"] and k not in d:
                    return False
                if not v["$exists"] and k in d:
                    return False
        else:
            if d.get(k) != v:
                return False
    return True


class _FakeColl:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    def find(self, q=None, _proj=None):
        q = q or {}
        return _FakeCursor([d for d in self.docs if _matches(d, q)])

    async def find_one(self, q, _proj=None):
        for d in self.docs:
            if _matches(d, q):
                return dict(d)
        return None

    async def count_documents(self, q):
        return sum(1 for d in self.docs if _matches(d, q))

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    async def update_one(self, q, update, upsert=False):
        sets = update.get("$set") or {}
        on_insert = update.get("$setOnInsert") or {}
        inc = update.get("$inc") or {}
        for d in self.docs:
            if _matches(d, q):
                d.update(sets)
                for k, v in inc.items():
                    d[k] = int(d.get(k) or 0) + int(v)
                return type("R", (), {"modified_count": 1, "upserted_id": None})()
        if upsert:
            new = {**{k: v for k, v in q.items() if not isinstance(v, dict)}, **on_insert, **sets}
            for k, v in inc.items():
                new[k] = int(v)
            self.docs.append(new)
            return type("R", (), {"modified_count": 0, "upserted_id": new.get("_id")})()
        return type("R", (), {"modified_count": 0, "upserted_id": None})()


class _FakeDb:
    def __init__(self, history=None, pages=None, budget=None):
        self.internal_link_history = _FakeColl(history or [])
        self.internal_link_budget = _FakeColl(budget or [])
        self.seo_pages = _FakeColl(pages or [])


# ─── status ────────────────────────────────────────────────────────────


def test_status_shape(client):
    db = _FakeDb(
        history=[
            {"id": "a", "action": "drafted", "created_at": "2026-04-26T00:00:00+00:00"},
            {"id": "b", "action": "auto_applied", "applied_at": "2026-04-26T01:00:00+00:00"},
        ],
        budget=[],
    )
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.get("/admin/seo/internal-links/status")
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] in (True, False)
    assert "budget" in body
    assert "auto_used" in body["budget"]
    assert "auto_cap" in body["budget"]
    assert body["pendingCount"] == 1
    assert "config" in body
    assert "autoApplyThreshold" in body["config"]


# ─── pending ───────────────────────────────────────────────────────────


def test_pending_returns_drafted_only(client):
    db = _FakeDb(history=[
        {"id": "d1", "action": "drafted", "anchor_text": "x",
         "created_at": "2026-04-26T00:00:00+00:00", "diff": {"before_excerpt": "b", "after_excerpt": "a"}},
        {"id": "a1", "action": "auto_applied",
         "created_at": "2026-04-26T00:00:00+00:00"},
    ])
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.get("/admin/seo/internal-links/pending")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    item = items[0]
    # camelCase contract.
    assert item["id"] == "d1"
    assert item["anchorText"] == "x"
    assert item["diff"]["beforeExcerpt"] == "b"
    assert item["diff"]["afterExcerpt"] == "a"


# ─── history ───────────────────────────────────────────────────────────


def test_history_filters_by_action(client):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDb(history=[
        {"id": "x", "action": "auto_applied", "created_at": now,
         "diff": {"before_excerpt": "", "after_excerpt": ""}},
        {"id": "y", "action": "drafted", "created_at": now,
         "diff": {"before_excerpt": "", "after_excerpt": ""}},
    ])
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.get("/admin/seo/internal-links/history?action=auto_applied")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["action"] == "auto_applied"


def test_history_rejects_unknown_action(client):
    db = _FakeDb()
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.get("/admin/seo/internal-links/history?action=nonsense")
    assert res.status_code == 400


# ─── approve / reject / revert ────────────────────────────────────────


def test_approve_404_when_missing(client):
    db = _FakeDb()
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.post("/admin/seo/internal-links/missing/approve")
    assert res.status_code == 404


def test_approve_409_when_anchor_unfindable(client):
    db = _FakeDb(
        history=[{
            "id": "r1", "source_page_id": "S", "target_page_id": "T",
            "anchor_text": "totally absent phrase",
            "target_url": "/x", "action": "drafted",
        }],
        pages=[{
            "id": "S", "topic_id": "ts", "page_type": "notes",
            "content": "<p>no match here</p>",
        }],
    )
    with patch("routes.admin_seo_internal_linker.db", db), \
         patch("seo_internal_linker._persist_body_update", new=_async_noop()):
        res = client.post("/admin/seo/internal-links/r1/approve")
    assert res.status_code == 409


def test_approve_200_inserts_anchor(client):
    db = _FakeDb(
        history=[{
            "id": "r1", "source_page_id": "S", "target_page_id": "T",
            "anchor_text": "Newton", "target_url": "/n", "action": "drafted",
        }],
        pages=[{
            "id": "S", "topic_id": "ts", "page_type": "notes",
            "content": "<p>Newton wrote the laws.</p>",
        }],
    )
    captured = {}

    async def _persist(_db, source, new_body):
        captured["body"] = new_body

    with patch("routes.admin_seo_internal_linker.db", db), \
         patch("seo_internal_linker._persist_body_update", new=_persist):
        res = client.post("/admin/seo/internal-links/r1/approve")
    assert res.status_code == 200
    assert "<!-- syrabit:autolink:T -->" in captured["body"]
    rec = next(d for d in db.internal_link_history.docs if d["id"] == "r1")
    assert rec["action"] == "auto_applied"
    assert rec["approved_by"] == "ops"


def test_reject_200_drops_pending(client):
    db = _FakeDb(history=[{
        "id": "r1", "action": "drafted",
    }])
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.post("/admin/seo/internal-links/r1/reject")
    assert res.status_code == 200
    rec = db.internal_link_history.docs[0]
    assert rec["action"] == "rejected"
    assert rec["rejected_by"] == "ops"


def test_revert_409_when_not_auto_applied(client):
    db = _FakeDb(history=[{"id": "r1", "action": "drafted"}])
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.post("/admin/seo/internal-links/r1/revert")
    assert res.status_code == 409


def test_revert_200_removes_anchor(client):
    body = '<p><!-- syrabit:autolink:T --><a href="/x">Newton</a></p>'
    db = _FakeDb(
        history=[{
            "id": "r1", "source_page_id": "S", "target_page_id": "T",
            "action": "auto_applied",
        }],
        pages=[{
            "id": "S", "topic_id": "ts", "page_type": "notes",
            "content": body,
        }],
    )
    captured = {}

    async def _persist(_db, source, new_body):
        captured["body"] = new_body

    with patch("routes.admin_seo_internal_linker.db", db), \
         patch("seo_internal_linker._persist_body_update", new=_persist):
        res = client.post("/admin/seo/internal-links/r1/revert")
    assert res.status_code == 200
    assert "<!-- syrabit:autolink:T -->" not in captured["body"]
    assert "Newton" in captured["body"]
    rec = db.internal_link_history.docs[0]
    assert rec["action"] == "reverted"


# ─── trigger ──────────────────────────────────────────────────────────


def test_trigger_400_when_no_id(client):
    with patch("routes.admin_seo_internal_linker.db", _FakeDb()):
        res = client.post("/admin/seo/internal-links/trigger", json={})
    assert res.status_code == 400


def test_trigger_404_when_page_missing(client):
    db = _FakeDb()
    with patch("routes.admin_seo_internal_linker.db", db):
        res = client.post(
            "/admin/seo/internal-links/trigger", json={"page_id": "nope"})
    assert res.status_code == 404


def test_trigger_200_runs_propose(client):
    target = {
        "id": "T", "topic_id": "tt", "page_type": "notes",
        "status": "published", "topic_title": "Newton",
        "subject_id": "phys", "subject_slug": "physics",
        "subject_name": "Physics", "topic_slug": "newton",
        "class_slug": "class-11", "board_slug": "ahsec",
        "content": "<p>some body</p>",
    }
    db = _FakeDb(pages=[target])

    async def _fake_propose(*_a, **_kw):
        return [{"action": "drafted"}]

    with patch("routes.admin_seo_internal_linker.db", db), \
         patch("seo_internal_linker.propose_internal_links_for_page",
               new=_fake_propose):
        res = client.post(
            "/admin/seo/internal-links/trigger", json={"page_id": "T"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["rows_created"] == 1
    assert body["actions"] == ["drafted"]


# ─── helpers ──────────────────────────────────────────────────────────


def _async_noop():
    async def _f(*_a, **_kw):
        return None
    return _f
