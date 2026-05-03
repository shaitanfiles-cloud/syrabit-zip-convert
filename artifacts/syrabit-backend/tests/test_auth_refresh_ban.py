"""Task #175 — Verify that the /api/auth/refresh endpoint blocks banned accounts.

If a user is banned after they already hold a valid refresh token they must
not be able to use that token to obtain a new access token.  The endpoint
must look up the user's current DB record on every refresh attempt and refuse
with HTTP 403 / "Account banned" when status == "banned".

Mock pattern mirrors test_auth_supabase_session_roles.py:
  - heavy dependencies (deps, cache, db_ops) are stubbed before import
  - only the module-level functions used by the endpoint are monkey-patched
  - no real network, DB, or Redis calls are made
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests._deps_stub import install_deps_stub

install_deps_stub()


# ──────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────

def _build_app():
    """Mount the admin_auth_users router on a minimal FastAPI app with
    heavy dependencies stubbed so tests focus on ban-check behaviour."""
    import sys

    # Stub cache module before the route module imports it.
    import types
    import cachetools
    if "cache" not in sys.modules:
        cache_stub = types.ModuleType("cache")
        cache_stub._redis_invalidate_session = MagicMock()
        cache_stub._redis_get_session = MagicMock(return_value=None)
        cache_stub._redis_cache_session = MagicMock()
        cache_stub._redis_get_conversation = MagicMock(return_value=None)
        cache_stub._redis_cache_conversation = MagicMock()
        cache_stub._redis_invalidate_conversation = MagicMock()
        cache_stub._invalidate_user_cache = MagicMock()
        cache_stub._invalidate_conv_cache = MagicMock()
        cache_stub._user_cache = cachetools.TTLCache(maxsize=100, ttl=900)
        cache_stub._conv_cache = cachetools.TTLCache(maxsize=100, ttl=600)
        cache_stub._conv_cache_key = lambda conv_id, uid: f"{uid}:{conv_id}"
        cache_stub.redis_list_all_anon_conversations = AsyncMock(return_value=[])
        sys.modules["cache"] = cache_stub

    # Stub cloudflare_client used by admin_auth_users at import time.
    if "cloudflare_client" not in sys.modules:
        cf_stub = types.ModuleType("cloudflare_client")
        sys.modules["cloudflare_client"] = cf_stub

    # Stub analytics_helpers.
    if "analytics_helpers" not in sys.modules:
        ah_stub = types.ModuleType("analytics_helpers")
        ah_stub.get_recent_user_events = AsyncMock(return_value=[])
        ah_stub.get_session_metrics = AsyncMock(return_value={})
        sys.modules["analytics_helpers"] = ah_stub

    # Stub cf_access.
    if "cf_access" not in sys.modules:
        cf_access_stub = types.ModuleType("cf_access")
        async def _noop_admin(*a, **kw):
            return {}
        cf_access_stub.require_cf_access_admin = _noop_admin
        sys.modules["cf_access"] = cf_access_stub

    from fastapi import FastAPI
    from routes import admin_auth_users as mod

    # Patch module-level callables used by the refresh endpoint.
    mod._redis_invalidate_session = MagicMock()
    mod.create_access_token = lambda uid, *, role, plan: f"new-access-{uid}"

    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    return app, mod


def _base_user(*, status: str = "active") -> dict:
    return {
        "id": "uid-001",
        "name": "Test User",
        "email": "user@example.com",
        "plan": "free",
        "is_admin": False,
        "role": "student",
        "status": status,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _patch_decode_token(mod, payload: dict):
    """Replace decode_token in the route module with one returning ``payload``."""
    mod.decode_token = lambda token: payload
    mod.JWTError = Exception


# ──────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────

def test_banned_user_refresh_returns_403():
    """A user whose DB record carries status='banned' must be refused at the
    refresh endpoint with HTTP 403 and detail 'Account banned'.  The new
    access token must never be issued and session invalidation must not run."""
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock

    app, mod = _build_app()

    _patch_decode_token(mod, {"type": "refresh", "sub": "uid-001"})
    mod.supa_get_user_by_id = AsyncMock(return_value=_base_user(status="banned"))

    token_spy = MagicMock(wraps=mod.create_access_token)
    mod.create_access_token = token_spy

    client = TestClient(app)
    resp = client.post(
        "/api/auth/refresh",
        headers={"Authorization": "Bearer fake-refresh-token"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Account banned"
    token_spy.assert_not_called()
    mod._redis_invalidate_session.assert_not_called()


def test_active_user_refresh_returns_200():
    """An active user with a valid refresh token must receive a new access
    token (HTTP 200)."""
    from fastapi.testclient import TestClient

    app, mod = _build_app()

    _patch_decode_token(mod, {"type": "refresh", "sub": "uid-001"})
    mod.supa_get_user_by_id = AsyncMock(return_value=_base_user(status="active"))

    client = TestClient(app)
    resp = client.post(
        "/api/auth/refresh",
        headers={"Authorization": "Bearer fake-refresh-token"},
    )

    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()


def test_missing_refresh_token_returns_401():
    """A request with no refresh token (neither cookie nor Authorization
    header) must be refused with HTTP 401."""
    from fastapi.testclient import TestClient

    app, mod = _build_app()

    mod.supa_get_user_by_id = AsyncMock(return_value=None)

    client = TestClient(app)
    resp = client.post("/api/auth/refresh")

    assert resp.status_code == 401, resp.text


def test_unknown_user_refresh_returns_401():
    """A refresh token for a user_id not found in the DB must be refused
    with HTTP 401 (user not found), not 403."""
    from fastapi.testclient import TestClient

    app, mod = _build_app()

    _patch_decode_token(mod, {"type": "refresh", "sub": "uid-unknown"})
    mod.supa_get_user_by_id = AsyncMock(return_value=None)

    client = TestClient(app)
    resp = client.post(
        "/api/auth/refresh",
        headers={"Authorization": "Bearer fake-refresh-token"},
    )

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "User not found"
