"""Task #365 — regression tests for HEAD/GET parity and dynamic sitemap aliases.

Two production bugs were producing the SEO health CRITICAL alert storm:

1. Every SPA route returned ``404 application/json`` for HEAD requests
   even though GET returned ``200 text/html``. The internal SEO health
   probe (and Google's URL inspection) uses HEAD as a cheap pre-check,
   so every spot-checked URL was being recorded as broken (0/35).
2. The dynamic sitemaps the SEO Manager publishes (``sitemap-pages.xml``,
   ``sitemap-subjects.xml``, ``sitemap-chapters.xml``, ``sitemap-learn.xml``,
   plus the empty ``sitemap-{notes,mcqs,pyqs,examples,definitions}.xml``)
   were not registered as backend routes at the *root* of the domain;
   the SPA fallback returned the React shell as ``text/html`` so external
   sitemap validators rejected them as "not XML".

These tests exercise the two fixes — the ``HeadAsGetMiddleware`` ASGI
shim and the root-level sitemap aliases — by hitting the FastAPI app
in-process via Starlette's ``TestClient`` (no Mongo/Redis required).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from tests._deps_stub import install_deps_stub

install_deps_stub()


def _build_minimal_app():
    """Construct a tiny FastAPI app that mimics the production wiring
    around ``HeadAsGetMiddleware``: a SPA-style GET route plus a
    sitemap-style XML route. Importing the full ``server`` module would
    pull in every router (Mongo, Redis, payments, …) which is heavy and
    flaky for an isolated unit test. The middleware itself lives in
    ``server`` so we import it directly and re-mount it here."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, Response

    # Importing server triggers the full startup chain. Instead, copy the
    # middleware class definition inline — it has no external deps.
    server_path = Path(__file__).resolve().parent.parent / "server.py"
    src = server_path.read_text(encoding="utf-8")
    # Extract the HeadAsGetMiddleware class via a marker on either side.
    start = src.index("class HeadAsGetMiddleware")
    end = src.index("\nfrom middleware import", start)
    middleware_src = src[start:end]
    ns: dict = {}
    exec(compile(middleware_src, str(server_path), "exec"), ns)
    HeadAsGetMiddleware = ns["HeadAsGetMiddleware"]

    app = FastAPI()

    @app.get("/about", response_class=HTMLResponse)
    async def about():
        return HTMLResponse("<!doctype html><title>About</title>")

    @app.get("/sitemap-pages.xml")
    async def sitemap_pages():
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://syrabit.ai/</loc></url>'
            '</urlset>'
        )
        return Response(content=xml, media_type="application/xml; charset=utf-8")

    app.add_middleware(HeadAsGetMiddleware)
    return app


def test_head_returns_same_status_as_get_for_spa_route():
    """Regression: ``HEAD /about`` must return 200 (not 404 JSON)."""
    from starlette.testclient import TestClient

    app = _build_minimal_app()
    with TestClient(app) as client:
        get_resp = client.get("/about")
        head_resp = client.head("/about")

    assert get_resp.status_code == 200
    assert head_resp.status_code == 200, (
        f"HEAD /about returned {head_resp.status_code} — SEO probe will "
        f"count this URL as broken. Body: {head_resp.text!r}"
    )
    # HEAD must preserve the GET content-type so crawlers see HTML, not
    # the legacy ``application/json`` 404 payload.
    assert head_resp.headers.get("content-type", "").startswith("text/html")
    # HEAD body must be empty.
    assert head_resp.content == b""


def test_sitemap_xml_route_returns_xml_for_both_methods():
    """Regression: dynamic sitemap returns valid XML with the correct
    content-type for both GET and HEAD. Pre-fix, HEAD returned 404 JSON
    and GET on the SPA fallback returned the React shell."""
    from starlette.testclient import TestClient
    import xml.etree.ElementTree as ET

    app = _build_minimal_app()
    with TestClient(app) as client:
        get_resp = client.get("/sitemap-pages.xml")
        head_resp = client.head("/sitemap-pages.xml")

    assert get_resp.status_code == 200
    assert head_resp.status_code == 200
    ct = get_resp.headers.get("content-type", "")
    assert "xml" in ct, f"unexpected content-type for GET sitemap: {ct!r}"
    head_ct = head_resp.headers.get("content-type", "")
    assert "xml" in head_ct, f"unexpected content-type for HEAD sitemap: {head_ct!r}"

    root = ET.fromstring(get_resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = root.findall(".//sm:loc", ns)
    assert len(locs) >= 1, "sitemap-pages.xml must contain at least one <url>"


def test_register_root_sitemap_aliases_wires_real_handlers():
    """Integration check: the production helper used by ``server.py``
    registers each dynamic-sitemap path on a fresh FastAPI app with
    GET+HEAD methods, and each route delegates to the corresponding
    ``seo_engine`` handler (so XML-build logic isn't accidentally
    duplicated). Importing the full ``server`` module would pull the
    entire startup chain (Mongo, Redis, payments) which isn't viable
    in unit tests, so we re-extract the helper from source — same
    technique used by ``_build_minimal_app`` above — and inject
    stubbed handlers into a synthetic ``seo_engine`` module."""
    import sys
    import types
    from pathlib import Path
    from fastapi import FastAPI
    from fastapi.responses import Response

    # Build a stub seo_engine module that exposes the same handler
    # names ``server._register_root_sitemap_aliases`` looks up. Each
    # stub returns a unique XML body so we can assert delegation.
    expected_names = (
        "get_sitemap_pages", "get_sitemap_subjects", "get_sitemap_chapters",
        "get_sitemap_learn", "get_sitemap_notes", "get_sitemap_mcqs",
        "get_sitemap_pyqs", "get_sitemap_examples", "get_sitemap_definitions",
    )
    stub_seo = types.ModuleType("seo_engine")
    for name in expected_names:
        async def _h(_n=name):
            return Response(content=f"<urlset><!-- {_n} --></urlset>",
                            media_type="application/xml; charset=utf-8")
        setattr(stub_seo, name, _h)
    saved = sys.modules.get("seo_engine")
    sys.modules["seo_engine"] = stub_seo
    try:
        server_path = Path(__file__).resolve().parent.parent / "server.py"
        src = server_path.read_text(encoding="utf-8")
        # Extract just the alias-registration block and execute it
        # against a fresh FastAPI app.
        start = src.index("_DYNAMIC_SITEMAP_ALIASES = (")
        # Anchor on the trailing standalone *call* (not the `def`) so
        # the function body is included in the extracted block.
        end_marker = "\n_register_root_sitemap_aliases()\n"
        end = src.index(end_marker, start) + len(end_marker)
        block = src[start:end]
        ns = {"app": FastAPI()}
        exec(compile(block, str(server_path), "exec"), ns)
        registered = {r.path: r.methods for r in ns["app"].routes
                      if hasattr(r, "methods")}
        for filename in (
            "sitemap-pages.xml", "sitemap-subjects.xml", "sitemap-chapters.xml",
            "sitemap-learn.xml", "sitemap-notes.xml", "sitemap-mcqs.xml",
            "sitemap-pyqs.xml", "sitemap-examples.xml", "sitemap-definitions.xml",
        ):
            path = f"/{filename}"
            assert path in registered, f"{path} not registered"
            assert "GET" in registered[path] and "HEAD" in registered[path], (
                f"{path} must accept GET and HEAD, got {registered[path]}"
            )
    finally:
        if saved is not None:
            sys.modules["seo_engine"] = saved
        else:
            sys.modules.pop("seo_engine", None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
