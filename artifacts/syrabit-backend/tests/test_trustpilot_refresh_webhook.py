"""Task #752 — backend coverage for the Trustpilot refresh webhook.

Covers:
  * missing ``TRUSTPILOT_REFRESH_SECRET`` env  → 503 (fail closed);
  * wrong / missing ``X-Trustpilot-Refresh-Secret`` header → 401;
  * malformed body (missing fields, non-numeric, non-positive) → 422;
  * happy path updates ``_tp_aggregate_cache`` so the next
    ``GET /api/config/trustpilot/aggregate`` returns the new values
    with ``cached: True`` and ``ageSeconds: 0``;
  * happy path clears the >24h staleness flags surfaced by
    ``get_trustpilot_aggregate_health()`` (``stale``, ``firstErrorTs``,
    ``lastErrorTs``, ``lastError``).
"""
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import config as config_module
from routes.config import router


REFRESH_PATH = "/api/config/trustpilot/aggregate/refresh"
GET_PATH = "/api/config/trustpilot/aggregate"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_tp_cache():
    """Snapshot/restore the in-process aggregate cache so tests don't
    bleed into each other (or into other test modules that read it)."""
    snapshot = dict(config_module._tp_aggregate_cache)
    yield
    config_module._tp_aggregate_cache.clear()
    config_module._tp_aggregate_cache.update(snapshot)


# ─── secret env not configured (503) ────────────────────────────────────────

def test_refresh_returns_503_when_secret_env_missing(client, monkeypatch):
    monkeypatch.delenv("TRUSTPILOT_REFRESH_SECRET", raising=False)
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "anything"},
        json={"ratingValue": 4.2, "ratingCount": 10},
    )
    assert res.status_code == 503
    assert res.json()["detail"] == "trustpilot_refresh_secret_not_configured"


def test_refresh_returns_503_when_secret_env_blank(client, monkeypatch):
    """An empty/whitespace secret env must fail closed exactly like a
    missing one — otherwise an accidentally-blanked deploy would accept
    anonymous writes."""
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "   ")
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "   "},
        json={"ratingValue": 4.2, "ratingCount": 10},
    )
    assert res.status_code == 503


# ─── wrong / missing secret header (401) ────────────────────────────────────

def test_refresh_returns_401_when_header_missing(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        REFRESH_PATH,
        json={"ratingValue": 4.2, "ratingCount": 10},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid_refresh_secret"


def test_refresh_returns_401_on_secret_mismatch(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "wrong"},
        json={"ratingValue": 4.2, "ratingCount": 10},
    )
    assert res.status_code == 401


# ─── invalid body (422) ─────────────────────────────────────────────────────

def test_refresh_returns_422_when_body_missing(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
    )
    # FastAPI's own body validation rejects no-body before our handler
    # runs, so this is a 422 from the framework.
    assert res.status_code == 422


def test_refresh_returns_422_when_required_fields_absent(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={"ratingCount": 10},  # ratingValue missing → float(None) raises
    )
    assert res.status_code == 422
    assert "ratingValue" in res.json()["detail"]


def test_refresh_returns_422_when_values_non_numeric(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={"ratingValue": "not-a-number", "ratingCount": 10},
    )
    assert res.status_code == 422


def test_refresh_returns_422_when_values_non_positive(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={"ratingValue": 0, "ratingCount": 0},
    )
    assert res.status_code == 422
    assert "positive" in res.json()["detail"]


# ─── happy path ─────────────────────────────────────────────────────────────

def test_refresh_happy_path_updates_cache_and_clears_staleness(
    client, monkeypatch
):
    """A valid POST should:
      * return 200 with the normalised payload + ``ageSeconds: 0``;
      * mutate the in-process cache so the next GET hits the cached
        branch (``cached: True``, ``ageSeconds: 0``);
      * clear the failure bookkeeping that drives the >24h staleness
        alert (``stale`` False, ``firstErrorTs``/``lastErrorTs``/
        ``lastError`` all None).
    """
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")

    # Pre-seed a broken-feed state so we can prove the webhook clears it.
    long_ago = time.time() - (48 * 3600)
    config_module._tp_aggregate_cache.update({
        "payload": None,
        "ts": 0.0,
        "fail_ts": long_ago,
        "first_fail_ts": long_ago,
        "last_error": "http_502",
    })
    pre_health = config_module.get_trustpilot_aggregate_health()
    assert pre_health["stale"] is True
    assert pre_health["firstErrorTs"] is not None
    assert pre_health["lastError"] == "http_502"

    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={
            "ratingValue": 4.27,
            "ratingCount": 42,
            "bestRating": 5,
            "worstRating": 1,
            "source": "github_actions_cron",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["ratingValue"] == 4.27
    assert body["ratingCount"] == 42
    assert body["bestRating"] == 5
    assert body["worstRating"] == 1
    assert body["ageSeconds"] == 0
    assert body["source"] == "github_actions_cron"

    # Cache mutation: the next GET must serve the new values from cache.
    get_res = client.get(GET_PATH)
    assert get_res.status_code == 200
    get_body = get_res.json()
    assert get_body["ratingValue"] == 4.27
    assert get_body["ratingCount"] == 42
    assert get_body["cached"] is True
    assert get_body["ageSeconds"] == 0

    # Staleness flags should have cleared.
    post_health = config_module.get_trustpilot_aggregate_health()
    assert post_health["stale"] is False
    assert post_health["hasPayload"] is True
    assert post_health["firstErrorTs"] is None
    assert post_health["lastErrorTs"] is None
    assert post_health["lastError"] is None
    assert post_health["lastSuccessAgeSeconds"] == 0


def test_refresh_defaults_best_worst_when_omitted(client, monkeypatch):
    """``bestRating`` / ``worstRating`` are optional and default to 5/1."""
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        REFRESH_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={"ratingValue": 3.8, "ratingCount": 7},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["bestRating"] == 5
    assert body["worstRating"] == 1
    # Default source label when caller omits it.
    assert body["source"] == "external_webhook"
