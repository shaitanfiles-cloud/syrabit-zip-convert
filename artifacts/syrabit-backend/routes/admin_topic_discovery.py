"""Task #937 — Admin endpoints for the autonomous topic-discovery agent.

Endpoints (all admin-only, mounted under the existing ``/api`` prefix):

    GET  /admin/seo/topic-discovery/runs            — recent runs
    GET  /admin/seo/topic-discovery/candidates      — paged candidate list
    POST /admin/seo/topic-discovery/run-now         — fire one run synchronously
    POST /admin/seo/topic-discovery/{cand_id}/override
                                                    — promote / reject

The frontend ``TopicDiscoveryTab`` consumes only these four endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from auth_deps import get_admin_user
from deps import db
import topic_discovery_service as tds

logger = logging.getLogger(__name__)

router = APIRouter()


def _shape_run(row: Dict[str, Any]) -> Dict[str, Any]:
    """camelCase + ISO timestamps for UI consumption."""
    if not row:
        return {}
    def _iso(v):
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).isoformat()
        return v
    out = {
        "id": row.get("id"),
        "kind": row.get("kind") or "run",
        "startedAt": _iso(row.get("started_at")),
        "finishedAt": _iso(row.get("finished_at")),
        "elapsedSeconds": row.get("elapsed_seconds"),
        "configSnapshot": row.get("config_snapshot") or {},
        "totals": row.get("totals") or {},
        "remainingAfterRun": row.get("remaining_after_run") or {},
    }
    if row.get("claimed_at") and not row.get("started_at"):
        out["claimedAt"] = _iso(row.get("claimed_at"))
    if row.get("ran_at"):
        out["ranAt"] = _iso(row.get("ran_at"))
    return out


def _shape_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    def _iso(v):
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).isoformat()
        return v
    return {
        "id": row.get("id"),
        "runId": row.get("run_id"),
        "query": row.get("query"),
        "sources": list(row.get("sources") or []),
        "signals": row.get("signals") or {},
        "score": row.get("score") or {},
        "decision": row.get("decision"),
        "decisionReason": row.get("decision_reason"),
        "enqueuedTopic": row.get("enqueued_topic"),
        "enqueueError": row.get("enqueue_error"),
        "createdAt": _iso(row.get("created_at")),
        "adminDecision": row.get("admin_decision"),
        "adminReason": row.get("admin_reason"),
        "adminId": row.get("admin_id"),
        "adminOverrideAt": _iso(row.get("admin_override_at")),
    }


@router.get("/admin/seo/topic-discovery/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_admin_user),
):
    """Most-recent topic-discovery runs (newest first)."""
    if db is None:
        return {"runs": []}
    try:
        cursor = db[tds.RUNS_COLLECTION].find(
            {"$or": [{"kind": {"$exists": False}}, {"kind": {"$ne": "daily_lock"}}]},
            {"_id": 0},
        ).sort("started_at", -1).limit(int(limit))
        rows = [row async for row in cursor]
    except Exception as exc:
        logger.info("admin/topic-discovery/runs read failed: %s", exc)
        rows = []
    return {"runs": [_shape_run(r) for r in rows]}


@router.get("/admin/seo/topic-discovery/candidates")
async def list_candidates(
    run_id: Optional[str] = Query(None, max_length=64),
    decision: Optional[str] = Query(
        None, regex="^(auto_published|drafted|rejected|error)$",
    ),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0, le=10000),
    admin: dict = Depends(get_admin_user),
):
    """Paged candidate list. Filterable by run_id and decision."""
    if db is None:
        return {"candidates": [], "total": 0}
    q: Dict[str, Any] = {}
    if run_id:
        q["run_id"] = run_id
    if decision:
        q["decision"] = decision
    try:
        total = await db[tds.CANDIDATES_COLLECTION].count_documents(q)
        cursor = db[tds.CANDIDATES_COLLECTION].find(q, {"_id": 0}) \
            .sort([("created_at", -1), ("score.total", -1)]).skip(int(skip)).limit(int(limit))
        rows = [row async for row in cursor]
    except Exception as exc:
        logger.info("admin/topic-discovery/candidates read failed: %s", exc)
        rows = []
        total = 0
    return {
        "candidates": [_shape_candidate(r) for r in rows],
        "total": int(total or 0),
    }


@router.post("/admin/seo/topic-discovery/run-now")
async def run_now(admin: dict = Depends(get_admin_user)):
    """Fire one synchronous run. Returns the run summary."""
    if db is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    try:
        summary = await tds.run_topic_discovery_once(db)
    except Exception as exc:
        logger.warning("admin/topic-discovery/run-now failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"run failed: {exc}")
    return _shape_run(summary)


@router.post("/admin/seo/topic-discovery/{candidate_id}/override")
async def override_decision(
    candidate_id: str,
    payload: Dict[str, Any] = Body(...),
    admin: dict = Depends(get_admin_user),
):
    """Promote or reject a candidate. Body: ``{decision, reason}``.

    ``decision`` must be one of ``auto_published`` / ``drafted`` /
    ``rejected``. Override is logged on the candidate row and the next
    grader run reads it as a few-shot example.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    decision = (payload.get("decision") or "").strip()
    reason = (payload.get("reason") or "").strip()
    if decision not in tds.VALID_OVERRIDE_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"decision must be one of {sorted(tds.VALID_OVERRIDE_DECISIONS)}",
        )
    try:
        updated = await tds.apply_override(
            db,
            candidate_id=candidate_id,
            new_decision=decision,
            admin_reason=reason,
            admin_id=str(admin.get("id") or admin.get("sub") or "admin"),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="candidate not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning("topic-discovery override failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"override failed: {exc}")
    return {"candidate": _shape_candidate(updated)}
