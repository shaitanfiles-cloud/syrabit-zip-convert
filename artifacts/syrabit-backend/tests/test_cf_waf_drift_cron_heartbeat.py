"""Task #831 — backend coverage for the cf-waf-drift cron heartbeat
endpoint (``POST /api/config/cf-waf-drift/heartbeat``).

Mirrors ``tests/test_trustpilot_refresh_cron_heartbeat.py`` (Task #756)
because the silence alerter on top reads back the same shared
``cf_waf_drift_cron_health`` health doc to drive the >36h "cron silent"
page. A regression in the auth gate, body coercion, or persisted
health-doc shape would silently break the page without any test
failing.

Covers:
  * missing ``CF_WAF_DRIFT_HEARTBEAT_SECRET`` env  → 503 (fail-closed);
  * blank/whitespace ``CF_WAF_DRIFT_HEARTBEAT_SECRET`` env → 503;
  * missing / wrong ``X-CF-WAF-Drift-Secret`` header → 401;
  * invalid body (non-object JSON) → 422;
  * happy path persists ``last_status`` / ``last_verify_rc`` /
    ``last_aggregate_rc`` / ``last_run_url`` (and advances
    ``last_heartbeat_ts`` via ``$max``);
  * Mongo unavailable → 200 anyway (best-effort persist);
  * non-numeric verifyRc/aggregateRc → coerced to ``None`` (no 422).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import cf_waf_drift_cron_heartbeat as heartbeat_module
from routes.cf_waf_drift_cron_heartbeat import router


HEARTBEAT_PATH = "/api/config/cf-waf-drift/heartbeat"


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
    orig_db = getattr(fake_module, "db", None) if fake_module else None
    orig_avail = (
        getattr(fake_module, "is_mongo_available", None) if fake_module else None
    )

    if fake_module is None:
        import types
        fake_module = types.ModuleType("deps")
        sys.modules["deps"] = fake_module

    fake_module.db = db
    fake_module.is_mongo_available = AsyncMock(return_value=True)

    yield update_one

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
    monkeypatch.delenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", raising=False)
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "anything"},
        json={"status": "success", "verifyRc": 0, "aggregateRc": 0},
    )
    assert res.status_code == 503
    assert (
        res.json()["detail"]
        == "cf_waf_drift_heartbeat_secret_not_configured"
    )


def test_heartbeat_returns_503_when_secret_env_blank(client, monkeypatch):
    """An empty/whitespace secret env must fail closed exactly like a
    missing one — otherwise an accidentally-blanked deploy would accept
    anonymous heartbeats and forever mask a silent cron."""
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "   ")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "   "},
        json={"status": "success"},
    )
    assert res.status_code == 503


# ─── wrong / missing secret header (401) ────────────────────────────────────

def test_heartbeat_returns_401_when_header_missing(client, monkeypatch):
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    res = client.post(HEARTBEAT_PATH, json={"status": "success"})
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid_heartbeat_secret"


def test_heartbeat_returns_401_on_secret_mismatch(client, monkeypatch):
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "wrong"},
        json={"status": "success"},
    )
    assert res.status_code == 401


def test_heartbeat_returns_401_on_blank_header_with_configured_secret(
    client, monkeypatch,
):
    """A whitespace-only header must NOT be treated as a valid secret —
    a blank header is by construction not equal to the (non-empty)
    configured secret, so the handler's ``hmac.compare_digest`` branch
    must reject."""
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "   "},
        json={"status": "success"},
    )
    assert res.status_code == 401


# ─── invalid body (422) ─────────────────────────────────────────────────────

def test_heartbeat_returns_422_when_body_is_not_an_object(client, monkeypatch):
    """The handler declares ``body: Dict[str, Any]`` so FastAPI's body
    validation rejects non-object JSON (lists, strings, numbers) with a
    422 before our handler runs."""
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "s3cret"},
        json=["status", "success"],
    )
    assert res.status_code == 422


# ─── happy path persists status/rc/run into the shared health doc ──────────

def test_heartbeat_happy_path_persists_success_fields(
    client, monkeypatch, fake_deps,
):
    """A valid POST with ``status=success`` must:
      * return 200 with ``ok: True`` and a numeric ``ts``;
      * upsert the shared ``cf_waf_drift_cron_health`` doc with the
        status/rc/run metadata the alerter reads back;
      * advance ``last_heartbeat_ts`` via ``$max`` so a late-arriving
        older heartbeat can never rewind the silence clock.
    """
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "s3cret"},
        json={
            "status": "success",
            "verifyRc": 0,
            "aggregateRc": 0,
            "runUrl": "https://github.com/o/r/actions/runs/42",
            "workflowUrl": "https://github.com/o/r/actions/workflows/cf-waf-drift-daily.yml",
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
    assert query == {"_id": heartbeat_module.CF_WAF_DRIFT_HEALTH_DOC_ID}
    assert kwargs.get("upsert") is True

    set_payload = update["$set"]
    assert set_payload["last_status"] == "success"
    assert set_payload["last_verify_rc"] == 0
    assert set_payload["last_aggregate_rc"] == 0
    assert set_payload["last_run_url"] == (
        "https://github.com/o/r/actions/runs/42"
    )
    assert set_payload["last_workflow_url"] == (
        "https://github.com/o/r/actions/workflows/cf-waf-drift-daily.yml"
    )
    assert set_payload["last_run_id"] == "42"
    assert set_payload["updated_at"] > 0

    max_payload = update["$max"]
    assert max_payload["last_heartbeat_ts"] > 0

    set_on_insert = update["$setOnInsert"]
    assert set_on_insert["first_observed_ts"] > 0


def test_heartbeat_drift_status_still_persists_run_metadata(
    client, monkeypatch, fake_deps,
):
    """A drift-detected heartbeat (verify_rc=1) must ALSO record the
    run metadata and advance the heartbeat clock — the workflow's
    per-run Slack alert covers the drift signal, but the silence
    alerter still needs to know the cron ran on schedule. This is the
    intentional divergence from the Trustpilot precedent: any
    heartbeat counts."""
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "s3cret"},
        json={
            "status": "drift",
            "verifyRc": 1,
            "aggregateRc": 0,
            "runUrl": "https://github.com/o/r/actions/runs/99",
            "runId": "99",
        },
    )
    assert res.status_code == 200

    update_one.assert_awaited_once()
    update = update_one.await_args.args[1]

    set_payload = update["$set"]
    assert set_payload["last_status"] == "drift"
    assert set_payload["last_verify_rc"] == 1
    assert set_payload["last_aggregate_rc"] == 0
    assert set_payload["last_run_url"] == (
        "https://github.com/o/r/actions/runs/99"
    )
    # Heartbeat clock advances even on drift — that's the whole point
    # of the silence-alerter divergence from the Trustpilot pattern.
    max_payload = update["$max"]
    assert max_payload["last_heartbeat_ts"] > 0


def test_heartbeat_skips_persist_when_mongo_unavailable(
    client, monkeypatch, fake_deps,
):
    """Mongo outage must not break the heartbeat — the handler swallows
    the persist failure and still returns 200 so the cron run isn't
    marked failed by GitHub Actions for a transient DB hiccup. The
    alerter degrades gracefully (no doc → "unknown" → no page)."""
    import sys

    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    sys.modules["deps"].is_mongo_available = AsyncMock(return_value=False)
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "s3cret"},
        json={"status": "success", "verifyRc": 0, "aggregateRc": 0},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    update_one.assert_not_awaited()


def test_heartbeat_coerces_non_numeric_rc_to_none(
    client, monkeypatch, fake_deps,
):
    """``verifyRc`` / ``aggregateRc`` arrive as strings from the GitHub
    Actions shell (``${{ steps.verify.outputs.rc }}`` is unquoted shell
    text). The handler must coerce non-integer values (including the
    empty string when a step was skipped/cancelled) to ``None`` rather
    than 422-ing the cron — the heartbeat is best-effort metadata."""
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "s3cret"},
        json={
            "status": "failure",
            "verifyRc": "not-an-int",
            "aggregateRc": "",
        },
    )
    assert res.status_code == 200

    update_one.assert_awaited_once()
    set_payload = update_one.await_args.args[1]["$set"]
    assert set_payload["last_verify_rc"] is None
    assert set_payload["last_aggregate_rc"] is None
    assert set_payload["last_status"] == "failure"


def test_heartbeat_accepts_string_rc_from_workflow_shell(
    client, monkeypatch, fake_deps,
):
    """The actual workflow ships ``"0"`` / ``"1"`` / ``"2"`` as strings
    via jq's ``--arg``. The coercer must accept those and store them as
    real ints so the dashboard renders them correctly."""
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "s3cret"},
        json={
            "status": "transport_error",
            "verifyRc": "0",
            "aggregateRc": "2",
        },
    )
    assert res.status_code == 200
    set_payload = update_one.await_args.args[1]["$set"]
    assert set_payload["last_verify_rc"] == 0
    assert set_payload["last_aggregate_rc"] == 2
    assert set_payload["last_status"] == "transport_error"


def test_heartbeat_records_unknown_status_truncated(
    client, monkeypatch, fake_deps,
):
    """An unrecognised status string must be recorded (truncated to 32
    chars) rather than rejected — the heartbeat endpoint stays
    permissive so a future status string addition doesn't 422 the cron
    until both sides ship."""
    monkeypatch.setenv("CF_WAF_DRIFT_HEARTBEAT_SECRET", "s3cret")
    update_one = fake_deps

    res = client.post(
        HEARTBEAT_PATH,
        headers={"X-CF-WAF-Drift-Secret": "s3cret"},
        json={"status": "x" * 100},
    )
    assert res.status_code == 200
    set_payload = update_one.await_args.args[1]["$set"]
    assert set_payload["last_status"] == "x" * 32
