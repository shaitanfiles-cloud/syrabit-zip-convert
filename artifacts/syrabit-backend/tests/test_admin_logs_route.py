"""Task #944 — admin route tests for /api/admin/logs and /api/logs/ingest.

Covers:
  - ingest auth (missing token, wrong token, correct token, paused)
  - admin list pagination + filter passthrough
  - trace endpoint
  - status snapshot fields
  - pause / resume toggling api_config + dao runtime override
  - rotate-token return + activity-log breadcrumb
  - clear records + activity-log breadcrumb
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import patch, AsyncMock

import pytest

import unified_logs_dao as dao
from tests.test_unified_logs_dao import _FakeColl, _FakeDb


# ─── shared fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "username": "ops", "name": "Ops"}


@pytest.fixture
def fake_db_with_token(monkeypatch):
    """Returns a _FakeDb with the ingest token pre-seeded in api_config."""
    monkeypatch.setenv("LOG_INGEST_TOKEN", "test-ingest-token")
    monkeypatch.delenv("LOGS_PAUSED", raising=False)
    dao._reset_backend_shipper_for_tests()
    db = _FakeDb()
    return db


@pytest.fixture
def client(mock_admin, fake_db_with_token, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user
    import routes.admin_logs as routes
    from db_ops import supa_insert_activity_log  # noqa: F401

    monkeypatch.setattr(routes, "db", fake_db_with_token, raising=False)
    monkeypatch.setattr(dao, "logger", dao.logger)  # no-op to avoid lint

    # Patch the activity-log breadcrumb so tests don't try to hit Supabase.
    activity_calls: List[Dict[str, Any]] = []

    async def _fake_activity(rec):
        activity_calls.append(dict(rec))
        return None
    monkeypatch.setattr(routes, "supa_insert_activity_log", _fake_activity)

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    cl = TestClient(app)
    cl._activity = activity_calls  # type: ignore[attr-defined]
    cl._db = fake_db_with_token   # type: ignore[attr-defined]
    return cl


# ─── /api/logs/ingest ─────────────────────────────────────────────────


def test_ingest_rejects_missing_token(client):
    r = client.post("/api/logs/ingest", json={"logs": [{"source": "edge"}]})
    assert r.status_code == 401


def test_ingest_rejects_wrong_token(client):
    r = client.post(
        "/api/logs/ingest",
        json={"logs": [{"source": "edge"}]},
        headers={"X-Logs-Ingest-Token": "wrong"},
    )
    assert r.status_code == 401


def test_ingest_accepts_correct_token_and_inserts(client):
    r = client.post(
        "/api/logs/ingest",
        json={"source": "edge", "logs": [
            {"status": 200, "duration_ms": 10, "route": "/x"},
            {"status": 500, "duration_ms": 20, "route": "/y"},
        ]},
        headers={"X-Logs-Ingest-Token": "test-ingest-token"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["accepted"] == 2
    assert body["dropped"] == 0
    assert body["paused"] is False
    coll = client._db[dao.UNIFIED_LOGS_COLLECTION]  # type: ignore[attr-defined]
    assert len(coll.docs) == 2


def test_ingest_returns_paused_when_kill_switch_on(client, monkeypatch):
    monkeypatch.setenv("LOGS_PAUSED", "1")
    r = client.post(
        "/api/logs/ingest",
        json={"logs": [{"source": "edge", "status": 200}]},
        headers={"X-Logs-Ingest-Token": "test-ingest-token"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["paused"] is True
    assert body["accepted"] == 0
    assert body["dropped"] == 1


def test_ingest_rejects_oversize_batch(client, monkeypatch):
    huge = [{"source": "edge"}] * (dao.MAX_INGEST_BATCH + 1)
    r = client.post(
        "/api/logs/ingest",
        json={"logs": huge},
        headers={"X-Logs-Ingest-Token": "test-ingest-token"},
    )
    assert r.status_code == 413


def test_ingest_503s_when_token_unconfigured(client, monkeypatch):
    monkeypatch.delenv("LOG_INGEST_TOKEN", raising=False)
    # Also clear api_config persistence:
    client._db.api_config.docs = []  # type: ignore[attr-defined]
    r = client.post("/api/logs/ingest", json={"logs": []})
    assert r.status_code == 503


# ─── /api/admin/logs ──────────────────────────────────────────────────


def test_admin_list_returns_logs_and_count(client):
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge",    "status": 200, "route": "/a",
         "timestamp": "2026-04-26T10:00:00Z"},
        {"source": "edge",    "status": 500, "route": "/b",
         "timestamp": "2026-04-26T10:01:00Z"},
        {"source": "backend", "status": 200, "route": "/c",
         "timestamp": "2026-04-26T10:02:00Z"},
    ], default_source="edge"))
    r = client.get("/api/admin/logs?sources=edge&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["total_capped"] is False
    assert all(row["source"] == "edge" for row in body["logs"])
    assert len(body["logs"]) == 2


def test_admin_list_filters_by_status_range(client):
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge", "status": 200},
        {"source": "edge", "status": 404},
        {"source": "edge", "status": 500},
    ], default_source="edge"))
    r = client.get("/api/admin/logs?status_min=400&status_max=499")
    assert r.status_code == 200
    body = r.json()
    assert {row["status"] for row in body["logs"]} == {404}


# ─── /api/admin/logs/trace ────────────────────────────────────────────


def test_admin_trace_lookup(client):
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge", "correlation_id": "trace-1", "status": 200,
         "timestamp": "2026-04-26T10:00:00Z"},
        {"source": "backend", "correlation_id": "trace-1", "status": 500,
         "timestamp": "2026-04-26T10:00:01Z"},
        {"source": "edge", "correlation_id": "trace-2", "status": 200},
    ], default_source="edge"))
    r = client.get("/api/admin/logs/trace/trace-1")
    assert r.status_code == 200
    body = r.json()
    assert body["correlation_id"] == "trace-1"
    assert body["total"] == 2


# ─── /api/admin/logs/status ───────────────────────────────────────────


def test_admin_status_reports_token_and_pause(client):
    r = client.get("/api/admin/logs/status")
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is False
    assert body["ingest_token_configured"] is True
    assert body["ttl_days"] >= 1
    assert body["max_ingest_batch"] >= 1
    # Status MUST surface per-source counts so the live-tail header
    # can render "edge: N • backend: M • cloudflare: K". We assert the
    # exact key + that every allowed source has a numeric counter.
    assert "counts" in body, body
    counts = body["counts"]
    for src in dao.ALLOWED_SOURCES:
        assert src in counts, f"missing source {src} in {counts}"
        assert isinstance(counts[src], int)
    # Also assert the CF-pull observability fields are present so the
    # admin can see when the last pull tick ran.
    assert "cf_pull_interval_s" in body
    assert "shipper_stats" in body


# ─── pause / resume ───────────────────────────────────────────────────


def test_pause_resume_toggles_runtime_state(client):
    r = client.post("/api/admin/logs/pause")
    assert r.status_code == 200
    assert dao._logs_paused_env() is True

    r = client.post("/api/admin/logs/resume")
    assert r.status_code == 200
    assert dao._logs_paused_env() is False


# ─── rotate-token ─────────────────────────────────────────────────────


def test_rotate_token_returns_new_token_and_breadcrumbs(client):
    r = client.post("/api/admin/logs/rotate-token")
    assert r.status_code == 200
    body = r.json()
    assert "token" in body and isinstance(body["token"], str) and len(body["token"]) > 20
    # The plaintext is now persisted in api_config so a worker can pick it up.
    assert any(d.get("token") == body["token"]
               for d in client._db.api_config.docs)  # type: ignore[attr-defined]
    # Activity-log breadcrumb fired.
    assert any(rec.get("action") == "unified_logs_token_rotated"
               for rec in client._activity)  # type: ignore[attr-defined]


# ─── DELETE /api/admin/logs ───────────────────────────────────────────


def test_clear_drops_logs_and_writes_breadcrumb(client):
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge",    "status": 200},
        {"source": "edge",    "status": 500},
        {"source": "backend", "status": 200},
    ], default_source="edge"))
    r = client.delete("/api/admin/logs?sources=edge")
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 2
    assert any(rec.get("action") == "unified_logs_cleared"
               for rec in client._activity)  # type: ignore[attr-defined]
    # Backend record survived the scoped purge.
    assert len(db[dao.UNIFIED_LOGS_COLLECTION].docs) == 1


def test_clear_rejects_unknown_sources_instead_of_full_purge(client):
    """Footgun guard: ?sources=garbage MUST 400 — never silently
    broaden into a full purge of every source."""
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge",    "status": 200},
        {"source": "backend", "status": 200},
    ], default_source="edge"))
    r = client.delete("/api/admin/logs?sources=blogspot,definitely_not_a_source")
    assert r.status_code == 400, r.text
    assert "Refusing destructive purge" in r.json()["detail"]
    # Nothing should have been deleted by the rejected request.
    assert len(db[dao.UNIFIED_LOGS_COLLECTION].docs) == 2


def test_clear_with_mix_of_valid_and_invalid_sources_only_purges_valid(client):
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge",    "status": 200},
        {"source": "backend", "status": 200},
    ], default_source="edge"))
    # 'edge' is valid, 'garbage' is silently dropped — should purge
    # only the edge row (NOT a full purge).
    r = client.delete("/api/admin/logs?sources=edge,garbage")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1
    assert len(db[dao.UNIFIED_LOGS_COLLECTION].docs) == 1


def test_clear_rejects_empty_sources_param(client):
    """``?sources=`` (present-but-empty) MUST 400 — operators must
    omit the param entirely to do a full purge, never pass an empty
    string."""
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge", "status": 200},
    ], default_source="edge"))
    for empty in ("", "   ", ",", " , ,"):
        r = client.delete(f"/api/admin/logs?sources={empty}")
        assert r.status_code == 400, f"empty={empty!r}: {r.text}"
        assert "empty" in r.json()["detail"].lower() or "Refusing" in r.json()["detail"]
    # Original record untouched after every rejected attempt.
    assert len(db[dao.UNIFIED_LOGS_COLLECTION].docs) == 1


def test_clear_with_no_sources_param_does_full_purge(client):
    """The ONLY way to trigger a full purge is to omit ?sources=
    entirely. This is the documented intentional behaviour."""
    db = client._db  # type: ignore[attr-defined]
    asyncio.run(dao.insert_logs(db, [
        {"source": "edge",    "status": 200},
        {"source": "backend", "status": 200},
    ], default_source="edge"))
    r = client.delete("/api/admin/logs")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 2
    assert len(db[dao.UNIFIED_LOGS_COLLECTION].docs) == 0
