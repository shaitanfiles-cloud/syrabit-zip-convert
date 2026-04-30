"""Task #470 — Surface the latest CI build result in the admin dashboard.

``GET /admin/ci-status`` returns the latest GitHub Actions workflow run
for the configured repo so the on-call admin can see red CI without
leaving the app.

``POST /admin/ci-rerun`` triggers a re-run of a failed workflow run by
its ``run_id``.  Requires the GITHUB_TOKEN to carry ``actions:write``
(now granted as of the token-edit-permission upgrade).

Configuration (env vars, all optional — route gracefully reports
``configured: false`` when missing):

* ``GITHUB_REPO`` — ``owner/name`` slug of the repository to query.
* ``GITHUB_TOKEN`` — PAT with ``actions:read`` (+ ``actions:write``
  for the re-run endpoint).  Only required for private repos;
  public repos work unauthenticated for reads.
* ``GITHUB_CI_WORKFLOW`` — workflow file name (default
  ``backend-tests.yml``) so we don't accidentally surface an unrelated
  workflow's status.
* ``GITHUB_CI_BRANCH`` — branch to filter on (default ``main``).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_deps import get_admin_user

logger = logging.getLogger(__name__)
router = APIRouter()

_FETCH_TIMEOUT_S = 5.0
_DEFAULT_WORKFLOW = "backend-tests.yml"
_DEFAULT_BRANCH = "main"


def _cfg() -> dict[str, str]:
    return {
        "repo": (os.environ.get("GITHUB_REPO") or "").strip(),
        "token": (os.environ.get("GITHUB_TOKEN") or "").strip(),
        "workflow": (os.environ.get("GITHUB_CI_WORKFLOW") or _DEFAULT_WORKFLOW).strip(),
        "branch": (os.environ.get("GITHUB_CI_BRANCH") or _DEFAULT_BRANCH).strip(),
    }


def _age_seconds(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        # GitHub returns Z-suffixed UTC timestamps.
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def _shape_run(run: dict[str, Any]) -> dict[str, Any]:
    """Normalize the GitHub run payload to just the fields the UI needs."""
    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "status": run.get("status"),  # queued | in_progress | completed
        "conclusion": run.get("conclusion"),  # success | failure | cancelled | None
        "html_url": run.get("html_url"),
        "head_branch": run.get("head_branch"),
        "head_sha": (run.get("head_sha") or "")[:7],
        "event": run.get("event"),
        "run_number": run.get("run_number"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "age_seconds": _age_seconds(run.get("updated_at") or run.get("created_at")),
        "actor": (run.get("actor") or {}).get("login"),
    }


@router.get("/admin/ci-status")
async def admin_ci_status(admin: dict = Depends(get_admin_user)):
    """Return ``{configured, runs: {<workflow>: <latest run>}, ...}``.

    Always 200 — surfaces ``configured: false`` when the repo isn't set
    so the dashboard can render a setup hint instead of an error pill.
    Failures to reach GitHub are reported via ``error`` so the UI can
    show "CI status temporarily unavailable" rather than going blank.
    """
    cfg = _cfg()
    if not cfg["repo"]:
        return {
            "configured": False,
            "reason": "GITHUB_REPO is not set",
            "runs": {},
        }

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"

    # Fetch latest run for both the backend and frontend workflows so the
    # admin sees both gates in one panel. We pin to the configured branch
    # (default `main`) so a feature-branch run can't make the badge green.
    workflows = [cfg["workflow"], "frontend-tests.yml"]
    runs: dict[str, Any] = {}
    error: str | None = None

    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S, headers=headers) as client:
        for wf in workflows:
            url = (
                f"https://api.github.com/repos/{cfg['repo']}"
                f"/actions/workflows/{wf}/runs"
                f"?branch={cfg['branch']}&per_page=1"
            )
            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    runs[wf] = None  # workflow not yet present on the branch
                    continue
                if resp.status_code != 200:
                    error = f"github returned {resp.status_code}"
                    runs[wf] = None
                    continue
                data = resp.json() or {}
                items = data.get("workflow_runs") or []
                runs[wf] = _shape_run(items[0]) if items else None
            except Exception as exc:
                logger.warning(f"[ci-status] fetch failed for {wf}: {exc}")
                error = f"github unreachable: {type(exc).__name__}"
                runs[wf] = None

    return {
        "configured": True,
        "repo": cfg["repo"],
        "branch": cfg["branch"],
        "runs": runs,
        "error": error,
    }


class _RerunRequest(BaseModel):
    run_id: int
    failed_only: bool = True


@router.post("/admin/ci-rerun")
async def admin_ci_rerun(
    body: _RerunRequest,
    admin: dict = Depends(get_admin_user),
):
    """Trigger a re-run of a GitHub Actions workflow run.

    Uses the ``/actions/runs/{run_id}/rerun`` (all jobs) or
    ``/actions/runs/{run_id}/rerun-failed-jobs`` (failed jobs only)
    GitHub API endpoint.  Requires GITHUB_TOKEN with ``actions:write``.

    Returns ``{queued: true}`` on success (GitHub returns 201 No Content
    for both rerun variants).  On failure the HTTP status code from GitHub
    is forwarded as a 502 so the frontend can display a helpful message.
    """
    cfg = _cfg()
    if not cfg["repo"]:
        raise HTTPException(status_code=503, detail="GITHUB_REPO is not configured")
    if not cfg["token"]:
        raise HTTPException(
            status_code=503,
            detail="GITHUB_TOKEN is not configured — actions:write is required to re-run",
        )

    path = (
        "rerun-failed-jobs" if body.failed_only else "rerun"
    )
    url = (
        f"https://api.github.com/repos/{cfg['repo']}"
        f"/actions/runs/{body.run_id}/{path}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {cfg['token']}",
    }

    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S, headers=headers) as client:
        try:
            resp = await client.post(url, content=b"{}")
        except Exception as exc:
            logger.warning(f"[ci-rerun] request failed: {exc}")
            raise HTTPException(status_code=502, detail=f"GitHub unreachable: {type(exc).__name__}")

    # GitHub returns 201 on success with an empty body.
    if resp.status_code not in (200, 201):
        logger.warning(
            f"[ci-rerun] GitHub returned {resp.status_code} for run {body.run_id}: {resp.text[:200]}"
        )
        raise HTTPException(
            status_code=502,
            detail=f"GitHub returned {resp.status_code}: {resp.text[:120]}",
        )

    logger.info(
        f"[ci-rerun] queued re-run for run {body.run_id} "
        f"(failed_only={body.failed_only}) by {admin.get('username', '?')}"
    )
    return {"queued": True, "run_id": body.run_id, "failed_only": body.failed_only}
