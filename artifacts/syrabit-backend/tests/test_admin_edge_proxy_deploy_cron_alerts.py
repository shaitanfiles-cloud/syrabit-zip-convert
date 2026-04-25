"""Task #893 — silence-alerter for the edge-proxy-deploy CI workflow.

Mirrors ``tests/test_admin_cf_waf_drift_cron_alerts.py`` (Task #831 /
#834) because the alerter is deliberately a copy of that pattern with
the input swapped from the cf-waf-drift heartbeat snapshot to the
existing ``/admin/health/edge-proxy-deploy/cron`` pill snapshot
(Task #882). The key divergences:

* the source signal is the GitHub-Actions-driven AdminHealth pill, not
  a backend heartbeat — there's no first-observed bootstrap window;
* the broken state has TWO sub-kinds — ``failed`` (red, last conclusion
  was ``failure``) and ``stale`` (amber, last successful run >7d old) —
  and a transition between sub-kinds re-pages even mid-debounce so the
  body's "what's currently wrong" line stays accurate.

Covers:
* classification (broken / healthy / unknown);
* sub-kind discrimination (failed vs stale);
* first broken detection alerts and persists state;
* broken→broken (same kind) inside the 24h debounce is suppressed;
* broken→broken (same kind) past the debounce re-pages;
* failed→stale inside the debounce still re-pages (kind changed);
* broken→healthy fires exactly one recovery, then settles;
* healthy→healthy never alerts AND never writes the alert lock doc;
* not_configured / never_observed / unknown never touches state;
* notification body includes the failing run's html_url;
* Slack helper renders mrkdwn payload + truncates long bodies +
  no-ops cleanly when env unset + swallows transport failures.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from routes import admin_edge_proxy_deploy_cron_alerts as alerter


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
    return datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)


def _pill(*, status="healthy", conclusion="success", age_seconds=3600,
          html_url="https://github.com/o/r/actions/runs/9001",
          run_status="completed", head_branch="master",
          head_sha="deadbee"):
    """Synthetic AdminHealth pill snapshot (matches the shape returned
    by ``routes.admin_health.get_edge_proxy_deploy_cron_health``)."""
    workflow_url = (
        "https://github.com/o/r/actions/workflows/edge-proxy-deploy.yml"
    )
    return {
        "configured": True,
        "status": status,
        "conclusion": conclusion,
        "html_url": html_url,
        "lastRunUrl": html_url,
        "workflowUrl": workflow_url,
        "ageSeconds": age_seconds,
        "staleThresholdSeconds": 7 * 86400,
        "updated_at": "2026-04-25T11:00:00Z",
        "runStatus": run_status,
        "runId": 9001,
        "runNumber": 42,
        "headSha": head_sha,
        "headBranch": head_branch,
        "event": "push",
        "actor": "ci-bot",
        "error": None,
    }


@pytest.fixture
def fake_db():
    return _FakeDb()


def _patch_send():
    return patch.object(alerter, "_send_cron_alert", new_callable=AsyncMock)


# ─── Classification ─────────────────────────────────────────────────────────

def test_classify_buckets():
    # Healthy pill → healthy.
    assert alerter._classify_pill(_pill(status="healthy")) == "healthy"
    # Failure pill → broken.
    assert alerter._classify_pill(
        _pill(status="silent", conclusion="failure"),
    ) == "broken"
    # Stale-success pill → broken.
    assert alerter._classify_pill(
        _pill(status="degraded", age_seconds=8 * 86400),
    ) == "broken"
    # Not configured / never observed / GitHub error → unknown (no page).
    assert alerter._classify_pill(_pill(status="not_configured")) == "unknown"
    assert alerter._classify_pill(_pill(status="never_observed")) == "unknown"
    assert alerter._classify_pill(_pill(status="unknown")) == "unknown"


def test_kind_discrimination():
    """``silent`` → failed (red), ``degraded`` → stale (amber). The
    body / Slack template branches on this so the page text says the
    right thing."""
    assert alerter._kind_for_pill(
        _pill(status="silent", conclusion="failure"),
    ) == "failed"
    assert alerter._kind_for_pill(
        _pill(status="degraded", age_seconds=8 * 86400),
    ) == "stale"


# ─── Alert lifecycle ────────────────────────────────────────────────────────

def test_first_broken_detection_alerts_and_persists(fake_db):
    now = _now()
    pill = _pill(status="silent", conclusion="failure", age_seconds=600)
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(fake_db, now, pill)
        )
    assert result == {
        "action": "alerted", "kind": "broken", "sub_kind": "failed",
    }
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[alerter._LOCK_ID]
    assert saved["last_state"] == "broken"
    assert saved["last_kind"] == "failed"
    assert saved["last_alert_at"] == now.isoformat()
    # html_url is the deep-link on-call needs — must be persisted on
    # the lock doc so subsequent debugging can find which run paged.
    assert saved["last_html_url"] == pill["html_url"]


def test_first_stale_detection_alerts_with_stale_kind(fake_db):
    now = _now()
    pill = _pill(
        status="degraded", conclusion="success", age_seconds=10 * 86400,
    )
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(fake_db, now, pill)
        )
    assert result == {
        "action": "alerted", "kind": "broken", "sub_kind": "stale",
    }
    mock_send.assert_called_once()
    assert fake_db.job_locks._docs[alerter._LOCK_ID]["last_kind"] == "stale"


def test_broken_within_debounce_same_kind_is_suppressed(fake_db):
    now = _now()
    fake_db.job_locks._docs[alerter._LOCK_ID] = {
        "_id": alerter._LOCK_ID,
        "last_state": "broken",
        "last_kind": "failed",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    pill = _pill(status="silent", conclusion="failure", age_seconds=10800)
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(fake_db, now, pill)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "debounced"
    mock_send.assert_not_called()


def test_broken_outside_debounce_re_pages(fake_db):
    now = _now()
    fake_db.job_locks._docs[alerter._LOCK_ID] = {
        "_id": alerter._LOCK_ID,
        "last_state": "broken",
        "last_kind": "failed",
        "last_alert_at": (now - timedelta(hours=25)).isoformat(),
    }
    pill = _pill(status="silent", conclusion="failure", age_seconds=90000)
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(fake_db, now, pill)
        )
    assert result == {
        "action": "alerted", "kind": "broken", "sub_kind": "failed",
    }
    mock_send.assert_called_once()


def test_failed_to_stale_re_pages_inside_debounce(fake_db):
    """Sub-kind change is itself a state change worth paging on: the
    cron's underlying problem moved from "smoke-preview is failing"
    to "no fresh deploys at all", which is a different on-call
    investigation. Re-page even mid-24h-debounce so the body's
    "this is what's wrong now" line is accurate."""
    now = _now()
    fake_db.job_locks._docs[alerter._LOCK_ID] = {
        "_id": alerter._LOCK_ID,
        "last_state": "broken",
        "last_kind": "failed",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    pill = _pill(status="degraded", conclusion="success",
                 age_seconds=8 * 86400)
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(fake_db, now, pill)
        )
    assert result == {
        "action": "alerted", "kind": "broken", "sub_kind": "stale",
    }
    mock_send.assert_called_once()
    assert fake_db.job_locks._docs[alerter._LOCK_ID]["last_kind"] == "stale"


def test_broken_to_healthy_fires_recovery_then_settles(fake_db):
    now = _now()
    fake_db.job_locks._docs[alerter._LOCK_ID] = {
        "_id": alerter._LOCK_ID,
        "last_state": "broken",
        "last_kind": "failed",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    healthy = _pill(status="healthy", conclusion="success", age_seconds=120)
    with _patch_send() as mock_send:
        first = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(
                fake_db, now, healthy,
            )
        )
    assert first == {"action": "alerted", "kind": "recovered"}
    mock_send.assert_called_once()
    assert fake_db.job_locks._docs[alerter._LOCK_ID]["last_state"] == "healthy"

    with _patch_send() as mock_send2:
        second = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(
                fake_db, now + timedelta(minutes=15), healthy,
            )
        )
    assert second["action"] == "skip"
    assert second["reason"] == "healthy"
    mock_send2.assert_not_called()


def test_healthy_to_healthy_never_alerts_or_writes_alert_state(fake_db):
    now = _now()
    healthy = _pill(status="healthy", conclusion="success", age_seconds=600)
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(
                fake_db, now, healthy,
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "healthy"
    mock_send.assert_not_called()
    # Healthy must NOT bootstrap a state doc (an unconditional upsert
    # could clobber a peer's broken claim and bypass the 24h debounce).
    assert alerter._LOCK_ID not in fake_db.job_locks._docs


def test_unknown_does_not_touch_existing_broken_state(fake_db):
    """A flaky GitHub fetch (status: unknown) must not flip the lock
    doc: prior broken state stays so the next conclusive iteration
    can reason about debounce correctly."""
    now = _now()
    fake_db.job_locks._docs[alerter._LOCK_ID] = {
        "_id": alerter._LOCK_ID,
        "last_state": "broken",
        "last_kind": "failed",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(
                fake_db, now, _pill(status="unknown"),
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    assert fake_db.job_locks._docs[alerter._LOCK_ID]["last_state"] == "broken"


def test_not_configured_skips_inconclusive(fake_db):
    now = _now()
    with _patch_send() as mock_send:
        result = asyncio.run(
            alerter._check_and_alert_edge_proxy_deploy_cron(
                fake_db, now, _pill(status="not_configured"),
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    assert alerter._LOCK_ID not in fake_db.job_locks._docs


# ─── Notification body ──────────────────────────────────────────────────────

def test_send_cron_alert_includes_html_url_in_notification(fake_db):
    """End-to-end: the persisted in-app notification + the email body
    BOTH include the failing run's html_url so on-call can jump
    straight to the GitHub Actions logs (the task spec requirement)."""
    now = _now()
    pill = _pill(
        status="silent", conclusion="failure", age_seconds=600,
        html_url="https://github.com/o/r/actions/runs/424242",
    )
    captured: dict = {}

    async def _fake_supa_insert(notif):
        captured["notif"] = notif

    async def _fake_email(title, msg, kind):
        captured["email"] = {"title": title, "msg": msg, "kind": kind}

    with patch("db_ops.supa_insert_notification", new=_fake_supa_insert), \
            patch.object(alerter, "_email_admins_about_cron",
                         side_effect=_fake_email) as _, \
            patch.object(alerter, "_post_slack_cron_alert",
                         new_callable=AsyncMock):
        asyncio.run(
            alerter._send_cron_alert(fake_db, "broken", "failed", pill, now)
        )
        # Allow the create_task'd email coroutine to run.
        asyncio.run(asyncio.sleep(0))
    notif = captured["notif"]
    assert notif["meta"]["html_url"] == pill["html_url"]
    assert pill["html_url"] in notif["message"]
    assert notif["meta"]["kind"] == "edge_proxy_deploy_cron_alert"
    assert notif["meta"]["sub_kind"] == "failed"
    assert notif["audience"] == "admins"
    assert notif["type"] == "error"


def test_send_cron_alert_recovery_uses_info_type(fake_db):
    now = _now()
    healthy = _pill(status="healthy", conclusion="success", age_seconds=120)
    captured: dict = {}

    async def _fake_supa_insert(notif):
        captured["notif"] = notif

    with patch("db_ops.supa_insert_notification", new=_fake_supa_insert), \
            patch.object(alerter, "_email_admins_about_cron",
                         new_callable=AsyncMock), \
            patch.object(alerter, "_post_slack_cron_alert",
                         new_callable=AsyncMock):
        asyncio.run(
            alerter._send_cron_alert(fake_db, "recovered", None, healthy, now)
        )
    assert captured["notif"]["type"] == "info"
    assert "recovered" in captured["notif"]["title"].lower()


# ─── Slack fan-out ─────────────────────────────────────────────────────────

def test_slack_payload_failed_renders_rotating_light_block_kit():
    payload = alerter._slack_payload_for_cron_alert(
        title="edge-proxy-deploy CI failed: latest run concluded `failure`",
        message="body...",
        kind="broken",
        sub_kind="failed",
        health=_pill(status="silent", conclusion="failure", age_seconds=600),
    )
    assert payload["text"].startswith(":rotating_light:")
    blocks = payload["blocks"]
    assert all(b["type"] == "section" for b in blocks)
    assert all(b["text"]["type"] == "mrkdwn" for b in blocks)
    header_md = blocks[0]["text"]["text"]
    assert "edge-proxy-deploy CI failed" in header_md
    assert "GitHub Actions workflow" in header_md
    assert "edge-proxy" in header_md
    detail_md = blocks[1]["text"]["text"]
    assert "conclusion=failure" in detail_md


def test_slack_payload_stale_calls_out_no_recent_deploy():
    payload = alerter._slack_payload_for_cron_alert(
        title="edge-proxy-deploy CI stale",
        message="body...",
        kind="broken",
        sub_kind="stale",
        health=_pill(
            status="degraded", conclusion="success", age_seconds=10 * 86400,
        ),
    )
    header_md = payload["blocks"][0]["text"]["text"]
    assert "stale" in header_md.lower()
    assert "No deploy in" in header_md


def test_slack_payload_recovered_uses_check_emoji():
    payload = alerter._slack_payload_for_cron_alert(
        title="edge-proxy-deploy CI recovered",
        message="body...",
        kind="recovered",
        sub_kind=None,
        health=_pill(status="healthy", conclusion="success", age_seconds=120),
    )
    assert payload["text"].startswith(":white_check_mark:")
    header_md = payload["blocks"][0]["text"]["text"]
    assert "recovered" in header_md.lower()
    assert "GitHub Actions run" in header_md


def test_slack_payload_truncates_long_message_body():
    huge = "x" * 5000
    payload = alerter._slack_payload_for_cron_alert(
        title="t", message=huge, kind="broken", sub_kind="failed",
        health=_pill(status="silent", conclusion="failure"),
    )
    body_md = payload["blocks"][2]["text"]["text"]
    assert len(body_md) <= 2900


def test_post_slack_cron_alert_noop_when_env_unset():
    """No env var → no network call, never raises."""
    import os
    captured = {"called": False}

    class _SentinelClient:
        def __init__(self, *a, **kw):
            captured["called"] = True

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("EDGE_PROXY_DEPLOY_SLACK_WEBHOOK", None)
        with patch("httpx.AsyncClient", _SentinelClient):
            asyncio.run(alerter._post_slack_cron_alert(
                "t", "m", "broken", "failed",
                _pill(status="silent", conclusion="failure"),
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
        {"EDGE_PROXY_DEPLOY_SLACK_WEBHOOK": "https://hooks.slack.test/abc"},
        clear=False,
    ):
        with patch("httpx.AsyncClient", _Client):
            asyncio.run(alerter._post_slack_cron_alert(
                "t", "m", "broken", "failed",
                _pill(status="silent", conclusion="failure"),
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
        {"EDGE_PROXY_DEPLOY_SLACK_WEBHOOK": "https://hooks.slack.test/abc"},
        clear=False,
    ):
        with patch("httpx.AsyncClient", _BoomClient):
            # Must not raise.
            asyncio.run(alerter._post_slack_cron_alert(
                "t", "m", "broken", "failed",
                _pill(status="silent", conclusion="failure"),
            ))
