"""Task #970 — Page on-call when one of the three sibling cron Slack
webhook env vars stays unset for >24h after deploy.

Task #963 documented the new ``UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK`` env
var so on-call knows to set it; Task #964 added a "Slack ✓ / ✗" badge
to the AdminHealth cf-pull / cf-waf-drift / edge-proxy-deploy cron
pills (rendered from the ``slackConfigured`` boolean
``routes.slack_alerter_config.slack_config_for`` returns). But that
signal is only visible while an admin is actively looking at the
dashboard — a deploy that ships without a webhook can sit "Slack ✗"
indefinitely, defeating the whole point of having a sibling alerter.
This module closes that "we documented it but nobody set it" gap by
running a small leader-gated job once per day per replica that
compares each of the three Slack-fan-out env vars
(``UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK``,
``CF_WAF_DRIFT_SLACK_WEBHOOK``, ``EDGE_PROXY_DEPLOY_SLACK_WEBHOOK``)
to the "should be configured" expectation and pages admins via the
same in-app + email channels the sibling silence-alerters already use
when any one of them has been unset for >24h after the alerter first
booted on this deployment.

Why no Slack fan-out for *this* alerter
---------------------------------------
The whole point of paging is "your Slack webhook is missing" — a
Slack POST would either silently drop into the void (if all three
webhooks are unset, which is the worst case) or fan back out to a
sibling alerter's channel and double-page on-call who is already
seeing the in-app + email page. Email + in-app are intentionally the
canonical channels for this alerter.

State machine + dedup
---------------------
One ``job_locks`` doc per env-var name
(``slack_webhook_missing_alert_state__<ENV_NAME>``) so the per-env
24h debounce + recovery semantics line up with the existing silence
alerters. Each doc carries:

* ``last_state`` — ``"missing"`` while the env is unset (broken side)
  or ``"healthy"`` after a recovery;
* ``last_alert_at`` — for the 24h re-page debounce;
* ``first_observed_ts`` — seeded the first time the loop runs against
  a fresh deployment so the 24h "after deploy" grace window has a
  defined start (mirrors :mod:`routes.admin_cf_waf_drift_cron_alerts`).

Cross-replica dedup is the same shape as the sibling silence
alerters: an outer Mongo lease (``slack_webhook_missing_alert_lease``)
gates the loop so only one replica reads + checks per tick, and an
inner per-env CAS guards the alert claim so two replicas waking up on
the same tick can't both page on-call.

Why bootstrap grace exists at all
---------------------------------
Without it, a freshly-rolled-out replica would page within minutes of
boot if the operator hadn't yet set the webhook, defeating the
"deploy then promptly set the webhook" workflow the runbook
recommends. 24h grace gives operators a full day to land the secret
before the alerter starts pestering on-call about a missing config
that's actively being set up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from routes.slack_alerter_config import (
    CF_WAF_DRIFT_SLACK_WEBHOOK_ENV,
    EDGE_PROXY_DEPLOY_SLACK_WEBHOOK_ENV,
    UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK_ENV,
    slack_webhook_url_for,
)

logger = logging.getLogger(__name__)

# Process-boot anchor used as a last-resort deploy identifier when no
# platform-supplied id is available. Captured at import time so all
# replicas of the same process agree on a single value across the
# loop's lifetime; a restart counts as a new "deploy" for the purposes
# of resetting the grace window — that's an acceptable conservative
# default because a restart is the only reliable signal we have on a
# bare-metal deploy that an operator could have just landed a fix.
_PROCESS_BOOT_ID = f"process-boot-{int(time.time())}"


def _current_deploy_id() -> str:
    """Best-effort identifier for the current deployment.

    The grace window must be anchored to the deploy, not to "the first
    time this Mongo doc was ever written" — otherwise a long-running
    cluster that loses a webhook on a fresh rollout would page
    immediately because the persisted ``first_observed_ts`` is already
    weeks old. We therefore reseed ``first_observed_ts`` whenever the
    deploy identifier on the per-env doc differs from the one the
    process is currently running under.

    Resolution order, most→least specific:

      * ``RAILWAY_DEPLOYMENT_ID`` — Railway's per-deployment uuid; the
        canonical signal a new image / config has rolled out.
      * ``RAILWAY_GIT_COMMIT_SHA`` — falls back to the git commit a
        deployment was built from. Two redeploys of the same commit
        (e.g. an env-only change) won't reset the anchor under this
        fallback alone, but Railway sets the ID above whenever an
        env-only change ships, so the combined signal is correct.
      * ``RENDER_GIT_COMMIT`` / ``GIT_COMMIT_SHA`` — generic
        equivalents for non-Railway deploys (Render, manual scripts).
      * ``DEPLOY_ID`` — manual override an operator can set when none
        of the above are available (e.g. a bare-metal rollout).
      * Process-boot timestamp — last resort. A pod restart counts as
        a new deploy for the purposes of resetting grace; this is
        the most conservative default since a stuck-old anchor is the
        failure mode we're trying to avoid.

    All values are trimmed; whitespace-only env vars fall through to
    the next level (mirrors the ``slack_webhook_url_for`` helper).
    """
    for env in (
        "RAILWAY_DEPLOYMENT_ID",
        "RAILWAY_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT",
        "GIT_COMMIT_SHA",
        "DEPLOY_ID",
    ):
        raw = (os.environ.get(env) or "").strip()
        if raw:
            return raw
    return _PROCESS_BOOT_ID


# ─── Tunables ───────────────────────────────────────────────────────────────

# How long after the alerter first observed this deployment we wait
# before paging on a still-missing env var. 24h matches the task spec
# ("a deploy that ships without the webhook can sit 'Slack ✗'
# indefinitely") — operators get a full day to land the secret before
# we start pestering on-call.
_BOOTSTRAP_GRACE_S = int(
    os.environ.get("SLACK_WEBHOOK_MISSING_BOOTSTRAP_GRACE_S")
    or 24 * 3600
)
# Re-page cadence while the env is still missing. 24h matches every
# sibling silence-alerter (cf-waf-drift, cf-pull, edge-proxy-deploy)
# so on-call sees a uniform page cadence across the admin surface.
_REALERT_INTERVAL_S = int(
    os.environ.get("SLACK_WEBHOOK_MISSING_REALERT_INTERVAL_S")
    or 24 * 3600
)
# Background poll cadence + warmup. The task spec says "once per day
# per replica" — daily is plenty since the underlying signal (env var
# set or not) only changes when an operator deploys a new secret, and
# a 24h window is fine because the bootstrap grace is also 24h.
# Warmup keeps a bouncing replica from spamming on the first 60s
# after boot when leadership hasn't settled.
_LOOP_SLEEP_S = int(
    os.environ.get("SLACK_WEBHOOK_MISSING_LOOP_SLEEP_S") or 24 * 3600
)
_WARMUP_S = int(
    os.environ.get("SLACK_WEBHOOK_MISSING_WARMUP_S") or 900
)
# Maximum lease TTL the loop will request from background_lease,
# regardless of how long ``_LOOP_SLEEP_S`` is. Caps the
# ``max(900, _LOOP_SLEEP_S * 3)`` formula so a 24h cadence loop
# doesn't end up holding a 72h lease that blocks failover for
# three days when a leader crashes between iterations. 1h is
# wildly generous for the actual workload (a handful of Mongo
# find_one + update_one calls that complete in milliseconds).
_LEASE_TTL_CEILING_S = int(
    os.environ.get("SLACK_WEBHOOK_MISSING_LEASE_TTL_CEILING_S") or 3600
)

# The three env-var names we monitor. Stored as a tuple (not a set)
# so the iteration order is deterministic — simplifies tests + makes
# the per-env state docs predictable for an operator hand-querying
# Mongo. Imported from :mod:`routes.slack_alerter_config` so the
# single source of truth for these names stays put.
_MONITORED_ENV_NAMES: tuple[str, ...] = (
    UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK_ENV,
    CF_WAF_DRIFT_SLACK_WEBHOOK_ENV,
    EDGE_PROXY_DEPLOY_SLACK_WEBHOOK_ENV,
)


def _lock_id_for(env_name: str) -> str:
    """Per-env state doc id. Keeping the env name in the id (instead
    of a single combined doc) lets the existing CAS / debounce
    machinery from the sibling silence alerters lift cleanly without
    a forked "which sub-key are we updating" multiplexer.
    """
    return f"slack_webhook_missing_alert_state__{env_name}"


def _human_label_for(env_name: str) -> str:
    """Human-readable description of which alerter the missing env
    var disables. Used in the email + in-app body so on-call knows
    *what* they lose when this env stays unset, not just the env name.
    """
    if env_name == UNIFIED_LOGS_CF_PULL_SLACK_WEBHOOK_ENV:
        return (
            "the unified-logs Cloudflare-pull silence alerter "
            "(Task #951)"
        )
    if env_name == CF_WAF_DRIFT_SLACK_WEBHOOK_ENV:
        return "the Cloudflare firewall drift cron alerter (Task #831)"
    if env_name == EDGE_PROXY_DEPLOY_SLACK_WEBHOOK_ENV:
        return "the edge-proxy-deploy CI alerter (Task #893)"
    return env_name


# ─── Classification ────────────────────────────────────────────────────────

def _classify_env(
    env_name: str, now_ts: float, first_observed_ts: Optional[float],
) -> str:
    """Reduce one env to ``missing`` / ``healthy`` / ``unknown``.

    * ``unknown`` — the env is unset BUT we are still inside the
      bootstrap grace window (operator hasn't had a chance to set
      the secret yet, or first observation hasn't even been seeded).
    * ``missing`` — the env is unset AND the bootstrap grace window
      has elapsed since the alerter first observed this deployment.
    * ``healthy`` — the env is set to a non-blank value.

    The "unset means whitespace-only counts" check lives in
    :func:`routes.slack_alerter_config.slack_webhook_url_for` which
    we delegate to so this alerter and the silence alerters
    (and the AdminHealth ``slackConfigured`` badge) all agree on
    what "configured" means.
    """
    if slack_webhook_url_for(env_name):
        return "healthy"
    if first_observed_ts is None:
        return "unknown"
    bootstrap_age = now_ts - float(first_observed_ts)
    if bootstrap_age >= _BOOTSTRAP_GRACE_S:
        return "missing"
    return "unknown"


async def _seed_first_observed_if_missing(
    db, env_name: str, now_ts: float,
) -> Optional[float]:
    """Stamp ``first_observed_ts`` (anchored to the current deploy)
    on the per-env state doc.

    The grace window is anchored to the *deploy*, not to "the first
    time this Mongo doc was ever written". On a brand-new doc we
    write the current deploy id alongside the freshly seeded
    timestamp. On a doc that already exists we compare the stored
    deploy id to the one the process is running under: if they match
    the persisted ``first_observed_ts`` is correct, but if they
    differ a new image / config has rolled out and we reseed
    ``first_observed_ts`` to ``now_ts`` (and update ``deploy_id``).
    Without this reseed, a long-running cluster that loses a webhook
    on a fresh rollout would page immediately because the persisted
    anchor is already weeks old — the failure mode the code review
    of Task #970 identified as blocking.

    ``last_state`` and ``last_alert_at`` are intentionally NOT cleared
    on deploy change. That preserves two important behaviours:

      * if the env is now set on the new deploy and the prior deploy
        had ``last_state="missing"``, the missing→healthy recovery
        page still fires so the operator gets the "good job, you
        fixed it" signal;
      * if the env is still unset on the new deploy, the broken-side
        CAS guard's debounce check on ``last_alert_at`` still rate-
        limits us to one page per 24h across the deploy boundary
        instead of double-paging an already-acknowledged incident.

    Best-effort — never raises (matches the sibling silence alerters'
    contract so an infra hiccup never turns into a spurious page).
    """
    lock_id = _lock_id_for(env_name)
    deploy_id = _current_deploy_id()
    try:
        existing = await db.job_locks.find_one({"_id": lock_id})
        if existing and existing.get("first_observed_ts"):
            stored_deploy = (existing.get("deploy_id") or "").strip() or None
            if stored_deploy == deploy_id:
                return float(existing["first_observed_ts"])
            # Deploy changed (or the doc predates the deploy_id field
            # entirely) — reseed the anchor to "now" so the new
            # deploy gets a full 24h grace window before we start
            # nagging on a still-missing env. Atomic so a concurrent
            # peer racing on the same tick can't collide.
            await db.job_locks.update_one(
                {"_id": lock_id},
                {"$set": {
                    "first_observed_ts": float(now_ts),
                    "deploy_id": deploy_id,
                    "env_name": env_name,
                    "deploy_id_seeded_at": (
                        datetime.fromtimestamp(now_ts, tz=timezone.utc)
                        .isoformat()
                    ),
                }},
                upsert=False,
            )
            return float(now_ts)
        # ``$setOnInsert`` so a concurrent peer cannot overwrite an
        # earlier observation — same shape as the cf-waf-drift seed.
        await db.job_locks.update_one(
            {"_id": lock_id},
            {"$setOnInsert": {
                "_id": lock_id,
                "env_name": env_name,
                "first_observed_ts": float(now_ts),
                "deploy_id": deploy_id,
            }},
            upsert=True,
        )
        refreshed = await db.job_locks.find_one({"_id": lock_id})
        if refreshed and refreshed.get("first_observed_ts"):
            stored_deploy = (refreshed.get("deploy_id") or "").strip() or None
            if stored_deploy and stored_deploy != deploy_id:
                # We lost the insert race to a peer running under a
                # different deploy id (vanishingly rare — only happens
                # mid-rollout when one replica is on the new image and
                # one is still on the old). Reseed to anchor on our
                # current deploy so the grace window starts now.
                await db.job_locks.update_one(
                    {"_id": lock_id},
                    {"$set": {
                        "first_observed_ts": float(now_ts),
                        "deploy_id": deploy_id,
                        "deploy_id_seeded_at": (
                            datetime.fromtimestamp(now_ts, tz=timezone.utc)
                            .isoformat()
                        ),
                    }},
                    upsert=False,
                )
                return float(now_ts)
            return float(refreshed["first_observed_ts"])
    except Exception as exc:
        logger.debug(
            f"[slack-webhook-missing] first_observed seed failed for "
            f"{env_name}: {exc}"
        )
    return None


# ─── CAS dedup ─────────────────────────────────────────────────────────────

async def _claim_alert_slot(
    db, env_name: str, kind: str, now_utc: datetime,
) -> bool:
    """Atomic single-winner CAS — same shape as the sibling silence
    alerters.

    ``kind`` is ``"missing"`` (broken side) or ``"recovered"``.

    Re-page guard for the broken side: state isn't already missing
    (first detection / recovery flipped back to missing) OR the 24h
    debounce has elapsed (or ``last_alert_at`` is missing on a
    legacy/corrupt doc). Unlike the cf-waf-drift / cf-pull alerters
    we don't need a "same run id" identity check — there is no
    upstream "run" here, just "is the env set or not", and an env
    that's been unset for 25h is genuinely the same incident the
    24h debounce is trying to suppress.
    """
    lock_id = _lock_id_for(env_name)
    set_payload = {
        "env_name": env_name,
        "last_state": "missing" if kind == "missing" else "healthy",
        "last_alert_at": now_utc.isoformat(),
        "updated_at": now_utc.isoformat(),
    }
    if kind == "missing":
        cutoff_iso = (
            now_utc - timedelta(seconds=_REALERT_INTERVAL_S)
        ).isoformat()
        guard = {
            "_id": lock_id,
            "$or": [
                {"last_state": {"$ne": "missing"}},
                {"$or": [
                    {"last_alert_at": {"$lt": cutoff_iso}},
                    {"last_alert_at": {"$exists": False}},
                ]},
            ],
        }
    else:
        guard = {"_id": lock_id, "last_state": "missing"}
    try:
        res = await db.job_locks.find_one_and_update(
            guard, {"$set": set_payload}, upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(
            f"[slack-webhook-missing] CAS failed for {env_name}: {exc}"
        )
        return False
    if kind != "missing":
        return False
    # Bootstrap insert path for the first-ever missing detection on a
    # fresh deployment whose state doc only carries the
    # ``first_observed_ts`` seed (no ``last_state`` yet). Mirrors the
    # sibling alerters so two replicas racing here can't both win.
    try:
        from pymongo.errors import DuplicateKeyError
        await db.job_locks.insert_one({"_id": lock_id, **set_payload})
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
            f"[slack-webhook-missing] bootstrap insert failed for "
            f"{env_name}: {exc}"
        )
        return False


# ─── Channels: email + in-app ──────────────────────────────────────────────

async def _email_admins_about_missing(
    title: str, message: str, kind: str,
) -> None:
    """Best-effort email blast to every admin. Mirrors the sibling
    silence alerters so the inbox is consistent."""
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(
            f"[slack-webhook-missing] email helper unavailable: {exc}"
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
            f"[slack-webhook-missing] admin lookup failed: {exc}"
        )
    color = "#16a34a" if kind == "recovered" else "#dc2626"
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit Slack-webhook config monitor "
        f"(Task #970).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                f"[slack-webhook-missing] email send failed for "
                f"{email}: {exc}"
            )


async def _send_alert(
    db, env_name: str, kind: str, now_utc: datetime,
    first_observed_ts: Optional[float] = None,
) -> None:
    """Email + in-app notification for one env transition.

    ``kind`` is ``"missing"`` or ``"recovered"``. Best-effort — never
    raises. Deliberately does NOT fan out to Slack (the whole point
    of paging is "Slack is broken / unconfigured" — see module
    docstring) so on-call sees a single in-app + email pair, not a
    duplicate page on a sibling alerter's channel.
    """
    label = _human_label_for(env_name)
    if kind == "recovered":
        title = (
            f"Slack webhook restored: {env_name} is configured again"
        )
        msg = (
            f"The on-call Slack incoming-webhook URL for {label} is "
            f"set on the backend again. Silence / recovery pages "
            f"emitted by that alerter will fan out to Slack alongside "
            "the email + in-app channels.\n\n"
            f"Env var: {env_name}\n\n"
            "No further action required."
        )
        notif_type = "info"
    else:
        if first_observed_ts is not None:
            try:
                missing_for_s = max(
                    0, int(now_utc.timestamp() - float(first_observed_ts)),
                )
                missing_for_h = f"{missing_for_s / 3600:.1f}h"
            except Exception:
                missing_for_h = "n/a"
        else:
            missing_for_h = "n/a"
        title = (
            f"Slack webhook missing: {env_name} unset on the backend"
        )
        msg = (
            f"The on-call Slack incoming-webhook URL for {label} is "
            f"unset on the backend (env var {env_name} is empty or "
            "blank). While it stays unset, silence / recovery pages "
            "from that alerter only reach admins via the in-app "
            "inbox + email — they will NOT show up in the on-call "
            "Slack channel the alerter is wired for.\n\n"
            f"Missing for: {missing_for_h} since this backend first "
            "observed the deploy.\n\n"
            "Set the env var to a Cloudflare incoming-webhook URL "
            "(see the AdminHealth cron pill's 'Slack ✗' badge for "
            "the affected alerter) and redeploy the backend. The "
            "alerter will fire a one-shot recovery page on the next "
            "scheduled tick once the value lands."
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
                "kind": "slack_webhook_missing_alert",
                "state": kind,
                "env_name": env_name,
                "first_observed_ts": first_observed_ts,
            },
        })
    except Exception as exc:
        logger.debug(
            f"[slack-webhook-missing] notification persist failed for "
            f"{env_name}: {exc}"
        )

    asyncio.create_task(_email_admins_about_missing(title, msg, kind))


# ─── Main alert iteration ─────────────────────────────────────────────────

async def _check_and_alert_one_env(
    db, env_name: str, now_utc: Optional[datetime] = None,
) -> dict[str, Any]:
    """One alert iteration for a single env var. Returns a small
    report dict (mirrors the sibling silence alerters so the loop's
    inner try/except has a uniform shape and tests can pin behavior
    per env)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    now_ts = now_utc.timestamp()

    first_observed_ts = await _seed_first_observed_if_missing(
        db, env_name, now_ts,
    )

    state = _classify_env(env_name, now_ts, first_observed_ts)
    if state == "unknown":
        return {
            "action": "skip",
            "reason": "inconclusive",
            "state": state,
            "env_name": env_name,
        }

    lock_id = _lock_id_for(env_name)
    prior: dict = {}
    try:
        prior = await db.job_locks.find_one({"_id": lock_id}) or {}
    except Exception as exc:
        logger.debug(
            f"[slack-webhook-missing] prior load failed for "
            f"{env_name}: {exc}"
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

    if state == "missing":
        if prior_state == "missing" and last_alert_dt is not None:
            elapsed_s = (now_utc - last_alert_dt).total_seconds()
            if elapsed_s < _REALERT_INTERVAL_S:
                return {
                    "action": "skip",
                    "reason": "debounced",
                    "elapsed_s": elapsed_s,
                    "env_name": env_name,
                }
        if not await _claim_alert_slot(db, env_name, "missing", now_utc):
            return {
                "action": "skip",
                "reason": "lost_race",
                "env_name": env_name,
            }
        await _send_alert(
            db, env_name, "missing", now_utc,
            first_observed_ts=first_observed_ts,
        )
        return {
            "action": "alerted",
            "kind": "missing",
            "env_name": env_name,
        }

    # state == "healthy"
    if prior_state == "missing":
        if not await _claim_alert_slot(db, env_name, "recovered", now_utc):
            return {
                "action": "skip",
                "reason": "lost_race",
                "env_name": env_name,
            }
        await _send_alert(db, env_name, "recovered", now_utc)
        return {
            "action": "alerted",
            "kind": "recovered",
            "env_name": env_name,
        }

    # Same race-avoidance reasoning as the sibling silence alerters —
    # do NOT bootstrap a healthy state doc here (an unconditional
    # upsert could clobber a peer's missing claim and bypass the 24h
    # debounce).
    return {"action": "skip", "reason": "healthy", "env_name": env_name}


async def _check_and_alert_all_envs(
    db, now_utc: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """One alert iteration across all three monitored envs.

    Each env is processed independently — a CAS lost-race or a
    Mongo blip on one env doesn't stop the loop from checking the
    other two on the same tick. Returns the per-env report dicts in
    the deterministic order :data:`_MONITORED_ENV_NAMES` defines so
    tests can pin the iteration shape.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    reports: list[dict[str, Any]] = []
    for env_name in _MONITORED_ENV_NAMES:
        try:
            reports.append(
                await _check_and_alert_one_env(db, env_name, now_utc)
            )
        except Exception as exc:
            logger.debug(
                f"[slack-webhook-missing] env iteration error for "
                f"{env_name}: {exc}"
            )
            reports.append({
                "action": "skip",
                "reason": "error",
                "env_name": env_name,
            })
    return reports


async def _slack_webhook_missing_alert_loop():
    """Background poll loop.

    Cross-replica dedup: the per-env CAS above already prevents
    N×-paging across replicas, but the loop also acquires a
    Mongo-backed lease so only one replica reads + checks per tick.
    Followers stand down on each tick, mirroring the sibling
    silence-alerter loops.
    """
    from deps import db, is_mongo_available  # type: ignore
    import background_lease as _bglease
    owner_id = _bglease.make_owner_id("slack-webhook-missing")
    lock_id = "slack_webhook_missing_alert_lease"
    # Lease TTL must be long enough that a busy/slow leader doesn't
    # lose its lease mid-iteration, but short enough that a dead
    # leader can be replaced quickly. The sibling silence alerters
    # use ``max(900, _LOOP_SLEEP_S * 3)`` because their loop sleeps
    # for an hour, so 3× = 3h is fine. This loop sleeps for 24h, so
    # the same formula would balloon the TTL to 72h — meaning a
    # crashed leader would block failover for up to three days,
    # exactly the kind of "no-page silence" failure mode this
    # alerter is supposed to catch elsewhere. Cap at
    # ``_LEASE_TTL_CEILING_S`` (1h by default) so failover happens
    # within an hour regardless of the loop cadence. The actual
    # work is three Mongo find_one + at-most-three update_one
    # calls — milliseconds — so 1h is wildly generous as a hold.
    ttl_s = max(900, min(_LEASE_TTL_CEILING_S, _LOOP_SLEEP_S * 3))
    follower_s = max(60, min(3600, _LOOP_SLEEP_S // 2))
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
                await _check_and_alert_all_envs(db)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(
                    f"[slack-webhook-missing] loop iteration error: "
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
