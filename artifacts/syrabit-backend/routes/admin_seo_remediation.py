"""Task #938 — Admin endpoints for the closed-loop content remediation agent.

Endpoints (all admin-only, mounted under the existing ``/api`` prefix):

    GET   /admin/seo/remediation/status              — budget + circuit pill
    GET   /admin/seo/remediation/history             — recent attempts (7d default)
    POST  /admin/seo/remediation/{rec_id}/promote    — publish a drafted attempt
    POST  /admin/seo/remediation/trigger             — manually enqueue a signal
    POST  /admin/seo/remediation/circuit/reset       — clear the breaker

The frontend ``RemediationTab`` consumes these endpoints to render
the "Auto-remediation history" panel + status pill described in
the task spec.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from auth_deps import get_admin_user
from deps import db
import seo_remediation_service as rem

logger = logging.getLogger(__name__)

router = APIRouter()


def _shape_history_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """camelCase + ISO timestamps for UI consumption. Mirrors the
    convention used by routes/admin_topic_discovery.py so the
    AdminSeoManager wrapper can be consistent."""
    if not row:
        return {}

    def _iso(v):
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).isoformat()
        return v

    scores = row.get("scores") or {}
    return {
        "id": row.get("id"),
        "signalId": row.get("signal_id"),
        "signalKind": row.get("signal_kind"),
        "signalUrl": row.get("signal_url"),
        "signalDetails": row.get("signal_details") or {},
        "detectedAt": _iso(row.get("detected_at")),
        "attemptedAt": _iso(row.get("attempted_at")),
        "promotedAt": _iso(row.get("promoted_at")),
        "pageId": row.get("page_id"),
        "topicId": row.get("topic_id"),
        "topicTitle": row.get("topic_title"),
        "pageType": row.get("page_type"),
        "topicSlug": row.get("topic_slug"),
        "subjectSlug": row.get("subject_slug"),
        "beforeStatus": row.get("before_status"),
        "afterStatus": row.get("after_status"),
        "scoreBefore": scores.get("before"),
        "scoreAfter": scores.get("after"),
        "scoreDelta": scores.get("delta"),
        "action": row.get("action"),
        "reason": row.get("reason"),
        "error": row.get("error"),
    }


@router.get("/admin/seo/remediation/status")
async def remediation_status(_admin: dict = Depends(get_admin_user)):
    """Return today's budget + circuit breaker state for the UI pill.

    Tiny, cheap call — the dashboard polls this alongside the rest
    of the SEO Manager refresh cycle, so it must not do any heavy
    aggregation. Two indexed point-reads (one per collection)."""
    cfg = rem.get_config()
    budget = await rem.get_budget_status(db)
    circuit = await rem.get_circuit_status(db)
    return {
        "enabled": cfg["enabled"],
        "budget": budget,
        "circuit": circuit,
        "config": {
            "minImprovementDelta": cfg["min_improvement_delta"],
            "fanoutCapPerEvent": cfg["fanout_cap_per_event"],
            "circuitWindowSize": cfg["circuit_window_size"],
            "circuitTripRatio": cfg["circuit_trip_ratio"],
            "circuitCooldownHours": cfg["circuit_cooldown_hours"],
        },
    }


@router.get("/admin/seo/remediation/history")
async def remediation_history(
    days: int = Query(7, ge=1, le=30, description="Lookback window."),
    limit: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None,
        description="Filter by action (auto_republished, drafted, etc.)."),
    _admin: dict = Depends(get_admin_user),
):
    """Return the most recent remediation attempts for the admin
    "Auto-remediation history" panel."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query: Dict[str, Any] = {"attempted_at": {"$gte": cutoff}}
    if action:
        if action not in rem.VALID_ACTIONS:
            raise HTTPException(status_code=400, detail=f"unknown action: {action}")
        query["action"] = action
    cursor = db.seo_remediation_history.find(query, {"_id": 0}) \
        .sort("attempted_at", -1).limit(limit)
    rows = await cursor.to_list(limit)
    return {
        "items": [_shape_history_row(r) for r in rows],
        "count": len(rows),
        "windowDays": days,
    }


@router.post("/admin/seo/remediation/{rec_id}/promote")
async def remediation_promote(
    rec_id: str,
    _admin: dict = Depends(get_admin_user),
):
    """Publish a drafted remediation attempt. The seo_pages doc has
    already been written by the worker; we just flip status to
    published + in_sitemap=true and stamp ``promoted_at`` on the
    history row so the panel can show "promoted by admin".

    Uses atomic ``find_one_and_update`` with predicates on both
    docs so two concurrent admin clicks cannot both succeed:
    the second one either sees the already-flipped doc (None
    returned) or the already-stamped history row.
    """
    rec = await db.seo_remediation_history.find_one({"id": rec_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="remediation record not found")
    if rec.get("action") != rem.ACTION_DRAFTED:
        raise HTTPException(
            status_code=400,
            detail=f"only drafted attempts can be promoted (got action={rec.get('action')})",
        )
    if rec.get("promoted_at"):
        raise HTTPException(status_code=409, detail="already promoted")
    page_id = rec.get("page_id")
    if not page_id:
        raise HTTPException(status_code=400, detail="record has no page_id")

    now = datetime.now(timezone.utc).isoformat()
    admin_label = (_admin or {}).get("username") or "admin"

    # 1) Atomically claim the history row by stamping promoted_at
    #    only if it is still null. Loser of the race gets None back
    #    and we can safely 409 without having mutated any pages doc.
    claimed = await db.seo_remediation_history.find_one_and_update(
        {"id": rec_id, "promoted_at": None},
        {"$set": {"promoted_at": now, "promoted_by": admin_label}},
        projection={"_id": 0},
    )
    if not claimed:
        raise HTTPException(status_code=409, detail="already promoted")

    # 2) Atomically flip the page only if it is still in draft
    #    state. If a concurrent admin/auto-publish already took
    #    over the page, roll back the history stamp so the rec
    #    becomes promotable again once the operator re-checks.
    flipped = await db.seo_pages.find_one_and_update(
        {"id": page_id, "status": "draft"},
        {"$set": {
            "status": "published",
            "in_sitemap": True,
            "updated_at": now,
        }},
        projection={"_id": 0},
    )
    if not flipped:
        # Roll back the history stamp so the record is not
        # incorrectly marked promoted when no actual page flip
        # happened. This keeps the audit log honest.
        await db.seo_remediation_history.update_one(
            {"id": rec_id},
            {"$set": {"promoted_at": None, "promoted_by": None}},
        )
        # Distinguish missing-page (404) from page-changed-state
        # (409) for the operator.
        page_now = await db.seo_pages.find_one({"id": page_id}, {"_id": 0})
        if not page_now:
            raise HTTPException(status_code=404, detail="page no longer exists")
        raise HTTPException(
            status_code=409,
            detail=f"page is not draft (status={page_now.get('status')}); "
                   "another change has happened since this attempt was filed",
        )
    # Best-effort IndexNow + edge cache fan-out so search engines
    # see the freshly-promoted page quickly. Same pattern the seo
    # engine uses on direct publish; failure here is non-fatal.
    try:
        from seo_fanout import fanout_for_page
        promoted_page = await db.seo_pages.find_one({"id": page_id}, {"_id": 0})
        if promoted_page:
            fanout_for_page(promoted_page, source="seo_remediation_promote")
    except Exception as exc:
        logger.debug(f"remediation promote fan-out skipped: {exc}")
    return {"ok": True, "promoted_at": now}


@router.post("/admin/seo/remediation/trigger")
async def remediation_trigger(
    body: Dict[str, Any] = Body(...),
    _admin: dict = Depends(get_admin_user),
):
    """Admin-callable: enqueue a manual remediation signal for a URL
    or page id. Useful for testing the loop end-to-end without
    waiting for the alerter to fire, and for one-off re-runs when
    an admin spots a low-quality page in the SEO Manager."""
    url = (body or {}).get("url")
    page_id = (body or {}).get("page_id")
    topic_id = (body or {}).get("topic_id")
    page_type = (body or {}).get("page_type")
    if not (url or page_id or topic_id):
        raise HTTPException(
            status_code=400,
            detail="must provide one of: url, page_id, topic_id",
        )
    signal: Dict[str, Any] = {
        "kind": "manual_trigger",
        "url": url,
        "page_id": page_id,
        "topic_id": topic_id,
        "page_type": page_type,
        "details": {
            "triggered_by": (_admin or {}).get("username") or "admin",
        },
    }
    sid = await rem.enqueue_remediation_signal(db, signal)
    if not sid:
        raise HTTPException(
            status_code=503,
            detail="failed to persist signal; try again shortly",
        )
    return {"ok": True, "signal_id": sid, "enqueued": True}


@router.post("/admin/seo/remediation/circuit/reset")
async def remediation_circuit_reset(_admin: dict = Depends(get_admin_user)):
    """Clear the circuit breaker cooldown + rolling window so the
    loop resumes immediately. Use after fixing whatever was
    producing weak output."""
    await rem.reset_circuit(db)
    return {"ok": True, "reset_at": datetime.now(timezone.utc).isoformat()}
