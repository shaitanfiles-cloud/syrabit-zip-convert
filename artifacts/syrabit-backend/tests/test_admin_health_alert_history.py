"""Task #918 — admin alert-history endpoint contract tests.

Locks down the JSON shape returned by the three alert-history GET
endpoints surfaced to the AdminHealth dashboard:

* ``/admin/health/edge-proxy-deploy/cron/alert-history``
  (Task #893 alerter, ``_LOCK_ID="edge_proxy_deploy_cron_alert_state"``)
* ``/admin/health/cf-waf-drift/cron/alert-history``
  (Task #831 alerter, ``_LOCK_ID="cf_waf_drift_cron_alert_state"``)
* ``/admin/health/trustpilot/refresh-cron/alert-history``
  (Task #751 alerter, ``_LOCK_ID="trustpilot_refresh_cron_alert_state"``)

Plus the recording side: the shared ``record_cron_alert_event``
helper that all three alerters call from inside their
``_send_cron_alert`` block. The recording helper is best-effort by
contract (must never raise inside the alerter loop), so we cover
both the happy-path insert + cap-trim and the Mongo-down
swallowing.

Mirrors the testing pattern in test_admin_health_alert_state.py
(``_FakeDb`` + ``_patch_mongo`` context manager) so a future
shared helper change can be validated against both contracts in
one place.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True,
            "sub": "admin-1"}


def _build_app(routers, mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user

    app = FastAPI()
    for r in routers:
        app.include_router(r)
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


from routes.admin_health import _HISTORY_DEFAULT_LIMIT  # noqa: E402


@pytest.fixture
def edge_proxy_client(mock_admin):
    from routes.admin_health import router
    return _build_app([router], mock_admin)


@pytest.fixture
def cf_waf_drift_client(mock_admin):
    from routes.admin_cf_waf_drift_cron_alerts import router
    return _build_app([router], mock_admin)


@pytest.fixture
def trustpilot_client(mock_admin):
    from routes.admin_trustpilot_cron_alerts import router
    return _build_app([router], mock_admin)


# ─── Fake collection / cursor mocks ────────────────────────────────────────

class _FakeCursor:
    """Minimal motor-like cursor supporting the
    ``find().sort().limit().to_list()`` chain used by
    ``_build_alert_history_response``. Returns ``self`` from
    ``sort`` / ``limit`` so the chain reads naturally; the actual
    docs are picked up at ``to_list`` time so a test can assert
    the requested ``limit`` was honoured."""

    def __init__(self, docs):
        self._docs = list(docs)
        self._limit = None

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    async def to_list(self, length=None):
        cap = length if length is not None else self._limit
        if cap is None:
            return list(self._docs)
        return list(self._docs)[: int(cap)]


class _FakeHistoryCollection:
    """Single-collection stub for ``cron_alert_history``. Only
    implements the read methods the endpoint touches; the
    recording-side helper is exercised separately below with its
    own collection mock."""

    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, _query, *_a, **_kw):
        return _FakeCursor(self._docs)


class _FakeDb:
    def __init__(self, history_docs):
        self._docs = list(history_docs)

    def __getitem__(self, name):
        if name == "cron_alert_history":
            return _FakeHistoryCollection(self._docs)
        raise KeyError(name)


def _patch_mongo(history_docs, available=True):
    import deps
    if available:
        availability = AsyncMock(return_value=True)
    else:
        availability = AsyncMock(return_value=False)
    return patch.multiple(
        deps,
        db=_FakeDb(history_docs),
        is_mongo_available=availability,
    )


def _evt(*, lock_id, kind, ago_seconds, sub_kind=None, run_id=12345,
         conclusion="failure"):
    """Compose a single stored cron_alert_history doc, mirroring the
    shape ``record_cron_alert_event`` writes. Centralised here so a
    future schema tweak only has to update one place."""
    paged_at = datetime.now(timezone.utc) - timedelta(seconds=ago_seconds)
    return {
        "_id": f"evt-{lock_id}-{ago_seconds}",
        "lock_id": lock_id,
        "kind": kind,
        "sub_kind": sub_kind,
        "paged_at": paged_at.isoformat(),
        "created_at": paged_at,
        "last_html_url":
            f"https://github.com/x/y/actions/runs/{run_id}",
        "last_run_url":
            f"https://github.com/x/y/actions/runs/{run_id}",
        "last_workflow_url":
            "https://github.com/x/y/actions/workflows/edge-proxy-deploy.yml",
        "last_conclusion": conclusion,
        "last_age_seconds": 600,
        "last_run_id": run_id,
        "last_head_sha": "deadbeef",
        "last_pill_status": "silent",
    }


# ─── /admin/health/edge-proxy-deploy/cron/alert-history ───────────────────

def test_edge_proxy_alert_history_returns_empty_when_no_events(edge_proxy_client):
    """Alerter has never fired → ``events: []`` plus the static
    ``limit``. Pill renders the "No on-call pages recorded yet"
    empty-state row."""
    with _patch_mongo([]):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-history"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["events"] == []
    assert body["limit"] == 20
    assert body["lockId"] == "edge_proxy_deploy_cron_alert_state"


def test_edge_proxy_alert_history_returns_empty_when_mongo_down(edge_proxy_client):
    """Mongo unavailable → defensive ``events: []`` rather than 500.
    Mirrors the alert-state helper above which already handles the
    same defensive contract."""
    docs = [_evt(lock_id="edge_proxy_deploy_cron_alert_state",
                 kind="broken", sub_kind="failed", ago_seconds=3600)]
    with _patch_mongo(docs, available=False):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-history"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["events"] == []
    # Even when Mongo is down the lockId/limit pair is still echoed
    # back so the dashboard's empty-state copy stays uniform across
    # transient infra hiccups vs "alerter has never fired".
    assert body["lockId"] == "edge_proxy_deploy_cron_alert_state"
    assert body["limit"] == 20


def test_edge_proxy_alert_history_shapes_events(edge_proxy_client):
    """Stored docs project to camelCase shape with the run-link /
    conclusion / kind fields the dashboard needs to render the
    coloured "PAGED · failure · run #N" rows."""
    docs = [
        _evt(lock_id="edge_proxy_deploy_cron_alert_state",
             kind="broken", sub_kind="failed", ago_seconds=3600,
             run_id=999, conclusion="failure"),
        _evt(lock_id="edge_proxy_deploy_cron_alert_state",
             kind="recovered", sub_kind=None, ago_seconds=600,
             run_id=1000, conclusion="success"),
    ]
    with _patch_mongo(docs):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-history"
        )
    body = res.json()
    assert len(body["events"]) == 2
    first = body["events"][0]
    # camelCase projection for the frontend.
    assert "pagedAt" in first
    assert first["kind"] == "broken"
    assert first["subKind"] == "failed"
    assert first["lastConclusion"] == "failure"
    assert first["lastRunId"] == 999
    assert first["lastRunUrl"].endswith("/runs/999")
    second = body["events"][1]
    assert second["kind"] == "recovered"
    assert second["subKind"] is None


def test_edge_proxy_alert_history_honours_limit_query(edge_proxy_client):
    """``?limit=`` is forwarded to the helper and clamped to the
    safe range. Asking for 5 returns at most 5 events; the cursor
    mock asserts the limit was actually pushed down."""
    docs = [
        _evt(lock_id="edge_proxy_deploy_cron_alert_state",
             kind="broken", sub_kind="failed", ago_seconds=i * 600,
             run_id=1000 + i)
        for i in range(10)
    ]
    with _patch_mongo(docs):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-history?limit=5"
        )
    body = res.json()
    assert body["limit"] == 5
    assert len(body["events"]) == 5


def test_edge_proxy_alert_history_clamps_excessive_limit(edge_proxy_client):
    """A misbehaving caller asking for ``?limit=99999`` is clamped to
    the per-lock cap so the endpoint cannot be used to page through
    every stored event in one shot."""
    with _patch_mongo([]):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-history?limit=99999"
        )
    body = res.json()
    # Hard cap is 200 (see _HISTORY_MAX_PER_LOCK).
    assert body["limit"] == 200


def test_edge_proxy_alert_history_zero_limit_falls_back_to_default(edge_proxy_client):
    """``?limit=0`` is treated as "use the default" (the helper does
    ``int(limit or _HISTORY_DEFAULT_LIMIT)`` so a falsy 0 short-
    circuits to 20). This locks down that behaviour so a future
    refactor doesn't accidentally start returning a single-item
    list to admins who passed ``?limit=0``."""
    with _patch_mongo([]):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-history?limit=0"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["limit"] == _HISTORY_DEFAULT_LIMIT


def test_edge_proxy_alert_history_clamps_negative_limit(edge_proxy_client):
    """A negative ``?limit=-5`` is clamped UP to 1 rather than
    returning ``[]`` (Mongo's ``.limit(-5)`` would otherwise behave
    as a single-batch hint and surprise the caller). Guards the
    floor side of the ``max(1, min(...))`` clamp in the helper."""
    with _patch_mongo([]):
        res = edge_proxy_client.get(
            "/admin/health/edge-proxy-deploy/cron/alert-history?limit=-5"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["limit"] == 1


# ─── Sibling endpoints — same shape, different lock_id ────────────────────

def test_cf_waf_drift_alert_history_returns_lock_id(cf_waf_drift_client):
    docs = [_evt(lock_id="cf_waf_drift_cron_alert_state",
                 kind="silent", ago_seconds=7200)]
    with _patch_mongo(docs):
        res = cf_waf_drift_client.get(
            "/admin/health/cf-waf-drift/cron/alert-history"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["lockId"] == "cf_waf_drift_cron_alert_state"
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "silent"


def test_trustpilot_alert_history_returns_lock_id(trustpilot_client):
    docs = [_evt(lock_id="trustpilot_refresh_cron_alert_state",
                 kind="silent", ago_seconds=3600)]
    with _patch_mongo(docs):
        res = trustpilot_client.get(
            "/admin/health/trustpilot/refresh-cron/alert-history"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["lockId"] == "trustpilot_refresh_cron_alert_state"
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "silent"


def test_trustpilot_alert_history_empty_when_mongo_down(trustpilot_client):
    """Defensive Mongo-down contract holds for the sibling endpoints
    too (they delegate to the same shared helper)."""
    docs = [_evt(lock_id="trustpilot_refresh_cron_alert_state",
                 kind="silent", ago_seconds=3600)]
    with _patch_mongo(docs, available=False):
        res = trustpilot_client.get(
            "/admin/health/trustpilot/refresh-cron/alert-history"
        )
    assert res.status_code == 200
    assert res.json()["events"] == []


# ─── Recording side: record_cron_alert_event ──────────────────────────────

class _FakeAsyncTrimCursor:
    """Tiny cursor stub for the recording-side trim path. Supports
    ``find(...).sort(...).limit(...)`` chaining and ``async for``
    iteration over a pre-canned list of ``{"_id": ...}`` docs.
    Kept as a real class (rather than ``MagicMock(__aiter__=…)``)
    because Python's ``async for`` resolves ``__aiter__`` via
    ``type(obj)`` and per-instance MagicMock attributes don't
    reliably participate in that lookup across versions."""

    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _FakeRecordingCollection:
    """Recording-side stub. The helper calls ``insert_one`` then a
    ``count_documents`` + ``find().sort().limit()`` + ``delete_many``
    for the cap trim. We mock all four and assert the helper called
    them in the right shape. The trim cursor is a real
    ``_FakeAsyncTrimCursor`` so ``async for`` works deterministically."""

    def __init__(self, *, count=0, trim_docs=None):
        self.insert_one = AsyncMock()
        self.count_documents = AsyncMock(return_value=count)
        self.delete_many = AsyncMock()
        self.trim_docs = list(trim_docs or [])
        self.find_calls: list[tuple] = []

    def find(self, *args, **kwargs):
        self.find_calls.append((args, kwargs))
        return _FakeAsyncTrimCursor(self.trim_docs)


class _FakeRecordingDb:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, name):
        assert name == "cron_alert_history"
        return self._collection


@pytest.mark.anyio
async def test_record_cron_alert_event_inserts_doc():
    """Happy path: helper inserts a well-shaped doc into
    ``cron_alert_history``. The lock_id / kind / sub_kind / paged_at
    fields must round-trip verbatim so the read endpoint can sort +
    project them back out."""
    from routes.admin_health import record_cron_alert_event
    coll = _FakeRecordingCollection(count=1)
    db = _FakeRecordingDb(coll)
    now_utc = datetime.now(timezone.utc)
    health = {
        "status": "silent",
        "html_url": "https://github.com/x/y/actions/runs/777",
        "lastRunUrl": "https://github.com/x/y/actions/runs/777",
        "workflowUrl":
            "https://github.com/x/y/actions/workflows/edge-proxy-deploy.yml",
        "conclusion": "failure",
        "ageSeconds": 600,
        "runId": 777,
        "headSha": "deadbeef",
    }
    await record_cron_alert_event(
        db,
        lock_id="edge_proxy_deploy_cron_alert_state",
        kind="broken",
        sub_kind="failed",
        health=health,
        now_utc=now_utc,
    )
    coll.insert_one.assert_awaited_once()
    inserted = coll.insert_one.await_args.args[0]
    assert inserted["lock_id"] == "edge_proxy_deploy_cron_alert_state"
    assert inserted["kind"] == "broken"
    assert inserted["sub_kind"] == "failed"
    assert inserted["paged_at"] == now_utc.isoformat()
    assert inserted["last_run_url"].endswith("/runs/777")
    assert inserted["last_pill_status"] == "silent"


@pytest.mark.anyio
async def test_record_cron_alert_event_swallows_mongo_errors():
    """Best-effort contract: any exception inside the helper is
    swallowed so a slow / dead Mongo can't propagate up into the
    alerter's _send loop and abort the rest of the fan-out."""
    from routes.admin_health import record_cron_alert_event
    coll = _FakeRecordingCollection()
    coll.insert_one = AsyncMock(side_effect=RuntimeError("mongo down"))
    db = _FakeRecordingDb(coll)
    # Must not raise.
    await record_cron_alert_event(
        db,
        lock_id="edge_proxy_deploy_cron_alert_state",
        kind="broken",
        sub_kind="failed",
        health={},
        now_utc=datetime.now(timezone.utc),
    )


@pytest.mark.anyio
async def test_record_cron_alert_event_trim_runs_when_over_cap():
    """When the per-lock count exceeds the 200-doc cap the helper
    schedules a ``delete_many`` for the oldest excess docs. Trim is
    best-effort; the insert above is unaffected by trim outcomes."""
    from routes.admin_health import (
        record_cron_alert_event, _HISTORY_MAX_PER_LOCK,
    )
    coll = _FakeRecordingCollection(
        count=_HISTORY_MAX_PER_LOCK + 3,
        # Pre-canned excess docs the trim cursor should yield.
        trim_docs=[{"_id": "old-1"}, {"_id": "old-2"}, {"_id": "old-3"}],
    )
    db = _FakeRecordingDb(coll)
    await record_cron_alert_event(
        db,
        lock_id="edge_proxy_deploy_cron_alert_state",
        kind="broken",
        sub_kind="failed",
        health={},
        now_utc=datetime.now(timezone.utc),
    )
    coll.delete_many.assert_awaited_once()
    delete_query = coll.delete_many.await_args.args[0]
    assert "_id" in delete_query
    assert set(delete_query["_id"]["$in"]) == {"old-1", "old-2", "old-3"}
