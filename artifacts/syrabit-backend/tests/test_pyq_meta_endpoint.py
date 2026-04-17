"""Tests for the public PYQ metadata endpoint (Task #338).

Locks the response shape and 404 / 503 behavior of
`GET /api/pyq/{slug}/meta` so the SPA can reliably feed
`pyqDatasetSchema` with real worker-backfilled fields.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _make_app(fake_db) -> TestClient:
    """Build a tiny FastAPI app that mounts the PYQ router with a patched db."""
    import deps as deps_mod
    from routes import pyq as pyq_mod

    deps_mod.db = fake_db
    pyq_mod.db = fake_db

    app = FastAPI()
    app.include_router(pyq_mod.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 200 — happy path
# ---------------------------------------------------------------------------

def test_meta_returns_canonical_shape_for_known_slug():
    fake_db = MagicMock()
    fake_db.pyq_html_pages.find_one = AsyncMock(return_value={
        "slug": "ahsec-2024-physics",
        "seo_title": "AHSEC Physics Major 2024",
        "seo_description": "AHSEC Physics 2024 paper.",
        "subject_name": "Physics",
        "board_name": "AHSEC",
        "class_name": "Class 12",
        "stream_name": "Science",
        "exam_year": 2024,
        "paper_type": "major",
        "question_count": 32,
        "created_at": "2025-03-12T08:00:00Z",
        "updated_at": "2026-01-04T09:30:00Z",
    })
    client = _make_app(fake_db)

    resp = client.get("/api/pyq/ahsec-2024-physics/meta")
    assert resp.status_code == 200
    body = resp.json()

    # Lock the canonical response shape — the SPA's pyqDatasetSchema
    # consumer reads these exact keys.
    expected_keys = {
        "slug", "title", "description", "subject", "board", "class_name",
        "stream", "year", "paper_type", "educational_level",
        "total_questions", "license", "author", "language",
        "published_at", "updated_at",
    }
    assert expected_keys.issubset(body.keys()), (
        f"missing keys: {expected_keys - body.keys()}"
    )

    # Spot-check field-level mapping to catch silent regressions.
    assert body["slug"] == "ahsec-2024-physics"
    assert body["subject"] == "Physics"
    assert body["board"] == "AHSEC"
    assert body["year"] == 2024
    assert body["total_questions"] == 32
    assert body["educational_level"] == "Class 12"
    assert body["author"] == "AHSEC"
    assert body["language"] == "en-IN"
    assert body["license"].startswith("https://")
    assert body["published_at"] == "2025-03-12T08:00:00Z"
    assert body["updated_at"] == "2026-01-04T09:30:00Z"


def test_meta_falls_back_to_higher_secondary_when_class_missing():
    fake_db = MagicMock()
    fake_db.pyq_html_pages.find_one = AsyncMock(return_value={
        "slug": "stray-paper",
        "seo_title": "Stray PYQ",
        "seo_description": "",
        "subject_name": "",
        "board_name": "",
        "class_name": "",
        "stream_name": "",
        "exam_year": 0,
        "paper_type": "",
        "question_count": 0,
    })
    client = _make_app(fake_db)
    resp = client.get("/api/pyq/stray-paper/meta")
    assert resp.status_code == 200
    body = resp.json()
    # Without board / class, the helper should still return a sensible default
    # so pyqDatasetSchema can emit `educationalLevel`.
    assert body["educational_level"] == "Higher Secondary"
    # Author falls back to the editorial team when the board name is empty.
    assert body["author"] == "Syrabit.ai Editorial Team"


# ---------------------------------------------------------------------------
# 404 — unknown slug
# ---------------------------------------------------------------------------

def test_meta_returns_404_when_slug_unknown():
    fake_db = MagicMock()
    fake_db.pyq_html_pages.find_one = AsyncMock(return_value=None)
    client = _make_app(fake_db)
    resp = client.get("/api/pyq/does-not-exist/meta")
    assert resp.status_code == 404
    assert "PYQ page not found" in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# 503 — DB outage
# ---------------------------------------------------------------------------

def test_meta_returns_503_when_db_unavailable():
    client = _make_app(None)
    resp = client.get("/api/pyq/anything/meta")
    assert resp.status_code == 503
    assert "Database unavailable" in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# Route ordering — `/meta` mustn't be shadowed by `/{slug}` HTML route.
# ---------------------------------------------------------------------------

def test_meta_route_is_not_shadowed_by_slug_html_route():
    from routes import pyq as pyq_mod
    paths = [r.path for r in pyq_mod.router.routes]
    assert "/api/pyq/{slug}/meta" in paths
    assert "/api/pyq/{slug}" in paths
