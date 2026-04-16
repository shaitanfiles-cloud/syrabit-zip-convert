"""Syrabit.ai — Admin notifications, push, exam schedule, export, rate policies"""
import re, json, asyncio, time, uuid, logging, hashlib, io, csv, os, base64, html as _html_mod
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timezone, timedelta
from fastapi import (
    APIRouter, HTTPException, Depends, Query, Body, Path,
    File, UploadFile, Response, Request, Cookie, BackgroundTasks,
    Form, Header, status,
)
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr
import mistune as _mistune

from models import (
    UserCreate, UserLogin, UserOut, TokenOut, OnboardingData, ChatMessage,
    ConversationCreate, AdminLoginReq, SubjectCreate, ChapterCreate, ChunkCreate,
    DocumentUpload, ProfileUpdate, PasswordResetReq, PasswordResetConfirm,
    UserStatusUpdate, UserPlanUpdate, UserCreditsUpdate, SettingsUpdate, RoadmapItemCreate,
    LibraryBundleOut, ChatResponseOut, SearchResultOut, HealthOut, ReadyOut, ErrorOut,
)
from config import *
from deps import *
from cache import *
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional,
)
from db_ops import *
from llm import call_llm_api, call_llm_api_stream
from rag import *
from utils import *
from analytics_helpers import *

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/admin/notifications")
async def admin_get_notifications(admin: dict = Depends(get_admin_user)):
    notifs = await supa_get_notifications()
    return notifs

@router.post("/admin/notifications")
async def admin_create_notification(data: dict, admin: dict = Depends(get_admin_user)):
    notif = {
        "id": str(uuid.uuid4()),
        "title": data.get("title", ""),
        "message": data.get("message", ""),
        "type": data.get("type", "info"),
        "channel": data.get("channel", "push"),
        "audience": data.get("audience", "all"),
        "status": data.get("status", "draft"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sent_at": datetime.now(timezone.utc).isoformat() if data.get("status") == "sent" else None,
    }
    await supa_insert_notification(notif)
    # Dispatch web-push immediately when status is "sent"
    if notif["status"] == "sent" and notif.get("channel", "push") == "push":
        asyncio.create_task(_dispatch_push_to_all({
            "title": notif["title"],
            "body":  notif["message"],
            "url":   data.get("url", "/"),
        }))
    return notif

@router.delete("/admin/notifications/{notif_id}")
async def admin_delete_notification(notif_id: str, admin: dict = Depends(get_admin_user)):
    await supa_delete_notification(notif_id)
    return {"message": "Deleted"}


# ─────────────────────────────────────────────
# PUSH NOTIFICATIONS — VAPID + Subscriptions
# ─────────────────────────────────────────────

async def _get_or_create_vapid_keys() -> dict:
    """Return VAPID key pair from db.api_config, generating once if absent."""
    cfg = await db.api_config.find_one({}, {"push_vapid": 1})
    existing = (cfg or {}).get("push_vapid", {})
    if existing.get("public_key") and existing.get("private_key_pem"):
        return existing
    try:
        from py_vapid import Vapid
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PrivateFormat, PublicFormat, NoEncryption
        )
        v = Vapid()
        v.generate_keys()
        private_pem = v.private_key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        ).decode()
        # Public key as uncompressed EC point, urlsafe-base64 (what browsers expect)
        pub_raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()
        keys = {"public_key": pub_b64, "private_key_pem": private_pem}
        await db.api_config.update_one({}, {"$set": {"push_vapid": keys}}, upsert=True)
        logger.info("VAPID keys generated and stored in db.api_config")
        return keys
    except Exception as e:
        logger.error(f"VAPID key generation failed: {e}")
        return {}


async def _dispatch_push_to_all(payload: dict):
    """Send a web-push to every stored subscription. Fire-and-forget."""
    await _dispatch_push(payload, admin_only=False)


async def _dispatch_push_to_admins(payload: dict):
    """Send a web-push only to admin-user subscriptions. Fire-and-forget.
    Respects per-admin notification preferences (push_enabled, push_severities)."""
    await _dispatch_push(payload, admin_only=True)


async def _dispatch_push(payload: dict, admin_only: bool = False):
    """Core push dispatcher. When admin_only=True, sends only to subscriptions
    belonging to users with is_admin=True, filtered by per-admin notification prefs."""
    try:
        from pywebpush import webpush, WebPushException
        vapid = await _get_or_create_vapid_keys()
        private_pem = vapid.get("private_key_pem", "")
        if not private_pem:
            logger.warning("Push dispatch skipped — VAPID private key missing")
            return
        if admin_only:
            admin_docs = await db.users.find(
                {"is_admin": True}, {"_id": 0, "id": 1, "email": 1}
            ).to_list(500)
            admin_ids = {str(d["id"]) for d in admin_docs if d.get("id")}
            if not admin_ids:
                logger.info("Push dispatch (admin-only): no admin users found, skipping")
                return

            id_to_email = {}
            for d in admin_docs:
                uid = str(d.get("id", ""))
                email = str(d.get("email", "")).lower().strip()
                if uid and email:
                    id_to_email[uid] = email

            alert_type = payload.get("alert_type", "")
            admin_prefs_map = {}
            try:
                all_admin_keys = list(admin_ids | set(id_to_email.values()))
                prefs_cursor = db.admin_notification_prefs.find(
                    {"admin_id": {"$in": all_admin_keys}}, {"_id": 0}
                )
                async for pref_doc in prefs_cursor:
                    admin_prefs_map[pref_doc["admin_id"]] = pref_doc
            except Exception as exc:
                logger.debug(f"Failed to load admin notification prefs for push filter: {exc}")

            eligible_admin_ids = set()
            for aid in admin_ids:
                email_key = id_to_email.get(aid, "")
                prefs = admin_prefs_map.get(aid) or admin_prefs_map.get(email_key, {})
                push_enabled = prefs.get("push_enabled", _ADMIN_NOTIF_PREFS_DEFAULTS.get("push_enabled", False))
                push_severities = prefs.get("push_severities", _ADMIN_NOTIF_PREFS_DEFAULTS.get("push_severities", []))
                if not push_enabled:
                    continue
                if alert_type and alert_type not in push_severities:
                    continue
                eligible_admin_ids.add(aid)

            if not eligible_admin_ids:
                logger.info("Push dispatch (admin-only): no admins with push enabled for this alert type, skipping")
                return

            subs = await db.push_subscriptions.find(
                {"user_id": {"$in": list(eligible_admin_ids)}}, {"_id": 0}
            ).to_list(10000)
        else:
            subs = await db.push_subscriptions.find({}, {"_id": 0}).to_list(10000)
        sent = failed = 0
        for sub in subs:
            try:
                webpush(
                    subscription_info=sub["subscription_info"],
                    data=json.dumps(payload),
                    vapid_private_key=private_pem,
                    vapid_claims={"sub": "mailto:admin@syrabit.ai"},
                )
                sent += 1
            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    await db.push_subscriptions.delete_one({"endpoint": sub.get("endpoint")})
                failed += 1
            except Exception:
                failed += 1
        label = "admin-only" if admin_only else "all"
        logger.info(f"Push dispatch ({label}): sent={sent} failed={failed} total={len(subs)}")
    except Exception as e:
        logger.error(f"Push dispatch error: {e}")


@router.get("/push/vapid-public-key")
async def push_vapid_public_key():
    """Return the VAPID public key so the browser can subscribe."""
    keys = await _get_or_create_vapid_keys()
    pub = keys.get("public_key", "")
    if not pub:
        raise HTTPException(503, "Push not configured — VAPID key generation failed")
    return {"public_key": pub}


@router.post("/push/subscribe")
async def push_subscribe(data: dict, user: dict = Depends(get_current_user)):
    """Store a browser push subscription for the authenticated user."""
    subscription_info = data.get("subscription")
    if not subscription_info or not subscription_info.get("endpoint"):
        raise HTTPException(400, "Missing subscription object")
    endpoint = subscription_info["endpoint"]
    doc = {
        "user_id":           str(user["id"]),
        "endpoint":          endpoint,
        "subscription_info": subscription_info,
        "subscribed_at":     datetime.now(timezone.utc).isoformat(),
    }
    await db.push_subscriptions.update_one(
        {"endpoint": endpoint}, {"$set": doc}, upsert=True
    )
    return {"ok": True}


@router.delete("/push/subscribe")
async def push_unsubscribe(data: dict, user: dict = Depends(get_current_user)):
    """Remove a push subscription for the authenticated user."""
    endpoint = (data or {}).get("endpoint", "")
    if endpoint:
        await db.push_subscriptions.delete_one({"endpoint": endpoint, "user_id": str(user["id"])})
    return {"ok": True}


# ─────────────────────────────────────────────
# EXAM REMINDER LOOP + ADMIN SCHEDULE
# ─────────────────────────────────────────────

async def _exam_reminder_loop():
    """
    Runs every 6 hours. Queries db.exam_schedule for exams 1 day, 3 days, or
    on the date of the exam (IST), then dispatches push notifications.
    Wakes every 6 hours so it never misses a window even after restart.
    """
    import zoneinfo
    from datetime import timedelta as _td
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
    await asyncio.sleep(30)   # let startup settle
    while True:
        try:
            now_ist   = datetime.now(IST)
            today_str = now_ist.date().isoformat()

            targets = {
                "today":      today_str,
                "1_day_away": (now_ist.date() + _td(days=1)).isoformat(),
                "3_day_away": (now_ist.date() + _td(days=3)).isoformat(),
            }

            exams = await db.exam_schedule.find(
                {"exam_date": {"$in": list(targets.values())}, "active": True},
                {"_id": 1, "board": 1, "class_name": 1, "subject": 1, "exam_date": 1, "notified_for": 1}
            ).to_list(200)

            for exam in exams:
                eid      = str(exam["_id"])
                board    = exam.get("board", "")
                subject  = exam.get("subject", "")
                klass    = exam.get("class_name", "")
                edate    = exam.get("exam_date", "")
                notified = set(exam.get("notified_for", []))

                trigger = None
                for label, dstr in targets.items():
                    if dstr == edate and label not in notified:
                        trigger = label
                        break

                if trigger is None:
                    continue

                if trigger == "today":
                    title = f"📋 {subject} exam is TODAY"
                    body  = f"{board} Class {klass} — Best of luck! You've got this."
                elif trigger == "1_day_away":
                    title = f"⏰ {subject} exam tomorrow"
                    body  = f"{board} Class {klass} — Quick revision time!"
                else:
                    title = f"📅 {subject} exam in 3 days"
                    body  = f"{board} Class {klass} — Keep revising!"

                asyncio.create_task(_dispatch_push_to_all({
                    "title": title,
                    "body":  body,
                    "icon":  "/icons/icon-192.png",
                    "url":   "/library",
                    "tag":   f"exam-{eid}-{trigger}",
                }))
                logger.info(f"Exam reminder dispatched: {subject} ({trigger})")

                await db.exam_schedule.update_one(
                    {"_id": exam["_id"]},
                    {"$addToSet": {"notified_for": trigger}}
                )

        except Exception as exc:
            logger.error(f"Exam reminder loop error: {exc}")

        await asyncio.sleep(6 * 3600)   # check every 6 hours


@router.get("/admin/exam-schedule")
async def admin_exam_schedule_list(admin: dict = Depends(get_admin_user)):
    """List all exam dates in the schedule."""
    items = await db.exam_schedule.find(
        {}, {"_id": 1, "board": 1, "class_name": 1, "subject": 1, "exam_date": 1, "active": 1, "notified_for": 1, "created_at": 1}
    ).sort("exam_date", 1).to_list(500)
    for i in items:
        i["id"] = str(i.pop("_id"))
    return {"exams": items}


@router.post("/admin/exam-schedule")
async def admin_exam_schedule_add(data: dict, admin: dict = Depends(get_admin_user)):
    """Add an exam date. Body: { board, class_name, subject, exam_date (YYYY-MM-DD) }"""
    board   = (data.get("board") or "").strip()
    klass   = (data.get("class_name") or "").strip()
    subject = (data.get("subject") or "").strip()
    edate   = (data.get("exam_date") or "").strip()
    if not all([board, klass, subject, edate]):
        raise HTTPException(400, "board, class_name, subject, and exam_date are required")
    try:
        datetime.strptime(edate, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "exam_date must be YYYY-MM-DD")
    doc = {
        "board":        board,
        "class_name":   klass,
        "subject":      subject,
        "exam_date":    edate,
        "active":       data.get("active", True),
        "notified_for": [],
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }
    result = await db.exam_schedule.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "Exam date added"}


@router.delete("/admin/exam-schedule/{exam_id}")
async def admin_exam_schedule_delete(exam_id: str, admin: dict = Depends(get_admin_user)):
    """Delete an exam date entry."""
    from bson import ObjectId as _ObjId
    try:
        oid = _ObjId(exam_id)
    except Exception:
        raise HTTPException(400, "Invalid exam_id")
    result = await db.exam_schedule.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Exam not found")
    return {"ok": True}


@router.patch("/admin/exam-schedule/{exam_id}")
async def admin_exam_schedule_toggle(exam_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    """Toggle active flag or reset notification history for an exam entry."""
    from bson import ObjectId as _ObjId
    try:
        oid = _ObjId(exam_id)
    except Exception:
        raise HTTPException(400, "Invalid exam_id")
    update = {}
    if "active" in data:
        update["active"] = bool(data["active"])
    if data.get("reset_notifications"):
        update["notified_for"] = []
    if not update:
        raise HTTPException(400, "Nothing to update")
    await db.exam_schedule.update_one({"_id": oid}, {"$set": update})
    return {"ok": True}


# ─────────────────────────────────────────────
# ADMIN EXPORT — CSV/JSON
# ─────────────────────────────────────────────
import csv
import io as _io

@router.get("/admin/export/users")
async def admin_export_users(format: str = "json", admin: dict = Depends(get_admin_user)):
    users = await supa_list_users()
    if format == "csv":
        if not users:
            return Response(content="", media_type="text/csv")
        output = _io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[k for k in users[0].keys() if k != "password_hash"])
        writer.writeheader()
        for u in users:
            row = {k: v for k, v in u.items() if k != "password_hash"}
            writer.writerow(row)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users_export.csv"},
        )
    return [({k: v for k, v in u.items() if k != "password_hash"}) for u in users]

@router.get("/admin/export/analytics")
async def admin_export_analytics(format: str = "json", days: int = 30, admin: dict = Depends(get_admin_user)):
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    docs = await db.analytics.find({"timestamp": {"$gte": start}}, {"_id": 0}).sort("timestamp", -1).to_list(10000)
    if format == "csv" and docs:
        output = _io.StringIO()
        all_keys = sorted(set().union(*(d.keys() for d in docs)))
        writer = csv.DictWriter(output, fieldnames=all_keys)
        writer.writeheader()
        for d in docs:
            writer.writerow({k: d.get(k, "") for k in all_keys})
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=analytics_export.csv"},
        )
    return docs

@router.get("/admin/export/conversations")
async def admin_export_conversations(format: str = "json", limit: int = 500, admin: dict = Depends(get_admin_user)):
    convs = await supa_get_all_conversations(limit)
    if format == "csv" and convs:
        output = _io.StringIO()
        keys = ["id", "user_id", "title", "subject_name", "created_at", "updated_at", "preview"]
        writer = csv.DictWriter(output, fieldnames=keys)
        writer.writeheader()
        for c in convs:
            writer.writerow({k: c.get(k, "") for k in keys})
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=conversations_export.csv"},
        )
    return convs


# ─────────────────────────────────────────────
# BULK SEO GENERATION PROGRESS TRACKING
# ─────────────────────────────────────────────
_seo_generation_progress: Dict[str, dict] = {}

@router.get("/admin/seo/generation-progress")
async def seo_generation_progress(admin: dict = Depends(get_admin_user)):
    return _seo_generation_progress

@router.get("/admin/seo/generation-progress/{job_id}")
async def seo_generation_progress_detail(job_id: str, admin: dict = Depends(get_admin_user)):
    if job_id not in _seo_generation_progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return _seo_generation_progress[job_id]


# ─────────────────────────────────────────────
# RATE LIMIT POLICIES
# ─────────────────────────────────────────────
DEFAULT_RATE_POLICIES = {
    "free":       {"req_per_min": 5,  "credits_per_day": 30,   "max_tokens": 10000,  "req_per_min_ip": 20},
    "starter":    {"req_per_min": 10, "credits_per_day": 500,  "max_tokens": 15000,  "req_per_min_ip": 30},
    "pro":        {"req_per_min": 15, "credits_per_day": 4000, "max_tokens": 20000,  "req_per_min_ip": 40},
    "enterprise": {"req_per_min": 60, "credits_per_day": 99999,"max_tokens": 200000, "req_per_min_ip": 200},
}

@router.get("/admin/rate-policies")
async def admin_get_rate_policies(admin: dict = Depends(get_admin_user)):
    saved = await db.rate_policies.find_one({}, {"_id": 0})
    return saved if saved else DEFAULT_RATE_POLICIES

@router.put("/admin/rate-policies")
async def admin_update_rate_policies(data: dict, admin: dict = Depends(get_admin_user)):
    await db.rate_policies.replace_one({}, data, upsert=True)
    return {"message": "Rate policies updated"}

@router.get("/admin/rate-stats")
async def admin_get_rate_stats(admin: dict = Depends(get_admin_user)):
    total_users = await supa_count_users()
    users = await supa_list_users()
    total_tokens = sum(u.get("credits_used", 0) * 300 for u in users)
    return {
        "active_requests": 0,
        "tokens_today": total_tokens,
        "daily_budget": 2_000_000,
        "cost_degraded": False,
    }


@router.get("/admin/notification-prefs")
async def admin_get_notification_prefs(admin: dict = Depends(get_admin_user)):
    admin_id = admin.get("sub") or admin.get("email") or "default"
    prefs = await get_admin_notification_prefs(admin_id)
    return prefs


@router.put("/admin/notification-prefs")
async def admin_update_notification_prefs(
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    admin_id = admin.get("sub") or admin.get("email") or "default"
    prefs = await upsert_admin_notification_prefs(admin_id, data)
    return prefs


@router.get("/admin/alert-settings")
async def admin_get_alert_settings(admin: dict = Depends(get_admin_user)):
    import metrics as _metrics_mod
    try:
        await _metrics_mod._load_alert_settings()
        return {
            "thresholds": {k: _metrics_mod._ALERT_THRESHOLDS.get(k, v) for k, v in _metrics_mod._ALERT_THRESHOLDS_DEFAULT.items()},
            "expiration": {k: _metrics_mod._alert_expiration.get(k, v) for k, v in _metrics_mod._ALERT_EXPIRATION_DEFAULT.items()},
            "notification_channels": {k: _metrics_mod._notification_channels.get(k, v) for k, v in _metrics_mod._NOTIFICATION_CHANNELS_DEFAULT.items()},
            "defaults": {
                "thresholds": _metrics_mod._ALERT_THRESHOLDS_DEFAULT,
                "expiration": _metrics_mod._ALERT_EXPIRATION_DEFAULT,
                "notification_channels": _metrics_mod._NOTIFICATION_CHANNELS_DEFAULT,
            },
        }
    except Exception as exc:
        logger.error(f"Failed to get alert settings: {exc}")
        raise HTTPException(status_code=500, detail="Failed to get alert settings")


@router.put("/admin/alert-settings")
async def admin_update_alert_settings(
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    import metrics as _metrics_mod
    thresholds = data.get("thresholds", {})
    expiration = data.get("expiration", {})
    notification_channels = data.get("notification_channels", {})
    validated_thresholds = {}
    _ZERO_ALLOWED_THRESHOLDS = {"auto_block_threshold"}
    for k, default_val in _metrics_mod._ALERT_THRESHOLDS_DEFAULT.items():
        if k in thresholds:
            try:
                val = float(thresholds[k])
                if k in _ZERO_ALLOWED_THRESHOLDS:
                    if val < 0:
                        raise ValueError("Must be zero or positive")
                else:
                    if val <= 0:
                        raise ValueError("Must be positive")
                validated_thresholds[k] = val
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail=f"Invalid value for threshold '{k}'")
    validated_expiration = {}
    if "enabled" in expiration:
        if not isinstance(expiration["enabled"], bool):
            raise HTTPException(status_code=400, detail="expiration.enabled must be a boolean")
        validated_expiration["enabled"] = expiration["enabled"]
    if "days" in expiration:
        try:
            days = int(expiration["days"])
            if days < 1 or days > 365:
                raise ValueError("Days must be 1-365")
            validated_expiration["days"] = days
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid value for expiration days (must be 1-365)")
    validated_channels = {}
    if "email" in notification_channels:
        email_val = str(notification_channels["email"]).strip()
        if email_val and "@" not in email_val:
            raise HTTPException(status_code=400, detail="Invalid email address for notification channel")
        validated_channels["email"] = email_val
    if "webhook_url" in notification_channels:
        wh_val = str(notification_channels["webhook_url"]).strip()
        if wh_val and not wh_val.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Webhook URL must start with http:// or https://")
        validated_channels["webhook_url"] = wh_val
    try:
        existing = await db.api_config.find_one({}, {"_id": 0})
        if existing is None:
            existing = {}
        existing["alert_settings"] = {
            "thresholds": validated_thresholds,
            "expiration": validated_expiration,
            "notification_channels": validated_channels,
        }
        await db.api_config.replace_one({}, existing, upsert=True)
        await _metrics_mod._load_alert_settings()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update alert settings: {exc}")
        raise HTTPException(status_code=500, detail="Failed to update alert settings")


@router.get("/admin/alerts")
async def admin_get_alerts(
    limit: int = Query(50, ge=1, le=200),
    acknowledged: Optional[bool] = Query(None),
    admin: dict = Depends(get_admin_user),
):
    try:
        query: Dict[str, Any] = {}
        if acknowledged is not None:
            query["acknowledged"] = acknowledged
        cursor = db.alerts.find(query).sort("fired_at", -1).limit(limit)
        alerts = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            alerts.append(doc)
        return {"alerts": alerts, "total": len(alerts)}
    except Exception as exc:
        logger.error(f"Failed to fetch alerts: {exc}")
        raise HTTPException(status_code=500, detail="Failed to fetch alerts")


@router.patch("/admin/alerts/{alert_id}/acknowledge")
async def admin_acknowledge_alert(
    alert_id: str,
    admin: dict = Depends(get_admin_user),
):
    from bson import ObjectId as _ObjId
    try:
        oid = _ObjId(alert_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid alert ID")
    result = await db.alerts.update_one(
        {"_id": oid},
        {"$set": {"acknowledged": True, "acknowledged_at": datetime.now(timezone.utc).isoformat(), "acknowledged_by": admin.get("email", "admin")}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@router.patch("/admin/alerts/acknowledge-all")
async def admin_acknowledge_all_alerts(
    admin: dict = Depends(get_admin_user),
):
    result = await db.alerts.update_many(
        {"acknowledged": False},
        {"$set": {"acknowledged": True, "acknowledged_at": datetime.now(timezone.utc).isoformat(), "acknowledged_by": admin.get("email", "admin")}},
    )
    return {"ok": True, "modified": result.modified_count}

