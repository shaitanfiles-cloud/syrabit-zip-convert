"""Syrabit.ai — Analytics tracking routes"""
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
from starlette.requests import Request as StarletteRequest
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
import cloudflare_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/admin/analytics/cf-status")
async def admin_cf_status(admin: dict = Depends(get_admin_user)):
    """Surface Cloudflare Analytics token health for the admin UI banner.

    Returns:
      configured: env vars present?
      auth_ok: True/False/None (None = not yet probed since startup)
      needs_rotation: True when token is rejected by Cloudflare
      last_error, last_check_at, blocked_for_seconds, rotation_hint
    """
    # If we've never tried, probe once now so the UI gets a definitive answer.
    status_obj = cloudflare_client.get_auth_status()
    if status_obj.get("auth_ok") is None and status_obj.get("configured"):
        await cloudflare_client.get_visitor_stats_cf(days=1)
        status_obj = cloudflare_client.get_auth_status()
    return status_obj


@router.post("/admin/analytics/cf-recheck")
async def admin_cf_recheck(admin: dict = Depends(get_admin_user)):
    """Reset the auth circuit breaker and re-probe Cloudflare immediately.
    Call this after rotating CF_ANALYTICS_API_TOKEN on Railway."""
    cloudflare_client.reset_auth_state()
    if cloudflare_client.is_configured():
        await cloudflare_client.get_visitor_stats_cf(days=1)
    return cloudflare_client.get_auth_status()


@router.get("/admin/analytics")
async def admin_analytics(days: int = 30, admin: dict = Depends(get_admin_user)):
    """Admin analytics — Cloudflare is the sole source of truth for
    visitor/page-view numbers. GA4/server-side/JS-tracked merge logic
    has been removed (Task #364)."""
    users = await supa_list_users()

    signup_range = min(days, 90)
    daily_signups = []
    for i in range(signup_range):
        day = (datetime.now(timezone.utc) - timedelta(days=signup_range-1-i)).strftime("%Y-%m-%d")
        count = sum(1 for u in users if u.get("created_at", "")[:10] == day)
        daily_signups.append({"date": day, "count": count})

    plan_usage = {}
    for u in users:
        p = u.get("plan", "free")
        plan_usage[p] = plan_usage.get(p, 0) + u.get("credits_used", 0)

    fetch_days = min(days, 90)
    cf_vs, cf_pages_res, library_stats = await asyncio.gather(
        cloudflare_client.get_visitor_stats_cf(days=fetch_days),
        cloudflare_client.get_top_pages_cf(),
        get_library_analytics(days=days),
        return_exceptions=True,
    )

    cf_data = cf_vs if isinstance(cf_vs, dict) and cf_vs else None
    cf_connected = cf_data is not None and any(
        k in cf_data for k in ("total_visitors", "visitors_today", "page_views_today", "daily_visitors")
    )
    ga4_connected = bool(os.getenv("GA4_REFRESH_TOKEN"))

    visitor_stats: dict = {}
    if cf_connected:
        cloudflare_block = {
            "total_visitors": cf_data.get("total_visitors", 0),
            "visitors_today": cf_data.get("visitors_today", 0),
            "page_views_today": cf_data.get("page_views_today", 0),
            "total_page_views": cf_data.get("total_page_views", 0),
            "total_requests": cf_data.get("total_requests", 0),
            "daily_visitors": cf_data.get("daily_visitors", []),
        }
        visitor_stats = {
            **cloudflare_block,
            "cloudflare": cloudflare_block,
        }

    top_pages = cf_pages_res if isinstance(cf_pages_res, list) else []
    top_referrers: list = []  # CF GraphQL free tier does not expose referrer dimension

    return {
        "daily_signups": daily_signups,
        "plan_usage": plan_usage,
        "library": library_stats if isinstance(library_stats, dict) else {},
        "total_users": len(users),
        "active_users": sum(1 for u in users if u.get("credits_used", 0) > 0),
        "visitor_stats": visitor_stats,
        "top_pages": top_pages,
        "top_referrers": top_referrers,
        "ga4_connected": ga4_connected,
        "cf_connected": cf_connected,
    }


@router.post("/analytics/page-view")
async def track_page_view_endpoint(
    request: StarletteRequest,
    path: str = Body(...),
    visitor_id: str = Body(...),
    referrer: str = Body(None),
    session_id: str = Body(None),
    user_agent: str = Body(None),
    screen_width: int = Body(None),
    is_404_hint: bool = Body(None),
    user: dict = Depends(get_current_user_optional)
):
    """
    Public endpoint to track a page view.
    Called from frontend on every route change.
    """
    user_id = user.get("id") if user else None
    effective_ua = user_agent or request.headers.get("user-agent") or ""
    cf_country = request.headers.get("cf-ipcountry", "")
    x_forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = x_forwarded.split(",")[0].strip() if x_forwarded else (request.client.host if request.client else "")
    await track_page_view(
        path=path,
        visitor_id=visitor_id,
        user_id=user_id,
        referrer=referrer,
        user_agent=effective_ua,
        screen_width=screen_width,
        session_id=session_id,
        client_ip=client_ip if not cf_country else None,
        pre_resolved_country=cf_country or None,
        is_404_hint=is_404_hint,
    )
    return {"status": "ok"}


_public_stats_cache: Dict[str, Any] = {"data": None, "ts": 0}

@router.get("/analytics/public-stats")
async def public_stats():
    """Lightweight cached stats for landing page (no auth required)."""
    now = time.time()
    if _public_stats_cache["data"] and now - _public_stats_cache["ts"] < 300:
        return _public_stats_cache["data"]

    total_users = 0
    try:
        from db_ops import supa_list_users
        users = await supa_list_users()
        total_users = len(users)
    except Exception:
        pass

    total_subjects = 0
    try:
        if db is not None and await is_mongo_available():
            total_subjects = await db.subjects.count_documents({})
    except Exception:
        pass

    result = {
        "total_users": total_users,
        "total_subjects": total_subjects,
    }
    _public_stats_cache["data"] = result
    _public_stats_cache["ts"] = now
    return result


# ─────────────────────────────────────────────
# Top routes for build-time prerendering (Task #388)
# ─────────────────────────────────────────────
# Returns the most-visited routes over the last `days` days based on the
# `page_views` collection (same source as the admin /admin/analytics
# dashboard). Public + cached so the static-site build can fetch it
# without an admin token. Filtered to subject + chapter route shapes
# (3 or 4 path segments, lowercase slug-style) so consumers don't need
# to re-filter. Falls back to an empty list when Mongo is unavailable.

_top_routes_cache: Dict[str, Any] = {}
_TOP_ROUTES_TTL_SECONDS = 600  # 10 min

_SLUG_SEG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _is_prerender_candidate_path(path: str) -> bool:
    if not path or not path.startswith("/"):
        return False
    parts = path.strip("/").split("/")
    if len(parts) not in (3, 4):
        return False
    return all(_SLUG_SEG_RE.match(p) for p in parts)


@router.get("/analytics/top-routes")
async def top_routes(days: int = 30, limit: int = 200):
    """Top subject + chapter routes by real pageviews.

    Used by the static prerender step (Task #388) to pick which routes
    to bake into HTML based on actual demand instead of bundle order.
    No auth: returns aggregate counts only, no PII.
    """
    days = max(1, min(int(days or 30), 90))
    limit = max(1, min(int(limit or 200), 1000))

    cache_key = f"{days}:{limit}"
    now = time.time()
    cached = _top_routes_cache.get(cache_key)
    if cached and now - cached["ts"] < _TOP_ROUTES_TTL_SECONDS:
        return cached["data"]

    routes: List[Dict[str, Any]] = []
    try:
        if db is not None and await is_mongo_available():
            since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            pipeline = [
                {"$match": {
                    "date": {"$gte": since},
                    "is_bot": {"$ne": True},
                    "is_404": {"$ne": True},
                }},
                {"$group": {"_id": "$path", "views": {"$sum": 1}}},
                {"$sort": {"views": -1}},
                {"$limit": limit * 4},  # over-fetch then filter
            ]
            rows = await db.page_views.aggregate(pipeline).to_list(limit * 4)
            for row in rows:
                p = row.get("_id") or ""
                if _is_prerender_candidate_path(p):
                    routes.append({"path": p, "views": int(row.get("views") or 0)})
                if len(routes) >= limit:
                    break
    except Exception as e:
        logger.debug(f"top_routes aggregation failed: {e}")
        routes = []

    result = {
        "days": days,
        "limit": limit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "routes": routes,
    }
    _top_routes_cache[cache_key] = {"ts": now, "data": result}
    return result


@router.post("/analytics/session-ping")
async def session_ping_endpoint(
    session_id: str = Body(...),
    visitor_id: str = Body(...),
):
    """Keep a session alive. Called every 30s from frontend heartbeat."""
    try:
        if db is not None and await is_mongo_available():
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.sessions.update_one(
                {"session_id": session_id},
                {
                    "$setOnInsert": {
                        "session_id": session_id,
                        "visitor_id": visitor_id,
                        "start_time": now_iso,
                        "entry_path": "",
                        "page_count": 0,
                        "is_bot": False,
                    },
                    "$set": {"last_ping": now_iso},
                },
                upsert=True,
            )
    except Exception as e:
        logger.debug(f"session_ping failed: {e}")
    return {"status": "ok"}


@router.post("/analytics/session-end")
async def session_end_endpoint(
    session_id: str = Body(...),
    visitor_id: str = Body(None),
    end_timestamp: str = Body(None),
):
    """Record session end time. Called via sendBeacon on tab close."""
    try:
        if db is not None and await is_mongo_available():
            end_iso = None
            if end_timestamp:
                try:
                    datetime.fromisoformat(end_timestamp.replace("Z", "+00:00"))
                    end_iso = end_timestamp
                except (ValueError, AttributeError):
                    pass
            if not end_iso:
                end_iso = datetime.now(timezone.utc).isoformat()
            await db.sessions.update_one(
                {"session_id": session_id},
                {"$set": {"end_time": end_iso, "last_ping": end_iso}},
            )
    except Exception as e:
        logger.debug(f"session_end failed: {e}")
    return {"status": "ok"}


@router.post("/analytics/track")
async def track_event(
    event_type: str = Body(...),
    subject_id: str = Body(None),
    chapter_id: str = Body(None),
    search_query: str = Body(None),
    metadata: dict = Body(None),
    user: dict = Depends(get_current_user_optional)
):
    """
    Public endpoint for tracking library interactions.
    Called from frontend when user interacts with content.
    
    Event types:
    - search: User searched in library
    - subject_view: User opened a subject
    - chapter_view: User viewed a chapter
    - ask_ai_click: User clicked Ask AI button
    - document_open: User opened document viewer
    """
    user_id = user.get("id") if user else None
    
    if event_type == "pwa_install":
        action = (metadata or {}).get("action", "unknown")
        await track_pwa_install(action=action, metadata=metadata, user_id=user_id)
        return {"status": "tracked"}

    await track_library_event(
        event_type=event_type,
        subject_id=subject_id,
        chapter_id=chapter_id,
        user_id=user_id,
        search_query=search_query,
        metadata=metadata
    )
    
    return {"status": "tracked"}


@router.get("/admin/pwa/stats")
async def admin_pwa_stats(admin: dict = Depends(get_admin_user)):
    return await get_pwa_stats()


# ─────────────────────────────────────────────────────────────────────────────
# Task #408: hydrate telemetry — server-side mirror of the client-side
# `hydrate_preload_failed` / `hydrate_recovered` / `hydrate_stalled` events.
# Stored separately from PostHog so the admin dashboard can render an
# "ops health" tile without a PostHog API integration. Documents are
# auto-deleted after 30 days via a TTL index (created lazily on first
# write to avoid startup churn).
# ─────────────────────────────────────────────────────────────────────────────

_HYDRATE_TTL_INDEX_READY = False
_HYDRATE_VALID_EVENTS = {
    "hydrate_preload_failed",
    "hydrate_recovered",
    "hydrate_stalled",
}


async def _ensure_hydrate_indexes():
    global _HYDRATE_TTL_INDEX_READY
    if _HYDRATE_TTL_INDEX_READY:
        return
    try:
        # 30-day TTL — operationally interesting window is the last 7d,
        # but we keep extra runway for incident postmortems.
        await db.hydrate_telemetry.create_index(
            "created_at", expireAfterSeconds=60 * 60 * 24 * 30,
        )
        await db.hydrate_telemetry.create_index([("event", 1), ("created_at", -1)])
        _HYDRATE_TTL_INDEX_READY = True
    except Exception as e:
        logger.warning(f"hydrate_telemetry index create failed (non-fatal): {e}")


@router.post("/analytics/hydrate-event")
async def track_hydrate_event(
    request: Request,
    event: str = Body(...),
    kind: Optional[str] = Body(None),
    path: Optional[str] = Body(None),
    auto_reload: Optional[bool] = Body(None),
    preload_failed: Optional[bool] = Body(None),
    message: Optional[str] = Body(None),
    name: Optional[str] = Body(None),
    elapsed_ms: Optional[int] = Body(None),
    ms_since_reload: Optional[int] = Body(None),
):
    """Public endpoint: persist a hydrate-lifecycle event for ops dashboards.

    Accepts only the three known event names; all other payloads are dropped
    so a misbehaving (or malicious) client cannot pollute the collection.
    Best-effort — never raises; analytics must not break page loads.
    """
    if event not in _HYDRATE_VALID_EVENTS:
        return {"status": "ignored"}
    try:
        await _ensure_hydrate_indexes()
        ua = request.headers.get("user-agent", "")[:300]
        # Cap free-form fields so a runaway client can't bloat documents.
        doc = {
            "event": event,
            "kind": (kind or "")[:64] or None,
            "path": (path or "")[:200] or None,
            "auto_reload": bool(auto_reload) if auto_reload is not None else None,
            "preload_failed": bool(preload_failed) if preload_failed is not None else None,
            "message": (message or "")[:300] or None,
            "name": (name or "")[:64] or None,
            "elapsed_ms": int(elapsed_ms) if isinstance(elapsed_ms, (int, float)) else None,
            "ms_since_reload": int(ms_since_reload) if isinstance(ms_since_reload, (int, float)) else None,
            "ua": ua or None,
            "created_at": datetime.now(timezone.utc),
        }
        await db.hydrate_telemetry.insert_one(doc)
    except Exception as e:
        logger.debug(f"hydrate-event ingest failed: {e}")
    return {"status": "tracked"}


@router.get("/admin/analytics/hydrate-stats")
async def admin_hydrate_stats(
    days: int = 7, admin: dict = Depends(get_admin_user),
):
    """7-day (configurable) ops view of stale-build / hydration health.

    Returns counters + small breakdowns so the admin tile can render a
    healthy empty state when there's nothing to worry about.
    """
    days = max(1, min(int(days or 7), 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    empty = {
        "days": days,
        "preload_failed_total": 0,
        "auto_reload_attempts": 0,
        "auto_reload_recoveries": 0,
        "auto_reload_success_rate_pct": None,
        "stalled_total": 0,
        "manual_failures": 0,  # preload_failed without auto_reload
        "top_kinds": [],
        "top_user_agents": [],
        "recent": [],
    }
    if not await is_mongo_available():
        return empty
    try:
        coll = db.hydrate_telemetry
        base = {"created_at": {"$gte": since}}

        preload_failed_total = await coll.count_documents({
            **base, "event": "hydrate_preload_failed"
        })
        auto_reload_attempts = await coll.count_documents({
            **base, "event": "hydrate_preload_failed", "auto_reload": True,
        })
        auto_reload_recoveries = await coll.count_documents({
            **base, "event": "hydrate_recovered",
        })
        stalled_total = await coll.count_documents({
            **base, "event": "hydrate_stalled",
        })
        manual_failures = max(0, preload_failed_total - auto_reload_attempts)

        success_rate = None
        if auto_reload_attempts > 0:
            success_rate = round(
                (auto_reload_recoveries / auto_reload_attempts) * 100, 1,
            )

        async def _top(field: str, match: dict, limit: int = 5):
            try:
                cur = coll.aggregate([
                    {"$match": {**base, **match, field: {"$nin": [None, ""]}}},
                    {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                    {"$limit": limit},
                ])
                return [
                    {"value": doc["_id"], "count": doc["count"]}
                    async for doc in cur
                ]
            except Exception:
                return []

        top_kinds = await _top("kind", {"event": "hydrate_preload_failed"})
        top_user_agents = await _top("ua", {"event": "hydrate_preload_failed"})

        recent_cur = coll.find(
            {**base, "event": {"$in": list(_HYDRATE_VALID_EVENTS)}},
            {"_id": 0, "created_at": 1, "event": 1, "kind": 1, "path": 1,
             "auto_reload": 1, "message": 1, "name": 1},
        ).sort("created_at", -1).limit(15)
        recent = []
        async for doc in recent_cur:
            ts = doc.get("created_at")
            if isinstance(ts, datetime):
                doc["created_at"] = ts.isoformat()
            recent.append(doc)

        return {
            "days": days,
            "preload_failed_total": preload_failed_total,
            "auto_reload_attempts": auto_reload_attempts,
            "auto_reload_recoveries": auto_reload_recoveries,
            "auto_reload_success_rate_pct": success_rate,
            "stalled_total": stalled_total,
            "manual_failures": manual_failures,
            "top_kinds": top_kinds,
            "top_user_agents": top_user_agents,
            "recent": recent,
        }
    except Exception as e:
        logger.warning(f"hydrate-stats query failed: {e}")
        return empty


# ─────────────────────────────────────────────
# ADMIN CONTENT MANAGEMENT — Boards / Classes / Streams
# ─────────────────────────────────────────────

# GET aliases — admin UI reads from these (proxy to public handlers)
