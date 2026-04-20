"""Contract test for GET /api/admin/grounded-recall/latest.

Ensures the admin observability endpoint keeps returning the shape the
frontend tile depends on (ok / latest / baseline / has_results) and is
protected by the admin dependency.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _build_app(*, admin_ok: bool):
    from routes import edu_browser as m
    from auth_deps import get_admin_user

    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    async def _ok_admin():
        return {"id": "t", "email": "t@example.com"}

    async def _deny():
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_admin_user] = _ok_admin if admin_ok else _deny
    return app


def test_requires_admin_auth():
    client = TestClient(_build_app(admin_ok=False))
    r = client.get("/api/admin/grounded-recall/latest")
    assert r.status_code == 401


def test_returns_expected_shape():
    client = TestClient(_build_app(admin_ok=True))
    r = client.get("/api/admin/grounded-recall/latest")
    assert r.status_code == 200
    body = r.json()
    # Contract: these keys must always be present so the frontend tile
    # can render without undefined-access errors.
    for key in ("ok", "latest", "baseline", "has_results"):
        assert key in body, f"missing key {key!r} in response"
    # Baseline.json is committed, so it should always come back populated.
    assert body["baseline"] is not None
    assert "metrics" in body["baseline"]
    for metric in ("recall@1", "recall@3", "recall@5"):
        assert metric in body["baseline"]["metrics"]
