"""Task #831 (silent-cron alerter) + Task #834 (Slack fan-out for it)
— heartbeat + >36h "cron silent" alerter for the daily Cloudflare
firewall drift workflow.

Mirrors ``tests/test_admin_trustpilot_cron_alerts.py`` (Task #751)
because the implementation deliberately copies that pattern. The key
divergence: this alerter keys off ``last_heartbeat_ts`` (any
heartbeat) rather than ``last_success_heartbeat_ts``, because the
firewall drift workflow's per-run Slack alert (Task #828) already
covers "workflow ran but found drift". Tests here pin BOTH the shared
behaviour AND that divergence.

Covers:
* classification (silent / healthy / unknown), including the bootstrap
  grace window for a never-observed cron;
* admin health endpoint reduces the snapshot to a status pill,
  including the ``degraded`` branch when a recent heartbeat reports
  drift / transport-error / non-zero rc;
* first silent detection alerts and persists state;
* silent→silent inside the 24h re-page debounce is suppressed;
* silent→silent past the debounce re-pages;
* silent→healthy fires exactly one recovery, then settles;
* healthy→healthy never alerts AND never writes the alert lock doc;
* not_configured never touches state;
* never-observed seeds first_observed_ts then pages after the grace
  window elapses;
* drift-status heartbeat keeps the cron classified as healthy (the
  per-run Slack alert is the right channel for drift, not this
  silence alerter).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from routes import admin_cf_waf_drift_cron_alerts as cron


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
            last_status="success", last_verify_rc=0, last_aggregate_rc=0,
            last_run_url="https://github.com/o/r/runs/1",
            first_observed_age_s=None):
    """Synthetic health snapshot."""
    now_ts = _now().timestamp()
    last_hb_ts = (
        now_ts - last_heartbeat_age_s
        if last_heartbeat_age_s is not None else None
    )
    first_obs_ts = (
        now_ts - first_observed_age_s
        if first_observed_age_s is not None else None
    )
    return {
        "configured": configured,
        "lastHeartbeatTs": last_hb_ts,
        "lastHeartbeatAgeSeconds": last_heartbeat_age_s,
        "lastStatus": last_status if last_heartbeat_age_s is not None else None,
        "lastVerifyRc": last_verify_rc if last_heartbeat_age_s is not None else None,
        "lastAggregateRc": last_aggregate_rc if last_heartbeat_age_s is not None else None,
        "lastRunUrl": last_run_url if last_heartbeat_age_s is not None else None,
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
    # Fresh heartbeat → healthy.
    assert cron._classify_cron(
        _health(last_heartbeat_age_s=3600), now_ts, None,
    ) == "healthy"
    # Last heartbeat past threshold → silent.
    assert cron._classify_cron(
        _health(last_heartbeat_age_s=37 * 3600), now_ts, None,
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


def test_drift_status_heartbeat_classifies_healthy():
    """Intentional divergence from the Trustpilot precedent: a fresh
    heartbeat with status=drift / verify_rc=1 keeps the silence
    classifier in the ``healthy`` bucket. The workflow's per-run Slack
    alert (Task #828) is the right channel for drift; this alerter
    must not double-page on a workflow that's running fine but keeps
    finding drift on the firewall side."""
    now_ts = _now().timestamp()
    h = _health(
        last_heartbeat_age_s=1800,
        last_status="drift",
        last_verify_rc=1,
        last_aggregate_rc=0,
    )
    assert cron._classify_cron(h, now_ts, None) == "healthy"


def test_perpetually_failing_cron_classifies_silent_after_threshold():
    """Even though we don't gate on success-only, a workflow whose
    last heartbeat is older than 36h must classify as silent
    regardless of the status field on that stale doc."""
    now_ts = _now().timestamp()
    h = _health(last_heartbeat_age_s=40 * 3600, last_status="failure")
    assert cron._classify_cron(h, now_ts, None) == "silent"


# ─── Alert lifecycle ────────────────────────────────────────────────────────

def test_first_silent_detection_alerts_and_persists(fake_db):
    now = _now()
    health = _health(last_heartbeat_age_s=40 * 3600, last_status="failure")
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron._check_and_alert_cf_waf_drift_cron(fake_db, now, health)
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
            cron._check_and_alert_cf_waf_drift_cron(fake_db, now, health)
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
            cron._check_and_alert_cf_waf_drift_cron(fake_db, now, health)
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
            cron._check_and_alert_cf_waf_drift_cron(fake_db, now, healthy)
        )
    assert first == {"action": "alerted", "kind": "recovered"}
    mock_send.assert_called_once()
    assert fake_db.job_locks._docs[cron._LOCK_ID]["last_state"] == "healthy"

    with _patch_send() as mock_send2:
        second = asyncio.run(
            cron._check_and_alert_cf_waf_drift_cron(
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
            cron._check_and_alert_cf_waf_drift_cron(fake_db, now, healthy)
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
            cron._check_and_alert_cf_waf_drift_cron(
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
            cron._check_and_alert_cf_waf_drift_cron(fake_db, now, h)
        )
    assert first["action"] == "skip"
    mock_send.assert_not_called()
    assert (
        fake_db.job_locks._docs[cron._LOCK_ID]["first_observed_ts"]
        == now.timestamp()
    )

    later = now + timedelta(hours=cron._CRON_BOOTSTRAP_GRACE_S // 3600 + 1)
    h2 = _health()
    with _patch_send() as mock_send2:
        second = asyncio.run(
            cron._check_and_alert_cf_waf_drift_cron(fake_db, later, h2)
        )
    assert second == {"action": "alerted", "kind": "silent"}
    mock_send2.assert_called_once()


# ─── Health endpoint ───────────────────────────────────────────────────────

def test_admin_health_endpoint_status_branches():
    async def _call(health):
        async def _fake():
            return health
        with patch.object(
            cron, "get_cf_waf_drift_cron_health", new=_fake,
        ):
            return await cron.admin_cf_waf_drift_cron_health(admin={})

    not_configured = asyncio.run(_call(_health(configured=False)))
    assert not_configured["status"] == "not_configured"

    never = asyncio.run(_call(_health()))
    assert never["status"] == "never_observed"
    assert never["workflowUrl"]  # default fallback present

    healthy = asyncio.run(_call(_health(last_heartbeat_age_s=300)))
    assert healthy["status"] == "healthy"
    assert healthy["lastHeartbeatAgeSeconds"] == 300

    # Recent heartbeat but reports drift → degraded (Slack already
    # paged via Task #828; pill warns ops without re-paging here).
    degraded_drift = asyncio.run(_call(_health(
        last_heartbeat_age_s=300,
        last_status="drift",
        last_verify_rc=1,
        last_aggregate_rc=0,
    )))
    assert degraded_drift["status"] == "degraded"

    # Recent heartbeat but reports transport_error → degraded.
    degraded_transport = asyncio.run(_call(_health(
        last_heartbeat_age_s=300,
        last_status="transport_error",
        last_verify_rc=0,
        last_aggregate_rc=2,
    )))
    assert degraded_transport["status"] == "degraded"

    # No heartbeat in >36h → silent.
    silent = asyncio.run(_call(_health(last_heartbeat_age_s=40 * 3600)))
    assert silent["status"] == "silent"
    assert silent["silentThresholdSeconds"] == 36 * 3600


# ─── Heartbeat endpoint authn (cross-module sanity) ────────────────────────

def test_heartbeat_endpoint_requires_secret_env():
    """Fail-closed: if CF_WAF_DRIFT_HEARTBEAT_SECRET isn't set the
    endpoint returns 503 — same shape as the Trustpilot heartbeat."""
    import os
    from fastapi import HTTPException
    from routes import cf_waf_drift_cron_heartbeat as hb

    with patch.dict(
        os.environ, {"CF_WAF_DRIFT_HEARTBEAT_SECRET": ""}, clear=False,
    ):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(
                hb.cf_waf_drift_heartbeat(
                    body={}, x_cf_waf_drift_secret=None,
                )
            )
        assert ei.value.status_code == 503


def test_heartbeat_endpoint_rejects_wrong_secret():
    import os
    from fastapi import HTTPException
    from routes import cf_waf_drift_cron_heartbeat as hb

    with patch.dict(
        os.environ,
        {"CF_WAF_DRIFT_HEARTBEAT_SECRET": "expected"},
        clear=False,
    ):
        with pytest.raises(HTTPException) as ei:
            asyncio.run(
                hb.cf_waf_drift_heartbeat(
                    body={"status": "success"},
                    x_cf_waf_drift_secret="nope",
                )
            )
        assert ei.value.status_code == 401


# ─── Task #834 — Slack fan-out ─────────────────────────────────────────────

def test_slack_payload_silent_has_drift_alert_style():
    """The Slack body for a silence page must mirror the per-run drift
    alert (Task #828) so the channel reads consistently:
    ``:rotating_light:`` header text, mrkdwn blocks, and a runbook
    pointer to ``docs/CLOUDFLARE_ZERO_TRUST.md``."""
    health = _health(
        last_heartbeat_age_s=40 * 3600,
        last_status="failure",
        last_verify_rc=2,
        last_aggregate_rc=0,
    )
    payload = cron._slack_payload_for_cron_alert(
        title="Cloudflare firewall drift cron silent: no run in 40.0h",
        message="body...",
        kind="silent",
        health=health,
    )
    assert payload["text"].startswith(":rotating_light:")
    blocks = payload["blocks"]
    assert all(b["type"] == "section" for b in blocks)
    assert all(b["text"]["type"] == "mrkdwn" for b in blocks)
    header_md = blocks[0]["text"]["text"]
    assert "Cloudflare firewall drift cron silent" in header_md
    assert "40.0h" in header_md
    assert "GitHub Actions workflow" in header_md
    assert "docs/CLOUDFLARE_ZERO_TRUST.md" in header_md
    detail_md = blocks[1]["text"]["text"]
    assert "verifyRc=2" in detail_md
    assert "aggregateRc=0" in detail_md
    assert "status=failure" in detail_md


def test_slack_payload_recovered_uses_check_emoji():
    health = _health(last_heartbeat_age_s=120, last_status="success")
    payload = cron._slack_payload_for_cron_alert(
        title="Cloudflare firewall drift cron recovered: heartbeat resumed",
        message="body...",
        kind="recovered",
        health=health,
    )
    assert payload["text"].startswith(":white_check_mark:")
    header_md = payload["blocks"][0]["text"]["text"]
    assert "recovered" in header_md.lower()
    assert "GitHub Actions run" in header_md


def test_slack_payload_truncates_long_message_body():
    """Defensively cap the free-form message section under Slack's
    3000-char per-section limit so an unusually verbose alert body
    can't 400 the webhook."""
    huge = "x" * 5000
    payload = cron._slack_payload_for_cron_alert(
        title="t", message=huge, kind="silent",
        health=_health(last_heartbeat_age_s=40 * 3600),
    )
    body_md = payload["blocks"][2]["text"]["text"]
    assert len(body_md) <= 2900


def test_post_slack_cron_alert_noop_when_env_unset():
    """No env var → no network call, no logs above DEBUG, never raises."""
    import os
    captured = {"called": False}

    class _SentinelClient:
        def __init__(self, *a, **kw):
            captured["called"] = True

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CF_WAF_DRIFT_SLACK_WEBHOOK", None)
        with patch("httpx.AsyncClient", _SentinelClient):
            asyncio.run(cron._post_slack_cron_alert(
                "t", "m", "silent",
                _health(last_heartbeat_age_s=40 * 3600),
            ))
    assert captured["called"] is False


def test_post_slack_cron_alert_posts_when_env_set():
    """When the env var is set the helper POSTs the rendered payload
    to that URL with a JSON body."""
    import os
    posted: dict = {}

    class _Resp:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            posted["url"] = url
            posted["json"] = json
            return _Resp()

    with patch.dict(
        os.environ,
        {"CF_WAF_DRIFT_SLACK_WEBHOOK": "https://hooks.slack.test/abc"},
        clear=False,
    ):
        with patch("httpx.AsyncClient", _Client):
            asyncio.run(cron._post_slack_cron_alert(
                "t", "m", "silent",
                _health(last_heartbeat_age_s=40 * 3600),
            ))
    assert posted["url"] == "https://hooks.slack.test/abc"
    assert posted["json"]["text"].startswith(":rotating_light:")
    assert posted["json"]["blocks"]


def test_post_slack_cron_alert_swallows_transport_failures():
    """A 500 / network error from the webhook must NOT propagate —
    the alerter's email + in-app channels already succeeded by the
    time the Slack task runs in the background."""
    import os

    class _BoomClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise RuntimeError("network dead")

    with patch.dict(
        os.environ,
        {"CF_WAF_DRIFT_SLACK_WEBHOOK": "https://hooks.slack.test/abc"},
        clear=False,
    ):
        with patch("httpx.AsyncClient", _BoomClient):
            # Must not raise.
            asyncio.run(cron._post_slack_cron_alert(
                "t", "m", "silent",
                _health(last_heartbeat_age_s=40 * 3600),
            ))


def test_send_cron_alert_schedules_slack_fan_out(fake_db):
    """End-to-end: ``_send_cron_alert`` must schedule a Slack POST
    alongside the email + in-app channels (Task #834). Patch the
    Slack helper itself so the test pins the contract — title, kind,
    and the same ``health`` dict — without exercising httpx."""
    now = _now()
    health = _health(last_heartbeat_age_s=40 * 3600, last_status="failure")
    captured: dict = {}

    async def _fake_slack(title, msg, kind, h):
        captured["title"] = title
        captured["kind"] = kind
        captured["health"] = h

    async def _run():
        with patch.object(cron, "_post_slack_cron_alert", new=_fake_slack):
            with patch.object(cron, "_email_admins_about_cron",
                              new=AsyncMock()):
                await cron._send_cron_alert(fake_db, "silent", health, now)
                # Background tasks scheduled via asyncio.create_task —
                # yield once so they run in the same loop before the
                # context managers tear the patches back down.
                await asyncio.sleep(0)

    asyncio.run(_run())
    assert captured.get("kind") == "silent"
    assert "silent" in captured.get("title", "").lower()
    assert captured.get("health") is health
