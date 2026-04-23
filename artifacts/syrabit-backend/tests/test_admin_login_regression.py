"""Task #700 — admin login regression coverage.

Locks in the two failure modes that have historically masked themselves
as a generic "Invalid credentials" 401:

1. Happy path: a configured admin can sign in with the exact env-loaded
   email/password and gets back an access_token + bearer cookie.
2. Wrong password for a known admin email returns 401, not a 200 with a
   stray token.

These tests exercise the parser-and-handler pipeline together (env →
ADMIN_ACCOUNTS → /admin/login) so future drift in either side fails the
test instead of silently shipping.
"""
from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture
def admin_app(monkeypatch):
    # Point the env at a known admin account, including a wrapping-quote
    # case to prove the parser strips them (the original regression).
    monkeypatch.setenv("ADMIN_EMAILS", '"ops@syrabit.test"')
    monkeypatch.setenv("ADMIN_PASSWORDS", "  s3cret-pa55!  ")
    monkeypatch.setenv("ADMIN_NAMES", "Ops Admin")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "test-admin-secret-do-not-use")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-do-not-use")
    monkeypatch.setenv("CF_ACCESS_ENFORCE", "")

    # Force a fresh config + route import so the env above is observed.
    for mod in ("config", "routes.admin_auth_users"):
        sys.modules.pop(mod, None)

    from tests._deps_stub import install_deps_stub
    install_deps_stub(force=True)

    config = importlib.import_module("config")
    assert config.ADMIN_ACCOUNTS, "env-driven ADMIN_ACCOUNTS should not be empty"
    # Quotes stripped, password trimmed, email lowercased.
    assert config.ADMIN_ACCOUNTS[0]["email"] == "ops@syrabit.test"
    assert config.ADMIN_ACCOUNTS[0]["password"] == "s3cret-pa55!"

    routes_mod = importlib.import_module("routes.admin_auth_users")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(routes_mod.router, prefix="/api")
    return TestClient(app)


def test_admin_login_happy_path(admin_app):
    res = admin_app.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "s3cret-pa55!"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("access_token")
    assert body.get("email") == "ops@syrabit.test"
    assert body.get("name") == "Ops Admin"


def test_admin_login_strips_form_whitespace_and_case(admin_app):
    # Browsers can submit emails with surrounding whitespace if the user
    # pasted the address — login must still succeed.
    res = admin_app.post(
        "/api/admin/login",
        json={"email": "  Ops@Syrabit.TEST  ", "password": "s3cret-pa55! "},
    )
    assert res.status_code == 200, res.text


def test_admin_login_invalid_password_rejected(admin_app):
    res = admin_app.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "wrong"},
    )
    assert res.status_code == 401


def test_admin_login_unknown_email_rejected(admin_app):
    res = admin_app.post(
        "/api/admin/login",
        json={"email": "nobody@syrabit.test", "password": "s3cret-pa55!"},
    )
    assert res.status_code == 401


def test_admin_login_503_when_no_admins_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "")
    monkeypatch.setenv("ADMIN_PASSWORDS", "")
    monkeypatch.setenv("ADMIN_NAMES", "")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "test-admin-secret-do-not-use")
    monkeypatch.delenv("ENABLE_E2E_ADMIN", raising=False)

    for mod in ("config", "routes.admin_auth_users"):
        sys.modules.pop(mod, None)

    from tests._deps_stub import install_deps_stub
    install_deps_stub(force=True)

    config = importlib.import_module("config")
    assert config.ADMIN_ACCOUNTS == []

    routes_mod = importlib.import_module("routes.admin_auth_users")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(routes_mod.router, prefix="/api")
    client = TestClient(app)

    res = client.post(
        "/api/admin/login",
        json={"email": "ops@syrabit.test", "password": "anything"},
    )
    # Loud failure surfaces the misconfiguration instead of pretending
    # the credentials are wrong.
    assert res.status_code == 503
