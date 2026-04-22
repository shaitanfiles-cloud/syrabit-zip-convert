"""Task #671 — Turnstile enforcement on /auth/signup and /auth/login.

The build brief requires Cloudflare Turnstile verification on the
signup, login, and chat surfaces. Chat already verifies; this test
locks in the same behaviour for the auth routes:

- When `CF_TURNSTILE_ENABLED` is False (dev / local), the check is a
  pass-through (same pattern as chat).
- When enabled, a missing or invalid token must reject the request
  with HTTP 400 `{detail: "turnstile_failed"}`.
- A valid token (siteverify returns success) must let the route
  continue and complete normally.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _build_auth_app():
    """Mount the auth router on a minimal FastAPI app with the heavy
    DB / password-hash / cookie dependencies stubbed out so the test
    only exercises the Turnstile gate + happy-path return shape."""
    from fastapi import FastAPI
    from routes import auth as auth_mod

    auth_mod.supa_get_user = AsyncMock(return_value=None)
    auth_mod.supa_insert_user = AsyncMock(return_value=None)
    auth_mod.supa_update_user = AsyncMock(return_value=None)
    auth_mod.supa_get_settings = AsyncMock(return_value={"registrations_open": True})
    auth_mod.create_access_token = lambda *a, **k: "test-access"
    auth_mod.create_refresh_token = lambda *a, **k: "test-refresh"

    class _PwdCtx:
        @staticmethod
        def hash(_pw):
            return "hashed"

        @staticmethod
        def verify(_pw, _h):
            return True

    auth_mod.pwd_ctx = _PwdCtx()

    app = FastAPI()
    app.include_router(auth_mod.router, prefix="/api")
    return app, auth_mod


def _signup_body():
    return {
        "name": "Test User",
        "email": "test@example.com",
        "password": "hunter2hunter2",
        "consent_dpdp": True,
    }


def _login_body():
    return {"email": "test@example.com", "password": "hunter2hunter2"}


# ──────────────────────────────────────────────────────────────────
# Disabled (dev/local) — Turnstile must be a no-op on both routes
# ──────────────────────────────────────────────────────────────────
def test_signup_skips_turnstile_when_disabled():
    from fastapi.testclient import TestClient
    import turnstile_verify as tv_mod

    tv_mod.CF_TURNSTILE_ENABLED = False

    app, _ = _build_auth_app()
    client = TestClient(app)
    resp = client.post("/api/auth/signup", json=_signup_body())
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token") == "test-access"


def test_login_skips_turnstile_when_disabled():
    from fastapi.testclient import TestClient
    import turnstile_verify as tv_mod

    tv_mod.CF_TURNSTILE_ENABLED = False

    app, auth_mod = _build_auth_app()
    auth_mod.supa_get_user = AsyncMock(return_value={
        "id": "u1", "name": "Test", "email": "test@example.com",
        "password_hash": "hashed", "plan": "free", "status": "active",
        "is_admin": False, "credits_used": 0, "credits_limit": 30,
        "onboarding_done": True, "created_at": "2026-01-01T00:00:00+00:00",
    })

    async def _credits(_u):
        return {"used": 0, "limit": 30}

    auth_mod.get_user_credits = _credits

    client = TestClient(app)
    resp = client.post("/api/auth/login", json=_login_body())
    assert resp.status_code == 200, resp.text
    assert resp.json().get("access_token") == "test-access"


# ──────────────────────────────────────────────────────────────────
# Enabled — happy path (valid token) and rejection (invalid token)
# ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("token_valid", [True, False])
def test_signup_enforces_turnstile_when_enabled(token_valid, monkeypatch):
    from fastapi.testclient import TestClient
    import turnstile_verify as tv_mod

    tv_mod.CF_TURNSTILE_ENABLED = True
    monkeypatch.setattr(
        tv_mod,
        "verify_turnstile_token",
        AsyncMock(return_value=token_valid),
    )

    app, _ = _build_auth_app()
    client = TestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json=_signup_body(),
        headers={"x-turnstile-token": "tok-from-widget"},
    )

    if token_valid:
        assert resp.status_code == 200, resp.text
        assert resp.json().get("access_token") == "test-access"
    else:
        assert resp.status_code == 400, resp.text
        assert resp.json().get("detail") == "turnstile_failed"


@pytest.mark.parametrize("token_valid", [True, False])
def test_login_enforces_turnstile_when_enabled(token_valid, monkeypatch):
    from fastapi.testclient import TestClient
    import turnstile_verify as tv_mod

    tv_mod.CF_TURNSTILE_ENABLED = True
    monkeypatch.setattr(
        tv_mod,
        "verify_turnstile_token",
        AsyncMock(return_value=token_valid),
    )

    app, auth_mod = _build_auth_app()
    auth_mod.supa_get_user = AsyncMock(return_value={
        "id": "u1", "name": "Test", "email": "test@example.com",
        "password_hash": "hashed", "plan": "free", "status": "active",
        "is_admin": False, "credits_used": 0, "credits_limit": 30,
        "onboarding_done": True, "created_at": "2026-01-01T00:00:00+00:00",
    })

    async def _credits(_u):
        return {"used": 0, "limit": 30}

    auth_mod.get_user_credits = _credits

    client = TestClient(app)
    resp = client.post(
        "/api/auth/login",
        json=_login_body(),
        headers={"x-turnstile-token": "tok-from-widget"},
    )

    if token_valid:
        assert resp.status_code == 200, resp.text
        assert resp.json().get("access_token") == "test-access"
    else:
        assert resp.status_code == 400, resp.text
        assert resp.json().get("detail") == "turnstile_failed"


def test_signup_missing_token_rejected_when_enabled(monkeypatch):
    """Even if the verifier would say success on an empty token, the
    route must reject a request that doesn't carry the header at all
    (bot bypass via direct POST)."""
    from fastapi.testclient import TestClient
    import turnstile_verify as tv_mod

    tv_mod.CF_TURNSTILE_ENABLED = True
    # Verifier should never even get called when token is missing.
    fake_verify = AsyncMock(return_value=True)
    monkeypatch.setattr(tv_mod, "verify_turnstile_token", fake_verify)

    app, _ = _build_auth_app()
    client = TestClient(app)
    resp = client.post("/api/auth/signup", json=_signup_body())

    assert resp.status_code == 400
    assert resp.json().get("detail") == "turnstile_failed"
    fake_verify.assert_not_called()


def test_login_missing_token_rejected_when_enabled(monkeypatch):
    from fastapi.testclient import TestClient
    import turnstile_verify as tv_mod

    tv_mod.CF_TURNSTILE_ENABLED = True
    fake_verify = AsyncMock(return_value=True)
    monkeypatch.setattr(tv_mod, "verify_turnstile_token", fake_verify)

    app, _ = _build_auth_app()
    client = TestClient(app)
    resp = client.post("/api/auth/login", json=_login_body())

    assert resp.status_code == 400
    assert resp.json().get("detail") == "turnstile_failed"
    fake_verify.assert_not_called()
