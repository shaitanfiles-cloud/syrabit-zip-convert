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
import os
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
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=days)

        # Share one aggregation helper with the weekly digest so the
        # admin tile and the Monday email can never drift on totals /
        # per-reason counts (Task #655 review feedback).
        agg = await _aggregate_review_prompt_window(since, now)
        totals = agg["totals"]
        shown = int(totals.get("shown") or 0)
        clicked = int(totals.get("clicked") or 0)
        dismissed = int(totals.get("dismissed") or 0)

        # Task #659 — also pull the immediately-preceding equal-sized
        # window so we can surface per-reason week-over-week deltas
        # (shown count + CTR) on the admin tile. Reasons that newly
        # appeared / disappeared get a `status` flag so ops can see
        # them at a glance.
        prev_until = since
        prev_since = since - (now - since)
        prev_agg = await _aggregate_review_prompt_window(prev_since, prev_until)
        prev_by_reason_map: Dict[str, Dict[str, int]] = {
            (row.get("reason") or "unknown"): {
                "shown": int(row.get("shown") or 0),
                "clicked": int(row.get("clicked") or 0),
                "dismissed": int(row.get("dismissed") or 0),
            }
            for row in prev_agg["by_reason"]
        }

        # Decorate the by-reason rows with per-reason CTR + dismiss-rate
        # (the shared helper returns raw counts only).
        by_reason: List[Dict[str, Any]] = []
        seen_reasons: set = set()
        for row in agg["by_reason"]:
            reason = row.get("reason") or "unknown"
            seen_reasons.add(reason)
            r_shown = int(row.get("shown") or 0)
            r_clicked = int(row.get("clicked") or 0)
            r_dismissed = int(row.get("dismissed") or 0)
            prev = prev_by_reason_map.get(reason, {})
            p_shown = int(prev.get("shown") or 0)
            p_clicked = int(prev.get("clicked") or 0)
            p_ctr = _ctr(p_clicked, p_shown)
            r_ctr = _ctr(r_clicked, r_shown)
            ctr_delta = (
                round(r_ctr - p_ctr, 1)
                if (r_ctr is not None and p_ctr is not None) else None
            )
            if p_shown == 0 and p_clicked == 0:
                status = "new"
            else:
                status = "active"
            by_reason.append({
                "reason": reason,
                "shown": r_shown,
                "clicked": r_clicked,
                "dismissed": r_dismissed,
                "ctr_pct": r_ctr,
                "dismiss_rate_pct": _ctr(r_dismissed, r_shown),
                "prev_shown": p_shown,
                "prev_clicked": p_clicked,
                "prev_ctr_pct": p_ctr,
                "shown_delta": r_shown - p_shown,
                "ctr_delta_pct": ctr_delta,
                "status": status,
            })
        # Reasons that fired last week but are gone this week — surface
        # them too so a regression that silenced a trigger is obvious.
        for reason, prev in prev_by_reason_map.items():
            if reason in seen_reasons:
                continue
            p_shown = int(prev.get("shown") or 0)
            p_clicked = int(prev.get("clicked") or 0)
            p_ctr = _ctr(p_clicked, p_shown)
            by_reason.append({
                "reason": reason,
                "shown": 0,
                "clicked": 0,
                "dismissed": 0,
                "ctr_pct": None,
                "dismiss_rate_pct": None,
                "prev_shown": p_shown,
                "prev_clicked": p_clicked,
                "prev_ctr_pct": p_ctr,
                "shown_delta": -p_shown,
                "ctr_delta_pct": None,
                "status": "gone",
            })
        # Sort by shown desc so the most-fired surfaces appear first;
        # gone reasons sink to the bottom because their shown == 0.
        by_reason.sort(key=lambda r: (r["shown"], r["clicked"]), reverse=True)

        # Recent events for spot-checks — kept inline because the digest
        # path doesn't need them.
        recent: List[Dict[str, Any]] = []
        coll = db.review_prompt_events
        base = {"created_at": {"$gte": since}}
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


# ─────────────────────────────────────────────
# Task #662 — per-reason 8-week trend (drill-down)
# ─────────────────────────────────────────────
@router.get("/admin/analytics/review-prompt-stats/by-reason-trend")
async def admin_review_prompt_by_reason_trend(
    reason: str = Query(..., min_length=1, max_length=64),
    weeks: int = Query(8, ge=1, le=26),
    admin: dict = Depends(get_admin_user),
):
    """Weekly shown / clicked / CTR buckets for a single trigger reason.

    Powers the inline sparkline that expands when an admin clicks a
    reason row in the review-prompt funnel tile. Buckets are rolling
    7-day windows aligned to ``now`` so the most-recent bucket matches
    the totals the tile already displays. Oldest bucket first.
    """
    reason_clean = (reason or "").strip()[:64] or "unknown"
    empty = {"reason": reason_clean, "weeks": weeks, "buckets": []}
    if not await is_mongo_available():
        return empty
    try:
        await _ensure_review_prompt_indexes()
        now = datetime.now(timezone.utc)
        buckets: List[Dict[str, Any]] = []
        for i in range(weeks - 1, -1, -1):
            end = now - timedelta(days=7 * i)
            start = end - timedelta(days=7)
            agg = await _aggregate_review_prompt_window(start, end)
            row = next(
                (r for r in agg["by_reason"]
                 if (r.get("reason") or "unknown") == reason_clean),
                {},
            )
            shown = int(row.get("shown") or 0)
            clicked = int(row.get("clicked") or 0)
            dismissed = int(row.get("dismissed") or 0)
            buckets.append({
                "week_start": start.isoformat(),
                "week_end": end.isoformat(),
                "shown": shown,
                "clicked": clicked,
                "dismissed": dismissed,
                "ctr_pct": _ctr(clicked, shown),
            })
        return {"reason": reason_clean, "weeks": weeks, "buckets": buckets}
    except Exception as e:
        logger.warning(f"review-prompt by-reason-trend query failed: {e}")
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

# Task #661 — per-reason CTR collapse defaults. Both knobs are
# overridable from the Alert Settings panel via
# ``metrics._ALERT_THRESHOLDS``.
REVIEW_PROMPT_REASON_CTR_DROP_PP = 5.0     # min pp drop WoW to alert
REVIEW_PROMPT_REASON_CTR_MIN_SHOWN = 30    # min shown in BOTH windows
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


def _effective_review_prompt_reason_drop_thresholds() -> tuple:
    """Return ``(min_shown, drop_pp)`` for the per-reason CTR-collapse
    alert, applying admin overrides from ``metrics._ALERT_THRESHOLDS``
    on top of the module-level defaults. Mirrors the resolution pattern
    used by ``_effective_review_prompt_thresholds``.
    """
    min_shown = REVIEW_PROMPT_REASON_CTR_MIN_SHOWN
    drop_pp = REVIEW_PROMPT_REASON_CTR_DROP_PP
    try:
        from metrics import _ALERT_THRESHOLDS
        try:
            min_shown = int(float(_ALERT_THRESHOLDS.get(
                "review_prompt_reason_ctr_min_shown", min_shown,
            )))
        except (TypeError, ValueError):
            pass
        try:
            drop_pp = float(_ALERT_THRESHOLDS.get(
                "review_prompt_reason_ctr_drop_pp", drop_pp,
            ))
        except (TypeError, ValueError):
            pass
    except Exception:
        pass
    return min_shown, drop_pp


async def _evaluate_review_prompt_reason_ctr_drop_alerts(
    now_ts: Optional[float] = None,
    *,
    window_days: int = REVIEW_PROMPT_ALERT_WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """Pure evaluator for Task #661.

    Compares per-trigger-reason CTR for the most recent ``window_days``
    against the immediately-preceding equal-sized window. Flags every
    reason whose CTR fell by ≥ ``drop_pp`` percentage points, *provided*
    both windows have at least ``min_shown`` shown events for that
    reason — without the sample-size gate, low-volume reasons would
    page on noise alone.

    The flagged reasons are batched into a single
    ``review_prompt_reason_ctr_drop`` alert (so a regression that hits
    multiple reasons at once doesn't create an inbox storm). Cooldown
    is also at the alert-type level — same pattern as
    ``_evaluate_review_prompt_ctr_alerts``.

    Returns the (possibly empty) list of dispatch-kwarg dicts. The
    caller is responsible for marking
    ``_REVIEW_PROMPT_ALERT_LAST_FIRED`` only after a successful send.
    """
    if now_ts is None:
        now_ts = time.time()
    if not await is_mongo_available():
        return []

    min_shown, drop_pp = _effective_review_prompt_reason_drop_thresholds()
    now_dt = datetime.now(timezone.utc)
    curr_start = now_dt - timedelta(days=window_days)
    prev_start = now_dt - timedelta(days=window_days * 2)

    try:
        curr = await _aggregate_review_prompt_window(curr_start, now_dt)
        prev = await _aggregate_review_prompt_window(prev_start, curr_start)
    except Exception as exc:
        logger.debug(f"reason-ctr-drop window aggregation failed: {exc}")
        return []

    prev_map: Dict[str, Dict[str, int]] = {
        str(r.get("reason") or "unknown"): {
            "shown": int(r.get("shown") or 0),
            "clicked": int(r.get("clicked") or 0),
        }
        for r in (prev.get("by_reason") or [])
    }

    flagged: List[Dict[str, Any]] = []
    for row in (curr.get("by_reason") or []):
        reason = str(row.get("reason") or "unknown")
        c_shown = int(row.get("shown") or 0)
        c_clicked = int(row.get("clicked") or 0)
        prev_row = prev_map.get(reason, {})
        p_shown = int(prev_row.get("shown") or 0)
        p_clicked = int(prev_row.get("clicked") or 0)
        # Sample-size gate on BOTH windows — protects against pages on
        # the noise of a barely-fired reason.
        if c_shown < min_shown or p_shown < min_shown:
            continue
        c_ctr = (c_clicked / c_shown) * 100
        p_ctr = (p_clicked / p_shown) * 100
        delta_pp = round(c_ctr - p_ctr, 2)
        if delta_pp > -drop_pp:  # not a deep enough collapse
            continue
        flagged.append({
            "reason": reason,
            "curr_shown": c_shown,
            "curr_clicked": c_clicked,
            "curr_ctr_pct": round(c_ctr, 2),
            "prev_shown": p_shown,
            "prev_clicked": p_clicked,
            "prev_ctr_pct": round(p_ctr, 2),
            "delta_pp": delta_pp,
        })

    if not flagged:
        return []

    # Sort worst-collapse-first so the alert body leads with the most
    # damaging regression.
    flagged.sort(key=lambda r: r["delta_pp"])

    last = _REVIEW_PROMPT_ALERT_LAST_FIRED.get("review_prompt_reason_ctr_drop")
    if last is not None and (now_ts - last) < REVIEW_PROMPT_ALERT_COOLDOWN_S:
        return []

    reason_lines: List[str] = []
    for r in flagged:
        reason_lines.append(
            f"  · {r['reason']}: CTR {r['prev_ctr_pct']:.1f}% → "
            f"{r['curr_ctr_pct']:.1f}% ({r['delta_pp']:+.1f} pp, "
            f"{r['curr_clicked']}/{r['curr_shown']} this week, "
            f"{r['prev_clicked']}/{r['prev_shown']} prev)"
        )
    body_lines = [
        (
            f"{len(flagged)} review-prompt trigger reason(s) saw a "
            f"CTR drop ≥ {drop_pp:.1f} pp week-over-week with ≥ "
            f"{min_shown} shown events in both windows:"
        ),
        *reason_lines,
        (
            "A regression confined to one reason is invisible to the "
            "aggregate `review_prompt_ctr_low` alert — investigate the "
            "specific trigger surface(s) before it washes out the "
            "overall number."
        ),
        f"Dashboard: {_REVIEW_PROMPT_DASHBOARD_URL}",
    ]
    title_reason = flagged[0]["reason"]
    if len(flagged) == 1:
        title = f"Review-prompt CTR collapsed for `{title_reason}` (WoW)"
    else:
        title = (
            f"Review-prompt CTR collapsed for {len(flagged)} reasons "
            f"(worst: `{title_reason}`)"
        )
    return [{
        "alert_type": "review_prompt_reason_ctr_drop",
        "title": title,
        "body": "\n".join(body_lines),
        "threshold_snapshot": {
            "metric": "review_prompt_reason_ctr_delta_pp",
            "value": -drop_pp,
            "min_shown": min_shown,
            "window_days": window_days,
            "reasons": flagged,
        },
    }]


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
            try:
                alerts = list(alerts) + list(
                    await _evaluate_review_prompt_reason_ctr_drop_alerts()
                )
            except Exception as exc:
                logger.debug(
                    f"reason-ctr-drop evaluator raised; skipping this tick: {exc}"
                )
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


# ─────────────────────────────────────────────────────────────────────────────
# Task #655 — weekly review-prompt summary email
#
# Background loop (modeled on `_seo_weekly_digest_loop` in
# `routes.bot_discovery`) that emails ops a 7-day rollup of the Google
# review-prompt funnel every Monday ~09:00 IST (= 03:30 UTC):
#   - shown / clicked / dismissed totals + CTR
#   - week-over-week CTR delta vs the previous 7 days
#   - top trigger reason in the window
#   - per-reason breakdown
#
# Reuses the existing alert/email plumbing:
#   - Resend SDK (same api key / from address as `email_templates`)
#   - admin email channel resolved through `metrics._notification_channels`
#     (falls back to env `ALERT_EMAIL`)
#
# Dedup is atomic across replicas via a singleton lock document in
# `db.job_locks` (same pattern the SEO digest uses) so multiple Railway
# replicas don't double-fire.
# ─────────────────────────────────────────────────────────────────────────────

REVIEW_PROMPT_WEEKLY_DIGEST_WINDOW_DAYS = 7
_REVIEW_PROMPT_DIGEST_DASHBOARD_URL = (
    "https://syrabit.ai/admin/dashboard?tab=overview#review-prompt-funnel"
)
_REVIEW_PROMPT_DIGEST_LOCK_ID = "review_prompt_weekly_digest_lock"
_REVIEW_PROMPT_DIGEST_API_CONFIG_KEY = "review_prompt_weekly_digest_last_iso_week"
# Same Monday 03:30 UTC (= 09:00 IST) target as the SEO digest so ops
# get one weekly inbox burst rather than two staggered ones.
_REVIEW_PROMPT_DIGEST_TARGET_WEEKDAY = 0
_REVIEW_PROMPT_DIGEST_TARGET_HOUR_UTC = 3
_REVIEW_PROMPT_DIGEST_TARGET_MINUTE_UTC = 30
_REVIEW_PROMPT_DIGEST_TOLERANCE_MINUTES = 15
_REVIEW_PROMPT_DIGEST_LOOP_SLEEP_S = 300  # poll every 5 minutes


def _review_prompt_iso_week_tag(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _should_send_review_prompt_digest_now(now_utc: datetime, last_iso_week: str) -> bool:
    """Pure gate predicate so the schedule logic can be unit-tested.
    True iff ``now_utc`` is within ±_REVIEW_PROMPT_DIGEST_TOLERANCE_MINUTES of
    Monday 03:30 UTC AND we have not already sent a digest this ISO week.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if now_utc.weekday() != _REVIEW_PROMPT_DIGEST_TARGET_WEEKDAY:
        return False
    target = now_utc.replace(
        hour=_REVIEW_PROMPT_DIGEST_TARGET_HOUR_UTC,
        minute=_REVIEW_PROMPT_DIGEST_TARGET_MINUTE_UTC,
        second=0, microsecond=0,
    )
    delta_minutes = abs((now_utc - target).total_seconds()) / 60.0
    if delta_minutes > _REVIEW_PROMPT_DIGEST_TOLERANCE_MINUTES:
        return False
    return _review_prompt_iso_week_tag(now_utc) != (last_iso_week or "")


def _ctr_pct_or_none(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 1)


def _compose_review_prompt_weekly_digest(
    curr_totals: Dict[str, int],
    curr_by_reason: List[Dict[str, Any]],
    prev_totals: Dict[str, int],
    prev_by_reason: Optional[List[Dict[str, Any]]] = None,
    *,
    now: Optional[datetime] = None,
    dashboard_url: str = _REVIEW_PROMPT_DIGEST_DASHBOARD_URL,
    window_days: int = REVIEW_PROMPT_WEEKLY_DIGEST_WINDOW_DAYS,
) -> Dict[str, Any]:
    """Pure aggregator: turn raw per-window event counts into the digest
    payload consumed by ``_format_review_prompt_weekly_digest_html`` and
    the manual-trigger admin endpoint.

    ``curr_by_reason`` is a list of dicts with the same shape returned by
    ``admin_review_prompt_stats`` (``reason``, ``shown``, ``clicked``,
    ``dismissed``).
    """
    _now = now or datetime.now(timezone.utc)
    if _now.tzinfo is None:
        _now = _now.replace(tzinfo=timezone.utc)
    window_end = _now
    window_start = _now - timedelta(days=window_days)

    shown = int(curr_totals.get("shown") or 0)
    clicked = int(curr_totals.get("clicked") or 0)
    dismissed = int(curr_totals.get("dismissed") or 0)
    ctr_pct = _ctr_pct_or_none(clicked, shown)
    dismiss_rate_pct = _ctr_pct_or_none(dismissed, shown)

    prev_shown = int(prev_totals.get("shown") or 0)
    prev_clicked = int(prev_totals.get("clicked") or 0)
    prev_dismissed = int(prev_totals.get("dismissed") or 0)
    prev_ctr_pct = _ctr_pct_or_none(prev_clicked, prev_shown)

    if ctr_pct is None or prev_ctr_pct is None:
        ctr_delta_pct = None
        ctr_trend = "flat"
    else:
        ctr_delta_pct = round(ctr_pct - prev_ctr_pct, 1)
        if ctr_delta_pct > 0:
            ctr_trend = "up"
        elif ctr_delta_pct < 0:
            ctr_trend = "down"
        else:
            ctr_trend = "flat"

    # Normalise + sort by-reason; compute per-reason CTR + WoW deltas
    # (Task #659) so the digest table can show which trigger reason
    # is responsible for the swing instead of just the overall CTR.
    prev_by_reason_map: Dict[str, Dict[str, int]] = {}
    for row in prev_by_reason or []:
        prev_by_reason_map[str(row.get("reason") or "unknown")] = {
            "shown": int(row.get("shown") or 0),
            "clicked": int(row.get("clicked") or 0),
            "dismissed": int(row.get("dismissed") or 0),
        }

    by_reason: List[Dict[str, Any]] = []
    seen_reasons: set = set()
    for row in curr_by_reason or []:
        reason = str(row.get("reason") or "unknown")
        seen_reasons.add(reason)
        r_shown = int(row.get("shown") or 0)
        r_clicked = int(row.get("clicked") or 0)
        r_dismissed = int(row.get("dismissed") or 0)
        prev = prev_by_reason_map.get(reason, {})
        p_shown = int(prev.get("shown") or 0)
        p_clicked = int(prev.get("clicked") or 0)
        p_ctr = _ctr_pct_or_none(p_clicked, p_shown)
        r_ctr = _ctr_pct_or_none(r_clicked, r_shown)
        ctr_delta = (
            round(r_ctr - p_ctr, 1)
            if (r_ctr is not None and p_ctr is not None) else None
        )
        status = "new" if (p_shown == 0 and p_clicked == 0) else "active"
        by_reason.append({
            "reason": reason,
            "shown": r_shown,
            "clicked": r_clicked,
            "dismissed": r_dismissed,
            "ctr_pct": r_ctr,
            "prev_shown": p_shown,
            "prev_clicked": p_clicked,
            "prev_ctr_pct": p_ctr,
            "shown_delta": r_shown - p_shown,
            "ctr_delta_pct": ctr_delta,
            "status": status,
        })
    # Reasons that fired last week but disappeared this week — call them
    # out so a regression that silenced a trigger surface is visible.
    for reason, prev in prev_by_reason_map.items():
        if reason in seen_reasons:
            continue
        p_shown = int(prev.get("shown") or 0)
        p_clicked = int(prev.get("clicked") or 0)
        p_ctr = _ctr_pct_or_none(p_clicked, p_shown)
        by_reason.append({
            "reason": reason,
            "shown": 0,
            "clicked": 0,
            "dismissed": 0,
            "ctr_pct": None,
            "prev_shown": p_shown,
            "prev_clicked": p_clicked,
            "prev_ctr_pct": p_ctr,
            "shown_delta": -p_shown,
            "ctr_delta_pct": None,
            "status": "gone",
        })
    by_reason.sort(key=lambda r: (r["shown"], r["clicked"]), reverse=True)

    # Top trigger reason = highest shown count in the window. Tie-broken
    # by clicked (already enforced by the sort above).
    top_reason = by_reason[0] if by_reason and by_reason[0]["shown"] > 0 else None

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_days": window_days,
        "iso_week": _review_prompt_iso_week_tag(_now),
        "shown": shown,
        "clicked": clicked,
        "dismissed": dismissed,
        "ctr_pct": ctr_pct,
        "dismiss_rate_pct": dismiss_rate_pct,
        "prev_shown": prev_shown,
        "prev_clicked": prev_clicked,
        "prev_dismissed": prev_dismissed,
        "prev_ctr_pct": prev_ctr_pct,
        "ctr_delta_pct": ctr_delta_pct,
        "ctr_trend": ctr_trend,
        "top_reason": top_reason,
        "by_reason": by_reason,
        "dashboard_url": dashboard_url,
    }


def _format_review_prompt_weekly_digest_html(stats: Dict[str, Any]) -> str:
    """Render the digest payload as a Resend-compatible HTML email body."""
    import html as _html
    shown = int(stats.get("shown") or 0)
    clicked = int(stats.get("clicked") or 0)
    dismissed = int(stats.get("dismissed") or 0)
    ctr_pct = stats.get("ctr_pct")
    prev_ctr_pct = stats.get("prev_ctr_pct")
    delta = stats.get("ctr_delta_pct")
    trend = stats.get("ctr_trend") or "flat"
    dashboard = stats.get("dashboard_url") or _REVIEW_PROMPT_DIGEST_DASHBOARD_URL
    window_days = int(stats.get("window_days") or REVIEW_PROMPT_WEEKLY_DIGEST_WINDOW_DAYS)

    ctr_str = "—" if ctr_pct is None else f"{ctr_pct:.1f}%"
    prev_ctr_str = "—" if prev_ctr_pct is None else f"{prev_ctr_pct:.1f}%"
    if delta is None:
        delta_html = "<span style='color:#475569'>n/a</span>"
    else:
        arrow = "▲" if trend == "up" else ("▼" if trend == "down" else "▬")
        color = "#16a34a" if trend == "up" else ("#c0392b" if trend == "down" else "#475569")
        sign = "+" if delta > 0 else ""
        delta_html = (
            f"<span style='color:{color};font-weight:bold'>"
            f"{arrow} {sign}{delta:.1f} pp</span>"
        )

    top = stats.get("top_reason")
    if top:
        top_ctr = "—" if top.get("ctr_pct") is None else f"{top['ctr_pct']:.1f}%"
        top_html = (
            f"<b>{_html.escape(str(top.get('reason','unknown')))}</b> · "
            f"{int(top.get('shown') or 0)} shown · "
            f"{int(top.get('clicked') or 0)} clicked · "
            f"CTR {top_ctr}"
        )
    else:
        top_html = "<span style='color:#94a3b8'>no events recorded</span>"

    def _fmt_shown_delta(row: Dict[str, Any]) -> str:
        status = row.get("status")
        if status == "new":
            return (
                "<span style='color:#16a34a;font-weight:bold'>new</span>"
            )
        if status == "gone":
            return (
                "<span style='color:#c0392b;font-weight:bold'>gone</span>"
            )
        d = row.get("shown_delta")
        if d is None:
            return "<span style='color:#475569'>n/a</span>"
        if d > 0:
            return f"<span style='color:#16a34a'>+{int(d):,}</span>"
        if d < 0:
            return f"<span style='color:#c0392b'>{int(d):,}</span>"
        return "<span style='color:#475569'>0</span>"

    def _fmt_ctr_delta(row: Dict[str, Any]) -> str:
        status = row.get("status")
        if status in ("new", "gone"):
            # CTR delta isn't meaningful when one side is missing.
            return "<span style='color:#94a3b8'>—</span>"
        d = row.get("ctr_delta_pct")
        if d is None:
            return "<span style='color:#475569'>n/a</span>"
        if d > 0:
            return f"<span style='color:#16a34a;font-weight:bold'>▲ +{d:.1f} pp</span>"
        if d < 0:
            return f"<span style='color:#c0392b;font-weight:bold'>▼ {d:.1f} pp</span>"
        return "<span style='color:#475569'>▬ 0.0 pp</span>"

    by_reason = stats.get("by_reason") or []
    rows_html: List[str] = []
    for row in by_reason[:8]:
        r_ctr = "—" if row.get("ctr_pct") is None else f"{row['ctr_pct']:.1f}%"
        rows_html.append(
            "<tr>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0'>{_html.escape(str(row.get('reason','unknown')))}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right'>{int(row.get('shown') or 0)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right'>{int(row.get('clicked') or 0)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right'>{int(row.get('dismissed') or 0)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right'><b>{r_ctr}</b></td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right'>{_fmt_shown_delta(row)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e2e8f0;text-align:right'>{_fmt_ctr_delta(row)}</td>"
            "</tr>"
        )
    by_reason_table = (
        "<table style='border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 18px'>"
        "<tr style='background:#f3f4f6'>"
        "<th style='text-align:left;padding:6px 10px;border:1px solid #e2e8f0'>Trigger reason</th>"
        "<th style='text-align:right;padding:6px 10px;border:1px solid #e2e8f0'>Shown</th>"
        "<th style='text-align:right;padding:6px 10px;border:1px solid #e2e8f0'>Clicked</th>"
        "<th style='text-align:right;padding:6px 10px;border:1px solid #e2e8f0'>Dismissed</th>"
        "<th style='text-align:right;padding:6px 10px;border:1px solid #e2e8f0'>CTR</th>"
        "<th style='text-align:right;padding:6px 10px;border:1px solid #e2e8f0'>Δ shown vs prev week</th>"
        "<th style='text-align:right;padding:6px 10px;border:1px solid #e2e8f0'>Δ CTR vs prev week</th>"
        "</tr>"
        + "".join(rows_html)
        + "</table>"
    ) if rows_html else "<p style='color:#94a3b8;font-size:13px'>No per-reason breakdown — no events fired this week.</p>"

    return (
        "<div style='font-family:sans-serif;max-width:560px;margin:auto;padding:24px;color:#0f172a'>"
        "<h2 style='color:#7c3aed;margin:0 0 4px'>Syrabit.ai · Google review prompt — weekly summary</h2>"
        f"<p style='color:#64748b;margin:0 0 18px;font-size:13px'>"
        f"Window: {stats.get('window_start','')[:10]} → {stats.get('window_end','')[:10]} "
        f"(ISO week {stats.get('iso_week','')}, last {window_days}d)"
        "</p>"
        "<table style='border-collapse:collapse;width:100%;font-size:14px;margin-bottom:18px'>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Prompt shown</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'><b>{shown:,}</b></td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Clicked</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'><b>{clicked:,}</b></td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Dismissed</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'><b>{dismissed:,}</b></td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Click-through rate</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'><b>{ctr_str}</b></td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Prev-week CTR</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'>{prev_ctr_str}</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Week-over-week change</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'>{delta_html}</td></tr>"
        f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>Top trigger reason</td>"
        f"<td style='padding:8px;border:1px solid #e2e8f0;text-align:right'>{top_html}</td></tr>"
        "</table>"
        "<h3 style='color:#0f172a;margin:16px 0 6px;font-size:14px'>Per-reason breakdown</h3>"
        f"{by_reason_table}"
        f"<p style='margin:18px 0'><a href='{dashboard}' style='display:inline-block;background:#7c3aed;"
        "color:white;text-decoration:none;padding:10px 20px;border-radius:8px;font-weight:600;font-size:14px'>"
        "Open review-prompt funnel</a></p>"
        "<p style='color:#94a3b8;font-size:12px;margin-top:24px'>"
        "You're getting this because you're listed as the Syrabit.ai admin email contact. "
        "To stop these weekly summaries, clear the email channel in /admin notifications."
        "</p></div>"
    )


async def _aggregate_review_prompt_window(since: datetime, until: datetime) -> Dict[str, Any]:
    """Aggregate review_prompt_events between ``since`` (inclusive) and
    ``until`` (exclusive) into ``{totals, by_reason}``. Returns a
    zero-shape on Mongo failure so the digest gracefully degrades.
    """
    out: Dict[str, Any] = {
        "totals": {"shown": 0, "clicked": 0, "dismissed": 0},
        "by_reason": [],
    }
    if not await is_mongo_available():
        return out
    try:
        coll = db.review_prompt_events
        base = {"created_at": {"$gte": since, "$lt": until}}
        ev_in = {"event": {"$in": list(_REVIEW_PROMPT_VALID_EVENTS)}}

        totals_map: Dict[str, int] = {e: 0 for e in _REVIEW_PROMPT_VALID_EVENTS}
        cur = coll.aggregate([
            {"$match": {**base, **ev_in}},
            {"$group": {"_id": "$event", "count": {"$sum": 1}}},
        ])
        async for row in cur:
            ev = row.get("_id")
            if ev in totals_map:
                totals_map[ev] = int(row.get("count") or 0)
        out["totals"] = {
            "shown": totals_map["review_prompt_shown"],
            "clicked": totals_map["review_prompt_clicked"],
            "dismissed": totals_map["review_prompt_dismissed"],
        }

        by_reason_map: Dict[str, Dict[str, int]] = {}
        cur2 = coll.aggregate([
            {"$match": {**base, **ev_in}},
            {"$group": {
                "_id": {"reason": "$reason", "event": "$event"},
                "count": {"$sum": 1},
            }},
        ])
        async for row in cur2:
            key = row.get("_id") or {}
            reason = key.get("reason") or "unknown"
            ev = key.get("event")
            bucket = by_reason_map.setdefault(reason, {
                "shown": 0, "clicked": 0, "dismissed": 0,
            })
            if ev == "review_prompt_shown":
                bucket["shown"] += int(row.get("count") or 0)
            elif ev == "review_prompt_clicked":
                bucket["clicked"] += int(row.get("count") or 0)
            elif ev == "review_prompt_dismissed":
                bucket["dismissed"] += int(row.get("count") or 0)
        out["by_reason"] = [
            {"reason": r, **counts} for r, counts in by_reason_map.items()
        ]
    except Exception as exc:
        logger.debug(f"review-prompt window aggregation failed: {exc}")
    return out


async def _gather_review_prompt_weekly_digest_inputs(
    now: Optional[datetime] = None,
    *,
    window_days: int = REVIEW_PROMPT_WEEKLY_DIGEST_WINDOW_DAYS,
) -> Dict[str, Any]:
    """Pull current and prior 7-day windows from Mongo and compose the
    digest stats. Returns ``{}`` when Mongo is unavailable so the loop
    can no-op cleanly.
    """
    if not await is_mongo_available():
        return {}
    _now = now or datetime.now(timezone.utc)
    if _now.tzinfo is None:
        _now = _now.replace(tzinfo=timezone.utc)
    curr_start = _now - timedelta(days=window_days)
    prev_start = _now - timedelta(days=window_days * 2)

    curr = await _aggregate_review_prompt_window(curr_start, _now)
    prev = await _aggregate_review_prompt_window(prev_start, curr_start)
    return _compose_review_prompt_weekly_digest(
        curr["totals"], curr["by_reason"], prev["totals"],
        prev_by_reason=prev["by_reason"],
        now=_now, window_days=window_days,
    )


def _resolve_review_prompt_digest_recipients(
    override: Optional[Any] = None,
) -> List[str]:
    """Return the ordered, deduped list of recipients for the weekly
    review-prompt digest.

    Resolution order (Task #660):
      1. ``override`` (str / list / comma-separated) — used by the manual
         "send me a test" button so admins can target an arbitrary
         address without first persisting it.
      2. ``metrics._notification_channels["review_prompt_digest_emails"]``
         — the dedicated digest list configured from the admin
         notifications panel.
      3. ``metrics._notification_channels["email"]`` — the legacy
         single-admin alert email, kept as a fallback so existing
         installs that haven't configured the new field keep working.
      4. ``ALERT_EMAIL`` env var — last-ditch fallback.

    Anything obviously bogus (no ``@``, blank, non-string) is dropped
    and addresses are deduped case-insensitively while preserving order.
    """
    candidates: List[str] = []

    def _extend(raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, str):
            for part in raw.split(","):
                p = part.strip()
                if p:
                    candidates.append(p)
        elif isinstance(raw, (list, tuple, set)):
            for item in raw:
                if isinstance(item, str):
                    p = item.strip()
                    if p:
                        candidates.append(p)

    if override is not None:
        _extend(override)
    if not candidates:
        try:
            from metrics import _notification_channels
            _extend(_notification_channels.get("review_prompt_digest_emails"))
            if not candidates:
                _extend(_notification_channels.get("email"))
        except Exception:
            pass
    if not candidates:
        _extend(os.environ.get("ALERT_EMAIL", ""))

    seen: set = set()
    cleaned: List[str] = []
    for c in candidates:
        if "@" not in c:
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(c)
    return cleaned


async def _send_review_prompt_weekly_digest_email(
    stats: Dict[str, Any], *, to: Optional[Any] = None,
) -> Dict[str, Any]:
    """Send the rendered digest via Resend. Returns
    ``{sent, to, recipients, reason?, subject?}`` so the loop and the
    manual-trigger / test-send endpoints can surface the outcome.

    ``to`` may be ``None`` (use the configured recipient list), a single
    address string, a comma-separated string, or a list of addresses
    (Task #660 — admin-configurable recipient list distinct from the
    incident-alert email channel).
    """
    if not stats:
        return {"sent": False, "to": "", "recipients": [], "reason": "no_stats"}
    try:
        from metrics import _load_alert_settings
        try:
            await _load_alert_settings()
        except Exception:
            pass
    except Exception:
        pass
    recipients = _resolve_review_prompt_digest_recipients(to)
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not recipients:
        return {"sent": False, "to": "", "recipients": [], "reason": "no_admin_email"}
    # Preserve legacy single-string ``to`` field for callers / tests that
    # only inspected the first recipient (the digest used to be 1:1).
    primary = recipients[0]
    if not resend_key:
        return {
            "sent": False, "to": primary, "recipients": recipients,
            "reason": "no_resend_key",
        }
    try:
        from email_templates import EMAIL_FROM as _from
    except Exception:
        _from = os.environ.get(
            "EMAIL_FROM", "Syrabit.ai <noreply@syrabit.ai>",
        ).strip()
    html = _format_review_prompt_weekly_digest_html(stats)
    ctr_pct = stats.get("ctr_pct")
    ctr_str = "—" if ctr_pct is None else f"{ctr_pct:.1f}%"
    subject = (
        f"Syrabit review-prompt weekly · "
        f"CTR {ctr_str} · "
        f"{stats.get('iso_week','')}"
    )
    try:
        import resend as _resend_sdk
        _resend_sdk.api_key = resend_key
        _resend_sdk.Emails.send({
            "from": _from,
            "to": list(recipients),
            "subject": subject,
            "html": html,
        })
        logger.info(
            f"[review-prompt digest] sent → {', '.join(recipients)} "
            f"({stats.get('iso_week','')})"
        )
        return {
            "sent": True, "to": primary, "recipients": recipients,
            "subject": subject,
        }
    except Exception as exc:
        logger.warning(f"[review-prompt digest] Resend send failed: {exc}")
        return {
            "sent": False, "to": primary, "recipients": recipients,
            "reason": f"send_error:{type(exc).__name__}",
        }


async def _claim_review_prompt_weekly_digest_slot(_db, cur_iso_week: str) -> bool:
    """Atomic compare-and-set on a singleton lock document inside
    ``job_locks`` (``_id`` = ``_REVIEW_PROMPT_DIGEST_LOCK_ID``). Mirrors
    ``_claim_weekly_digest_slot`` in ``routes.bot_discovery``.

    Returns True iff this caller successfully advanced the marker from
    ``!= cur_iso_week`` to ``cur_iso_week`` — guaranteeing at most one
    digest send per ISO week even with multiple replicas.
    """
    from pymongo.errors import DuplicateKeyError
    try:
        res = await _db.job_locks.find_one_and_update(
            {
                "_id": _REVIEW_PROMPT_DIGEST_LOCK_ID,
                _REVIEW_PROMPT_DIGEST_API_CONFIG_KEY: {"$ne": cur_iso_week},
            },
            {"$set": {_REVIEW_PROMPT_DIGEST_API_CONFIG_KEY: cur_iso_week}},
            upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(f"[review-prompt digest] CAS update failed: {exc}")
        return False
    try:
        await _db.job_locks.insert_one({
            "_id": _REVIEW_PROMPT_DIGEST_LOCK_ID,
            _REVIEW_PROMPT_DIGEST_API_CONFIG_KEY: cur_iso_week,
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"[review-prompt digest] bootstrap insert failed: {exc}")
        return False


async def _try_send_review_prompt_weekly_digest_once(
    _db, now_utc: datetime,
) -> Dict[str, Any]:
    """One iteration of the digest loop, factored out for testability."""
    cur_iso_week = _review_prompt_iso_week_tag(now_utc)
    try:
        cfg = await _db.job_locks.find_one(
            {"_id": _REVIEW_PROMPT_DIGEST_LOCK_ID},
            {"_id": 0, _REVIEW_PROMPT_DIGEST_API_CONFIG_KEY: 1},
        ) or {}
    except Exception:
        cfg = {}
    last_sent = cfg.get(_REVIEW_PROMPT_DIGEST_API_CONFIG_KEY, "")
    if not _should_send_review_prompt_digest_now(now_utc, last_sent):
        return {"claimed": False, "sent": False, "reason": "outside_window_or_dedup"}
    if not await _claim_review_prompt_weekly_digest_slot(_db, cur_iso_week):
        return {"claimed": False, "sent": False, "reason": "lost_race"}

    stats = await _gather_review_prompt_weekly_digest_inputs(now_utc)
    result = await _send_review_prompt_weekly_digest_email(stats)
    if not result.get("sent"):
        # Roll the marker back so a subsequent poll inside the same
        # window can retry (transient Resend outage, etc.).
        logger.info(
            f"[review-prompt digest] send failed for {cur_iso_week} "
            f"(reason={result.get('reason','unknown')}); rolling back claim"
        )
        try:
            await _db.job_locks.update_one(
                {
                    "_id": _REVIEW_PROMPT_DIGEST_LOCK_ID,
                    _REVIEW_PROMPT_DIGEST_API_CONFIG_KEY: cur_iso_week,
                },
                {"$set": {_REVIEW_PROMPT_DIGEST_API_CONFIG_KEY: last_sent or ""}},
            )
        except Exception:
            pass
    return {
        "claimed": True,
        "sent": result.get("sent", False),
        "reason": result.get("reason"),
    }


async def _review_prompt_weekly_digest_loop():
    """Background loop for the weekly review-prompt digest. Polls every
    ``_REVIEW_PROMPT_DIGEST_LOOP_SLEEP_S`` (5 min) and only fires inside
    a ±15 min window around Monday 03:30 UTC (= 09:00 IST). Best-effort
    — swallows its own errors so a flaky Mongo can't kill the task.
    """
    # Stagger boot so we don't pile onto the startup burst alongside
    # the SEO digest loop (which sleeps 600s).
    await asyncio.sleep(720)
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            if await is_mongo_available():
                await _try_send_review_prompt_weekly_digest_once(db, now_utc)
        except Exception as exc:
            logger.debug(f"[review-prompt digest] loop iteration error: {exc}")
        await asyncio.sleep(_REVIEW_PROMPT_DIGEST_LOOP_SLEEP_S)


@router.post("/admin/analytics/review-prompt-weekly-digest/send")
async def admin_review_prompt_weekly_digest_send(
    body: Optional[Dict[str, Any]] = Body(None),
    preview_only: bool = Query(
        False,
        description="If true, return the rendered stats/HTML without sending the email.",
    ),
    admin: dict = Depends(get_admin_user),
):
    """Manually trigger (or preview) the weekly review-prompt digest.
    Useful for QA and for catching up after an outage. Does not advance
    the ISO-week dedup marker so the regular Monday send still happens.

    Optional JSON body:
      ``{"to": "ops@example.com" | ["a@x", "b@y"]}`` overrides the
      configured recipient list — used by the admin "send me a test
      now" button so admins can sanity-check delivery before saving the
      list (Task #660).
    """
    override_to: Optional[Any] = None
    if isinstance(body, dict):
        override_to = body.get("to")
    stats = await _gather_review_prompt_weekly_digest_inputs()
    html = _format_review_prompt_weekly_digest_html(stats) if stats else ""
    if preview_only:
        # Surface the resolved recipient list so the admin UI can show
        # who *would* receive a non-preview send without actually firing
        # email — useful for confirming the configured list is valid.
        return {
            "sent": False,
            "preview": True,
            "stats": stats,
            "html": html,
            "recipients": _resolve_review_prompt_digest_recipients(override_to),
        }
    result = await _send_review_prompt_weekly_digest_email(stats, to=override_to)
    return {
        "sent": result.get("sent", False),
        "to": result.get("to", ""),
        "recipients": result.get("recipients", []),
        "reason": result.get("reason"),
        "subject": result.get("subject"),
        "stats": stats,
    }
