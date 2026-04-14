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
import cloudflare_client

logger = logging.getLogger(__name__)

router = APIRouter()


def _merge_daily_sources(*daily_lists):
    by_date: dict = {}
    for src_list in daily_lists:
        if not src_list:
            continue
        for entry in src_list:
            d = entry.get("date", "")
            if not d:
                continue
            if d not in by_date:
                by_date[d] = {"date": d, "visitors": 0, "page_views": 0, "sources": {}}
            visitors = entry.get("visitors", 0)
            page_views = entry.get("page_views", 0)
            source = entry.get("source", "unknown")
            existing = by_date[d]["sources"].get(source)
            if existing:
                by_date[d]["sources"][source] = {
                    "visitors": max(existing["visitors"], visitors),
                    "page_views": max(existing["page_views"], page_views),
                }
            else:
                by_date[d]["sources"][source] = {
                    "visitors": visitors,
                    "page_views": page_views,
                }
    for d, row in by_date.items():
        sources = row["sources"]
        best_v, best_v_src = 0, "none"
        best_pv, best_pv_src = 0, "none"
        for src, vals in sources.items():
            if vals["visitors"] > best_v:
                best_v = vals["visitors"]
                best_v_src = src
            if vals["page_views"] > best_pv:
                best_pv = vals["page_views"]
                best_pv_src = src
        row["visitors"] = best_v
        row["best_visitor_source"] = best_v_src
        row["page_views"] = best_pv
        row["best_pv_source"] = best_pv_src
    return sorted(by_date.values(), key=lambda x: x["date"])


_SOURCE_PRIORITY = ["cloudflare", "ga4", "server", "js-tracked"]

def _best_metric(*values_with_sources):
    best_val, best_src = 0, "none"
    for val, src in values_with_sources:
        if val and val > best_val:
            best_val = val
            best_src = src
    return best_val, best_src


@router.get("/admin/analytics")
async def admin_analytics(days: int = 30, admin: dict = Depends(get_admin_user)):
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
    cf_vs, ga4_vs, ga4_pages, ga4_refs, library_stats, mongo_vs = await asyncio.gather(
        cloudflare_client.get_visitor_stats_cf(days=fetch_days),
        ga4_client.get_visitor_stats_ga4(days=fetch_days),
        ga4_client.get_top_pages_ga4(limit=20),
        ga4_client.get_top_referrers_ga4(limit=15),
        get_library_analytics(days=days),
        get_visitor_stats(days=fetch_days),
        return_exceptions=True,
    )

    cf_data = cf_vs if isinstance(cf_vs, dict) else None
    ga4_data = ga4_vs if isinstance(ga4_vs, dict) else None
    mongo_data = mongo_vs if isinstance(mongo_vs, dict) else {}

    cf_7d_visitors = sum(d.get("visitors", 0) for d in (cf_data.get("daily_visitors", []) if cf_data else []))
    ga4_7d_visitors = sum(d.get("visitors", 0) for d in (ga4_data.get("daily_visitors", []) if ga4_data else []))
    ss_7d_visitors = sum(d.get("visitors", 0) for d in (mongo_data.get("server_side", {}).get("daily_visitors", [])))
    js_7d_visitors = sum(d.get("visitors", 0) for d in (mongo_data.get("daily_visitors", [])))

    best_total, best_total_src = _best_metric(
        (cf_7d_visitors, "cloudflare"),
        (ga4_7d_visitors, "ga4"),
        (ss_7d_visitors, "server"),
        (js_7d_visitors, "js-tracked"),
    )
    best_today, best_today_src = _best_metric(
        (cf_data.get("visitors_today", 0) if cf_data else 0, "cloudflare"),
        (ga4_data.get("visitors_today", 0) if ga4_data else 0, "ga4"),
        (mongo_data.get("server_side", {}).get("unique_today", 0), "server"),
        (mongo_data.get("visitors_today", 0), "js-tracked"),
    )
    best_pv_today, best_pv_src = _best_metric(
        (cf_data.get("page_views_today", 0) if cf_data else 0, "cloudflare"),
        (ga4_data.get("page_views_today", 0) if ga4_data else 0, "ga4"),
        (mongo_data.get("server_side", {}).get("hits_today", 0), "server"),
        (mongo_data.get("page_views_today", 0), "js-tracked"),
    )

    cf_daily = None
    if cf_data:
        cf_daily = [dict(d, source="cloudflare") for d in cf_data.get("daily_visitors", [])]
    ga4_daily = None
    if ga4_data:
        ga4_daily = [dict(d, source="ga4") for d in ga4_data.get("daily_visitors", [])]
    ss_daily = mongo_data.get("server_side", {}).get("daily_visitors")
    if ss_daily:
        ss_daily = [dict(d, source="server") for d in ss_daily]
    js_daily = mongo_data.get("daily_visitors")
    if js_daily:
        js_daily = [dict(d, source="js-tracked") for d in js_daily]

    backfill_daily = await _load_backfill_daily(days=fetch_days)

    merged_daily = _merge_daily_sources(cf_daily, ga4_daily, ss_daily, js_daily, backfill_daily)

    visitor_stats = dict(mongo_data)
    visitor_stats["best_estimate"] = {
        "total_visitors": best_total,
        "total_visitors_source": best_total_src,
        "visitors_today": best_today,
        "visitors_today_source": best_today_src,
        "page_views_today": best_pv_today,
        "page_views_today_source": best_pv_src,
    }
    visitor_stats["merged_daily"] = merged_daily
    if cf_data:
        visitor_stats["cloudflare"] = {
            "total_visitors": cf_data.get("total_visitors", 0),
            "visitors_today": cf_data.get("visitors_today", 0),
            "page_views_today": cf_data.get("page_views_today", 0),
            "total_page_views": cf_data.get("total_page_views", 0),
            "total_requests": cf_data.get("total_requests", 0),
            "daily_visitors": cf_data.get("daily_visitors", []),
        }
    if ga4_data:
        visitor_stats["ga4"] = {
            "total_visitors": ga4_data.get("total_visitors", 0),
            "visitors_today": ga4_data.get("visitors_today", 0),
            "page_views_today": ga4_data.get("page_views_today", 0),
            "daily_visitors": ga4_data.get("daily_visitors", []),
        }

    top_pages = []
    if isinstance(ga4_pages, list):
        top_pages = ga4_pages
    else:
        cf_pages = None
        try:
            cf_pages = await cloudflare_client.get_top_pages_cf()
        except Exception:
            pass
        if cf_pages:
            top_pages = cf_pages
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
        "cf_connected": isinstance(cf_vs, dict),
    }


class SyncHistoricalReq(BaseModel):
    days: int = 90

@router.post("/admin/analytics/sync-historical")
async def sync_historical_data(
    req: SyncHistoricalReq = Body(...),
    admin: dict = Depends(get_admin_user),
):
    days = req.days
    synced = {"cloudflare": 0, "ga4": 0}

    cf_daily, ga4_daily = await asyncio.gather(
        cloudflare_client.get_historical_daily(days=days),
        _fetch_ga4_historical(days=days),
        return_exceptions=True,
    )

    if isinstance(cf_daily, list) and cf_daily:
        for entry in cf_daily:
            try:
                await db.analytics_daily_totals.update_one(
                    {"date": entry["date"], "source": "cloudflare"},
                    {"$set": {
                        "date": entry["date"],
                        "source": "cloudflare",
                        "visitors": entry.get("visitors", 0),
                        "page_views": entry.get("page_views", 0),
                        "requests": entry.get("requests", 0),
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
                synced["cloudflare"] += 1
            except Exception as e:
                logger.debug(f"CF sync upsert error: {e}")

    if isinstance(ga4_daily, list) and ga4_daily:
        for entry in ga4_daily:
            try:
                await db.analytics_daily_totals.update_one(
                    {"date": entry["date"], "source": "ga4"},
                    {"$set": {
                        "date": entry["date"],
                        "source": "ga4",
                        "visitors": entry.get("visitors", 0),
                        "page_views": entry.get("page_views", 0),
                        "synced_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
                synced["ga4"] += 1
            except Exception as e:
                logger.debug(f"GA4 sync upsert error: {e}")

    return {
        "status": "ok",
        "synced_days": synced,
        "total_synced": synced["cloudflare"] + synced["ga4"],
    }


async def _load_backfill_daily(days: int = 7) -> list:
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return []
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = await db.analytics_daily_totals.find(
            {"date": {"$gte": start_date}},
            {"_id": 0, "date": 1, "source": 1, "visitors": 1, "page_views": 1},
        ).to_list(days * 4)
        results = []
        for r in rows:
            src = r.get("source", "backfill")
            results.append({
                "date": r.get("date", ""),
                "visitors": r.get("visitors", 0),
                "page_views": r.get("page_views", 0),
                "source": src,
            })
        return results
    except Exception as e:
        logger.debug(f"backfill load failed: {e}")
        return []


async def _fetch_ga4_historical(days: int = 90) -> list:
    try:
        resp = await ga4_client.run_report(
            dimensions=["date"],
            metrics=["activeUsers", "screenPageViews"],
            date_ranges=[{"startDate": f"{days}daysAgo", "endDate": "today"}],
            order_bys=[{"dimension": {"dimensionName": "date"}}],
            limit=days + 1,
        )
        if not resp or not resp.get("rows"):
            return []
        results = []
        for row in resp["rows"]:
            raw_date = row["dimensionValues"][0]["value"]
            formatted = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            results.append({
                "date": formatted,
                "visitors": int(row["metricValues"][0]["value"]),
                "page_views": int(row["metricValues"][1]["value"]),
                "source": "ga4",
            })
        return results
    except Exception as e:
        logger.warning(f"GA4 historical fetch failed: {e}")
        return []


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
