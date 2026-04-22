"""Tests for Task #656 — review-prompt CTR alert loop in
``routes/admin_review_prompts.py``. Mirrors the patterns in
``test_hydrate_alerting.py``: install the deps stub, patch
``deps.db`` / ``deps.is_mongo_available``, and exercise the pure-ish
helpers (``_gather_review_prompt_alert_window``,
``_evaluate_review_prompt_ctr_alerts``) without spinning up the asyncio
loop in production.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()
from routes import admin_review_prompts as arp  # noqa: E402


def _reset_cooldowns():
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()


def _fake_db(*, shown: int = 0, clicked: int = 0, dismissed: int = 0):
    """Build a fake ``db`` whose ``review_prompt_events.aggregate`` yields
    the same shape the gather helper consumes — one row per event type.
    """
    fake_db = MagicMock()

    class _AggCursor:
        def __init__(self, docs):
            self._docs = list(docs)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._docs:
                raise StopAsyncIteration
            return self._docs.pop(0)

    def _make_docs():
        return [
            {"_id": "review_prompt_shown", "count": shown},
            {"_id": "review_prompt_clicked", "count": clicked},
            {"_id": "review_prompt_dismissed", "count": dismissed},
        ]

    # Fresh cursor per call so the gather helper can be invoked multiple
    # times in the same test (cooldown / repeat-evaluation cases).
    fake_db.review_prompt_events.aggregate = MagicMock(
        side_effect=lambda *a, **kw: _AggCursor(_make_docs()),
    )
    return fake_db


# ------------- _gather_review_prompt_alert_window -------------

def test_gather_returns_zero_shape_when_mongo_unavailable():
    with patch.object(arp, "is_mongo_available", AsyncMock(return_value=False)):
        snap = asyncio.run(arp._gather_review_prompt_alert_window())
    assert snap["shown"] == 0
    assert snap["clicked"] == 0
    assert snap["dismissed"] == 0
    assert snap["ctr_pct"] is None


def test_gather_computes_ctr_pct():
    fake_db = _fake_db(shown=200, clicked=10, dismissed=40)
    with patch.object(arp, "db", fake_db), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        snap = asyncio.run(arp._gather_review_prompt_alert_window())
    assert snap["shown"] == 200
    assert snap["clicked"] == 10
    assert snap["dismissed"] == 40
    assert snap["ctr_pct"] == 5.0


def test_gather_ctr_none_when_no_shown():
    fake_db = _fake_db(shown=0, clicked=0)
    with patch.object(arp, "db", fake_db), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        snap = asyncio.run(arp._gather_review_prompt_alert_window())
    assert snap["ctr_pct"] is None


# ------------- _evaluate_review_prompt_ctr_alerts -------------

def test_no_alert_when_shown_below_minimum():
    """Sparse data (shown < min) must never page — preserves the floor of
    statistical relevance even if CTR is mathematically 0%."""
    _reset_cooldowns()
    fake_db = _fake_db(shown=arp.REVIEW_PROMPT_CTR_MIN_SHOWN - 1, clicked=0)
    with patch.object(arp, "db", fake_db), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(now_ts=1000.0))
    assert alerts == []


def test_no_alert_when_ctr_at_or_above_floor():
    _reset_cooldowns()
    # CTR == floor → not "below", so no alert.
    shown = arp.REVIEW_PROMPT_CTR_MIN_SHOWN * 2
    clicked = int(shown * arp.REVIEW_PROMPT_CTR_FLOOR_PCT / 100)
    fake_db = _fake_db(shown=shown, clicked=clicked)
    with patch.object(arp, "db", fake_db), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(now_ts=1000.0))
    assert alerts == []


def test_alert_fires_when_ctr_below_floor_and_enough_shown():
    _reset_cooldowns()
    shown = arp.REVIEW_PROMPT_CTR_MIN_SHOWN * 4
    clicked = 1  # tiny CTR — well below 5% floor
    fake_db = _fake_db(shown=shown, clicked=clicked)
    with patch.object(arp, "db", fake_db), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(now_ts=1000.0))
    assert len(alerts) == 1
    a = alerts[0]
    assert a["alert_type"] == "review_prompt_ctr_low"
    assert "writeReviewUrl" in a["body"]
    assert "/admin/dashboard" in a["body"]
    snap = a["threshold_snapshot"]
    assert snap["metric"] == "review_prompt_ctr_pct"
    assert snap["value"] == arp.REVIEW_PROMPT_CTR_FLOOR_PCT
    assert snap["actual"] < arp.REVIEW_PROMPT_CTR_FLOOR_PCT
    assert snap["shown"] == shown
    assert snap["clicked"] == clicked
    assert snap["window_days"] == arp.REVIEW_PROMPT_ALERT_WINDOW_DAYS


def test_cooldown_suppresses_duplicate_within_window():
    _reset_cooldowns()
    shown = arp.REVIEW_PROMPT_CTR_MIN_SHOWN * 4
    fake_db = _fake_db(shown=shown, clicked=1)
    with patch.object(arp, "db", fake_db), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        first = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(now_ts=1000.0))
        # Simulate the loop marking cooldown after a successful dispatch.
        arp._REVIEW_PROMPT_ALERT_LAST_FIRED["review_prompt_ctr_low"] = 1000.0
        # Halfway through the cooldown — still suppressed.
        second = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(
            now_ts=1000.0 + arp.REVIEW_PROMPT_ALERT_COOLDOWN_S / 2,
        ))
        # Just past the cooldown — alert may fire again.
        third = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(
            now_ts=1000.0 + arp.REVIEW_PROMPT_ALERT_COOLDOWN_S + 60,
        ))
    assert len(first) == 1
    assert second == []
    assert len(third) == 1


def test_evaluator_does_not_mutate_cooldown_state():
    """Cooldown advancement is the loop's responsibility — evaluator must
    stay pure so a downstream dispatch failure can be retried next tick.
    """
    _reset_cooldowns()
    shown = arp.REVIEW_PROMPT_CTR_MIN_SHOWN * 4
    fake_db = _fake_db(shown=shown, clicked=1)
    with patch.object(arp, "db", fake_db), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts1 = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(now_ts=1000.0))
        alerts2 = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(now_ts=1000.0 + 60))
    assert len(alerts1) == 1
    assert len(alerts2) == 1
    assert arp._REVIEW_PROMPT_ALERT_LAST_FIRED == {}


# ------------- _evaluate_review_prompt_reason_ctr_drop_alerts (Task #661) ----

def _patch_reason_windows(curr_by_reason, prev_by_reason):
    """Stub ``_aggregate_review_prompt_window`` so the reason-drop
    evaluator sees deterministic curr/prev rollups without needing a
    full Mongo aggregation fake. The first awaited call returns the
    *current* window, the second returns the *previous* window — same
    order the production code requests them.
    """
    # Distinguish curr vs prev by ``until`` — the production code asks
    # for the current window with ``until=now`` and the previous window
    # with ``until=curr_start``. Counter-based fakes break under repeat
    # invocations within the same test (cooldown / mutation cases).
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=arp.REVIEW_PROMPT_ALERT_WINDOW_DAYS - 1,
    )

    async def _fake_agg(since, until):
        if until >= cutoff:
            return {"totals": {}, "by_reason": list(curr_by_reason)}
        return {"totals": {}, "by_reason": list(prev_by_reason)}

    return patch.object(arp, "_aggregate_review_prompt_window", _fake_agg)


def _reason_row(reason, shown, clicked):
    return {"reason": reason, "shown": shown, "clicked": clicked, "dismissed": 0}


def test_reason_drop_no_alert_when_per_reason_sample_too_small():
    """Sample-size gate must protect both windows: a reason that fired
    only a handful of times can't page on noise even if its CTR
    dropped 100 pp."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # 5 shown / 5 clicked → 100% prev; 5 shown / 0 → 0% curr; massive
    # drop but well under the 30-shown gate on both sides.
    curr = [_reason_row("answer_helpful", 5, 0)]
    prev = [_reason_row("answer_helpful", 5, 5)]
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert alerts == []


def test_reason_drop_no_alert_when_only_curr_sample_meets_gate():
    """One-sided sample size shouldn't satisfy the gate either — a
    reason that just turned on this week has no comparable baseline."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    curr = [_reason_row("answer_helpful", 200, 0)]
    prev = [_reason_row("answer_helpful", 5, 5)]   # prev under min
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert alerts == []


def test_reason_drop_no_alert_when_drop_is_below_threshold():
    """A small dip (< drop_pp) on a healthy-volume reason must not page."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # prev: 200/40 = 20%; curr: 200/38 = 19% → -1pp drop, under 5pp default.
    curr = [_reason_row("answer_helpful", 200, 38)]
    prev = [_reason_row("answer_helpful", 200, 40)]
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert alerts == []


def test_reason_drop_alert_fires_for_collapsed_reason():
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # prev: 200/40 = 20%; curr: 200/4 = 2% → -18pp drop, well past 5pp.
    # Second reason stays healthy and must NOT appear in the alert.
    curr = [
        _reason_row("answer_helpful", 200, 4),
        _reason_row("session_end", 200, 50),
    ]
    prev = [
        _reason_row("answer_helpful", 200, 40),
        _reason_row("session_end", 200, 48),
    ]
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert len(alerts) == 1
    a = alerts[0]
    assert a["alert_type"] == "review_prompt_reason_ctr_drop"
    assert "answer_helpful" in a["title"]
    assert "answer_helpful" in a["body"]
    assert "session_end" not in a["body"]
    assert "/admin/dashboard" in a["body"]
    snap = a["threshold_snapshot"]
    assert snap["metric"] == "review_prompt_reason_ctr_delta_pp"
    assert len(snap["reasons"]) == 1
    assert snap["reasons"][0]["reason"] == "answer_helpful"
    assert snap["reasons"][0]["delta_pp"] <= -5.0


def test_reason_drop_alert_batches_multiple_reasons_worst_first():
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # answer_helpful: 20% → 2% (-18pp);  session_end: 15% → 5% (-10pp).
    # answer_helpful collapsed harder so it must lead the title + body.
    curr = [
        _reason_row("answer_helpful", 200, 4),
        _reason_row("session_end", 200, 10),
    ]
    prev = [
        _reason_row("answer_helpful", 200, 40),
        _reason_row("session_end", 200, 30),
    ]
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert len(alerts) == 1
    a = alerts[0]
    snap_reasons = a["threshold_snapshot"]["reasons"]
    assert [r["reason"] for r in snap_reasons] == ["answer_helpful", "session_end"]
    # Worst reason mentioned in the title.
    assert "answer_helpful" in a["title"]
    assert "2 reasons" in a["title"] or "2 trigger" in a["title"] or "2 " in a["title"]


def test_reason_drop_cooldown_suppresses_repeats_then_releases():
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    curr = [_reason_row("answer_helpful", 200, 4)]
    prev = [_reason_row("answer_helpful", 200, 40)]
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        first = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert len(first) == 1
    # Simulate a successful dispatch marking the cooldown.
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED["review_prompt_reason_ctr_drop"] = 1000.0
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        mid = asyncio.run(arp._evaluate_review_prompt_reason_ctr_drop_alerts(
            now_ts=1000.0 + arp.REVIEW_PROMPT_ALERT_COOLDOWN_S / 2,
        ))
        after = asyncio.run(arp._evaluate_review_prompt_reason_ctr_drop_alerts(
            now_ts=1000.0 + arp.REVIEW_PROMPT_ALERT_COOLDOWN_S + 60,
        ))
    assert mid == []
    assert len(after) == 1


def test_reason_drop_evaluator_does_not_mutate_cooldown_state():
    """Pure helper — the loop is responsible for cooldown bookkeeping
    so a downstream Resend failure can be retried next tick."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    curr = [_reason_row("answer_helpful", 200, 4)]
    prev = [_reason_row("answer_helpful", 200, 40)]
    with _patch_reason_windows(curr, prev), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        a1 = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
        a2 = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1060.0)
        )
    assert len(a1) == 1
    assert len(a2) == 1
    assert arp._REVIEW_PROMPT_ALERT_LAST_FIRED == {}


def test_reason_drop_no_alert_when_mongo_unavailable():
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    with patch.object(arp, "is_mongo_available", AsyncMock(return_value=False)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert alerts == []


def test_reason_drop_admin_threshold_overrides_take_effect():
    """Lowering ``review_prompt_reason_ctr_drop_pp`` from the Alert
    Settings panel must let smaller dips page; lowering ``min_shown``
    must let lower-volume reasons through the sample gate."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # Volume is below the default 30-shown gate, dip is below the
    # default 5pp threshold — neither would alert under defaults.
    curr = [_reason_row("answer_helpful", 20, 2)]   # 10%
    prev = [_reason_row("answer_helpful", 20, 4)]   # 20%, -10pp
    import metrics as _m
    saved = dict(_m._ALERT_THRESHOLDS)
    try:
        _m._ALERT_THRESHOLDS["review_prompt_reason_ctr_min_shown"] = 10
        _m._ALERT_THRESHOLDS["review_prompt_reason_ctr_drop_pp"] = 3.0
        with _patch_reason_windows(curr, prev), \
             patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
            alerts = asyncio.run(
                arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
            )
    finally:
        _m._ALERT_THRESHOLDS.clear()
        _m._ALERT_THRESHOLDS.update(saved)
    assert len(alerts) == 1
    snap = alerts[0]["threshold_snapshot"]
    assert snap["min_shown"] == 10
    assert snap["value"] == -3.0


# ------------- Task #670: auto-tuned per-reason sigma gate -------------------

def _patch_baseline_weeks(curr_by_reason, weekly_by_reason):
    """Stub ``_aggregate_review_prompt_window`` so each baseline week
    returns a DIFFERENT ``by_reason`` rollup — needed to exercise the
    rolling-stddev path. ``weekly_by_reason`` is indexed week-back:
    index 0 == most recent baseline week (the WoW "prev" window),
    index 1 == one week before that, etc.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=arp.REVIEW_PROMPT_ALERT_WINDOW_DAYS - 1,
    )
    week = timedelta(days=arp.REVIEW_PROMPT_ALERT_WINDOW_DAYS)
    curr_start = datetime.now(timezone.utc) - week

    async def _fake_agg(since, until):
        if until >= cutoff:
            return {"totals": {}, "by_reason": list(curr_by_reason)}
        # Map ``until`` back to which baseline week it represents.
        # Week 0 has until ≈ curr_start, week 1 has until ≈ curr_start - 7d, ...
        delta_days = (curr_start - until).total_seconds() / 86400.0
        idx = int(round(delta_days / arp.REVIEW_PROMPT_ALERT_WINDOW_DAYS))
        idx = max(0, min(idx, len(weekly_by_reason) - 1))
        return {"totals": {}, "by_reason": list(weekly_by_reason[idx])}

    return patch.object(arp, "_aggregate_review_prompt_window", _fake_agg)


def test_reason_drop_sigma_gate_suppresses_within_noise():
    """A 6 pp WoW drop on a reason whose baseline routinely swings
    ±10 pp must NOT page once the auto-tuned sigma gate is in effect —
    the absolute floor alone would have fired."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # curr: 200/30 = 15%; prev (week 0): 200/42 = 21% → -6 pp delta,
    # past the 5 pp absolute floor.
    curr = [_reason_row("answer_helpful", 200, 30)]
    # Baseline weeks: 21%, 8%, 28%, 12% — mean ≈ 17.25%, stddev ≈ 9 pp.
    # 2× stddev ≈ 18 pp, so -6 pp drop is well within noise.
    weekly = [
        [_reason_row("answer_helpful", 200, 42)],   # 21%
        [_reason_row("answer_helpful", 200, 16)],   #  8%
        [_reason_row("answer_helpful", 200, 56)],   # 28%
        [_reason_row("answer_helpful", 200, 24)],   # 12%
    ]
    with _patch_baseline_weeks(curr, weekly), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert alerts == []


def test_reason_drop_sigma_gate_allows_when_drop_exceeds_noise():
    """When the WoW drop dwarfs the baseline stddev, the sigma gate
    must still let the alert through."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # curr: 200/4 = 2%; prev (week 0): 200/40 = 20% → -18 pp delta.
    curr = [_reason_row("answer_helpful", 200, 4)]
    # Tight baseline: 20%, 19%, 21%, 20% — stddev < 1 pp, so 2× stddev
    # is tiny and a -18 pp drop blows right through.
    weekly = [
        [_reason_row("answer_helpful", 200, 40)],   # 20%
        [_reason_row("answer_helpful", 200, 38)],   # 19%
        [_reason_row("answer_helpful", 200, 42)],   # 21%
        [_reason_row("answer_helpful", 200, 40)],   # 20%
    ]
    with _patch_baseline_weeks(curr, weekly), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert len(alerts) == 1
    snap_reason = alerts[0]["threshold_snapshot"]["reasons"][0]
    # Baseline stats are surfaced for the on-call engineer.
    assert snap_reason["baseline_weeks_used"] == 4
    assert snap_reason["baseline_mean_ctr_pct"] is not None
    assert snap_reason["baseline_stddev_pp"] is not None
    assert snap_reason["sigma_threshold_pp"] is not None
    snap = alerts[0]["threshold_snapshot"]
    assert snap["sigma_mult"] == arp.REVIEW_PROMPT_REASON_CTR_DROP_SIGMA
    assert snap["baseline_weeks"] == arp.REVIEW_PROMPT_REASON_CTR_BASELINE_WEEKS


def test_reason_drop_sigma_disabled_via_admin_override():
    """Setting ``review_prompt_reason_ctr_drop_sigma`` to 0 from the
    Alert Settings panel must disable the noise gate — the alert then
    reverts to the original absolute-pp-only behaviour."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    # Same noisy baseline as the suppression test, but admin disabled
    # the sigma gate so the -6 pp drop should now page.
    curr = [_reason_row("answer_helpful", 200, 30)]
    weekly = [
        [_reason_row("answer_helpful", 200, 42)],
        [_reason_row("answer_helpful", 200, 16)],
        [_reason_row("answer_helpful", 200, 56)],
        [_reason_row("answer_helpful", 200, 24)],
    ]
    import metrics as _m
    saved = dict(_m._ALERT_THRESHOLDS)
    try:
        _m._ALERT_THRESHOLDS["review_prompt_reason_ctr_drop_sigma"] = 0.0
        with _patch_baseline_weeks(curr, weekly), \
             patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
            alerts = asyncio.run(
                arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
            )
    finally:
        _m._ALERT_THRESHOLDS.clear()
        _m._ALERT_THRESHOLDS.update(saved)
    assert len(alerts) == 1
    assert alerts[0]["threshold_snapshot"]["sigma_mult"] == 0.0


def test_reason_drop_sigma_gate_skipped_when_baseline_too_thin():
    """If too few baseline weeks have enough volume to compute a
    stddev, the alert must still be allowed to fire on the absolute
    floor alone — otherwise newly-popular reasons would never page."""
    arp._REVIEW_PROMPT_ALERT_LAST_FIRED.clear()
    curr = [_reason_row("answer_helpful", 200, 4)]   # 2%
    # Only the most recent baseline week clears min_shown — every
    # earlier week is below the gate, so we can't compute a stddev.
    weekly = [
        [_reason_row("answer_helpful", 200, 40)],   # 20%, qualifies
        [_reason_row("answer_helpful", 5, 1)],      # too small
        [_reason_row("answer_helpful", 5, 1)],
        [_reason_row("answer_helpful", 5, 1)],
    ]
    with _patch_baseline_weeks(curr, weekly), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        alerts = asyncio.run(
            arp._evaluate_review_prompt_reason_ctr_drop_alerts(now_ts=1000.0)
        )
    assert len(alerts) == 1
    snap_reason = alerts[0]["threshold_snapshot"]["reasons"][0]
    assert snap_reason["baseline_stddev_pp"] is None
    assert snap_reason["sigma_threshold_pp"] is None


def test_admin_threshold_overrides_take_effect():
    """Admin-tuned thresholds in metrics._ALERT_THRESHOLDS must override
    the module-level defaults (the whole point of the editable knobs)."""
    _reset_cooldowns()
    # 30 shown / 0 clicked → would NOT fire under default min_shown=50,
    # but should fire when admin lowers min_shown to 20.
    fake_db = _fake_db(shown=30, clicked=0)
    import metrics as _m
    saved = dict(_m._ALERT_THRESHOLDS)
    try:
        _m._ALERT_THRESHOLDS["review_prompt_ctr_min_shown"] = 20
        _m._ALERT_THRESHOLDS["review_prompt_ctr_floor_pct"] = 5.0
        with patch.object(arp, "db", fake_db), \
             patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
            alerts = asyncio.run(arp._evaluate_review_prompt_ctr_alerts(now_ts=1000.0))
    finally:
        _m._ALERT_THRESHOLDS.clear()
        _m._ALERT_THRESHOLDS.update(saved)
    assert len(alerts) == 1
    snap = alerts[0]["threshold_snapshot"]
    assert snap["min_shown"] == 20
    assert snap["value"] == 5.0
