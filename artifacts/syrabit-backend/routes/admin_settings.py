"""Syrabit.ai — Admin settings, roadmap, activity log"""
import uuid, logging
from datetime import datetime, timezone
from fastapi import (
    APIRouter, HTTPException, Depends,
)

from models import (
    SettingsUpdate, RoadmapItemCreate,
)
from deps import db
from auth_deps import (
    get_admin_user,
)
from db_ops import (
    supa_clear_activity_log,
    supa_get_activity_logs,
    supa_get_settings,
    supa_insert_activity_log,
    supa_update_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────
@router.get("/admin/settings")
async def admin_get_settings(admin: dict = Depends(get_admin_user)):
    settings = await supa_get_settings()
    if not settings:
        settings = {"registrations_open": True, "maintenance_mode": False, "app_name": "Syrabit.ai", "tagline": "AI-Powered AHSEC Exam Prep", "crawl_coverage_red": 30, "crawl_coverage_yellow": 50, "bot_missing_days": 3}
    settings.setdefault("crawl_coverage_red", 30)
    settings.setdefault("crawl_coverage_yellow", 50)
    settings.setdefault("bot_missing_days", 3)
    return settings

@router.patch("/admin/settings")
async def admin_update_settings(data: SettingsUpdate, admin: dict = Depends(get_admin_user)):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "crawl_coverage_red" in update or "crawl_coverage_yellow" in update:
        current = await supa_get_settings() or {}
        red = update.get("crawl_coverage_red", current.get("crawl_coverage_red", 30))
        yellow = update.get("crawl_coverage_yellow", current.get("crawl_coverage_yellow", 50))
        if red >= yellow:
            raise HTTPException(
                status_code=400,
                detail=f"crawl_coverage_red ({red}) must be strictly less than crawl_coverage_yellow ({yellow})",
            )
    if update:
        await supa_update_settings(update)
    return {"message": "Settings updated"}

@router.get("/settings")
async def get_public_settings():
    settings = await supa_get_settings()
    if not settings:
        settings = {"registrations_open": True, "maintenance_mode": False, "app_name": "Syrabit.ai", "tagline": "AI-Powered AHSEC Exam Prep"}
    settings.pop("crawl_coverage_red", None)
    settings.pop("crawl_coverage_yellow", None)
    settings.pop("bot_missing_days", None)
    return settings

# ─────────────────────────────────────────────
# ROADMAP
# ─────────────────────────────────────────────
@router.get("/admin/roadmap")
async def admin_get_roadmap(admin: dict = Depends(get_admin_user)):
    items = await db.roadmap.find({}, {"_id": 0}).to_list(100)
    return items

@router.post("/admin/roadmap")
async def admin_create_roadmap_item(data: RoadmapItemCreate, admin: dict = Depends(get_admin_user)):
    item = {
        "id": str(uuid.uuid4()),
        "title": data.title,
        "description": data.description,
        "status": data.status,
        "priority": data.priority,
        "category": data.category,
        "phase": data.phase,
        "effort": data.effort,
        "impact": data.impact,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.roadmap.insert_one(item)
    return {k: v for k, v in item.items() if k != "_id"}

@router.patch("/admin/roadmap/{item_id}")
async def admin_update_roadmap_item(item_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    update = {k: v for k, v in data.items() if k in ("title", "description", "status", "priority", "category", "phase", "effort", "impact")}
    if not update:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.roadmap.update_one({"id": item_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Updated"}

@router.delete("/admin/roadmap/{item_id}")
async def admin_delete_roadmap_item(item_id: str, admin: dict = Depends(get_admin_user)):
    result = await db.roadmap.delete_one({"id": item_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Deleted"}

# ─────────────────────────────────────────────
# ACTIVITY LOG
# ─────────────────────────────────────────────
@router.get("/admin/activity-log")
async def admin_get_activity_log(admin: dict = Depends(get_admin_user)):
    logs = await supa_get_activity_logs()
    return {"logs": logs, "total": len(logs)}

@router.post("/admin/activity-log")
async def admin_log_activity(data: dict, admin: dict = Depends(get_admin_user)):
    entry = {
        "id": str(uuid.uuid4()),
        "action": data.get("action", "unknown"),
        "details": data.get("details", ""),
        "level": data.get("level", "info"),
        "admin_name": admin.get("name", "Admin"),
        "admin_email": admin.get("email", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await supa_insert_activity_log(entry)
    return {"message": "Logged"}

@router.delete("/admin/activity-log")
async def admin_clear_activity_log(admin: dict = Depends(get_admin_user)):
    await supa_clear_activity_log()
    return {"message": "Activity log cleared"}

# ─────────────────────────────────────────────
# ALERT DELIVERY TEST (Task #418)
# ─────────────────────────────────────────────
@router.post("/admin/alert-settings/test-delivery")
async def admin_test_alert_delivery(admin: dict = Depends(get_admin_user)):
    """Post a synthetic ``hydrate_failure_spike`` alert through every
    configured delivery channel and report per-channel success/failure so
    admins can confirm their Slack/email/push integrations actually work
    without waiting for a real incident.

    The synthetic alert is tagged with ``synthetic: True`` on the persisted
    document and push payload so it can be filtered out of the normal alert
    feed. Cooldown is bypassed (``force=True``) so admins can re-test on
    demand.
    """
    import metrics as _metrics_mod
    await _metrics_mod._load_alert_settings()
    snapshot = {
        "metric": "hydrate_failure_spike",
        "value": 10,
        "actual": 42,
        "top_kind": "syllabus_chunk",
        "auto_reload_attempts": 12,
        "auto_reload_recoveries": 3,
        "synthetic": True,
    }
    outcomes = await _metrics_mod._dispatch_alert(
        "hydrate_failure_spike",
        "[TEST] Synthetic stale-build alert",
        f"This is a synthetic test triggered by {admin.get('email', 'admin')} from the Alert Settings page. "
        "If you see this, your alert delivery is wired up correctly.",
        threshold_snapshot=snapshot,
        force=True,
        mark_synthetic=True,
    )
    return {
        "ok": True,
        "alert_type": "hydrate_failure_spike",
        "outcomes": outcomes,
        "channel_status": {k: dict(v) for k, v in _metrics_mod._channel_status.items()},
    }


# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────
