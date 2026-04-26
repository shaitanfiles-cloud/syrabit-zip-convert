"""Task #944 — defense-in-depth check that the OriginSharedSecretMiddleware
gates ``/api/logs/ingest`` when ``ORIGIN_SHARED_SECRET`` is configured.

The ingest token already authenticates the producer, but the worker also
attaches ``X-Origin-Auth`` and the production deployment relies on that
middleware to keep the Cloud Run / Railway origin URL invisible to the
public internet. This test wires the *real* middleware into a tiny
Starlette app + the *real* ingest route and asserts that:

    1. With ORIGIN_SHARED_SECRET set + missing X-Origin-Auth header,
       the request is rejected at the middleware boundary (status >= 400)
       BEFORE the ingest token check ever runs.
    2. With ORIGIN_SHARED_SECRET set + matching X-Origin-Auth header,
       the request reaches the ingest handler (which then enforces its
       own ingest-token check, returning 401 / 503 / 202 as appropriate).
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware import OriginSharedSecretMiddleware


@pytest.fixture
def app_with_middleware(monkeypatch):
    """Build a fresh FastAPI app with the real OriginSharedSecretMiddleware
    in front of a stub ingest handler. We don't use the real ingest route
    because that would also require Mongo + the ingest-token plumbing —
    here we only want to assert the middleware boundary behaviour."""
    monkeypatch.setenv("ORIGIN_SHARED_SECRET", "test-shared-secret-XYZ")
    monkeypatch.setenv("ORIGIN_SHARED_SECRET_HEADER", "X-Origin-Auth")
    # Re-import the module so the env-derived module-level constants pick
    # up the test values (the middleware module reads them at import time).
    import importlib
    import middleware as mw_mod
    importlib.reload(mw_mod)

    app = FastAPI()
    app.add_middleware(mw_mod.OriginSharedSecretMiddleware)

    @app.post("/api/logs/ingest")
    async def fake_ingest():
        # If we reach here the middleware let us through.
        return {"reached_handler": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app


def test_ingest_rejected_without_origin_auth_header(app_with_middleware):
    client = TestClient(app_with_middleware)
    r = client.post("/api/logs/ingest", json={"records": []})
    assert r.status_code >= 400, r.text
    # Critical: the inner handler's "reached_handler": True payload must
    # NOT appear — the middleware short-circuited the request.
    assert "reached_handler" not in r.text


def test_ingest_rejected_with_wrong_origin_auth_header(app_with_middleware):
    client = TestClient(app_with_middleware)
    r = client.post(
        "/api/logs/ingest",
        json={"records": []},
        headers={"X-Origin-Auth": "this-is-not-the-secret"},
    )
    assert r.status_code >= 400, r.text
    assert "reached_handler" not in r.text


def test_ingest_passes_middleware_with_correct_origin_auth_header(
    app_with_middleware,
):
    client = TestClient(app_with_middleware)
    r = client.post(
        "/api/logs/ingest",
        json={"records": []},
        headers={"X-Origin-Auth": "test-shared-secret-XYZ"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"reached_handler": True}


def test_health_endpoint_open_even_without_origin_auth(app_with_middleware):
    """``/api/health`` is on the OPEN_PATHS allowlist so probes don't
    need the shared secret. This test guards against accidentally
    locking the health endpoint behind the middleware."""
    client = TestClient(app_with_middleware)
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_middleware_no_op_when_secret_unset(monkeypatch):
    """When ORIGIN_SHARED_SECRET is empty the middleware short-circuits
    and lets every request through (legacy / dev mode)."""
    monkeypatch.setenv("ORIGIN_SHARED_SECRET", "")
    import importlib
    import middleware as mw_mod
    importlib.reload(mw_mod)

    app = FastAPI()
    app.add_middleware(mw_mod.OriginSharedSecretMiddleware)

    @app.post("/api/logs/ingest")
    async def fake_ingest():
        return {"reached_handler": True}

    client = TestClient(app)
    r = client.post("/api/logs/ingest", json={"records": []})
    assert r.status_code == 200, r.text
    assert r.json() == {"reached_handler": True}
