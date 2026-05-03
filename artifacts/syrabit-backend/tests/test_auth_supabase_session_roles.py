"""Task #168 / Task #170 — Verify Google OAuth role resolution in /api/auth/supabase-session.

The old /api/auth/google endpoint always assigned 'student' regardless of the
DB role field (Task #156 bug). That endpoint has been removed. The replacement
is /api/auth/supabase-session, which resolves role from the DB record.

These tests confirm the three branches of the role-resolution logic, checking
BOTH the JWT token role AND the user.role field returned in the response body
(the value the browser's user object will contain):

  - is_admin=True  → role="admin"   in JWT and user object
  - role="staff"   → role="staff"   in JWT and user object
  - regular user   → role="student" in JWT and user object
  - new user (auto-created via Google OAuth) → role="student" in JWT and user object

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
    """A user with no special flags gets role='student' in the JWT and in the
    user object returned to the browser."""
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
    assert resp.json()["user"]["role"] == "student", (
        "Browser user object must carry role='student' for a regular account"
    )


def test_staff_role_issued_for_staff_user():
    """A user with role='staff' in the DB gets role='staff' in the JWT AND in
    the user object returned to the browser (Task #168 criterion 5)."""
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
    assert resp.json()["user"]["role"] == "staff", (
        "Browser user object must carry role='staff' — Task #168 criterion 5"
    )


def test_admin_role_issued_for_admin_user():
    """A user with is_admin=True gets role='admin' in the JWT regardless of
    the role field, confirming is_admin takes priority.
    The user object returned to the browser also carries role='admin'."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="admin@example.com")
    _patch_supa_client(auth_mod, sb_user)

    user_record = _base_user_record(
        email="admin@example.com", is_admin=True, role="admin"
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
    assert resp.json()["user"]["role"] == "admin", (
        "Browser user object must carry role='admin' for admin accounts"
    )


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


# ──────────────────────────────────────────────────────────────────
# Task #172 — Google OAuth auto-create gated by registrations_open
# Task #168 — confirm new-user path assigns role='student' in browser
# ──────────────────────────────────────────────────────────────────

def test_new_google_user_blocked_when_registrations_closed():
    """A brand-new Google OAuth user is rejected with 403 when
    registrations_open=False.  supa_get_user returns None (unknown email),
    so the endpoint must check settings before creating an account."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="newcomer@gmail.com")
    _patch_supa_client(auth_mod, sb_user)

    # No existing account for this email.
    auth_mod.supa_get_user = AsyncMock(return_value=None)
    # Registrations are closed.
    auth_mod.supa_get_settings = AsyncMock(
        return_value={"registrations_open": False}
    )

    client = TestClient(app)
    resp = client.post("/api/auth/supabase-session", json=_SUPABASE_SESSION_BODY)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Registrations are currently closed"
    # Confirm no account was written.
    auth_mod.supa_insert_user.assert_not_called()


def test_new_google_user_auto_created_with_student_role():
    """A brand-new Google OAuth user gets an account and role='student' when
    registrations_open=True. supa_insert_user must be called exactly once.
    Both the JWT token and the browser user object must carry role='student'
    (Task #168 criterion 4 — new-user path; Task #172 — registrations gate)."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="newuser@gmail.com")
    _patch_supa_client(auth_mod, sb_user)

    # No existing account for this email.
    auth_mod.supa_get_user = AsyncMock(return_value=None)
    # Registrations are open (default, but be explicit).
    auth_mod.supa_get_settings = AsyncMock(
        return_value={"registrations_open": True}
    )

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
    # Confirm account creation was triggered exactly once.
    auth_mod.supa_insert_user.assert_called_once()
    # New user has no is_admin / role flags → student.
    assert captured_role["role"] == "student"
    assert resp.json()["access_token"] == "tok-student"
    assert resp.json()["user"]["role"] == "student", (
        "Auto-created Google users must start with role='student'"
    )
    assert resp.json()["user"]["email"] == "newuser@gmail.com"


def test_banned_account_returns_403():
    """A user whose DB record has status='banned' must be refused with HTTP 403
    and never reach token-issuance logic."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="banned@example.com")
    _patch_supa_client(auth_mod, sb_user)

    banned_record = _base_user_record(email="banned@example.com")
    banned_record["status"] = "banned"
    auth_mod.supa_get_user = AsyncMock(return_value=banned_record)

    client = TestClient(app)
    resp = client.post("/api/auth/supabase-session", json=_SUPABASE_SESSION_BODY)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Account banned"


def test_existing_user_can_sign_in_when_registrations_closed():
    """An existing user must receive a 200 and a valid token even when
    registrations_open=False.  The guard only applies to brand-new accounts;
    it lives in the ``else`` branch of ``if existing:``, so existing users
    should never see a 403 regardless of the registration setting."""
    from fastapi.testclient import TestClient

    app, auth_mod = _build_app()

    sb_user = _make_sb_user(email="returning@example.com")
    _patch_supa_client(auth_mod, sb_user)

    # Existing account found — registrations_open check must be skipped.
    auth_mod.supa_get_user = AsyncMock(
        return_value=_base_user_record(email="returning@example.com")
    )
    # Registrations are closed — must NOT affect existing users.
    auth_mod.supa_get_settings = AsyncMock(
        return_value={"registrations_open": False}
    )

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
    assert "access_token" in resp.json()
    assert captured_role["role"] == "student"
    # Existing user — no new account should be created.
    auth_mod.supa_insert_user.assert_not_called()
