"""Task #899 — Daily prod-down-alert webhook configuration check.

Task #886 set the ``SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL`` Wrangler secret
on the live ``syrabit-edge`` worker, which is what makes the per-minute
synthetic probe (Task #708) actually wake a human if production goes
dark. Nothing today prevents that secret — or the three other secrets
the probe relies on — from being silently removed during an unrelated
Wrangler env reshuffle, an accidental ``wrangler secret delete``, or a
misapplied env-promotion script. If the webhook secret disappears the
next outage looks identical to "everything is healthy" again (the exact
failure mode Task #877 was triggered by).

This module ingests a daily ping from the
``.github/workflows/synthetic-probe-secrets-daily.yml`` cron. The cron
runs ``wrangler secret list --name syrabit-edge`` and, if any of the
four required secrets is missing from the live worker, POSTs the list
of missing names here. We re-dispatch through the existing
``metrics._dispatch_alert`` pipeline (email + webhook + persisted +
push) with ``alert_type="synthetic_probe_secret_missing"`` so the on-call
gets paged the same way every other critical alert does.

Auth uses a shared secret stored in
``SYNTHETIC_PROBE_SECRETS_CHECK_TOKEN`` (repo secret on the GitHub side,
env var on the backend) — same shape as ``CF_WAF_DRIFT_HEARTBEAT_SECRET``
for the Trustpilot/CF-WAF-drift heartbeats.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


# Kept in sync with the ``REQUIRED_SECRETS`` array in
# ``.github/workflows/synthetic-probe-secrets-daily.yml`` and the
# Variables-and-Secrets table in ``docs/CLOUDFLARE_ZERO_TRUST.md`` §7.1.
# Listed here for the sole purpose of bounding the alert body — the
# workflow is the source of truth for what gets checked.
_REQUIRED_SECRETS: List[str] = [
    "SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL",
    "SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID",
    "SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET",
    "SYNTHETIC_PROBE_ADMIN_JWT",
]

_ALERT_TYPE = "synthetic_probe_secret_missing"


def _normalise_missing(raw: Any) -> List[str]:
    """Coerce the workflow payload's ``missing`` field to a clean list.

    Defensive on shape because the workflow ships these via a shell
    ``jq`` invocation — a malformed payload should still land an alert
    rather than 422 the cron and silently mask the problem we exist to
    surface.
    """
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        # Cap individual names so a hostile payload can't blow up the
        # email body. Wrangler secret names are short in practice.
        seen.add(name)
        out.append(name[:128])
        if len(out) >= 32:
            break
    return out


@router.post("/api/config/synthetic-probe-secrets/missing-alert")
async def synthetic_probe_secret_missing_alert(
    body: Dict[str, Any] = Body(default={}),
    x_synthetic_probe_secrets_check_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Page on-call when the daily Wrangler-secrets check finds drift.

    Task #899 — POSTed to by ``synthetic-probe-secrets-daily.yml`` when
    ``wrangler secret list --name syrabit-edge`` reports that one or
    more of the four secrets the synthetic probe / watchdog relies on
    is missing from the live worker.

    Auth: ``SYNTHETIC_PROBE_SECRETS_CHECK_TOKEN`` env on the backend,
    sent by the workflow as ``X-Synthetic-Probe-Secrets-Check-Token``.
    Returns 503 when the secret env var isn't configured (fails closed
    so an unconfigured backend is loud, not silent — the workflow turns
    the 503 into a job failure and GitHub's failed-workflow email then
    serves as the secondary signal).

    Body fields (all optional, best-effort recorded):

      * ``missing``: list of secret names absent from the live worker.
        Empty / omitted means "the cron ran fine, nothing missing" and
        the endpoint becomes a no-op (we still 200 so the workflow
        treats it as a successful round-trip — the alert dispatch is
        gated on ``missing`` being non-empty).
      * ``checked``: list of secret names the workflow verified
        (echoed back in the alert body for context).
      * ``runUrl``: deep link to the specific GitHub Actions run page.
      * ``workflowUrl``: link to the workflow's run history.
      * ``runId``: ``${{ github.run_id }}``.

    Returns ``{"ok": True, "alert_dispatched": bool}``.
    """
    expected = (
        os.environ.get("SYNTHETIC_PROBE_SECRETS_CHECK_TOKEN") or ""
    ).strip()
    if not expected:
        # Fail closed so the workflow's "alert step" turns red and the
        # GitHub failed-workflow email at least makes the missing
        # backend env var visible to repo admins.
        raise HTTPException(
            status_code=503,
            detail="synthetic_probe_secrets_check_token_not_configured",
        )
    provided = (x_synthetic_probe_secrets_check_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401, detail="invalid_synthetic_probe_secrets_check_token"
        )

    missing = _normalise_missing(body.get("missing"))
    checked = _normalise_missing(body.get("checked"))
    run_url = (str(body.get("runUrl") or "").strip() or None)
    workflow_url = (str(body.get("workflowUrl") or "").strip() or None)
    run_id = (str(body.get("runId") or "").strip() or None)

    if not missing:
        # Nothing to alert on. We deliberately do NOT page on a
        # "successful" check ping — the workflow only POSTs here when
        # it has drift to report, but be defensive about an empty list
        # so a future "always heartbeat" change doesn't accidentally
        # spam the on-call.
        logger.info(
            "[synthetic-probe-secrets-check] no missing secrets reported "
            "(checked=%s run=%s) — alert NOT dispatched",
            checked, run_url,
        )
        return {"ok": True, "alert_dispatched": False}

    # Build a body string that's actionable on every channel
    # (Slack/PagerDuty/email/push) without needing to click through
    # to the workflow run.
    lines = [
        "The daily Wrangler-secrets check found that one or more secrets",
        "the synthetic probe / prod-down watchdog relies on are MISSING",
        "from the live `syrabit-edge` worker. Until they are restored",
        "the per-minute probe and/or its watchdog cannot page on a real",
        "outage — exactly the failure mode Task #877 was triggered by.",
        "",
        "Missing secrets (re-set with `wrangler secret put <NAME>",
        "--name syrabit-edge` from `workers/edge-proxy/`):",
    ]
    for name in missing:
        lines.append(f"  - {name}")
    if run_url:
        lines.append("")
        lines.append(f"GitHub Actions run: {run_url}")
    lines.append("")
    lines.append(
        "Runbook: docs/CLOUDFLARE_ZERO_TRUST.md §7.1 (rotation procedure"
        " + nightly-check section)."
    )
    body_text = "\n".join(lines)

    title = (
        f"Synthetic-probe Wrangler secrets MISSING ({len(missing)} of "
        f"{len(_REQUIRED_SECRETS)})"
    )

    threshold_snapshot = {
        "metric": "wrangler.secret_list.required_present",
        "value": str(len(_REQUIRED_SECRETS)),
        "actual": str(len(_REQUIRED_SECRETS) - len(missing)),
        "missing": missing,
        "checked": checked or _REQUIRED_SECRETS,
        "run_url": run_url,
        "workflow_url": workflow_url,
        "run_id": run_id,
    }

    alert_dispatched = False
    try:
        from metrics import _dispatch_alert  # local import: heavy module

        await _dispatch_alert(
            _ALERT_TYPE,
            title,
            body_text,
            threshold_snapshot=threshold_snapshot,
        )
        alert_dispatched = True
    except Exception as exc:  # noqa: BLE001
        # Log loudly but do NOT 5xx — the workflow's "fail the job"
        # step is also armed on a missing-secrets payload, so the
        # GitHub failed-workflow email still carries the signal.
        logger.warning(
            "[synthetic-probe-secrets-check] _dispatch_alert failed: %s",
            exc, exc_info=True,
        )

    logger.warning(
        "ALERT [%s] %s: missing=%s run=%s",
        _ALERT_TYPE, title, missing, run_url,
    )
    return {"ok": True, "alert_dispatched": alert_dispatched}
