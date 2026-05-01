"""Task #123 — MtlsClientCertMiddleware behaviour tests.

Verifies all guard cases for the mTLS HMAC enforcement middleware:

1. No-op when ORIGIN_SHARED_SECRET is unset (backward-compat).
2. No-op when ENFORCE_MTLS is not set, even if ORIGIN_SHARED_SECRET is present.
3. Rejects (403) when the X-Cf-Mtls-Active header is missing.
4. Rejects (403) when the X-Cf-Mtls-Active header carries a wrong HMAC.
5. Passes (200) when the header carries the correct HMAC.
6. Probe paths /api/livez, /api/readyz, /api/ready are exempt without the header.
7. /api/health is NOT exempt — blocked without the correct HMAC.
"""
import hashlib
import hmac
import importlib
import os

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
