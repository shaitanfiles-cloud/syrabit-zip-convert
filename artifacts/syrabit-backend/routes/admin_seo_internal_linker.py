"""Task #939 — Admin endpoints for the agentic internal-linker.

Endpoints (all admin-only, mounted under the existing ``/api`` prefix):

    GET   /admin/seo/internal-links/status                — budget + counts
    GET   /admin/seo/internal-links/pending               — drafted suggestions
    GET   /admin/seo/internal-links/history               — full audit log
    POST  /admin/seo/internal-links/{id}/approve          — insert anchor
    POST  /admin/seo/internal-links/{id}/reject           — drop suggestion
    POST  /admin/seo/internal-links/{id}/revert           — undo auto-applied
    POST  /admin/seo/internal-links/trigger               — manual re-run

The frontend ``LinksTab`` "Pending suggestions" panel consumes these
to render approve/reject buttons + diff preview + revert.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from auth_deps import get_admin_user
from deps import db
import seo_internal_linker as linker

logger = logging.getLogger(__name__)

router = APIRouter()


def _shape_history_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """camelCase + ISO timestamps for UI consumption. Mirrors
    ``routes/admin_seo_remediation._shape_history_row`` so the
    AdminSeoManager wrappers stay consistent."""
    if not row:
        return {}

    def _iso(v):
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).isoformat()
        return v

    diff = row.get("diff") or {}
    return {
        "id": row.get("id"),
        "targetPageId": row.get("target_page_id"),
        "targetTopicId": row.get("target_topic_id"),
        "targetTopicTitle": row.get("target_topic_title"),
        "targetUrl": row.get("target_url"),
        "targetPageType": row.get("target_page_type"),
        "sourcePageId": row.get("source_page_id"),
        "sourceTopicId": row.get("source_topic_id"),
        "sourceTopicTitle": row.get("source_topic_title"),
        "sourceUrl": row.get("source_url"),
        "sourcePageType": row.get("source_page_type"),
        "anchorText": row.get("anchor_text"),
        "confidence": row.get("confidence"),
        "action": row.get("action"),
        "reason": row.get("reason"),
        "trigger": row.get("trigger"),
        "createdAt": _iso(row.get("created_at")),
        "appliedAt": _iso(row.get("applied_at")),
        "approvedAt": _iso(row.get("approved_at")),
        "approvedBy": row.get("approved_by"),
        "rejectedAt": _iso(row.get("rejected_at")),
        "rejectedBy": row.get("rejected_by"),
        "revertedAt": _iso(row.get("reverted_at")),
        "revertedBy": row.get("reverted_by"),
        "diff": {
            "beforeExcerpt": diff.get("before_excerpt") or "",
            "afterExcerpt": diff.get("after_excerpt") or "",
        },
        "error": row.get("error"),
    }


@router.get("/admin/seo/internal-links/status")
async def linker_status(_admin: dict = Depends(get_admin_user)):
    """Budget + recent-action counts for the admin status pill."""
    cfg = linker.get_config()
    budget = await linker.get_budget_status(db)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    pending = await db.internal_link_history.count_documents(
        {"action": linker.ACTION_DRAFTED}
    )
    recent_auto = await db.internal_link_history.count_documents(
        {"action": linker.ACTION_AUTO_APPLIED, "applied_at": {"$gte": cutoff}}
    )
    return {
        "enabled": cfg["enabled"],
        "budget": budget,
        "pendingCount": pending,
        "recentAutoApplied24h": recent_auto,
        "config": {
            "autoApplyThreshold": cfg["auto_apply_threshold"],
            "minLinksPerTarget": cfg["min_links_per_target"],
            "maxLinksPerTarget": cfg["max_links_per_target"],
            "candidatePoolSize": cfg["candidate_pool_size"],
            "nightlyTopN": cfg["nightly_top_n"],
        },
    }


@router.get("/admin/seo/internal-links/pending")
async def linker_pending(
    limit: int = Query(50, ge=1, le=200),
    _admin: dict = Depends(get_admin_user),
):
    """Drafted suggestions awaiting admin approval, newest first."""
    cursor = db.internal_link_history.find(
        {"action": linker.ACTION_DRAFTED}, {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(limit)
    return {"items": [_shape_history_row(r) for r in rows], "count": len(rows)}


@router.get("/admin/seo/internal-links/history")
async def linker_history(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(100, ge=1, le=500),
    action: Optional[str] = Query(None),
    _admin: dict = Depends(get_admin_user),
):
    """Recent activity for the audit panel — filterable by action."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query: Dict[str, Any] = {"created_at": {"$gte": cutoff}}
    if action:
        if action not in linker.VALID_ACTIONS:
            raise HTTPException(status_code=400, detail=f"unknown action: {action}")
        query["action"] = action
    cursor = db.internal_link_history.find(query, {"_id": 0}) \
        .sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(limit)
    return {
        "items": [_shape_history_row(r) for r in rows],
        "count": len(rows),
        "windowDays": days,
    }


@router.post("/admin/seo/internal-links/{rec_id}/approve")
async def linker_approve(rec_id: str, _admin: dict = Depends(get_admin_user)):
    """Approve a pending suggestion: insert the anchor into the
    source body and flip the row to ``auto_applied`` (with
    ``approved_by`` stamped so the audit trail distinguishes
    bot-auto vs human-approved)."""
    admin_label = (_admin or {}).get("username") or "admin"
    res = await linker.apply_pending_suggestion(db, rec_id, admin_label)
    if not res.get("ok"):
        err = res.get("error") or "approve failed"
        status = 404 if err == "not_found" else 409
        raise HTTPException(status_code=status, detail=err)
    return {"ok": True, "approved_at": datetime.now(timezone.utc).isoformat()}


@router.post("/admin/seo/internal-links/{rec_id}/reject")
async def linker_reject(rec_id: str, _admin: dict = Depends(get_admin_user)):
    """Drop a pending suggestion without touching any page body."""
    admin_label = (_admin or {}).get("username") or "admin"
    res = await linker.reject_pending_suggestion(db, rec_id, admin_label)
    if not res.get("ok"):
        err = res.get("error") or "reject failed"
        status = 404 if err == "not_found" else 409
        raise HTTPException(status_code=status, detail=err)
    return {"ok": True, "rejected_at": datetime.now(timezone.utc).isoformat()}


@router.post("/admin/seo/internal-links/{rec_id}/revert")
async def linker_revert(rec_id: str, _admin: dict = Depends(get_admin_user)):
    """Remove a previously auto-applied (or admin-approved) anchor
    from the source body. Idempotent — calling on an already-reverted
    row is a no-op response. Designed for "oops, that link looks
    weird" recovery without an admin having to hand-edit the page."""
    admin_label = (_admin or {}).get("username") or "admin"
    res = await linker.revert_applied_suggestion(db, rec_id, admin_label)
    if not res.get("ok"):
        err = res.get("error") or "revert failed"
        status = 404 if err == "not_found" else 409
        raise HTTPException(status_code=status, detail=err)
    return {"ok": True, "reverted_at": datetime.now(timezone.utc).isoformat(),
            "warning": res.get("warning")}


@router.post("/admin/seo/internal-links/trigger")
async def linker_trigger(
    body: Dict[str, Any] = Body(...),
    _admin: dict = Depends(get_admin_user),
):
    """Manually re-run the linker against a target page, identified
    by ``page_id`` (preferred) or ``(topic_id, page_type)``. Useful
    for re-running after a body edit changed the candidate pool, or
    for testing the loop end-to-end without waiting for the nightly
    pass. Awaits inline so the admin sees the result row count."""
    page_id = (body or {}).get("page_id")
    topic_id = (body or {}).get("topic_id")
    page_type = (body or {}).get("page_type") or "notes"
    if not page_id and not topic_id:
        raise HTTPException(
            status_code=400,
            detail="must provide one of: page_id, topic_id",
        )
    if page_id:
        target = await db.seo_pages.find_one({"id": page_id}, {"_id": 0})
    else:
        target = await db.seo_pages.find_one(
            {"topic_id": topic_id, "page_type": page_type}, {"_id": 0},
        )
    if not target:
        raise HTTPException(status_code=404, detail="target page not found")
    rows = await linker.propose_internal_links_for_page(
        db, target, source="manual_trigger",
    )
    return {
        "ok": True,
        "rows_created": len(rows),
        "actions": [r.get("action") for r in rows],
    }
