"""Task #970 — alerter that pages on-call when one of the three sibling
cron Slack webhook env vars stays unset for >24h after deploy.

Mirrors ``tests/test_admin_logs_cf_pull_silence_alerts.py`` because the
implementation deliberately copies that pattern. Pins:

* classification (``missing`` / ``healthy`` / ``unknown``), including
  the bootstrap grace window;
* first ``missing`` detection alerts and persists state;
* missing→missing inside the 24h re-page debounce is suppressed;
* missing→healthy fires exactly one recovery, then settles;
* healthy→healthy never alerts AND never writes the ``last_state``
  field on the per-env doc (the bootstrap seed step may still write
  ``first_observed_ts``);
* unknown (inside grace) doesn't touch existing missing state;
* per-env state docs are independent — paging on one env doesn't
  bleed into another env's debounce window;
* the in-app notification carries the env name + the missing-for
  duration so on-call can triage without opening Mongo;
* the alerter explicitly does NOT post to Slack (the whole point is
  "Slack is unconfigured" — a Slack POST would silently drop or
  duplicate-page the sibling alerter's channel).
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from routes import admin_slack_webhook_missing_alerts as alerter


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

CF_PULL = alerter.UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK_ENV
CF_WAF = alerter.CF_WAF_DRIFT_SLACK_WEBHOOK_ENV
EDGE_PROXY = alerter.EDGE_PROXY_DEPLOY_SLACK_WEBHOOK_ENV


def _now():
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake_db():
    return _FakeDb()


@pytest.fixture(autouse=True)
def _stable_deploy_id(monkeypatch):
    """Pin a stable deploy id for tests so the deploy-change reseed
    branch in ``_seed_first_observed_if_missing`` only fires when a
    test explicitly opts into a different one. Without this, the
    process-boot fallback would flap on each pytest invocation."""
    monkeypatch.setenv("DEPLOY_ID", "test-deploy-current")
    # Drop any platform-supplied deploy ids so DEPLOY_ID is the
    # winning source per ``_current_deploy_id``'s resolution order.
    for env in (
        "RAILWAY_DEPLOYMENT_ID",
        "RAILWAY_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT",
        "GIT_COMMIT_SHA",
    ):
        monkeypatch.delenv(env, raising=False)


_CURRENT_DEPLOY_ID = "test-deploy-current"


def _patch_send():
    return patch.object(alerter, "_send_alert", new_callable=AsyncMock)


def _clear_envs():
    """Drop the three monitored env vars so classification reads "unset"
    in the test process regardless of what the developer's shell has
    exported. Used as a context manager so the cleanup is deterministic
    even when tests fail mid-body."""
    return patch.dict(
        os.environ,
        {k: "" for k in (CF_PULL, CF_WAF, EDGE_PROXY)},
        clear=False,
    )


def _set_env(env_name: str, value: str):
    return patch.dict(os.environ, {env_name: value}, clear=False)


# ─── Classification ─────────────────────────────────────────────────────────

def test_classify_buckets():
    now_ts = _now().timestamp()
    with _clear_envs():
        # Env unset, first observation seeded but inside the grace
        # window → unknown (don't page during the operator's grace
        # period).
        assert alerter._classify_env(
            CF_PULL, now_ts, now_ts - 60,
        ) == "unknown"
        # Env unset, no first-observed anchor yet → unknown (we
        # haven't even seeded the deploy time, so we can't tell
        # whether the operator has had time to react).
        assert alerter._classify_env(CF_PULL, now_ts, None) == "unknown"
        # Env unset and grace window has elapsed → missing (the
        # operator had a full 24h and didn't set the secret).
        assert alerter._classify_env(
            CF_PULL, now_ts, now_ts - (alerter._BOOTSTRAP_GRACE_S + 60),
        ) == "missing"
    # Env set → healthy regardless of grace window (the recovery
    # path needs to flip from missing→healthy as soon as the secret
    # lands, even mid-grace, so a bouncing deploy doesn't get a
    # spurious page once the operator finally lands the value).
    with _set_env(CF_PULL, "https://hooks.slack.test/abc"):
        assert alerter._classify_env(CF_PULL, now_ts, None) == "healthy"
        assert alerter._classify_env(
            CF_PULL, now_ts, now_ts - (alerter._BOOTSTRAP_GRACE_S + 60),
        ) == "healthy"


def test_classify_treats_whitespace_as_unset():
    """Whitespace-only env values are not a real Slack URL — a broken
    secret-manager render that emits ``"  "`` would otherwise make the
    alerter (and the AdminHealth ``slackConfigured`` badge) claim
    Slack was wired even though every POST would 400. Mirrors the
    contract in :mod:`routes.slack_alerter_config`."""
    now_ts = _now().timestamp()
    with _set_env(CF_PULL, "   "):
        assert alerter._classify_env(
            CF_PULL, now_ts, now_ts - (alerter._BOOTSTRAP_GRACE_S + 60),
        ) == "missing"


# ─── Alert lifecycle ────────────────────────────────────────────────────────

def test_first_missing_detection_alerts_and_persists(fake_db):
    """A fresh deployment whose env has been unset since boot and is
    now past the bootstrap grace window must page once and persist
    ``last_state="missing"`` so the next tick can debounce."""
    now = _now()
    # Pre-seed first_observed_ts past the grace window so the
    # classifier returns missing on the first iteration.
    fake_db.job_locks._docs[alerter._lock_id_for(CF_PULL)] = {
        "_id": alerter._lock_id_for(CF_PULL),
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
    }
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert result == {
        "action": "alerted", "kind": "missing", "env_name": CF_PULL,
    }
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[alerter._lock_id_for(CF_PULL)]
    assert saved["last_state"] == "missing"
    assert saved["last_alert_at"] == now.isoformat()
    assert saved["env_name"] == CF_PULL


def test_missing_within_debounce_is_suppressed(fake_db):
    """Inside the 24h re-page window we must NOT re-page on the same
    already-acknowledged missing env."""
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "debounced"
    mock_send.assert_not_called()


def test_missing_past_debounce_re_pages(fake_db):
    """Past the 24h debounce we must re-page on the still-missing env
    (the operator has had two days now and STILL hasn't set the
    secret — keep nagging until they do)."""
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 25 * 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=25)).isoformat(),
    }
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert result == {
        "action": "alerted", "kind": "missing", "env_name": CF_PULL,
    }
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[lock_id]
    assert saved["last_alert_at"] == now.isoformat()


def test_missing_to_healthy_fires_recovery_then_settles(fake_db):
    """Missing → healthy fires exactly one recovery alert, then a
    subsequent healthy tick must NOT re-fire."""
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    with _set_env(CF_PULL, "https://hooks.slack.test/recovered"), \
            _patch_send() as mock_send:
        first = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert first == {
        "action": "alerted", "kind": "recovered", "env_name": CF_PULL,
    }
    mock_send.assert_called_once()
    assert fake_db.job_locks._docs[lock_id]["last_state"] == "healthy"

    later = now + timedelta(minutes=15)
    with _set_env(CF_PULL, "https://hooks.slack.test/recovered"), \
            _patch_send() as mock_send2:
        second = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, later)
        )
    assert second["action"] == "skip"
    assert second["reason"] == "healthy"
    mock_send2.assert_not_called()


def test_healthy_to_healthy_never_alerts_or_writes_alert_state(fake_db):
    """A deployment whose env has been set since boot must never page
    AND must not write ``last_state`` on the per-env doc (the
    bootstrap seed step may still write ``first_observed_ts``)."""
    now = _now()
    with _set_env(CF_PULL, "https://hooks.slack.test/abc"), \
            _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "healthy"
    mock_send.assert_not_called()
    saved = fake_db.job_locks._docs.get(alerter._lock_id_for(CF_PULL), {})
    assert saved.get("last_state") in (None, "")


def test_inconclusive_in_grace_window_does_not_touch_existing_state(fake_db):
    """Inside the bootstrap grace window we must classify as
    ``unknown`` and leave any existing state alone (a previous
    deployment's missing state must not get cleared just because the
    new boot hasn't elapsed grace yet)."""
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    # Pre-existing missing state from an earlier deployment.
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": now.timestamp() - 60,  # inside grace
        "deploy_id": _CURRENT_DEPLOY_ID,
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    assert fake_db.job_locks._docs[lock_id]["last_state"] == "missing"


def test_seeds_first_observed_ts_on_first_iteration(fake_db):
    """The very first iteration against a fresh deployment must seed
    ``first_observed_ts`` so the bootstrap grace window has a
    defined start — without it, a long-running unset env would
    indefinitely classify as ``unknown``."""
    now = _now()
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    # Inside grace (we just seeded "now") → unknown / inconclusive.
    assert result["action"] == "skip"
    mock_send.assert_not_called()
    saved = fake_db.job_locks._docs[alerter._lock_id_for(CF_PULL)]
    assert saved["first_observed_ts"] == now.timestamp()
    assert saved["env_name"] == CF_PULL


def test_per_env_docs_are_independent(fake_db):
    """Pinning one env's debounce window must not bleed into another
    env's iteration — each env owns its own state doc."""
    now = _now()
    cf_pull_lock = alerter._lock_id_for(CF_PULL)
    cf_waf_lock = alerter._lock_id_for(CF_WAF)
    # cf-pull is mid-debounce.
    fake_db.job_locks._docs[cf_pull_lock] = {
        "_id": cf_pull_lock,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    # cf-waf has never been seen — past grace from a prior boot.
    fake_db.job_locks._docs[cf_waf_lock] = {
        "_id": cf_waf_lock,
        "env_name": CF_WAF,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
    }
    with _clear_envs(), _patch_send() as mock_send:
        cf_pull_report = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
        cf_waf_report = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_WAF, now)
        )
    assert cf_pull_report["reason"] == "debounced"
    assert cf_waf_report["action"] == "alerted"
    assert cf_waf_report["env_name"] == CF_WAF
    # _send_alert called once total — only for the cf-waf branch.
    assert mock_send.call_count == 1


def test_check_and_alert_all_envs_iterates_all_three(fake_db):
    """The aggregate iterator must hit all three env vars in
    deterministic order so the loop / tests can pin behaviour."""
    now = _now()
    with _clear_envs(), _patch_send():
        reports = asyncio.run(
            alerter._check_and_alert_all_envs(fake_db, now)
        )
    env_names = [r["env_name"] for r in reports]
    assert env_names == [CF_PULL, CF_WAF, EDGE_PROXY]


# ─── Deploy-scoped grace-window anchor (Task #970 code-review fix) ─────────

def test_grace_window_resets_when_deploy_id_changes(fake_db):
    """The blocking gap from the Task #970 code review.

    A long-running cluster has been up for weeks with the env set,
    so the per-env doc has an ancient ``first_observed_ts``. An
    operator then ships a new deploy that accidentally drops the
    Slack webhook env. Without the deploy-anchor reset, the alerter
    would page IMMEDIATELY on the first iteration after rollout
    because the persisted anchor is already weeks past the 24h
    grace window — violating the task's "unset for >24h *after
    deploy*" requirement and waking on-call for a config change
    they can still fix within the deploy's 24h grace.

    With the deploy-anchor reset, the seeder sees the doc's
    ``deploy_id`` differs from the current process's deploy id,
    overwrites ``first_observed_ts`` with ``now``, and the
    classifier correctly returns ``unknown`` (no page) until 24h
    has elapsed under the new deploy.
    """
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    # Pre-existing doc from a deploy that ran weeks ago. Env was
    # presumably set back then (no last_state="missing"); now the
    # operator has rolled out a new image that dropped the webhook.
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (14 * 24 * 3600)  # 2 weeks ago
        ),
        "deploy_id": "test-deploy-OLD",
    }
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    # MUST NOT page — the new deploy gets a fresh 24h grace window.
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    saved = fake_db.job_locks._docs[lock_id]
    # first_observed_ts was reseeded to "now" (within a small
    # tolerance for the seeder running slightly after _now() was
    # captured).
    assert saved["first_observed_ts"] == now.timestamp()
    assert saved["deploy_id"] == _CURRENT_DEPLOY_ID
    assert "deploy_id_seeded_at" in saved


def test_deploy_change_preserves_prior_missing_state_for_recovery(fake_db):
    """A redeploy that fixes a previously-missing env must still
    fire the missing→healthy recovery alert. Reseeding
    ``first_observed_ts`` on deploy change is correct, but blowing
    away ``last_state`` would silently swallow the "good job, you
    fixed it" recovery signal — so this test pins that the
    seeder leaves prior alert-state fields alone.
    """
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (14 * 24 * 3600)
        ),
        "deploy_id": "test-deploy-OLD",
        # Prior deploy paged us about the missing env.
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    # New deploy ships WITH the env set — recovery should fire.
    with _set_env(CF_PULL, "https://hooks.slack.test/now-fixed"), \
            _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert result == {
        "action": "alerted", "kind": "recovered", "env_name": CF_PULL,
    }
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[lock_id]
    assert saved["last_state"] == "healthy"
    # Anchor was reseeded for the new deploy.
    assert saved["deploy_id"] == _CURRENT_DEPLOY_ID
    assert saved["first_observed_ts"] == now.timestamp()


def test_same_deploy_id_preserves_first_observed_ts(fake_db):
    """Across multiple iterations of the SAME deploy, the seeder
    must NOT clobber ``first_observed_ts`` — otherwise the grace
    window would reset on every loop tick and the alerter would
    never reach the "missing" classification, defeating the whole
    purpose of the alerter."""
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    original_anchor = now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": original_anchor,
        "deploy_id": _CURRENT_DEPLOY_ID,
    }
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    # Past grace under the same deploy → page.
    assert result["action"] == "alerted"
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[lock_id]
    # Original anchor preserved (NOT reseeded to "now").
    assert saved["first_observed_ts"] == original_anchor
    assert saved["deploy_id"] == _CURRENT_DEPLOY_ID


def test_legacy_doc_without_deploy_id_is_treated_as_old_deploy(fake_db):
    """Docs written by a pre-fix version of this alerter have no
    ``deploy_id`` field. The seeder must treat "no stored deploy id"
    as "deploy changed" so legacy docs get reseeded on the first
    iteration after the fix ships — without this, the bug the code
    review identified would persist for legacy state docs even after
    the fix is deployed.
    """
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        # Ancient anchor, NO deploy_id field at all.
        "first_observed_ts": now.timestamp() - (14 * 24 * 3600),
    }
    with _clear_envs(), _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    saved = fake_db.job_locks._docs[lock_id]
    assert saved["first_observed_ts"] == now.timestamp()
    assert saved["deploy_id"] == _CURRENT_DEPLOY_ID


def test_lease_ttl_is_capped_for_24h_loop_cadence():
    """A daily (24h) loop cadence with the sibling alerters' raw
    ``max(900, _LOOP_SLEEP_S * 3)`` formula would request a 72h
    lease — meaning a leader that crashes right after acquiring the
    lease would block any other replica from running this alerter
    for nearly three days. That's exactly the silent-failure mode
    this alerter is meant to catch elsewhere, so we cap at
    ``_LEASE_TTL_CEILING_S`` (1h default). This test pins the cap
    so a future copy-paste from a sibling can't silently re-
    introduce the 3-day failover hole.
    """
    # The constant lives at module scope so loop config is auditable.
    assert hasattr(alerter, "_LEASE_TTL_CEILING_S")
    assert alerter._LEASE_TTL_CEILING_S == 3600
    # Source-level pin: the lease formula must use the cap, not
    # the raw sibling formula. Reading the source is the
    # cheapest way to assert this without spinning up a real
    # background_lease module + Mongo.
    import inspect
    src = inspect.getsource(alerter._slack_webhook_missing_alert_loop)
    assert "_LEASE_TTL_CEILING_S" in src, (
        "lease TTL must be capped via _LEASE_TTL_CEILING_S to "
        "avoid multi-day failover holes on this 24h cadence loop"
    )
    # And the actual computed value with default tunables must
    # collapse to the cap, not the 72h the raw formula would yield.
    computed = max(
        900,
        min(alerter._LEASE_TTL_CEILING_S, alerter._LOOP_SLEEP_S * 3),
    )
    assert computed == 3600
    assert computed < 24 * 3600, (
        "lease TTL must be shorter than the loop cadence so a "
        "dead leader can be replaced within one cadence"
    )


def test_current_deploy_id_resolution_order(monkeypatch):
    """``_current_deploy_id`` must prefer the most-specific platform
    signal so a Railway redeploy that bumps only RAILWAY_DEPLOYMENT_ID
    (e.g. an env-only change with no commit change) still resets the
    grace window."""
    # Most-specific wins.
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "rdid-1")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "sha-1")
    monkeypatch.setenv("DEPLOY_ID", "manual-1")
    assert alerter._current_deploy_id() == "rdid-1"
    # Falls through whitespace-only to the next level.
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "   ")
    assert alerter._current_deploy_id() == "sha-1"
    # All platform vars absent → manual override wins.
    monkeypatch.delenv("RAILWAY_DEPLOYMENT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    assert alerter._current_deploy_id() == "manual-1"
    # Nothing set at all → process-boot fallback.
    monkeypatch.delenv("DEPLOY_ID", raising=False)
    fallback = alerter._current_deploy_id()
    assert fallback.startswith("process-boot-")


# ─── Notification body contract ─────────────────────────────────────────────

def test_send_alert_persists_in_app_notification(fake_db):
    """End-to-end on the broken side: ``_send_alert`` must persist an
    in-app admin notification carrying the env name + the missing-for
    duration so on-call can triage without opening Mongo. Patch the
    email fan-out so the test stays focused on the persist contract.
    """
    now = _now()
    first_obs = now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
    captured: dict = {}

    async def _fake_persist(payload):
        captured.update(payload)

    async def _run():
        with patch("db_ops.supa_insert_notification", new=_fake_persist), \
                patch.object(
                    alerter, "_email_admins_about_missing", new=AsyncMock(),
                ):
            await alerter._send_alert(
                fake_db, CF_PULL, "missing", now,
                first_observed_ts=first_obs,
            )
            # Background tasks scheduled via asyncio.create_task —
            # yield once so they run in the same loop before the
            # context managers tear the patches back down.
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert captured["channel"] == "in_app"
    assert captured["audience"] == "admins"
    assert captured["type"] == "error"
    assert CF_PULL in captured["title"]
    assert captured["meta"]["state"] == "missing"
    assert captured["meta"]["env_name"] == CF_PULL
    assert captured["meta"]["kind"] == "slack_webhook_missing_alert"
    # Body mentions the env name + the human label so on-call knows
    # which alerter is disabled by the unset env.
    assert CF_PULL in captured["message"]
    assert "Task #951" in captured["message"]


def test_send_alert_recovery_uses_info_type(fake_db):
    now = _now()
    captured: dict = {}

    async def _fake_persist(payload):
        captured.update(payload)

    async def _run():
        with patch("db_ops.supa_insert_notification", new=_fake_persist), \
                patch.object(
                    alerter, "_email_admins_about_missing", new=AsyncMock(),
                ):
            await alerter._send_alert(
                fake_db, EDGE_PROXY, "recovered", now,
            )
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert captured["type"] == "info"
    assert "restored" in captured["title"].lower()
    assert EDGE_PROXY in captured["title"]


# ─── Task #974 — record_cron_alert_event wired into _send_alert ───────────

def test_send_alert_records_history_event_on_missing(fake_db):
    """``_send_alert`` must schedule a ``record_cron_alert_event`` call
    so the new ``/admin/health/slack-webhook-missing/<env>/alert-history``
    endpoint can render this page next to the affected pill. The
    persisted event must carry the per-env ``lock_id`` (so the
    default one-pill-one-history view scopes correctly without any
    client-side filtering), ``kind="missing"``, ``sub_kind=env_name``
    (so a combined audit query can disambiguate which webhook the
    page was about) and a small health payload with the env name +
    missing-for duration.
    """
    now = _now()
    first_obs = now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 7200)
    captured: dict = {}

    async def _fake_record(_db, *, lock_id, kind, sub_kind, health, now_utc):
        captured.update({
            "lock_id": lock_id,
            "kind": kind,
            "sub_kind": sub_kind,
            "health": health,
            "now_utc": now_utc,
        })

    async def _run():
        with patch("db_ops.supa_insert_notification", new=AsyncMock()), \
                patch.object(
                    alerter, "_email_admins_about_missing", new=AsyncMock(),
                ), \
                patch(
                    "routes.admin_health.record_cron_alert_event",
                    new=_fake_record,
                ):
            await alerter._send_alert(
                fake_db, CF_PULL, "missing", now,
                first_observed_ts=first_obs,
            )
            # Yield once so the asyncio.create_task scheduled inside
            # _send_alert (record_cron_alert_event is fire-and-forget
            # mirroring the email fan-out) actually runs in the same
            # loop before we tear the patches down.
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert captured["lock_id"] == alerter._lock_id_for(CF_PULL)
    assert captured["kind"] == "missing"
    assert captured["sub_kind"] == CF_PULL
    assert captured["now_utc"] == now
    assert captured["health"]["envName"] == CF_PULL
    # Human label so an admin reading the audit log doesn't have to
    # cross-reference env-var name → which alerter it disables.
    assert "envLabel" in captured["health"]
    # Missing-for surface so the audit row carries enough context to
    # triage without re-reading the lock doc.
    assert captured["health"]["firstObservedTs"] == first_obs
    assert captured["health"]["missingForSeconds"] >= (
        alerter._BOOTSTRAP_GRACE_S + 7200 - 1
    )


def test_send_alert_records_history_event_on_recovery(fake_db):
    """The recovery side must also append an event so the audit log
    shows the missing → recovered transition (otherwise admins would
    only see the page-on side and never know when the env was
    finally set, defeating the audit log's "what happened" use)."""
    now = _now()
    captured: dict = {}

    async def _fake_record(_db, *, lock_id, kind, sub_kind, health, now_utc):
        captured.update({
            "lock_id": lock_id, "kind": kind,
            "sub_kind": sub_kind, "health": health,
        })

    async def _run():
        with patch("db_ops.supa_insert_notification", new=AsyncMock()), \
                patch.object(
                    alerter, "_email_admins_about_missing", new=AsyncMock(),
                ), \
                patch(
                    "routes.admin_health.record_cron_alert_event",
                    new=_fake_record,
                ):
            await alerter._send_alert(
                fake_db, EDGE_PROXY, "recovered", now,
            )
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert captured["lock_id"] == alerter._lock_id_for(EDGE_PROXY)
    assert captured["kind"] == "recovered"
    assert captured["sub_kind"] == EDGE_PROXY
    # The recovered side has no first_observed_ts so the health
    # payload omits ``firstObservedTs`` / ``missingForSeconds`` — but
    # must still carry the env name so the audit row has scope.
    assert captured["health"]["envName"] == EDGE_PROXY
    assert "firstObservedTs" not in captured["health"]
    assert "missingForSeconds" not in captured["health"]


def test_send_alert_history_record_failure_does_not_break_alert(fake_db):
    """A Mongo blip on the audit-log persist side must NOT undo the
    in-app notification or kill the alert iteration. Mirrors the
    ``except Exception`` guard already wrapping the call site
    (a slow Mongo can't be allowed to stall the alert loop)."""
    now = _now()
    persisted: dict = {}

    async def _fake_persist(payload):
        persisted.update(payload)

    def _broken_record(*_a, **_kw):
        raise RuntimeError("mongo down")

    async def _run():
        with patch("db_ops.supa_insert_notification", new=_fake_persist), \
                patch.object(
                    alerter, "_email_admins_about_missing", new=AsyncMock(),
                ), \
                patch(
                    "routes.admin_health.record_cron_alert_event",
                    new=_broken_record,
                ):
            # Should not raise even though the helper call blows up.
            await alerter._send_alert(
                fake_db, CF_WAF, "missing", now,
                first_observed_ts=now.timestamp() - (
                    alerter._BOOTSTRAP_GRACE_S + 60
                ),
            )
            await asyncio.sleep(0)

    asyncio.run(_run())
    # The in-app notification must still have landed — the audit log
    # is best-effort decoration, not a precondition.
    assert persisted["meta"]["env_name"] == CF_WAF


# ─── Task #974 — admin-readable surfaces (alert-state + alert-history) ────

@pytest.fixture
def http_client_authed():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user
    app = FastAPI()
    app.include_router(alerter.router)
    app.dependency_overrides = {
        get_admin_user: lambda: {
            "id": "admin-1", "email": "ops@syrabit.ai",
            "is_admin": True, "sub": "admin-1",
        },
    }
    return TestClient(app)


@pytest.fixture
def http_client_no_auth():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from auth_deps import get_admin_user
    app = FastAPI()
    app.include_router(alerter.router)

    def _deny():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides = {get_admin_user: _deny}
    return TestClient(app)


class _RouteFakeJobLocks:
    def __init__(self, doc=None):
        self._doc = doc

    async def find_one(self, query, projection=None, sort=None):
        if not self._doc:
            return None
        if "_id" in query and self._doc.get("_id") != query["_id"]:
            return None
        return dict(self._doc)

    async def update_one(self, query, update, upsert=False):
        """Task #980 — minimal upsert path so the snooze POST endpoint
        can persist ``snoozed_*`` fields against a per-env lock doc
        the route fixture didn't pre-seed. Mirrors the shape the real
        Motor collection returns (``None``-ish; we ignore the result
        in the route handler, just like the alerter loop does)."""
        _id = (query or {}).get("_id")
        if self._doc is None:
            if not upsert:
                return None
            self._doc = {"_id": _id}
            self._doc.update(update.get("$setOnInsert", {}))
            self._doc.update(update.get("$set", {}))
            return None
        if "_id" in query and self._doc.get("_id") != _id:
            return None
        for k, v in (update.get("$set") or {}).items():
            self._doc[k] = v
        return None


class _RouteFakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._docs = self._docs[: int(n)]
        return self

    async def to_list(self, length=None):
        cap = length if length is not None else len(self._docs)
        return list(self._docs)[: int(cap)]


class _RouteFakeHistory:
    """Honors the ``lock_id`` filter in the find query — the route
    relies on per-lock-id scoping to keep one env's audit log out
    of another's history view, so the fake must enforce that
    rather than returning everything (which would hide a regression
    where the helper widened the lookup)."""

    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, query, *_a, **_kw):
        scoped_lock_id = (query or {}).get("lock_id") if query else None
        if scoped_lock_id is None:
            return _RouteFakeCursor(self._docs)
        return _RouteFakeCursor(
            [d for d in self._docs if d.get("lock_id") == scoped_lock_id]
        )


class _RouteFakeDb:
    def __init__(self, lock_doc=None, history_docs=None):
        self.job_locks = _RouteFakeJobLocks(lock_doc)
        self._history_docs = list(history_docs or [])

    def __getitem__(self, name):
        if name == "cron_alert_history":
            return _RouteFakeHistory(self._history_docs)
        raise KeyError(name)


def _patch_route_mongo(*, lock_doc=None, history_docs=None, available=True):
    import deps
    return patch.multiple(
        deps,
        db=_RouteFakeDb(lock_doc, history_docs),
        is_mongo_available=AsyncMock(return_value=bool(available)),
    )


def test_alert_state_endpoint_requires_admin_auth(http_client_no_auth):
    res = http_client_no_auth.get(
        f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-state",
    )
    assert res.status_code in (401, 403)


def test_alert_state_endpoint_rejects_unknown_env(http_client_authed):
    """Unknown env names must 404 — the lock-doc id is templated from
    the path param so without this guard a caller could probe Mongo
    for any ``slack_webhook_missing_alert_state__*`` doc and leak a
    side channel for "is this env name something we monitor"."""
    res = http_client_authed.get(
        "/admin/health/slack-webhook-missing/NOT_A_REAL_ENV/alert-state",
    )
    assert res.status_code == 404


def test_alert_state_endpoint_returns_present_false_when_no_doc(
    http_client_authed,
):
    """No lock doc yet (alerter has never fired) → 200 with
    ``present: false`` so the dashboard renders the pre-Task #974
    badge shape rather than erroring out."""
    with _patch_route_mongo(lock_doc=None):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-state",
        )
    assert res.status_code == 200
    body = res.json()
    assert body["present"] is False
    assert body["lastAlertAt"] is None
    assert body["lastAlertAgeSeconds"] is None
    assert body["inDebounce"] is False
    assert body["realertIntervalSeconds"] == int(
        alerter._REALERT_INTERVAL_S
    )


def test_alert_state_endpoint_surfaces_missing_state_with_debounce(
    http_client_authed,
):
    """A populated lock doc with ``last_state="missing"`` inside the
    24h re-page debounce must surface ``inDebounce: true`` so the
    badge can render the "next nag in Yh" tooltip suffix. The
    ``broken_state_label="missing"`` argument on the route is what
    distinguishes this alerter from the cf-waf-drift / cf-pull
    siblings (which write ``last_state="silent"``)."""
    lock_id = alerter._lock_id_for(CF_PULL)
    paged_at = datetime.now(timezone.utc) - timedelta(hours=2)
    lock_doc = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "last_state": "missing",
        "last_alert_at": paged_at.isoformat(),
        "first_observed_ts": (
            datetime.now(timezone.utc) - timedelta(hours=72)
        ).timestamp(),
    }
    with _patch_route_mongo(lock_doc=lock_doc):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-state",
        )
    assert res.status_code == 200
    body = res.json()
    assert body["present"] is True
    assert body["lastState"] == "missing"
    assert body["envName"] == CF_PULL
    # ~2h ago, comfortably inside the 24h debounce window.
    assert body["lastAlertAgeSeconds"] is not None
    assert 6900 < body["lastAlertAgeSeconds"] < 7500
    assert body["inDebounce"] is True
    assert body["debounceRemainingSeconds"] is not None
    assert body["debounceRemainingSeconds"] > 0


def test_alert_state_endpoint_recovered_state_clears_debounce(
    http_client_authed,
):
    """After recovery (``last_state="healthy"``) the doc is still
    "present" but the badge's "next nag in Yh" suffix must be off —
    the alerter has stopped paging on this env, so a stale "in
    debounce" caption would be actively misleading."""
    lock_id = alerter._lock_id_for(EDGE_PROXY)
    paged_at = datetime.now(timezone.utc) - timedelta(hours=1)
    lock_doc = {
        "_id": lock_id,
        "env_name": EDGE_PROXY,
        "last_state": "healthy",
        "last_alert_at": paged_at.isoformat(),
    }
    with _patch_route_mongo(lock_doc=lock_doc):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{EDGE_PROXY}"
            "/alert-state",
        )
    assert res.status_code == 200
    body = res.json()
    assert body["present"] is True
    assert body["lastState"] == "healthy"
    assert body["inDebounce"] is False
    assert body["debounceRemainingSeconds"] is None


def test_alert_state_endpoint_isolates_per_env_lock_docs(
    http_client_authed,
):
    """A lock doc for env A must not bleed into env B's response —
    the per-env state contract is the whole point of templating
    ``_lock_id_for(env_name)`` into the lookup."""
    lock_id_for_cf_pull = alerter._lock_id_for(CF_PULL)
    only_cf_pull_doc = {
        "_id": lock_id_for_cf_pull,
        "env_name": CF_PULL,
        "last_state": "missing",
        "last_alert_at": datetime.now(timezone.utc).isoformat(),
    }
    with _patch_route_mongo(lock_doc=only_cf_pull_doc):
        # Asking for the CF_WAF env must NOT pick up the cf-pull
        # doc (the fake's _id check guards this; the test pins the
        # contract so a future helper change can't silently widen
        # the lookup).
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{CF_WAF}/alert-state",
        )
    assert res.status_code == 200
    assert res.json()["present"] is False


def test_alert_history_endpoint_requires_admin_auth(http_client_no_auth):
    res = http_client_no_auth.get(
        f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-history",
    )
    assert res.status_code in (401, 403)


def test_alert_history_endpoint_rejects_unknown_env(http_client_authed):
    res = http_client_authed.get(
        "/admin/health/slack-webhook-missing/NOT_A_REAL_ENV/alert-history",
    )
    assert res.status_code == 404


def test_alert_history_endpoint_returns_empty_when_no_events(
    http_client_authed,
):
    with _patch_route_mongo(history_docs=[]):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-history",
        )
    assert res.status_code == 200
    body = res.json()
    assert body["events"] == []


def test_alert_history_endpoint_isolates_per_env_lock_ids(
    http_client_authed,
):
    """A combined ``cron_alert_history`` collection (events for ALL
    three webhook envs interleaved) must be filtered down to the
    requested env's own lock-id when the per-env endpoint is hit —
    otherwise an admin reading the cf-pull pill's history would
    see edge-proxy / cf-waf pages mixed in. The route relies on
    ``lock_id``-scoped find queries; this test pins that contract."""
    cf_pull_lock_id = alerter._lock_id_for(CF_PULL)
    edge_proxy_lock_id = alerter._lock_id_for(EDGE_PROXY)
    paged_at = datetime.now(timezone.utc) - timedelta(hours=4)
    history_docs = [
        {
            "_id": "evt-cfpull",
            "lock_id": cf_pull_lock_id,
            "kind": "missing",
            "sub_kind": CF_PULL,
            "paged_at": paged_at.isoformat(),
            "created_at": paged_at,
        },
        {
            "_id": "evt-edge",
            "lock_id": edge_proxy_lock_id,
            "kind": "missing",
            "sub_kind": EDGE_PROXY,
            "paged_at": paged_at.isoformat(),
            "created_at": paged_at,
        },
    ]
    with _patch_route_mongo(history_docs=history_docs):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-history",
        )
    assert res.status_code == 200
    body = res.json()
    # Only the cf-pull event must come back — the edge-proxy event
    # belongs to a different pill's history view.
    assert len(body["events"]) == 1
    assert body["events"][0]["subKind"] == CF_PULL


def test_alert_history_endpoint_returns_recorded_events(
    http_client_authed,
):
    """A populated ``cron_alert_history`` collection must surface
    its events on the per-env endpoint, scoped via ``lock_id`` to
    the env's own lock-doc id (so cross-env events on the same
    deployment don't bleed into one another's history view)."""
    lock_id = alerter._lock_id_for(EDGE_PROXY)
    paged_at = datetime.now(timezone.utc) - timedelta(hours=3)
    history_docs = [
        {
            "_id": "evt-1",
            "lock_id": lock_id,
            "kind": "missing",
            "sub_kind": EDGE_PROXY,
            "paged_at": paged_at.isoformat(),
            "created_at": paged_at,
        },
    ]
    with _patch_route_mongo(history_docs=history_docs):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{EDGE_PROXY}"
            "/alert-history",
        )
    assert res.status_code == 200
    body = res.json()
    assert len(body["events"]) == 1
    evt = body["events"][0]
    assert evt["kind"] == "missing"
    assert evt["subKind"] == EDGE_PROXY


# ─── Slack-fan-out contract: this alerter explicitly does NOT post ─────────

def test_alerter_module_does_not_post_to_slack():
    """The module must not import ``httpx`` at top level and must not
    expose a ``_post_slack_*`` helper. The whole point of the alerter
    is "Slack is broken / unconfigured" — fanning out to Slack would
    either silently drop into the void or duplicate-page the sibling
    alerter's channel. Pinned with a direct attribute scan so a
    future copy-paste from a sibling alerter can't accidentally
    re-introduce a Slack post path without a corresponding test
    being added that justifies it.
    """
    public_attrs = [n for n in dir(alerter) if "slack" in n.lower()]
    # The only Slack-related helpers we should be using are the
    # config helpers (env-name constants + ``slack_webhook_url_for``)
    # we import from :mod:`routes.slack_alerter_config` to read the
    # env, never to post.
    forbidden = [n for n in public_attrs if "post" in n.lower()]
    assert forbidden == [], (
        f"slack-webhook-missing alerter must not expose Slack POST "
        f"helpers; found: {forbidden}"
    )


# ─── Task #980 — admin snooze affordance ───────────────────────────────────

def test_snooze_remaining_seconds_helper_handles_missing_blank_and_corrupt():
    """Pure unit test pinning the gate's "no snooze on file" semantics.

    The gate inside ``_check_and_alert_one_env`` and the derived
    ``snoozeRemainingSeconds`` field on ``/alert-state`` both delegate
    to this helper; if it lies about an unset doc, the dashboard
    starts rendering "snoozed for 0s" forever and the alerter starts
    silencing pages it should be sending.
    """
    now = _now()
    assert alerter._snooze_remaining_seconds({}, now) == 0
    assert alerter._snooze_remaining_seconds({"snoozed_until": ""}, now) == 0
    assert alerter._snooze_remaining_seconds(
        {"snoozed_until": "not-an-iso-timestamp"}, now,
    ) == 0
    # Past timestamp (already expired) → 0, NOT a negative number.
    expired = (now - timedelta(hours=2)).isoformat()
    assert alerter._snooze_remaining_seconds(
        {"snoozed_until": expired}, now,
    ) == 0
    # Future timestamp → positive seconds remaining, clamped to int.
    future = (now + timedelta(hours=24)).isoformat()
    remaining = alerter._snooze_remaining_seconds(
        {"snoozed_until": future}, now,
    )
    assert 24 * 3600 - 2 <= remaining <= 24 * 3600 + 2
    # Trailing-Z (Mongo BSON sometimes emits this) parses cleanly.
    z_form = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    z_remaining = alerter._snooze_remaining_seconds(
        {"snoozed_until": z_form}, now,
    )
    assert 3600 - 2 <= z_remaining <= 3600 + 2


def test_clamp_snooze_hours_accepts_bounds_and_rejects_garbage():
    """Both the floor and ceiling must be inclusive — the dashboard's
    "Snooze 7d" button POSTs 168 (the ceiling) and a hand-crafted
    1h request must succeed on the floor. Booleans must be rejected
    explicitly (``True`` / ``False`` pass ``isinstance(_, int)`` in
    Python and would otherwise be coerced into a 1h or 0h snooze)."""
    from fastapi import HTTPException
    assert alerter._clamp_snooze_hours(alerter._SNOOZE_MIN_HOURS) == (
        alerter._SNOOZE_MIN_HOURS
    )
    assert alerter._clamp_snooze_hours(alerter._SNOOZE_MAX_HOURS) == (
        alerter._SNOOZE_MAX_HOURS
    )
    for bad in (
        0, -1, alerter._SNOOZE_MAX_HOURS + 1, "168", 168.0,
        None, True, False,
    ):
        with pytest.raises(HTTPException) as exc_info:
            alerter._clamp_snooze_hours(bad)
        assert exc_info.value.status_code == 400


def test_missing_branch_short_circuits_when_snooze_active(fake_db):
    """The whole point of the snooze: with the env unset and the
    grace window elapsed, ``_check_and_alert_one_env`` must return
    ``action=skip`` with ``reason=snoozed`` instead of paging on-call.
    Pinned because a regression that gates snooze AFTER the
    debounce check would silently re-page on the first tick where
    the 24h debounce expires inside the snooze window.
    """
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
        # Past last-alert timestamp so the 24h debounce would not
        # otherwise suppress this iteration — the snooze gate is the
        # ONLY thing keeping this from paging.
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=48)).isoformat(),
        "snoozed_until": (now + timedelta(hours=12)).isoformat(),
        "snoozed_at": (now - timedelta(minutes=30)).isoformat(),
        "snoozed_by": "ops@syrabit.ai",
        "snooze_hours": 24,
    }
    with _clear_envs(), _patch_send() as mock_send:
        report = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert report["action"] == "skip"
    assert report["reason"] == "snoozed"
    assert report["env_name"] == CF_PULL
    assert report["snooze_remaining_seconds"] > 0
    mock_send.assert_not_awaited()


def test_recovery_branch_ignores_snooze_and_still_pages(fake_db):
    """Snooze ONLY suppresses missing-side pages — once the operator
    lands the missing webhook, the missing→healthy recovery page
    must still fire so the admin gets the "good job, you fixed it"
    confirmation. Without this asymmetry, a snooze that outlives the
    fix would hide the recovery and admins wouldn't know the secret
    rotation actually landed.
    """
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
        "last_state": "missing",
        "last_alert_at": (now - timedelta(hours=48)).isoformat(),
        "snoozed_until": (now + timedelta(hours=12)).isoformat(),
        "snooze_hours": 24,
    }
    with _set_env(CF_PULL, "https://hooks.slack.test/abc"), _patch_send() as mock_send:
        report = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert report["action"] == "alerted"
    assert report["kind"] == "recovered"
    mock_send.assert_awaited_once()
    args, _kwargs = mock_send.call_args
    assert args[1] == CF_PULL
    assert args[2] == "recovered"


def test_expired_snooze_does_not_suppress_paging(fake_db):
    """An expired snooze must NOT keep silencing the nag — the
    intent is "shut up for X hours", not "shut up forever". A
    regression that compares timestamps in the wrong direction (or
    treats ``snooze_remaining_seconds == 0`` as truthy) would extend
    the snooze indefinitely.
    """
    now = _now()
    lock_id = alerter._lock_id_for(CF_PULL)
    fake_db.job_locks._docs[lock_id] = {
        "_id": lock_id,
        "env_name": CF_PULL,
        "first_observed_ts": (
            now.timestamp() - (alerter._BOOTSTRAP_GRACE_S + 3600)
        ),
        "deploy_id": _CURRENT_DEPLOY_ID,
        # Snoozed_until is in the past → should no longer suppress.
        "snoozed_until": (now - timedelta(hours=2)).isoformat(),
        "snooze_hours": 1,
    }
    with _clear_envs(), _patch_send() as mock_send:
        report = asyncio.run(
            alerter._check_and_alert_one_env(fake_db, CF_PULL, now)
        )
    assert report["action"] == "alerted"
    assert report["kind"] == "missing"
    mock_send.assert_awaited_once()


def test_snooze_endpoint_requires_admin_auth(http_client_no_auth):
    """The snooze endpoint mutates per-env state — without auth a
    drive-by request could silence pages the admin team doesn't
    even know about. Mirrors the GET endpoints' auth contract."""
    res = http_client_no_auth.post(
        f"/admin/health/slack-webhook-missing/{CF_PULL}/snooze",
        json={"untilHours": 24},
    )
    assert res.status_code in (401, 403)


def test_snooze_endpoint_rejects_unknown_env(http_client_authed):
    """Unknown env names must 404 — same surface-tightening reason
    as the GETs (path param feeds the lock-doc id template)."""
    res = http_client_authed.post(
        "/admin/health/slack-webhook-missing/NOT_A_REAL_ENV/snooze",
        json={"untilHours": 24},
    )
    assert res.status_code == 404


@pytest.mark.parametrize("payload", [
    {"untilHours": 0},
    {"untilHours": -1},
    {"untilHours": 169},
    {"untilHours": "24"},
    {"untilHours": 24.5},
    {"untilHours": None},
    {"untilHours": True},
    {},
])
def test_snooze_endpoint_rejects_invalid_until_hours(
    http_client_authed, payload,
):
    """The clamp helper is the single source of validation truth;
    pin the route's HTTP surface so a future refactor can't bypass
    it (e.g. by accidentally accepting a default value or coercing
    the body before validation)."""
    with _patch_route_mongo(lock_doc=None):
        res = http_client_authed.post(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/snooze",
            json=payload,
        )
    assert res.status_code == 400


def test_snooze_endpoint_persists_fields_and_returns_alert_state(
    http_client_authed,
):
    """The happy path: a valid POST must persist ``snoozed_until`` /
    ``snoozed_at`` / ``snoozed_by`` / ``snooze_hours`` on the lock
    doc, schedule a ``record_cron_alert_event(kind="snoozed")`` audit
    entry, and echo back the same shape the GET ``/alert-state``
    returns (with the derived ``snoozeRemainingSeconds`` /
    ``snoozeActive`` fields populated) so the dashboard can update
    its tooltip atomically without waiting for the 60s polling tick.
    """
    with _patch_route_mongo(lock_doc=None) as _mongo, \
         patch(
             "routes.admin_health.record_cron_alert_event",
             new_callable=AsyncMock,
         ) as mock_record:
        res = http_client_authed.post(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/snooze",
            json={"untilHours": 24},
        )
    assert res.status_code == 200
    body = res.json()
    # Auto-projected raw fields from the lock doc.
    assert body["present"] is True
    assert body.get("snoozeHours") == 24
    assert body.get("snoozedBy") == "ops@syrabit.ai"
    assert body["snoozedUntil"]
    assert body["snoozedAt"]
    # Derived gate fields layered on by the route handler.
    assert body["snoozeActive"] is True
    assert body["snoozeRemainingSeconds"] > 0
    assert body["snoozeRemainingSeconds"] <= 24 * 3600
    # Best-effort audit log entry was scheduled (fire-and-forget via
    # asyncio.create_task — give the loop one tick to drain it).
    asyncio.run(asyncio.sleep(0))
    mock_record.assert_called_once()
    _args, kwargs = mock_record.call_args
    assert kwargs["kind"] == "snoozed"
    assert kwargs["sub_kind"] == CF_PULL
    assert kwargs["lock_id"] == alerter._lock_id_for(CF_PULL)
    assert kwargs["health"]["envName"] == CF_PULL
    assert kwargs["health"]["snoozeHours"] == 24
    assert kwargs["health"]["snoozedBy"] == "ops@syrabit.ai"


def test_snooze_endpoint_returns_503_when_mongo_unavailable(
    http_client_authed,
):
    """When Mongo is down we must NOT cheerfully claim the snooze
    landed — otherwise the badge updates but the alerter keeps
    paging. 503 mirrors how the alerter loop itself stands down on
    Mongo unavailability and matches the FE's retry semantics."""
    with _patch_route_mongo(available=False):
        res = http_client_authed.post(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/snooze",
            json={"untilHours": 24},
        )
    assert res.status_code == 503


def test_alert_state_endpoint_surfaces_snooze_derived_fields(
    http_client_authed,
):
    """A pre-existing snooze on the lock doc must round-trip through
    ``/alert-state`` with both the raw camelCase fields (auto-projected
    by ``_build_alert_state_response``) and the derived
    ``snoozeRemainingSeconds`` / ``snoozeActive`` gate fields. Pinned
    so the dashboard's tooltip stays in lockstep with the alerter
    loop's gate without re-implementing ISO parsing client-side.
    """
    now = datetime.now(timezone.utc)
    lock_doc = {
        "_id": alerter._lock_id_for(CF_PULL),
        "env_name": CF_PULL,
        "snoozed_until": (now + timedelta(hours=10)).isoformat(),
        "snoozed_at": now.isoformat(),
        "snoozed_by": "ops@syrabit.ai",
        "snooze_hours": 10,
    }
    with _patch_route_mongo(lock_doc=lock_doc):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-state",
        )
    assert res.status_code == 200
    body = res.json()
    assert body["present"] is True
    assert body["snoozedBy"] == "ops@syrabit.ai"
    assert body["snoozeHours"] == 10
    assert body["snoozeActive"] is True
    assert body["snoozeRemainingSeconds"] > 0
    assert body["snoozeRemainingSeconds"] <= 10 * 3600


def test_alert_state_endpoint_marks_expired_snooze_inactive(
    http_client_authed,
):
    """A stale snooze (snoozed_until in the past) must surface as
    ``snoozeActive=false`` / ``snoozeRemainingSeconds=0`` so the
    dashboard hides the "snoozed for Xh" caption and re-enables the
    Snooze button. Without this branch the badge would lie about an
    active snooze the alerter has already silently expired through.
    """
    now = datetime.now(timezone.utc)
    lock_doc = {
        "_id": alerter._lock_id_for(CF_PULL),
        "env_name": CF_PULL,
        "snoozed_until": (now - timedelta(hours=2)).isoformat(),
        "snoozed_at": (now - timedelta(hours=4)).isoformat(),
        "snooze_hours": 1,
    }
    with _patch_route_mongo(lock_doc=lock_doc):
        res = http_client_authed.get(
            f"/admin/health/slack-webhook-missing/{CF_PULL}/alert-state",
        )
    assert res.status_code == 200
    body = res.json()
    assert body["snoozeActive"] is False
    assert body["snoozeRemainingSeconds"] == 0
    # Raw projected fields still come through so an admin can see
    # "this was last snoozed at X for Y hours" in the history view.
    assert body["snoozeHours"] == 1
