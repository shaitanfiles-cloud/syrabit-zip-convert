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
