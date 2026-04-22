"""Syrabit.ai — Google review prompt funnel (Task #654).

Mirrors the client-side `review_prompt_shown` / `review_prompt_clicked` /
`review_prompt_dismissed` PostHog events into our own collection so the
admin dashboard can render a small funnel tile (totals, click-through
rate, per-reason breakdown) without depending on the PostHog API.

Mirrors the pattern already used for hydrate-event (`/analytics/hydrate-event`)
and ad-impression (`/analytics/ad-impression`) ingest.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query, Request

from auth_deps import get_admin_user
from deps import db, is_mongo_available

logger = logging.getLogger(__name__)
router = APIRouter()

_REVIEW_PROMPT_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 days
_REVIEW_PROMPT_INDEXES_READY = False
_REVIEW_PROMPT_VALID_EVENTS = {
    "review_prompt_shown",
    "review_prompt_clicked",
    "review_prompt_dismissed",
}


async def _ensure_review_prompt_indexes() -> None:
    global _REVIEW_PROMPT_INDEXES_READY
    if _REVIEW_PROMPT_INDEXES_READY:
        return
    try:
        await db.review_prompt_events.create_index(
            "created_at", expireAfterSeconds=_REVIEW_PROMPT_TTL_SECONDS,
        )
        await db.review_prompt_events.create_index(
            [("event", 1), ("created_at", -1)],
        )
        await db.review_prompt_events.create_index(
            [("reason", 1), ("event", 1), ("created_at", -1)],
        )
        _REVIEW_PROMPT_INDEXES_READY = True
    except Exception as e:
        logger.warning(f"review_prompt_events index create failed (non-fatal): {e}")


# ─────────────────────────────────────────────
# Public ingest
# ─────────────────────────────────────────────
@router.post("/analytics/review-prompt-event")
async def track_review_prompt_event(
    request: Request,
    event: str = Body(...),
    reason: Optional[str] = Body(None),
):
    """Persist one review-prompt funnel event.

    Best-effort + capped — never raises; analytics must not break page
    loads. Drops obviously-bogus payloads (unknown event, oversized
    fields) instead of polluting the collection.
    """
    if not isinstance(event, str) or event not in _REVIEW_PROMPT_VALID_EVENTS:
        return {"status": "ignored"}
    if reason is not None and not isinstance(reason, str):
        reason = None
    if reason is not None:
        reason = reason[:64] or None
    try:
        await _ensure_review_prompt_indexes()
        ua = request.headers.get("user-agent", "")[:200]
        await db.review_prompt_events.insert_one({
            "event": event,
            "reason": reason or "unknown",
            "ua": ua or None,
            "created_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.debug(f"review-prompt-event ingest failed: {e}")
    return {"status": "tracked"}


# ─────────────────────────────────────────────
# Admin: funnel rollup
# ─────────────────────────────────────────────
def _ctr(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 1)


@router.get("/admin/analytics/review-prompt-stats")
async def admin_review_prompt_stats(
    days: int = Query(30, ge=1, le=180),
    admin: dict = Depends(get_admin_user),
):
    """Funnel rollup for the admin Google-review-prompt tile.

    Returns:
      shown, clicked, dismissed: totals over the window.
      ctr_pct: clicked / shown * 100 (None when shown == 0).
      dismiss_rate_pct: dismissed / shown * 100.
      by_reason: per-trigger-reason breakdown with the same counts +
        per-reason CTR so the team can see which surfaces convert.
      recent: last 15 events for spot-checks.
    """
    empty = {
        "days": days,
        "shown": 0,
        "clicked": 0,
        "dismissed": 0,
        "ctr_pct": None,
        "dismiss_rate_pct": None,
        "by_reason": [],
        "recent": [],
    }
    if not await is_mongo_available():
        return empty
    try:
        await _ensure_review_prompt_indexes()
        coll = db.review_prompt_events
        since = datetime.now(timezone.utc) - timedelta(days=days)
        base = {"created_at": {"$gte": since}}

        # Totals — single aggregation rather than three count_documents
        # round-trips.
        totals: Dict[str, int] = {e: 0 for e in _REVIEW_PROMPT_VALID_EVENTS}
        cur = coll.aggregate([
            {"$match": {**base, "event": {"$in": list(_REVIEW_PROMPT_VALID_EVENTS)}}},
            {"$group": {"_id": "$event", "count": {"$sum": 1}}},
        ])
        async for row in cur:
            ev = row.get("_id")
            if ev in totals:
                totals[ev] = int(row.get("count") or 0)
        shown = totals["review_prompt_shown"]
        clicked = totals["review_prompt_clicked"]
        dismissed = totals["review_prompt_dismissed"]

        # Per-reason breakdown
        by_reason_map: Dict[str, Dict[str, int]] = {}
        cur2 = coll.aggregate([
            {"$match": {**base, "event": {"$in": list(_REVIEW_PROMPT_VALID_EVENTS)}}},
            {"$group": {
                "_id": {"reason": "$reason", "event": "$event"},
                "count": {"$sum": 1},
            }},
        ])
        async for row in cur2:
            key = row["_id"] or {}
            reason = key.get("reason") or "unknown"
            ev = key.get("event")
            bucket = by_reason_map.setdefault(reason, {
                "review_prompt_shown": 0,
                "review_prompt_clicked": 0,
                "review_prompt_dismissed": 0,
            })
            if ev in bucket:
                bucket[ev] += int(row.get("count") or 0)

        by_reason: List[Dict[str, Any]] = []
        for reason, counts in by_reason_map.items():
            r_shown = counts["review_prompt_shown"]
            r_clicked = counts["review_prompt_clicked"]
            r_dismissed = counts["review_prompt_dismissed"]
            by_reason.append({
                "reason": reason,
                "shown": r_shown,
                "clicked": r_clicked,
                "dismissed": r_dismissed,
                "ctr_pct": _ctr(r_clicked, r_shown),
                "dismiss_rate_pct": _ctr(r_dismissed, r_shown),
            })
        # Sort by shown desc so the most-fired surfaces appear first.
        by_reason.sort(key=lambda r: (r["shown"], r["clicked"]), reverse=True)

        # Recent events for spot-checks
        recent: List[Dict[str, Any]] = []
        recent_cur = coll.find(
            {**base, "event": {"$in": list(_REVIEW_PROMPT_VALID_EVENTS)}},
            {"_id": 0, "event": 1, "reason": 1, "created_at": 1},
        ).sort("created_at", -1).limit(15)
        async for doc in recent_cur:
            ts = doc.get("created_at")
            if isinstance(ts, datetime):
                doc["created_at"] = ts.isoformat()
            recent.append(doc)

        return {
            "days": days,
            "shown": shown,
            "clicked": clicked,
            "dismissed": dismissed,
            "ctr_pct": _ctr(clicked, shown),
            "dismiss_rate_pct": _ctr(dismissed, shown),
            "by_reason": by_reason,
            "recent": recent,
        }
    except Exception as e:
        logger.warning(f"review-prompt-stats query failed: {e}")
        return empty
