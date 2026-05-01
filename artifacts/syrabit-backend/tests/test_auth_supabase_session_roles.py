"""Task #170 — Verify Google OAuth role resolution in /api/auth/supabase-session.

The old /api/auth/google endpoint always assigned 'student' regardless of the
DB role field (Task #156 bug). That endpoint has been removed. The replacement
is /api/auth/supabase-session, which resolves role from the DB record.

These tests confirm the three branches of the role-resolution logic:
  - is_admin=True  → role="admin"  in the issued JWT
  - role="staff"   → role="staff" in the issued JWT
  - regular user   → role="student" in the issued JWT

All tests mock the Supabase auth.get_user call so no real Supabase network
traffic is produced.
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
    """Mount the auth router on a minimal FastAPI app with heavy
    dependencies stubbed out so tests focus on role resolution only."""
    from fastapi import FastAPI
    from routes import auth as auth_mod

    auth_mod.supa_get_settings = AsyncMock(return_value={"registrations_open": True})
    auth_mod.supa_insert_user = AsyncMock(return_value=None)

    app = FastAPI()
    app.include_router(auth_mod.router, prefix="/api")
    return app, auth_mod


def _make_sb_user(email: str = "user@example.com"):
    """Return a minimal Supabase user-like object."""
    sb_user = MagicMock()
    sb_user.email = email
    sb_user.user_metadata = {"full_name": "Test User"}
    return sb_user


def _patch_supa_client(auth_mod, sb_user):
    """Install a fake Supabase client on deps so the endpoint can call
    auth.get_user without hitting the real Supabase service."""
    import deps

    fake_response = MagicMock()
    fake_response.user = sb_user

    fake_auth = MagicMock()
    fake_auth.get_user = MagicMock(return_value=fake_response)

    fake_supa = MagicMock()
    fake_supa.auth = fake_auth

    deps.supa = fake_supa


def _base_user_record(
    *,
    email: str = "user@example.com",
    is_admin: bool = False,
    role: str = "student",
) -> dict:
    return {
        "id": "uid-001",
        "name": "Test User",
        "email": email,
        "password_hash": "",
        "plan": "free",
        "credits_used": 0,
        "credits_limit": 30,
        "onboarding_done": True,
        "is_admin": is_admin,
        "role": role,
        "status": "active",
        "bio": "",
        "phone": "",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


_SUPABASE_SESSION_BODY = {
    "supabase_token": "fake-sb-token",
    "name": "",
    "consent_dpdp": True,
}


# ──────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────

def test_student_role_issued_for_regular_user():
    """A user with no special flags gets role='student' in the JWT."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user()
    _patch_supa_client(auth_mod, sb_user)

    user_record = _base_user_record(is_admin=False, role="student")
    auth_mod.supa_get_user = AsyncMock(return_value=user_record)

    captured_role = {}

    def _fake_token(user_id, *, role, plan):
        captured_role["role"] = role
        return f"tok-{role}"

    auth_mod.create_access_token = _fake_token
    auth_mod.create_refresh_token = lambda *a, **k: "refresh"

    async def _credits(_u):
        return {"used": 0, "limit": 30}

    auth_mod.get_user_credits = _credits

    client = TestClient(app)
    resp = client.post("/api/auth/supabase-session", json=_SUPABASE_SESSION_BODY)

    assert resp.status_code == 200, resp.text
    assert captured_role["role"] == "student"
    assert resp.json()["access_token"] == "tok-student"


def test_staff_role_issued_for_staff_user():
    """A user with role='staff' in the DB gets role='staff' in the JWT."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="staff@school.com")
    _patch_supa_client(auth_mod, sb_user)

    user_record = _base_user_record(
        email="staff@school.com", is_admin=False, role="staff"
    )
    auth_mod.supa_get_user = AsyncMock(return_value=user_record)

    captured_role = {}

    def _fake_token(user_id, *, role, plan):
        captured_role["role"] = role
        return f"tok-{role}"

    auth_mod.create_access_token = _fake_token
    auth_mod.create_refresh_token = lambda *a, **k: "refresh"

    async def _credits(_u):
        return {"used": 0, "limit": 30}

    auth_mod.get_user_credits = _credits

    client = TestClient(app)
    resp = client.post("/api/auth/supabase-session", json=_SUPABASE_SESSION_BODY)

    assert resp.status_code == 200, resp.text
    assert captured_role["role"] == "staff"
    assert resp.json()["access_token"] == "tok-staff"


def test_admin_role_issued_for_admin_user():
    """A user with is_admin=True gets role='admin' in the JWT regardless of
    the role field, confirming is_admin takes priority."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="admin@example.com")
    _patch_supa_client(auth_mod, sb_user)

    user_record = _base_user_record(
        email="admin@example.com", is_admin=True, role="student"
    )
    auth_mod.supa_get_user = AsyncMock(return_value=user_record)

    captured_role = {}

    def _fake_token(user_id, *, role, plan):
        captured_role["role"] = role
        return f"tok-{role}"

    auth_mod.create_access_token = _fake_token
    auth_mod.create_refresh_token = lambda *a, **k: "refresh"

    async def _credits(_u):
        return {"used": 0, "limit": 30}

    auth_mod.get_user_credits = _credits

    client = TestClient(app)
    resp = client.post("/api/auth/supabase-session", json=_SUPABASE_SESSION_BODY)

    assert resp.status_code == 200, resp.text
    assert captured_role["role"] == "admin"
    assert resp.json()["access_token"] == "tok-admin"


def test_is_admin_takes_priority_over_staff_role():
    """When a user has both is_admin=True and role='staff', the JWT must
    carry 'admin' — is_admin is evaluated first in the resolution chain."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="superstaff@example.com")
    _patch_supa_client(auth_mod, sb_user)

    user_record = _base_user_record(
        email="superstaff@example.com", is_admin=True, role="staff"
    )
    auth_mod.supa_get_user = AsyncMock(return_value=user_record)

    captured_role = {}

    def _fake_token(user_id, *, role, plan):
        captured_role["role"] = role
        return f"tok-{role}"

    auth_mod.create_access_token = _fake_token
    auth_mod.create_refresh_token = lambda *a, **k: "refresh"

    async def _credits(_u):
        return {"used": 0, "limit": 30}

    auth_mod.get_user_credits = _credits

    client = TestClient(app)
    resp = client.post("/api/auth/supabase-session", json=_SUPABASE_SESSION_BODY)

    assert resp.status_code == 200, resp.text
    assert captured_role["role"] == "admin"


def test_invalid_supabase_token_returns_401():
    """When Supabase token verification raises, the endpoint must return 401
    and never reach role-resolution logic."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    import deps

    fake_auth = MagicMock()
    fake_auth.get_user = MagicMock(side_effect=Exception("token expired"))

    fake_supa = MagicMock()
    fake_supa.auth = fake_auth
    deps.supa = fake_supa

    auth_mod.supa_get_user = AsyncMock(return_value=None)

    client = TestClient(app)
    resp = client.post("/api/auth/supabase-session", json=_SUPABASE_SESSION_BODY)

    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Invalid or expired Supabase token"
