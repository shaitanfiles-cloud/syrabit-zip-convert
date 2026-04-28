"""Task #952 — Alert operators when busy hours still lose Cloudflare buckets.

Task #948 added pagination to the Cloudflare GraphQL pull so the
``httpRequestsAdaptiveGroups`` cap (200 distinct buckets per call) no
longer silently drops surplus rows when the window is busy. The pull
recursively halves the time range on minute boundaries until each
slice fits under the cap. When even a single ``CF_PULL_MIN_WINDOW_S``
(60s) slice is still saturated, the affected minute is recorded on
the cursor doc as ``last_saturated_windows`` and exposed via
``/api/admin/logs/status`` as ``cf_pull_last_saturated_windows`` —
but until this module landed, nobody was actively watching that
field. An admin had to open the status panel and read a list of
ISO timestamps to notice that traffic was high enough to drop
buckets.

This module closes that gap:

  * ``record_saturated_windows`` is called fire-and-forget by
    ``_try_run_cf_pull_once`` (Task #948 wiring) every time a tick
    yields a non-empty ``saturated_windows``. It persists each
    saturated minute to the ``cf_pull_saturated_minutes`` collection,
    deduplicating by minute ISO so the same minute saturating across
    multiple ticks doesn't double-count. The collection has a 25h
    TTL index so the rolling 24h count never grows unbounded.
  * ``maybe_alert_on_saturation`` fires an in-app + email alert when
    NEW saturated minutes are observed, debounced to one page per
    24h via the standard ``unified_logs_cf_pull_saturation_alert_state``
    job_lock CAS (mirrors the cf-waf-drift / cf-pull-silence pattern).
  * ``count_saturated_minutes_24h`` is called by ``/api/admin/logs/status``
    so the admin dashboard shows "saturated minutes in last 24h: N"
    next to the existing ``cf_pull_last_saturated_windows`` snapshot.
  * ``ensure_saturation_indexes`` creates the TTL index at startup
    (called from ``server.py``'s unified-logs wiring block).

Lock-doc snapshot + paged-history audit endpoints surface the alert
state to the AdminHealth dashboard via the same shaping helpers the
cf-waf-drift / cf-pull-silence pills already use, so the admin
surface stays consistent.

Why we hook directly into ``_try_run_cf_pull_once`` instead of a
separate poll loop
-------------------------------------------------------------------
The saturation signal is *exactly* the saturated_windows list we
already compute inside the pull. There's no observability lag to
absorb (unlike the silence alerter, which is detecting the *absence*
of a successful tick) and adding a second poll loop would just
duplicate the per-replica lease bookkeeping for no benefit. Doing
the record + alert inline (as a fire-and-forget task so a slow Mongo
or email provider can't stall the pull loop) keeps the alert latency
sub-second from the moment a busy minute is detected.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends

from auth_deps import get_admin_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Tunables ───────────────────────────────────────────────────────────────

# One doc per saturated minute, keyed by the minute's ISO timestamp
# so the same minute saturating across multiple ticks dedups
# naturally. Created with a 25h TTL on ``first_observed_at`` — long
# enough to compute a rolling 24h count plus a small safety margin
# for clock skew, short enough that the collection never grows past
# ~1500 docs in worst case (one saturated minute per minute for 25h).
SATURATION_COLLECTION = "cf_pull_saturated_minutes"
_TTL_S = 25 * 3600

# Reported back by the admin pill so the AdminHealth dashboard can show
# the dedupe window the alerter is using. Saturation alerts dedupe at
# the *minute* level (each unique saturated minute alerts at most once
# via the ``cf_pull_saturated_minutes`` collection's primary key) rather
# than the *time-window* level used by sibling alerters — Task #952's
# done condition is "alert fires whenever a tick reports a non-empty
# saturated_windows", and time-window debouncing would silently drop
# alerts about distinct, NEW saturated minutes whenever they happened
# to land inside an open debounce window. The minute-level dedupe is
# enough to keep alert volume bounded (worst case: 1440 minutes/day)
# while still surfacing every distinct saturation event.
_DEDUPE_WINDOW_S = 60  # one minute = one alert (effective floor)

_LOCK_ID = "unified_logs_cf_pull_saturation_alert_state"
_STATUS_URL = "/api/admin/logs/status"


# ─── Index bootstrap ────────────────────────────────────────────────────────

async def ensure_saturation_indexes(db) -> None:
    """Create the TTL index on ``cf_pull_saturated_minutes`` so the
    rolling 24h count never has to scan beyond its useful retention.

    Idempotent — Motor's ``create_index`` is a no-op when the index
    already exists with the same spec. Failures are logged but never
    propagate (the count still works without the index, just slower
    than necessary, and the collection bounded grows back to ~1500
    docs once the TTL kicks in).
    """
    if db is None:
        return
    try:
        await db[SATURATION_COLLECTION].create_index(
            "first_observed_at",
            expireAfterSeconds=_TTL_S,
            name="ttl_first_observed_at",
        )
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] TTL index create failed: {exc}"
        )


# ─── Recording: persist saturated minutes & flag fresh ones ─────────────────

async def record_saturated_windows(
    db,
    saturated_windows: Iterable[Any],
    now_utc: Optional[datetime] = None,
) -> list[tuple[str, str]]:
    """Persist each ``(since_iso, until_iso)`` saturated minute into
    ``cf_pull_saturated_minutes`` and return the subset that was newly
    observed (i.e. not already on file from a previous tick).

    Uses ``insert_one``-with-DuplicateKey-fallthrough rather than an
    upsert, because the fake Mongo used in unit tests doesn't support
    ``find_one_and_update(upsert=True)`` on a collection that doesn't
    have a matching doc — the insert path is also a clean signal of
    "this minute is fresh" without having to interpret a returned
    BEFORE doc.

    ``saturated_windows`` items can be either ``(since_iso, until_iso)``
    tuples or 2-element lists (the cursor doc round-trips them through
    BSON which preserves either shape). We coerce defensively so a
    legacy doc shape doesn't crash the recorder.

    Best-effort by contract: a Mongo failure on one minute logs at
    DEBUG and moves on; never raises (the caller is a fire-and-forget
    task inside the CF pull loop).
    """
    if db is None or not saturated_windows:
        return []
    now_utc = now_utc or datetime.now(timezone.utc)
    fresh: list[tuple[str, str]] = []
    coll = db[SATURATION_COLLECTION]
    for entry in saturated_windows:
        try:
            since_iso = str(entry[0])
            until_iso = str(entry[1])
        except Exception:
            continue
        if not since_iso:
            continue
        try:
            await coll.insert_one({
                "_id": since_iso,
                "until": until_iso,
                "first_observed_at": now_utc,
                "last_observed_at": now_utc,
            })
            fresh.append((since_iso, until_iso))
        except Exception as exc:
            # DuplicateKeyError (already on file) is the common path
            # — refresh ``last_observed_at`` so an operator can see
            # "this minute keeps coming back" if the cursor ever
            # reverses (it shouldn't, but the field is harmless).
            name = type(exc).__name__
            if "DuplicateKey" in name:
                try:
                    await coll.update_one(
                        {"_id": since_iso},
                        {"$set": {"last_observed_at": now_utc}},
                    )
                except Exception as exc2:
                    logger.debug(
                        f"[unified-logs-cf-pull-saturation] last_observed "
                        f"refresh failed for {since_iso}: {exc2}"
                    )
            else:
                logger.debug(
                    f"[unified-logs-cf-pull-saturation] persist failed "
                    f"for {since_iso}: {exc}"
                )
    return fresh


async def count_saturated_minutes_24h(
    db, now_utc: Optional[datetime] = None,
) -> int:
    """Count saturated minutes whose ``first_observed_at`` falls inside
    the last 24h. The TTL index above means stale rows are auto-purged
    after 25h, so this count never grows unbounded.

    Always returns an int; Mongo unavailable / collection missing → 0.
    """
    if db is None:
        return 0
    now_utc = now_utc or datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=24)
    try:
        return int(await db[SATURATION_COLLECTION].count_documents(
            {"first_observed_at": {"$gte": cutoff}},
        ))
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] 24h count failed: {exc}"
        )
        return 0


# ─── Health snapshot ────────────────────────────────────────────────────────

async def get_saturation_health(
    db=None, now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """Synthesize the health snapshot for the saturation alerter.

    Reads the cursor doc (``unified_logs_cf_pull_lock``) for the most
    recent ``last_saturated_windows`` and the saturation collection
    for the rolling 24h count, then projects both into the camelCase
    shape sibling pills use. Always returns 200-ready JSON.
    """
    if db is None:
        try:
            from deps import db as _db  # type: ignore
            db = _db
        except Exception:
            db = None
    out: dict[str, Any] = {
        "configured": False,
        "lastSaturatedWindows": [],
        "lastSaturatedAt": None,
        "saturatedCount24h": 0,
    }
    try:
        from config import CF_ZONE_ID, CF_ANALYTICS_API_TOKEN
        out["configured"] = bool(CF_ZONE_ID and CF_ANALYTICS_API_TOKEN)
    except Exception:
        out["configured"] = False
    if db is None:
        return out
    try:
        from routes.admin_logs import CF_PULL_LOCK_ID
        lock = await db.job_locks.find_one({"_id": CF_PULL_LOCK_ID})
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] lock read failed: {exc}"
        )
        lock = None
    if lock:
        sw = lock.get("last_saturated_windows") or []
        out["lastSaturatedWindows"] = list(sw)
        out["lastSaturatedAt"] = lock.get("updated_at")
    out["saturatedCount24h"] = await count_saturated_minutes_24h(db, now_utc)
    return out


# ─── Admin endpoints ────────────────────────────────────────────────────────

@router.get("/admin/health/unified-logs/cf-pull/saturation")
async def admin_unified_logs_cf_pull_saturation_health(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Health snapshot for the CF-pull saturation alerter — admin pill.

    Always 200; the dashboard branches on ``status``:
      * ``not_configured`` — CF analytics env vars unset.
      * ``saturated`` — at least one saturated minute in the last 24h.
      * ``healthy`` — no saturated minutes in the last 24h.
    """
    health = await get_saturation_health()
    if not health.get("configured"):
        status = "not_configured"
    elif health.get("saturatedCount24h", 0) > 0 or (
        health.get("lastSaturatedWindows") or []
    ):
        status = "saturated"
    else:
        status = "healthy"
    return {
        **health,
        "status": status,
        # Dedupe is per-minute (one alert per unique saturated minute,
        # never debounced beyond that — see `maybe_alert_on_saturation`).
        # Surfaced so the AdminHealth pill can show the exact dedupe
        # contract instead of guessing based on the sibling pills.
        "dedupeWindowSeconds": _DEDUPE_WINDOW_S,
        "statusUrl": _STATUS_URL,
    }


@router.get("/admin/health/unified-logs/cf-pull/saturation/alert-state")
async def admin_unified_logs_cf_pull_saturation_alert_state(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Lock-doc snapshot for the saturation alerter (Task #952).

    Mirrors the sibling cf-pull-silence ``alert-state`` route so the
    AdminHealth pill can render "last paged Nh ago" inline. Always
    200; ``present: False`` when the alerter has never fired or when
    Mongo is unavailable.

    The interval passed in is the per-minute dedupe floor (60s) — this
    alerter intentionally does not time-window-debounce, so the
    "remaining debounce" line the sibling pills render will be ~0 by
    construction (which is the correct UX for an alerter whose dedupe
    is per-event, not per-window).
    """
    from routes.admin_health import _build_alert_state_response
    return await _build_alert_state_response(
        _LOCK_ID, _DEDUPE_WINDOW_S, broken_state_label="saturated",
    )


@router.get("/admin/health/unified-logs/cf-pull/saturation/alert-history")
async def admin_unified_logs_cf_pull_saturation_alert_history(
    limit: int = 20,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Audit log of pages issued by the saturation alerter (Task #952),
    most recent first.

    Always 200; ``events: []`` when the alerter has never fired or
    when Mongo is unavailable. Mirrors the sibling alerter contracts.
    """
    from routes.admin_health import _build_alert_history_response
    return await _build_alert_history_response(_LOCK_ID, limit=limit)


# ─── Lock-doc bookkeeping for the AdminHealth pill ─────────────────────────

async def _record_alert_emission(
    db, now_utc: datetime, count_24h: int, latest_minute: Optional[str],
) -> None:
    """Update the AdminHealth pill's lock doc to reflect the most
    recent saturation alert.

    This is bookkeeping, not a guard — Task #952's done condition
    requires that every CF pull tick with a non-empty
    ``saturated_windows`` produces an admin-visible alert, so the
    alert decision is gated on per-minute dedupe (handled by the
    ``cf_pull_saturated_minutes`` collection's primary key) rather
    than a time-window debounce. The lock doc is still maintained
    so the AdminHealth `/alert-state` route can show "last paged
    Nh ago" the same way it does for sibling alerters.

    Best-effort — never raises.
    """
    payload = {
        "last_state": "saturated",
        "last_alert_at": now_utc.isoformat(),
        "last_saturated_count_24h": count_24h,
        "last_saturated_minute": latest_minute,
        "updated_at": now_utc.isoformat(),
    }
    try:
        await db.job_locks.update_one(
            {"_id": _LOCK_ID},
            {"$set": payload, "$setOnInsert": {"_id": _LOCK_ID}},
            upsert=True,
        )
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] lock doc update failed: "
            f"{exc}"
        )


# ─── Channels: email + in-app ───────────────────────────────────────────────

async def _email_admins_about_saturation(
    title: str, message: str,
) -> None:
    """Best-effort email blast to every admin. Mirrors the cf-pull-silence
    alerter so the inbox is consistent."""
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] email helper unavailable: "
            f"{exc}"
        )
        return
    admins: list[str] = []
    try:
        from deps import db as _mongo_db  # type: ignore
        if _mongo_db is not None:
            cursor = _mongo_db.users.find(
                {"is_admin": True}, {"_id": 0, "email": 1}
            )
            async for u in cursor:
                e = (u.get("email") or "").strip()
                if e:
                    admins.append(e)
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] admin lookup failed: {exc}"
        )
    html = (
        f"<h2 style='color:#dc2626;margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit unified-logs Cloudflare-pull saturation "
        f"monitor (Task #952).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                f"[unified-logs-cf-pull-saturation] email send failed "
                f"for {email}: {exc}"
            )


async def _send_saturation_alert(
    db,
    fresh: list[tuple[str, str]],
    count_24h: int,
    now_utc: datetime,
) -> None:
    """Email + in-app notification + paged-on-call audit append.

    Best-effort — never raises. The in-app notification persist is
    the canonical "we paged" signal; the email and history-record
    fan-outs are background tasks (matching the sibling alerters)
    so a slow Mongo or email provider can't stall the alert path
    or undo a notification that already succeeded.
    """
    fresh_minutes = [m[0] for m in fresh]
    sample = ", ".join(fresh_minutes[:5])
    if len(fresh_minutes) > 5:
        sample += f", +{len(fresh_minutes) - 5} more"
    title = (
        f"Cloudflare pull saturated: {len(fresh)} new minute(s) hit "
        f"the bucket cap"
    )
    msg = (
        "The Cloudflare GraphQL pull recorded one or more 1-minute "
        "windows where >200 distinct (path, status, colo, host, "
        "country, cache, method) buckets were observed. Past 200 "
        "buckets per minute the GraphQL endpoint silently truncates "
        "the response, so some traffic is being lost from the "
        "unified-logs explorer for the affected minutes.\n\n"
        f"Newly saturated minutes: {sample}\n"
        f"Saturated minutes in last 24h: {count_24h}\n\n"
        "If this is a one-off spike, no action needed — a single "
        "saturated minute under traffic surge is expected. If "
        "saturated minutes are climbing across 24h, the dimension "
        "cut is too fine for current traffic — drop `country` or "
        "`coloCode` from the GraphQL group-by (see "
        "`_pull_cf_window_paginated` in `routes/admin_logs.py`) so "
        "buckets aggregate to a coarser granularity that fits.\n\n"
        f"Status endpoint: {_STATUS_URL}"
    )
    try:
        from db_ops import supa_insert_notification
        await supa_insert_notification({
            "id": str(uuid.uuid4()),
            "title": title,
            "message": msg,
            "type": "error",
            "channel": "in_app",
            "audience": "admins",
            "status": "sent",
            "created_at": now_utc.isoformat(),
            "sent_at": now_utc.isoformat(),
            "meta": {
                "kind": "unified_logs_cf_pull_saturation_alert",
                "fresh_minutes": fresh_minutes,
                "saturated_count_24h": count_24h,
            },
        })
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] notification persist "
            f"failed: {exc}"
        )

    asyncio.create_task(_email_admins_about_saturation(title, msg))
    try:
        from routes.admin_health import record_cron_alert_event
        history_health = {
            "status": "saturated",
            "ageSeconds": None,
            "lastRunUrl": _STATUS_URL,
        }
        asyncio.create_task(record_cron_alert_event(
            db,
            lock_id=_LOCK_ID,
            kind="saturated",
            sub_kind=None,
            health=history_health,
            now_utc=now_utc,
        ))
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] history record schedule "
            f"failed: {exc}"
        )


# ─── Public entrypoint: record + maybe alert ────────────────────────────────

async def maybe_alert_on_saturation(
    db,
    fresh: list[tuple[str, str]],
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """If ``fresh`` (newly observed saturated minutes) is non-empty,
    fire the admin-visible alert.

    Per Task #952's done condition, every CF pull tick with a
    non-empty ``saturated_windows`` must surface an alert. Dedupe is
    handled at the *minute* level by ``record_saturated_windows``
    (the ``cf_pull_saturated_minutes`` collection's primary key on
    ``since_iso`` rejects re-inserts for an already-recorded minute,
    so ``fresh`` only contains genuinely new saturated minutes).
    There is no time-window debounce on top — that would silently
    drop alerts for distinct, never-before-seen saturated minutes
    just because a *different* minute happened to alert recently.

    Returns a small report dict for tests:
      * ``{"action": "skip", "reason": "no_new_saturation"}`` —
        every minute in this tick was already on file from a
        previous tick; no new information to surface.
      * ``{"action": "alerted", "fresh": [...], "count_24h": N}``
    """
    if db is None:
        return {"action": "skip", "reason": "no_db"}
    if not fresh:
        return {"action": "skip", "reason": "no_new_saturation"}
    now_utc = now_utc or datetime.now(timezone.utc)
    count_24h = await count_saturated_minutes_24h(db, now_utc)
    latest_minute = fresh[-1][0]
    await _send_saturation_alert(db, fresh, count_24h, now_utc)
    await _record_alert_emission(db, now_utc, count_24h, latest_minute)
    return {
        "action": "alerted", "fresh": fresh, "count_24h": count_24h,
    }


async def record_and_maybe_alert(
    db,
    saturated_windows: Iterable[Any],
    now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """Convenience wrapper called from ``_try_run_cf_pull_once``:
    persist the saturated minutes, then debounce + page if any were
    newly observed.

    Best-effort by contract — wraps both halves so a Mongo / email
    blip on the alert side cannot undo the persist (the rolling 24h
    counter has to keep working even when the on-call channel is
    flaky).
    """
    try:
        fresh = await record_saturated_windows(db, saturated_windows, now_utc)
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] record failed: {exc}"
        )
        fresh = []
    if not fresh:
        return {"action": "skip", "reason": "no_new_saturation"}
    try:
        return await maybe_alert_on_saturation(db, fresh, now_utc)
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-saturation] alert failed: {exc}"
        )
        return {"action": "skip", "reason": "alert_error", "fresh": fresh}
