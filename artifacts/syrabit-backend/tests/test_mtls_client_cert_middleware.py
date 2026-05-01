"""Task #123 — MtlsClientCertMiddleware behaviour tests.

Verifies all guard cases for the mTLS HMAC enforcement middleware:

1. No-op when ORIGIN_SHARED_SECRET is unset (backward-compat).
2. No-op when ENFORCE_MTLS is not set, even if ORIGIN_SHARED_SECRET is present.
3. Rejects (403) when the X-Cf-Mtls-Active header is missing.
4. Rejects (403) when the X-Cf-Mtls-Active header carries a wrong HMAC.
5. Passes (200) when the header carries the correct HMAC.
6. Probe paths /api/livez, /api/readyz, /api/ready are exempt without the header.
7. /api/health is NOT exempt — blocked without the correct HMAC.

Task #135 — misconfiguration alerting:
8. MTLS_MISCONFIGURED flag is True when ENFORCE_MTLS=true but secret is absent.
9. MTLS_MISCONFIGURED flag is False when ENFORCE_MTLS=true and secret is present.
10. MTLS_MISCONFIGURED flag is False when ENFORCE_MTLS is not set.
11. A readyz-style endpoint returns 503 when MTLS_MISCONFIGURED is True.
12. A readyz-style endpoint returns 200 when MTLS_MISCONFIGURED is False.
13. The startup ERROR log contains the expected keywords when misconfigured.
14. The REAL /api/readyz handler returns 503 + mtls_config=misconfigured on misconfig.
15. The REAL /api/readyz handler returns 200 + mtls_config=ok when correctly configured.

Task #136 — CORS preflight bypass:
16. OPTIONS to a protected endpoint is NOT rejected 403 (bypass is working / intentional).
17. OPTIONS to a GET-only data endpoint does NOT return the data body (bypass is safe).
"""
import hashlib
import hmac
import importlib
import logging
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient


_TEST_SECRET = "test-mtls-secret-abc123"


def _compute_expected_hmac(secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), b"mtls-active", hashlib.sha256
    ).hexdigest()


def _build_app(*, enforce_mtls: bool, secret: str | None):
    from config import Configurator

    if enforce_mtls:
        Configurator.set_runtime_env("ENFORCE_MTLS", "true")
    else:
        os.environ.pop("ENFORCE_MTLS", None)

    if secret is None:
        os.environ.pop("ORIGIN_SHARED_SECRET", None)
    else:
        Configurator.set_runtime_env("ORIGIN_SHARED_SECRET", secret)

    import middleware
    importlib.reload(middleware)

    app = FastAPI()
    app.add_middleware(middleware.MtlsClientCertMiddleware)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/livez")
    async def livez():
        return {"ok": True}

    @app.get("/api/readyz")
    async def readyz():
        return {"ok": True}

    @app.get("/api/ready")
    async def ready():
        return {"ok": True}

    @app.get("/api/admin/data")
    async def admin_data():
        return JSONResponse({"data": []})

    return app


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    os.environ.pop("ENFORCE_MTLS", None)
    os.environ.pop("ORIGIN_SHARED_SECRET", None)
    import middleware
    importlib.reload(middleware)


def test_no_op_when_secret_unset():
    """Middleware must be a no-op when ORIGIN_SHARED_SECRET is not configured."""
    app = _build_app(enforce_mtls=True, secret=None)
    client = TestClient(app)
    assert client.get("/api/admin/data").status_code == 200


def test_no_op_when_enforce_mtls_not_set():
    """Middleware must be a no-op when ENFORCE_MTLS is absent, even if secret is set."""
    app = _build_app(enforce_mtls=False, secret=_TEST_SECRET)
    client = TestClient(app)
    assert client.get("/api/admin/data").status_code == 200


def test_blocks_missing_header():
    """A request with no X-Cf-Mtls-Active header must be rejected with 403."""
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    resp = client.get("/api/admin/data")
    assert resp.status_code == 403
    assert "mTLS" in resp.json()["detail"] or "certificate" in resp.json()["detail"]


def test_blocks_wrong_fingerprint():
    """A request with a wrong HMAC value must be rejected with 403."""
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    resp = client.get(
        "/api/admin/data",
        headers={"X-Cf-Mtls-Active": "deadbeefdeadbeefdeadbeef"},
    )
    assert resp.status_code == 403


def test_allows_correct_fingerprint():
    """A request carrying the correct HMAC must pass through (200)."""
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    correct_hmac = _compute_expected_hmac(_TEST_SECRET)
    client = TestClient(app)
    resp = client.get(
        "/api/admin/data",
        headers={"X-Cf-Mtls-Active": correct_hmac},
    )
    assert resp.status_code == 200


def test_probe_path_livez_exempt():
    """/api/livez must be reachable without the HMAC header."""
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    assert client.get("/api/livez").status_code == 200


def test_probe_path_readyz_exempt():
    """/api/readyz must be reachable without the HMAC header."""
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    assert client.get("/api/readyz").status_code == 200


def test_probe_path_ready_exempt():
    """/api/ready must be reachable without the HMAC header."""
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    assert client.get("/api/ready").status_code == 200


def test_health_is_not_exempt():
    """/api/health is NOT a probe path and must be blocked without the HMAC header."""
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Task #135 — MTLS_MISCONFIGURED flag and /readyz 503 alerting
# ---------------------------------------------------------------------------

def _reload_middleware_flag(*, enforce_mtls: bool, secret: str | None) -> bool:
    """Reload the middleware module with the given env config and return MTLS_MISCONFIGURED."""
    from config import Configurator

    if enforce_mtls:
        Configurator.set_runtime_env("ENFORCE_MTLS", "true")
    else:
        os.environ.pop("ENFORCE_MTLS", None)

    if secret is None:
        os.environ.pop("ORIGIN_SHARED_SECRET", None)
    else:
        Configurator.set_runtime_env("ORIGIN_SHARED_SECRET", secret)

    import middleware
    importlib.reload(middleware)
    return middleware.MTLS_MISCONFIGURED


def test_misconfigured_flag_set_when_enforce_without_secret():
    """MTLS_MISCONFIGURED must be True when ENFORCE_MTLS=true but no secret is set."""
    flag = _reload_middleware_flag(enforce_mtls=True, secret=None)
    assert flag is True


def test_misconfigured_flag_clear_when_enforce_with_secret():
    """MTLS_MISCONFIGURED must be False when ENFORCE_MTLS=true and secret is present."""
    flag = _reload_middleware_flag(enforce_mtls=True, secret=_TEST_SECRET)
    assert flag is False


def test_misconfigured_flag_clear_when_enforce_not_set():
    """MTLS_MISCONFIGURED must be False when ENFORCE_MTLS is not set at all."""
    flag = _reload_middleware_flag(enforce_mtls=False, secret=None)
    assert flag is False


def _build_readyz_app(*, enforce_mtls: bool, secret: str | None):
    """Build a minimal app whose /api/readyz mirrors the mtls_config check from
    cms_sarvam_health.readyz so we can test the 503 path without the full
    health-snapshot-cache machinery."""
    from config import Configurator

    if enforce_mtls:
        Configurator.set_runtime_env("ENFORCE_MTLS", "true")
    else:
        os.environ.pop("ENFORCE_MTLS", None)

    if secret is None:
        os.environ.pop("ORIGIN_SHARED_SECRET", None)
    else:
        Configurator.set_runtime_env("ORIGIN_SHARED_SECRET", secret)

    import middleware
    importlib.reload(middleware)

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse as _JSONResponse
    import middleware as _mw

    test_app = FastAPI()

    @test_app.get("/api/readyz")
    async def readyz():
        mtls_ok = not _mw.MTLS_MISCONFIGURED
        mtls_check = (
            {"status": "ok"}
            if mtls_ok
            else {
                "status": "misconfigured",
                "detail": (
                    "ENFORCE_MTLS=true but ORIGIN_SHARED_SECRET is not set — "
                    "mTLS enforcement is INACTIVE and the origin is UNPROTECTED."
                ),
            }
        )
        critical_ok = mtls_ok
        return _JSONResponse(
            status_code=200 if critical_ok else 503,
            content={"status": "ready" if critical_ok else "degraded", "checks": {"mtls_config": mtls_check}},
            headers={"Cache-Control": "no-store"},
        )

    return test_app


def test_readyz_returns_503_when_mtls_misconfigured():
    """/api/readyz must return 503 when ENFORCE_MTLS=true but ORIGIN_SHARED_SECRET is absent."""
    app = _build_readyz_app(enforce_mtls=True, secret=None)
    client = TestClient(app)
    resp = client.get("/api/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["mtls_config"]["status"] == "misconfigured"
    assert "ORIGIN_SHARED_SECRET" in body["checks"]["mtls_config"]["detail"]


def test_readyz_returns_200_when_mtls_correctly_configured():
    """/api/readyz must return 200 (for the mtls check) when both env vars are set."""
    app = _build_readyz_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    resp = client.get("/api/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["mtls_config"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Task #135 — additional coverage: log text + real readyz route integration
# ---------------------------------------------------------------------------

def test_startup_error_log_contains_expected_keywords(caplog):
    """MtlsClientCertMiddleware.__init__ must log at ERROR with key terms when
    ENFORCE_MTLS=true but ORIGIN_SHARED_SECRET is absent, so log-based alerting
    rules that look for 'MISCONFIGURED' or 'UNPROTECTED' fire correctly.

    Note: Starlette builds the middleware stack lazily — __init__ is called on
    the first request, not at TestClient construction time, so we send one
    dummy request inside the caplog capture block to trigger instantiation.
    """
    from config import Configurator

    Configurator.set_runtime_env("ENFORCE_MTLS", "true")
    os.environ.pop("ORIGIN_SHARED_SECRET", None)

    import middleware
    importlib.reload(middleware)

    from fastapi import FastAPI as _FA

    test_app = _FA()
    test_app.add_middleware(middleware.MtlsClientCertMiddleware)

    @test_app.get("/probe")
    async def _probe():
        return {}

    with caplog.at_level(logging.ERROR, logger="middleware"):
        client = TestClient(test_app, raise_server_exceptions=False)
        client.get("/probe")

    error_messages = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("MISCONFIGURED" in m for m in error_messages), (
        f"Expected ERROR log containing 'MISCONFIGURED', got: {error_messages}"
    )
    assert any("UNPROTECTED" in m for m in error_messages), (
        f"Expected ERROR log containing 'UNPROTECTED', got: {error_messages}"
    )
    assert any("ORIGIN_SHARED_SECRET" in m for m in error_messages), (
        f"Expected ERROR log mentioning 'ORIGIN_SHARED_SECRET', got: {error_messages}"
    )


def _build_real_readyz_app(*, enforce_mtls: bool, secret: str | None):
    """Build a FastAPI app that registers the REAL cms_sarvam_health readyz handler,
    with health_snapshot_cache and _vertex_block_for_health patched out so the test
    does not require Mongo / Postgres / Vertex to be available."""
    from config import Configurator

    if enforce_mtls:
        Configurator.set_runtime_env("ENFORCE_MTLS", "true")
    else:
        os.environ.pop("ENFORCE_MTLS", None)

    if secret is None:
        os.environ.pop("ORIGIN_SHARED_SECRET", None)
    else:
        Configurator.set_runtime_env("ORIGIN_SHARED_SECRET", secret)

    import middleware
    importlib.reload(middleware)

    from fastapi import FastAPI as _FA
    import routes.cms_sarvam_health as _health_route

    test_app = _FA()
    test_app.include_router(_health_route.router, prefix="/api")
    return test_app


def test_real_readyz_returns_503_when_mtls_misconfigured():
    """The REAL readyz handler must return 503 with mtls_config=misconfigured
    when ENFORCE_MTLS=true but ORIGIN_SHARED_SECRET is absent.
    health_snapshot_cache and vertex are patched to isolate the mTLS path."""
    app = _build_real_readyz_app(enforce_mtls=True, secret=None)
    client = TestClient(app, raise_server_exceptions=False)

    _ok_snapshot = {
        "mongodb": {"status": "ok"},
        "postgresql": {"status": "ok"},
        "cloudflare_cache": {"status": "ok"},
        "razorpay": {"status": "ok"},
    }
    _vertex_block = ({"status": "ok"}, True)

    with (
        patch(
            "routes.cms_sarvam_health.health_snapshot_cache.get_all",
            new=AsyncMock(return_value=_ok_snapshot),
        ),
        patch(
            "routes.cms_sarvam_health._vertex_block_for_health",
            return_value=_vertex_block,
        ),
    ):
        resp = client.get("/api/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["mtls_config"]["status"] == "misconfigured"
    assert "ORIGIN_SHARED_SECRET" in body["checks"]["mtls_config"]["detail"]


def test_real_readyz_returns_200_when_mtls_correctly_configured():
    """The REAL readyz handler must return 200 with mtls_config=ok when
    ENFORCE_MTLS=true and ORIGIN_SHARED_SECRET is present."""
    app = _build_real_readyz_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app, raise_server_exceptions=False)

    _ok_snapshot = {
        "mongodb": {"status": "ok"},
        "postgresql": {"status": "ok"},
        "cloudflare_cache": {"status": "ok"},
        "razorpay": {"status": "ok"},
    }
    _vertex_block = ({"status": "ok"}, True)

    with (
        patch(
            "routes.cms_sarvam_health.health_snapshot_cache.get_all",
            new=AsyncMock(return_value=_ok_snapshot),
        ),
        patch(
            "routes.cms_sarvam_health._vertex_block_for_health",
            return_value=_vertex_block,
        ),
    ):
        resp = client.get("/api/readyz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["mtls_config"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Task #136 — CORS preflight bypass: intentional and safe
# ---------------------------------------------------------------------------

def test_options_bypasses_hmac_check_intentionally():
    """OPTIONS to a protected endpoint must NOT be rejected with 403.

    Browsers send an OPTIONS preflight before every cross-origin request.
    The Cloudflare edge worker does not attach X-Cf-Mtls-Active on preflights,
    so the middleware must let OPTIONS through unconditionally.  This test
    confirms that the bypass is present and working as intended.
    """
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    # Send OPTIONS with no HMAC header — must NOT get 403.
    resp = client.options("/api/admin/data")
    assert resp.status_code != 403, (
        "OPTIONS preflight must not be blocked by the mTLS HMAC check "
        f"(got {resp.status_code})"
    )


def test_options_to_data_endpoint_does_not_return_data():
    """OPTIONS to a GET-only data endpoint must not return the data payload.

    Confirms the CORS bypass cannot be abused to exfiltrate data.  A GET-only
    route has no OPTIONS handler; Starlette returns 405 Method Not Allowed
    (or a CORS-headers-only 200) — never the application data body.
    """
    app = _build_app(enforce_mtls=True, secret=_TEST_SECRET)
    client = TestClient(app)
    resp = client.options("/api/admin/data")
    # The response must not contain the data payload {"data": []}.
    # 405 is the expected Starlette default for a method-not-allowed route.
    assert resp.status_code != 200 or "data" not in resp.json(), (
        "OPTIONS to a GET-only endpoint must not return the route's data body; "
        f"got status={resp.status_code} body={resp.text!r}"
    )
