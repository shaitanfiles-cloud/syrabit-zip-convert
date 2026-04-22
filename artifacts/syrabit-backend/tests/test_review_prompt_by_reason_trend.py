"""Tests for Task #662 — per-reason 8-week CTR trend endpoint in
``routes/admin_review_prompts.py``. Mirrors the fake-Mongo patterns
used in ``test_review_prompt_weekly_digest.py``.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()
from routes import admin_review_prompts as arp  # noqa: E402


def _fake_db_for_reason(reason: str, weekly_counts):
    """Stub `db.review_prompt_events.aggregate` so that each successive
    by-reason+event aggregation call returns one bucket from
    ``weekly_counts`` (oldest first). The endpoint loops 8 times from
    oldest to newest, so the helper consumes them in order.
    """
    weekly_iter = iter(weekly_counts)

    class _Cursor:
        def __init__(self, docs):
            self._docs = list(docs)
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self._docs:
                raise StopAsyncIteration
            return self._docs.pop(0)

    fake = MagicMock()

    def _aggregate(pipeline, *a, **kw):
        group_id = pipeline[1]["$group"]["_id"]
        if isinstance(group_id, str):
            # totals-by-event aggregation — not consumed by the endpoint
            # logic itself but called inside `_aggregate_review_prompt_window`.
            counts = next(weekly_iter, {"shown": 0, "clicked": 0, "dismissed": 0})
            # Stash counts for the matching by-reason call below.
            fake._pending = counts
            return _Cursor([
                {"_id": "review_prompt_shown", "count": counts["shown"]},
                {"_id": "review_prompt_clicked", "count": counts["clicked"]},
                {"_id": "review_prompt_dismissed", "count": counts["dismissed"]},
            ])
        # by reason+event aggregation
        counts = getattr(fake, "_pending", {"shown": 0, "clicked": 0, "dismissed": 0})
        if counts["shown"] == 0 and counts["clicked"] == 0 and counts["dismissed"] == 0:
            return _Cursor([])
        return _Cursor([
            {"_id": {"reason": reason, "event": "review_prompt_shown"},
             "count": counts["shown"]},
            {"_id": {"reason": reason, "event": "review_prompt_clicked"},
             "count": counts["clicked"]},
            {"_id": {"reason": reason, "event": "review_prompt_dismissed"},
             "count": counts["dismissed"]},
        ])

    fake.review_prompt_events.aggregate = MagicMock(side_effect=_aggregate)
    fake.review_prompt_events.create_index = AsyncMock(return_value=None)
    return fake


def test_trend_returns_empty_when_mongo_unavailable():
    with patch.object(arp, "is_mongo_available", AsyncMock(return_value=False)):
        out = asyncio.run(arp.admin_review_prompt_by_reason_trend(
            reason="quiz_high_score", weeks=8, admin={"email": "x@y"},
        ))
    assert out == {"reason": "quiz_high_score", "weeks": 8, "buckets": []}


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
