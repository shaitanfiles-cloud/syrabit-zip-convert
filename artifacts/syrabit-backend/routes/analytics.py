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
import ga4_client

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/admin/analytics")
async def admin_analytics(days: int = 30, admin: dict = Depends(get_admin_user)):
    """
    Enhanced admin analytics dashboard with library interaction tracking
    
    Query params:
    - days: Number of days to look back (default: 30)
    """
    users = await supa_list_users()
    
    # Daily signups
    daily_signups = []
    for i in range(7):
        day = (datetime.now(timezone.utc) - timedelta(days=6-i)).strftime("%Y-%m-%d")
        count = sum(1 for u in users if u.get("created_at", "")[:10] == day)
        daily_signups.append({"date": day, "count": count})
    
    # Plan usage
    plan_usage = {}
    for u in users:
        p = u.get("plan", "free")
        plan_usage[p] = plan_usage.get(p, 0) + u.get("credits_used", 0)
    
    # Library analytics + GA4 + MongoDB visitor stats (all in parallel)
    ga4_vs, ga4_pages, ga4_refs, library_stats, mongo_vs = await asyncio.gather(
        ga4_client.get_visitor_stats_ga4(days=7),
        ga4_client.get_top_pages_ga4(limit=20),
        ga4_client.get_top_referrers_ga4(limit=15),
        get_library_analytics(days=days),
        get_visitor_stats(),
        return_exceptions=True,
    )

    # Prefer GA4 data; fall back to MongoDB
    visitor_stats = ga4_vs if isinstance(ga4_vs, dict) else (mongo_vs if isinstance(mongo_vs, dict) else {})

    # Top visited pages — GA4 preferred
    top_pages = []
    if isinstance(ga4_pages, list):
        top_pages = ga4_pages
    else:
        try:
            pipeline = [
                {"$group": {"_id": "$path", "views": {"$sum": 1}, "unique": {"$addToSet": "$visitor_id"}}},
                {"$project": {"path": "$_id", "views": 1, "unique_visitors": {"$size": "$unique"}, "_id": 0}},
                {"$sort": {"views": -1}},
                {"$limit": 15},
            ]
            top_pages = await db.page_views.aggregate(pipeline).to_list(15)
        except Exception:
            pass

    # Referrers — GA4 preferred
    top_referrers = []
    if isinstance(ga4_refs, list):
        top_referrers = ga4_refs
    else:
        try:
            ref_pipeline = [
                {"$match": {"referrer": {"$ne": None, "$ne": ""}}},
                {"$group": {"_id": "$referrer", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10},
            ]
            raw_refs = await db.page_views.aggregate(ref_pipeline).to_list(10)
            for r in raw_refs:
                if r.get("_id"):
                    from urllib.parse import urlparse
                    try:
                        domain = urlparse(r["_id"]).netloc or r["_id"]
                    except Exception:
                        domain = r["_id"]
                    top_referrers.append({"source": domain, "count": r["count"]})
        except Exception:
            pass

    return {
        "daily_signups": daily_signups,
        "plan_usage": plan_usage,
        "library": library_stats if isinstance(library_stats, dict) else {},
        "total_users": len(users),
        "active_users": sum(1 for u in users if u.get("credits_used", 0) > 0),
        "visitor_stats": visitor_stats,
        "top_pages": top_pages,
        "top_referrers": top_referrers,
        "ga4_connected": isinstance(ga4_vs, dict),
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
):
    """Record session end time. Called via sendBeacon on tab close."""
    try:
        if db is not None and await is_mongo_available():
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.sessions.update_one(
                {"session_id": session_id},
                {"$set": {"end_time": now_iso, "last_ping": now_iso}},
            )
    except Exception as e:
        logger.debug(f"session_end failed: {e}")
    return {"status": "ok"}


@router.get("/admin/analytics/live")
async def live_visitors_endpoint(admin: dict = Depends(get_admin_user)):
    """Count sessions with last_ping in the last 5 minutes (live visitors)."""
    try:
        if not await is_mongo_available():
            return {"live_visitors": 0}
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        count = await db.sessions.count_documents({
            "last_ping": {"$gte": cutoff},
            "end_time": {"$exists": False},
        })
        return {"live_visitors": count}
    except Exception as e:
        logger.error(f"live_visitors error: {e}")
        return {"live_visitors": 0}


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

# ─────────────────────────────────────────────
# ADMIN CONTENT MANAGEMENT — Boards / Classes / Streams
# ─────────────────────────────────────────────

# GET aliases — admin UI reads from these (proxy to public handlers)
