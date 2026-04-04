"""Syrabit.ai — Database operations: supa_*, pg_* helpers."""
import json, asyncio, logging, uuid, concurrent.futures as _cf
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from fastapi import HTTPException
import deps as _deps_mod
from deps import supa, db, redis_client, logger as _dep_logger
from cache import (
    _invalidate_user_cache, _user_cache, _conv_cache, _conv_cache_key,
    _invalidate_conv_cache, _redis_cache_session, _redis_get_conversation,
    _redis_invalidate_conversation, _redis_cache_conversation,
)

logger = logging.getLogger(__name__)

__all__ = [
    "_THREAD_POOL", "_pg_row", "_pg_rows", "_pg_user_cols", "_supa", "_supa_mirror",
    "_ALLOWED_CONV_COLUMNS", "_ALLOWED_SETTINGS_COLUMNS", "_ALLOWED_USER_COLUMNS",
    "atomic_deduct_credit", "supa_clear_activity_log", "supa_count_conversations",
    "supa_count_users", "supa_create_password_reset", "supa_delete_conversation",
    "supa_delete_notification", "supa_delete_password_reset", "supa_get_activity_logs",
    "supa_get_all_conversations", "supa_get_conversation", "supa_get_conversations",
    "supa_get_notifications", "supa_get_password_reset", "supa_get_settings",
    "supa_get_user", "supa_get_user_by_id", "supa_get_user_for_reset",
    "supa_get_users_by_ids", "supa_insert_activity_log", "supa_insert_notification",
    "supa_insert_user", "supa_list_users", "supa_update_conversation",
    "supa_update_settings", "supa_update_user", "supa_update_user_password",
    "supa_upsert_conversation",
]

_THREAD_POOL = _cf.ThreadPoolExecutor(max_workers=32)

async def _supa(fn):
    """Await a sync supabase-py operation non-blockingly."""
    return await asyncio.get_event_loop().run_in_executor(_THREAD_POOL, fn)

def _pg_row(row) -> dict:
    """Convert asyncpg Record to plain dict, parsing JSON fields."""
    if row is None:
        return None
    d = dict(row)
    for field in ("saved_subjects", "messages"):
        if field in d and isinstance(d[field], str):
            try: d[field] = json.loads(d[field])
            except: d[field] = [] if field == "messages" else []
    if "metadata" in d and isinstance(d["metadata"], str):
        try: d["metadata"] = json.loads(d["metadata"])
        except: d["metadata"] = {}
    return d

def _pg_rows(rows) -> list:
    return [_pg_row(r) for r in rows] if rows else []

def _pg_user_cols():
    return """id, name, email, password_hash, plan, credits_used, credits_limit,
              document_access, onboarding_done, is_admin, status, bio, phone,
              avatar_url, saved_subjects::text, has_free_credits_issued,
              board_id, board_name, class_id, class_name, stream_id, stream_name,
              credits_used_today, credits_reset_date, created_at,
              google_id, auth_provider,
              consent_dpdp, consent_dpdp_version, consent_dpdp_at"""

# ── Supabase mirror helper ────────────────────────────────────────────────────
def _supa_mirror(fn):
    """Fire-and-forget Supabase write (non-blocking, best-effort)."""
    if supa:
        async def _run():
            try:
                await asyncio.get_event_loop().run_in_executor(_THREAD_POOL, fn)
            except Exception as e:
                logger.debug(f"Supabase mirror failed (non-critical): {e}")
        asyncio.ensure_future(_run())


# ─────────────────────────────────────────────
# USER OPERATIONS  (Supabase / Replit PG layer)
# ─────────────────────────────────────────────

async def supa_get_user(email: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_pg_user_cols()} FROM users WHERE email = $1 LIMIT 1",
                    email.lower()
                )
                if row:
                    return _pg_row(row)
                # not found in PG — fall through to Supabase
        except Exception as e:
            logger.warning(f"pg supa_get_user failed: {e}")
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("*").eq("email", email.lower()).limit(1).execute())
            if r.data:
                user = r.data[0]
                # Back-fill PG so future logins are fast
                try:
                    await supa_insert_user(user)
                except Exception:
                    pass
                return user
        except Exception: pass
    try:
        if db is not None:
            return await db.users.find_one({"email": email.lower()}, {"_id": 0})
    except Exception:
        pass
    return None

async def supa_get_user_by_id(uid: str):
    # Fast path: in-memory 30-second cache — skips DB on every auth'd request
    if uid in _user_cache:
        return _user_cache[uid]
    result = None
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_pg_user_cols()} FROM users WHERE id = $1 LIMIT 1", uid
                )
                if row:
                    result = _pg_row(row)
        except Exception as e:
            logger.warning(f"pg supa_get_user_by_id failed: {e}")
    if result is None and supa:
        try:
            r = await _supa(lambda: supa.table("users").select("*").eq("id", uid).limit(1).execute())
            if r.data:
                result = r.data[0]
                try:
                    await supa_insert_user(result)
                except Exception:
                    pass
        except Exception:
            pass
    if result is None:
        try:
            if db is not None:
                result = await db.users.find_one({"id": uid}, {"_id": 0})
        except Exception:
            pass
    if result:
        _user_cache[uid] = result
    return result

async def supa_insert_user(user: dict):
    if _deps_mod.pg_pool:
        try:
            saved = json.dumps(user.get("saved_subjects", []))
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO users (id, name, email, password_hash, plan, credits_used,
                       credits_limit, document_access, onboarding_done, is_admin, status,
                       bio, phone, avatar_url, saved_subjects, has_free_credits_issued,
                       board_id, board_name, class_id, class_name, stream_id, stream_name,
                       referred_by_code, referred_by_user_id, created_at,
                       google_id, auth_provider)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16,
                               $17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27)
                       ON CONFLICT (id) DO NOTHING""",
                    user.get("id",""), user.get("name",""), user.get("email",""),
                    user.get("password_hash",""), user.get("plan","free"),
                    user.get("credits_used",0), user.get("credits_limit",30),
                    user.get("document_access","zero"), user.get("onboarding_done",False),
                    user.get("is_admin",False), user.get("status","active"),
                    user.get("bio",""), user.get("phone",""), user.get("avatar_url",""),
                    saved, user.get("has_free_credits_issued",True),
                    user.get("board_id"), user.get("board_name"),
                    user.get("class_id"), user.get("class_name"),
                    user.get("stream_id"), user.get("stream_name"),
                    user.get("referred_by_code"), user.get("referred_by_user_id"),
                    user.get("created_at",""),
                    user.get("google_id"), user.get("auth_provider"),
                )
            _supa_mirror(lambda: supa.table("users").upsert(user).execute())
            return
        except Exception as e:
            logger.warning(f"pg supa_insert_user failed: {e}")
    if supa:
        try: await _supa(lambda: supa.table("users").insert(user).execute()); return
        except Exception: pass
    try:
        await db.users.insert_one(user)
    except Exception as e:
        logger.warning(f"All stores failed for insert_user: {e}")

_ALLOWED_USER_COLUMNS = frozenset({
    "name", "bio", "phone", "avatar_url", "plan", "status",
    "credits_used", "credits_limit", "document_access",
    "credits_used_today", "credits_reset_date",
    "saved_subjects", "deletion_requested_at", "deletion_hard_at",
    "last_seen", "onboarding_done",
    "board_id", "board_name", "class_id", "class_name",
    "stream_id", "stream_name",
    "referred_by_code", "referred_by_user_id",
    "google_id", "auth_provider",
    "consent_dpdp", "consent_dpdp_version", "consent_dpdp_at",
})

_ALLOWED_CONV_COLUMNS = frozenset({
    "title", "preview", "subject_id", "subject_name",
    "starred", "archived", "messages", "tokens", "updated_at",
    "metadata",
})

_ALLOWED_SETTINGS_COLUMNS = frozenset({
    "registrations_open", "maintenance_mode", "app_name", "tagline",
})

def _quote_ident(name: str) -> str:
    """Double-quote a SQL identifier to prevent injection (defense-in-depth on top of allowlists)."""
    return '"' + name.replace('"', '""') + '"'

async def supa_update_user(uid: str, updates: dict):
    _invalidate_user_cache(uid)  # always bust cache before touching DB
    if _deps_mod.pg_pool and updates:
        try:
            unknown = set(updates) - _ALLOWED_USER_COLUMNS
            if unknown:
                raise ValueError(f"supa_update_user: disallowed column(s): {unknown}")
            cols = []
            vals = []
            for i, (k, v) in enumerate(updates.items(), start=1):
                qi = _quote_ident(k)
                if k == "saved_subjects":
                    cols.append(f"{qi} = ${i}::jsonb")
                    vals.append(json.dumps(v))
                else:
                    cols.append(f"{qi} = ${i}")
                    vals.append(v)
            vals.append(uid)
            sql = f"UPDATE users SET {', '.join(cols)} WHERE id = ${len(vals)}"
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(sql, *vals)
            _supa_mirror(lambda: supa.table("users").update(updates).eq("id", uid).execute())
            return
        except Exception as e:
            logger.warning(f"pg supa_update_user failed: {e}")
    if supa:
        try: await _supa(lambda: supa.table("users").update(updates).eq("id", uid).execute()); return
        except Exception: pass
    try:
        await db.users.update_one({"id": uid}, {"$set": updates})
    except Exception as e:
        logger.warning(f"All stores failed for update_user: {e}")

async def atomic_deduct_credit(uid: str, current_used: int, current_limit: int) -> bool:
    """Atomically deduct 1 daily credit only if credits_used_today < daily limit.
    Returns True on success, False if limit already reached (race condition guard).
    Resets credits_used_today to 0 when credits_reset_date is before today (UTC).
    Uses PG UPDATE...WHERE for atomic check+increment; falls back to Redis INCR/DECR
    CAS pattern; last resort falls back to Supabase with explicit limit guard.
    """
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _invalidate_user_cache(uid)
    # ── Primary: PostgreSQL atomic UPDATE (multi-worker safe) ──────────────
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE users
                          SET credits_used_today = 0,
                              credits_reset_date = $2
                        WHERE id = $1
                          AND (credits_reset_date IS NULL OR credits_reset_date::text < $2)""",
                    uid, today_str,
                )
                result = await conn.execute(
                    """UPDATE users
                          SET credits_used_today = credits_used_today + 1,
                              credits_used = credits_used + 1
                        WHERE id = $1
                          AND credits_used_today < $2""",
                    uid, current_limit,
                )
            if result and result.split()[-1] != '0':
                return True
            return False
        except Exception as e:
            logger.warning(f"atomic_deduct_credit pg failed, falling back: {e}")
    # ── Fallback: Redis INCR + rollback CAS (atomic per Redis INCR semantics) ──
    if redis_client:
        try:
            redis_key = f"daily_credits:{uid}:{today_str}"
            redis_client.set(redis_key, current_used, ex=86400, nx=True)
            new_count = redis_client.incr(redis_key)
            if new_count > current_limit:
                redis_client.decr(redis_key)
                return False
            user_data = await supa_get_user_by_id(uid)
            lifetime_used = (user_data.get("credits_used", 0) if user_data else 0) + 1
            await supa_update_user(uid, {"credits_used_today": int(new_count), "credits_reset_date": today_str, "credits_used": lifetime_used})
            return True
        except Exception as e:
            logger.warning(f"atomic_deduct_credit redis failed, falling back: {e}")
    # ── Last resort: Supabase with explicit limit guard ─────────────────────
    if current_used >= current_limit:
        return False
    new_used = current_used + 1
    user_data = await supa_get_user_by_id(uid)
    lifetime_used = (user_data.get("credits_used", 0) if user_data else 0) + 1
    await supa_update_user(uid, {"credits_used_today": new_used, "credits_reset_date": today_str, "credits_used": lifetime_used})
    return True

async def supa_list_users():
    """Return all non-admin users, merging PG + Supabase so no one is lost."""
    pg_users = []
    supa_users = []

    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT {_pg_user_cols()} FROM users WHERE is_admin = FALSE ORDER BY created_at DESC LIMIT 2000"
                )
                pg_users = _pg_rows(rows)
        except Exception as e:
            logger.warning(f"pg supa_list_users failed: {e}")

    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("*").neq("is_admin", True).order("created_at", desc=True).limit(2000).execute())
            supa_users = r.data or []
        except Exception:
            pass

    if pg_users or supa_users:
        # Merge: PG is authoritative for users it has; fill in Supabase-only users
        seen = {u["id"] for u in pg_users if u.get("id")}
        for u in supa_users:
            if u.get("id") and u["id"] not in seen:
                seen.add(u["id"])
                pg_users.append(u)
        # Sort by created_at descending
        pg_users.sort(key=lambda u: u.get("created_at") or "", reverse=True)
        return pg_users

    # Fallback to MongoDB
    try:
        if db is not None:
            return await db.users.find({"is_admin": {"$ne": True}}, {"_id": 0}).to_list(2000)
    except Exception:
        pass
    return []

async def supa_get_user_for_reset(email: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT id, email FROM users WHERE email = $1 LIMIT 1", email.lower())
                return _pg_row(row)
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("id,email").eq("email", email.lower()).limit(1).execute())
            if r.data: return r.data[0]
        except Exception: pass
    try:
        return await db.users.find_one({"email": email.lower()}, {"_id": 0, "id": 1, "email": 1})
    except Exception:
        return None

async def supa_update_user_password(email: str, password_hash: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute("UPDATE users SET password_hash = $1 WHERE email = $2", password_hash, email.lower())
            _supa_mirror(lambda: supa.table("users").update({"password_hash": password_hash}).eq("email", email.lower()).execute())
            return
        except Exception as e:
            logger.warning(f"pg supa_update_user_password failed: {e}")
    if supa:
        try:
            await _supa(lambda: supa.table("users").update({"password_hash": password_hash}).eq("email", email.lower()).execute())
            return
        except Exception: pass
    try:
        await db.users.update_one({"email": email.lower()}, {"$set": {"password_hash": password_hash}})
    except Exception: pass

async def supa_count_users():
    """Count users from both PG and Supabase, returning the larger (most complete) count."""
    pg_count = 0
    supa_count = 0
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                pg_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_admin = FALSE") or 0
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("id", count="exact").neq("is_admin", True).execute())
            supa_count = r.count if r.count is not None else len(r.data or [])
        except Exception: pass
    if pg_count or supa_count:
        return max(pg_count, supa_count)
    try:
        if db is not None:
            return await db.users.count_documents({"is_admin": {"$ne": True}})
    except Exception: pass
    return 0

async def supa_get_users_by_ids(user_ids: list):
    if not user_ids:
        return []
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, name, email, plan, avatar_url, board_name, class_name, stream_name FROM users WHERE id = ANY($1::text[])",
                    user_ids
                )
                return _pg_rows(rows)
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select(
                "id,name,email,plan,avatar_url,board_name,class_name,stream_name"
            ).in_("id", user_ids).execute())
            return r.data
        except Exception: pass
    try:
        return await db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "plan": 1, "avatar_url": 1,
             "board_name": 1, "class_name": 1, "stream_name": 1}
        ).to_list(len(user_ids))
    except Exception:
        return []

# ─────────────────────────────────────────────
# CONVERSATION OPERATIONS  (Supabase = metadata, MongoDB = full content)
# ─────────────────────────────────────────────

async def supa_get_conversations(uid: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, title, preview, subject_id, subject_name, starred, archived,
                              tokens, created_at, updated_at
                       FROM conversations WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 200""",
                    uid
                )
                return _pg_rows(rows)
        except Exception as e:
            logger.warning(f"pg supa_get_conversations failed: {e}")
    if supa:
        try:
            r = await _supa(lambda: supa.table("conversations").select(
                "id,title,preview,subject_id,subject_name,starred,archived,tokens,created_at,updated_at"
            ).eq("user_id", uid).order("updated_at", desc=True).limit(200).execute())
            return r.data
        except Exception: pass
    try:
        return await db.conversations.find({"user_id": uid}, {"_id": 0, "messages": 0}).sort("updated_at", -1).to_list(200)
    except Exception:
        return []

async def supa_get_conversation(conv_id: str, uid: str):
    _ck = _conv_cache_key(conv_id, uid)
    if _ck in _conv_cache:
        return _conv_cache[_ck]
    cached = _redis_get_conversation(conv_id, uid)
    if cached:
        _conv_cache[_ck] = cached
        return cached

    async def _pg_fetch():
        if not _deps_mod.pg_pool:
            return None
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM conversations WHERE id = $1 AND user_id = $2 LIMIT 1",
                    conv_id, uid
                )
                return _pg_row(row)
        except Exception as e:
            logger.warning(f"pg supa_get_conversation failed: {e}")
            return None

    async def _mongo_fetch():
        try:
            return await db.conversations.find_one({"id": conv_id, "user_id": uid}, {"_id": 0})
        except Exception:
            return None

    import asyncio
    pg_result, mongo_result = await asyncio.gather(_pg_fetch(), _mongo_fetch(), return_exceptions=True)
    result = None
    if pg_result and not isinstance(pg_result, Exception):
        result = pg_result
    elif mongo_result and not isinstance(mongo_result, Exception):
        result = mongo_result

    if result is None and supa:
        try:
            r = await _supa(lambda: supa.table("conversations").select("*").eq("id", conv_id).eq("user_id", uid).limit(1).execute())
            if r.data:
                result = r.data[0]
                if isinstance(result.get("messages"), str):
                    try: result["messages"] = json.loads(result["messages"])
                    except: result["messages"] = []
        except Exception: pass
    if result:
        _conv_cache[_conv_cache_key(conv_id, uid)] = result
        _redis_cache_conversation(conv_id, uid, result)
    return result

async def supa_upsert_conversation(conv: dict):
    _invalidate_conv_cache(conv.get("id",""), conv.get("user_id",""))
    _redis_invalidate_conversation(conv.get("id",""), conv.get("user_id",""))
    if _deps_mod.pg_pool:
        try:
            msgs = json.dumps(conv.get("messages", [])) if isinstance(conv.get("messages"), list) else (conv.get("messages") or "[]")
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO conversations (id, user_id, title, preview, subject_id, subject_name,
                       starred, archived, messages, tokens, created_at, updated_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                       ON CONFLICT (id) DO UPDATE SET
                         title=EXCLUDED.title, preview=EXCLUDED.preview,
                         subject_id=EXCLUDED.subject_id, subject_name=EXCLUDED.subject_name,
                         starred=EXCLUDED.starred, archived=EXCLUDED.archived,
                         messages=EXCLUDED.messages, tokens=EXCLUDED.tokens,
                         updated_at=EXCLUDED.updated_at""",
                    conv.get("id",""), conv.get("user_id",""),
                    conv.get("title","New Chat"), conv.get("preview",""),
                    conv.get("subject_id"), conv.get("subject_name"),
                    conv.get("starred",False), conv.get("archived",False),
                    msgs, conv.get("tokens",0),
                    conv.get("created_at",""), conv.get("updated_at","")
                )
            _mirror_fields = {"id","user_id","title","preview","subject_id","subject_name","starred","archived","messages","tokens","created_at","updated_at"}
            _mirror_data = {}
            for k, v in conv.items():
                if k not in _mirror_fields:
                    continue
                if k == "messages" and isinstance(v, list):
                    _mirror_data[k] = json.dumps(v)
                else:
                    _mirror_data[k] = v
            _supa_mirror(lambda d=_mirror_data: supa.table("conversations").upsert(d).execute())
            return
        except Exception as e:
            logger.warning(f"pg supa_upsert_conversation failed: {e}")
    if supa:
        try:
            allowed = {"id","user_id","title","preview","subject_id","subject_name","starred","archived","messages","tokens","created_at","updated_at"}
            c = {k: v for k, v in conv.items() if k in allowed}
            if isinstance(c.get("messages"), list): c["messages"] = json.dumps(c["messages"])
            await _supa(lambda: supa.table("conversations").upsert(c).execute()); return
        except Exception as e:
            logger.warning(f"supa_upsert_conversation failed: {e}")
    try:
        await db.conversations.replace_one({"id": conv["id"]}, conv, upsert=True)
    except Exception as e:
        logger.warning(f"All stores failed for upsert_conversation: {e}")

async def supa_update_conversation(conv_id: str, uid: str, updates: dict):
    _invalidate_conv_cache(conv_id, uid)
    _redis_invalidate_conversation(conv_id, uid)
    if _deps_mod.pg_pool and updates:
        try:
            u = {k: v for k, v in updates.items() if k in _ALLOWED_CONV_COLUMNS}
            unknown = set(updates) - _ALLOWED_CONV_COLUMNS
            if unknown:
                raise ValueError(f"supa_update_conversation: disallowed column(s): {unknown}")
            if isinstance(u.get("messages"), list): u["messages"] = json.dumps(u["messages"])
            if isinstance(u.get("metadata"), dict): u["metadata"] = json.dumps(u["metadata"])
            if u:
                cols = [f"{_quote_ident(k)} = ${i}" for i, k in enumerate(u.keys(), start=1)]
                vals = list(u.values()) + [conv_id, uid]
                sql = f"UPDATE conversations SET {', '.join(cols)} WHERE id = ${len(vals)-1} AND user_id = ${len(vals)}"
                async with _deps_mod.pg_pool.acquire() as conn:
                    await conn.execute(sql, *vals)
            if supa:
                _supa_allowed = {"title","preview","subject_id","subject_name","starred","archived","messages","tokens","updated_at","metadata"}
                _su = {k: v for k, v in updates.items() if k in _supa_allowed}
                if isinstance(_su.get("messages"), list): _su["messages"] = json.dumps(_su["messages"])
                if _su:
                    _supa_mirror(lambda d=_su, cid=conv_id, u=uid: supa.table("conversations").update(d).eq("id", cid).eq("user_id", u).execute())
            return
        except Exception as e:
            logger.warning(f"pg supa_update_conversation failed: {e}")
    if supa:
        try:
            allowed = {"title","preview","subject_id","subject_name","starred","archived","messages","tokens","updated_at","metadata"}
            u = {k: v for k, v in updates.items() if k in allowed}
            if isinstance(u.get("messages"), list): u["messages"] = json.dumps(u["messages"])
            if u:
                await _supa(lambda: supa.table("conversations").update(u).eq("id", conv_id).eq("user_id", uid).execute())
            return
        except Exception as e:
            logger.warning(f"supa_update_conversation failed: {e}")
    try:
        await db.conversations.update_one({"id": conv_id, "user_id": uid}, {"$set": updates})
    except Exception: pass

async def supa_delete_conversation(conv_id: str, uid: str):
    _redis_invalidate_conversation(conv_id, uid)
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute("DELETE FROM conversations WHERE id = $1 AND user_id = $2", conv_id, uid)
            _supa_mirror(lambda: supa.table("conversations").delete().eq("id", conv_id).eq("user_id", uid).execute())
            return
        except Exception: pass
    if supa:
        try: await _supa(lambda: supa.table("conversations").delete().eq("id", conv_id).eq("user_id", uid).execute()); return
        except Exception: pass
    try:
        await db.conversations.delete_one({"id": conv_id, "user_id": uid})
    except Exception: pass

async def supa_count_conversations():
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                return await conn.fetchval("SELECT COUNT(*) FROM conversations")
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("conversations").select("id", count="exact").execute())
            return r.count if r.count is not None else len(r.data)
        except Exception: pass
    try:
        return await db.conversations.count_documents({})
    except Exception:
        return 0

async def supa_get_all_conversations(limit: int = 200):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT $1", limit)
                result = _pg_rows(rows)
                return result
        except Exception as e:
            logger.warning(f"pg supa_get_all_conversations failed: {e}")
    if supa:
        try:
            r = await _supa(lambda: supa.table("conversations").select("*").order("updated_at", desc=True).limit(limit).execute())
            for row in r.data:
                if isinstance(row.get("messages"), str):
                    try: row["messages"] = json.loads(row["messages"])
                    except: row["messages"] = []
            return r.data
        except Exception as e:
            logger.warning(f"supa_get_all_conversations failed: {e}")
    try:
        return await db.conversations.find({}, {"_id": 0}).sort("updated_at", -1).to_list(limit)
    except Exception:
        return []

# ─────────────────────────────────────────────
# APP SETTINGS  (Supabase layer)
# ─────────────────────────────────────────────

async def supa_get_settings():
    defaults = {"registrations_open": True, "maintenance_mode": False, "app_name": "Syrabit.ai", "tagline": "AI-Powered Exam Prep"}
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM app_settings WHERE id = 1 LIMIT 1")
                if row: return {**defaults, **dict(row)}
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("app_settings").select("*").eq("id", 1).limit(1).execute())
            if r.data: return {**defaults, **r.data[0]}
        except Exception: pass
    try:
        s = await db.settings.find_one({}, {"_id": 0})
        return {**defaults, **(s or {})}
    except Exception:
        return defaults

async def supa_update_settings(updates: dict):
    if _deps_mod.pg_pool and updates:
        try:
            unknown = set(updates) - _ALLOWED_SETTINGS_COLUMNS
            if unknown:
                raise ValueError(f"supa_update_settings: disallowed column(s): {unknown}")
            cols = [f"{_quote_ident(k)} = ${i}" for i, k in enumerate(updates.keys(), start=1)]
            vals = list(updates.values())
            sql = f"UPDATE app_settings SET {', '.join(cols)} WHERE id = 1"
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(sql, *vals)
            return
        except Exception: pass
    if supa:
        try: await _supa(lambda: supa.table("app_settings").update(updates).eq("id", 1).execute()); return
        except Exception: pass
    try:
        await db.settings.update_one({}, {"$set": updates}, upsert=True)
    except Exception: pass

# ─────────────────────────────────────────────
# PASSWORD RESETS  (Supabase layer)
# ─────────────────────────────────────────────

async def supa_create_password_reset(token: str, email: str, expires: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO password_resets (token, email, expires) VALUES ($1, $2, $3) ON CONFLICT (token) DO UPDATE SET email=EXCLUDED.email, expires=EXCLUDED.expires",
                    token, email.lower(), expires
                )
            return
        except Exception as e:
            logger.warning(f"pg supa_create_password_reset failed: {e}")
    if supa:
        try:
            await _supa(lambda: supa.table("password_resets").upsert(
                {"token": token, "email": email.lower(), "expires": expires}, on_conflict="email"
            ).execute()); return
        except Exception as e:
            logger.warning(f"supa_create_password_reset failed: {e}")
    try:
        await db.password_resets.replace_one({"email": email.lower()}, {"email": email.lower(), "token": token, "expires": expires}, upsert=True)
    except Exception: pass

async def supa_get_password_reset(token: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM password_resets WHERE token = $1 LIMIT 1", token)
                return _pg_row(row)
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("password_resets").select("*").eq("token", token).limit(1).execute())
            if r.data: return r.data[0]
        except Exception: pass
    try:
        return await db.password_resets.find_one({"token": token}, {"_id": 0})
    except Exception:
        return None

async def supa_delete_password_reset(token: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute("DELETE FROM password_resets WHERE token = $1", token)
            return
        except Exception: pass
    if supa:
        try: await _supa(lambda: supa.table("password_resets").delete().eq("token", token).execute()); return
        except Exception: pass
    try:
        await db.password_resets.delete_one({"token": token})
    except Exception: pass

# ─────────────────────────────────────────────
# ACTIVITY LOG + NOTIFICATIONS  (Supabase / Admin layer)
# ─────────────────────────────────────────────

async def supa_get_activity_logs(limit: int = 200):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM activity_log ORDER BY created_at DESC LIMIT $1", limit)
                return _pg_rows(rows)
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("activity_log").select("*").order("created_at", desc=True).limit(limit).execute())
            return r.data
        except Exception: pass
    try:
        return await db.activity_log.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    except Exception:
        return []

async def supa_insert_activity_log(entry: dict):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO activity_log (id, action, details, level, admin_name, admin_email, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (id) DO NOTHING""",
                    entry.get("id", str(uuid.uuid4())), entry.get("action",""),
                    entry.get("details",""), entry.get("level","info"),
                    entry.get("admin_name",""), entry.get("admin_email",""),
                    entry.get("created_at", datetime.now(timezone.utc).isoformat())
                )
            return
        except Exception as e:
            logger.warning(f"pg supa_insert_activity_log failed: {e}")
    if supa:
        try:
            allowed = {"id", "action", "details", "level", "admin_name", "admin_email", "created_at"}
            await _supa(lambda: supa.table("activity_log").insert({k: v for k, v in entry.items() if k in allowed}).execute()); return
        except Exception as e:
            logger.warning(f"supa_insert_activity_log failed: {e}")
    try:
        await db.activity_log.insert_one(entry)
    except Exception: pass

async def supa_clear_activity_log():
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute("DELETE FROM activity_log")
            return
        except Exception: pass
    if supa:
        try:
            await _supa(lambda: supa.table("activity_log").delete().neq("id", "").execute()); return
        except Exception: pass
    try:
        await db.activity_log.delete_many({})
    except Exception: pass

async def supa_get_notifications(limit: int = 100):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM notifications ORDER BY created_at DESC LIMIT $1", limit)
                return _pg_rows(rows)
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("notifications").select("*").order("created_at", desc=True).limit(limit).execute())
            return r.data
        except Exception: pass
    try:
        return await db.notifications.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    except Exception:
        return []

async def supa_insert_notification(notif: dict):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO notifications (id, title, message, type, audience, status, sent_at, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (id) DO NOTHING""",
                    notif.get("id", str(uuid.uuid4())), notif.get("title",""),
                    notif.get("message",""), notif.get("type","info"),
                    notif.get("audience","all"), notif.get("status","sent"),
                    notif.get("sent_at"), notif.get("created_at", datetime.now(timezone.utc).isoformat())
                )
            return
        except Exception as e:
            logger.warning(f"pg supa_insert_notification failed: {e}")
    if supa:
        try:
            allowed = {"id", "title", "message", "type", "audience", "status", "sent_at", "created_at"}
            await _supa(lambda: supa.table("notifications").insert({k: v for k, v in notif.items() if k in allowed}).execute()); return
        except Exception as e:
            logger.warning(f"supa_insert_notification failed: {e}")
    try:
        await db.notifications.insert_one(notif)
    except Exception: pass

async def supa_delete_notification(notif_id: str):
    if _deps_mod.pg_pool:
        try:
            async with _deps_mod.pg_pool.acquire() as conn:
                await conn.execute("DELETE FROM notifications WHERE id = $1", notif_id)
            return
        except Exception: pass
    if supa:
        try: await _supa(lambda: supa.table("notifications").delete().eq("id", notif_id).execute()); return
        except Exception: pass
    try:
        await db.notifications.delete_one({"id": notif_id})
    except Exception: pass
