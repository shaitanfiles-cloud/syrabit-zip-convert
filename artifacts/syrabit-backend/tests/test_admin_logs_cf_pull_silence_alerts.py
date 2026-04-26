"""Task #951 — silence alerter for the unified-logs Cloudflare GraphQL
pull (`unified_logs_cf_pull_lock.updated_at`).

Mirrors ``tests/test_admin_cf_waf_drift_cron_alerts.py`` because the
implementation deliberately copies that pattern. Pins:

* classification (silent / healthy / unknown), including the bootstrap
  grace window and the CF-not-configured fail-to-unknown branch;
* the admin pill endpoint reduces the snapshot into a status string
  with ``not_configured`` / ``never_observed`` / ``silent`` /
  ``healthy``;
* first silent detection alerts and persists state;
* silent→silent inside the 24h re-page debounce is suppressed;
* silent→silent past the debounce with the SAME ``last_updated_ts``
  is dedup'd as ``same_run`` (Task #903 sibling);
* silent→silent past the debounce with a NEW ``last_updated_ts``
  re-pages (a fresh successful pull landed in between before silence
  resumed → genuinely new silent episode);
* silent→healthy fires exactly one recovery, then settles;
* healthy→healthy never alerts AND never writes the alert lock doc;
* not_configured never touches state (an env-misconfig deployment
  shouldn't bleed pages while CF env vars are unset);
* never-observed seeds first_observed_ts then pages after the grace
  window elapses;
* the CAS bootstrap path inserts the lock doc on the first detection
  against a brand-new deployment.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from routes import admin_logs_cf_pull_silence_alerts as cron


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
                if k == "$and":
                    if not all(_matches(doc, sub) for sub in v):
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
            self._docs[_id] = doc
            return None
        for k, v in (update.get("$set") or {}).items():
            doc[k] = v
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
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


def _health(*, configured=True, last_updated_age_s=None,
            lease_owner="cf-pull-host-abc",
            cursor="2026-04-26T11:59:00+00:00",
            first_observed_age_s=None):
    """Synthetic health snapshot.

    ``last_updated_age_s=None`` means "the lock doc has no
    ``updated_at`` yet" — i.e. no successful pull has ever run.
    """
    now_ts = _now().timestamp()
    last_ts = (
        now_ts - last_updated_age_s
        if last_updated_age_s is not None else None
    )
    last_iso = (
        datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
        if last_ts is not None else None
    )
    first_obs_ts = (
        now_ts - first_observed_age_s
        if first_observed_age_s is not None else None
    )
    return {
        "configured": configured,
        "lastUpdatedTs": last_ts,
        "lastUpdatedAt": last_iso,
        "lastUpdatedAgeSeconds": last_updated_age_s,
        "leaseOwner": lease_owner,
        "leaseExpiresAt": "2026-04-26T12:01:00+00:00",
        "cursor": cursor,
        "lastAccepted": 5,
        "lastDropped": 0,
        "lastCalls": 1,
        "firstObservedTs": first_obs_ts,
    }


@pytest.fixture
def fake_db():
    return _FakeDb()


def _patch_send():
    return patch.object(cron, "_send_silence_alert", new_callable=AsyncMock)


def _patch_threshold(seconds: int):
    """Pin the silent threshold so tests don't depend on env vars or
    on the live ``CF_PULL_INTERVAL_S`` import path."""
    return patch.object(cron, "_silent_threshold_s", lambda: seconds)


# ─── Classification ─────────────────────────────────────────────────────────

def test_classify_buckets():
    now_ts = _now().timestamp()
    threshold = 600  # 10 min for the tests
    with _patch_threshold(threshold):
        # Not configured → unknown.
        assert cron._classify_cf_pull(
            _health(configured=False), now_ts, None,
        ) == "unknown"
        # Fresh updated_at → healthy.
        assert cron._classify_cf_pull(
            _health(last_updated_age_s=60), now_ts, None,
        ) == "healthy"
        # Last updated past threshold → silent.
        assert cron._classify_cf_pull(
            _health(last_updated_age_s=900), now_ts, None,
        ) == "silent"
        # Never observed, inside bootstrap grace → unknown.
        assert cron._classify_cf_pull(
            _health(), now_ts, now_ts - 300,
        ) == "unknown"
        # Never observed, past bootstrap grace → silent.
        assert cron._classify_cf_pull(
            _health(), now_ts, now_ts - (cron._BOOTSTRAP_GRACE_S + 60),
        ) == "silent"
        # Never observed, no first-observed anchor yet → unknown.
        assert cron._classify_cf_pull(_health(), now_ts, None) == "unknown"


def test_classify_uses_dynamic_threshold():
    """The threshold is read every classification (so an operator can
    bump UNIFIED_LOGS_CF_PULL_SILENT_THRESHOLD_S without restarting
    the API). 60s old + 30s threshold should classify silent; flip
    the threshold to 600s and the same snapshot is healthy."""
    now_ts = _now().timestamp()
    with _patch_threshold(30):
        assert cron._classify_cf_pull(
            _health(last_updated_age_s=60), now_ts, None,
        ) == "silent"
    with _patch_threshold(600):
        assert cron._classify_cf_pull(
            _health(last_updated_age_s=60), now_ts, None,
        ) == "healthy"


# ─── Health endpoint ───────────────────────────────────────────────────────

def test_admin_health_endpoint_status_branches():
    async def _call(health):
        async def _fake():
            return health
        with patch.object(cron, "get_cf_pull_health", new=_fake):
            with _patch_threshold(600):
                return await cron.admin_unified_logs_cf_pull_cron_health(
                    admin={},
                )

    not_configured = asyncio.run(_call(_health(configured=False)))
    assert not_configured["status"] == "not_configured"
    # The status URL is always surfaced so the dashboard tile can link
    # straight to the lock-doc snapshot for an operator triaging.
    assert not_configured["statusUrl"] == "/api/admin/logs/status"

    never = asyncio.run(_call(_health()))
    assert never["status"] == "never_observed"

    healthy = asyncio.run(_call(_health(last_updated_age_s=60)))
    assert healthy["status"] == "healthy"
    assert healthy["lastUpdatedAgeSeconds"] == 60

    silent = asyncio.run(_call(_health(last_updated_age_s=900)))
    assert silent["status"] == "silent"
    assert silent["silentThresholdSeconds"] == 600


# ─── Alert lifecycle ────────────────────────────────────────────────────────

def test_first_silent_detection_alerts_and_persists(fake_db):
    now = _now()
    health = _health(last_updated_age_s=4 * 3600)
    with _patch_threshold(600), _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, now, health)
        )
    assert result == {"action": "alerted", "kind": "silent"}
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[cron._LOCK_ID]
    assert saved["last_state"] == "silent"
    assert saved["last_alert_at"] == now.isoformat()
    assert saved["last_updated_ts"] == health["lastUpdatedTs"]


def test_silent_within_debounce_is_suppressed(fake_db):
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
        "last_updated_ts": _now().timestamp() - 3600,
    }
    health = _health(last_updated_age_s=4 * 3600)
    with _patch_threshold(600), _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, now, health)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "debounced"
    mock_send.assert_not_called()


def test_same_updated_ts_does_not_re_page_after_debounce(fake_db):
    """While the pull is silent, ``lastUpdatedTs`` doesn't change (no
    new successful pull happened). Past the 24h debounce we must NOT
    re-page on the same already-acknowledged silent episode — just
    like the cf-waf-drift alerter dedups on ``last_run_url``."""
    now = _now()
    last_ts = _now().timestamp() - 6 * 3600
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=25)).isoformat(),
        "last_updated_ts": last_ts,
    }
    health = _health(last_updated_age_s=6 * 3600)
    health["lastUpdatedTs"] = last_ts  # pin to the same identity
    with _patch_threshold(600), _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, now, health)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "same_run"
    assert result["last_updated_ts"] == last_ts
    mock_send.assert_not_called()
    # The lock doc was untouched so the "last paged" timestamp on the
    # admin pill keeps pointing at the original page.
    saved = fake_db.job_locks._docs[cron._LOCK_ID]
    assert saved["last_alert_at"] == (
        now - timedelta(hours=25)
    ).isoformat()


def test_new_updated_ts_after_debounce_re_pages(fake_db):
    """If a fresh pull DID land in between (lastUpdatedTs rolled
    forward) and the cursor then went silent again past the 24h
    window, that's a genuinely new silent episode worth paging on."""
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=25)).isoformat(),
        "last_updated_ts": _now().timestamp() - 30 * 3600,
    }
    health = _health(last_updated_age_s=4 * 3600)  # different ts
    with _patch_threshold(600), _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, now, health)
        )
    assert result == {"action": "alerted", "kind": "silent"}
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[cron._LOCK_ID]
    assert saved["last_updated_ts"] == health["lastUpdatedTs"]


def test_silent_to_healthy_fires_recovery_then_settles(fake_db):
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    healthy = _health(last_updated_age_s=60)
    with _patch_threshold(600), _patch_send() as mock_send:
        first = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, now, healthy)
        )
    assert first == {"action": "alerted", "kind": "recovered"}
    mock_send.assert_called_once()
    assert fake_db.job_locks._docs[cron._LOCK_ID]["last_state"] == "healthy"

    # 15 minutes later — but the CF pull is still ticking on schedule,
    # so synthesize a fresh "60s ago" lastUpdatedTs anchored at the
    # later wall-clock moment. Re-using the original snapshot would
    # make age = 16min > threshold and falsely classify as silent
    # (unrelated to the recovery debounce we're trying to pin here).
    later = now + timedelta(minutes=15)
    healthy_later = dict(healthy)
    healthy_later["lastUpdatedTs"] = later.timestamp() - 60
    healthy_later["lastUpdatedAt"] = (
        later - timedelta(seconds=60)
    ).isoformat()
    healthy_later["lastUpdatedAgeSeconds"] = 60
    with _patch_threshold(600), _patch_send() as mock_send2:
        second = asyncio.run(
            cron._check_and_alert_cf_pull_silence(
                fake_db, later, healthy_later,
            )
        )
    assert second["action"] == "skip"
    assert second["reason"] == "healthy"
    mock_send2.assert_not_called()


def test_healthy_to_healthy_never_alerts_or_writes_alert_state(fake_db):
    now = _now()
    healthy = _health(last_updated_age_s=120)
    with _patch_threshold(600), _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, now, healthy)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "healthy"
    mock_send.assert_not_called()
    # The bootstrap seed step may still write first_observed_ts on the
    # alert lock doc, but the state must NOT flip to anything other
    # than missing/unset.
    saved = fake_db.job_locks._docs.get(cron._LOCK_ID, {})
    assert saved.get("last_state") in (None, "")


def test_inconclusive_does_not_touch_existing_silent_state(fake_db):
    now = _now()
    fake_db.job_locks._docs[cron._LOCK_ID] = {
        "_id": cron._LOCK_ID,
        "last_state": "silent",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    with _patch_threshold(600), _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_cf_pull_silence(
                fake_db, now, _health(configured=False),
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    assert (
        fake_db.job_locks._docs[cron._LOCK_ID]["last_state"] == "silent"
    )


def test_never_observed_seeds_first_observed_then_pages_after_grace(fake_db):
    """A freshly-deployed backend whose CF pull hasn't run yet must:
    1. seed first_observed_ts on first iteration (skip = inconclusive),
    2. once the grace window has elapsed, classify as silent and page.
    """
    now = _now()
    h = _health()  # configured, no updated_at, no first_observed
    with _patch_threshold(600), _patch_send() as mock_send:
        first = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, now, h)
        )
    assert first["action"] == "skip"
    mock_send.assert_not_called()
    assert (
        fake_db.job_locks._docs[cron._LOCK_ID]["first_observed_ts"]
        == now.timestamp()
    )

    later = now + timedelta(seconds=cron._BOOTSTRAP_GRACE_S + 60)
    h2 = _health()
    with _patch_threshold(600), _patch_send() as mock_send2:
        second = asyncio.run(
            cron._check_and_alert_cf_pull_silence(fake_db, later, h2)
        )
    assert second == {"action": "alerted", "kind": "silent"}
    mock_send2.assert_called_once()


def test_send_silence_alert_persists_in_app_notification(fake_db):
    """End-to-end on the broken side: ``_send_silence_alert`` must
    persist an in-app admin notification carrying the silent kind +
    the lock-doc snapshot fields the dashboard renders. Patch the
    email and history fan-outs so the test stays focused on the
    notification persist contract.
    """
    now = _now()
    health = _health(last_updated_age_s=4 * 3600)
    captured: dict = {}

    async def _fake_persist(payload):
        captured.update(payload)

    async def _run():
        with patch("db_ops.supa_insert_notification", new=_fake_persist):
            with patch.object(
                cron, "_email_admins_about_silence", new=AsyncMock(),
            ):
                await cron._send_silence_alert(
                    fake_db, "silent", health, now,
                )
                # Background tasks scheduled via asyncio.create_task —
                # yield once so they run in the same loop before the
                # context managers tear the patches back down.
                await asyncio.sleep(0)

    with _patch_threshold(600):
        asyncio.run(_run())
    assert captured["channel"] == "in_app"
    assert captured["audience"] == "admins"
    assert captured["type"] == "error"
    assert "silent" in captured["title"].lower()
    assert captured["meta"]["state"] == "silent"
    assert (
        captured["meta"]["kind"] == "unified_logs_cf_pull_silence_alert"
    )
    assert captured["meta"]["last_updated_ts"] == health["lastUpdatedTs"]


def test_send_recovery_alert_uses_info_level(fake_db):
    """Recovery side: notification level flips to ``info`` and the
    title speaks to the resumed ingest. Patch the fan-outs so the
    test only pins the in-app contract."""
    now = _now()
    healthy = _health(last_updated_age_s=120)
    captured: dict = {}

    async def _fake_persist(payload):
        captured.update(payload)

    async def _run():
        with patch("db_ops.supa_insert_notification", new=_fake_persist):
            with patch.object(
                cron, "_email_admins_about_silence", new=AsyncMock(),
            ):
                await cron._send_silence_alert(
                    fake_db, "recovered", healthy, now,
                )
                await asyncio.sleep(0)

    with _patch_threshold(600):
        asyncio.run(_run())
    assert captured["type"] == "info"
    assert "recovered" in captured["title"].lower()
    assert captured["meta"]["state"] == "recovered"
