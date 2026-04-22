"""Syrabit.ai — Google review prompt funnel (Task #654).

Mirrors the client-side `review_prompt_shown` / `review_prompt_clicked` /
`review_prompt_dismissed` PostHog events into our own collection so the
admin dashboard can render a small funnel tile (totals, click-through
rate, per-reason breakdown) without depending on the PostHog API.

Mirrors the pattern already used for hydrate-event (`/analytics/hydrate-event`)
and ad-impression (`/analytics/ad-impression`) ingest.

Task #656 — also exposes a background alert loop
(`_review_prompt_alert_loop`) modeled on
`routes.analytics._hydrate_alert_loop` that fires
`review_prompt_ctr_low` via `metrics._dispatch_alert` when the 7-day
click-through rate collapses below an admin-configurable floor (e.g.
because a UI regression broke the prompt CTA / `writeReviewUrl`).
"""
import asyncio
import logging
import time
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


# ─────────────────────────────────────────────────────────────────────────────
# Task #656 — alert ops when the review-prompt CTR collapses
#
# Background loop modeled on `routes.analytics._hydrate_alert_loop`. Every
# `REVIEW_PROMPT_ALERT_INTERVAL_S` we aggregate the last 7 days of
# `review_prompt_events` and fire a `review_prompt_ctr_low` alert via
# `metrics._dispatch_alert` when:
#
#   shown >= REVIEW_PROMPT_CTR_MIN_SHOWN  AND  ctr_pct < REVIEW_PROMPT_CTR_FLOOR_PCT
#
# Both knobs are admin-tunable from the Alert Settings panel — they live
# in `metrics._ALERT_THRESHOLDS_DEFAULT` so the existing GET/PUT
# `/admin/alert-settings` endpoints already surface and persist them.
#
# The constants below are *defaults* (mirroring the
# `HYDRATE_FAILURE_THRESHOLD` pattern) and are exported so the test suite
# can pin values without coupling to the saved admin config.
# ─────────────────────────────────────────────────────────────────────────────

REVIEW_PROMPT_CTR_MIN_SHOWN = 50           # min shown events in window
REVIEW_PROMPT_CTR_FLOOR_PCT = 5.0          # ctr_pct < this → alert
REVIEW_PROMPT_ALERT_WINDOW_DAYS = 7
REVIEW_PROMPT_ALERT_COOLDOWN_S = 6 * 60 * 60   # 6 h per incident
REVIEW_PROMPT_ALERT_INTERVAL_S = 30 * 60       # poll every 30 min
_REVIEW_PROMPT_DASHBOARD_URL = (
    "https://syrabit.ai/admin/dashboard?tab=overview#review-prompt-funnel"
)

_REVIEW_PROMPT_ALERT_LAST_FIRED: Dict[str, float] = {}


def _effective_review_prompt_thresholds() -> tuple:
    """Return ``(min_shown, floor_pct)`` using admin-configured values from
    ``metrics._ALERT_THRESHOLDS``, falling back to module-level defaults
    on missing / invalid entries. Mirrors
    ``routes.analytics._effective_hydrate_thresholds``.
    """
    min_shown = REVIEW_PROMPT_CTR_MIN_SHOWN
    floor_pct = REVIEW_PROMPT_CTR_FLOOR_PCT
    try:
        from metrics import _ALERT_THRESHOLDS
        try:
            min_shown = int(float(_ALERT_THRESHOLDS.get(
                "review_prompt_ctr_min_shown", min_shown,
            )))
        except (TypeError, ValueError):
            pass
        try:
            floor_pct = float(_ALERT_THRESHOLDS.get(
                "review_prompt_ctr_floor_pct", floor_pct,
            ))
        except (TypeError, ValueError):
            pass
    except Exception:
        pass
    return min_shown, floor_pct


async def _gather_review_prompt_alert_window(
    window_days: int = REVIEW_PROMPT_ALERT_WINDOW_DAYS,
) -> Dict[str, Any]:
    """Aggregate the last `window_days` of review-prompt telemetry into the
    counters required by the threshold check. Always returns a stable
    shape; on Mongo failure returns zeros so the alert loop just no-ops.
    """
    out: Dict[str, Any] = {
        "since": datetime.now(timezone.utc) - timedelta(days=window_days),
        "window_days": window_days,
        "shown": 0,
        "clicked": 0,
        "dismissed": 0,
        "ctr_pct": None,
    }
    if not await is_mongo_available():
        return out
    try:
        coll = db.review_prompt_events
        base = {"created_at": {"$gte": out["since"]}}
        totals: Dict[str, int] = {e: 0 for e in _REVIEW_PROMPT_VALID_EVENTS}
        cur = coll.aggregate([
            {"$match": {**base, "event": {"$in": list(_REVIEW_PROMPT_VALID_EVENTS)}}},
            {"$group": {"_id": "$event", "count": {"$sum": 1}}},
        ])
        async for row in cur:
            ev = row.get("_id")
            if ev in totals:
                totals[ev] = int(row.get("count") or 0)
        out["shown"] = totals["review_prompt_shown"]
        out["clicked"] = totals["review_prompt_clicked"]
        out["dismissed"] = totals["review_prompt_dismissed"]
        if out["shown"] > 0:
            out["ctr_pct"] = round((out["clicked"] / out["shown"]) * 100, 1)
    except Exception as e:
        logger.debug(f"review-prompt alert window aggregation failed: {e}")
    return out


async def _evaluate_review_prompt_ctr_alerts(
    now_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Pure helper used by the loop and tests. Returns the list of alerts
    that *should* be dispatched right now (after cooldown checks). Does
    NOT mutate ``_REVIEW_PROMPT_ALERT_LAST_FIRED`` — the loop is
    responsible for marking cooldown only after a successful dispatch
    (so a transient Resend/webhook failure doesn't suppress the next
    alert for the cooldown window).
    Each entry is the kwargs dict for ``metrics._dispatch_alert``.
    """
    if now_ts is None:
        now_ts = time.time()
    snap = await _gather_review_prompt_alert_window()
    alerts: List[Dict[str, Any]] = []
    min_shown, floor_pct = _effective_review_prompt_thresholds()

    shown = int(snap.get("shown") or 0)
    clicked = int(snap.get("clicked") or 0)
    ctr = snap.get("ctr_pct")

    if shown < min_shown or ctr is None or ctr >= floor_pct:
        return alerts

    last = _REVIEW_PROMPT_ALERT_LAST_FIRED.get("review_prompt_ctr_low")
    if last is not None and (now_ts - last) < REVIEW_PROMPT_ALERT_COOLDOWN_S:
        return alerts

    body_lines = [
        f"Review-prompt click-through rate is {ctr:.1f}% "
        f"({clicked}/{shown}) over the last "
        f"{REVIEW_PROMPT_ALERT_WINDOW_DAYS}d, below the "
        f"{floor_pct:.1f}% floor with ≥ {min_shown} shown events.",
        "Likely a UI regression — check that `writeReviewUrl` still "
        "resolves and the prompt CTA is reachable.",
        f"Dashboard: {_REVIEW_PROMPT_DASHBOARD_URL}",
    ]
    alerts.append({
        "alert_type": "review_prompt_ctr_low",
        "title": "Review-prompt CTR dropped below floor",
        "body": "\n".join(body_lines),
        "threshold_snapshot": {
            "metric": "review_prompt_ctr_pct",
            "value": floor_pct,
            "actual": ctr,
            "shown": shown,
            "clicked": clicked,
            "min_shown": min_shown,
            "window_days": REVIEW_PROMPT_ALERT_WINDOW_DAYS,
        },
    })
    return alerts


async def _review_prompt_alert_loop():
    """Background loop: poll review_prompt_events and fire admin alerts
    when the 7-day CTR falls below the configured floor. Modeled on
    ``routes.analytics._hydrate_alert_loop`` — best-effort, swallows its
    own errors so a flaky Mongo can't kill the task.
    """
    # Stagger start so we don't pile onto the boot-time burst alongside
    # the other alert loops.
    await asyncio.sleep(180)
    while True:
        try:
            # Refresh persisted alert settings BEFORE evaluation so admin
            # threshold changes take effect within the next tick — same
            # pattern the hydrate / metrics alert loops use.
            try:
                from metrics import _load_alert_settings
                await _load_alert_settings()
            except Exception:
                pass
            alerts = await _evaluate_review_prompt_ctr_alerts()
            if alerts:
                try:
                    from metrics import _dispatch_alert, _alert_last_fired
                    for a in alerts:
                        # Bypass the shared 30-min metrics cooldown — we
                        # already gate ourselves at REVIEW_PROMPT_ALERT_COOLDOWN_S.
                        _alert_last_fired.pop(a["alert_type"], None)
                        try:
                            await _dispatch_alert(
                                a["alert_type"], a["title"], a["body"],
                                threshold_snapshot=a.get("threshold_snapshot"),
                            )
                        except Exception as dexc:
                            # Don't advance our cooldown on failure — let
                            # the next tick retry.
                            logger.warning(
                                f"review-prompt alert {a['alert_type']} dispatch "
                                f"failed; will retry next tick: {dexc}"
                            )
                            continue
                        _REVIEW_PROMPT_ALERT_LAST_FIRED[a["alert_type"]] = time.time()
                except Exception as exc:
                    logger.warning(f"review-prompt alert dispatch failed: {exc}")
        except Exception as exc:
            logger.debug(f"review-prompt alert loop error: {exc}")
        await asyncio.sleep(REVIEW_PROMPT_ALERT_INTERVAL_S)
