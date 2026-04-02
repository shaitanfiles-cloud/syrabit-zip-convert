"""Syrabit.ai — Admin auth, users, conversations"""
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
import deps
from cache import *
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    create_token, decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional, JWTError,
)
from db_ops import *
from llm import call_llm_api, call_llm_api_stream
from rag import *
from utils import *
from analytics_helpers import *

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/admin/login")
async def admin_login(data: AdminLoginReq, response: Response):

    # Find the matching admin account across the array
    matched = next(
        (a for a in ADMIN_ACCOUNTS
         if a["email"].lower() == data.email.lower()
         and a["password"] == data.password),
        None
    )
    if not matched:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    # Token payload includes name so the frontend welcome toast can greet by name
    token = create_token(
        {
            "sub":      matched["email"],
            "email":    matched["email"],
            "name":     matched["name"],
            "is_admin": True,
        },
        secret=ADMIN_JWT_SECRET,
        expires_delta=60 * 24,   # 24-hour session
    )
    _ck = dict(key="syrabit_admin_session", value=token, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, max_age=60 * 24 * 60)
    if COOKIE_DOMAIN:
        _ck["domain"] = COOKIE_DOMAIN
    response.set_cookie(**_ck)
    return {
        "access_token": token,
        "token_type":   "bearer",
        "email":        matched["email"],
        "name":         matched["name"],
    }

@router.post("/auth/refresh")
async def refresh_token(
    response: Response,
    syrabit_refresh: Optional[str] = Cookie(default=None),
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    token = creds.credentials if creds else syrabit_refresh
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token provided")
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Not a refresh token")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.get("status") in ("banned", "suspended"):
        raise HTTPException(status_code=403, detail=f"Account {user.get('status')}")
    role = "admin" if user.get("is_admin") else "student"
    new_access = create_access_token(user_id, role=role, plan=user.get("plan", "free"))
    _redis_invalidate_session(user_id)
    _ck = dict(key="syrabit_session", value=new_access, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, max_age=JWT_ACCESS_EXPIRE_MINUTES * 60)
    if COOKIE_DOMAIN:
        _ck["domain"] = COOKIE_DOMAIN
    response.set_cookie(**_ck)
    return {"access_token": new_access, "token_type": "bearer"}

@router.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user_optional)):
    if user:
        _redis_invalidate_session(user.get("id", ""))
    _del_kwargs = dict(samesite=COOKIE_SAMESITE, secure=SECURE_COOKIES)
    if COOKIE_DOMAIN:
        _del_kwargs["domain"] = COOKIE_DOMAIN
    response.delete_cookie(key="syrabit_session", **_del_kwargs)
    response.delete_cookie(key="syrabit_refresh", path="/api/auth/refresh", **_del_kwargs)
    return {"message": "Logged out"}

@router.post("/admin/logout")
async def admin_logout(response: Response):
    _del_kwargs = dict(samesite=COOKIE_SAMESITE, secure=SECURE_COOKIES)
    if COOKIE_DOMAIN:
        _del_kwargs["domain"] = COOKIE_DOMAIN
    response.delete_cookie(key="syrabit_admin_session", **_del_kwargs)
    return {"message": "Logged out"}

@router.get("/admin/verify")
async def admin_verify(response: Response, admin: dict = Depends(get_admin_user)):
    """Verify admin session and silently slide the cookie expiry forward (keep-alive)."""
    refreshed = create_token(
        {
            "sub":      admin.get("email"),
            "email":    admin.get("email"),
            "name":     admin.get("name", "Admin"),
            "is_admin": True,
        },
        secret=ADMIN_JWT_SECRET,
        expires_delta=60 * 24,
    )
    _ck = dict(key="syrabit_admin_session", value=refreshed, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, max_age=60 * 24 * 60)
    if COOKIE_DOMAIN:
        _ck["domain"] = COOKIE_DOMAIN
    response.set_cookie(**_ck)
    return {"valid": True, "email": admin.get("email"), "name": admin.get("name", "Admin"), "access_token": refreshed}

# ─────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────
@router.get("/admin/dashboard")
async def admin_dashboard(admin: dict = Depends(get_admin_user)):
    total_users = await supa_count_users()

    # ── Conversations + messages: merge PG and Supabase ──────────────────────
    pg_conv_map: dict = {}   # id -> {"messages": [...]}
    supa_conv_rows: list = []

    if deps.pg_pool:
        try:
            async with deps.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, messages, created_at FROM conversations ORDER BY created_at ASC"
                )
                for r in _pg_rows(rows):
                    pg_conv_map[r["id"]] = r
        except Exception: pass

    if supa:
        try:
            all_supa: list = []
            offset = 0
            while True:
                r = await _supa(lambda o=offset: supa.table("conversations")
                    .select("id, messages, created_at, user_id")
                    .order("created_at", desc=False)
                    .range(o, o + 199).execute())
                batch = r.data or []
                if not batch:
                    break
                for row in batch:
                    msgs = row.get("messages")
                    if isinstance(msgs, str):
                        try: row["messages"] = json.loads(msgs)
                        except: row["messages"] = []
                    elif msgs is None:
                        row["messages"] = []
                all_supa.extend(batch)
                offset += 200
                if len(batch) < 200:
                    break
            supa_conv_rows = all_supa
        except Exception as e:
            logger.warning(f"dashboard supa conv fetch: {e}")

    # Merge: PG rows take precedence (better message fidelity); Supabase fills the rest
    merged_convs: dict = {}
    for row in supa_conv_rows:
        merged_convs[row["id"]] = row
    for cid, row in pg_conv_map.items():
        merged_convs[cid] = row   # PG overwrites supa for same id

    total_convs = len(merged_convs)
    pg_conv_count = len(pg_conv_map)
    supa_conv_count = len(supa_conv_rows)

    convs_with_messages = sum(1 for c in merged_convs.values() if len(c.get("messages") or []) > 0)
    total_messages = sum(len(c.get("messages") or []) for c in merged_convs.values())

    # Date range of conversations
    all_dates = [c.get("created_at", "") for c in merged_convs.values() if c.get("created_at")]
    oldest_conv = min(all_dates)[:10] if all_dates else None
    newest_conv = max(all_dates)[:10] if all_dates else None

    # Unique users who have ever chatted
    unique_chatters = len({c.get("user_id") for c in supa_conv_rows if c.get("user_id")})

    try:
        total_subjects = await db.subjects.count_documents({}) if await is_mongo_available() else 0
    except Exception:
        total_subjects = 0
    users = await supa_list_users()
    plan_dist = {}
    for u in users:
        p = u.get("plan", "free")
        plan_dist[p] = plan_dist.get(p, 0) + 1

    # Visitor analytics + recent user events
    visitor_stats, recent_events = await asyncio.gather(
        get_visitor_stats(),
        get_recent_user_events(limit=10),
    )

    return {
        "total_users": total_users,
        "total_conversations": total_convs,
        "conversations_with_messages": convs_with_messages,
        "total_messages": total_messages,
        "unique_chatters": unique_chatters,
        "total_subjects": total_subjects,
        "plan_distribution": plan_dist,
        "visitor_stats": visitor_stats,
        "recent_events": recent_events,
        "conversation_date_range": {
            "oldest": oldest_conv,
            "newest": newest_conv,
        },
        "pg_conversations": pg_conv_count,
        "supa_conversations": supa_conv_count,
    }

@router.get("/admin/users")
async def admin_get_users(
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    admin: dict = Depends(get_admin_user),
):
    users = await supa_list_users()
    if search:
        q = search.lower()
        users = [u for u in users if q in u.get("email", "").lower() or q in u.get("name", "").lower()]
    total = len(users)
    users = users[offset: offset + limit]
    result = []
    for u in users:
        u.pop("password_hash", None)
        credits_info = await get_user_credits(u)
        result.append({**u, "credits_used": credits_info["used"], "credits_limit": credits_info["limit"]})
    return {"users": result, "total": total, "limit": limit, "offset": offset}

@router.patch("/admin/users/{user_id}/status")
async def admin_update_user_status(user_id: str, data: UserStatusUpdate, admin: dict = Depends(get_admin_user)):
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await supa_update_user(user_id, {"status": data.status})
    return {"message": "Updated"}

@router.patch("/admin/users/{user_id}/plan")
async def admin_update_user_plan(user_id: str, data: UserPlanUpdate, admin: dict = Depends(get_admin_user)):
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update = {"plan": data.plan}
    if data.credits_used is not None:
        update["credits_used"] = data.credits_used
    await supa_update_user(user_id, update)
    _redis_invalidate_session(user_id)
    return {"message": "Updated"}

@router.patch("/admin/users/{user_id}/credits")
async def admin_update_user_credits(user_id: str, data: UserCreditsUpdate, admin: dict = Depends(get_admin_user)):
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.action not in ("add", "deduct", "reset"):
        raise HTTPException(status_code=400, detail="action must be one of: add, deduct, reset")
    if data.action != "reset" and (data.amount is None or data.amount < 0):
        raise HTTPException(status_code=400, detail="amount must be a non-negative integer for add/deduct actions")
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reset_date = user.get("credits_reset_date") or ""
    if isinstance(reset_date, datetime):
        reset_date = reset_date.strftime("%Y-%m-%d")
    elif hasattr(reset_date, "isoformat"):
        reset_date = str(reset_date)[:10]
    credits_used_today = user.get("credits_used_today", 0) if reset_date == today_str else 0
    action = data.action
    amount = data.amount if data.amount is not None else 0
    update = {"credits_reset_date": today_str}
    if action == "reset":
        update["credits_used_today"] = 0
    elif action == "deduct":
        update["credits_used_today"] = credits_used_today + amount
    else:
        update["credits_used_today"] = max(0, credits_used_today - amount)
    await supa_update_user(user_id, update)
    return {"message": "Credits updated", **update}

@router.post("/admin/sync-conversations")
async def admin_sync_conversations(admin: dict = Depends(get_admin_user)):
    """Sync all Supabase conversations → PostgreSQL (upsert, PG wins on message count tie)."""
    if not supa or not deps.pg_pool:
        raise HTTPException(status_code=503, detail="Both Supabase and PostgreSQL required for sync")

    # ── 1. Fetch all Supabase conversations (paginated) ──────────────────────
    all_supa: list = []
    offset = 0
    while True:
        r = await _supa(lambda o=offset: supa.table("conversations")
            .select("id, user_id, title, preview, subject_id, subject_name, starred, archived, messages, tokens, created_at, updated_at")
            .order("created_at", desc=False)
            .range(o, o + 199).execute())
        batch = r.data or []
        if not batch:
            break
        for row in batch:
            msgs = row.get("messages")
            if isinstance(msgs, str) and msgs.strip():
                try:
                    parsed = json.loads(msgs)
                    row["_parsed_messages"] = parsed if isinstance(parsed, list) else []
                    row["_raw_messages"] = msgs
                except Exception:
                    row["_parsed_messages"] = []
                    row["_raw_messages"] = "[]"
            elif isinstance(msgs, list):
                row["_parsed_messages"] = msgs
                row["_raw_messages"] = json.dumps(msgs)
            else:
                row["_parsed_messages"] = []
                row["_raw_messages"] = "[]"
        all_supa.extend(batch)
        offset += 200
        if len(batch) < 200:
            break

    total_supa = len(all_supa)

    # ── 2. Fetch existing PG ids + message lengths ────────────────────────────
    async with deps.pg_pool.acquire() as conn:
        pg_rows = await conn.fetch("SELECT id, octet_length(messages) AS msg_len FROM conversations")
    pg_map = {r["id"]: (r["msg_len"] or 0) for r in pg_rows}

    # ── 3. Upsert each Supabase row into PG ───────────────────────────────────
    inserted = 0
    updated = 0
    skipped = 0
    errors = 0

    UPSERT_SQL = """
        INSERT INTO conversations
            (id, user_id, title, preview, subject_id, subject_name, starred, archived,
             messages, tokens, created_at, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (id) DO UPDATE SET
            messages   = CASE
                WHEN octet_length(EXCLUDED.messages) > octet_length(conversations.messages)
                THEN EXCLUDED.messages
                ELSE conversations.messages
            END,
            title      = COALESCE(EXCLUDED.title, conversations.title),
            preview    = COALESCE(EXCLUDED.preview, conversations.preview),
            updated_at = GREATEST(EXCLUDED.updated_at, conversations.updated_at)
    """

    async with deps.pg_pool.acquire() as conn:
        for row in all_supa:
            try:
                raw_msgs = row["_raw_messages"]
                supa_msg_len = len(raw_msgs.encode())
                pg_msg_len = pg_map.get(row["id"], -1)

                if pg_msg_len == -1:
                    # Not in PG at all — insert
                    action = "insert"
                elif supa_msg_len > pg_msg_len:
                    # Supabase has more data — update
                    action = "update"
                else:
                    skipped += 1
                    continue

                await conn.execute(
                    UPSERT_SQL,
                    row.get("id"),
                    row.get("user_id"),
                    row.get("title") or "Untitled",
                    row.get("preview") or "",
                    row.get("subject_id") or "",
                    row.get("subject_name") or "",
                    bool(row.get("starred", False)),
                    bool(row.get("archived", False)),
                    raw_msgs,
                    int(row.get("tokens") or 0),
                    str(row.get("created_at") or ""),
                    str(row.get("updated_at") or ""),
                )
                if action == "insert":
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                logger.warning(f"sync conv {row.get('id')}: {e}")
                errors += 1

    # ── 4. Final PG counts ────────────────────────────────────────────────────
    async with deps.pg_pool.acquire() as conn:
        pg_total = await conn.fetchval("SELECT COUNT(*) FROM conversations") or 0
        pg_with_msgs = await conn.fetchval(
            "SELECT COUNT(*) FROM conversations WHERE messages IS NOT NULL AND messages != '[]' AND length(messages) > 2"
        ) or 0
        pg_total_msgs = await conn.fetchval(
            "SELECT SUM(jsonb_array_length(messages::jsonb)) FROM conversations "
            "WHERE messages IS NOT NULL AND messages != '[]' AND length(messages) > 2"
        ) or 0

    return {
        "ok": True,
        "supa_total": total_supa,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "pg_total_after": pg_total,
        "pg_with_messages_after": pg_with_msgs,
        "pg_total_messages_after": pg_total_msgs,
    }


@router.get("/admin/conversations")
async def admin_get_conversations(admin: dict = Depends(get_admin_user)):
    # Fetch from both PostgreSQL and Supabase and merge (PG takes precedence for messages)
    pg_convs: list = []
    supa_convs: list = []

    if deps.pg_pool:
        try:
            async with deps.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 1000"
                )
                pg_convs = _pg_rows(rows)
        except Exception as e:
            logger.warning(f"admin_get_conversations pg fetch: {e}")

    if supa:
        try:
            r = await _supa(lambda: supa.table("conversations").select("*").order("updated_at", desc=True).limit(1000).execute())
            for row in (r.data or []):
                if isinstance(row.get("messages"), str):
                    try: row["messages"] = json.loads(row["messages"])
                    except: row["messages"] = []
                elif row.get("messages") is None:
                    row["messages"] = []
            supa_convs = r.data or []
        except Exception as e:
            logger.warning(f"admin_get_conversations supa fetch: {e}")

    # Merge: use PG row if available (has real messages), otherwise use Supabase row
    pg_ids = {c.get("id") for c in pg_convs}
    merged = list(pg_convs)
    for sc in supa_convs:
        if sc.get("id") not in pg_ids:
            if isinstance(sc.get("messages"), list):
                pass  # already parsed
            sc["messages"] = sc.get("messages") or []
            merged.append(sc)

    # Sort by updated_at desc
    def _conv_sort_key(c):
        ts = c.get("updated_at") or c.get("created_at") or ""
        return str(ts)

    merged.sort(key=_conv_sort_key, reverse=True)

    # Enrich with user info
    user_ids = list({c.get("user_id") for c in merged if c.get("user_id")})
    users_map = {}
    if user_ids:
        try:
            users = await supa_get_users_by_ids(user_ids)
            users_map = {u["id"]: u for u in users}
        except Exception:
            pass
    for c in merged:
        uid = c.get("user_id")
        u = users_map.get(uid, {})
        c["user_name"] = u.get("name", "")
        c["user_email"] = u.get("email", c.get("user_email", ""))
        c["user_plan"] = u.get("plan", "free")
        c["user_avatar"] = u.get("avatar_url", "")
        c["user_board"] = u.get("board_name", "")
        c["user_class"] = u.get("class_name", "")
        c["user_stream"] = u.get("stream_name", "")
        c["has_messages"] = len(c.get("messages") or []) > 0

    return merged

