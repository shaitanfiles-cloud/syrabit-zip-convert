"""Admin login regression coverage — Supabase-backed credentials.

Admin accounts are now verified via Supabase Auth (sign_in_with_password)
plus an is_admin flag in the users table.  These tests lock in:

1. Happy path: valid Supabase credentials + is_admin=True → 200 + admin JWT.
2. Wrong password (Supabase rejects) → 401.
3. Non-admin Supabase account (is_admin=False) → 403.
4. Supabase user not found in users table → 403.
5. Supabase client unavailable → 503.
6. CF Access enforcement gates (unchanged logic, Task #702).
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_auth_user(email: str):
    u = MagicMock()
    u.email = email
    u.user_metadata = {"full_name": "Test Admin"}
    return u


def _fake_auth_response(email: str):
    r = MagicMock()
    r.user = _fake_auth_user(email)
    return r


def _build_app(
    monkeypatch,
    *,
    supa_sign_in=None,       # callable or exception to raise
    db_user=None,             # dict returned by supa_get_user, or None
    supa_is_none: bool = False,
    cf_enforce: bool = False,
    cf_team_domain: str = "",
    cf_aud: str = "",
):
    """Assemble a fresh FastAPI TestClient with the given mocks.

    We reload `routes.admin_auth_users` fresh so env changes (CF_ACCESS_ENFORCE
    etc.) are picked up at import time, just like in production.
    """
    monkeypatch.setenv("ADMIN_JWT_SECRET", "a" * 64)
    monkeypatch.setenv("JWT_SECRET",       "b" * 64)
    monkeypatch.setenv("CF_ACCESS_ENFORCE", "true" if cf_enforce else "")
    if cf_enforce:
        monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", cf_team_domain)
        monkeypatch.setenv("CF_ACCESS_AUD_ADMIN",   cf_aud)
    else:
        monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN", raising=False)
        monkeypatch.delenv("CF_ACCESS_AUD_ADMIN",   raising=False)

    for mod in ("config", "cf_access", "routes.admin_auth_users"):
        sys.modules.pop(mod, None)

    from tests._deps_stub import install_deps_stub
    stub = install_deps_stub(force=True)

    if supa_is_none:
        stub.supa = None
    else:
        mock_supa = MagicMock()
        if isinstance(supa_sign_in, type) and issubclass(supa_sign_in, Exception):
            mock_supa.auth.sign_in_with_password.side_effect = supa_sign_in("bad creds")
        elif callable(supa_sign_in):
            mock_supa.auth.sign_in_with_password.side_effect = supa_sign_in
        else:
            mock_supa.auth.sign_in_with_password.return_value = _fake_auth_response("ops@syrabit.test")
        stub.supa = mock_supa

    routes_mod = importlib.import_module("routes.admin_auth_users")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(routes_mod.router, prefix="/api")

    async def _mock_supa_get_user(email: str):
        return db_user

    with patch.object(routes_mod, "supa_get_user", _mock_supa_get_user):
        client = TestClient(app, raise_server_exceptions=False)
        yield client, routes_mod


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_admin_login_happy_path(monkeypatch):
    gen = _build_app(
        monkeypatch,
        db_user={"email": "ops@syrabit.test", "name": "Ops Admin", "is_admin": True},
    )
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "s3cret-pa55!"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("access_token")
    assert body.get("email") == "ops@syrabit.test"
    assert body.get("name") == "Ops Admin"


def test_admin_login_strips_form_whitespace_and_case(monkeypatch):
    gen = _build_app(
        monkeypatch,
        db_user={"email": "ops@syrabit.test", "name": "Ops Admin", "is_admin": True},
    )
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "  Ops@Syrabit.TEST  ", "password": "s3cret-pa55! "},
    )
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# Rejection cases
# ---------------------------------------------------------------------------

def test_admin_login_wrong_password_rejected(monkeypatch):
    """Supabase rejects the credentials → 401."""
    try:
        from supabase_auth.errors import AuthApiError
        def _raise(_creds):
            raise AuthApiError("Invalid login credentials", 400, None)
    except ImportError:
        def _raise(_creds):
            raise Exception("Invalid login credentials")

    gen = _build_app(
        monkeypatch,
        supa_sign_in=_raise,
        db_user={"email": "ops@syrabit.test", "name": "Ops Admin", "is_admin": True},
    )
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "wrong"},
    )
    assert res.status_code == 401, res.text


def test_admin_login_non_admin_account_rejected(monkeypatch):
    """Valid Supabase credentials but is_admin=False in users table → 403."""
    gen = _build_app(
        monkeypatch,
        db_user={"email": "staff@syrabit.test", "name": "Staff", "is_admin": False},
    )
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "staff@syrabit.test", "password": "any"},
    )
    assert res.status_code == 403, res.text


def test_admin_login_user_not_in_db_rejected(monkeypatch):
    """Valid Supabase credentials but user not in users table → 403."""
    gen = _build_app(monkeypatch, db_user=None)
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "ghost@syrabit.test", "password": "any"},
    )
    assert res.status_code == 403, res.text


def test_admin_login_503_when_supa_unavailable(monkeypatch):
    """supa=None (client not initialised) → 503, not a confusing 401."""
    gen = _build_app(monkeypatch, supa_is_none=True)
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "anything"},
    )
    assert res.status_code == 503, res.text


# ---------------------------------------------------------------------------
# Task #702 — Cloudflare Access gate on the login entry point
# ---------------------------------------------------------------------------

def test_admin_login_blocked_without_cf_access_jwt_when_enforced(monkeypatch):
    """With CF Access enforcement on, /admin/login must 401 BEFORE the
    Supabase check — an attacker with the right password but no CF JWT
    cannot log in."""
    gen = _build_app(
        monkeypatch,
        cf_enforce=True,
        cf_team_domain="syrabit-test",
        cf_aud="aud-admin-tag",
        db_user={"email": "ops@syrabit.test", "name": "Ops Admin", "is_admin": True},
    )
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "s3cret-pa55!"},
    )
    assert res.status_code == 401, res.text
    assert "Cloudflare Access" in res.json().get("detail", "")


def test_admin_login_unaffected_when_enforcement_off(monkeypatch):
    """Pre-rollout safety: with CF_ACCESS_ENFORCE unset the dependency
    is a strict no-op and the happy path still works."""
    gen = _build_app(
        monkeypatch,
        db_user={"email": "ops@syrabit.test", "name": "Ops Admin", "is_admin": True},
    )
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "s3cret-pa55!"},
    )
    assert res.status_code == 200, res.text
    assert res.json().get("access_token")


def test_admin_login_503_when_cf_access_enforce_on_but_misconfigured(monkeypatch):
    """Fail-closed at the route boundary: CF_ACCESS_ENFORCE=true without
    CF_ACCESS_TEAM_DOMAIN + CF_ACCESS_AUD_ADMIN → 503 (loud misconfig)."""
    gen = _build_app(
        monkeypatch,
        cf_enforce=True,
        cf_team_domain="",
        cf_aud="",
        db_user={"email": "ops@syrabit.test", "name": "Ops Admin", "is_admin": True},
    )
    client, _ = next(gen)
    res = client.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "s3cret-pa55!"},
    )
    assert res.status_code == 503, res.text
    assert "misconfigured" in res.json().get("detail", "").lower()
