"""Task #951 — Page on-call when nightly Cloudflare log polling goes
silent across all replicas.

Task #947 ensures only one backend replica polls the Cloudflare
GraphQL ``httpRequestsAdaptiveGroups`` endpoint at a time (Mongo
lease on ``db.job_locks[unified_logs_cf_pull_lock]``). The flip side
of that contract is a brand-new failure mode: if **every** replica
is unhealthy — or the lease doc gets stuck owned by a zombie process
whose ``lease_expires_at`` is somehow being refreshed by a frozen
task — the unified log explorer silently stops ingesting Cloudflare
data. Until this alerter shipped, the only signal of that outage was
``cf_pull_last_run`` on ``/api/admin/logs/status`` quietly growing
old; an admin had to actually open the dashboard to notice.

This module mirrors :mod:`routes.admin_cf_waf_drift_cron_alerts`
(Task #831, itself a copy of the Task #751 Trustpilot precedent) so
the inbox / dedup / debounce semantics line up with every other
silence alerter on the admin surface:

  * a 10-minute background loop polls the lock doc and classifies
    "is the most recent ``updated_at`` younger than ~3× the configured
    pull interval?";
  * email + in-app notification go out on the silent transition,
    debounced to one page per 24h while still broken;
  * a one-shot recovery alert fires on silent → healthy;
  * cross-replica dedup uses the shared :mod:`background_lease`
    helper plus an atomic Mongo CAS on ``job_locks`` so two replicas
    waking up on the same tick can't both page on-call;
  * lock-doc snapshot + paged-history audit endpoints surface the
    state to the AdminHealth dashboard via the same shaping helpers
    the cf-waf-drift / edge-proxy-deploy pills already use.

Why we read ``updated_at`` and not ``lease_expires_at``
-------------------------------------------------------
The Task #947 lease refreshes ``lease_expires_at`` on every loop
tick of the holding replica regardless of whether the GraphQL pull
inside that tick actually succeeded. A zombie task that's frozen
mid-pull but whose outer loop coroutine is still being scheduled
could therefore keep ``lease_expires_at`` fresh while ``updated_at``
(only written after a successful pull's cursor advance) silently
ages out. Reading ``updated_at`` is the only reliable "ingest is
actually flowing" signal — exactly the invariant the task spec
calls out.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends

from auth_deps import get_admin_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Tunables ───────────────────────────────────────────────────────────────

# How long since the lock doc's ``updated_at`` before we page. The
# task spec says ~3× ``CF_PULL_INTERVAL_S``; we floor at 5 min so the
# alerter doesn't trip on its own loop cadence in the pathological
# config where the operator has set a very short pull interval.
def _default_silent_threshold_s() -> int:
    from routes.admin_logs import CF_PULL_INTERVAL_S
    return max(300, 3 * int(CF_PULL_INTERVAL_S))


def _silent_threshold_s() -> int:
    raw = os.environ.get("UNIFIED_LOGS_CF_PULL_SILENT_THRESHOLD_S")
    if raw and raw.strip():
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return _default_silent_threshold_s()


# Re-page cadence while still silent. 24h matches every sibling
# alerter (cf-waf-drift, edge-proxy-deploy, Trustpilot) so on-call
# sees a uniform page cadence across the admin surface.
_REALERT_INTERVAL_S = int(
    os.environ.get("UNIFIED_LOGS_CF_PULL_REALERT_INTERVAL_S") or 24 * 3600
)
# Background poll cadence + warmup. 10-minute poll matches the task
# spec; warmup keeps a bouncing replica from spamming on the first
# 60s after boot when the very first pull tick hasn't yet completed.
_LOOP_SLEEP_S = int(
    os.environ.get("UNIFIED_LOGS_CF_PULL_SILENCE_LOOP_S") or 600
)
_WARMUP_S = int(
    os.environ.get("UNIFIED_LOGS_CF_PULL_SILENCE_WARMUP_S") or 900
)
# Bootstrap grace: when the lock doc has never had ``updated_at``
# stamped, give the CF pull loop this long to land its first
# successful pull before paging "never observed". Default 1h (much
# shorter than the cf-waf-drift cron's 48h since CF pull runs every
# minute by default — a healthy deploy stamps ``updated_at`` within
# seconds of warmup).
_BOOTSTRAP_GRACE_S = int(
    os.environ.get("UNIFIED_LOGS_CF_PULL_SILENCE_BOOTSTRAP_GRACE_S")
    or 3600
)

_LOCK_ID = "unified_logs_cf_pull_silence_alert_state"
_STATUS_URL = "/api/admin/logs/status"

# Task #957 — fan out silence / recovery pages to Slack as well, so
# on-call sees them in the same channel they already watch for the
# sibling cf-waf-drift / edge-proxy-deploy alerters (which post via
# ``CF_WAF_DRIFT_SLACK_WEBHOOK`` and ``EDGE_PROXY_DEPLOY_SLACK_WEBHOOK``
# respectively). We mirror that env-var-per-alerter pattern with a
# dedicated ``UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK`` so operators can
# point all three at the same incoming-webhook URL today and split
# them per-channel later without code changes. Best-effort: a missing
# env var or a failing POST never blocks the email + in-app channels
# above and never raises out of the alert loop.
#
# Task #969 — the env-var name and the read-and-strip helper now live
# in ``routes.slack_alerter_config`` so all three cron silence-alerter
# modules share a single source of truth and admin_health.py can
# surface the same ``slackConfigured`` / ``slackWebhookEnv`` pair
# without late-importing private symbols from this module. The
# ``_CRON_SLACK_WEBHOOK_ENV`` / ``_slack_webhook_url`` aliases below
# preserve the in-module API the rest of this file (and the existing
# tests) rely on.
from routes.slack_alerter_config import (
    UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK_ENV as _CRON_SLACK_WEBHOOK_ENV,
    slack_config_for,
    slack_webhook_url_for,
)


def _slack_webhook_url() -> str:
    return slack_webhook_url_for(_CRON_SLACK_WEBHOOK_ENV)


# ─── Health snapshot ───────────────────────────────────────────────────────

def _cf_configured() -> bool:
    """Mirror the gate inside ``_try_run_cf_pull_once``: when the CF
    analytics token / zone id aren't set, the pull loop returns
    ``cf_not_configured`` without ever stamping ``updated_at``. Paging
    on that would be a deploy-misconfiguration bug, not a silent-pull
    incident — fail to ``unknown`` instead so a bare-bones deployment
    without CF analytics doesn't get a 24h page cadence."""
    try:
        from config import CF_ZONE_ID, CF_ANALYTICS_API_TOKEN
        return bool(CF_ZONE_ID and CF_ANALYTICS_API_TOKEN)
    except Exception:
        return False


async def get_cf_pull_health() -> dict[str, Any]:
    """Synthesize the health snapshot for the CF pull silence alerter.

    Reads ``db.job_locks[unified_logs_cf_pull_lock]`` and projects the
    fields the alerter needs into the same camelCase shape
    ``cf_waf_drift_cron_heartbeat.get_cf_waf_drift_cron_health`` uses,
    so the admin pill / alert-state endpoints line up with the rest
    of the AdminHealth surface.

    Always returns 200-ready JSON. Mongo unavailable, lock doc absent,
    or CF env vars unset all collapse to ``configured: False`` /
    ``lastUpdatedTs: None`` — the classifier handles those branches as
    ``unknown`` so an infra hiccup never turns into a spurious page.
    """
    out: dict[str, Any] = {
        "configured": _cf_configured(),
        "lastUpdatedTs": None,
        "lastUpdatedAgeSeconds": None,
        "lastUpdatedAt": None,
        "leaseOwner": None,
        "leaseExpiresAt": None,
        "lastAccepted": None,
        "lastDropped": None,
        "lastCalls": None,
        "cursor": None,
    }
    try:
        from deps import db, is_mongo_available  # type: ignore
        if not await is_mongo_available():
            return out
        from routes.admin_logs import (
            CF_PULL_LOCK_ID,
            CF_PULL_CURSOR_FIELD,
            CF_PULL_LEASE_OWNER_FIELD,
            CF_PULL_LEASE_EXPIRES_FIELD,
        )
        lock = await db.job_locks.find_one({"_id": CF_PULL_LOCK_ID})
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-silence] health read failed: {exc}"
        )
        return out
    if not lock:
        return out
    raw_updated = lock.get("updated_at")
    if isinstance(raw_updated, str) and raw_updated.strip():
        try:
            s = raw_updated
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out["lastUpdatedTs"] = dt.timestamp()
            out["lastUpdatedAt"] = dt.isoformat()
            out["lastUpdatedAgeSeconds"] = max(
                0, int((datetime.now(timezone.utc) - dt).total_seconds()),
            )
        except Exception as exc:
            logger.debug(
                f"[unified-logs-cf-pull-silence] updated_at parse failed: {exc}"
            )
    out["leaseOwner"] = lock.get(CF_PULL_LEASE_OWNER_FIELD)
    expires = lock.get(CF_PULL_LEASE_EXPIRES_FIELD)
    if isinstance(expires, datetime):
        out["leaseExpiresAt"] = expires.isoformat()
    elif isinstance(expires, str):
        out["leaseExpiresAt"] = expires
    out["lastAccepted"] = lock.get("last_accepted")
    out["lastDropped"] = lock.get("last_dropped")
    out["lastCalls"] = lock.get("last_calls")
    out["cursor"] = lock.get(CF_PULL_CURSOR_FIELD)
    out["firstObservedTs"] = lock.get("first_observed_ts")
    return out


# ─── Admin health endpoint ─────────────────────────────────────────────────

@router.get("/admin/health/unified-logs/cf-pull/cron")
async def admin_unified_logs_cf_pull_cron_health(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Heartbeat snapshot for the unified-logs CF pull — admin pill.

    Always 200; the dashboard branches on ``status``:

      * ``not_configured`` — CF analytics env vars unset; the pull
        loop is a no-op, so a stale ``updated_at`` is expected.
      * ``never_observed`` — env configured but the lock doc has no
        ``updated_at`` yet (typically pre-rollout / during warmup).
      * ``silent`` — last successful pull older than the threshold;
        the alerter is paging.
      * ``healthy`` — last successful pull within the threshold.
    """
    health = await get_cf_pull_health()
    age = health.get("lastUpdatedAgeSeconds")
    threshold = _silent_threshold_s()
    if not health.get("configured"):
        status = "not_configured"
    elif age is None:
        status = "never_observed"
    elif age >= threshold:
        status = "silent"
    else:
        status = "healthy"
    return {
        **health,
        "status": status,
        "silentThresholdSeconds": threshold,
        "statusUrl": _STATUS_URL,
        # Task #964 — surface whether the Slack fan-out for this
        # alerter has its webhook env var (`UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK`)
        # set, so the AdminHealth dashboard can render a small
        # "Slack ✓ / ✗" badge next to the pill. We deliberately
        # publish only the boolean, never the URL itself, since
        # webhook URLs are sensitive and admin-readable JSON
        # surfaces should not leak them. Task #969 collapsed the
        # boolean + env-name pair into a single shared helper that
        # all three cron silence-alerter health endpoints call into.
        **slack_config_for(_CRON_SLACK_WEBHOOK_ENV),
    }


# ─── Task #902 — alert-state lock-doc snapshot ─────────────────────────────

@router.get("/admin/health/unified-logs/cf-pull/cron/alert-state")
async def admin_unified_logs_cf_pull_cron_alert_state(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Lock-doc snapshot for the unified-logs CF pull silence alerter.

    Mirrors the cf-waf-drift / edge-proxy-deploy alert-state routes
    so the AdminHealth pill can render "last paged Nh ago" + the
    remaining 24h debounce window inline with the pill. Always 200;
    ``present: False`` when the alerter hasn't fired even once or
    when Mongo is unavailable.
    """
    from routes.admin_health import _build_alert_state_response
    return await _build_alert_state_response(
        _LOCK_ID, _REALERT_INTERVAL_S, broken_state_label="silent",
    )


# ─── Task #918 — paged-on-call audit log ──────────────────────────────────

@router.get("/admin/health/unified-logs/cf-pull/cron/alert-history")
async def admin_unified_logs_cf_pull_cron_alert_history(
    limit: int = 20,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Audit log of pages issued by the unified-logs CF pull silence
    alerter (Task #951), most recent first.

    Always 200; ``events: []`` when the alerter has never fired or
    when Mongo is unavailable. Mirrors the contract of the sibling
    ``alert-history`` endpoints on the cf-waf-drift, edge-proxy-deploy
    and Trustpilot pills.
    """
    from routes.admin_health import _build_alert_history_response
    return await _build_alert_history_response(_LOCK_ID, limit=limit)


# ─── Classification ────────────────────────────────────────────────────────

def _classify_cf_pull(
    health: dict[str, Any], now_ts: float, first_observed_ts: Optional[float],
) -> str:
    """Reduce to ``silent`` / ``healthy`` / ``unknown``.

    * ``unknown``: CF analytics env vars unset (the pull loop is a
      no-op, so a stale ``updated_at`` is expected), OR the lock doc
      has no ``updated_at`` yet AND we are still inside the bootstrap
      grace window.
    * ``silent``: last ``updated_at`` older than the threshold, OR no
      ``updated_at`` at all and bootstrap grace has elapsed.
    * ``healthy``: ``updated_at`` arrived within the threshold.
    """
    if not health.get("configured"):
        return "unknown"
    threshold = _silent_threshold_s()
    last_ts = health.get("lastUpdatedTs")
    if last_ts:
        age = now_ts - float(last_ts)
        return "silent" if age >= threshold else "healthy"
    if first_observed_ts is not None:
        bootstrap_age = now_ts - float(first_observed_ts)
        if bootstrap_age >= _BOOTSTRAP_GRACE_S:
            return "silent"
    return "unknown"


async def _seed_first_observed_if_missing(db, now_ts: float) -> Optional[float]:
    """Stamp ``first_observed_ts`` on the alert state doc the first
    time the loop runs against a fresh deployment so the bootstrap
    grace window has a defined start. Returns the (existing or freshly
    seeded) value. Best-effort — never raises.
    """
    try:
        existing = await db.job_locks.find_one({"_id": _LOCK_ID})
        if existing and existing.get("first_observed_ts"):
            return float(existing["first_observed_ts"])
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
        logger.debug(
            f"[unified-logs-cf-pull-silence] first_observed seed failed: {exc}"
        )
    return None


# ─── CAS dedup ─────────────────────────────────────────────────────────────

async def _claim_alert_slot(
    db, kind: str, now_utc: datetime, health: dict[str, Any],
) -> bool:
    """Atomic single-winner CAS — same shape as the cf-waf-drift alerter.

    ``kind`` is ``"silent"`` (broken side) or ``"recovered"``.

    Re-page guard mirrors :mod:`routes.admin_cf_waf_drift_cron_alerts`
    (Task #903): past the 24h debounce we only re-page when
    ``last_updated_ts`` has rolled forward since the prior page (a
    fresh successful pull landed in between before silence resumed).
    Without that, we'd double-page on-call every 24h for the same
    already-acknowledged silent ingest. The legacy-doc branch
    (``last_alert_at`` missing) only fires together with the
    identity check, so a doc that's both missing the timestamp AND
    has the same ``last_updated_ts`` still gets dedup'd; that's
    intentional (the prior page already covered the same silent
    episode).
    """
    set_payload = {
        "last_state": "silent" if kind == "silent" else "healthy",
        "last_alert_at": now_utc.isoformat(),
        "last_updated_ts": health.get("lastUpdatedTs"),
        "last_updated_at": health.get("lastUpdatedAt"),
        "last_updated_age_seconds": health.get("lastUpdatedAgeSeconds"),
        "last_lease_owner": health.get("leaseOwner"),
        "last_lease_expires_at": health.get("leaseExpiresAt"),
        "last_cursor": health.get("cursor"),
        "updated_at": now_utc.isoformat(),
    }
    if kind == "silent":
        cutoff_iso = (
            now_utc - timedelta(seconds=_REALERT_INTERVAL_S)
        ).isoformat()
        cur_updated_ts = health.get("lastUpdatedTs")
        guard = {
            "_id": _LOCK_ID,
            "$or": [
                {"last_state": {"$ne": "silent"}},
                {"$and": [
                    {"$or": [
                        {"last_alert_at": {"$lt": cutoff_iso}},
                        {"last_alert_at": {"$exists": False}},
                    ]},
                    {"last_updated_ts": {"$ne": cur_updated_ts}},
                ]},
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
        logger.debug(
            f"[unified-logs-cf-pull-silence] CAS failed: {exc}"
        )
        return False
    if kind != "silent":
        return False
    try:
        from pymongo.errors import DuplicateKeyError
        await db.job_locks.insert_one({"_id": _LOCK_ID, **set_payload})
        return True
    except DuplicateKeyError:
        try:
            res = await db.job_locks.find_one_and_update(
                guard, {"$set": set_payload}, upsert=False,
            )
            return res is not None
        except Exception:
            return False
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-silence] bootstrap insert failed: {exc}"
        )
        return False


# ─── Channels: email + in-app ──────────────────────────────────────────────

async def _email_admins_about_silence(
    title: str, message: str, kind: str,
) -> None:
    """Best-effort email blast to every admin. Mirrors the cf-waf-drift
    alerter so the inbox is consistent."""
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-silence] email helper unavailable: {exc}"
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
            f"[unified-logs-cf-pull-silence] admin lookup failed: {exc}"
        )
    color = "#16a34a" if kind == "recovered" else "#dc2626"
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit unified-logs Cloudflare-pull monitor "
        f"(Task #951).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                f"[unified-logs-cf-pull-silence] email send failed for "
                f"{email}: {exc}"
            )


def _slack_payload_for_silence_alert(
    title: str, message: str, kind: str, health: dict[str, Any],
) -> dict[str, Any]:
    """Build the Slack incoming-webhook JSON body for the silence /
    recovered alert.

    Mirrors :func:`routes.admin_cf_waf_drift_cron_alerts._slack_payload_for_cron_alert`
    so the channel reads consistently against the sibling alerter:
    a ``:rotating_light:`` (or ``:white_check_mark:`` on recovery)
    section header, plus a follow-up section listing the lock-doc
    metadata that motivated the page (age + lease owner + status URL),
    so on-call has the same triage context as the in-app notification
    body without having to context-switch to email.

    The ``text`` fallback is required by Slack so push notifications
    and clients that don't render Block Kit still show something.
    """
    age_s = health.get("lastUpdatedAgeSeconds")
    age_h = (
        f"{age_s / 3600:.1f}h"
        if isinstance(age_s, (int, float)) else "never"
    )
    threshold = _silent_threshold_s()
    threshold_min = threshold / 60.0
    lease_owner = health.get("leaseOwner") or "<none>"
    last_updated_at = health.get("lastUpdatedAt") or "<never>"

    if kind == "recovered":
        emoji = ":white_check_mark:"
        header_md = (
            f"{emoji} *Unified-logs Cloudflare pull recovered*\n"
            f"Last successful pull: {age_h} ago\n"
            f"<{_STATUS_URL}|Status endpoint>"
        )
    else:
        emoji = ":rotating_light:"
        header_md = (
            f"{emoji} *Unified-logs Cloudflare pull silent*\n"
            f"No successful tick in `{age_h}` "
            f"(threshold `{threshold_min:.0f} min`)\n"
            f"<{_STATUS_URL}|Status endpoint>"
        )

    detail_md = (
        "*Last lock-doc snapshot*\n"
        f"```last_updated_at={last_updated_at}\n"
        f"age={age_h}\n"
        f"lease_owner={lease_owner}```"
    )

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_md}},
        {"type": "section", "text": {"type": "mrkdwn", "text": detail_md}},
        # Slack section text caps at 3000 chars; defensively truncate
        # the free-form notification body for the same reason the
        # cf-waf-drift / Trustpilot helpers do.
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": (message or "")[:2900]},
        },
    ]
    return {"text": f"{emoji} {title}", "blocks": blocks}


async def _post_slack_silence_alert(
    title: str, message: str, kind: str, health: dict[str, Any],
) -> None:
    """Best-effort POST to ``UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK``.
    No-op when the env var is unset; never raises. Mirrors
    :func:`routes.admin_cf_waf_drift_cron_alerts._post_slack_cron_alert`
    so the failure modes are uniform across the admin alert surface —
    a 4xx response is logged at WARNING with the body snippet,
    transport / connection failures are logged at DEBUG and swallowed
    so the email + in-app notifications that already succeeded aren't
    undone."""
    webhook_url = _slack_webhook_url()
    if not webhook_url:
        return
    payload = _slack_payload_for_silence_alert(title, message, kind, health)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "[unified-logs-cf-pull-silence] slack webhook %s: %s",
                    resp.status_code, resp.text[:200],
                )
    except Exception as exc:
        logger.debug(
            "[unified-logs-cf-pull-silence] slack webhook post failed: %s",
            exc,
        )


async def _send_silence_alert(
    db, kind: str, health: dict[str, Any], now_utc: datetime,
) -> None:
    """Email + in-app notification + paged-on-call audit append.

    ``kind`` is ``"silent"`` or ``"recovered"``. Best-effort — never
    raises. The in-app notification persist is the canonical "we paged"
    signal; the email and history-record fan-outs are background tasks
    (matching the sibling alerters) so a slow Mongo or email provider
    can't stall the alert loop or undo a notification that already
    succeeded.
    """
    age_s = health.get("lastUpdatedAgeSeconds")
    age_h = (
        f"{age_s / 3600:.1f}h"
        if isinstance(age_s, (int, float)) else "never"
    )
    threshold = _silent_threshold_s()
    threshold_min = threshold / 60.0
    lease_owner = health.get("leaseOwner") or "<none>"
    last_updated_at = health.get("lastUpdatedAt") or "<never>"

    if kind == "recovered":
        title = (
            "Unified-logs Cloudflare pull recovered: ingest resumed"
        )
        msg = (
            "The unified log explorer's Cloudflare GraphQL pull is "
            "advancing its cursor again. The most recent successful "
            f"tick stamped `updated_at = {last_updated_at}` on "
            "`db.job_locks[unified_logs_cf_pull_lock]`.\n\n"
            f"Current lease owner: {lease_owner}\n"
            f"Status endpoint: {_STATUS_URL}\n\n"
            "No further action required."
        )
        notif_type = "info"
    else:
        title = (
            f"Unified-logs Cloudflare pull silent: no successful tick "
            f"in {age_h}"
        )
        if age_s is not None:
            last_run_line = (
                f"Last successful pull: {age_h} ago "
                f"({last_updated_at})"
            )
        else:
            last_run_line = (
                "No successful pull has ever been recorded against "
                "the unified_logs_cf_pull_lock doc."
            )
        msg = (
            "The unified log explorer's Cloudflare GraphQL pull has "
            f"not advanced `updated_at` on its lock doc in {age_h} "
            f"(threshold: {threshold_min:.0f} min). Until it resumes, "
            "Cloudflare edge log ingest into the admin log explorer is "
            "frozen — bot-traffic / WAF / cache-status panels keep "
            "showing the last cursor and silently grow stale.\n\n"
            f"{last_run_line}\n"
            f"Current lease owner: {lease_owner}\n\n"
            "Likely causes: every backend replica is unhealthy "
            "(check /api/admin/health), the Mongo lease doc is owned "
            "by a zombie process whose lease_expires_at is being "
            "refreshed by a frozen task, the Cloudflare analytics "
            "token / zone id has been rotated, or the CF GraphQL "
            "endpoint is returning errors that are dropping every "
            "tick. Open the status endpoint below for the lease + "
            "cursor snapshot, then restart the holding replica (or "
            "POST /api/admin/logs/cf/pull as a one-shot diagnostic) "
            "to force fail-over.\n\n"
            f"Status endpoint: {_STATUS_URL}"
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
                "kind": "unified_logs_cf_pull_silence_alert",
                "state": kind,
                "last_updated_ts": health.get("lastUpdatedTs"),
                "last_updated_at": health.get("lastUpdatedAt"),
                "last_updated_age_seconds": age_s,
                "lease_owner": health.get("leaseOwner"),
                "lease_expires_at": health.get("leaseExpiresAt"),
                "cursor": health.get("cursor"),
                "silent_threshold_seconds": threshold,
            },
        })
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-silence] notification persist failed: "
            f"{exc}"
        )

    asyncio.create_task(_email_admins_about_silence(title, msg, kind))
    # Task #957 — fan out to the on-call Slack channel as well, so the
    # page lands alongside the sibling cf-waf-drift / edge-proxy-deploy
    # silence alerts on-call already watches. Scheduled as a background
    # task (matching the email fan-out above) so a slow / dead webhook
    # can't stall the alert loop or undo the in-app notification that
    # already succeeded.
    asyncio.create_task(_post_slack_silence_alert(title, msg, kind, health))
    # Task #918 — append to the paged-on-call audit log so the
    # AdminHealth dashboard's "show paged history" panel can render
    # this event next to the pill. Fire-and-forget for the same
    # reason as the email fan-out above (a slow Mongo can't be
    # allowed to stall the alert loop). The shared helper accepts
    # ``sub_kind=None`` so the doc shape stays uniform across pills;
    # this alerter only carries one broken sub-kind ("silent").
    try:
        from routes.admin_health import record_cron_alert_event
        asyncio.create_task(record_cron_alert_event(
            db,
            lock_id=_LOCK_ID,
            kind=kind,
            sub_kind=None,
            health=health,
            now_utc=now_utc,
        ))
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-silence] history record schedule "
            f"failed: {exc}"
        )


# ─── Main alert iteration ─────────────────────────────────────────────────

async def _check_and_alert_cf_pull_silence(
    db, now_utc: Optional[datetime] = None,
    health: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One alert iteration. Returns a small report dict for tests."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if health is None:
        health = await get_cf_pull_health()

    first_observed_ts = health.get("firstObservedTs")
    if first_observed_ts is None:
        first_observed_ts = await _seed_first_observed_if_missing(
            db, now_utc.timestamp(),
        )

    state = _classify_cf_pull(health, now_utc.timestamp(), first_observed_ts)
    if state == "unknown":
        return {"action": "skip", "reason": "inconclusive", "state": state}

    prior: dict = {}
    try:
        prior = await db.job_locks.find_one({"_id": _LOCK_ID}) or {}
    except Exception as exc:
        logger.debug(
            f"[unified-logs-cf-pull-silence] prior load failed: {exc}"
        )
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
            if elapsed_s < _REALERT_INTERVAL_S:
                return {
                    "action": "skip",
                    "reason": "debounced",
                    "elapsed_s": elapsed_s,
                }
            # Task #903 sibling: past the 24h debounce, but the lock
            # doc's ``updated_at`` hasn't rolled forward since our
            # last page (no successful pull landed in between). Re-
            # paging here would be a duplicate page for the same
            # already-acknowledged silent episode. Surface explicitly
            # so the report dict tells operators why we didn't page.
            prior_updated_ts = prior.get("last_updated_ts")
            cur_updated_ts = health.get("lastUpdatedTs")
            if cur_updated_ts == prior_updated_ts:
                return {
                    "action": "skip",
                    "reason": "same_run",
                    "elapsed_s": elapsed_s,
                    "last_updated_ts": cur_updated_ts,
                }
        if not await _claim_alert_slot(db, "silent", now_utc, health):
            return {"action": "skip", "reason": "lost_race"}
        await _send_silence_alert(db, "silent", health, now_utc)
        return {"action": "alerted", "kind": "silent"}

    # state == "healthy"
    if prior_state == "silent":
        if not await _claim_alert_slot(db, "recovered", now_utc, health):
            return {"action": "skip", "reason": "lost_race"}
        await _send_silence_alert(db, "recovered", health, now_utc)
        return {"action": "alerted", "kind": "recovered"}

    # Same race-avoidance reasoning as the cf-waf-drift alerter — do
    # NOT bootstrap a healthy state doc here (an unconditional upsert
    # could clobber a peer's silent claim and bypass the 24h debounce).
    return {"action": "skip", "reason": "healthy"}


async def _cf_pull_silence_alert_loop():
    """Background poll loop.

    Cross-replica dedup (Task #950): the per-state CAS above already
    prevents N×-paging across replicas, but the loop also acquires a
    Mongo-backed lease so only one replica reads the lock doc on
    each tick. Followers stand down on each tick, mirroring the
    cf-waf-drift / edge-proxy-deploy alert loops.
    """
    from deps import db, is_mongo_available  # type: ignore
    import background_lease as _bglease
    owner_id = _bglease.make_owner_id("unified-logs-cf-pull-silence")
    lock_id = "unified_logs_cf_pull_silence_alert_lease"
    ttl_s = max(900, _LOOP_SLEEP_S * 3)
    follower_s = max(60, min(600, _LOOP_SLEEP_S // 2))
    await asyncio.sleep(_WARMUP_S)
    try:
        while True:
            try:
                if not await is_mongo_available():
                    await asyncio.sleep(follower_s)
                    continue
                if not await _bglease.try_acquire_lease(
                    db, lock_id, owner_id, ttl_s,
                ):
                    await asyncio.sleep(follower_s)
                    continue
                await _check_and_alert_cf_pull_silence(db)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(
                    f"[unified-logs-cf-pull-silence] loop iteration error: "
                    f"{exc}"
                )
            await asyncio.sleep(_LOOP_SLEEP_S)
    finally:
        try:
            await asyncio.shield(_bglease.release_lease(
                db, lock_id, owner_id,
            ))
        except Exception:
            pass
