"""Task #422 — admin runtime override + test-fire route tests."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture(autouse=True)
def _reset_runtime_override():
    from lang_sanitizer import clear_runtime_override
    clear_runtime_override()
    yield
    clear_runtime_override()


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True}


@pytest.fixture
def app_client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.cms_sarvam_health import router

    app = FastAPI()
    app.include_router(router)
    from auth_deps import get_admin_user
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


def _mock_db():
    """Builds a MagicMock(api_config=AsyncMock-collection) usable by the
    routes' `from deps import db as _db` import paths."""
    api_cfg = MagicMock()
    api_cfg.find_one = AsyncMock(return_value=None)
    api_cfg.update_one = AsyncMock(return_value=None)
    db = MagicMock()
    db.api_config = api_cfg
    return db, api_cfg


def _patch_db(db):
    """Routes do `from deps import db as _db` lazily — patch the source."""
    return patch("deps.db", db, create=True)


class TestGetAssamesePurity:
    def test_get_returns_config_and_test_sample(self, app_client):
        db, _ = _mock_db()
        with _patch_db(db):
            r = app_client.get("/admin/assamese-purity")
        assert r.status_code == 200
        body = r.json()
        assert "config" in body
        cfg = body["config"]
        assert cfg["behaviour"] in cfg["valid_behaviours"]
        assert "behaviour_source" in cfg and "threshold_source" in cfg
        # Default leaky sample is non-empty so admins always have
        # something to fire the test against.
        assert body["test_sample"] and "অসম" in body["test_sample"] or body["test_sample"]


class TestPatchAssamesePurity:
    def test_patch_validates_behaviour(self, app_client):
        db, _ = _mock_db()
        with _patch_db(db):
            r = app_client.patch(
                "/admin/assamese-purity",
                json={"behaviour": "junk-mode"},
            )
        assert r.status_code == 400
        assert "behaviour" in r.json()["detail"]

    def test_patch_validates_threshold_range(self, app_client):
        db, _ = _mock_db()
        with _patch_db(db):
            r = app_client.patch(
                "/admin/assamese-purity",
                json={"threshold": 1.5},
            )
        assert r.status_code == 400

    def test_patch_requires_at_least_one_field(self, app_client):
        db, _ = _mock_db()
        with _patch_db(db):
            r = app_client.patch("/admin/assamese-purity", json={})
        assert r.status_code == 400

    def test_patch_persists_and_applies_override(self, app_client):
        from lang_sanitizer import get_behaviour, get_threshold
        db, api_cfg = _mock_db()
        with _patch_db(db):
            r = app_client.patch(
                "/admin/assamese-purity",
                json={"behaviour": "off", "threshold": 0.07},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        # In-memory layer reflects the override.
        assert get_behaviour() == "off"
        assert get_threshold() == pytest.approx(0.07)
        # Persisted doc carries the audit fields.
        assert body["persisted"]["behaviour"] == "off"
        assert body["persisted"]["threshold"] == pytest.approx(0.07)
        assert body["persisted"]["updated_by"] == "ops@syrabit.ai"
        assert "updated_at" in body["persisted"]
        # Mongo write happened with $set on the override key.
        api_cfg.update_one.assert_awaited()
        call_args = api_cfg.update_one.call_args
        assert "$set" in call_args.args[1]
        assert "assamese_purity_override" in call_args.args[1]["$set"]
        # Source columns are now "override".
        assert body["config"]["behaviour_source"] == "override"
        assert body["config"]["threshold_source"] == "override"

    def test_patch_partial_update_only_changes_one_field(self, app_client):
        from lang_sanitizer import get_behaviour, get_threshold
        # Seed an override first via the in-memory layer directly.
        from lang_sanitizer import apply_runtime_override
        apply_runtime_override(behaviour="strip", threshold=0.10, updated_by="seed")
        db, _ = _mock_db()
        with _patch_db(db):
            r = app_client.patch(
                "/admin/assamese-purity",
                json={"behaviour": "translate"},
            )
        assert r.status_code == 200
        # Threshold preserved from the existing override.
        assert get_behaviour() == "translate"
        assert get_threshold() == pytest.approx(0.10)


class TestDeleteAssamesePurity:
    def test_delete_clears_override_and_unsets_doc(self, app_client):
        from lang_sanitizer import (
            apply_runtime_override, get_runtime_override,
        )
        apply_runtime_override(behaviour="off", threshold=0.5, updated_by="x")
        assert get_runtime_override() is not None
        db, api_cfg = _mock_db()
        with _patch_db(db):
            r = app_client.delete("/admin/assamese-purity")
        assert r.status_code == 200
        body = r.json()
        assert body["cleared"] is True
        assert get_runtime_override() is None
        api_cfg.update_one.assert_awaited()
        call_args = api_cfg.update_one.call_args
        assert "$unset" in call_args.args[1]

    def test_delete_fails_closed_when_persistence_fails(self, app_client):
        """If mongo unset fails, in-memory override must NOT be cleared
        (otherwise the override would silently come back on next worker
        restart and admins would have no idea the clear didn't stick)."""
        from lang_sanitizer import (
            apply_runtime_override, get_runtime_override,
        )
        apply_runtime_override(behaviour="off", threshold=0.5, updated_by="x")
        api_cfg = MagicMock()
        api_cfg.find_one = AsyncMock(return_value=None)
        api_cfg.update_one = AsyncMock(side_effect=RuntimeError("mongo down"))
        db = MagicMock()
        db.api_config = api_cfg
        with _patch_db(db):
            r = app_client.delete("/admin/assamese-purity")
        assert r.status_code == 500
        # In-memory override survived the failed clear.
        ov = get_runtime_override()
        assert ov is not None
        assert ov.get("behaviour") == "off"


class TestTestFireRoute:
    def test_test_fire_runs_sanitiser_against_default_sample(self, app_client):
        db, _ = _mock_db()
        # Disable sarvam_client so the translate callable returns "" and the
        # strip fallback handles cleanup deterministically (no network).
        with _patch_db(db), \
             patch("routes.cms_sarvam_health.sarvam_client", None):
            r = app_client.post("/admin/assamese-purity/test", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["raw"]
        # Live sanitiser cleaned the leaky sample — the obvious leakage
        # tokens should be gone from the cleaned output.
        assert "me uses" not in body["cleaned"]
        assert "ssible" not in body["cleaned"]
        # Diagnostic block has the required fields the UI renders.
        diag = body["diag"]
        for k in ("action", "ratio", "threshold", "behaviour"):
            assert k in diag

    def test_test_fire_rejects_empty_sample(self, app_client):
        db, _ = _mock_db()
        with _patch_db(db), \
             patch("routes.cms_sarvam_health.sarvam_client", None):
            r = app_client.post("/admin/assamese-purity/test", json={"sample": "   "})
        assert r.status_code == 400


class TestPersistedOverrideRoundTrip:
    def test_apply_persisted_override_seeds_in_memory_layer(self):
        """The lifespan loader must read the persisted doc on api boot
        and seed the in-memory override so behaviour survives restart."""
        import asyncio
        from lang_sanitizer import (
            get_behaviour, get_threshold, get_runtime_override,
        )
        from routes.cms_sarvam_health import (
            apply_persisted_assamese_purity_override,
        )
        api_cfg = MagicMock()
        api_cfg.find_one = AsyncMock(return_value={
            "assamese_purity_override": {
                "behaviour": "off",
                "threshold": 0.09,
                "updated_by": "boot-test",
            }
        })
        db = MagicMock()
        db.api_config = api_cfg
        with _patch_db(db):
            asyncio.new_event_loop().run_until_complete(
                apply_persisted_assamese_purity_override()
            )
        assert get_behaviour() == "off"
        assert get_threshold() == pytest.approx(0.09)
        ov = get_runtime_override()
        assert ov and ov.get("updated_by") == "boot-test"
