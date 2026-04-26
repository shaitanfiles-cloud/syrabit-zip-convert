"""Task #728 — Trustpilot aggregate feed health endpoint + >24h alerter.

Covers:
* feed classification (broken / healthy / unknown);
* health endpoint surfaces freshness + last-error from the in-process cache;
* never-configured / warmup states never page;
* first broken detection alerts and persists state;
* broken→broken inside the 24h debounce is suppressed;
* broken→broken past the 24h debounce re-pages;
* broken→healthy fires exactly one recovery, then settles;
* healthy→healthy never alerts AND never writes the lock doc;
* inconclusive (not_configured) never touches state.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from routes import admin_trustpilot_alerts


# ─── Fake Mongo (job_locks only — copy of the CI-alerter test fake) ─────────

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
                if k == "$or":
                    if not any(_matches(doc, sub) for sub in v):
                        return False
                    continue
                actual = doc.get(k)
                if isinstance(v, dict):
                    if "$ne" in v and actual == v["$ne"]:
                        return False
                    if "$lt" in v and not (actual is not None and actual < v["$lt"]):
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
    return datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


def _health(*, configured=True, last_success_age_s=None,
            last_error=None, last_error_age_s=None,
            first_error_age_s=None):
    """Build a synthetic health snapshot like
    :func:`routes.config.get_trustpilot_aggregate_health` would return.

    ``first_error_age_s`` defaults to ``last_error_age_s`` when omitted —
    i.e. the test simulates a single failed fetch. Tests that exercise
    a continuous outage (rolling ``last_error_age_s`` while
    ``first_error_age_s`` keeps growing) pass both explicitly.
    """
    now_ts = _now().timestamp()
    last_success_ts = (
        now_ts - last_success_age_s if last_success_age_s is not None else None
    )
    last_error_ts = (
        now_ts - last_error_age_s if last_error_age_s is not None else None
    )
    if first_error_age_s is None:
        first_error_age_s = last_error_age_s
    first_error_ts = (
        now_ts - first_error_age_s if first_error_age_s is not None else None
    )
    return {
        "configured": configured,
        "businessUnitId": "biz-1" if configured else None,
        "ttlSeconds": 6 * 3600,
        "hasPayload": last_success_age_s is not None,
        "lastSuccessTs": last_success_ts,
        "lastSuccessAgeSeconds": last_success_age_s,
        "lastErrorTs": last_error_ts,
        "lastErrorAgeSeconds": last_error_age_s,
        "firstErrorTs": first_error_ts,
        "firstErrorAgeSeconds": first_error_age_s,
        "lastError": last_error,
        "stale": (last_success_age_s or 0) >= 6 * 3600,
        "cachedPayload": {"ratingValue": 4.7} if last_success_age_s is not None else None,
    }


@pytest.fixture
def fake_db():
    return _FakeDb()


def _patch_send():
    return patch.object(
        admin_trustpilot_alerts, "_send_trustpilot_alert", new_callable=AsyncMock,
    )


# ─── Classification ─────────────────────────────────────────────────────────

def test_classify_buckets():
    now_ts = _now().timestamp()
    # Not configured → unknown.
    assert admin_trustpilot_alerts._classify_feed(
        _health(configured=False), now_ts,
    ) == "unknown"
    # Fresh success → healthy.
    assert admin_trustpilot_alerts._classify_feed(
        _health(last_success_age_s=3600), now_ts,
    ) == "healthy"
    # Stale success past threshold → broken.
    assert admin_trustpilot_alerts._classify_feed(
        _health(last_success_age_s=25 * 3600,
                last_error="http_403", last_error_age_s=1800),
        now_ts,
    ) == "broken"
    # Never succeeded but only failing for an hour → unknown (warmup).
    assert admin_trustpilot_alerts._classify_feed(
        _health(last_error="http_403", last_error_age_s=3600),
        now_ts,
    ) == "unknown"
    # Never succeeded and failing > threshold → broken.
    assert admin_trustpilot_alerts._classify_feed(
        _health(last_error="http_403", last_error_age_s=25 * 3600),
        now_ts,
    ) == "broken"


def test_continuous_outage_classified_broken_despite_rolling_last_error_ts():
    """Regression guard for the timing bug:

    During a continuous outage the cache's ``fail_ts`` (a.k.a.
    ``lastErrorTs``) is overwritten on every retry (~5 min cadence), so
    its age never crosses the 24h threshold. The classifier MUST instead
    use ``firstErrorTs`` (set once on entering failure, cleared on
    success), otherwise a never-succeeded feed could stay broken
    forever without paging.
    """
    now_ts = _now().timestamp()
    # Most recent retry attempt 2 minutes ago, but the outage actually
    # started >25h ago — exactly the shape of a feed that has been
    # continuously failing across many retry windows.
    h = _health(
        last_error="http_403",
        last_error_age_s=120,
        first_error_age_s=25 * 3600,
    )
    assert admin_trustpilot_alerts._classify_feed(h, now_ts) == "broken"


# ─── Alert lifecycle ────────────────────────────────────────────────────────

def test_first_broken_detection_alerts_and_persists(fake_db):
    now = _now()
    health = _health(last_success_age_s=25 * 3600, last_error="http_403",
                     last_error_age_s=600)
    with _patch_send() as mock_send:
        result = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now, health,
            )
        )
    assert result == {"action": "alerted", "kind": "broken"}
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID]
    assert saved["last_state"] == "broken"
    assert saved["last_alert_at"] == now.isoformat()


def test_broken_within_debounce_is_suppressed(fake_db):
    now = _now()
    fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID] = {
        "_id": admin_trustpilot_alerts._LOCK_ID,
        "last_state": "broken",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    health = _health(last_success_age_s=27 * 3600, last_error="http_403",
                     last_error_age_s=600)
    with _patch_send() as mock_send:
        result = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now, health,
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "debounced"
    mock_send.assert_not_called()


def test_broken_outside_debounce_re_pages(fake_db):
    now = _now()
    fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID] = {
        "_id": admin_trustpilot_alerts._LOCK_ID,
        "last_state": "broken",
        "last_alert_at": (now - timedelta(hours=25)).isoformat(),
    }
    health = _health(last_success_age_s=50 * 3600, last_error="http_403",
                     last_error_age_s=600)
    with _patch_send() as mock_send:
        result = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now, health,
            )
        )
    assert result == {"action": "alerted", "kind": "broken"}
    mock_send.assert_called_once()


def test_broken_to_healthy_fires_recovery_then_settles(fake_db):
    now = _now()
    fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID] = {
        "_id": admin_trustpilot_alerts._LOCK_ID,
        "last_state": "broken",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    healthy = _health(last_success_age_s=120)
    with _patch_send() as mock_send:
        first = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now, healthy,
            )
        )
    assert first == {"action": "alerted", "kind": "recovered"}
    mock_send.assert_called_once()
    saved = fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID]
    assert saved["last_state"] == "healthy"

    with _patch_send() as mock_send2:
        second = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now + timedelta(minutes=15), healthy,
            )
        )
    assert second["action"] == "skip"
    assert second["reason"] == "healthy"
    mock_send2.assert_not_called()


def test_healthy_to_healthy_never_alerts_or_writes(fake_db):
    """Healthy observations must never alert AND must never write to the
    lock doc — writing on healthy would race a concurrent broken claim
    from another replica and silently bypass the 24h debounce."""
    now = _now()
    healthy = _health(last_success_age_s=600)
    with _patch_send() as mock_send:
        result = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now, healthy,
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "healthy"
    mock_send.assert_not_called()
    assert admin_trustpilot_alerts._LOCK_ID not in fake_db.job_locks._docs


def test_inconclusive_does_not_touch_state(fake_db):
    """Not-configured / warmup must never page and must leave any prior
    broken state alone (so a transient config glitch can't silently
    mask an outstanding outage)."""
    now = _now()
    fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID] = {
        "_id": admin_trustpilot_alerts._LOCK_ID,
        "last_state": "broken",
        "last_alert_at": (now - timedelta(hours=1)).isoformat(),
    }
    with _patch_send() as mock_send:
        result = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now, _health(configured=False),
            )
        )
    assert result["action"] == "skip"
    assert result["reason"] == "inconclusive"
    mock_send.assert_not_called()
    saved = fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID]
    assert saved["last_state"] == "broken"  # untouched


# ─── Health endpoint ───────────────────────────────────────────────────────

def test_admin_health_endpoint_status_branches():
    """The endpoint reduces the cache snapshot into a single status
    string the dashboard can pill on."""
    async def _call(health):
        async def _fake_global():
            return health
        with patch.object(
            admin_trustpilot_alerts, "get_trustpilot_global_health",
            new=_fake_global,
        ):
            return await admin_trustpilot_alerts.admin_trustpilot_health(admin={})

    not_configured = asyncio.run(_call(_health(configured=False)))
    assert not_configured["status"] == "not_configured"

    healthy = asyncio.run(_call(_health(last_success_age_s=120)))
    assert healthy["status"] == "healthy"
    assert healthy["lastSuccessAgeSeconds"] == 120

    degraded = asyncio.run(_call(
        _health(last_success_age_s=600, last_error="http_403",
                last_error_age_s=60)
    ))
    assert degraded["status"] == "degraded"
    assert degraded["lastError"] == "http_403"

    broken = asyncio.run(_call(
        _health(last_success_age_s=25 * 3600, last_error="http_403",
                last_error_age_s=600)
    ))
    assert broken["status"] == "broken"
    assert broken["staleThresholdSeconds"] == 24 * 3600

    never = asyncio.run(_call(_health()))  # configured=True, no success/err
    assert never["status"] == "never_succeeded"


# ─── Cross-replica safety ──────────────────────────────────────────────────

def test_no_false_recovery_when_global_health_disagrees_with_local(fake_db):
    """Multi-replica regression: replica A's local cache says "healthy"
    (its last fetch happened to succeed seconds ago) but the GLOBAL
    health doc — which aggregates outcomes across replicas — still
    shows the outage is ongoing because replica B is failing.

    The alerter must read the GLOBAL view, so it must NOT flip the
    state to recovered just because A's local cache looks fine."""
    now = _now()
    # Seed the lock as broken.
    fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID] = {
        "_id": admin_trustpilot_alerts._LOCK_ID,
        "last_state": "broken",
        "last_alert_at": (now - timedelta(hours=2)).isoformat(),
    }
    # Global health says: still failing for >25h (outage ongoing).
    global_broken = _health(
        last_error="http_403",
        last_error_age_s=120,
        first_error_age_s=25 * 3600,
    )
    with _patch_send() as mock_send:
        result = asyncio.run(
            admin_trustpilot_alerts._check_and_alert_trustpilot_feed(
                fake_db, now, global_broken,
            )
        )
    # Inside the 24h re-page debounce → skip; never call recovery.
    assert result["action"] == "skip"
    assert result["reason"] == "debounced"
    mock_send.assert_not_called()
    # Lock state must remain broken — no false flip to healthy.
    assert (fake_db.job_locks._docs[admin_trustpilot_alerts._LOCK_ID]
            ["last_state"] == "broken")


# ─── Cache integration with config.py ──────────────────────────────────────

def test_get_trustpilot_aggregate_health_reflects_cache_state():
    """End-to-end: writing into the in-process cache must surface in the
    health snapshot the alerter consumes."""
    import time as _time
    from routes import config as cfg

    saved = dict(cfg._tp_aggregate_cache)
    try:
        cfg._tp_aggregate_cache["payload"] = {
            "ratingValue": 4.6, "ratingCount": 200,
            "bestRating": 5, "worstRating": 1,
        }
        cfg._tp_aggregate_cache["ts"] = _time.time() - 60
        cfg._tp_aggregate_cache["fail_ts"] = 0.0
        cfg._tp_aggregate_cache["last_error"] = None

        snap = cfg.get_trustpilot_aggregate_health()
        assert snap["hasPayload"] is True
        assert snap["lastSuccessAgeSeconds"] is not None
        assert snap["lastSuccessAgeSeconds"] < 120
        assert snap["lastError"] is None

        cfg._tp_aggregate_cache["fail_ts"] = _time.time() - 30
        cfg._tp_aggregate_cache["last_error"] = "http_403: forbidden"
        snap = cfg.get_trustpilot_aggregate_health()
        assert snap["lastError"] == "http_403: forbidden"
        assert snap["lastErrorAgeSeconds"] is not None
        assert snap["lastErrorAgeSeconds"] < 120
    finally:
        cfg._tp_aggregate_cache.clear()
        cfg._tp_aggregate_cache.update(saved)


def test_get_trustpilot_aggregate_cached_persists_first_fail_ts_across_retries(
    monkeypatch,
):
    """Regression guard tying config.py + the alerter together:

    ``_get_trustpilot_aggregate_cached`` is called repeatedly during an
    outage. Each call updates ``fail_ts`` (the last failure) but
    ``first_fail_ts`` must be set once and then preserved — it's the
    timestamp the alerter uses to decide whether the outage has
    crossed >24h. If we overwrote it every retry, alerts would never
    fire during a real outage.
    """
    from routes import config as cfg

    saved = dict(cfg._tp_aggregate_cache)
    try:
        cfg._tp_aggregate_cache.clear()
        cfg._tp_aggregate_cache.update({
            "payload": None, "ts": 0.0, "fail_ts": 0.0,
            "first_fail_ts": 0.0, "last_error": None,
        })

        async def _always_fail():
            cfg._tp_aggregate_cache["last_error"] = "http_403"
            return None

        monkeypatch.setattr(
            cfg, "_fetch_trustpilot_aggregate_remote", _always_fail,
        )
        # Force the per-call retry throttle to fire so the second call
        # actually attempts a fresh fetch.
        monkeypatch.setattr(cfg, "_TP_AGGREGATE_FAIL_TTL_S", 0)

        asyncio.run(cfg._get_trustpilot_aggregate_cached())
        first_fail_after_call_1 = cfg._tp_aggregate_cache["first_fail_ts"]
        last_fail_after_call_1 = cfg._tp_aggregate_cache["fail_ts"]
        assert first_fail_after_call_1 > 0
        assert last_fail_after_call_1 > 0

        # Sleep a hair so the next call's fail_ts is strictly newer.
        import time as _time
        _time.sleep(0.01)

        asyncio.run(cfg._get_trustpilot_aggregate_cached())
        first_fail_after_call_2 = cfg._tp_aggregate_cache["first_fail_ts"]
        last_fail_after_call_2 = cfg._tp_aggregate_cache["fail_ts"]

        # first_fail_ts must be PRESERVED across retries, while fail_ts
        # rolls forward — the exact bug the code review caught.
        assert first_fail_after_call_2 == first_fail_after_call_1
        assert last_fail_after_call_2 > last_fail_after_call_1
    finally:
        cfg._tp_aggregate_cache.clear()
        cfg._tp_aggregate_cache.update(saved)


# ─── Task #971 — Slack fan-out for the data-feed alerter ──────────────────
#
# Mirrors the cf-waf-drift cron silence-alerter Slack tests
# (``tests/test_admin_cf_waf_drift_cron_alerts.py``) so the failure
# modes are uniform across the admin alert surface: payload shape,
# noop-on-missing-env, transport-failure swallow, and the end-to-end
# scheduling check that pins ``_send_trustpilot_alert`` actually
# fans out to the Slack helper alongside the email + in-app channels.
# Plus the Task #964-style health-endpoint tests pinning the new
# ``slackConfigured`` / ``slackWebhookEnv`` pair (env-set → True,
# env-unset/whitespace → False, webhook URL never serialized).

import os  # noqa: E402  — late import to avoid reordering the file


def test_slack_payload_broken_has_drift_alert_style():
    """The Slack body for a broken page must mirror the per-event
    JSON-LD alerter (Task #757) so the channel reads consistently:
    ``:rotating_light:`` header text, mrkdwn blocks, and the freshness
    metadata that motivated the page."""
    health = _health(
        last_success_age_s=25 * 3600,
        last_error="http_403",
        last_error_age_s=600,
    )
    payload = admin_trustpilot_alerts._slack_payload_for_feed_alert(
        title="Trustpilot feed broken: aggregate rating is stale",
        message="body...",
        kind="broken",
        health=health,
    )
    assert payload["text"].startswith(":rotating_light:")
    blocks = payload["blocks"]
    assert all(b["type"] == "section" for b in blocks)
    assert all(b["text"]["type"] == "mrkdwn" for b in blocks)
    header_md = blocks[0]["text"]["text"]
    assert "Trustpilot data feed broken" in header_md
    assert "25.0h" in header_md
    assert "/api/config/trustpilot/aggregate" in header_md
    detail_md = blocks[1]["text"]["text"]
    assert "lastError=http_403" in detail_md
    assert "lastSuccessAge=25.0h" in detail_md


def test_slack_payload_recovered_uses_check_emoji():
    health = _health(last_success_age_s=120)
    payload = admin_trustpilot_alerts._slack_payload_for_feed_alert(
        title="Trustpilot feed recovered: aggregate rating is fresh again",
        message="body...",
        kind="recovered",
        health=health,
    )
    assert payload["text"].startswith(":white_check_mark:")
    header_md = payload["blocks"][0]["text"]["text"]
    assert "recovered" in header_md.lower()
    assert "/api/config/trustpilot/aggregate" in header_md


def test_slack_payload_truncates_long_message_body():
    """Defensively cap the free-form message section under Slack's
    3000-char per-section limit so an unusually verbose alert body
    can't 400 the webhook."""
    huge = "x" * 5000
    payload = admin_trustpilot_alerts._slack_payload_for_feed_alert(
        title="t", message=huge, kind="broken",
        health=_health(last_success_age_s=25 * 3600),
    )
    body_md = payload["blocks"][2]["text"]["text"]
    assert len(body_md) <= 2900


def test_post_slack_feed_alert_noop_when_env_unset():
    """No env var → no network call, no logs above DEBUG, never raises."""
    captured = {"called": False}

    class _SentinelClient:
        def __init__(self, *a, **kw):
            captured["called"] = True

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SLACK_TRUSTPILOT_FEED_WEBHOOK_URL", None)
        with patch("httpx.AsyncClient", _SentinelClient):
            asyncio.run(admin_trustpilot_alerts._post_slack_feed_alert(
                "t", "m", "broken",
                _health(last_success_age_s=25 * 3600),
            ))
    assert captured["called"] is False


def test_post_slack_feed_alert_treats_whitespace_as_unset():
    """Whitespace-only env values must be treated as not configured —
    an accidental ``"  "`` from a broken secret-manager render would
    otherwise fire a doomed POST every page."""
    captured = {"called": False}

    class _SentinelClient:
        def __init__(self, *a, **kw):
            captured["called"] = True

    with patch.dict(
        os.environ,
        {"SLACK_TRUSTPILOT_FEED_WEBHOOK_URL": "   "},
        clear=False,
    ):
        with patch("httpx.AsyncClient", _SentinelClient):
            asyncio.run(admin_trustpilot_alerts._post_slack_feed_alert(
                "t", "m", "broken",
                _health(last_success_age_s=25 * 3600),
            ))
    assert captured["called"] is False


def test_post_slack_feed_alert_posts_when_env_set():
    """When the env var is set the helper POSTs the rendered payload
    to that URL with a JSON body."""
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
        {"SLACK_TRUSTPILOT_FEED_WEBHOOK_URL": "https://hooks.slack.test/abc"},
        clear=False,
    ):
        with patch("httpx.AsyncClient", _Client):
            asyncio.run(admin_trustpilot_alerts._post_slack_feed_alert(
                "t", "m", "broken",
                _health(last_success_age_s=25 * 3600),
            ))
    assert posted["url"] == "https://hooks.slack.test/abc"
    assert posted["json"]["text"].startswith(":rotating_light:")
    assert posted["json"]["blocks"]


def test_post_slack_feed_alert_swallows_transport_failures():
    """A 500 / network error from the webhook must NOT propagate —
    the alerter's email + in-app channels already succeeded by the
    time the Slack task runs in the background."""

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
        {"SLACK_TRUSTPILOT_FEED_WEBHOOK_URL": "https://hooks.slack.test/abc"},
        clear=False,
    ):
        with patch("httpx.AsyncClient", _BoomClient):
            # Must not raise.
            asyncio.run(admin_trustpilot_alerts._post_slack_feed_alert(
                "t", "m", "broken",
                _health(last_success_age_s=25 * 3600),
            ))


def test_send_trustpilot_alert_schedules_slack_fan_out(fake_db):
    """End-to-end: ``_send_trustpilot_alert`` must schedule a Slack
    POST alongside the email + in-app channels (Task #971). Patch
    the Slack helper itself so the test pins the contract — title,
    kind, and the same ``health`` dict — without exercising httpx."""
    now = _now()
    health = _health(last_success_age_s=25 * 3600, last_error="http_403",
                     last_error_age_s=600)
    captured: dict = {}

    async def _fake_slack(title, msg, kind, h):
        captured["title"] = title
        captured["kind"] = kind
        captured["health"] = h

    async def _run():
        with patch.object(
            admin_trustpilot_alerts, "_post_slack_feed_alert",
            new=_fake_slack,
        ):
            with patch.object(
                admin_trustpilot_alerts, "_email_admins_about_trustpilot",
                new=AsyncMock(),
            ):
                await admin_trustpilot_alerts._send_trustpilot_alert(
                    fake_db, "broken", health, now,
                )
                # Background tasks scheduled via asyncio.create_task —
                # yield once so they run in the same loop before the
                # context managers tear the patches back down.
                await asyncio.sleep(0)

    asyncio.run(_run())
    assert captured.get("kind") == "broken"
    assert "broken" in captured.get("title", "").lower()
    assert captured.get("health") is health


# ─── Task #971 — slackConfigured surfaces on the data-feed health endpoint ─

def test_admin_health_endpoint_surfaces_slack_configured_true_when_env_set():
    """When ``SLACK_TRUSTPILOT_FEED_WEBHOOK_URL`` is set, the data-feed
    health endpoint must surface ``slackConfigured: True`` and the env
    var name (so the AdminHealth dashboard pill renders the "Slack ✓"
    badge alongside the other indicators). The webhook URL itself must
    NOT appear anywhere in the response."""
    async def _call(env_value):
        async def _fake_global():
            return _health(last_success_age_s=120)
        with patch.object(
            admin_trustpilot_alerts, "get_trustpilot_global_health",
            new=_fake_global,
        ), patch.dict(
            os.environ,
            {"SLACK_TRUSTPILOT_FEED_WEBHOOK_URL": env_value},
            clear=False,
        ):
            return await admin_trustpilot_alerts.admin_trustpilot_health(
                admin={},
            )

    payload = asyncio.run(_call(
        "https://hooks.slack.example.com/services/T000/B000/feed-secret"
    ))
    assert payload["slackConfigured"] is True
    assert payload["slackWebhookEnv"] == "SLACK_TRUSTPILOT_FEED_WEBHOOK_URL"
    import json
    assert "feed-secret" not in json.dumps(payload)


def test_admin_health_endpoint_surfaces_slack_configured_false_when_env_unset(
    monkeypatch,
):
    """Slack-not-wired: ``slackConfigured: False`` so the dashboard pill
    renders the neutral "Slack ✗" badge that names the env var operators
    need to set. Whitespace-only values are also treated as not
    configured (``_slack_webhook_url`` strips them) so an accidental
    ``" "`` in a deploy template doesn't look like coverage."""
    async def _call():
        async def _fake_global():
            return _health(last_success_age_s=120)
        with patch.object(
            admin_trustpilot_alerts, "get_trustpilot_global_health",
            new=_fake_global,
        ):
            return await admin_trustpilot_alerts.admin_trustpilot_health(
                admin={},
            )

    monkeypatch.delenv("SLACK_TRUSTPILOT_FEED_WEBHOOK_URL", raising=False)
    payload_unset = asyncio.run(_call())
    assert payload_unset["slackConfigured"] is False
    assert payload_unset["slackWebhookEnv"] == "SLACK_TRUSTPILOT_FEED_WEBHOOK_URL"

    monkeypatch.setenv("SLACK_TRUSTPILOT_FEED_WEBHOOK_URL", "   ")
    payload_blank = asyncio.run(_call())
    assert payload_blank["slackConfigured"] is False
