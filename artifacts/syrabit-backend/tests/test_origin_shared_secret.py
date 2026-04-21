"""Task #606 — OriginSharedSecretMiddleware behaviour tests.

Verifies the three states of the middleware:

1. ``ORIGIN_SHARED_SECRET`` unset → middleware is a no-op (Railway today).
2. ``ORIGIN_SHARED_SECRET`` set + correct ``X-Origin-Auth`` header on the
   request → request flows through.
3. ``ORIGIN_SHARED_SECRET`` set + missing/wrong header → 403, except for
   the open paths the Cloud Run platform probes use (``/api/health``,
   ``/health``, ``/docs``, ``/openapi.json``, ``/robots.txt``).
"""
import importlib
import os

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient


def _build_app(secret: str | None, header: str | None = None):
    if secret is None:
        os.environ.pop("ORIGIN_SHARED_SECRET", None)
    else:
        os.environ["ORIGIN_SHARED_SECRET"] = secret
    if header is None:
        os.environ.pop("ORIGIN_SHARED_SECRET_HEADER", None)
    else:
        os.environ["ORIGIN_SHARED_SECRET_HEADER"] = header

    import middleware
    importlib.reload(middleware)

    app = FastAPI()
    app.add_middleware(middleware.OriginSharedSecretMiddleware)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/admin/things")
    async def admin_things():
        return JSONResponse({"things": []})

    return app


def test_disabled_when_secret_unset():
    app = _build_app(secret=None)
    client = TestClient(app)
    assert client.get("/api/admin/things").status_code == 200


def test_blocks_when_header_missing():
    app = _build_app(secret="s3cret")
    client = TestClient(app)
    resp = client.get("/api/admin/things")
    assert resp.status_code == 403
    assert "edge worker" in resp.json()["detail"]


def test_blocks_when_header_wrong():
    app = _build_app(secret="s3cret")
    client = TestClient(app)
    resp = client.get("/api/admin/things", headers={"X-Origin-Auth": "wrong"})
    assert resp.status_code == 403


def test_allows_with_correct_header():
    app = _build_app(secret="s3cret")
    client = TestClient(app)
    resp = client.get("/api/admin/things", headers={"X-Origin-Auth": "s3cret"})
    assert resp.status_code == 200


def test_health_open_for_platform_probes():
    app = _build_app(secret="s3cret")

    @app.get("/openapi.json")
    async def fake_openapi():
        return {"openapi": "3.0.0"}

    client = TestClient(app)
    # Cloud Run startup/liveness probes do not (and cannot) carry the secret.
    assert client.get("/api/health").status_code == 200
    # /openapi.json must NOT be open — schema-leak hardening for the
    # publicly-resolvable *.run.app URL.
    assert client.get("/openapi.json").status_code == 403


def test_options_passes_for_cors_preflight():
    app = _build_app(secret="s3cret")
    client = TestClient(app)
    # OPTIONS without the secret must succeed so CORS preflight from the
    # browser (which does not carry our shared header) still works.
    resp = client.options("/api/admin/things", headers={
        "Origin": "https://syrabit.ai",
        "Access-Control-Request-Method": "GET",
    })
    assert resp.status_code in (200, 405)


def test_custom_header_name_honoured():
    app = _build_app(secret="s3cret", header="X-Edge-Token")
    client = TestClient(app)
    assert client.get("/api/admin/things").status_code == 403
    assert client.get(
        "/api/admin/things", headers={"X-Edge-Token": "s3cret"}
    ).status_code == 200


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    os.environ.pop("ORIGIN_SHARED_SECRET", None)
    os.environ.pop("ORIGIN_SHARED_SECRET_HEADER", None)
    import middleware
    importlib.reload(middleware)
