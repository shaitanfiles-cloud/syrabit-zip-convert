"""Task #728 — Alert admins when the Trustpilot aggregate feed stops working.

Cross-replica safety
--------------------
The aggregate cache lives in per-process memory, but the alert state +
health snapshot the loop reads from are persisted to a single shared
Mongo doc (see ``routes/config.py:_TP_HEALTH_DOC_ID``). That means:

* a successful fetch on ANY replica advances the global last-success
  timestamp, so a leader-only loop cannot miss the outage signal and a
  multi-replica loop cannot flap into false recoveries based on a
  divergent local cache;
* the per-doc CAS on ``db.job_locks`` deduplicates pages across
  replicas, so it's safe to start this loop on every worker.

The ``/api/config/trustpilot/aggregate`` endpoint silently serves stale
or null data when Trustpilot's API errors, the API key is rotated, or
the production IP gets WAF-blocked. Without monitoring we won't notice
the SERP stars disappearing until rankings drop.

This module wires three things together:

* ``GET /admin/health/trustpilot`` — admin-protected snapshot of the
  in-process aggregate cache (last successful fetch timestamp + age,
  most recent error, configured/stale flags). Always 200 so the admin
  dashboard can render a clear status pill instead of a network error.
* :func:`_check_and_alert_trustpilot_feed` — one alert iteration that
  pages admins when the feed has been failing for >24h, debounces
  re-pages to once per 24h while broken, and fires exactly one
  recovery notification on broken→healthy.
* :func:`_trustpilot_feed_alert_loop` — hourly background poll that
  drives the iteration. Cross-replica safety + spam debounce both use
  atomic CAS on ``db.job_locks`` (the same pattern Task #471's SEO
  staleness monitor and Task #484's CI alerter use), so the loop is
  safe to run on every replica even though ``server.py`` only spawns
  it on the leader.

The alert helper deliberately mirrors :mod:`routes.admin_ci_alerts`'s
notification + email shape so all admin alert channels look consistent
in the inbox.
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
from routes.config import (
    get_trustpilot_aggregate_health,
    get_trustpilot_global_health,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Tunables ───────────────────────────────────────────────────────────────

# How long the feed must have been failing before we page the team.
# Default 24h matches the task spec; tunable for tests + ops.
_TP_FEED_STALE_THRESHOLD_S = int(
    os.environ.get("TRUSTPILOT_FEED_STALE_THRESHOLD_S") or 24 * 3600
)
# Re-page cadence while the feed remains broken.
_TP_FEED_REALERT_INTERVAL_S = int(
    os.environ.get("TRUSTPILOT_FEED_REALERT_INTERVAL_S") or 24 * 3600
)
# Background poll cadence + warmup delay (give the API a chance to do its
# first fetch before we start scolding it for being stale).
_TP_FEED_LOOP_SLEEP_S = int(os.environ.get("TRUSTPILOT_FEED_LOOP_SLEEP_S") or 3600)
_TP_FEED_WARMUP_S = int(os.environ.get("TRUSTPILOT_FEED_WARMUP_S") or 900)

_LOCK_ID = "trustpilot_feed_alert_state"

# Task #971 — fan out the data-feed alerter to a dedicated Slack
# incoming webhook so on-call gets paged in the same channel they
# already watch for the per-event JSON-LD alerter (Task #757), the
# refresh-cron silence alerter (Task #834), the cf-waf-drift cron
# silence alerter, and the unified-logs cf-pull silence alerter.
# Until this task, the feed alerter only fanned out to in-app + email,
# leaving a coverage gap for the most user-visible Trustpilot incident
# (SERP stars disappearing). Best-effort: a missing env var or a failed
# POST never duplicates the alert and never breaks the email + in-app
# channels above.
_FEED_SLACK_WEBHOOK_ENV = "SLACK_TRUSTPILOT_FEED_WEBHOOK_URL"


def _slack_webhook_url() -> str:
    """Return the trimmed Slack webhook URL, or ``""`` when unset.

    Whitespace-only values are treated as not configured: an accidental
    ``"  "`` from a broken secret-manager render would otherwise make
    ``bool(...)`` return ``True`` and the dashboard claim Slack was
    wired even though every POST would 400.
    """
    return (os.environ.get(_FEED_SLACK_WEBHOOK_ENV) or "").strip()


def _slack_config() -> dict[str, Any]:
    """Compute the ``slackConfigured`` / ``slackWebhookEnv`` pair the
    admin pill renders next to the data-feed status. Mirrors the shape
    surfaced by the cron silence-alerter health endpoints (Task #964).
    The webhook URL itself is deliberately never included — only the
    boolean configured-ness and the env-var name — so admin-readable
    JSON surfaces never leak it.
    """
    return {
        "slackConfigured": bool(_slack_webhook_url()),
        "slackWebhookEnv": _FEED_SLACK_WEBHOOK_ENV,
    }


# ─── Admin health endpoint ─────────────────────────────────────────────────

@router.get("/admin/health/trustpilot")
async def admin_trustpilot_health(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Return the live freshness snapshot of the Trustpilot aggregate feed.

    Always 200; the dashboard branches on ``configured`` /
    ``lastSuccessAgeSeconds`` / ``lastError`` rather than on HTTP status.

    Uses the *global* (cross-replica) health view so a multi-replica
    deployment shows a consistent answer regardless of which replica
    the request lands on.
    """
    health = await get_trustpilot_global_health()
    last_success_age = health.get("lastSuccessAgeSeconds")
    if not health.get("configured"):
        status = "not_configured"
    elif last_success_age is None:
        status = "never_succeeded"
    elif last_success_age >= _TP_FEED_STALE_THRESHOLD_S:
        status = "broken"
    elif health.get("lastError"):
        status = "degraded"
    else:
        status = "healthy"
    return {
        **health,
        "status": status,
        "staleThresholdSeconds": _TP_FEED_STALE_THRESHOLD_S,
        # Task #971 — surface whether the Slack fan-out for this
        # alerter has its webhook env var
        # (`SLACK_TRUSTPILOT_FEED_WEBHOOK_URL`) set, so the AdminHealth
        # data-feed pill can render a small "Slack ✓ / ✗" badge next
        # to the status string. Sibling fields on the cron health
        # endpoints (Task #964 / Task #968) carry the same shape.
        # The boolean only — never the URL itself.
        **_slack_config(),
    }


# ─── Alerting ──────────────────────────────────────────────────────────────

def _classify_feed(health: dict[str, Any], now_ts: float) -> str:
    """Reduce the health snapshot to ``broken`` / ``healthy`` / ``unknown``.

    * ``unknown``: the feed isn't configured (no API key / business unit) or
      we have not yet had a chance to attempt a fetch. We do NOT page on
      these — they're an ops/setup signal, not a runtime outage.
    * ``broken``: the last successful fetch is older than the configured
      threshold (default 24h), OR we have never succeeded but have at
      least one recorded failure older than the threshold.
    * ``healthy``: a successful fetch has happened within the threshold.
    """
    if not health.get("configured"):
        return "unknown"
    last_success_ts = health.get("lastSuccessTs")
    if last_success_ts:
        age = now_ts - float(last_success_ts)
        return "broken" if age >= _TP_FEED_STALE_THRESHOLD_S else "healthy"
    # Never succeeded — only call it broken once a failure has actually
    # been observed past the threshold. We must use ``firstErrorTs``
    # (set once on entering failure, cleared on success) rather than
    # ``lastErrorTs`` (overwritten every retry, ~5 min cadence) — using
    # the latter would let the age window roll forever and silently
    # suppress the alert during a real outage.
    first_error_ts = health.get("firstErrorTs")
    if first_error_ts:
        err_age = now_ts - float(first_error_ts)
        if err_age >= _TP_FEED_STALE_THRESHOLD_S:
            return "broken"
    return "unknown"


async def _claim_trustpilot_alert_slot(
    db, kind: str, now_utc: datetime,
    health: dict[str, Any],
) -> bool:
    """Atomic single-winner CAS so a multi-replica deployment cannot
    page admins twice for the same broken→healthy or healthy→broken
    transition (or the same 24h re-page cycle while broken).

    Mirrors :func:`routes.admin_ci_alerts._claim_ci_alert_slot`.
    """
    set_payload = {
        "last_state": "broken" if kind == "broken" else "healthy",
        "last_alert_at": now_utc.isoformat(),
        "last_error": health.get("lastError"),
        "last_success_ts": health.get("lastSuccessTs"),
        "last_error_ts": health.get("lastErrorTs"),
        "last_success_age_seconds": health.get("lastSuccessAgeSeconds"),
        "updated_at": now_utc.isoformat(),
    }
    if kind == "broken":
        cutoff_iso = (
            now_utc - timedelta(seconds=_TP_FEED_REALERT_INTERVAL_S)
        ).isoformat()
        guard = {
            "_id": _LOCK_ID,
            "$or": [
                {"last_state": {"$ne": "broken"}},
                {"last_alert_at": {"$lt": cutoff_iso}},
                {"last_alert_at": {"$exists": False}},
            ],
        }
    else:
        guard = {"_id": _LOCK_ID, "last_state": "broken"}
    try:
        res = await db.job_locks.find_one_and_update(
            guard, {"$set": set_payload}, upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(f"[trustpilot-alerts] CAS failed: {exc}")
        return False
    if kind != "broken":
        # Recovery has no bootstrap path: there must be a prior broken row.
        return False
    try:
        from pymongo.errors import DuplicateKeyError
        await db.job_locks.insert_one({"_id": _LOCK_ID, **set_payload})
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"[trustpilot-alerts] bootstrap insert failed: {exc}")
        return False


async def _email_admins_about_trustpilot(
    title: str, message: str, kind: str,
) -> None:
    """Email every admin (best-effort). Mirrors the helper shape used
    by the CI alerter (Task #484) and SEO staleness monitor (Task #471)
    so all admin alert channels look consistent in the inbox.
    """
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(f"[trustpilot-alerts] email helper unavailable: {exc}")
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
        logger.debug(f"[trustpilot-alerts] admin lookup failed: {exc}")
    color = "#16a34a" if kind == "recovered" else "#dc2626"
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit Trustpilot feed monitor (Task #728).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                f"[trustpilot-alerts] email send failed for {email}: {exc}"
            )


def _slack_payload_for_feed_alert(
    title: str, message: str, kind: str, health: dict[str, Any],
) -> dict[str, Any]:
    """Build the Slack incoming-webhook JSON body for the data-feed
    broken / recovered alert.

    Mirrors the per-event JSON-LD alerter (Task #757) and the cron
    silence alerters' payload shape so the Slack channel reads
    consistently across every Trustpilot incident channel: a
    ``:rotating_light:`` (or ``:white_check_mark:`` on recovery)
    section with the same mrkdwn header, plus a follow-up section
    listing the freshness metadata that motivated the page.

    The ``text`` fallback is required by Slack so push notifications
    and clients that don't render Block Kit still show something.
    """
    last_age = health.get("lastSuccessAgeSeconds")
    age_h = (
        f"{last_age / 3600:.1f}h"
        if isinstance(last_age, (int, float)) else "never"
    )
    last_error = health.get("lastError") or "n/a"

    if kind == "recovered":
        emoji = ":white_check_mark:"
        header_md = (
            f"{emoji} *Trustpilot data feed recovered*\n"
            f"Aggregate fetch is fresh again "
            f"(last success {age_h} ago).\n"
            f"Endpoint: `/api/config/trustpilot/aggregate`"
        )
    else:
        emoji = ":rotating_light:"
        header_md = (
            f"{emoji} *Trustpilot data feed broken*\n"
            f"No successful aggregate fetch in `{age_h}` "
            f"(threshold `{_TP_FEED_STALE_THRESHOLD_S // 3600}h`).\n"
            f"Endpoint: `/api/config/trustpilot/aggregate`"
        )

    detail_md = (
        "*Last freshness metadata*\n"
        f"```lastError={last_error}\n"
        f"lastSuccessAge={age_h}```"
    )

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_md}},
        {"type": "section", "text": {"type": "mrkdwn", "text": detail_md}},
        # Slack section text caps at 3000 chars; truncate defensively
        # for the same reason the sibling helpers do (Task #757).
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": (message or "")[:2900]},
        },
    ]
    return {"text": f"{emoji} {title}", "blocks": blocks}


async def _post_slack_feed_alert(
    title: str, message: str, kind: str, health: dict[str, Any],
) -> None:
    """Best-effort POST to ``SLACK_TRUSTPILOT_FEED_WEBHOOK_URL``.
    No-op when the env var is unset; never raises. Mirrors
    ``routes/admin_cf_waf_drift_cron_alerts._post_slack_cron_alert`` so
    the failure modes are uniform across the admin alert surface."""
    webhook_url = _slack_webhook_url()
    if not webhook_url:
        return
    payload = _slack_payload_for_feed_alert(title, message, kind, health)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "[trustpilot-alerts] slack webhook %s: %s",
                    resp.status_code, resp.text[:200],
                )
    except Exception as exc:
        logger.debug(
            "[trustpilot-alerts] slack webhook post failed: %s", exc,
        )


async def _send_trustpilot_alert(
    db, kind: str, health: dict[str, Any], now_utc: datetime,
) -> None:
    """Email admins + record an in-app notification. ``kind`` is
    ``"broken"`` or ``"recovered"``. Best-effort: never raises."""
    last_success_age = health.get("lastSuccessAgeSeconds")
    last_error = health.get("lastError") or "unknown"
    age_h = (
        f"{last_success_age / 3600:.1f}h"
        if isinstance(last_success_age, (int, float)) else "never"
    )

    if kind == "recovered":
        title = "Trustpilot feed recovered: aggregate rating is fresh again"
        msg = (
            "The Trustpilot aggregate rating endpoint "
            "(`/api/config/trustpilot/aggregate`) is fetching fresh data "
            "again. SERP star rich-snippets should reappear on the next "
            "Google crawl. No further action required."
        )
        notif_type = "info"
    else:
        title = "Trustpilot feed broken: aggregate rating is stale"
        msg = (
            "The Trustpilot aggregate rating endpoint "
            "(`/api/config/trustpilot/aggregate`) has not had a successful "
            f"upstream fetch in {age_h}. JSON-LD stars will disappear from "
            "Google search results within hours.\n\n"
            f"Most recent upstream error: {last_error}\n\n"
            "Likely causes: rotated TRUSTPILOT_API_KEY, expired plan, or "
            "the production egress IP being WAF-blocked by Trustpilot."
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
                "kind": "trustpilot_feed_alert",
                "state": kind,
                "last_success_age_seconds": last_success_age,
                "last_error": health.get("lastError"),
                "last_success_ts": health.get("lastSuccessTs"),
                "last_error_ts": health.get("lastErrorTs"),
            },
        })
    except Exception as exc:
        logger.debug(f"[trustpilot-alerts] notification persist failed: {exc}")

    asyncio.create_task(_email_admins_about_trustpilot(title, msg, kind))
    # Task #971 — fan out to the Trustpilot ops Slack channel as well.
    # Scheduled as a background task (matching the email fan-out above)
    # so a slow/dead webhook can't stall the alert loop or the in-app
    # notification persist that already succeeded.
    asyncio.create_task(_post_slack_feed_alert(title, msg, kind, health))


async def _check_and_alert_trustpilot_feed(
    db, now_utc: Optional[datetime] = None,
    health: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One alert iteration. Returns a small report dict for
    tests/observability."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if health is None:
        # Use the GLOBAL (cross-replica) health view, not the local
        # in-process cache — otherwise a leader-only loop could miss an
        # outage and a multi-replica loop could flap on divergent local
        # state. See the comment block at the top of routes/config.py.
        health = await get_trustpilot_global_health()
    state = _classify_feed(health, now_utc.timestamp())
    if state == "unknown":
        # Not-configured / warmup — never page, never touch the lock doc.
        return {"action": "skip", "reason": "inconclusive", "state": state}

    prior: dict = {}
    try:
        prior = await db.job_locks.find_one({"_id": _LOCK_ID}) or {}
    except Exception as exc:
        logger.debug(f"[trustpilot-alerts] prior load failed: {exc}")
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

    if state == "broken":
        # Fast-path debounce — avoids a CAS round-trip when we just paged.
        if prior_state == "broken" and last_alert_dt is not None:
            elapsed_s = (now_utc - last_alert_dt).total_seconds()
            if elapsed_s < _TP_FEED_REALERT_INTERVAL_S:
                return {"action": "skip", "reason": "debounced",
                        "elapsed_s": elapsed_s}
        if not await _claim_trustpilot_alert_slot(
            db, "broken", now_utc, health,
        ):
            return {"action": "skip", "reason": "lost_race"}
        await _send_trustpilot_alert(db, "broken", health, now_utc)
        return {"action": "alerted", "kind": "broken"}

    # state == "healthy"
    if prior_state == "broken":
        if not await _claim_trustpilot_alert_slot(
            db, "recovered", now_utc, health,
        ):
            return {"action": "skip", "reason": "lost_race"}
        await _send_trustpilot_alert(db, "recovered", health, now_utc)
        return {"action": "alerted", "kind": "recovered"}

    # healthy → healthy: same race-avoidance reasoning as the CI alerter
    # — do NOT bootstrap a state doc here. An unconditional upsert from
    # this replica could race a peer that just claimed `broken`,
    # silently overwriting the lock and bypassing the 24h debounce.
    return {"action": "skip", "reason": "healthy"}


async def _trustpilot_feed_alert_loop():
    """Background poll loop. Cross-replica dedup is handled by the CAS
    so this loop is safe to run on every replica, but in practice
    ``server.py`` only spawns it on the leader to keep the work cheap."""
    from deps import db, is_mongo_available  # type: ignore
    await asyncio.sleep(_TP_FEED_WARMUP_S)
    while True:
        try:
            if await is_mongo_available():
                await _check_and_alert_trustpilot_feed(db)
        except Exception as exc:
            logger.debug(f"[trustpilot-alerts] loop iteration error: {exc}")
        await asyncio.sleep(_TP_FEED_LOOP_SLEEP_S)
