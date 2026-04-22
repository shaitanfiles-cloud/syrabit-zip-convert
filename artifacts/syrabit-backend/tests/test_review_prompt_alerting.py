"""Tests for Task #656 — review-prompt CTR alert loop in
``routes/admin_review_prompts.py``. Mirrors the patterns in
``test_hydrate_alerting.py``: install the deps stub, patch
``deps.db`` / ``deps.is_mongo_available``, and exercise the pure-ish
helpers (``_gather_review_prompt_alert_window``,
``_evaluate_review_prompt_ctr_alerts``) without spinning up the asyncio
loop in production.
"""
import asyncio
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
