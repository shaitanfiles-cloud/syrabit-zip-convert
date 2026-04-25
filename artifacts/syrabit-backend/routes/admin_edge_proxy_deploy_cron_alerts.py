"""Task #893 — Alert when the edge-proxy-deploy CI workflow turns red.

Task #882 added an AdminHealth pill that surfaces the latest
``edge-proxy-deploy`` GitHub Actions run (red on ``failure``, amber
when the most recent successful run is >7d stale, green otherwise).
The pill solves "is the smoke job currently red?" but it only fires
when an admin happens to be looking at the dashboard. A red
``smoke-preview`` regression at 03:00 UTC therefore waits until
someone opens the dashboard before paging.

This module mirrors :mod:`routes.admin_cf_waf_drift_cron_alerts`
(Task #831 — itself a copy of the Task #751 Trustpilot pattern) so
the inbox / dedup / debounce semantics line up across every cron
alert channel:

* poll the same snapshot the pill renders, on a 1h background loop;
* email admins + insert an in-app notification + (best-effort) post
  to a Slack webhook when the pill flips to ``silent`` (failure) or
  ``degraded`` (>7d stale);
* atomic Mongo CAS dedup so a still-red workflow only re-pages once
  per 24h debounce window;
* one-shot recovery alert on broken→healthy.

The notification body always includes the failing run's ``html_url``
so on-call can jump straight to the GitHub Actions logs without
hunting through the dashboard. Slack fan-out is gated on
``EDGE_PROXY_DEPLOY_SLACK_WEBHOOK`` and is best-effort: a missing or
broken webhook never duplicates the alert and never breaks the email
+ in-app channels above (same contract as the cf-waf-drift Slack
helper).
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from routes.admin_health import get_edge_proxy_deploy_cron_health

logger = logging.getLogger(__name__)


# ─── Tunables ───────────────────────────────────────────────────────────────

# Re-page cadence while the workflow is still broken. 24h matches the
# cf-waf-drift alerter so on-call sees a uniform cadence across cron
# pages and can build muscle memory around it.
_CRON_REALERT_INTERVAL_S = int(
    os.environ.get("EDGE_PROXY_DEPLOY_REALERT_INTERVAL_S") or 24 * 3600
)
# Background poll cadence + warmup. Hourly poll because the run-cost
# is one GitHub REST call (already exercised by the AdminHealth pill);
# warmup keeps a bouncing replica from spamming on the first 60s after
# boot when leadership hasn't settled.
_CRON_LOOP_SLEEP_S = int(
    os.environ.get("EDGE_PROXY_DEPLOY_LOOP_SLEEP_S") or 3600
)
_CRON_WARMUP_S = int(
    os.environ.get("EDGE_PROXY_DEPLOY_WARMUP_S") or 900
)

_LOCK_ID = "edge_proxy_deploy_cron_alert_state"
_DEFAULT_WORKFLOW_URL = (
    "https://github.com/syrabit/syrabit/actions/workflows/"
    "edge-proxy-deploy.yml"
)

# Best-effort Slack fan-out. Mirrors the cf-waf-drift Slack helper's
# contract: env-gated, non-blocking, never raises. Operators who want
# the same channel they already get drift / Trustpilot pages on can
# point this at the same incoming webhook.
_CRON_SLACK_WEBHOOK_ENV = "EDGE_PROXY_DEPLOY_SLACK_WEBHOOK"


def _slack_webhook_url() -> str:
    return (os.environ.get(_CRON_SLACK_WEBHOOK_ENV) or "").strip()


# ─── Classification ────────────────────────────────────────────────────────

def _classify_pill(health: dict[str, Any]) -> str:
    """Reduce the pill snapshot to ``broken`` / ``healthy`` / ``unknown``.

    The task spec ("page on `silent` or `degraded`") translates into
    one ``broken`` bucket here so the CAS / debounce machinery stays
    identical to the cf-waf-drift alerter. The sub-kind (failure vs
    stale) is preserved separately via :func:`_kind_for_pill` so the
    email / Slack body can name the proximate cause without forking
    the state machine.

    * ``unknown``: ``not_configured`` (GITHUB_REPO unset),
      ``never_observed`` (workflow exists but no runs yet), or the
      GitHub fetch errored out (``status: unknown``). All three are
      "we don't know yet" — never page on inconclusive signal.
    * ``broken``: pill is ``silent`` (last conclusion=failure) OR
      ``degraded`` (last successful run > 7d stale).
    * ``healthy``: pill is ``healthy``.
    """
    status = (health.get("status") or "").strip().lower()
    if status in {"silent", "degraded"}:
        return "broken"
    if status == "healthy":
        return "healthy"
    return "unknown"


def _kind_for_pill(health: dict[str, Any]) -> str:
    """Return the broken sub-kind: ``failed`` (red) or ``stale`` (amber).

    Only meaningful when :func:`_classify_pill` returned ``broken``;
    callers should not invoke this for healthy/unknown snapshots.
    """
    status = (health.get("status") or "").strip().lower()
    return "stale" if status == "degraded" else "failed"


# ─── CAS dedup ─────────────────────────────────────────────────────────────

async def _claim_cron_alert_slot(
    db, kind: str, sub_kind: Optional[str], now_utc: datetime,
    health: dict[str, Any],
) -> bool:
    """Atomic single-winner CAS — same shape as the cf-waf-drift alerter.

    ``kind`` is ``"broken"`` (failure / stale) or ``"recovered"``.
    ``sub_kind`` is ``"failed"`` / ``"stale"`` for the broken side and
    ignored on recovery. Transitioning failed↔stale (e.g. the cron
    fixes the failure but the resulting run is still >7d stale) is
    treated as a fresh page so the body's "this is what's currently
    wrong" line stays accurate even mid-debounce.
    """
    set_payload = {
        "last_state": "broken" if kind == "broken" else "healthy",
        "last_kind": sub_kind if kind == "broken" else None,
        "last_alert_at": now_utc.isoformat(),
        "last_html_url": health.get("html_url"),
        "last_run_url": health.get("lastRunUrl"),
        "last_workflow_url": health.get("workflowUrl"),
        "last_conclusion": health.get("conclusion"),
        "last_age_seconds": health.get("ageSeconds"),
        "last_run_id": health.get("runId"),
        "last_head_sha": health.get("headSha"),
        "last_pill_status": health.get("status"),
        "updated_at": now_utc.isoformat(),
    }
    if kind == "broken":
        cutoff_iso = (
            now_utc - timedelta(seconds=_CRON_REALERT_INTERVAL_S)
        ).isoformat()
        # Re-page when:
        #  - prior state isn't broken at all (first detection / recovery
        #    flipped back to broken), OR
        #  - prior broken sub-kind differs from the current one
        #    (failed↔stale transition — root cause changed), OR
        #  - the 24h debounce has elapsed since the last page, OR
        #  - we somehow have no last_alert_at (corrupt/legacy doc).
        guard = {
            "_id": _LOCK_ID,
            "$or": [
                {"last_state": {"$ne": "broken"}},
                {"last_kind": {"$ne": sub_kind}},
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
        logger.debug(f"[edge-proxy-deploy-cron-alerts] CAS failed: {exc}")
        return False
    if kind != "broken":
        return False
    # Bootstrap insert path for the first-ever broken detection on a
    # fresh deployment (the doc didn't exist so the find_one_and_update
    # above missed). Mirrors the cf-waf-drift alerter so two replicas
    # racing here can't both win the slot.
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
            f"[edge-proxy-deploy-cron-alerts] bootstrap insert failed: {exc}"
        )
        return False


# ─── Channels: email / in-app / Slack ──────────────────────────────────────

async def _email_admins_about_cron(
    title: str, message: str, kind: str,
) -> None:
    """Best-effort email blast to every admin. Mirrors the cf-waf-drift
    alerter so the inbox is consistent."""
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(
            f"[edge-proxy-deploy-cron-alerts] email helper unavailable: {exc}"
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
            f"[edge-proxy-deploy-cron-alerts] admin lookup failed: {exc}"
        )
    color = "#16a34a" if kind == "recovered" else "#dc2626"
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit edge-proxy-deploy CI monitor "
        f"(Task #893).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                f"[edge-proxy-deploy-cron-alerts] email send failed for "
                f"{email}: {exc}"
            )


def _slack_payload_for_cron_alert(
    title: str, message: str, kind: str, sub_kind: Optional[str],
    health: dict[str, Any],
) -> dict[str, Any]:
    """Build the Slack incoming-webhook JSON body.

    Mirrors the per-run drift alert format in cf-waf-drift-daily.yml
    (Task #828) and the cf-waf-drift silence alerter (Task #834) so
    this channel reads consistently. ``text`` fallback is required by
    Slack so push notifications and clients that don't render Block
    Kit still show something.
    """
    workflow_url = health.get("workflowUrl") or _DEFAULT_WORKFLOW_URL
    html_url = health.get("html_url") or health.get("lastRunUrl")
    conclusion = health.get("conclusion") or "n/a"
    age_s = health.get("ageSeconds")
    age_h = (
        f"{age_s / 3600:.1f}h"
        if isinstance(age_s, (int, float)) else "n/a"
    )
    head_sha = health.get("headSha") or "-"
    head_branch = health.get("headBranch") or "-"

    if kind == "recovered":
        emoji = ":white_check_mark:"
        header_md = (
            f"{emoji} *edge-proxy-deploy CI recovered*\n"
            f"Latest run: `{conclusion}` "
            f"({age_h} ago, `{head_branch}@{head_sha}`)\n"
            f"<{html_url or workflow_url}|GitHub Actions run>\n"
            f"Runbook: replit.md § \"Cloudflare Workers edge-proxy\""
        )
    else:
        emoji = ":rotating_light:"
        if sub_kind == "stale":
            line = (
                f"No deploy in `{age_h}` "
                f"(threshold `{7 * 24}h`)"
            )
        else:
            line = (
                f"Latest run conclusion: `{conclusion}` "
                f"({age_h} ago, `{head_branch}@{head_sha}`)"
            )
        header_md = (
            f"{emoji} *edge-proxy-deploy CI {sub_kind or 'broken'}*\n"
            f"{line}\n"
            f"<{workflow_url}|GitHub Actions workflow>"
            + (f" · <{html_url}|last run>" if html_url else "")
            + "\nRunbook: replit.md § \"Cloudflare Workers edge-proxy\""
        )

    detail_md = (
        "*Last run metadata*\n"
        f"```conclusion={conclusion}  "
        f"age={age_h}  "
        f"branch={head_branch}  "
        f"sha={head_sha}```"
    )

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_md}},
        {"type": "section", "text": {"type": "mrkdwn", "text": detail_md}},
        # Slack section text caps at 3000 chars; truncate defensively for
        # the same reason the cf-waf-drift helper does.
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": (message or "")[:2900]},
        },
    ]
    return {"text": f"{emoji} {title}", "blocks": blocks}


async def _post_slack_cron_alert(
    title: str, message: str, kind: str, sub_kind: Optional[str],
    health: dict[str, Any],
) -> None:
    """Best-effort POST to ``EDGE_PROXY_DEPLOY_SLACK_WEBHOOK``. No-op
    when the env var is unset; never raises. Mirrors
    :func:`routes.admin_cf_waf_drift_cron_alerts._post_slack_cron_alert`
    so the failure modes are uniform across the admin alert surface."""
    webhook_url = _slack_webhook_url()
    if not webhook_url:
        return
    payload = _slack_payload_for_cron_alert(
        title, message, kind, sub_kind, health,
    )
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "[edge-proxy-deploy-cron-alerts] slack webhook %s: %s",
                    resp.status_code, resp.text[:200],
                )
    except Exception as exc:
        logger.debug(
            "[edge-proxy-deploy-cron-alerts] slack webhook post failed: %s",
            exc,
        )


async def _send_cron_alert(
    db, kind: str, sub_kind: Optional[str], health: dict[str, Any],
    now_utc: datetime,
) -> None:
    """Email + in-app notification + best-effort Slack fan-out.

    ``kind`` is ``"broken"`` or ``"recovered"``. ``sub_kind`` describes
    the broken cause (``"failed"`` / ``"stale"``); ignored for recovery.
    Best-effort — never raises.
    """
    workflow_url = health.get("workflowUrl") or _DEFAULT_WORKFLOW_URL
    html_url = health.get("html_url") or health.get("lastRunUrl")
    conclusion = health.get("conclusion") or "n/a"
    age_s = health.get("ageSeconds")
    age_h = (
        f"{age_s / 3600:.1f}h"
        if isinstance(age_s, (int, float)) else "n/a"
    )
    head_sha = health.get("headSha") or "-"
    head_branch = health.get("headBranch") or "-"

    if kind == "recovered":
        title = "edge-proxy-deploy CI recovered: latest run is green"
        msg = (
            "The edge-proxy-deploy GitHub Actions workflow has gone "
            "back to green. The smoke-preview job (burst / D1 / KV / "
            "bot-cache checks from `smoke:preview`) is passing again "
            "on the latest run.\n\n"
            f"Latest run: {html_url or workflow_url}\n"
            f"Conclusion: {conclusion} ({age_h} ago, "
            f"{head_branch}@{head_sha})\n\n"
            "No further action required."
        )
        notif_type = "info"
    else:
        if sub_kind == "stale":
            title = (
                f"edge-proxy-deploy CI stale: no successful deploy "
                f"in {age_h}"
            )
            msg = (
                "The edge-proxy-deploy GitHub Actions workflow has not "
                f"produced a fresh run in {age_h} (threshold: 7 days). "
                "The workflow only fires on pushes to "
                "`workers/edge-proxy/**`, so a long quiet window is "
                "either intentional (no edge-proxy changes recently) "
                "or a sign the trigger has stopped firing — check "
                "GitHub Actions to confirm.\n\n"
                f"Last run: {html_url or workflow_url}\n"
                f"Conclusion: {conclusion} ({age_h} ago, "
                f"{head_branch}@{head_sha})\n\n"
                f"Workflow runs: {workflow_url}"
            )
        else:
            title = (
                f"edge-proxy-deploy CI failed: latest run "
                f"concluded `{conclusion}`"
            )
            msg = (
                "The edge-proxy-deploy GitHub Actions workflow's most "
                f"recent run concluded `{conclusion}`. The "
                "`smoke-preview` job is the canonical signal that the "
                "latest worker build still passes the burst / D1 / KV "
                "/ bot-cache checks (see replit.md § \"Cloudflare "
                "Workers edge-proxy\"); while it is red, an "
                "edge-proxy regression can ship to production "
                "unnoticed.\n\n"
                f"Failing run: {html_url or workflow_url}\n"
                f"Triggered by: {head_branch}@{head_sha}, {age_h} ago\n\n"
                "Open the run above for the failed step's logs and "
                "re-run the workflow once a fix lands on master.\n\n"
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
                "kind": "edge_proxy_deploy_cron_alert",
                "state": kind,
                "sub_kind": sub_kind,
                "html_url": html_url,
                "workflow_url": workflow_url,
                "conclusion": conclusion,
                "age_seconds": age_s,
                "head_branch": head_branch,
                "head_sha": head_sha,
                "run_id": health.get("runId"),
                "pill_status": health.get("status"),
            },
        })
    except Exception as exc:
        logger.debug(
            f"[edge-proxy-deploy-cron-alerts] notification persist failed: "
            f"{exc}"
        )

    asyncio.create_task(_email_admins_about_cron(title, msg, kind))
    # Slack fan-out as a background task (matching the email fan-out
    # above) so a slow/dead webhook can't stall the alert loop or the
    # in-app notification persist that already succeeded.
    asyncio.create_task(
        _post_slack_cron_alert(title, msg, kind, sub_kind, health)
    )


# ─── Main alert iteration ─────────────────────────────────────────────────

async def _check_and_alert_edge_proxy_deploy_cron(
    db, now_utc: Optional[datetime] = None,
    health: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One alert iteration. Returns a small report dict for tests."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if health is None:
        health = await get_edge_proxy_deploy_cron_health()

    state = _classify_pill(health)
    if state == "unknown":
        return {"action": "skip", "reason": "inconclusive", "state": state}

    sub_kind = _kind_for_pill(health) if state == "broken" else None

    prior: dict = {}
    try:
        prior = await db.job_locks.find_one({"_id": _LOCK_ID}) or {}
    except Exception as exc:
        logger.debug(
            f"[edge-proxy-deploy-cron-alerts] prior load failed: {exc}"
        )
        prior = {}
    prior_state = prior.get("last_state")
    prior_kind = prior.get("last_kind")

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
        # Same broken kind, inside debounce → suppress.
        if (
            prior_state == "broken"
            and prior_kind == sub_kind
            and last_alert_dt is not None
        ):
            elapsed_s = (now_utc - last_alert_dt).total_seconds()
            if elapsed_s < _CRON_REALERT_INTERVAL_S:
                return {
                    "action": "skip",
                    "reason": "debounced",
                    "elapsed_s": elapsed_s,
                    "kind": sub_kind,
                }
        if not await _claim_cron_alert_slot(
            db, "broken", sub_kind, now_utc, health,
        ):
            return {"action": "skip", "reason": "lost_race"}
        await _send_cron_alert(db, "broken", sub_kind, health, now_utc)
        return {"action": "alerted", "kind": "broken", "sub_kind": sub_kind}

    # state == "healthy"
    if prior_state == "broken":
        if not await _claim_cron_alert_slot(
            db, "recovered", None, now_utc, health,
        ):
            return {"action": "skip", "reason": "lost_race"}
        await _send_cron_alert(db, "recovered", None, health, now_utc)
        return {"action": "alerted", "kind": "recovered"}

    # Same race-avoidance reasoning as the cf-waf-drift alerter — do
    # NOT bootstrap a healthy state doc here (an unconditional upsert
    # could clobber a peer's broken claim and bypass the 24h debounce).
    return {"action": "skip", "reason": "healthy"}


async def _edge_proxy_deploy_cron_alert_loop():
    """Background poll loop — safe to run on every replica thanks to the
    atomic CAS dedup above, but in practice ``server.py`` only spawns it
    on the leader to keep the GitHub REST quota usage cheap."""
    from deps import db, is_mongo_available  # type: ignore
    await asyncio.sleep(_CRON_WARMUP_S)
    while True:
        try:
            if await is_mongo_available():
                await _check_and_alert_edge_proxy_deploy_cron(db)
        except Exception as exc:
            logger.debug(
                f"[edge-proxy-deploy-cron-alerts] loop iteration error: {exc}"
            )
        await asyncio.sleep(_CRON_LOOP_SLEEP_S)
