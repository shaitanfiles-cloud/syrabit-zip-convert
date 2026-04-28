"""Tests for Task #662 — per-reason 8-week CTR trend endpoint in
``routes/admin_review_prompts.py``. Mirrors the fake-Mongo patterns
used in ``test_review_prompt_weekly_digest.py``.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()
from routes import admin_review_prompts as arp  # noqa: E402


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


def _fake_db_for_reason(reason: str, weekly_counts):
    """Stub `db.review_prompt_events.aggregate` for the Task #674
    single-pipeline endpoint. ``weekly_counts`` is oldest-first; we
    re-emit each bucket as ``(wk, reason, event)`` rows where ``wk``
    is the week-offset-from-newest the endpoint uses to slot rows
    back into oldest-first response buckets.
    """
    weeks = len(weekly_counts)
    fake = MagicMock()
    aggregate_calls = {"n": 0}

    def _aggregate(pipeline, *a, **kw):
        aggregate_calls["n"] += 1
        docs = []
        for oldest_idx, counts in enumerate(weekly_counts):
            wk = weeks - 1 - oldest_idx
            for ev_field, ev in (
                ("shown", "review_prompt_shown"),
                ("clicked", "review_prompt_clicked"),
                ("dismissed", "review_prompt_dismissed"),
            ):
                n = int(counts.get(ev_field) or 0)
                if n > 0:
                    docs.append({
                        "_id": {"wk": wk, "reason": reason, "event": ev},
                        "count": n,
                    })
        return _Cursor(docs)

    fake.review_prompt_events.aggregate = MagicMock(side_effect=_aggregate)
    fake.review_prompt_events.create_index = AsyncMock(return_value=None)
    fake._aggregate_calls = aggregate_calls
    return fake


def test_trend_returns_empty_when_mongo_unavailable():
    with patch.object(arp, "is_mongo_available", AsyncMock(return_value=False)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=8, admin={"email": "x@y"},
        ))
    assert out == {
        "reason": "quiz_high_score",
        "weeks": 8,
        "buckets": [],
        "compare_reason": None,
        "compare_buckets": [],
        "available_reasons": [],
    }


def test_trend_returns_eight_weekly_buckets_oldest_first():
    weekly = [
        {"shown": 10 + i, "clicked": i, "dismissed": 1}
        for i in range(8)
    ]
    fake = _fake_db_for_reason("quiz_high_score", weekly)
    arp._REVIEW_PROMPT_INDEXES_READY = True  # skip index path

    with patch.object(arp, "db", fake), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=8, admin={"email": "x@y"},
        ))

    assert out["reason"] == "quiz_high_score"
    assert out["weeks"] == 8
    assert len(out["buckets"]) == 8
    # Oldest bucket is index 0 — should be `shown=10, clicked=0`.
    first = out["buckets"][0]
    last = out["buckets"][-1]
    assert first["shown"] == 10
    assert first["clicked"] == 0
    assert first["ctr_pct"] == 0.0  # 0/10
    assert last["shown"] == 17
    assert last["clicked"] == 7
    # CTR rounded to one decimal.
    assert last["ctr_pct"] == round((7 / 17) * 100, 1)
    # Each bucket carries an ISO week_start / week_end.
    for b in out["buckets"]:
        assert "week_start" in b and "week_end" in b


def test_trend_filters_to_requested_reason_only():
    """Buckets with no events for the reason → zeros + ctr_pct=None."""
    weekly = [
        {"shown": 0, "clicked": 0, "dismissed": 0} for _ in range(4)
    ]
    fake = _fake_db_for_reason("answer_helpful", weekly)
    arp._REVIEW_PROMPT_INDEXES_READY = True

    with patch.object(arp, "db", fake), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="answer_helpful", weeks=4, admin={"email": "x@y"},
        ))

    assert len(out["buckets"]) == 4
    assert all(b["shown"] == 0 and b["clicked"] == 0 for b in out["buckets"])
    assert all(b["ctr_pct"] is None for b in out["buckets"])


def test_trend_clamps_oversized_reason_string():
    """Reasons capped to 64 chars (matches ingest cap)."""
    long_reason = "a" * 200
    arp._REVIEW_PROMPT_INDEXES_READY = True
    with patch.object(arp, "is_mongo_available", AsyncMock(return_value=False)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason=long_reason, weeks=8, admin={"email": "x@y"},
        ))
    assert out["reason"] == "a" * 64


# ─────────────────────────────────────────────
# Task #673 — compare overlay + available reasons
# ─────────────────────────────────────────────
def _fake_db_for_multi_reasons(weekly_by_reason):
    """Stub for the Task #674 single-pipeline endpoint with full
    per-reason control. ``weekly_by_reason`` is a list (oldest first)
    of ``{reason: {shown, clicked, dismissed}}`` per week. The fake
    flattens all weeks into one batch of ``(wk, reason, event)`` rows
    so the endpoint's single ``aggregate`` call gets everything.
    """
    weeks = len(weekly_by_reason)
    fake = MagicMock()
    aggregate_calls = {"n": 0}

    def _aggregate(pipeline, *a, **kw):
        aggregate_calls["n"] += 1
        docs = []
        for oldest_idx, week in enumerate(weekly_by_reason):
            wk = weeks - 1 - oldest_idx
            for r, counts in week.items():
                for ev_field, ev in (
                    ("shown", "review_prompt_shown"),
                    ("clicked", "review_prompt_clicked"),
                    ("dismissed", "review_prompt_dismissed"),
                ):
                    n = int(counts.get(ev_field) or 0)
                    if n > 0:
                        docs.append({
                            "_id": {"wk": wk, "reason": r, "event": ev},
                            "count": n,
                        })
        return _Cursor(docs)

    fake.review_prompt_events.aggregate = MagicMock(side_effect=_aggregate)
    fake.review_prompt_events.create_index = AsyncMock(return_value=None)
    fake._aggregate_calls = aggregate_calls
    return fake


def test_trend_overlays_compare_reason_buckets():
    """Supplying ``compare`` returns parallel buckets for that reason."""
    weekly = [
        {
            "quiz_high_score": {"shown": 100, "clicked": 10, "dismissed": 1},
            "chapter_engaged": {"shown": 50, "clicked": 8, "dismissed": 2},
        }
        for _ in range(4)
    ]
    fake = _fake_db_for_multi_reasons(weekly)
    arp._REVIEW_PROMPT_INDEXES_READY = True

    with patch.object(arp, "db", fake), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=4,
            compare="chapter_engaged", admin={"email": "x@y"},
        ))

    assert out["reason"] == "quiz_high_score"
    assert out["compare_reason"] == "chapter_engaged"
    assert len(out["buckets"]) == 4
    assert len(out["compare_buckets"]) == 4
    # Primary series reflects quiz_high_score counts.
    assert out["buckets"][-1]["shown"] == 100
    assert out["buckets"][-1]["clicked"] == 10
    assert out["buckets"][-1]["ctr_pct"] == 10.0
    # Compare series reflects chapter_engaged counts.
    assert out["compare_buckets"][-1]["shown"] == 50
    assert out["compare_buckets"][-1]["clicked"] == 8
    assert out["compare_buckets"][-1]["ctr_pct"] == 16.0
    # Bucket boundaries align so the UI can plot side-by-side.
    for a, b in zip(out["buckets"], out["compare_buckets"]):
        assert a["week_start"] == b["week_start"]
        assert a["week_end"] == b["week_end"]


def test_trend_compare_same_as_primary_is_dropped():
    """Comparing a reason to itself yields no overlay (no extra info)."""
    arp._REVIEW_PROMPT_INDEXES_READY = True
    with patch.object(arp, "is_mongo_available", AsyncMock(return_value=False)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=4,
            compare="quiz_high_score", admin={"email": "x@y"},
        ))
    assert out["compare_reason"] is None
    assert out["compare_buckets"] == []


def test_trend_available_reasons_only_lists_reasons_with_data():
    """``available_reasons`` excludes reasons with zero events in window
    so the UI picker doesn't surface dead options.
    """
    weekly = [
        {
            "quiz_high_score": {"shown": 10, "clicked": 1, "dismissed": 0},
            "chapter_engaged": {"shown": 5, "clicked": 0, "dismissed": 1},
        },
        {
            "quiz_high_score": {"shown": 8, "clicked": 0, "dismissed": 0},
            "answer_helpful": {"shown": 0, "clicked": 0, "dismissed": 0},
        },
    ]
    fake = _fake_db_for_multi_reasons(weekly)
    arp._REVIEW_PROMPT_INDEXES_READY = True
    with patch.object(arp, "db", fake), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=2, admin={"email": "x@y"},
        ))
    available = set(out["available_reasons"])
    assert "quiz_high_score" in available
    assert "chapter_engaged" in available
    assert "answer_helpful" not in available


def test_trend_runs_single_aggregation_regardless_of_weeks():
    """Task #674 — endpoint must hit Mongo at most once per request,
    even at the max ``weeks=26`` window, so high-traffic drill-downs
    don't pay 26 round-trips.
    """
    weekly = [
        {"quiz_high_score": {"shown": 10, "clicked": 1, "dismissed": 0}}
        for _ in range(26)
    ]
    fake = _fake_db_for_multi_reasons(weekly)
    arp._REVIEW_PROMPT_INDEXES_READY = True
    with patch.object(arp, "db", fake), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=26,
            compare="chapter_engaged", admin={"email": "x@y"},
        ))
    assert fake._aggregate_calls["n"] == 1
    assert len(out["buckets"]) == 26


def test_trend_available_reasons_always_includes_primary():
    """Even when the primary fired no events (e.g. just created), it
    must appear in the picker so the open panel doesn't lose its row.
    """
    weekly = [
        {"chapter_engaged": {"shown": 5, "clicked": 1, "dismissed": 0}}
        for _ in range(2)
    ]
    fake = _fake_db_for_multi_reasons(weekly)
    arp._REVIEW_PROMPT_INDEXES_READY = True
    with patch.object(arp, "db", fake), \
         patch.object(arp, "is_mongo_available", AsyncMock(return_value=True)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=2, admin={"email": "x@y"},
        ))
    assert "quiz_high_score" in out["available_reasons"]
    assert "chapter_engaged" in out["available_reasons"]
