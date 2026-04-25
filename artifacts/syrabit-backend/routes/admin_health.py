"""Task #882 — AdminHealth pill for the edge-proxy-deploy CI workflow.

The ``edge-proxy-deploy`` GitHub Actions workflow
(``.github/workflows/edge-proxy-deploy.yml``) runs unattended on every
push to master that touches ``workers/edge-proxy/**``. Its
``smoke-preview`` job is the canonical signal that the latest worker
build still passes the burst / D1 / KV / bot-cache checks the
``smoke:preview`` script exercises (see replit.md § "Cloudflare
Workers edge-proxy"). When that job goes red the only current signal
is a red badge in the GitHub Actions UI — the AdminHealth dashboard
that on-call already keeps open is silent.

This module surfaces the latest run via the same cron-pill convention
as the Trustpilot / cf-waf-drift pills (Task #751, Task #831). The
shape returned here intentionally differs from those two: this cron
does NOT post a heartbeat to the backend (no point — the GitHub
Actions REST API is the source of truth for whether the workflow ran
and what it concluded), so we hit
``/repos/<owner>/<repo>/actions/workflows/edge-proxy-deploy.yml/runs?per_page=1``
and translate the response into the
``healthy/silent/degraded/never_observed/not_configured`` status keys
the shared ``<CronHealthPill>`` component understands. Concretely:

* ``conclusion == "failure"`` → ``silent`` (red) — the smoke job
  regressed and on-call should look right now.
* run age > 7 days → ``degraded`` (amber) — deploys this rare are
  themselves suspicious (the workflow only fires on
  ``workers/edge-proxy/**`` pushes, but a 7-day silent gap usually
  means master hasn't moved, which is the signal we want to see).
* otherwise (``success``, in-progress, queued) → ``healthy``.
* No runs returned → ``never_observed``.
* ``GITHUB_REPO`` not set → ``not_configured`` (mirrors
  ``routes.admin_ci_status`` so the same setup hint can render).

The configuration env vars are deliberately the same as
``routes.admin_ci_status`` (``GITHUB_REPO``, ``GITHUB_TOKEN``) so a
single PAT covers every admin GitHub-Actions surface; the workflow
file name is overridable via ``EDGE_PROXY_DEPLOY_WORKFLOW`` in case
someone renames it but otherwise defaults to
``edge-proxy-deploy.yml``. Failures to reach GitHub are surfaced via
``error`` so the UI can render "status temporarily unavailable"
rather than going blank — same defensive shape as
``admin_ci_status``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends

from auth_deps import get_admin_user

logger = logging.getLogger(__name__)
router = APIRouter()

_FETCH_TIMEOUT_S = 5.0
_DEFAULT_WORKFLOW = "edge-proxy-deploy.yml"
# 7 days — the task spec: "a run older than 7 days (deploys this rare
# are themselves suspicious)". Override knob exists so the threshold
# can be tuned without a redeploy if the cadence changes.
_STALE_RUN_THRESHOLD_S = int(
    os.environ.get("EDGE_PROXY_DEPLOY_STALE_THRESHOLD_S") or 7 * 86400
)


def _cfg() -> dict[str, str]:
    return {
        "repo": (os.environ.get("GITHUB_REPO") or "").strip(),
        "token": (os.environ.get("GITHUB_TOKEN") or "").strip(),
        "workflow": (
            os.environ.get("EDGE_PROXY_DEPLOY_WORKFLOW") or _DEFAULT_WORKFLOW
        ).strip(),
    }


def _workflow_url(repo: str, workflow: str) -> str:
    """Public URL of the workflow's runs page on github.com."""
    return f"https://github.com/{repo}/actions/workflows/{workflow}"


def _age_seconds(iso_ts: Optional[str]) -> Optional[int]:
    if not iso_ts:
        return None
    try:
        # GitHub returns Z-suffixed UTC timestamps.
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def _classify(
    *,
    conclusion: Optional[str],
    age_seconds: Optional[int],
) -> str:
    """Map a GitHub run to the shared CronHealthPill status keys.

    Precedence is deliberate: a ``failure`` is the most actionable
    signal so it wins regardless of age — an old red run is still red
    until someone fixes it. A successful run that is simply stale is
    only amber: the smoke gate passed, the box just hasn't been
    touched, which is mildly suspicious but not on-call-page-worthy.
    Anything else (success within window, in-progress, queued) is
    green.
    """
    if (conclusion or "").lower() == "failure":
        return "silent"
    if age_seconds is not None and age_seconds > _STALE_RUN_THRESHOLD_S:
        return "degraded"
    return "healthy"


@router.get("/admin/health/edge-proxy-deploy/cron")
async def admin_edge_proxy_deploy_cron(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Return the latest ``edge-proxy-deploy`` run shaped for the pill.

    Always 200 — surfaces ``configured: false`` / ``status:
    not_configured`` when ``GITHUB_REPO`` isn't set so the dashboard
    can render a setup hint instead of an error. Surfaces ``status:
    never_observed`` when the workflow exists but has not produced any
    runs yet (e.g. brand-new workflow file, or repo just renamed).
    GitHub-side errors land in ``error`` with ``status: unknown``;
    this mirrors ``routes.admin_ci_status``'s defensive contract so
    the AdminHealth tile renders an "unavailable" banner instead of
    going blank.
    """
    cfg = _cfg()
    workflow_url = _workflow_url(cfg["repo"] or "syrabit/syrabit", cfg["workflow"])

    if not cfg["repo"]:
        return {
            "configured": False,
            "status": "not_configured",
            "conclusion": None,
            "html_url": None,
            "updated_at": None,
            "lastRunUrl": None,
            "workflowUrl": workflow_url,
            "ageSeconds": None,
            "staleThresholdSeconds": _STALE_RUN_THRESHOLD_S,
            "error": None,
        }

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"

    url = (
        f"https://api.github.com/repos/{cfg['repo']}"
        f"/actions/workflows/{cfg['workflow']}/runs?per_page=1"
    )

    base = {
        "configured": True,
        "workflowUrl": workflow_url,
        "staleThresholdSeconds": _STALE_RUN_THRESHOLD_S,
    }

    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT_S, headers=headers
        ) as client:
            resp = await client.get(url)
    except Exception as exc:
        logger.warning(f"[edge-proxy-deploy-cron] fetch failed: {exc}")
        return {
            **base,
            "status": "unknown",
            "conclusion": None,
            "html_url": None,
            "updated_at": None,
            "lastRunUrl": None,
            "ageSeconds": None,
            "error": f"github unreachable: {type(exc).__name__}",
        }

    if resp.status_code == 404:
        # Workflow file not present (e.g. renamed). Treat as
        # never_observed so the gray "no run yet" pill renders rather
        # than the red "silent" pill — a 404 here is a config issue,
        # not a CI regression.
        return {
            **base,
            "status": "never_observed",
            "conclusion": None,
            "html_url": None,
            "updated_at": None,
            "lastRunUrl": None,
            "ageSeconds": None,
            "error": None,
        }

    if resp.status_code != 200:
        return {
            **base,
            "status": "unknown",
            "conclusion": None,
            "html_url": None,
            "updated_at": None,
            "lastRunUrl": None,
            "ageSeconds": None,
            "error": f"github returned {resp.status_code}",
        }

    try:
        data = resp.json() or {}
    except Exception:
        data = {}
    items = data.get("workflow_runs") or []
    if not items:
        return {
            **base,
            "status": "never_observed",
            "conclusion": None,
            "html_url": None,
            "updated_at": None,
            "lastRunUrl": None,
            "ageSeconds": None,
            "error": None,
        }

    run = items[0]
    conclusion = run.get("conclusion")
    html_url = run.get("html_url")
    updated_at = run.get("updated_at") or run.get("created_at")
    age_s = _age_seconds(updated_at)
    pill_status = _classify(conclusion=conclusion, age_seconds=age_s)

    return {
        **base,
        "status": pill_status,
        "conclusion": conclusion,
        "html_url": html_url,
        "updated_at": updated_at,
        # Alias used by the shared CronHealthPill wrapper convention
        # (matches lastRunUrl on the cf-waf-drift heartbeat shape) so
        # the pill can render the "Last run" deep-link without the
        # wrapper having to know about the GitHub-specific html_url.
        "lastRunUrl": html_url,
        "ageSeconds": age_s,
        "runStatus": run.get("status"),
        "runId": run.get("id"),
        "runNumber": run.get("run_number"),
        "headSha": (run.get("head_sha") or "")[:7] or None,
        "headBranch": run.get("head_branch"),
        "event": run.get("event"),
        "actor": (run.get("actor") or {}).get("login"),
        "error": None,
    }
