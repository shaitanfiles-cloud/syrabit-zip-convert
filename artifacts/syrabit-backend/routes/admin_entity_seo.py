"""Task #940 — admin routes for the Entity SEO + Knowledge Graph health
panel.

Three endpoints, all admin-auth:

  GET  /admin/seo/entity/status     — latest snapshot + drift + missing
                                      claims (panel main payload)
  GET  /admin/seo/entity/history    — recent snapshots for the WoW
                                      sparkline / debugger
  POST /admin/seo/entity/refresh    — manual trigger; bypasses the
                                      Mon 04:30 window so an admin can
                                      re-probe after filing a Wikidata
                                      claim

Response shape is camelCase to match the rest of the admin API. Each
snapshot is `_id`-stripped so it serialises cleanly through Pydantic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth_deps import get_admin_user
from deps import db, is_mongo_available

import entity_seo_health as esh

logger = logging.getLogger(__name__)
router = APIRouter()


def _strip(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    # Mongo datetimes need ISO conversion so axios receives strings.
    gen = doc.get("generated_at")
    if isinstance(gen, datetime):
        doc["generated_at"] = gen.astimezone(timezone.utc).isoformat()
    return doc


def _build_status_payload(latest: Optional[Dict[str, Any]],
                          previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Shape the panel's main payload from raw snapshots."""
    if not latest:
        # Empty-state — surface the canonical "what we'd track" lists so
        # an admin can start filing claims / pitching mentions even
        # before the first weekly snapshot has run.
        return {
            "configured": True,
            "snapshot": None,
            "previous": None,
            "drift": {"hadBaseline": False, "regressions": [],
                      "improvements": [], "summaryDeltas": {}},
            "missingClaims": [
                {**c, "edit_url": esh.wikidata_edit_url("", c["prop"])}
                for c in esh.DESIRED_WIKIDATA_CLAIMS
            ],
            "missingMentions": [
                {**t, "status": "missing", "mentioned": False,
                 "summary": "Pending first weekly probe."}
                for t in esh.MENTION_OPPORTUNITY_TARGETS
            ],
            "alertState": None,
        }
    drift = latest.get("drift") or esh.compute_drift(previous, latest)
    return {
        "configured": True,
        "snapshot": _strip(latest),
        "previous": _strip(previous),
        "drift": {
            "hadBaseline": drift.get("had_baseline", bool(previous)),
            "regressions": drift.get("regressions") or [],
            "improvements": drift.get("improvements") or [],
            "summaryDeltas": drift.get("summary_deltas") or {},
        },
        "missingClaims": list(latest.get("missing_claims") or []),
        "missingMentions": list(latest.get("missing_mentions") or []),
    }


async def _load_latest_pair() -> tuple:
    """Return (latest, previous) snapshots, or (None, None) if absent."""
    coll = db[esh.ENTITY_SEO_COLLECTION]
    docs = await coll.find({}).sort("generated_at", -1).limit(2).to_list(2)
    latest = docs[0] if docs else None
    previous = docs[1] if len(docs) > 1 else None
    return latest, previous


@router.get("/admin/seo/entity/status")
async def entity_seo_status(_admin: dict = Depends(get_admin_user)):
    """Return the latest entity SEO snapshot, its diff vs the prior week,
    and the list of missing Wikidata claims to file."""
    if not await is_mongo_available():
        raise HTTPException(status_code=503,
                            detail="Database unavailable")
    latest, previous = await _load_latest_pair()
    payload = _build_status_payload(latest, previous)

    # Surface alerter lock-doc state so the panel can show a "last
    # paged Xh ago" caption like the cron pills do.
    try:
        lock = await db.job_locks.find_one({"_id": esh._ALERT_LOCK_ID}) or {}
    except Exception:
        lock = {}
    if lock:
        last_at = lock.get("last_paged_at")
        if isinstance(last_at, datetime):
            last_at = last_at.astimezone(timezone.utc).isoformat()
        payload["alertState"] = {
            "lastPagedAt": last_at,
            "fingerprint": lock.get("fingerprint"),
            "regressionCount": lock.get("regression_count", 0),
        }
    return payload


@router.get("/admin/seo/entity/history")
async def entity_seo_history(
    limit: int = Query(20, ge=1, le=200),
    _admin: dict = Depends(get_admin_user),
):
    """Return the most recent N snapshots for the WoW chart."""
    if not await is_mongo_available():
        raise HTTPException(status_code=503,
                            detail="Database unavailable")
    coll = db[esh.ENTITY_SEO_COLLECTION]
    docs = await coll.find({}).sort("generated_at", -1).limit(int(limit)).to_list(int(limit))
    items: List[Dict[str, Any]] = []
    for d in docs:
        d = _strip(d)
        if not d:
            continue
        items.append({
            "isoWeek": d.get("iso_week"),
            "generatedAt": d.get("generated_at"),
            "aggregateStatus": d.get("aggregate_status"),
            "summary": d.get("summary") or {},
            "regressionCount": len((d.get("drift") or {}).get("regressions") or []),
        })
    return {"items": items}


@router.post("/admin/seo/entity/refresh")
async def entity_seo_refresh(_admin: dict = Depends(get_admin_user)):
    """Manually re-run the collectors and persist a fresh snapshot.

    Bypasses the Mon 04:30 ±15 min schedule gate (admin-explicit); the
    underlying ``_try_run_entity_seo_once(... force=True)`` still
    persists into the same ``entity_seo_health`` collection (keyed by
    ISO week) so a same-day re-trigger updates the existing doc rather
    than appending a duplicate.
    """
    if not await is_mongo_available():
        raise HTTPException(status_code=503,
                            detail="Database unavailable")
    now_utc = datetime.now(timezone.utc)
    result = await esh._try_run_entity_seo_once(db, now_utc, force=True)
    latest, previous = await _load_latest_pair()
    payload = _build_status_payload(latest, previous)
    payload["refresh"] = result
    return payload
