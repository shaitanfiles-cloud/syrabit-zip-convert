"""Task #953 — rolling 24h pagination-cost aggregate tests.

Pins three contracts:
  1. ``_compute_cf_pull_24h_aggregate`` returns the right totals/max/%
     for a multi-tick history, drops entries older than the 24h window,
     and gracefully handles malformed entries / empty history.
  2. ``_try_run_cf_pull_once`` actually persists an entry to
     ``cf_pull_history`` on the cursor doc each tick (so the widget
     has data to render).
  3. The ``/api/admin/logs/status`` payload exposes ``cf_pull_24h``
     when the cursor doc has history, and ``None`` when it doesn't —
     so a fresh deploy hides the widget instead of rendering "0/0/0".
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from routes import admin_logs as routes
from tests.test_unified_logs_dao import _FakeDb


# ─────────────────────────────────────────────────────────────────────────────
# A. Aggregate helper
# ─────────────────────────────────────────────────────────────────────────────

def test_aggregate_empty_history_returns_none():
    assert routes._compute_cf_pull_24h_aggregate([]) is None
    assert routes._compute_cf_pull_24h_aggregate(None) is None


def test_aggregate_drops_entries_older_than_24h():
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    history = [
        # > 24h old — must be dropped
        {"ts": (now - timedelta(hours=25)).isoformat(),
         "calls": 999, "subdivisions": 99, "saturated": 9},
        # exactly 23h old — kept
        {"ts": (now - timedelta(hours=23)).isoformat(),
         "calls": 1, "subdivisions": 0, "saturated": 0},
        # 1h old — kept
        {"ts": (now - timedelta(hours=1)).isoformat(),
         "calls": 5, "subdivisions": 2, "saturated": 0},
    ]
    agg = routes._compute_cf_pull_24h_aggregate(history, now=now)
    assert agg is not None
    assert agg["ticks"] == 2
    # The 25h-old huge entry must NOT contribute.
    assert agg["total_calls"] == 6
    assert agg["total_subdivisions"] == 2
    assert agg["max_calls"] == 5
    assert agg["max_subdivisions"] == 2


def test_aggregate_computes_subdivided_pct_and_max():
    """5 ticks: 2 paginated. Aggregate must show 40.0% subdivided and
    correctly identify the worst tick's call/subdivision counts."""
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    history = [
        {"ts": (now - timedelta(minutes=m)).isoformat(),
         "calls": calls, "subdivisions": subs, "saturated": sat}
        for m, calls, subs, sat in [
            (1,  1, 0, 0),  # quiet
            (2,  1, 0, 0),  # quiet
            (3,  1, 0, 0),  # quiet
            (4,  8, 3, 0),  # paginated
            (5, 50, 6, 2),  # paginated AND lost data
        ]
    ]
    agg = routes._compute_cf_pull_24h_aggregate(history, now=now)
    assert agg["ticks"] == 5
    assert agg["total_calls"] == 61
    assert agg["total_subdivisions"] == 9
    assert agg["total_saturated"] == 2
    assert agg["max_calls"] == 50
    assert agg["max_subdivisions"] == 6
    assert agg["subdivided_ticks"] == 2
    assert agg["subdivided_pct"] == 40.0


def test_aggregate_tolerates_malformed_entries():
    """A corrupted entry (bad ts, wrong type) must NOT crash the
    helper or skew the aggregate — it's silently dropped so the
    dashboard can still render."""
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    history = [
        "not-a-dict",                                          # wrong type
        {"ts": "garbage", "calls": 999},                       # bad ts
        {"ts": None, "calls": 999},                            # None ts
        {"ts": (now - timedelta(minutes=1)).isoformat(),       # good
         "calls": 3, "subdivisions": 1, "saturated": 0},
    ]
    agg = routes._compute_cf_pull_24h_aggregate(history, now=now)
    assert agg is not None
    assert agg["ticks"] == 1
    assert agg["total_calls"] == 3
    assert agg["total_subdivisions"] == 1


def test_aggregate_window_s_reflects_actual_span_not_full_24h():
    """A fresh deploy with only 30 minutes of history should report
    window_s ≈ 1800, so the dashboard can label it "~1h" rather than
    misleadingly suggesting 24h of data."""
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    history = [
        {"ts": (now - timedelta(minutes=30)).isoformat(),
         "calls": 1, "subdivisions": 0, "saturated": 0},
        {"ts": (now - timedelta(minutes=1)).isoformat(),
         "calls": 1, "subdivisions": 0, "saturated": 0},
    ]
    agg = routes._compute_cf_pull_24h_aggregate(history, now=now)
    assert agg["ticks"] == 2
    # 29 minutes between oldest and newest
    assert 1700 <= agg["window_s"] <= 1800


# ─────────────────────────────────────────────────────────────────────────────
# B. _try_run_cf_pull_once persists rolling history
# ─────────────────────────────────────────────────────────────────────────────

def _make_cf_group(minute_iso: str, idx: int) -> dict:
    """Minimal CF GraphQL row shaped like httpRequestsAdaptiveGroups."""
    return {
        "dimensions": {
            "datetimeMinute": minute_iso,
            "edgeResponseStatus": 200,
            "originResponseStatus": 200,
            "cacheStatus": "HIT",
            "clientRequestPath": f"/x/{idx}",
            "clientRequestHTTPMethodName": "GET",
            "clientRequestHTTPHost": "syrabit.ai",
            "clientCountryName": "IN",
            "coloCode": "BLR",
        },
        "avg": {"originResponseDurationMs": 12.0},
        "count": 1,
    }


def test_try_run_cf_pull_once_appends_to_cf_pull_history(monkeypatch):
    """A successful tick must append exactly one entry to the rolling
    cf_pull_history list on the cursor doc, with the right shape."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)

        async def fake_graphql(query, variables):
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": [
                    _make_cf_group("2026-04-26T10:00:00+00:00", 0),
                ],
            }]}}}

        # Seed the cursor 1 minute back so we have a small window to pull.
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD: "2026-04-26T10:00:00+00:00",
        })
        now = datetime(2026, 4, 26, 10, 1, tzinfo=timezone.utc)
        res = await routes._try_run_cf_pull_once(
            now_utc=now, graphql_callable=fake_graphql)
        assert res["ok"] is True

        lock = next(d for d in db.job_locks.docs
                    if d.get("_id") == routes.CF_PULL_LOCK_ID)
        history = lock.get("cf_pull_history")
        assert isinstance(history, list)
        assert len(history) == 1
        entry = history[0]
        assert entry["ts"] == now.isoformat()
        assert entry["calls"] == res["calls"]
        assert entry["subdivisions"] == res["subdivisions"]
        assert entry["saturated"] == len(res["saturated_windows"])
    asyncio.run(_inner())


def test_try_run_cf_pull_once_keeps_old_entries_in_raw_history_but_aggregate_filters_them(monkeypatch):
    """Task #961 — write-time pruning was dropped in favour of an
    atomic ``$push`` + ``$slice``. Old (>24h) entries therefore stay
    in the raw cursor doc until they age out of the size cap, but
    ``_compute_cf_pull_24h_aggregate`` already filters them at read
    time so the dashboard never shows stale-window data."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)

        async def fake_graphql(query, variables):
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": [
                    _make_cf_group("2026-04-26T10:00:00+00:00", 0),
                ],
            }]}}}

        now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
        old_ts = (now - timedelta(hours=25)).isoformat()
        recent_ts = (now - timedelta(hours=1)).isoformat()
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD: (now - timedelta(minutes=2)).isoformat(),
            "cf_pull_history": [
                {"ts": old_ts,    "calls": 999, "subdivisions": 99, "saturated": 9},
                {"ts": recent_ts, "calls":   2, "subdivisions":  1, "saturated": 0},
            ],
        })
        res = await routes._try_run_cf_pull_once(
            now_utc=now, graphql_callable=fake_graphql)
        assert res["ok"] is True

        lock = next(d for d in db.job_locks.docs
                    if d.get("_id") == routes.CF_PULL_LOCK_ID)
        history = lock["cf_pull_history"]
        # All three entries (old + recent + this-tick) are present in
        # the raw list — the size cap, not a time filter, bounds it.
        ts_set = {e["ts"] for e in history}
        assert old_ts in ts_set
        assert recent_ts in ts_set
        assert now.isoformat() in ts_set
        assert len(history) == 3
        # But the aggregate filters the >24h entry out at read time:
        agg = routes._compute_cf_pull_24h_aggregate(history, now=now)
        assert agg is not None
        assert agg["ticks"] == 2  # only the in-window entries count
        # The runaway 999 calls / 9 saturated from the stale entry
        # must NOT contaminate the trend the dashboard renders.
        assert agg["max_calls"] < 999
        assert agg["total_saturated"] == 0
    asyncio.run(_inner())


def test_try_run_cf_pull_once_atomic_push_does_not_lose_concurrent_appends(monkeypatch):
    """Task #961 — the previous implementation used a Python
    read-modify-write to append to ``cf_pull_history``, which meant a
    manual admin "run CF pull now" click during a normal background
    tick could stomp the leader's append (or vice versa). The atomic
    ``$push`` operator must let both writers' entries land. We
    simulate the race by interleaving two pulls' update_one calls
    around a yield point."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)

        # Seed the cursor so both pulls have a tiny non-empty window.
        now_a = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
        now_b = datetime(2026, 4, 26, 12, 0, 30, tzinfo=timezone.utc)
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD:
                (now_a - timedelta(minutes=1)).isoformat(),
        })

        # Each call resolves on its own asyncio event so we can
        # deterministically interleave the two pulls and force them
        # to read the same cursor doc state before either writes.
        gate_a = asyncio.Event()
        gate_b = asyncio.Event()
        call_order: list[str] = []

        async def fake_graphql_a(query, variables):
            call_order.append("a_graphql")
            # Wait for B to also have read the cursor before either
            # writes — this is the worst case for read-modify-write.
            await gate_a.wait()
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": [
                    _make_cf_group("2026-04-26T11:59:00+00:00", 0),
                ],
            }]}}}

        async def fake_graphql_b(query, variables):
            call_order.append("b_graphql")
            await gate_b.wait()
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": [
                    _make_cf_group("2026-04-26T11:59:30+00:00", 1),
                ],
            }]}}}

        task_a = asyncio.create_task(routes._try_run_cf_pull_once(
            now_utc=now_a, graphql_callable=fake_graphql_a))
        task_b = asyncio.create_task(routes._try_run_cf_pull_once(
            now_utc=now_b, graphql_callable=fake_graphql_b))

        # Give both pulls a chance to load the cursor doc and reach
        # their graphql await point before either is allowed to
        # finish and write.
        for _ in range(5):
            await asyncio.sleep(0)
        # Release A first, then B — both will write back with their
        # own ``$push``. Under the old read-modify-write, B's write
        # would clobber A's appended entry.
        gate_a.set()
        gate_b.set()
        res_a, res_b = await asyncio.gather(task_a, task_b)
        assert res_a["ok"] is True
        assert res_b["ok"] is True

        lock = next(d for d in db.job_locks.docs
                    if d.get("_id") == routes.CF_PULL_LOCK_ID)
        history = lock["cf_pull_history"]
        ts_set = {e["ts"] for e in history}
        # BOTH ticks' entries must be present — neither writer
        # silently lost its append to the other.
        assert now_a.isoformat() in ts_set, (
            f"writer A's entry missing; history={history}"
        )
        assert now_b.isoformat() in ts_set, (
            f"writer B's entry missing; history={history}"
        )
        assert len(history) == 2
    asyncio.run(_inner())


def test_try_run_cf_pull_once_caps_history_at_max_entries(monkeypatch):
    """Even with a bizarrely small interval that would keep more than
    CF_PULL_HISTORY_MAX_ENTRIES inside the 24h window, the list must
    be hard-capped so the cursor doc cannot blow up."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        monkeypatch.setattr("config.CF_ZONE_ID", "zone-1", raising=False)
        monkeypatch.setattr("config.CF_ANALYTICS_API_TOKEN", "tok", raising=False)
        # Shrink the cap so we don't have to seed thousands of entries.
        monkeypatch.setattr(routes, "CF_PULL_HISTORY_MAX_ENTRIES", 5,
                            raising=False)

        async def fake_graphql(query, variables):
            return {"data": {"viewer": {"zones": [{
                "httpRequestsAdaptiveGroups": [
                    _make_cf_group("2026-04-26T11:59:00+00:00", 0),
                ],
            }]}}}

        now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
        # Seed 7 recent entries (all within 24h).
        seed = [
            {"ts": (now - timedelta(minutes=m)).isoformat(),
             "calls": m, "subdivisions": 0, "saturated": 0}
            for m in range(2, 9)
        ]
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD: (now - timedelta(minutes=1)).isoformat(),
            "cf_pull_history": seed,
        })
        res = await routes._try_run_cf_pull_once(
            now_utc=now, graphql_callable=fake_graphql)
        assert res["ok"] is True

        lock = next(d for d in db.job_locks.docs
                    if d.get("_id") == routes.CF_PULL_LOCK_ID)
        history = lock["cf_pull_history"]
        assert len(history) == 5
        # The most recent entry (this tick) must be present; the
        # oldest seeded entries must be the ones that got trimmed.
        assert history[-1]["ts"] == now.isoformat()
    asyncio.run(_inner())


# ─────────────────────────────────────────────────────────────────────────────
# C. /api/admin/logs/status surfaces cf_pull_24h
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_logs_status_exposes_cf_pull_24h_when_history_present(monkeypatch):
    """End-to-end: when the cursor doc has rolling history, the
    /status payload must contain a populated ``cf_pull_24h`` block
    so the dashboard widget renders."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        from unified_logs_dao import get_backend_shipper, _reset_backend_shipper_for_tests
        _reset_backend_shipper_for_tests()

        now = datetime.now(timezone.utc)
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD: now.isoformat(),
            "updated_at": now.isoformat(),
            "cf_pull_history": [
                {"ts": (now - timedelta(minutes=2)).isoformat(),
                 "calls": 1, "subdivisions": 0, "saturated": 0},
                {"ts": (now - timedelta(minutes=1)).isoformat(),
                 "calls": 7, "subdivisions": 3, "saturated": 1},
            ],
        })
        # Bypass the admin-auth dependency.
        payload = await routes.admin_logs_status(admin={"id": "test"})
        assert "cf_pull_24h" in payload
        agg = payload["cf_pull_24h"]
        assert agg is not None
        assert agg["ticks"] == 2
        assert agg["total_calls"] == 8
        assert agg["total_subdivisions"] == 3
        assert agg["max_calls"] == 7
        assert agg["max_subdivisions"] == 3
        assert agg["total_saturated"] == 1
        assert agg["subdivided_pct"] == 50.0
    asyncio.run(_inner())


def test_admin_logs_status_returns_none_for_cf_pull_24h_on_fresh_deploy(monkeypatch):
    """On a brand-new deploy (no cursor doc yet), ``cf_pull_24h`` must
    be None so the UI hides the widget instead of rendering a
    misleading "0 calls / 0 subdivisions" row."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        from unified_logs_dao import _reset_backend_shipper_for_tests
        _reset_backend_shipper_for_tests()

        payload = await routes.admin_logs_status(admin={"id": "test"})
        assert "cf_pull_24h" in payload
        assert payload["cf_pull_24h"] is None
    asyncio.run(_inner())


# ─────────────────────────────────────────────────────────────────────────────
# D. Task #960 — per-tick sparkline payload
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_history_recent_returns_none_for_empty_or_all_stale():
    """No usable entries → None so the UI hides the sparkline rather
    than rendering an empty chart."""
    assert routes._extract_cf_pull_history_recent([]) is None
    assert routes._extract_cf_pull_history_recent(None) is None
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    stale = [
        {"ts": (now - timedelta(hours=25)).isoformat(),
         "calls": 3, "subdivisions": 1, "saturated": 0},
    ]
    assert routes._extract_cf_pull_history_recent(stale, now=now) is None


def test_extract_history_recent_filters_24h_and_sorts_oldest_first():
    """The sparkline must plot left-to-right by time and exclude
    entries older than the 24h aggregation window — otherwise a stale
    spike from 25h ago would falsely appear as "recent drift"."""
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    history = [
        # Out of order on purpose to exercise the sort.
        {"ts": (now - timedelta(hours=1)).isoformat(),
         "calls": 5, "subdivisions": 2, "saturated": 0},
        {"ts": (now - timedelta(hours=25)).isoformat(),
         "calls": 999, "subdivisions": 99, "saturated": 9},  # stale → dropped
        {"ts": (now - timedelta(hours=2)).isoformat(),
         "calls": 1, "subdivisions": 0, "saturated": 0},
    ]
    out = routes._extract_cf_pull_history_recent(history, now=now)
    assert out is not None
    assert len(out) == 2
    assert out[0]["calls"] == 1     # 2h-old entry first (oldest)
    assert out[1]["calls"] == 5     # 1h-old entry last (newest)
    # Stale entry's runaway numbers must NOT leak into the sparkline.
    assert all(p["calls"] != 999 for p in out)
    # Each datapoint exposes exactly the fields the frontend needs.
    for p in out:
        assert set(p.keys()) == {"ts", "calls", "subdivisions", "saturated"}


def test_extract_history_recent_coerces_malformed_numeric_fields_to_zero():
    """Forwards-compat guard: a stray string / float / negative value in
    the persisted telemetry must not crash the dashboard render path —
    bad fields silently coerce to 0 so the rest of the trend still
    plots correctly."""
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    history = [
        {"ts": (now - timedelta(minutes=3)).isoformat(),
         "calls": "abc", "subdivisions": None, "saturated": -7},
        {"ts": (now - timedelta(minutes=2)).isoformat(),
         "calls": 12.7, "subdivisions": "2", "saturated": 0},
        {"ts": (now - timedelta(minutes=1)).isoformat(),
         "calls": 5, "subdivisions": 1, "saturated": 0},
    ]
    out = routes._extract_cf_pull_history_recent(history, now=now)
    assert out is not None
    assert len(out) == 3
    # Garbage row → all zeros, but still emitted (so the time axis on
    # the sparkline is contiguous).
    assert out[0]["calls"] == 0
    assert out[0]["subdivisions"] == 0
    assert out[0]["saturated"] == 0
    # Float coerces (truncates) to int; numeric string parses normally.
    assert out[1]["calls"] == 12
    assert out[1]["subdivisions"] == 2
    # Healthy row unchanged.
    assert out[2]["calls"] == 5


def test_extract_history_recent_caps_at_max_points_keeping_most_recent():
    """A nearly-full 24h history must be downsampled by trimming the
    oldest entries — the sparkline is for spotting RECENT drift, and
    the JSON payload should stay small even with a misconfigured
    sub-minute pull interval."""
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    # 200 entries, 1 minute apart, all within 24h.
    history = [
        {"ts": (now - timedelta(minutes=200 - i)).isoformat(),
         "calls": i, "subdivisions": 0, "saturated": 0}
        for i in range(200)
    ]
    out = routes._extract_cf_pull_history_recent(history, now=now, max_points=50)
    assert out is not None
    assert len(out) == 50
    # The most-recent 50 (by call count, since we used i as calls) must
    # be the ones kept — if the cap silently trimmed the new end, the
    # operator would be looking at a 4h-stale chart.
    assert out[0]["calls"] == 150
    assert out[-1]["calls"] == 199


def test_admin_logs_status_exposes_cf_pull_history_recent_when_present(monkeypatch):
    """End-to-end: when the cursor doc has rolling history, the /status
    payload must surface ``cf_pull_history_recent`` alongside the
    aggregate so the dashboard sparkline can render."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        from unified_logs_dao import _reset_backend_shipper_for_tests
        _reset_backend_shipper_for_tests()

        now = datetime.now(timezone.utc)
        db.job_locks.docs.append({
            "_id": routes.CF_PULL_LOCK_ID,
            routes.CF_PULL_CURSOR_FIELD: now.isoformat(),
            "updated_at": now.isoformat(),
            "cf_pull_history": [
                {"ts": (now - timedelta(minutes=2)).isoformat(),
                 "calls": 1, "subdivisions": 0, "saturated": 0},
                {"ts": (now - timedelta(minutes=1)).isoformat(),
                 "calls": 7, "subdivisions": 3, "saturated": 1},
            ],
        })
        payload = await routes.admin_logs_status(admin={"id": "test"})
        assert "cf_pull_history_recent" in payload
        recent = payload["cf_pull_history_recent"]
        assert isinstance(recent, list)
        assert len(recent) == 2
        # Oldest first so the sparkline plots left-to-right by time.
        assert recent[0]["calls"] == 1
        assert recent[1]["calls"] == 7
        assert recent[1]["subdivisions"] == 3
        assert recent[1]["saturated"] == 1
    asyncio.run(_inner())


def test_admin_logs_status_returns_none_for_cf_pull_history_recent_on_fresh_deploy(monkeypatch):
    """No cursor doc → ``cf_pull_history_recent`` is None so the UI
    hides the sparkline (and renders nothing instead of a blank chart)."""
    async def _inner():
        db = _FakeDb()
        monkeypatch.setattr(routes, "db", db, raising=False)
        from unified_logs_dao import _reset_backend_shipper_for_tests
        _reset_backend_shipper_for_tests()

        payload = await routes.admin_logs_status(admin={"id": "test"})
        assert "cf_pull_history_recent" in payload
        assert payload["cf_pull_history_recent"] is None
    asyncio.run(_inner())
