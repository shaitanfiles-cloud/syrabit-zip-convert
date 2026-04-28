"""
Admin endpoints for the topic-citation pipeline (Task #914 Step 1).

Surfaces:
- `GET  /api/admin/topics/audit-summary`       counters of slug + definition coverage.
- `GET  /api/admin/topics/definition-missing`  paginated list of topics that need a definition before their AI answer card / topic deep-link can publish.
- `POST /api/admin/topics/backfill-slugs`      idempotent re-run of the slug + definition_status backfill, returning the same counters as the CLI.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import db, is_mongo_available
from auth_deps import get_admin_user
from scripts.backfill_topic_slugs import (
    DEFINITION_STATUS_MISSING,
    DEFINITION_STATUS_OK,
    run_backfill,
)

router = APIRouter()


async def _audit_counters() -> dict[str, int]:
    """Live counts straight off the topics collection, no caching.

    Cheap (single aggregation) and the admin panel only polls when an
    operator opens the audit tab, so no value in caching here.
    """
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total": {"$sum": 1},
                "with_topic_slug": {
                    "$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$topic_slug", ""]}}, 0]}, 1, 0]},
                },
                "definition_ok": {
                    "$sum": {"$cond": [{"$eq": ["$definition_status", DEFINITION_STATUS_OK]}, 1, 0]},
                },
                "definition_missing": {
                    "$sum": {"$cond": [{"$eq": ["$definition_status", DEFINITION_STATUS_MISSING]}, 1, 0]},
                },
                "published": {
                    "$sum": {"$cond": [{"$eq": ["$status", "published"]}, 1, 0]},
                },
            },
        },
    ]
    rows = await db.topics.aggregate(pipeline).to_list(1)
    if not rows:
        return {
            "total": 0,
            "with_topic_slug": 0,
            "definition_ok": 0,
            "definition_missing": 0,
            "published": 0,
            # Topics that have neither been backfilled nor explicitly
            # marked. Helpful for spotting freshly-imported docs that
            # haven't seen the audit yet.
            "unaudited": 0,
        }
    row = rows[0]
    audited = int(row.get("definition_ok", 0)) + int(row.get("definition_missing", 0))
    return {
        "total": int(row.get("total", 0)),
        "with_topic_slug": int(row.get("with_topic_slug", 0)),
        "definition_ok": int(row.get("definition_ok", 0)),
        "definition_missing": int(row.get("definition_missing", 0)),
        "published": int(row.get("published", 0)),
        "unaudited": int(row.get("total", 0)) - audited,
    }


@router.get("/admin/topics/audit-summary")
async def admin_topic_audit_summary(admin: dict = Depends(get_admin_user)) -> dict[str, Any]:
    counters = await _audit_counters()
    return {"counters": counters}


@router.get("/admin/topics/definition-missing")
async def admin_topic_definition_missing(
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    cursor = (
        db.topics
        .find(
            {"definition_status": DEFINITION_STATUS_MISSING},
            {"_id": 0, "id": 1, "title": 1, "topic_slug": 1, "chapter_id": 1, "subject_id": 1, "status": 1, "created_at": 1},
        )
        .sort([("status", -1), ("created_at", -1)])
        .skip(skip)
        .limit(limit)
    )
    items = await cursor.to_list(limit)
    total = await db.topics.count_documents({"definition_status": DEFINITION_STATUS_MISSING})
    return {"items": items, "total": total, "limit": limit, "skip": skip}


@router.post("/admin/topics/backfill-slugs")
async def admin_topic_backfill_slugs(
    dry_run: bool = Query(False, description="Report what would change without writing."),
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    counters = await run_backfill(dry_run=dry_run)
    return {"dry_run": dry_run, "counters": counters}
