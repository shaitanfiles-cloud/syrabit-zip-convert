"""Task #756 — backend coverage for the Trustpilot refresh-cron heartbeat
endpoint (``POST /api/config/trustpilot/refresh-cron-heartbeat``).

Task #751 added the heartbeat ping so the GitHub Actions cron can prove
it ran independently of whether the Trustpilot fetch itself succeeded.
The cron-staleness alerter (Task #728) reads back the same shared
``_TP_REFRESH_CRON_HEALTH_DOC_ID`` health doc to drive the >36h "cron
silent" page. The endpoint had no direct test coverage — only the
alerter side did — so a regression in the auth gate, body coercion, or
the persisted health-doc shape would silently break the page without
any test failing.

Covers, mirroring the shape of ``tests/test_trustpilot_refresh_webhook.py``:
  * missing ``TRUSTPILOT_REFRESH_SECRET`` env  → 503 (fail-closed);
  * blank/whitespace ``TRUSTPILOT_REFRESH_SECRET`` env → 503;
  * missing / wrong ``X-Trustpilot-Refresh-Secret`` header → 401;
  * invalid body (non-object JSON) → 422;
  * happy path persists ``last_status`` / ``last_rc`` / ``last_run_url``
    (and the success-only ``last_success_heartbeat_ts`` /
    ``last_success_run_url``) into the shared health doc and returns
    200; the persisted shape matches what
    ``get_trustpilot_refresh_cron_health()`` reads back so the alerter
    keeps working.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import config as config_module
from routes.config import router


HEARTBEAT_PATH = "/api/config/trustpilot/refresh-cron-heartbeat"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def fake_deps(monkeypatch):
    """Stub ``deps.db.job_locks.update_one`` + ``is_mongo_available`` so
    the handler's ``from deps import db, is_mongo_available`` lazy
    import resolves to a controllable fake. Returns the ``update_one``
    AsyncMock so tests can introspect the persisted payload.
    """
    import sys

    update_one = AsyncMock(return_value=None)
    job_locks = MagicMock()
    job_locks.update_one = update_one
    db = MagicMock()
    db.job_locks = job_locks

    fake_module = sys.modules.get("deps")
    # Snapshot the originals so we can restore them after the test.
    orig_db = getattr(fake_module, "db", None) if fake_module else None
    orig_avail = getattr(fake_module, "is_mongo_available", None) if fake_module else None

    if fake_module is None:
        import types
        fake_module = types.ModuleType("deps")
        sys.modules["deps"] = fake_module

    fake_module.db = db
    fake_module.is_mongo_available = AsyncMock(return_value=True)

    yield update_one

    # Restore (or scrub) so other tests aren't tainted by our overrides.
    if orig_db is None:
        try:
            delattr(fake_module, "db")
        except AttributeError:
            pass
    else:
        fake_module.db = orig_db
    if orig_avail is None:
        try:
            delattr(fake_module, "is_mongo_available")
        except AttributeError:
            pass
    else:
        fake_module.is_mongo_available = orig_avail


# ─── secret env not configured (503) ────────────────────────────────────────

def test_heartbeat_returns_503_when_secret_env_missing(client, monkeypatch):
    monkeypatch.delenv("TRUSTPILOT_REFRESH_SECRET", raising=False)
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "anything"},
        json={"status": "success", "rc": 0},
    )
    assert res.status_code == 503
    assert res.json()["detail"] == "trustpilot_refresh_secret_not_configured"


def test_heartbeat_returns_503_when_secret_env_blank(client, monkeypatch):
    """An empty/whitespace secret env must fail closed exactly like a
    missing one — otherwise an accidentally-blanked deploy would accept
    anonymous heartbeats and forever mask a silent cron."""
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "   ")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "   "},
        json={"status": "success"},
    )
    assert res.status_code == 503
    assert res.json()["detail"] == "trustpilot_refresh_secret_not_configured"


# ─── wrong / missing secret header (401) ────────────────────────────────────

def test_heartbeat_returns_401_when_header_missing(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(HEARTBEAT_PATH, json={"status": "success"})
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid_refresh_secret"


def test_heartbeat_returns_401_on_secret_mismatch(client, monkeypatch):
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "wrong"},
        json={"status": "success"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid_refresh_secret"


def test_heartbeat_returns_401_on_blank_header_with_configured_secret(
    client, monkeypatch,
):
    """A whitespace-only header must NOT be treated as a valid secret
    even when the env secret is also whitespace-stripped — a blank
    header is by construction not equal to the (non-empty) configured
    secret, so the handler's ``hmac.compare_digest`` branch must reject."""
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "   "},
        json={"status": "success"},
    )
    assert res.status_code == 401


# ─── invalid body (422) ─────────────────────────────────────────────────────

def test_heartbeat_returns_422_when_body_is_not_an_object(client, monkeypatch):
    """The handler declares ``body: Dict[str, Any]`` so FastAPI's body
    validation rejects non-object JSON (lists, strings, numbers) with a
    422 before our handler runs. This guards against a workflow that
    accidentally posts a JSON array of fields instead of an object."""
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json=["status", "success"],
    )
    assert res.status_code == 422


# ─── happy path persists status/rc/run into the shared health doc ──────────

def test_heartbeat_happy_path_persists_success_fields(
    client, monkeypatch, fake_deps,
):
    """A valid POST with ``status=success`` must:
      * return 200 with ``ok: True`` and a numeric ``ts``;
      * upsert the shared ``_TP_REFRESH_CRON_HEALTH_DOC_ID`` doc with
        the status/rc/run metadata the alerter (Task #728) reads back;
      * advance BOTH ``last_heartbeat_ts`` (any-status) AND
        ``last_success_heartbeat_ts`` (success-only) via ``$max`` so a
        late-arriving older heartbeat can never rewind the silence
        clock; persist ``last_success_run_url`` for the dashboard.
    """
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={
            "status": "success",
            "rc": 0,
            "runUrl": "https://github.com/o/r/actions/runs/42",
            "workflowUrl": "https://github.com/o/r/actions/workflows/trustpilot.yml",
            "runId": "42",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["ts"], (int, float))
    assert body["ts"] > 0

    update_one.assert_awaited_once()
    args, kwargs = update_one.await_args
    query, update = args[0], args[1]
    assert query == {"_id": config_module._TP_REFRESH_CRON_HEALTH_DOC_ID}
    assert kwargs.get("upsert") is True

    set_payload = update["$set"]
    assert set_payload["last_status"] == "success"
    assert set_payload["last_rc"] == 0
    assert set_payload["last_run_url"] == "https://github.com/o/r/actions/runs/42"
    assert set_payload["last_workflow_url"] == (
        "https://github.com/o/r/actions/workflows/trustpilot.yml"
    )
    assert set_payload["last_run_id"] == "42"
    assert set_payload["updated_at"] > 0
    # Success branch must also pin the success-only run-url so the
    # dashboard's "last good run" link works.
    assert set_payload["last_success_run_url"] == (
        "https://github.com/o/r/actions/runs/42"
    )

    max_payload = update["$max"]
    assert max_payload["last_heartbeat_ts"] > 0
    # status=success → success heartbeat clock advances too.
    assert max_payload["last_success_heartbeat_ts"] > 0
    assert (
        max_payload["last_heartbeat_ts"]
        == max_payload["last_success_heartbeat_ts"]
    )

    set_on_insert = update["$setOnInsert"]
    assert set_on_insert["first_observed_ts"] > 0


def test_heartbeat_failure_status_does_not_advance_success_clock(
    client, monkeypatch, fake_deps,
):
    """A ``status=failure`` heartbeat must record the run metadata but
    must NOT update ``last_success_heartbeat_ts`` / ``last_success_run_url``
    — otherwise a perpetually-failing cron would forever silence the
    >36h "no successful run" page (the very regression the alerter test
    ``test_perpetually_failing_cron_classifies_silent_after_threshold``
    guards against on the read side). This test enforces the same
    invariant on the WRITE side.
    """
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={
            "status": "failure",
            "rc": 2,
            "runUrl": "https://github.com/o/r/actions/runs/99",
            "runId": "99",
        },
    )
    assert res.status_code == 200

    update_one.assert_awaited_once()
    _, update = update_one.await_args.args[0], update_one.await_args.args[1]

    set_payload = update["$set"]
    assert set_payload["last_status"] == "failure"
    assert set_payload["last_rc"] == 2
    assert set_payload["last_run_url"] == "https://github.com/o/r/actions/runs/99"
    # Critical invariant: failure must not pin a fake "last good run".
    assert "last_success_run_url" not in set_payload

    max_payload = update["$max"]
    assert max_payload["last_heartbeat_ts"] > 0
    assert "last_success_heartbeat_ts" not in max_payload


def test_heartbeat_skips_persist_when_mongo_unavailable(
    client, monkeypatch, fake_deps,
):
    """Mongo outage must not break the heartbeat — the handler swallows
    the persist failure and still returns 200 so the cron run isn't
    marked failed by GitHub Actions for a transient DB hiccup. The
    alerter degrades gracefully (no doc → "unknown" → no page)."""
    import sys

    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    sys.modules["deps"].is_mongo_available = AsyncMock(return_value=False)
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={"status": "success", "rc": 0},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    update_one.assert_not_awaited()


def test_heartbeat_coerces_non_numeric_rc_to_none(
    client, monkeypatch, fake_deps,
):
    """``rc`` arrives as a string from the GitHub Actions shell. The
    handler must coerce non-integer values to ``None`` (recorded as-is
    in the doc) rather than 422-ing the cron — the heartbeat is
    best-effort metadata, not a contract the workflow can satisfy
    perfectly."""
    monkeypatch.setenv("TRUSTPILOT_REFRESH_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-Trustpilot-Refresh-Secret": "s3cret"},
        json={"status": "success", "rc": "not-an-int"},
    )
    assert res.status_code == 200

    update_one.assert_awaited_once()
    set_payload = update_one.await_args.args[1]["$set"]
    assert set_payload["last_rc"] is None
    assert set_payload["last_status"] == "success"
