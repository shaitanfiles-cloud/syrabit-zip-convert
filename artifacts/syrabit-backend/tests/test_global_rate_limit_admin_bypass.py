"""Regression tests for ``GlobalRateLimitMiddleware`` admin bypass.

The admin dashboard fans out 30+ admin endpoints in parallel from a
single browser session on first load (and the BreakGlassBanner polls
``/admin/diagnostics`` every 60 s on top of that). The previous IP-based
cap (free-plan ``req_per_min_ip = 60``) was getting blown immediately,
which produced a ~minute-long 429 storm across the whole admin UI.

The most visible symptom was the BreakGlassBanner falling into its
"diagnostics unavailable, retrying" stale state during normal admin
sessions — not just during real Cloudflare Access incidents.

These tests pin the bypass: an authenticated admin (``is_admin=true``
or ``role=='admin'`` JWT claim) must NOT be 429ed by the IP cap. Every
other caller (anon, plain student) must still be capped exactly as
before so the abuse protection on public endpoints is preserved.
"""
import os

# Set a deterministic JWT secret BEFORE auth_deps / middleware import
# so the tokens we mint here can be decoded inside the middleware.
os.environ.setdefault("JWT_SECRET", "test-secret-global-rate-limit")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import middleware as _mw  # noqa: E402
from auth_deps import create_token  # noqa: E402


def _build_app(monkeypatch, *, allow_rate_limit: bool):
    """Build a minimal FastAPI app that mounts ONLY the global rate
    limit middleware, with ``check_rate_limit`` stubbed to a known
    answer. We always have it return ``allow_rate_limit`` — i.e. when
    we want to verify the 429 path we set ``False`` (the bucket is
    full); when we want to verify the bypass we still set ``False``
    so any non-bypassed caller would be 429ed."""
    monkeypatch.setattr(_mw, "check_rate_limit", lambda *a, **kw: allow_rate_limit)
    # Disable the bot-spoof / bot-verify branch so the middleware does
    # not try to hit the real DNS verifier in the test loop.
    monkeypatch.setattr(_mw, "verify_bot_ip", lambda *a, **kw: False)
    # Skip the IP-block cache check (returns False = not blocked).
    monkeypatch.setattr(_mw, "_is_ip_blocked", lambda _h: False)
    # No Redis-cached session enrichment; the JWT claims are enough.
    monkeypatch.setattr(_mw, "_redis_get_session", lambda _u: None)

    app = FastAPI()
    app.add_middleware(_mw.GlobalRateLimitMiddleware)

    @app.get("/api/admin/diagnostics")
    def _diag():
        return {"ok": True}

    @app.get("/api/admin/dashboard")
    def _dash():
        return {"ok": True}

    return app


def _admin_token() -> str:
    return create_token({"sub": "admin-1", "is_admin": True, "role": "admin", "plan": "free"})


def _student_token() -> str:
    return create_token({"sub": "student-1", "role": "student", "plan": "free"})


def test_anonymous_request_is_429ed_when_bucket_full(monkeypatch):
    """Baseline: with the rate limiter exhausted, an anonymous caller
    must still receive HTTP 429 — the abuse cap on public endpoints
    is unchanged."""
    app = _build_app(monkeypatch, allow_rate_limit=False)
    client = TestClient(app)
    resp = client.get("/api/admin/diagnostics")
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "60"


def test_student_request_is_429ed_when_bucket_full(monkeypatch):
    """Plain authenticated students do NOT bypass the IP cap — only
    admins do. Otherwise any free-tier user could escape the abuse
    cap by simply being logged in."""
    app = _build_app(monkeypatch, allow_rate_limit=False)
    client = TestClient(app)
    resp = client.get(
        "/api/admin/diagnostics",
        headers={"Authorization": f"Bearer {_student_token()}"},
    )
    assert resp.status_code == 429


def test_admin_request_bypasses_rate_limit_via_is_admin_claim(monkeypatch):
    """An admin JWT (``is_admin=True``) must pass straight through the
    middleware even when the IP bucket is exhausted. This is the
    regression: the admin dashboard's parallel fan-out used to 429-
    storm itself on first load and silently mask the BreakGlassBanner
    diagnostics."""
    app = _build_app(monkeypatch, allow_rate_limit=False)
    client = TestClient(app)
    resp = client.get(
        "/api/admin/diagnostics",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}


def test_admin_request_bypasses_rate_limit_via_role_claim(monkeypatch):
    """Same bypass triggers off ``role == 'admin'`` so historical
    tokens that don't carry ``is_admin`` (created by
    :func:`create_access_token`) still get the bypass."""
    token = create_token({"sub": "admin-2", "role": "admin", "plan": "free"})
    app = _build_app(monkeypatch, allow_rate_limit=False)
    client = TestClient(app)
    resp = client.get(
        "/api/admin/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_admin_bypass_does_not_apply_to_non_api_paths(monkeypatch):
    """The middleware short-circuits non-``/api`` paths *before* it
    decodes the token, so an admin hitting a non-API path is simply
    not rate-limited (and not authenticated either) by this layer.
    Ensures the bypass code-path doesn't accidentally leak into the
    page-routing surface."""
    app = _build_app(monkeypatch, allow_rate_limit=False)
    # Mount a non-/api route to confirm the early-return still works.
    @app.get("/some/page")
    def _page():
        return {"ok": True}
    client = TestClient(app)
    resp = client.get("/some/page")
    assert resp.status_code == 200
