"""Syrabit.ai — Analytics tracking helpers."""
import re, asyncio, logging, uuid, time, hashlib
from typing import Optional
from datetime import datetime, timezone, timedelta
import deps
from deps import db, logger as _dep_logger
from utils import _is_bot, _get_device_type, _resolve_country

logger = logging.getLogger(__name__)

__all__ = [
    "get_library_analytics", "get_recent_user_events", "get_visitor_stats",
    "track_library_event", "track_page_view",
]

from deps import is_mongo_available

async def track_library_event(
    event_type: str,
    subject_id: str = None,
    chapter_id: str = None,
    user_id: str = None,
    search_query: str = None,
    metadata: dict = None
):
    """
    Track library user interactions for analytics.
    
    Event types:
    - 'search': User searched in library
    - 'subject_view': User opened a subject
    - 'chapter_view': User viewed a chapter
    - 'ask_ai_click': User clicked Ask AI button
    - 'document_open': User opened document viewer
    """
    try:
        event = {
            "id": str(uuid.uuid4()),
            "event_type": event_type,
            "subject_id": subject_id,
            "chapter_id": chapter_id,
            "user_id": user_id,
            "search_query": search_query,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await db.analytics.insert_one(event)
        logger.debug(f"📊 Analytics tracked: {event_type} | subject: {subject_id}")
    except Exception as e:
        logger.error(f"Analytics tracking failed: {e}")


async def get_library_analytics(days: int = 30):
    """Get library analytics summary"""
    if not await is_mongo_available():
        return {"period_days": days, "top_searches": [], "most_viewed_subjects": [], "most_ask_ai_subjects": [], "document_opens": 0, "events_by_type": {}}
    try:
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        start_iso = start_date.isoformat()
        
        search_pipeline = [
            {"$match": {"event_type": "search", "timestamp": {"$gte": start_iso}}},
            {"$group": {"_id": "$search_query", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        top_searches = await db.analytics.aggregate(search_pipeline).to_list(10)
        
        subject_view_pipeline = [
            {"$match": {"event_type": "subject_view", "timestamp": {"$gte": start_iso}, "subject_id": {"$ne": None}}},
            {"$group": {"_id": "$subject_id", "view_count": {"$sum": 1}}},
            {"$sort": {"view_count": -1}},
            {"$limit": 10}
        ]
        top_subjects_raw = await db.analytics.aggregate(subject_view_pipeline).to_list(10)
        
        if top_subjects_raw:
            subject_ids = [item["_id"] for item in top_subjects_raw]
            subjects = await db.subjects.find({"id": {"$in": subject_ids}}, {"_id": 0, "id": 1, "name": 1, "description": 1}).to_list(20)
            subject_map = {s["id"]: s for s in subjects}
            top_subjects = []
            for item in top_subjects_raw:
                subj = subject_map.get(item["_id"])
                if subj:
                    top_subjects.append({"subject_id": item["_id"], "name": subj["name"], "view_count": item["view_count"]})
        else:
            top_subjects = []
        
        ask_ai_pipeline = [
            {"$match": {"event_type": "ask_ai_click", "timestamp": {"$gte": start_iso}, "subject_id": {"$ne": None}}},
            {"$group": {"_id": "$subject_id", "ask_count": {"$sum": 1}}},
            {"$sort": {"ask_count": -1}},
            {"$limit": 10}
        ]
        top_ask_ai_raw = await db.analytics.aggregate(ask_ai_pipeline).to_list(10)
        
        if top_ask_ai_raw:
            ask_subject_ids = [item["_id"] for item in top_ask_ai_raw]
            ask_subjects = await db.subjects.find({"id": {"$in": ask_subject_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(20)
            ask_subject_map = {s["id"]: s["name"] for s in ask_subjects}
            top_ask_ai = []
            for item in top_ask_ai_raw:
                name = ask_subject_map.get(item["_id"], "Unknown")
                top_ask_ai.append({"subject_id": item["_id"], "name": name, "ask_count": item["ask_count"]})
        else:
            top_ask_ai = []
        
        doc_open_count = await db.analytics.count_documents({"event_type": "document_open", "timestamp": {"$gte": start_iso}})
        
        event_type_pipeline = [
            {"$match": {"timestamp": {"$gte": start_iso}}},
            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        events_by_type = await db.analytics.aggregate(event_type_pipeline).to_list(20)
        
        return {
            "period_days": days,
            "top_searches": [{"query": item["_id"], "count": item["count"]} for item in top_searches if item["_id"]],
            "most_viewed_subjects": top_subjects,
            "most_ask_ai_subjects": top_ask_ai,
            "document_opens": doc_open_count,
            "events_by_type": {item["_id"]: item["count"] for item in events_by_type},
        }
    except Exception:
        return {"period_days": days, "top_searches": [], "most_viewed_subjects": [], "most_ask_ai_subjects": [], "document_opens": 0, "events_by_type": {}}


# ── Bot/crawler User-Agent patterns ───────────────────────────────────────────
_BOT_PATTERNS = re.compile(
    r'(googlebot|bingbot|yandexbot|duckduckbot|baiduspider|facebookexternalhit|'
    r'twitterbot|rogerbot|linkedinbot|embedly|quora link preview|showyoubot|'
    r'outbrain|pinterest/0\.|developers\.google\.com/\+/web/snippet|slackbot|'
    r'vkshare|w3c_validator|redditbot|applebot|whatsapp|googleweblight|'
    r'ia_archiver|curl|wget|python-requests|go-http-client|okhttp|'
    r'scrapy|heritrix|nmap|masscan|zgrab)',
    re.IGNORECASE,
)

def _is_bot(user_agent: str) -> bool:
    if not user_agent:
        return False
    return bool(_BOT_PATTERNS.search(user_agent))

def _get_device_type(user_agent: str) -> str:
    if not user_agent:
        return 'desktop'
    if _parse_ua:
        try:
            ua = _parse_ua(user_agent)
            if ua.is_mobile:
                return 'mobile'
            if ua.is_tablet:
                return 'tablet'
            return 'desktop'
        except Exception:
            pass
    ua_lower = user_agent.lower()
    if any(k in ua_lower for k in ('mobile', 'android', 'iphone', 'ipod', 'windows phone')):
        return 'mobile'
    if any(k in ua_lower for k in ('ipad', 'tablet')):
        return 'tablet'
    return 'desktop'

_ip_country_cache: dict = {}

async def _resolve_country(ip: str) -> str:
    """Resolve IP to country code using ip-api.com free tier."""
    if not ip or ip in ('127.0.0.1', '::1', 'unknown'):
        return ''
    if ip in _ip_country_cache:
        return _ip_country_cache[ip]
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f'http://ip-api.com/json/{ip}?fields=countryCode,status')
            data = r.json()
            if data.get('status') == 'success':
                country = data.get('countryCode', '')
                _ip_country_cache[ip] = country
                if len(_ip_country_cache) > 2000:
                    oldest = list(_ip_country_cache.keys())[:500]
                    for k in oldest:
                        _ip_country_cache.pop(k, None)
                return country
    except Exception:
        pass
    return ''


async def track_page_view(
    path: str,
    visitor_id: str,
    user_id: str = None,
    referrer: str = None,
    user_agent: str = None,
    screen_width: int = None,
    session_id: str = None,
    client_ip: str = None,
    pre_resolved_country: str = None,
    is_404_hint: bool = None,
):
    """Track a single page view for visitor analytics."""
    try:
        if user_agent and _is_bot(user_agent):
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now = datetime.now(timezone.utc)

        device_type = _get_device_type(user_agent or '')
        # is_404: rely on frontend signal only (is_404_hint). The frontend has
        # full React Router context and signals True when the NotFoundPage renders.
        # Server-side route guessing is unreliable given dynamic SEO routes.
        is_404 = bool(is_404_hint)

        country = pre_resolved_country or ''
        if not country and client_ip:
            try:
                country = await asyncio.wait_for(_resolve_country(client_ip), timeout=3.0)
            except Exception:
                pass

        event = {
            "id": str(uuid.uuid4()),
            "path": path,
            "visitor_id": visitor_id,
            "session_id": session_id or '',
            "user_id": user_id,
            "referrer": referrer or "",
            "date": today,
            "timestamp": now.isoformat(),
            "device_type": device_type,
            "country": country,
            "screen_width": screen_width,
            "is_bot": False,
            "is_404": is_404,
        }
        await db.page_views.insert_one(event)

        if session_id:
            now_iso = now.isoformat()
            await db.sessions.update_one(
                {"session_id": session_id},
                {
                    "$setOnInsert": {
                        "session_id": session_id,
                        "visitor_id": visitor_id,
                        "start_time": now_iso,
                        "entry_path": path,
                    },
                    "$set": {"last_ping": now_iso},
                    "$inc": {"page_count": 1},
                },
                upsert=True,
            )

    except Exception as e:
        logger.debug(f"page_view tracking failed: {e}")


async def get_visitor_stats() -> dict:
    """Return aggregated visitor stats for the admin dashboard."""
    if not await is_mongo_available():
        return {"total_visitors": 0, "visitors_today": 0, "page_views_today": 0, "daily_visitors": []}
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Headline metrics exclude bots AND 404/empty-content pages
        base_filter = {"is_bot": {"$ne": True}, "is_404": {"$ne": True}}
        # All-inclusive filter (excludes only bots) for new/returning calc
        all_valid_filter = {"is_bot": {"$ne": True}}

        total_visitors = await db.page_views.distinct("visitor_id", base_filter)
        total_visitors_count = len(total_visitors)

        visitors_today_list = await db.page_views.distinct("visitor_id", {**base_filter, "date": today})
        visitors_today_count = len(visitors_today_list)

        page_views_today = await db.page_views.count_documents({**base_filter, "date": today})
        total_page_views = await db.page_views.count_documents(base_filter)

        # 404 / empty-content traffic — counted separately so the admin can see them
        not_found_today = await db.page_views.count_documents({"is_bot": {"$ne": True}, "is_404": True, "date": today})
        not_found_total = await db.page_views.count_documents({"is_bot": {"$ne": True}, "is_404": True})

        # Daily visitors last 7 days (headline: no bots, no 404)
        daily_visitors = []
        for i in range(7):
            day = (datetime.now(timezone.utc) - timedelta(days=6 - i)).strftime("%Y-%m-%d")
            unique = await db.page_views.distinct("visitor_id", {**base_filter, "date": day})
            pv = await db.page_views.count_documents({**base_filter, "date": day})
            daily_visitors.append({"date": day, "visitors": len(unique), "page_views": pv})

        # New vs returning — based on main content views (no bots, no 404) visitors today
        new_visitors_count = 0
        returning_count = 0
        for vid in visitors_today_list:
            older = await db.page_views.count_documents({
                "visitor_id": vid,
                "date": {"$lt": today},
                **all_valid_filter,
            })
            if older > 0:
                returning_count += 1
            else:
                new_visitors_count += 1

        # Device breakdown (exclude bots + 404 so metrics are clean)
        device_pipeline = [
            {"$match": {**base_filter, "device_type": {"$exists": True, "$ne": None, "$ne": ""}}},
            {"$group": {"_id": "$device_type", "count": {"$sum": 1}}},
        ]
        device_rows = await db.page_views.aggregate(device_pipeline).to_list(10)
        device_total = sum(r["count"] for r in device_rows) or 1
        device_breakdown = {
            r["_id"]: {"count": r["count"], "pct": round(r["count"] / device_total * 100, 1)}
            for r in device_rows if r["_id"]
        }

        # Top countries (headline views only)
        country_pipeline = [
            {"$match": {**base_filter, "country": {"$exists": True, "$ne": None, "$ne": ""}}},
            {"$group": {"_id": "$country", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        country_rows = await db.page_views.aggregate(country_pipeline).to_list(5)
        top_countries = [{"country": r["_id"], "count": r["count"]} for r in country_rows]

        # Session metrics (avg duration + bounce rate)
        session_pipeline = [
            {"$match": {"end_time": {"$exists": True}}},
            {"$project": {
                "page_count": 1,
                "duration_secs": {
                    "$divide": [
                        {"$subtract": [
                            {"$toDate": "$end_time"},
                            {"$toDate": "$start_time"},
                        ]},
                        1000,
                    ]
                },
            }},
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "bounces": {"$sum": {"$cond": [{"$lte": ["$page_count", 1]}, 1, 0]}},
                "avg_duration": {"$avg": "$duration_secs"},
            }},
        ]
        session_rows = await db.sessions.aggregate(session_pipeline).to_list(1)
        avg_session_duration = None
        bounce_rate = None
        if session_rows:
            row = session_rows[0]
            total_sess = row.get("total", 0)
            if total_sess > 0:
                bounce_rate = round(row.get("bounces", 0) / total_sess * 100, 1)
                avg_dur = row.get("avg_duration")
                if avg_dur is not None:
                    avg_session_duration = round(avg_dur)

        # ── Multi-source visitor recovery ────────────────────────────────────
        # 1. Registered users from PG (all-time confirmed real visitors)
        registered_visitors = 0
        daily_signups: list = []
        users_since: str = ""
        chatters: int = 0
        try:
            if deps.pg_pool:
                async with deps.pg_pool.acquire() as conn:
                    reg_rows = await conn.fetch(
                        "SELECT created_at FROM users ORDER BY created_at ASC"
                    )
                    registered_visitors = len(reg_rows)
                    if reg_rows:
                        users_since = str(reg_rows[0]["created_at"])[:10]
                    by_day: dict = {}
                    for r in reg_rows:
                        d = str(r["created_at"])[:10]
                        by_day[d] = by_day.get(d, 0) + 1
                    daily_signups = [{"date": d, "signups": n} for d, n in sorted(by_day.items())]

                    # Unique chatters from conversations
                    chatter_ids = await conn.fetch(
                        "SELECT DISTINCT user_id FROM conversations WHERE user_id IS NOT NULL AND user_id != ''"
                    )
                    chatters = len(chatter_ids)
        except Exception as ex:
            logger.warning(f"visitor_stats pg enrichment: {ex}")

        # Best total estimate: at least the registered count (confirmed); MongoDB tracking is additive
        # Registered users = definitive floor of real visitors (they navigated + signed up)
        best_total_visitors = max(registered_visitors, total_visitors_count)

        return {
            "total_visitors": total_visitors_count,           # MongoDB cookie-tracked
            "visitors_today": visitors_today_count,
            "page_views_today": page_views_today,
            "total_page_views": total_page_views,
            "daily_visitors": daily_visitors,
            "new_visitors": new_visitors_count,
            "returning_visitors": returning_count,
            "device_breakdown": device_breakdown,
            "top_countries": top_countries,
            "avg_session_duration": avg_session_duration,
            "bounce_rate": bounce_rate,
            "not_found_today": not_found_today,
            "not_found_total": not_found_total,
            # Multi-source enrichment
            "registered_visitors": registered_visitors,       # All-time signed-up users
            "chatters": chatters,                             # Users who actually chatted
            "daily_signups": daily_signups,                   # Registration timeline
            "users_since": users_since,                       # Earliest user date
            "tracking_since": "2026-03-29",                   # When MongoDB tracking started
            "best_total_visitors": best_total_visitors,       # Best recoverable estimate
        }
    except Exception as e:
        logger.error(f"get_visitor_stats error: {e}")
        return {"total_visitors": 0, "visitors_today": 0, "page_views_today": 0, "total_page_views": 0, "daily_visitors": []}


async def get_recent_user_events(limit: int = 10) -> list:
    """Return recent user-facing events: signups, conversations started, AI chats."""
    events = []
    try:
        users = await supa_list_users()
        users_sorted = sorted(users, key=lambda u: u.get("created_at", ""), reverse=True)
        for u in users_sorted[:5]:
            events.append({
                "type": "signup",
                "icon": "👤",
                "message": f"New user signed up: {u.get('name') or u.get('email', 'Unknown')}",
                "details": u.get("board_name", ""),
                "timestamp": u.get("created_at", ""),
                "level": "info",
            })
    except Exception:
        pass

    try:
        convs = await supa_get_all_conversations(20)
        convs_sorted = sorted(convs, key=lambda c: c.get("updated_at") or c.get("created_at", ""), reverse=True)
        for c in convs_sorted[:5]:
            events.append({
                "type": "conversation",
                "icon": "💬",
                "message": f"AI chat: {c.get('title') or 'Untitled conversation'}",
                "details": c.get("subject_name", ""),
                "timestamp": c.get("updated_at") or c.get("created_at", ""),
                "level": "info",
            })
    except Exception:
        pass

    try:
        if await is_mongo_available():
            recent_analytics = await db.analytics.find(
                {}, {"_id": 0, "event_type": 1, "timestamp": 1, "search_query": 1, "user_id": 1}
            ).sort("timestamp", -1).limit(10).to_list(10)
            for ev in recent_analytics:
                etype = ev.get("event_type", "")
                if etype == "search" and ev.get("search_query"):
                    events.append({
                        "type": "search",
                        "icon": "🔍",
                        "message": f"Library search: \"{ev.get('search_query')}\"",
                        "details": "",
                        "timestamp": ev.get("timestamp", ""),
                        "level": "info",
                    })
                elif etype == "subject_view":
                    events.append({
                        "type": "subject_view",
                        "icon": "📖",
                        "message": "Subject opened in Library",
                        "details": "",
                        "timestamp": ev.get("timestamp", ""),
                        "level": "info",
                    })
                elif etype == "ask_ai_click":
                    events.append({
                        "type": "ai_click",
                        "icon": "🤖",
                        "message": "Ask AI clicked on a subject",
                        "details": "",
                        "timestamp": ev.get("timestamp", ""),
                        "level": "info",
                    })
    except Exception:
        pass

    # Sort all events by timestamp descending
    events_sorted = sorted(
        [e for e in events if e.get("timestamp")],
        key=lambda x: x.get("timestamp", ""),
        reverse=True,
    )
    return events_sorted[:limit]
