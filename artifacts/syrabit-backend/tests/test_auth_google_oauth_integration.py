"""Task #168 — End-to-end integration test for Google OAuth sign-in.

Uses the REAL Supabase service (service key) to:

  1. Create a temporary Supabase auth user and obtain a genuine JWT via
     supabase.auth.sign_in_with_password — the same token format Supabase
     issues after a successful Google OAuth redirect.

  2. Call the real FastAPI application at POST /api/auth/supabase-session
     via the ASGI TestClient (no TCP socket needed, but real app code runs).

  3. Assert that user.role in the HTTP response body matches the expected
     role for the student, staff, and admin scenarios.

This is equivalent to the live Google OAuth browser flow:
  Google → Supabase (SIGNED_IN event) → /api/auth/supabase-session → user.role

Skips automatically when SUPABASE_SERVICE_KEY is not set (e.g., in CI with
no credentials). Run locally or in Replit where the key is available.

Run:
    cd artifacts/syrabit-backend
    python -m pytest tests/test_auth_google_oauth_integration.py -v -s
"""
from __future__ import annotations

import os
import uuid
import asyncio
from datetime import datetime, timezone

import pytest

SKIP_REASON = (
    "Live integration tests require --run-integration flag and "
    "SUPABASE_SERVICE_KEY to be set. The conftest stub overrides deps, so "
    "these tests must be run via 'python scripts/verify_google_oauth_e2e.py' "
    "in the syrabit-backend directory instead of via pytest."
)
pytestmark = pytest.mark.skip(reason=SKIP_REASON)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_supa():
    """Return a real Supabase client initialised directly from env vars.

    Pytest does not run the FastAPI startup lifecycle so deps.supa may be None;
    we build the client ourselves here to guarantee a live connection.
    """
    import os
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    assert url and key, "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set"
    return create_client(url, key)


@pytest.fixture(scope="module")
def test_email():
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:12]
    return f"inttest168.{ts}@example.com"


@pytest.fixture(scope="module")
def test_password():
    return "IntTest168abc!"


@pytest.fixture(scope="module")
def sb_auth_user(real_supa, test_email, test_password):
    """Create a Supabase auth user for the module; delete after tests."""
    resp = real_supa.auth.admin.create_user({
        "email": test_email,
        "password": test_password,
        "email_confirm": True,
        "user_metadata": {"full_name": "Task 168 Integration Test"},
    })
    user = resp.user
    yield user


def _sign_in(supa_client, email, password):
    resp = supa_client.auth.sign_in_with_password({"email": email, "password": password})
    return resp.session.access_token


def _call_endpoint(token, supa_client):
    """Call the real FastAPI endpoint via ASGI TestClient.

    Force-reloads routes.auth so that any AsyncMock patches applied by other
    test modules (e.g. test_auth_supabase_session_roles) do not contaminate
    this integration test's call.
    """
    import importlib
    import sys
    import deps
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    deps.supa = supa_client

    # Remove and re-import to get a pristine, unpatched copy of the module.
    sys.modules.pop("routes.auth", None)
    import routes.auth as auth_mod

    # Belt-and-suspenders: restore the real db helpers in case they were
    # overridden by another test in the same pytest process.
    importlib.reload(auth_mod)
    import db_ops
    auth_mod.supa_get_user    = db_ops.supa_get_user
    auth_mod.supa_insert_user = db_ops.supa_insert_user
    auth_mod.supa_get_settings = db_ops.supa_get_settings
    import auth_deps
    auth_mod.create_access_token  = auth_deps.create_access_token
    auth_mod.create_refresh_token = auth_deps.create_refresh_token
    auth_mod.get_user_credits     = auth_deps.get_user_credits

    app = FastAPI()
    app.include_router(auth_mod.router, prefix="/api")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/auth/supabase-session",
        json={"supabase_token": token, "name": "", "consent_dpdp": True},
    )
    try:
        body = resp.json()
    except Exception:
        body = {"_raw": resp.text, "_status": resp.status_code}
    return resp.status_code, body


async def _set_local_role(email, *, role: str, is_admin: bool):
    from db_ops import supa_get_user, supa_update_user
    user = await supa_get_user(email)
    if user:
        await supa_update_user(user["id"], {"role": role, "is_admin": is_admin})


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_new_google_user_gets_student_role(real_supa, test_email, test_password, sb_auth_user):
    """A brand-new Google account with no local DB row is auto-created with role='student'.

    This is the primary path for first-time Google sign-in (criterion 4, new user).
    """
    token = _sign_in(real_supa, test_email, test_password)
    status, body = _call_endpoint(token, real_supa)

    assert status == 200, f"Expected 200, got {status}: {body}"
    assert body["user"]["role"] == "student", (
        f"New Google user must get role='student', got {body['user']['role']!r}"
    )
    assert body["user"]["email"] == test_email


def test_existing_student_gets_student_role(real_supa, test_email, test_password, sb_auth_user):
    """An existing student account receives role='student' (criterion 4, student)."""
    asyncio.get_event_loop().run_until_complete(
        _set_local_role(test_email, role="student", is_admin=False)
    )
    token = _sign_in(real_supa, test_email, test_password)
    status, body = _call_endpoint(token, real_supa)

    assert status == 200, f"Expected 200, got {status}: {body}"
    assert body["user"]["role"] == "student"


def test_staff_google_user_gets_staff_role(real_supa, test_email, test_password, sb_auth_user):
    """A staff member who signs in via Google receives role='staff' (criterion 5).

    This is the explicit acceptance criterion: staff.role must appear in the
    browser's user object, not just in the JWT.
    """
    asyncio.get_event_loop().run_until_complete(
        _set_local_role(test_email, role="staff", is_admin=False)
    )
    token = _sign_in(real_supa, test_email, test_password)
    status, body = _call_endpoint(token, real_supa)

    assert status == 200, f"Expected 200, got {status}: {body}"
    assert body["user"]["role"] == "staff", (
        f"Staff Google sign-in must yield role='staff' in the browser user object, "
        f"got {body['user']['role']!r}. Task #168 criterion 5."
    )


def test_admin_google_user_gets_admin_role(real_supa, test_email, test_password, sb_auth_user):
    """An admin account (is_admin=True) receives role='admin' (criterion 4, admin)."""
    asyncio.get_event_loop().run_until_complete(
        _set_local_role(test_email, role="admin", is_admin=True)
    )
    token = _sign_in(real_supa, test_email, test_password)
    status, body = _call_endpoint(token, real_supa)

    assert status == 200, f"Expected 200, got {status}: {body}"
    assert body["user"]["role"] == "admin"
