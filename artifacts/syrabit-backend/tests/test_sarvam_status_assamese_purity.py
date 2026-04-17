"""Task #421 — /sarvam/status must expose live assamese_purity config."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_runtime_override():
    from lang_sanitizer import clear_runtime_override
    clear_runtime_override()
    yield
    clear_runtime_override()


@pytest.fixture
def app_client():
    from routes.cms_sarvam_health import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_sarvam_status_exposes_assamese_purity_block(app_client):
    from lang_sanitizer import _VALID_BEHAVIOURS

    r = app_client.get("/sarvam/status")
    assert r.status_code == 200
    body = r.json()

    assert "assamese_purity" in body
    ap = body["assamese_purity"]
    assert "behaviour" in ap
    assert "threshold" in ap
    assert "valid_behaviours" in ap
    assert ap["behaviour"] in ap["valid_behaviours"]
    assert ap["behaviour"] in _VALID_BEHAVIOURS
    assert isinstance(ap["threshold"], (int, float))
