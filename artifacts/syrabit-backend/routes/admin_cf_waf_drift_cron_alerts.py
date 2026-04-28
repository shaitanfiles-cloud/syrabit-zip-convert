"""Task #831 — Alert when the daily Cloudflare firewall drift cron silently
stops running.

The cron — ``.github/workflows/cf-waf-drift-daily.yml`` (Task #828) —
POSTs an unconditional heartbeat to ``/api/config/cf-waf-drift/heartbeat``
on every run, regardless of whether the inner ``verify`` / ``aggregate``
gates passed. That gives us a *job-level* signal independent of the
*drift-detected* signal:

  * The workflow's per-run Slack alert (Task #828) fires →
    "the firewall has drifted (or the CF API is down)" — actionable
    finding from a workflow that DID run.
  * THIS alert fires → "the cron itself hasn't run" — repo archived,
    workflow disabled, secret expired, GitHub Actions outage,
    account billing lapse.

When BOTH fire the on-call knows GitHub Actions is the proximate
cause; when only the per-run drift alert fires they know the workflow
ran but the firewall state needs attention.

The implementation deliberately mirrors
:mod:`routes.admin_trustpilot_cron_alerts` (Task #751, the working
precedent the task description points us at) so all admin alert
channels look consistent in the inbox: same Mongo CAS dedup, same
email + in-app notification shape, same 36/24h debounce semantics.

Where it diverges: the firewall drift cron's per-run Slack alert
already covers "workflow ran but drift detected", so this alerter
keys off ``last_heartbeat_ts`` only (any heartbeat counts) rather
than the Trustpilot alerter's ``last_success_heartbeat_ts``. That
intentionally avoids double-paging on a healthy workflow that simply
keeps finding drift — operators are already being notified about
that via the per-run Slack channel.
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
from routes.cf_waf_drift_cron_heartbeat import get_cf_waf_drift_cron_health

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Tunables ───────────────────────────────────────────────────────────────

# How long since the last heartbeat before we page.
# Default 36h: the workflow runs daily at 04:47 UTC, so a fresh run is
# always <26h old. 36h gives us a 10h grace window for a single missed
# run (transient GitHub outage) before scolding.
_CRON_SILENT_THRESHOLD_S = int(
    os.environ.get("CF_WAF_DRIFT_CRON_SILENT_THRESHOLD_S") or 36 * 3600
)
# Re-page cadence while still silent.
_CRON_REALERT_INTERVAL_S = int(
    os.environ.get("CF_WAF_DRIFT_CRON_REALERT_INTERVAL_S") or 24 * 3600
)
# Background poll cadence + warmup.
_CRON_LOOP_SLEEP_S = int(
    os.environ.get("CF_WAF_DRIFT_CRON_LOOP_SLEEP_S") or 3600
)
_CRON_WARMUP_S = int(
    os.environ.get("CF_WAF_DRIFT_CRON_WARMUP_S") or 900
)
# Bootstrap grace: when the backend has never seen a heartbeat, give the
# workflow this long to register one before paging "never observed".
# Default 48h so a freshly-deployed backend doesn't immediately page if
# the daily cron happens to land on the wrong side of deploy time.
_CRON_BOOTSTRAP_GRACE_S = int(
    os.environ.get("CF_WAF_DRIFT_CRON_BOOTSTRAP_GRACE_S") or 48 * 3600
)

_LOCK_ID = "cf_waf_drift_cron_alert_state"
_DEFAULT_WORKFLOW_URL = (
    "https://github.com/syrabit/syrabit/actions/workflows/"
    "cf-waf-drift-daily.yml"
)

# Task #834 — fan-out the silence / recovered alert to the same Slack
# webhook the per-run drift alert (Task #828, ``.github/workflows/
# cf-waf-drift-daily.yml``) posts to. Operators already watch this
# channel for "workflow ran and found drift" findings; consolidating
# the "workflow stopped running entirely" signal here removes the gap
# where they'd otherwise have to also watch admin email + the in-app
# inbox to catch a silent cron. Best-effort: a missing env var or a
# failed POST never duplicates the alert and never breaks the email +
# in-app channels above.
#
# Task #969 — the env-var name and the read-and-strip helper now live
# in ``routes.slack_alerter_config`` so all three cron silence-alerter
# modules share a single source of truth. The ``_CRON_SLACK_WEBHOOK_ENV``
# / ``_slack_webhook_url`` aliases below preserve the in-module API
# the rest of this file (and existing tests) rely on.
from routes.slack_alerter_config import (
    CF_WAF_DRIFT_SLACK_WEBHOOK_ENV as _CRON_SLACK_WEBHOOK_ENV,
    slack_config_for,
    slack_webhook_url_for,
)


def _slack_webhook_url() -> str:
    return slack_webhook_url_for(_CRON_SLACK_WEBHOOK_ENV)


# ─── Admin health endpoint ─────────────────────────────────────────────────

@router.get("/admin/health/cf-waf-drift/cron")
async def admin_cf_waf_drift_cron_health(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Heartbeat snapshot for the daily cf-waf-drift cron — admin pill.

    Always 200; the dashboard branches on ``status``:

      * ``not_configured`` — ``CF_WAF_DRIFT_HEARTBEAT_SECRET`` env
        unset on the backend; nothing is enforced.
      * ``never_observed`` — secret configured but no heartbeat has
        ever arrived (typically pre-rollout).
      * ``silent`` — last heartbeat older than the 36h threshold;
        the alerter is paging.
      * ``degraded`` — recent heartbeat, but it reports
        ``verifyRc != 0`` or ``aggregateRc != 0`` (the workflow's own
        Slack alert is the primary channel for that case; surfacing
        on the pill keeps ops informed without re-paging).
      * ``healthy`` — recent heartbeat AND last run reports both
        gates clean.
    """
    health = await get_cf_waf_drift_cron_health()
    last_age = health.get("lastHeartbeatAgeSeconds")
    if not health.get("configured"):
        status = "not_configured"
    elif last_age is None:
        status = "never_observed"
    elif last_age >= _CRON_SILENT_THRESHOLD_S:
        status = "silent"
    else:
        # Inside the threshold window. Recent run may still have
        # detected drift / hit a transport error — surface that so the
        # pill isn't a misleading green when the per-run Slack alert
        # has already fired.
        last_status = (health.get("lastStatus") or "").strip().lower()
        verify_rc = health.get("lastVerifyRc")
        aggregate_rc = health.get("lastAggregateRc")
        clean_rc = (
            (verify_rc in (None, 0)) and (aggregate_rc in (None, 0))
        )
        if last_status in {"drift", "transport_error", "failure"} or not clean_rc:
            status = "degraded"
        else:
            status = "healthy"
    return {
        **health,
        "status": status,
        "silentThresholdSeconds": _CRON_SILENT_THRESHOLD_S,
        "workflowUrl": health.get("lastWorkflowUrl") or _DEFAULT_WORKFLOW_URL,
        # Task #964 — surface whether the Slack fan-out for this
        # alerter has its webhook env var (`CF_WAF_DRIFT_SLACK_WEBHOOK`)
        # set, so the AdminHealth dashboard can render a small
        # "Slack ✓ / ✗" badge next to the pill. Sibling fields on
        # the cf-pull and edge-proxy-deploy cron endpoints carry the
        # same shape. The boolean only — never the URL itself.
        # Task #969 collapsed the boolean + env-name pair into a
        # single shared helper used by all three cron silence-alerter
        # health endpoints.
        **slack_config_for(_CRON_SLACK_WEBHOOK_ENV),
    }


# ─── Task #902 — alert-state lock-doc snapshot ─────────────────────────────
#
# Mirror of ``/admin/health/edge-proxy-deploy/cron/alert-state``: surfaces
# the cf-waf-drift silence alerter's persisted dedup state so the
# AdminHealth tile next to the pill can show "last paged Nh ago" and
# the remaining 24h debounce window. The lock doc already exists
# (the alerter writes it on every CAS claim); this route just exposes
# it. Reuses the shared shaping helper from
# :mod:`routes.admin_health` so all three admin pills (edge-proxy,
# cf-waf-drift, Trustpilot) surface the same JSON shape.
@router.get("/admin/health/cf-waf-drift/cron/alert-state")
async def admin_cf_waf_drift_cron_alert_state(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Lock-doc snapshot for the cf-waf-drift silence alerter.

    Always 200; surfaces ``present: False`` when the alerter hasn't
    fired even once (the lock doc gets created on the first CAS
    claim) or when Mongo is unavailable. ``last_state`` is
    ``"silent"`` while the alerter is pending re-page and
    ``"healthy"`` after a recovery, so the shared helper below uses
    ``broken_state_label="silent"`` to compute the ``inDebounce`` /
    ``debounceRemainingSeconds`` derived fields.
    """
    from routes.admin_health import _build_alert_state_response
    return await _build_alert_state_response(
        _LOCK_ID, _CRON_REALERT_INTERVAL_S, broken_state_label="silent",
    )


# ─── Task #918 — paged-on-call audit log ──────────────────────────────────
#
# Sibling of ``/admin/health/cf-waf-drift/cron/alert-state`` above.
# Surfaces the last ~20 alerter events (page + recovery) for the
# cf-waf-drift cron so the AdminHealth pill can render a small
# "show paged history" panel. The audit collection + shaping helper
# live in :mod:`routes.admin_health` so all three pills share one
# implementation; this route is a thin wrapper that pins the
# ``_LOCK_ID`` for this specific alerter.
@router.get("/admin/health/cf-waf-drift/cron/alert-history")
async def admin_cf_waf_drift_cron_alert_history(
    limit: int = 20,
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Audit-log of pages issued by the cf-waf-drift silence alerter
    (Task #831), most recent first. Always 200; returns
    ``events: []`` when the alerter has never fired or when Mongo is
    unavailable.
    """
    from routes.admin_health import _build_alert_history_response
    return await _build_alert_history_response(_LOCK_ID, limit=limit)


# ─── Alerting ──────────────────────────────────────────────────────────────

def _classify_cron(
    health: dict[str, Any], now_ts: float, first_observed_ts: Optional[float],
) -> str:
    """Reduce to ``silent`` / ``healthy`` / ``unknown``.

    The signal is "age of the last heartbeat" — any heartbeat counts,
    because the workflow's own per-run Slack alert (Task #828) already
    pages on drift / transport errors. This alerter exists to catch the
    distinct failure mode where the workflow itself stops running
    (repo archived, workflow disabled in the Actions UI, GitHub
    outage, billing lapse).

    * ``unknown``: heartbeat secret isn't configured (not deployed
      yet), OR the heartbeat doc is empty AND we are still within the
      bootstrap grace window.
    * ``silent``: last heartbeat older than the threshold, OR no
      heartbeat at all and bootstrap grace has elapsed.
    * ``healthy``: a heartbeat arrived within the threshold.
    """
    if not health.get("configured"):
        return "unknown"
    last_ts = health.get("lastHeartbeatTs")
    if last_ts:
        age = now_ts - float(last_ts)
        return "silent" if age >= _CRON_SILENT_THRESHOLD_S else "healthy"
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
        logger.debug(f"[cf-waf-drift-cron-alerts] first_observed seed failed: {exc}")
    return None


async def _claim_cron_alert_slot(
    db, kind: str, now_utc: datetime, health: dict[str, Any],
) -> bool:
    """Atomic single-winner CAS — same shape as the Trustpilot alerter.

    ``kind`` is ``"silent"`` (broken side) or ``"recovered"``.
    """
    set_payload = {
        "last_state": "silent" if kind == "silent" else "healthy",
        "last_alert_at": now_utc.isoformat(),
        "last_heartbeat_ts": health.get("lastHeartbeatTs"),
        "last_heartbeat_age_seconds": health.get("lastHeartbeatAgeSeconds"),
        "last_status": health.get("lastStatus"),
        "last_verify_rc": health.get("lastVerifyRc"),
        "last_aggregate_rc": health.get("lastAggregateRc"),
        "last_run_url": health.get("lastRunUrl"),
        "updated_at": now_utc.isoformat(),
    }
    if kind == "silent":
        cutoff_iso = (
            now_utc - timedelta(seconds=_CRON_REALERT_INTERVAL_S)
        ).isoformat()
        cur_run_url = health.get("lastRunUrl")
        # Task #903: re-page when state isn't silent (recovery flipped
        # back), OR when the 24h debounce has elapsed (or last_alert_at
        # is missing on a corrupt/legacy doc) AND the last run url has
        # rolled over (a fresh heartbeat landed in between before
        # silence resumed). The lone "debounce elapsed" branch used to
        # fire even when nothing had changed since the prior page —
        # re-paging on-call every 24h for the same already-acknowledged
        # silent cron. The legacy-doc branch only fires together with
        # the run-url change check, so a doc that's both missing the
        # timestamp AND has the same last_run_url still gets dedup'd;
        # that's intentional (the prior page already covered the same
        # silent episode).
        guard = {
            "_id": _LOCK_ID,
            "$or": [
                {"last_state": {"$ne": "silent"}},
                {"$and": [
                    {"$or": [
                        {"last_alert_at": {"$lt": cutoff_iso}},
                        {"last_alert_at": {"$exists": False}},
                    ]},
                    {"last_run_url": {"$ne": cur_run_url}},
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
        logger.debug(f"[cf-waf-drift-cron-alerts] CAS failed: {exc}")
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
        logger.debug(f"[cf-waf-drift-cron-alerts] bootstrap insert failed: {exc}")
        return False


async def _email_admins_about_cron(
    title: str, message: str, kind: str,
) -> None:
    """Best-effort email blast to every admin. Mirrors the Trustpilot
    alerter so the inbox is consistent."""
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(f"[cf-waf-drift-cron-alerts] email helper unavailable: {exc}")
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
        logger.debug(f"[cf-waf-drift-cron-alerts] admin lookup failed: {exc}")
    color = "#16a34a" if kind == "recovered" else "#dc2626"
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit Cloudflare-firewall drift-cron monitor "
        f"(Task #831).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                f"[cf-waf-drift-cron-alerts] email send failed for {email}: {exc}"
            )


def _slack_payload_for_cron_alert(
    title: str, message: str, kind: str, health: dict[str, Any],
) -> dict[str, Any]:
    """Build the Slack incoming-webhook JSON body for the cron silence /
    recovered alert.

    Mirrors the per-run drift alert format in
    ``.github/workflows/cf-waf-drift-daily.yml`` so this channel reads
    consistently: a ``:rotating_light:`` (or ``:white_check_mark:`` on
    recovery) section with the same mrkdwn shape, plus a follow-up
    section listing the heartbeat metadata that motivated the page.

    The ``text`` fallback is required by Slack so push notifications
    and clients that don't render Block Kit still show something.
    """
    last_age = health.get("lastHeartbeatAgeSeconds")
    age_h = (
        f"{last_age / 3600:.1f}h"
        if isinstance(last_age, (int, float)) else "never"
    )
    workflow_url = health.get("lastWorkflowUrl") or _DEFAULT_WORKFLOW_URL
    run_url = health.get("lastRunUrl")
    last_status = health.get("lastStatus") or "n/a"
    verify_rc = health.get("lastVerifyRc")
    aggregate_rc = health.get("lastAggregateRc")

    if kind == "recovered":
        emoji = ":white_check_mark:"
        header_md = (
            f"{emoji} *Cloudflare firewall drift cron recovered*\n"
            f"Last heartbeat: {age_h} ago, status=`{last_status}`\n"
            f"<{run_url or workflow_url}|GitHub Actions run>\n"
            f"Runbook: `docs/CLOUDFLARE_ZERO_TRUST.md` §8.7.7"
        )
    else:
        emoji = ":rotating_light:"
        header_md = (
            f"{emoji} *Cloudflare firewall drift cron silent*\n"
            f"No heartbeat in `{age_h}` "
            f"(threshold `{_CRON_SILENT_THRESHOLD_S // 3600}h`)\n"
            f"<{workflow_url}|GitHub Actions workflow>"
            + (f" · <{run_url}|last run>" if run_url else "")
            + "\nRunbook: `docs/CLOUDFLARE_ZERO_TRUST.md` §8.7.7"
        )

    detail_md = (
        "*Last heartbeat metadata*\n"
        f"```status={last_status}  "
        f"verifyRc={verify_rc if verify_rc is not None else '-'}  "
        f"aggregateRc={aggregate_rc if aggregate_rc is not None else '-'}\n"
        f"age={age_h}```"
    )

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_md}},
        {"type": "section", "text": {"type": "mrkdwn", "text": detail_md}},
        # Slack section text caps at 3000 chars; the cron alert body is
        # already short, but truncate defensively for the same reason
        # the Trustpilot helper does (Task #757).
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": (message or "")[:2900]},
        },
    ]
    return {"text": f"{emoji} {title}", "blocks": blocks}


async def _post_slack_cron_alert(
    title: str, message: str, kind: str, health: dict[str, Any],
) -> None:
    """Best-effort POST to ``CF_WAF_DRIFT_SLACK_WEBHOOK``. No-op when
    the env var is unset; never raises. Mirrors
    ``routes/admin_trustpilot_jsonld_status._post_jsonld_slack_alert``
    (Task #757) — same httpx client, same logging discipline — so the
    failure modes are uniform across the admin alert surface."""
    webhook_url = _slack_webhook_url()
    if not webhook_url:
        return
    payload = _slack_payload_for_cron_alert(title, message, kind, health)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "[cf-waf-drift-cron-alerts] slack webhook %s: %s",
                    resp.status_code, resp.text[:200],
                )
    except Exception as exc:
        logger.debug(
            "[cf-waf-drift-cron-alerts] slack webhook post failed: %s", exc,
        )


async def _send_cron_alert(
    db, kind: str, health: dict[str, Any], now_utc: datetime,
) -> None:
    """Email + in-app notification + (Task #834) best-effort Slack
    fan-out to ``CF_WAF_DRIFT_SLACK_WEBHOOK``. ``kind`` is ``"silent"``
    or ``"recovered"``. Best-effort — never raises."""
    last_age = health.get("lastHeartbeatAgeSeconds")
    age_h = (
        f"{last_age / 3600:.1f}h"
        if isinstance(last_age, (int, float)) else "never"
    )
    workflow_url = health.get("lastWorkflowUrl") or _DEFAULT_WORKFLOW_URL
    run_url = health.get("lastRunUrl")

    if kind == "recovered":
        title = "Cloudflare firewall drift cron recovered: heartbeat resumed"
        msg = (
            "The daily Cloudflare firewall drift GitHub Actions workflow "
            "is checking in again. The most recent run posted a "
            f"heartbeat to the backend.\n\nLast run: {run_url or workflow_url}"
            "\n\nNo further action required."
        )
        notif_type = "info"
    else:
        title = (
            f"Cloudflare firewall drift cron silent: no run in {age_h}"
        )
        if last_age is not None:
            last_run_line = (
                f"Last heartbeat: {age_h} ago"
                + (f" ({run_url})" if run_url else "")
            )
        else:
            last_run_line = (
                "No heartbeat has ever been recorded from the workflow."
            )
        msg = (
            "The daily Cloudflare firewall drift GitHub Actions workflow "
            f"has not posted a heartbeat in {age_h}. The workflow runs "
            "the §8.7.4 verify and §8.7.6 aggregate gates from "
            "`docs/CLOUDFLARE_ZERO_TRUST.md`; while it is silent, "
            "drift introduced via the Cloudflare dashboard surfaces "
            "only when a user complains (the failure mode Task #828 "
            "was meant to remove).\n\n"
            f"{last_run_line}\n\n"
            "Likely causes: workflow disabled in the GitHub Actions "
            "tab, repo renamed/archived, GitHub Actions outage, "
            "GITHUB_TOKEN / CF_WAF_DRIFT_HEARTBEAT_SECRET expired, or "
            "an account billing lapse. Re-enable the workflow and "
            "trigger a manual run via `workflow_dispatch` to confirm.\n\n"
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
                "kind": "cf_waf_drift_cron_alert",
                "state": kind,
                "last_heartbeat_age_seconds": last_age,
                "last_heartbeat_ts": health.get("lastHeartbeatTs"),
                "last_run_url": run_url,
                "workflow_url": workflow_url,
                "last_status": health.get("lastStatus"),
                "last_verify_rc": health.get("lastVerifyRc"),
                "last_aggregate_rc": health.get("lastAggregateRc"),
            },
        })
    except Exception as exc:
        logger.debug(f"[cf-waf-drift-cron-alerts] notification persist failed: {exc}")

    asyncio.create_task(_email_admins_about_cron(title, msg, kind))
    # Task #834 — fan out to the per-run drift Slack channel as well.
    # Scheduled as a background task (matching the email fan-out above)
    # so a slow/dead webhook can't stall the alert loop or the in-app
    # notification persist that already succeeded.
    asyncio.create_task(_post_slack_cron_alert(title, msg, kind, health))
    # Task #918 — append to the paged-on-call audit log so the
    # AdminHealth dashboard's "show paged history" panel can render
    # this event next to the pill. Fire-and-forget for the same
    # reason as the email + Slack fan-outs above (a slow Mongo can't
    # be allowed to stall the alert loop). This alerter only carries
    # one broken sub_kind ("silent" — the cron stopped heartbeating),
    # so sub_kind is always None on the broken side; the helper
    # accepts None so the doc shape stays uniform across pills.
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
            f"[cf-waf-drift-cron-alerts] history record schedule "
            f"failed: {exc}"
        )


async def _check_and_alert_cf_waf_drift_cron(
    db, now_utc: Optional[datetime] = None,
    health: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One alert iteration. Returns a small report dict for tests."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if health is None:
        health = await get_cf_waf_drift_cron_health()

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
        logger.debug(f"[cf-waf-drift-cron-alerts] prior load failed: {exc}")
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
            # Task #903: past the 24h debounce, but the last observed
            # run url hasn't rolled over since we paged. Nothing has
            # changed about the silent state — re-paging on-call here
            # would be a duplicate page for the same already-known
            # silent cron. Surface explicitly so the report dict tells
            # operators why we didn't page (vs. a CAS lost-race).
            prior_run_url = prior.get("last_run_url")
            cur_run_url = health.get("lastRunUrl")
            if prior_run_url is not None and cur_run_url == prior_run_url:
                return {
                    "action": "skip",
                    "reason": "same_run",
                    "elapsed_s": elapsed_s,
                    "run_url": cur_run_url,
                }
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

    # Same race-avoidance reasoning as the Trustpilot alerter — do
    # NOT bootstrap a healthy state doc here (an unconditional upsert
    # could clobber a peer's silent claim and bypass the 24h debounce).
    return {"action": "skip", "reason": "healthy"}


async def _cf_waf_drift_cron_alert_loop():
    """Background poll loop.

    Cross-replica dedup (Task #950): the per-state CAS above already
    prevents N×-paging across replicas, but the loop also acquires a
    Mongo-backed lease so only one replica polls upstream state on each
    tick. Followers stand down on each tick.
    """
    from deps import db, is_mongo_available  # type: ignore
    import background_lease as _bglease
    owner_id = _bglease.make_owner_id("cf-waf-drift-cron")
    lock_id = "cf_waf_drift_cron_alert_lease"
    ttl_s = max(900, _CRON_LOOP_SLEEP_S * 3)
    follower_s = max(60, min(600, _CRON_LOOP_SLEEP_S // 2))
    await asyncio.sleep(_CRON_WARMUP_S)
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
                await _check_and_alert_cf_waf_drift_cron(db)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(f"[cf-waf-drift-cron-alerts] loop iteration error: {exc}")
            await asyncio.sleep(_CRON_LOOP_SLEEP_S)
    finally:
        try:
            await asyncio.shield(_bglease.release_lease(
                db, lock_id, owner_id,
            ))
        except Exception:
            pass
