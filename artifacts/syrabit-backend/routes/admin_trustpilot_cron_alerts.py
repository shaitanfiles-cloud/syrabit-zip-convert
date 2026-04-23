"""Task #751 — Alert when the daily Trustpilot refresh GitHub Actions cron
silently stops running (separate from the Task #728 data-staleness alert).

The cron — .github/workflows/trustpilot-aggregate-refresh.yml — POSTs an
unconditional heartbeat to ``/api/config/trustpilot/refresh-cron-heartbeat``
on every run, regardless of the inner Trustpilot fetch outcome. That
gives us a *job-level* signal independent of the *data* signal:

  * Task #728 alert fires → "Trustpilot data is stale" — could be the
    upstream API, the cron, or both.
  * THIS alert fires → "the cron itself hasn't run" — repo renamed,
    workflow disabled, secret expired, GitHub-side outage.

When BOTH fire the on-call knows the cron is the proximate cause; when
only Task #728 fires they know the cron ran but Trustpilot is down.

The implementation deliberately mirrors :mod:`routes.admin_trustpilot_alerts`
(the data-staleness alerter) so all admin alert channels look consistent
in the inbox: same Mongo CAS dedup, same email + in-app notification
shape, same 36/24h debounce semantics.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends

from auth_deps import get_admin_user
from routes.config import get_trustpilot_refresh_cron_health

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Tunables ───────────────────────────────────────────────────────────────

# How long since the last successful heartbeat before we page.
# Default 36h: the workflow runs daily at 04:30 UTC, so a fresh run is
# always <26h old. 36h gives us a 10h grace window for a single missed
# run (transient GitHub outage) before scolding.
_CRON_SILENT_THRESHOLD_S = int(
    os.environ.get("TRUSTPILOT_REFRESH_CRON_SILENT_THRESHOLD_S") or 36 * 3600
)
# Re-page cadence while still silent.
_CRON_REALERT_INTERVAL_S = int(
    os.environ.get("TRUSTPILOT_REFRESH_CRON_REALERT_INTERVAL_S") or 24 * 3600
)
# Background poll cadence + warmup.
_CRON_LOOP_SLEEP_S = int(
    os.environ.get("TRUSTPILOT_REFRESH_CRON_LOOP_SLEEP_S") or 3600
)
_CRON_WARMUP_S = int(
    os.environ.get("TRUSTPILOT_REFRESH_CRON_WARMUP_S") or 900
)
# Bootstrap grace: when the backend has never seen a heartbeat, give the
# workflow this long to register one before paging "never observed".
# Default 48h so a freshly-deployed backend doesn't immediately page if
# the daily cron happens to land on the wrong side of deploy time.
_CRON_BOOTSTRAP_GRACE_S = int(
    os.environ.get("TRUSTPILOT_REFRESH_CRON_BOOTSTRAP_GRACE_S") or 48 * 3600
)

_LOCK_ID = "trustpilot_refresh_cron_alert_state"
_DEFAULT_WORKFLOW_URL = (
    "https://github.com/syrabit/syrabit/actions/workflows/"
    "trustpilot-aggregate-refresh.yml"
)


# ─── Admin health endpoint ─────────────────────────────────────────────────

@router.get("/admin/health/trustpilot/refresh-cron")
async def admin_trustpilot_refresh_cron_health(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Heartbeat snapshot for the daily refresh cron — admin dashboard pill.

    Always 200; the dashboard branches on ``status``. ``silent`` here
    matches the alerter's classification: no SUCCESSFUL heartbeat in
    the threshold window (a perpetually-failing cron is still "silent"
    because the data refresh isn't actually happening).
    """
    health = await get_trustpilot_refresh_cron_health()
    last_any_age = health.get("lastHeartbeatAgeSeconds")
    last_success_age = health.get("lastSuccessHeartbeatAgeSeconds")
    if not health.get("configured"):
        status = "not_configured"
    elif last_any_age is None and last_success_age is None:
        status = "never_observed"
    elif last_success_age is None or last_success_age >= _CRON_SILENT_THRESHOLD_S:
        # No recent SUCCESS — either nothing has run or every recent
        # run failed. Either way the data isn't being refreshed.
        status = "silent"
    elif (health.get("lastStatus") or "success") != "success":
        # The cron is succeeding within threshold (so we're not paging),
        # but the most recent run still failed — surface that on the pill.
        status = "degraded"
    else:
        status = "healthy"
    return {
        **health,
        "status": status,
        "silentThresholdSeconds": _CRON_SILENT_THRESHOLD_S,
        "workflowUrl": health.get("lastWorkflowUrl") or _DEFAULT_WORKFLOW_URL,
    }


# ─── Alerting ──────────────────────────────────────────────────────────────

def _classify_cron(
    health: dict[str, Any], now_ts: float, first_observed_ts: Optional[float],
) -> str:
    """Reduce to ``silent`` / ``healthy`` / ``unknown``.

    The signal is "age of the last SUCCESSFUL heartbeat" — not just any
    heartbeat — so a workflow that runs on schedule but whose inner
    refresh script always fails (rotated key, expired plan, GitHub-side
    push of empty cache) still pages after the threshold elapses. That
    matches the task spec wording ("last-success age >36h") and means
    on-call always learns when fresh Trustpilot data has stopped
    flowing into the cache, regardless of which half is broken.

    * ``unknown``: refresh secret isn't configured (not deployed yet),
      OR the heartbeat doc is empty AND we are still within the
      bootstrap grace window.
    * ``silent``: last successful heartbeat older than the threshold,
      OR no heartbeat at all and bootstrap grace has elapsed.
    * ``healthy``: a successful heartbeat arrived within the threshold.
    """
    if not health.get("configured"):
        return "unknown"
    last_success_ts = health.get("lastSuccessHeartbeatTs")
    if last_success_ts:
        age = now_ts - float(last_success_ts)
        return "silent" if age >= _CRON_SILENT_THRESHOLD_S else "healthy"
    # Never had a successful run. If we've at least seen a (failing)
    # heartbeat, the cron is *running* but the refresh isn't succeeding
    # — still alert as silent (the data is going stale either way).
    last_any_ts = health.get("lastHeartbeatTs")
    if last_any_ts:
        age = now_ts - float(last_any_ts)
        if age >= _CRON_SILENT_THRESHOLD_S:
            return "silent"
        # The cron is running and failing inside the threshold window.
        # Don't page yet — give it a chance to succeed (and surface as
        # "degraded" on the dashboard pill in the meantime).
        return "healthy"
    # Truly never observed — fall through to bootstrap-grace logic.
    if first_observed_ts is not None:
        bootstrap_age = now_ts - float(first_observed_ts)
        if bootstrap_age >= _CRON_BOOTSTRAP_GRACE_S:
            return "silent"
    return "unknown"


async def _seed_first_observed_if_missing(db, now_ts: float) -> Optional[float]:
    """Stamp ``first_observed_ts`` on the alert state doc the first time
    the loop runs against a fresh deployment, so the bootstrap grace
    window has a defined start. Returns the (existing or freshly seeded)
    value. Best-effort — never raises.
    """
    try:
        # Try to read first.
        existing = await db.job_locks.find_one({"_id": _LOCK_ID})
        if existing and existing.get("first_observed_ts"):
            return float(existing["first_observed_ts"])
        # Insert-or-update with $setOnInsert so a concurrent peer cannot
        # overwrite an earlier observation.
        await db.job_locks.update_one(
            {"_id": _LOCK_ID},
            {"$setOnInsert": {
                "_id": _LOCK_ID,
                "first_observed_ts": float(now_ts),
            }},
            upsert=True,
        )
        refreshed = await db.job_locks.find_one({"_id": _LOCK_ID})
        if refreshed and refreshed.get("first_observed_ts"):
            return float(refreshed["first_observed_ts"])
    except Exception as exc:
        logger.debug(f"[trustpilot-cron-alerts] first_observed seed failed: {exc}")
    return None


async def _claim_cron_alert_slot(
    db, kind: str, now_utc: datetime, health: dict[str, Any],
) -> bool:
    """Atomic single-winner CAS — same shape as the data-staleness alerter.

    ``kind`` is ``"silent"`` (broken side) or ``"recovered"``.
    """
    set_payload = {
        "last_state": "silent" if kind == "silent" else "healthy",
        "last_alert_at": now_utc.isoformat(),
        "last_heartbeat_ts": health.get("lastHeartbeatTs"),
        "last_heartbeat_age_seconds": health.get("lastHeartbeatAgeSeconds"),
        "last_success_heartbeat_ts": health.get("lastSuccessHeartbeatTs"),
        "last_success_heartbeat_age_seconds": (
            health.get("lastSuccessHeartbeatAgeSeconds")
        ),
        "last_status": health.get("lastStatus"),
        "last_run_url": health.get("lastRunUrl"),
        "updated_at": now_utc.isoformat(),
    }
    if kind == "silent":
        cutoff_iso = (
            now_utc - timedelta(seconds=_CRON_REALERT_INTERVAL_S)
        ).isoformat()
        guard = {
            "_id": _LOCK_ID,
            "$or": [
                {"last_state": {"$ne": "silent"}},
                {"last_alert_at": {"$lt": cutoff_iso}},
                {"last_alert_at": {"$exists": False}},
            ],
        }
    else:
        guard = {"_id": _LOCK_ID, "last_state": "silent"}
    try:
        res = await db.job_locks.find_one_and_update(
            guard, {"$set": set_payload}, upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(f"[trustpilot-cron-alerts] CAS failed: {exc}")
        return False
    if kind != "silent":
        return False
    try:
        from pymongo.errors import DuplicateKeyError
        await db.job_locks.insert_one({"_id": _LOCK_ID, **set_payload})
        return True
    except DuplicateKeyError:
        # Another replica raced us into existence; retry the CAS so the
        # timestamp on the doc still reflects the latest claim.
        try:
            res = await db.job_locks.find_one_and_update(
                guard, {"$set": set_payload}, upsert=False,
            )
            return res is not None
        except Exception:
            return False
    except Exception as exc:
        logger.debug(f"[trustpilot-cron-alerts] bootstrap insert failed: {exc}")
        return False


async def _email_admins_about_cron(
    title: str, message: str, kind: str,
) -> None:
    """Best-effort email blast to every admin. Mirrors the data-staleness
    alerter so the inbox is consistent."""
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(f"[trustpilot-cron-alerts] email helper unavailable: {exc}")
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
        logger.debug(f"[trustpilot-cron-alerts] admin lookup failed: {exc}")
    color = "#16a34a" if kind == "recovered" else "#dc2626"
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit Trustpilot refresh-cron monitor "
        f"(Task #751).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                f"[trustpilot-cron-alerts] email send failed for {email}: {exc}"
            )


async def _send_cron_alert(
    db, kind: str, health: dict[str, Any], now_utc: datetime,
) -> None:
    """Email + in-app notification. ``kind`` is ``"silent"`` or
    ``"recovered"``. Best-effort — never raises."""
    last_age = health.get("lastSuccessHeartbeatAgeSeconds")
    last_any_age = health.get("lastHeartbeatAgeSeconds")
    age_h = (
        f"{last_age / 3600:.1f}h"
        if isinstance(last_age, (int, float)) else "never"
    )
    any_age_h = (
        f"{last_any_age / 3600:.1f}h"
        if isinstance(last_any_age, (int, float)) else "never"
    )
    workflow_url = health.get("lastWorkflowUrl") or _DEFAULT_WORKFLOW_URL
    run_url = health.get("lastSuccessRunUrl") or health.get("lastRunUrl")
    last_status = health.get("lastStatus") or "unknown"

    if kind == "recovered":
        title = "Trustpilot refresh cron recovered: heartbeat resumed"
        msg = (
            "The daily Trustpilot refresh GitHub Actions workflow is "
            "checking in again. The most recent run posted a heartbeat "
            f"to the backend.\n\nLast run: {run_url or workflow_url}\n\n"
            "No further action required."
        )
        notif_type = "info"
    else:
        title = (
            f"Trustpilot refresh cron silent: no successful run in {age_h}"
        )
        if last_age is not None:
            last_run_line = (
                f"Last SUCCESSFUL heartbeat: {age_h} ago"
                + (f" ({run_url})" if run_url else "")
            )
        else:
            last_run_line = (
                "No successful heartbeat has ever been recorded from "
                "the workflow."
            )
        # Distinguish "cron is silent" from "cron is running but failing"
        # so on-call knows whether to look at GitHub Actions or at the
        # Trustpilot API. The data-staleness alerter (Task #728) covers
        # the upstream-Trustpilot view; this message covers the cron.
        if (
            last_any_age is not None
            and (last_age is None or last_any_age < last_age)
        ):
            running_line = (
                f"The cron IS still running (last heartbeat {any_age_h} "
                f"ago, status={last_status}) but its refresh script keeps "
                "failing. Check the most recent run for the upstream "
                "error — likely a rotated TRUSTPILOT_API_KEY, expired "
                "plan, or WAF block."
            )
        else:
            running_line = (
                "The workflow itself appears to have stopped running. "
                "Likely causes: workflow disabled in the Actions tab, "
                "repo renamed, GITHUB_TOKEN / TRUSTPILOT_REFRESH_SECRET "
                "expired, or a GitHub-side incident."
            )
        msg = (
            "The daily Trustpilot refresh GitHub Actions workflow has "
            f"not had a SUCCESSFUL run in {age_h}. This is independent "
            "of the upstream Trustpilot data-staleness alert (Task "
            "#728): if you see only THIS alert, on-call should start "
            "with the workflow side; if you see both, this one usually "
            "explains the other.\n\n"
            f"{last_run_line}\n\n"
            f"{running_line}\n\n"
            f"Workflow runs: {workflow_url}"
        )
        notif_type = "error"

    try:
        from db_ops import supa_insert_notification
        await supa_insert_notification({
            "id": str(uuid.uuid4()),
            "title": title,
            "message": msg,
            "type": notif_type,
            "channel": "in_app",
            "audience": "admins",
            "status": "sent",
            "created_at": now_utc.isoformat(),
            "sent_at": now_utc.isoformat(),
            "meta": {
                "kind": "trustpilot_refresh_cron_alert",
                "state": kind,
                # Disambiguate: the silence threshold is keyed off the
                # SUCCESSFUL heartbeat age (not just any heartbeat).
                # Both are surfaced so downstream consumers / dashboards
                # don't have to guess which "last_*" the alert is on.
                "last_success_heartbeat_age_seconds": last_age,
                "last_success_heartbeat_ts": (
                    health.get("lastSuccessHeartbeatTs")
                ),
                "last_heartbeat_age_seconds": last_any_age,
                "last_heartbeat_ts": health.get("lastHeartbeatTs"),
                "last_run_url": run_url,
                "workflow_url": workflow_url,
                "last_status": health.get("lastStatus"),
                "last_rc": health.get("lastRc"),
            },
        })
    except Exception as exc:
        logger.debug(f"[trustpilot-cron-alerts] notification persist failed: {exc}")

    asyncio.create_task(_email_admins_about_cron(title, msg, kind))


async def _check_and_alert_refresh_cron(
    db, now_utc: Optional[datetime] = None,
    health: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One alert iteration. Returns a small report dict for tests."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if health is None:
        health = await get_trustpilot_refresh_cron_health()

    # Resolve / seed bootstrap timestamp so a freshly-deployed backend
    # has a defined "we started waiting" anchor for the never-observed
    # case. The seed lives on the alert state doc rather than the
    # heartbeat doc so heartbeat writes stay completely decoupled from
    # alert bookkeeping.
    first_observed_ts = health.get("firstObservedTs")
    if first_observed_ts is None:
        first_observed_ts = await _seed_first_observed_if_missing(
            db, now_utc.timestamp(),
        )

    state = _classify_cron(health, now_utc.timestamp(), first_observed_ts)
    if state == "unknown":
        return {"action": "skip", "reason": "inconclusive", "state": state}

    prior: dict = {}
    try:
        prior = await db.job_locks.find_one({"_id": _LOCK_ID}) or {}
    except Exception as exc:
        logger.debug(f"[trustpilot-cron-alerts] prior load failed: {exc}")
        prior = {}
    prior_state = prior.get("last_state")

    last_alert_dt = None
    if prior.get("last_alert_at"):
        try:
            s = str(prior["last_alert_at"])
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            last_alert_dt = datetime.fromisoformat(s)
            if last_alert_dt.tzinfo is None:
                last_alert_dt = last_alert_dt.replace(tzinfo=timezone.utc)
        except Exception:
            last_alert_dt = None

    if state == "silent":
        if prior_state == "silent" and last_alert_dt is not None:
            elapsed_s = (now_utc - last_alert_dt).total_seconds()
            if elapsed_s < _CRON_REALERT_INTERVAL_S:
                return {"action": "skip", "reason": "debounced",
                        "elapsed_s": elapsed_s}
        if not await _claim_cron_alert_slot(db, "silent", now_utc, health):
            return {"action": "skip", "reason": "lost_race"}
        await _send_cron_alert(db, "silent", health, now_utc)
        return {"action": "alerted", "kind": "silent"}

    # state == "healthy"
    if prior_state == "silent":
        if not await _claim_cron_alert_slot(db, "recovered", now_utc, health):
            return {"action": "skip", "reason": "lost_race"}
        await _send_cron_alert(db, "recovered", health, now_utc)
        return {"action": "alerted", "kind": "recovered"}

    # Same race-avoidance reasoning as the data-staleness alerter — do
    # NOT bootstrap a healthy state doc here (an unconditional upsert
    # could clobber a peer's silent claim and bypass the 24h debounce).
    return {"action": "skip", "reason": "healthy"}


async def _trustpilot_refresh_cron_alert_loop():
    """Background poll loop — safe to run on every replica thanks to the
    atomic CAS dedup above, but in practice ``server.py`` only spawns it
    on the leader to keep the work cheap."""
    from deps import db, is_mongo_available  # type: ignore
    await asyncio.sleep(_CRON_WARMUP_S)
    while True:
        try:
            if await is_mongo_available():
                await _check_and_alert_refresh_cron(db)
        except Exception as exc:
            logger.debug(f"[trustpilot-cron-alerts] loop iteration error: {exc}")
        await asyncio.sleep(_CRON_LOOP_SLEEP_S)
