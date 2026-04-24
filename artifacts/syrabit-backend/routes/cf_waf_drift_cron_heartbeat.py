"""Task #831 — Heartbeat ingest for the daily Cloudflare firewall drift cron.

Task #828 wired up ``.github/workflows/cf-waf-drift-daily.yml`` so the
``cf_waf_override.py verify`` and ``aggregate`` gates run once a day and
post a Slack alert on drift. That alerting only works when the cron
actually fires; if GitHub Actions stops scheduling the workflow (repo
archived, workflow disabled in the UI, GitHub Actions outage, account
billing lapse, secret expiry that prevents checkout), the alert path
goes silent and we are back to "drift surfaces only when a user
complains" — exactly the failure mode #828 was meant to remove.

The Trustpilot refresh cron hit the same shape and Task #751 fixed it
by adding an unconditional heartbeat ping from the workflow to the
backend, plus a separate >36h-silence alerter. We mirror that pattern
here so the firewall drift workflow gets the same silent-cron coverage:

  * The workflow POSTs to ``/api/config/cf-waf-drift/heartbeat`` on
    EVERY run (``if: always()``), regardless of whether ``verify`` or
    ``aggregate`` passed. The body includes the verify rc, aggregate
    rc, an aggregate ``status`` string ({success, drift, transport_error,
    failure}) and a deep link to the GitHub Actions run.
  * This module persists the most recent heartbeat to Mongo
    (``job_locks`` doc id ``cf_waf_drift_cron_health``).
  * :mod:`routes.admin_cf_waf_drift_cron_alerts` polls that doc and
    pages admins when no heartbeat has arrived in >36 h.

Auth uses a shared secret stored in ``CF_WAF_DRIFT_HEARTBEAT_SECRET``
(repo secret on the GitHub side, env var on the backend) — same shape
as ``TRUSTPILOT_REFRESH_SECRET`` for the Trustpilot heartbeat.
"""
from __future__ import annotations

import hmac
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


# Shared between the heartbeat writer (this module) and the silence
# alerter so a typo on one side can't silently desync the two.
CF_WAF_DRIFT_HEALTH_DOC_ID = "cf_waf_drift_cron_health"

# Per-task valid status strings the workflow is allowed to send. Anything
# else is recorded verbatim (truncated) but not blessed — keeps the
# endpoint permissive so a future status string addition doesn't 422 the
# cron until both sides ship.
_VALID_STATUSES = {"success", "drift", "transport_error", "failure"}


async def get_cf_waf_drift_cron_health() -> Dict[str, Any]:
    """Return the heartbeat snapshot for the daily cf-waf-drift cron.

    Always returns a plain dict; never raises. Falls back to a
    not-configured shape when Mongo is unavailable so the alerter
    degrades gracefully (treats it as "unknown" → never pages).
    """
    expected_secret = bool(
        (os.environ.get("CF_WAF_DRIFT_HEARTBEAT_SECRET") or "").strip()
    )
    base: Dict[str, Any] = {
        "configured": expected_secret,
        "lastHeartbeatTs": None,
        "lastHeartbeatAgeSeconds": None,
        "lastStatus": None,
        "lastVerifyRc": None,
        "lastAggregateRc": None,
        "lastRunUrl": None,
        "lastWorkflowUrl": None,
        "lastRunId": None,
        "firstObservedTs": None,
    }
    try:
        from deps import db, is_mongo_available  # type: ignore

        if not await is_mongo_available():
            return base
        doc = await db.job_locks.find_one(
            {"_id": CF_WAF_DRIFT_HEALTH_DOC_ID}
        )
    except Exception:
        return base
    if not doc:
        return base
    now = time.time()
    last_hb_ts = float(doc.get("last_heartbeat_ts") or 0.0) or None
    first_obs_ts = float(doc.get("first_observed_ts") or 0.0) or None
    return {
        **base,
        "lastHeartbeatTs": last_hb_ts,
        "lastHeartbeatAgeSeconds": (
            int(now - last_hb_ts) if last_hb_ts else None
        ),
        "lastStatus": doc.get("last_status"),
        "lastVerifyRc": doc.get("last_verify_rc"),
        "lastAggregateRc": doc.get("last_aggregate_rc"),
        "lastRunUrl": doc.get("last_run_url"),
        "lastWorkflowUrl": doc.get("last_workflow_url"),
        "lastRunId": doc.get("last_run_id"),
        "firstObservedTs": first_obs_ts,
    }


def _coerce_optional_int(raw: Any) -> Optional[int]:
    """Best-effort int coercion; returns ``None`` for missing / non-numeric.

    The workflow shell ships these as strings (``echo "rc=$rc"``), so we
    accept both. We deliberately do NOT 422 the cron on a bad payload —
    a transient typo upstream shouldn't mask a real heartbeat.
    """
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@router.post("/api/config/cf-waf-drift/heartbeat")
async def cf_waf_drift_heartbeat(
    body: Dict[str, Any] = Body(default={}),
    x_cf_waf_drift_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Heartbeat ping from the daily cf-waf-drift GitHub Actions workflow.

    Task #831 — the workflow calls this on every run (``if: always()``)
    so the >36h "cron silent" alerter can distinguish "the firewall is
    drifting" from "the firewall drift cron has stopped running".

    Auth: ``CF_WAF_DRIFT_HEARTBEAT_SECRET`` env on the backend, sent by
    the workflow as ``X-CF-WAF-Drift-Secret``. Returns 503 when the
    secret env var isn't configured (fails closed). Always 200 on
    success. Body fields (all optional, best-effort recorded):

      * ``status``: ``"success"`` | ``"drift"`` | ``"transport_error"`` |
        ``"failure"``
      * ``verifyRc``: integer exit code from
        ``cf_waf_override.py verify`` (0 = invariants hold, 1 = drift,
        2 = transport / config error)
      * ``aggregateRc``: integer exit code from
        ``cf_waf_override.py aggregate`` (same convention as ``verify``)
      * ``runUrl``: deep link to the specific GitHub Actions run page
      * ``workflowUrl``: link to the workflow's run history
      * ``runId``: ``${{ github.run_id }}``
    """
    expected = (os.environ.get("CF_WAF_DRIFT_HEARTBEAT_SECRET") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="cf_waf_drift_heartbeat_secret_not_configured",
        )
    provided = (x_cf_waf_drift_secret or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid_heartbeat_secret")

    status_raw = (body.get("status") or "").strip() or None
    if status_raw and status_raw not in _VALID_STATUSES:
        # Be permissive — record what we got but don't 422 the workflow.
        status_raw = status_raw[:32]
    verify_rc = _coerce_optional_int(body.get("verifyRc"))
    aggregate_rc = _coerce_optional_int(body.get("aggregateRc"))
    run_url = (str(body.get("runUrl") or "").strip() or None)
    workflow_url = (str(body.get("workflowUrl") or "").strip() or None)
    run_id = (str(body.get("runId") or "").strip() or None)
    now_ts = time.time()

    try:
        from deps import db, is_mongo_available  # type: ignore

        if await is_mongo_available():
            # ``$max`` on the heartbeat clock so an out-of-order
            # delivery (workflow A's heartbeat lands AFTER workflow B's
            # but reports an earlier timestamp) cannot rewind the
            # silence clock. ``$set`` replaces the metadata with the
            # most recent payload — fine because the alerter only
            # cares about the LATEST run's verify/aggregate state for
            # dashboard rendering, not historical accumulation.
            max_payload: Dict[str, Any] = {"last_heartbeat_ts": float(now_ts)}
            set_payload: Dict[str, Any] = {
                "last_status": status_raw,
                "last_verify_rc": verify_rc,
                "last_aggregate_rc": aggregate_rc,
                "last_run_url": run_url,
                "last_workflow_url": workflow_url,
                "last_run_id": run_id,
                "updated_at": now_ts,
            }
            await db.job_locks.update_one(
                {"_id": CF_WAF_DRIFT_HEALTH_DOC_ID},
                {
                    "$max": max_payload,
                    "$set": set_payload,
                    "$setOnInsert": {"first_observed_ts": float(now_ts)},
                },
                upsert=True,
            )
    except Exception:
        logger.debug(
            "cf-waf-drift heartbeat persist failed", exc_info=True,
        )

    logger.info(
        "cf-waf-drift heartbeat: status=%s verify_rc=%s aggregate_rc=%s run=%s",
        status_raw, verify_rc, aggregate_rc, run_url,
    )
    return {"ok": True, "ts": now_ts}
