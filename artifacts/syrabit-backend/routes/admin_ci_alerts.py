"""Task #484 — Alert admins when main-branch CI goes red.

Polls the same GitHub Actions workflow runs surfaced by
``/admin/ci-status`` (Task #470) on a 10-minute cadence and:

* fires an admin email + in-app notification on a green→red transition
  (or on first observation of a red main run);
* re-pages every 6h while CI stays red so a multi-day outage doesn't
  silently fall off the radar;
* fires exactly one recovery notification on red→green so the on-call
  knows the gate is healthy again.

Cross-replica safety + spam debounce are both implemented via atomic
CAS on ``db.job_locks`` (one row per workflow,
``_id = "ci_alert_state__<workflow>"``), the same pattern Task #471's
SEO staleness monitor uses. No new collection.

The poller is a no-op when ``GITHUB_REPO`` is unset (local dev) so we
don't burn the unauthenticated GitHub quota guessing at a repo URL.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from routes.admin_ci_status import (
    _cfg,
    _shape_run,
    _DEFAULT_WORKFLOW,
    _FETCH_TIMEOUT_S,
)

logger = logging.getLogger(__name__)

_CI_ALERT_LOOP_SLEEP_S = int(os.environ.get("CI_ALERT_LOOP_SLEEP_S", "600"))
_CI_ALERT_WARMUP_S = int(os.environ.get("CI_ALERT_WARMUP_S", "600"))
_CI_REALERT_INTERVAL_H = int(os.environ.get("CI_ALERT_REALERT_HOURS", "6"))


def _lock_id(workflow: str) -> str:
    return f"ci_alert_state__{workflow}"


def _watched_workflows() -> list[str]:
    """Same two-workflow list the read-only ``/admin/ci-status`` route
    surfaces — keep them in lockstep so the badge and the alerter never
    disagree about which gates count as "main CI"."""
    cfg = _cfg()
    primary = cfg["workflow"] or _DEFAULT_WORKFLOW
    workflows = [primary]
    if "frontend-tests.yml" not in workflows:
        workflows.append("frontend-tests.yml")
    return workflows


async def _fetch_latest_runs_for_alerting(
    workflows: list[str],
) -> tuple[dict[str, Optional[dict[str, Any]]], Optional[str]]:
    """Fetch the latest branch-pinned run for each workflow. Returns
    ``(runs_by_workflow, error_string)``. Mirrors the headers + URL
    shape of ``/admin/ci-status`` so the two paths can't accidentally
    diverge.
    """
    cfg = _cfg()
    if not cfg["repo"]:
        return ({wf: None for wf in workflows}, "GITHUB_REPO not set")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    runs: dict[str, Optional[dict[str, Any]]] = {}
    error: Optional[str] = None
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
                    runs[wf] = None
                    continue
                if resp.status_code != 200:
                    error = f"github returned {resp.status_code}"
                    runs[wf] = None
                    continue
                data = resp.json() or {}
                items = data.get("workflow_runs") or []
                runs[wf] = _shape_run(items[0]) if items else None
            except Exception as exc:
                logger.warning(f"[ci-alerts] fetch failed for {wf}: {exc}")
                error = f"github unreachable: {type(exc).__name__}"
                runs[wf] = None
    return runs, error


def _classify_run(run: Optional[dict[str, Any]]) -> str:
    """Reduce a GitHub run payload to one of ``red`` / ``green`` /
    ``unknown``. ``in_progress`` / ``queued`` / ``cancelled`` runs are
    ``unknown`` — we don't page on those because they're not signal
    that main is broken.
    """
    if not run:
        return "unknown"
    if run.get("status") != "completed":
        return "unknown"
    conclusion = run.get("conclusion")
    if conclusion == "failure":
        return "red"
    if conclusion == "success":
        return "green"
    # cancelled / skipped / timed_out / neutral — inconclusive.
    return "unknown"


async def _claim_ci_alert_slot(
    db, workflow: str, kind: str, prior_state: Optional[str],
    now_utc: datetime, run: Optional[dict[str, Any]],
) -> bool:
    """Atomic single-winner CAS so a multi-replica deployment cannot
    page admins twice for the same red→green or green→red transition
    (or the same 6h re-page cycle while red).

    Guards:
      * ``red``: prior must NOT already be red (initial detection) OR
        the prior alert must be older than the re-alert window
        (legitimate re-page).
      * ``recovered``: prior must currently be ``red``.
    """
    run_id = (run or {}).get("id")
    set_payload = {
        "workflow": workflow,
        "last_state": "red" if kind == "red" else "green",
        "last_alert_at": now_utc.isoformat(),
        "last_run_id": run_id,
        "last_run_conclusion": (run or {}).get("conclusion"),
        "last_run_html_url": (run or {}).get("html_url"),
        "updated_at": now_utc.isoformat(),
    }
    if kind == "red":
        cutoff_iso = (now_utc - timedelta(hours=_CI_REALERT_INTERVAL_H)).isoformat()
        guard = {
            "_id": _lock_id(workflow),
            "$or": [
                {"last_state": {"$ne": "red"}},
                {"last_alert_at": {"$lt": cutoff_iso}},
                {"last_alert_at": {"$exists": False}},
            ],
        }
    else:
        guard = {"_id": _lock_id(workflow), "last_state": "red"}
    try:
        res = await db.job_locks.find_one_and_update(
            guard, {"$set": set_payload}, upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug(f"[ci-alerts] CAS failed for {workflow}: {exc}")
        return False
    if kind != "red":
        # Recovery has no bootstrap path: there must be a prior red row.
        return False
    try:
        from pymongo.errors import DuplicateKeyError
        await db.job_locks.insert_one({"_id": _lock_id(workflow), **set_payload})
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(f"[ci-alerts] bootstrap insert failed for {workflow}: {exc}")
        return False


async def _send_ci_alert(
    db, workflow: str, kind: str, run: Optional[dict[str, Any]],
    now_utc: datetime,
) -> None:
    """Email admins + record an in-app notification. ``kind`` is
    ``"red"`` or ``"recovered"``. Best-effort: never raises."""
    cfg = _cfg()
    branch = cfg["branch"]
    repo = cfg["repo"]
    sha = (run or {}).get("head_sha") or "unknown"
    actor = (run or {}).get("actor") or "unknown"
    url = (run or {}).get("html_url") or ""
    run_no = (run or {}).get("run_number")

    if kind == "recovered":
        title = f"CI recovered: {workflow} on {branch} is green again"
        msg = (
            f"GitHub Actions workflow `{workflow}` on `{repo}@{branch}` "
            f"is passing again (run #{run_no}, commit {sha}). The previous "
            f"failure has been resolved — no further action required."
        )
        notif_type = "info"
    else:
        title = f"CI red: {workflow} failed on {branch}"
        msg = (
            f"GitHub Actions workflow `{workflow}` failed on "
            f"`{repo}@{branch}` (run #{run_no}, commit {sha}, pushed by "
            f"{actor}). Main is currently red — block deploys until this "
            f"is fixed.\n\nRun: {url}"
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
                "kind": "ci_main_alert",
                "state": kind,
                "workflow": workflow,
                "branch": branch,
                "repo": repo,
                "run_id": (run or {}).get("id"),
                "run_number": run_no,
                "head_sha": sha,
                "html_url": url,
            },
        })
    except Exception as exc:
        logger.debug(f"[ci-alerts] notification persist failed: {exc}")

    asyncio.create_task(_email_admins_about_ci(title, msg, url, kind))


async def _email_admins_about_ci(
    title: str, message: str, run_url: str, kind: str,
) -> None:
    """Email every admin (best-effort). Mirrors the helper shape used
    by the KV usage monitor (Task #476) and the SEO staleness monitor
    (Task #471) so all three admin alert channels look consistent in
    the inbox.
    """
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(f"[ci-alerts] email helper unavailable: {exc}")
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
        logger.debug(f"[ci-alerts] admin lookup failed: {exc}")
    color = "#16a34a" if kind == "recovered" else "#dc2626"
    run_link = (
        f"<p style='font-size:13px;'><a href='{run_url}' "
        f"style='color:#2563eb;'>View the failing run on GitHub →</a></p>"
        if run_url and kind != "recovered" else ""
    )
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{message}</p>"
        f"{run_link}"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit main-branch CI monitor (Task #484).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(f"[ci-alerts] email send failed for {email}: {exc}")


async def _check_and_alert_ci_for_workflow(
    db, workflow: str, run: Optional[dict[str, Any]], now_utc: datetime,
) -> dict:
    """One iteration of the alerter for a single workflow. Returns a
    small report dict for tests / observability."""
    state = _classify_run(run)
    if state == "unknown":
        # Don't touch the state doc — an in-progress run shouldn't
        # erase the last completed observation.
        return {"action": "skip", "reason": "inconclusive",
                "workflow": workflow, "state": state}

    prior: dict = {}
    try:
        prior = await db.job_locks.find_one(
            {"_id": _lock_id(workflow)}
        ) or {}
    except Exception as exc:
        logger.debug(f"[ci-alerts] prior load failed for {workflow}: {exc}")
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

    if state == "red":
        # Fast-path debounce — avoids an unnecessary CAS round-trip.
        if prior_state == "red" and last_alert_dt is not None:
            elapsed_h = (now_utc - last_alert_dt).total_seconds() / 3600.0
            if elapsed_h < _CI_REALERT_INTERVAL_H:
                return {"action": "skip", "reason": "debounced",
                        "workflow": workflow, "elapsed_h": elapsed_h}
        if not await _claim_ci_alert_slot(db, workflow, "red",
                                          prior_state, now_utc, run):
            return {"action": "skip", "reason": "lost_race",
                    "workflow": workflow}
        await _send_ci_alert(db, workflow, "red", run, now_utc)
        return {"action": "alerted", "kind": "red", "workflow": workflow}

    # state == "green"
    if prior_state == "red":
        if not await _claim_ci_alert_slot(db, workflow, "recovered",
                                          prior_state, now_utc, run):
            return {"action": "skip", "reason": "lost_race",
                    "workflow": workflow}
        await _send_ci_alert(db, workflow, "recovered", run, now_utc)
        return {"action": "alerted", "kind": "recovered",
                "workflow": workflow}

    # green → green: do NOT bootstrap a state doc here. An absent doc
    # is treated identically to ``last_state="green"`` by every read
    # path above (red detection bootstraps via insert; green detection
    # short-circuits), so writing one would be pure noise — and worse,
    # an unconditional upsert from this replica could race a peer
    # that just claimed `red`, silently overwriting the lock and
    # bypassing the 6h debounce on the next iteration.
    return {"action": "skip", "reason": "healthy", "workflow": workflow}


async def _check_and_alert_ci(
    db, now_utc: Optional[datetime] = None,
) -> dict:
    """One full poll cycle covering every watched workflow. Returns a
    per-workflow report. No-ops cleanly when GITHUB_REPO isn't set."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if not _cfg()["repo"]:
        return {"action": "skip", "reason": "not_configured", "results": {}}
    workflows = _watched_workflows()
    runs, fetch_error = await _fetch_latest_runs_for_alerting(workflows)
    results: dict[str, dict] = {}
    for wf in workflows:
        try:
            results[wf] = await _check_and_alert_ci_for_workflow(
                db, wf, runs.get(wf), now_utc,
            )
        except Exception as exc:
            logger.warning(f"[ci-alerts] iteration error for {wf}: {exc}")
            results[wf] = {"action": "skip", "reason": "exception",
                           "workflow": wf, "error": str(exc)[:200]}
    return {"action": "checked", "results": results, "fetch_error": fetch_error}


async def _ci_alert_loop():
    """Background poll loop. Cross-replica dedup is handled by the
    per-workflow CAS so this loop is safe to run on every replica, but
    in practice ``server.py`` only spawns it on the leader to keep
    GitHub API calls cheap."""
    from deps import db, is_mongo_available  # type: ignore
    await asyncio.sleep(_CI_ALERT_WARMUP_S)
    while True:
        try:
            if _cfg()["repo"] and await is_mongo_available():
                await _check_and_alert_ci(db)
        except Exception as exc:
            logger.debug(f"[ci-alerts] loop iteration error: {exc}")
        await asyncio.sleep(_CI_ALERT_LOOP_SLEEP_S)
