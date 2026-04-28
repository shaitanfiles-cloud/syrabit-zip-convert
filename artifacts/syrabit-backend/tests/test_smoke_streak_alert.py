"""Task #565 — alert when the publish→IndexNow smoke fails for two
consecutive UTC days.

The new evaluator (`_evaluate_smoke_failure_streak` /
`_maybe_dispatch_smoke_streak_alert` in `routes.bot_discovery`) walks
the persisted `indexnow_smoke_log` collection and dispatches a single
consolidated alert via `metrics._dispatch_alert` when *every* day in
the look-back window has at least one failed run and zero successes.
This file pins down four behaviours we don't want to regress:

1. A clean 2-day failure streak triggers exactly one alert.
2. A successful run inside the window breaks the streak (no alert).
3. A day with zero recorded runs breaks the streak (no false-positive
   alerts when the cron simply didn't run).
4. The 24-hour cooldown prevents the streak alert from re-firing on
   every cron tick.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List
from unittest.mock import AsyncMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _run(coro):
    return asyncio.run(coro)


class _FakeCursor:
    def __init__(self, docs: Iterable[dict]):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return list(self._docs) if length is None else list(self._docs)[:length]


class _FakeSmokeLog:
    def __init__(self, docs: List[dict]):
        self._docs = docs

    def find(self, query=None, _proj=None):
        if not query:
            return _FakeCursor(self._docs)
        rng = (query or {}).get("ran_at") or {}
        gte = rng.get("$gte")
        lt = rng.get("$lt")
        # The production query also carries an ``$or`` clause that excludes
        # rows whose ``skipped_reason`` is set (so quiet "no_publish_today"
        # runs don't pollute the streak window). Honour it here so tests can
        # mix skipped + real rows on the same day.
        or_clauses = (query or {}).get("$or")
        out = []
        for d in self._docs:
            ts = d.get("ran_at")
            if gte is not None and ts < gte:
                continue
            if lt is not None and ts >= lt:
                continue
            if or_clauses:
                sr = d.get("skipped_reason")
                # Skipped row → not match the "skipped_reason missing/None/empty"
                # disjunction → drop.
                if sr is not None and sr != "":
                    continue
            out.append(d)
        return _FakeCursor(out)


def _install_db(docs: List[dict]) -> Any:
    import deps
    deps.db.indexnow_smoke_log = _FakeSmokeLog(docs)

    async def _ok():
        return True
    deps.is_mongo_available = _ok
    return deps.db


def _utc_day(days_ago: int, hour: int = 12) -> datetime:
    today = datetime.now(timezone.utc).date()
    d = today - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)


def _row(days_ago: int, ok: bool, *, url: str = "https://syrabit.ai/x", error=None) -> dict:
    return {
        "ran_at": _utc_day(days_ago),
        "ok": ok,
        "url": url,
        "error": error,
    }


def _reset_cooldown():
    from routes import bot_discovery as bd
    bd._SMOKE_STREAK_ALERT_LAST_FIRED["ts"] = 0.0


def test_streak_alert_fires_on_two_failed_days():
    # Today + yesterday both failed → trip the alert on day 2 itself.
    _install_db([
        _row(0, ok=False, url="https://syrabit.ai/p1", error="404"),
        _row(1, ok=False, url="https://syrabit.ai/p2", error="500"),
    ])
    _reset_cooldown()
    from routes import bot_discovery as bd

    breakdown = _run(bd._evaluate_smoke_failure_streak())
    assert breakdown is not None, "two failed days should match the streak"
    assert breakdown["threshold_days"] == 2
    per_day = breakdown["per_day"]
    assert all(b["passes"] == 0 for b in per_day.values())
    assert all(b["failures"] >= 1 for b in per_day.values())

    fake_dispatch = AsyncMock()
    import metrics
    real = getattr(metrics, "_dispatch_alert", None)
    metrics._dispatch_alert = fake_dispatch
    try:
        fired = _run(bd._maybe_dispatch_smoke_streak_alert())
    finally:
        if real is not None:
            metrics._dispatch_alert = real

    assert fired is True
    fake_dispatch.assert_awaited_once()
    args, kwargs = fake_dispatch.call_args
    assert args[0] == "publish_indexnow_smoke_streak_failed"
    body = args[2]
    # Day breakdown + admin path link both appear in the consolidated body.
    assert "Day breakdown" in body
    assert "/admin" in body
    snap = kwargs.get("threshold_snapshot") or {}
    assert snap.get("metric") == "publish_indexnow_smoke_streak"


def test_streak_alert_skipped_when_a_day_has_a_pass():
    _install_db([
        _row(0, ok=False),
        _row(1, ok=False),
        _row(1, ok=True),  # one pass on day -1 → streak broken
    ])
    _reset_cooldown()
    from routes import bot_discovery as bd
    assert _run(bd._evaluate_smoke_failure_streak()) is None


def test_streak_alert_skipped_on_same_day_recovery():
    # Today's earlier run failed but a later run on the *same* UTC day
    # passed → the streak must reset immediately, not wait until the
    # next day.
    _install_db([
        _row(0, ok=False, url="https://syrabit.ai/p1", error="503"),
        {**_row(0, ok=True), "ran_at": _utc_day(0, hour=18)},
        _row(1, ok=False),
    ])
    _reset_cooldown()
    from routes import bot_discovery as bd
    assert _run(bd._evaluate_smoke_failure_streak()) is None


def test_streak_alert_skipped_when_a_day_has_no_runs():
    # Only today has any records; yesterday is empty → not an active streak.
    _install_db([_row(0, ok=False)])
    _reset_cooldown()
    from routes import bot_discovery as bd
    assert _run(bd._evaluate_smoke_failure_streak()) is None


def test_streak_alert_fires_when_failed_day_also_has_skipped_runs():
    """Task #988 — quiet smoke runs (``skipped_reason`` set) must NOT
    mask an actively-failing day.

    The architect-flagged regression was: a day where the smoke ALSO
    happened to log a "no published page today" skipped row alongside
    a real failure was being treated as having a "passing" run, which
    silently broke the streak even though the chain was genuinely
    broken. The fix filters skipped rows out at the query level so the
    failed row stands alone and the day still counts as a failure day.

    Scenario: today + yesterday both have a failed smoke run, AND each
    day also has a later skipped (quiet) row. The streak alert must
    still fire.
    """
    docs = [
        # Today — early failure, later quiet skip.
        _row(0, ok=False, url="https://syrabit.ai/p1", error="503"),
        {**_row(0, ok=True), "ran_at": _utc_day(0, hour=18),
         "skipped_reason": "no_publish_today"},
        # Yesterday — same shape: a failure plus a later skipped row.
        _row(1, ok=False, url="https://syrabit.ai/p2", error="500"),
        {**_row(1, ok=True), "ran_at": _utc_day(1, hour=20),
         "skipped_reason": "no_publish_today"},
    ]
    _install_db(docs)
    _reset_cooldown()
    from routes import bot_discovery as bd

    breakdown = _run(bd._evaluate_smoke_failure_streak())
    assert breakdown is not None, (
        "skipped/quiet rows must be filtered so a failed day still "
        "counts toward the streak"
    )
    per_day = breakdown["per_day"]
    # Both days should register exactly one failure (the skipped rows
    # are dropped at the query layer, so they don't show up as passes).
    assert all(b["passes"] == 0 for b in per_day.values()), (
        "skipped rows must not be counted as passes"
    )
    assert all(b["failures"] == 1 for b in per_day.values())
    assert breakdown["failure_days"] == 2


def test_streak_alert_respects_cooldown():
    _install_db([
        _row(0, ok=False),
        _row(1, ok=False),
    ])
    _reset_cooldown()
    from routes import bot_discovery as bd

    fake_dispatch = AsyncMock()
    import metrics
    real = getattr(metrics, "_dispatch_alert", None)
    metrics._dispatch_alert = fake_dispatch
    try:
        first = _run(bd._maybe_dispatch_smoke_streak_alert())
        second = _run(bd._maybe_dispatch_smoke_streak_alert())
    finally:
        if real is not None:
            metrics._dispatch_alert = real

    assert first is True
    assert second is False, "cooldown should block the second dispatch"
    assert fake_dispatch.await_count == 1
