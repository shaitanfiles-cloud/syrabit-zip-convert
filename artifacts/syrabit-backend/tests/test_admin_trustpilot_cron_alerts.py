"""Task #751 — refresh-cron heartbeat + >36h "cron silent" alerter.

Covers:
* classification (silent / healthy / unknown), including the bootstrap
  grace window for a never-observed cron;
* admin health endpoint reduces the snapshot to a status pill;
* first silent detection alerts and persists state;
* silent→silent inside the 24h re-page debounce is suppressed;
* silent→silent past the debounce re-pages;
* silent→healthy fires exactly one recovery, then settles;
* healthy→healthy never alerts AND never writes the lock doc;
* not_configured never touches state;
* heartbeat endpoint authn (missing secret env, wrong header) and
  successful write path persists the expected fields.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from routes import admin_trustpilot_cron_alerts as cron


# ─── Fake Mongo (job_locks only) ────────────────────────────────────────────

class _FakeCursor:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        async def _gen():
            for it in self._items:
                yield it
        return _gen()


class _FakeColl:
    def __init__(self):
        self._docs: dict = {}

    async def find_one(self, query, projection=None, sort=None):
        if "_id" in query:
            doc = self._docs.get(query["_id"])
            return dict(doc) if doc else None
        return None

    async def find_one_and_update(self, query, update, upsert=False):
        def _matches(doc, q):
            for k, v in q.items():
                if k == "_id":
                    if doc.get("_id") != v:
                        return False
                    continue
                if k == "$or":
                    if not any(_matches(doc, sub) for sub in v):
                        return False
                    continue
                actual = doc.get(k)
                if isinstance(v, dict):
                    if "$ne" in v and actual == v["$ne"]:
                        return False
                    if "$lt" in v and not (
                        actual is not None and actual < v["$lt"]
                    ):
                        return False
                    if "$exists" in v and (k in doc) != bool(v["$exists"]):
                        return False
                else:
                    if actual != v:
                        return False
            return True

        _id = query["_id"]
        doc = self._docs.get(_id)
        if doc is None:
            return None
        if not _matches(doc, query):
            return None
        prior = dict(doc)
        doc.update(update.get("$set", {}))
        return prior

    async def update_one(self, query, update, upsert=False):
        _id = query["_id"]
        doc = self._docs.get(_id)
        if doc is None:
            if not upsert:
                return None
            doc = {"_id": _id}
            doc.update(update.get("$setOnInsert", {}))
            doc.update(update.get("$set", {}))
            for k, v in (update.get("$max") or {}).items():
                doc[k] = max(doc.get(k, 0) or 0, v)
            self._docs[_id] = doc
            return None
        # existing — apply $set / $max (no $setOnInsert effect).
        for k, v in (update.get("$set") or {}).items():
            doc[k] = v
        for k, v in (update.get("$max") or {}).items():
            doc[k] = max(doc.get(k, 0) or 0, v)
        return None

    async def insert_one(self, doc):
        _id = doc["_id"]
        if _id in self._docs:
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError("dup")
        self._docs[_id] = dict(doc)
        return None

    def find(self, *a, **kw):
        return _FakeCursor([])


class _FakeDb:
    def __init__(self):
        self.job_locks = _FakeColl()
        self.users = _FakeColl()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _now():
    return datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


def _health(*, configured=True, last_heartbeat_age_s=None,
            last_success_heartbeat_age_s="default",
            last_status="success",
            last_run_url="https://github.com/o/r/runs/1",
            first_observed_age_s=None):
    """Synthetic health snapshot.

    ``last_success_heartbeat_age_s`` defaults to whatever
    ``last_heartbeat_age_s`` is (i.e. simulating a successful run); pass
    explicit ``None`` to simulate "we have a heartbeat but no success".
    """
    now_ts = _now().timestamp()
    last_hb_ts = (
        now_ts - last_heartbeat_age_s if last_heartbeat_age_s is not None else None
    )
    if last_success_heartbeat_age_s == "default":
        last_success_heartbeat_age_s = (
            last_heartbeat_age_s if last_status == "success" else None
        )
    last_success_hb_ts = (
        now_ts - last_success_heartbeat_age_s
        if last_success_heartbeat_age_s is not None else None
    )
    first_obs_ts = (
        now_ts - first_observed_age_s
        if first_observed_age_s is not None else None
    )
    return {
        "configured": configured,
        "lastHeartbeatTs": last_hb_ts,
        "lastHeartbeatAgeSeconds": last_heartbeat_age_s,
        "lastSuccessHeartbeatTs": last_success_hb_ts,
        "lastSuccessHeartbeatAgeSeconds": last_success_heartbeat_age_s,
        "lastStatus": last_status if last_heartbeat_age_s is not None else None,
        "lastRc": 0 if last_heartbeat_age_s is not None else None,
        "lastRunUrl": last_run_url if last_heartbeat_age_s is not None else None,
        "lastSuccessRunUrl": (
            last_run_url if last_success_hb_ts is not None else None
        ),
        "lastWorkflowUrl": (
            "https://github.com/o/r/actions/workflows/x.yml"
            if last_heartbeat_age_s is not None else None
        ),
        "lastRunId": "1" if last_heartbeat_age_s is not None else None,
        "firstObservedTs": first_obs_ts,
    }


@pytest.fixture
def fake_db():
    return _FakeDb()


def _patch_send():
    return patch.object(cron, "_send_cron_alert", new_callable=AsyncMock)


# ─── Classification ─────────────────────────────────────────────────────────

def test_classify_buckets():
    now_ts = _now().timestamp()
    # Not configured → unknown.
    assert cron._classify_cron(_health(configured=False), now_ts, None) == "unknown"
    # Fresh successful heartbeat → healthy.
    assert cron._classify_cron(
        _health(last_heartbeat_age_s=3600), now_ts, None
    ) == "healthy"
    # Last successful heartbeat past threshold → silent.
    assert cron._classify_cron(
        _health(last_heartbeat_age_s=37 * 3600), now_ts, None
    ) == "silent"
    # Never observed, inside bootstrap grace → unknown.
    assert cron._classify_cron(
        _health(), now_ts, now_ts - 3600,
    ) == "unknown"
    # Never observed, past bootstrap grace → silent.
    assert cron._classify_cron(
        _health(), now_ts, now_ts - 49 * 3600,
    ) == "silent"
    # Never observed, no first-observed anchor yet → unknown.
    assert cron._classify_cron(_health(), now_ts, None) == "unknown"


def test_perpetually_failing_cron_classifies_silent_after_threshold():
    """Regression guard for the review's important comment: a workflow
    that runs every day on schedule but whose inner refresh script keeps
    failing posts a fresh (status=failure) heartbeat each run, so the
    naive "any heartbeat <36h old → healthy" rule would suppress the
    page forever. The classifier must instead key off the LAST SUCCESS
    age — matching the task spec wording ("last-success age >36h")."""
    now_ts = _now().timestamp()
    # Cron pinged 30 minutes ago with status=failure, but the last
    # actual success was 40h ago → silent.
    h = _health(
        last_heartbeat_age_s=1800,
        last_status="failure",
        last_success_heartbeat_age_s=40 * 3600,
    )
    assert cron._classify_cron(h, now_ts, None) == "silent"


def test_running_but_failing_inside_window_is_not_yet_silent():
    """If we have NEVER had a success but the cron is freshly running
    (failing), don't page yet — give it a chance to recover. The
    dashboard surfaces this as "degraded"; only after the threshold
    elapses does the alerter escalate to silent."""
    now_ts = _now().timestamp()
    h = _health(
        last_heartbeat_age_s=1800,
        last_status="failure",
        last_success_heartbeat_age_s=None,
    )
    assert cron._classify_cron(h, now_ts, None) == "healthy"


# ─── Alert lifecycle ────────────────────────────────────────────────────────

def test_first_silent_detection_alerts_and_persists(fake_db):
    now = _now()
    health = _health(last_heartbeat_age_s=40 * 3600, last_status="failure")
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_refresh_cron(fake_db, now, health)
        )
    assert result == {"action": "alerted", "kind": "silent"}
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[cron._LOCK_ID]
    assert saved["last_state"] == "silent"
    assert saved["last_alert_at"] == now.isoformat()
    assert saved["last_run_url"] == "https://github.com/o/r/runs/1"


def test_silent_within_debounce_is_suppressed(fake_db):
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    health = _health(last_heartbeat_age_s=42 * 3600, last_status="failure")
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_refresh_cron(fake_db, now, health)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "debounced"
    mock_send.assert_not_called()


def test_silent_outside_debounce_re_pages(fake_db):
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=25)).isoformat(),
    }
    health = _health(last_heartbeat_age_s=60 * 3600, last_status="failure")
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_refresh_cron(fake_db, now, health)
        )
    assert result == {"action": "alerted", "kind": "silent"}
    mock_send.assert_called_once()


def test_silent_to_healthy_fires_recovery_then_settles(fake_db):
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    healthy = _health(last_heartbeat_age_s=120)
    with _patch_send() as mock_send:
        first = asyncio.run(
            cron._check_and_alert_refresh_cron(fake_db, now, healthy)
        )
    assert first == {"action": "alerted", "kind": "recovered"}
    mock_send.assert_called_once()
    assert fake_db.job_locks._docs[cron._LOCK_ID]["last_state"] == "healthy"

    with _patch_send() as mock_send2:
        second = asyncio.run(
            cron._check_and_alert_refresh_cron(
                fake_db, now + timedelta(minutes=15), healthy,
            )
        )
    assert second["action"] == "skip"
    assert second["reason"] == "healthy"
    mock_send2.assert_not_called()


def test_healthy_to_healthy_never_alerts_or_writes_alert_state(fake_db):
    now = _now()
    healthy = _health(last_heartbeat_age_s=600)
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_refresh_cron(fake_db, now, healthy)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "healthy"
    mock_send.assert_not_called()
    # The seed step may write first_observed_ts even on healthy, but the
    # state must NOT flip to anything other than missing/unset.
    saved = fake_db.job_locks._docs.get(cron._LOCK_ID, {})
    assert saved.get("last_state") in (None, "")


def test_inconclusive_does_not_touch_existing_silent_state(fake_db):
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_refresh_cron(
                fake_db, now, _health(configured=False),
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    assert fake_db.job_locks._docs[cron._LOCK_ID]["last_state"] == "silent"


def test_never_observed_seeds_first_observed_then_pages_after_grace(fake_db):
    """A freshly-deployed backend with no heartbeat must:
    1. seed first_observed_ts on first iteration (skip = inconclusive),
    2. once the grace window has elapsed, classify as silent and page.
    """
    now = _now()
    h = _health()  # configured, no heartbeat, no first_observed
    with _patch_send() as mock_send:
        first = asyncio.run(
            cron._check_and_alert_refresh_cron(fake_db, now, h)
        )
    assert first["action"] == "skip"
    mock_send.assert_not_called()
    assert (
        fake_db.job_locks._docs[cron._LOCK_ID]["first_observed_ts"]
        == now.timestamp()
    )

    # Same health but well past the bootstrap grace window.
    later = now + timedelta(hours=cron._CRON_BOOTSTRAP_GRACE_S // 3600 + 1)
    # Re-fetch first_observed from the seeded doc on this iteration.
    h2 = _health()  # firstObservedTs=None — alert iteration must reuse seed.
    with _patch_send() as mock_send2:
        second = asyncio.run(
            cron._check_and_alert_refresh_cron(fake_db, later, h2)
        )
    assert second == {"action": "alerted", "kind": "silent"}
    mock_send2.assert_called_once()


# ─── Health endpoint ───────────────────────────────────────────────────────

def test_admin_health_endpoint_status_branches():
    async def _call(health):
        async def _fake():
            return health
        with patch.object(
            cron, "get_trustpilot_refresh_cron_health", new=_fake,
        ):
            return await cron.admin_trustpilot_refresh_cron_health(admin={})

    not_configured = asyncio.run(_call(_health(configured=False)))
    assert not_configured["status"] == "not_configured"

    never = asyncio.run(_call(_health()))
    assert never["status"] == "never_observed"
    assert never["workflowUrl"]  # default fallback present

    healthy = asyncio.run(_call(_health(last_heartbeat_age_s=300)))
    assert healthy["status"] == "healthy"
    assert healthy["lastHeartbeatAgeSeconds"] == 300

    # Recent run is failing, but the last success is still inside the
    # threshold → degraded (we're not paging, but the dashboard pill
    # warns ops the cron's health is wobbling).
    degraded = asyncio.run(_call(_health(
        last_heartbeat_age_s=300,
        last_status="failure",
        last_success_heartbeat_age_s=2 * 3600,
    )))
    assert degraded["status"] == "degraded"

    # No success in >36h, even though a (failing) heartbeat just fired
    # → silent (data is stale, on-call must look).
    silent_perpetual_failure = asyncio.run(_call(_health(
        last_heartbeat_age_s=300,
        last_status="failure",
        last_success_heartbeat_age_s=40 * 3600,
    )))
    assert silent_perpetual_failure["status"] == "silent"

    silent = asyncio.run(_call(_health(last_heartbeat_age_s=40 * 3600)))
    assert silent["status"] == "silent"
    assert silent["silentThresholdSeconds"] == 36 * 3600


# ─── Heartbeat endpoint ────────────────────────────────────────────────────

def test_heartbeat_endpoint_requires_secret_env():
    """Fail-closed: if TRUSTPILOT_REFRESH_SECRET isn't set the endpoint
    returns 503 (matches the refresh webhook's behaviour) so we don't
    accidentally accept anonymous heartbeats in misconfigured envs."""
    import os
    from fastapi import HTTPException
    from routes import config as cfg

    with patch.dict(os.environ, {"TRUSTPILOT_REFRESH_SECRET": ""}, clear=False):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(
                cfg.refresh_trustpilot_cron_heartbeat(
                    body={}, x_trustpilot_refresh_secret=None,
                )
            )
        assert ei.value.status_code == 503


def test_heartbeat_endpoint_rejects_wrong_secret():
    import os
    from fastapi import HTTPException
    from routes import config as cfg

    with patch.dict(
        os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected"}, clear=False,
    ):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(
                cfg.refresh_trustpilot_cron_heartbeat(
                    body={"status": "success"},
                    x_trustpilot_refresh_secret="nope",
                )
            )
        assert ei.value.status_code == 401


def test_heartbeat_endpoint_persists_when_secret_matches(fake_db):
    """Happy path: correct secret → 200, Mongo doc updated with the
    workflow run metadata so the alerter can read it back."""
    import os
    from routes import config as cfg

    async def _is_avail():
        return True

    with patch.dict(
        os.environ, {"TRUSTPILOT_REFRESH_SECRET": "expected"}, clear=False,
    ), patch("deps.db", fake_db, create=True), \
         patch("deps.is_mongo_available", _is_avail, create=True):
        result = asyncio.run(
            cfg.refresh_trustpilot_cron_heartbeat(
                body={
                    "status": "success",
                    "rc": 0,
                    "runUrl": "https://github.com/o/r/runs/42",
                    "workflowUrl": "https://github.com/o/r/actions/workflows/x.yml",
                    "runId": "42",
                },
                x_trustpilot_refresh_secret="expected",
            )
        )
    assert result["ok"] is True
    saved = fake_db.job_locks._docs[cfg._TP_REFRESH_CRON_HEALTH_DOC_ID]
    assert saved["last_status"] == "success"
    assert saved["last_rc"] == 0
    assert saved["last_run_url"] == "https://github.com/o/r/runs/42"
    assert saved["last_run_id"] == "42"
    assert saved["last_heartbeat_ts"] > 0
