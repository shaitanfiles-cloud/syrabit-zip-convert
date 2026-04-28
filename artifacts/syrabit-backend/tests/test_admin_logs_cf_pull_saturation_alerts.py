"""Task #952 — saturation alerter for the unified-logs Cloudflare GraphQL
pull (`unified_logs_cf_pull_lock.last_saturated_windows`).

Pins:

* recording persists each saturated minute exactly once, even when the
  same minute appears across multiple ticks (idempotency via Mongo
  ``_id == since_iso``);
* the rolling 24h count reflects only minutes whose ``first_observed_at``
  is inside the window (older docs are filtered out — TTL is set up
  by ``ensure_saturation_indexes`` and exercised by Mongo at runtime);
* a tick with non-empty ``saturated_windows`` and at least one *new*
  minute fires the alert exactly once and writes the lock doc;
* a tick with non-empty ``saturated_windows`` but every minute already
  on file from a previous tick does NOT page (no fresh saturation);
* the alerter has *no* time-window debounce on top of per-minute
  dedupe — back-to-back ticks with distinct fresh minutes each
  produce their own alert, even if the previous alert was minutes
  ago. This is the Task #952 done condition: every CF pull tick
  that reports a non-empty saturated_windows must be admin-visible.
* ``record_and_maybe_alert`` is best-effort: a Mongo blip on the
  alert side never undoes the persist (so the rolling counter keeps
  working when the on-call channel is flaky).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from routes import admin_logs_cf_pull_saturation_alerts as cron


# ─── Fake Mongo ─────────────────────────────────────────────────────────────

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
        self.indexes: list = []

    async def create_index(self, spec, **kwargs):
        self.indexes.append({"spec": spec, **kwargs})

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
                    if "$lt" in v and not (
                        actual is not None and actual < v["$lt"]
                    ):
                        return False
                    if "$exists" in v and (k in doc) != bool(v["$exists"]):
                        return False
                    if "$gte" in v and not (
                        actual is not None and actual >= v["$gte"]
                    ):
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
            self._docs[_id] = doc
        for k, v in (update.get("$set") or {}).items():
            doc[k] = v
        for k, v in (update.get("$setOnInsert") or {}).items():
            doc.setdefault(k, v)
        return None

    async def insert_one(self, doc):
        _id = doc["_id"]
        if _id in self._docs:
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError("dup")
        self._docs[_id] = dict(doc)
        return None

    async def count_documents(self, query, limit=None):
        def _match(doc):
            for k, v in query.items():
                actual = doc.get(k)
                if isinstance(v, dict):
                    if "$gte" in v and not (
                        actual is not None and actual >= v["$gte"]
                    ):
                        return False
                else:
                    if actual != v:
                        return False
            return True
        return sum(1 for d in self._docs.values() if _match(d))

    def find(self, *a, **kw):
        return _FakeCursor([])


class _FakeDb:
    def __init__(self):
        self._colls: dict = {}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeColl())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._colls.setdefault(name, _FakeColl())


@pytest.fixture
def fake_db():
    return _FakeDb()


def _now():
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)


def _patch_send():
    return patch.object(
        cron, "_send_saturation_alert", new_callable=AsyncMock,
    )


# ─── ensure_saturation_indexes ──────────────────────────────────────────────

def test_ensure_saturation_indexes_creates_ttl(fake_db):
    asyncio.run(cron.ensure_saturation_indexes(fake_db))
    coll = fake_db[cron.SATURATION_COLLECTION]
    # The TTL index has the ``expireAfterSeconds`` kwarg pinned to ~25h.
    matching = [
        idx for idx in coll.indexes
        if idx.get("spec") == "first_observed_at"
    ]
    assert matching, "first_observed_at TTL index must be created"
    assert matching[0].get("expireAfterSeconds") == 25 * 3600


def test_ensure_saturation_indexes_handles_no_db():
    # No db handle (e.g. Mongo unavailable at startup) must not raise.
    asyncio.run(cron.ensure_saturation_indexes(None))


# ─── record_saturated_windows ───────────────────────────────────────────────

def test_record_persists_each_minute_once(fake_db):
    now = _now()
    sw = [
        ("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00"),
        ("2026-04-26T11:56:00+00:00", "2026-04-26T11:57:00+00:00"),
    ]
    fresh = asyncio.run(cron.record_saturated_windows(fake_db, sw, now))
    assert len(fresh) == 2
    coll = fake_db[cron.SATURATION_COLLECTION]
    assert "2026-04-26T11:55:00+00:00" in coll._docs
    assert "2026-04-26T11:56:00+00:00" in coll._docs
    # ``first_observed_at`` is what the rolling 24h count keys on.
    assert coll._docs["2026-04-26T11:55:00+00:00"][
        "first_observed_at"
    ] == now


def test_record_dedups_same_minute_across_ticks(fake_db):
    now = _now()
    sw = [("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00")]
    first = asyncio.run(cron.record_saturated_windows(fake_db, sw, now))
    later = now + timedelta(minutes=1)
    second = asyncio.run(cron.record_saturated_windows(fake_db, sw, later))
    assert len(first) == 1
    # The second tick on the same minute must not re-flag it as fresh
    # — otherwise we'd page on every tick that re-pulls a stale window.
    assert second == []
    coll = fake_db[cron.SATURATION_COLLECTION]
    # ``last_observed_at`` advances; ``first_observed_at`` is sticky so
    # the rolling 24h count stays anchored at the original detection.
    doc = coll._docs["2026-04-26T11:55:00+00:00"]
    assert doc["last_observed_at"] == later
    assert doc["first_observed_at"] == now


def test_record_handles_legacy_list_shape(fake_db):
    """The cursor doc round-trips ``saturated_windows`` through BSON
    which can flatten tuples into lists. The recorder must accept
    either shape so a redeploy mid-flight doesn't crash."""
    now = _now()
    sw = [
        ["2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00"],
    ]
    fresh = asyncio.run(cron.record_saturated_windows(fake_db, sw, now))
    assert fresh == [
        ("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00"),
    ]


def test_record_skips_empty_input(fake_db):
    now = _now()
    assert asyncio.run(
        cron.record_saturated_windows(fake_db, [], now)
    ) == []
    assert asyncio.run(
        cron.record_saturated_windows(fake_db, None, now)
    ) == []


def test_record_skips_when_db_is_none():
    # Best-effort: never raises even with no Mongo handle.
    sw = [("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00")]
    assert asyncio.run(cron.record_saturated_windows(None, sw, _now())) == []


# ─── count_saturated_minutes_24h ────────────────────────────────────────────

def test_count_24h_filters_old_docs(fake_db):
    now = _now()
    coll = fake_db[cron.SATURATION_COLLECTION]
    coll._docs["recent"] = {
        "_id": "recent",
        "first_observed_at": now - timedelta(hours=2),
    }
    coll._docs["edge"] = {
        "_id": "edge",
        "first_observed_at": now - timedelta(hours=23, minutes=59),
    }
    coll._docs["stale"] = {
        "_id": "stale",
        "first_observed_at": now - timedelta(hours=25),
    }
    n = asyncio.run(cron.count_saturated_minutes_24h(fake_db, now))
    assert n == 2  # ``stale`` is past the 24h cutoff


def test_count_24h_returns_zero_when_db_is_none():
    assert asyncio.run(cron.count_saturated_minutes_24h(None, _now())) == 0


# ─── maybe_alert_on_saturation ──────────────────────────────────────────────

def test_alert_fires_on_fresh_saturation(fake_db):
    now = _now()
    fresh = [("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00")]
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron.maybe_alert_on_saturation(fake_db, fresh, now)
        )
    assert result["action"] == "alerted"
    assert result["fresh"] == fresh
    mock_send.assert_called_once()
    # The lock doc records that we paged so the next tick inside the
    # 24h debounce window can dedup against it.
    saved = fake_db.job_locks._docs[cron._LOCK_ID]
    assert saved["last_state"] == "saturated"
    assert saved["last_alert_at"] == now.isoformat()
    assert saved["last_saturated_minute"] == fresh[-1][0]


def test_alert_skipped_when_no_fresh_minutes(fake_db):
    """A tick whose saturated minutes were all already on file from a
    previous tick must not page — operator was already paged on the
    original detection."""
    now = _now()
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron.maybe_alert_on_saturation(fake_db, [], now)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "no_new_saturation"
    mock_send.assert_not_called()
    assert cron._LOCK_ID not in fake_db.job_locks._docs


def test_alert_fires_again_immediately_for_distinct_fresh_minute(fake_db):
    """Task #952 done condition: every CF pull tick with a non-empty
    saturated_windows must be admin-visible. Two ticks separated by
    only a minute, each containing a *distinct* never-before-seen
    saturated minute, must each produce their own alert — there is
    no time-window debounce on top of the per-minute dedupe.
    """
    now = _now()
    # First alert: brand-new doc, brand-new fresh minute.
    fresh1 = [("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00")]
    fresh2 = [("2026-04-26T11:56:00+00:00", "2026-04-26T11:57:00+00:00")]
    with _patch_send() as mock_send:
        r1 = asyncio.run(
            cron.maybe_alert_on_saturation(fake_db, fresh1, now)
        )
        # Second tick lands one minute later with a different fresh
        # minute (well inside what used to be a 24h debounce).
        r2 = asyncio.run(cron.maybe_alert_on_saturation(
            fake_db, fresh2, now + timedelta(minutes=1),
        ))
    assert r1["action"] == "alerted"
    assert r2["action"] == "alerted"
    # Both ticks paged — no debounce suppressed the second one.
    assert mock_send.call_count == 2
    # The lock doc is overwritten in place by the second alert so
    # the AdminHealth pill always reflects the most recent page.
    saved = fake_db.job_locks._docs[cron._LOCK_ID]
    assert saved["last_alert_at"] == (
        now + timedelta(minutes=1)
    ).isoformat()
    assert saved["last_saturated_minute"] == fresh2[-1][0]


def test_alert_fires_for_back_to_back_distinct_minutes_in_one_tick(fake_db):
    """A single tick whose ``saturated_windows`` contains multiple
    distinct fresh minutes must produce exactly one alert (per the
    same dedupe contract — one alert per *call* covers all the fresh
    minutes in that call) and the alert must mention all of them so
    the operator doesn't miss a co-occurring saturation."""
    now = _now()
    fresh = [
        ("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00"),
        ("2026-04-26T11:56:00+00:00", "2026-04-26T11:57:00+00:00"),
        ("2026-04-26T11:57:00+00:00", "2026-04-26T11:58:00+00:00"),
    ]
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron.maybe_alert_on_saturation(fake_db, fresh, now)
        )
    assert result["action"] == "alerted"
    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    # _send_saturation_alert(db, fresh, count_24h, now)
    assert args[1] == fresh  # all 3 minutes carried into the alert


def test_alert_carries_24h_count(fake_db):
    """The alert payload must carry the rolling 24h count so the
    operator can tell a one-off spike from a structural problem
    without having to open the dashboard separately."""
    now = _now()
    coll = fake_db[cron.SATURATION_COLLECTION]
    # Pre-populate two pre-existing saturated minutes inside the 24h
    # window so the counter is non-zero before the new fresh minute.
    coll._docs["pre1"] = {
        "_id": "pre1",
        "first_observed_at": now - timedelta(hours=4),
    }
    coll._docs["pre2"] = {
        "_id": "pre2",
        "first_observed_at": now - timedelta(hours=8),
    }
    fresh = [("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00")]
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron.maybe_alert_on_saturation(fake_db, fresh, now)
        )
    assert result["action"] == "alerted"
    # 24h count is taken from the saturation collection — the brand-new
    # fresh minute hasn't been persisted yet (the recorder runs before
    # the alerter), so the count reflects only the pre-existing two.
    assert result["count_24h"] == 2
    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    # _send_saturation_alert(db, fresh, count_24h, now)
    assert args[2] == 2


# ─── record_and_maybe_alert (the end-to-end entrypoint) ────────────────────

def test_record_and_maybe_alert_full_flow(fake_db):
    now = _now()
    sw = [
        ("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00"),
        ("2026-04-26T11:56:00+00:00", "2026-04-26T11:57:00+00:00"),
    ]
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron.record_and_maybe_alert(fake_db, sw, now)
        )
    assert result["action"] == "alerted"
    # Both minutes were freshly persisted.
    assert len(result["fresh"]) == 2
    # The 24h counter sees both new minutes (record runs before count).
    assert result["count_24h"] == 2
    mock_send.assert_called_once()
    # Lock doc records the page.
    assert fake_db.job_locks._docs[cron._LOCK_ID]["last_state"] == "saturated"


def test_record_and_maybe_alert_second_tick_same_minute_does_not_page(fake_db):
    """Second tick covers the same already-recorded saturated minute
    (e.g. an admin re-runs the manual /cf/pull) — must not re-page."""
    now = _now()
    sw = [("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00")]
    with _patch_send() as mock_send:
        first = asyncio.run(
            cron.record_and_maybe_alert(fake_db, sw, now)
        )
        second = asyncio.run(
            cron.record_and_maybe_alert(
                fake_db, sw, now + timedelta(minutes=1),
            )
        )
    assert first["action"] == "alerted"
    assert second["action"] == "skip"
    assert second["reason"] == "no_new_saturation"
    assert mock_send.call_count == 1


def test_record_and_maybe_alert_handles_empty_input(fake_db):
    """Empty saturated_windows is the common path (most ticks fit
    cleanly) — must short-circuit without touching Mongo or the
    alert lock doc."""
    now = _now()
    with _patch_send() as mock_send:
        result = asyncio.run(
            cron.record_and_maybe_alert(fake_db, [], now)
        )
    assert result["action"] == "skip"
    assert result["reason"] == "no_new_saturation"
    mock_send.assert_not_called()
    assert cron._LOCK_ID not in fake_db.job_locks._docs


# ─── get_saturation_health / admin pill ─────────────────────────────────────

def test_health_pill_status_branches(fake_db):
    now = _now()

    async def _call(*, configured, last_windows=(), count_24h=0):
        # Patch the CF env-var probe inside get_saturation_health.
        async def _fake_get_health():
            return {
                "configured": configured,
                "lastSaturatedWindows": list(last_windows),
                "lastSaturatedAt": None,
                "saturatedCount24h": count_24h,
            }
        with patch.object(cron, "get_saturation_health", new=_fake_get_health):
            return await cron.admin_unified_logs_cf_pull_saturation_health(
                admin={},
            )

    not_configured = asyncio.run(_call(configured=False))
    assert not_configured["status"] == "not_configured"

    saturated = asyncio.run(
        _call(configured=True, count_24h=3),
    )
    assert saturated["status"] == "saturated"
    # Per-minute dedupe is the only throttling on the alerter — no
    # time-window debounce — so the pill surfaces the 60s floor as
    # the dedupe contract instead of a multi-hour interval.
    assert saturated["dedupeWindowSeconds"] == cron._DEDUPE_WINDOW_S
    assert saturated["dedupeWindowSeconds"] == 60
    assert saturated["statusUrl"] == "/api/admin/logs/status"

    saturated_now = asyncio.run(
        _call(
            configured=True,
            last_windows=[
                ("2026-04-26T11:55:00+00:00", "2026-04-26T11:56:00+00:00"),
            ],
        ),
    )
    assert saturated_now["status"] == "saturated"

    healthy = asyncio.run(_call(configured=True))
    assert healthy["status"] == "healthy"
