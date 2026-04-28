"""Task #944 — Cloudflare GraphQL → unified_logs adapter tests.

We do NOT exercise the real cloudflare_client._graphql_query — instead
we inject a fake callable into ``_try_run_cf_pull_once`` and assert
that:
  - dimensions are mapped to the unified-log shape correctly
  - the cursor is advanced (db.job_locks updated)
  - rerunning with the same data is a no-op (cursor moves past the
    already-pulled window)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import unified_logs_dao as dao
from routes import admin_logs as routes
from tests.test_unified_logs_dao import _FakeDb


def test_normalize_cf_http_request_row_maps_all_fields():
    row = {
        "dimensions": {
            "datetimeMinute": "2026-04-26T10:00:00Z",
            "edgeResponseStatus": 200,
            "originResponseStatus": 200,
            "cacheStatus": "HIT",
            "clientRequestPath": "/api/foo",
            "clientRequestHTTPMethodName": "GET",
            "clientRequestHTTPHost": "syrabit.ai",
            "clientCountryName": "IN",
            "coloCode": "BLR",
        },
        "avg": {"originResponseDurationMs": 42.7},
        "count": 5,
    }
    out = routes.normalize_cf_http_request_row(row)
    assert out["source"] == "cloudflare"
    assert out["status"] == 200
    assert out["level"] == "info"
    assert out["route"] == "/api/foo"
    assert out["method"] == "GET"
    assert out["country"] == "IN"
    assert out["colo"] == "BLR"
    assert out["cache"] == "hit"
    # ``httpRequestsAdaptiveGroups`` is aggregated and does not expose
    # per-request ray identifiers, so cloudflare rows ship with no cid.
    assert out["ray_id"] is None
    assert out["correlation_id"] is None
    assert out["duration_ms"] == 43
    assert out["extra"]["host"] == "syrabit.ai"
    assert out["extra"]["request_count"] == 5


def test_normalize_cf_row_uses_warn_for_4xx_and_error_for_5xx():
    base = {
        "dimensions": {"clientRequestPath": "/x", "clientRequestHTTPMethodName": "GET"},
        "avg": {}, "sum": {"requests": 1},
    }
    base["dimensions"]["edgeResponseStatus"] = 404
    assert routes.normalize_cf_http_request_row(base)["level"] == "warn"
    base["dimensions"]["edgeResponseStatus"] = 502
    assert routes.normalize_cf_http_request_row(base)["level"] == "error"


def test_normalize_cf_row_idempotency_key_includes_all_grouping_dims():
    """Two CF buckets that share minute+method+path+status+colo+cache
    but differ on host or country are *legitimately distinct* rows
    coming out of httpRequestsAdaptiveGroups. The deterministic _id
    must NOT collapse them — otherwise insert_logs() would silently
    drop the second one as an E11000 duplicate, undercounting traffic.
    """
    base_dim = {
        "datetimeMinute": "2026-04-26T10:00:00Z",
        "edgeResponseStatus": 200,
        "originResponseStatus": 200,
        "cacheStatus": "HIT",
        "clientRequestPath": "/",
        "clientRequestHTTPMethodName": "GET",
        "coloCode": "BLR",
    }
    row_in = {**base_dim, "clientRequestHTTPHost": "syrabit.ai",
              "clientCountryName": "IN"}
    row_us = {**base_dim, "clientRequestHTTPHost": "syrabit.ai",
              "clientCountryName": "US"}
    row_other_host = {**base_dim, "clientRequestHTTPHost": "blog.syrabit.ai",
                      "clientCountryName": "IN"}
    n_in = routes.normalize_cf_http_request_row({"dimensions": row_in,
                                                 "avg": {}, "count": 3})
    n_us = routes.normalize_cf_http_request_row({"dimensions": row_us,
                                                 "avg": {}, "count": 5})
    n_other = routes.normalize_cf_http_request_row({"dimensions": row_other_host,
                                                    "avg": {}, "count": 7})
    assert n_in["_id"] != n_us["_id"], "country should split the bucket"
    assert n_in["_id"] != n_other["_id"], "host should split the bucket"
    assert n_us["_id"] != n_other["_id"]
    # Sanity: re-normalising the *same* bucket yields the same id —
    # that's the retry-dedupe behaviour we want to keep.
    n_in_again = routes.normalize_cf_http_request_row({"dimensions": row_in,
                                                       "avg": {}, "count": 99})
    assert n_in["_id"] == n_in_again["_id"]


def test_normalize_cf_row_collapses_dynamic_cache_status():
    row = {
        "dimensions": {"cacheStatus": "DYNAMIC", "edgeResponseStatus": 200,
                       "clientRequestPath": "/", "clientRequestHTTPMethodName": "GET"},
        "avg": {}, "sum": {"requests": 1},
    }
    assert routes.normalize_cf_http_request_row(row)["cache"] == "dynamic"


def test_try_run_cf_pull_once_inserts_rows_and_advances_cursor(monkeypatch):
    async def _inner():
        """Smoke-test the full pull adapter against a fake GraphQL response."""
        dao._reset_backend_shipper_for_tests()
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)

        # Stand-in for the cloudflare_client.config import.
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)

        async def fake_graphql(query, variables):
            # Locks down the query shape lightly — the variables must
            # carry the zone tag the route claims to be using.
            assert variables["zone"] == "zone-1"
            return {"data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [
                {
                    "dimensions": {
                        "datetimeMinute": "2026-04-26T10:00:00Z",
                        "edgeResponseStatus": 500,
                        "cacheStatus": "MISS",
                        "clientRequestPath": "/api/explode",
                        "clientRequestHTTPMethodName": "POST",
                        "clientRequestHTTPHost": "syrabit.ai",
                        "clientCountryName": "IN", "coloCode": "BLR",
                        "rayName": "ray-1",
                    },
                    "avg": {"originResponseDurationMs": 1234.0},
                    "sum": {"requests": 1},
                },
            ]}]}}}

        now = datetime(2026, 4, 26, 10, 5, tzinfo=timezone.utc)
        res = await routes._try_run_cf_pull_once(now_utc=now, graphql_callable=fake_graphql)
        assert res["ok"] is True
        assert res["accepted"] == 1
        assert res["dropped"] == 0

        inserted = db[dao.UNIFIED_LOGS_COLLECTION].docs
        assert len(inserted) == 1
        assert inserted[0]["source"] == "cloudflare"
        assert inserted[0]["status"] == 500
        assert inserted[0]["route"] == "/api/explode"

        lock = next((d for d in db.job_locks.docs if d.get("_id") == routes.CF_PULL_LOCK_ID), None)
        assert lock is not None
        assert lock["last_accepted"] == 1
        assert lock[routes.CF_PULL_CURSOR_FIELD] == res["until"]


    asyncio.run(_inner())
def test_try_run_cf_pull_once_returns_reason_when_cf_unconfigured(monkeypatch):
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "", raising=False)
        res = await routes._try_run_cf_pull_once(graphql_callable=None)
        assert res["ok"] is False
        assert res["reason"] == "cf_not_configured"
    asyncio.run(_inner())


# ─── Task #947 — cross-replica lease for the CF pull loop ─────────────


def _lease_doc(db: _FakeDb):
    """Helper: pluck the lease/cursor doc from the fake job_locks coll."""
    return next(
        (d for d in db.job_locks.docs if d.get("_id") == routes.CF_PULL_LOCK_ID),
        None,
    )


def test_acquire_cf_pull_lease_bootstraps_when_no_doc_exists():
    """Fresh deployment: no doc in job_locks → insert path wins,
    lease_owner is set to OUR id, lease_expires_at is in the future."""
    async def _inner():
        db = _FakeDb()
        now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        ok = await routes._try_acquire_cf_pull_lease(
            db, now=now, owner_id="replica-A", ttl_s=120,
        )
        assert ok is True
        doc = _lease_doc(db)
        assert doc is not None
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "replica-A"
        assert doc[routes.CF_PULL_LEASE_EXPIRES_FIELD] > now
    asyncio.run(_inner())


def test_acquire_cf_pull_lease_renews_when_already_owned():
    """Renewal path: same owner re-acquires every tick. lease_expires_at
    is pushed forward; ownership does not change."""
    async def _inner():
        db = _FakeDb()
        now1 = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        await routes._try_acquire_cf_pull_lease(
            db, now=now1, owner_id="replica-A", ttl_s=120,
        )
        first_expiry = _lease_doc(db)[routes.CF_PULL_LEASE_EXPIRES_FIELD]
        now2 = now1 + timedelta(seconds=30)
        ok = await routes._try_acquire_cf_pull_lease(
            db, now=now2, owner_id="replica-A", ttl_s=120,
        )
        assert ok is True
        doc = _lease_doc(db)
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "replica-A"
        assert doc[routes.CF_PULL_LEASE_EXPIRES_FIELD] > first_expiry
    asyncio.run(_inner())


def test_acquire_cf_pull_lease_blocks_when_other_replica_is_alive():
    """Anti-spam path: replica-A holds an unexpired lease → replica-B
    cannot acquire and the doc still belongs to replica-A. This is the
    core of Task #947 — without it, two Railway replicas would both
    enter the pull-and-write branch on the same tick."""
    async def _inner():
        db = _FakeDb()
        now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        ok_a = await routes._try_acquire_cf_pull_lease(
            db, now=now, owner_id="replica-A", ttl_s=120,
        )
        assert ok_a is True
        # Replica-B tries to grab it 5 seconds later, well inside TTL.
        ok_b = await routes._try_acquire_cf_pull_lease(
            db, now=now + timedelta(seconds=5),
            owner_id="replica-B", ttl_s=120,
        )
        assert ok_b is False
        doc = _lease_doc(db)
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "replica-A"
    asyncio.run(_inner())


def test_acquire_cf_pull_lease_takes_over_after_expiry():
    """Fail-over path: replica-A acquired then died (no renewal). After
    lease_expires_at passes, replica-B can take over without waiting on
    a human."""
    async def _inner():
        db = _FakeDb()
        t0 = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        await routes._try_acquire_cf_pull_lease(
            db, now=t0, owner_id="replica-A", ttl_s=60,
        )
        # Replica-B wakes up after the lease expired.
        ok_b = await routes._try_acquire_cf_pull_lease(
            db, now=t0 + timedelta(seconds=120),
            owner_id="replica-B", ttl_s=60,
        )
        assert ok_b is True
        doc = _lease_doc(db)
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "replica-B"
    asyncio.run(_inner())


def test_acquire_cf_pull_lease_bootstraps_legacy_doc_without_lease_fields():
    """Migration path: a job_locks doc may already exist from before
    Task #947 (just ``cursor`` + ``updated_at``, no lease fields).
    The CAS branch matching ``lease_owner == None`` lets us upgrade
    in place without losing the cursor."""
    async def _inner():
        db = _FakeDb()
        # Seed the legacy doc shape — cursor + updated_at only.
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD: "2026-04-26T09:00:00+00:00",
            "updated_at": "2026-04-26T09:00:00+00:00",
        })
        now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        ok = await routes._try_acquire_cf_pull_lease(
            db, now=now, owner_id="replica-A", ttl_s=120,
        )
        assert ok is True
        doc = _lease_doc(db)
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "replica-A"
        # Cursor must survive the lease bootstrap.
        assert doc[routes.CF_PULL_CURSOR_FIELD] == "2026-04-26T09:00:00+00:00"
    asyncio.run(_inner())


def test_release_cf_pull_lease_clears_owner_for_self_only():
    """Graceful shutdown: the owning replica clears lease_owner so peers
    can take over on their next follower tick. A non-owner calling
    release must NOT clobber a peer's lease."""
    async def _inner():
        db = _FakeDb()
        now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        await routes._try_acquire_cf_pull_lease(
            db, now=now, owner_id="replica-A", ttl_s=120,
        )
        # Replica-B's release is a no-op — must not touch A's lease.
        await routes._release_cf_pull_lease(db, owner_id="replica-B")
        assert _lease_doc(db)[routes.CF_PULL_LEASE_OWNER_FIELD] == "replica-A"
        # Replica-A releases properly → owner cleared, replica-B can
        # acquire on its next tick without waiting out the TTL.
        await routes._release_cf_pull_lease(db, owner_id="replica-A")
        assert _lease_doc(db)[routes.CF_PULL_LEASE_OWNER_FIELD] is None
        ok_b = await routes._try_acquire_cf_pull_lease(
            db, now=now + timedelta(seconds=1),
            owner_id="replica-B", ttl_s=120,
        )
        assert ok_b is True
        assert _lease_doc(db)[routes.CF_PULL_LEASE_OWNER_FIELD] == "replica-B"
    asyncio.run(_inner())


def test_acquire_cf_pull_lease_is_a_noop_when_db_is_none():
    """Defensive: if Mongo is unreachable at boot ``deps.db`` is None;
    the loop must back off gracefully rather than throw, otherwise the
    backend would die instead of just losing the CF pull until Mongo
    comes back."""
    async def _inner():
        ok = await routes._try_acquire_cf_pull_lease(None)
        assert ok is False
    asyncio.run(_inner())


def test_cursor_write_is_fenced_on_lease_owner(monkeypatch):
    """Fencing guard: if a slow GraphQL call returns AFTER the caller's
    lease has been taken over by a peer, the late cursor write must
    NOT clobber the new owner's cursor. Same hazard the reviewer
    flagged on Task #947 — without this, a slow tick could rewind the
    cursor and trigger duplicate ingest of an already-pulled window.
    """
    async def _inner():
        dao._reset_backend_shipper_for_tests()
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)

        async def fake_graphql(query, variables):
            return {"data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [
                {"dimensions": {
                    "datetimeMinute": "2026-04-26T10:00:00Z",
                    "edgeResponseStatus": 200, "cacheStatus": "HIT",
                    "clientRequestPath": "/", "clientRequestHTTPMethodName": "GET",
                    "clientRequestHTTPHost": "syrabit.ai",
                    "clientCountryName": "IN", "coloCode": "BLR"},
                 "avg": {}, "count": 1},
            ]}]}}}

        # Peer-B currently holds the lease + has already advanced the
        # cursor to a "newer" timestamp.
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_LEASE_OWNER_FIELD: "peer-B",
            routes.CF_PULL_CURSOR_FIELD: "2026-04-26T11:00:00+00:00",
            "updated_at": "2026-04-26T11:00:00+00:00",
        })
        # Stale leader-A's slow pull finally returns and tries to write
        # back its cursor while fencing on its own (now-defunct) lease.
        now = datetime(2026, 4, 26, 10, 5, tzinfo=timezone.utc)
        res = await routes._try_run_cf_pull_once(
            now_utc=now, graphql_callable=fake_graphql,
            lease_owner="leader-A",
        )
        assert res["ok"] is True  # the pull itself succeeded
        # …but the cursor must STILL belong to peer-B's view of the
        # world. Leader-A's stale write was filtered out by the
        # `lease_owner` predicate on update_one.
        doc = next(d for d in db.job_locks.docs
                   if d.get("_id") == routes.CF_PULL_LOCK_ID)
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "peer-B"
        assert doc[routes.CF_PULL_CURSOR_FIELD] == "2026-04-26T11:00:00+00:00"
    asyncio.run(_inner())


def test_pull_loop_releases_lease_when_cancelled_during_sleep(monkeypatch):
    """Regression for the most likely shutdown race: SIGTERM lands
    while the loop is parked in its post-tick ``asyncio.sleep`` (the
    state it spends ~95% of its life in). The outer ``try/finally``
    must still run ``_release_cf_pull_lease`` so a peer can take over
    on its next follower tick — without this fix the lease lingers
    until full TTL and the "clean handover" criterion of Task #947
    silently fails in production.
    """
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        # Pre-seed the lease as held by us so the loop's first tick
        # immediately enters the "leader" path → completes the GraphQL
        # call → drops into the outer sleep, where we'll cancel it.
        # Skip the GraphQL path entirely by stubbing
        # _try_run_cf_pull_once to a no-op success.
        async def fake_pull(now_utc=None, lease_owner=None, **_):
            return {"ok": True, "accepted": 0, "dropped": 0,
                    "since": "x", "until": "y"}
        monkeypatch.setattr(routes, "_try_run_cf_pull_once", fake_pull)
        # Skip the 30s warmup and shorten intervals so the test runs
        # in milliseconds, not seconds.
        orig_sleep = asyncio.sleep
        async def fast_sleep(delay):
            # First call is the 30s warmup → make it instant. Once the
            # loop is past warmup, normal sleeps stay normal so the
            # test can cancel mid-sleep.
            await orig_sleep(0)
        monkeypatch.setattr(routes.asyncio, "sleep", fast_sleep)
        # Kick the loop. After it's clearly past warmup + first tick
        # (one event-loop turn is enough with our fast_sleep), cancel.
        task = asyncio.create_task(routes._unified_logs_cf_pull_loop())
        # Yield enough turns for: warmup sleep → acquire lease →
        # fake_pull → enter outer sleep.
        for _ in range(20):
            await orig_sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # The lease doc should have its owner cleared (CAS scoped
        # release). If the bug regressed, owner would still be set to
        # _CF_PULL_LEASE_OWNER_ID.
        doc = next((d for d in db.job_locks.docs
                    if d.get("_id") == routes.CF_PULL_LOCK_ID), None)
        assert doc is not None, "lease doc should have been created"
        assert doc.get(routes.CF_PULL_LEASE_OWNER_FIELD) is None, (
            "lease must be released on cancellation, even when "
            "cancellation lands during asyncio.sleep"
        )
    asyncio.run(_inner())


# ─── Task #948 — adaptive window subdivision (no dropped buckets) ────


def _make_cf_group(minute_iso: str, idx: int) -> dict:
    """Synthesize a unique CF httpRequestsAdaptiveGroups row.

    ``idx`` varies one of the dimensions so each row gets a distinct
    deterministic id (otherwise the dedup in insert_logs would mask
    pagination bugs by collapsing the rows back down).
    """
    return {
        "dimensions": {
            "datetimeMinute": minute_iso,
            "edgeResponseStatus": 200,
            "originResponseStatus": 200,
            "cacheStatus": "HIT",
            "clientRequestPath": f"/api/r/{idx}",
            "clientRequestHTTPMethodName": "GET",
            "clientRequestHTTPHost": "syrabit.ai",
            "clientCountryName": "IN",
            "coloCode": "BLR",
        },
        "avg": {"originResponseDurationMs": 10.0},
        "count": 1,
    }


def test_paginated_pull_does_nothing_when_window_under_limit(monkeypatch):
    """Common-case: a quiet window returns < limit rows in a single
    GraphQL call. The pagination machinery must NOT subdivide just
    because it can — that would multiply the API quota cost on every
    tick of every quiet hour."""
    async def _inner():
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        calls = []

        async def fake_graphql(query, variables):
            calls.append((variables["since"], variables["until"]))
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": [
                    _make_cf_group("2026-04-26T10:00:00Z", 0),
                    _make_cf_group("2026-04-26T10:01:00Z", 1),
                ]
            }]}}}

        since = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        until = datetime(2026, 4, 26, 10, 5, tzinfo=timezone.utc)
        out = await routes._pull_cf_window_paginated(fake_graphql, since, until)
        assert out["calls"] == 1
        assert out["subdivisions"] == 0
        assert out["saturated_windows"] == []
        assert len(out["rows"]) == 2
        assert len(calls) == 1
    asyncio.run(_inner())


def test_paginated_pull_subdivides_when_window_hits_limit(monkeypatch):
    """Critical Task #948 path: when the limit is hit, the window MUST
    be split on a minute boundary and each half pulled separately so
    the surplus buckets aren't silently dropped by CF."""
    async def _inner():
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        # Force a low limit so we don't have to fabricate 200 fake rows.
        monkeypatch.setattr(routes, "CF_PULL_LIMIT", 4, raising=False)

        calls = []

        async def fake_graphql(query, variables):
            since_iso = variables["since"]
            until_iso = variables["until"]
            calls.append((since_iso, until_iso))
            since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
            until_dt = datetime.fromisoformat(until_iso.replace("Z", "+00:00"))
            span_min = int((until_dt - since_dt).total_seconds() // 60)
            # The full 4-minute window saturates at the cap. Each half
            # (2-minute) returns 2 rows — plenty of headroom — so the
            # recursion stops after a single split.
            if span_min >= 4:
                rows = [_make_cf_group(
                    since_iso.replace("Z", "+00:00"), i) for i in range(4)]
            else:
                rows = [_make_cf_group(
                    since_iso.replace("Z", "+00:00"), 100 + i)
                    for i in range(2)]
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": rows,
            }]}}}

        since = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        until = datetime(2026, 4, 26, 10, 4, tzinfo=timezone.utc)
        out = await routes._pull_cf_window_paginated(fake_graphql, since, until)
        # 1 saturated parent call + 2 half-window calls = 3 total.
        assert out["calls"] == 3, calls
        assert out["subdivisions"] == 1
        assert out["saturated_windows"] == []
        # Rows from the two halves should be merged AND distinct —
        # this is the bug Task #948 fixes (previously the surplus
        # was dropped wholesale. The two halves cover disjoint
        # minute buckets, so their per-row deterministic ids must
        # differ and the merged set must have all 4 rows (2 per
        # half), NOT just 2 (parent-only) or 0 (lost).
        ids = {routes.normalize_cf_http_request_row(r)["_id"]
               for r in out["rows"]}
        assert len(ids) == 4, (
            f"expected 4 distinct rows after split (2 per half), "
            f"got {len(ids)}: {ids}")
    asyncio.run(_inner())


def test_paginated_pull_recurses_until_floor_then_logs_saturation(monkeypatch):
    """Pathological window: every minute bucket has ≥ limit distinct
    (path, status, ...) combos. The recursion must NOT loop forever —
    it bottoms out at CF_PULL_MIN_WINDOW_S and surfaces the affected
    minutes via ``saturated_windows`` so an operator can react."""
    async def _inner():
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr(routes, "CF_PULL_LIMIT", 2, raising=False)

        async def fake_graphql(query, variables):
            # Every single window — no matter how small — returns at
            # the cap. Simulates an extremely-busy zone.
            since_iso = variables["since"]
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": [
                    _make_cf_group(since_iso.replace("Z", "+00:00"), 0),
                    _make_cf_group(since_iso.replace("Z", "+00:00"), 1),
                ],
            }]}}}

        since = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        until = datetime(2026, 4, 26, 10, 4, tzinfo=timezone.utc)
        out = await routes._pull_cf_window_paginated(fake_graphql, since, until)
        # The full window subdivides 4m → 2m → 1m on each branch.
        # We MUST end up with at least one saturated_windows entry per
        # minute that hit the floor; the exact number depends on the
        # split tree, but it must be > 0 (else the bug regressed).
        assert out["saturated_windows"], (
            "minute-granularity saturation must be reported, otherwise "
            "operators cannot tell that buckets were lost")
        # Every saturated entry must be a 1-minute span (the floor).
        for since_iso, until_iso in out["saturated_windows"]:
            s = datetime.fromisoformat(since_iso)
            u = datetime.fromisoformat(until_iso)
            assert (u - s).total_seconds() <= routes.CF_PULL_MIN_WINDOW_S
        # The recursion must terminate (Task #948's hard guard) — if
        # CF_PULL_MAX_SUBDIVISIONS were missing this test would hang.
        assert out["calls"] > 0
    asyncio.run(_inner())


def test_try_run_cf_pull_once_persists_pagination_telemetry(monkeypatch):
    """End-to-end: when a pull subdivides, the cursor doc must record
    last_calls / last_subdivisions / last_saturated_windows so the
    admin /status endpoint can show the operator what happened on
    that tick — without these fields, busy-hour bucket loss would
    be invisible from the dashboard."""
    async def _inner():
        dao._reset_backend_shipper_for_tests()
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)
        monkeypatch.setattr(routes, "CF_PULL_LIMIT", 4, raising=False)

        async def fake_graphql(query, variables):
            since_iso = variables["since"]
            since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
            until_dt = datetime.fromisoformat(
                variables["until"].replace("Z", "+00:00"))
            span_min = int((until_dt - since_dt).total_seconds() // 60)
            if span_min >= 4:
                rows = [_make_cf_group(
                    since_iso.replace("Z", "+00:00"), i) for i in range(4)]
            else:
                rows = [_make_cf_group(
                    since_iso.replace("Z", "+00:00"), 100 + i)
                    for i in range(2)]
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": rows,
            }]}}}

        now = datetime(2026, 4, 26, 10, 4, tzinfo=timezone.utc)
        # Seed the cursor 4 minutes back so the window saturates.
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD: "2026-04-26T10:00:00+00:00",
        })
        res = await routes._try_run_cf_pull_once(
            now_utc=now, graphql_callable=fake_graphql)
        assert res["ok"] is True
        # Fan-out telemetry must travel back in the result for the
        # manual-pull admin endpoint.
        assert res["calls"] >= 2
        assert res["subdivisions"] >= 1
        # …and must be persisted to the cursor doc for /status.
        lock = next(d for d in db.job_locks.docs
                    if d.get("_id") == routes.CF_PULL_LOCK_ID)
        assert lock["last_calls"] == res["calls"]
        assert lock["last_subdivisions"] == res["subdivisions"]
        assert lock["last_saturated_windows"] == res["saturated_windows"]
    asyncio.run(_inner())


def test_pull_loop_handover_when_leader_is_cancelled(monkeypatch):
    """Integration-style: simulate the Railway "scale down by 1"
    sequence — leader replica's loop is cancelled (SIGTERM ⇒ asyncio
    cancellation), it must release the lease so the peer replica can
    take over on its NEXT follower tick instead of waiting out the
    full ``CF_PULL_LEASE_TTL_S``. This is the round-trip Task #947's
    "Replicas hand the lease over cleanly when one is restarted/scaled
    down" acceptance criterion describes.
    """
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        # Leader-A claims the lease.
        await routes._try_acquire_cf_pull_lease(
            db, owner_id="leader-A", ttl_s=120,
        )
        doc = next(d for d in db.job_locks.docs
                   if d.get("_id") == routes.CF_PULL_LOCK_ID)
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "leader-A"
        # Peer-B sees the lease still held by A → cannot acquire.
        ok_b = await routes._try_acquire_cf_pull_lease(
            db, owner_id="peer-B", ttl_s=120,
        )
        assert ok_b is False
        # Now leader-A is cancelled → release runs.
        await routes._release_cf_pull_lease(db, owner_id="leader-A")
        # Peer-B retries IMMEDIATELY on its next follower tick (not
        # waiting out the 120s TTL) and wins.
        ok_b = await routes._try_acquire_cf_pull_lease(
            db, owner_id="peer-B", ttl_s=120,
        )
        assert ok_b is True
        doc = next(d for d in db.job_locks.docs
                   if d.get("_id") == routes.CF_PULL_LOCK_ID)
        assert doc[routes.CF_PULL_LEASE_OWNER_FIELD] == "peer-B"
    asyncio.run(_inner())
