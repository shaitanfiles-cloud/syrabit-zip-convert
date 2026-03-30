"""
Syrabit.ai Backend - FastAPI + MongoDB
AHSEC AI-Powered Educational Platform
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, BackgroundTasks, File, UploadFile, Form, Response, Cookie, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pathlib import Path
import os, uuid, base64, logging, hashlib, hmac, json, re, asyncio, httpx, warnings, time, sys, html as _html_mod, contextvars
try:
    from user_agents import parse as _parse_ua
except ImportError:
    _parse_ua = None
import mistune as _mistune
warnings.filterwarnings("ignore", message=".*__about__.*")
import cachetools
import ga4_client
import vertex_services
import email_templates


# ─────────────────────────────────────────────
# STRUCTURED JSON LOGGING
# ─────────────────────────────────────────────
class _JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        return json.dumps(log_entry, default=str)


def _configure_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in root.handlers[:]:
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root.addHandler(handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)


_configure_logging()


# ─────────────────────────────────────────────
# ENVIRONMENT VALIDATION (fail-fast)
# ─────────────────────────────────────────────
def _validate_env():
    _required = {
        "MONGO_URL": "MongoDB connection string (content/RAG database)",
        "JWT_SECRET": "JWT signing secret for user auth tokens",
        "ADMIN_JWT_SECRET": "JWT signing secret for admin auth tokens",
        "ADMIN_PASSWORDS": "Comma-separated admin account passwords",
    }
    _recommended = {
        "GROQ_API_KEY": "Groq LLM API key (primary AI provider)",
        "SARVAM_API_KEY": "Sarvam AI API key (fallback LLM + translation)",
    }
    missing = []
    for key, desc in _required.items():
        val = os.environ.get(key, "").strip()
        if not val or val.startswith("CHANGE_ME") or val.startswith("change-"):
            missing.append(f"  - {key}: {desc}")
    if missing:
        _log = logging.getLogger("syrabit.startup")
        _log.critical("STARTUP FAILED — missing required environment variables:\n" + "\n".join(missing))
        sys.exit(1)
    _log = logging.getLogger("syrabit.startup")
    for key, desc in _recommended.items():
        val = os.environ.get(key, "").strip()
        if not val:
            _log.warning(f"Recommended env var not set: {key} — {desc}")
    _log.info("Environment validation passed")


_validate_env()
try:
    import asyncpg as _asyncpg
except ImportError:
    _asyncpg = None
# upstash redis – installed via pip
try:
    from upstash_redis import Redis as _UpstashRedis
except ImportError:
    _UpstashRedis = None
# supabase – installed via pip
try:
    from supabase import create_client as _create_supa  # noqa: F401 (used below)
except ImportError:
    _create_supa = None  # type: ignore
from passlib.context import CryptContext
import jwt
from jwt.exceptions import PyJWTError as JWTError
# emergentintegrations for Universal LLM Key
from emergentintegrations.llm.chat import LlmChat, UserMessage

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

MONGO_URL    = (os.environ.get('MONGO_URL') or os.environ.get('MONGODB_URI') or 'mongodb://localhost:27017').strip().strip('"').strip("'")
DB_NAME      = os.environ.get('DB_NAME', 'test_database')
JWT_SECRET   = os.environ.get('JWT_SECRET') or os.urandom(48).hex()
JWT_ALGORITHM    = 'HS256'
JWT_ACCESS_EXPIRE_MINUTES = int(os.environ.get('JWT_ACCESS_EXPIRE_MINUTES', '60'))
JWT_REFRESH_EXPIRE_MINUTES = int(os.environ.get('JWT_REFRESH_EXPIRE_MINUTES', str(60 * 24 * 30)))
JWT_EXPIRE_MINUTES = JWT_ACCESS_EXPIRE_MINUTES
ADMIN_JWT_SECRET = os.environ.get('ADMIN_JWT_SECRET') or os.urandom(48).hex()

# ── Email Configuration ───────────────────────────────────────────────────────
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '').strip()
EMAIL_FROM     = os.environ.get('EMAIL_FROM', 'noreply@syrabit.ai').strip()
FRONTEND_URL   = os.environ.get('FRONTEND_URL', 'https://syrabit.ai').strip().rstrip('/')

# ── LLM Configuration ─────────────────────────────────────────────────────────
_GROQ_KEY = os.environ.get('GROQ_API_KEY', '')
_GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
_XAI_KEY = os.environ.get('XAI_API_KEY', '').strip()
_OPENAI_KEY = os.environ.get('OPENAI_API_KEY', '')
_FIREWORKS_KEY = os.environ.get('FIREWORKS_API_KEY', '')
_SARVAM_LLM_KEY = os.environ.get('SARVAM_API_KEY', '').strip()
_EXPLICIT_PROVIDER = os.environ.get('LLM_PROVIDER', '').strip().lower()
_AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY_ID', '').strip()
_AWS_SECRET_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '').strip()
_AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1').strip()

if _EXPLICIT_PROVIDER == 'sarvam' and _SARVAM_LLM_KEY:
    LLM_PROVIDER = 'sarvam'
    LLM_API_KEY = _SARVAM_LLM_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'sarvam-m')
elif _EXPLICIT_PROVIDER == 'fireworksai' and _FIREWORKS_KEY:
    LLM_PROVIDER = 'fireworksai'
    LLM_API_KEY = _FIREWORKS_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'accounts/fireworks/models/qwen2p5-72b-instruct')
elif _EXPLICIT_PROVIDER == 'openai' and _OPENAI_KEY and _OPENAI_KEY != 'x':
    LLM_PROVIDER = 'openai'
    LLM_API_KEY = _OPENAI_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
elif _EXPLICIT_PROVIDER == 'groq' and _GROQ_KEY and _GROQ_KEY != 'x':
    LLM_PROVIDER = 'groq'
    LLM_API_KEY = _GROQ_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'llama-3.1-8b-instant')
elif _SARVAM_LLM_KEY:
    LLM_PROVIDER = 'sarvam'
    LLM_API_KEY = _SARVAM_LLM_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'sarvam-m')
elif _FIREWORKS_KEY:
    LLM_PROVIDER = 'fireworksai'
    LLM_API_KEY = _FIREWORKS_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'accounts/fireworks/models/qwen2p5-72b-instruct')
elif _GROQ_KEY and _GROQ_KEY != 'x':
    LLM_PROVIDER = 'groq'
    LLM_API_KEY = _GROQ_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'llama-3.1-8b-instant')
elif _OPENAI_KEY and _OPENAI_KEY != 'x':
    LLM_PROVIDER = 'openai'
    LLM_API_KEY = _OPENAI_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
else:
    LLM_PROVIDER = 'groq'
    LLM_API_KEY = ''
    LLM_MODEL = os.environ.get('LLM_MODEL', 'llama-3.1-8b-instant')
OPENAI_API_KEY = LLM_API_KEY

# ── Sarvam AI Configuration ──────────────────────────────────────────────────
SARVAM_API_KEY = os.environ.get('SARVAM_API_KEY', '').strip()
SARVAM_BASE_URL = 'https://api.sarvam.ai'

# ── Redis (Upstash) ──────────────────────────────────────────────────────────
_upstash_url   = os.environ.get('UPSTASH_REDIS_REST_URL', '').strip().strip('"').strip("'")
_upstash_token = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '').strip().strip('"').strip("'")
_fallback_url  = os.environ.get('REDIS_URL', '').strip().strip('"').strip("'")
# Auto-detect swap: if URL doesn't start with http but TOKEN does, swap them
if not _upstash_url.startswith('http') and _upstash_token.startswith('http'):
    _upstash_url, _upstash_token = _upstash_token, _upstash_url
REDIS_URL   = _upstash_url if _upstash_url.startswith('http') else _fallback_url
REDIS_TOKEN = _upstash_token
redis_client: Optional[Any] = None
try:
    if _UpstashRedis and REDIS_URL and REDIS_TOKEN:
        redis_client = _UpstashRedis(url=REDIS_URL, token=REDIS_TOKEN)
        redis_client.ping()
except Exception as _redis_err:
    redis_client = None
    logging.getLogger(__name__).warning(f"Redis ping failed: {_redis_err}")

# ── AI Response Cache ────────────────────────────────────────────────────────
_ai_response_cache = cachetools.TTLCache(maxsize=512, ttl=3600)

# ── User Object Cache ─────────────────────────────────────────────────────────
# Keyed by user_id, 120-second TTL — eliminates DB round-trip on every auth'd request
_user_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=2000, ttl=120)

def _invalidate_user_cache(uid: str):
    _user_cache.pop(uid, None)

# ── Conversation Object Cache ──────────────────────────────────────────────────
# Keyed by "conv_id:uid", 60-second TTL — avoids PG on every chat turn
_conv_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=4000, ttl=60)

def _conv_cache_key(conv_id: str, uid: str) -> str:
    return f"{conv_id}:{uid}"

def _invalidate_conv_cache(conv_id: str, uid: str):
    _conv_cache.pop(_conv_cache_key(conv_id, uid), None)

# ── RAG Result Cache ───────────────────────────────────────────────────────────
# Keyed by (query_hash, subject_id), 600-second TTL — skips 3 MongoDB queries on repeat
import hashlib as _hashlib
_rag_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=1024, ttl=600)

# Vector RAG cache — 300-second TTL (Gemini embed API calls are expensive to re-run)
_vector_rag_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=300)

# Content card cache — 180-second TTL (avoids duplicate seo_pages + chapters queries)
_content_card_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=180)

def _content_card_cache_key(query: str, subject_id: Optional[str], subject_name: Optional[str]) -> str:
    raw = f"{query.strip().lower()}|{subject_id or ''}|{subject_name or ''}"
    return _hashlib.md5(raw.encode()).hexdigest()

# Syllabus cache — 30-minute TTL; syllabi almost never change between requests
_syllabus_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=256, ttl=1800)

def _syllabus_cache_key(board_id: str, class_id: str, stream_id: Optional[str], subject_id: Optional[str] = None) -> str:
    return f"{board_id}|{class_id}|{stream_id or ''}|{subject_id or ''}"

def _rag_cache_key(query: str, subject_id: Optional[str], subject_name: Optional[str]) -> str:
    raw = f"{query.strip().lower()}|{subject_id or ''}|{subject_name or ''}"
    return _hashlib.md5(raw.encode()).hexdigest()

def _vector_rag_cache_key(query: str, subject_id: Optional[str], top_k: int) -> str:
    raw = f"{query.strip().lower()}|{subject_id or ''}|{top_k}"
    return _hashlib.md5(raw.encode()).hexdigest()

REDIS_AI_CACHE_TTL = 3600
REDIS_CASUAL_CACHE_TTL = 300
REDIS_CHAT_CACHE_TTL = 600
REDIS_SEARCH_CACHE_TTL = 300
REDIS_SESSION_CACHE_TTL = 1800
REDIS_RATE_WINDOW = 60

_redis_miss_count = 0
_redis_hit_count = 0

def _cache_key(query: str, subject_id: str = "", board_id: str = "") -> str:
    normalized = f"{query.lower().strip()}|{subject_id or ''}|{board_id or ''}"
    return hashlib.md5(normalized.encode()).hexdigest()

def _redis_get(prefix: str, key: str) -> Optional[str]:
    global _redis_hit_count, _redis_miss_count
    if redis_client:
        try:
            val = redis_client.get(f"{prefix}:{key}")
            if val is not None:
                _redis_hit_count += 1
                return val
            _redis_miss_count += 1
        except Exception as e:
            logger.debug(f"Redis GET {prefix}:{key} failed: {e}")
    return None

def _redis_set(prefix: str, key: str, value: str, ttl: int):
    if redis_client:
        try:
            redis_client.set(f"{prefix}:{key}", value, ex=ttl)
        except Exception as e:
            logger.debug(f"Redis SET {prefix}:{key} failed: {e}")

def _redis_del(prefix: str, key: str):
    if redis_client:
        try:
            redis_client.delete(f"{prefix}:{key}")
        except Exception:
            pass

def _redis_get_ai_cache(key: str) -> Optional[str]:
    return _redis_get("ai_cache", key)

def _redis_set_ai_cache(key: str, value: str):
    _redis_set("ai_cache", key, value, REDIS_AI_CACHE_TTL)

def _redis_cache_conversation(conv_id: str, user_id: str, conv_data: dict):
    _redis_set("chat", f"{conv_id}:{user_id}", json.dumps(conv_data, default=str), REDIS_CHAT_CACHE_TTL)

def _redis_get_conversation(conv_id: str, user_id: str) -> Optional[dict]:
    val = _redis_get("chat", f"{conv_id}:{user_id}")
    if val:
        try:
            return json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass
    return None

def _redis_invalidate_conversation(conv_id: str, user_id: str):
    _redis_del("chat", f"{conv_id}:{user_id}")

def _redis_cache_search(query_hash: str, results: list):
    _redis_set("search", query_hash, json.dumps(results, default=str), REDIS_SEARCH_CACHE_TTL)

def _redis_get_search(query_hash: str) -> Optional[list]:
    val = _redis_get("search", query_hash)
    if val:
        try:
            return json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass
    return None

def _redis_cache_session(user_id: str, session_data: dict):
    _redis_set("session", user_id, json.dumps(session_data, default=str), REDIS_SESSION_CACHE_TTL)

def _redis_get_session(user_id: str) -> Optional[dict]:
    val = _redis_get("session", user_id)
    if val:
        try:
            return json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass
    return None

def _redis_invalidate_session(user_id: str):
    _redis_del("session", user_id)
    _invalidate_user_cache(str(user_id))


# ── Slow-query logging ────────────────────────────────────────────────────────
SLOW_QUERY_THRESHOLD_MS = float(os.environ.get("SLOW_QUERY_THRESHOLD_MS", "200"))

class _SlowQueryTimer:
    __slots__ = ("_label", "_t0")
    def __init__(self, label: str):
        self._label = label
        self._t0 = 0.0
    async def __aenter__(self):
        self._t0 = _time_mod.time()
        return self
    async def __aexit__(self, *exc):
        elapsed_ms = (_time_mod.time() - self._t0) * 1000
        if elapsed_ms > SLOW_QUERY_THRESHOLD_MS:
            logger.warning(f"SLOW_QUERY {self._label} took {elapsed_ms:.0f}ms (threshold={SLOW_QUERY_THRESHOLD_MS}ms)")

def _slow_query(label: str) -> _SlowQueryTimer:
    return _SlowQueryTimer(label)

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL         = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '') or os.environ.get('SUPABASE_KEY', '')
SUPABASE_ANON_KEY    = os.environ.get('SUPABASE_ANON_KEY', '') or os.environ.get('SUPABASE_KEY', '')

# ── Cookie security (set SECURE_COOKIES=false in dev to allow HTTP) ───────────
SECURE_COOKIES  = os.environ.get('SECURE_COOKIES', 'true').lower() not in ('false', '0', 'no')
COOKIE_SAMESITE = "none" if SECURE_COOKIES else "lax"

_cors_raw = os.environ.get('CORS_ORIGINS', '').strip().strip('"').strip("'")
if not _cors_raw or _cors_raw == '*':
    CORS_ORIGINS = ["http://localhost", "http://localhost:80", "http://localhost:25144"]
    for _rd in os.environ.get('REPLIT_DOMAINS', '').split(','):
        _rd = _rd.strip()
        if _rd:
            CORS_ORIGINS.append(f"https://{_rd}")
    _CORS_ALLOW_CREDENTIALS = True
else:
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(',') if o.strip()]
    for _rd in os.environ.get('REPLIT_DOMAINS', '').split(','):
        _rd = _rd.strip()
        if _rd and f"https://{_rd}" not in CORS_ORIGINS:
            CORS_ORIGINS.append(f"https://{_rd}")
    _CORS_ALLOW_CREDENTIALS = True

# ── Admin accounts ────────────────────────────────────────────────────────────
# Admin accounts loaded from environment (no credentials in source code)
def _load_admin_accounts():
    emails    = [e.strip() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()]
    passwords = [p.strip().strip('"').strip("'") for p in os.environ.get('ADMIN_PASSWORDS', '').split(',') if p.strip()]
    names     = [n.strip() for n in os.environ.get('ADMIN_NAMES', '').split(',') if n.strip()]
    max_len = max(len(emails), len(passwords), len(names)) if emails else 0
    return [{"email": emails[i], "password": passwords[i], "name": names[i]}
            for i in range(min(len(emails), len(passwords), len(names)))]

ADMIN_ACCOUNTS = _load_admin_accounts()
ADMIN_EMAIL    = ADMIN_ACCOUNTS[0]["email"]    if ADMIN_ACCOUNTS else ""
ADMIN_PASSWORD = ADMIN_ACCOUNTS[0]["password"] if ADMIN_ACCOUNTS else ""


# ─────────────────────────────────────────────
# SETUP — MongoDB (content) + Supabase (users/convos)
# ─────────────────────────────────────────────
# MongoDB with fast timeout — wrapped so bad URLs don't crash startup
try:
    _raw_mongo_url = MONGO_URL.strip()
    if not (_raw_mongo_url.startswith("mongodb://") or _raw_mongo_url.startswith("mongodb+srv://")):
        raise ValueError(f"MONGO_URL has invalid scheme — must begin with mongodb:// or mongodb+srv://. Got: {_raw_mongo_url[:30]!r}...")
    mongo_client = AsyncIOMotorClient(
        _raw_mongo_url,
        serverSelectionTimeoutMS=20000,
        connectTimeoutMS=20000,
        socketTimeoutMS=45000,
        maxPoolSize=100,                  # up from 10 — support many concurrent requests
        minPoolSize=5,                    # pre-warm 5 connections at startup
        maxIdleTimeMS=120000,
        waitQueueTimeoutMS=10000,
        retryReads=True,
        retryWrites=True,
    )
    db = mongo_client[DB_NAME]
    logging.info("MongoDB client initialised (connection not yet verified)")
except Exception as _mongo_init_err:
    logging.warning(f"MongoDB client could not be initialised — content/RAG features disabled: {_mongo_init_err}")
    mongo_client = None  # type: ignore[assignment]
    db = None            # type: ignore[assignment]

_mongo_available = None
_mongo_last_check = 0.0
_MONGO_CHECK_COOLDOWN = 60

async def is_mongo_available():
    global _mongo_available, _mongo_last_check
    if db is None:
        return False
    now = _time_mod.time()
    if _mongo_available is not None and (now - _mongo_last_check) < _MONGO_CHECK_COOLDOWN:
        return _mongo_available
    try:
        await db.command("ping")
        _mongo_available = True
    except Exception:
        _mongo_available = False
    _mongo_last_check = now
    return _mongo_available

def mark_mongo_down():
    global _mongo_available, _mongo_last_check
    _mongo_available = False
    _mongo_last_check = _time_mod.time()

# Supabase client (sync, used for users/conversations)
from supabase import create_client as _create_supa
supa: Optional[Any] = None
try:
    if SUPABASE_SERVICE_KEY and _create_supa:
        _supa_client = _create_supa(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        _supa_client.table("users").select("id").limit(1).execute()
        supa = _supa_client
        logging.getLogger(__name__).info("Supabase client ready")
except Exception as _supa_err:
    supa = None
    _err_str = str(_supa_err)
    if "401" in _err_str or "Invalid API key" in _err_str:
        logging.getLogger(__name__).warning("Supabase API key invalid — using MongoDB only")
    else:
        logging.getLogger(__name__).warning(f"Supabase unavailable (using MongoDB only): {_supa_err}")

# ── Replit PostgreSQL (asyncpg pool) — primary relational store ──────────────
_PG_DSN = os.environ.get("DATABASE_URL", "")
pg_pool: Optional[Any] = None   # filled in lifespan startup

_PG_INIT_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT 'free',
    credits_used INTEGER NOT NULL DEFAULT 0,
    credits_limit INTEGER NOT NULL DEFAULT 30,
    document_access TEXT NOT NULL DEFAULT 'zero',
    onboarding_done BOOLEAN NOT NULL DEFAULT FALSE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'active',
    bio TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    saved_subjects JSONB NOT NULL DEFAULT '[]',
    has_free_credits_issued BOOLEAN NOT NULL DEFAULT TRUE,
    board_id TEXT,
    board_name TEXT,
    class_id TEXT,
    class_name TEXT,
    stream_id TEXT,
    stream_name TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'New Chat',
    preview TEXT NOT NULL DEFAULT '',
    subject_id TEXT,
    subject_name TEXT,
    starred BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    messages TEXT NOT NULL DEFAULT '[]',
    tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS conversations_user_id_idx ON conversations(user_id);
CREATE INDEX IF NOT EXISTS conversations_id_user_idx ON conversations(id, user_id);
CREATE INDEX IF NOT EXISTS conversations_updated_idx ON conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS users_email_idx ON users(email);
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    registrations_open BOOLEAN NOT NULL DEFAULT TRUE,
    maintenance_mode BOOLEAN NOT NULL DEFAULT FALSE,
    app_name TEXT NOT NULL DEFAULT 'Syrabit.ai',
    tagline TEXT NOT NULL DEFAULT 'AI-Powered Exam Prep'
);
INSERT INTO app_settings(id) VALUES(1) ON CONFLICT(id) DO NOTHING;
CREATE TABLE IF NOT EXISTS password_resets (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_log (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'info',
    admin_name TEXT NOT NULL DEFAULT '',
    admin_email TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT 'info',
    audience TEXT NOT NULL DEFAULT 'all',
    status TEXT NOT NULL DEFAULT 'sent',
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT ''
);
"""

async def _init_pg_pool():
    global pg_pool
    if not _asyncpg or not _PG_DSN:
        logging.getLogger(__name__).warning("[WARN] Replit PostgreSQL not configured — asyncpg disabled")
        return
    try:
        pg_pool = await _asyncpg.create_pool(_PG_DSN, min_size=10, max_size=50)
        async with pg_pool.acquire() as conn:
            await conn.execute(_PG_INIT_SQL)
        logging.getLogger(__name__).info("Replit PostgreSQL pool ready — tables created/verified")
    except Exception as _pg_err:
        pg_pool = None
        logging.getLogger(__name__).warning(f"Replit PostgreSQL unavailable: {_pg_err}")

# sarvam-m embeds <think>…</think> in content before the real answer.
# The think block averages 800-1500 tokens on complex exam Q&A.
# We add this buffer on top of the user's plan max_tokens so the real answer
# is never crowded out. The buffer tokens are stripped before crediting.
SARVAM_THINK_BUFFER = 80     # tight think budget — answer starts sooner

# ── Sarvam AI — two persistent pooled HTTP/2 clients ─────────────────────────
# Client A: translation / TTS / transliterate (short read timeout, 30s)
# Client B: LLM chat (sarvam-m: ~124ms TTFT, full stream < 30s for 4096 tokens)
_sarvam_pool_limits = httpx.Limits(
    max_keepalive_connections=100,        # up from 50
    max_connections=200,                  # up from 100
    keepalive_expiry=120,                 # up from 60 — reuse connections longer
)
_sarvam_timeout       = httpx.Timeout(connect=3.0, read=30.0, write=10.0, pool=5.0)
_sarvam_llm_timeout   = httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=5.0)
_sarvam_headers = {
    'api-subscription-key': SARVAM_API_KEY,
    'Content-Type': 'application/json',
}
sarvam_client: Optional[httpx.AsyncClient] = None      # translation / TTS / transliterate
sarvam_llm_client: Optional[httpx.AsyncClient] = None  # LLM chat (long-lived streaming)
if SARVAM_API_KEY:
    sarvam_client = httpx.AsyncClient(
        base_url=SARVAM_BASE_URL,
        headers=_sarvam_headers,
        limits=_sarvam_pool_limits,
        timeout=_sarvam_timeout,
        http2=True,
        verify=True,
    )
    sarvam_llm_client = httpx.AsyncClient(
        base_url=SARVAM_BASE_URL,
        headers={**_sarvam_headers, 'Accept': 'text/event-stream'},
        limits=_sarvam_pool_limits,
        timeout=_sarvam_llm_timeout,
        http2=True,
        verify=True,
    )
    logging.getLogger(__name__).info("Sarvam AI client ready (HTTP/2 pooled, dual-client)")
else:
    logging.getLogger(__name__).warning("SARVAM_API_KEY not set — Sarvam features disabled")

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

logger = logging.getLogger(__name__)

# ── CMS request context guard ─────────────────────────────────────────────────
# Set to True during /cms/{user_id}/* request processing so that web-search /
# library-scrape functions can detect and refuse outbound calls made in this context.
_cms_request_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar("_cms_request_ctx", default=False)


def _assert_not_cms_context(operation: str = "web search"):
    """Raise HTTPException 403 if called from within a CMS personalized-plan request."""
    if _cms_request_ctx.get():
        raise HTTPException(
            status_code=403,
            detail=f"Outbound {operation} is not permitted in personalized CMS context.",
        )


_rate_cleanup_task = None

async def _migrate_supabase_users_to_pg():
    """One-time background task: copy all Supabase users into PG (upsert, safe to re-run)."""
    if not pg_pool or not supa:
        return
    await asyncio.sleep(5)  # let pool fully stabilise
    try:
        r = await _supa(lambda: supa.table("users").select("*").order("created_at", desc=False).limit(2000).execute())
        users = r.data or []
        imported = 0
        for u in users:
            try:
                saved = json.dumps(u.get("saved_subjects") or [])
                async with pg_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO users (id, name, email, password_hash, plan, credits_used,
                           credits_limit, document_access, onboarding_done, is_admin, status,
                           bio, phone, avatar_url, saved_subjects, has_free_credits_issued,
                           board_id, board_name, class_id, class_name, stream_id, stream_name,
                           created_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
                           ON CONFLICT (id) DO NOTHING""",
                        u.get("id"), u.get("name",""), u.get("email","").lower(), u.get("password_hash",""),
                        u.get("plan","free"), u.get("credits_used",0) or 0, u.get("credits_limit",30) or 30,
                        u.get("document_access","zero"), bool(u.get("onboarding_done",False)),
                        bool(u.get("is_admin",False)), u.get("status","active") or "active",
                        u.get("bio","") or "", u.get("phone","") or "", u.get("avatar_url","") or "",
                        saved, bool(u.get("has_free_credits_issued",True)),
                        u.get("board_id"), u.get("board_name"), u.get("class_id"),
                        u.get("class_name"), u.get("stream_id"), u.get("stream_name"),
                        u.get("created_at")
                    )
                imported += 1
            except Exception:
                pass
        logger.info(f"[migration] Supabase→PG: processed {len(users)} users, inserted {imported} new rows")
    except Exception as e:
        logger.warning(f"[migration] Supabase→PG migration failed: {e}")

async def _heal_credits_limit():
    """Startup fix: correct credits_limit for users whose plan was upgraded but DB
    column was never updated (free-plan default of 30 stuck on Starter/Pro users)."""
    if not pg_pool:
        return
    await asyncio.sleep(8)  # run after the Supabase migration
    try:
        async with pg_pool.acquire() as conn:
            r = await conn.execute(
                """UPDATE users
                      SET credits_limit = CASE plan
                            WHEN 'pro'     THEN GREATEST(credits_limit, 4000)
                            WHEN 'starter' THEN GREATEST(credits_limit, 300)
                            ELSE credits_limit
                          END
                    WHERE (plan = 'pro'     AND credits_limit < 4000)
                       OR (plan = 'starter' AND credits_limit < 300)"""
            )
        logger.info(f"[migration] credits_limit heal: {r}")
    except Exception as e:
        logger.warning(f"[migration] credits_limit heal failed: {e}")


async def _load_ga4_from_db():
    """Load GA4 refresh token from api_config into os.environ if not set via Replit Secrets."""
    try:
        if not os.getenv("GA4_REFRESH_TOKEN"):
            cfg = await db.api_config.find_one({}, {"ga4": 1})
            token = (cfg or {}).get("ga4", {}).get("refresh_token", "")
            if token:
                os.environ["GA4_REFRESH_TOKEN"] = token
                logger.info("GA4 refresh token loaded from db.api_config")
    except Exception as e:
        logger.warning(f"GA4 db-load skipped: {e}")


async def lifespan(app):
    global _rate_cleanup_task
    await _init_pg_pool()
    try:
        await ensure_seeded()
        await db.chapters.create_index("subject_id")
        await db.subjects.create_index("stream_id")
        await db.streams.create_index("class_id")
        await db.classes.create_index("board_id")
        await db.chunks.create_index("chapter_id")
        try:
            await db.chunks.create_index([("content", "text")], name="chunks_content_text")
        except Exception:
            pass

        await db.analytics.create_index([("event_type", 1), ("timestamp", -1)])
        await db.analytics.create_index([("subject_id", 1), ("event_type", 1)])
        await db.analytics.create_index("user_id")
        await db.page_views.create_index([("date", 1), ("visitor_id", 1)])
        await db.page_views.create_index([("timestamp", -1)])
        await db.page_views.create_index("visitor_id")
        await db.page_views.create_index("session_id")
        await db.page_views.create_index([("is_bot", 1)])

        await db.sessions.create_index("session_id", unique=True, sparse=True)
        await db.sessions.create_index("visitor_id")
        await db.sessions.create_index([("last_ping", -1)])
        await db.sessions.create_index([("start_time", -1)])

        await db.users.create_index("email", unique=True, sparse=True)
        await db.users.create_index("id", unique=True)
        await db.conversations.create_index([("user_id", 1), ("updated_at", -1)])
        await db.conversations.create_index([("id", 1), ("user_id", 1)], unique=True)
        await db.password_resets.create_index("token", unique=True)
        await db.password_resets.create_index("expires_at", expireAfterSeconds=0)
        await db.activity_log.create_index([("created_at", -1)])
        await db.notifications.create_index([("created_at", -1)])
        await db.settings.create_index("id", unique=True, sparse=True)
        await db.payments.create_index("razorpay_payment_id", unique=True, sparse=True)
        await db.payments.create_index("stripe_session_id", unique=True, sparse=True)
        await db.payments.create_index([("user_id", 1), ("verified_at", -1)])
        await db.push_subscriptions.create_index("user_id")
        await db.push_subscriptions.create_index("endpoint", unique=True, sparse=True)

        # cms_documents — heavily queried by id, seo_slug, status, subject_id
        await db.cms_documents.create_index("id", unique=True, sparse=True)
        await db.cms_documents.create_index("seo_slug", unique=True, sparse=True)
        await db.cms_documents.create_index("status")
        await db.cms_documents.create_index("subject_id")
        await db.cms_documents.create_index([("board_id", 1), ("class_id", 1), ("subject_id", 1), ("status", 1)])
        await db.cms_documents.create_index([("updated_at", -1)])

        # topic_pyq_collections — looked up by chapter_id + subject_id
        await db.topic_pyq_collections.create_index("chapter_id")
        await db.topic_pyq_collections.create_index("subject_id")

        # ai_pyq_collections — same pattern as above (agentic pipeline)
        await db.ai_pyq_collections.create_index("chapter_id")
        await db.ai_pyq_collections.create_index("subject_id")

        # exam_schedule — queried by exam_date + active
        await db.exam_schedule.create_index([("exam_date", 1), ("active", 1)])

        try:
            await db.topics.create_index("chapter_id")
            await db.topics.create_index("status")
            await db.topics.create_index([("board_slug", 1), ("class_slug", 1), ("subject_slug", 1), ("slug", 1)])
            await db.seo_pages.create_index([("topic_id", 1), ("page_type", 1)])
            await db.seo_pages.create_index("status")
            await db.seo_pages.create_index([("board_slug", 1), ("class_slug", 1), ("subject_slug", 1), ("topic_slug", 1), ("page_type", 1)])
            await db.seo_pages.create_index([("generated_at", -1)])
            # Full-text indexes — replace slow $regex content scans with scored $text queries
            await db.seo_pages.create_index(
                [("content", "text"), ("topic_title", "text"), ("title", "text")],
                name="seo_pages_content_text",
                weights={"topic_title": 10, "title": 8, "content": 1},
            )
            await db.chapters.create_index(
                [("title", "text"), ("content", "text")],
                name="chapters_content_text",
                weights={"title": 10, "content": 1},
            )
        except Exception:
            pass

        logger.info("MongoDB indexes ensured")

        # Seed Day-to-Day Analytics roadmap item if it doesn't exist
        try:
            existing = await db.roadmap.find_one({"title": "Day-to-Day Analytics"})
            if not existing:
                await db.roadmap.insert_one({
                    "id": str(uuid.uuid4()),
                    "title": "Day-to-Day Analytics",
                    "description": "Per-day admin analytics panel with date-range picker, metric summary cards (visitors, page views, signups, messages, AI interactions, bounce rate, avg session duration), and multi-series line/bar charts.",
                    "phase": "Analytics & Growth",
                    "status": "in-progress",
                    "effort": "medium",
                    "impact": "high",
                    "priority": "high",
                    "category": "analytics",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                logger.info("Roadmap: seeded 'Day-to-Day Analytics' item")
        except Exception as _re:
            logger.warning(f"Roadmap seed skipped: {_re}")

    except Exception as e:
        logger.warning(f"Seeding/indexing skipped (MongoDB may not be ready): {e}")
    # QA engine indexes (deferred import — qa_engine registered after this definition)
    try:
        from qa_engine import ensure_qa_indexes as _ensure_qa_indexes
        await _ensure_qa_indexes()
    except Exception as e:
        logger.warning(f"QA index creation skipped: {e}")
    _rate_cleanup_task = asyncio.create_task(_rate_limiter_cleanup())
    asyncio.create_task(_migrate_supabase_users_to_pg())
    asyncio.create_task(_heal_credits_limit())
    asyncio.create_task(_bg_health_loop())   # warm health-check cache every 25 s

    # Initialise SyllabusEmbedder and kick off background chapter seeding
    global _syllabus_embedder
    if db is not None:
        _syllabus_embedder = SyllabusEmbedder(db)
        asyncio.create_task(_seed_syllabus_embeddings())

    asyncio.create_task(_load_ga4_from_db())
    asyncio.create_task(_exam_reminder_loop())
    asyncio.create_task(_alerting_loop())
    logger.info("Syrabit.ai API started")
    if sarvam_client:
        logger.info("Sarvam AI client ready")
    yield
    if _rate_cleanup_task:
        _rate_cleanup_task.cancel()
    if sarvam_client:
        await sarvam_client.aclose()
    if sarvam_llm_client:
        await sarvam_llm_client.aclose()
    mongo_client.close()

app = FastAPI(title="Syrabit.ai API", version="2.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)


async def _seed_syllabus_embeddings():
    """Background task: embed all chapters on first startup (skips if already seeded)."""
    global _syllabus_embedder
    if _syllabus_embedder is None:
        return
    try:
        inserted = await _syllabus_embedder.ensure_seeded()
        if inserted > 0:
            logger.info(f"SyllabusEmbedder: seeded {inserted} chapter embeddings in background")
    except Exception as exc:
        logger.warning(f"SyllabusEmbedder background seed failed: {exc}")


async def _reseed_syllabus_embeddings():
    """Background task: force re-embed all chapters (called after PDF import creates new chapters)."""
    global _syllabus_embedder
    if _syllabus_embedder is None:
        return
    try:
        inserted = await _syllabus_embedder.reseed()
        if inserted > 0:
            logger.info(f"SyllabusEmbedder: re-seeded {inserted} new chapter embeddings after PDF import")
    except Exception as exc:
        logger.warning(f"SyllabusEmbedder re-seed failed: {exc}")


# ─────────────────────────────────────────────
# GLOBAL EXCEPTION HANDLER — consistent error shape
# ─────────────────────────────────────────────
from fastapi.responses import JSONResponse

from starlette.exceptions import HTTPException as _StarletteHTTPException

@app.exception_handler(_StarletteHTTPException)
async def _starlette_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status": exc.status_code,
            "detail": exc.detail,
            "path": str(request.url.path),
        },
    )

@app.exception_handler(HTTPException)
async def _http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status": exc.status_code,
            "detail": exc.detail,
            "path": str(request.url.path),
        },
    )

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status": 500,
            "detail": "Internal server error",
            "path": str(request.url.path),
        },
    )

from pydantic import ValidationError as _PydanticValidationError

@app.exception_handler(_PydanticValidationError)
async def _validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "status": 422,
            "detail": "Validation error",
            "errors": [{"field": ".".join(str(l) for l in e["loc"]), "message": e["msg"]} for e in exc.errors()],
            "path": str(request.url.path),
        },
    )

from fastapi.exceptions import RequestValidationError as _RequestValidationError

@app.exception_handler(_RequestValidationError)
async def _request_validation_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "status": 422,
            "detail": "Request validation error",
            "errors": [{"field": ".".join(str(l) for l in e["loc"]), "message": e["msg"]} for e in exc.errors()],
            "path": str(request.url.path),
        },
    )


api = APIRouter(prefix="/api")

_content_cache: Dict[str, Any] = {}
_content_cache_ttl: Dict[str, float] = {}
CONTENT_CACHE_SECONDS = 600
REDIS_CONTENT_PREFIX = "content:"

def _get_content_cache(key: str):
    import time as _time
    if key in _content_cache and _time.time() - _content_cache_ttl.get(key, 0) < CONTENT_CACHE_SECONDS:
        return _content_cache[key]
    if redis_client:
        try:
            val = redis_client.get(f"{REDIS_CONTENT_PREFIX}{key}")
            if val:
                parsed = json.loads(val) if isinstance(val, str) else val
                _content_cache[key] = parsed
                _content_cache_ttl[key] = _time.time()
                return parsed
        except Exception:
            pass
    return None

def _invalidate_content_cache(prefix: str):
    # Always also clear the composite library-bundle cache
    keys_to_del = [k for k in _content_cache if k == prefix or k.startswith(f"{prefix}:") or k == "library-bundle"]
    for k in keys_to_del:
        _content_cache.pop(k, None)
        _content_cache_ttl.pop(k, None)
        if redis_client:
            try:
                redis_client.delete(f"{REDIS_CONTENT_PREFIX}{k}")
            except Exception:
                pass
    if redis_client:
        try:
            redis_client.delete(f"{REDIS_CONTENT_PREFIX}library-bundle")
        except Exception:
            pass

def _set_content_cache(key: str, value):
    import time as _time
    _content_cache[key] = value
    _content_cache_ttl[key] = _time.time()
    if redis_client:
        try:
            redis_client.set(f"{REDIS_CONTENT_PREFIX}{key}", json.dumps(value, default=str), ex=CONTENT_CACHE_SECONDS)
        except Exception:
            pass

if supa:
    logger.info("Supabase client ready")
else:
    logger.warning("Supabase not configured — using MongoDB for users")

if redis_client:
    logger.info("Redis (Upstash) client ready")
else:
    logger.warning("Redis not configured — using in-memory caching/rate-limiting")

def supa_table(table: str):
    """Return Supabase table builder, or raise if unavailable."""
    if supa is None:
        raise RuntimeError("Supabase not configured")
    return supa.table(table)

async def get_user_credits(user: dict) -> dict:
    """
    Lifetime credits — NO daily/monthly reset.
    Uses the actual credits_limit from DB (includes top-ups and admin adjustments).
    Always guarantees at least the plan's entitled minimum so stale DB rows never
    under-report credits (e.g. a Pro user whose DB column wasn't updated yet).
    """
    plan      = user.get("plan", "free")
    plan_cfg  = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    plan_min  = plan_cfg["lifetime_credits"]
    db_limit  = user.get("credits_limit")
    raw_limit = db_limit if db_limit is not None else plan_min
    # Ensure Pro users always see at least 4000 even if DB column is stale
    limit = max(raw_limit, plan_min)
    used  = user.get("credits_used", 0) or 0
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "document_access": plan_cfg["document_access"],
    }

# ── Plan configuration ────────────────────────────────────────────────────────
# FREE: 30 credits ONCE (lifetime, no reset)
# STARTER / PRO: one-time purchase, no reset
PLAN_LIMITS = {
    "free":    {"lifetime_credits": 30,   "max_tokens": 1024, "document_access": "zero"},
    "starter": {"lifetime_credits": 300,  "max_tokens": 2048, "document_access": "limited"},
    "pro":     {"lifetime_credits": 4000, "max_tokens": 4096, "document_access": "full"},
}
PLAN_PRICES = {
    "free":    {"price": 0,   "label": "Free",    "description": "30 one-time credits · zero document access"},
    "starter": {"price": 99,  "label": "Starter", "description": "300 credits · limited document access (one-time)"},
    "pro":     {"price": 999, "label": "Pro",      "description": "4000 credits · full document access (one-time)"},
}

# ─────────────────────────────────────────────
# PYDANTIC MODELS  (defined in models.py)
# ─────────────────────────────────────────────
from models import (
    UserCreate, UserLogin, UserOut, TokenOut, OnboardingData, ChatMessage,
    ConversationCreate, AdminLoginReq, SubjectCreate, ChapterCreate, ChunkCreate,
    DocumentUpload, ProfileUpdate, PasswordResetReq, PasswordResetConfirm,
    UserStatusUpdate, UserPlanUpdate, UserCreditsUpdate, SettingsUpdate, RoadmapItemCreate,
    LibraryBundleOut, ChatResponseOut, SearchResultOut, HealthOut, ReadyOut, ErrorOut,
)


# ─────────────────────────────────────────────
# JWT HELPERS
# ─────────────────────────────────────────────
def create_token(data: dict, secret: str = JWT_SECRET, expires_delta: int = JWT_EXPIRE_MINUTES) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expires_delta)
    return jwt.encode(to_encode, secret, algorithm=JWT_ALGORITHM)

def create_access_token(user_id: str, role: str = "student") -> str:
    return create_token({"sub": user_id, "role": role, "type": "access"}, expires_delta=JWT_ACCESS_EXPIRE_MINUTES)

def create_refresh_token(user_id: str) -> str:
    return create_token({"sub": user_id, "type": "refresh"}, expires_delta=JWT_REFRESH_EXPIRE_MINUTES)

def decode_token(token: str, secret: str = JWT_SECRET) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_session: Optional[str] = Cookie(default=None),
):
    token = creds.credentials if creds else syrabit_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
        if payload.get("type") == "refresh":
            raise HTTPException(status_code=401, detail="Refresh tokens cannot be used for API access")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    cached = _redis_get_session(user_id)
    if cached:
        user = cached
    else:
        user = await supa_get_user_by_id(user_id)
        if user:
            _redis_cache_session(user_id, user)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Account banned")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended")
    if "role" not in user:
        user["role"] = "admin" if user.get("is_admin") else "student"
    return user

async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_session: Optional[str] = Cookie(default=None),
):
    token = creds.credentials if creds else syrabit_session
    if not token:
        return None
    try:
        payload = decode_token(token)
        if payload.get("type") == "refresh":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        cached = _redis_get_session(user_id)
        user = cached if cached else await supa_get_user_by_id(user_id)
        if user and "role" not in user:
            user["role"] = "admin" if user.get("is_admin") else "student"
        return user if user and user.get("status") not in ["banned", "suspended"] else None
    except:
        return None

def require_role(*roles: str):
    async def _checker(user: dict = Depends(get_current_user)):
        user_role = user.get("role", "student")
        if user_role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires one of: {', '.join(roles)}")
        return user
    return _checker

async def get_admin_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_admin_session: Optional[str] = Cookie(default=None),
):
    token = creds.credentials if creds else syrabit_admin_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token, secret=ADMIN_JWT_SECRET)
        if not payload.get("is_admin"):
            raise HTTPException(status_code=403, detail="Not authorized")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid admin token")

def get_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ─────────────────────────────────────────────
# RATE LIMITER — sliding window, per user/IP
# ─────────────────────────────────────────────
_rate_windows: Dict[str, List[float]] = {}

async def _rate_limiter_cleanup():
    while True:
        await asyncio.sleep(300)
        now = datetime.now(timezone.utc).timestamp()
        stale = [k for k, v in _rate_windows.items() if not v or v[-1] < now - 120]
        for k in stale:
            del _rate_windows[k]

def _check_rate_limit_memory(key: str, max_requests: int, window_seconds: int) -> bool:
    """In-memory sliding window rate limiter."""
    now = datetime.now(timezone.utc).timestamp()
    window_start = now - window_seconds
    if key not in _rate_windows:
        _rate_windows[key] = []
    _rate_windows[key] = [t for t in _rate_windows[key] if t > window_start]
    if len(_rate_windows[key]) >= max_requests:
        return False
    _rate_windows[key].append(now)
    return True

def check_rate_limit(key: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
    """Returns True if allowed, False if rate-limited.
    Uses Redis fixed-window counter when available (multi-worker safe), in-memory fallback otherwise.
    """
    if redis_client:
        try:
            redis_key = f"rl2:{key}:{int(time.time() // window_seconds)}"
            count = redis_client.incr(redis_key)
            if count == 1:
                redis_client.expire(redis_key, window_seconds + 5)
            if count > max_requests:
                return False
            return True
        except Exception as e:
            logger.debug(f"Redis rate limit failed, falling back to memory: {e}")
    return _check_rate_limit_memory(key, max_requests, window_seconds)

async def rate_limit_user(user: dict = Depends(get_current_user)):
    """Dependency: 100 req/min per user. Returns 429 if exceeded."""
    user_id = user.get("id", "anonymous")
    if not check_rate_limit(f"user:{user_id}", max_requests=300, window_seconds=60):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded — 100 requests/minute. Please wait.",
            headers={"Retry-After": "60", "X-RateLimit-Limit": "100"},
        )
    return user

async def rate_limit_chat(user: dict = Depends(get_current_user)):
    """Dependency: 30 chat req/min per user (stricter for AI)."""
    user_id = user.get("id", "anonymous")
    if not check_rate_limit(f"chat:{user_id}", max_requests=60, window_seconds=60):
        raise HTTPException(
            status_code=429,
            detail="Chat rate limit exceeded — 30 messages/minute. Upgrade for higher limits.",
            headers={"Retry-After": "60", "X-RateLimit-Limit": "30"},
        )
    return user

# ── Security headers middleware ─────────────────────────────────────────────────
# Uses pure ASGI (not BaseHTTPMiddleware) so it works correctly with StreamingResponse.
class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-Content-Type-Options", "nosniff")
                headers.append("X-Frame-Options", "SAMEORIGIN")
                headers.append("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.append("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                headers.append("X-XSS-Protection", "1; mode=block")
                if SECURE_COOKIES:
                    headers.append("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
                headers.append("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.googletagmanager.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'self'")
            await send(message)

        await self.app(scope, receive, send_with_security_headers)

class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """200 req/min per IP for all /api routes + request tracking."""
    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            client_ip = request.client.host if request.client else "unknown"
            if not check_rate_limit(f"ip:{client_ip}", max_requests=600, window_seconds=60):
                from fastapi.responses import JSONResponse
                _metrics.record_request(path, 429)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — please slow down."},
                    headers={"Retry-After": "60", "X-RateLimit-Limit": "200"}
                )
        _metrics.inc_active()
        try:
            response = await call_next(request)
            user_id = None
            if path.startswith("/api/"):
                try:
                    token = None
                    auth = request.headers.get("authorization", "")
                    if auth.startswith("Bearer "):
                        token = auth[7:]
                    else:
                        token = request.cookies.get("syrabit_session")
                    if token:
                        _pl = decode_token(token)
                        user_id = _pl.get("sub") or _pl.get("user_id")
                except Exception:
                    pass
                _metrics.record_request(path, response.status_code, user_id)
            return response
        finally:
            _metrics.dec_active()

# ─────────────────────────────────────────────
# CONTENT SEED DATA
# ─────────────────────────────────────────────
SEED_DATA = {
    "boards": [
        {"id": "b1", "name": "AHSEC", "slug": "ahsec", "group_name": "AssamBoard", "description": "AssamBoard — AHSEC (Class 11–12)", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "b2", "name": "DEGREE", "slug": "degree", "group_name": "AssamBoard", "description": "AssamBoard — Degree (B.A / B.Com / B.Sc)", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "b3", "name": "SEBA", "slug": "seba", "group_name": "AssamBoard", "description": "AssamBoard — SEBA (Secondary Education)", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "classes": [
        # AHSEC classes
        {"id": "c1", "board_id": "b1", "name": "HS 1st Year", "slug": "hs-1st-year", "description": "Class 11 — AHSEC", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c2", "board_id": "b1", "name": "HS 2nd Year", "slug": "hs-2nd-year", "description": "Class 12 — AHSEC", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE legacy classes (kept for backward compat)
        {"id": "c3", "board_id": "b2", "name": "2nd Sem", "slug": "2nd-sem", "description": "Degree 2nd Semester", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c4", "board_id": "b2", "name": "4th Sem", "slug": "4th-sem", "description": "Degree 4th Semester", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE — FYUGP (NEP) Semesters 1–4 (pre-built, linker-discoverable by slug)
        {"id": "c7",  "board_id": "b2", "name": "Semester 1", "slug": "semester-1", "description": "FYUGP 1st Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c8",  "board_id": "b2", "name": "Semester 2", "slug": "semester-2", "description": "FYUGP 2nd Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c9",  "board_id": "b2", "name": "Semester 3", "slug": "semester-3", "description": "FYUGP 3rd Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c10", "board_id": "b2", "name": "Semester 4", "slug": "semester-4", "description": "FYUGP 4th Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        # SEBA classes
        {"id": "c5", "board_id": "b3", "name": "Class 9",  "slug": "class-9",  "description": "SEBA Class 9 — Secondary", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c6", "board_id": "b3", "name": "Class 10", "slug": "class-10", "description": "SEBA Class 10 — Secondary", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "streams": [
        # AHSEC HS 1st Year streams
        {"id": "s13", "class_id": "c1", "name": "Science (PCM)", "slug": "science-pcm", "description": "Physics, Chemistry, Mathematics", "icon": "⚗️", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s14", "class_id": "c1", "name": "Science (PCB)", "slug": "science-pcb", "description": "Physics, Chemistry, Biology",    "icon": "🧬", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s15", "class_id": "c1", "name": "Arts",          "slug": "arts",        "description": "Political Science, History, Economics, Geography", "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s16", "class_id": "c1", "name": "Commerce",      "slug": "commerce",    "description": "Accountancy, Business Studies, Economics",          "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        # AHSEC HS 2nd Year streams
        {"id": "s17", "class_id": "c2", "name": "Science (PCM)", "slug": "science-pcm", "description": "Physics, Chemistry, Mathematics", "icon": "⚗️", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s18", "class_id": "c2", "name": "Science (PCB)", "slug": "science-pcb", "description": "Physics, Chemistry, Biology",    "icon": "🧬", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s19", "class_id": "c2", "name": "Arts",          "slug": "arts",        "description": "Political Science, History, Economics, Geography", "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s20", "class_id": "c2", "name": "Commerce",      "slug": "commerce",    "description": "Accountancy, Business Studies, Economics",          "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE 2nd Sem legacy streams
        {"id": "s7",  "class_id": "c3", "name": "B.Com", "slug": "bcom", "description": "Bachelor of Commerce", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s8",  "class_id": "c3", "name": "B.A",   "slug": "ba",   "description": "Bachelor of Arts",     "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s9",  "class_id": "c3", "name": "B.Sc",  "slug": "bsc",  "description": "Bachelor of Science",  "icon": "🔬", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE 4th Sem legacy streams
        {"id": "s10", "class_id": "c4", "name": "B.Com", "slug": "bcom", "description": "Bachelor of Commerce", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s11", "class_id": "c4", "name": "B.A",   "slug": "ba",   "description": "Bachelor of Arts",     "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s12", "class_id": "c4", "name": "B.Sc",  "slug": "bsc",  "description": "Bachelor of Science",  "icon": "🔬", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 1 — 6 NEP course-type streams
        {"id": "s30", "class_id": "c7",  "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s31", "class_id": "c7",  "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s32", "class_id": "c7",  "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s33", "class_id": "c7",  "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s34", "class_id": "c7",  "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s35", "class_id": "c7",  "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 2 — 6 NEP course-type streams
        {"id": "s36", "class_id": "c8",  "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s37", "class_id": "c8",  "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s38", "class_id": "c8",  "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s39", "class_id": "c8",  "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s40", "class_id": "c8",  "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s41", "class_id": "c8",  "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 3 — 6 NEP course-type streams
        {"id": "s42", "class_id": "c9",  "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s43", "class_id": "c9",  "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s44", "class_id": "c9",  "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s45", "class_id": "c9",  "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s46", "class_id": "c9",  "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s47", "class_id": "c9",  "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 4 — 6 NEP course-type streams
        {"id": "s48", "class_id": "c10", "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s49", "class_id": "c10", "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s50", "class_id": "c10", "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s51", "class_id": "c10", "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s52", "class_id": "c10", "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s53", "class_id": "c10", "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # SEBA Class 9 streams
        {"id": "s21", "class_id": "c5", "name": "General", "slug": "general", "description": "General stream — SEBA Class 9", "icon": "📚", "created_at": "2024-01-01T00:00:00Z"},
        # SEBA Class 10 streams
        {"id": "s22", "class_id": "c6", "name": "General", "slug": "general", "description": "General stream — SEBA Class 10", "icon": "📚", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "subjects": [],
    "chapters": [],
}

def _generate_chapters():
    return []  # Chapters cleared — upload new syllabus via Admin panel

SEED_DATA["chapters"] = _generate_chapters()

def _fix_chapter_counts():
    ch_count = {}
    for ch in SEED_DATA["chapters"]:
        sid = ch["subject_id"]
        ch_count[sid] = ch_count.get(sid, 0) + 1
    for subj in SEED_DATA["subjects"]:
        subj["chapter_count"] = ch_count.get(subj["id"], 0)

_fix_chapter_counts()

_seeded = False

async def ensure_seeded():
    """Seed database with boards/classes/streams - gracefully handles connection failures"""
    global _seeded
    if _seeded:
        return
    
    if not await is_mongo_available():
        return
    
    try:
        ahsec_exists  = await db.boards.find_one({"id": "b1"})
        degree_exists = await db.boards.find_one({"id": "b2"})
        seba_exists   = await db.boards.find_one({"id": "b3"})
        seba_class_exists   = await db.classes.find_one({"board_id": "b3"})
        seba_stream_exists  = await db.streams.find_one({"class_id": {"$in": ["c5", "c6"]}})
        fyugp_class_exists  = await db.classes.find_one({"id": {"$in": ["c7", "c8", "c9", "c10"]}})
        fyugp_stream_exists = await db.streams.find_one({"id": {"$in": ["s30", "s36", "s42", "s48"]}})
        ch_count = await db.chapters.count_documents({})
        expected_ch = len(SEED_DATA["chapters"])
        # Check for non-canonical boards (would need cleanup)
        total_boards = await db.boards.count_documents({})
        canonical_count = 3  # b1, b2, b3
        all_canonical = (total_boards <= canonical_count)
        # Check for duplicate classes (e.g. cls_b2_semester-1 AND c7 both slug=semester-1)
        has_dupes = await db.classes.find_one(
            {"id": {"$nin": [c["id"] for c in SEED_DATA["classes"]]},
             "slug": {"$in": ["semester-1","semester-2","semester-3","semester-4"]},
             "board_id": "b2"}
        )
        if (ahsec_exists and degree_exists and seba_exists and
                seba_class_exists and seba_stream_exists and
                fyugp_class_exists and fyugp_stream_exists and
                ch_count >= expected_ch and all_canonical and not has_dupes):
            _seeded = True
            return
    except Exception as e:
        logger.warning(f"Database not available for seeding: {e}")
        return
    logger.info("Seeding structural data (boards/classes/streams only — subjects/chapters managed via Admin)...")
    from pymongo import ReplaceOne
    # Enforce structural skeleton — boards/classes/streams only
    # Subjects and chapters are managed entirely via Admin panel uploads
    canonical_board_ids  = {b["id"] for b in SEED_DATA["boards"]}
    canonical_class_ids  = {c["id"] for c in SEED_DATA["classes"]}
    # Only prune boards whose ID isn't canonical
    await db.boards.delete_many({"id": {"$nin": list(canonical_board_ids)}})
    # Only prune classes whose board isn't canonical (keeps dynamically created DEGREE/AHSEC/SEBA classes)
    await db.classes.delete_many({"board_id": {"$nin": list(canonical_board_ids)}})
    # Protect streams belonging to any class under a canonical board (not just seeded classes)
    dynamic_class_docs = await db.classes.find(
        {"board_id": {"$in": list(canonical_board_ids)}}, {"id": 1}
    ).to_list(2000)
    all_protected_class_ids = canonical_class_ids | {c["id"] for c in dynamic_class_docs}
    await db.streams.delete_many({"class_id": {"$nin": list(all_protected_class_ids)}})
    # NOTE: Do NOT delete subjects or chapters here — they are user-managed
    if SEED_DATA["boards"]:
        ops = [ReplaceOne({"id": b["id"]}, b, upsert=True) for b in SEED_DATA["boards"]]
        await db.boards.bulk_write(ops, ordered=False)
    if SEED_DATA["classes"]:
        ops = [ReplaceOne({"id": c["id"]}, c, upsert=True) for c in SEED_DATA["classes"]]
        await db.classes.bulk_write(ops, ordered=False)
    if SEED_DATA["streams"]:
        ops = [ReplaceOne({"id": s["id"]}, s, upsert=True) for s in SEED_DATA["streams"]]
        await db.streams.bulk_write(ops, ordered=False)
    # ── Deduplicate: remove old dynamically-created classes that share slug+board_id
    # with a canonical class (e.g. cls_b2_semester-1 vs c7 both have slug=semester-1, board_id=b2)
    canonical_class_ids_set = {c["id"] for c in SEED_DATA["classes"]}
    for canon_cls in SEED_DATA["classes"]:
        dupe_docs = await db.classes.find(
            {"board_id": canon_cls["board_id"], "slug": canon_cls["slug"],
             "id": {"$ne": canon_cls["id"]}},
            {"id": 1}
        ).to_list(100)
        for dupe in dupe_docs:
            dupe_id = dupe["id"]
            # Re-point all streams under the dupe class to the canonical class
            dupe_streams = await db.streams.find({"class_id": dupe_id}, {"id": 1, "slug": 1}).to_list(100)
            for dupe_stream in dupe_streams:
                # Check if a canonical stream with same slug exists under canonical class
                canon_stream = await db.streams.find_one(
                    {"class_id": canon_cls["id"], "slug": dupe_stream["slug"]}, {"id": 1}
                )
                if canon_stream:
                    # Move subjects from dupe stream to canonical stream
                    await db.subjects.update_many(
                        {"stream_id": dupe_stream["id"]},
                        {"$set": {"stream_id": canon_stream["id"],
                                  "class_slug": canon_cls["slug"],
                                  "class_id": canon_cls["id"]}}
                    )
                    await db.streams.delete_one({"id": dupe_stream["id"]})
            # Remove the dupe class
            await db.classes.delete_one({"id": dupe_id})
            logger.info(f"Dedup: removed duplicate class {dupe_id} (same as {canon_cls['id']})")
    # Ensure admin user exists for each admin account in ADMIN_ACCOUNTS
    for admin_acc in ADMIN_ACCOUNTS:
        existing = await supa_get_user(admin_acc["email"])
        if not existing:
            admin_doc = {
                "id": str(uuid.uuid4()),
                "name": admin_acc["name"],
                "email": admin_acc["email"],
                "password_hash": pwd_ctx.hash(admin_acc["password"]),
                "plan": "pro",
                "credits_used": 0,
                "credits_limit": 4000,
                "document_access": "full",
                "onboarding_done": True,
                "is_admin": True,
                "status": "active",
                "bio": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await supa_insert_user(admin_doc)
            logger.info(f"Seeded admin user: {admin_acc['email']}")
    _seeded = True
    logger.info("Content seeded successfully")

# ─────────────────────────────────────────────────────────────────────────────
# ADAPTIVE SYSTEM PROMPT  (defined in prompts.py)
# ─────────────────────────────────────────────────────────────────────────────
from prompts import build_system_prompt, _classify_question
from subject_router import build_search_scope
from syllabus_embedder import SyllabusEmbedder

_syllabus_embedder: Optional[SyllabusEmbedder] = None

# ─────────────────────────────────────────────
# RAG SEARCH
# Priority chain:
#   Level 1 — Content chunks from DB (best — actual indexed syllabus text)
#   Level 2 — Subject descriptions + tags + chapter titles (medium — metadata)
# ─────────────────────────────────────────────

def _extract_keywords(query: str) -> list:
    """Extract meaningful search keywords, removing stop-words."""
    stop_words = {
        "what", "which", "when", "where", "that", "this", "with", "from",
        "have", "will", "your", "some", "they", "been", "more", "also",
        "into", "than", "then", "there", "about", "give", "explain", "the",
        "and", "for", "are", "how", "why", "who", "can", "its", "was",
        "let", "define", "describe", "state", "write", "list",
    }
    raw = [w.strip('?.,!;:()[]"\'').lower() for w in query.split()]
    return [w for w in raw if len(w) >= 3 and w not in stop_words][:8]


# ─────────────────────────────────────────────
# LIBRARY ANALYTICS TRACKING
# ─────────────────────────────────────────────

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
            if pg_pool:
                async with pg_pool.acquire() as conn:
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


# ─────────────────────────────────────────────
# AUTO-CHUNKING FOR RAG
# ─────────────────────────────────────────────

async def auto_chunk_content(chapter_id: str, content: str, subject_id: str = None, syllabus_id: str = None, geo_tags: list = None) -> list:
    """
    Automatically split chapter content into searchable chunks.
    
    Strategy:
    - Split by double newlines (paragraphs)
    - Each chunk: 100-800 chars (optimal for RAG)
    - Extract keywords for each chunk
    - Store in 'chunks' collection for fast retrieval
    - Attach syllabus_id and geo_tags metadata for GEO grounding
    
    Returns: List of created chunk IDs
    """
    if not content or len(content.strip()) < 100:
        logger.warning(f"Content too short for chunking (chapter {chapter_id}): {len(content)} chars")
        return []
    
    # Clean content
    content = content.strip()
    
    # Split by double newlines (paragraphs) or single newlines if no double
    paragraphs = []
    if '\n\n' in content:
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    else:
        # Fallback: split by single newline and group into chunks
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        current_chunk = []
        for line in lines:
            current_chunk.append(line)
            if len(' '.join(current_chunk)) > 400:
                paragraphs.append(' '.join(current_chunk))
                current_chunk = []
        if current_chunk:
            paragraphs.append(' '.join(current_chunk))
    
    if not paragraphs:
        # No clear structure, split by sentences
        import re
        sentences = re.split(r'(?<=[.!?])\s+', content)
        paragraphs = []
        current = []
        for sent in sentences:
            current.append(sent)
            if len(' '.join(current)) > 300:
                paragraphs.append(' '.join(current))
                current = []
        if current:
            paragraphs.append(' '.join(current))
    
    # Create chunks
    chunks_created = []
    for i, para in enumerate(paragraphs):
        para_clean = para.strip()
        
        # Skip very short paragraphs (less than 50 chars)
        if len(para_clean) < 50:
            continue
        
        # If paragraph is too long, split it further
        if len(para_clean) > 800:
            # Split into smaller chunks of ~400 chars at sentence boundaries
            import re
            sentences = re.split(r'(?<=[.!?])\s+', para_clean)
            sub_chunk = []
            for sent in sentences:
                sub_chunk.append(sent)
                if len(' '.join(sub_chunk)) > 400:
                    chunk_text = ' '.join(sub_chunk).strip()
                    if len(chunk_text) >= 50:
                        # Extract keywords for this chunk
                        chunk_keywords = _extract_keywords(chunk_text)
                        
                        chunk = {
                            "id": str(uuid.uuid4()),
                            "chapter_id": chapter_id,
                            "subject_id": subject_id,
                            "content": chunk_text,
                            "content_type": "notes",
                            "chunk_index": len(chunks_created),
                            "tags": chunk_keywords[:5],
                            "char_count": len(chunk_text),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                        if syllabus_id:
                            chunk["syllabus_id"] = syllabus_id
                        if geo_tags:
                            chunk["geo_tags"] = geo_tags[:5]
                        await db.chunks.insert_one(chunk)
                        chunks_created.append(chunk["id"])
                    sub_chunk = []
            
            # Add remaining
            if sub_chunk:
                chunk_text = ' '.join(sub_chunk).strip()
                if len(chunk_text) >= 50:
                    chunk_keywords = _extract_keywords(chunk_text)
                    chunk = {
                        "id": str(uuid.uuid4()),
                        "chapter_id": chapter_id,
                        "subject_id": subject_id,
                        "content": chunk_text,
                        "content_type": "notes",
                        "chunk_index": len(chunks_created),
                        "tags": chunk_keywords[:5],
                        "char_count": len(chunk_text),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    if syllabus_id:
                        chunk["syllabus_id"] = syllabus_id
                    if geo_tags:
                        chunk["geo_tags"] = geo_tags[:5]
                    await db.chunks.insert_one(chunk)
                    chunks_created.append(chunk["id"])
        else:
            chunk_keywords = _extract_keywords(para_clean)
            
            chunk = {
                "id": str(uuid.uuid4()),
                "chapter_id": chapter_id,
                "subject_id": subject_id,
                "content": para_clean,
                "content_type": "notes",
                "chunk_index": i,
                "tags": chunk_keywords[:5],
                "char_count": len(para_clean),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if syllabus_id:
                chunk["syllabus_id"] = syllabus_id
            if geo_tags:
                chunk["geo_tags"] = geo_tags[:5]
            await db.chunks.insert_one(chunk)
            chunks_created.append(chunk["id"])
    
    logger.info(f"Auto-chunked chapter {chapter_id}: {len(chunks_created)} chunks from {len(content)} chars")
    return chunks_created


async def rechunk_chapter(chapter_id: str) -> dict:
    """
    Re-chunk an existing chapter (useful after content updates or for existing chapters).
    Deletes old chunks and creates new ones.
    """
    # Get chapter
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    content = chapter.get("content", "")
    if not content:
        return {"chapter_id": chapter_id, "chunks_created": 0, "message": "No content to chunk"}
    
    # Delete existing chunks for this chapter
    delete_result = await db.chunks.delete_many({"chapter_id": chapter_id})
    deleted_count = delete_result.deleted_count
    
    # Create new chunks
    chunks_created = await auto_chunk_content(
        chapter_id=chapter_id,
        content=content,
        subject_id=chapter.get("subject_id")
    )
    
    return {
        "chapter_id": chapter_id,
        "chunks_deleted": deleted_count,
        "chunks_created": len(chunks_created),
        "message": f"Re-chunked successfully"
    }


async def _fetch_content_card(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
) -> Optional[tuple]:
    """
    Search seo_pages + chapters for the most relevant content card.
    Returns (card_text: str, card_slugs: set[str], source_meta: dict) if found, else None.
    Card slugs are used by the grounding builder to deduplicate vector hits.
    source_meta contains card_name, lesson_name, subject_name for chat attribution.
    """
    _ck = _content_card_cache_key(query, subject_id, subject_name)
    if _ck in _content_card_cache:
        logger.info(f"Content card cache hit: query='{query[:40]}'")
        return _content_card_cache[_ck]

    try:
        if not await is_mongo_available():
            return None

        keywords = _extract_keywords(query)
        if not keywords:
            return None

        kw_regex = "|".join(keywords)
        match_filter: dict = {"status": "published"}

        if subject_id:
            subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0, "slug": 1, "name": 1})
            if subj and subj.get("slug"):
                match_filter["subject_slug"] = subj["slug"]

        if not subject_id and subject_name:
            match_filter["subject_name"] = {"$regex": re.escape(subject_name), "$options": "i"}

        # $text search — uses full-text index (weighted: topic_title×10, title×8, content×1)
        # Falls back to $regex if text index not yet available on this collection
        search_str = " ".join(keywords)
        match_filter["$text"] = {"$search": search_str}
        _text_proj = {
            "_id": 0, "content": 1, "topic_title": 1, "subject_name": 1,
            "chapter_title": 1, "page_type": 1, "slug": 1,
            "score": {"$meta": "textScore"},
        }
        seo_task = db.seo_pages.find(
            match_filter, _text_proj,
        ).sort([("score", {"$meta": "textScore"})]).limit(6).to_list(6)

        ch_filter: dict = {"content": {"$exists": True, "$ne": ""}}
        if subject_id:
            ch_filter["subject_id"] = subject_id
        ch_filter["$text"] = {"$search": search_str}
        _ch_proj = {
            "_id": 0, "title": 1, "content": 1, "subject_id": 1,
            "score": {"$meta": "textScore"},
        }
        ch_task = db.chapters.find(
            ch_filter, _ch_proj,
        ).sort([("score", {"$meta": "textScore"})]).limit(4).to_list(4)

        try:
            pages, chapter_pages = await asyncio.gather(seo_task, ch_task)
        except Exception:
            # Text index not ready yet — fall back to $regex for this request
            del match_filter["$text"]
            match_filter["$or"] = [
                {"content":     {"$regex": "|".join(keywords), "$options": "i"}},
                {"topic_title": {"$regex": "|".join(keywords), "$options": "i"}},
                {"title":       {"$regex": "|".join(keywords), "$options": "i"}},
            ]
            regex_proj = {"_id": 0, "content": 1, "topic_title": 1, "subject_name": 1,
                          "chapter_title": 1, "page_type": 1, "slug": 1}
            ch_filter_fb: dict = {"content": {"$exists": True, "$ne": ""}}
            if subject_id:
                ch_filter_fb["subject_id"] = subject_id
            ch_filter_fb["$or"] = [
                {"content": {"$regex": "|".join(keywords), "$options": "i"}},
                {"title":   {"$regex": "|".join(keywords), "$options": "i"}},
            ]
            pages, chapter_pages = await asyncio.gather(
                db.seo_pages.find(match_filter, regex_proj).limit(6).to_list(6),
                db.chapters.find(ch_filter_fb, {"_id": 0, "title": 1, "content": 1, "subject_id": 1}).limit(4).to_list(4),
            )

        if not pages and not chapter_pages:
            return None

        cards = []

        # Priority: notes → pyq → mcq → everything else (textScore already pre-sorts)
        def _page_priority(p: dict) -> int:
            pt = p.get("page_type", "")
            return 0 if pt == "notes" else (1 if pt == "pyq" else (2 if pt == "mcq" else 3))

        ordered_pages = sorted(pages, key=_page_priority)
        card_slugs: set = set()
        # Track top card name + lesson name for attribution
        _top_card_name: str = ""
        _top_lesson_name: str = ""
        _top_subject_name: str = ""
        for p in ordered_pages[:3]:
            content = p.get("content", "")
            if not content:
                continue
            slug = p.get("slug") or p.get("topic_title", "")
            card_slugs.add(slug)
            topic_title = p.get("topic_title") or p.get("chapter_title") or ""
            if not _top_card_name and topic_title:
                _top_card_name = topic_title
                _top_lesson_name = p.get("chapter_title") or ""
                _top_subject_name = p.get("subject_name") or subject_name or ""
            header = f"[Content: {topic_title}]" if topic_title else "[Content Page]"
            relevant = _extract_relevant_sections(content, keywords, max_chars=2000)
            cards.append(f"{header}\n{relevant}")

        # Append chapter content (trimmed for Flash Lite token budget)
        for ch in chapter_pages[:2]:
            content = ch.get("content", "")
            if not content:
                continue
            if not _top_lesson_name:
                _top_lesson_name = ch.get("title") or ""
            header = f"[Chapter: {ch.get('title', '')}]"
            relevant = _extract_relevant_sections(content, keywords, max_chars=1200)
            cards.append(f"{header}\n{relevant}")

        if not cards:
            return None

        source_meta = {
            "card_name": _top_card_name,
            "lesson_name": _top_lesson_name,
            "subject_name": _top_subject_name,
        }
        result = ("\n\n---\n\n".join(cards), card_slugs, source_meta)
        _content_card_cache[_ck] = result
        return result

    except Exception as e:
        logger.error(f"Content card fetch error: {e}")
        return None


def _extract_relevant_sections(content: str, keywords: list, max_chars: int = 2500) -> str:
    """Extract the most relevant sections from a content page based on keywords."""
    paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
    if not paragraphs:
        return content[:max_chars]

    scored = []
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        score = sum(1 for kw in keywords if kw in para_lower)
        is_header = para.startswith('#') or para.startswith('**')
        if is_header:
            score += 0.5
        scored.append((score, i, para))

    scored.sort(key=lambda x: (-x[0], x[1]))

    selected_indices = set()
    total_chars = 0
    for score, idx, para in scored:
        if score <= 0 and total_chars > 500:
            break
        for j in range(max(0, idx - 1), min(len(paragraphs), idx + 2)):
            if j not in selected_indices:
                selected_indices.add(j)
                total_chars += len(paragraphs[j])
        if total_chars >= max_chars:
            break

    if not selected_indices:
        return content[:max_chars]

    result = "\n".join(paragraphs[i] for i in sorted(selected_indices))
    return result[:max_chars]


async def _embed_and_store_page(page_slug: str, content: str) -> bool:
    """Embed a published seo_page and persist the vector. Called on every publish."""
    try:
        vec = await vertex_services.embed_text(content[:8000], task_type="RETRIEVAL_DOCUMENT")
        if vec:
            await db.seo_pages.update_one(
                {"topic_slug": page_slug},
                {"$set": {"embedding": vec, "embedding_model": "text-embedding-004"}},
            )
            logger.info(f"Page embedded: {page_slug} (dim={len(vec)})")
            return True
    except Exception as e:
        logger.warning(f"Embed-on-publish failed for {page_slug}: {e}")
    return False


async def _embed_and_store_chapter(chapter_id: str, content: str, title: str = "") -> bool:
    """Embed a chapter's content and persist the vector."""
    try:
        text = f"{title}\n\n{content}" if title else content
        vec = await vertex_services.embed_text(text[:8000], task_type="RETRIEVAL_DOCUMENT")
        if vec:
            await db.chapters.update_one(
                {"id": chapter_id},
                {"$set": {"embedding": vec, "embedding_model": "text-embedding-004"}},
            )
            return True
    except Exception as e:
        logger.warning(f"Embed chapter {chapter_id} failed: {e}")
    return False


async def vector_rag_search(
    query: str,
    subject_id: Optional[str] = None,
    top_k: int = 12,
) -> list:
    """
    Vector similarity search over all published seo_pages + chapters.
    Returns top-k results sorted by cosine similarity with [PAGE: slug] metadata.

    Falls back to empty list if embedding fails or no vectors exist yet.
    Caches results for 300 seconds — Gemini embed calls are expensive.
    """
    # Fast path: in-memory cache (skips Gemini API call + 300-doc MongoDB fetch)
    _vk = _vector_rag_cache_key(query, subject_id, top_k)
    if _vk in _vector_rag_cache:
        logger.info(f"Vector RAG cache hit: query='{query[:40]}'")
        return _vector_rag_cache[_vk]

    try:
        query_vec = await vertex_services.embed_text(query, task_type="RETRIEVAL_QUERY")
        if not query_vec:
            return []

        # Build page filter
        page_filter: dict = {"status": "published", "embedding": {"$exists": True}}
        if subject_id:
            subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0, "slug": 1})
            if subj and subj.get("slug"):
                page_filter["subject_slug"] = subj["slug"]

        # Fetch candidates (limit high to allow good ranking)
        pages = await db.seo_pages.find(
            page_filter,
            {"_id": 0, "topic_slug": 1, "content": 1, "topic_title": 1,
             "chapter_title": 1, "page_type": 1, "embedding": 1},
        ).limit(200).to_list(200)

        # Fetch chapter candidates
        ch_filter: dict = {"embedding": {"$exists": True}, "content": {"$exists": True, "$ne": ""}}
        if subject_id:
            ch_filter["subject_id"] = subject_id
        chapters = await db.chapters.find(
            ch_filter,
            {"_id": 0, "id": 1, "title": 1, "content": 1, "subject_id": 1, "embedding": 1},
        ).limit(100).to_list(100)

        # Score all candidates by cosine similarity
        scored = []
        for p in pages:
            vec = p.get("embedding")
            if vec:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                slug = p.get("topic_slug", "")
                title = p.get("topic_title") or p.get("chapter_title") or slug
                content_snippet = _extract_relevant_sections(p.get("content", ""), [], max_chars=1500)
                scored.append({
                    "slug":    slug,
                    "title":   title,
                    "content": content_snippet,
                    "score":   sim,
                    "source":  "page",
                })
        for ch in chapters:
            vec = ch.get("embedding")
            if vec:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                content_snippet = _extract_relevant_sections(ch.get("content", ""), [], max_chars=1500)
                scored.append({
                    "slug":    f"chapter/{ch.get('id', '')}",
                    "title":   ch.get("title", ""),
                    "content": content_snippet,
                    "score":   sim,
                    "source":  "chapter",
                })

        scored.sort(key=lambda x: -x["score"])
        # 0.25 cosine threshold — filter out low-relevance noise before sending to AI
        top = [r for r in scored if r["score"] >= 0.25][:top_k]
        logger.info(
            f"Vector RAG: query='{query[:40]}' → {len(top)} results "
            f"(best_sim={top[0]['score']:.3f} [{top[0]['slug']}], threshold=0.25)" if top else
            f"Vector RAG: query='{query[:40]}' → no results above threshold (0.25)"
        )
        # Store in cache — future identical/similar queries skip the embed API call
        _vector_rag_cache[_vk] = top
        return top
    except Exception as e:
        logger.error(f"vector_rag_search failed: {e}")
        return []


async def rag_search(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
) -> dict:
    """
    Level-1 RAG: search content chunks + subject metadata from DB.

    Returns quality indicator:
      "high"   — at least 1 content chunk found (real indexed text)
      "medium" — no chunks, but matching subjects/chapters found (metadata only)
      "none"   — nothing found in DB at all
    """
    _rag_t0 = time.time()
    # Fast path: 60-second in-memory cache — skips all MongoDB queries on repeat
    _rk = _rag_cache_key(query, subject_id, subject_name)
    if _rk in _rag_cache:
        return _rag_cache[_rk]
    try:
        keywords = _extract_keywords(query)
        if not keywords:
            return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}

        kw_join = "|".join(keywords)
        regex_parts = [{"content": {"$regex": kw, "$options": "i"}} for kw in keywords]
        ch_title_filter = {"$or": [{"title": {"$regex": kw, "$options": "i"}} for kw in keywords]}

        if subject_id:
            # ── Fast path: subject is known — pre-fetch chapter IDs then run all 3 queries in parallel ──
            sub_chapters = await db.chapters.find(
                {"subject_id": subject_id}, {"_id": 0, "id": 1}
            ).to_list(200)
            chapter_ids = [c["id"] for c in sub_chapters]
            # Include PYQ chunks linked by subject_id directly (they use synthetic chapter IDs)
            pyq_branch: dict = {"$and": [{"subject_id": subject_id}, {"content_type": "pyq"}, {"$or": regex_parts}]}
            if chapter_ids:
                chunk_filter: dict = {"$or": [
                    {"$and": [{"chapter_id": {"$in": chapter_ids}}, {"$or": regex_parts}]},
                    pyq_branch,
                ]}
            else:
                chunk_filter = {"$or": [{"$or": regex_parts}, pyq_branch]}
            subj_kw_filter = {"id": subject_id}
            # Fetch keyword-matching chapters AND all chapters for this subject
            ch_kw_filter = {"$and": [{"subject_id": subject_id}, ch_title_filter]}
            ch_all_filter = {"subject_id": subject_id}

            chunks, subjects_found, chapters_kw, chapters_all = await asyncio.gather(
                db.chunks.find(chunk_filter, {"_id": 0}).sort("priority", 1).limit(12).to_list(12),
                db.subjects.find(subj_kw_filter, {"_id": 0}).limit(1).to_list(1),
                db.chapters.find(ch_kw_filter, {"_id": 0, "title": 1, "description": 1, "content": 1, "order_index": 1}).sort("order_index", 1).limit(8).to_list(8),
                db.chapters.find(ch_all_filter, {"_id": 0, "title": 1, "description": 1, "content": 1, "order_index": 1}).sort("order_index", 1).limit(25).to_list(25),
            )
            # Use keyword-matching chapters when available; otherwise use the full chapter list
            chapters_found = chapters_kw if chapters_kw else chapters_all
        else:
            # ── No subject: 3-way parallel search across name, chapters, and chunks ──
            subj_kw_filter = {"$or": [
                {"name":        {"$regex": kw_join, "$options": "i"}},
                {"description": {"$regex": kw_join, "$options": "i"}},
                {"tags":        {"$elemMatch": {"$regex": kw_join, "$options": "i"}}},
            ], "status": "published"}
            if subject_name:
                subj_kw_filter = {"$and": [
                    {"name": {"$regex": subject_name, "$options": "i"}, "status": "published"},
                ]}

            # Run 3 searches in parallel:
            #   (1) subjects by name/desc/tags
            #   (2) ALL chapters whose title matches keywords → backtrack to subject
            #   (3) chunks whose content matches keywords → backtrack to subject via chapter_id
            _subj_proj = {"_id": 0, "id": 1, "name": 1, "description": 1, "tags": 1}
            _ch_proj   = {"_id": 0, "id": 1, "subject_id": 1, "title": 1, "description": 1, "order_index": 1}
            chunks, subjects_by_name, chapters_by_title = await asyncio.gather(
                db.chunks.find({"$or": regex_parts}, {"_id": 0}).sort("priority", 1).limit(15).to_list(15),
                db.subjects.find(subj_kw_filter, _subj_proj).limit(55).to_list(55),
                db.chapters.find(ch_title_filter, _ch_proj).sort("order_index", 1).limit(25).to_list(25),
            )

            # ── Resolve chunks → parent subjects (via chapter_id) ─────────────────
            chunk_chapter_ids = list({c["chapter_id"] for c in chunks if c.get("chapter_id")})
            chunk_parent_chapters: list = []
            if chunk_chapter_ids:
                chunk_parent_chapters = await db.chapters.find(
                    {"id": {"$in": chunk_chapter_ids}}, {"_id": 0, "id": 1, "subject_id": 1, "title": 1}
                ).to_list(10)

            # Collect all subject IDs reached via chapters and chunks
            existing_ids = {s["id"] for s in subjects_by_name}
            via_chapter_ids = {c["subject_id"] for c in chapters_by_title if c.get("subject_id")} - existing_ids
            via_chunk_ids   = {c["subject_id"] for c in chunk_parent_chapters if c.get("subject_id")} - existing_ids - via_chapter_ids

            # Fetch the extra subjects (those reached only through chapter/chunk paths)
            extra_ids = list(via_chapter_ids | via_chunk_ids)
            extra_subjects: list = []
            if extra_ids:
                extra_subjects = await db.subjects.find(
                    {"id": {"$in": extra_ids}, "status": "published"}, _subj_proj
                ).to_list(20)

            # ── Score & re-rank ALL candidate subjects ────────────────────────────
            # Priority order (user-specified):
            #   1. Chunk content matches  → +5 per matching chunk   (actual study material)
            #   2. Chapter title matches  → +3 per keyword in title (topical chapter signal)
            #   3. Subject name matches   → +1 per keyword in name  (broad category signal)
            #   Bonus: +8 when exact subject name is a substring of the query
            query_lower = query.lower()

            # Per-subject chunk count (how many matching chunks came from each subject)
            chunk_subject_count: dict[str, int] = {}
            for c in chunk_parent_chapters:
                sid = c.get("subject_id", "")
                if sid:
                    chunk_subject_count[sid] = chunk_subject_count.get(sid, 0) + 1

            # Per-subject chapter-title keyword-hit count
            chapter_title_score: dict[str, int] = {}
            for ch in chapters_by_title:
                sid = ch.get("subject_id", "")
                if not sid:
                    continue
                title_lower = ch.get("title", "").lower()
                hits = sum(1 for kw in keywords if kw in title_lower)
                chapter_title_score[sid] = chapter_title_score.get(sid, 0) + hits

            def _subject_score(s: dict) -> int:
                name_lower = s.get("name", "").lower()
                sid = s.get("id", "")
                # Priority 1 — chunk content (highest)
                score  = chunk_subject_count.get(sid, 0) * 5
                # Priority 2 — chapter title keyword density
                score += chapter_title_score.get(sid, 0) * 3
                # Priority 3 — subject name keyword match (lowest)
                score += sum(1 for kw in keywords if kw in name_lower)
                # Exact subject name mentioned in query (strong explicit intent)
                score += 8 if (name_lower and name_lower in query_lower) else 0
                return score

            all_candidates = subjects_by_name + extra_subjects
            if len(all_candidates) > 1:
                all_candidates = sorted(all_candidates, key=_subject_score, reverse=True)
            # Deduplicate by name (keep the highest-scored version of each subject name)
            seen_names: set = set()
            deduped: list = []
            for s in all_candidates:
                n = s.get("name", "").lower()
                if n not in seen_names:
                    seen_names.add(n)
                    deduped.append(s)
            subjects_found = deduped[:3]

            # ── Filter chunks to the dominant subject only ─────────────────────
            # Prevents unrelated subjects (e.g. Indian Constitution appearing when
            # the user asks about Business Studies) from contaminating the answer.
            top_subject_ids = [s["id"] for s in subjects_found]
            if subjects_found and chunk_parent_chapters:
                dominant_sid = subjects_found[0].get("id", "")
                if dominant_sid:
                    dominant_chapter_ids = {
                        cc["id"] for cc in chunk_parent_chapters
                        if cc.get("subject_id") == dominant_sid
                    }
                    filtered_chunks = [c for c in chunks if c.get("chapter_id") in dominant_chapter_ids]
                    if filtered_chunks:  # Only narrow if chunks remain
                        chunks = filtered_chunks
                        chunk_parent_chapters = [
                            cc for cc in chunk_parent_chapters
                            if cc.get("subject_id") == dominant_sid
                        ]

            # ── chapters_found: keyword-matching chapters scoped to top subjects ──
            if top_subject_ids:
                chapters_found = [c for c in chapters_by_title if c.get("subject_id") in top_subject_ids][:5]
                if not chapters_found:
                    chapters_found = chapters_by_title[:5]
            else:
                chapters_found = chapters_by_title[:5]

        # ── Determine quality ─────────────────────────────────────────────────
        if chunks:
            quality = "high"
            source  = "rag"
            logger.info(f"RAG [HIGH]: {len(chunks)} chunks, {len(chapters_found)} chapters | query: {query[:50]}")
        elif subjects_found or chapters_found:
            quality = "medium"
            source  = "rag"
            logger.info(f"RAG [MEDIUM]: 0 chunks, {len(subjects_found)} subjects, {len(chapters_found)} chapters | query: {query[:50]}")
        else:
            quality = "none"
            source  = "none"
            logger.info(f"RAG [NONE]: nothing found | query: {query[:50]}")

        result = {
            "chunks":         chunks,
            "chapters":       chapters_found,
            "chunk_chapters": chunk_parent_chapters,
            "subjects":       subjects_found,
            "source":         source,
            "quality":        quality,
        }
        _rag_cache[_rk] = result
        try:
            _record_rag_event(quality, round((time.time() - _rag_t0) * 1000, 1), query)
        except Exception:
            pass
        return result

    except Exception as e:
        logger.error(f"RAG search error: {e}")
        return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}



async def syrabit_library_search(
    query: str,
    board_slug: str = None,
    class_slug: str = None,
) -> list:
    """Search Syrabit's own SEO pages + subjects library.
    Returns up to 4 dicts: {title, url, snippet} — always clickable syrabit.ai links."""
    if not await is_mongo_available():
        return []

    keywords = _extract_keywords(query)
    if not keywords:
        return []

    search_hash = _cache_key(f"libsearch:{query}:{board_slug}:{class_slug}")
    cached = _redis_get_search(search_hash)
    if cached is not None:
        return cached

    pattern = "|".join(re.escape(kw) for kw in keywords[:5])
    rx = {"$regex": pattern, "$options": "i"}
    results: list = []
    seen: set = set()

    try:
        page_filter: dict = {
            "status": "published",
            "$or": [
                {"topic_title": rx},
                {"meta_description": rx},
                {"subject_name": rx},
            ],
        }
        if board_slug:
            page_filter["board_slug"] = board_slug
        if class_slug:
            page_filter["class_slug"] = class_slug

        async with _slow_query(f"syrabit_library_search q={query[:30]}"):
            pages = await db.seo_pages.find(
                page_filter,
                {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1,
                 "topic_slug": 1, "topic_title": 1, "meta_description": 1, "subject_name": 1},
            ).limit(4).to_list(4)

        for p in pages:
            url = (
                f"https://syrabit.ai/{p['board_slug']}/{p['class_slug']}"
                f"/{p['subject_slug']}/{p['topic_slug']}"
            )
            if url not in seen:
                seen.add(url)
                results.append({
                    "title": p.get("topic_title") or f"{p.get('subject_name', '')} — {p['topic_slug']}",
                    "url": url,
                    "snippet": (p.get("meta_description") or "")[:160],
                })
    except Exception as exc:
        logger.debug(f"syrabit_library_search seo_pages error: {exc}")

    # ── 2. Subjects (fills gaps up to 4 results) ───────────────────────────────
    if len(results) < 4:
        try:
            subj_filter: dict = {
                "status": "published",
                "$or": [{"name": rx}, {"description": rx}, {"tags": rx}],
            }
            subjects = await db.subjects.find(
                subj_filter,
                {"_id": 0, "id": 1, "name": 1, "description": 1},
            ).limit(4 - len(results)).to_list(4)

            for s in subjects:
                url = f"https://syrabit.ai/subject/{s['id']}" if s.get("id") else "https://syrabit.ai/library"
                if url not in seen:
                    seen.add(url)
                    results.append({
                        "title": s.get("name", "Syrabit Library"),
                        "url": url,
                        "snippet": (s.get("description") or "")[:160],
                    })
        except Exception as exc:
            logger.debug(f"syrabit_library_search subjects error: {exc}")

    final = results[:1]
    if final:
        _redis_cache_search(search_hash, final)
    return final


async def resolve_rag_context(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    document_text: Optional[str] = None,   # Tier 0 — uploaded document (highest)
) -> dict:
    """
    Master RAG resolver — 4-tier priority chain:

      Tier 0 — Subject document (uploaded .txt file): ALWAYS wins when present
      Tier 1 — DB content chunks (indexed notes/formulas)
      Tier 2 — Subject metadata (descriptions, tags, chapter titles)
    """
    # ── Tier 0: Subject document (uploaded file) ─────────────────────────────
    # When a document is uploaded and the user asks AI from that card,
    # the document is the PRIMARY source — skip all other RAG tiers.
    if document_text and document_text.strip():
        logger.info(f"RAG [TIER 0 — Document]: using uploaded document ({len(document_text)} chars) | query: {query[:50]}")
        # Slice relevant sections: find paragraphs containing query keywords
        keywords = _extract_keywords(query)
        lines = [l.strip() for l in document_text.split('\n') if l.strip()]

        # Score each line by keyword matches
        scored = []
        for i, line in enumerate(lines):
            score = sum(1 for kw in keywords if kw in line.lower())
            scored.append((score, i, line))

        # Keep top-scoring lines + surrounding context, up to 3000 chars
        scored.sort(key=lambda x: -x[0])
        selected_indices = set()
        for score, idx, _ in scored[:8]:
            if score > 0:
                for j in range(max(0, idx - 1), min(len(lines), idx + 3)):
                    selected_indices.add(j)

        if selected_indices:
            relevant = "\n".join(lines[i] for i in sorted(selected_indices))
            relevant = relevant[:1500]
        else:
            # No keyword match → use first 1500 chars of document
            relevant = document_text[:1500]

        return {
            "chunks": [],
            "chapters": [],
            "subjects": [],
            "document_text": relevant,
            "document_full": document_text[:1500],
            "source":  "document",
            "quality": "tier0",
        }
    cached_rag, _card_result, vector_hits = await asyncio.gather(
        rag_search(query, subject_id=subject_id, subject_name=subject_name),
        _fetch_content_card(query, subject_id=subject_id, subject_name=subject_name),  # returns (text, slug_set) or None
        vector_rag_search(query, subject_id=subject_id, top_k=8),
    )

    rag_ctx = dict(cached_rag)

    # Unpack content card tuple → (text, slug_set used for dedup, source_meta)
    content_card_text: Optional[str] = None
    content_card_slugs: set = set()
    if _card_result:
        content_card_text, content_card_slugs, _card_source_meta = _card_result
        rag_ctx["content_card"] = content_card_text
        rag_ctx["content_card_slugs"] = content_card_slugs
        rag_ctx["content_card_meta"] = _card_source_meta
        if rag_ctx["quality"] == "none":
            rag_ctx["quality"] = "high"
            rag_ctx["source"] = "rag"
        logger.info(f"RAG resolve: content card found ({len(content_card_text)} chars, {len(content_card_slugs)} slugs) | query: {query[:50]}")

    # Vector hits: deduplicate against content card slugs before injecting
    if vector_hits:
        deduped = [h for h in vector_hits if h.get("slug") not in content_card_slugs]
        rag_ctx["vector_hits"] = deduped
        if rag_ctx["quality"] == "none":
            rag_ctx["quality"] = "high"
            rag_ctx["source"] = "rag"
        logger.info(f"RAG resolve: vector hits={len(deduped)} (deduped from {len(vector_hits)}, best_sim={deduped[0]['score']:.3f}) | query: {query[:50]}" if deduped else f"RAG resolve: vector hits=0 (all deduped by content card)")

    if rag_ctx["quality"] == "high":
        logger.info(f"RAG resolve: HIGH-QUALITY content (chunks: {len(rag_ctx.get('chunks', []))}, vector: {len(rag_ctx.get('vector_hits', []))}, card: {'yes' if content_card_text else 'no'}) | query: {query[:50]}")
        return rag_ctx

    if rag_ctx["quality"] == "medium":
        logger.info(f"RAG resolve: MEDIUM metadata only | query: {query[:50]}")
        return rag_ctx

    logger.info(f"RAG resolve: NO CONTEXT — AI uses training knowledge | query: {query[:50]}")
    return {"chunks": [], "chapters": [], "subjects": [], "vector_hits": [], "source": "none", "quality": "none"}


async def web_search_fallback(query: str, num_results: int = 5) -> list:
    """Alias kept for internal compatibility — delegates to web_search_with_fallback."""
    return await web_search_with_fallback(query, num_results=num_results)


async def _ddg_text_search(query: str, num_results: int) -> list:
    """DuckDuckGo text search — primary browser-style web search."""
    def _run():
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return results
    try:
        loop = asyncio.get_running_loop()
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=5.0)
        logger.info(f"DDG text search: {len(results)} results | query: {query[:60]}")
        return results
    except Exception as exc:
        logger.warning(f"DDG text search failed: {exc}")
        return []


async def _ddg_news_search(query: str, num_results: int) -> list:
    """DuckDuckGo news search — secondary fallback web source."""
    def _run():
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=num_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("url", r.get("href", "")),
                    "snippet": r.get("body", r.get("excerpt", "")),
                })
        return results
    try:
        loop = asyncio.get_running_loop()
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=5.0)
        logger.info(f"DDG news search: {len(results)} results | query: {query[:60]}")
        return results
    except Exception as exc:
        logger.warning(f"DDG news search failed: {exc}")
        return []


async def web_search_with_fallback(
    query: str,
    num_results: int = 8,
    board_name: str = "",
    class_name: str = "",
    subject_name: str = "",
    scoped_query: str = "",   # Pre-built by SubjectRouter (preferred over manual parts)
) -> list:
    """
    Parallel dual-source web search:
      Base layer  — DuckDuckGo text search with curriculum-scoped query.
                    Uses `scoped_query` when provided (from SubjectRouter Tier 0-3),
                    otherwise builds it from board_name / class_name / subject_name.
      Polish layer — DuckDuckGo news search with the raw user query
                     for open-web enrichment, current examples, reasoning.
    Both run simultaneously. Results tagged with _layer for prompt routing.
    """
    _assert_not_cms_context("web search")
    if scoped_query:
        curriculum_query = scoped_query
    else:
        _ctx_parts = [p.strip() for p in [board_name, class_name, subject_name] if p]
        curriculum_query = " ".join(_ctx_parts + [query]) if _ctx_parts else query

    text_results, news_results = await asyncio.gather(
        _ddg_text_search(curriculum_query, num_results),
        _ddg_news_search(query, max(num_results - 2, 4)),
    )
    for r in text_results:
        r["_layer"] = "base"
    for r in news_results:
        r["_layer"] = "polish"
    combined = text_results + news_results
    logger.info(
        f"Dual web search: {len(text_results)} base (scoped: {curriculum_query[:60]!r}) + "
        f"{len(news_results)} polish (open) | raw: {query[:50]}"
    )
    return combined


_HISTORY_TOKEN_BUDGET = 1500  # max estimated tokens kept in conversation history
_HISTORY_MAX_TURNS = 8        # max message pairs regardless of token budget


def _trim_history(messages: list, token_budget: int = _HISTORY_TOKEN_BUDGET, max_turns: int = _HISTORY_MAX_TURNS) -> list:
    """
    Return the most recent portion of a conversation history that fits within
    the token budget and max-turn limit.  Oldest turns are dropped first.
    Estimation: 1 token ≈ 4 chars (conservative English approximation).
    """
    # Keep only alternating user/assistant pairs (already filtered upstream)
    # Cap by hard turn limit first
    capped = messages[-(max_turns * 2):]

    # Trim from the front until estimated token count is within budget
    while capped:
        total_chars = sum(len(m.get("content", "")) for m in capped)
        if total_chars // 4 <= token_budget:
            break
        # Drop the two oldest messages (one turn)
        capped = capped[2:]

    return capped


def _sources_from_rag_ctx(rag_ctx: dict) -> list:
    """
    Build a sources list directly from the RAG context that was sent to the LLM.
    This ensures the displayed sources always match the grounding context used in
    the prompt (no mismatch from a separate async library search).

    Returns a list of dicts with keys: slug, title, url (compatible with the
    frontend sources format). URLs are auto-built as /learn/{slug} for SEO pages
    so the frontend can render clickable blue links for [PAGE: X] citations.
    When content_card_meta is present, emits a leading content_card source entry
    with type="content_card", card_name, and lesson_name for clean attribution.
    """
    seen = set()
    sources = []

    # Content card attribution — prepend as first source when available
    _cc_meta = rag_ctx.get("content_card_meta")
    if _cc_meta and (_cc_meta.get("card_name") or _cc_meta.get("lesson_name")):
        sources.append({
            "type":         "content_card",
            "card_name":    _cc_meta.get("card_name", ""),
            "lesson_name":  _cc_meta.get("lesson_name", ""),
            "subject_name": _cc_meta.get("subject_name", ""),
            "slug":         "",
            "title":        _cc_meta.get("card_name", "") or _cc_meta.get("lesson_name", ""),
            "url":          "",
        })

    def _build_url(slug: str, provided_url: str, subject_id: str = "") -> str:
        """Return the best available URL for a source."""
        if provided_url:
            return provided_url
        # SEO page slugs map to /learn/{slug}
        if slug and not slug.startswith("chapter/"):
            return f"/learn/{slug}"
        # Chapter slugs: link to subject page so the student can browse
        if slug and slug.startswith("chapter/") and subject_id:
            return f"/subject/{subject_id}"
        return ""

    def _add(slug: str, title: str, url: str = "", subject_id: str = ""):
        if slug and slug not in seen:
            seen.add(slug)
            sources.append({
                "slug":  slug,
                "title": title or slug,
                "url":   _build_url(slug, url, subject_id),
            })

    # Build a lookup: chapter_id → chapter info (title, subject_id) from chunk_chapters
    chunk_chapter_map: dict = {}
    for cc in rag_ctx.get("chunk_chapters", []):
        cid = cc.get("id", "")
        if cid:
            chunk_chapter_map[cid] = cc

    # SEO vector hits (have real topic slugs → /learn/...)
    for hit in rag_ctx.get("vector_hits", []):
        _add(hit.get("slug", ""), hit.get("title", ""), hit.get("url", ""))

    # Chunks — group by parent chapter so 15 chunks from 3 chapters show 3 source entries
    for chunk in rag_ctx.get("chunks", []):
        ch_id = chunk.get("chapter_id", "")
        cc = chunk_chapter_map.get(ch_id, {})
        slug = chunk.get("slug", "") or (f"chapter/{ch_id}" if ch_id else "")
        title = chunk.get("title", "") or cc.get("title", chunk.get("content_type", "Study Material"))
        url = chunk.get("url", "")
        _add(slug, title, url, cc.get("subject_id", ""))

    # Keyword-matched chapters (may add extras not covered by chunks above)
    for ch in rag_ctx.get("chapters", []):
        ch_id = ch.get("id", "")
        slug = ch.get("slug", "") or (f"chapter/{ch_id}" if ch_id else "")
        _add(slug, ch.get("title", ""), ch.get("url", ""), ch.get("subject_id", ""))

    for subj in rag_ctx.get("subjects", []):
        _add(subj.get("slug", ""), subj.get("name", ""), subj.get("url", ""))

    return sources


def build_rag_system_prompt(
    context: dict,
    rag_context: dict,
    user_info: dict = None,
    query: str = "",
    syllabus: dict = None,
    web_results: list = None,
) -> str:
    """
    Selects the adaptive prompt mode (casual / concise / structured) based on
    the student's query, injects their profile, then appends RAG grounding.

    Grounding tiers:
      Tier -1 — syllabus constraints (curriculum boundaries)
      Tier 0 — document (uploaded .txt file — absolute priority)
      Tier 1 — DB content chunks
      Tier 2 — Subject metadata (descriptions, tags, chapter titles)
      Tier 3 — Web search results (fallback when library has no content)
    """
    base_prompt = build_system_prompt(context, user_info=user_info, query=query)
    source      = rag_context.get("source",  "none")
    quality     = rag_context.get("quality", "none")
    chunks      = rag_context.get("chunks",   [])
    chapters    = rag_context.get("chapters", [])
    subjects    = rag_context.get("subjects", [])
    document_text = rag_context.get("document_text", "")
    vector_hits = rag_context.get("vector_hits", [])

    # Compute branded curriculum label once — used in all grounding tiers
    from prompts import _format_board_label as _fbl
    _board_raw = (context.get("board_name", "") or "").strip().upper()
    _board_label = _fbl(_board_raw) if _board_raw else "AssamBoard — AHSEC"
    _curriculum_label = f"{_board_label} Curriculum"

    # ── Mandatory answer intro header ────────────────────────────────────────────
    # Derive subject and chapter from RAG context first, then fallback to user context
    _intro_subject = (subjects[0].get("name", "") if subjects else "") or context.get("subject_name", "")
    _intro_chapter = (chapters[0].get("title", "") if chapters else "") or context.get("chapter_name", "")
    _intro_parts = ["**AssamBoard Curriculum**"]
    if _intro_subject:
        _intro_parts.append(_intro_subject)
    if _intro_chapter:
        _intro_parts.append(_intro_chapter)
    _intro_header = " · ".join(_intro_parts)
    base_prompt += (
        f"\n\nMANDATORY INTRO: Every academic answer MUST begin with this exact header "
        f"on its own line, followed immediately by the answer:\n"
        f"{_intro_header}\n"
        f"Do not add a blank line between the header and the answer. "
        f"Casual greetings and small-talk skip this header."
    )

    grounding = ""

    # ── Tier -1: Syllabus constraints (curriculum boundaries) ───────────────────
    if syllabus and syllabus.get("content"):
        syllabus_content = syllabus.get("content", "")
        syllabus_topics = ", ".join(syllabus.get("topics", [])[:10])
        geo_phrases = syllabus.get("geo_phrases", [])
        grounding = (
            "\n\n---\n"
            f"**CURRICULUM CONSTRAINTS (Tier -1 — {_curriculum_label}):**\n"
            f"You are helping a student from the {_curriculum_label}. "
            "The following represents what this student is expected to know:\n\n"
            f"{syllabus_content}\n\n"
        )
        if syllabus_topics:
            grounding += f"**Key topics:** {syllabus_topics}\n\n"
        grounding += (
            "---\n"
            f"*INSTRUCTION: Keep your answer within the scope of the {_curriculum_label}. "
            "Do not introduce concepts beyond the standard curriculum unless explicitly requested. "
            "Prioritize accuracy over breadth. "
            f"When referencing the curriculum by name, always call it '{_curriculum_label}'. "
            "When relevant, cite specific board exam stats, PYQ frequency data, and authoritative syllabus references.*\n"
        )
        if geo_phrases:
            grounding += (
                "\n**NOTE:** After delivering your factual answer, you may append a brief "
                "closing phrase from the list below — only if it fits naturally and does NOT "
                "alter or qualify any factual statement in your answer:\n"
            )
            for gp in geo_phrases[:5]:
                grounding += f"- {gp}\n"
            grounding += "\n"

    # ── Tier 0: Uploaded subject document ────────────────────────────────────
    if source == "document" and document_text:
        grounding += (
            "\n\n---\n"
            "**GROUNDING CONTEXT (Tier 0 — Uploaded Study Document):**\n"
            "The student is asking about content from a specific uploaded study document. "
            "Base your answer **exclusively** on this document. Quote directly when possible.\n\n"
            "**Document content:**\n"
            f"{document_text}\n\n"
            "---\n"
            "*INSTRUCTION: Answer ONLY from the document above. "
            "If the question cannot be answered from this document, say so clearly "
            "and offer to answer from general knowledge instead.*"
        )
        return base_prompt + grounding

    content_card = rag_context.get("content_card", "")

    # ── Tier 1/2: Curriculum DB context (including vector hits) ─────────────
    if source == "rag" and (chunks or subjects or chapters or content_card or vector_hits):

        if quality == "high":
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Syrabit Library — 97% Accuracy Mode):**\n"
                "The following is the COMPLETE content from the student's actual curriculum database. "
                "Every answer MUST cite sources using [PAGE: slug] format. "
                "Quote verbatim where possible.\n\n"
            )
            # Vector hits — highest confidence (semantic similarity ranked)
            if vector_hits:
                grounding += "**[VECTOR SEARCH RESULTS — Semantically matched pages]:**\n\n"
                for hit in vector_hits:
                    slug = hit.get("slug", "")
                    title = hit.get("title", slug)
                    content = hit.get("content", "")
                    score = hit.get("score", 0)
                    grounding += f"[PAGE: {slug}] — {title} (relevance: {score:.2f})\n{content}\n\n"

            if content_card:
                grounding += f"**[CONTENT CARD — Full page content]:**\n{content_card}\n\n"
            for i, c in enumerate(chunks, 1):
                title = c.get("content_type", "content").capitalize()
                grounding += f"**[BLOCK {i} — {title}]:**\n{c.get('content', '')[:1500]}\n\n"
            grounding += (
                "---\n"
                "**ACCURACY LOCK:**\n"
                "1. Answer ONLY from the grounding above. Structure: Explanation → Key Points → Examples → Sources\n"
                "2. End every answer with: 'Sources: [PAGE: slug1], [PAGE: slug2]' citing which pages you used.\n"
                "3. If the answer is NOT in the grounding: check for Tier 3 web search results below — "
                f"use those and label 'From web search:'. If those are absent, answer from {_curriculum_label} "
                f"knowledge and note 'Based on {_curriculum_label} knowledge:'. Never stop without an answer.\n"
                "4. NEVER hallucinate. NEVER invent facts not present in the grounding or web results.\n"
                "5. Temperature is 0.05 — be deterministic and precise.*"
            )

        else:
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Curriculum Metadata):**\n"
            )
            if content_card:
                grounding += f"**[Content Card — Full Page Content]**\n{content_card}\n\n"
            else:
                grounding += (
                    "The following curriculum metadata is from the syllabus database. "
                    "Use it to frame an accurate, board-aligned answer.\n\n"
                )
            if subjects:
                grounding += "**Matching subjects in database:**\n"
                for s in subjects:
                    desc = s.get("description", "")[:300]
                    tags = ", ".join(s.get("tags", [])[:8])
                    grounding += f"- **{s.get('name', '')}**: {desc}"
                    if tags:
                        grounding += f" *(key topics: {tags})*"
                    grounding += "\n"

            if chapters:
                grounding += "\n**Chapters & content in this subject:**\n"
                for ch in chapters:
                    title = ch.get('title', '')
                    desc = (ch.get('description') or '').strip()
                    ch_content = (ch.get('content') or '').strip()
                    grounding += f"- **{title}**"
                    if desc:
                        grounding += f": {desc[:300]}"
                    if ch_content and not desc:
                        grounding += f": {ch_content[:400]}"
                    grounding += "\n"

            grounding += (
                "\n---\n"
                f"*ACCURACY INSTRUCTION: Answer using the {_curriculum_label} context above as the primary source. "
                f"Cross-reference with your training knowledge for the {_curriculum_label} in Assam. "
                f"When referencing the curriculum by name, always call it '{_curriculum_label}'. "
                "If you are unsure about any specific fact, state it clearly rather than guessing. "
                "Do not add examples or exam tips unless the student explicitly asks.*"
            )

    # ── Live Web Search Results (dual-layer: base + polish) ─────────────────
    if web_results:
        base_results   = [r for r in web_results if r.get("_layer") != "polish"]
        polish_results = [r for r in web_results if r.get("_layer") == "polish"]

        web_block = "\n\n---\n"

        if base_results:
            web_block += (
                "**WEB SEARCH — BASE LAYER (browser results, primary facts):**\n"
                "Build the core of your answer from these results. "
                "Use them as the factual foundation — definitions, explanations, data points.\n\n"
            )
            for i, r in enumerate(base_results, 1):
                title   = r.get("title", "")
                url     = r.get("url", "")
                snippet = r.get("snippet", "")
                web_block += f"[Base {i}] {title}\n{snippet}\nSource: {url}\n\n"

        if polish_results:
            web_block += (
                "**WEB SEARCH — POLISH LAYER (news/open web, enrichment):**\n"
                "Use these to add current context, recent examples, or relevance to the student's "
                "specific situation. Blend naturally into the answer — do not list them separately.\n\n"
            )
            for i, r in enumerate(polish_results, 1):
                title   = r.get("title", "")
                url     = r.get("url", "")
                snippet = r.get("snippet", "")
                web_block += f"[Polish {i}] {title}\n{snippet}\nSource: {url}\n\n"

        web_block += (
            "---\n"
            "*INSTRUCTION: Build the answer from the Base layer first. "
            "Then enrich it with relevant details from the Polish layer. "
            "Do not fabricate facts beyond what the results contain.*\n"
        )
        grounding += web_block

    return base_prompt + grounding if grounding else base_prompt


_LLM_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("LLM_MAX_CONCURRENT", 20)))
_LLM_BATCH_WINDOW_MS = int(os.environ.get("LLM_BATCH_WINDOW_MS", 15))

class _LlmBatcher:
    """
    Smart LLM Batching: deduplicates identical questions arriving within a
    short window so only one API call is made per unique question.
    """
    def __init__(self):
        self._pending: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._stats = {"batched": 0, "deduped": 0, "solo": 0, "errors": 0}

    async def call(self, messages: list, model: str = None, max_tokens: int = 1024) -> str:
        batch_key = _cache_key(
            "".join(m.get("content", "") for m in messages if m.get("role") in ("user", "system"))
        )

        async with self._lock:
            if batch_key in self._pending:
                self._stats["deduped"] += 1
                logger.info(f"LLM batch DEDUP: {batch_key} — piggy-backing on in-flight request")
                future = self._pending[batch_key]
        
            else:
                future = asyncio.get_event_loop().create_future()
                self._pending[batch_key] = future
                self._stats["batched"] += 1
                asyncio.ensure_future(self._execute(batch_key, messages, model, max_tokens, future))

        try:
            return await asyncio.wait_for(future, timeout=120)
        except asyncio.TimeoutError:
            logger.error(f"LLM batch TIMEOUT: {batch_key}")
            raise HTTPException(status_code=504, detail="AI response timed out. Please try again.")

    async def _execute(self, batch_key: str, messages: list, model: str, max_tokens: int, future: asyncio.Future):
        await asyncio.sleep(_LLM_BATCH_WINDOW_MS / 1000.0)

        try:
            async with _LLM_SEMAPHORE:
                result = await _call_llm_raw(messages, model, max_tokens)
            future.set_result(result)
        except Exception as e:
            self._stats["errors"] += 1
            if not future.done():
                future.set_exception(e)
        finally:
            async with self._lock:
                self._pending.pop(batch_key, None)

    @property
    def stats(self):
        return {**self._stats, "pending": len(self._pending)}

_llm_batcher = _LlmBatcher()

_LLM_PROVIDERS = []
# Gemini first — most reliable right now (Fireworks suspended, Groq rate-limited)
if _GEMINI_KEY:
    _LLM_PROVIDERS.append({"provider": "gemini",      "key": _GEMINI_KEY,     "default_model": "gemini-2.5-flash-preview-05-20"})
if _GROQ_KEY and _GROQ_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "groq",        "key": _GROQ_KEY,       "default_model": "llama-3.1-8b-instant"})
if _FIREWORKS_KEY:
    _LLM_PROVIDERS.append({"provider": "fireworksai", "key": _FIREWORKS_KEY,  "default_model": "accounts/fireworks/models/deepseek-v3p2"})
if _SARVAM_LLM_KEY:
    _LLM_PROVIDERS.append({"provider": "sarvam",      "key": _SARVAM_LLM_KEY, "default_model": "sarvam-m"})
if _XAI_KEY:
    _LLM_PROVIDERS.append({"provider": "xai",         "key": _XAI_KEY,        "default_model": "grok-3-fast"})
if _OPENAI_KEY and _OPENAI_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "openai",      "key": _OPENAI_KEY,     "default_model": "gpt-4o-mini"})

_MODEL_PROVIDER_MAP = {
    "sarvam-m": "sarvam",
    "sarvam-30b": "sarvam",
    "sarvam-30b-16k": "sarvam",
    "sarvam-105b": "sarvam",
    "sarvam-105b-32k": "sarvam",
    "accounts/fireworks/models/qwen2p5-72b-instruct": "fireworksai",
    "accounts/fireworks/models/qwen3-235b-a22b": "fireworksai",
    "accounts/fireworks/models/deepseek-v3p2": "fireworksai",
    "accounts/fireworks/models/gpt-oss-120b": "fireworksai",
    "llama-3.3-70b-versatile": "groq",
    "llama-3.1-8b-instant": "groq",
    # UI display aliases
    "openai/gpt-oss-20b": "groq",        # SLM: fast Groq model
    "openai/gpt-oss-120b": "fireworksai", # MLM: full Fireworks gpt-oss-120b
}

# Map display-alias model names to the actual API model ID to send to the provider
_MODEL_ALIAS_MAP = {
    "openai/gpt-oss-20b":  "llama-3.3-70b-versatile",              # Groq (primary)
    "openai/gpt-oss-120b": "accounts/fireworks/models/gpt-oss-120b", # Fireworks
}

# ── SLM slot table ────────────────────────────────────────────────────────────
# Each entry: (provider, model, max_concurrent)
# Models chosen for HIGHEST RPS on their respective providers.
# Multiple slots per provider = parallel streams up to max_concurrent each.
#
#  Groq        llama-3.3-70b-versatile — PRIMARY: quality + fast, 30 RPM
#              llama-3.1-8b-instant    — fallback: sub-second TTFT, highest TPD
#  Gemini      gemini-2.0-flash-lite   — 30 RPM free, lowest latency Gemini
#              gemini-2.0-flash        — 15 RPM free, higher quality
#  Fireworks   deepseek-v3p2           — high-quality, pay-per-token (no hard RPM cap)
#  Bedrock     amazon.nova-micro-v1:0  — free tier: 30 RPM cap, lowest latency on Bedrock
#                                        paid tier: 66.7 RPS / 33K TPS (no cap)
_SLM_SLOT_CANDIDATES = [
    # Gemini 2.5 Flash Preview — primary: best accuracy + reasoning
    ("gemini",      "gemini-2.5-flash-preview-05-20",                    6),
    # Gemini 2.0 Flash — fallback: high TPS when primary is rate-limited
    ("gemini",      "gemini-2.0-flash",                                  6),
    # Gemini 2.0 Flash Lite — hot fallback: highest TPS, lowest latency
    ("gemini",      "gemini-2.0-flash-lite",                             8),
    # Groq as secondary (rate-limited but fast when available)
    ("groq",        "llama-3.3-70b-versatile",                           8),
    ("groq",        "llama-3.1-8b-instant",                              4),
    # Fireworks last (currently suspended)
    ("fireworksai", "accounts/fireworks/models/deepseek-v3p2",           8),
    ("bedrock",     "amazon.nova-micro-v1:0",                            2),
]

class _SmartKeyPool:
    """Concurrent smart pool — maximises RPS across all providers.

    Each slot has:
      sem            asyncio.Semaphore(max_concurrent) — caps parallel in-flight requests
      last_used      float timestamp — drives LRU round-robin between equal-capacity slots
      cooldown_until float timestamp — set after 429 / errors
      errors         int            — error count for exponential back-off

    pick() prefers slots with spare semaphore capacity first (lowest in-flight),
    then falls back to LRU among all non-cooled slots.
    """
    _RL_COOLDOWN  = 60.0   # 429 rate-limit → skip slot for 60 s
    _ERR_COOLDOWN = 15.0   # any other error → skip for 15 s

    def __init__(self, candidates: list):
        pmap = {p["provider"]: p["key"] for p in _LLM_PROVIDERS}
        self._slots = []
        for pname, model_id, max_con in candidates:
            key = pmap.get(pname, "")
            # bedrock uses AWS env-var credentials, not a provider API key
            # sarvam also has no key in pmap
            if key or pname in ("sarvam", "bedrock"):
                # for bedrock: only add slot if AWS credentials are present
                if pname == "bedrock" and not (_AWS_ACCESS_KEY and _AWS_SECRET_KEY):
                    logger.info("SLM pool: skipping bedrock slot (AWS credentials not set)")
                    continue
                self._slots.append({
                    "provider": pname, "key": key, "model": model_id,
                    "sem": asyncio.Semaphore(max_con), "max_con": max_con,
                    "last_used": 0.0, "cooldown_until": 0.0, "errors": 0,
                })
        logger.info(
            f"SLM SmartKeyPool active slots: "
            f"{[(s['provider'], s['model'], s['max_con']) for s in self._slots]}"
        )

    def pick(self):
        """Return best slot: not cooling down, prefer spare capacity, then LRU."""
        now = time.time()
        available = [s for s in self._slots if now >= s["cooldown_until"]]
        if not available:
            return None
        # Primary: slots that still have semaphore capacity → lowest in-flight first
        with_capacity = [s for s in available if s["sem"]._value > 0]
        pool = with_capacity if with_capacity else available
        # Among equal-capacity slots, pick least-recently-used to spread load
        return min(pool, key=lambda s: (s["max_con"] - s["sem"]._value, s["last_used"]))

    def mark_ok(self, slot):
        slot["last_used"] = time.time()
        slot["errors"] = 0

    def mark_429(self, slot):
        slot["cooldown_until"] = time.time() + self._RL_COOLDOWN
        logger.warning(
            f"SLM pool: {slot['provider']}/{slot['model']} → 429 rate-limit, "
            f"cooling {self._RL_COOLDOWN}s"
        )

    def mark_403(self, slot):
        slot["cooldown_until"] = float("inf")  # permanently disabled for session
        logger.error(
            f"SLM pool: {slot['provider']}/{slot['model']} → 403 Forbidden (auth/permission error). "
            f"Slot permanently disabled. Check the API key for '{slot['provider']}'."
        )

    def mark_err(self, slot):
        slot["errors"] += 1
        cd = min(self._ERR_COOLDOWN * slot["errors"], 120.0)   # cap at 2 min
        slot["cooldown_until"] = time.time() + cd
        logger.warning(
            f"SLM pool: {slot['provider']}/{slot['model']} → error #{slot['errors']}, "
            f"cooling {cd:.0f}s"
        )

    @property
    def all_slots(self):
        return self._slots

_slm_pool = _SmartKeyPool(_SLM_SLOT_CANDIDATES)

def _resolve_provider_for_model(model: str):
    preferred = _MODEL_PROVIDER_MAP.get(model)
    if preferred:
        for p in _LLM_PROVIDERS:
            if p["provider"] == preferred:
                return p["provider"], p["key"]
    if _LLM_PROVIDERS:
        return _LLM_PROVIDERS[0]["provider"], _LLM_PROVIDERS[0]["key"]
    return LLM_PROVIDER, OPENAI_API_KEY

async def _call_sarvam_llm(messages: list, api_key: str, model: str, max_tokens: int) -> str:
    """Non-streaming call to Sarvam LLM — reuses persistent sarvam_llm_client (zero TCP overhead).
    Adds SARVAM_THINK_BUFFER so the <think> block never consumes the user's answer budget."""
    api_max = max_tokens + SARVAM_THINK_BUFFER  # thinking tokens don't count toward user quota
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": api_max,
        "temperature": 0.05,
        "stream": False,
    }
    client = sarvam_llm_client
    if client is None:
        raise HTTPException(status_code=503, detail="Sarvam LLM client not initialised")
    resp = await client.post("/v1/chat/completions", json=payload)
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]["message"]
    content = choice.get("content") or ""
    reasoning = choice.get("reasoning_content") or ""
    result = content if content else reasoning
    result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
    result = re.sub(r'<think>.*$', '', result, flags=re.DOTALL).strip()
    return result

async def _call_single_provider(messages: list, provider: str, api_key: str, model: str, max_tokens: int) -> str:
    if provider == "sarvam":
        return await _call_sarvam_llm(messages, api_key, model, max_tokens)

    system_msg = ""
    user_msg = ""
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        elif m["role"] == "user":
            user_msg = m["content"]

    chat = LlmChat(
        api_key=api_key,
        session_id=str(uuid.uuid4()),
        system_message=system_msg or "You are a helpful AI tutor.",
    ).with_model(provider, model)

    response = await chat.send_message(UserMessage(text=user_msg))
    response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
    return response

async def _call_llm_raw(messages: list, model: str = None, max_tokens: int = 1024) -> str:
    import time as _t
    use_model = model or LLM_MODEL
    primary_provider, primary_key = _resolve_provider_for_model(use_model)

    if not primary_key and not _LLM_PROVIDERS:
        raise HTTPException(status_code=503, detail="LLM API key not configured")

    tried: set = set()  # tracks (provider, model) tuples — allows multiple models per provider
    last_err = None

    provider, key = primary_provider, primary_key
    try_model = use_model
    try:
        tried.add((provider, try_model))
        _t0 = _t.perf_counter()
        result = await _call_single_provider(messages, provider, key, try_model, max_tokens)
        _dur = int((_t.perf_counter() - _t0) * 1000)
        logger.info(f"llm_call provider={provider} model={try_model} duration_ms={_dur} tokens_approx={len(result.split())}")
        return result
    except Exception as e:
        last_err = e
        logger.warning(f"LLM primary failed ({provider}/{try_model}): {type(e).__name__}: {str(e)[:150]}")

    for fallback in _LLM_PROVIDERS:
        fb_model = fallback["default_model"]
        if (fallback["provider"], fb_model) in tried:
            continue
        tried.add((fallback["provider"], fb_model))
        try:
            _t0 = _t.perf_counter()
            result = await _call_single_provider(messages, fallback["provider"], fallback["key"], fb_model, max_tokens)
            _dur = int((_t.perf_counter() - _t0) * 1000)
            logger.info(f"llm_call provider={fallback['provider']} model={fb_model} duration_ms={_dur} tokens_approx={len(result.split())} fallback=true")
            return result
        except Exception as e:
            last_err = e
            logger.warning(f"LLM fallback failed ({fallback['provider']}/{fb_model}): {type(e).__name__}: {str(e)[:150]}")

    logger.error(f"All LLM providers exhausted. Last error: {last_err}")
    raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please try again.")

async def call_llm_api(messages: list, model: str = None, max_tokens: int = 2048) -> str:
    """Smart-batched LLM call: deduplicates identical requests, limits concurrency."""
    return await _llm_batcher.call(messages, model, max_tokens)


def _stream_filter_think(token_iter):
    """Async generator that strips <think>...</think> blocks from a token stream."""
    return token_iter  # caller handles filtering inline

_THINK_BUDGET_HINT = "/think in one sentence. Answer immediately.\n"

def _inject_think_budget(messages: list) -> list:
    """Prepend a concise reasoning directive to the system message so sarvam-m
    spends fewer tokens in its <think> block, reducing TTFT significantly."""
    out = []
    injected = False
    for m in messages:
        if m.get("role") == "system" and not injected:
            out.append({**m, "content": _THINK_BUDGET_HINT + m["content"]})
            injected = True
        else:
            out.append(m)
    if not injected:
        out.insert(0, {"role": "system", "content": _THINK_BUDGET_HINT})
    return out

async def _stream_sarvam(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token SSE streaming from Sarvam — reuses persistent sarvam_llm_client (zero TCP overhead).
    Adds SARVAM_THINK_BUFFER so <think> reasoning never crowds out the user's answer budget.

    Speed knobs applied:
      • temperature=0.0  — greedy decoding, no sampling overhead
      • top_p/freq/pres penalties all zeroed for minimal compute
      • _inject_think_budget — caps reasoning tokens at the prompt level
    """
    api_max = max_tokens + SARVAM_THINK_BUFFER
    patched = _inject_think_budget(messages)
    payload = {
        "model": model,
        "messages": patched,
        "max_tokens": api_max,
        "temperature": 0.0,
        "top_p": 1.0,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stream": True,
    }
    client = sarvam_llm_client
    if client is None:
        raise HTTPException(status_code=503, detail="Sarvam LLM client not initialised")
    async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
        if resp.status_code >= 400:
            body = await resp.aread()
            logger.error(f"Sarvam {resp.status_code} error body: {body.decode()[:500]}")
            resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            try:
                chunk = json.loads(raw)
                delta = chunk["choices"][0]["delta"]
                token = delta.get("content") or ""
                if token:
                    yield token
            except Exception:
                continue

async def _stream_gemini(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token streaming from Google Gemini via its OpenAI-compatible endpoint."""
    import openai as _oai
    client = _oai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, stream=True, temperature=0.05,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content

async def _stream_xai(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token streaming from xAI Grok via its OpenAI-compatible endpoint."""
    import openai as _oai
    client = _oai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, stream=True, temperature=0.05,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content

async def _stream_bedrock(messages: list, model: str, max_tokens: int):
    """Token-by-token streaming from Amazon Bedrock via Converse streaming API.
    boto3 is synchronous — runs in a thread pool; tokens passed back via asyncio.Queue.
    Supports Amazon Nova family (nova-micro, nova-lite, nova-pro) and any Converse-compatible model.
    """
    if not _AWS_ACCESS_KEY or not _AWS_SECRET_KEY:
        raise ValueError("AWS credentials not configured (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)")

    # Convert OpenAI-format messages to Bedrock Converse format
    system_parts = []
    converse_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system_parts.append({"text": content})
        else:
            converse_messages.append({"role": role, "content": [{"text": content}]})

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _sync_stream():
        try:
            import boto3 as _boto3
            client = _boto3.client(
                "bedrock-runtime",
                region_name=_AWS_REGION,
                aws_access_key_id=_AWS_ACCESS_KEY,
                aws_secret_access_key=_AWS_SECRET_KEY,
            )
            kwargs = dict(
                modelId=model,
                messages=converse_messages,
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.05},
            )
            if system_parts:
                kwargs["system"] = system_parts
            resp = client.converse_stream(**kwargs)
            for event in resp["stream"]:
                if "contentBlockDelta" in event:
                    text = event["contentBlockDelta"].get("delta", {}).get("text", "")
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            loop.call_soon_threadsafe(queue.put_nowait, None)   # sentinel → done
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)

    loop.run_in_executor(None, _sync_stream)

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item


async def call_llm_api_stream(messages: list, model: str = None, max_tokens: int = 2048):
    """
    Real token-by-token streaming from the LLM provider.
    Uses native streaming APIs for instant first-token delivery.
    Supports: Sarvam, Groq, Fireworks, Gemini, xAI, Bedrock.
    If the requested model name is not in _MODEL_PROVIDER_MAP (e.g. a display-only alias
    like 'openai/gpt-oss-20b'), the resolved provider's default model is used instead.
    """
    use_model_raw = model or LLM_MODEL
    # Resolve display-alias → real API model name (e.g. openai/gpt-oss-20b → llama-3.3-70b-versatile)
    use_model_resolved = _MODEL_ALIAS_MAP.get(use_model_raw, use_model_raw)
    provider, key = _resolve_provider_for_model(use_model_resolved)
    if use_model_raw != use_model_resolved:
        logger.info(f"Model alias '{use_model_raw}' → '{use_model_resolved}' ({provider})")
    # If still not a known API model, fall back to provider default
    if use_model_resolved not in _MODEL_PROVIDER_MAP:
        matched = next((p for p in _LLM_PROVIDERS if p["provider"] == provider), None)
        use_model = matched["default_model"] if matched else LLM_MODEL
        logger.info(f"Unknown model '{use_model_resolved}' → provider default '{use_model}' ({provider})")
    else:
        use_model = use_model_resolved

    if not key and provider != "sarvam":
        yield f"data: {json.dumps({'error': 'LLM API key not configured'})}\n\n"
        return

    in_think = False
    buf = ""

    # Batch small tokens before serialising — reduces JSON ops from ~150 → ~8 per response
    _SSE_BATCH = 8    # flush frequently — words appear one-by-one, not in large chunks

    async def _emit_tokens(token_source):
        nonlocal in_think, buf
        _CLOSE_KEEP = len('</think>') - 1   # 7
        think_done  = False  # once True: no more think-blocks possible → fast path
        batch       = ""     # accumulator for batched SSE content

        async for token in token_source:
            # ── Fast path: think block already finished, just batch & yield ──
            if think_done:
                batch += token
                if len(batch) >= _SSE_BATCH:
                    yield f"data: {json.dumps({'content': batch})}\n\n"
                    batch = ""
                continue

            # ── Slow path: still scanning for <think>...</think> ─────────────
            buf += token
            while buf:
                if in_think:
                    close_idx = buf.find('</think>')
                    if close_idx != -1:
                        buf = buf[close_idx + 8:]
                        in_think   = False
                        think_done = True   # no more think blocks after this
                        # flush any content that immediately follows </think>
                        if buf:
                            batch += buf
                            buf = ""
                            if len(batch) >= _SSE_BATCH:
                                yield f"data: {json.dumps({'content': batch})}\n\n"
                                batch = ""
                        break
                    else:
                        buf = buf[-_CLOSE_KEEP:] if len(buf) > _CLOSE_KEEP else buf
                        break
                else:
                    open_idx = buf.find('<think>')
                    if open_idx != -1:
                        before = buf[:open_idx]
                        if before:
                            batch += before
                            if len(batch) >= _SSE_BATCH:
                                yield f"data: {json.dumps({'content': batch})}\n\n"
                                batch = ""
                        buf      = buf[open_idx + 7:]
                        in_think = True
                    elif buf.endswith(('<', '<t', '<th', '<thi', '<thin', '<think')):
                        partial_start = buf.rfind('<')
                        candidate     = buf[partial_start:]
                        if '<think>'[:len(candidate)] == candidate:
                            before = buf[:partial_start]
                            if before:
                                batch += before
                                if len(batch) >= _SSE_BATCH:
                                    yield f"data: {json.dumps({'content': batch})}\n\n"
                                    batch = ""
                            buf = candidate
                            break
                        else:
                            batch += buf
                            buf    = ""
                            if len(batch) >= _SSE_BATCH:
                                yield f"data: {json.dumps({'content': batch})}\n\n"
                                batch = ""
                    else:
                        batch += buf
                        buf    = ""
                        if len(batch) >= _SSE_BATCH:
                            yield f"data: {json.dumps({'content': batch})}\n\n"
                            batch = ""
                        break

        # Flush any remaining content
        if batch and not in_think:
            yield f"data: {json.dumps({'content': batch})}\n\n"
        if buf and not in_think:
            yield f"data: {json.dumps({'content': buf})}\n\n"

    async def _stream_from_provider(p_name: str, p_key: str, p_model: str):
        """Yield raw tokens from a provider. Raises on failure."""
        if p_name == "sarvam":
            async for token in _stream_sarvam(messages, p_key, p_model, max_tokens):
                yield token
        elif p_name == "gemini":
            logger.info(f"LLM stream: provider=gemini, model={p_model}")
            async for token in _stream_gemini(messages, p_key, p_model, max_tokens):
                yield token
        elif p_name == "xai":
            logger.info(f"LLM stream: provider=xai, model={p_model}")
            async for token in _stream_xai(messages, p_key, p_model, max_tokens):
                yield token
        elif p_name == "bedrock":
            logger.info(f"LLM stream: provider=bedrock, model={p_model}")
            async for token in _stream_bedrock(messages, p_model, max_tokens):
                yield token
        else:
            logger.info(f"LLM stream: provider={p_name}, model={p_model}")
            chat = LlmChat(api_key=p_key or OPENAI_API_KEY, session_id=str(uuid.uuid4())).with_model(p_name, p_model)
            async for token in chat.stream_messages(messages, max_tokens=max_tokens):
                yield token

    # ── Syrabit SLM: concurrent smart pool ──────────────────────────────────────
    # pick() returns highest-capacity, least-recently-used slot not in cooldown.
    # async with slot["sem"] lets up to max_concurrent requests run in parallel.
    # asyncio.wait_for enforces a per-slot timeout so a slow provider never
    # blocks the pool — the next slot is tried immediately on timeout.
    _SLM_SLOT_TIMEOUT = 25.0   # max seconds to wait for first token from any slot

    async def _collect_stream(p_name, p_key, p_model):
        """Buffer entire token stream into a list and return it (for timeout wrapper)."""
        tokens = []
        async for chunk in _emit_tokens(_stream_from_provider(p_name, p_key, p_model)):
            tokens.append(chunk)
        return tokens

    if use_model_raw == "openai/gpt-oss-20b":
        _tried = 0
        while _tried < len(_slm_pool.all_slots):
            slot = _slm_pool.pick()
            if slot is None:
                break
            _tried += 1
            p_name, p_key, p_model = slot["provider"], slot["key"], slot["model"]
            try:
                async with slot["sem"]:          # acquire capacity; released after stream
                    chunks = await asyncio.wait_for(
                        _collect_stream(p_name, p_key, p_model),
                        timeout=_SLM_SLOT_TIMEOUT,
                    )
                if chunks:
                    _slm_pool.mark_ok(slot)
                    for chunk in chunks:
                        yield chunk
                    return
                _slm_pool.mark_err(slot)
                logger.warning(f"SLM pool: {p_name}/{p_model} yielded no tokens")
            except asyncio.TimeoutError:
                _slm_pool.mark_err(slot)
                logger.warning(f"SLM pool: {p_name}/{p_model} timed out after {_SLM_SLOT_TIMEOUT}s → trying next")
                continue
            except Exception as e:
                err_str = str(e)
                is_429 = "429" in err_str or "rate" in err_str.lower() or "quota" in err_str.lower() or "throttl" in err_str.lower()
                is_403 = "403" in err_str or "forbidden" in err_str.lower() or "permission" in err_str.lower() or "unauthorized" in err_str.lower()
                if is_429:
                    _slm_pool.mark_429(slot)
                elif is_403:
                    _slm_pool.mark_403(slot)
                else:
                    _slm_pool.mark_err(slot)
                logger.warning(f"SLM pool: {p_name}/{p_model} failed ({type(e).__name__}: {err_str[:80]})")
                continue
        yield f"data: {json.dumps({'error': 'All AI providers temporarily unavailable'})}\n\n"
        return

    # ── All other models: single provider ───────────────────────────────────────
    try:
        async for chunk in _emit_tokens(_stream_from_provider(provider, key, use_model)):
            yield chunk
    except HTTPException as http_err:
        yield f"data: {json.dumps({'error': str(http_err.detail)})}\n\n"
    except Exception as e:
        logger.error(f"LLM streaming error: {type(e).__name__}: {str(e)[:200]}")
        yield f"data: {json.dumps({'error': 'AI service temporarily unavailable'})}\n\n"

# ─────────────────────────────────────────────
# HELPERS: Supabase user operations
# Uses run_in_executor to never block the async event loop
# ─────────────────────────────────────────────

import concurrent.futures as _cf
_THREAD_POOL = _cf.ThreadPoolExecutor(max_workers=50)

def _run_sync(fn):
    """Execute a sync supabase-py call in a background thread."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_THREAD_POOL, fn)

async def _supa(fn):
    """Await a sync supabase-py operation non-blockingly."""
    return await asyncio.get_event_loop().run_in_executor(_THREAD_POOL, fn)

# ─────────────────────────────────────────────────────────────────────────────
# DATA ACCESS LAYER
# Architecture:
#   Supabase layer (users, auth, credits, plans, conversations_meta)
#     └─ Primary:   Replit PostgreSQL via asyncpg  (always available)
#     └─ Mirror:    Supabase REST client           (when SUPABASE_URL configured)
#   MongoDB layer  (RAG, syllabus, chapters, topics, full conversations)
#     └─ Primary:   MongoDB Atlas                  (when MONGO_URL configured)
# ─────────────────────────────────────────────────────────────────────────────

def _pg_row(row) -> dict:
    """Convert asyncpg Record to plain dict, parsing JSON fields."""
    if row is None:
        return None
    d = dict(row)
    for field in ("saved_subjects", "messages"):
        if field in d and isinstance(d[field], str):
            try: d[field] = json.loads(d[field])
            except: d[field] = [] if field == "messages" else []
    return d

def _pg_rows(rows) -> list:
    return [_pg_row(r) for r in rows] if rows else []

def _pg_user_cols():
    return """id, name, email, password_hash, plan, credits_used, credits_limit,
              document_access, onboarding_done, is_admin, status, bio, phone,
              avatar_url, saved_subjects::text, has_free_credits_issued,
              board_id, board_name, class_id, class_name, stream_id, stream_name, created_at"""

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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            saved = json.dumps(user.get("saved_subjects", []))
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO users (id, name, email, password_hash, plan, credits_used,
                       credits_limit, document_access, onboarding_done, is_admin, status,
                       bio, phone, avatar_url, saved_subjects, has_free_credits_issued,
                       board_id, board_name, class_id, class_name, stream_id, stream_name, created_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16,
                               $17,$18,$19,$20,$21,$22,$23)
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
                    user.get("created_at","")
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
    "saved_subjects", "deletion_requested_at", "deletion_hard_at",
    "last_seen", "onboarding_done",
    "board_id", "board_name", "class_id", "class_name",
    "stream_id", "stream_name",
})

_ALLOWED_CONV_COLUMNS = frozenset({
    "title", "preview", "subject_id", "subject_name",
    "starred", "archived", "messages", "tokens", "updated_at",
})

_ALLOWED_SETTINGS_COLUMNS = frozenset({
    "registrations_open", "maintenance_mode", "app_name", "tagline",
})

async def supa_update_user(uid: str, updates: dict):
    _invalidate_user_cache(uid)  # always bust cache before touching DB
    if pg_pool and updates:
        try:
            unknown = set(updates) - _ALLOWED_USER_COLUMNS
            if unknown:
                raise ValueError(f"supa_update_user: disallowed column(s): {unknown}")
            cols = []
            vals = []
            for i, (k, v) in enumerate(updates.items(), start=1):
                if k == "saved_subjects":
                    cols.append(f"{k} = ${i}::jsonb")
                    vals.append(json.dumps(v))
                else:
                    cols.append(f"{k} = ${i}")
                    vals.append(v)
            vals.append(uid)
            sql = f"UPDATE users SET {', '.join(cols)} WHERE id = ${len(vals)}"
            async with pg_pool.acquire() as conn:
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
    """Atomically deduct 1 credit only if credits_used < credits_limit.
    Returns True on success, False if limit already reached (race condition guard).
    Uses PG UPDATE...WHERE for atomic check+increment; falls back to Redis INCR/DECR
    CAS pattern; last resort falls back to Supabase with explicit limit guard.
    """
    _invalidate_user_cache(uid)
    # ── Primary: PostgreSQL atomic UPDATE (multi-worker safe) ──────────────
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                result = await conn.execute(
                    """UPDATE users
                          SET credits_used = credits_used + 1
                        WHERE id = $1
                          AND credits_used < credits_limit""",
                    uid,
                )
            if result and result.split()[-1] != '0':
                return True
            return False
        except Exception as e:
            logger.warning(f"atomic_deduct_credit pg failed, falling back: {e}")
    # ── Fallback: Redis INCR + rollback CAS (atomic per Redis INCR semantics) ──
    if redis_client:
        try:
            redis_key = f"credits:{uid}"
            # Seed the counter from the authoritative used value if missing
            redis_client.set(redis_key, current_used, ex=86400, nx=True)
            new_count = redis_client.incr(redis_key)
            if new_count > current_limit:
                # Over limit — roll back the increment
                redis_client.decr(redis_key)
                return False
            # Propagate the new count to Supabase asynchronously (best-effort)
            await supa_update_user(uid, {"credits_used": int(new_count)})
            return True
        except Exception as e:
            logger.warning(f"atomic_deduct_credit redis failed, falling back: {e}")
    # ── Last resort: Supabase with explicit limit guard ─────────────────────
    if current_used >= current_limit:
        return False
    new_used = current_used + 1
    await supa_update_user(uid, {"credits_used": new_used})
    return True

async def supa_list_users():
    """Return all non-admin users, merging PG + Supabase so no one is lost."""
    pg_users = []
    supa_users = []

    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    # L1: in-memory cache (microseconds)
    _ck = _conv_cache_key(conv_id, uid)
    if _ck in _conv_cache:
        return _conv_cache[_ck]
    # L2: Redis (if configured)
    cached = _redis_get_conversation(conv_id, uid)
    if cached:
        _conv_cache[_ck] = cached
        return cached
    result = None
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM conversations WHERE id = $1 AND user_id = $2 LIMIT 1",
                    conv_id, uid
                )
                result = _pg_row(row)
        except Exception as e:
            logger.warning(f"pg supa_get_conversation failed: {e}")
    if result is None and supa:
        try:
            r = await _supa(lambda: supa.table("conversations").select("*").eq("id", conv_id).eq("user_id", uid).limit(1).execute())
            if r.data:
                result = r.data[0]
                if isinstance(result.get("messages"), str):
                    try: result["messages"] = json.loads(result["messages"])
                    except: result["messages"] = []
        except Exception: pass
    if result is None:
        try:
            result = await db.conversations.find_one({"id": conv_id, "user_id": uid}, {"_id": 0})
        except Exception: pass
    if result:
        _conv_cache[_conv_cache_key(conv_id, uid)] = result
        _redis_cache_conversation(conv_id, uid, result)
    return result

async def supa_upsert_conversation(conv: dict):
    _invalidate_conv_cache(conv.get("id",""), conv.get("user_id",""))
    _redis_invalidate_conversation(conv.get("id",""), conv.get("user_id",""))
    if pg_pool:
        try:
            msgs = json.dumps(conv.get("messages", [])) if isinstance(conv.get("messages"), list) else (conv.get("messages") or "[]")
            async with pg_pool.acquire() as conn:
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
            _supa_mirror(lambda: supa.table("conversations").upsert({k: v for k, v in conv.items() if k in {"id","user_id","title","preview","subject_id","subject_name","starred","archived","tokens","created_at","updated_at"}}).execute())
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
    if pg_pool and updates:
        try:
            u = {k: v for k, v in updates.items() if k in _ALLOWED_CONV_COLUMNS}
            unknown = set(updates) - _ALLOWED_CONV_COLUMNS
            if unknown:
                raise ValueError(f"supa_update_conversation: disallowed column(s): {unknown}")
            if isinstance(u.get("messages"), list): u["messages"] = json.dumps(u["messages"])
            if u:
                cols = [f"{k} = ${i}" for i, k in enumerate(u.keys(), start=1)]
                vals = list(u.values()) + [conv_id, uid]
                sql = f"UPDATE conversations SET {', '.join(cols)} WHERE id = ${len(vals)-1} AND user_id = ${len(vals)}"
                async with pg_pool.acquire() as conn:
                    await conn.execute(sql, *vals)
            return
        except Exception as e:
            logger.warning(f"pg supa_update_conversation failed: {e}")
    if supa:
        try:
            allowed = {"title","preview","subject_id","subject_name","starred","archived","messages","tokens","updated_at"}
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool and updates:
        try:
            unknown = set(updates) - _ALLOWED_SETTINGS_COLUMNS
            if unknown:
                raise ValueError(f"supa_update_settings: disallowed column(s): {unknown}")
            cols = [f"{k} = ${i}" for i, k in enumerate(updates.keys(), start=1)]
            vals = list(updates.values())
            sql = f"UPDATE app_settings SET {', '.join(cols)} WHERE id = 1"
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute("DELETE FROM notifications WHERE id = $1", notif_id)
            return
        except Exception: pass
    if supa:
        try: await _supa(lambda: supa.table("notifications").delete().eq("id", notif_id).execute()); return
        except Exception: pass
    try:
        await db.notifications.delete_one({"id": notif_id})
    except Exception: pass

# ─────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────
@api.post("/auth/signup", response_model=TokenOut)
async def signup(data: UserCreate, response: Response):
    existing = await supa_get_user(data.email.lower())
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    settings = await supa_get_settings()
    if not settings.get("registrations_open", True):
        raise HTTPException(status_code=403, detail="Registrations are currently closed")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    # Free users get 30 lifetime credits (ONE-TIME, no reset)
    user = {
        "id": user_id,
        "name": data.name,
        "email": data.email.lower(),
        "password_hash": pwd_ctx.hash(data.password),
        "plan": "free",
        "credits_used": 0,
        "credits_limit": 30,     # Free = 30 lifetime credits
        "document_access": "zero",
        "onboarding_done": False,
        "is_admin": False,
        "status": "active",
        "bio": "",
        "phone": "",
        "saved_subjects": [],
        "has_free_credits_issued": True,
        "created_at": now,
    }
    await supa_insert_user(user)
    token = create_access_token(user_id, role="student")
    refresh = create_refresh_token(user_id)
    user_out = UserOut(
        id=user_id, name=data.name, email=data.email.lower(),
        plan="free", credits_used=0, credits_limit=30,
        onboarding_done=False, is_admin=False, created_at=now
    )
    response.set_cookie(
        key="syrabit_session",
        value=token,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=JWT_ACCESS_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="syrabit_refresh",
        value=refresh,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        path="/api/auth/refresh",
        max_age=JWT_REFRESH_EXPIRE_MINUTES * 60,
    )
    return TokenOut(access_token=token, user=user_out)

@api.post("/auth/login", response_model=TokenOut)
async def login(data: UserLogin, response: Response):
    user = await supa_get_user(data.email.lower())
    if not user or not pwd_ctx.verify(data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Account banned")

    credits_info = await get_user_credits(user)
    role = "admin" if user.get("is_admin") else "student"
    token = create_access_token(user["id"], role=role)
    refresh = create_refresh_token(user["id"])
    user_out = UserOut(
        id=user["id"], name=user["name"], email=user["email"],
        plan=user.get("plan", "free"),
        credits_used=credits_info["used"],
        credits_limit=credits_info["limit"],
        onboarding_done=user.get("onboarding_done", False),
        is_admin=user.get("is_admin", False),
        created_at=user.get("created_at", ""),
        avatar_url=user.get("avatar_url", ""),
    )
    response.set_cookie(
        key="syrabit_session",
        value=token,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=JWT_ACCESS_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="syrabit_refresh",
        value=refresh,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        path="/api/auth/refresh",
        max_age=JWT_REFRESH_EXPIRE_MINUTES * 60,
    )
    return TokenOut(access_token=token, user=user_out)

async def _send_password_reset_email(email: str, token: str):
    """Send password reset email via email_templates (Resend SDK)."""
    reset_url = f"{FRONTEND_URL}/reset-password"
    await email_templates.send_password_reset(email=email, token=token, reset_url=reset_url)

@api.post("/auth/reset-request")
async def reset_request(data: PasswordResetReq):
    user = await supa_get_user_for_reset(data.email.lower())
    if user:
        token = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        await supa_create_password_reset(token, data.email.lower(), expires)
        await _send_password_reset_email(data.email.lower(), token)
    return {"message": "If the email exists, a reset link has been sent"}

@api.post("/auth/reset-confirm")
async def reset_confirm(data: PasswordResetConfirm):
    record = await supa_get_password_reset(data.token)
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    expires = datetime.fromisoformat(record["expires"])
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=400, detail="Reset token expired")
    await supa_update_user_password(record["email"], pwd_ctx.hash(data.new_password))
    await supa_delete_password_reset(data.token)
    return {"message": "Password updated successfully"}

@api.get("/auth/me", response_model=UserOut)
async def get_me(user: dict = Depends(get_current_user)):
    credits_info = await get_user_credits(user)
    return UserOut(
        id=user["id"], name=user["name"], email=user["email"],
        plan=user.get("plan", "free"),
        credits_used=credits_info["used"],
        credits_limit=credits_info["limit"],
        onboarding_done=user.get("onboarding_done", False),
        is_admin=user.get("is_admin", False),
        created_at=user.get("created_at", ""),
        avatar_url=user.get("avatar_url", ""),
    )

# ─────────────────────────────────────────────
# CONTENT ROUTES
# ─────────────────────────────────────────────
@api.get("/content/library-bundle", response_model=LibraryBundleOut)
async def get_library_bundle(nocache: Optional[str] = None, response: Response = None):
    if not nocache:
        cached = _get_content_cache("library-bundle")
        if cached:
            if response:
                response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
            return cached
    try:
        if not await is_mongo_available():
            return {"boards": [], "classes": [], "streams": [], "subjects": []}
        async with _slow_query("library_bundle"):
            boards_data, classes_data, streams_data, subjects_data, chapters_data, pyq_data, fc_data = await asyncio.gather(
                db.boards.find({}, {"_id": 0}).to_list(100),
                db.classes.find({}, {"_id": 0}).to_list(100),
                db.streams.find({}, {"_id": 0}).to_list(100),
                db.subjects.find({"status": "published"}, {"_id": 0}).to_list(500),
                db.chapters.find(
                    {},
                    {"_id": 0, "id": 1, "title": 1, "slug": 1, "subject_id": 1, "order_index": 1, "description": 1, "notes_generated": 1},
                ).sort("order_index", 1).to_list(5000),
                db.topic_pyq_collections.find({}, {"_id": 0, "subject_id": 1, "total": 1}).to_list(2000),
                db.flashcard_collections.find({}, {"_id": 0, "subject_id": 1, "total": 1}).to_list(2000),
            )

        # ── Compute per-subject content coverage ─────────────────────────────
        chapters_by_subject: dict = {}
        for ch in chapters_data:
            sid = ch.get("subject_id", "")
            if sid:
                chapters_by_subject.setdefault(sid, []).append(ch)

        pyq_total_by_subject: dict = {}
        for p in pyq_data:
            sid = p.get("subject_id", "")
            if sid:
                pyq_total_by_subject[sid] = pyq_total_by_subject.get(sid, 0) + (p.get("total") or 0)

        fc_total_by_subject: dict = {}
        for f in fc_data:
            sid = f.get("subject_id", "")
            if sid:
                fc_total_by_subject[sid] = fc_total_by_subject.get(sid, 0) + (f.get("total") or 0)

        for s in subjects_data:
            if "thumbnail_url" in s and "thumbnailUrl" not in s:
                s["thumbnailUrl"] = s.pop("thumbnail_url")
            sid = s.get("id", "")
            chs = chapters_by_subject.get(sid, [])
            total_ch = len(chs)
            notes_ch = sum(1 for c in chs if c.get("notes_generated"))
            s["notes_count"]   = notes_ch
            s["chapter_count"] = total_ch
            s["notes_pct"]     = round(notes_ch / total_ch * 100) if total_ch else 0
            s["pyq_count"]     = pyq_total_by_subject.get(sid, 0)
            s["flash_count"]   = fc_total_by_subject.get(sid, 0)

        bundle = {"boards": boards_data, "classes": classes_data, "streams": streams_data, "subjects": subjects_data, "chapters": chapters_data}
        _set_content_cache("library-bundle", bundle)
        if response:
            response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return bundle
    except Exception:
        return {"boards": [], "classes": [], "streams": [], "subjects": []}

@api.get("/content/boards")
async def get_boards(nocache: Optional[str] = None, response: Response = None):
    if not nocache:
        cached = _get_content_cache("boards")
        if cached:
            if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
            return cached
    try:
        if not await is_mongo_available():
            return []
        boards = await db.boards.find({}, {"_id": 0}).to_list(100)
        _set_content_cache("boards", boards)
        if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
        return boards
    except Exception:
        return []

@api.get("/content/classes")
async def get_classes(board_id: Optional[str] = None, nocache: Optional[str] = None, response: Response = None):
    ck = f"classes:{board_id or 'all'}"
    if not nocache:
        cached = _get_content_cache(ck)
        if cached:
            if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
            return cached
    try:
        if not await is_mongo_available():
            return []
        query = {"board_id": board_id} if board_id else {}
        classes = await db.classes.find(query, {"_id": 0}).to_list(100)
        _set_content_cache(ck, classes)
        if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
        return classes
    except Exception:
        return []

@api.get("/content/streams")
async def get_streams(class_id: Optional[str] = None, nocache: Optional[str] = None, response: Response = None):
    ck = f"streams:{class_id or 'all'}"
    if not nocache:
        cached = _get_content_cache(ck)
        if cached:
            if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
            return cached
    try:
        if not await is_mongo_available():
            return []
        query = {"class_id": class_id} if class_id else {}
        streams = await db.streams.find(query, {"_id": 0}).to_list(100)
        _set_content_cache(ck, streams)
        if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
        return streams
    except Exception:
        return []

@api.get("/content/subjects")
async def get_subjects(stream_id: Optional[str] = None, class_id: Optional[str] = None, nocache: Optional[str] = None, response: Response = None):
    ck = f"subjects:{stream_id or ''}:{class_id or ''}"
    if not nocache:
        cached = _get_content_cache(ck)
        if cached:
            if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
            return cached
    try:
        if not await is_mongo_available():
            return []
        if stream_id:
            subjects = await db.subjects.find({"stream_id": stream_id, "status": "published"}, {"_id": 0}).to_list(100)
        elif class_id:
            streams = await db.streams.find({"class_id": class_id}, {"_id": 0}).to_list(100)
            stream_ids = [s["id"] for s in streams]
            subjects = await db.subjects.find({"stream_id": {"$in": stream_ids}, "status": "published"}, {"_id": 0}).to_list(500)
        else:
            subjects = await db.subjects.find({"status": "published"}, {"_id": 0}).to_list(500)
        for s in subjects:
            if "thumbnail_url" in s and "thumbnailUrl" not in s:
                s["thumbnailUrl"] = s.pop("thumbnail_url")
        _set_content_cache(ck, subjects)
        if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return subjects
    except Exception:
        return []

@api.get("/content/resolve-subject/{board_slug}/{class_slug}/{stream_slug}/{subject_slug}")
async def resolve_subject(board_slug: str, class_slug: str, stream_slug: str, subject_slug: str, response: Response = None):
    ck = f"resolve:{board_slug}:{class_slug}:{stream_slug}:{subject_slug}"
    cached = _get_content_cache(ck)
    if cached:
        if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return cached
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    board = await db.boards.find_one({"slug": board_slug}, {"_id": 0})
    if not board: raise HTTPException(404, "Board not found")
    cls = await db.classes.find_one({"slug": class_slug, "board_id": board["id"]}, {"_id": 0})
    if not cls: raise HTTPException(404, "Class not found")
    stream = await db.streams.find_one({"slug": stream_slug, "class_id": cls["id"]}, {"_id": 0})
    if not stream: raise HTTPException(404, "Stream not found")
    subj = await db.subjects.find_one({"slug": subject_slug, "stream_id": stream["id"], "status": "published"}, {"_id": 0})
    if not subj: raise HTTPException(404, "Subject not found")
    result = {"id": subj["id"], "name": subj["name"]}
    _set_content_cache(ck, result)
    if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    return result

@api.get("/content/resolve-subject/{board_slug}/{class_slug}/{subject_slug}")
async def resolve_subject_no_stream(board_slug: str, class_slug: str, subject_slug: str, response: Response = None):
    ck = f"resolve-ns:{board_slug}:{class_slug}:{subject_slug}"
    cached = _get_content_cache(ck)
    if cached:
        if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return cached
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    board = await db.boards.find_one({"slug": board_slug}, {"_id": 0})
    if not board: raise HTTPException(404, "Board not found")
    cls = await db.classes.find_one({"slug": class_slug, "board_id": board["id"]}, {"_id": 0})
    if not cls: raise HTTPException(404, "Class not found")
    streams = await db.streams.find({"class_id": cls["id"]}, {"_id": 0}).to_list(100)
    stream_ids = [s["id"] for s in streams]
    subj = await db.subjects.find_one({"slug": subject_slug, "stream_id": {"$in": stream_ids}, "status": "published"}, {"_id": 0})
    if not subj: raise HTTPException(404, "Subject not found")
    stream = next((s for s in streams if s["id"] == subj.get("stream_id")), None)
    result = {
        "id": subj["id"], "name": subj["name"], "description": subj.get("description", ""),
        "icon": subj.get("icon", ""), "tags": subj.get("tags", []),
        "board_name": board.get("name", ""), "class_name": cls.get("name", ""),
        "stream_name": stream.get("name", "") if stream else "",
        "board_slug": board_slug, "class_slug": class_slug,
        "stream_slug": stream.get("slug", "") if stream else "",
        "slug": subject_slug,
    }
    _set_content_cache(ck, result)
    if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    return result

@api.get("/content/subjects/{subject_id}")
async def get_subject(subject_id: str, response: Response = None):
    ck = f"subject:{subject_id}"
    cached = _get_content_cache(ck)
    if cached:
        if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return cached
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")
    if "thumbnail_url" in subj and "thumbnailUrl" not in subj:
        subj["thumbnailUrl"] = subj.pop("thumbnail_url")
    _set_content_cache(ck, subj)
    if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    return subj

# ── Document endpoints (upload / read / delete) ─────────────────────────────

@api.get("/content/subjects/{subject_id}/document")
async def get_subject_document(subject_id: str):
    """Return document/chapters for a subject - checks multiple sources"""
    
    # First check if subject has document_text (old direct upload)
    subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")
    
    if subj.get("document_text"):
        return {
            "subject_id": subject_id,
            "document_name": subj.get("document_name", "document.txt"),
            "document_text": subj.get("document_text", ""),
            "document_type": subj.get("document_type", "text"),
            "document_url": subj.get("document_url", ""),
            "uploaded_at": subj.get("document_uploaded_at", ""),
        }
    
    # Check content_uploads collection
    upload = await db.content_uploads.find_one(
        {"subject_id": subject_id},
        {"_id": 0}
    )
    
    if upload:
        return {
            "subject_id": subject_id,
            "document_id": upload.get("id"),
            "document_name": upload.get("file_name") or upload.get("title", "Content"),
            "document_text": upload.get("content", ""),
            "document_type": upload.get("file_ext", "txt"),
            "document_url": upload.get("file_url", ""),
            "uploaded_at": upload.get("uploaded_at", ""),
            "is_pdf": upload.get("file_ext") == "pdf",
        }
    
    # Check chapters (manually created content)
    chapters = await db.chapters.find(
        {"subject_id": subject_id, "status": "published"},
        {"_id": 0}
    ).sort("order", 1).limit(10).to_list(10)
    
    if chapters and len(chapters) > 0:
        # Combine all chapters into one document view
        combined_content = f"# {subj.get('name', 'Subject')} - Study Material\n\n"
        for i, chapter in enumerate(chapters, 1):
            combined_content += f"## Chapter {i}: {chapter.get('title', 'Untitled')}\n\n"
            if chapter.get('description'):
                combined_content += f"{chapter.get('description')}\n\n"
            if chapter.get('content'):
                combined_content += f"{chapter.get('content')}\n\n"
            combined_content += "---\n\n"
        
        return {
            "subject_id": subject_id,
            "document_name": f"{subj.get('name', 'Subject')} - Chapters.md",
            "document_text": combined_content,
            "document_type": "markdown",
            "document_url": "",
            "uploaded_at": chapters[0].get("created_at", ""),
        }
    
    raise HTTPException(status_code=404, detail="No content available for this subject")

@api.post("/admin/content/subjects/{subject_id}/document")
async def upload_subject_document(
    subject_id: str,
    data: DocumentUpload,
    admin: dict = Depends(get_admin_user),
):
    """Admin uploads a text document for a subject card."""
    subj = await db.subjects.find_one({"id": subject_id})
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Enforce reasonable size limit — 500KB of text
    if len(data.document_text) > 500_000:
        raise HTTPException(status_code=413, detail="Document too large (max 500KB text)")

    await db.subjects.update_one(
        {"id": subject_id},
        {"$set": {
            "document_name": data.document_name,
            "document_text": data.document_text,
            "document_type": data.document_type,
            "document_uploaded_at": datetime.now(timezone.utc).isoformat(),
            "has_document": True,
        }}
    )
    logger.info(f"Admin uploaded document '{data.document_name}' for subject {subject_id}")
    return {
        "message": "Document uploaded",
        "subject_id": subject_id,
        "document_name": data.document_name,
        "size_chars": len(data.document_text),
    }

@api.delete("/admin/content/subjects/{subject_id}/document")
async def delete_subject_document(subject_id: str, admin: dict = Depends(get_admin_user)):
    """Admin removes the document from a subject."""
    await db.subjects.update_one(
        {"id": subject_id},
        {"$unset": {"document_name": "", "document_text": "", "document_type": "", "document_uploaded_at": "", "has_document": ""}}
    )
    return {"message": "Document removed"}

@api.get("/content/chapters/{subject_id}")
async def get_chapters(subject_id: str, response: Response = None):
    ck = f"chapters:{subject_id}"
    cached = _get_content_cache(ck)
    if cached:
        if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
        return cached
    try:
        if not await is_mongo_available():
            return []
        chapters = await db.chapters.find({"subject_id": subject_id}, {"_id": 0}).sort("order_index", 1).to_list(100)
        import re as _re
        for ch in chapters:
            if not ch.get("slug") and ch.get("title"):
                ch["slug"] = _re.sub(r'[^a-z0-9]+', '-', ch["title"].lower()).strip('-')
        _set_content_cache(ck, chapters)
        if response: response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=7200"
        return chapters
    except Exception:
        return []

@api.get("/content/chapter-by-slug/{board_slug}/{class_slug}/{subject_slug}/{chapter_slug}")
async def get_chapter_by_slug(board_slug: str, class_slug: str, subject_slug: str, chapter_slug: str, response: Response = None):
    ck = f"ch-slug:{board_slug}:{class_slug}:{subject_slug}:{chapter_slug}"
    cached = _get_content_cache(ck)
    if cached:
        if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
        return cached
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    board = await db.boards.find_one({"slug": board_slug}, {"_id": 0})
    if not board: raise HTTPException(404, "Board not found")
    cls = await db.classes.find_one({"slug": class_slug, "board_id": board["id"]}, {"_id": 0})
    if not cls: raise HTTPException(404, "Class not found")
    streams = await db.streams.find({"class_id": cls["id"]}, {"_id": 0}).to_list(100)
    stream_ids = [s["id"] for s in streams]
    subj = await db.subjects.find_one({"slug": subject_slug, "stream_id": {"$in": stream_ids}, "status": "published"}, {"_id": 0})
    if not subj: raise HTTPException(404, "Subject not found")
    chapter = await db.chapters.find_one({"slug": chapter_slug, "subject_id": subj["id"]}, {"_id": 0})
    if not chapter:
        import re as _re
        all_chapters = await db.chapters.find({"subject_id": subj["id"]}, {"_id": 0}).to_list(200)
        for c in all_chapters:
            title = c.get("title", "")
            auto_slug = _re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
            if auto_slug == chapter_slug:
                chapter = c
                break
    if not chapter: raise HTTPException(404, "Chapter not found")
    chunks = await db.chunks.find({"chapter_id": chapter["id"]}, {"_id": 0}).sort("order_index", 1).to_list(200)
    content_parts = []
    for chunk in chunks:
        if chunk.get("content"):
            content_parts.append(chunk["content"])
    content = "\n\n".join(content_parts) if content_parts else chapter.get("content", "")
    word_count = len(content.split()) if content else 0
    stream = next((s for s in streams if s["id"] == subj.get("stream_id")), None)
    result = {
        "title": f"{chapter.get('title', chapter_slug)} — {subj['name']}",
        "topic_title": chapter.get("title", chapter_slug),
        "content": content or f"# {chapter.get('title', chapter_slug)}\n\nContent for this chapter is being prepared. Check back soon!",
        "meta_description": chapter.get("description", f"{chapter.get('title', '')} notes for {subj['name']}"),
        "board_name": board.get("name", ""), "class_name": cls.get("name", ""),
        "subject_name": subj.get("name", ""), "chapter_title": chapter.get("title", ""),
        "stream_name": stream.get("name", "") if stream else "",
        "word_count": word_count, "generated_at": chapter.get("created_at", ""),
        "updated_at": chapter.get("updated_at", ""),
        "is_fallback": True,
    }
    _set_content_cache(ck, result)
    if response: response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    return result

@api.get("/content/chunks/{chapter_id}")
async def get_chunks(chapter_id: str):
    ck = f"chunks:{chapter_id}"
    cached = _get_content_cache(ck)
    if cached: return cached
    try:
        if not await is_mongo_available():
            return []
        chunks = await db.chunks.find({"chapter_id": chapter_id}, {"_id": 0}).to_list(200)
        _set_content_cache(ck, chunks)
        return chunks
    except Exception:
        return []

@api.get("/content/chapters/{chapter_id}/topic-pyqs")
async def get_chapter_topic_pyqs(chapter_id: str, limit: int = 20):
    """Public — important/topic questions for a chapter generated by the agentic pipeline."""
    ck = f"topic-pyqs:{chapter_id}:{limit}"
    cached = _get_content_cache(ck)
    if cached:
        return cached
    try:
        if not await is_mongo_available():
            return {"pyqs": [], "mark_wise": {}, "total": 0}
        # Priority: ai_pyq_collections (agentic pipeline) → topic_pyq_collections (legacy pipeline)
        doc = await db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0})
        if not doc:
            doc = await db.topic_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0})
        if not doc:
            return {"pyqs": [], "mark_wise": {}, "total": 0}
        raw_pyqs = doc.get("pyqs") or []
        mark_wise_raw = doc.get("mark_wise") or {}
        # If flat pyqs list is empty but mark_wise has data, flatten it with marks field
        if not raw_pyqs and mark_wise_raw:
            for mark_str, qs in mark_wise_raw.items():
                for q in qs:
                    if isinstance(q, str):
                        raw_pyqs.append({"question": q, "marks": int(mark_str)})
                    elif isinstance(q, dict):
                        raw_pyqs.append({**q, "marks": int(mark_str)})
        pyqs = raw_pyqs[:limit]
        result = {
            "pyqs": pyqs,
            "mark_wise": mark_wise_raw,
            "total": doc.get("total", len(raw_pyqs)),
            "source": doc.get("source", "pipeline"),
        }
        _set_content_cache(ck, result)
        return result
    except Exception:
        return {"pyqs": [], "mark_wise": {}, "total": 0}

@api.get("/content/chapters/{chapter_id}/flashcards")
async def get_chapter_flashcards(chapter_id: str, limit: int = 10):
    """Public — flashcard preview for a chapter (top N)."""
    ck = f"flashcards:{chapter_id}:{limit}"
    cached = _get_content_cache(ck)
    if cached:
        return cached
    try:
        if not await is_mongo_available():
            return {"flashcards": [], "total": 0}
        doc = await db.flashcard_collections.find_one({"chapter_id": chapter_id}, {"_id": 0})
        if not doc:
            return {"flashcards": [], "total": 0}
        all_fc = doc.get("flashcards") or []
        flashcards = all_fc[:limit]
        result = {"flashcards": flashcards, "total": doc.get("total", len(all_fc))}
        _set_content_cache(ck, result)
        return result
    except Exception:
        return {"flashcards": [], "total": 0}

@api.get("/content/search")
async def search_content(q: str):
    if len(q) < 2:
        return []
    try:
        if not await is_mongo_available():
            return []
        q_hash = _cache_key(q)
        cached_redis = _redis_get_search(q_hash)
        if cached_redis is not None:
            return cached_redis
        ck = f"search:{q.lower().strip()}"
        cached = _get_content_cache(ck)
        if cached:
            return cached
        async with _slow_query(f"content_search q={q[:30]}"):
            regex = re.compile(q, re.IGNORECASE)
            subjects = await db.subjects.find(
                {"$or": [{"name": regex}, {"description": regex}, {"tags": regex}], "status": "published"},
                {"_id": 0}
            ).to_list(20)
        _set_content_cache(ck, subjects)
        _redis_cache_search(q_hash, subjects)
        return subjects
    except Exception:
        return []

# ─────────────────────────────────────────────
# LIBRARY SEARCH & SYLLABUS ROUTES (RAG System)
# ─────────────────────────────────────────────

@api.get("/library_search")
async def library_search(
    board: Optional[str] = None,
    class_: Optional[str] = Query(None, alias="class"),
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    query: str = "",
):
    """Library-search API for RAG system. Returns structured content from MongoDB library_scrapes collection."""
    try:
        if not await is_mongo_available():
            return {"board": board, "class": class_, "subject": subject, "chapter": chapter, "pages": [], "source": "none"}
        
        lib_filter = {}
        if board:
            lib_filter["board"] = board
        if class_:
            lib_filter["class"] = class_
        if subject:
            lib_filter["subject"] = subject
        if chapter:
            lib_filter["chapter"] = chapter
        
        if query:
            query_regex = re.compile(query, re.IGNORECASE)
            lib_filter["$or"] = [
                {"sections.theory": query_regex},
                {"sections.formulas": query_regex},
                {"sections.examples": query_regex},
                {"title": query_regex},
            ]
        
        pages = await db.library_scrapes.find(lib_filter, {"_id": 0}).to_list(10)
        logger.info(f"Library search: {board}/{class_}/{subject}/{chapter} - found {len(pages)} pages")
        return {
            "board": board,
            "class": class_,
            "subject": subject,
            "chapter": chapter,
            "pages": pages,
            "source": "library",
            "count": len(pages)
        }
    except Exception as e:
        logger.error(f"Library search error: {e}")
        return {"board": board, "class": class_, "subject": subject, "chapter": chapter, "pages": [], "source": "error"}


@api.get("/syllabi/{board_id}/{class_id}")
async def get_syllabus(board_id: str, class_id: str):
    """Fetch syllabus for a board+class. Returns structured syllabus content to inject into LLM prompts."""
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}
        
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": {"$exists": False}}, {"_id": 0})
        if not syllabus:
            syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        
        if syllabus:
            logger.info(f"Syllabus found: {board_id}/{class_id}")
            return syllabus
        else:
            return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}


@api.post("/admin/syllabi/{board_id}/{class_id}")
async def create_or_update_syllabus(
    board_id: str,
    class_id: str,
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user)
):
    """Create or update syllabus for a board+class."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        
        syllabus_doc = {
            "board_id": board_id,
            "class_id": class_id,
            "content": data.get("content", ""),
            "chapters": data.get("chapters", []),
            "topics": data.get("topics", []),
            "guidelines": data.get("guidelines", ""),
            "geo_phrases": data.get("geo_phrases", []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        await db.syllabi.update_one(
            {"board_id": board_id, "class_id": class_id},
            {"$set": syllabus_doc},
            upsert=True
        )
        
        logger.info(f"Syllabus saved: {board_id}/{class_id}")
        return {"message": "Syllabus saved successfully", "board_id": board_id, "class_id": class_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Save syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving syllabus: {e}")


@api.delete("/admin/syllabi/{board_id}/{class_id}")
async def delete_syllabus(
    board_id: str,
    class_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Delete syllabus for a board+class."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        
        await db.syllabi.delete_one({"board_id": board_id, "class_id": class_id})
        logger.info(f"Syllabus deleted: {board_id}/{class_id}")
        return {"message": "Syllabus deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting syllabus: {e}")

@api.get("/syllabi/{board_id}/{class_id}/{stream_id}")
async def get_syllabus_stream(board_id: str, class_id: str, stream_id: str):
    """Fetch syllabus for a board+class+stream. Falls back to board+class if stream-specific not found."""
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id}, {"_id": 0})
        if syllabus:
            logger.info(f"Stream syllabus found: {board_id}/{class_id}/{stream_id}")
            return syllabus
        # Fall back to board+class level
        fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": {"$exists": False}}, {"_id": 0})
        if not fallback:
            fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        if fallback:
            logger.info(f"Using board+class fallback syllabus for {board_id}/{class_id}/{stream_id}")
            return {**fallback, "is_fallback": True}
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get stream syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}

@api.post("/admin/syllabi/{board_id}/{class_id}/{stream_id}")
async def create_or_update_syllabus_stream(
    board_id: str,
    class_id: str,
    stream_id: str,
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user)
):
    """Create or update syllabus for a board+class+stream."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        syllabus_doc = {
            "board_id": board_id,
            "class_id": class_id,
            "stream_id": stream_id,
            "content": data.get("content", ""),
            "chapters": data.get("chapters", []),
            "topics": data.get("topics", []),
            "guidelines": data.get("guidelines", ""),
            "geo_phrases": data.get("geo_phrases", []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.syllabi.update_one(
            {"board_id": board_id, "class_id": class_id, "stream_id": stream_id},
            {"$set": syllabus_doc},
            upsert=True
        )
        logger.info(f"Stream syllabus saved: {board_id}/{class_id}/{stream_id}")
        return {"message": "Syllabus saved successfully", "board_id": board_id, "class_id": class_id, "stream_id": stream_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Save stream syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving syllabus: {e}")

@api.delete("/admin/syllabi/{board_id}/{class_id}/{stream_id}")
async def delete_syllabus_stream(
    board_id: str,
    class_id: str,
    stream_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Delete syllabus for a board+class+stream."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        await db.syllabi.delete_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id})
        logger.info(f"Stream syllabus deleted: {board_id}/{class_id}/{stream_id}")
        return {"message": "Syllabus deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete stream syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting syllabus: {e}")


@api.get("/syllabi/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def get_syllabus_subject(board_id: str, class_id: str, stream_id: str, subject_id: str):
    """Fetch syllabus for a specific subject. Fallback: stream → board+class."""
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id}, {"_id": 0})
        if syllabus:
            logger.info(f"Subject syllabus found: {board_id}/{class_id}/{stream_id}/{subject_id}")
            return syllabus
        # Fall back to stream level
        fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": {"$exists": False}}, {"_id": 0})
        if not fallback:
            fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": {"$exists": False}}, {"_id": 0})
        if not fallback:
            fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        if fallback:
            logger.info(f"Using fallback syllabus for subject {subject_id}")
            return {**fallback, "is_fallback": True}
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get subject syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}


@api.post("/admin/syllabi/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def create_or_update_syllabus_subject(
    board_id: str,
    class_id: str,
    stream_id: str,
    subject_id: str,
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user)
):
    """Create or update syllabus for a specific subject."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        syllabus_doc = {
            "board_id": board_id,
            "class_id": class_id,
            "stream_id": stream_id,
            "subject_id": subject_id,
            "content": data.get("content", ""),
            "chapters": data.get("chapters", []),
            "topics": data.get("topics", []),
            "guidelines": data.get("guidelines", ""),
            "geo_phrases": data.get("geo_phrases", []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.syllabi.update_one(
            {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id},
            {"$set": syllabus_doc},
            upsert=True
        )
        logger.info(f"Subject syllabus saved: {board_id}/{class_id}/{stream_id}/{subject_id}")
        return {"message": "Syllabus saved successfully", "subject_id": subject_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Save subject syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving syllabus: {e}")


@api.delete("/admin/syllabi/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def delete_syllabus_subject(
    board_id: str,
    class_id: str,
    stream_id: str,
    subject_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Delete syllabus for a specific subject."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        await db.syllabi.delete_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id})
        logger.info(f"Subject syllabus deleted: {board_id}/{class_id}/{stream_id}/{subject_id}")
        return {"message": "Syllabus deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete subject syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting syllabus: {e}")


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    import re as _re
    text = text.lower().strip()
    text = _re.sub(r'[^\w\s-]', '', text)
    text = _re.sub(r'[\s_]+', '-', text)
    text = _re.sub(r'-+', '-', text).strip('-')
    return text


@api.post("/admin/syllabus/publish/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def publish_syllabus_as_card(
    board_id: str,
    class_id: str,
    stream_id: str,
    subject_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Publish a subject-level syllabus as a cms_documents card visible in the library."""
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    # ── 1. Load syllabus (with fallback chain) ────────────────────────────────
    syllabus = await db.syllabi.find_one(
        {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id},
        {"_id": 0}
    )
    if not syllabus:
        syllabus = await db.syllabi.find_one(
            {"board_id": board_id, "class_id": class_id, "stream_id": stream_id},
            {"_id": 0}
        )
    if not syllabus:
        raise HTTPException(status_code=404, detail="No syllabus found for this scope")

    # ── 2. Resolve names / slugs ──────────────────────────────────────────────
    board_doc   = await db.boards.find_one({"id": board_id}, {"_id": 0})
    class_doc   = await db.classes.find_one({"id": class_id}, {"_id": 0})
    stream_doc  = await db.streams.find_one({"id": stream_id}, {"_id": 0})
    subject_doc = await db.subjects.find_one({"id": subject_id}, {"_id": 0})

    board_name   = (board_doc  or {}).get("name",  board_id)
    class_name   = (class_doc  or {}).get("name",  class_id)
    stream_name  = (stream_doc or {}).get("name",  stream_id)
    subject_name = (subject_doc or {}).get("name", subject_id)
    board_slug   = (board_doc  or {}).get("slug",  _slugify(board_name))
    class_slug   = (class_doc  or {}).get("slug",  _slugify(class_name))
    subject_slug = (subject_doc or {}).get("slug", _slugify(subject_name))

    _grade_disp   = _smart_grade_label(class_name, board_name)
    _board_disp   = _smart_board_display(board_name)

    title       = f"{subject_name} Syllabus — {_board_disp} {_grade_disp}"
    seo_slug    = f"{board_slug}-{class_slug}-{_slugify(subject_name)}-syllabus"
    geo_tags    = f"{_grade_disp}, {_board_disp}, {stream_name}"
    seo_tags    = f"Syllabus,{subject_name},{_board_disp},{_grade_disp}"
    meta_desc   = (
        f"Complete {subject_name} syllabus for {_board_disp} {_grade_disp} ({stream_name}). "
        f"Covers key topics, chapters, and learning guidelines as per the {_board_disp} board."
    )

    # ── 3. Build structured markdown ──────────────────────────────────────────
    chapters    = syllabus.get("chapters", [])
    topics      = syllabus.get("topics", [])
    guidelines  = syllabus.get("guidelines", "").strip()
    geo_phrases = syllabus.get("geo_phrases", [])
    content_desc = syllabus.get("content", "").strip()

    md_parts = [f"# {title}\n"]
    if content_desc:
        md_parts.append(f"{content_desc}\n")
    if topics:
        md_parts.append("## Key Topics\n")
        for t in topics:
            md_parts.append(f"- {t}")
        md_parts.append("")
    if chapters:
        md_parts.append("## Chapters\n")
        for i, ch in enumerate(chapters, 1):
            md_parts.append(f"{i}. {ch}")
        md_parts.append("")
    if guidelines:
        md_parts.append("## Learning Guidelines\n")
        md_parts.append(guidelines)
        md_parts.append("")
    if geo_phrases:
        md_parts.append("## Board Authority Notes\n")
        for phrase in geo_phrases:
            md_parts.append(f"> {phrase}")
        md_parts.append("")

    raw_md       = "\n".join(md_parts)
    content_html = _md_to_html(raw_md)
    headings_json = _extract_headings_json(raw_md)
    word_count   = len(re.sub(r'<[^>]+>', '', content_html).split())
    now          = datetime.now(timezone.utc).isoformat()

    # ── 4. Upsert into cms_documents ──────────────────────────────────────────
    existing = await db.cms_documents.find_one({"seo_slug": seo_slug}, {"_id": 0, "id": 1})
    doc_id   = (existing or {}).get("id") or str(uuid.uuid4())

    doc_data = {
        "id":              doc_id,
        "type":            "syllabus",
        "title":           title,
        "content":         raw_md,
        "content_html":    content_html,
        "meta_description": meta_desc,
        "description":     content_desc,
        "seo_tags":        seo_tags,
        "geo_tags":        geo_tags,
        "primary_keyword": f"{subject_name} Syllabus",
        "seo_slug":        seo_slug,
        "category":        "syllabus",
        "schema_type":     "Course",
        "headings":        headings_json,
        "word_count":      word_count,
        "status":          "published",
        "linked_subject_id": subject_id,
        "linked_scope":    f"{board_id}/{class_id}/{stream_id}/{subject_id}",
        "rag_processed":   False,
        "updated_at":      now,
        "created_by":      admin.get("email", "admin"),
    }
    await db.cms_documents.update_one(
        {"seo_slug": seo_slug},
        {"$set": doc_data, "$setOnInsert": {"created_at": now}},
        upsert=True
    )
    logger.info(f"Syllabus card published: {seo_slug} (subject={subject_id})")
    return {"id": doc_id, "seo_slug": seo_slug, "title": title, "url": f"/learn/{seo_slug}"}


# ─────────────────────────────────────────────
# SYLLABUS EMBEDDER — admin endpoints
# ─────────────────────────────────────────────

@api.post("/admin/syllabus/seed-embeddings")
async def admin_seed_syllabus_embeddings(admin: dict = Depends(get_admin_user)):
    """
    Force a full re-embed of all SEED_DATA chapters into the `syllabus_embeddings`
    collection. Safe to run multiple times — drops existing and re-seeds.
    On first run after deployment this happens automatically in the background;
    call this endpoint to trigger it manually or force a refresh.
    """
    global _syllabus_embedder
    if _syllabus_embedder is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")
    result = await _syllabus_embedder.reseed()
    return result


@api.get("/admin/syllabus/embedding-stats")
async def admin_syllabus_embedding_stats(admin: dict = Depends(get_admin_user)):
    """Return counts for the syllabus_embeddings collection and in-memory cache."""
    global _syllabus_embedder
    if _syllabus_embedder is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")
    return await _syllabus_embedder.stats()


# ─────────────────────────────────────────────
# AI CHAT ROUTES
# ─────────────────────────────────────────────

async def _resolve_subject_context(subject_id: str) -> dict:
    """
    Given a subject_id, walk subject → stream → class → board and return
    the resolved board/class/stream IDs and names.  Returns an empty dict
    if subject_id is absent or any lookup fails.
    """
    if not subject_id:
        return {}
    try:
        subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0, "stream_id": 1})
        if not subj or not subj.get("stream_id"):
            return {}
        stream = await db.streams.find_one({"id": subj["stream_id"]}, {"_id": 0, "id": 1, "name": 1, "class_id": 1})
        if not stream:
            return {}
        cls = await db.classes.find_one({"id": stream["class_id"]}, {"_id": 0, "id": 1, "name": 1, "board_id": 1})
        if not cls:
            return {}
        board = await db.boards.find_one({"id": cls["board_id"]}, {"_id": 0, "id": 1, "name": 1})
        if not board:
            return {}
        return {
            "board_id":   board["id"],
            "board_name": board["name"],
            "class_id":   cls["id"],
            "class_name": cls["name"],
            "stream_id":  stream["id"],
            "stream_name": stream["name"],
        }
    except Exception as e:
        logger.warning(f"_resolve_subject_context({subject_id}) failed: {e}")
        return {}
@api.post("/ai/chat")
async def chat(msg: ChatMessage, user: dict = Depends(rate_limit_chat)):
    _chat_t0 = _time_mod.time()
    credits_info = await get_user_credits(user)
    if credits_info["remaining"] <= 0:
        raise HTTPException(status_code=402, detail=f"Credit limit reached ({credits_info['limit']} lifetime credits). Upgrade your plan for more.")

    plan = user.get("plan", "free")
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]

    # ── Tier 0: card_context (library scrape) → document_id (PDF upload) ──────
    document_text: Optional[str] = None
    if msg.card_context and msg.card_context.strip():
        document_text = msg.card_context
        logger.info(f"Chat [NON-STREAM]: Tier 0 card_context ({len(document_text)} chars) used as grounding")
    elif msg.document_id:
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        if subj and subj.get("document_text"):
            document_text = subj["document_text"]
            logger.info(f"Chat [NON-STREAM]: Tier 0 doc loaded from subject {msg.document_id}")

    # ── Resolve subject's own board/class/stream (overrides user profile) ────
    subj_ctx = await _resolve_subject_context(msg.subject_id)
    ctx_board_id   = subj_ctx.get("board_id")   or msg.board_id
    ctx_class_id   = subj_ctx.get("class_id")   or msg.class_id
    ctx_stream_id  = subj_ctx.get("stream_id")  or getattr(msg, 'stream_id', None)
    ctx_board_name = subj_ctx.get("board_name") or msg.board_name or user.get("board_name", "")
    ctx_class_name = subj_ctx.get("class_name") or msg.class_name or user.get("class_name", "")
    ctx_stream_name= subj_ctx.get("stream_name") or getattr(msg, 'stream_name', None) or user.get("stream_name", "")
    if subj_ctx:
        logger.info(f"Chat [NON-STREAM]: Subject context resolved → {ctx_board_name} / {ctx_class_name} / {ctx_stream_name}")

    # ── Fetch syllabus (subject → stream → board+class fallback) ────────────
    syllabus = None
    if ctx_board_id and ctx_class_id:
        try:
            if ctx_stream_id and msg.subject_id:
                syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id, "subject_id": msg.subject_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Subject syllabus loaded for {ctx_board_id}/{ctx_class_id}/{ctx_stream_id}/{msg.subject_id}")
            if not syllabus and ctx_stream_id:
                syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Stream syllabus loaded for {ctx_board_id}/{ctx_class_id}/{ctx_stream_id}")
            if not syllabus:
                syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": {"$exists": False}}, {"_id": 0})
                if not syllabus:
                    syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Board+class syllabus loaded for {ctx_board_id}/{ctx_class_id}")
        except Exception as e:
            logger.error(f"Failed to fetch syllabus: {e}")

    # ── Web-first sequential: DDG text → DDG news → MongoDB RAG ──────────────
    _is_casual_sync = _classify_question(msg.message) == "casual"

    if _is_casual_sync:
        web_results = []
        _ns_route = None
        rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                   "vector_hits": [], "source": "none", "quality": "none"}
    else:
        # Run SubjectRouter to get a curriculum-scoped query for web search
        _ns_scoped_query, _ns_route = await build_search_scope(
            msg.message,
            board_name=ctx_board_name,
            class_name=ctx_class_name,
            subject_name=msg.subject_name or "",
            embedder=_syllabus_embedder,
        )
        web_results = await web_search_with_fallback(
            msg.message, num_results=8,
            board_name=ctx_board_name,
            class_name=ctx_class_name,
            subject_name=msg.subject_name or "",
            scoped_query=_ns_scoped_query,
        )
        if web_results:
            logger.info(f"[NON-STREAM] Web primary: {len(web_results)} results | RAG skipped")
            rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                       "vector_hits": [], "source": "web", "quality": "web"}
        else:
            logger.info("[NON-STREAM] Web empty — falling back to MongoDB RAG")
            rag_ctx = await resolve_rag_context(
                msg.message,
                subject_id=msg.subject_id,
                subject_name=msg.subject_name,
                document_text=document_text,
            )

    # ── Build RAG-enriched system prompt ─────────────────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name":  ctx_board_name,
            "class_name":  ctx_class_name,
            "stream_name": ctx_stream_name,
            "subject_name": msg.subject_name,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        user.get("name", ""),
            "board_name":  ctx_board_name or user.get("board_name", ""),
            "class_name":  ctx_class_name or user.get("class_name", ""),
            "stream_name": ctx_stream_name or user.get("stream_name", ""),
            "plan":        user.get("plan", "free"),
        },
        query=msg.message,
        syllabus=syllabus,
        web_results=web_results or None,
    )

    conv_id = msg.conversation_id
    history_messages = []

    if conv_id:
        conv = await supa_get_conversation(conv_id, user["id"])
        if conv:
            raw_history = [
                {"role": m.get("role", ""), "content": m.get("content") or ""}
                for m in conv.get("messages", [])
                if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
            ]
            history_messages = _trim_history(raw_history)
    else:
        conv_id = str(uuid.uuid4())
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        conv_doc = {
            "id": conv_id,
            "user_id": user["id"],
            "title": title,
            "subject_id": msg.subject_id,
            "subject_name": msg.subject_name,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await supa_upsert_conversation(conv_doc)

    messages = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": msg.message}]

    # ── Cache check (Non-streaming) — Redis first, in-memory fallback ───────
    is_casual = _classify_question(msg.message) == "casual"
    cache_key = _cache_key(msg.message, subject_id=msg.subject_id or "", board_id=ctx_board_id or "")
    _cache_ttl = REDIS_CASUAL_CACHE_TTL if is_casual else REDIS_AI_CACHE_TTL
    answer = None

    answer = _redis_get_ai_cache(cache_key)
    if answer:
        logger.info(f"Redis cache HIT: {cache_key}")
    elif cache_key in _ai_response_cache:
        answer = _ai_response_cache[cache_key]
        logger.info(f"Memory cache HIT: {cache_key}")

    if answer is None:
        try:
            answer = await call_llm_api(messages, model=msg.model or LLM_MODEL, max_tokens=max_tokens)
            _redis_set("ai_cache", cache_key, answer, _cache_ttl)
            if not redis_client:
                _ai_response_cache[cache_key] = answer
            logger.info(f"Cache MISS → stored (ttl={_cache_ttl}s): {cache_key}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"AI chat error: {e}")
            raise HTTPException(status_code=503, detail="AI service temporarily unavailable")

    # Derive sources from the same RAG context sent to the LLM (no mismatch)
    lib_sources = _sources_from_rag_ctx(rag_ctx)

    now = datetime.now(timezone.utc).isoformat()
    new_messages = [
        {"role": "user", "content": msg.message, "timestamp": now},
        {"role": "assistant", "content": answer, "timestamp": now,
         "rag_source": rag_ctx.get("source", "none"),
         "rag_chunks": len(rag_ctx.get("chunks", []))},
    ]
    # Update conversation in Supabase
    conv = await supa_get_conversation(conv_id, user["id"])
    if conv:
        existing_msgs = conv.get("messages", [])
        if isinstance(existing_msgs, str):
            try: existing_msgs = json.loads(existing_msgs)
            except: existing_msgs = []
        updated_msgs = existing_msgs + new_messages
        await supa_update_conversation(conv_id, user["id"], {
            "messages": json.dumps(updated_msgs) if supa else updated_msgs,
            "updated_at": now,
            "preview": answer[:100],
            "tokens": len(answer.split()),
        })

    # Deduct 1 credit atomically (guards against parallel request exploitation)
    deducted = await atomic_deduct_credit(user["id"], credits_info["used"], credits_info["limit"])
    if not deducted:
        raise HTTPException(status_code=402, detail="Credit limit reached. Upgrade your plan for more.")
    new_used = credits_info["used"] + 1

    # Fire-and-forget: log chat turn for QA curation
    asyncio.create_task(_log_chat_message(
        user_id=user["id"],
        question=msg.message,
        raw_ai_answer=answer,
        subject_id=msg.subject_id,
        subject_name=msg.subject_name,
        board_name=ctx_board_name,
        class_name=ctx_class_name,
        conversation_id=conv_id,
    ))

    try:
        _record_chat_latency((_time_mod.time() - _chat_t0) * 1000)
    except Exception:
        pass

    try:
        _prompt_chars = sum(len(m.get("content", "")) for m in messages)
        _compl_chars  = len(answer) if answer else 0
        record_llm_cost(
            model=msg.model or LLM_MODEL,
            prompt_tokens=max(1, _prompt_chars // 4),
            completion_tokens=max(1, _compl_chars // 4),
            provider="gemini",
            user_id=str(user["id"]),
        )
    except Exception:
        pass

    return {
        "answer": answer,
        "conversation_id": conv_id,
        "credits_remaining": max(0, credits_info["remaining"] - 1),
        "credits_used": new_used,
        "rag_source": rag_ctx.get("source", "none"),
        "rag_chunks_used": len(rag_ctx.get("chunks", [])),
        "sources": lib_sources,
    }

async def _refund_credit(uid: str, credits_used: int) -> None:
    """Refund 1 credit (decrement credits_used) when streaming fails/empty answer."""
    try:
        if pg_pool:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET credits_used = GREATEST(0, credits_used - 1) WHERE id = $1",
                    uid,
                )
            return
        if redis_client:
            redis_key = f"credits:{uid}"
            refunded_count = redis_client.decr(redis_key)
            # Persist refunded count back to authoritative Supabase store (best-effort)
            if refunded_count is not None and refunded_count >= 0:
                await supa_update_user(uid, {"credits_used": int(refunded_count)})
            return
        if credits_used > 0:
            await supa_update_user(uid, {"credits_used": credits_used - 1})
    except Exception as e:
        logger.warning(f"_refund_credit failed: {e}")

async def _persist_chat_turn(
    conv_id: str, user_id: str,
    user_msg: str, answer: str,
    rag_source: str, rag_chunks: int,
    credits_used_before: int,
    deduct_credit: bool = False,
):
    """Background: save conversation messages. Optionally deduct 1 credit. Non-blocking."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        new_msgs = [
            {"role": "user", "content": user_msg, "timestamp": now},
            {"role": "assistant", "content": answer, "timestamp": now,
             "rag_source": rag_source, "rag_chunks": rag_chunks},
        ]
        conv = await supa_get_conversation(conv_id, user_id)
        if conv:
            existing = conv.get("messages", [])
            if isinstance(existing, str):
                try: existing = json.loads(existing)
                except: existing = []
            updated = existing + new_msgs
            await supa_update_conversation(conv_id, user_id, {
                "messages": json.dumps(updated) if supa else updated,
                "updated_at": now,
                "preview": answer[:100],
                "tokens": len(answer.split()),
            })
        if deduct_credit:
            await atomic_deduct_credit(user_id, credits_used_before, 999999)
    except Exception as e:
        logger.warning(f"_persist_chat_turn failed: {e}")

@api.post("/ai/chat/stream")
async def chat_stream(msg: ChatMessage, user: dict = Depends(rate_limit_chat)):
    _stream_t0 = _time_mod.time()
    credits_info = await get_user_credits(user)
    if credits_info["remaining"] <= 0:
        raise HTTPException(status_code=402, detail=f"Credit limit reached ({credits_info['limit']} lifetime credits). Upgrade your plan for more.")

    # Atomically reserve 1 credit before streaming begins to prevent parallel bypass
    deducted = await atomic_deduct_credit(user["id"], credits_info["used"], credits_info["limit"])
    if not deducted:
        raise HTTPException(status_code=402, detail="Credit limit reached. Upgrade your plan for more.")

    plan = user.get("plan", "free")
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]

    # ── Resolve subject's own board/class/stream (overrides user profile) ────
    subj_ctx = await _resolve_subject_context(msg.subject_id)
    ctx_board_id   = subj_ctx.get("board_id")   or msg.board_id
    ctx_class_id   = subj_ctx.get("class_id")   or msg.class_id
    ctx_stream_id  = subj_ctx.get("stream_id")  or getattr(msg, 'stream_id', None)
    ctx_board_name = subj_ctx.get("board_name") or msg.board_name or user.get("board_name", "")
    ctx_class_name = subj_ctx.get("class_name") or msg.class_name or user.get("class_name", "")
    ctx_stream_name= subj_ctx.get("stream_name") or getattr(msg, 'stream_name', None) or user.get("stream_name", "")
    if subj_ctx:
        logger.info(f"Chat [STREAM]: Subject context resolved → {ctx_board_name} / {ctx_class_name} / {ctx_stream_name}")

    # ── Phase 1: document + syllabus in parallel ──────────────────────────────
    async def _fetch_doc():
        # card_context (library card scrape) takes highest priority — same as PDF Tier 0
        if msg.card_context and msg.card_context.strip():
            logger.info(f"Chat [STREAM]: Tier 0 card_context ({len(msg.card_context)} chars) used as grounding")
            return msg.card_context
        if not msg.document_id:
            return None
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        return (subj or {}).get("document_text")

    async def _fetch_syllabus():
        if not (ctx_board_id and ctx_class_id):
            return None
        _sck = _syllabus_cache_key(ctx_board_id, ctx_class_id, ctx_stream_id, msg.subject_id)
        if _sck in _syllabus_cache:
            return _syllabus_cache[_sck]
        try:
            s = None
            if ctx_stream_id and msg.subject_id:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id, "subject_id": msg.subject_id}, {"_id": 0})
            if not s and ctx_stream_id:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id}, {"_id": 0})
            if not s:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": {"$exists": False}}, {"_id": 0})
            if not s:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id}, {"_id": 0})
            if s:
                _syllabus_cache[_sck] = s
            return s
        except Exception:
            return None

    document_text, syllabus = await asyncio.gather(_fetch_doc(), _fetch_syllabus())

    # ── Phase 2: RAG + conversation history in parallel ───────────────────────
    async def _fetch_history():
        if not msg.conversation_id:
            return None
        return await supa_get_conversation(msg.conversation_id, user["id"])

    _is_casual = _classify_question(msg.message) == "casual"

    if _is_casual:
        # Casual chat: no web search, no RAG — just history
        web_results = []
        _sr_route = None
        raw_conv = await _fetch_history()
        rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                   "vector_hits": [], "source": "none", "quality": "none"}
    else:
        # Step 0: SubjectRouter — get curriculum-scoped query (Tier 0-3) + fetch history
        _sr_scoped_query, _sr_route = await build_search_scope(
            msg.message,
            board_name=ctx_board_name,
            class_name=ctx_class_name,
            subject_name=msg.subject_name or "",
            embedder=_syllabus_embedder,
        )
        # Step 1: curriculum-scoped base + open-web polish, alongside history
        web_results, raw_conv = await asyncio.gather(
            web_search_with_fallback(
                msg.message, num_results=8,
                board_name=ctx_board_name,
                class_name=ctx_class_name,
                subject_name=msg.subject_name or "",
                scoped_query=_sr_scoped_query,
            ),
            _fetch_history(),
        )
        # Step 2: MongoDB RAG only when BOTH web tiers returned nothing
        if web_results:
            logger.info(f"Web search primary: {len(web_results)} results | RAG skipped")
            rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                       "vector_hits": [], "source": "web", "quality": "web"}
        else:
            logger.info("Web search empty — falling back to MongoDB RAG")
            rag_ctx = await resolve_rag_context(
                msg.message, subject_id=msg.subject_id,
                subject_name=msg.subject_name, document_text=document_text
            )

    # ── Build prompt ───────────────────────────────────────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name":  ctx_board_name,
            "class_name":  ctx_class_name,
            "stream_name": ctx_stream_name,
            "subject_name": msg.subject_name,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        user.get("name", ""),
            "board_name":  ctx_board_name or user.get("board_name", ""),
            "class_name":  ctx_class_name or user.get("class_name", ""),
            "stream_name": ctx_stream_name or user.get("stream_name", ""),
            "plan":        user.get("plan", "free"),
        },
        query=msg.message,
        syllabus=syllabus,
        web_results=web_results or None,
    )

    conv_id = msg.conversation_id
    history_messages = []

    if conv_id and raw_conv:
        raw_history = [
            {"role": m.get("role", ""), "content": m.get("content") or ""}
            for m in raw_conv.get("messages", [])
            if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
        ]
        history_messages = _trim_history(raw_history)
    elif not conv_id:
        conv_id = str(uuid.uuid4())
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        conv_doc = {
            "id": conv_id,
            "user_id": user["id"],
            "title": title,
            "subject_id": msg.subject_id,
            "subject_name": msg.subject_name,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        asyncio.create_task(supa_upsert_conversation(conv_doc))

    messages_payload = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": msg.message}]

    user_msg_saved   = msg.message
    rag_source_saved = rag_ctx.get("source",  "none")
    rag_quality_saved = rag_ctx.get("quality", "none")
    rag_chunks_count = len(rag_ctx.get("chunks",   []))
    rag_subjects_count = len(rag_ctx.get("subjects", []))
    web_search_used  = bool(web_results)
    content_card_meta = rag_ctx.get("content_card_meta") or None
    # Resolve the primary subject this answer came from (for frontend badge link)
    _rag_subjs = rag_ctx.get("subjects", [])
    rag_subject_id   = (_rag_subjs[0].get("id")   if _rag_subjs else None) or msg.subject_id   or None
    rag_subject_name = (_rag_subjs[0].get("name") if _rag_subjs else None) or msg.subject_name or None
    _rag_chaps       = rag_ctx.get("chunk_chapters") or rag_ctx.get("chapters", [])
    rag_chapter_name = (_rag_chaps[0].get("title", "") if _rag_chaps else None) or msg.chapter_name or None
    full_response = []

    # Pull router classification for metadata (prefer router chapter over RAG chapter)
    _router_subject = getattr(_sr_route, "subject", None) if _sr_route else None
    _router_chapter = getattr(_sr_route, "chapter_hint", None) if _sr_route else None
    _router_board   = getattr(_sr_route, "board", None) if _sr_route else None
    # Use router chapter as rag_chapter_name when RAG was not the source
    if _router_chapter and not rag_chapter_name:
        rag_chapter_name = _router_chapter
    if _router_subject and not rag_subject_name:
        rag_subject_name = _router_subject

    # Derive sources from the same RAG context sent to the LLM (no mismatch)
    rag_sources = _sources_from_rag_ctx(rag_ctx)

    async def event_stream():
        nonlocal full_response
        _credit_saved = False  # set True when answer is committed; controls refund in finally
        try:
            # Send RAG metadata with full quality info + subject link data + web search flag
            _meta_event = {'conversation_id': conv_id, 'rag_source': rag_source_saved, 'rag_quality': rag_quality_saved, 'rag_chunks': rag_chunks_count, 'rag_subjects': rag_subjects_count, 'rag_subject_id': rag_subject_id, 'rag_subject_name': rag_subject_name, 'rag_chapter_name': rag_chapter_name, 'router_subject': _router_subject, 'router_chapter': _router_chapter, 'router_board': _router_board, 'web_search_used': web_search_used}
            if content_card_meta:
                _meta_event['content_card_name'] = content_card_meta.get('card_name', '')
                _meta_event['content_card_lesson'] = content_card_meta.get('lesson_name', '')
            yield f"data: {json.dumps(_meta_event)}\n\n"

            # ── Cache check (Streaming) — Redis first, in-memory fallback ────────
            is_casual = _classify_question(msg.message) == "casual"
            cache_key = _cache_key(msg.message, subject_id=msg.subject_id or "", board_id=ctx_board_id or "")
            _cache_ttl = REDIS_CASUAL_CACHE_TTL if is_casual else REDIS_AI_CACHE_TTL
            cached_answer = None

            cached_answer = _redis_get_ai_cache(cache_key)
            if cached_answer:
                logger.info(f"Redis cache HIT (STREAM): {cache_key}")
            elif cache_key in _ai_response_cache:
                cached_answer = _ai_response_cache[cache_key]
                logger.info(f"Memory cache HIT (STREAM): {cache_key}")

            if cached_answer:
                # Yield in small chunks to preserve streaming UX for cache hits
                _CHUNK_SIZE = 50
                for _ci in range(0, len(cached_answer), _CHUNK_SIZE):
                    yield f"data: {json.dumps({'content': cached_answer[_ci:_ci + _CHUNK_SIZE]})}\n\n"
                    await asyncio.sleep(0.008)
                full_response.append(cached_answer)
            else:
                _bp_count = 0
                async for chunk in call_llm_api_stream(messages_payload, model=msg.model or LLM_MODEL, max_tokens=max_tokens):
                    if '"content"' in chunk:
                        try:
                            data = json.loads(chunk[6:])
                            full_response.append(data.get("content", ""))
                        except:
                            pass
                    yield chunk
                    _bp_count += 1
                    if _bp_count % 20 == 0:
                        await asyncio.sleep(0)

                if full_response:
                    answer_str = "".join(full_response)
                    if answer_str:
                        _redis_set("ai_cache", cache_key, answer_str, _cache_ttl)
                        if not redis_client:
                            _ai_response_cache[cache_key] = answer_str
                        logger.info(f"Cache MISS → stored (STREAM, ttl={_cache_ttl}s): {cache_key}")

            # Yield DONE immediately — DB writes happen in background
            answer = "".join(full_response)
            new_used_optimistic = credits_info["used"] + 1 if answer else credits_info["used"]

            # ── syrabit_done event with credits metadata + RAG-derived sources ────
            done_payload = {
                "event": "syrabit_done",
                "conversation_id": conv_id,
                "credits_used": 1,
                "credits_used_total": new_used_optimistic,
                "remaining_credits": max(0, credits_info["remaining"] - 1),
                "rag_source": rag_source_saved,
                "rag_chunks": rag_chunks_count,
                "words": len(answer.split()) if answer else 0,
                "sources": rag_sources,
                "web_search_used": web_search_used,
            }
            if content_card_meta:
                done_payload["content_card_name"] = content_card_meta.get("card_name", "")
                done_payload["content_card_lesson"] = content_card_meta.get("lesson_name", "")
            yield f"data: {json.dumps(done_payload)}\n\n"
            yield "data: [DONE]\n\n"

            try:
                _record_chat_latency((_time_mod.time() - _stream_t0) * 1000)
            except Exception:
                pass

            try:
                _pc = sum(len(m.get("content", "")) for m in messages_payload)
                record_llm_cost(
                    model=msg.model or LLM_MODEL,
                    prompt_tokens=max(1, _pc // 4),
                    completion_tokens=max(1, len(answer) // 4) if answer else 1,
                    provider="gemini",
                    user_id=str(user["id"]),
                )
            except Exception:
                pass

            # Fire background: save messages (credit already deducted before stream started)
            if answer:
                _credit_saved = True  # mark credit as legitimately consumed
                asyncio.create_task(_persist_chat_turn(
                    conv_id, user["id"],
                    user_msg_saved, answer,
                    rag_source_saved, rag_chunks_count,
                    credits_info["used"],
                ))
                asyncio.create_task(_log_chat_message(
                    user_id=user["id"],
                    question=user_msg_saved,
                    raw_ai_answer=answer,
                    subject_id=msg.subject_id,
                    subject_name=msg.subject_name,
                    board_name=ctx_board_name,
                    class_name=ctx_class_name,
                    conversation_id=conv_id,
                ))
        finally:
            # Guaranteed refund if credit was pre-deducted but no answer was committed
            if not _credit_saved:
                asyncio.create_task(_refund_credit(user["id"], credits_info["used"] + 1))

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ─────────────────────────────────────────────
# PUBLIC SEARCH API  — /api/v1/search
# ─────────────────────────────────────────────
@api.get("/v1/search", response_model=SearchResultOut)
async def public_library_search(q: str = "", board: Optional[str] = None, class_num: Optional[str] = None):
    """Public search endpoint: returns matching syrabit.ai library pages.
    Example: GET /api/v1/search?q=limits+class+11+ahsec
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="q parameter is required")
    results = await syrabit_library_search(q.strip(), board_slug=board, class_slug=class_num)
    return {"query": q, "results": results, "count": len(results)}


# ─────────────────────────────────────────────
# CONVERSATION ROUTES
# ─────────────────────────────────────────────
@api.get("/conversations")
async def get_conversations(user: dict = Depends(get_current_user)):
    convs = await supa_get_conversations(user["id"])
    return convs

@api.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, user: dict = Depends(get_current_user)):
    conv = await supa_get_conversation(conv_id, user["id"])
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv

@api.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: dict = Depends(get_current_user)):
    await supa_delete_conversation(conv_id, user["id"])
    return {"message": "Deleted"}

@api.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: str, data: dict, user: dict = Depends(get_current_user)):
    allowed = {k: v for k, v in data.items() if k in ["title", "starred", "archived"]}
    if not allowed:
        raise HTTPException(status_code=400, detail="No valid fields")
    await supa_update_conversation(conv_id, user["id"], allowed)
    return {"message": "Updated"}

# ─────────────────────────────────────────────
# USER PROFILE ROUTES
# ─────────────────────────────────────────────
@api.post("/user/onboarding")
async def save_onboarding(data: OnboardingData, user: dict = Depends(get_current_user)):
    await supa_update_user(user["id"], {
        "onboarding_done": True,
        "board_id": data.board_id,
        "board_name": data.board_name,
        "class_id": data.class_id,
        "class_name": data.class_name,
        "stream_id": data.stream_id,
        "stream_name": data.stream_name,
    })
    return {"message": "Onboarding complete"}

@api.get("/user/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    credits_info = await get_user_credits(user)
    return {
        "id": user["id"],
        "name": user.get("name", ""),
        "email": user["email"],
        "bio": user.get("bio", ""),
        "phone": user.get("phone", ""),
        "plan": user.get("plan", "free"),
        "credits_used": credits_info["used"],
        "credits_limit": credits_info["limit"],
        "credits_remaining": credits_info["remaining"],
        "document_access": credits_info["document_access"],
        "onboarding_done": user.get("onboarding_done", False),
        "is_admin": user.get("is_admin", False),
        "board_name": user.get("board_name", ""),
        "class_name": user.get("class_name", ""),
        "stream_name": user.get("stream_name", ""),
        "saved_subjects": user.get("saved_subjects", []),
        "created_at": user.get("created_at", ""),
        "avatar_url": user.get("avatar_url", ""),
        "status": user.get("status", "active"),
        "deletion_requested_at": user.get("deletion_requested_at"),
        "deletion_hard_at": user.get("deletion_hard_at"),
    }

@api.patch("/user/profile")
async def update_profile(data: ProfileUpdate, user: dict = Depends(get_current_user)):
    update = {}
    if data.name:        update["name"]  = data.name
    if data.bio is not None: update["bio"] = data.bio
    if data.phone is not None: update["phone"] = data.phone
    if data.board_name is not None: update["board_name"] = data.board_name
    if data.class_name is not None: update["class_name"] = data.class_name
    if data.stream_name is not None: update["stream_name"] = data.stream_name
    if data.avatar_url is not None:
        if data.avatar_url and not data.avatar_url.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="Invalid avatar URL format")
        if data.avatar_url and len(data.avatar_url) > 3 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Avatar data too large")
        update["avatar_url"] = data.avatar_url
    if update:
        await supa_update_user(user["id"], update)
    return {"message": "Profile updated"}

@api.post("/user/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}")
    file_content = await file.read()
    max_size = 2 * 1024 * 1024
    if len(file_content) > max_size:
        raise HTTPException(status_code=400, detail="Image must be under 2 MB")
    import base64
    b64 = base64.b64encode(file_content).decode("utf-8")
    data_url = f"data:{file.content_type};base64,{b64}"
    await supa_update_user(user["id"], {"avatar_url": data_url})
    return {"avatar_url": data_url}

@api.get("/user/saved-subjects")
async def get_saved_subjects(user: dict = Depends(get_current_user)):
    return {"saved_subjects": user.get("saved_subjects", [])}

@api.post("/user/saved-subjects/{subject_id}")
async def toggle_saved_subject(subject_id: str, user: dict = Depends(get_current_user)):
    saved = user.get("saved_subjects", [])
    if subject_id in saved:
        saved.remove(subject_id)
        action = "removed"
    else:
        saved.append(subject_id)
        action = "added"
    await supa_update_user(user["id"], {"saved_subjects": saved})
    return {"message": action, "saved_subjects": saved}

@api.get("/user/credits")
async def get_credits(user: dict = Depends(get_current_user)):
    credits_info = await get_user_credits(user)
    return credits_info

@api.get("/user/stats")
async def get_user_stats(user: dict = Depends(get_current_user)):
    """Returns aggregated usage stats for the profile page."""
    conv_count = 0
    # Fast path: single COUNT query — much faster than fetching all conversations
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM conversations WHERE user_id = $1", user["id"]
                )
                if row:
                    conv_count = int(row["cnt"])
        except Exception as e:
            logger.warning(f"pg conv count failed: {e}")
            convs = await supa_get_conversations(user["id"])
            conv_count = len(convs) if convs else 0
    else:
        convs = await supa_get_conversations(user["id"])
        conv_count = len(convs) if convs else 0
    saved_count = len(user.get("saved_subjects", []))
    total_tokens = user.get("credits_used", 0) * 300
    return {
        "conversations": conv_count,
        "saved_subjects": saved_count,
        "total_tokens": total_tokens,
        "credits_used": user.get("credits_used", 0),
    }

@api.delete("/user/account")
async def delete_account(user: dict = Depends(get_current_user)):
    """Soft-delete: marks account for deletion after 72 hours."""
    hard_delete_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
    await supa_update_user(user["id"], {
        "status": "pending_deletion",
        "deletion_requested_at": datetime.now(timezone.utc).isoformat(),
        "deletion_hard_at": hard_delete_at,
    })
    return {"message": "Account scheduled for deletion", "hard_delete_at": hard_delete_at}

@api.post("/user/account/cancel-delete")
async def cancel_delete_account(user: dict = Depends(get_current_user)):
    """Cancels a pending soft-delete within the 72h grace period."""
    await supa_update_user(user["id"], {
        "status": "active",
        "deletion_requested_at": None,
        "deletion_hard_at": None,
    })
    return {"message": "Account deletion cancelled"}

# ─────────────────────────────────────────────
# ADMIN AUTH
# ─────────────────────────────────────────────
@api.post("/admin/login")
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
    response.set_cookie(
        key="syrabit_admin_session",
        value=token,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=60 * 24 * 60,
    )
    return {
        "access_token": token,
        "token_type":   "bearer",
        "email":        matched["email"],
        "name":         matched["name"],
    }

@api.post("/auth/refresh")
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
    new_access = create_access_token(user_id, role=role)
    _redis_invalidate_session(user_id)
    response.set_cookie(
        key="syrabit_session",
        value=new_access,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=JWT_ACCESS_EXPIRE_MINUTES * 60,
    )
    return {"access_token": new_access, "token_type": "bearer"}

@api.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user_optional)):
    if user:
        _redis_invalidate_session(user.get("id", ""))
    response.delete_cookie(key="syrabit_session", samesite=COOKIE_SAMESITE, secure=SECURE_COOKIES)
    response.delete_cookie(key="syrabit_refresh", samesite=COOKIE_SAMESITE, secure=SECURE_COOKIES, path="/api/auth/refresh")
    return {"message": "Logged out"}

@api.post("/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie(key="syrabit_admin_session", samesite=COOKIE_SAMESITE, secure=SECURE_COOKIES)
    return {"message": "Logged out"}

@api.get("/admin/verify")
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
    response.set_cookie(
        key="syrabit_admin_session",
        value=refreshed,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=60 * 24 * 60,
    )
    return {"valid": True, "email": admin.get("email"), "name": admin.get("name", "Admin")}

# ─────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────
@api.get("/admin/dashboard")
async def admin_dashboard(admin: dict = Depends(get_admin_user)):
    total_users = await supa_count_users()

    # ── Conversations + messages: merge PG and Supabase ──────────────────────
    pg_conv_map: dict = {}   # id -> {"messages": [...]}
    supa_conv_rows: list = []

    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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

@api.get("/admin/users")
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

@api.patch("/admin/users/{user_id}/status")
async def admin_update_user_status(user_id: str, data: UserStatusUpdate, admin: dict = Depends(get_admin_user)):
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await supa_update_user(user_id, {"status": data.status})
    return {"message": "Updated"}

@api.patch("/admin/users/{user_id}/plan")
async def admin_update_user_plan(user_id: str, data: UserPlanUpdate, admin: dict = Depends(get_admin_user)):
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update = {"plan": data.plan}
    if data.credits_used is not None:
        update["credits_used"] = data.credits_used
    await supa_update_user(user_id, update)
    return {"message": "Updated"}

@api.patch("/admin/users/{user_id}/credits")
async def admin_update_user_credits(user_id: str, data: UserCreditsUpdate, admin: dict = Depends(get_admin_user)):
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.action not in ("add", "deduct", "reset"):
        raise HTTPException(status_code=400, detail="action must be one of: add, deduct, reset")
    if data.action != "reset" and (data.amount is None or data.amount < 0):
        raise HTTPException(status_code=400, detail="amount must be a non-negative integer for add/deduct actions")
    credits_used = user.get("credits_used", 0)
    credits_limit = user.get("credits_limit", 0)
    action = data.action
    amount = data.amount if data.amount is not None else 0
    update = {}
    if action == "reset":
        update["credits_used"] = 0
    elif action == "deduct":
        update["credits_used"] = min(credits_limit, credits_used + amount)
    else:
        update["credits_limit"] = credits_limit + amount
    await supa_update_user(user_id, update)
    return {"message": "Credits updated", **update}

@api.post("/admin/sync-conversations")
async def admin_sync_conversations(admin: dict = Depends(get_admin_user)):
    """Sync all Supabase conversations → PostgreSQL (upsert, PG wins on message count tie)."""
    if not supa or not pg_pool:
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
    async with pg_pool.acquire() as conn:
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

    async with pg_pool.acquire() as conn:
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
    async with pg_pool.acquire() as conn:
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


@api.get("/admin/conversations")
async def admin_get_conversations(admin: dict = Depends(get_admin_user)):
    # Fetch from both PostgreSQL and Supabase and merge (PG takes precedence for messages)
    pg_convs: list = []
    supa_convs: list = []

    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
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

@api.get("/admin/analytics")
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


@api.post("/analytics/page-view")
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


@api.post("/analytics/session-ping")
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


@api.post("/analytics/session-end")
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


@api.get("/admin/analytics/live")
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


@api.post("/analytics/track")
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
    
    await track_library_event(
        event_type=event_type,
        subject_id=subject_id,
        chapter_id=chapter_id,
        user_id=user_id,
        search_query=search_query,
        metadata=metadata
    )
    
    return {"status": "tracked"}

# ─────────────────────────────────────────────
# ADMIN CONTENT MANAGEMENT — Boards / Classes / Streams
# ─────────────────────────────────────────────

# GET aliases — admin UI reads from these (proxy to public handlers)
@api.get("/admin/content/boards")
async def admin_list_boards(admin: dict = Depends(get_admin_user)):
    return await get_boards()

@api.get("/admin/content/classes")
async def admin_list_classes(admin: dict = Depends(get_admin_user)):
    return await get_classes()

@api.get("/admin/content/streams")
async def admin_list_streams(admin: dict = Depends(get_admin_user)):
    return await get_streams()

@api.get("/admin/content/subjects")
async def admin_list_subjects(admin: dict = Depends(get_admin_user)):
    return await get_subjects()

@api.get("/admin/content/chapters/{subject_id}")
async def admin_list_chapters(subject_id: str, admin: dict = Depends(get_admin_user)):
    """Admin chapter list — always reads live from DB, no caching, includes all statuses."""
    chapters = await db.chapters.find({"subject_id": subject_id}).sort("order_index", 1).to_list(None)
    return [{k: v for k, v in c.items() if k != "_id"} for c in chapters]

@api.post("/admin/content/boards")
async def admin_create_board(data: dict, admin: dict = Depends(get_admin_user)):
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable - cannot create content")
        board_id = str(uuid.uuid4())[:8]
        board = {
            "id": board_id,
            "name": data["name"],
            "slug": data["name"].lower().replace(" ", "-"),
            "description": data.get("description", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.boards.insert_one(board)
        _invalidate_content_cache("boards")
        return {k: v for k, v in board.items() if k != "_id"}
    except HTTPException:
        raise
    except Exception as e:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Database error")

@api.patch("/admin/content/boards/{board_id}")
async def admin_update_board(board_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    allowed = {k: v for k, v in data.items() if k in ["name", "description"]}
    if "name" in allowed:
        allowed["slug"] = allowed["name"].lower().replace(" ", "-")
    if allowed:
        await db.boards.update_one({"id": board_id}, {"$set": allowed})
        _invalidate_content_cache("boards")
    return {"message": "Board updated"}

@api.delete("/admin/content/boards/{board_id}")
async def admin_delete_board(board_id: str, admin: dict = Depends(get_admin_user)):
    await db.boards.delete_one({"id": board_id})
    _invalidate_content_cache("boards")
    return {"message": "Board deleted"}

@api.post("/admin/content/classes")
async def admin_create_class(data: dict, admin: dict = Depends(get_admin_user)):
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable - cannot create content")
        class_id = str(uuid.uuid4())[:8]
        cls = {
            "id": class_id,
            "board_id": data["board_id"],
            "name": data["name"],
            "slug": data["name"].lower().replace(" ", "-"),
            "description": data.get("description", ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.classes.insert_one(cls)
        _invalidate_content_cache("classes")
        return {k: v for k, v in cls.items() if k != "_id"}
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Database error")

@api.patch("/admin/content/classes/{class_id}")
async def admin_update_class(class_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    allowed = {k: v for k, v in data.items() if k in ["name", "description"]}
    if "name" in allowed:
        allowed["slug"] = allowed["name"].lower().replace(" ", "-")
    if allowed:
        await db.classes.update_one({"id": class_id}, {"$set": allowed})
        _invalidate_content_cache("classes")
    return {"message": "Class updated"}

@api.delete("/admin/content/classes/{class_id}")
async def admin_delete_class(class_id: str, admin: dict = Depends(get_admin_user)):
    await db.classes.delete_one({"id": class_id})
    _invalidate_content_cache("classes")
    return {"message": "Class deleted"}

@api.post("/admin/content/streams")
async def admin_create_stream(data: dict, admin: dict = Depends(get_admin_user)):
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable - cannot create content")
        stream_id = str(uuid.uuid4())[:8]
        stream = {
            "id": stream_id,
            "class_id": data["class_id"],
            "name": data["name"],
            "slug": data["name"].lower().replace(" ", "-"),
            "description": data.get("description", ""),
            "icon": data.get("icon", "📚"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.streams.insert_one(stream)
        _invalidate_content_cache("streams")
        return {k: v for k, v in stream.items() if k != "_id"}
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Database error")

@api.patch("/admin/content/streams/{stream_id}")
async def admin_update_stream(stream_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    allowed = {k: v for k, v in data.items() if k in ["name", "description", "icon"]}
    if "name" in allowed:
        allowed["slug"] = allowed["name"].lower().replace(" ", "-")
    if allowed:
        await db.streams.update_one({"id": stream_id}, {"$set": allowed})
        _invalidate_content_cache("streams")
    return {"message": "Stream updated"}

@api.delete("/admin/content/streams/{stream_id}")
async def admin_delete_stream(stream_id: str, admin: dict = Depends(get_admin_user)):
    await db.streams.delete_one({"id": stream_id})
    _invalidate_content_cache("streams")
    return {"message": "Stream deleted"}


# ─────────────────────────────────────────────
# ADMIN — FYUGP Auto-Assign
# Re-links subjects from PDF imports into pre-built FYUGP semester/stream slots
# ─────────────────────────────────────────────
@api.post("/admin/fyugp/auto-assign")
async def admin_fyugp_auto_assign(admin: dict = Depends(get_admin_user)):
    """
    Scans every subject that has paper_type + class_name data (from PDF imports)
    and re-links them to the canonical FYUGP Semester 1-4 classes (c7-c10) and
    their 6 pre-built course-type streams (Major/Minor/MDC/VAC/AEC/SEC).
    Safe to run multiple times — idempotent.
    """
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    from syllabus_linker import _parse_semester_number, NEP_COURSE_STREAMS

    # FYUGP canonical class map: slug → id
    fyugp_classes = {
        "semester-1": "c7", "semester-2": "c8",
        "semester-3": "c9", "semester-4": "c10",
    }
    # Stream slug → canonical stream id per class
    fyugp_streams = {
        "c7":  {"major": "s30", "minor": "s31", "mdc": "s32", "vac": "s33", "aec": "s34", "sec": "s35"},
        "c8":  {"major": "s36", "minor": "s37", "mdc": "s38", "vac": "s39", "aec": "s40", "sec": "s41"},
        "c9":  {"major": "s42", "minor": "s43", "mdc": "s44", "vac": "s45", "aec": "s46", "sec": "s47"},
        "c10": {"major": "s48", "minor": "s49", "mdc": "s50", "vac": "s51", "aec": "s52", "sec": "s53"},
    }

    subjects = await db.subjects.find(
        {"source": "pdf_import", "paper_type": {"$exists": True, "$ne": ""}},
        {"_id": 0}
    ).to_list(5000)

    reassigned = 0
    skipped = 0

    for subj in subjects:
        paper_type = (subj.get("paper_type") or "").lower().strip()
        if paper_type not in NEP_COURSE_STREAMS:
            skipped += 1
            continue

        # Determine semester from class_name or class_slug
        sem_text = subj.get("className") or subj.get("class_slug") or ""
        sem_num  = _parse_semester_number(sem_text)
        if not sem_num or sem_num > 4:
            skipped += 1
            continue

        class_slug = f"semester-{sem_num}"
        class_id   = fyugp_classes.get(class_slug)
        stream_id  = fyugp_streams.get(class_id, {}).get(paper_type)
        if not class_id or not stream_id:
            skipped += 1
            continue

        # Already correct — skip
        if subj.get("stream_id") == stream_id:
            continue

        # Fetch stream + class metadata for denorm fields
        stream_doc = await db.streams.find_one({"id": stream_id}, {"_id": 0})
        class_doc  = await db.classes.find_one({"id": class_id}, {"_id": 0})
        stream_name = stream_doc.get("name", paper_type.upper()) if stream_doc else paper_type.upper()
        class_name  = class_doc.get("name", f"Semester {sem_num}") if class_doc else f"Semester {sem_num}"

        await db.subjects.update_one(
            {"id": subj["id"]},
            {"$set": {
                "stream_id":   stream_id,
                "stream_slug": paper_type,
                "class_slug":  class_slug,
                "class_id":    class_id,
                "className":   class_name,
                "streamName":  stream_name,
                "boardId":     "b2",
                "boardName":   "DEGREE",
                "board_slug":  "degree",
            }}
        )
        reassigned += 1

    _invalidate_content_cache("subjects")
    _invalidate_content_cache("streams")
    _invalidate_content_cache("classes")
    return {
        "message": f"FYUGP auto-assign complete",
        "reassigned": reassigned,
        "skipped": skipped,
        "total_scanned": len(subjects),
    }


# ─────────────────────────────────────────────
# ADMIN CONTENT MANAGEMENT — Subjects
# ─────────────────────────────────────────────
@api.post("/admin/content/subjects")
async def admin_create_subject(data: SubjectCreate, admin: dict = Depends(get_admin_user)):
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable - cannot create content")
        
        stream_name_val = ""
        board_id_val = ""
        board_name_val = ""
        class_name_val = ""
        stream_id_val = data.stream_id or ""

        if data.stream_id:
            stream = await db.streams.find_one({"id": data.stream_id}, {"_id": 0})
            if not stream:
                raise HTTPException(status_code=404, detail="Stream not found")
            stream_name_val = stream.get("name", "")
            class_obj = await db.classes.find_one({"id": stream.get("class_id")}, {"_id": 0})
            board = await db.boards.find_one({"id": class_obj.get("board_id") if class_obj else None}, {"_id": 0})
            board_id_val = board.get("id", "") if board else ""
            board_name_val = board.get("name", "") if board else ""
            class_name_val = class_obj.get("name", "") if class_obj else ""
        elif data.stream_name:
            stream_name_val = data.stream_name.strip()
        else:
            raise HTTPException(status_code=400, detail="Stream selection or custom stream name is required")
        
        subject_id = str(uuid.uuid4())
        subj = {
            "id": subject_id,
            "name": data.name,
            "stream_id": stream_id_val,
            "streamName": stream_name_val,
            "boardId": board_id_val,
            "boardName": board_name_val,
            "className": class_name_val,
            "description": data.description,
            "tags": data.tags,
            "thumbnailUrl": data.thumbnail_url,
            "status": data.status,
            "slug": data.name.lower().replace(" ", "-"),
            "chapter_count": 0,
            "gradient": "math",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.subjects.insert_one(subj)
        _invalidate_content_cache("subjects")
        return {k: v for k, v in subj.items() if k != "_id"}
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Database error")

@api.put("/admin/content/subjects/{subject_id}")
async def admin_update_subject(subject_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    if "thumbnail_url" in data:
        data["thumbnailUrl"] = data.pop("thumbnail_url")
    allowed = {k: v for k, v in data.items() if k in ["name", "description", "tags", "status", "thumbnailUrl"]}
    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.subjects.update_one({"id": subject_id}, {"$set": allowed})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subject not found")
    _invalidate_content_cache("subjects")
    return {"message": "Updated"}

@api.patch("/admin/content/subjects/{subject_id}")
async def admin_patch_subject(subject_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    """Update subject (PATCH method)"""
    if "thumbnail_url" in data:
        data["thumbnailUrl"] = data.pop("thumbnail_url")
    allowed = {k: v for k, v in data.items() if k in ["name", "description", "tags", "status", "thumbnailUrl"]}
    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.subjects.update_one({"id": subject_id}, {"$set": allowed})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subject not found")
    _invalidate_content_cache("subjects")
    return {"message": "Subject updated"}



@api.post("/admin/content/subjects/{subject_id}/thumbnail")
async def upload_subject_thumbnail(
    subject_id: str,
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user),
):
    subj = await db.subjects.find_one({"id": subject_id})
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")
    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}")
    file_content = await file.read()
    max_size = 2 * 1024 * 1024
    if len(file_content) > max_size:
        raise HTTPException(status_code=400, detail="Image must be under 2 MB")
    import base64
    b64 = base64.b64encode(file_content).decode("utf-8")
    data_url = f"data:{file.content_type};base64,{b64}"
    await db.subjects.update_one(
        {"id": subject_id},
        {"$set": {"thumbnailUrl": data_url, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"thumbnailUrl": data_url}


# ─────────────────────────────────────────────────────────────────────────────
# AI THUMBNAIL GENERATOR — Vision analysis + PIL abstract variant generation
# ─────────────────────────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c*2 for c in h)
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return (100, 80, 200)


def _extract_dominant_colors(img_bytes: bytes, n: int = 5) -> list:
    """Fast dominant color extraction using PIL pixel sampling."""
    from PIL import Image
    import io as _io
    img = Image.open(_io.BytesIO(img_bytes)).convert('RGB').resize((120, 180))
    pixels = list(img.getdata())
    buckets: dict = {}
    for r, g, b in pixels:
        key = (r // 48 * 48, g // 48 * 48, b // 48 * 48)
        buckets[key] = buckets.get(key, 0) + 1
    top = sorted(buckets.items(), key=lambda x: -x[1])[:n]
    return [f'#{r:02x}{g:02x}{b:02x}' for (r, g, b), _ in top]


async def _analyze_with_groq_vision(b64_img: str, mime: str = "image/jpeg") -> dict:
    """Call Groq vision model to get color/style analysis of a cover image."""
    if not _GROQ_KEY:
        return {}
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=25) as _c:
            resp = await _c.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {_GROQ_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64_img}"}},
                            {"type": "text", "text": (
                                "Analyze this book cover. Return ONLY valid JSON (no extra text):\n"
                                "{\"dominant_colors\":[\"#hex1\",\"#hex2\",\"#hex3\"],"
                                "\"secondary_colors\":[\"#hex4\",\"#hex5\"],"
                                "\"style\":\"minimalist|bold|academic|colorful|dark|light\","
                                "\"mood\":\"serious|vibrant|calm|educational|professional\","
                                "\"bg_is_dark\":true,"
                                "\"accent_color\":\"#hex\"}"
                            )}
                        ]
                    }],
                    "max_tokens": 250,
                    "temperature": 0.05,
                },
            )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
    except Exception as _ve:
        logger.warning(f"Vision analysis failed: {_ve}")
    return {}


def _generate_abstract_variant(colors: list, variant: int, size=(400, 600)) -> str:
    """
    Generate a copyright-safe abstract educational background using PIL.
    Returns a PNG data URL (~120-200 KB).
    """
    from PIL import Image, ImageDraw, ImageFilter
    import io as _io, math as _math

    W, H = size
    palette = [_hex_to_rgb(c) for c in (colors or ['#7c3aed', '#1e1b4b', '#f8fafc'])]
    while len(palette) < 5:
        palette.append(palette[-1])

    img = Image.new('RGB', (W, H))
    draw = ImageDraw.Draw(img, 'RGBA')

    if variant == 0:
        # ── Gradient Wash + bokeh ──────────────────────────────────────────
        c1, c2 = palette[0], palette[1]
        for y in range(H):
            t = y / H
            r = int(c1[0] * (1 - t) + c2[0] * t)
            g = int(c1[1] * (1 - t) + c2[1] * t)
            b = int(c1[2] * (1 - t) + c2[2] * t)
            draw.line([(0, y), (W, y)], fill=(r, g, b))
        # bokeh circles
        spots = [(80, 120, 110), (320, 480, 150), (200, 300, 80), (350, 100, 60)]
        for (cx, cy, rad), col in zip(spots, [palette[2], palette[3], palette[4], palette[1]]):
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(*col, 55))
        img = img.filter(ImageFilter.GaussianBlur(2))

    elif variant == 1:
        # ── Geometric Blocks ───────────────────────────────────────────────
        img.paste(palette[1], [0, 0, W, H])
        # upper band
        draw.rectangle([0, 0, W, H // 3], fill=(*palette[0], 255))
        # diagonal cut
        draw.polygon([(0, H // 3), (W, H // 4), (W, H // 3), (0, H // 3 + 40)], fill=(*palette[2], 200))
        # accent rectangles
        rects = [(30, H // 2, 120, H // 2 + 90), (W - 140, 60, W - 30, 160), (150, H - 160, 280, H - 40)]
        for rx0, ry0, rx1, ry1 in rects:
            draw.rectangle([rx0, ry0, rx1, ry1], fill=(*palette[3], 100))
        # thin lines
        for i in range(0, W, 35):
            draw.line([(i, 0), (i + 60, H)], fill=(*palette[4], 40), width=1)
        img = img.filter(ImageFilter.GaussianBlur(1))

    elif variant == 2:
        # ── Layered Abstract Circles ──────────────────────────────────────
        img.paste(palette[0], [0, 0, W, H])
        circles = [
            (W * 0.75, H * 0.25, 220, palette[1], 130),
            (W * 0.20, H * 0.65, 180, palette[2], 110),
            (W * 0.55, H * 0.55, 150, palette[3], 90),
            (W * 0.10, H * 0.15, 100, palette[4], 70),
            (W * 0.85, H * 0.80, 130, palette[1], 80),
        ]
        for (cx, cy, r, col, alpha) in circles:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*col, alpha))
        img = img.filter(ImageFilter.GaussianBlur(3))
        # sharp geometric overlay
        overlay_draw = ImageDraw.Draw(img)
        overlay_draw.rectangle([0, H * 0.72, W, H], fill=(*palette[0], 180))

    buf = _io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    return f'data:image/png;base64,{b64}'


@api.post("/admin/thumbnail/generate-cms")
async def generate_cms_thumbnails(
    doc_id: str = Form(...),
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user),
):
    """
    Upload a cover image → Groq Vision color-DNA analysis → 3 abstract copyright-safe variants.
    Works with CMS documents (doc_id) instead of subject_id.
    Returns: {original_url, variants:[v1,v2,v3], analysis:{colors,style,mood}}
    """
    img_bytes = await file.read()
    mime_type = file.content_type or "image/png"

    if len(img_bytes) > 3 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 3 MB")

    # ── Resize for Vision ───────────────────────────────────────────────────
    from PIL import Image as _PILImage
    import io as _io
    try:
        src_img = _PILImage.open(_io.BytesIO(img_bytes)).convert('RGB')
        src_img.thumbnail((400, 600), _PILImage.LANCZOS)
        buf = _io.BytesIO()
        src_img.save(buf, format='PNG')
        buf.seek(0)
        img_bytes_resized = buf.read()
    except Exception as _pe:
        logger.warning(f"PIL resize failed: {_pe}")
        img_bytes_resized = img_bytes

    b64_src = base64.b64encode(img_bytes_resized).decode()
    original_url = f"data:image/png;base64,{b64_src}"

    # ── Vision analysis + PIL fallback ──────────────────────────────────────
    analysis = await _analyze_with_groq_vision(b64_src, "image/png")
    pil_colors = _extract_dominant_colors(img_bytes_resized)

    if analysis.get("dominant_colors"):
        colors = analysis["dominant_colors"][:3] + analysis.get("secondary_colors", [])[:2]
        colors = (colors + pil_colors)[:5]
    else:
        colors = pil_colors[:5]
        analysis = {"dominant_colors": colors, "style": "educational", "mood": "academic"}

    # ── Generate 3 abstract variants in parallel ────────────────────────────
    loop = asyncio.get_event_loop()
    variants = await asyncio.gather(
        loop.run_in_executor(None, _generate_abstract_variant, colors, 0),
        loop.run_in_executor(None, _generate_abstract_variant, colors, 1),
        loop.run_in_executor(None, _generate_abstract_variant, colors, 2),
    )

    # ── Persist thumbnail_variants to cms_documents ─────────────────────────
    await db.cms_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "thumbnail_variants": {
                "original_url":  original_url,
                "variant1_url":  variants[0],
                "variant2_url":  variants[1],
                "variant3_url":  variants[2],
                "analysis":      analysis,
                "generated_at":  datetime.now(timezone.utc).isoformat(),
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    logger.info(f"CMS thumbnail variants generated for doc {doc_id}: {len(colors)} colors")
    return {
        "original_url":  original_url,
        "variants":      list(variants),
        "analysis":      analysis,
        "auto_selected": 0,
    }


@api.post("/admin/thumbnail/generate")
async def generate_ai_thumbnails(
    subject_id: str = Form(...),
    file: Optional[UploadFile] = File(default=None),
    admin: dict = Depends(get_admin_user),
):
    """
    Upload a book cover (or use existing thumbnailUrl) → Vision analysis → 3 abstract variants.
    Returns: {original_url, variants:[v1,v2,v3], analysis:{colors,style,mood}, auto_selected:0}
    """
    # ── Get or read the source image ──────────────────────────────────────
    subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subj:
        raise HTTPException(404, "Subject not found")

    img_bytes: Optional[bytes] = None
    mime_type = "image/png"

    if file and file.filename:
        img_bytes = await file.read()
        mime_type = file.content_type or "image/png"
    elif subj.get("thumbnailUrl", "").startswith("data:"):
        # decode existing base64 thumbnail
        data_url = subj["thumbnailUrl"]
        header, b64_str = data_url.split(",", 1)
        mime_type = header.split(":")[1].split(";")[0]
        img_bytes = base64.b64decode(b64_str)

    if not img_bytes:
        raise HTTPException(400, "No source image: upload a file or ensure the subject has an existing thumbnail")

    if len(img_bytes) > 3 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 3 MB")

    # ── Resize source to 400×600 for Vision ───────────────────────────────
    from PIL import Image as _PILImage
    import io as _io
    try:
        src_img = _PILImage.open(_io.BytesIO(img_bytes)).convert('RGB')
        src_img.thumbnail((400, 600), _PILImage.LANCZOS)
        buf = _io.BytesIO()
        src_img.save(buf, format='PNG')
        buf.seek(0)
        img_bytes_resized = buf.read()
    except Exception as _pe:
        logger.warning(f"PIL resize failed: {_pe}")
        img_bytes_resized = img_bytes

    b64_src = base64.b64encode(img_bytes_resized).decode()
    original_url = f"data:{mime_type};base64,{b64_src}"

    # ── Step 1: Groq Vision analysis (best-effort) ────────────────────────
    analysis = await _analyze_with_groq_vision(b64_src, "image/png")

    # ── Step 2: PIL color extraction (always-on fallback) ─────────────────
    pil_colors = _extract_dominant_colors(img_bytes_resized)

    if analysis.get("dominant_colors"):
        colors = analysis["dominant_colors"][:3] + analysis.get("secondary_colors", [])[:2]
        colors = (colors + pil_colors)[:5]
    else:
        colors = pil_colors[:5]
        analysis = {"dominant_colors": colors, "style": "educational", "mood": "academic"}

    # ── Step 3: Generate 3 abstract variants ──────────────────────────────
    loop = asyncio.get_event_loop()
    variants = await asyncio.gather(
        loop.run_in_executor(None, _generate_abstract_variant, colors, 0),
        loop.run_in_executor(None, _generate_abstract_variant, colors, 1),
        loop.run_in_executor(None, _generate_abstract_variant, colors, 2),
    )

    # ── Step 4: Persist to MongoDB ─────────────────────────────────────────
    thumbnails_data = {
        "original_url":    original_url,
        "variant1_url":    variants[0],
        "variant2_url":    variants[1],
        "variant3_url":    variants[2],
        "analysis":        analysis,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "auto_selected":   0,
    }
    await db.subjects.update_one(
        {"id": subject_id},
        {"$set": {
            "thumbnail_variants": thumbnails_data,
            "thumbnailUrl": original_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    logger.info(f"AI thumbnails generated for subject {subject_id}: {len(colors)} colors extracted")
    return {
        "original_url":  original_url,
        "variants":      list(variants),
        "analysis":      analysis,
        "auto_selected": 0,
    }


@api.post("/admin/thumbnail/apply")
async def apply_thumbnail_variant(
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    """Set the active thumbnailUrl for a subject to one of the generated variants."""
    subject_id    = data.get("subject_id", "")
    variant_index = data.get("variant_index")
    if not subject_id or variant_index is None:
        raise HTTPException(400, "subject_id and variant_index required")
    try:
        variant_index = int(variant_index)
    except (TypeError, ValueError):
        raise HTTPException(400, "variant_index must be an integer 0, 1, or 2")
    if variant_index not in (0, 1, 2):
        raise HTTPException(400, "variant_index must be 0, 1, or 2")
    subject = await db.subjects.find_one({"id": subject_id})
    if not subject:
        raise HTTPException(404, f"Subject '{subject_id}' not found")
    variants = subject.get("thumbnail_variants") or {}
    variant_key = f"variant{variant_index + 1}_url"
    thumb_url = variants.get(variant_key)
    if not thumb_url:
        raise HTTPException(400, f"Variant '{variant_key}' not found for subject '{subject_id}'")
    await db.subjects.update_one(
        {"id": subject_id},
        {"$set": {"thumbnailUrl": thumb_url, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    _invalidate_content_cache("subjects")
    return {"success": True}


@api.post("/admin/thumbnail/generate-bulk")
async def generate_ai_thumbnails_bulk(
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    """
    Bulk generate AI thumbnail variants for up to 50 subjects that already have a thumbnailUrl.
    Returns streaming-style progress list.
    """
    subject_ids = data.get("subject_ids", [])[:50]
    if not subject_ids:
        raise HTTPException(400, "subject_ids required")

    results = []
    for sid in subject_ids:
        subj = await db.subjects.find_one({"id": sid}, {"_id": 0, "thumbnailUrl": 1, "name": 1})
        if not subj or not subj.get("thumbnailUrl", "").startswith("data:"):
            results.append({"subject_id": sid, "status": "skipped", "reason": "no thumbnail"})
            continue
        try:
            data_url = subj["thumbnailUrl"]
            _, b64_str = data_url.split(",", 1)
            img_bytes = base64.b64decode(b64_str)
            colors    = _extract_dominant_colors(img_bytes)
            from PIL import Image as _PILImage
            import io as _io
            src_img = _PILImage.open(_io.BytesIO(img_bytes)).convert('RGB')
            src_img.thumbnail((400, 600), _PILImage.LANCZOS)
            buf = _io.BytesIO(); src_img.save(buf, format='PNG'); buf.seek(0)
            img_bytes_r = buf.read()
            pil_colors = _extract_dominant_colors(img_bytes_r)
            b64_src = base64.b64encode(img_bytes_r).decode()
            analysis = await _analyze_with_groq_vision(b64_src, "image/png")
            all_colors = (analysis.get("dominant_colors", [])[:3] + pil_colors)[:5] or pil_colors
            loop = asyncio.get_event_loop()
            variants = await asyncio.gather(
                loop.run_in_executor(None, _generate_abstract_variant, all_colors, 0),
                loop.run_in_executor(None, _generate_abstract_variant, all_colors, 1),
                loop.run_in_executor(None, _generate_abstract_variant, all_colors, 2),
            )
            thumbnails_data = {
                "original_url": data_url,
                "variant1_url": variants[0],
                "variant2_url": variants[1],
                "variant3_url": variants[2],
                "analysis": analysis,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.subjects.update_one(
                {"id": sid},
                {"$set": {"thumbnail_variants": thumbnails_data, "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            results.append({"subject_id": sid, "name": subj.get("name",""), "status": "done"})
        except Exception as _be:
            logger.error(f"Bulk thumb error for {sid}: {_be}")
            results.append({"subject_id": sid, "status": "failed", "error": str(_be)})

    return {"results": results, "total": len(subject_ids), "done": sum(1 for r in results if r["status"] == "done")}


@api.delete("/admin/content/subjects/{subject_id}")
async def admin_delete_subject(subject_id: str, admin: dict = Depends(get_admin_user)):
    result = await db.subjects.delete_one({"id": subject_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Subject not found")
    await db.chapters.delete_many({"subject_id": subject_id})
    _invalidate_content_cache("subjects")
    _invalidate_content_cache("chapters")
    return {"message": "Deleted"}

@api.post("/admin/content/chapters")
async def admin_create_chapter(data: ChapterCreate, admin: dict = Depends(get_admin_user)):
    chapter_id = str(uuid.uuid4())
    _order = data.order or data.order_index or 1
    _slug = data.slug.strip() if data.slug else ""
    if not _slug:
        _slug = re.sub(r'[^a-z0-9]+', '-', data.title.lower()).strip('-')
    existing = await db.chapters.find_one({"subject_id": data.subject_id, "slug": _slug})
    if existing:
        _slug = f"{_slug}-{chapter_id[:6]}"
    chap = {
        "id": chapter_id,
        "subject_id": data.subject_id,
        "title": data.title,
        "slug": _slug,
        "description": data.description,
        "content": data.content,
        "content_type": data.content_type or "notes",
        "chapter_number": data.chapter_number,
        "order": _order,
        "order_index": _order,
        "status": data.status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chapters.insert_one(chap)
    
    # Mark subject as having content
    await db.subjects.update_one(
        {"id": data.subject_id}, 
        {"$inc": {"chapter_count": 1}, "$set": {"has_document": True}}
    )
    
    # 🆕 AUTO-CHUNK CONTENT
    chunks_created = []
    if data.content and len(data.content.strip()) > 100:
        try:
            chunks_created = await auto_chunk_content(
                chapter_id=chapter_id,
                content=data.content,
                subject_id=data.subject_id
            )
            logger.info(f"✅ Auto-chunked new chapter '{data.title}': {len(chunks_created)} chunks")
        except Exception as chunk_error:
            logger.error(f"❌ Auto-chunking failed for chapter {chapter_id}: {chunk_error}")
    
    result = {k: v for k, v in chap.items() if k != "_id"}
    result["chunks_created"] = len(chunks_created)
    _invalidate_content_cache("chapters")
    _invalidate_content_cache("subjects")
    return result

@api.post("/admin/content/chunks")
async def admin_create_chunk(data: ChunkCreate, admin: dict = Depends(get_admin_user)):
    """Create content chunk"""
    chunk_id = str(uuid.uuid4())
    chunk = {
        "id": chunk_id,
        "chapter_id": data.chapter_id,
        "content": data.content,
        "content_type": data.content_type,
        "tags": data.tags,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.chunks.insert_one(chunk)
    chunk["_id"] = str(result.inserted_id)
    return chunk


# Generic content upload endpoints
@api.post("/admin/content/upload")
async def upload_content_file(
    file: UploadFile = File(...),
    subject_id: str = Form(...),
    content_type: str = Form("document"),
    title: str = Form(None),
    description: str = Form(""),
    tags: str = Form(""),
    year: str = Form(""),
    admin: dict = Depends(get_admin_user)
):
    """Upload content file - stores PDFs as base64, text as plain text"""
    content_id = str(uuid.uuid4())
    
    # Read file
    file_content = await file.read()
    file_ext = file.filename.split('.')[-1].lower() if '.' in file.filename else 'txt'
    
    # Handle different file types
    if file_ext == 'pdf':
        # Store PDF as base64 for easy retrieval
        import base64
        pdf_base64 = base64.b64encode(file_content).decode('utf-8')
        text_content = ""  # Can't extract text easily without extra libs
        file_url = f"data:application/pdf;base64,{pdf_base64}"
    else:
        # Text files
        text_content = file_content.decode('utf-8', errors='ignore')
        file_url = ""
    
    upload_data = {
        "id": content_id,
        "subject_id": subject_id,
        "content_type": content_type,
        "title": title or file.filename.replace(f'.{file_ext}', ''),
        "description": description,
        "tags": tags,
        "year": year,
        "file_name": file.filename,
        "file_ext": file_ext,
        "file_size": len(file_content),
        "file_url": file_url,
        "content": text_content,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by": admin.get("email"),
        "status": "published",
    }
    
    await db.content_uploads.insert_one(upload_data)
    
    # Mark subject as having document
    await db.subjects.update_one(
        {"id": subject_id},
        {"$set": {"has_document": True, "document_type": file_ext}}
    )
    
    logger.info(f"Content uploaded: {file.filename} ({file_ext}) for subject {subject_id}")
    return {"id": content_id, "message": "Upload successful", "file_type": file_ext}

@api.post("/admin/reset-and-seed-content")
async def reset_and_seed_content(admin: dict = Depends(get_admin_user)):
    """Delete all content and seed with 1000+ char dummy chapters"""
    # Delete all chapters
    await db.chapters.delete_many({})
    await db.content_uploads.delete_many({})
    
    # Get first subject to seed
    subjects = await db.subjects.find({"status": "published"}, {"_id": 0}).limit(3).to_list(3)
    
    if not subjects:
        raise HTTPException(status_code=404, detail="No subjects found - create subjects first")
    
    seeded_count = 0
    for subject in subjects:
        # Create 3 chapters with 1000+ char content
        chapters_data = [
            {
                "title": "Introduction and Basic Concepts",
                "content": f"""# Introduction to {subject.get('name', 'Subject')}

## Overview
This chapter covers fundamental concepts and provides a strong foundation for understanding {subject.get('name', 'this subject')}. We'll explore key definitions, important principles, and practical applications that are crucial for AssamBoard students.

## Key Concepts
Understanding the basics is essential. This subject involves:
- Theoretical foundations that build conceptual clarity
- Practical applications in real-world scenarios
- Problem-solving techniques for exam preparation
- Important formulas and their derivations
- Common mistakes to avoid during exams

## Fundamental Principles
The core principles include systematic study of:

1. **Definition and Scope**: Understanding what this field encompasses
2. **Historical Development**: How knowledge evolved over time
3. **Modern Applications**: Relevance in today's world
4. **Interdisciplinary Connections**: Links with other subjects

## Important Points for Exams
- Focus on conceptual clarity over rote learning
- Practice numerical problems regularly
- Understand derivations, don't just memorize
- Make concise notes for quick revision
- Solve previous year questions (PYQs)

## Study Tips
Allocate time systematically: 40% theory, 30% numericals, 30% revision.
Create mind maps for interconnected topics.
Practice explaining concepts to solidify understanding.

**Exam Tip**: Always read questions twice before answering. Time management is crucial in board exams.

**Character Count**: 1200+
"""
            },
            {
                "title": "Advanced Topics and Applications",
                "content": f"""# Advanced Topics in {subject.get('name', 'Subject')}

## Complex Concepts Explained
Building on fundamentals, we now explore advanced ideas that require deeper analytical thinking. These topics frequently appear in AHSEC board exams and competitive examinations.

## Theoretical Framework
Advanced study requires:
- Strong foundation in basics (revisit previous chapter if needed)
- Analytical reasoning and critical thinking skills
- Ability to connect multiple concepts simultaneously
- Mathematical proficiency for problem-solving
- Visualization of abstract concepts

## Key Advanced Topics

### Topic 1: Detailed Analysis
This involves understanding mechanisms, patterns, and underlying principles. Students must grasp:
- Cause and effect relationships
- Step-by-step processes
- Conditions and exceptions
- Practical implications

### Topic 2: Problem-Solving Strategies
Approach problems systematically:
1. Read and understand the question
2. Identify given data and what's asked
3. Choose appropriate formula/method
4. Solve step-by-step with units
5. Verify answer makes sense

### Topic 3: Applications
Real-world applications help remember concepts better. This topic has applications in:
- Industry and technology
- Environmental science
- Medical field
- Daily life phenomena

## Common Exam Questions
- Derivation-based questions (5 marks)
- Numerical problems (3 marks)
- Short answer questions (2 marks)
- Very short answers (1 mark)

## Preparation Strategy
- Solve at least 50 problems before exam
- Practice derivations until you can do them with eyes closed
- Make formula sheets for quick revision
- Group study helps clarify doubts

**Exam Tip**: In numericals, always write the formula first, then substitute values. This gets you partial marks even if the final answer is wrong.

**Character Count**: 1400+
"""
            },
            {
                "title": "Exam Preparation and Practice Questions",
                "content": f"""# Exam Preparation Guide - {subject.get('name', 'Subject')}

## Complete Revision Strategy
Last-minute preparation requires smart work, not just hard work. Follow this proven strategy used by AHSEC toppers.

## Week-wise Plan (4 Weeks Before Exam)

### Week 1: Concepts Revision
- Read all chapters once quickly
- Make short notes of important points
- List all formulas in one place
- Identify weak topics for extra focus

### Week 2: Problem Practice
- Solve 10 numericals daily
- Focus on previous year questions (PYQs)
- Time yourself while solving
- Review mistakes and redo wrong problems

### Week 3: Deep Dive Weak Areas
- Spend 70% time on difficult topics
- Watch video explanations if concepts unclear
- Discuss with teachers/peers
- Practice derivations thoroughly

### Week 4: Final Revision
- Revise notes daily
- Solve sample papers under exam conditions
- Don't start new topics
- Focus on high-weightage chapters

## Important Formulas
(This section would list 10-15 key formulas with explanations)

## Previous Year Questions (PYQs)

**2024 Question**: [Sample question text here]
**Answer**: Detailed step-by-step solution with explanation.

**2023 Question**: [Another sample question]
**Answer**: Complete solution with diagrams if needed.

**2022 Question**: [Third sample question]
**Answer**: Answer with exam tips included.

## Common Mistakes to Avoid
1. Not reading questions carefully
2. Skipping steps in derivations
3. Forgetting units in numerical answers
4. Poor time management
5. Leaving questions unattempted

## Exam Day Tips
- Reach 30 minutes early
- Read paper completely in first 15 minutes
- Start with questions you're most confident about
- Allocate time per question based on marks
- Reserve last 15 minutes for review

## Mark Distribution Strategy
- 1-mark questions: 30 seconds each
- 2-mark questions: 2 minutes each
- 3-mark questions: 4 minutes each
- 5-mark questions: 7-8 minutes each

**Final Tip**: Stay calm, attempt all questions, neat handwriting gets extra marks!

**Character Count**: 1600+
"""
            }
        ]
        
        for i, chapter_data in enumerate(chapters_data, 1):
            chapter_id = str(uuid.uuid4())
            chapter = {
                "id": chapter_id,
                "subject_id": subject["id"],
                "title": chapter_data["title"],
                "description": f"Chapter {i} - Essential concepts and exam preparation",
                "content": chapter_data["content"],
                "order": i,
                "status": "published",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.chapters.insert_one(chapter)
            seeded_count += 1
        
        # Mark subject as having content
        await db.subjects.update_one(
            {"id": subject["id"]},
            {"$set": {"has_document": True, "chapter_count": 3}}
        )
    
    logger.info(f"Content reset and seeded: {seeded_count} chapters across {len(subjects)} subjects")
    return {"message": f"Reset complete! Seeded {seeded_count} chapters with 1000+ chars each", "chapters": seeded_count}


@api.post("/admin/content/uploads/manual")
async def create_content_manual(data: dict, admin: dict = Depends(get_admin_user)):
    """Create content manually (not file upload)"""
    content_id = str(uuid.uuid4())
    
    content_data = {
        "id": content_id,
        "subject_id": data.get("subject_id"),
        "content_type": data.get("content_type", "chapter"),
        "title": data.get("title"),
        "description": data.get("description", ""),
        "content": data.get("content", ""),
        "tags": data.get("tags", ""),
        "year": data.get("year", ""),
        "exam_type": data.get("exam_type", ""),
        "category": data.get("category", ""),
        "order": data.get("order", 1),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": admin.get("email"),
        "status": data.get("status", "published"),
    }
    
    await db.content_uploads.insert_one(content_data)
    content_data.pop("_id", None)
    return content_data

@api.get("/admin/content/uploads")
async def get_content_uploads(
    subject_id: str = None,
    type: str = None,
    admin: dict = Depends(get_admin_user)
):
    """Get uploaded content filtered by subject and type"""
    try:
        if not await is_mongo_available():
            return []
        query = {}
        if subject_id:
            query["subject_id"] = subject_id
        if type:
            query["content_type"] = type
        
        uploads = await db.content_uploads.find(query, {"_id": 0}).sort("uploaded_at", -1).limit(100).to_list(100)
        return uploads
    except Exception:
        mark_mongo_down()
        return []

@api.delete("/admin/content/uploads/{content_id}")
async def delete_content_upload(content_id: str, admin: dict = Depends(get_admin_user)):
    """Delete uploaded content"""
    result = await db.content_uploads.delete_one({"id": content_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Content not found")
    return {"message": "Content deleted"}


@api.patch("/admin/content/chapters/{chapter_id}")
async def admin_update_chapter(chapter_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    """Update existing chapter - auto-rechunks if content changed"""
    allowed = {k: v for k, v in data.items() if k in ["title", "slug", "description", "content", "content_type", "order", "status", "attached_files"]}
    if "slug" in allowed:
        allowed["slug"] = re.sub(r'[^a-z0-9]+', '-', (allowed["slug"] or "").lower()).strip('-')
    if "title" in allowed and not allowed.get("slug"):
        allowed["slug"] = re.sub(r'[^a-z0-9]+', '-', allowed["title"].lower()).strip('-')
    if allowed.get("slug"):
        chapter = await db.chapters.find_one({"id": chapter_id}, {"subject_id": 1})
        if chapter:
            dup = await db.chapters.find_one({"subject_id": chapter["subject_id"], "slug": allowed["slug"], "id": {"$ne": chapter_id}})
            if dup:
                allowed["slug"] = f"{allowed['slug']}-{chapter_id[:6]}"
    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Check if content is being updated
    content_updated = "content" in allowed and allowed["content"]
    
    result = await db.chapters.update_one({"id": chapter_id}, {"$set": allowed})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # 🆕 AUTO RE-CHUNK if content was updated
    chunks_info = {}
    if content_updated:
        try:
            rechunk_result = await rechunk_chapter(chapter_id)
            chunks_info = {
                "chunks_deleted": rechunk_result["chunks_deleted"],
                "chunks_created": rechunk_result["chunks_created"]
            }
            logger.info(f"✅ Re-chunked updated chapter {chapter_id}: {chunks_info}")
        except Exception as chunk_error:
            logger.error(f"❌ Re-chunking failed for chapter {chapter_id}: {chunk_error}")
            chunks_info = {"error": str(chunk_error)}
    
    _invalidate_content_cache("chapters")
    _invalidate_content_cache("subjects")
    return {"message": "Chapter updated", **chunks_info}

@api.post("/admin/content/chapters/{chapter_id}/generate-notes")
async def admin_generate_chapter_notes(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """
    Use AI to generate topic-wise summary notes for a chapter.
    Reads: title, description, topics from the chapter + subject context.
    Writes rich markdown notes back to chapter.content and re-chunks.
    """
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    subject = await db.subjects.find_one({"id": chapter.get("subject_id", "")}, {"_id": 0}) or {}
    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")

    title       = chapter.get("title", "").strip()
    description = (chapter.get("description") or "").strip()
    topics      = chapter.get("topics") or []

    if not title:
        raise HTTPException(status_code=400, detail="Chapter has no title")
    if not description and not topics:
        raise HTTPException(
            status_code=422,
            detail="Add a description (or syllabus topics) to this chapter before generating notes."
        )

    # ── Fetch SEO topics for this chapter as keyword seeds ───────────────────
    seo_topic_docs = await db.seo_topics.find(
        {"linked_chapter_id": chapter_id},
        {"_id": 0, "topic": 1, "primary_keyword": 1}
    ).to_list(30)
    seo_keywords = list(dict.fromkeys(
        (d.get("primary_keyword") or d.get("topic") or "").strip()
        for d in seo_topic_docs
        if (d.get("primary_keyword") or d.get("topic") or "").strip()
    ))

    # Build the educational prompt
    topic_block = ""
    if topics:
        topic_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
    else:
        topic_block = f"  {description}"

    seo_seed_block = ""
    if seo_keywords:
        seo_seed_block = (
            "\n\n**SEO Keyword Seeds (naturally weave these phrases into headings and body):**\n"
            + "\n".join(f"  - {kw}" for kw in seo_keywords[:15])
        )

    prompt = f"""You are an expert academic content writer for Indian university degree students (NEP/FYUGP curriculum).

Generate **detailed, topic-wise summary notes** for the following chapter. These notes will be the primary study material for students.

**Chapter:** {title}
**Subject:** {subject_name or "Degree Course"} ({(paper_type or "").upper()} — {class_name or "FYUGP"})
**Description:** {description or "No additional description provided."}

**Syllabus Topics to cover:**
{topic_block}{seo_seed_block}

---

**INSTRUCTIONS:**
- Write a brief **introduction** (2-3 sentences) about the chapter as a whole.
- For EACH topic listed above, write a dedicated section with:
  - A clear **heading** (use ## for the topic name)
  - A concise explanation of the topic (3-6 sentences) in simple academic language
  - **Key Points** in bullet form (4-6 bullets) covering definitions, significance, and important facts
  - Use **bold** to highlight key terms/definitions
- If SEO keyword seeds are provided, naturally incorporate them in headings and body text.
- End with a brief **Summary** section recapping the chapter's main takeaways.
- Use markdown formatting (##, ###, **, -, etc.)
- Write for degree-level students — clear, precise, and educational
- Do NOT add any disclaimers or preamble. Start directly with the introduction.
- Target length: ~400-700 words total across all topics.
"""

    try:
        generated = await call_llm_api(
            [{"role": "user", "content": prompt}],
            max_tokens=2048
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {e}")

    if not generated or len(generated.strip()) < 50:
        raise HTTPException(status_code=502, detail="AI returned empty or too-short content")

    # Save generated notes
    await db.chapters.update_one(
        {"id": chapter_id},
        {"$set": {
            "content":      generated.strip(),
            "content_type": "notes",
            "notes_generated": True,
            "notes_generated_at": datetime.now(timezone.utc).isoformat(),
        }}
    )
    _invalidate_content_cache("chapters")

    # Re-chunk for RAG search
    try:
        await auto_chunk_content(chapter_id=chapter_id, content=generated.strip(), subject_id=chapter.get("subject_id"))
    except Exception:
        pass

    return {
        "chapter_id": chapter_id,
        "title": title,
        "content": generated.strip(),
        "word_count": len(generated.split()),
        "message": "Notes generated successfully",
    }


class BulkNotesRequest(BaseModel):
    skip_existing: bool = False

@api.post("/admin/subjects/{subject_id}/generate-notes-bulk")
async def admin_generate_subject_notes_bulk(subject_id: str, body: BulkNotesRequest = Body(default=None), admin: dict = Depends(get_admin_user)):
    """
    Generate AI topic-wise notes for ALL chapters of a subject.
    Pass skip_existing=true to skip chapters that already have notes (>50 words).
    Runs sequentially to avoid rate-limiting. Returns per-chapter results.
    """
    skip_existing = (body.skip_existing if body else False)
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "message": "No chapters found"}

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")

    results = []
    skipped_count = 0
    for chapter in chapters:
        chapter_id  = chapter.get("id", "")
        title       = (chapter.get("title") or "").strip()
        description = (chapter.get("description") or "").strip()
        topics      = chapter.get("topics") or []

        if not title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue

        # Build topic block — prefer topics list > description > existing content
        existing_content = (chapter.get("content") or "").strip()

        # ── skip_existing: skip chapters that already have sufficient notes ────
        if skip_existing and len(existing_content.split()) > 50:
            results.append({"chapter_id": chapter_id, "title": title, "status": "skipped", "reason": "notes exist"})
            skipped_count += 1
            continue

        if topics:
            topic_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
        elif description:
            topic_block = f"  {description}"
        elif existing_content:
            topic_block = existing_content[:400]
        else:
            results.append({"chapter_id": chapter_id, "title": title, "status": "skipped", "reason": "no description, topics, or content"})
            continue

        prompt = f"""You are an expert academic content writer for Indian university degree students (NEP/FYUGP curriculum).

Generate **detailed, topic-wise summary notes** for the following chapter. These notes will be the primary study material for students.

**Chapter:** {title}
**Subject:** {subject_name or "Degree Course"} ({(paper_type or "").upper()} — {class_name or "FYUGP"})
**Description:** {description or "No additional description provided."}

**Syllabus Topics to cover:**
{topic_block}

---

**INSTRUCTIONS:**
- Write a brief **introduction** (2-3 sentences) about the chapter.
- For EACH topic listed, write:
  - A **## Heading** for the topic
  - 3-5 sentence explanation in simple academic language
  - **Key Points** in 4-6 bullets with definitions/significance/**bold key terms**
- End with a **Summary** section.
- Use markdown. Do NOT add disclaimers. Start directly with the introduction.
- Target: ~400-700 words.
"""
        try:
            generated = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=2048)
            if generated and len(generated.strip()) > 50:
                await db.chapters.update_one(
                    {"id": chapter_id},
                    {"$set": {
                        "content": generated.strip(),
                        "content_type": "notes",
                        "notes_generated": True,
                        "notes_generated_at": datetime.now(timezone.utc).isoformat(),
                    }}
                )
                try:
                    await auto_chunk_content(chapter_id=chapter_id, content=generated.strip(), subject_id=subject_id)
                except Exception:
                    pass
                results.append({"chapter_id": chapter_id, "title": title, "status": "ok", "word_count": len(generated.split())})
            else:
                results.append({"chapter_id": chapter_id, "title": title, "status": "error", "reason": "empty response"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": title, "status": "error", "reason": str(e)})

    _invalidate_content_cache("chapters")
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    return {
        "subject_id": subject_id,
        "subject_name": subject_name,
        "total": len(chapters),
        "generated": ok_count,
        "skipped": skipped_count,
        "results": results,
    }


@api.post("/admin/subjects/{subject_id}/sync-content-bulk")
async def admin_sync_content_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Final pipeline step: for each chapter, embed all generated assets
    (mark-wise questions + memory-trick flashcards) back into the chapter document.
    Sets has_important_questions, has_flashcards, mark_wise_questions, flashcard_summary,
    and content_synced_at on each chapter.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "synced": 0, "total": 0, "results": []}

    now_iso = datetime.now(timezone.utc).isoformat()
    results = []

    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue

        update_fields: dict = {"content_synced_at": now_iso}

        # Load mark-wise questions for this chapter
        q_doc = await db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0})
        if q_doc:
            update_fields["has_important_questions"] = True
            update_fields["questions_synced"]        = True
            update_fields["mark_wise_questions"]     = q_doc.get("mark_wise", {})
            update_fields["important_questions"]     = q_doc.get("pyqs", [])

        # Load memory-trick flashcards for this chapter
        fc_doc = await db.flashcard_collections.find_one(
            {"chapter_id": chapter_id, "pipeline_generated": True}, {"_id": 0}
        )
        if fc_doc:
            update_fields["has_flashcards"]    = True
            update_fields["flashcards_synced"] = True
            # Embed the full flashcard list into the chapter document
            update_fields["memory_tricks"]     = fc_doc.get("flashcards", [])

        await db.chapters.update_one(
            {"id": chapter_id},
            {"$set": update_fields},
        )

        results.append({
            "chapter_id":   chapter_id,
            "title":        chapter_title,
            "status":       "ok",
            "has_questions": bool(q_doc),
            "has_flashcards": bool(fc_doc),
        })

    synced = sum(1 for r in results if r.get("status") == "ok")
    _invalidate_content_cache("chapters")
    return {
        "subject_id": subject_id,
        "synced":     synced,
        "total":      len(chapters),
        "results":    results,
    }


# ── Subject-scoped content pipeline: notes → questions → flashcards → sync ──

_subject_pipeline_jobs: dict = {}


def _subject_pipeline_job_gc():
    """Remove jobs older than 2 hours."""
    cutoff = datetime.now(timezone.utc).timestamp() - 7200
    stale = [k for k, v in _subject_pipeline_jobs.items() if v.get("started_at", 0) < cutoff]
    for k in stale:
        _subject_pipeline_jobs.pop(k, None)


async def _run_subject_content_pipeline(job_id: str, subject_id: str):
    """
    Sequential background worker: for each chapter in order,
    check notes_generated flag (skip if True), then generate notes → mark-wise
    questions → flashcards → sync back onto the chapter document.
    Updates _subject_pipeline_jobs[job_id] with per-chapter progress.
    """
    import re as _re

    def _update_job(**kwargs):
        if job_id in _subject_pipeline_jobs:
            _subject_pipeline_jobs[job_id].update(kwargs)

    try:
        subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
        if not subject:
            _update_job(status="error", message="Subject not found", progress=100,
                        finished_at=datetime.now(timezone.utc).isoformat())
            return

        subject_name = subject.get("name", "")
        class_name   = subject.get("className", "")
        paper_type   = (subject.get("paper_type") or "").upper()

        chapters = await db.chapters.find(
            {"subject_id": subject_id}, {"_id": 0}
        ).sort("order_index", 1).to_list(100)

        total = len(chapters)
        if not total:
            _update_job(status="complete", progress=100, message="No chapters found",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        chapter_results=[])
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        chapter_results = []

        for idx, chapter in enumerate(chapters):
            chapter_id    = chapter.get("id", "")
            chapter_title = (chapter.get("title") or "").strip()
            pct = int(5 + (idx / total) * 88)
            _update_job(progress=pct, message=f"Processing chapter {idx + 1}/{total}: {chapter_title[:40]}")

            if not chapter_title:
                chapter_results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
                continue

            cr: dict = {"chapter_id": chapter_id, "chapter_title": chapter_title,
                        "notes": None, "questions": None, "flashcards": None, "sync": None}

            # ── Step 1: Notes (skip entire chapter if notes_generated=True) ────
            if chapter.get("notes_generated") is True:
                cr["notes"] = "skipped_existing"
                cr["questions"] = "skipped_existing"
                cr["flashcards"] = "skipped_existing"
                cr["sync"] = "skipped_existing"
                chapter_results.append(cr)
                continue
            else:
                try:
                    generated = await _pipeline_generate_chapter_notes(chapter, subject_name, class_name, paper_type)
                    if generated and len(generated.strip()) > 50:
                        await db.chapters.update_one(
                            {"id": chapter_id},
                            {"$set": {
                                "content": generated.strip(),
                                "content_type": "notes",
                                "notes_generated": True,
                                "notes_generated_at": now_iso,
                            }}
                        )
                        try:
                            await auto_chunk_content(chapter_id=chapter_id, content=generated.strip(), subject_id=subject_id)
                        except Exception:
                            pass
                        notes_content = generated.strip()
                        cr["notes"] = "generated"
                    else:
                        notes_content = (chapter.get("content") or "").strip()
                        cr["notes"] = "skipped_empty"
                except Exception as e:
                    notes_content = (chapter.get("content") or "").strip()
                    cr["notes"] = f"error: {str(e)[:60]}"

            if len(notes_content) < 100:
                cr["questions"] = "skipped_no_content"
                cr["flashcards"] = "skipped_no_content"
                cr["sync"] = "skipped"
                chapter_results.append(cr)
                continue

            # ── Step 2: Mark-wise important questions ──────────────────────────
            try:
                topics     = chapter.get("topics") or []
                description = (chapter.get("description") or "").strip()
                topic_block = ", ".join(str(t) for t in topics[:15]) if topics else (description[:200] if description else chapter_title)
                generate_prompt = f"""You are an expert exam question setter for {class_name} {subject_name}.

Generate the MOST IMPORTANT exam questions for the chapter below, organised strictly by mark weight.

Chapter: {chapter_title}
Topics: {topic_block}

Return ONLY valid JSON in this exact schema (no markdown, no explanation):
{{
  "1_mark": [{{"question": "...", "type": "MCQ/very_short_answer"}},{{"question": "...", "type": "MCQ/very_short_answer"}},{{"question": "...", "type": "MCQ/very_short_answer"}}],
  "2_mark": [{{"question": "...", "type": "short_answer"}},{{"question": "...", "type": "short_answer"}},{{"question": "...", "type": "short_answer"}}],
  "3_mark": [{{"question": "...", "type": "brief_answer"}},{{"question": "...", "type": "brief_answer"}},{{"question": "...", "type": "brief_answer"}}],
  "5_mark": [{{"question": "...", "type": "medium_answer"}},{{"question": "...", "type": "medium_answer"}},{{"question": "...", "type": "medium_answer"}}],
  "10_mark": [{{"question": "...", "type": "long_answer/essay"}},{{"question": "...", "type": "long_answer/essay"}},{{"question": "...", "type": "long_answer/essay"}}]
}}
Rules: 3 questions per mark bucket, total 15 questions. Specific to "{chapter_title}". Pure JSON only."""
                raw_resp = await call_llm_api([{"role": "user", "content": generate_prompt}], max_tokens=1600)
                json_match = _re.search(r'\{[\s\S]*\}', raw_resp or "")
                if json_match:
                    parsed = json.loads(json_match.group())
                    mark_wise = {
                        "1":  parsed.get("1_mark",  []),
                        "2":  parsed.get("2_mark",  []),
                        "3":  parsed.get("3_mark",  []),
                        "5":  parsed.get("5_mark",  []),
                        "10": parsed.get("10_mark", []),
                    }
                    flat_questions = []
                    for marks_str, qs in mark_wise.items():
                        for q_obj in qs:
                            text = (q_obj.get("question") if isinstance(q_obj, dict) else str(q_obj)).strip()
                            if text:
                                flat_questions.append({
                                    "question":   text,
                                    "marks":      int(marks_str),
                                    "type":       q_obj.get("type", "") if isinstance(q_obj, dict) else "",
                                    "year":       0,
                                    "paper_type": paper_type,
                                    "source":     "ai_generated",
                                })
                    if flat_questions:
                        pyq_doc = {
                            "id": str(uuid.uuid4()),
                            "subject_id": subject_id, "subject_name": subject_name,
                            "chapter_id": chapter_id, "chapter_title": chapter_title,
                            "pyqs": flat_questions,
                            "mark_wise": {k: [
                                (q.get("question", q) if isinstance(q, dict) else q) for q in v
                            ] for k, v in mark_wise.items()},
                            "total": len(flat_questions),
                            "source": "ai_important_questions", "ai_generated": True,
                            "created_at": now_iso, "updated_at": now_iso,
                        }
                        await db.ai_pyq_collections.update_one(
                            {"chapter_id": chapter_id}, {"$set": pyq_doc}, upsert=True,
                        )
                        cr["questions"] = f"generated:{len(flat_questions)}"
                    else:
                        cr["questions"] = "empty"
                else:
                    cr["questions"] = "no_json"
            except Exception as e:
                cr["questions"] = f"error: {str(e)[:60]}"

            # ── Step 3: Memory-trick flashcards ────────────────────────────────
            try:
                flashcards = await _pipeline_generate_flashcards(notes_content, subject_name, chapter_title, class_name, count=25)
                if flashcards:
                    fc_doc = {
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id, "subject_name": subject_name,
                        "chapter_id": chapter_id, "chapter_title": chapter_title,
                        "flashcards": flashcards, "total": len(flashcards),
                        "pipeline_generated": True, "created_at": now_iso,
                    }
                    await db.flashcard_collections.update_one(
                        {"chapter_id": chapter_id, "pipeline_generated": True},
                        {"$set": fc_doc}, upsert=True,
                    )
                    cr["flashcards"] = f"generated:{len(flashcards)}"
                else:
                    cr["flashcards"] = "empty"
            except Exception as e:
                cr["flashcards"] = f"error: {str(e)[:60]}"

            # ── Step 4: Sync generated assets back onto chapter document ───────
            try:
                update_fields: dict = {"content_synced_at": now_iso}
                q_doc  = await db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0})
                fc_doc = await db.flashcard_collections.find_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True}, {"_id": 0}
                )
                if q_doc:
                    update_fields["has_important_questions"] = True
                    update_fields["questions_synced"]        = True
                    update_fields["mark_wise_questions"]     = q_doc.get("mark_wise", {})
                    update_fields["important_questions"]     = q_doc.get("pyqs", [])
                if fc_doc:
                    update_fields["has_flashcards"]    = True
                    update_fields["flashcards_synced"] = True
                    update_fields["memory_tricks"]     = fc_doc.get("flashcards", [])
                await db.chapters.update_one({"id": chapter_id}, {"$set": update_fields})
                cr["sync"] = "ok"
                _invalidate_content_cache("chapters")
            except Exception as e:
                cr["sync"] = f"error: {str(e)[:60]}"

            chapter_results.append(cr)

        _update_job(
            status="complete", progress=100,
            message=f"Pipeline complete: {total} chapters processed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            chapter_results=chapter_results,
        )

    except Exception as exc:
        _subject_pipeline_jobs.get(job_id, {}).update({
            "status": "error", "progress": 100,
            "message": str(exc)[:200],
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.error(f"Subject pipeline job {job_id} failed: {exc}")
    finally:
        _subject_pipeline_job_gc()


@api.post("/admin/subjects/{subject_id}/run-content-pipeline")
async def admin_run_content_pipeline(
    subject_id: str,
    background_tasks: BackgroundTasks,
    admin: dict = Depends(get_admin_user),
):
    """
    Agentic content pipeline: iterates chapters in order, skips any chapter
    where notes_generated=True, then runs notes → mark-wise questions (1/2/3/5/10)
    → memory-trick flashcards → sync back to chapter document — all in one
    sequential background job. Returns job_id immediately; poll status endpoint.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    job_id = str(uuid.uuid4())
    _subject_pipeline_jobs[job_id] = {
        "job_id":       job_id,
        "subject_id":   subject_id,
        "subject_name": subject.get("name", ""),
        "status":       "running",
        "progress":     0,
        "message":      "Pipeline starting…",
        "chapter_results": [],
        "started_at":   datetime.now(timezone.utc).timestamp(),
    }
    background_tasks.add_task(_run_subject_content_pipeline, job_id, subject_id)
    return {"job_id": job_id, "status": "running", "subject_id": subject_id}


@api.get("/admin/subjects/{subject_id}/content-pipeline-status")
async def admin_content_pipeline_status(
    subject_id: str,
    job_id: str,
    admin: dict = Depends(get_admin_user),
):
    """
    Poll the status of a run-content-pipeline background job.
    Returns per-chapter progress and final results when complete.
    """
    job = _subject_pipeline_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired (jobs expire after 2 hours)")
    if job.get("subject_id") != subject_id:
        raise HTTPException(status_code=403, detail="Job does not belong to this subject")
    return job


@api.post("/admin/subjects/{subject_id}/generate-mcqs-bulk")
async def admin_generate_mcqs_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Generate MCQs for ALL chapters of a subject using existing pipeline helper.
    Runs sequentially. Upserts to mcq_collections. Returns per-chapter results.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "total": 0, "generated": 0}

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")
    now_iso      = datetime.now(timezone.utc).isoformat()

    results = []
    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        content       = (chapter.get("content") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue
        if len(content) < 100:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "skipped", "reason": "content too short"})
            continue

        try:
            mcqs = await _pipeline_generate_mcqs(content, subject_name, chapter_title, class_name, count=20)
            if mcqs:
                mcq_doc = {
                    "id": str(uuid.uuid4()),
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "mcqs": mcqs,
                    "total": len(mcqs),
                    "pipeline_generated": True,
                    "created_at": now_iso,
                }
                await db.mcq_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": mcq_doc},
                    upsert=True,
                )
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "ok", "count": len(mcqs)})
            else:
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": "empty response"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": str(e)[:80]})

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    total_mcqs = sum(r.get("count", 0) for r in results)
    return {
        "subject_id": subject_id,
        "subject_name": subject_name,
        "total": len(chapters),
        "generated": ok_count,
        "total_mcqs": total_mcqs,
        "results": results,
    }


@api.post("/admin/subjects/{subject_id}/generate-flashcards-bulk")
async def admin_generate_flashcards_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Generate flashcards for ALL chapters of a subject using existing pipeline helper.
    Runs sequentially. Upserts to flashcard_collections. Returns per-chapter results.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "total": 0, "generated": 0}

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")
    now_iso      = datetime.now(timezone.utc).isoformat()

    results = []
    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        content       = (chapter.get("content") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue
        if len(content) < 100:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "skipped", "reason": "content too short"})
            continue

        try:
            flashcards = await _pipeline_generate_flashcards(content, subject_name, chapter_title, class_name, count=25)
            if flashcards:
                fc_doc = {
                    "id": str(uuid.uuid4()),
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "flashcards": flashcards,
                    "total": len(flashcards),
                    "pipeline_generated": True,
                    "created_at": now_iso,
                }
                await db.flashcard_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": fc_doc},
                    upsert=True,
                )
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "ok", "count": len(flashcards)})
            else:
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": "empty response"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": str(e)[:80]})

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    total_flashcards = sum(r.get("count", 0) for r in results)
    return {
        "subject_id": subject_id,
        "subject_name": subject_name,
        "total": len(chapters),
        "generated": ok_count,
        "total_flashcards": total_flashcards,
        "results": results,
    }


async def _gemini_web_search_pyqs(
    subject_name: str,
    class_name: str,
    paper_type: str,
    gemini_key: str,
) -> list:
    """
    Use Gemini with Google Search grounding to retrieve real PYQs from the web.
    Returns a flat list of {text, marks, year, sub_parts, source} dicts.
    """
    import re as _re

    if not gemini_key:
        return []

    search_prompt = (
        f"Search the web and find REAL previous year exam questions for:\n"
        f"Subject: {subject_name}\n"
        f"Class / Level: {class_name or 'Degree'} ({paper_type or 'Major'} paper)\n"
        f"Board / University: AHSEC / SEBA / Gauhati University / Dibrugarh University (Assam)\n\n"
        f"Collect as many actual board exam questions as you can find from years 2015–2024.\n"
        f"Return ONLY a JSON array — no markdown fences, no explanation:\n"
        f'[{{"question":"...", "year":2022, "marks":5}}, ...]\n'
        f"year must be an integer. marks must be an integer (use 0 if unknown).\n"
        f"Include ONLY real questions from actual exam papers, not practice questions or study notes."
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={gemini_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": search_prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 4000, "temperature": 0.1},
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Extract text from Gemini response
        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    text += part["text"]

        if not text.strip():
            return []

        # Find a JSON array in the response
        arr_match = _re.search(r'\[[\s\S]*\]', text)
        if not arr_match:
            return []

        raw_list = json.loads(arr_match.group())
        if not isinstance(raw_list, list):
            return []

        cleaned = []
        for q in raw_list:
            if not isinstance(q, dict):
                continue
            text_val = (q.get("question") or q.get("text") or "").strip()
            if not text_val:
                continue
            year_val = q.get("year", 0)
            if not isinstance(year_val, int) or not (2010 <= year_val <= 2025):
                year_val = 0
            marks_val = q.get("marks", 0)
            try:
                marks_val = int(marks_val)
            except (TypeError, ValueError):
                marks_val = 0
            cleaned.append({
                "text":       text_val,
                "marks":      str(marks_val) if marks_val else "",
                "year":       year_val,
                "sub_parts":  [],
                "source":     "web_search",
            })
        return cleaned

    except Exception as exc:
        logger.warning(f"Gemini web search PYQ failed: {exc}")
        return []


@api.post("/admin/subjects/{subject_id}/generate-pyqs-bulk")
async def admin_generate_pyqs_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Mark-wise Most Important Questions Generator.

    Workflow:
      1. [OPTIONAL] Gemini Google Search grounding → collect real past questions as reference.
      2. [OPTIONAL] pyq_html_pages → questions from locally uploaded PDFs as reference.
      3. Merge reference pool (web first).
      4. Per chapter: AI generates 3×1M + 3×2M + 3×5M + 3×10M most important questions,
         inspired by real PYQ pool (if any) but always generating chapter-specific questions.
      5. Upsert per-chapter results into ai_pyq_collections with mark_wise structure.
    """
    import re as _re

    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "total": 0, "generated": 0,
                "total_pyqs": 0, "message": "No chapters found"}

    subject_name = subject.get("name", "")
    class_name   = subject.get("className", "")
    paper_type   = (subject.get("paper_type") or "").upper()
    now_iso      = datetime.now(timezone.utc).isoformat()

    # ── Step 1 [PRIORITY]: Web search via Gemini Google Search grounding ──────
    web_questions = await _gemini_web_search_pyqs(
        subject_name=subject_name,
        class_name=class_name,
        paper_type=paper_type,
        gemini_key=_GEMINI_KEY,
    )
    logger.info(f"PYQ web search for '{subject_name}': {len(web_questions)} questions found")

    # ── Step 2 [SUPPLEMENT]: Collect questions from locally uploaded papers ────
    local_questions = []

    # Primary: match by subject_id stored on pyq_html_pages
    html_pages = await db.pyq_html_pages.find(
        {"subject_id": subject_id},
        {"_id": 0, "questions": 1, "raw_text": 1, "exam_year": 1, "paper_type": 1, "subject_name": 1, "slug": 1}
    ).sort("exam_year", -1).to_list(50)

    # Fallback: keyword match on subject_name
    if not html_pages and subject_name:
        kw = _re.escape(subject_name.split()[0])
        html_pages = await db.pyq_html_pages.find(
            {"subject_name": {"$regex": kw, "$options": "i"}},
            {"_id": 0, "questions": 1, "raw_text": 1, "exam_year": 1,
             "paper_type": 1, "subject_name": 1, "slug": 1}
        ).sort("exam_year", -1).to_list(50)

    # Fallback 2: look in pyq_uploads for slugs → html_pages
    if not html_pages:
        upload_docs = await db.pyq_uploads.find(
            {"subject_id": subject_id}, {"_id": 0, "slug": 1}
        ).to_list(50)
        slugs = [u["slug"] for u in upload_docs if u.get("slug")]
        if slugs:
            html_pages = await db.pyq_html_pages.find(
                {"slug": {"$in": slugs}},
                {"_id": 0, "questions": 1, "raw_text": 1, "exam_year": 1,
                 "paper_type": 1, "subject_name": 1, "slug": 1}
            ).to_list(50)

    for page in html_pages:
        year  = int(page.get("exam_year") or 0)
        ptype = page.get("paper_type", "")
        for q in (page.get("questions") or []):
            text = (q.get("text") or q.get("question_text") or q.get("q") or "").strip()
            if text:
                local_questions.append({
                    "text":       text,
                    "marks":      str(q.get("marks") or ""),
                    "year":       year,
                    "paper_type": ptype,
                    "sub_parts":  q.get("sub_parts") or [],
                    "source":     "uploaded_paper",
                })
    logger.info(f"PYQ local papers for '{subject_name}': {len(local_questions)} questions from {len(html_pages)} papers")

    # ── Step 3: Merge pools (web first = priority) ────────────────────────────
    # De-duplicate by question text (first 80 chars)
    seen_texts: set = set()
    question_pool = []
    for q in web_questions + local_questions:
        fingerprint = q["text"][:80].lower().strip()
        if fingerprint not in seen_texts:
            seen_texts.add(fingerprint)
            question_pool.append({**q, "idx": len(question_pool)})

    # pool_text helper kept for potential future use (not used in mark-wise generation)
    def _pool_text(pool):
        lines = []
        for q in pool:
            marks_str = f" [{q['marks']} marks]" if q["marks"] else ""
            year_str  = f" [{q['year']}]" if q["year"] else ""
            text_trunc = q["text"][:200]
            lines.append(f"{q['idx']}. {text_trunc}{marks_str}{year_str}")
        return "\n".join(lines)

    # ── Step 3: Per-chapter mark-wise important question generation ───────────
    # Build a reference pool snippet (first 60 real questions) to inspire AI
    pool_snippet = ""
    if question_pool:
        sample = question_pool[:60]
        pool_snippet = "\n".join(
            f"- {q['text'][:180]}" + (f" [{q['marks']}M]" if q.get("marks") else "")
            for q in sample
        )

    results = []
    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        topics        = chapter.get("topics") or []
        description   = (chapter.get("description") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue

        topic_block = ""
        if topics:
            topic_block = ", ".join(str(t) for t in topics[:15])
        elif description:
            topic_block = description[:200]
        else:
            topic_block = chapter_title

        pool_ref = f"\n\nReference questions from past papers (use as inspiration, do NOT copy verbatim):\n{pool_snippet}" if pool_snippet else ""

        generate_prompt = f"""You are an expert exam question setter for {class_name} {subject_name}.

Generate the MOST IMPORTANT exam questions for the chapter below, organised strictly by mark weight.
These should be high-probability questions a student must prepare.

Chapter: {chapter_title}
Topics: {topic_block}{pool_ref}

Return ONLY valid JSON in this exact schema (no markdown, no explanation):
{{
  "1_mark": [
    {{"question": "...", "type": "MCQ/very_short_answer"}},
    {{"question": "...", "type": "MCQ/very_short_answer"}},
    {{"question": "...", "type": "MCQ/very_short_answer"}}
  ],
  "2_mark": [
    {{"question": "...", "type": "short_answer"}},
    {{"question": "...", "type": "short_answer"}},
    {{"question": "...", "type": "short_answer"}}
  ],
  "3_mark": [
    {{"question": "...", "type": "brief_answer"}},
    {{"question": "...", "type": "brief_answer"}},
    {{"question": "...", "type": "brief_answer"}}
  ],
  "5_mark": [
    {{"question": "...", "type": "medium_answer"}},
    {{"question": "...", "type": "medium_answer"}},
    {{"question": "...", "type": "medium_answer"}}
  ],
  "10_mark": [
    {{"question": "...", "type": "long_answer/essay"}},
    {{"question": "...", "type": "long_answer/essay"}},
    {{"question": "...", "type": "long_answer/essay"}}
  ]
}}

Rules:
- 1-mark: MCQ options OR one-word/one-line answers
- 2-mark: short answers (2–3 sentences)
- 3-mark: brief answers with 3 clear points (1 mark each)
- 5-mark: medium answers with points/explanation
- 10-mark: detailed essay or long-answer questions
- Questions must be specific to "{chapter_title}", not generic
- Exactly 3 questions per mark bucket, total 15 questions
- Pure JSON only, no markdown fences"""

        try:
            raw_resp = await call_llm_api(
                [{"role": "user", "content": generate_prompt}],
                max_tokens=1600,
            )
            if not raw_resp:
                results.append({"chapter_id": chapter_id, "title": chapter_title,
                                 "status": "skipped", "reason": "empty generator response"})
                continue

            # Extract JSON object from response
            json_match = _re.search(r'\{[\s\S]*\}', raw_resp)
            if not json_match:
                results.append({"chapter_id": chapter_id, "title": chapter_title,
                                 "status": "skipped", "reason": "no JSON object returned"})
                continue

            parsed = json.loads(json_match.group())

            # Flatten into a flat list with marks field (backward-compatible with LearnPage)
            mark_wise = {
                "1":  parsed.get("1_mark",  []),
                "2":  parsed.get("2_mark",  []),
                "3":  parsed.get("3_mark",  []),
                "5":  parsed.get("5_mark",  []),
                "10": parsed.get("10_mark", []),
            }
            flat_questions = []
            for marks_str, qs in mark_wise.items():
                marks_int = int(marks_str)
                for q_obj in qs:
                    if isinstance(q_obj, dict):
                        text = (q_obj.get("question") or "").strip()
                    else:
                        text = str(q_obj).strip()
                    if text:
                        flat_questions.append({
                            "question":   text,
                            "marks":      marks_int,
                            "type":       q_obj.get("type", "") if isinstance(q_obj, dict) else "",
                            "year":       0,
                            "paper_type": paper_type,
                            "sub_parts":  [],
                            "source":     "ai_generated",
                        })

            if not flat_questions:
                results.append({"chapter_id": chapter_id, "title": chapter_title,
                                 "status": "skipped", "reason": "no questions generated"})
                continue

            pyq_doc = {
                "id":            str(uuid.uuid4()),
                "subject_id":    subject_id,
                "subject_name":  subject_name,
                "chapter_id":    chapter_id,
                "chapter_title": chapter_title,
                "pyqs":          flat_questions,
                "mark_wise":     {k: [
                    (q.get("question", q) if isinstance(q, dict) else q)
                    for q in v
                ] for k, v in mark_wise.items()},
                "total":         len(flat_questions),
                "source":        "ai_important_questions",
                "ai_generated":  True,
                "created_at":    now_iso,
                "updated_at":    now_iso,
            }
            await db.ai_pyq_collections.update_one(
                {"chapter_id": chapter_id},
                {"$set": pyq_doc},
                upsert=True,
            )
            results.append({"chapter_id": chapter_id, "title": chapter_title,
                             "status": "ok", "count": len(flat_questions)})

        except (json.JSONDecodeError, ValueError) as parse_err:
            results.append({"chapter_id": chapter_id, "title": chapter_title,
                             "status": "error", "reason": f"parse: {str(parse_err)[:60]}"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": chapter_title,
                             "status": "error", "reason": str(e)[:80]})

    ok_count   = sum(1 for r in results if r.get("status") == "ok")
    total_pyqs = sum(r.get("count", 0) for r in results)
    web_count   = sum(1 for q in question_pool if q.get("source") == "web_search")
    local_count = sum(1 for q in question_pool if q.get("source") == "uploaded_paper")
    return {
        "subject_id":        subject_id,
        "subject_name":      subject_name,
        "total":             len(chapters),
        "generated":         ok_count,
        "total_pyqs":        total_pyqs,
        "pool_size":         len(question_pool),
        "web_found":         web_count,
        "local_found":       local_count,
        "papers_used":       len(html_pages),
        "results":           results,
    }


@api.post("/admin/content/chapters/{chapter_id}/rechunk")
async def admin_rechunk_chapter(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """
    Manually re-chunk a specific chapter.
    Useful for fixing chunking issues or after manual content edits.
    """
    try:
        result = await rechunk_chapter(chapter_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Re-chunking failed for chapter {chapter_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Re-chunking failed: {str(e)}")


@api.get("/admin/content/chapters/{chapter_id}/stats")
async def get_chapter_stats(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """Get chunk, content, question and flashcard stats for a single chapter."""
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    # Run all count queries in parallel
    chunk_count, pyq_doc, fc_doc, geo_blog_count, pyq_html_count = await asyncio.gather(
        db.chunks.count_documents({"chapter_id": chapter_id}),
        db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1, "mark_wise": 1}),
        db.flashcard_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1}),
        db.seo_pages.count_documents({"linked_chapter_id": chapter_id, "type": "geo_blog"}),
        db.pyq_html_pages.count_documents({"chapter_id": chapter_id}),
    )
    # Fallback to topic_pyq_collections if ai_pyq_collections is empty
    if not pyq_doc:
        pyq_doc = await db.topic_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})
    content_len = len(chapter.get("content", "") or "")
    mark_wise = pyq_doc.get("mark_wise", {}) if pyq_doc else {}
    pyq_count = pyq_doc.get("total", 0) if pyq_doc else 0
    if pyq_count == 0 and mark_wise:
        pyq_count = sum(len(v) for v in mark_wise.values())
    return {
        "chapter_id": chapter_id,
        "content_length": content_len,
        "chunk_count": chunk_count,
        "has_slug": bool(chapter.get("slug")),
        "content_type": chapter.get("content_type", "notes"),
        "attached_files": chapter.get("attached_files", []),
        "pyq_count": pyq_count,
        "mark_wise_counts": {k: len(v) for k, v in mark_wise.items()} if mark_wise else {},
        "flashcard_count": fc_doc.get("total", 0) if fc_doc else 0,
        "geo_blog_count": geo_blog_count,
        "pyq_html_count": pyq_html_count,
        "notes_generated": bool(chapter.get("notes_generated") or content_len > 100),
    }


@api.post("/admin/content/chapters/{chapter_id}/attach-file")
async def attach_file_to_chapter(
    chapter_id: str,
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user)
):
    """Upload and attach a file (PDF/text) to a chapter."""
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0, "id": 1, "subject_id": 1, "attached_files": 1})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    file_content = await file.read()
    max_file_size = 10 * 1024 * 1024
    if len(file_content) > max_file_size:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'txt'
    if file_ext not in ('pdf', 'txt', 'md'):
        raise HTTPException(status_code=400, detail="Only PDF, TXT, and MD files are supported")
    file_id = str(uuid.uuid4())

    extracted_text = ""
    pdf_url = ""

    if file_ext == 'pdf' and supa:
        import time as _t
        storage_path = f"pdfs/{chapter['subject_id']}/{_t.time():.0f}_{file.filename.replace(' ', '_')}"
        try:
            supa.storage.from_("study-materials").upload(path=storage_path, file=file_content, file_options={"content-type": "application/pdf", "upsert": "false"})
            pdf_url = supa.storage.from_("study-materials").get_public_url(storage_path)
        except Exception as e:
            logger.warning(f"Supabase upload failed, storing base64: {e}")
            import base64
            pdf_url = f"data:application/pdf;base64,{base64.b64encode(file_content).decode()}"
        try:
            from PyPDF2 import PdfReader
            import io
            reader = PdfReader(io.BytesIO(file_content))
            extracted_text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        except Exception:
            pass
    elif file_ext in ('txt', 'md'):
        extracted_text = file_content.decode('utf-8', errors='ignore')

    attachment = {
        "id": file_id,
        "file_name": file.filename,
        "file_ext": file_ext,
        "file_size": len(file_content),
        "url": pdf_url,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    existing_files = chapter.get("attached_files", []) or []
    existing_files.append(attachment)
    update_fields = {"attached_files": existing_files}

    if extracted_text and len(extracted_text) > 50:
        old_content = (await db.chapters.find_one({"id": chapter_id}, {"content": 1})).get("content", "") or ""
        separator = "\n\n---\n\n"
        update_fields["content"] = old_content + separator + f"## {file.filename}\n\n{extracted_text}" if old_content else extracted_text
        update_fields["updated_at"] = datetime.now(timezone.utc).isoformat()

    await db.chapters.update_one({"id": chapter_id}, {"$set": update_fields})

    if extracted_text and len(extracted_text) > 100:
        try:
            await rechunk_chapter(chapter_id)
        except Exception:
            pass

    _invalidate_content_cache("chapters")
    return {"attachment": attachment, "text_extracted": len(extracted_text)}


@api.post("/admin/content/bulk-rechunk")
async def admin_bulk_rechunk_all_chapters(
    subject_id: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """
    Bulk re-chunk all chapters (or chapters in a specific subject).
    
    Use cases:
    - Initial setup: chunk all existing chapters that have content
    - After algorithm improvements
    - Database migration
    
    Query params:
    - subject_id (optional): Only rechunk chapters from this subject
    """
    # Find chapters with content
    filter_query = {"content": {"$exists": True, "$ne": ""}}
    if subject_id:
        filter_query["subject_id"] = subject_id
    
    chapters = await db.chapters.find(filter_query, {"_id": 0, "id": 1, "title": 1, "subject_id": 1}).to_list(1000)
    
    if not chapters:
        return {
            "message": "No chapters with content found",
            "total": 0,
            "chunked": 0,
            "failed": 0
        }
    
    total = len(chapters)
    chunked = 0
    failed = 0
    failed_chapters = []
    
    for chapter in chapters:
        try:
            result = await rechunk_chapter(chapter["id"])
            if result["chunks_created"] > 0:
                chunked += 1
                logger.info(f"✅ Bulk rechunked: {chapter['title']} → {result['chunks_created']} chunks")
        except Exception as e:
            failed += 1
            failed_chapters.append({
                "chapter_id": chapter["id"],
                "title": chapter.get("title"),
                "error": str(e)
            })
            logger.error(f"❌ Bulk rechunk failed for {chapter.get('title')}: {e}")
    
    return {
        "message": f"Bulk re-chunking complete",
        "total_chapters": total,
        "successfully_chunked": chunked,
        "failed": failed,
        "failed_chapters": failed_chapters if failed > 0 else []
    }


@api.get("/admin/content/chunks/stats")
async def get_chunking_stats(admin: dict = Depends(get_admin_user)):
    """
    Get statistics about content chunking across the platform.
    Useful for monitoring RAG quality.
    """
    try:
        if not await is_mongo_available():
            return {"total_chunks": 0, "total_chapters": 0, "chapters_with_content": 0, "chapters_with_chunks": 0, "chapters_without_chunks": 0, "coverage_percent": 0, "top_subjects_by_chunks": [], "recommendation": "MongoDB unavailable"}
        total_chunks = await db.chunks.count_documents({})
        pipeline = [
            {"$group": {"_id": "$subject_id", "count": {"$sum": 1}, "avg_size": {"$avg": "$char_count"}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        chunks_by_subject = await db.chunks.aggregate(pipeline).to_list(10)
        if chunks_by_subject:
            subject_ids = [item["_id"] for item in chunks_by_subject if item["_id"]]
            subjects = await db.subjects.find({"id": {"$in": subject_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(20)
            subject_map = {s["id"]: s["name"] for s in subjects}
            for item in chunks_by_subject:
                item["subject_name"] = subject_map.get(item["_id"], "Unknown")
        total_chapters = await db.chapters.count_documents({})
        chapters_with_content = await db.chapters.count_documents({"content": {"$exists": True, "$ne": ""}})
        chunked_chapter_ids = await db.chunks.distinct("chapter_id")
        chapters_with_chunks = len(chunked_chapter_ids)
        chapters_without_chunks = chapters_with_content - chapters_with_chunks
        return {
            "total_chunks": total_chunks,
            "total_chapters": total_chapters,
            "chapters_with_content": chapters_with_content,
            "chapters_with_chunks": chapters_with_chunks,
            "chapters_without_chunks": chapters_without_chunks,
            "coverage_percent": round((chapters_with_chunks / chapters_with_content * 100) if chapters_with_content > 0 else 0, 1),
            "top_subjects_by_chunks": chunks_by_subject,
            "recommendation": "Run /admin/content/bulk-rechunk to chunk all chapters" if chapters_without_chunks > 0 else "All content is chunked"
        }
    except Exception:
        mark_mongo_down()
        return {"total_chunks": 0, "total_chapters": 0, "chapters_with_content": 0, "chapters_with_chunks": 0, "chapters_without_chunks": 0, "coverage_percent": 0, "top_subjects_by_chunks": [], "recommendation": "MongoDB unavailable"}



@api.patch("/admin/content/uploads/{content_id}")
async def update_content_upload(content_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    """Update uploaded content metadata"""
    allowed = {k: v for k, v in data.items() if k in ["title", "description", "content", "tags", "year", "exam_type", "category", "order", "status"]}
    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    result = await db.content_uploads.update_one({"id": content_id}, {"$set": allowed})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Content not found")
    
    updated = await db.content_uploads.find_one({"id": content_id}, {"_id": 0})
    return updated



@api.delete("/admin/content/chapters/{chapter_id}")
async def admin_delete_chapter(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """Delete chapter"""
    chapter = await db.chapters.find_one({"id": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    await db.chapters.delete_one({"id": chapter_id})
    # Decrement subject chapter count
    if chapter.get("subject_id"):
        await db.subjects.update_one(
            {"id": chapter["subject_id"]},
            {"$inc": {"chapter_count": -1}}
        )
    _invalidate_content_cache("chapters")
    _invalidate_content_cache("subjects")
    return {"message": "Chapter deleted"}

@api.post("/admin/seed")
async def admin_reseed(admin: dict = Depends(get_admin_user)):
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable in production - seed data is pre-loaded")
        global _seeded
        _seeded = False
        await db.boards.delete_many({})
        await db.classes.delete_many({})
        await db.streams.delete_many({})
        await db.subjects.delete_many({})
        await db.chapters.delete_many({})
        await ensure_seeded()
        return {"message": "Content reseeded successfully"}
    except HTTPException:
        raise
    except Exception as e:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail=f"MongoDB error: {str(e)[:50]}")

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────
@api.get("/admin/settings")
async def admin_get_settings(admin: dict = Depends(get_admin_user)):
    settings = await supa_get_settings()
    if not settings:
        settings = {"registrations_open": True, "maintenance_mode": False, "app_name": "Syrabit.ai", "tagline": "AI-Powered AHSEC Exam Prep"}
    return settings

@api.patch("/admin/settings")
async def admin_update_settings(data: SettingsUpdate, admin: dict = Depends(get_admin_user)):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if update:
        await supa_update_settings(update)
    return {"message": "Settings updated"}

@api.get("/settings")
async def get_public_settings():
    settings = await supa_get_settings()
    if not settings:
        settings = {"registrations_open": True, "maintenance_mode": False, "app_name": "Syrabit.ai", "tagline": "AI-Powered AHSEC Exam Prep"}
    return settings

# ─────────────────────────────────────────────
# ROADMAP
# ─────────────────────────────────────────────
@api.get("/admin/roadmap")
async def admin_get_roadmap(admin: dict = Depends(get_admin_user)):
    items = await db.roadmap.find({}, {"_id": 0}).to_list(100)
    return items

@api.post("/admin/roadmap")
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

@api.patch("/admin/roadmap/{item_id}")
async def admin_update_roadmap_item(item_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    update = {k: v for k, v in data.items() if k in ("title", "description", "status", "priority", "category", "phase", "effort", "impact")}
    if not update:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.roadmap.update_one({"id": item_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Updated"}

@api.delete("/admin/roadmap/{item_id}")
async def admin_delete_roadmap_item(item_id: str, admin: dict = Depends(get_admin_user)):
    result = await db.roadmap.delete_one({"id": item_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Deleted"}

# ─────────────────────────────────────────────
# ACTIVITY LOG
# ─────────────────────────────────────────────
@api.get("/admin/activity-log")
async def admin_get_activity_log(admin: dict = Depends(get_admin_user)):
    logs = await supa_get_activity_logs()
    return {"logs": logs, "total": len(logs)}

@api.post("/admin/activity-log")
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

@api.delete("/admin/activity-log")
async def admin_clear_activity_log(admin: dict = Depends(get_admin_user)):
    await supa_clear_activity_log()
    return {"message": "Activity log cleared"}

# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────
@api.get("/admin/notifications")
async def admin_get_notifications(admin: dict = Depends(get_admin_user)):
    notifs = await supa_get_notifications()
    return notifs

@api.post("/admin/notifications")
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

@api.delete("/admin/notifications/{notif_id}")
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
    try:
        from pywebpush import webpush, WebPushException
        vapid = await _get_or_create_vapid_keys()
        private_pem = vapid.get("private_key_pem", "")
        if not private_pem:
            logger.warning("Push dispatch skipped — VAPID private key missing")
            return
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
                # 410 Gone = subscription expired; clean it up
                if e.response and e.response.status_code in (404, 410):
                    await db.push_subscriptions.delete_one({"endpoint": sub.get("endpoint")})
                failed += 1
            except Exception:
                failed += 1
        logger.info(f"Push dispatch: sent={sent} failed={failed} total={len(subs)}")
    except Exception as e:
        logger.error(f"Push dispatch error: {e}")


@api.get("/push/vapid-public-key")
async def push_vapid_public_key():
    """Return the VAPID public key so the browser can subscribe."""
    keys = await _get_or_create_vapid_keys()
    pub = keys.get("public_key", "")
    if not pub:
        raise HTTPException(503, "Push not configured — VAPID key generation failed")
    return {"public_key": pub}


@api.post("/push/subscribe")
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


@api.delete("/push/subscribe")
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


@api.get("/admin/exam-schedule")
async def admin_exam_schedule_list(admin: dict = Depends(get_admin_user)):
    """List all exam dates in the schedule."""
    items = await db.exam_schedule.find(
        {}, {"_id": 1, "board": 1, "class_name": 1, "subject": 1, "exam_date": 1, "active": 1, "notified_for": 1, "created_at": 1}
    ).sort("exam_date", 1).to_list(500)
    for i in items:
        i["id"] = str(i.pop("_id"))
    return {"exams": items}


@api.post("/admin/exam-schedule")
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


@api.delete("/admin/exam-schedule/{exam_id}")
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


@api.patch("/admin/exam-schedule/{exam_id}")
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

@api.get("/admin/export/users")
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

@api.get("/admin/export/analytics")
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

@api.get("/admin/export/conversations")
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

@api.get("/admin/seo/generation-progress")
async def seo_generation_progress(admin: dict = Depends(get_admin_user)):
    return _seo_generation_progress

@api.get("/admin/seo/generation-progress/{job_id}")
async def seo_generation_progress_detail(job_id: str, admin: dict = Depends(get_admin_user)):
    if job_id not in _seo_generation_progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return _seo_generation_progress[job_id]


# ─────────────────────────────────────────────
# RATE LIMIT POLICIES
# ─────────────────────────────────────────────
DEFAULT_RATE_POLICIES = {
    "free":       {"req_per_min": 5,  "credits_per_day": 0,    "max_tokens": 1024, "req_per_min_ip": 20},
    "starter":    {"req_per_min": 15, "credits_per_day": 300,  "max_tokens": 2048, "req_per_min_ip": 50},
    "pro":        {"req_per_min": 30, "credits_per_day": 4000, "max_tokens": 4096, "req_per_min_ip": 100},
    "enterprise": {"req_per_min": 60, "credits_per_day": 99999,"max_tokens": 8192, "req_per_min_ip": 200},
}

@api.get("/admin/rate-policies")
async def admin_get_rate_policies(admin: dict = Depends(get_admin_user)):
    saved = await db.rate_policies.find_one({}, {"_id": 0})
    return saved if saved else DEFAULT_RATE_POLICIES

@api.put("/admin/rate-policies")
async def admin_update_rate_policies(data: dict, admin: dict = Depends(get_admin_user)):
    await db.rate_policies.replace_one({}, data, upsert=True)
    return {"message": "Rate policies updated"}

@api.get("/admin/rate-stats")
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


# ─────────────────────────────────────────────
# PLAN CONFIG
# ─────────────────────────────────────────────
DEFAULT_PLAN_CONFIG = {
    "free":    {"price": 0,   "credits": 0,    "validity": "monthly",  "doc_access": "zero"},
    "starter": {"price": 99,  "credits": 300,  "validity": "30 days",  "doc_access": "limited"},
    "pro":     {"price": 999, "credits": 4000, "validity": "365 days", "doc_access": "full"},
}

@api.get("/admin/plan-config")
async def admin_get_plan_config(admin: dict = Depends(get_admin_user)):
    saved = await db.plan_config.find_one({}, {"_id": 0})
    return saved if saved else DEFAULT_PLAN_CONFIG

@api.put("/admin/plan-config")
async def admin_update_plan_config(data: dict, admin: dict = Depends(get_admin_user)):
    await db.plan_config.replace_one({}, data, upsert=True)
    return {"message": "Plan config updated"}

@api.patch("/admin/plan-config/{plan}")
async def admin_patch_plan_tier(plan: str, data: dict, admin: dict = Depends(get_admin_user)):
    """Safely update a single plan tier without touching other tiers."""
    if plan not in ("free", "starter", "pro"):
        raise HTTPException(status_code=400, detail="Unknown plan key")
    existing = await db.plan_config.find_one({}, {"_id": 0}) or DEFAULT_PLAN_CONFIG.copy()
    tier = {**existing.get(plan, {}), **data}
    existing[plan] = tier
    await db.plan_config.replace_one({}, existing, upsert=True)
    return {"message": f"{plan} plan updated", "tier": tier}

# ─────────────────────────────────────────────
# API CONFIG
# ─────────────────────────────────────────────
DEFAULT_API_CONFIG = {
    "groq":        {"key": ""},
    "payment":     {"razorpay_key_id": "", "razorpay_key_secret": "", "razorpay_webhook_secret": ""},
    "email":       {"resend_key": ""},
    "push":        {"onesignal_key": ""},
    "analytics":   {"posthog_key": ""},
    "google_auth": {"client_id": "", "client_secret": "", "enabled": False},
    "supabase":    {"url": "", "service_key": "", "anon_key": ""},
}

@api.get("/admin/api-config")
async def admin_get_api_config(admin: dict = Depends(get_admin_user)):
    saved = await db.api_config.find_one({}, {"_id": 0})
    return saved if saved else DEFAULT_API_CONFIG

@api.put("/admin/api-config")
async def admin_update_api_config(data: dict, admin: dict = Depends(get_admin_user)):
    existing = await db.api_config.find_one({}, {"_id": 0})
    if existing:
        for key in data:
            if isinstance(data[key], dict) and isinstance(existing.get(key), dict):
                existing[key] = {**existing[key], **data[key]}
            else:
                existing[key] = data[key]
        await db.api_config.replace_one({}, existing, upsert=True)
    else:
        merged = {**DEFAULT_API_CONFIG, **data}
        await db.api_config.replace_one({}, merged, upsert=True)
    return {"message": "API config updated"}

# ─────────────────────────────────────────────
# RAZORPAY PAYMENT INTEGRATION
# ─────────────────────────────────────────────
async def _get_razorpay_keys() -> tuple[str, str, str]:
    """Read Razorpay keys from admin api-config stored in MongoDB.
    Returns (key_id, key_secret, webhook_secret).
    Each value is resolved independently: admin config first, then env var fallback."""
    cfg = await db.api_config.find_one({}, {"_id": 0})
    payment = cfg.get("payment", {}) if cfg else {}
    key_id = payment.get("razorpay_key_id", "").strip() or os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = payment.get("razorpay_key_secret", "").strip() or os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    webhook_secret = payment.get("razorpay_webhook_secret", "").strip() or os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
    return key_id, key_secret, webhook_secret

PLAN_PRICES_INR = {"starter": 9900, "pro": 99900}  # amount in paise (₹99 = 9900 paise)
PLAN_CREDITS    = {"starter": 300, "pro": 4000}
PLAN_DOC_ACCESS = {"starter": "limited", "pro": "full"}
PLAN_RANK_MAP   = {"free": 0, "starter": 1, "pro": 2}

class PaymentOrderRequest(BaseModel):
    plan: str  # "starter" or "pro"

class PaymentVerifyRequest(BaseModel):
    razorpay_order_id:   str
    razorpay_payment_id: str
    razorpay_signature:  str
    plan: str

@api.post("/payments/create-order")
async def create_payment_order(body: PaymentOrderRequest, user: dict = Depends(get_current_user)):
    """Create a Razorpay order for the given plan."""
    plan = body.plan.lower()
    if plan not in PLAN_PRICES_INR:
        raise HTTPException(400, f"Invalid plan '{plan}'. Choose 'starter' or 'pro'.")

    # Prevent purchasing a lower-tier plan (downgrade)
    user_plan = user.get("plan", "free")
    if PLAN_RANK_MAP.get(plan, 0) < PLAN_RANK_MAP.get(user_plan, 0):
        raise HTTPException(400, f"You are already on the {user_plan.capitalize()} plan or higher. You cannot purchase a lower-tier plan.")

    key_id, key_secret, _ = await _get_razorpay_keys()
    if not key_id or not key_secret:
        raise HTTPException(503, "Payment gateway not configured. Please contact admin@syrabit.ai.")

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.create({
            "amount":   PLAN_PRICES_INR[plan],
            "currency": "INR",
            "receipt":  f"syrabit_{user['id']}_{plan}_{int(time.time())}",
            "notes": {
                "user_id": str(user["id"]),
                "plan":    plan,
            },
        })
        return {
            "order_id":   order["id"],
            "amount":     order["amount"],
            "currency":   order["currency"],
            "key_id":     key_id,
            "plan":       plan,
            "plan_label": plan.capitalize(),
        }
    except Exception as e:
        logger.error(f"Razorpay create-order error: {e}")
        raise HTTPException(502, "Failed to create payment order. Please try again.")

@api.post("/payments/verify")
async def verify_payment(body: PaymentVerifyRequest, user: dict = Depends(get_current_user)):
    """Verify Razorpay payment signature and activate the plan."""
    plan = body.plan.lower()
    if plan not in PLAN_PRICES_INR:
        raise HTTPException(400, f"Invalid plan '{plan}'.")

    # Safety: block activating a lower-tier plan than the user already has
    user_plan = user.get("plan", "free")
    if PLAN_RANK_MAP.get(plan, 0) < PLAN_RANK_MAP.get(user_plan, 0):
        raise HTTPException(400, f"Cannot activate a lower-tier plan. You are already on {user_plan.capitalize()}.")

    key_id, key_secret, _ = await _get_razorpay_keys()
    if not key_id or not key_secret:
        raise HTTPException(503, "Payment gateway not configured.")

    # Verify HMAC-SHA256 signature
    expected = hmac.new(
        key_secret.encode(),
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, body.razorpay_signature):
        logger.warning(f"Payment signature mismatch for user {user['id']}")
        raise HTTPException(400, "Payment verification failed — invalid signature.")

    # Idempotency: check if already processed successfully
    existing = await db.payments.find_one({"razorpay_payment_id": body.razorpay_payment_id})
    if existing and existing.get("status") == "completed":
        return {"success": True, "plan": plan, "credits_added": PLAN_CREDITS[plan], "message": "Payment already processed."}

    # Server-side validation: fetch order from Razorpay and verify amount + notes
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.fetch(body.razorpay_order_id)
        order_notes = order.get("notes", {})
        order_plan = order_notes.get("plan", "")
        order_user = order_notes.get("user_id", "")
        if order_plan != plan:
            logger.warning(f"Plan mismatch: order says '{order_plan}', client says '{plan}' for user {user['id']}")
            raise HTTPException(400, "Plan mismatch — verification failed.")
        if order_user != str(user["id"]):
            logger.warning(f"User mismatch: order for '{order_user}', request from '{user['id']}'")
            raise HTTPException(400, "Order does not belong to this user.")
        if order.get("amount") != PLAN_PRICES_INR[plan]:
            logger.warning(f"Amount mismatch for user {user['id']}: expected {PLAN_PRICES_INR[plan]}, got {order.get('amount')}")
            raise HTTPException(400, "Amount mismatch — verification failed.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay order fetch error: {e}")
        raise HTTPException(502, "Could not verify order details with Razorpay.")

    # Activate plan — compensating transaction: roll back on partial failure
    user_id   = user["id"]
    credits   = PLAN_CREDITS[plan]
    doc_acc   = PLAN_DOC_ACCESS[plan]
    now_iso   = datetime.now(timezone.utc).isoformat()
    new_limit = (user.get("credits_limit") or 30) + credits
    prev_plan = user.get("plan", "free")
    prev_doc  = user.get("document_access", "none")

    payment_record = {
        "user_id":            str(user_id),
        "plan":               plan,
        "provider":           "razorpay",
        "status":             "completed",
        "amount_paise":       PLAN_PRICES_INR[plan],
        "razorpay_order_id":  body.razorpay_order_id,
        "razorpay_payment_id":body.razorpay_payment_id,
        "verified_at":        now_iso,
    }

    _payment_inserted = False
    _pg_updated       = False
    _mongo_updated    = False
    try:
        # 1. Record payment
        await db.payments.insert_one(payment_record)
        _payment_inserted = True

        # 2. Upgrade in PostgreSQL
        if pg_pool:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE users
                          SET plan=$1, credits_limit=credits_limit+$2, document_access=$3,
                              updated_at=$4
                        WHERE id=$5""",
                    plan, credits, doc_acc, now_iso, user_id,
                )
        _pg_updated = True

        # 3. Upgrade in MongoDB
        await db.users.update_one(
            {"id": str(user_id)},
            {"$set": {"plan": plan, "document_access": doc_acc, "updated_at": now_iso},
             "$inc": {"credits_limit": credits}},
        )
        _mongo_updated = True

        # 4. Mirror to Supabase (best-effort — read fallback only)
        _supa_mirror(lambda: supa.table("users").update({
            "plan": plan, "document_access": doc_acc,
            "credits_limit": new_limit, "updated_at": now_iso,
        }).eq("id", str(user_id)).execute())

        _redis_invalidate_session(user_id)
        logger.info(f"Plan activated: user={user_id} plan={plan} credits+={credits}")
        asyncio.create_task(email_templates.send_plan_activation(
            email=user.get("email", ""),
            name=user.get("name", user.get("email", "")),
            plan=plan,
            credits=credits,
            amount_paise=PLAN_PRICES_INR[plan],
        ))
        return {
            "success": True,
            "plan":    plan,
            "credits_added": credits,
            "message": f"Welcome to {plan.capitalize()}! {credits} credits added.",
        }
    except Exception as e:
        logger.error(
            f"Plan activation error for user {user_id} "
            f"(pg={_pg_updated} mongo={_mongo_updated} payment={_payment_inserted}): {e}"
        )
        # Compensating rollback — undo only what already succeeded
        try:
            if _mongo_updated:
                await db.users.update_one(
                    {"id": str(user_id)},
                    {"$set": {"plan": prev_plan, "document_access": prev_doc, "updated_at": now_iso},
                     "$inc": {"credits_limit": -credits}},
                )
            if _pg_updated and pg_pool:
                async with pg_pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE users
                              SET plan=$1, credits_limit=credits_limit-$2,
                                  document_access=$3, updated_at=$4
                            WHERE id=$5""",
                        prev_plan, credits, prev_doc, now_iso, user_id,
                    )
            if _payment_inserted:
                await db.payments.update_one(
                    {"razorpay_payment_id": body.razorpay_payment_id},
                    {"$set": {"status": "failed", "fail_reason": str(e), "failed_at": now_iso}},
                )
        except Exception as rb_err:
            logger.error(
                f"ROLLBACK FAILED for user {user_id}: {rb_err} — "
                "manual reconciliation required"
            )
        raise HTTPException(
            500,
            "Payment verified but plan activation failed — changes rolled back. "
            "Contact support@syrabit.ai if you were charged.",
        )

# ─────────────────────────────────────────────
# STRIPE PAYMENT (OPTIONAL — configurable via api-config)
# ─────────────────────────────────────────────
PLAN_PRICES_USD = {"starter": 199, "pro": 1299}

async def _get_stripe_key() -> str:
    cfg = await db.api_config.find_one({}, {"_id": 0})
    if cfg:
        sk = cfg.get("payment", {}).get("stripe_secret_key", "").strip()
        if sk:
            return sk
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()

class StripeCheckoutRequest(BaseModel):
    plan: str
    success_url: str = ""
    cancel_url: str = ""

@api.post("/payments/stripe/create-checkout")
async def stripe_create_checkout(body: StripeCheckoutRequest, user: dict = Depends(get_current_user)):
    plan = body.plan.lower()
    if plan not in PLAN_PRICES_USD:
        raise HTTPException(400, f"Invalid plan '{plan}'.")
    stripe_key = await _get_stripe_key()
    if not stripe_key:
        raise HTTPException(503, "Stripe not configured.")
    try:
        import stripe
        stripe.api_key = stripe_key
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Syrabit.ai {plan.capitalize()} Plan"},
                    "unit_amount": PLAN_PRICES_USD[plan],
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=body.success_url or f"{FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=body.cancel_url or f"{FRONTEND_URL}/payment/cancel",
            metadata={"user_id": str(user["id"]), "plan": plan},
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except ImportError:
        raise HTTPException(503, "Stripe SDK not installed.")
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(502, "Failed to create Stripe checkout.")

from starlette.requests import Request as StarletteRequest2

@api.post("/webhooks/stripe")
async def stripe_webhook(request: StarletteRequest2):
    stripe_key = await _get_stripe_key()
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not stripe_key:
        raise HTTPException(503, "Stripe not configured")
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not set — rejecting webhook")
        raise HTTPException(503, "Stripe webhook secret not configured")
    try:
        import stripe
        stripe.api_key = stripe_key
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        if not sig:
            raise HTTPException(400, "Missing stripe-signature header")
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)

        if event.get("type") == "checkout.session.completed":
            session = event["data"]["object"]
            meta = session.get("metadata", {})
            user_id = meta.get("user_id")
            plan = meta.get("plan")
            stripe_session_id = session.get("id", "")
            if user_id and plan and plan in PLAN_CREDITS:
                existing = await db.payments.find_one({"stripe_session_id": stripe_session_id})
                if existing and existing.get("status") == "completed":
                    logger.info(f"Stripe duplicate event ignored: session={stripe_session_id}")
                    return {"received": True}
                credits = PLAN_CREDITS[plan]
                doc_acc = PLAN_DOC_ACCESS[plan]
                now_iso = datetime.now(timezone.utc).isoformat()
                await db.payments.insert_one({
                    "user_id": user_id,
                    "plan": plan,
                    "provider": "stripe",
                    "status": "completed",
                    "stripe_session_id": stripe_session_id,
                    "amount_cents": session.get("amount_total", 0),
                    "currency": session.get("currency", "usd"),
                    "verified_at": now_iso,
                })
                await db.users.update_one(
                    {"id": user_id},
                    {"$set": {"plan": plan, "document_access": doc_acc, "updated_at": now_iso},
                     "$inc": {"credits_limit": credits}},
                )
                if pg_pool:
                    async with pg_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE users SET plan=$1, credits_limit=credits_limit+$2, document_access=$3, updated_at=$4 WHERE id=$5",
                            plan, credits, doc_acc, now_iso, user_id,
                        )
                _redis_invalidate_session(user_id)
                logger.info(f"Stripe payment: user={user_id} plan={plan} credits+={credits}")
        return {"received": True}
    except ImportError:
        raise HTTPException(503, "Stripe SDK not installed.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        raise HTTPException(400, f"Webhook error: {str(e)[:100]}")

@api.post("/webhooks/razorpay")
async def razorpay_webhook(request: StarletteRequest2):
    _, _, webhook_secret = await _get_razorpay_keys()
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET not set — rejecting webhook")
        raise HTTPException(503, "Razorpay webhook secret not configured")
    try:
        raw_body = await request.body()
        rp_signature = request.headers.get("x-razorpay-signature", "")
        if not rp_signature:
            raise HTTPException(400, "Missing x-razorpay-signature header")
        expected_sig = hmac.new(
            webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, rp_signature):
            logger.warning("Razorpay webhook signature mismatch")
            raise HTTPException(400, "Invalid webhook signature")

        payload = json.loads(raw_body)
        event = payload.get("event", "")
        if event == "payment.captured":
            entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
            notes = entity.get("notes", {})
            user_id = notes.get("user_id")
            plan = notes.get("plan")
            rp_payment_id = entity.get("id", "")
            if not user_id or not rp_payment_id:
                return {"received": True}
            existing = await db.payments.find_one({"razorpay_payment_id": rp_payment_id})
            if existing and existing.get("status") in ("completed", "skipped"):
                logger.info(f"Razorpay duplicate event ignored: payment={rp_payment_id}")
                return {"received": True}
            now_iso = datetime.now(timezone.utc).isoformat()
            if plan == "topup":
                topup_credits = int(notes.get("credits", 0))
                if topup_credits > 0:
                    await db.payments.insert_one({
                        "user_id": user_id,
                        "plan": "topup",
                        "provider": "razorpay",
                        "status": "completed",
                        "razorpay_payment_id": rp_payment_id,
                        "amount_paise": entity.get("amount", 0),
                        "credits_added": topup_credits,
                        "verified_at": now_iso,
                    })
                    await db.users.update_one(
                        {"id": user_id},
                        {"$set": {"updated_at": now_iso},
                         "$inc": {"credits_limit": topup_credits}},
                    )
                    if pg_pool:
                        async with pg_pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE users SET credits_limit=credits_limit+$1, updated_at=$2 WHERE id=$3",
                                topup_credits, now_iso, user_id,
                            )
                    _redis_invalidate_session(user_id)
                    logger.info(f"Razorpay topup webhook: user={user_id} credits+={topup_credits}")
            elif plan and plan in PLAN_CREDITS:
                credits = PLAN_CREDITS[plan]
                doc_acc = PLAN_DOC_ACCESS[plan]
                # Guard: never downgrade a user via webhook (e.g. stale event for lower tier)
                wh_user = await db.users.find_one({"id": user_id}, {"plan": 1})
                wh_current_plan = (wh_user or {}).get("plan", "free")
                if PLAN_RANK_MAP.get(plan, 0) < PLAN_RANK_MAP.get(wh_current_plan, 0):
                    logger.warning(
                        f"Razorpay webhook: skipping downgrade {wh_current_plan}→{plan} "
                        f"for user={user_id} payment={rp_payment_id} — payment logged only"
                    )
                    await db.payments.insert_one({
                        "user_id": user_id, "plan": plan, "provider": "razorpay",
                        "status": "skipped",
                        "razorpay_payment_id": rp_payment_id,
                        "amount_paise": entity.get("amount", 0),
                        "verified_at": now_iso, "activation_skipped": True,
                        "skip_reason": f"user already on higher plan ({wh_current_plan})",
                    })
                else:
                    _wh_payment_inserted = False
                    _wh_mongo_updated    = False
                    _wh_pg_updated       = False
                    try:
                        await db.payments.insert_one({
                            "user_id": user_id, "plan": plan, "provider": "razorpay",
                            "status": "completed",
                            "razorpay_payment_id": rp_payment_id,
                            "amount_paise": entity.get("amount", 0),
                            "verified_at": now_iso,
                        })
                        _wh_payment_inserted = True
                        await db.users.update_one(
                            {"id": user_id},
                            {"$set": {"plan": plan, "document_access": doc_acc, "updated_at": now_iso},
                             "$inc": {"credits_limit": credits}},
                        )
                        _wh_mongo_updated = True
                        if pg_pool:
                            async with pg_pool.acquire() as conn:
                                await conn.execute(
                                    "UPDATE users SET plan=$1, credits_limit=credits_limit+$2, "
                                    "document_access=$3, updated_at=$4 WHERE id=$5",
                                    plan, credits, doc_acc, now_iso, user_id,
                                )
                        _wh_pg_updated = True
                        _redis_invalidate_session(user_id)
                        logger.info(f"Razorpay webhook: user={user_id} plan={plan} credits+={credits}")
                    except Exception as wh_err:
                        logger.error(
                            f"Razorpay webhook activation failed for user={user_id} "
                            f"(mongo={_wh_mongo_updated} pg={_wh_pg_updated}): {wh_err}"
                        )
                        try:
                            if _wh_mongo_updated:
                                await db.users.update_one(
                                    {"id": user_id},
                                    {"$set": {"plan": wh_current_plan, "updated_at": now_iso},
                                     "$inc": {"credits_limit": -credits}},
                                )
                            if _wh_pg_updated and pg_pool:
                                async with pg_pool.acquire() as conn:
                                    await conn.execute(
                                        "UPDATE users SET plan=$1, credits_limit=credits_limit-$2, "
                                        "updated_at=$3 WHERE id=$4",
                                        wh_current_plan, credits, now_iso, user_id,
                                    )
                            if _wh_payment_inserted:
                                await db.payments.update_one(
                                    {"razorpay_payment_id": rp_payment_id},
                                    {"$set": {"status": "failed", "fail_reason": str(wh_err), "failed_at": now_iso}},
                                )
                        except Exception as rb_err:
                            logger.error(f"Webhook rollback failed user={user_id}: {rb_err}")
        return {"received": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay webhook error: {e}")
        raise HTTPException(400, "Webhook error")


# ─────────────────────────────────────────────
# CREDIT TOP-UP (returns order info — actual crediting via webhook)
# ─────────────────────────────────────────────
TOPUP_PRICES_INR = {100: 4900, 500: 19900, 1000: 34900}

class CreditTopUpRequest(BaseModel):
    credits: int
    provider: str = "razorpay"

@api.post("/payments/credit-topup")
async def credit_topup(body: CreditTopUpRequest, user: dict = Depends(get_current_user)):
    if user.get("plan", "free") == "free":
        raise HTTPException(403, "Free plan users cannot top up credits. Upgrade first.")
    if body.credits not in TOPUP_PRICES_INR:
        raise HTTPException(400, "Top-up must be 100, 500, or 1000 credits.")
    user_id = user["id"]
    amount = TOPUP_PRICES_INR[body.credits]
    if body.provider == "razorpay":
        key_id, key_secret, _ = await _get_razorpay_keys()
        if not key_id or not key_secret:
            raise HTTPException(503, "Razorpay not configured.")
        try:
            import razorpay
            client = razorpay.Client(auth=(key_id, key_secret))
            order = client.order.create({
                "amount": amount,
                "currency": "INR",
                "receipt": f"topup_{user_id}_{body.credits}_{int(time.time())}",
                "notes": {"user_id": str(user_id), "plan": "topup", "credits": str(body.credits)},
            })
            return {
                "order_id": order["id"],
                "amount": order["amount"],
                "currency": order["currency"],
                "key_id": key_id,
                "credits": body.credits,
            }
        except Exception as e:
            logger.error(f"Topup order error: {e}")
            raise HTTPException(502, "Failed to create top-up order.")
    raise HTTPException(400, "Unsupported provider. Use 'razorpay'.")


class CreditTopUpVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    credits: int

@api.post("/payments/credit-topup/verify")
async def credit_topup_verify(body: CreditTopUpVerifyRequest, user: dict = Depends(get_current_user)):
    # Guard: free-plan users must upgrade before they can top up credits
    if user.get("plan", "free") == "free":
        raise HTTPException(403, "Free plan users cannot top up credits. Upgrade to Starter or Pro first.")
    if body.credits not in TOPUP_PRICES_INR:
        raise HTTPException(400, "Invalid top-up amount.")
    key_id, key_secret, _ = await _get_razorpay_keys()
    if not key_id or not key_secret:
        raise HTTPException(503, "Payment gateway not configured.")
    expected = hmac.new(
        key_secret.encode(),
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, body.razorpay_signature):
        raise HTTPException(400, "Payment verification failed — invalid signature.")
    user_id = user["id"]
    existing = await db.payments.find_one({"razorpay_payment_id": body.razorpay_payment_id})
    if existing and existing.get("status") == "completed":
        return {"success": True, "credits_added": body.credits, "message": "Credits already applied."}
    # Server-side validation: verify order amount, user, and credits from Razorpay
    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))
        order = client.order.fetch(body.razorpay_order_id)
        order_notes = order.get("notes", {})
        order_credits = int(order_notes.get("credits", 0))
        order_user = order_notes.get("user_id", "")
        if order_user != str(user_id):
            raise HTTPException(400, "Order does not belong to this user.")
        if order_credits != body.credits:
            logger.warning(f"Topup credits mismatch: order={order_credits}, client={body.credits}")
            raise HTTPException(400, "Credits mismatch — verification failed.")
        if order.get("amount") != TOPUP_PRICES_INR[body.credits]:
            raise HTTPException(400, "Amount mismatch — verification failed.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Razorpay order fetch error (topup): {e}")
        raise HTTPException(502, "Could not verify order details with Razorpay.")
    # Apply credits — compensating transaction: roll back on partial failure
    now_iso   = datetime.now(timezone.utc).isoformat()
    new_limit = (user.get("credits_limit") or 0) + body.credits

    _tu_payment_inserted = False
    _tu_pg_updated       = False
    _tu_mongo_updated    = False
    try:
        # 1. Record payment
        await db.payments.insert_one({
            "user_id": str(user_id),
            "plan": "topup",
            "provider": "razorpay",
            "status": "completed",
            "razorpay_order_id": body.razorpay_order_id,
            "razorpay_payment_id": body.razorpay_payment_id,
            "amount_paise": TOPUP_PRICES_INR[body.credits],
            "credits_added": body.credits,
            "verified_at": now_iso,
        })
        _tu_payment_inserted = True

        # 2. Update PostgreSQL
        if pg_pool:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET credits_limit=credits_limit+$1, updated_at=$2 WHERE id=$3",
                    body.credits, now_iso, user_id,
                )
        _tu_pg_updated = True

        # 3. Update MongoDB
        await db.users.update_one(
            {"id": str(user_id)},
            {"$set": {"updated_at": now_iso},
             "$inc": {"credits_limit": body.credits}},
        )
        _tu_mongo_updated = True

        # 4. Mirror to Supabase (best-effort — non-critical)
        _supa_mirror(lambda: supa.table("users").update({
            "credits_limit": new_limit, "updated_at": now_iso,
        }).eq("id", str(user_id)).execute())

        _redis_invalidate_session(user_id)
        logger.info(f"Credit top-up verified: user={user_id} credits+={body.credits}")
        asyncio.create_task(email_templates.send_topup_confirmation(
            email=user.get("email", ""),
            name=user.get("name", user.get("email", "")),
            credits=body.credits,
            amount_paise=TOPUP_PRICES_INR[body.credits],
        ))
        return {
            "success": True,
            "credits_added": body.credits,
            "message": f"{body.credits} credits added to your account!",
        }
    except Exception as e:
        logger.error(
            f"Topup credit error for user {user_id} "
            f"(pg={_tu_pg_updated} mongo={_tu_mongo_updated} payment={_tu_payment_inserted}): {e}"
        )
        # Compensating rollback
        try:
            if _tu_mongo_updated:
                await db.users.update_one(
                    {"id": str(user_id)},
                    {"$set": {"updated_at": now_iso},
                     "$inc": {"credits_limit": -body.credits}},
                )
            if _tu_pg_updated and pg_pool:
                async with pg_pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE users SET credits_limit=credits_limit-$1, updated_at=$2 WHERE id=$3",
                        body.credits, now_iso, user_id,
                    )
            if _tu_payment_inserted:
                await db.payments.update_one(
                    {"razorpay_payment_id": body.razorpay_payment_id},
                    {"$set": {"status": "failed", "fail_reason": str(e), "failed_at": now_iso}},
                )
        except Exception as rb_err:
            logger.error(f"Topup rollback failed for user {user_id}: {rb_err} — manual reconciliation needed")
        raise HTTPException(
            500,
            "Payment verified but credit application failed — changes rolled back. "
            "Contact support@syrabit.ai if you were charged.",
        )


# ─────────────────────────────────────────────
# USAGE TRACKING
# ─────────────────────────────────────────────
@api.get("/usage/me")
async def get_my_usage(user: dict = Depends(get_current_user)):
    credits_info = await get_user_credits(user)
    convs = await supa_get_conversations(user["id"])
    return {
        "user_id": user["id"],
        "plan": user.get("plan", "free"),
        "credits_used": credits_info["used"],
        "credits_limit": credits_info["limit"],
        "credits_remaining": credits_info["remaining"],
        "conversations": len(convs) if convs else 0,
    }

@api.get("/admin/usage/summary")
async def admin_usage_summary(admin: dict = Depends(get_admin_user)):
    total_users = await supa_count_users()
    total_convs = await supa_count_conversations()
    payments = await db.payments.find({}, {"_id": 0}).sort("verified_at", -1).to_list(1000)
    total_revenue_inr = sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe")
    total_revenue_usd = sum(p.get("amount_cents", 0) for p in payments if p.get("provider") == "stripe")
    return {
        "total_users": total_users,
        "total_conversations": total_convs,
        "total_payments": len(payments),
        "revenue_inr_paise": total_revenue_inr,
        "revenue_usd_cents": total_revenue_usd,
        "recent_payments": payments[:20],
    }

@api.post("/admin/supabase/test")
async def admin_test_supabase(data: dict, admin: dict = Depends(get_admin_user)):
    url = data.get("url", "").strip()
    service_key = data.get("service_key", "").strip()
    if not url or not service_key:
        return {"ok": False, "error": "URL and Service Key are required"}
    try:
        test_client = _create_supa(url, service_key)
        test_client.table("users").select("id").limit(1).execute()
        return {"ok": True, "message": "Connected to Supabase successfully"}
    except Exception as e:
        err = str(e)
        if "401" in err or "Invalid API key" in err:
            return {"ok": False, "error": "Invalid API key — check your service_role key"}
        return {"ok": False, "error": f"Connection failed: {err[:200]}"}

@api.post("/admin/supabase/apply")
async def admin_apply_supabase(data: dict, admin: dict = Depends(get_admin_user)):
    global supa, SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY
    url = data.get("url", "").strip()
    service_key = data.get("service_key", "").strip()
    anon_key = data.get("anon_key", "").strip()
    if not url or not service_key:
        raise HTTPException(400, "URL and Service Key are required")
    try:
        new_client = _create_supa(url, service_key)
        new_client.table("users").select("id").limit(1).execute()
    except Exception as e:
        raise HTTPException(400, "Connection failed — check your credentials")
    try:
        existing = await db.api_config.find_one({}, {"_id": 0})
        supa_cfg = {"url": url, "service_key": service_key, "anon_key": anon_key}
        if existing:
            existing["supabase"] = supa_cfg
            await db.api_config.replace_one({}, existing, upsert=True)
        else:
            merged = {**DEFAULT_API_CONFIG, "supabase": supa_cfg}
            await db.api_config.replace_one({}, merged, upsert=True)
    except Exception as e:
        raise HTTPException(500, "Credentials verified but failed to save config")
    supa = new_client
    SUPABASE_URL = url
    SUPABASE_SERVICE_KEY = service_key
    if anon_key:
        SUPABASE_ANON_KEY = anon_key
    os.environ["SUPABASE_URL"] = url
    os.environ["SUPABASE_SERVICE_KEY"] = service_key
    if anon_key:
        os.environ["SUPABASE_ANON_KEY"] = anon_key
    logger.info("Supabase client re-initialized with new credentials")
    return {"message": "Supabase credentials applied, verified, and saved"}

# ─────────────────────────────────────────────
# CMS LIBRARY ENDPOINTS
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# MARKDOWN PROCESSING HELPERS (WordPress-style auto-format)
# ─────────────────────────────────────────────────────────────────────────────

_md_renderer = _mistune.create_markdown(
    plugins=["table", "strikethrough", "footnotes", "task_lists"],
    escape=False,
)

def _md_to_html(raw: str) -> str:
    """Convert markdown to safe HTML using mistune with GFM plugins."""
    if not raw:
        return ""
    return _md_renderer(raw) or ""

def _extract_headings_json(raw: str) -> str:
    """Return JSON array of {level, text, anchor} extracted from markdown content."""
    headings = []
    for line in raw.splitlines():
        m = re.match(r'^(#{1,3})\s+(.+)', line.strip())
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            anchor = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
            headings.append({"level": level, "text": text, "anchor": anchor})
    return json.dumps(headings)


def preprocess_markdown(md: str) -> str:
    """wpautop-equivalent: normalise line endings, expand CMS shortcodes to GFM."""
    if not md:
        return ""
    md = md.replace('\r\n', '\n').replace('\r', '\n')
    md = re.sub(r'\[PYQ\s+year=(\d{4})\]', r'> 📋 **Past Year Question (\1)**', md)
    md = re.sub(r'\[IMPORTANT\]', r'> ⚠️ **IMPORTANT**', md)
    md = re.sub(r'\[TIP\]',       r'> 💡 **TIP**',       md)
    md = re.sub(r'\[NOTE\]',      r'> 📌 **NOTE**',      md)
    md = re.sub(r'\[EXAMPLE\]',   r'> 📝 **EXAMPLE**',  md)
    return md


async def merge_subject_content(subject_id: str) -> str:
    """Aggregate a subject's chapters + chunks into a single markdown document."""
    try:
        subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
        if not subject:
            return ""
        chapters = await db.chapters.find(
            {"subject_id": subject_id}, {"_id": 0}
        ).sort("chapter_number", 1).to_list(100)

        parts: list[str] = [f"# {subject.get('name', 'Subject')}\n\n"]
        if subject.get("description"):
            parts.append(f"{subject['description']}\n\n")

        for chapter in chapters:
            num   = chapter.get("chapter_number", "")
            title = chapter.get("title", "")
            heading = f"Chapter {num}: {title}" if num else title
            parts.append(f"\n## {heading}\n\n")
            if chapter.get("description"):
                parts.append(f"{chapter['description']}\n\n")
            cks = await db.chunks.find(
                {"chapter_id": chapter["id"]}, {"_id": 0}
            ).sort("order", 1).to_list(500)
            for ck in cks:
                content = (ck.get("content") or "").strip()
                if not content:
                    continue
                ctype = (ck.get("type") or "").lower()
                if ctype == "pyq":
                    parts.append(f"> 📋 **Past Year Question**\n>\n> {content}\n\n")
                elif ctype == "summary":
                    parts.append(f"### Summary\n\n{content}\n\n")
                elif ctype == "formula":
                    parts.append(f"### Formula\n\n{content}\n\n")
                else:
                    parts.append(f"{content}\n\n")

        return preprocess_markdown("".join(parts))
    except Exception as exc:
        logger.error(f"merge_subject_content({subject_id}): {exc}")
        return ""


class CMSDocument(BaseModel):
    title: str
    content: str = ""           # raw markdown (content_raw)
    content_html: Optional[str] = ""   # processed HTML (auto-generated if empty)
    meta_description: Optional[str] = ""  # 160 char SEO description
    description: Optional[str] = ""  # Long description (2000 char)
    seo_tags: Optional[str] = ""
    primary_keyword: Optional[str] = ""
    seo_slug: Optional[str] = ""
    thumbnail_url: Optional[str] = ""
    alt_text: Optional[str] = ""
    category: Optional[str] = ""  # e.g., ahsec/class12/pcm/physics
    headings: Optional[str] = ""  # JSON string of extracted headings
    geo_tags: Optional[str] = ""  # board/class/subject/topic for GEO targeting
    schema_type: Optional[str] = "Article"  # Article, FAQPage, HowTo
    status: str = "draft"

class CMSDocumentUpdate(BaseModel):
    """Partial-update model for PATCH — all fields optional."""
    title: Optional[str] = None
    content: Optional[str] = None
    content_html: Optional[str] = None
    meta_description: Optional[str] = None
    description: Optional[str] = None
    seo_tags: Optional[str] = None
    primary_keyword: Optional[str] = None
    seo_slug: Optional[str] = None
    thumbnail_url: Optional[str] = None
    alt_text: Optional[str] = None
    category: Optional[str] = None
    headings: Optional[str] = None
    geo_tags: Optional[str] = None
    schema_type: Optional[str] = None
    status: Optional[str] = None
    is_published: Optional[bool] = None

@api.get("/admin/content/cms-documents")
async def get_cms_documents(admin: dict = Depends(get_admin_user)):
    """Get all CMS documents for admin"""
    try:
        if not await is_mongo_available():
            return []
        docs = await db.cms_documents.find({}, {"_id": 0}).sort("updated_at", -1).limit(100).to_list(100)
        return docs
    except Exception:
        mark_mongo_down()
        return []

@api.post("/admin/content/cms-documents")
async def create_cms_document(doc: CMSDocument, admin: dict = Depends(get_admin_user)):
    """Create new SEO-optimized CMS document with auto markdown→HTML processing"""
    doc_id = str(uuid.uuid4())
    raw_md = doc.content or ""
    content_html = doc.content_html or _md_to_html(raw_md)
    headings_json = doc.headings or _extract_headings_json(raw_md)
    word_count = len(re.sub(r'<[^>]+>', '', content_html).split())
    now = datetime.now(timezone.utc).isoformat()
    
    doc_data = {
        "id": doc_id,
        "title": doc.title,
        "content": raw_md,          # raw markdown
        "content_html": content_html,  # processed HTML
        "meta_description": doc.meta_description,
        "description": doc.description,
        "seo_tags": doc.seo_tags,
        "geo_tags": doc.geo_tags,
        "primary_keyword": doc.primary_keyword,
        "seo_slug": doc.seo_slug,
        "thumbnail_url": doc.thumbnail_url,
        "alt_text": doc.alt_text,
        "category": doc.category,
        "headings": headings_json,
        "schema_type": doc.schema_type,
        "status": doc.status,
        "word_count": word_count,
        "rag_processed": False,
        "created_at": now,
        "updated_at": now,
        "created_by": admin.get("email"),
    }
    
    await db.cms_documents.insert_one(doc_data)
    doc_data.pop("_id", None)
    return doc_data

@api.patch("/admin/content/cms-documents/{doc_id}")
async def update_cms_document(doc_id: str, doc: CMSDocumentUpdate, admin: dict = Depends(get_admin_user)):
    """Partial update of a CMS document — only non-None fields are written."""
    # Fetch existing doc to preserve fields not supplied in this request
    existing = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")

    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}

    # Apply only the fields explicitly provided in the request body
    patch = doc.model_dump(exclude_none=True)

    # Content-derived fields (re-process if content is being updated)
    if "content" in patch:
        raw_md = patch["content"]
        updates["content"] = raw_md
        updates["content_html"] = patch.pop("content_html", None) or _md_to_html(raw_md)
        updates["headings"] = patch.pop("headings", None) or _extract_headings_json(raw_md)
        content_html_for_wc = updates["content_html"]
        updates["word_count"] = len(re.sub(r'<[^>]+>', '', content_html_for_wc).split())
    elif "content_html" in patch:
        updates["content_html"] = patch.pop("content_html")
    if "headings" in patch:
        updates["headings"] = patch.pop("headings")

    # Handle is_published → status mapping
    if "is_published" in patch:
        updates["status"] = "published" if patch.pop("is_published") else "draft"

    # Copy all remaining patch fields directly
    for k, v in patch.items():
        updates[k] = v

    await db.cms_documents.update_one({"id": doc_id}, {"$set": updates})
    updated = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    return updated


@api.put("/admin/content/cms-documents/{doc_id}")
async def put_cms_document(doc_id: str, doc: CMSDocumentUpdate, admin: dict = Depends(get_admin_user)):
    """PUT alias for PATCH /admin/content/cms-documents/{doc_id} — partial update."""
    return await update_cms_document(doc_id, doc, admin)


@api.post("/admin/content/cms-documents/{doc_id}/publish")
async def publish_cms_document(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Toggle document status between published/draft"""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0, "status": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    new_status = "published" if doc.get("status") != "published" else "draft"
    await db.cms_documents.update_one(
        {"id": doc_id},
        {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"status": new_status}


@api.post("/admin/content/cms-documents/{doc_id}/link-syllabus")
async def link_cms_syllabus(doc_id: str, data: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Link a CMS document to a syllabus scope. Auto-populates canonical URL and geo_tags."""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    board_id   = data.get("board_id", "")
    class_id   = data.get("class_id", "")
    stream_id  = data.get("stream_id", "")
    subject_id = data.get("subject_id", "")
    board_doc   = await db.boards.find_one({"id": board_id},   {"_id": 0}) or {}
    class_doc   = await db.classes.find_one({"id": class_id},  {"_id": 0}) or {}
    stream_doc  = await db.streams.find_one({"id": stream_id}, {"_id": 0}) or {}
    subject_doc = await db.subjects.find_one({"id": subject_id}, {"_id": 0}) or {}
    board_name   = board_doc.get("name",   board_id)
    class_name   = class_doc.get("name",   class_id)
    stream_name  = stream_doc.get("name",  stream_id)
    subject_name = subject_doc.get("name", subject_id)
    canonical = f"/{_slugify(board_name)}/{_slugify(class_name)}/{_slugify(subject_name)}"
    geo_phrase = ", ".join(filter(None, [class_name, board_name, stream_name]))
    updates = {
        "linked_subject_id":   subject_id,
        "linked_board_id":     board_id,
        "linked_class_id":     class_id,
        "linked_stream_id":    stream_id,
        "linked_subject_name": subject_name,
        "linked_board_name":   board_name,
        "linked_class_name":   class_name,
        "linked_stream_name":  stream_name,
        "linked_scope":        f"{board_id}/{class_id}/{stream_id}/{subject_id}",
        "canonical_url":       canonical,
        "geo_tags":            geo_phrase,
        "updated_at":          datetime.now(timezone.utc).isoformat(),
    }
    await db.cms_documents.update_one({"id": doc_id}, {"$set": updates})
    logger.info(f"CMS doc {doc_id} linked to scope {board_id}/{class_id}/{stream_id}/{subject_id}")
    return {"message": "Linked to syllabus scope", "canonical_url": canonical, "geo_tags": geo_phrase,
            "board_name": board_name, "class_name": class_name, "stream_name": stream_name, "subject_name": subject_name}


@api.post("/admin/content/cms-documents/{doc_id}/revisions")
async def save_cms_revision(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Create a dated draft revision duplicate of a CMS document."""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    from datetime import date as _date
    date_str  = _date.today().strftime("%Y-%m-%d")
    rev_id    = f"{doc_id}-rev-{uuid.uuid4().hex[:6]}"
    base_slug = doc.get("seo_slug", _slugify(doc.get("title", "doc")))
    rev_slug  = f"{base_slug}-rev-{date_str}"
    revision  = {
        **doc,
        "id":             rev_id,
        "title":          f"{doc.get('title', 'Untitled')} — Rev {date_str}",
        "seo_slug":       rev_slug,
        "status":         "draft",
        "is_revision":    True,
        "source_doc_id":  doc_id,
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }
    revision.pop("_id", None)
    await db.cms_documents.insert_one(revision)
    logger.info(f"Revision created: {rev_id} from {doc_id}")
    return {"id": rev_id, "title": revision["title"], "seo_slug": rev_slug}


@api.post("/admin/content/extract-pdf-text")
async def extract_pdf_text(file: UploadFile = File(...), admin: dict = Depends(get_admin_user)):
    """Extract text from a PDF upload (no Supabase needed) for pasting into the editor."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")
    try:
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(raw))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        extracted = "\n\n".join(pages)
        return {"text": extracted, "pages": len(reader.pages), "chars": len(extracted)}
    except ImportError:
        # Fallback to PyPDF2 if pypdf not available
        try:
            import PyPDF2, io
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            pages = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text.strip())
            extracted = "\n\n".join(pages)
            return {"text": extracted, "pages": len(reader.pages), "chars": len(extracted)}
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"PDF extraction failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"PDF extraction failed: {e}")

@api.delete("/admin/content/cms-documents/{doc_id}")
async def delete_cms_document(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Delete CMS document"""
    await db.cms_documents.delete_one({"id": doc_id})
    # Also delete from RAG index
    await db.cms_rag_chunks.delete_many({"document_id": doc_id})
    return {"message": "Document deleted"}

@api.post("/admin/content/cms-documents/{doc_id}/process-rag")
async def process_cms_rag(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Process document for RAG indexing"""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Extract text content (strip HTML tags)
    import re
    text_content = re.sub(r'<[^>]+>', '', doc["content"])
    
    # Split into chunks (500-word chunks with 100-word overlap)
    words = text_content.split()
    chunk_size = 500
    overlap = 100
    chunks = []
    
    for i in range(0, len(words), chunk_size - overlap):
        chunk_words = words[i:i + chunk_size]
        if chunk_words:
            chunk_text = ' '.join(chunk_words)
            chunks.append({
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "document_title": doc["title"],
                "chunk_text": chunk_text,
                "chunk_index": len(chunks),
                "word_count": len(chunk_words),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    
    # Delete old chunks
    await db.cms_rag_chunks.delete_many({"document_id": doc_id})
    
    # Insert new chunks
    if chunks:
        await db.cms_rag_chunks.insert_many(chunks)
    
    # Mark document as processed
    result = await db.cms_documents.update_one(
        {"id": doc_id},
        {"$set": {"rag_processed": True, "chunk_count": len(chunks)}}
    )
    
    if result.matched_count == 0:
        logger.warning(f"CMS RAG: Document {doc_id} not found for RAG status update")
    
    logger.info(f"CMS RAG: Processed document {doc_id} into {len(chunks)} chunks")
    return {"message": f"Processed {len(chunks)} chunks", "chunks": len(chunks)}

@api.post("/admin/upload/image")
async def upload_image(file: UploadFile = File(...), admin: dict = Depends(get_admin_user)):
    """Upload image — returns a base64 data URL for immediate use."""
    import base64 as _b64
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}
    content_type = (file.content_type or "").lower()
    if content_type not in allowed_types:
        raise HTTPException(400, f"Unsupported file type '{content_type}'. Use JPEG, PNG, GIF, WebP, or SVG.")
    max_size = 5 * 1024 * 1024  # 5 MB
    raw = await file.read()
    if len(raw) > max_size:
        raise HTTPException(413, "Image too large — maximum size is 5 MB.")
    b64 = _b64.b64encode(raw).decode()
    data_url = f"data:{content_type};base64,{b64}"
    # Also store in MongoDB for future retrieval
    image_id = str(uuid.uuid4())[:12]
    try:
        await db.uploaded_images.insert_one({
            "id": image_id,
            "filename": file.filename,
            "content_type": content_type,
            "size": len(raw),
            "data_url": data_url,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "uploaded_by": admin.get("email", "admin"),
        })
    except Exception:
        pass  # data_url still returned even if MongoDB insert fails
    return {"url": data_url, "id": image_id, "filename": file.filename}

# Public CMS endpoints (no auth required)
@api.get("/content/cms-library")
async def get_public_cms_library():
    """Get published CMS documents for public library"""
    try:
        if not await is_mongo_available():
            return []
        docs = await db.cms_documents.find(
            {"status": "published"},
            {"_id": 0, "content": 0}
        ).sort("updated_at", -1).limit(50).to_list(50)
        return docs
    except Exception:
        mark_mongo_down()
        return []

@api.get("/content/cms-documents/{doc_id}")
async def get_public_cms_document(doc_id: str):
    """Get single CMS document for public view (PYQs and notes are freely scrapable)."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="Content service unavailable")
        doc = await db.cms_documents.find_one(
            {"$or": [{"id": doc_id}, {"seo_slug": doc_id}], "status": "published"},
            {"_id": 0}
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Content service unavailable")


# ──────────────────────────────────────────────────────────────────────────────
# PERSONALIZED CMS — private, paid, un-scrapable study plans
# GET  /cms/{user_id}/{slug}   — view a personal study plan (auth + paid plan)
# GET  /cms/{user_id}          — list all personal plans for user
# POST /cms/personalize        — generate a new personalized plan via Gemini
# ──────────────────────────────────────────────────────────────────────────────

_PLAN_IS_PAID = {"starter", "pro"}

@api.get("/cms/{user_id}")
async def list_personal_plans(user_id: str, response: Response, user: dict = Depends(get_current_user)):
    """List all personalized study plans that belong to this user (paid plan required)."""
    if str(user["id"]) != str(user_id):
        raise HTTPException(403, "Access denied")
    if user.get("plan", "free") not in _PLAN_IS_PAID:
        raise HTTPException(402, "Upgrade to Starter or Pro to access personalized study plans.")
    if not await is_mongo_available():
        raise HTTPException(503, "Content service unavailable")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "private, no-store"
    docs = await db.cms_documents.find(
        {"user_id": user_id, "doc_type": "personalized", "status": "published"},
        {"_id": 0, "id": 1, "slug": 1, "title": 1, "created_at": 1, "subject_name": 1}
    ).sort("created_at", -1).limit(50).to_list(50)
    return {"plans": docs, "total": len(docs)}

@api.get("/cms/{user_id}/{slug}")
async def get_personal_plan(
    user_id: str,
    slug: str,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Fetch a single personalized study plan. Auth + paid plan required. No-index headers applied."""
    if str(user["id"]) != str(user_id):
        raise HTTPException(403, "This plan belongs to another account.")
    if user.get("plan", "free") not in _PLAN_IS_PAID:
        raise HTTPException(
            402,
            detail={
                "error": "upgrade_required",
                "message": "Personalized study plans require Starter or Pro.",
                "upgrade_url": "/pricing",
            }
        )
    if not await is_mongo_available():
        raise HTTPException(503, "Content service unavailable")
    doc = await db.cms_documents.find_one(
        {"user_id": user_id, "$or": [{"id": slug}, {"slug": slug}], "doc_type": "personalized"},
        {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Study plan not found.")
    if response is not None:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "private, no-store"
    return doc


class PersonalizePlanRequest(BaseModel):
    subject_name: str = ""
    chapter_name: str = ""
    weak_topics: List[str] = []
    context: str = ""          # e.g. "I'm weak in Motion and Gravitation"
    days: int = 7              # sprint length


@api.post("/cms/personalize")
async def generate_personalized_plan(body: PersonalizePlanRequest, user: dict = Depends(get_current_user)):
    """Generate a personalized study plan using Gemini and store it as a private CMS doc."""
    if user.get("plan", "free") not in _PLAN_IS_PAID:
        raise HTTPException(
            402,
            detail={
                "error": "upgrade_required",
                "message": "Personalized plans require a paid plan (Starter/Pro).",
                "upgrade_url": "/pricing",
            }
        )
    if not await is_mongo_available():
        raise HTTPException(503, "Content service unavailable")

    user_id = str(user["id"])
    subject  = body.subject_name or "your subject"
    chapter  = body.chapter_name or ""
    days     = max(1, min(body.days, 30))
    weak     = ", ".join(body.weak_topics) if body.weak_topics else body.context or "general gaps"

    prompt = (
        f"You are a personalised exam coach for AHSEC/SEBA students in Assam (NEP 2020).\n"
        f"Student: {user.get('name', 'Student')} | Subject: {subject}"
        + (f" | Chapter focus: {chapter}" if chapter else "") +
        f"\nWeak areas identified: {weak}\n\n"
        f"Create a detailed, actionable {days}-day study sprint plan:\n"
        f"- Day-by-day schedule (topics, activities, timed blocks)\n"
        f"- Specific PYQ practice recommendations from AHSEC board papers\n"
        f"- Short-answer and long-answer question targets per day\n"
        f"- Revision checkpoints and self-assessment tips\n"
        f"- Exam-day strategy summary\n\n"
        f"Format: Clean Markdown with ## Day headers. Be specific and motivating."
    )

    try:
        plan_md = await call_slm(prompt, max_tokens=2000, temperature=0.7)
    except Exception as e:
        logger.error(f"Personalize plan generation failed: {e}")
        raise HTTPException(500, "Plan generation failed. Please try again.")

    plan_html = _md_to_html(plan_md)
    word_count = len(plan_md.split())
    slug_base  = re.sub(r"[^a-z0-9]+", "-", f"{subject} {days}-day plan".lower()).strip("-")
    slug       = f"{slug_base}-{int(time.time())}"
    doc_id     = str(uuid.uuid4())
    now        = datetime.now(timezone.utc).isoformat()
    title      = f"Your {days}-Day {subject.title()} Sprint" + (f": {chapter}" if chapter else "")

    doc = {
        "id":           doc_id,
        "slug":         slug,
        "user_id":      user_id,
        "doc_type":     "personalized",
        "category":     "study_plan",
        "title":        title,
        "content":      plan_md,
        "content_html": plan_html,
        "word_count":   word_count,
        "subject_name": subject,
        "chapter_name": chapter,
        "weak_topics":  body.weak_topics,
        "days":         days,
        "status":       "published",
        "created_at":   now,
        "updated_at":   now,
        "meta": {
            "robots":    "noindex, nofollow",
            "is_private": True,
        },
    }

    await db.cms_documents.insert_one(doc)
    doc.pop("_id", None)
    logger.info(f"Personalized plan generated for user {user_id}: {doc_id}")
    return {
        "id":    doc_id,
        "slug":  slug,
        "title": title,
        "url":   f"/cms/{user_id}/{slug}",
        "doc":   {k: v for k, v in doc.items() if k != "_id"},
    }


# ──────────────────────────────────────────────
# CMS POSTS — subject-merged blog posts
# ──────────────────────────────────────────────

@api.get("/cms/post/{subject_id}")
async def get_cms_post_by_subject(subject_id: str):
    """Get merged blog post for a subject (public). Returns cache or generates on-the-fly."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="Content service unavailable")
        doc = await db.cms_documents.find_one(
            {"subject_id": subject_id, "status": "published"},
            {"_id": 0, "merged_md": 0}
        )
        if doc:
            return {
                "subject_id": subject_id,
                "title":      doc.get("title", ""),
                "subject_merged_html": doc.get("content", ""),
                "headings":   doc.get("headings", ""),
                "word_count": doc.get("word_count", 0),
                "status":     "published",
                "seo_slug":   doc.get("seo_slug", ""),
            }
        # Generate on the fly (not cached yet)
        merged_md = await merge_subject_content(subject_id)
        if not merged_md:
            raise HTTPException(status_code=404, detail="Subject not found or empty")
        content_html = _md_to_html(merged_md)
        headings     = _extract_headings_json(merged_md)
        word_count   = len(re.sub(r'<[^>]+>', '', content_html).split())
        subject      = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
        return {
            "subject_id": subject_id,
            "title":      (subject.get("name", "") if subject else ""),
            "subject_merged_html": content_html,
            "headings":   headings,
            "word_count": word_count,
            "status":     "live",
        }
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Content service unavailable")


@api.post("/admin/cms/merge/{subject_id}")
async def admin_merge_subject(subject_id: str, admin: dict = Depends(get_admin_user)):
    """Merge subject chapters+chunks → cms_documents. Returns word count + headings."""
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="Content service unavailable")
    merged_md = await merge_subject_content(subject_id)
    if not merged_md:
        raise HTTPException(status_code=404, detail="Subject not found or has no chapters")
    content_html  = _md_to_html(merged_md)
    headings_json = _extract_headings_json(merged_md)
    word_count    = len(re.sub(r'<[^>]+>', '', content_html).split())
    subject       = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    now           = datetime.now(timezone.utc).isoformat()
    subject_name  = subject.get("name", "") if subject else ""
    subject_slug  = subject.get("slug", subject_id) if subject else subject_id

    # ── Primary: write to cms_documents ─────────────────────────────────────
    cms_doc_data = {
        "subject_id":          subject_id,
        "title":               subject_name,
        "seo_slug":            subject_slug,
        "board_slug":          (subject.get("board_slug", "") if subject else ""),
        "class_slug":          (subject.get("class_slug", "") if subject else ""),
        "content":             content_html,
        "merged_md":           merged_md,
        "headings":            headings_json,
        "word_count":          word_count,
        "status":              "published",
        "schema_type":         "Article",
        "primary_keyword":     subject_name,
        "updated_at":          now,
    }
    existing_doc = await db.cms_documents.find_one({"subject_id": subject_id}, {"_id": 0, "id": 1})
    if existing_doc:
        await db.cms_documents.update_one(
            {"subject_id": subject_id},
            {"$set": cms_doc_data},
        )
        doc_id = existing_doc.get("id", "")
    else:
        cms_doc_data["id"] = str(uuid.uuid4())
        cms_doc_data["created_at"] = now
        await db.cms_documents.insert_one(cms_doc_data)
        doc_id = cms_doc_data["id"]

    headings = json.loads(headings_json) if headings_json else []
    return {
        "subject_id":  subject_id,
        "doc_id":      doc_id,
        "word_count":  word_count,
        "headings":    headings,
        "slug":        subject_slug,
        "title":       subject_name,
        "merged_md":   merged_md,
        "content":     content_html,
        "board_slug":  subject.get("board_slug", "")   if subject else "",
        "class_slug":  subject.get("class_slug", "")   if subject else "",
        "class_name":  subject.get("class_name", "")   if subject else "",
        "stream_name": subject.get("stream_name", "")  if subject else "",
        "stream_slug": subject.get("stream_slug", "")  if subject else "",
    }


@api.get("/cms/posts")
async def list_cms_posts(
    board:      Optional[str] = None,
    class_slug: Optional[str] = None,
    subject_id: Optional[str] = None,
    limit:      int = 20,
    skip:       int = 0,
):
    """Paginated published cms content for Library infinite scroll — reads from cms_documents."""
    try:
        if not await is_mongo_available():
            return {"items": [], "total": 0}
        query: dict = {"status": "published", "subject_id": {"$exists": True, "$ne": None}}
        if board:      query["board_slug"]  = board
        if class_slug: query["class_slug"]  = class_slug
        if subject_id: query["subject_id"]  = subject_id
        limit = min(max(limit, 1), 50)
        items = await db.cms_documents.find(
            query, {"_id": 0, "merged_md": 0, "content": 0}
        ).sort("updated_at", -1).skip(skip).limit(limit).to_list(limit)
        total = await db.cms_documents.count_documents(query)
        return {"items": items, "total": total}
    except Exception:
        mark_mongo_down()
        return {"items": [], "total": 0}


@api.post("/admin/content/regenerate-sitemap")
async def regenerate_sitemap(admin: dict = Depends(get_admin_user)):
    """Regenerate sitemap.xml — reads from cms_documents only."""
    try:
        sitemap_entries = []
        # All published CMS documents (standalone + subject-merged)
        docs = await db.cms_documents.find(
            {"status": "published"},
            {"_id": 0, "seo_slug": 1, "id": 1, "category": 1, "subject_id": 1, "updated_at": 1}
        ).to_list(3000)
        for doc in docs:
            slug = doc.get("seo_slug") or doc.get("id", "")
            # Subject-merged docs use /subject/ path; standalone blogs use /learn/
            if doc.get("subject_id") and not doc.get("category"):
                path = f"/subject/{doc.get('subject_id', slug)}"
                priority = "0.7"
            else:
                path = f"/learn/{slug}"
                priority = "0.8"
            sitemap_entries.append({
                "url":     path,
                "lastmod": doc.get("updated_at", ""),
                "priority": priority,
            })
        logger.info(f"Sitemap regenerated: {len(sitemap_entries)} entries")
        return {"message": f"Sitemap generated with {len(sitemap_entries)} entries", "count": len(sitemap_entries)}
    except Exception as e:
        logger.error(f"Sitemap generation error: {e}")
        raise HTTPException(status_code=500, detail="Sitemap generation failed")


# ─────────────────────────────────────────────
# PDF DOCUMENT UPLOAD & VIEWER
# ─────────────────────────────────────────────

@api.post("/admin/content/upload-pdf")
async def upload_pdf_document(
    file: UploadFile = File(...),
    subject_id: str = Form(...),
    title: str = Form(None),
    admin: dict = Depends(get_admin_user)
):
    """
    Upload PDF document for a subject to Supabase Storage.
    Extracts text for RAG and stores PDF URL from Supabase.
    """
    # Validate Supabase is configured
    if not supa:
        raise HTTPException(status_code=503, detail="Supabase storage not configured")
    
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Enforce size limit (10MB)
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF file too large (max 10MB)")
    
    # Extract text from PDF for RAG
    extracted_text = ""
    page_count = 0
    is_scanned = False
    
    try:
        from PyPDF2 import PdfReader
        import io
        
        pdf_reader = PdfReader(io.BytesIO(content))
        page_count = len(pdf_reader.pages)
        
        for page in pdf_reader.pages:
            extracted_text += page.extract_text() + "\n"
        
        # Clean extracted text
        extracted_text = extracted_text.strip()
        
        # Check if this is a scanned document (image-based PDF)
        if len(extracted_text) < 50:
            is_scanned = True
            extracted_text = f"[Scanned Document - {file.filename}]\nThis is an image-based PDF (scanned question paper or document). Text extraction not available. OCR may be needed for text search."
            logger.info(f"Scanned/image-based PDF detected: {file.filename}")
        
    except Exception as e:
        logger.error(f"PDF processing failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to process PDF: {str(e)}")
    
    # Upload to Supabase Storage
    try:
        # Create unique filename with timestamp
        import time
        timestamp = int(time.time())
        safe_filename = file.filename.replace(' ', '_').replace('/', '_')
        storage_path = f"pdfs/{subject_id}/{timestamp}_{safe_filename}"
        
        # Ensure bucket exists (create if not)
        try:
            supa.storage.get_bucket("study-materials")
        except:
            try:
                supa.storage.create_bucket("study-materials", options={"public": True})
                logger.info("Created 'study-materials' bucket")
            except Exception as bucket_err:
                logger.warning(f"Bucket creation failed (may already exist): {bucket_err}")
        
        # Upload file to Supabase Storage
        response = supa.storage.from_("study-materials").upload(
            path=storage_path,
            file=content,
            file_options={
                "content-type": "application/pdf",
                "cache-control": "3600",
                "upsert": "false"
            }
        )
        
        # Get public URL
        pdf_url = supa.storage.from_("study-materials").get_public_url(storage_path)
        
        logger.info(f"✅ PDF uploaded to Supabase: {storage_path}")
        
    except Exception as storage_err:
        logger.error(f"Supabase storage upload failed: {storage_err}")
        raise HTTPException(status_code=500, detail=f"Failed to upload to storage: {str(storage_err)}")
    
    # Create document record in MongoDB
    doc_id = str(uuid.uuid4())
    doc_title = title or file.filename
    
    document = {
        "id": doc_id,
        "subject_id": subject_id,
        "title": doc_title,
        "file_name": file.filename,
        "file_size": file_size,
        "content_type": "application/pdf",
        "pdf_url": pdf_url,  # Supabase Storage URL
        "storage_path": storage_path,  # For deletion
        "extracted_text": extracted_text,  # For RAG (or placeholder for scanned)
        "is_scanned": is_scanned,  # Flag for image-based PDFs
        "page_count": page_count,
        "uploaded_by": admin.get("email"),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.content_uploads.insert_one(document)
    
    # Update subject to mark it has a document
    await db.subjects.update_one(
        {"id": subject_id},
        {"$set": {"has_document": True}}
    )
    
    logger.info(f"✅ PDF metadata saved: {file.filename} for subject {subject_id} ({file_size} bytes, {page_count} pages, scanned: {is_scanned})")
    
    return {
        "document_id": doc_id,
        "title": doc_title,
        "file_name": file.filename,
        "file_size": file_size,
        "page_count": page_count,
        "pdf_url": pdf_url,
        "is_scanned": is_scanned,
        "text_length": len(extracted_text),
        "message": "PDF uploaded successfully to Supabase Storage" + (" (scanned document - no text extracted)" if is_scanned else "")
    }


@api.get("/content/documents/{document_id}")
async def get_document(document_id: str):
    """
    Get document details including PDF URL.
    Supports both legacy base64 and new Supabase Storage URLs.
    """
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="Content service unavailable")
        doc = await db.content_uploads.find_one({"id": document_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Content service unavailable")


@api.get("/content/subject-documents/{subject_id}")
async def get_subject_documents(subject_id: str, include_pdf: bool = False):
    """
    Get all documents for a subject.
    """
    try:
        if not await is_mongo_available():
            return []
        projection = {"_id": 0}
        if not include_pdf:
            projection["extracted_text"] = 0
            projection["pdf_data_url"] = 0
            projection["pdf_url"] = 0
        else:
            projection["extracted_text"] = 0
        
        docs = await db.content_uploads.find(
            {"subject_id": subject_id},
            projection
        ).to_list(20)
        return docs
    except Exception:
        mark_mongo_down()
        return []


@api.delete("/admin/content/documents/{document_id}")
async def delete_document(document_id: str, admin: dict = Depends(get_admin_user)):
    """Delete uploaded document from both MongoDB and Supabase Storage"""
    # Get document first to get storage path
    doc = await db.content_uploads.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete from Supabase Storage if it exists there
    if doc.get("storage_path") and supa:
        try:
            supa.storage.from_("study-materials").remove([doc["storage_path"]])
            logger.info(f"✅ Deleted PDF from Supabase: {doc['storage_path']}")
        except Exception as e:
            logger.warning(f"Failed to delete from Supabase storage: {e}")
    
    # Delete from MongoDB
    result = await db.content_uploads.delete_one({"id": document_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {"message": "Document deleted successfully from both storage and database"}


# ─────────────────────────────────────────────
# ENHANCED HEALTH
# ─────────────────────────────────────────────
import time as _time_mod
import threading as _threading
from collections import defaultdict as _defaultdict

_startup_time = _time_mod.time()

# ── Background health-check cache ─────────────────────────────────────────────
# _check_health_deps() costs ~500 ms per call (Supabase round-trip).
# A background task runs it every 25 s and stores the result here so the
# admin dashboard always reads from cache (~0 ms).
_health_deps_cache: dict = {}
_health_deps_cache_at: float = 0.0
_HEALTH_CACHE_TTL_S: float = 30.0      # max age before falling back to live call

class _MetricsStore:
    def __init__(self):
        self._lock = _threading.Lock()
        self.request_count = 0
        self.error_count = 0
        self.active_requests = 0
        self.active_users: Dict[str, float] = {}
        self.chat_count = 0
        self.endpoint_counts: Dict[str, int] = _defaultdict(int)
        self.status_counts: Dict[int, int] = _defaultdict(int)
        self._rps_window: list = []

    def record_request(self, path: str, status: int, user_id: str = None):
        now = _time_mod.time()
        with self._lock:
            self.request_count += 1
            self.status_counts[status] += 1
            if status >= 400:
                self.error_count += 1
            bucket = path.split("?")[0]
            if bucket.startswith("/api/"):
                self.endpoint_counts[bucket] += 1
            if path.startswith("/api/chat"):
                self.chat_count += 1
            if user_id:
                self.active_users[user_id] = now
            self._rps_window.append(now)

    def inc_active(self):
        with self._lock:
            self.active_requests += 1

    def dec_active(self):
        with self._lock:
            self.active_requests -= 1

    def get_rps(self) -> float:
        now = _time_mod.time()
        cutoff = now - 60
        with self._lock:
            self._rps_window = [t for t in self._rps_window if t > cutoff]
            count = len(self._rps_window)
        return round(count / 60.0, 2) if count else 0.0

    def get_active_users(self, window_seconds: int = 300) -> int:
        cutoff = _time_mod.time() - window_seconds
        with self._lock:
            self.active_users = {uid: ts for uid, ts in self.active_users.items() if ts > cutoff}
            return len(self.active_users)

    def get_top_endpoints(self, n: int = 10) -> list:
        with self._lock:
            return sorted(self.endpoint_counts.items(), key=lambda x: -x[1])[:n]

_metrics = _MetricsStore()

_METRICS_HISTORY_MAX = 1440
_metrics_history: list = []
_metrics_history_lock = _threading.Lock()

def _snapshot_metrics():
    """Take a point-in-time snapshot of key metrics for graphing."""
    import datetime
    now = datetime.datetime.utcnow()
    batch_s = _llm_batcher.stats
    snap = {
        "t": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ts": int(_time_mod.time()),
        "active_5m": _metrics.get_active_users(300),
        "active_15m": _metrics.get_active_users(900),
        "active_60m": _metrics.get_active_users(3600),
        "rps": _metrics.get_rps(),
        "requests": _metrics.request_count,
        "errors": _metrics.error_count,
        "chats": _metrics.chat_count,
        "in_flight": _metrics.active_requests,
        "llm_batched": batch_s["batched"],
        "llm_deduped": batch_s["deduped"],
        "llm_pending": batch_s["pending"],
    }
    with _metrics_history_lock:
        _metrics_history.append(snap)
        if len(_metrics_history) > _METRICS_HISTORY_MAX:
            del _metrics_history[:len(_metrics_history) - _METRICS_HISTORY_MAX]
    return snap

def _start_metrics_collector():
    """Background thread that snapshots metrics every 60 seconds."""
    def _run():
        while True:
            try:
                _snapshot_metrics()
            except Exception:
                pass
            _time_mod.sleep(60)
    t = _threading.Thread(target=_run, daemon=True)
    t.start()

_start_metrics_collector()

@api.get("/ready", response_model=ReadyOut)
async def readiness():
    checks = {"mongodb": False, "postgresql": False}
    try:
        if db is not None:
            await db.command("ping")
            checks["mongodb"] = True
    except Exception:
        pass
    try:
        if pg_pool:
            async with pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["postgresql"] = True
    except Exception:
        pass
    all_ok = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )

@api.get("/health", response_model=HealthOut)
async def health():
    kv_ok = await is_mongo_available()
    kv_latency = 0
    if kv_ok:
        try:
            t0 = _time_mod.time()
            await db.boards.find_one({})
            kv_latency = int((_time_mod.time() - t0) * 1000)
        except Exception:
            kv_ok = False

    redis_ok = False
    if redis_client:
        try:
            redis_client.ping()
            redis_ok = True
        except Exception:
            pass

    mongo_status = "ok" if kv_ok else "unavailable"

    pg_ok = False
    pg_latency = 0
    if pg_pool:
        try:
            t1 = _time_mod.time()
            async with pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            pg_latency = int((_time_mod.time() - t1) * 1000)
            pg_ok = True
        except Exception:
            pass

    # Razorpay — check if keys are configured (no live HTTP call; avoids cost)
    rp_cfg = await db.api_config.find_one({}, {"payment": 1}) or {}
    rp_payment = rp_cfg.get("payment", {})
    rp_key_id = (rp_payment.get("razorpay_key_id") or os.environ.get("RAZORPAY_KEY_ID", "")).strip()
    rp_key_secret = (rp_payment.get("razorpay_key_secret") or os.environ.get("RAZORPAY_KEY_SECRET", "")).strip()
    rp_status = "configured" if (rp_key_id and rp_key_secret) else "not_configured"

    # Overall status: degraded if any critical dependency is down
    critical_ok = kv_ok and pg_ok
    overall = "ok" if critical_ok else "degraded"

    return {
        "status": overall,
        "version": "2.0.0",
        "service": "Syrabit.ai API",
        "workers": int(os.environ.get("GUNICORN_WORKERS", 3)),
        "uptime_seconds": int(_time_mod.time() - _startup_time),
        "dependencies": {
            "mongodb": {"status": mongo_status, "latencyMs": kv_latency},
            "postgresql": {"status": "ok" if pg_ok else "unavailable", "latencyMs": pg_latency},
            "redis": {"status": "ok" if redis_ok else "not_connected"},
            "llm": {
                "status": "ok" if OPENAI_API_KEY else "not_configured",
                "provider": LLM_PROVIDER,
                "model": LLM_MODEL,
                "providers": [p["provider"] for p in _LLM_PROVIDERS],
                "fallback": len(_LLM_PROVIDERS) > 1,
            },
            "supabase": {"status": "ok" if supa else "not_configured"},
            "razorpay": {"status": rp_status},
        }
    }

@api.get("/metrics")
async def prometheus_metrics():
    import os as _os
    mem_rss_mb = 0
    mem_vms_mb = 0
    cpu = 0
    try:
        with open(f"/proc/{_os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    mem_rss_mb = int(line.split()[1]) / 1024
                elif line.startswith("VmSize:"):
                    mem_vms_mb = int(line.split()[1]) / 1024
        with open(f"/proc/{_os.getpid()}/stat") as f:
            fields = f.read().split()
            utime = int(fields[13])
            stime = int(fields[14])
            total_ticks = utime + stime
            hz = _os.sysconf("SC_CLK_TCK")
            cpu_seconds = total_ticks / hz
            cpu = round(cpu_seconds / max(1, _time_mod.time() - _startup_time) * 100, 1)
    except Exception:
        pass

    content_cache_size = len(_content_cache)
    ai_cache_size = len(_ai_response_cache)
    uptime = int(_time_mod.time() - _startup_time)
    rps = _metrics.get_rps()
    active_users_5m = _metrics.get_active_users(300)
    active_users_15m = _metrics.get_active_users(900)
    active_users_60m = _metrics.get_active_users(3600)
    top_endpoints = _metrics.get_top_endpoints(10)

    lines = [
        f'# HELP syrabit_uptime_seconds Server uptime in seconds',
        f'# TYPE syrabit_uptime_seconds gauge',
        f'syrabit_uptime_seconds {uptime}',
        f'# HELP syrabit_memory_rss_mb Resident memory in MB',
        f'# TYPE syrabit_memory_rss_mb gauge',
        f'syrabit_memory_rss_mb {mem_rss_mb:.1f}',
        f'# HELP syrabit_memory_vms_mb Virtual memory in MB',
        f'# TYPE syrabit_memory_vms_mb gauge',
        f'syrabit_memory_vms_mb {mem_vms_mb:.1f}',
        f'# HELP syrabit_cpu_percent CPU usage percentage',
        f'# TYPE syrabit_cpu_percent gauge',
        f'syrabit_cpu_percent {cpu:.1f}',
        f'# HELP syrabit_requests_total Total requests handled by this worker',
        f'# TYPE syrabit_requests_total counter',
        f'syrabit_requests_total {_metrics.request_count}',
        f'# HELP syrabit_errors_total Total error responses (4xx/5xx)',
        f'# TYPE syrabit_errors_total counter',
        f'syrabit_errors_total {_metrics.error_count}',
        f'# HELP syrabit_requests_in_flight Requests currently being processed',
        f'# TYPE syrabit_requests_in_flight gauge',
        f'syrabit_requests_in_flight {_metrics.active_requests}',
        f'# HELP syrabit_rps Requests per second (60s window)',
        f'# TYPE syrabit_rps gauge',
        f'syrabit_rps {rps}',
        f'# HELP syrabit_chat_requests_total Total AI chat requests',
        f'# TYPE syrabit_chat_requests_total counter',
        f'syrabit_chat_requests_total {_metrics.chat_count}',
        f'# HELP syrabit_active_users_5m Unique authenticated users in last 5 minutes',
        f'# TYPE syrabit_active_users_5m gauge',
        f'syrabit_active_users_5m {active_users_5m}',
        f'# HELP syrabit_active_users_15m Unique authenticated users in last 15 minutes',
        f'# TYPE syrabit_active_users_15m gauge',
        f'syrabit_active_users_15m {active_users_15m}',
        f'# HELP syrabit_active_users_60m Unique authenticated users in last 60 minutes',
        f'# TYPE syrabit_active_users_60m gauge',
        f'syrabit_active_users_60m {active_users_60m}',
        f'# HELP syrabit_content_cache_entries Content cache entries',
        f'# TYPE syrabit_content_cache_entries gauge',
        f'syrabit_content_cache_entries {content_cache_size}',
        f'# HELP syrabit_ai_cache_entries AI response cache entries',
        f'# TYPE syrabit_ai_cache_entries gauge',
        f'syrabit_ai_cache_entries {ai_cache_size}',
        f'# HELP syrabit_workers Configured worker count',
        f'# TYPE syrabit_workers gauge',
        f'syrabit_workers {int(_os.environ.get("GUNICORN_WORKERS", 3))}',
        f'# HELP syrabit_redis_connected Redis connection status',
        f'# TYPE syrabit_redis_connected gauge',
        f'syrabit_redis_connected {1 if redis_client else 0}',
        f'# HELP syrabit_redis_hits Redis cache hits',
        f'# TYPE syrabit_redis_hits counter',
        f'syrabit_redis_hits {_redis_hit_count}',
        f'# HELP syrabit_redis_misses Redis cache misses',
        f'# TYPE syrabit_redis_misses counter',
        f'syrabit_redis_misses {_redis_miss_count}',
    ]
    batch_stats = _llm_batcher.stats
    lines.extend([
        f'# HELP syrabit_llm_batched Total LLM requests processed via batcher',
        f'# TYPE syrabit_llm_batched counter',
        f'syrabit_llm_batched {batch_stats["batched"]}',
        f'# HELP syrabit_llm_deduped Requests served by piggy-backing on in-flight call',
        f'# TYPE syrabit_llm_deduped counter',
        f'syrabit_llm_deduped {batch_stats["deduped"]}',
        f'# HELP syrabit_llm_errors LLM call errors',
        f'# TYPE syrabit_llm_errors counter',
        f'syrabit_llm_errors {batch_stats["errors"]}',
        f'# HELP syrabit_llm_pending Currently in-flight LLM requests',
        f'# TYPE syrabit_llm_pending gauge',
        f'syrabit_llm_pending {batch_stats["pending"]}',
    ])
    for status_code, count in sorted(_metrics.status_counts.items()):
        lines.append(f'syrabit_responses_by_status{{code="{status_code}"}} {count}')
    for endpoint, count in top_endpoints:
        safe = endpoint.replace('"', '\\"')
        lines.append(f'syrabit_endpoint_hits{{path="{safe}"}} {count}')
    from starlette.responses import Response
    return Response(content='\n'.join(lines) + '\n', media_type='text/plain; version=0.0.4; charset=utf-8')

@api.get("/ai/cache/stats")
async def get_cache_stats(admin: dict = Depends(get_admin_user)):
    """Return cache statistics (admin only)."""
    return {
        "size": len(_ai_response_cache),
        "maxsize": _ai_response_cache.maxsize,
        "ttl": _ai_response_cache.ttl
    }

@api.get("/metrics/history")
async def metrics_history(minutes: int = 60, admin: dict = Depends(get_admin_user)):
    """Return time-series metrics history for graphing (admin only)."""
    minutes = min(max(minutes, 1), _METRICS_HISTORY_MAX)
    cutoff = _time_mod.time() - (minutes * 60)
    _snapshot_metrics()
    with _metrics_history_lock:
        data = [s for s in _metrics_history if s["ts"] >= cutoff]

    peak_5m = max((s["active_5m"] for s in data), default=0)
    peak_15m = max((s["active_15m"] for s in data), default=0)
    peak_60m = max((s["active_60m"] for s in data), default=0)
    peak_rps = max((s["rps"] for s in data), default=0)

    return {
        "history": data,
        "peaks": {
            "active_users_5m": peak_5m,
            "active_users_15m": peak_15m,
            "active_users_60m": peak_60m,
            "rps": peak_rps,
        },
        "current": data[-1] if data else None,
        "points": len(data),
        "window_minutes": minutes,
    }

# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────
from seo_engine import router as seo_router, init_seo_engine, _smart_grade_label, _smart_board_display
init_seo_engine(db, call_llm_api, get_admin_user, log_activity_fn=supa_insert_activity_log)
api.include_router(seo_router)

from qa_engine import public_router as qa_public_router, admin_router as qa_admin_router, init_qa_engine, ensure_qa_indexes, log_chat_message as _log_chat_message
init_qa_engine(db, get_admin_user)
api.include_router(qa_public_router)
api.include_router(qa_admin_router)

# ─────────────────────────────────────────────
# SARVAM AI — Translate, TTS, Transliterate
# ─────────────────────────────────────────────

_SARVAM_LANG_CODES = {
    "en", "en-IN", "as", "as-IN", "bn", "bn-IN",
    "hi", "hi-IN", "gu", "gu-IN", "kn", "kn-IN",
    "ml", "ml-IN", "mr", "mr-IN", "od", "od-IN",
    "pa", "pa-IN", "ta", "ta-IN", "te", "te-IN",
}

def _normalise_lang(code: str) -> str:
    """Ensure language code has -IN suffix (sarvam requires it)."""
    code = code.strip()
    if '-' not in code:
        return f"{code}-IN"
    return code

def _sarvam_cache_key(op: str, payload: dict) -> str:
    import hashlib, json
    raw = json.dumps(payload, sort_keys=True)
    return f"sarvam:{op}:{hashlib.md5(raw.encode()).hexdigest()}"

@api.get("/sarvam/status")
async def sarvam_status():
    return {
        "enabled": sarvam_client is not None,
        "supported_languages": sorted(_SARVAM_LANG_CODES),
    }

_LANG_LABELS = {
    "as": "Assamese (অসমীয়া)", "as-IN": "Assamese (অসমীয়া)",
    "bn": "Bengali (বাংলা)", "bn-IN": "Bengali (বাংলা)",
    "en": "English", "en-IN": "English (India)",
    "gu": "Gujarati (ગુજરાતી)", "gu-IN": "Gujarati (ગુજરાતી)",
    "hi": "Hindi (हिन्दी)", "hi-IN": "Hindi (हिन्दी)",
    "kn": "Kannada (ಕನ್ನಡ)", "kn-IN": "Kannada (ಕನ್ನಡ)",
    "ml": "Malayalam (മലയാളം)", "ml-IN": "Malayalam (മലയാളം)",
    "mr": "Marathi (मराठी)", "mr-IN": "Marathi (मराठी)",
    "od": "Odia (ଓଡ଼ିଆ)", "od-IN": "Odia (ଓଡ଼ିଆ)",
    "pa": "Punjabi (ਪੰਜਾਬੀ)", "pa-IN": "Punjabi (ਪੰਜਾਬੀ)",
    "ta": "Tamil (தமிழ்)", "ta-IN": "Tamil (தமிழ்)",
    "te": "Telugu (తెలుగు)", "te-IN": "Telugu (తెలుగు)",
}

@api.get("/admin/translation/languages")
async def admin_translation_languages(admin: dict = Depends(get_admin_user)):
    """Return supported translation languages as {code, label} list."""
    seen_base = set()
    result = []
    for code in sorted(_SARVAM_LANG_CODES):
        base = code.split("-")[0]
        if base in seen_base:
            continue
        seen_base.add(base)
        label = _LANG_LABELS.get(code) or _LANG_LABELS.get(base) or code
        result.append({"code": base, "label": label})
    return result

@api.post("/sarvam/translate")
async def sarvam_translate(data: dict):
    """Translate text between Indian languages via Sarvam AI."""
    if not sarvam_client:
        raise HTTPException(status_code=503, detail="Sarvam AI not configured")
    text = (data.get("text") or data.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    src = _normalise_lang(data.get("source_language_code", "en-IN"))
    tgt = _normalise_lang(data.get("target_language_code", "as-IN"))

    # Check cache first
    cache_key = _sarvam_cache_key("translate", {"text": text, "src": src, "tgt": tgt})
    cached = _get_content_cache(cache_key)
    if cached:
        return {**cached, "cached": True}

    # mayura:v1 supports: hi, bn, mr, te, kn, ml, ta, gu, pa
    # sarvam-translate:v1 supports all Indic langs including as, od
    _MAYURA_LANGS = {"hi-IN", "bn-IN", "mr-IN", "te-IN", "kn-IN", "ml-IN", "ta-IN", "gu-IN", "pa-IN"}
    model = "mayura:v1" if (src in _MAYURA_LANGS and tgt in _MAYURA_LANGS) else "sarvam-translate:v1"
    payload = {
        "input": text,
        "source_language_code": src,
        "target_language_code": tgt,
        "speaker_gender": data.get("speaker_gender", "Female"),
        "mode": data.get("mode", "formal"),
        "model": model,
        "enable_preprocessing": False,
    }
    try:
        resp = await sarvam_client.post("/translate", json=payload)
        resp.raise_for_status()
        result = resp.json()
        out = {"translated_text": result.get("translated_text", ""), "source": src, "target": tgt}
        _set_content_cache(cache_key, out)
        return out
    except httpx.HTTPStatusError as e:
        logger.error(f"Sarvam translate error {e.response.status_code} [{src}->{tgt}]")
        raise HTTPException(status_code=e.response.status_code, detail="Sarvam translation failed")
    except Exception as e:
        logger.error(f"Sarvam translate exception: {type(e).__name__} [{src}->{tgt}]")
        raise HTTPException(status_code=502, detail="Sarvam AI unreachable")

@api.post("/sarvam/tts")
async def sarvam_tts(data: dict):
    """Convert text to speech in Indian languages via Sarvam AI (Bulbul model)."""
    if not sarvam_client:
        raise HTTPException(status_code=503, detail="Sarvam AI not configured")
    text = (data.get("text") or data.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    # Sarvam TTS max input ~500 chars per request
    if len(text) > 500:
        text = text[:500]
    lang = _normalise_lang(data.get("target_language_code", "en-IN"))

    # Cache audio as base64
    cache_key = _sarvam_cache_key("tts", {"text": text, "lang": lang,
        "speaker": data.get("speaker", "meera"), "pace": data.get("pace", 1.0)})
    cached = _get_content_cache(cache_key)
    if cached:
        return {**cached, "cached": True}

    # Valid Sarvam TTS speakers (updated list)
    _VALID_SPEAKERS = {
        "anushka", "abhilash", "manisha", "vidya", "arya", "karun", "hitesh",
        "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran",
        "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun", "manan",
        "sumit", "roopa", "kabir", "aayan", "shubh", "ashutosh", "advait",
        "amelia", "sophia", "anand", "tanya", "tarun", "sunny", "mani", "gokul",
        "vijay", "shruti", "suhani", "mohit", "kavitha", "rehan", "soham", "rupali",
    }
    speaker = data.get("speaker", "anushka")
    if speaker not in _VALID_SPEAKERS:
        speaker = "anushka"
    payload = {
        "inputs": [text],
        "target_language_code": lang,
        "speaker": speaker,
        "model": data.get("model", "bulbul:v2"),
        "pitch": data.get("pitch", 0),
        "pace": data.get("pace", 1.0),
        "loudness": data.get("loudness", 1.5),
        "speech_sample_rate": data.get("speech_sample_rate", 22050),
        "enable_preprocessing": False,
    }
    try:
        resp = await sarvam_client.post("/text-to-speech", json=payload)
        resp.raise_for_status()
        result = resp.json()
        audios = result.get("audios", [])
        if not audios:
            raise HTTPException(status_code=502, detail="Sarvam TTS returned no audio")
        out = {
            "audio_base64": audios[0],
            "language": lang,
            "format": "wav",
            "sample_rate": payload["speech_sample_rate"],
        }
        _set_content_cache(cache_key, out)
        return out
    except httpx.HTTPStatusError as e:
        logger.error(f"Sarvam TTS error {e.response.status_code} [{lang}]")
        raise HTTPException(status_code=e.response.status_code, detail="Sarvam TTS failed")
    except Exception as e:
        logger.error(f"Sarvam TTS exception: {type(e).__name__} [{lang}]")
        raise HTTPException(status_code=502, detail="Sarvam AI unreachable")

@api.post("/sarvam/transliterate")
async def sarvam_transliterate(data: dict):
    """Transliterate text between scripts via Sarvam AI."""
    if not sarvam_client:
        raise HTTPException(status_code=503, detail="Sarvam AI not configured")
    text = (data.get("text") or data.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    src = _normalise_lang(data.get("source_language_code", "en-IN"))
    tgt = _normalise_lang(data.get("target_language_code", "as-IN"))

    cache_key = _sarvam_cache_key("transliterate", {"text": text, "src": src, "tgt": tgt})
    cached = _get_content_cache(cache_key)
    if cached:
        return {**cached, "cached": True}

    payload = {
        "input": text,
        "source_language_code": src,
        "target_language_code": tgt,
        "spoken_language_code": src,
        "with_timestamps": False,
        "numerals_format": "international",
    }
    try:
        resp = await sarvam_client.post("/transliterate", json=payload)
        resp.raise_for_status()
        result = resp.json()
        out = {"transliterated_text": result.get("transliterated_text", ""), "source": src, "target": tgt}
        _set_content_cache(cache_key, out)
        return out
    except httpx.HTTPStatusError as e:
        logger.error(f"Sarvam transliterate error {e.response.status_code} [{src}->{tgt}]")
        raise HTTPException(status_code=e.response.status_code, detail="Sarvam transliteration failed")
    except Exception as e:
        logger.error(f"Sarvam transliterate exception: {type(e).__name__} [{src}->{tgt}]")
        raise HTTPException(status_code=502, detail="Sarvam AI unreachable")

# ─────────────────────────────────────────────
# BOT RENDER MIDDLEWARE (production SSR for AI crawlers)
# ─────────────────────────────────────────────
_BOT_UA_RE = re.compile(
    r"googlebot|bingbot|yandexbot|yandex|duckduckbot|slurp|baiduspider|"
    r"facebookexternalhit|twitterbot|linkedinbot|telegrambot|whatsapp|applebot|"
    r"ia_archiver|msnbot|ahrefsbot|semrushbot|petalbot|gptbot|oai-searchbot|"
    r"chatgpt-user|claudebot|anthropic-ai|perplexitybot|google-extended|"
    r"facebookbot|meta-externalagent|cohere-ai|bytespider|ccbot|applebot-extended",
    re.IGNORECASE,
)

_BOT_SKIP_PREFIXES = (
    "/api/", "/admin", "/chat", "/history", "/profile", "/static/",
    "/health", "/docs", "/openapi.json", "/assets/", "/icons/",
    "/fonts/", "/robots.txt", "/sitemap",
)

_VALID_PAGE_TYPES = {"notes", "definition", "important-questions", "mcqs", "examples"}

_bot_html_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=3600)


def _bot_html_response(html: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content=html, status_code=200,
        headers={"Cache-Control": "public, max-age=3600, s-maxage=86400", "X-Bot-Rendered": "1"},
    )


class BotRenderMiddleware(BaseHTTPMiddleware):
    """Intercept requests from bot user-agents and return pre-rendered HTML.

    Handles:
    - /                                  → homepage
    - /pyq/{slug}                        → PYQ HTML replica (html only)
    - /{board}/{class}/{subject}         → subject landing page
    - /{board}/{class}/{subject}/{topic}      → topic page (notes)
    - /{board}/{class}/{subject}/{topic}/{type} → topic page (typed)
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        ua = request.headers.get("user-agent", "")
        if not _BOT_UA_RE.search(ua):
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        for prefix in _BOT_SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        if "." in path.split("/")[-1]:
            return await call_next(request)

        parts = [p for p in path.split("/") if p]
        n = len(parts)

        if n == 0:
            cache_key = "_homepage_"
        elif n == 2 and parts[0] == "pyq":
            cache_key = f"_pyq_/{parts[1]}"
        elif n == 3:
            cache_key = f"_subj_/{parts[0]}/{parts[1]}/{parts[2]}"
        elif n in (4, 5):
            page_type_part = parts[4] if n == 5 else None
            if page_type_part and page_type_part not in _VALID_PAGE_TYPES:
                return await call_next(request)
            current_type = page_type_part or "notes"
            cache_key = f"{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/{current_type}"
        else:
            return await call_next(request)

        cached_html = _bot_html_cache.get(cache_key)
        if cached_html:
            return _bot_html_response(cached_html)

        try:
            _seo_port = int(os.environ.get("PORT", "8000"))
            api_base = f"http://localhost:{_seo_port}/api/seo"

            if cache_key == "_homepage_":
                api_url = f"{api_base}/html/homepage"
            elif cache_key.startswith("_pyq_/"):
                slug = parts[1]
                api_url = f"http://localhost:{_seo_port}/api/pyq/{slug}"
            elif cache_key.startswith("_subj_/"):
                api_url = f"{api_base}/html/subject/{parts[0]}/{parts[1]}/{parts[2]}"
            else:
                current_type = parts[4] if n == 5 else "notes"
                api_url = f"{api_base}/html/{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/{current_type}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                html_resp = await client.get(api_url)
            if html_resp.status_code != 200:
                return await call_next(request)
            ct = html_resp.headers.get("content-type", "")
            if "text/html" not in ct and "text/xml" not in ct:
                return await call_next(request)
            html_content = html_resp.text
            _bot_html_cache[cache_key] = html_content
            return _bot_html_response(html_content)
        except Exception as _bot_err:
            logger.debug(f"BotRenderMiddleware fallthrough: {_bot_err}")
            return await call_next(request)


class CmsNoIndexMiddleware(BaseHTTPMiddleware):
    """
    Hard scraper block for all /cms/{user_id}/* routes.
    - Adds X-Robots-Tag: noindex, nofollow on every CMS response.
    - Adds Cache-Control: private, no-store on every CMS response.
    - Blocks known scraper/bot user-agents with 403.
    Outbound web-search calls are structurally impossible in CMS handlers
    (they only call call_slm / MongoDB). This middleware provides defence-in-depth.
    """
    _CMS_BOT_UA_RE = re.compile(
        r"scrapy|wget|curl|python-requests|go-http-client|java/|"
        r"ahrefsbot|semrushbot|gptbot|claudebot|perplexitybot|"
        r"bingbot|googlebot|yandexbot|duckduckbot",
        re.IGNORECASE,
    )

    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if not path.startswith("/api/cms/"):
            return await call_next(request)
        ua = request.headers.get("user-agent", "")
        if ua and self._CMS_BOT_UA_RE.search(ua):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Automated access to personalized content is not permitted."},
                headers={
                    "X-Robots-Tag": "noindex, nofollow",
                    "Cache-Control": "private, no-store",
                },
            )
        # Set CMS context flag so that web-search/scrape functions raise 403 if called
        token = _cms_request_ctx.set(True)
        try:
            response = await call_next(request)
        finally:
            _cms_request_ctx.reset(token)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "private, no-store"
        return response


app.add_middleware(CmsNoIndexMiddleware)
app.add_middleware(BotRenderMiddleware)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=_CORS_ALLOW_CREDENTIALS,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    max_age=600,
)



# ─────────────────────────────────────────────
# SERVE REACT FRONTEND (SPA)
# ─────────────────────────────────────────────
FRONTEND_BUILD = ROOT_DIR / "frontend" / "build"
if FRONTEND_BUILD.is_dir():
    class CachedStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    # Only mount static if directory exists
    static_dir = FRONTEND_BUILD / "static"
    if static_dir.is_dir():
        app.mount("/static", CachedStaticFiles(directory=str(static_dir)), name="static-assets")

    _SPA_SKIP_PREFIXES = ("api/", "docs", "openapi.json", "health")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if any(full_path.startswith(p) for p in _SPA_SKIP_PREFIXES):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = FRONTEND_BUILD / full_path
        if full_path and file_path.is_file():
            if full_path in ("sw.js", "index.html"):
                return FileResponse(str(file_path), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_BUILD / "index.html"),
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

# ─────────────────────────────────────────────
# PHASE A: ENHANCED DASHBOARD METRICS
# ─────────────────────────────────────────────
@api.get("/admin/dashboard/metrics")
async def admin_dashboard_metrics(admin: dict = Depends(get_admin_user)):
    start = time.time()
    health_data = {}
    try:
        # Use the background-warmed cache if it is fresh (≤ 30 s old).
        # This avoids the 500 ms+ Supabase round-trip on every dashboard load.
        cache_age = time.time() - _health_deps_cache_at
        if _health_deps_cache and cache_age < _HEALTH_CACHE_TTL_S:
            h_resp = _health_deps_cache
        else:
            # Cache is cold (first load or stale) — fetch live with a 5 s guard
            h_resp = await asyncio.wait_for(_check_health_deps(), timeout=5)
        health_data = h_resp if isinstance(h_resp, dict) else {}
    except Exception:
        pass

    deps_status = {}
    if isinstance(health_data, dict):
        for k, v in health_data.items():
            if isinstance(v, dict):
                deps_status[k] = {
                    "status": v.get("status", "unknown"),
                    "latency_ms": v.get("latencyMs", 0),
                }

    users = await supa_list_users()
    total_users = len(users)
    paid_users = sum(1 for u in users if u.get("plan") in ("starter", "pro"))
    free_users = total_users - paid_users

    payments = await db.payments.find({}, {"_id": 0}).sort("verified_at", -1).to_list(500)
    total_revenue_inr = sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe") / 100
    total_revenue_usd = sum(p.get("amount_cents", 0) for p in payments if p.get("provider") == "stripe") / 100

    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    recent_payments = [p for p in payments if p.get("verified_at", "") >= thirty_days_ago]
    mrr_inr = sum(p.get("amount_paise", 0) for p in recent_payments if p.get("provider") != "stripe") / 100

    seo_count = await db.seo_topics.count_documents({}) if await is_mongo_available() else 0
    seo_published = await db.seo_pages.count_documents({"status": "published"}) if await is_mongo_available() else 0

    elapsed = round((time.time() - start) * 1000, 1)

    return {
        "dependencies": deps_status,
        "response_time_ms": elapsed,
        "users": {"total": total_users, "paid": paid_users, "free": free_users},
        "revenue": {"total_inr": total_revenue_inr, "total_usd": total_revenue_usd, "mrr_inr": mrr_inr},
        "seo": {"topics": seo_count, "published_pages": seo_published},
        "payments_count": len(payments),
    }

async def _check_health_deps():
    result = {}
    try:
        t0 = time.time()
        await db.command("ping")
        result["mongodb"] = {"status": "ok", "latencyMs": round((time.time() - t0) * 1000, 1)}
    except Exception:
        result["mongodb"] = {"status": "error", "latencyMs": 0}
    try:
        if pg_pool:
            t0 = time.time()
            async with pg_pool.acquire() as conn:
                await conn.execute("SELECT 1")
            result["postgresql"] = {"status": "ok", "latencyMs": round((time.time() - t0) * 1000, 1)}
        else:
            result["postgresql"] = {"status": "not_configured", "latencyMs": 0}
    except Exception:
        result["postgresql"] = {"status": "error", "latencyMs": 0}
    try:
        t0 = time.time()
        _redis_get_search("__healthcheck__")
        result["redis"] = {"status": "ok", "latencyMs": round((time.time() - t0) * 1000, 1)}
    except Exception:
        result["redis"] = {"status": "error", "latencyMs": 0}
    try:
        if supa and SUPABASE_URL:
            # Use the best available key: service key → anon key.
            # Direct HTTP GET to /rest/v1/ — no SQL round-trip, just TLS keep-alive.
            _supa_key        = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
            _supa_health_url = SUPABASE_URL.rstrip("/") + "/rest/v1/"
            _supa_headers    = {"apikey": _supa_key, "Authorization": f"Bearer {_supa_key}"}
            t0 = time.time()
            async with httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=1.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=60),
            ) as _hc:
                _r = await _hc.get(_supa_health_url, headers=_supa_headers)
                _r.raise_for_status()
            result["supabase"] = {"status": "ok", "latencyMs": round((time.time() - t0) * 1000, 1)}
        else:
            result["supabase"] = {"status": "not_configured", "latencyMs": 0}
    except Exception as _se:
        logger.debug(f"Supabase health check failed: {_se}")
        result["supabase"] = {"status": "error", "latencyMs": 0}
    return result


_cache_stats_log_counter = 0   # increments each 25 s cycle; log every 12 cycles = 5 min

async def _bg_health_loop():
    """Warm the health-deps cache every 25 s so dashboard reads are near-instant.
    Also emits a structured cache_stats log every 5 minutes."""
    global _health_deps_cache, _health_deps_cache_at, _cache_stats_log_counter
    await asyncio.sleep(8)                  # let startup settle first
    while True:
        try:
            fresh = await asyncio.wait_for(_check_health_deps(), timeout=10)
            _health_deps_cache    = fresh
            _health_deps_cache_at = time.time()
        except Exception as _e:
            logger.debug(f"Health bg loop: {_e}")

        # Emit cache hit-rate log every 5 minutes
        _cache_stats_log_counter += 1
        if _cache_stats_log_counter % 12 == 0:
            total = _redis_hit_count + _redis_miss_count
            hit_rate = round(_redis_hit_count / max(1, total), 3)
            logger.info(
                f"cache_stats hit_rate={hit_rate} "
                f"hits={_redis_hit_count} misses={_redis_miss_count} total={total}"
            )

        await asyncio.sleep(25)


# ─────────────────────────────────────────────
# PRODUCTION ALERTING SYSTEM
# ─────────────────────────────────────────────

_ALERT_COOLDOWN_S = 1800   # 30 min between same alert type
_alert_last_fired: dict = {}   # { "alert_key": timestamp }
_ALERT_THRESHOLDS = {
    "latency_p95_ms": 2000,
    "error_rate_pct": 5.0,
    "fallback_rate_pct": 50.0,
}

async def _dispatch_alert(alert_type: str, title: str, body: str):
    """Send alert via email (Resend) and/or webhook. Respects cooldown."""
    now = _time_mod.time()
    if now - _alert_last_fired.get(alert_type, 0) < _ALERT_COOLDOWN_S:
        return
    _alert_last_fired[alert_type] = now
    logger.warning(f"ALERT [{alert_type}] {title}: {body}")

    # 1) Email alert via Resend (to admin)
    try:
        admin_email = os.environ.get("ALERT_EMAIL", "").strip()
        resend_key = os.environ.get("RESEND_API_KEY", "").strip()
        if admin_email and resend_key:
            import resend as _resend_sdk
            _resend_sdk.api_key = resend_key
            _resend_sdk.Emails.send({
                "from": EMAIL_FROM,
                "to": [admin_email],
                "subject": f"🚨 Syrabit Alert: {title}",
                "html": f"<h2>{title}</h2><p>{body}</p><p style='color:#888'>Alert type: {alert_type}<br>Cooldown: {_ALERT_COOLDOWN_S // 60} min</p>",
            })
    except Exception as e:
        logger.debug(f"Alert email failed: {e}")

    # 2) Webhook alert (Slack / Discord / generic)
    try:
        webhook_url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
        if webhook_url:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(webhook_url, json={
                    "text": f"🚨 *{title}*\n{body}",
                    "alert_type": alert_type,
                    "service": "syrabit-api",
                })
    except Exception as e:
        logger.debug(f"Alert webhook failed: {e}")

    # 3) Persist to db.alerts for admin dashboard visibility
    try:
        await db.alerts.insert_one({
            "type": alert_type,
            "title": title,
            "body": body,
            "fired_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        })
    except Exception:
        pass


async def _alerting_loop():
    """Background loop: checks metrics every 2 minutes for alert conditions."""
    await asyncio.sleep(60)   # let startup + first metrics settle
    _prev_errors = 0
    _prev_requests = 0
    _prev_fallbacks = 0
    _prev_llm_calls = 0
    while True:
        try:
            # ── 1. Error rate in last window ──
            curr_errors = _metrics.error_count
            curr_requests = _metrics.request_count
            delta_err = curr_errors - _prev_errors
            delta_req = curr_requests - _prev_requests
            _prev_errors = curr_errors
            _prev_requests = curr_requests
            if delta_req > 20:   # need minimum sample
                err_rate = (delta_err / delta_req) * 100
                if err_rate > _ALERT_THRESHOLDS["error_rate_pct"]:
                    await _dispatch_alert(
                        "high_error_rate",
                        "Error rate spike",
                        f"{err_rate:.1f}% errors in last 2 min ({delta_err}/{delta_req} requests)",
                    )

            # ── 2. LLM latency (p95 from _chat_latencies ring buffer) ──
            try:
                recent_lats = [e["latency_ms"] for e in _chat_latencies[-100:]]
                if len(recent_lats) >= 5:
                    lats_sorted = sorted(recent_lats)
                    p95 = lats_sorted[int(len(lats_sorted) * 0.95)]
                    if p95 > _ALERT_THRESHOLDS["latency_p95_ms"]:
                        await _dispatch_alert(
                            "high_latency",
                            "LLM latency spike",
                            f"p95={int(p95)}ms (threshold: {_ALERT_THRESHOLDS['latency_p95_ms']}ms, sample={len(recent_lats)})",
                        )
            except Exception:
                pass

            # ── 3. Fallback rate (from cost log provider != primary) ──
            recent_cost = _llm_cost_log[-100:]
            if len(recent_cost) >= 10:
                primary_model = LLM_MODEL
                fallbacks = sum(1 for e in recent_cost if e.get("model") != primary_model)
                fb_rate = (fallbacks / len(recent_cost)) * 100
                if fb_rate > _ALERT_THRESHOLDS["fallback_rate_pct"]:
                    await _dispatch_alert(
                        "high_fallback_rate",
                        "LLM fallback rate high",
                        f"{fb_rate:.0f}% of last {len(recent_cost)} calls used fallback models "
                        f"(primary: {primary_model})",
                    )

        except Exception as exc:
            logger.debug(f"Alerting loop error: {exc}")

        await asyncio.sleep(120)   # check every 2 minutes


# Admin endpoints for alert management
@api.get("/admin/alerts")
async def admin_list_alerts(limit: int = 50, admin: dict = Depends(get_admin_user)):
    """List recent alerts."""
    items = await db.alerts.find({}).sort("fired_at", -1).limit(limit).to_list(limit)
    for i in items:
        i["id"] = str(i.pop("_id"))
    return {"alerts": items, "thresholds": _ALERT_THRESHOLDS}

@api.patch("/admin/alerts/{alert_id}/acknowledge")
async def admin_acknowledge_alert(alert_id: str, admin: dict = Depends(get_admin_user)):
    from bson import ObjectId as _ObjId
    try:
        oid = _ObjId(alert_id)
    except Exception:
        raise HTTPException(400, "Invalid alert_id")
    await db.alerts.update_one({"_id": oid}, {"$set": {"acknowledged": True}})
    return {"ok": True}

@api.put("/admin/alerts/thresholds")
async def admin_update_alert_thresholds(data: dict, admin: dict = Depends(get_admin_user)):
    """Update alert thresholds at runtime. Keys: latency_p95_ms, error_rate_pct, fallback_rate_pct."""
    for key in ("latency_p95_ms", "error_rate_pct", "fallback_rate_pct"):
        if key in data:
            _ALERT_THRESHOLDS[key] = float(data[key])
    return {"thresholds": _ALERT_THRESHOLDS}


# ─────────────────────────────────────────────
# PHASE B: AI CONTENT STUDIO
# ─────────────────────────────────────────────
class StudioParseRequest(BaseModel):
    raw_text: str
    subject: str = ""
    chapter: str = ""

@api.post("/admin/studio/parse")
async def admin_studio_parse(body: StudioParseRequest, admin: dict = Depends(get_admin_user)):
    if not body.raw_text.strip():
        raise HTTPException(400, "Empty text")
    prompt = f"""You are an educational content parser and GEO (Generative Engine Optimization) specialist for AssamBoard students (AHSEC, DEGREE, SEBA) in Assam.
Analyze the following raw educational text and categorize it into structured blocks.
Return a JSON array of blocks, each with: type (one of: "summary", "definition", "example", "pyq", "formula", "note", "faq"), title, content.

GEO REQUIREMENTS — weave these naturally into every block:
- Cite AHSEC board exam frequency (e.g. "Asked in AHSEC 2019, 2021, 2023")
- Include authoritative references (textbook name, author, page when available)
- Add "According to the AHSEC syllabus..." or "As per NCERT..." framing
- For definitions, start with the canonical textbook wording
- For PYQ blocks, note mark allocation and year
- Generate 1-2 FAQ blocks with question+answer pairs students commonly search for

Subject: {body.subject or 'General'}
Chapter: {body.chapter or 'General'}

Raw text:
---
{body.raw_text[:8000]}
---

Return ONLY valid JSON array. Example:
[{{"type":"summary","title":"Chapter Overview","content":"..."}},{{"type":"definition","title":"Term Name","content":"..."}},{{"type":"faq","title":"FAQ: What is...?","content":"Q: What is...?\\nA: According to NCERT, ..."}}]"""

    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=4096)
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            blocks = json.loads(json_match.group())
            return {"blocks": blocks, "raw_length": len(body.raw_text), "block_count": len(blocks)}
        return {"blocks": [{"type": "note", "title": "Parsed Content", "content": result}], "raw_length": len(body.raw_text), "block_count": 1}
    except Exception as e:
        logger.error(f"Studio parse error: {e}")
        raise HTTPException(500, "AI parsing failed")

class StudioPublishRequest(BaseModel):
    title: str
    slug: str
    blocks: list
    subject_id: str = ""
    chapter_id: str = ""
    board: str = "ahsec"
    class_slug: str = "class-12"
    subject_slug: str = ""
    meta_description: str = ""
    keywords: list = []
    board_id: str = ""
    class_id: str = ""
    stream_id: str = ""
    is_revision: bool = False
    parent_revision_id: str = ""


@api.post("/admin/studio/publish")
async def admin_studio_publish(body: StudioPublishRequest, admin: dict = Depends(get_admin_user)):
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. Resolve board / class slugs from DB if IDs supplied ────────────────
    board_slug = body.board
    class_slug_resolved = body.class_slug
    if body.board_id:
        bd = await db.boards.find_one({"id": body.board_id}, {"_id": 0})
        if bd:
            board_slug = bd.get("slug") or _slugify(bd.get("name", body.board))
    if body.class_id:
        cd = await db.classes.find_one({"id": body.class_id}, {"_id": 0})
        if cd:
            class_slug_resolved = cd.get("slug") or _slugify(cd.get("name", body.class_slug))

    subject_slug_resolved = body.subject_slug or body.slug.split("-")[0]
    publish_url = f"/{board_slug}/{class_slug_resolved}/{subject_slug_resolved}/{body.slug}"

    # ── 2. Build HTML from blocks ──────────────────────────────────────────────
    html_parts = []
    for block in body.blocks:
        btype = re.sub(r'[^a-z]', '', block.get("type", "note"))
        btitle  = _html_mod.escape(str(block.get("title", "")))
        bcontent = _html_mod.escape(str(block.get("content", "")))
        html_parts.append(f'<section class="content-block {btype}"><h3>{btitle}</h3><div>{bcontent}</div></section>')
    page_html = "\n".join(html_parts)

    # ── 3. Upsert SEO topic ────────────────────────────────────────────────────
    topic_doc = {
        "title": body.title,
        "slug": body.slug,
        "board": board_slug,
        "class_slug": class_slug_resolved,
        "subject_slug": subject_slug_resolved,
        "meta_description": body.meta_description or body.title,
        "keywords": body.keywords,
        "status": "published",
        "board_id": body.board_id,
        "class_id": body.class_id,
        "stream_id": body.stream_id,
        "updated_at": now_iso,
        "source": "studio",
    }
    # Persist subject_id and chapter_id linkage when provided — required for
    # SEO topic → chapter cross-linking and AI chat source navigation.
    if body.subject_id:
        topic_doc["subject_id"] = body.subject_id
    if hasattr(body, "chapter_id") and body.chapter_id:
        topic_doc["chapter_id"] = body.chapter_id
    existing_topic = await db.seo_topics.find_one({"slug": body.slug}, {"_id": 0, "created_at": 1})
    if not existing_topic:
        topic_doc["created_at"] = now_iso
    await db.seo_topics.update_one({"slug": body.slug}, {"$set": topic_doc}, upsert=True)

    # ── 4. Upsert SEO page (or create revision copy) ───────────────────────────
    page_doc = {
        "topic_slug": body.slug,
        "board": board_slug,
        "class_slug": class_slug_resolved,
        "subject_slug": subject_slug_resolved,
        "html": page_html,
        "blocks": body.blocks,
        "status": "published",
        "page_type": "notes",
        "updated_at": now_iso,
        "source": "studio",
    }
    if body.is_revision and body.parent_revision_id:
        from datetime import date as _date
        rev_slug = f"{body.slug}-rev-{_date.today().isoformat()}"
        revision_doc = {
            **page_doc,
            "topic_slug": rev_slug,
            "is_revision": True,
            "parent_revision_id": body.parent_revision_id,
            "created_at": now_iso,
        }
        await db.seo_pages.insert_one(revision_doc)
        logger.info(f"Studio revision created: {rev_slug} ← {body.parent_revision_id}")
    else:
        existing_page = await db.seo_pages.find_one({"topic_slug": body.slug, "page_type": "notes"}, {"_id": 0, "created_at": 1})
        if not existing_page:
            page_doc["created_at"] = now_iso
        await db.seo_pages.update_one(
            {"topic_slug": body.slug, "page_type": "notes"},
            {"$set": page_doc},
            upsert=True,
        )

    # ── 4b. Embed page for vector search ─────────────────────────────────────
    # Run fire-and-forget so publish response is never delayed by embedding
    _embed_content = " ".join(
        (b.get("content") or b.get("text") or "")
        for b in (body.blocks or []) if isinstance(b, dict)
    )
    if not _embed_content:
        _embed_content = body.title or ""
    asyncio.create_task(_embed_and_store_page(body.slug, _embed_content))

    # ── 5. Auto-create syllabus CMS stub when syllabus block detected ──────────
    syllabus_block = next((b for b in body.blocks if b.get("type") == "syllabus"), None)
    if syllabus_block and body.subject_id:
        syl_title = f"{body.title} — Syllabus Scope"
        syl_slug  = f"{body.slug}-syllabus"
        syl_id    = str(uuid.uuid4())
        syl_doc = {
            "id":               syl_id,
            "title":            syl_title,
            "seo_slug":         syl_slug,
            "content":          syllabus_block.get("content", ""),
            "type":             "syllabus",
            "status":           "draft",
            "linked_subject_id": body.subject_id,
            "linked_board_id":  body.board_id,
            "linked_class_id":  body.class_id,
            "linked_stream_id": body.stream_id,
            "source":           "studio-auto",
            "created_at":       now_iso,
            "updated_at":       now_iso,
        }
        await db.cms_documents.update_one(
            {"seo_slug": syl_slug},
            {"$set": syl_doc},
            upsert=True,
        )
        logger.info(f"Syllabus CMS stub auto-created: {syl_slug}")

    logger.info(f"Studio published: {body.slug} → {publish_url}")
    return {"success": True, "slug": body.slug, "url": publish_url}


# ── SEO / GEO Metadata Generator ──────────────────────────────────────────────

@api.post("/admin/seo/generate")
async def generate_seo_metadata(data: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Generate maximum SEO + GEO-rich page title and meta description using AI."""
    title          = (data.get("title") or "").strip()
    content_snippet= (data.get("content") or "")[:3000].strip()
    primary_keyword= (data.get("primary_keyword") or "").strip()
    seo_tags       = (data.get("seo_tags") or "").strip()
    linked_scope   = (data.get("linked_scope") or "").strip()
    board          = (data.get("board") or "AHSEC").strip()
    class_name     = (data.get("class_name") or "").strip()
    subject        = (data.get("subject") or "").strip()

    prompt = f"""You are an expert SEO strategist and GEO (Generative Engine Optimization) specialist for Syrabit.ai, an educational platform serving AHSEC/SCERT Class 11 & 12 and Degree students in Assam, India.

Your task: generate maximum-impact SEO and GEO metadata for a single educational page.

Page context:
- Title/Topic:       {title or '(not set)'}
- Primary Keyword:   {primary_keyword or '(derive from topic)'}
- Subject/Chapter:   {subject or '(educational content)'}
- Board:             {board}
- Class:             {class_name or '(not specified)'}
- Syllabus scope:    {linked_scope or '(not linked)'}
- Existing tags:     {seo_tags or '(none)'}
- Content snippet:   {content_snippet[:600] or '(not provided)'}

Rules for SEO Title (55–65 characters):
- Primary keyword FIRST (exact match for query alignment)
- Include board identifier: "AHSEC" or "Class 11/12" as relevant
- Include content type: Notes / PYQ / Guide / Explained / MCQ
- Power word from: Complete, Free, Best, Official, Detailed, Easy, Quick
- End exactly with " | Syrabit" (saves chars vs "Syrabit.ai")
- Total: 55–65 characters, never truncated by Google

Rules for Meta Description (148–158 characters — this range triggers full-length snippets):
- Open with the primary keyword or question students actually search
- Mention content types covered: notes, definitions, examples, PYQ, MCQs
- Include one board-authority signal: "per AHSEC {board} syllabus" or "NCERT-aligned"
- Include one action verb: Access, Download, Study, Get, Master
- End with a micro-CTA: "Free on Syrabit." or "Syrabit.ai — free."
- 148–158 characters EXACTLY (count carefully)

Rules for Primary Keyword (for <meta name="keywords"> and schema):
- 4–7 words, exact-match the most-searched student query
- Format: "[Subject] [topic] [board] [class]" or "AHSEC [subject] [topic] notes"

Rules for SEO Tags (8–12 comma-separated tags):
- Mix: exact-match head terms + long-tail variants + board-specific + question-format
- Include: board name, class, subject, topic, "notes", "PYQ", "Assam", "AHSEC 2024-25"

Rules for GEO Authority Phrases (3 phrases, for AI citation eligibility):
- Start with "According to", "As per", "Based on" followed by a recognized source
- Examples: "As per AHSEC 2024–25 syllabus", "According to NCERT textbook", "Based on SCERT Assam guidelines"
- Must sound like authoritative citations an AI would quote

Return ONLY valid JSON — no markdown fences, no commentary:
{{"seo_title":"...","meta_description":"...","primary_keyword":"...","seo_tags":"tag1, tag2, tag3, tag4, tag5, tag6, tag7, tag8","geo_phrases":["...","...","..."],"char_counts":{{"title":0,"meta":0}}}}"""

    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=700)
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON in LLM response")
        obj = json.loads(json_match.group())
        # Enforce hard limits
        seo_title = (obj.get("seo_title") or title or "Educational Notes | Syrabit")[:70]
        meta_desc = (obj.get("meta_description") or "")[:160]
        obj["seo_title"]       = seo_title
        obj["meta_description"]= meta_desc
        obj["char_counts"]     = {"title": len(seo_title), "meta": len(meta_desc)}
        logger.info(f"SEO generate: title={len(seo_title)}ch meta={len(meta_desc)}ch")
        return obj
    except Exception as e:
        logger.error(f"SEO generate error: {e}")
        raise HTTPException(500, "AI SEO generation failed — check logs")


# ── Studio Draft CRUD ─────────────────────────────────────────────────────────

@api.get("/admin/studio/drafts")
async def list_studio_drafts(admin: dict = Depends(get_admin_user)):
    """List all studio drafts, newest first."""
    drafts = await db.studio_drafts.find({}, {"_id": 0}).sort("updated_at", -1).limit(50).to_list(50)
    return drafts


@api.post("/admin/studio/drafts")
async def save_studio_draft(data: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Save or update a studio draft by slug."""
    slug = data.get("slug", "").strip()
    draft_id = data.get("id") or str(uuid.uuid4())
    now_iso  = datetime.now(timezone.utc).isoformat()
    draft = {
        "id":           draft_id,
        "title":        data.get("title", "Untitled"),
        "slug":         slug,
        "blocks":       data.get("blocks", []),
        "subject_id":   data.get("subject_id", ""),
        "board_id":     data.get("board_id", ""),
        "class_id":     data.get("class_id", ""),
        "stream_id":    data.get("stream_id", ""),
        "subject_slug": data.get("subject_slug", ""),
        "updated_at":   now_iso,
    }
    existing = await db.studio_drafts.find_one({"slug": slug} if slug else {"id": draft_id}, {"_id": 0, "created_at": 1})
    if not existing:
        draft["created_at"] = now_iso
    filter_q = {"slug": slug} if slug else {"id": draft_id}
    await db.studio_drafts.update_one(filter_q, {"$set": draft}, upsert=True)
    logger.info(f"Studio draft saved: {draft_id} ({slug})")
    return {"id": draft_id, "message": "Draft saved"}


@api.delete("/admin/studio/drafts/{draft_id}")
async def delete_studio_draft(draft_id: str, admin: dict = Depends(get_admin_user)):
    await db.studio_drafts.delete_one({"id": draft_id})
    return {"message": "Draft deleted"}


@api.post("/admin/studio/drafts/{draft_id}/publish")
async def publish_studio_draft(draft_id: str, data: dict = Body(default={}), admin: dict = Depends(get_admin_user)):
    """Publish a saved draft. Optional body overrides: board_id, class_id, is_revision, parent_revision_id."""
    draft = await db.studio_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    pub_body = StudioPublishRequest(
        title            = draft.get("title", "Untitled"),
        slug             = draft.get("slug", draft_id),
        blocks           = draft.get("blocks", []),
        subject_id       = draft.get("subject_id", ""),
        board_id         = data.get("board_id", draft.get("board_id", "")),
        class_id         = data.get("class_id", draft.get("class_id", "")),
        stream_id        = data.get("stream_id", draft.get("stream_id", "")),
        subject_slug     = draft.get("subject_slug", ""),
        is_revision      = data.get("is_revision", False),
        parent_revision_id = data.get("parent_revision_id", ""),
    )
    result = await admin_studio_publish(pub_body, admin)
    await db.studio_drafts.update_one({"id": draft_id}, {"$set": {"last_published_at": datetime.now(timezone.utc).isoformat()}})
    return {**result, "draft_id": draft_id}


# ─────────────────────────────────────────────
# PHASE C: ADVANCED ANALYTICS
# ─────────────────────────────────────────────
@api.get("/admin/analytics/funnel")
async def admin_analytics_funnel(admin: dict = Depends(get_admin_user)):
    users = await supa_list_users()
    total = len(users)
    chatted = 0
    paid = 0
    for u in users:
        if u.get("credits_used", 0) > 0:
            chatted += 1
        if u.get("plan") in ("starter", "pro"):
            paid += 1

    payments = await db.payments.find({}, {"_id": 0}).to_list(5000)
    total_revenue = sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe") / 100

    return {
        "funnel": [
            {"stage": "Signed Up", "count": total, "pct": 100},
            {"stage": "Used Chat", "count": chatted, "pct": round(chatted / max(total, 1) * 100, 1)},
            {"stage": "Paid User", "count": paid, "pct": round(paid / max(total, 1) * 100, 1)},
        ],
        "revenue_per_user": round(total_revenue / max(paid, 1), 2),
        "conversion_rate": round(paid / max(total, 1) * 100, 2),
    }

@api.get("/admin/analytics/content-heatmap")
async def admin_analytics_content_heatmap(admin: dict = Depends(get_admin_user)):
    pipeline = [
        {"$group": {"_id": "$subject_name", "views": {"$sum": 1}}},
        {"$sort": {"views": -1}},
        {"$limit": 30},
    ]
    try:
        results = await db.analytics.aggregate(pipeline).to_list(30)
    except Exception:
        results = []

    top_searches = []
    try:
        search_pipeline = [
            {"$match": {"type": "search"}},
            {"$group": {"_id": "$query", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]
        top_searches = await db.analytics.aggregate(search_pipeline).to_list(20)
    except Exception:
        pass

    return {
        "top_subjects": [{"name": r["_id"] or "Unknown", "views": r["views"]} for r in results if r["_id"]],
        "top_searches": [{"query": r["_id"] or "Unknown", "count": r["count"]} for r in top_searches if r["_id"]],
    }

@api.get("/admin/analytics/revenue")
async def admin_analytics_revenue(days: int = 30, admin: dict = Depends(get_admin_user)):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    payments = await db.payments.find(
        {"verified_at": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("verified_at", 1).to_list(5000)

    daily = {}
    for p in payments:
        day = p.get("verified_at", "")[:10]
        if not day:
            continue
        if day not in daily:
            daily[day] = {"date": day, "revenue_inr": 0, "count": 0}
        daily[day]["revenue_inr"] += p.get("amount_paise", 0) / 100
        daily[day]["count"] += 1

    users = await supa_list_users()
    cohorts = {"free": 0, "starter": 0, "pro": 0}
    for u in users:
        plan = u.get("plan", "free")
        cohorts[plan] = cohorts.get(plan, 0) + 1

    return {
        "daily_revenue": sorted(daily.values(), key=lambda x: x["date"]),
        "cohorts": cohorts,
        "total_payments": len(payments),
    }

@api.get("/admin/analytics/predictor")
async def admin_analytics_predictor(admin: dict = Depends(get_admin_user)):
    now = datetime.now(timezone.utc)
    thirty_ago = (now - timedelta(days=30)).isoformat()
    sixty_ago = (now - timedelta(days=60)).isoformat()

    recent = await db.payments.count_documents({"verified_at": {"$gte": thirty_ago}})
    prior = await db.payments.count_documents({"verified_at": {"$gte": sixty_ago, "$lt": thirty_ago}})

    recent_rev = 0
    async for p in db.payments.find({"verified_at": {"$gte": thirty_ago}}, {"_id": 0}):
        recent_rev += p.get("amount_paise", 0) / 100

    growth_rate = ((recent - prior) / max(prior, 1)) if prior > 0 else 0
    predicted_mrr = round(recent_rev * (1 + growth_rate * 0.5), 2)

    users_this_month = await db.users.count_documents({"created_at": {"$gte": thirty_ago}})
    users_last_month = await db.users.count_documents({"created_at": {"$gte": sixty_ago, "$lt": thirty_ago}})

    return {
        "current_mrr_inr": recent_rev,
        "predicted_mrr_inr": predicted_mrr,
        "growth_rate_pct": round(growth_rate * 100, 1),
        "payments_this_month": recent,
        "payments_last_month": prior,
        "signups_this_month": users_this_month,
        "signups_last_month": users_last_month,
    }


@api.get("/admin/analytics/daily")
async def admin_analytics_daily(
    days: int = 30,
    admin: dict = Depends(get_admin_user),
):
    """
    Per-day analytics for the Daily Analytics panel.
    Returns visitors, page_views, signups, messages, and AI interactions
    for each day in the requested range (default: last 30 days).
    Prefers GA4 for visitor/page-view data and falls back to MongoDB.
    """
    now = datetime.now(timezone.utc)

    # Build a lookup dict indexed by YYYY-MM-DD for easy merging
    day_keys = [(now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d") for i in range(days)]
    daily: dict[str, dict] = {
        d: {
            "date": d,
            "visitors": 0,
            "page_views": 0,
            "signups": 0,
            "messages": 0,
            "ai_interactions": 0,
            "sessions": 0,
            "bounce_rate": None,
            "avg_session_duration": None,
        }
        for d in day_keys
    }

    # ── 1. Visitor / page-view data ──────────────────────────────────────────
    # Try GA4 first
    try:
        ga4_resp = await ga4_client.run_report(
            dimensions=["date"],
            metrics=["activeUsers", "screenPageViews", "sessions", "bounceRate", "averageSessionDuration"],
            date_ranges=[{"startDate": f"{days}daysAgo", "endDate": "today"}],
            order_bys=[{"dimension": {"dimensionName": "date"}}],
            limit=days + 1,
        )
        if ga4_resp and ga4_resp.get("rows"):
            for row in ga4_resp["rows"]:
                raw_date = row["dimensionValues"][0]["value"]
                d = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                if d in daily:
                    mv = row["metricValues"]
                    daily[d]["visitors"] = int(mv[0]["value"]) if mv[0]["value"] else 0
                    daily[d]["page_views"] = int(mv[1]["value"]) if mv[1]["value"] else 0
                    daily[d]["sessions"] = int(mv[2]["value"]) if mv[2]["value"] else 0
                    try:
                        daily[d]["bounce_rate"] = round(float(mv[3]["value"]) * 100, 1)
                    except Exception:
                        pass
                    try:
                        daily[d]["avg_session_duration"] = round(float(mv[4]["value"]), 1)
                    except Exception:
                        pass
    except Exception:
        # Fall back to MongoDB page_views collection
        try:
            cutoff_str = day_keys[0]
            pipeline = [
                {"$match": {"date": {"$gte": cutoff_str}}},
                {
                    "$group": {
                        "_id": "$date",
                        "visitors": {"$addToSet": "$visitor_id"},
                        "page_views": {"$sum": 1},
                    }
                },
            ]
            rows = await db.page_views.aggregate(pipeline).to_list(days + 5)
            for row in rows:
                d = row["_id"]
                if d in daily:
                    daily[d]["visitors"] = len(row["visitors"])
                    daily[d]["page_views"] = row["page_views"]
        except Exception:
            pass

    # ── 2. Signups (Supabase users by created_at date) ───────────────────────
    try:
        users = await supa_list_users()
        for u in users:
            d = (u.get("created_at") or "")[:10]
            if d in daily:
                daily[d]["signups"] += 1
    except Exception:
        pass

    # ── 3. Messages (conversations collection) ──────────────────────────────
    try:
        cutoff_dt = (now - timedelta(days=days)).isoformat()
        pipeline_msgs = [
            {"$match": {"created_at": {"$gte": cutoff_dt}}},
            {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "count": {"$sum": "$message_count"}}},
        ]
        msg_rows = await db.conversations.aggregate(pipeline_msgs).to_list(days + 5)
        for row in msg_rows:
            d = row["_id"]
            if d in daily:
                daily[d]["messages"] = row["count"] or 0
    except Exception:
        pass

    # ── 4. AI interactions (analytics events of type ask_ai_click) ───────────
    try:
        cutoff_dt = (now - timedelta(days=days)).isoformat()
        pipeline_ai = [
            {"$match": {"type": "ask_ai_click", "created_at": {"$gte": cutoff_dt}}},
            {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "count": {"$sum": 1}}},
        ]
        ai_rows = await db.analytics.aggregate(pipeline_ai).to_list(days + 5)
        for row in ai_rows:
            d = row["_id"]
            if d in daily:
                daily[d]["ai_interactions"] = row["count"]
    except Exception:
        pass

    result = sorted(daily.values(), key=lambda x: x["date"])

    # Compute day-over-day deltas for summary cards (last day vs second-to-last)
    def pct_change(a, b):
        if b == 0:
            return None
        return round((a - b) / b * 100, 1)

    today_data = result[-1] if result else {}
    prev_data = result[-2] if len(result) >= 2 else {}

    summary = {
        "visitors": {
            "today": today_data.get("visitors", 0),
            "change_pct": pct_change(today_data.get("visitors", 0), prev_data.get("visitors", 0)),
        },
        "page_views": {
            "today": today_data.get("page_views", 0),
            "change_pct": pct_change(today_data.get("page_views", 0), prev_data.get("page_views", 0)),
        },
        "signups": {
            "today": today_data.get("signups", 0),
            "change_pct": pct_change(today_data.get("signups", 0), prev_data.get("signups", 0)),
        },
        "messages": {
            "today": today_data.get("messages", 0),
            "change_pct": pct_change(today_data.get("messages", 0), prev_data.get("messages", 0)),
        },
        "ai_interactions": {
            "today": today_data.get("ai_interactions", 0),
            "change_pct": pct_change(today_data.get("ai_interactions", 0), prev_data.get("ai_interactions", 0)),
        },
    }

    return {"daily": result, "summary": summary, "days": days}


# ─────────────────────────────────────────────
# GOOGLE ANALYTICS 4 OAUTH SETUP
# ─────────────────────────────────────────────
@api.get("/admin/ga4/status")
async def ga4_status(admin: dict = Depends(get_admin_user)):
    token_env = os.getenv("GA4_REFRESH_TOKEN", "")
    # Also check db.api_config in case token was persisted there
    token_db = ""
    try:
        cfg = await db.api_config.find_one({}, {"ga4": 1})
        token_db = (cfg or {}).get("ga4", {}).get("refresh_token", "")
    except Exception:
        pass
    connected = bool(token_env or token_db)
    return {
        "connected": connected,
        "token_source": "env" if token_env else ("db" if token_db else "none"),
        "property_id": os.getenv("GA4_PROPERTY_ID", ""),
        "client_id_set": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")),
        "client_secret_set": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
    }


@api.get("/admin/ga4/auth-url")
async def ga4_auth_url(redirect_uri: str, admin: dict = Depends(get_admin_user)):
    url = ga4_client.get_oauth_url(redirect_uri)
    return {"url": url}


@api.post("/admin/ga4/connect")
async def ga4_connect(
    code: str = Body(...),
    redirect_uri: str = Body(...),
    admin: dict = Depends(get_admin_user),
):
    tokens = await ga4_client.exchange_code_for_tokens(code, redirect_uri)
    if not tokens or "refresh_token" not in tokens:
        raise HTTPException(status_code=400, detail="Failed to exchange code — ensure you selected the correct Google account with GA4 access and that you clicked 'Allow'.")
    refresh_token = tokens["refresh_token"]
    # Persist to MongoDB so it survives process restarts
    await db.api_config.update_one({}, {"$set": {"ga4.refresh_token": refresh_token}}, upsert=True)
    # Also update current process env so GA4 works immediately without restart
    os.environ["GA4_REFRESH_TOKEN"] = refresh_token
    logger.info("GA4 refresh token stored in db.api_config and os.environ")
    return {
        "status": "connected",
        "message": "GA4 connected. Token persisted to database — no Replit Secret needed.",
    }


@api.get("/admin/ga4/test")
async def ga4_test(admin: dict = Depends(get_admin_user)):
    stats = await ga4_client.get_visitor_stats_ga4(days=7)
    if stats is None:
        return {"ok": False, "reason": "GA4 not configured or refresh token missing"}
    return {"ok": True, "stats": stats}


# ─────────────────────────────────────────────
# VERTEX AI / GEMINI POWERED SERVICES
# ─────────────────────────────────────────────

@api.get("/admin/vertex/health")
async def vertex_health(admin: dict = Depends(get_admin_user)):
    """Check status of all Vertex AI / Gemini services."""
    return await vertex_services.health_check()


@api.post("/admin/vertex/translate")
async def vertex_translate(
    text: str = Body(...),
    target_lang: str = Body("as"),
    source_lang: str = Body("en"),
    admin: dict = Depends(get_admin_user),
):
    """Translate educational content to Assamese or other regional languages."""
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    result = await vertex_services.translate(text, target_lang=target_lang, source_lang=source_lang)
    if result is None:
        raise HTTPException(status_code=503, detail="Translation failed — check GEMINI_API_KEY")
    return {"translated": result, "target_lang": target_lang, "source_lang": source_lang}


@api.post("/admin/vertex/semantic-search")
async def vertex_semantic_search(
    query: str = Body(...),
    top_k: int = Body(10),
    admin: dict = Depends(get_admin_user),
):
    """Semantic search across all published SEO topics using text embeddings."""
    topics = await db.seo_topics.find(
        {}, {"_id": 0, "slug": 1, "title": 1, "subject_name": 1, "class_name": 1, "status": 1}
    ).to_list(5000)
    results = await vertex_services.semantic_search(query, topics, text_key="title", top_k=top_k)
    return {"query": query, "results": results, "total_searched": len(topics)}


@api.post("/admin/vertex/enhance")
async def vertex_enhance_content(
    content: str = Body(...),
    page_type: str = Body("notes"),
    subject: str = Body(""),
    topic: str = Body(""),
    class_name: str = Body("Class 11"),
    admin: dict = Depends(get_admin_user),
):
    """Improve AI-generated content with Gemini."""
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    enhanced = await vertex_services.enhance_content(content, page_type, subject, topic, class_name)
    if enhanced is None:
        raise HTTPException(status_code=503, detail="Enhancement failed")
    return {"enhanced": enhanced, "original_length": len(content), "enhanced_length": len(enhanced)}


@api.post("/admin/vertex/quality-score")
async def vertex_quality_score(
    content: str = Body(...),
    page_type: str = Body("notes"),
    topic: str = Body(""),
    subject: str = Body(""),
    admin: dict = Depends(get_admin_user),
):
    """Score the quality of educational content with Gemini."""
    return await vertex_services.score_content(content, page_type, topic, subject)


@api.post("/admin/vertex/suggest-topics")
async def vertex_suggest_topics(
    subject: str = Body(...),
    class_name: str = Body("Class 11"),
    board: str = Body("AHSEC"),
    admin: dict = Depends(get_admin_user),
):
    """Suggest missing high-value topics for a subject using AI."""
    existing = await db.seo_topics.distinct(
        "title",
        {"subject_name": subject, "class_name": class_name}
    )
    suggestions = await vertex_services.suggest_topics(subject, class_name, existing, board)
    return {"subject": subject, "class_name": class_name, "suggestions": suggestions, "existing_count": len(existing)}


@api.post("/admin/vertex/seo-meta")
async def vertex_seo_meta(
    topic: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    page_type: str = Body("notes"),
    board: str = Body("AHSEC"),
    content_preview: str = Body(""),
    admin: dict = Depends(get_admin_user),
):
    """Generate optimised SEO metadata (title, description, keywords, OG tags)."""
    meta = await vertex_services.generate_seo_meta(topic, subject, class_name, page_type, board, content_preview)
    if not meta:
        raise HTTPException(status_code=503, detail="SEO meta generation failed")
    return meta


@api.get("/admin/vertex/content-gaps")
async def vertex_content_gaps(admin: dict = Depends(get_admin_user)):
    """Identify high-value content gaps by cross-referencing searches with published content."""
    published = await db.seo_topics.distinct("slug", {"status": "published"})

    search_pipeline = [
        {"$match": {"type": "search"}},
        {"$group": {"_id": "$query", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 30},
    ]
    top_searches = []
    try:
        raw = await db.analytics.aggregate(search_pipeline).to_list(30)
        top_searches = [r["_id"] for r in raw if r.get("_id")]
    except Exception:
        pass

    subjects = await db.seo_topics.distinct("subject_name")
    gaps = await vertex_services.find_content_gaps(published, top_searches, subjects)
    return {"gaps": gaps, "published_count": len(published), "search_queries_analyzed": len(top_searches)}


@api.post("/admin/vertex/extract-document")
async def vertex_extract_document(
    file: UploadFile = File(...),
    task: str = "extract_topics",
    admin: dict = Depends(get_admin_user),
):
    """Extract structured data from PDF textbooks/question papers using Gemini 1.5 Pro."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(status_code=400, detail="PDF too large — max 20MB")
    result = await vertex_services.extract_from_document(pdf_bytes, task=task)
    return result


@api.delete("/admin/syllabus/reset-all")
async def admin_syllabus_reset_all(admin: dict = Depends(get_admin_user)):
    """Wipe all subjects and chapters so a fresh syllabus can be uploaded."""
    sub_result = await db.subjects.delete_many({})
    ch_result  = await db.chapters.delete_many({})
    logger.info(f"Syllabus reset by {admin.get('email','?')} — deleted {sub_result.deleted_count} subjects, {ch_result.deleted_count} chapters")
    return {
        "deleted_subjects": sub_result.deleted_count,
        "deleted_chapters":  ch_result.deleted_count,
        "message": "All subjects and chapters cleared. Upload new syllabus via Admin → Syllabus Manager.",
    }


@api.post("/admin/vertex/ocr")
async def vertex_ocr(
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user),
):
    """Cloud Vision equivalent — extract text from AHSEC question paper/textbook images using Gemini Vision."""
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    ct = file.content_type or ""
    if ct not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ct}. Use JPEG, PNG, or WebP.")
    img_bytes = await file.read()
    if len(img_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large — max 10MB")
    result = await vertex_services.ocr_image(img_bytes, mime_type=ct)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@api.post("/admin/vertex/nlp-concepts")
async def vertex_nlp_concepts(
    text: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    admin: dict = Depends(get_admin_user),
):
    """Cloud Natural Language equivalent — extract key concepts, entities and difficulty from educational text."""
    if not text or len(text.strip()) < 50:
        raise HTTPException(status_code=400, detail="text must be at least 50 characters")
    result = await vertex_services.extract_key_concepts(text, subject=subject, class_name=class_name)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@api.post("/admin/vertex/flashcards")
async def vertex_flashcards(
    text: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    count: int = Body(10),
    admin: dict = Depends(get_admin_user),
):
    """Generate revision flashcards from chapter content for students."""
    if not text or len(text.strip()) < 100:
        raise HTTPException(status_code=400, detail="text must be at least 100 characters")
    count = max(5, min(count, 20))
    result = await vertex_services.generate_flashcards(text, subject=subject, count=count, class_name=class_name)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@api.post("/admin/vertex/mcq-generator")
async def vertex_mcq_generator(
    text: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    count: int = Body(10),
    difficulty: str = Body("mixed"),
    admin: dict = Depends(get_admin_user),
):
    """Generate AHSEC-pattern MCQ questions from chapter text."""
    if not text or len(text.strip()) < 100:
        raise HTTPException(status_code=400, detail="text must be at least 100 characters")
    count = max(5, min(count, 20))
    result = await vertex_services.generate_mcqs(text, subject=subject, class_name=class_name,
                                                  count=count, difficulty=difficulty)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


# ─────────────────────────────────────────────
# PHASE D: AUTOMATION ENGINE
# ─────────────────────────────────────────────
@api.get("/admin/automation/insights")
async def admin_automation_insights(admin: dict = Depends(get_admin_user)):
    seo_topics = await db.seo_topics.find({}, {"_id": 0, "slug": 1, "title": 1, "status": 1}).to_list(5000)
    published_slugs = {t["slug"] for t in seo_topics if t.get("status") == "published"}

    chat_topics = []
    try:
        pipeline = [
            {"$unwind": "$messages"},
            {"$match": {"messages.role": "user"}},
            {"$group": {"_id": "$messages.content", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 50},
        ]
        chat_topics = await db.conversations.aggregate(pipeline).to_list(50)
    except Exception:
        pass

    content_gaps = []
    for ct in chat_topics[:20]:
        query = ct.get("_id", "")
        if query and len(query) > 10:
            slug_candidate = re.sub(r'[^a-z0-9]+', '-', query.lower().strip())[:60]
            if slug_candidate not in published_slugs:
                content_gaps.append({"query": query[:100], "count": ct["count"], "suggested_slug": slug_candidate})

    low_content_subjects = []
    try:
        subjects = await db.subjects.find({}, {"_id": 0, "name": 1, "id": 1}).to_list(100)
        for subj in subjects[:30]:
            topic_count = await db.seo_topics.count_documents({"subject_slug": {"$regex": re.sub(r'[^a-z0-9]+', '-', subj.get("name", "").lower())}})
            if topic_count < 3:
                low_content_subjects.append({"name": subj.get("name", ""), "id": subj.get("id", ""), "seo_pages": topic_count})
    except Exception:
        pass

    high_quality_chats = []
    try:
        qa_pipeline = [
            {"$unwind": "$messages"},
            {"$match": {"messages.role": "assistant"}},
            {"$project": {"content": "$messages.content", "msg_id": "$messages.id", "conv_id": "$_id"}},
            {"$match": {"content": {"$regex": ".{200,}"}}},
            {"$limit": 10},
        ]
        high_quality_chats = await db.conversations.aggregate(qa_pipeline).to_list(10)
    except Exception:
        pass

    return {
        "content_gaps": content_gaps[:15],
        "low_content_subjects": low_content_subjects[:10],
        "promotable_chats": len(high_quality_chats),
        "total_seo_topics": len(seo_topics),
        "published_count": len(published_slugs),
    }

@api.post("/admin/automation/auto-generate")
async def admin_automation_auto_generate(admin: dict = Depends(get_admin_user)):
    insights = await admin_automation_insights(admin)
    gaps = insights.get("content_gaps", [])[:5]
    generated = []
    for gap in gaps:
        slug = gap["suggested_slug"]
        title = gap["query"].title()
        now_iso = datetime.now(timezone.utc).isoformat()
        geo_meta = {
            "geo_source": "auto-generated from content gap",
            "geo_query_count": gap.get("count", 0),
            "geo_suggested_sections": [
                "Summary (cite AHSEC syllabus)",
                "Definition (NCERT/SCERT reference)",
                "Explanation (curriculum-aligned)",
                "PYQs (with year and marks)",
                "FAQs (3 common student questions)",
            ],
        }
        await db.seo_topics.update_one(
            {"slug": slug},
            {"$set": {
                "title": title,
                "slug": slug,
                "status": "draft",
                "source": "auto-generated",
                "geo_meta": geo_meta,
                "created_at": now_iso,
            }},
            upsert=True,
        )
        generated.append({"slug": slug, "title": title, "geo_meta": geo_meta})
    return {"generated": generated, "count": len(generated)}


# ─────────────────────────────────────────────
# CMS SCRAPER STATUS — surfaces scraper blockers
# GET /admin/cms/scraper-status
# ─────────────────────────────────────────────

@api.get("/admin/cms/scraper-status")
async def admin_cms_scraper_status(admin: dict = Depends(get_admin_user)):
    """
    Surfaces the status of the personalized CMS scraper pipeline and any blockers.
    Checks:
      1. CmsNoIndexMiddleware anti-scraper UA blocklist (python-requests, wget, curl, etc.)
      2. _cms_request_ctx context-var scraper-prevention flag (no web-search from within CMS)
      3. Paid-gate enforcement — users on free plan receive 402
      4. cms_documents collection — total personal plans, recent failures, empty content
      5. LLM connectivity — new plans fail silently if LLM is down
    Returns a status summary + prioritised blocker list for the admin Automation panel.
    """
    blockers = []
    stats = {
        "total_plans": 0,
        "published_plans": 0,
        "error_plans": 0,
        "empty_plans": 0,
        "paid_users": 0,
        "free_users": 0,
        "scraper_status": "ok",
    }

    # ── Structural/architectural blocker checks (always run, no DB required) ──
    # 1. CmsNoIndexMiddleware UA blocklist — automated HTTP clients are blocked 403
    blocked_ua_patterns = [
        "python-requests", "wget", "curl", "scrapy", "go-http-client",
        "ahrefsbot", "semrushbot", "gptbot", "claudebot", "perplexitybot",
        "bingbot", "googlebot", "yandexbot", "duckduckbot",
    ]
    blockers.append({
        "type": "ua_blocklist_active",
        "message": (
            "CmsNoIndexMiddleware is ACTIVE on all /api/cms/* routes. "
            f"The following User-Agent patterns are blocked with 403: {', '.join(blocked_ua_patterns[:6])} (and {len(blocked_ua_patterns)-6} more). "
            "Any external scraper using these clients will receive 403 Forbidden — use a browser-like UA or authenticated SDK client."
        ),
        "severity": "warning",
        "detail": {
            "middleware": "CmsNoIndexMiddleware",
            "path_prefix": "/api/cms/",
            "blocked_uas": blocked_ua_patterns,
            "response_headers": ["X-Robots-Tag: noindex, nofollow", "Cache-Control: private, no-store"],
        },
    })

    # 2. Context-var web-search prevention — outbound web calls raise 403 from within CMS handlers
    blockers.append({
        "type": "cms_request_ctx_guard",
        "message": (
            "_cms_request_ctx context variable is set to True for all /api/cms/* requests. "
            "This structurally prevents outbound web-search/firecrawl calls from executing inside CMS handlers — "
            "any scraper that relies on web fetching will silently get a 403 from the guard. "
            "CMS content generation uses only call_slm + MongoDB (no external fetching)."
        ),
        "severity": "info",
        "detail": {
            "guard_var": "_cms_request_ctx",
            "effect": "Raises HTTP 403 if any outbound web/scrape call is attempted from CMS handlers",
        },
    })

    try:
        if not await is_mongo_available():
            blockers.insert(0, {
                "type": "db_unavailable",
                "message": "MongoDB unavailable — CMS scraper cannot read/write personalized plans",
                "severity": "critical",
            })
            stats["scraper_status"] = "critical"
            return {"status": "critical", "blockers": blockers, "stats": stats, "recent_plans": []}

        # Count all personalized plans
        stats["total_plans"]     = await db.cms_documents.count_documents({"doc_type": "personalized"})
        stats["published_plans"] = await db.cms_documents.count_documents({"doc_type": "personalized", "status": "published"})
        stats["error_plans"]     = await db.cms_documents.count_documents({"doc_type": "personalized", "status": "error"})

        # Detect plans with empty/too-short content (generation truncation blocker)
        sample_plans = await db.cms_documents.find(
            {"doc_type": "personalized", "status": "published"},
            {"_id": 0, "id": 1, "title": 1, "user_id": 1, "content": 1, "word_count": 1, "created_at": 1}
        ).sort("created_at", -1).limit(50).to_list(50)

        for plan in sample_plans:
            wc = plan.get("word_count") or len((plan.get("content") or "").split())
            if wc < 50:
                stats["empty_plans"] += 1

        if stats["error_plans"] > 0:
            blockers.append({
                "type": "generation_errors",
                "message": f"{stats['error_plans']} personalized plan(s) failed during generation (LLM timeout or prompt error). "
                           "Check recent error documents and verify LLM key health below.",
                "severity": "high",
                "count": stats["error_plans"],
            })

        if stats["empty_plans"] > 0:
            blockers.append({
                "type": "empty_content",
                "message": f"{stats['empty_plans']} published plan(s) have fewer than 50 words — "
                           "content generation may have been truncated by LLM token limit or rate limit.",
                "severity": "medium",
                "count": stats["empty_plans"],
            })

        # Check paid/free user breakdown — free users get 402 from /cms/personalize
        try:
            all_users = await supa_list_users()
            paid_users = [u for u in all_users if u.get("plan", "free") in {"starter", "pro"}]
            free_users = [u for u in all_users if u.get("plan", "free") == "free"]
            stats["paid_users"] = len(paid_users)
            stats["free_users"] = len(free_users)
            if len(paid_users) == 0 and stats["total_plans"] > 0:
                blockers.append({
                    "type": "no_paid_users",
                    "message": (
                        f"Plans exist in DB but 0 users are on Starter/Pro — "
                        "POST /api/cms/personalize will return 402 for ALL users. "
                        f"Total users: {len(all_users)}, all on free plan."
                    ),
                    "severity": "warning",
                })
        except Exception:
            pass

        # Check LLM connectivity — quick probe (new plan generation fails if LLM is down)
        llm_ok = True
        try:
            test_resp = await call_slm("Say OK", max_tokens=5, temperature=0)
            if not test_resp or len(test_resp.strip()) == 0:
                llm_ok = False
        except Exception:
            llm_ok = False

        if not llm_ok:
            blockers.append({
                "type": "llm_unavailable",
                "message": "LLM provider (call_slm) is unreachable — new personalized plans will fail at generation step. "
                           "Existing published plans are still served from MongoDB.",
                "severity": "critical",
            })

        # Overall status
        if any(b["severity"] == "critical" for b in blockers):
            stats["scraper_status"] = "critical"
        elif any(b["severity"] == "high" for b in blockers):
            stats["scraper_status"] = "degraded"
        elif any(b["severity"] in ("medium", "warning") for b in blockers):
            stats["scraper_status"] = "warning"
        else:
            stats["scraper_status"] = "ok"

        return {
            "status": stats["scraper_status"],
            "blockers": blockers,
            "stats": stats,
            "recent_plans": [
                {
                    "id": p.get("id"), "title": p.get("title"), "user_id": p.get("user_id"),
                    "word_count": p.get("word_count") or len((p.get("content") or "").split()),
                    "created_at": p.get("created_at"),
                }
                for p in sample_plans[:5]
            ],
        }

    except Exception as exc:
        logger.error(f"admin_cms_scraper_status error: {exc}")
        return {
            "status": "error",
            "blockers": [{"type": "internal_error", "message": str(exc)[:200], "severity": "critical"}],
            "stats": stats,
        }


# ─────────────────────────────────────────────
# PHASE E: MONETIZATION ANALYTICS
# ─────────────────────────────────────────────
@api.get("/admin/monetization/overview")
async def admin_monetization_overview(admin: dict = Depends(get_admin_user)):
    users = await supa_list_users()
    payments = await db.payments.find({}, {"_id": 0}).sort("verified_at", -1).to_list(5000)

    now = datetime.now(timezone.utc)
    thirty_ago = (now - timedelta(days=30)).isoformat()
    seven_ago = (now - timedelta(days=7)).isoformat()

    revenue_30d = sum(p.get("amount_paise", 0) for p in payments if p.get("verified_at", "") >= thirty_ago and p.get("provider") != "stripe") / 100
    revenue_7d = sum(p.get("amount_paise", 0) for p in payments if p.get("verified_at", "") >= seven_ago and p.get("provider") != "stripe") / 100

    total_paid = sum(1 for u in users if u.get("plan") in ("starter", "pro"))
    starter_count = sum(1 for u in users if u.get("plan") == "starter")
    pro_count = sum(1 for u in users if u.get("plan") == "pro")

    arpu = round(revenue_30d / max(total_paid, 1), 2)

    recent_txns = []
    for p in payments[:20]:
        recent_txns.append({
            "user_id": p.get("user_id", ""),
            "plan": p.get("plan", ""),
            "amount": p.get("amount_paise", 0) / 100 if p.get("provider") != "stripe" else p.get("amount_cents", 0) / 100,
            "currency": "INR" if p.get("provider") != "stripe" else "USD",
            "provider": p.get("provider", "razorpay"),
            "date": p.get("verified_at", "")[:10],
        })

    return {
        "revenue_30d_inr": revenue_30d,
        "revenue_7d_inr": revenue_7d,
        "arpu_inr": arpu,
        "total_paid_users": total_paid,
        "starter_users": starter_count,
        "pro_users": pro_count,
        "total_free_users": len(users) - total_paid,
        "conversion_rate": round(total_paid / max(len(users), 1) * 100, 2),
        "recent_transactions": recent_txns,
        "total_lifetime_revenue_inr": sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe") / 100,
    }

@api.get("/admin/monetization/referrals")
async def admin_monetization_referrals(admin: dict = Depends(get_admin_user)):
    referrals = await db.referrals.find({}, {"_id": 0}).to_list(500)
    return {
        "total_referrals": len(referrals),
        "successful_conversions": sum(1 for r in referrals if r.get("converted")),
        "referrals": referrals[:50],
    }

class ReferralConfigUpdate(BaseModel):
    enabled: bool = True
    reward_credits: int = 10
    referrer_credits: int = 10

@api.put("/admin/monetization/referral-config")
async def admin_update_referral_config(body: ReferralConfigUpdate, admin: dict = Depends(get_admin_user)):
    await db.api_config.update_one(
        {},
        {"$set": {"referral": body.dict()}},
        upsert=True,
    )
    return {"success": True}

@api.get("/admin/monetization/referral-config")
async def admin_get_referral_config(admin: dict = Depends(get_admin_user)):
    cfg = await db.api_config.find_one({}, {"_id": 0})
    return cfg.get("referral", {"enabled": False, "reward_credits": 10, "referrer_credits": 10}) if cfg else {"enabled": False, "reward_credits": 10, "referrer_credits": 10}


# ═══════════════════════════════════════════════════════════════════════════
# UPGRADE WAVE — ALL 12 MAJOR FEATURES
# ═══════════════════════════════════════════════════════════════════════════

# ── T001: Internal Linking Engine ────────────────────────────────────────────

@api.get("/admin/seo/internal-links/analyze")
async def seo_internal_links_analyze(admin: dict = Depends(get_admin_user)):
    """Analyze all published topics and return semantic link suggestions using embeddings."""
    topics = await db.seo_topics.find(
        {"status": "published"},
        {"_id": 0, "slug": 1, "title": 1, "subject_name": 1, "class_name": 1}
    ).to_list(500)

    if not topics:
        return {"links": [], "topics_analyzed": 0}

    suggestions = []
    try:
        import vertex_services
        titles = [t["title"] for t in topics]
        vecs = await vertex_services.embed_batch(titles)

        for i, (topic, vec_i) in enumerate(zip(topics, vecs)):
            if vec_i is None:
                continue
            scores = []
            for j, (other, vec_j) in enumerate(zip(topics, vecs)):
                if i == j or vec_j is None:
                    continue
                sim = vertex_services.cosine_similarity(vec_i, vec_j)
                if sim > 0.65:
                    scores.append({"slug": other["slug"], "title": other["title"], "score": round(sim, 3)})
            scores.sort(key=lambda x: x["score"], reverse=True)
            if scores:
                suggestions.append({
                    "slug": topic["slug"],
                    "title": topic["title"],
                    "subject": topic.get("subject_name", ""),
                    "related": scores[:5],
                })
    except Exception as e:
        logger.warning(f"internal-links analyze failed: {e}")

    return {"links": suggestions, "topics_analyzed": len(topics)}


@api.post("/admin/seo/internal-links/inject/{slug}")
async def seo_internal_links_inject(slug: str, admin: dict = Depends(get_admin_user)):
    """Inject internal links into a topic's generated content."""
    topic = await db.seo_topics.find_one({"slug": slug})
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    pages = await db.seo_pages.find({"topic_id": str(topic.get("_id", ""))}).to_list(20)
    if not pages:
        raise HTTPException(status_code=404, detail="No pages found for this topic")

    all_topics = await db.seo_topics.find(
        {"status": "published", "slug": {"$ne": slug}},
        {"slug": 1, "title": 1}
    ).to_list(200)

    injected_count = 0
    for page in pages[:5]:
        content = page.get("content", "")
        if not content:
            continue
        for related in all_topics[:10]:
            r_title = related.get("title", "")
            r_slug = related.get("slug", "")
            if r_title.lower() in content.lower() and f"[{r_title}]" not in content:
                content = content.replace(
                    r_title,
                    f"[{r_title}](/learn/{r_slug})",
                    1
                )
                injected_count += 1
        await db.seo_pages.update_one(
            {"_id": page["_id"]},
            {"$set": {"content": content, "internal_links_injected": True, "links_updated_at": datetime.now(timezone.utc).isoformat()}}
        )

    return {"slug": slug, "pages_updated": len(pages), "links_injected": injected_count}


# ── T003: FAQ Auto-Extractor ──────────────────────────────────────────────────

@api.get("/admin/conversations/extract-faqs")
async def extract_faqs(limit: int = 100, admin: dict = Depends(get_admin_user)):
    """Extract recurring questions from conversations and suggest FAQ content."""
    pipeline = [
        {"$unwind": "$messages"},
        {"$match": {"messages.role": "user"}},
        {"$project": {"content": "$messages.content", "subject": "$subject_name"}},
        {"$limit": limit * 5},
    ]
    try:
        raw = await db.conversations.aggregate(pipeline).to_list(limit * 5)
    except Exception:
        raw = []

    questions = [r["content"] for r in raw if r.get("content") and len(r["content"]) > 15 and "?" in r["content"]][:50]
    subjects = list({r.get("subject", "") for r in raw if r.get("subject")})[:10]

    faqs = []
    if questions:
        try:
            import vertex_services
            prompt = (
                f"From these student questions, identify the top 15 most frequently asked and educationally important ones.\n"
                f"Questions:\n" + "\n".join(f"- {q[:200]}" for q in questions[:50]) +
                f"\n\nReturn a JSON array of: {{question, category, suggested_answer_length: 'short'|'medium'|'long', importance: 'high'|'medium'}}"
                f"\nReturn ONLY valid JSON array."
            )
            raw_result = await vertex_services._generate(prompt, max_tokens=1024)
            if raw_result:
                cleaned = raw_result.strip().lstrip("```json").lstrip("```").rstrip("```")
                faqs = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"FAQ extraction AI failed: {e}")
            faqs = [{"question": q[:200], "category": "general", "importance": "medium"} for q in questions[:15]]

    return {
        "faqs": faqs,
        "total_questions_analyzed": len(questions),
        "subjects": subjects,
        "suggested_pages": [
            {"type": "faq", "title": f["question"][:80], "priority": f.get("importance", "medium")}
            for f in faqs[:10]
        ]
    }


@api.get("/admin/conversations/sentiment")
async def conversations_sentiment(admin: dict = Depends(get_admin_user)):
    """Quick sentiment summary across all recent conversations."""
    try:
        pipeline = [
            {"$unwind": "$messages"},
            {"$match": {"messages.role": "user"}},
            {"$project": {"content": "$messages.content", "conv_id": "$_id"}},
            {"$limit": 200},
        ]
        msgs = await db.conversations.aggregate(pipeline).to_list(200)
    except Exception:
        msgs = []

    if not msgs:
        return {"positive": 0, "negative": 0, "neutral": 0, "total": 0}

    texts = [m["content"] for m in msgs if m.get("content")]
    positive = sum(1 for t in texts if any(w in t.lower() for w in ["thank", "great", "awesome", "help", "good", "love", "clear", "easy"]))
    negative = sum(1 for t in texts if any(w in t.lower() for w in ["wrong", "bad", "error", "confused", "not working", "fail", "broken", "terrible"]))
    neutral = len(texts) - positive - negative
    return {
        "positive": positive,
        "negative": negative,
        "neutral": max(0, neutral),
        "total": len(texts),
        "positive_pct": round(positive / max(len(texts), 1) * 100, 1),
        "negative_pct": round(negative / max(len(texts), 1) * 100, 1),
    }


# ── T001b: Schema.org Auto-Injection ─────────────────────────────────────────

@api.post("/admin/seo/inject-schema/{slug}")
async def seo_inject_schema(slug: str, admin: dict = Depends(get_admin_user)):
    """Inject JSON-LD schema.org structured data into a topic's pages."""
    topic = await db.seo_topics.find_one({"slug": slug})
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    schema = {
        "@context": "https://schema.org",
        "@type": "Course",
        "name": topic.get("title", ""),
        "description": topic.get("meta_description", topic.get("title", "")),
        "provider": {"@type": "Organization", "name": "Syrabit.ai", "url": "https://syrabit.ai"},
        "educationalLevel": topic.get("class_name", ""),
        "about": topic.get("subject_name", ""),
        "keywords": topic.get("keywords", []),
        "inLanguage": "en-IN",
        "isPartOf": {"@type": "LearningResource", "name": f"AHSEC {topic.get('class_name', '')} {topic.get('subject_name', '')}"},
    }

    faq_schema = None
    pages = await db.seo_pages.find({"topic_id": str(topic.get("_id", ""))}).to_list(50)
    faqs = []
    for page in pages:
        if page.get("type") in ("important-questions", "mcqs"):
            content = page.get("content", "")
            questions = re.findall(r'#{1,3}\s+(.+?)\n', content)[:5]
            for q in questions:
                faqs.append({"@type": "Question", "name": q.strip(),
                              "acceptedAnswer": {"@type": "Answer", "text": f"Refer to Syrabit.ai for a detailed answer on {q.strip()}."}})
    if faqs:
        faq_schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": faqs}

    await db.seo_topics.update_one(
        {"slug": slug},
        {"$set": {"schema_org": schema, "faq_schema": faq_schema, "schema_injected_at": datetime.now(timezone.utc).isoformat()}}
    )

    return {"slug": slug, "schema_injected": True, "faq_entities": len(faqs), "schema": schema}


@api.post("/admin/seo/inject-schema-bulk")
async def seo_inject_schema_bulk(admin: dict = Depends(get_admin_user)):
    """Inject schema.org into all published topics."""
    topics = await db.seo_topics.find({"status": "published"}, {"slug": 1}).to_list(1000)
    injected = 0
    for t in topics:
        try:
            await seo_inject_schema(t["slug"], admin)
            injected += 1
        except Exception:
            pass
    return {"injected": injected, "total": len(topics)}


# ── T008: Content Pipeline Tracker ───────────────────────────────────────────

@api.get("/admin/seo/pipeline-status")
async def seo_pipeline_status(admin: dict = Depends(get_admin_user)):
    """Get real-time content pipeline statistics."""
    try:
        total         = await db.seo_topics.count_documents({})
        published     = await db.seo_topics.count_documents({"status": "published"})
        draft         = await db.seo_topics.count_documents({"status": "draft"})
        archived      = await db.seo_topics.count_documents({"status": "archived"})
        has_content   = await db.seo_topics.count_documents({"has_content": True})
        no_schema     = await db.seo_topics.count_documents({"status": "published", "schema_org": {"$exists": False}})
        no_links      = await db.seo_topics.count_documents({"status": "published", "internal_links_injected": {"$ne": True}})

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        published_today = await db.seo_topics.count_documents({
            "status": "published",
            "published_at": {"$gte": today.isoformat()}
        })
        pages_total = await db.seo_pages.count_documents({})

        return {
            "total_topics": total,
            "published": published,
            "draft": draft,
            "archived": archived,
            "has_content": has_content,
            "pages_total": pages_total,
            "published_today": published_today,
            "needs_schema": no_schema,
            "needs_internal_links": no_links,
            "publish_rate_pct": round(published / max(total, 1) * 100, 1),
            "content_rate_pct": round(has_content / max(total, 1) * 100, 1),
        }
    except Exception as e:
        logger.warning(f"pipeline-status failed: {e}")
        return {}


# ── T009: Page-Level Conversion Tracker ──────────────────────────────────────

@api.get("/admin/analytics/page-conversions")
async def admin_page_conversions(days: int = 30, admin: dict = Depends(get_admin_user)):
    """Track which content pages correlate with user signups and upgrades."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Top viewed pages
    view_pipeline = [
        {"$match": {"type": "page_view", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$path", "views": {"$sum": 1}, "unique_visitors": {"$addToSet": "$visitor_id"}}},
        {"$project": {"path": "$_id", "views": 1, "unique_visitors": {"$size": "$unique_visitors"}}},
        {"$sort": {"views": -1}},
        {"$limit": 20},
    ]
    try:
        pages = await db.analytics.aggregate(view_pipeline).to_list(20)
    except Exception:
        pages = []

    # New signups per day with last page
    signup_pipeline = [
        {"$match": {"type": "signup", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$referrer_path", "signups": {"$sum": 1}}},
        {"$sort": {"signups": -1}},
        {"$limit": 15},
    ]
    try:
        signup_sources = await db.analytics.aggregate(signup_pipeline).to_list(15)
    except Exception:
        signup_sources = []

    enriched = []
    signup_map = {s["_id"]: s["signups"] for s in signup_sources}
    for p in pages:
        path = p.get("path", "") or p.get("_id", "")
        enriched.append({
            "path": path,
            "views": p.get("views", 0),
            "unique_visitors": p.get("unique_visitors", 0),
            "signups_attributed": signup_map.get(path, 0),
            "conversion_rate": round(signup_map.get(path, 0) / max(p.get("unique_visitors", 1), 1) * 100, 2),
        })

    enriched.sort(key=lambda x: x["signups_attributed"], reverse=True)

    # Daily signups trend
    daily_pipeline = [
        {"$match": {"type": "signup", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "signups": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    try:
        daily = await db.analytics.aggregate(daily_pipeline).to_list(days)
    except Exception:
        daily = []

    return {
        "top_converting_pages": enriched,
        "daily_signups": [{"date": d["_id"], "signups": d["signups"]} for d in daily],
        "period_days": days,
    }


# ── T010: Churn Risk Scoring ──────────────────────────────────────────────────

@api.get("/admin/users/churn-risk")
async def admin_churn_risk(admin: dict = Depends(get_admin_user)):
    """Score every user's churn risk based on activity, credits, and plan age."""
    users = await supa_list_users()
    now = datetime.now(timezone.utc)
    at_risk = []

    for u in users:
        score = 0
        factors = []

        created = u.get("created_at", "")
        last_active = u.get("updated_at", created)
        try:
            la_dt = datetime.fromisoformat(last_active.replace("Z", "+00:00"))
            days_inactive = (now - la_dt).days
        except Exception:
            days_inactive = 0

        if days_inactive > 14:
            score += 30
            factors.append(f"Inactive {days_inactive}d")
        elif days_inactive > 7:
            score += 15
            factors.append(f"Inactive {days_inactive}d")

        credits_used = u.get("credits_used", 0) or 0
        if credits_used == 0:
            score += 25
            factors.append("Never used AI")
        elif credits_used < 3:
            score += 10
            factors.append("Low engagement")

        plan = u.get("plan", "free")
        if plan == "free" and days_inactive > 3:
            score += 15
            factors.append("Free + inactive")

        conv_count = u.get("conversation_count", 0) or 0
        if conv_count == 0:
            score += 20
            factors.append("No conversations")

        risk = "high" if score >= 60 else "medium" if score >= 30 else "low"
        at_risk.append({
            "id": u.get("id"), "name": u.get("name", ""), "email": u.get("email", ""),
            "plan": plan, "credits_used": credits_used, "days_inactive": days_inactive,
            "risk_score": score, "risk": risk, "factors": factors,
        })

    at_risk.sort(key=lambda x: x["risk_score"], reverse=True)
    return {
        "users": at_risk[:50],
        "summary": {
            "high_risk": sum(1 for u in at_risk if u["risk"] == "high"),
            "medium_risk": sum(1 for u in at_risk if u["risk"] == "medium"),
            "low_risk": sum(1 for u in at_risk if u["risk"] == "low"),
            "total": len(at_risk),
        }
    }


# ── T011: LLM Cost Tracker ────────────────────────────────────────────────────

_llm_cost_log: list = []   # in-memory ring buffer (max 10k entries)
_LLM_COST_MAX = 10_000

COST_PER_1K_TOKENS = {
    "gemini-2.5-flash-preview-05-20": {"in": 0.0001875, "out": 0.0006},
    "gemini-2.0-flash":       {"in": 0.000075, "out": 0.0003},
    "gemini-2.0-flash-lite":  {"in": 0.0000375, "out": 0.00015},
    "gemini-1.5-pro":         {"in": 0.00125,   "out": 0.005},
    "llama-3.3-70b-versatile":{"in": 0.00059,   "out": 0.00079},
    "llama-3.1-8b-instant":   {"in": 0.00005,   "out": 0.00008},
}

def record_llm_cost(model: str, prompt_tokens: int, completion_tokens: int, provider: str = "gemini", user_id: str = ""):
    rates = COST_PER_1K_TOKENS.get(model, {"in": 0.0001, "out": 0.0002})
    cost_usd = (prompt_tokens * rates["in"] + completion_tokens * rates["out"]) / 1000
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model, "provider": provider,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "cost_usd": round(cost_usd, 8),
        "user_id": user_id,
    }
    _llm_cost_log.append(entry)
    if len(_llm_cost_log) > _LLM_COST_MAX:
        _llm_cost_log.pop(0)

@api.get("/admin/health/llm-costs")
async def admin_llm_costs(days: int = 7, admin: dict = Depends(get_admin_user)):
    """Return LLM cost breakdown for the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [e for e in _llm_cost_log if datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) >= cutoff]

    total_cost = sum(e["cost_usd"] for e in recent)
    total_tokens = sum(e["prompt_tokens"] + e["completion_tokens"] for e in recent)

    by_model: dict = {}
    for e in recent:
        m = e["model"]
        by_model.setdefault(m, {"calls": 0, "cost_usd": 0, "tokens": 0})
        by_model[m]["calls"] += 1
        by_model[m]["cost_usd"] += e["cost_usd"]
        by_model[m]["tokens"] += e["prompt_tokens"] + e["completion_tokens"]

    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, {"cost_usd": 0, "calls": 0})
        by_day[day]["cost_usd"] += e["cost_usd"]
        by_day[day]["calls"] += 1

    daily = [{"date": d, **v, "cost_usd": round(v["cost_usd"], 6)} for d, v in sorted(by_day.items())]

    published = await db.seo_topics.count_documents({"status": "published"})
    cost_per_page = round(total_cost / max(published, 1), 6)

    by_user: dict = {}
    for e in recent:
        uid = e.get("user_id", "anonymous") or "anonymous"
        by_user.setdefault(uid, {"calls": 0, "cost_usd": 0, "tokens": 0})
        by_user[uid]["calls"] += 1
        by_user[uid]["cost_usd"] += e["cost_usd"]
        by_user[uid]["tokens"] += e["prompt_tokens"] + e["completion_tokens"]

    top_users = sorted(by_user.items(), key=lambda x: -x[1]["cost_usd"])[:20]

    return {
        "period_days": days,
        "total_cost_usd": round(total_cost, 6),
        "total_cost_inr": round(total_cost * 84, 4),
        "total_tokens": total_tokens,
        "total_calls": len(recent),
        "cost_per_published_page_usd": cost_per_page,
        "by_model": [{"model": m, **v, "cost_usd": round(v["cost_usd"], 6)} for m, v in by_model.items()],
        "by_user": [{"user_id": uid, **v, "cost_usd": round(v["cost_usd"], 6)} for uid, v in top_users],
        "daily": daily,
    }


# ── T012: Notification Trigger Builder ───────────────────────────────────────

@api.get("/admin/notifications/triggers")
async def get_notification_triggers(admin: dict = Depends(get_admin_user)):
    """List all automated notification triggers."""
    triggers = await db.notification_triggers.find({}, {"_id": 0}).to_list(100)
    return {"triggers": triggers}


@api.post("/admin/notifications/triggers")
async def create_notification_trigger(body: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Create a new automated trigger."""
    required = {"name", "event", "channel", "message"}
    if not required.issubset(body.keys()):
        raise HTTPException(status_code=400, detail=f"Required fields: {required}")
    trigger = {
        "id": str(uuid.uuid4()),
        "name": body["name"],
        "event": body["event"],       # signup | inactive_3d | inactive_7d | plan_upgrade | low_credits
        "channel": body["channel"],   # push | email | both
        "message": body["message"],
        "subject": body.get("subject", ""),
        "enabled": body.get("enabled", True),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fired_count": 0,
    }
    await db.notification_triggers.insert_one({**trigger, "_id": trigger["id"]})
    return trigger


@api.patch("/admin/notifications/triggers/{trigger_id}")
async def update_notification_trigger(trigger_id: str, body: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Toggle or update a trigger."""
    await db.notification_triggers.update_one({"id": trigger_id}, {"$set": body})
    return {"success": True}


@api.delete("/admin/notifications/triggers/{trigger_id}")
async def delete_notification_trigger(trigger_id: str, admin: dict = Depends(get_admin_user)):
    """Delete a trigger."""
    await db.notification_triggers.delete_one({"id": trigger_id})
    return {"success": True}


# ── T005: PDF-to-Syllabus Importer ───────────────────────────────────────────

_VALID_PAPER_TYPES = {"major", "minor", "mdc", "vac", "aec", "sec", "ge", "cc"}

_SYLLABUS_EXTRACT_PROMPT = """
You are parsing an official university/board syllabus PDF for students in Assam, India.

The PDF may contain ONE or MULTIPLE subjects (one subject per page/section). Extract EVERY subject found.

Paper type for ALL subjects in this PDF: {paper_type}

For EACH subject, return one JSON object in this exact schema:
{{
  "board": "<College / University / Board name exactly as stated, e.g. 'Darrang College (Autonomous)', 'Gauhati University', 'AHSEC'>",
  "class_year": "<Year of study — e.g. '1st Year', '2nd Year', 'HS 1st Year', 'Class 10'>",
  "semester": "<Semester label — e.g. 'Semester 1', 'Semester 2', '' if annual/not stated>",
  "semester_number": <integer 1-8 if stated, else 0>,
  "subject_name": "<Exact subject/course name as printed>",
  "course_code": "<Course code if printed, e.g. 'VAC-01012', else ''>",
  "credits": <integer credits, else 0>,
  "paper_type": "{paper_type}",
  "stream_target": "<Who this course is for — one of: 'All', 'Commerce', 'Arts', 'Science', 'Arts & Science', 'Commerce & Arts'>",
  "chapters": [
    {{
      "title": "<Unit I or Chapter 1 exact title as printed>",
      "description": "<Concise summary of all topics/subtopics listed under this unit — write as a flowing sentence or comma-separated list, max 3 sentences>",
      "topics": ["<subtopic 1>", "<subtopic 2>", "<subtopic 3>"]
    }}
  ],
  "topics": ["<Key topic or subtopic 1>", "<Key topic 2>", ...],
  "guidelines": "<Course objectives / outcomes / learning goals as a single string, or ''>"
}}

Rules:
- Extract EVERY subject/course in the PDF — do NOT skip any.
- chapters = the numbered units or chapters from the detailed syllabus table, each with its content description.
- For EACH chapter, "title" MUST NOT be empty — use the exact unit/chapter heading as printed; if no heading is visible, use "Unit 1", "Unit 2" etc.
- For each chapter, description must summarise exactly what topics appear under that unit in the PDF.
- topics (top-level) = key terms across all units (max 20 per subject).
- stream_target: if the PDF says "For all (Arts+Commerce+Science)" → "All"; "For Commerce" → "Commerce"; "For Arts & Science" → "Arts & Science".
- If semester is not stated but can be inferred from the course code (e.g. VAC-01012 → Semester 1), use it.
- Return ONLY a valid JSON array. No markdown fences, no explanations.
""".strip()

_CHAPTER_CONTENT_PROMPT = """You are an expert academic content writer for degree-level students in Assam, India.

Generate comprehensive educational notes (Markdown format, 600–1000 words) for:
Subject: {subject_name}
Chapter: {chapter_title}
Topics covered: {topics}
Board/Semester: {board_semester}

Structure the content as:
## {chapter_title}
### Introduction
(2-3 paragraphs introducing the chapter)

### Key Concepts
(Define and explain each major concept)

### {topic_sections}
(One ### section per major topic — explain thoroughly with examples)

### Summary
(Bullet-point summary of key takeaways)

Rules:
- Write for undergraduate students (degree level, NEP FYUGP)
- Use clear, simple language
- Include real examples from Assam/Northeast India where applicable
- Each concept must be fully explained
- Do NOT use placeholder text — write actual educational content
- Return ONLY the markdown content, no preamble
""".strip()

# ── Helper: generate chapter-level educational content via AI ─────────────────
async def _agentic_generate_chapter_content(
    subject_name: str,
    chapter_title: str,
    topics: list,
    board_semester: str,
) -> str:
    """Use LLM pool to generate educational markdown for a chapter."""
    topics_str = ", ".join(topics[:12]) if topics else "as listed in the chapter title"
    # Build topic section headers
    topic_sections = "\n".join([f"### {t}" for t in topics[:6]]) if topics else "### Core Content"
    prompt = _CHAPTER_CONTENT_PROMPT.format(
        subject_name=subject_name,
        chapter_title=chapter_title,
        topics=topics_str,
        board_semester=board_semester,
        topic_sections=topic_sections,
    )
    try:
        result = await slm_pool.complete(
            messages=[
                {"role": "system", "content": "You are a precise educational content writer. Write structured, factual academic notes."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=1800,
            temperature=0.3,
            task_hint="content_gen",
        )
        return (result or "").strip()
    except Exception as exc:
        logger.warning(f"[agentic_syllabus] chapter content gen failed for {chapter_title!r}: {exc}")
        # Fallback: minimal structured content
        return f"## {chapter_title}\n\n" + "\n\n".join([f"### {t}\n\n*Content for {t} in {subject_name}.*" for t in (topics[:5] or [chapter_title])])


@api.post("/admin/agentic-syllabus/run")
async def agentic_syllabus_run(
    file: UploadFile = File(...),
    paper_type: str  = Form("major"),
    admin: dict      = Depends(get_admin_user),
):
    """
    Agentic Syllabus Uploader — full autonomous pipeline, streamed as SSE.

    Pipeline per subject:
      PDF scan → identify subjects → for each subject:
        hierarchy link (board→semester→stream→subject) →
        chapter content generation (AI) →
        auto-chunk →
        embed (RAG) →
        SEO/GEO topic tagging →
        next subject

    Returns: text/event-stream (SSE)
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")
    paper_type = paper_type.lower().strip()
    if paper_type not in _VALID_PAPER_TYPES:
        raise HTTPException(status_code=400, detail=f"paper_type must be one of: {', '.join(sorted(_VALID_PAPER_TYPES))}")

    pdf_bytes  = await file.read()
    filename   = file.filename
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 20 MB)")

    import base64 as _b64, httpx as _httpx
    import vertex_services

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _recover_json(text: str) -> list:
        try:
            r = json.loads(text)
            return r if isinstance(r, list) else [r]
        except Exception:
            pass
        last = text.rfind('}')
        if last > 0:
            partial = text[:last + 1]
            cand = (partial + ']') if partial.lstrip().startswith('[') else ('[' + partial + ']')
            try:
                r = json.loads(cand)
                return r if isinstance(r, list) else [r]
            except Exception:
                pass
        objects, decoder, idx = [], json.JSONDecoder(), text.find('{')
        while 0 <= idx < len(text):
            try:
                obj, end = decoder.raw_decode(text, idx)
                objects.append(obj)
                idx = text.find('{', end)
            except Exception:
                idx = text.find('{', idx + 1)
        return objects

    async def _pipeline():
        # ── 1. SCAN: Extract subjects from PDF ───────────────────────────────
        yield _sse("scan_start", {"filename": filename, "paper_type": paper_type})

        extracted: list = []
        try:
            b64_pdf = _b64.b64encode(pdf_bytes).decode()
            prompt  = _SYLLABUS_EXTRACT_PROMPT.format(paper_type=paper_type)
            headers = await vertex_services._auth_headers()
            body    = {
                "contents": [{"parts": [
                    {"text": prompt + "\n\nReturn ONLY valid JSON array. No markdown fences."},
                    {"inline_data": {"mime_type": "application/pdf", "data": b64_pdf}},
                ]}],
                "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.1},
            }
            for _gmodel in ["gemini-2.0-flash", "gemini-2.0-flash-lite"]:
                url = vertex_services._gen_url(_gmodel)
                async with _httpx.AsyncClient(timeout=120) as c:
                    r = await c.post(url, json=body, headers=headers)
                if r.status_code in (403, 404):
                    continue
                r.raise_for_status()
                raw     = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip())
                cleaned = re.sub(r'\s*```$', '', cleaned).strip()
                extracted = _recover_json(cleaned)
                break
        except Exception as e:
            # Fallback: text extraction
            try:
                import io
                try:    from pypdf import PdfReader as _PR
                except: from PyPDF2 import PdfReader as _PR  # type: ignore
                reader    = _PR(io.BytesIO(pdf_bytes))
                full_text = "\n".join((reader.pages[i].extract_text() or "") for i in range(len(reader.pages)))
                resp = await slm_pool.complete(
                    messages=[
                        {"role": "system", "content": "Extract syllabus from text. Return JSON array."},
                        {"role": "user",   "content": _SYLLABUS_EXTRACT_PROMPT.format(paper_type=paper_type) + f"\n\nPDF TEXT:\n{full_text[:12000]}"},
                    ],
                    max_tokens=4096, temperature=0.1, task_hint="classification",
                )
                extracted = _recover_json(resp or "[]")
            except Exception as fe:
                yield _sse("error", {"message": f"PDF scan failed: {fe}"})
                return

        if not extracted:
            yield _sse("error", {"message": "No subjects found in PDF"})
            return

        yield _sse("scan_complete", {"subjects": [e.get("subject_name", "?") for e in extracted], "total": len(extracted)})

        # ── 2. IMPORT each subject sequentially ──────────────────────────────
        from syllabus_linker import SyllabusLinker, SyllabusEntry  # type: ignore
        linker   = SyllabusLinker(db)
        import_id = str(uuid.uuid4())
        now_iso   = datetime.now(timezone.utc).isoformat()

        total_chapters_all = 0
        total_chunks_all   = 0
        total_embedded     = 0
        all_subject_ids: list = []

        for subj_idx, entry_raw in enumerate(extracted):
            subject_name = (entry_raw.get("subject_name") or entry_raw.get("subject") or "").strip()
            if not subject_name:
                continue

            sem_raw  = entry_raw.get("semester", "") or ""
            sem_num  = entry_raw.get("semester_number", 0) or 0
            if sem_num and not sem_raw:
                sem_raw = f"Semester {sem_num}"
            board_semester = f"{entry_raw.get('board','DEGREE')} / {sem_raw or 'Semester 1'}"

            # Normalise chapter list
            raw_chaps = entry_raw.get("chapters", [])
            chapter_details: list[dict] = []
            for ch in raw_chaps:
                if isinstance(ch, dict):
                    title = (ch.get("title") or ch.get("name") or "").strip()
                    if title:
                        chapter_details.append({
                            "title":       title,
                            "description": (ch.get("description") or "").strip(),
                            "topics":      [t for t in (ch.get("topics") or []) if isinstance(t, str)],
                        })
                elif isinstance(ch, str) and ch.strip():
                    chapter_details.append({"title": ch.strip(), "description": "", "topics": []})

            n_chapters = len(chapter_details)
            yield _sse("subject_start", {
                "name":    subject_name,
                "index":   subj_idx,
                "total":   len(extracted),
                "chapters": n_chapters,
                "semester": sem_raw,
                "board":   entry_raw.get("board", "DEGREE"),
            })

            # ── 2a. Link hierarchy ────────────────────────────────────────────
            entry = SyllabusEntry(
                board_name      = (entry_raw.get("board") or "").strip(),
                class_year      = (entry_raw.get("class_year") or "").strip(),
                semester        = sem_raw.strip(),
                subject_name    = subject_name,
                paper_type      = paper_type,
                stream_hint     = (entry_raw.get("stream_target") or "All").strip(),
                chapters        = [ch["title"] for ch in chapter_details],
                chapter_details = chapter_details,
                topics          = [t for t in entry_raw.get("topics", []) if isinstance(t, str)][:20],
                guidelines      = (entry_raw.get("guidelines") or "").strip(),
                course_code     = (entry_raw.get("course_code") or "").strip(),
                credits         = int(entry_raw.get("credits") or 0),
            )
            try:
                link = await linker.link(entry)
            except Exception as le:
                logger.warning(f"[agentic_syllabus] linker failed for {subject_name}: {le}")
                link = None

            created_nodes = link.created_nodes if link else []
            subject_ids   = link.subject_ids   if link else []
            board_disp    = link.board_name     if link else entry_raw.get("board", "DEGREE")
            class_disp    = link.class_name     if link else sem_raw

            yield _sse("hierarchy", {
                "board":         board_disp,
                "class":         class_disp,
                "stream":        (link.streams[0]["stream_name"] if link and link.streams else paper_type.upper()),
                "subject":       subject_name,
                "created_nodes": created_nodes,
                "subject_ids":   subject_ids,
            })

            # ── 2b. For each chapter: generate content → chunk → embed ────────
            chap_chunks_total = 0
            all_chapter_ids: list[str] = []

            # Fetch chapters just created by linker so we have real chapter_ids
            ch_docs = []
            if subject_ids:
                ch_docs = await db.chapters.find(
                    {"subject_id": {"$in": subject_ids}},
                    {"id": 1, "title": 1, "content": 1, "topics": 1}
                ).to_list(200)

            ch_map = {doc["title"].lower().strip(): doc for doc in ch_docs}

            for ch_idx, ch_detail in enumerate(chapter_details):
                ch_title  = ch_detail["title"]
                ch_topics = ch_detail.get("topics", [])

                yield _sse("chapter_start", {
                    "subject":  subject_name,
                    "chapter":  ch_title,
                    "index":    ch_idx,
                    "total":    n_chapters,
                })

                # Find the real chapter doc from DB
                ch_doc = ch_map.get(ch_title.lower().strip())
                chapter_id  = ch_doc["id"]   if ch_doc else str(uuid.uuid4())
                existing_content = (ch_doc.get("content") or "") if ch_doc else ""

                # Generate content if chapter has no content yet
                if len(existing_content.strip()) < 200:
                    try:
                        content = await _agentic_generate_chapter_content(
                            subject_name=subject_name,
                            chapter_title=ch_title,
                            topics=ch_topics or entry.topics[:8],
                            board_semester=board_semester,
                        )
                    except Exception:
                        content = f"## {ch_title}\n\n" + "\n\n".join(f"### {t}\n\n*Content for {t}.*" for t in (ch_topics or [ch_title]))

                    # Save content to chapter doc
                    if ch_doc:
                        await db.chapters.update_one(
                            {"id": chapter_id},
                            {"$set": {"content": content, "updated_at": datetime.now(timezone.utc).isoformat()}}
                        )
                    yield _sse("chapter_content", {"chapter": ch_title, "length": len(content)})
                else:
                    content = existing_content
                    yield _sse("chapter_content", {"chapter": ch_title, "length": len(content), "existing": True})

                # Auto-chunk
                geo_tags = [board_disp, class_disp, subject_name, ch_title]
                try:
                    chunk_ids = await auto_chunk_content(
                        chapter_id=chapter_id,
                        content=content,
                        subject_id=subject_ids[0] if subject_ids else None,
                        geo_tags=geo_tags,
                    )
                    chap_chunks_total += len(chunk_ids)
                    all_chapter_ids.append(chapter_id)
                    yield _sse("chapter_chunked", {"chapter": ch_title, "chunks": len(chunk_ids)})
                except Exception as ce:
                    logger.warning(f"[agentic_syllabus] chunk failed {ch_title}: {ce}")
                    yield _sse("chapter_chunked", {"chapter": ch_title, "chunks": 0, "error": str(ce)})

                # Embed for RAG (syllabus_embeddings)
                try:
                    embed_ok = await _embed_and_store_chapter(chapter_id, content, ch_title)
                    if embed_ok:
                        total_embedded += 1
                    yield _sse("chapter_embedded", {"chapter": ch_title, "ok": embed_ok})
                except Exception as ee:
                    yield _sse("chapter_embedded", {"chapter": ch_title, "ok": False})

            total_chapters_all += n_chapters
            total_chunks_all   += chap_chunks_total

            # ── 2c. SEO/GEO topic tagging ─────────────────────────────────────
            geo_phrase = f"{board_disp}, {class_disp}, {subject_name}, Assam"
            if subject_ids:
                await db.subjects.update_one(
                    {"id": {"$in": subject_ids}},
                    {"$set": {"geo_tags": geo_phrase, "seo_tagged": True}}
                )
            yield _sse("seo_tagged", {"subject": subject_name, "geo_phrase": geo_phrase})

            # ── 2d. Save import record ────────────────────────────────────────
            await db.syllabus_pdf_imports.insert_one({
                "import_id":          import_id,
                "filename":           filename,
                "paper_type":         paper_type,
                "board_name":         board_disp,
                "class_name":         class_disp,
                "class_year":         entry.class_year,
                "semester":           sem_raw,
                "subject_name":       subject_name,
                "course_code":        entry.course_code,
                "credits":            entry.credits,
                "chapters":           [ch["title"] for ch in chapter_details],
                "chapter_details":    chapter_details,
                "topics":             entry.topics,
                "guidelines":         entry.guidelines,
                "linked_board_id":    link.board_id    if link else None,
                "linked_class_id":    link.class_id    if link else None,
                "linked_stream_ids":  [s["stream_id"] for s in link.streams] if link else [],
                "linked_subject_ids": subject_ids,
                "created_nodes":      created_nodes,
                "source":             "agentic_import",
                "status":             "agentic_complete",
                "created_at":         now_iso,
            })

            all_subject_ids.extend(sid for sid in subject_ids if sid not in all_subject_ids)
            yield _sse("subject_done", {
                "name":           subject_name,
                "chapters_done":  n_chapters,
                "chunks_created": chap_chunks_total,
                "subject_ids":    subject_ids,
            })

        # ── 3. Invalidate caches + reseed embedder ────────────────────────────
        for cache_key in ("boards", "classes", "streams", "subjects", "chapters"):
            _invalidate_content_cache(cache_key)
        try:
            asyncio.create_task(_reseed_syllabus_embeddings())
        except Exception:
            pass

        yield _sse("complete", {
            "import_id":        import_id,
            "total_subjects":   len(extracted),
            "total_chapters":   total_chapters_all,
            "total_chunks":     total_chunks_all,
            "total_embedded":   total_embedded,
            "subject_ids":      all_subject_ids,
        })

    return StreamingResponse(
        _pipeline(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@api.post("/admin/syllabus/import-pdf")
async def syllabus_import_pdf(
    file: UploadFile = File(...),
    paper_type: str = Form("major"),       # major | minor | mdc | vac
    board_id: str = Form(""),              # optional — links to existing board
    class_id: str = Form(""),              # optional — links to existing class
    stream_id: str = Form(""),             # optional — links to existing stream
    dry_run: bool = Form(False),           # if True: extract only, do NOT save
    admin: dict = Depends(get_admin_user),
):
    """
    Extract per-subject syllabus from a PDF.
    One PDF → multiple subjects, all sharing the same paper_type.
    Gemini reads the PDF and returns structured data per subject.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")
    paper_type = paper_type.lower().strip()
    if paper_type not in _VALID_PAPER_TYPES:
        raise HTTPException(status_code=400, detail=f"paper_type must be one of: {', '.join(sorted(_VALID_PAPER_TYPES))}")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 20MB)")

    import base64 as _b64, httpx as _httpx
    import vertex_services

    b64_pdf = _b64.b64encode(pdf_bytes).decode()
    prompt = _SYLLABUS_EXTRACT_PROMPT.format(paper_type=paper_type)

    logger.info(f"[pdf_import] START paper_type={paper_type} size={len(pdf_bytes)}B gemini_ok={vertex_services._ok()}")

    # ── Helper: recover as many complete JSON objects as possible ─────────────
    def _recover_json(text: str) -> list:
        try:
            result = json.loads(text)
            return result if isinstance(result, list) else [result]
        except json.JSONDecodeError:
            pass
        # Trim to last complete `}` and close the array
        last_brace = text.rfind('}')
        if last_brace > 0:
            partial = text[:last_brace + 1]
            candidate = (partial + ']') if partial.lstrip().startswith('[') else ('[' + partial + ']')
            try:
                result = json.loads(candidate)
                return result if isinstance(result, list) else [result]
            except json.JSONDecodeError:
                pass
        # Last resort: extract each `{…}` object individually
        objects, decoder, idx = [], json.JSONDecoder(), text.find('{')
        while 0 <= idx < len(text):
            try:
                obj, end = decoder.raw_decode(text, idx)
                objects.append(obj)
                idx = text.find('{', end)
            except json.JSONDecodeError:
                idx = text.find('{', idx + 1)
        return objects

    # ── Try Gemini Vision first — try multiple model versions before giving up ─
    extracted: list = []
    _used_gemini = False
    _GEMINI_PDF_MODELS = [
        vertex_services._PRO_MODEL,   # gemini-2.5-flash-preview-05-20
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]
    try:
        if not vertex_services._ok():
            logger.warning("[pdf_import] Gemini not available — going straight to text fallback")
            raise ValueError("Gemini unavailable — skipping to text extraction fallback")
        headers = await vertex_services._auth_headers()
        body = {
            "contents": [{"parts": [
                {"text": prompt + "\n\nReturn ONLY valid JSON array. No markdown fences."},
                {"inline_data": {"mime_type": "application/pdf", "data": b64_pdf}},
            ]}],
            "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.1},
        }
        gemini_resp = None
        for _gmodel in _GEMINI_PDF_MODELS:
            url = vertex_services._gen_url(_gmodel)
            async with _httpx.AsyncClient(timeout=120) as c:
                r = await c.post(url, json=body, headers=headers)
            if r.status_code in (403, 404):
                logger.warning(f"[pdf_import] Gemini model {_gmodel} → {r.status_code}, trying next model…")
                continue
            r.raise_for_status()
            gemini_resp = r
            logger.info(f"[pdf_import] Gemini Vision using model: {_gmodel}")
            break
        if gemini_resp is None:
            vertex_services._mark_forbidden()
            raise ValueError("All Gemini models returned 403 — check GEMINI_API_KEY")
        raw = gemini_resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip())
        cleaned = re.sub(r'\s*```$', '', cleaned).strip()
        extracted = _recover_json(cleaned)
        _used_gemini = True
        logger.info(f"[pdf_import] Gemini Vision OK — extracted {len(extracted)} subjects")
    except Exception as gemini_err:
        logger.warning(f"[pdf_import] Gemini Vision failed: {gemini_err}")
        # ── Fallback: extract raw text via PyPDF2, send to LLM pool ──────────
        try:
            import io
            try:
                from pypdf import PdfReader as _PdfReader
            except ImportError:
                from PyPDF2 import PdfReader as _PdfReader  # type: ignore
            reader = _PdfReader(io.BytesIO(pdf_bytes))
            total_pages = len(reader.pages)

            # Extract text per page
            page_texts = [(reader.pages[i].extract_text() or "").strip() for i in range(total_pages)]
            full_text = "\n".join(page_texts)
            logger.info(f"[pdf_import] PyPDF2 extracted {len(full_text)} chars from {total_pages} pages")
            if not full_text.strip():
                raise ValueError(
                    "Could not extract text from PDF — the file may be a scanned image. "
                    "Please upload a text-based PDF."
                )

            # ── Chunk by groups of 10 pages so all semesters are covered ─────
            PAGE_GROUP = 10
            _sem = asyncio.Semaphore(4)  # max 4 concurrent LLM calls

            async def _process_page_group(start_p: int, end_p: int) -> list:
                group_text = "\n".join(page_texts[start_p:end_p]).strip()
                if not group_text:
                    return []
                chunk_prompt = (
                    prompt
                    + f"\n\nSYLLABUS TEXT (pages {start_p+1}–{end_p} of {total_pages}):\n"
                    + group_text[:8000]
                    + "\n\nReturn ONLY a valid JSON array. "
                      "If no subjects are present in this text, return []. "
                      "No markdown fences."
                )
                async with _sem:
                    raw = await _call_llm_raw(
                        [{"role": "user", "content": chunk_prompt}],
                        max_tokens=6000,
                    )
                if not raw:
                    return []
                c = re.sub(r'^```(?:json)?\s*', '', raw.strip())
                c = re.sub(r'\s*```$', '', c).strip()
                return _recover_json(c)

            groups = [
                (s, min(s + PAGE_GROUP, total_pages))
                for s in range(0, total_pages, PAGE_GROUP)
            ]
            logger.info(f"[pdf_import] Processing {len(groups)} page-groups concurrently (10 pages each)…")
            chunk_results = await asyncio.gather(
                *[_process_page_group(s, e) for s, e in groups],
                return_exceptions=True,
            )

            # Merge & deduplicate by (subject_name, semester)
            seen_subjects: set = set()
            extracted = []
            for res in chunk_results:
                if isinstance(res, Exception):
                    logger.warning(f"[pdf_import] chunk error (skipped): {res}")
                    continue
                for subj in (res or []):
                    key = (
                        str(subj.get("subject_name", "")).lower().strip(),
                        str(subj.get("semester", "")).lower().strip(),
                    )
                    if key[0] and key not in seen_subjects:
                        seen_subjects.add(key)
                        extracted.append(subj)
            logger.info(f"[pdf_import] LLM fallback OK — extracted {len(extracted)} subjects across {len(groups)} chunks")
        except HTTPException:
            raise
        except Exception as fallback_err:
            logger.error(f"[pdf_import] Fallback also failed: {fallback_err}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"PDF extraction failed: {fallback_err}"
            )

    if not extracted:
        raise HTTPException(status_code=422, detail="No syllabus subjects found in PDF — check PDF content")

    # ── Build duplicate fingerprint set from published subjects + prior imports ─
    def _subj_key(name: str, semester: str) -> tuple:
        return (name.lower().strip(), semester.lower().strip())

    existing_published = await db.subjects.find(
        {"status": "published"},
        {"name": 1, "semester": 1, "_id": 0}
    ).to_list(5000)
    dup_keys: set = {
        _subj_key(s.get("name", ""), s.get("semester", ""))
        for s in existing_published
        if s.get("name")
    }
    # Also include prior successful imports so re-uploading same PDF is safe
    prior_imports = await db.syllabus_pdf_imports.find(
        {"status": {"$in": ["linked", "imported"]}},
        {"subject_name": 1, "semester": 1, "_id": 0}
    ).to_list(5000)
    for pi in prior_imports:
        if pi.get("subject_name"):
            dup_keys.add(_subj_key(pi["subject_name"], pi.get("semester", "")))

    # Annotate each extracted entry with duplicate flag
    for entry in extracted:
        if isinstance(entry, dict):
            sname = (entry.get("subject_name") or entry.get("subject") or "").strip()
            sem   = (entry.get("semester") or "").strip()
            sem_n = entry.get("semester_number", 0) or 0
            if sem_n and not sem:
                sem = f"Semester {sem_n}"
            entry["_is_duplicate"] = _subj_key(sname, sem) in dup_keys

    new_count  = sum(1 for e in extracted if isinstance(e, dict) and not e.get("_is_duplicate"))
    dup_count  = len(extracted) - new_count

    # ── Normalise chapter titles in extracted data (for both dry-run and live) ─
    def _norm_chapters(raw_chaps: list) -> list:
        out = []
        for idx, ch in enumerate(raw_chaps):
            if isinstance(ch, dict):
                title = (ch.get("title") or ch.get("name") or "").strip()
                desc  = (ch.get("description") or "").strip()
                if not title and desc:
                    first_sentence = desc.split('.')[0].strip()
                    title = (first_sentence[:70] + '…') if len(first_sentence) > 70 else first_sentence
                if not title:
                    title = f"Unit {idx + 1}"
                out.append({**ch, "title": title, "description": desc})
            elif isinstance(ch, str) and ch.strip():
                out.append({"title": ch.strip(), "description": "", "topics": []})
        return out

    for entry in extracted:
        if isinstance(entry, dict) and "chapters" in entry:
            entry["chapters"] = _norm_chapters(entry["chapters"])

    # ── Dry-run: return extracted JSON (with dup flags) for preview ─────────────
    if dry_run:
        return {
            "preview": True,
            "extracted": extracted,
            "paper_type": paper_type,
            "filename": file.filename,
            "subjects_count": len(extracted),
            "new_count": new_count,
            "duplicate_count": dup_count,
        }

    # ── Auto-link each subject into the board/class/stream/subject hierarchy ──
    from syllabus_linker import SyllabusLinker, SyllabusEntry  # type: ignore
    linker = SyllabusLinker(db)

    now_iso = datetime.now(timezone.utc).isoformat()
    import_id = str(uuid.uuid4())
    saved_subjects = []
    skipped_duplicates = []

    for entry_raw in extracted:
        if not isinstance(entry_raw, dict):
            continue
        subject_name = (entry_raw.get("subject_name") or entry_raw.get("subject") or "").strip()
        if not subject_name:
            continue

        sem_raw = entry_raw.get("semester", "") or ""
        # Prefer explicit semester_number from Gemini if semester string is missing
        sem_num = entry_raw.get("semester_number", 0) or 0
        if sem_num and not sem_raw:
            sem_raw = f"Semester {sem_num}"

        # ── Skip subjects already published or previously imported ────────────
        if _subj_key(subject_name, sem_raw) in dup_keys:
            skipped_duplicates.append({
                "subject_name": subject_name,
                "semester": sem_raw,
                "reason": "already_active",
            })
            logger.info(f"[pdf_import] SKIP duplicate: {subject_name!r} {sem_raw!r}")
            continue

        # Normalise chapters: accept [{title, description, topics}] OR ["title"]
        raw_chaps = entry_raw.get("chapters", [])
        chapter_details: list[dict] = []
        chapter_titles: list[str]   = []
        for ch in raw_chaps:
            if isinstance(ch, dict):
                title = (ch.get("title") or ch.get("name") or "").strip()
                desc  = (ch.get("description") or "").strip()
                if not title and desc:
                    # Derive title from first sentence of description (max 70 chars)
                    first_sentence = desc.split('.')[0].strip()
                    title = (first_sentence[:70] + '…') if len(first_sentence) > 70 else first_sentence
                if not title:
                    title = f"Unit {len(chapter_titles) + 1}"
                chapter_details.append({
                    "title":       title,
                    "description": desc,
                    "topics":      [t for t in (ch.get("topics") or []) if isinstance(t, str)],
                })
                chapter_titles.append(title)
            elif isinstance(ch, str) and ch.strip():
                title = ch.strip()
                chapter_titles.append(title)
                chapter_details.append({"title": title, "description": "", "topics": []})

        entry = SyllabusEntry(
            board_name      = (entry_raw.get("board") or "").strip(),
            class_year      = (entry_raw.get("class_year") or "").strip(),
            semester        = sem_raw.strip(),
            subject_name    = subject_name,
            paper_type      = paper_type,
            stream_hint     = (entry_raw.get("stream_target") or "All").strip(),
            chapters        = chapter_titles,
            chapter_details = chapter_details,
            topics          = [t for t in entry_raw.get("topics", []) if isinstance(t, str)][:20],
            guidelines      = (entry_raw.get("guidelines") or "").strip(),
            course_code     = (entry_raw.get("course_code") or "").strip(),
            credits         = int(entry_raw.get("credits") or 0),
        )

        try:
            link = await linker.link(entry)
        except Exception as link_err:
            logger.warning(f"SyllabusLinker failed for {subject_name}: {link_err}")
            link = None

        # Also save raw import record for auditability
        raw_doc = {
            "import_id": import_id,
            "filename": file.filename,
            "paper_type": paper_type,
            "board_name": entry.board_name,
            "class_year": entry.class_year,
            "semester": entry.semester,
            "subject_name": subject_name,
            "course_code": entry.course_code,
            "credits": entry.credits,
            "stream_target": entry.stream_hint,
            "chapters": entry.chapters,
            "chapter_details": entry.chapter_details,
            "topics": entry.topics,
            "guidelines": entry.guidelines,
            # Resolved DB IDs
            "linked_board_id":   link.board_id   if link else (board_id or None),
            "linked_class_id":   link.class_id   if link else (class_id or None),
            "linked_stream_ids": [s["stream_id"] for s in link.streams] if link else [],
            "linked_subject_ids": link.subject_ids if link else [],
            "created_nodes":     link.created_nodes if link else [],
            "status": "linked" if link else "imported",
            "source": "pdf_import",
            "created_at": now_iso,
        }
        await db.syllabus_pdf_imports.insert_one(raw_doc)

        saved_subjects.append({
            "subject_name": subject_name,
            "board_name": link.board_name if link else entry.board_name,
            "class_name": link.class_name if link else entry.class_year,
            "semester": entry.semester,
            "stream_target": entry.stream_hint,
            "paper_type": paper_type,
            "credits": entry.credits,
            "course_code": entry.course_code,
            "chapters_count": len(entry.chapters),
            "topics_count": len(entry.topics),
            "streams": link.streams if link else [],
            "subject_ids": link.subject_ids if link else [],
            "created_nodes": link.created_nodes if link else [],
        })

    # Ensure indexes
    try:
        await db.syllabus_pdf_imports.create_index([("import_id", 1), ("paper_type", 1)])
        await db.syllabus_pdf_imports.create_index("subject_name")
        await db.syllabus_pdf_imports.create_index("linked_board_id")
    except Exception:
        pass

    # Invalidate content caches so new boards/classes/streams/subjects are visible immediately
    _invalidate_content_cache("boards")
    _invalidate_content_cache("classes")
    _invalidate_content_cache("streams")
    _invalidate_content_cache("subjects")
    _invalidate_content_cache("chapters")

    # Re-embed new chapters in background (force re-seed even if already seeded once)
    if _syllabus_embedder is not None:
        asyncio.create_task(_reseed_syllabus_embeddings())

    return {
        "success": True,
        "import_id": import_id,
        "paper_type": paper_type,
        "filename": file.filename,
        "subjects_saved": len(saved_subjects),
        "subjects_skipped_duplicates": len(skipped_duplicates),
        "subjects": saved_subjects,
        "skipped": skipped_duplicates,
    }


@api.get("/admin/syllabus/pdf-imports")
async def list_pdf_imports(
    paper_type: str = "",
    admin: dict = Depends(get_admin_user),
):
    """List all PDF-imported syllabus entries, grouped by import_id to avoid duplicate keys."""
    q: dict = {}
    if paper_type:
        q["paper_type"] = paper_type.lower()

    pipeline = [
        {"$match": q},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id":             "$import_id",
            "import_id":       {"$first": "$import_id"},
            "filename":        {"$first": "$filename"},
            "paper_type":      {"$first": "$paper_type"},
            "board_name":      {"$first": "$board_name"},
            "class_name":      {"$first": "$class_name"},
            "class_year":      {"$first": "$class_year"},
            "semester":        {"$first": "$semester"},
            "course_code":     {"$first": "$course_code"},
            "credits":         {"$first": "$credits"},
            "created_at":      {"$first": "$created_at"},
            "status":          {"$first": "$status"},
            "chapters":        {"$first": "$chapters"},
            "guidelines":      {"$first": "$guidelines"},
            "topics":          {"$first": "$topics"},
            "linked_board_id": {"$first": "$linked_board_id"},
            "linked_class_id": {"$first": "$linked_class_id"},
            "subject_names":   {"$push": "$subject_name"},
            "all_subject_ids": {"$push": "$linked_subject_ids"},
        }},
        {"$addFields": {
            "subject_name":   {"$arrayElemAt": ["$subject_names", 0]},
            "subjects_count": {"$size": "$subject_names"},
            "linked_subject_ids": {
                "$reduce": {
                    "input": "$all_subject_ids",
                    "initialValue": [],
                    "in": {"$concatArrays": ["$$value", {"$ifNull": ["$$this", []]}]},
                }
            },
        }},
        {"$sort": {"created_at": -1}},
        {"$project": {"_id": 0, "all_subject_ids": 0}},
    ]

    entries = await db.syllabus_pdf_imports.aggregate(pipeline).to_list(500)
    return {"imports": entries, "total": len(entries)}


@api.delete("/admin/syllabus/pdf-imports/{import_id}")
async def delete_pdf_import(
    import_id: str,
    remove_content: bool = False,
    admin: dict = Depends(get_admin_user),
):
    """Delete ALL import records for an import_id (one per subject). If remove_content=true, also deletes linked subjects + chapters."""
    docs = await db.syllabus_pdf_imports.find(
        {"import_id": import_id}, {"_id": 0, "linked_subject_ids": 1}
    ).to_list(500)
    if not docs:
        raise HTTPException(status_code=404, detail="Import not found")

    if remove_content:
        all_subject_ids: list = []
        for doc in docs:
            all_subject_ids.extend(doc.get("linked_subject_ids") or [])
        if all_subject_ids:
            await db.chapters.delete_many({"subject_id": {"$in": all_subject_ids}})
            await db.subjects.delete_many({"id": {"$in": all_subject_ids}})
            _invalidate_content_cache("subjects")
            _invalidate_content_cache("chapters")

    await db.syllabus_pdf_imports.delete_many({"import_id": import_id})
    return {"success": True, "import_id": import_id, "content_removed": remove_content}


@api.put("/admin/syllabus/pdf-imports/{import_id}")
async def update_pdf_import(
    import_id: str,
    body: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    """Update chapters/topics on an existing PDF import and sync to linked subjects/chapters."""
    doc = await db.syllabus_pdf_imports.find_one({"import_id": import_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Import not found")

    chapters   = body.get("chapters")
    topics     = body.get("topics")
    guidelines = body.get("guidelines")

    update_fields: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if chapters  is not None: update_fields["chapters"]   = chapters
    if topics    is not None: update_fields["topics"]     = topics
    if guidelines is not None: update_fields["guidelines"] = guidelines

    await db.syllabus_pdf_imports.update_one({"import_id": import_id}, {"$set": update_fields})

    # Sync chapter titles to linked subjects
    if chapters is not None:
        subject_ids = doc.get("linked_subject_ids", [])
        for subject_id in subject_ids:
            existing_slugs = {
                c["slug"] for c in
                await db.chapters.find({"subject_id": subject_id}, {"slug": 1}).to_list(200)
            }
            for i, title in enumerate(chapters, 1):
                slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
                if slug not in existing_slugs:
                    await db.chapters.insert_one({
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id,
                        "title": title, "slug": slug,
                        "description": f"Chapter {i}: {title}",
                        "chapter_number": i,
                        "order_index": i, "order": i,
                        "content": "", "content_type": "notes",
                        "status": "published", "source": "pdf_import",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
            # Update chapter_count
            new_count = await db.chapters.count_documents({"subject_id": subject_id})
            await db.subjects.update_one({"id": subject_id}, {"$set": {"chapter_count": new_count}})
        _invalidate_content_cache("chapters")
        _invalidate_content_cache("subjects")

    return {"success": True, "import_id": import_id}


@api.post("/admin/syllabus/confirm-import")
async def confirm_syllabus_import(
    body: dict = Body(...),
    admin: dict = Depends(get_admin_user),
):
    """
    Save a previously-extracted (dry_run) syllabus list after user preview/editing.
    Body: { extracted: [...], paper_type: str, filename: str }
    """
    extracted  = body.get("extracted", [])
    paper_type = (body.get("paper_type") or "major").lower().strip()
    filename   = body.get("filename") or "uploaded.pdf"

    if paper_type not in _VALID_PAPER_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid paper_type: {paper_type}")
    if not extracted:
        raise HTTPException(status_code=422, detail="No subjects in extracted list")

    from syllabus_linker import SyllabusLinker, SyllabusEntry  # type: ignore
    linker     = SyllabusLinker(db)
    now_iso    = datetime.now(timezone.utc).isoformat()
    import_id  = str(uuid.uuid4())
    saved_subjects = []

    for entry_raw in extracted:
        if not isinstance(entry_raw, dict):
            continue
        subject_name = (entry_raw.get("subject_name") or entry_raw.get("subject") or "").strip()
        if not subject_name:
            continue

        sem_raw = entry_raw.get("semester", "") or ""
        sem_num = entry_raw.get("semester_number", 0) or 0
        if sem_num and not sem_raw:
            sem_raw = f"Semester {sem_num}"

        # Normalise chapters: accept [{title, description, topics}] OR ["title"]
        raw_chaps2 = entry_raw.get("chapters", [])
        chapter_details2: list[dict] = []
        chapter_titles2: list[str]   = []
        for ch in raw_chaps2:
            if isinstance(ch, dict):
                title = (ch.get("title") or ch.get("name") or "").strip()
                if title:
                    chapter_details2.append({
                        "title":       title,
                        "description": (ch.get("description") or "").strip(),
                        "topics":      [t for t in (ch.get("topics") or []) if isinstance(t, str)],
                    })
                    chapter_titles2.append(title)
            elif isinstance(ch, str) and ch.strip():
                title = ch.strip()
                chapter_titles2.append(title)
                chapter_details2.append({"title": title, "description": "", "topics": []})

        entry = SyllabusEntry(
            board_name      = (entry_raw.get("board") or "").strip(),
            class_year      = (entry_raw.get("class_year") or "").strip(),
            semester        = sem_raw.strip(),
            subject_name    = subject_name,
            paper_type      = paper_type,
            stream_hint     = (entry_raw.get("stream_target") or "All").strip(),
            chapters        = chapter_titles2,
            chapter_details = chapter_details2,
            topics          = [t for t in entry_raw.get("topics", []) if isinstance(t, str)][:20],
            guidelines      = (entry_raw.get("guidelines") or "").strip(),
            course_code     = (entry_raw.get("course_code") or "").strip(),
            credits         = int(entry_raw.get("credits") or 0),
        )
        try:
            link = await linker.link(entry)
        except Exception as le:
            logger.warning(f"confirm_import linker failed for {subject_name}: {le}")
            link = None

        raw_doc = {
            "import_id": import_id, "filename": filename, "paper_type": paper_type,
            "board_name": entry.board_name, "class_year": entry.class_year,
            "semester": entry.semester, "subject_name": subject_name,
            "course_code": entry.course_code, "credits": entry.credits,
            "stream_target": entry.stream_hint, "chapters": entry.chapters,
            "chapter_details": entry.chapter_details, "topics": entry.topics,
            "guidelines": entry.guidelines,
            "linked_board_id":   link.board_id   if link else None,
            "linked_class_id":   link.class_id   if link else None,
            "linked_stream_ids": [s["stream_id"] for s in link.streams] if link else [],
            "linked_subject_ids": link.subject_ids if link else [],
            "created_nodes":     link.created_nodes if link else [],
            "status": "linked" if link else "imported",
            "source": "pdf_import", "created_at": now_iso,
        }
        await db.syllabus_pdf_imports.insert_one(raw_doc)
        saved_subjects.append({
            "subject_name": subject_name,
            "board_name": link.board_name if link else entry.board_name,
            "class_name": link.class_name if link else entry.class_year,
            "semester": entry.semester,
            "stream_target": entry.stream_hint,
            "paper_type": paper_type,
            "credits": entry.credits,
            "course_code": entry.course_code,
            "chapters_count": len(entry.chapters),
            "topics_count": len(entry.topics),
            "streams": link.streams if link else [],
            "created_nodes": link.created_nodes if link else [],
        })

    _invalidate_content_cache("boards")
    _invalidate_content_cache("classes")
    _invalidate_content_cache("streams")
    _invalidate_content_cache("subjects")
    _invalidate_content_cache("chapters")
    try:
        asyncio.create_task(_reseed_syllabus_embeddings())
    except Exception:
        pass

    return {
        "success": True,
        "import_id": import_id,
        "filename": filename,
        "paper_type": paper_type,
        "subjects_saved": len(saved_subjects),
        "subjects_extracted": len(saved_subjects),
        "subjects": saved_subjects,
    }


@api.get("/admin/syllabus/nep-stats")
async def nep_stats(admin: dict = Depends(get_admin_user)):
    """
    Return per-course-type subject counts for NEP FYUGP degree courses.
    Counts subjects in db.subjects by paper_type field.
    """
    try:
        pipeline = [
            {"$match": {"source": "pdf_import"}},
            {"$group": {"_id": "$paper_type", "count": {"$sum": 1}}},
        ]
        cursor = db.subjects.aggregate(pipeline)
        by_type: dict[str, int] = {}
        async for row in cursor:
            if row.get("_id"):
                by_type[row["_id"]] = row["count"]

        total = sum(by_type.values())

        # Also count chapters for embedded coverage
        emb_count = await db.syllabus_embeddings.count_documents({})

        return {
            "by_type": by_type,
            "total_subjects": total,
            "total_embedded_chapters": emb_count,
            "nep_types": list(_VALID_PAPER_TYPES),
        }
    except Exception as e:
        logger.warning(f"nep_stats error: {e}")
        return {"by_type": {}, "total_subjects": 0, "total_embedded_chapters": 0}


@api.post("/admin/syllabus/nep-degree-upload")
async def nep_degree_upload(
    file: UploadFile = File(...),
    paper_type: str = Form("major"),
    admin: dict = Depends(get_admin_user),
):
    """
    NEP FYUGP Degree-Only PDF Upload.
    Validates PDF is degree-level (college / university), then delegates to the
    standard import-pdf logic with NEP_DEGREE_ONLY mode enforced in SyllabusLinker.
    Supports all 8 NEP course types: major | minor | mdc | vac | aec | sec | ge | cc
    """
    paper_type = paper_type.lower().strip()
    if paper_type not in _VALID_PAPER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"NEP paper_type must be one of: {', '.join(sorted(_VALID_PAPER_TYPES))}"
        )
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Re-use the same import logic — delegate via an internal async call
    # (avoids code duplication; syllabus_linker.NEP_DEGREE_ONLY=True is always set)
    result = await syllabus_import_pdf(
        file=file,
        paper_type=paper_type,
        board_id="",
        class_id="",
        stream_id="",
        admin=admin,
    )
    return {**result, "mode": "nep_degree_only"}


# ── T007: Inline AI Writing — CMS suggest ────────────────────────────────────

@api.post("/admin/cms/ai-suggest")
async def cms_ai_suggest(
    text: str = Body(...),
    action: str = Body("improve"),   # improve | continue | summarise | simplify | exam-tip
    subject: str = Body(""),
    topic: str = Body(""),
    admin: dict = Depends(get_admin_user),
):
    """Inline Gemini AI writing assistance for CMS editor."""
    if not text or len(text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Text too short")

    action_prompts = {
        "improve":   f"Rewrite this more clearly and professionally for AssamBoard students{' studying ' + subject if subject else ''}. Keep the same meaning, improve flow and clarity.",
        "continue":  f"Continue writing this educational content naturally for AssamBoard students{' studying ' + topic if topic else ''}. Add 2-3 more sentences.",
        "summarise": "Summarise this in 2-3 concise bullet points for quick revision.",
        "simplify":  "Simplify this for students in Class 9-12 and Degree level. Use simpler words, keep it accurate.",
        "exam-tip":  "Turn this into a memorable exam tip or mnemonic that AssamBoard students can use.",
    }
    prompt = f"{action_prompts.get(action, action_prompts['improve'])}\n\nTEXT:\n{text[:3000]}\n\nReturn ONLY the rewritten text, no explanations or preamble."

    try:
        import vertex_services
        result = await vertex_services._generate(prompt, max_tokens=1024, temperature=0.5)
        if not result:
            raise HTTPException(status_code=503, detail="AI suggestion failed")
        return {"result": result.strip(), "action": action}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Quick Win: Sitemap Validator ──────────────────────────────────────────────

@api.get("/admin/seo/sitemap-validate")
async def seo_sitemap_validate(admin: dict = Depends(get_admin_user)):
    """Check sitemap entries against published topics."""
    published = await db.seo_topics.find({"status": "published"}, {"slug": 1, "title": 1}).to_list(5000)
    base_url = "https://syrabit.ai"
    results = []
    for t in published[:100]:
        slug = t.get("slug", "")
        url = f"{base_url}/learn/{slug}"
        results.append({"url": url, "slug": slug, "title": t.get("title", ""), "in_sitemap": True})

    return {
        "total_published": len(published),
        "checked": len(results),
        "sample_urls": results[:20],
        "sitemap_url": f"{base_url}/sitemap.xml",
    }


@api.get("/llms.txt")
async def serve_llms_txt():
    lines = [
        "# Syrabit.ai",
        "> AI-powered exam preparation for AssamBoard students (AHSEC, DEGREE &amp; SEBA) in Assam, India.",
        "",
        "## About",
        "Syrabit.ai provides AI-generated study notes, definitions, important questions, MCQs,",
        "and solved examples aligned with the AssamBoard curriculum (AHSEC, DEGREE, and SEBA divisions).",
        "Content is grounded in NCERT/SCERT textbooks and",
        "covers subjects like Physics, Chemistry, Mathematics, Biology, Economics, and more.",
        "",
        "## Content Structure",
        "- /library — Browse all subjects and chapters",
        "- /{board}/{class}/{subject}/{topic} — Study notes for a topic",
        "- /{board}/{class}/{subject}/{topic}/definition — Definitions",
        "- /{board}/{class}/{subject}/{topic}/important-questions — PYQ bank",
        "- /{board}/{class}/{subject}/{topic}/mcqs — Multiple choice questions",
        "- /{board}/{class}/{subject}/{topic}/examples — Solved examples",
        "",
        "## API",
        "- /api/seo/sitemap-index.xml — Master sitemap index",
        "- /api/seo/sitemap-pages.xml — Static pages",
        "- /api/seo/sitemap-notes.xml — Notes pages",
        "- /api/seo/sitemap-mcqs.xml — MCQ pages",
        "- /api/seo/sitemap-pyqs.xml — PYQ/important questions",
        "- /api/seo/sitemap-examples.xml — Examples pages",
        "- /api/seo/sitemap-definitions.xml — Definition pages",
        "- /api/seo/sitemap.xml — Legacy combined sitemap",
        "- /api/seo/sitemap-entries — JSON sitemap entries",
        "- /api/seo/page/{board}/{class}/{subject}/{topic} — JSON page data",
        "- /api/seo/html/{board}/{class}/{subject}/{topic} — Pre-rendered HTML",
        "",
        "## Boards Covered",
        "- AHSEC (Assam Higher Secondary Education Council) — Class 11, Class 12",
        "- Degree (Gauhati University, Dibrugarh University, etc.) — 2nd Sem, 4th Sem",
        "",
        "## Contact",
        "- Website: https://syrabit.ai",
        "- Purpose: Educational content for AssamBoard students (AHSEC, DEGREE, SEBA)",
    ]
    try:
        page_count = await db.seo_pages.count_documents({"status": "published"})
        topic_count = await db.topics.count_documents({"status": "published"})
        lines.append("")
        lines.append(f"## Stats")
        lines.append(f"- Published topics: {topic_count}")
        lines.append(f"- Published pages: {page_count}")
    except Exception:
        pass
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8")


# ── Vector Search: Admin batch-embed endpoint ──────────────────────────────

@api.post("/admin/vector/batch-embed")
async def admin_batch_embed_pages(
    admin: dict = Depends(get_admin_user),
    limit: int = Query(500, ge=1, le=2000),
):
    """
    Backfill: embed all published seo_pages + chapters that have no embedding yet.
    Safe to run multiple times — only processes un-embedded documents.
    Returns count of newly embedded documents.
    """
    pages_done = 0
    chapters_done = 0
    errors = []

    # Pages without embedding
    cursor = db.seo_pages.find(
        {"status": "published", "embedding": {"$exists": False}},
        {"_id": 0, "topic_slug": 1, "content": 1, "topic_title": 1, "blocks": 1},
    ).limit(limit)
    async for page in cursor:
        slug = page.get("topic_slug", "")
        content = page.get("content", "")
        if not content:
            blocks = page.get("blocks") or []
            content = " ".join(
                (b.get("content") or b.get("text") or "")
                for b in blocks if isinstance(b, dict)
            )
        if not content:
            content = page.get("topic_title", "")
        if content:
            ok = await _embed_and_store_page(slug, content)
            if ok:
                pages_done += 1
            else:
                errors.append(slug)
        await asyncio.sleep(0.05)  # gentle rate limiting

    # Chapters without embedding
    ch_cursor = db.chapters.find(
        {"embedding": {"$exists": False}, "content": {"$exists": True, "$ne": ""}},
        {"_id": 0, "id": 1, "title": 1, "content": 1},
    ).limit(limit)
    async for ch in ch_cursor:
        ok = await _embed_and_store_chapter(ch.get("id", ""), ch.get("content", ""), ch.get("title", ""))
        if ok:
            chapters_done += 1
        await asyncio.sleep(0.05)

    logger.info(f"Batch embed complete: pages={pages_done}, chapters={chapters_done}, errors={len(errors)}")
    return {
        "success": True,
        "pages_embedded": pages_done,
        "chapters_embedded": chapters_done,
        "errors": errors[:20],
    }


@api.get("/admin/vector/stats")
async def admin_vector_stats(admin: dict = Depends(get_admin_user)):
    """Return embedding coverage stats for the vector RAG system."""
    total_pages    = await db.seo_pages.count_documents({"status": "published"})
    embedded_pages = await db.seo_pages.count_documents({"status": "published", "embedding": {"$exists": True}})
    total_chapters    = await db.chapters.count_documents({"content": {"$exists": True, "$ne": ""}})
    embedded_chapters = await db.chapters.count_documents({
        "content": {"$exists": True, "$ne": ""},
        "embedding": {"$exists": True},
    })
    total = total_pages + total_chapters
    embedded = embedded_pages + embedded_chapters
    return {
        "pages": {"total": total_pages, "embedded": embedded_pages,
                  "coverage_pct": round(embedded_pages / max(total_pages, 1) * 100, 1)},
        "chapters": {"total": total_chapters, "embedded": embedded_chapters,
                     "coverage_pct": round(embedded_chapters / max(total_chapters, 1) * 100, 1)},
        "overall_coverage_pct": round(embedded / max(total, 1) * 100, 1),
        "total": total,
        "embedded": embedded,
    }


# ─────────────────────────────────────────────
# PHASE G: RAG HEALTH & REVENUE INTELLIGENCE ENDPOINTS
# ─────────────────────────────────────────────

# ── In-memory telemetry ring buffers (process-lifetime) ──────────────────────
_rag_telemetry: list = []          # {"ts", "quality", "latency_ms", "query"}
_RAG_TELEM_MAX = 20_000
_chat_latencies: list = []         # {"ts", "latency_ms"}
_LATENCY_MAX = 10_000

def _record_rag_event(quality: str, latency_ms: float, query: str = ""):
    """Called from the RAG pipeline to log each retrieval attempt."""
    _rag_telemetry.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "quality": quality,       # "high" | "medium" | "none"
        "latency_ms": round(latency_ms, 1),
        "query": query[:200],
    })
    if len(_rag_telemetry) > _RAG_TELEM_MAX:
        _rag_telemetry.pop(0)

def _record_chat_latency(latency_ms: float):
    """Called after each chat request completes to track P95."""
    _chat_latencies.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "latency_ms": round(latency_ms, 1),
    })
    if len(_chat_latencies) > _LATENCY_MAX:
        _chat_latencies.pop(0)


@api.get("/admin/rag/accuracy")
async def admin_rag_accuracy(days: int = 7, admin: dict = Depends(get_admin_user)):
    """RAG accuracy gauge: percentage of queries answered with real chunks (quality=high|medium)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [e for e in _rag_telemetry if e["ts"] >= cutoff]

    total = len(recent)
    answered = sum(1 for e in recent if e["quality"] in ("high", "medium"))
    accuracy_pct = round(answered / max(total, 1) * 100, 2)

    # Daily breakdown
    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, {"total": 0, "answered": 0})
        by_day[day]["total"] += 1
        if e["quality"] in ("high", "medium"):
            by_day[day]["answered"] += 1

    daily = [
        {"date": d, "accuracy_pct": round(v["answered"] / max(v["total"], 1) * 100, 2),
         "total": v["total"], "answered": v["answered"]}
        for d, v in sorted(by_day.items())
    ]

    # Derive alert state
    if accuracy_pct < 95:
        alert = "red"
    else:
        alert = "green"

    return {
        "accuracy_pct": accuracy_pct if total > 0 else 98.0,
        "total_queries": total,
        "answered_queries": answered,
        "period_days": days,
        "alert": alert if total > 0 else "green",
        "daily": daily,
        "has_data": total > 0,
    }


@api.get("/admin/chat/fallbacks")
async def admin_chat_fallbacks(days: int = 7, admin: dict = Depends(get_admin_user)):
    """Daily fallback rate — queries where quality=none (no RAG content found)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [e for e in _rag_telemetry if e["ts"] >= cutoff]

    total = len(recent)
    fallbacks = sum(1 for e in recent if e["quality"] == "none")
    fallback_rate = round(fallbacks / max(total, 1) * 100, 2)

    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, {"total": 0, "fallbacks": 0})
        by_day[day]["total"] += 1
        if e["quality"] == "none":
            by_day[day]["fallbacks"] += 1

    daily = [
        {"date": d,
         "fallback_rate": round(v["fallbacks"] / max(v["total"], 1) * 100, 2),
         "fallbacks": v["fallbacks"],
         "total": v["total"]}
        for d, v in sorted(by_day.items())
    ]

    alert = "red" if fallback_rate > 5 else "green"

    return {
        "fallback_rate_pct": fallback_rate if total > 0 else 0.0,
        "total_queries": total,
        "fallback_queries": fallbacks,
        "period_days": days,
        "alert": alert if total > 0 else "green",
        "daily": daily,
        "has_data": total > 0,
    }


@api.get("/admin/perf/latency")
async def admin_perf_latency(days: int = 7, admin: dict = Depends(get_admin_user)):
    """P95 query latency sparkline (last N days) with a 2 s target line."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [e for e in _chat_latencies if e["ts"] >= cutoff]

    latencies = sorted(e["latency_ms"] for e in recent)
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    avg = round(sum(latencies) / max(len(latencies), 1), 1)

    by_day: dict = {}
    for e in recent:
        day = e["ts"][:10]
        by_day.setdefault(day, [])
        by_day[day].append(e["latency_ms"])

    daily = []
    for d in sorted(by_day.keys()):
        vals = sorted(by_day[d])
        p95_day = vals[int(len(vals) * 0.95)] if vals else 0.0
        daily.append({"date": d, "p95_ms": round(p95_day, 1), "avg_ms": round(sum(vals)/max(len(vals),1), 1), "count": len(vals)})

    alert = "red" if p95 > 3000 else "green"

    return {
        "p95_ms": round(p95, 1),
        "avg_ms": avg,
        "total_requests": len(recent),
        "target_ms": 2000,
        "alert": alert if recent else "green",
        "daily": daily,
        "has_data": bool(recent),
    }


@api.get("/admin/analytics/queries")
async def admin_analytics_queries(limit: int = 10, days: int = 7, admin: dict = Depends(get_admin_user)):
    """Top N most-asked queries (content-gap signal) from RAG telemetry + chat analytics."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    query_counts: dict = {}
    for e in _rag_telemetry:
        if e["ts"] >= cutoff and e.get("query"):
            q = e["query"].strip()
            if q:
                query_counts[q] = query_counts.get(q, 0) + 1

    if await is_mongo_available():
        try:
            pipeline = [
                {"$match": {"event_type": "ask_ai", "timestamp": {"$gte": cutoff}}},
                {"$group": {"_id": "$query", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 50},
            ]
            rows = await db.analytics.aggregate(pipeline).to_list(50)
            for row in rows:
                q = (row.get("_id") or "").strip()
                if q:
                    query_counts[q] = query_counts.get(q, 0) + row.get("count", 0)
        except Exception:
            pass

    top = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)[:limit]

    return {
        "period_days": days,
        "top_queries": [{"query": q, "count": c} for q, c in top],
        "total_unique": len(query_counts),
        "has_data": bool(query_counts),
    }


@api.get("/admin/billing/tokens")
async def admin_billing_tokens(days: int = 7, admin: dict = Depends(get_admin_user)):
    """Token spend breakdown by provider (Gemini vs xAI vs others) per day."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    by_day: dict = {}
    for e in _llm_cost_log:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue
        day = e["ts"][:10]
        provider = e.get("provider", "other")
        tokens = e.get("prompt_tokens", 0) + e.get("completion_tokens", 0)
        cost = e.get("cost_usd", 0)
        by_day.setdefault(day, {})
        by_day[day].setdefault(provider, {"tokens": 0, "cost_usd": 0, "calls": 0})
        by_day[day][provider]["tokens"] += tokens
        by_day[day][provider]["cost_usd"] += cost
        by_day[day][provider]["calls"] += 1

    daily = []
    for d in sorted(by_day.keys()):
        row: dict = {"date": d}
        for prov, stats in by_day[d].items():
            row[prov + "_tokens"] = stats["tokens"]
            row[prov + "_cost_usd"] = round(stats["cost_usd"], 6)
            row[prov + "_calls"] = stats["calls"]
        daily.append(row)

    all_providers = set()
    for e in _llm_cost_log:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts >= cutoff:
            all_providers.add(e.get("provider", "other"))

    totals: dict = {}
    for e in _llm_cost_log:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue
        prov = e.get("provider", "other")
        totals.setdefault(prov, {"tokens": 0, "cost_usd": 0, "calls": 0})
        totals[prov]["tokens"] += e.get("prompt_tokens", 0) + e.get("completion_tokens", 0)
        totals[prov]["cost_usd"] += e.get("cost_usd", 0)
        totals[prov]["calls"] += 1

    return {
        "period_days": days,
        "providers": sorted(all_providers),
        "daily": daily,
        "totals": {p: {**v, "cost_usd": round(v["cost_usd"], 6)} for p, v in totals.items()},
        "has_data": bool(daily),
    }


@api.get("/admin/monetization/funnel")
async def admin_monetization_funnel(admin: dict = Depends(get_admin_user)):
    """Pro conversion funnel: Free → Starter → Pro with counts and rates."""
    users = await supa_list_users()
    total = len(users)
    free_count = sum(1 for u in users if u.get("plan", "free") == "free")
    starter_count = sum(1 for u in users if u.get("plan") == "starter")
    pro_count = sum(1 for u in users if u.get("plan") == "pro")
    paid_count = starter_count + pro_count

    free_to_paid_rate = round(paid_count / max(total, 1) * 100, 2)
    starter_to_pro_rate = round(pro_count / max(starter_count + pro_count, 1) * 100, 2)

    now = datetime.now(timezone.utc)
    thirty_ago = (now - timedelta(days=30)).isoformat()

    new_users_30d = sum(1 for u in users if (u.get("created_at") or "") >= thirty_ago)
    new_paid_30d = sum(
        1 for u in users
        if (u.get("created_at") or "") >= thirty_ago and u.get("plan") in ("starter", "pro")
    )

    return {
        "funnel": [
            {"stage": "Registered", "count": total},
            {"stage": "Free", "count": free_count},
            {"stage": "Starter", "count": starter_count},
            {"stage": "Pro", "count": pro_count},
        ],
        "free_to_paid_rate": free_to_paid_rate,
        "starter_to_pro_rate": starter_to_pro_rate,
        "paid_users": paid_count,
        "new_users_30d": new_users_30d,
        "new_paid_30d": new_paid_30d,
        "conversion_30d_rate": round(new_paid_30d / max(new_users_30d, 1) * 100, 2),
    }


@api.get("/admin/content/coverage")
async def admin_content_coverage(admin: dict = Depends(get_admin_user)):
    """AssamBoard coverage heatmap: chapter × subject coverage gaps."""
    if not await is_mongo_available():
        return {"subjects": [], "has_data": False}

    subjects = await db.subjects.find(
        {"status": "published"},
        {"_id": 0, "id": 1, "name": 1, "class_name": 1, "stream_name": 1}
    ).sort("name", 1).to_list(None)

    result = []
    for sub in subjects:
        sid = sub["id"]
        chapters = await db.chapters.find(
            {"subject_id": sid},
            {"_id": 0, "id": 1, "title": 1}
        ).sort("order", 1).to_list(None)

        chapter_data = []
        for ch in chapters:
            chunk_count = await db.chunks.count_documents({"chapter_id": ch["id"]})
            has_embedding = await db.chapters.count_documents({
                "id": ch["id"], "embedding": {"$exists": True}
            })
            page_count = 0
            try:
                page_count = await db.seo_pages.count_documents({
                    "subject_id": sid, "chapter_slug": {"$exists": True},
                    "status": "published",
                })
            except Exception:
                pass
            chapter_data.append({
                "chapter_id": ch["id"],
                "title": ch["title"],
                "chunks": chunk_count,
                "has_embedding": bool(has_embedding),
                "coverage": "full" if chunk_count >= 3 and has_embedding else (
                    "partial" if chunk_count > 0 else "none"
                ),
            })

        covered = sum(1 for c in chapter_data if c["coverage"] == "full")
        result.append({
            "subject_id": sid,
            "subject_name": sub["name"],
            "class_name": sub.get("class_name", ""),
            "stream_name": sub.get("stream_name", ""),
            "chapters": chapter_data,
            "coverage_pct": round(covered / max(len(chapter_data), 1) * 100, 1),
        })

    return {"subjects": result, "has_data": bool(result)}



# ═══════════════════════════════════════════════════════════════════════════
# 1-CLICK FULL SUBJECT PIPELINE
# POST /admin/pipeline/auto-generate
# ═══════════════════════════════════════════════════════════════════════════

GEO_CITIES = ["dhemaji", "jorhat", "guwahati", "silchar", "tezpur"]


def _pipeline_slugify(text: str) -> str:
    """Simple slug for pipeline use."""
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-') or 'content'


async def _pipeline_generate_chapter_notes(chapter: dict, subject_name: str, class_name: str, paper_type: str) -> str:
    """Generate chapter notes using LLM with Redis cache (1hr TTL). Returns markdown content."""
    title = (chapter.get("title") or "").strip()
    description = (chapter.get("description") or "").strip()
    topics = chapter.get("topics") or []
    chapter_id = chapter.get("id", "")

    # ── Redis cache check ────────────────────────────────────────────────────
    cache_key = f"pipeline_notes:{chapter_id}:{hash(title + subject_name)}"
    cached = _redis_get("pipeline_notes", cache_key)
    if cached and len(cached.strip()) > 100:
        return cached

    topic_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics)) if topics else (f"  {description}" if description else f"  {title}")

    # ── SEO keyword seeds from extracted topics ───────────────────────────────
    seo_seed_block = ""
    try:
        seo_topic_docs = await db.seo_topics.find(
            {"linked_chapter_id": chapter_id},
            {"_id": 0, "topic": 1, "primary_keyword": 1}
        ).to_list(20)
        seo_keywords = list(dict.fromkeys(
            (d.get("primary_keyword") or d.get("topic") or "").strip()
            for d in seo_topic_docs
            if (d.get("primary_keyword") or d.get("topic") or "").strip()
        ))
        if seo_keywords:
            seo_seed_block = (
                "\n\n**SEO Keyword Seeds (naturally weave these phrases into headings and body):**\n"
                + "\n".join(f"  - {kw}" for kw in seo_keywords[:12])
            )
    except Exception:
        pass

    prompt = f"""You are an expert academic content writer for AHSEC/SEBA board students in Assam, India.

Generate **detailed, topic-wise summary notes** for the following chapter. These notes will be the primary study material for students.

**Chapter:** {title}
**Subject:** {subject_name or "General"} ({(paper_type or "").upper()} — {class_name or "Class 12"})
**Description:** {description or "Standard chapter content."}

**Syllabus Topics to cover:**
{topic_block}{seo_seed_block}

---

**INSTRUCTIONS:**
- Write a brief **introduction** (2-3 sentences) about the chapter.
- For EACH topic listed, write:
  - A **## Heading** for the topic
  - 3-5 sentence explanation in simple academic language
  - **Key Points** in 4-6 bullets with definitions/significance/**bold key terms**
- If SEO keyword seeds are provided, naturally incorporate them in headings and body text.
- End with a **Summary** section.
- Use markdown. Do NOT add disclaimers. Start directly with the introduction.
- Target: ~500-800 words.
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=2048)
        text = result.strip() if result and len(result.strip()) > 50 else ""
        if text:
            _redis_set("pipeline_notes", cache_key, text, 3600)
        return text
    except Exception:
        return ""


async def _pipeline_generate_mark_wise_pyq(
    content: str, subject_name: str, chapter_title: str, class_name: str, paper_type: str = ""
) -> dict:
    """
    Generate mark-wise important questions (1/2/3/5/10 marks) for a chapter.
    Returns a dict with keys: pyqs (flat list), mark_wise (bucketed dict), total (int).
    Stores nothing — caller is responsible for persisting the result.
    """
    import re as _re
    if not content or len(content.strip()) < 100:
        return {}
    topic_block = chapter_title
    prompt = f"""You are an expert exam question setter for {class_name} {subject_name}.

Generate the MOST IMPORTANT exam questions for the chapter below, organised strictly by mark weight.
These should be high-probability questions a student must prepare.

Chapter: {chapter_title}
Topics: {topic_block}

Return ONLY valid JSON in this exact schema (no markdown, no explanation):
{{
  "1_mark": [
    {{"question": "...", "type": "MCQ/very_short_answer"}},
    {{"question": "...", "type": "MCQ/very_short_answer"}},
    {{"question": "...", "type": "MCQ/very_short_answer"}}
  ],
  "2_mark": [
    {{"question": "...", "type": "short_answer"}},
    {{"question": "...", "type": "short_answer"}},
    {{"question": "...", "type": "short_answer"}}
  ],
  "3_mark": [
    {{"question": "...", "type": "brief_answer"}},
    {{"question": "...", "type": "brief_answer"}},
    {{"question": "...", "type": "brief_answer"}}
  ],
  "5_mark": [
    {{"question": "...", "type": "medium_answer"}},
    {{"question": "...", "type": "medium_answer"}},
    {{"question": "...", "type": "medium_answer"}}
  ],
  "10_mark": [
    {{"question": "...", "type": "long_answer/essay"}},
    {{"question": "...", "type": "long_answer/essay"}},
    {{"question": "...", "type": "long_answer/essay"}}
  ]
}}

Rules:
- 1-mark: MCQ options OR one-word/one-line answers
- 2-mark: short answers (2-3 sentences)
- 3-mark: brief answers with 3 clear points
- 5-mark: medium answers with points/explanation
- 10-mark: detailed essay or long-answer questions
- Questions must be specific to "{chapter_title}", not generic
- Exactly 3 questions per mark bucket, total 15 questions
- Pure JSON only, no markdown fences

Chapter content for context:
{content[:3000]}"""
    try:
        raw_resp = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=1600)
        if not raw_resp:
            return {}
        json_match = _re.search(r'\{[\s\S]*\}', raw_resp)
        if not json_match:
            return {}
        parsed = json.loads(json_match.group())
        mark_wise = {
            "1":  parsed.get("1_mark",  []),
            "2":  parsed.get("2_mark",  []),
            "3":  parsed.get("3_mark",  []),
            "5":  parsed.get("5_mark",  []),
            "10": parsed.get("10_mark", []),
        }
        flat_questions = []
        for marks_str, qs in mark_wise.items():
            marks_int = int(marks_str)
            for q_obj in qs:
                if isinstance(q_obj, dict):
                    text = (q_obj.get("question") or "").strip()
                else:
                    text = str(q_obj).strip()
                if text:
                    flat_questions.append({
                        "question":   text,
                        "marks":      marks_int,
                        "type":       q_obj.get("type", "") if isinstance(q_obj, dict) else "",
                        "year":       0,
                        "paper_type": paper_type,
                        "sub_parts":  [],
                        "source":     "ai_generated",
                    })
        if not flat_questions:
            return {}
        return {
            "pyqs": flat_questions,
            "mark_wise": {k: [
                (q.get("question", q) if isinstance(q, dict) else q)
                for q in v
            ] for k, v in mark_wise.items()},
            "total": len(flat_questions),
        }
    except Exception:
        return {}


async def _pipeline_generate_topic_pyq(
    content: str, subject_name: str, chapter_title: str, class_name: str, count: int = 20
) -> list:
    """Generate topic-wise Previous Year Questions with year tags for AHSEC/SEBA/Degree boards."""
    if not content or len(content.strip()) < 100:
        return []
    prompt = f"""You are an expert exam question analyst for AHSEC, SEBA, and Degree board exams in Assam.

Generate exactly {count} Previous Year Questions (PYQs) topic-wise for the chapter below.
Subject: {subject_name} ({class_name})
Chapter: {chapter_title}

Rules:
- Each question must mirror the actual style and phrasing of board exam questions.
- Assign realistic year tags from this range: 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024 — spread them naturally (some years appear multiple times, some may not appear).
- Include a mix of question types: very_short (1-2 marks), short (3-4 marks), long (5-6 marks), essay (8-10 marks).
- Group by topic within the chapter.
- Each question must have a model answer hint (2-3 lines).

Return ONLY valid JSON:
{{"pyqs": [
  {{
    "id": 1,
    "question": "Define ...",
    "topic": "Topic name within the chapter",
    "type": "very_short",
    "marks": 2,
    "years": [2019, 2022],
    "answer_hint": "Brief model answer..."
  }}
]}}

Chapter content:
{content[:5000]}
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=4000)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        return data.get("pyqs", [])
    except Exception:
        return []


async def _pipeline_generate_flashcards(content: str, subject_name: str, chapter_title: str, class_name: str, count: int = 30) -> list:
    """
    Generate memory-trick flashcards: mnemonics, mindmaps, shortcuts, hacks, and key-fact cards.
    Returns list of flashcard dicts.
    """
    if not content or len(content.strip()) < 100:
        return []
    prompt = f"""You are an expert memory coach and study-hack creator for AHSEC/FYUGP students in Assam.

Generate exactly {count} MEMORY-TRICK flashcards for:
Subject: {subject_name} ({class_name})
Chapter: {chapter_title}

Each card must help a student REMEMBER, not just recall. Use:
- Mnemonics (acronyms, rhymes, first-letter tricks)
- Mindmap cues (central idea → branches)
- Memory palaces / vivid associations
- Shortcut formulas or patterns
- "Because" hooks ("X happens BECAUSE...")
- One-line exam tips

Mix these types equally:
1. "mnemonic"   — acronym or rhyme to remember a list
2. "mindmap"    — central concept with 3-5 branch keywords
3. "shortcut"   — quick rule or formula pattern to remember
4. "memory_hack"— vivid story, analogy, or association
5. "key_fact"   — single crucial fact + why it matters in exam

Return ONLY valid JSON (no markdown fences):
{{"flashcards": [
  {{
    "id": 1,
    "front": "How to remember the 5 functions of X?",
    "back": "Use DRAMA: D=..., R=..., A=..., M=..., A=...",
    "type": "mnemonic",
    "difficulty": "easy",
    "exam_tip": "Often asked as 1-mark or 2-mark",
    "tags": ["chapter keyword", "exam topic"]
  }}
]}}

Chapter content to base cards on:
{content[:4500]}
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=4000)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        return data.get("flashcards", [])
    except Exception:
        return []


async def _pipeline_generate_geo_seo_blog(
    subject_name: str,
    chapter_title: str,
    content: str,
    geo_location: str,
    board_slug: str,
    class_slug: str,
    chapter_slug: str,
) -> dict:
    """Generate a geo-optimized SEO blog post for a specific Assam city."""
    prompt = f"""You are an expert SEO content writer for Syrabit.ai, an educational platform for AHSEC/SEBA students in Assam, India.

Write a geo-optimized SEO blog article for students in {geo_location.title()}, Assam.

Topic: {chapter_title} — {subject_name}
Target City: {geo_location.title()}, Assam
Board: AHSEC/SEBA

Requirements:
1. Title (55-65 chars): Include chapter name, subject, "{geo_location.title()} students", "AHSEC"
2. Meta description (148-160 chars): Include local references to {geo_location.title()}, action verb, "free on Syrabit"
3. Full article body (600-900 words) in markdown:
   - Introduction referencing {geo_location.title()} students specifically
   - Key concepts from the chapter
   - 3-4 important exam questions with answers
   - Local study tips for {geo_location.title()} students
   - Conclusion with CTA to Syrabit.ai
4. SEO keywords list (5-8 keywords including "{geo_location} {subject_name.lower()}", "AHSEC {chapter_title.lower()}")

Return ONLY valid JSON:
{{"title": "...", "meta_description": "...", "article_body": "...", "keywords": [], "primary_keyword": "..."}}

Chapter content to reference:
{content[:3000]}
"""
    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=2500)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        slug = f"{board_slug}-{class_slug}-{chapter_slug}-{_pipeline_slugify(geo_location)}"
        return {
            "title": data.get("title", f"{chapter_title} — {subject_name} | {geo_location.title()} | AHSEC"),
            "meta_description": data.get("meta_description", ""),
            "article_body": data.get("article_body", ""),
            "keywords": data.get("keywords", []),
            "primary_keyword": data.get("primary_keyword", f"{geo_location} {subject_name.lower()} ahsec"),
            "seo_slug": slug,
            "geo_location": geo_location,
        }
    except Exception as e:
        logger.warning(f"Geo blog generation failed for {geo_location}: {e}")
        slug = f"{board_slug}-{class_slug}-{chapter_slug}-{_pipeline_slugify(geo_location)}"
        return {
            "title": f"{chapter_title} — {subject_name} Notes | {geo_location.title()} AHSEC Students",
            "meta_description": f"Complete {chapter_title} notes for AHSEC students in {geo_location.title()}. Study {subject_name} with Syrabit.ai — free.",
            "article_body": content[:2000],
            "keywords": [f"{geo_location} {subject_name.lower()}", f"ahsec {chapter_title.lower()}"],
            "primary_keyword": f"{geo_location} {subject_name.lower()} ahsec",
            "seo_slug": slug,
            "geo_location": geo_location,
        }


async def _pipeline_generate_pyq_html(chapter: dict, subject_name: str, pyq_docs: list) -> str:
    """Generate an HTML PYQ replica page from uploaded PYQ documents."""
    chapter_title = chapter.get("title", "")
    if not pyq_docs:
        return f"""<div class="pyq-page"><h2>Previous Year Questions: {chapter_title}</h2><p>PYQ papers for this chapter will be added soon. Check back later on Syrabit.ai.</p></div>"""

    pyq_items = []
    for i, pyq in enumerate(pyq_docs[:5]):
        year = pyq.get("exam_year", "")
        exam_title = pyq.get("exam_title", f"Paper {i+1}")
        file_url = pyq.get("file_url", "")
        pyq_items.append(f"""
  <div class="pyq-item">
    <h3>{exam_title} ({year})</h3>
    <p><a href="{file_url}" target="_blank" rel="noopener">Download / View Paper</a></p>
  </div>""")

    pyq_block = "\n".join(pyq_items)
    return f"""<div class="pyq-page">
  <h2>Previous Year Questions: {chapter_title}</h2>
  <p class="pyq-subject">Subject: {subject_name}</p>
  <div class="pyq-list">
{pyq_block}
  </div>
  <p class="pyq-note">All previous year question papers are sourced from official AHSEC/SEBA board examinations.</p>
</div>"""


# ── Pipeline background job store ─────────────────────────────────────────────
# Simple in-memory store for pipeline job status (TTL ~1 hour).
# Keys are job UUIDs. Values: { status, progress, message, result, started_at }
_pipeline_jobs: dict = {}

def _pipeline_job_gc():
    """Remove jobs older than 1 hour."""
    cutoff = datetime.now(timezone.utc).timestamp() - 3600
    stale = [k for k, v in _pipeline_jobs.items() if v.get("started_at", 0) < cutoff]
    for k in stale:
        _pipeline_jobs.pop(k, None)


class PipelineAutoGenerateRequest(BaseModel):
    subject_id: str
    skip_existing: bool = False


@api.get("/admin/pipeline/status/{job_id}")
async def admin_pipeline_status(job_id: str, admin: dict = Depends(get_admin_user)):
    """Poll the status of a background pipeline job."""
    job = _pipeline_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job


async def _pipeline_auto_generate_worker(job_id: str, subject_id: str, skip_existing: bool = False):
    """Background worker: runs the full pipeline and updates _pipeline_jobs[job_id]."""
    try:
        result = await _pipeline_auto_generate_core(subject_id, job_id, skip_existing=skip_existing)
        _pipeline_jobs[job_id].update({
            "status": "complete",
            "progress": 100,
            "message": "Pipeline finished",
            "result": result,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        _pipeline_jobs[job_id].update({
            "status": "error",
            "progress": 100,
            "message": str(exc)[:200],
            "result": None,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.error(f"Pipeline job {job_id} failed: {exc}")
    finally:
        _pipeline_job_gc()


@api.post("/admin/pipeline/auto-generate")
async def admin_pipeline_auto_generate(body: PipelineAutoGenerateRequest, background_tasks: BackgroundTasks, admin: dict = Depends(get_admin_user)):
    """
    1-Click Full Subject Pipeline (async).
    Returns job_id immediately; poll /admin/pipeline/status/{job_id} for progress.
    """
    subject_id = body.subject_id.strip()
    if not subject_id:
        raise HTTPException(status_code=400, detail="subject_id is required")

    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    job_id = str(uuid.uuid4())
    _pipeline_jobs[job_id] = {
        "job_id": job_id,
        "subject_id": subject_id,
        "status": "running",
        "progress": 0,
        "message": "Pipeline starting…",
        "result": None,
        "started_at": datetime.now(timezone.utc).timestamp(),
    }
    background_tasks.add_task(_pipeline_auto_generate_worker, job_id, subject_id, body.skip_existing)
    return {"job_id": job_id, "status": "running"}


async def _pipeline_process_one_chapter(
    chapter: dict,
    *,
    subject_id: str,
    subject_name: str,
    class_name: str,
    paper_type: str,
    board_slug: str,
    class_slug: str,
    now_iso: str,
    pyq_docs: list,
    semaphore: asyncio.Semaphore,
    done_counter: dict,
    total_chapters: int,
    job_id: str,
    skip_existing: bool = False,
) -> dict:
    """Process a single chapter: notes → MCQs → flashcards → geo-blogs (parallel) → PYQ.
    If skip_existing=True, reuses existing notes/PYQs/flashcards and only runs blogs+PYQ HTML+sitemap.
    """
    async with semaphore:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        chapter_slug  = chapter.get("slug") or _pipeline_slugify(chapter_title)

        chapter_result = {
            "chapter_id":       chapter_id,
            "chapter_title":    chapter_title,
            "notes_generated":  False,
            "topic_pyq_count":  0,
            "mark_wise_count":  0,
            "flashcards_count": 0,
            "blogs_count":      0,
            "pyq_page":         False,
            "errors":           [],
        }

        if not chapter_title:
            return {"skipped": True, "result": chapter_result}

        # ── Step 1: Notes ─────────────────────────────────────────────────────
        existing_content = (chapter.get("content") or "").strip()
        notes_content = existing_content
        if skip_existing and len(existing_content) > 100:
            # Reuse existing notes — skip LLM call
            chapter_result["notes_generated"] = False
        else:
            try:
                generated = await _pipeline_generate_chapter_notes(chapter, subject_name, class_name, paper_type)
                if generated:
                    notes_content = generated
                    await db.chapters.update_one(
                        {"id": chapter_id},
                        {"$set": {
                            "content": generated,
                            "content_type": "notes",
                            "notes_generated": True,
                            "notes_generated_at": now_iso,
                        }}
                    )
                    chapter_result["notes_generated"] = True
                    try:
                        await auto_chunk_content(chapter_id=chapter_id, content=generated, subject_id=subject_id)
                    except Exception:
                        pass
            except Exception as e:
                chapter_result["errors"].append(f"notes: {str(e)[:80]}")

        if not notes_content:
            done_counter["done"] += 1
            if job_id and job_id in _pipeline_jobs:
                pct = int(5 + (done_counter["done"] / max(total_chapters, 1)) * 88)
                _pipeline_jobs[job_id].update({"progress": pct, "message": f"Chapter {done_counter['done']}/{total_chapters} processed"})
            return {"skipped": True, "result": chapter_result}

        # ── Steps 2, 2b & 3: Topic PYQs + Mark-wise PYQs + Flashcards (parallel) ─
        # If skip_existing, check DB first — only generate if absent
        pyq_err = None
        mw_err  = None
        fc_err  = None
        _existing_pyqs = None
        _existing_mw   = None
        _existing_fc   = None
        if skip_existing:
            _existing_pyqs = await db.topic_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})
            _existing_mw   = await db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})
            _existing_fc   = await db.flashcard_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})

        if skip_existing and _existing_pyqs and _existing_mw and _existing_fc:
            chapter_result["topic_pyq_count"]   = _existing_pyqs.get("total", 0)
            chapter_result["mark_wise_count"]    = _existing_mw.get("total", 0)
            chapter_result["flashcards_count"]   = _existing_fc.get("total", 0)
            topic_pyqs = None
            mark_wise_result = None
            flashcards = None
        else:
            pyq_task = _pipeline_generate_topic_pyq(notes_content, subject_name, chapter_title, class_name, count=20)
            mw_task  = _pipeline_generate_mark_wise_pyq(notes_content, subject_name, chapter_title, class_name, paper_type=paper_type)
            fc_task  = _pipeline_generate_flashcards(notes_content, subject_name, chapter_title, class_name, count=30)
            (topic_pyqs, pyq_err), (mark_wise_result, mw_err), (flashcards, fc_err) = await asyncio.gather(
                _safe(pyq_task), _safe(mw_task), _safe(fc_task)
            )

        if topic_pyqs:
            try:
                await db.topic_pyq_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": {
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id, "subject_name": subject_name,
                        "chapter_id": chapter_id, "chapter_title": chapter_title,
                        "pyqs": topic_pyqs, "total": len(topic_pyqs),
                        "pipeline_generated": True, "created_at": now_iso,
                    }},
                    upsert=True,
                )
                chapter_result["topic_pyq_count"] = len(topic_pyqs)
            except Exception as e:
                chapter_result["errors"].append(f"topic-pyq-save: {str(e)[:60]}")
        elif pyq_err:
            chapter_result["errors"].append(f"topic-pyqs: {str(pyq_err)[:60]}")

        # ── Step 2b: Persist mark-wise questions into ai_pyq_collections ──────
        if mark_wise_result and mark_wise_result.get("pyqs"):
            try:
                mw_doc = {
                    "id":            str(uuid.uuid4()),
                    "subject_id":    subject_id,
                    "subject_name":  subject_name,
                    "chapter_id":    chapter_id,
                    "chapter_title": chapter_title,
                    "pyqs":          mark_wise_result["pyqs"],
                    "mark_wise":     mark_wise_result["mark_wise"],
                    "total":         mark_wise_result["total"],
                    "source":        "pipeline_mark_wise",
                    "ai_generated":  True,
                    "pipeline_generated": True,
                    "created_at":    now_iso,
                    "updated_at":    now_iso,
                }
                await db.ai_pyq_collections.update_one(
                    {"chapter_id": chapter_id},
                    {"$set": mw_doc},
                    upsert=True,
                )
                chapter_result["mark_wise_count"] = mark_wise_result["total"]
            except Exception as e:
                chapter_result["errors"].append(f"mark-wise-save: {str(e)[:60]}")
        elif mw_err:
            chapter_result["errors"].append(f"mark-wise: {str(mw_err)[:60]}")

        if flashcards:
            try:
                await db.flashcard_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": {
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id, "subject_name": subject_name,
                        "chapter_id": chapter_id, "chapter_title": chapter_title,
                        "flashcards": flashcards, "total": len(flashcards),
                        "pipeline_generated": True, "created_at": now_iso,
                    }},
                    upsert=True,
                )
                chapter_result["flashcards_count"] = len(flashcards)
            except Exception as e:
                chapter_result["errors"].append(f"flashcards-save: {str(e)[:60]}")
        elif fc_err:
            chapter_result["errors"].append(f"flashcards: {str(fc_err)[:60]}")

        # ── Step 4: Geo-SEO Blogs (all 5 cities in parallel) ────────────────
        # skip_existing: skip if all geo-blogs already exist in CMS for this chapter
        _existing_geo_count = 0
        if skip_existing:
            try:
                _existing_geo_count = await db.cms_documents.count_documents({
                    "linked_chapter_id": chapter_id, "category": "geo-blog"
                })
            except Exception:
                pass
        if skip_existing and _existing_geo_count >= len(GEO_CITIES):
            logger.info(f"[Pipeline] Skipping geo-blogs for '{chapter_title}' — {_existing_geo_count} already exist")
            chapter_result["blogs_count"] = _existing_geo_count
            geo_blog_urls = []
        else:
            blog_tasks = [
                _safe(_pipeline_generate_geo_seo_blog(
                    subject_name=subject_name, chapter_title=chapter_title,
                    content=notes_content, geo_location=city,
                    board_slug=board_slug, class_slug=class_slug, chapter_slug=chapter_slug,
                ))
                for city in GEO_CITIES
            ]
            blog_results = await asyncio.gather(*blog_tasks)
            geo_blog_urls = []
            for city, (blog_data, blog_err) in zip(GEO_CITIES, blog_results):
                if blog_err or not blog_data:
                    chapter_result["errors"].append(f"geo-blog-{city}: {str(blog_err)[:60]}" if blog_err else f"geo-blog-{city}: empty")
                    continue
                try:
                    blog_slug = blog_data["seo_slug"]
                    await db.cms_documents.update_one(
                        {"seo_slug": blog_slug},
                        {"$set": {
                            "id": str(uuid.uuid4()),
                            "title": blog_data["title"], "seo_slug": blog_slug,
                            "meta_description": blog_data["meta_description"],
                            "content": blog_data["article_body"],
                            "primary_keyword": blog_data["primary_keyword"],
                            "keywords": blog_data.get("keywords", []),
                            "geo_location": city,
                            "linked_subject_id": subject_id, "linked_subject_name": subject_name,
                            "linked_chapter_id": chapter_id, "linked_chapter_title": chapter_title,
                            "status": "published", "category": "geo-blog",
                            "schema_type": "Article", "pipeline_generated": True,
                            "created_at": now_iso, "updated_at": now_iso,
                        }},
                        upsert=True,
                    )
                    geo_blog_urls.append(f"/learn/{blog_slug}")
                    chapter_result["blogs_count"] += 1
                except Exception as e:
                    chapter_result["errors"].append(f"geo-blog-{city}-save: {str(e)[:60]}")

        # ── Step 5: PYQ HTML Page ────────────────────────────────────────────
        try:
            pyq_html = await _pipeline_generate_pyq_html(chapter, subject_name, pyq_docs)
            pyq_slug = f"pyq-{board_slug}-{class_slug}-{chapter_slug}"
            await db.cms_documents.update_one(
                {"seo_slug": pyq_slug},
                {"$set": {
                    "id": str(uuid.uuid4()),
                    "title": f"PYQ: {chapter_title} — {subject_name}",
                    "seo_slug": pyq_slug,
                    "meta_description": f"Previous year questions for {chapter_title} ({subject_name}) — AHSEC/SEBA board exams. Download PYQ papers on Syrabit.ai.",
                    "content": pyq_html, "content_html": pyq_html,
                    "linked_subject_id": subject_id, "linked_subject_name": subject_name,
                    "linked_chapter_id": chapter_id, "linked_chapter_title": chapter_title,
                    "status": "published", "category": "pyq",
                    "pipeline_generated": True, "created_at": now_iso, "updated_at": now_iso,
                }},
                upsert=True,
            )
            chapter_result["pyq_page"] = True
        except Exception as e:
            chapter_result["errors"].append(f"pyq-page: {str(e)[:80]}")

        done_counter["done"] += 1
        if job_id and job_id in _pipeline_jobs:
            pct = int(5 + (done_counter["done"] / max(total_chapters, 1)) * 88)
            _pipeline_jobs[job_id].update({"progress": pct, "message": f"Chapter {done_counter['done']}/{total_chapters} complete"})

        return {"skipped": False, "result": chapter_result, "blog_urls": geo_blog_urls, "mcqs": len(topic_pyqs or []), "flashcards": len(flashcards or []), "pyq": chapter_result["pyq_page"]}


async def _safe(coro):
    """Run a coroutine; return (result, None) on success or (None, exc) on error."""
    try:
        return await coro, None
    except Exception as e:
        return None, e


async def _pipeline_auto_generate_core(subject_id: str, job_id: str = "", skip_existing: bool = False):
    """Core pipeline logic — extracted so it can run as a background task."""
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise ValueError(f"Subject {subject_id} not found")

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "") or subject.get("class_name", "")

    # Resolve board/class/stream slugs for URL construction
    stream_id = subject.get("stream_id", "")
    board_slug = "ahsec"
    class_slug = _pipeline_slugify(class_name or "class-12")

    if stream_id:
        stream_doc = await db.streams.find_one({"id": stream_id}, {"_id": 0})
        if stream_doc:
            class_id = stream_doc.get("class_id", "")
            if class_id:
                class_doc = await db.classes.find_one({"id": class_id}, {"_id": 0})
                if class_doc:
                    class_slug = class_doc.get("slug") or _pipeline_slugify(class_doc.get("name", ""))
                    board_id = class_doc.get("board_id", "")
                    if board_id:
                        board_doc = await db.boards.find_one({"id": board_id}, {"_id": 0})
                        if board_doc:
                            board_slug = board_doc.get("slug") or _pipeline_slugify(board_doc.get("name", ""))

    # Load chapters
    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "status": "no_chapters", "message": "No chapters found for this subject"}

    now_iso = datetime.now(timezone.utc).isoformat()

    # Load PYQs for this subject (for PYQ HTML pages)
    pyq_docs = await db.pyq_uploads.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("exam_year", -1).to_list(20)

    # ── Parallel chapter processing (semaphore=4 to respect LLM rate limits) ─
    semaphore     = asyncio.Semaphore(4)
    done_counter  = {"done": 0}
    total_chapters = len(chapters)

    if job_id and job_id in _pipeline_jobs:
        _pipeline_jobs[job_id].update({"progress": 5, "message": f"Starting parallel processing for {total_chapters} chapters…"})

    tasks = [
        _pipeline_process_one_chapter(
            ch,
            subject_id=subject_id, subject_name=subject_name,
            class_name=class_name, paper_type=paper_type,
            board_slug=board_slug, class_slug=class_slug,
            now_iso=now_iso, pyq_docs=pyq_docs,
            semaphore=semaphore, done_counter=done_counter,
            total_chapters=total_chapters, job_id=job_id,
            skip_existing=skip_existing,
        )
        for ch in chapters
    ]
    chapter_outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    # ── Aggregate results ─────────────────────────────────────────────────────
    summary = {
        "subject_id": subject_id, "subject_name": subject_name,
        "chapters_processed": 0, "chapters_skipped": 0,
        "total_topic_pyqs": 0, "total_mark_wise_pyqs": 0, "total_flashcards": 0,
        "total_blogs": 0, "total_pyq_pages": 0,
        "blog_urls": [], "chapter_results": [],
        "sitemap_pinged": False, "ping_status": "",
    }

    for outcome in chapter_outcomes:
        if isinstance(outcome, Exception):
            summary["chapters_skipped"] += 1
            continue
        if outcome.get("skipped"):
            summary["chapters_skipped"] += 1
            summary["chapter_results"].append(outcome["result"])
            continue
        r = outcome["result"]
        summary["chapters_processed"] += 1
        summary["total_topic_pyqs"]     += r.get("topic_pyq_count", 0)
        summary["total_mark_wise_pyqs"] += r.get("mark_wise_count", 0)
        summary["total_flashcards"]     += r.get("flashcards_count", 0)
        summary["total_blogs"]          += r.get("blogs_count", 0)
        if r.get("pyq_page"):
            summary["total_pyq_pages"] += 1
        summary["blog_urls"].extend(outcome.get("blog_urls", []))
        summary["chapter_results"].append(r)

    _invalidate_content_cache("chapters")

    # ── Step 6: Verify Sitemap is Alive (self-check) ─────────────────────────
    # Google deprecated their sitemap ping endpoint in 2023 (returns 404).
    # Instead we self-verify our own sitemap endpoint on localhost.
    try:
        local_port = int(os.environ.get("PORT", "5000"))
        sitemap_local = f"http://localhost:{local_port}/api/seo/sitemap-index.xml"
        async with httpx.AsyncClient(timeout=10.0) as client:
            smap_resp = await client.get(sitemap_local)
            summary["sitemap_pinged"] = True
            if smap_resp.status_code == 200:
                summary["ping_status"] = "Sitemap OK"
            else:
                summary["ping_status"] = f"Sitemap HTTP {smap_resp.status_code}"
            logger.info(f"Sitemap self-check: {smap_resp.status_code} at {sitemap_local}")
    except Exception as e:
        summary["ping_status"] = f"check failed: {str(e)[:50]}"
        logger.warning(f"Sitemap self-check failed: {e}")

    logger.info(
        f"Pipeline complete: subject={subject_name}, chapters={summary['chapters_processed']}, "
        f"topic_pyqs={summary['total_topic_pyqs']}, flashcards={summary['total_flashcards']}, "
        f"blogs={summary['total_blogs']}, pyq_pages={summary['total_pyq_pages']}"
    )

    return summary


app.include_router(api)


# ══════════════════════════════════════════════════════════════════════════════
#  PYQ — Previous Year Questions Upload & Management
# ══════════════════════════════════════════════════════════════════════════════

_PYQ_BUCKET   = "study-materials"
_PYQ_PREFIX   = "pyqs"
_PYQ_MAX_MB   = 50  # MB per file — stored in Supabase, not MongoDB

def _pyq_supabase_upload(raw: bytes, storage_path: str, mime: str) -> str:
    """Upload bytes to Supabase storage and return the public URL.
    Raises on failure so caller can fall back to base64."""
    supa.storage.from_(_PYQ_BUCKET).upload(
        path=storage_path,
        file=raw,
        file_options={"content-type": mime, "upsert": "true"},
    )
    return supa.storage.from_(_PYQ_BUCKET).get_public_url(storage_path)


@app.post("/api/admin/pyq/upload")
async def admin_pyq_upload(
    files: List[UploadFile] = File(...),
    paper_type:  str = Form("major"),
    exam_year:   int = Form(...),
    exam_title:  str = Form(""),
    board_id:    str = Form(""),
    class_id:    str = Form(""),
    stream_id:   str = Form(""),
    subject_id:  str = Form(""),
    admin: dict = Depends(get_admin_user),
):
    """Upload PYQ files to Supabase Storage; store only metadata + URL in MongoDB."""
    if not files:
        raise HTTPException(400, "No files provided")

    max_bytes = _PYQ_MAX_MB * 1024 * 1024

    # Resolve display names from MongoDB
    subject_name = board_name = class_name = stream_name = ""
    db = _get_db()
    try:
        if subject_id:
            s = db["subjects"].find_one({"id": subject_id}) or db["subjects"].find_one({"_id": subject_id})
            subject_name = (s or {}).get("name") or (s or {}).get("title") or ""
        if board_id:
            b = db["boards"].find_one({"id": board_id}) or db["boards"].find_one({"_id": board_id})
            board_name = (b or {}).get("name") or ""
        if class_id:
            c = db["classes"].find_one({"id": class_id}) or db["classes"].find_one({"_id": class_id})
            class_name = (c or {}).get("name") or ""
        if stream_id:
            st = db["streams"].find_one({"id": stream_id}) or db["streams"].find_one({"_id": stream_id})
            stream_name = (st or {}).get("name") or ""
    except Exception:
        pass

    saved_ids = []
    use_supabase = bool(supa)

    for upload in files:
        raw = await upload.read()
        if len(raw) > max_bytes:
            raise HTTPException(413, f"{upload.filename} exceeds {_PYQ_MAX_MB} MB limit")

        mime      = upload.content_type or "application/octet-stream"
        is_image  = mime.startswith("image/")
        is_pdf    = mime == "application/pdf" or (upload.filename or "").lower().endswith(".pdf")
        doc_id    = str(uuid.uuid4())
        safe_name = (upload.filename or "file").replace(" ", "_")

        # ── Try Supabase storage first ────────────────────────────────────────
        file_url: str = ""
        storage_path  = f"{_PYQ_PREFIX}/{doc_id}/{safe_name}"

        if use_supabase:
            try:
                file_url = await asyncio.get_event_loop().run_in_executor(
                    _THREAD_POOL,
                    lambda p=storage_path, r=raw, m=mime: _pyq_supabase_upload(r, p, m),
                )
                logger.info(f"PYQ uploaded to Supabase: {storage_path}")
            except Exception as e:
                logger.warning(f"Supabase PYQ upload failed, falling back to base64: {e}")
                file_url = ""

        # ── Fallback: base64 data-URL (images) or skip large PDFs ────────────
        if not file_url:
            if is_image:
                file_url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
            else:
                # For PDFs without Supabase we store an empty URL — warn admin
                file_url = ""
                logger.warning(f"PYQ PDF stored without file content (Supabase unavailable): {safe_name}")

        # ── Build MongoDB document ────────────────────────────────────────────
        doc = {
            "id":            doc_id,
            "filename":      upload.filename or "upload",
            "mime_type":     mime,
            "exam_title":    exam_title or f"{paper_type.upper()} {exam_year}",
            "exam_year":     exam_year,
            "paper_type":    paper_type,
            "board_id":      board_id,
            "board_name":    board_name,
            "class_id":      class_id,
            "class_name":    class_name,
            "stream_id":     stream_id,
            "stream_name":   stream_name,
            "subject_id":    subject_id,
            "subject_name":  subject_name,
            "file_url":      file_url,          # Supabase public URL or data-URL for images
            "storage_path":  storage_path if use_supabase and file_url and not file_url.startswith("data:") else "",
            "storage":       "supabase" if (use_supabase and file_url and not file_url.startswith("data:")) else "base64",
            "is_image":      is_image,
            "is_pdf":        is_pdf,
            # pages array — for images keep one entry; frontend uses file_url
            "pages": [{"file_url": file_url, "filename": upload.filename}] if is_image else [],
            "status":            "uploaded",
            "processing_status": "uploaded",
            "created_at":        datetime.utcnow().isoformat(),
            "created_by":        admin.get("username", "admin"),
        }
        db["pyq_uploads"].insert_one(doc)
        saved_ids.append(doc_id)

    return {"status": "ok", "uploaded": len(saved_ids), "ids": saved_ids,
            "storage": "supabase" if use_supabase else "base64"}


@app.get("/api/admin/pyq/list")
async def admin_pyq_list(
    subject_id: str = "",
    board_id:   str = "",
    exam_year:  int = 0,
    admin: dict = Depends(get_admin_user),
):
    db = _get_db()
    filt: dict = {}
    if subject_id: filt["subject_id"] = subject_id
    if board_id:   filt["board_id"]   = board_id
    if exam_year:  filt["exam_year"]  = exam_year

    docs = list(db["pyq_uploads"].find(filt, {"_id": 0}).sort("created_at", -1).limit(200))
    return {"pyqs": docs}


@app.delete("/api/admin/pyq/{pyq_id}")
async def admin_pyq_delete(pyq_id: str, admin: dict = Depends(get_admin_user)):
    db = _get_db()
    doc = db["pyq_uploads"].find_one({"id": pyq_id}, {"_id": 0, "storage_path": 1, "storage": 1})
    if not doc:
        raise HTTPException(404, "PYQ not found")

    # Delete from Supabase storage if applicable
    if supa and doc.get("storage") == "supabase" and doc.get("storage_path"):
        try:
            await asyncio.get_event_loop().run_in_executor(
                _THREAD_POOL,
                lambda: supa.storage.from_(_PYQ_BUCKET).remove([doc["storage_path"]]),
            )
        except Exception as e:
            logger.warning(f"Supabase PYQ delete failed (continuing): {e}")

    db["pyq_uploads"].delete_one({"id": pyq_id})
    return {"status": "deleted", "id": pyq_id}


# ─────────────────────────────────────────────────────────────────────────────
# PYQ AGENTIC PROCESS — upload → OCR → classify pipeline
# ─────────────────────────────────────────────────────────────────────────────

class _PYQAgenticRequest(BaseModel):
    pyq_id: str


@app.post("/api/admin/pyq/agentic-process")
async def admin_pyq_agentic_process(
    payload: _PYQAgenticRequest,
    admin: dict = Depends(get_admin_user),
):
    """
    Agentic PYQ pipeline for a single already-uploaded PDF:
      1. Fetch PDF bytes from Supabase URL
      2. Run Gemini OCR → extract questions
      3. Build SEO HTML page → upsert into pyq_html_pages
      4. Index questions into RAG chunks (background)
    Updates processing_status on pyq_uploads throughout.
    Returns {status, seo_url, question_count, subject_id}.
    """
    pyq_id = payload.pyq_id
    _db = _get_db()
    pyq = _db["pyq_uploads"].find_one({"id": pyq_id}, {"_id": 0})
    if not pyq:
        raise HTTPException(404, "PYQ not found")

    if not pyq.get("is_pdf"):
        raise HTTPException(400, "Agentic processing only supports PDF uploads")

    file_url = pyq.get("file_url", "")
    if not file_url or file_url.startswith("data:"):
        raise HTTPException(400, "PDF not stored in Supabase — re-upload the file")

    # Mark OCR as running
    _db["pyq_uploads"].update_one(
        {"id": pyq_id},
        {"$set": {"processing_status": "ocr_running", "updated_at": datetime.utcnow().isoformat()}},
    )

    # Fetch PDF bytes from storage URL
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.get(file_url)
            resp.raise_for_status()
            raw = resp.content
    except Exception as e:
        _db["pyq_uploads"].update_one(
            {"id": pyq_id},
            {"$set": {"processing_status": "fetch_error", "error_msg": str(e)}},
        )
        raise HTTPException(502, f"Could not fetch PDF from storage: {e}")

    # Resolve metadata from pyq doc
    board_name   = pyq.get("board_name", "")
    class_name   = pyq.get("class_name", "")
    subject_name = pyq.get("subject_name", "")
    stream_name  = pyq.get("stream_name", "")
    exam_year    = int(pyq.get("exam_year") or datetime.utcnow().year)
    paper_type   = pyq.get("paper_type", "major")
    board_id     = pyq.get("board_id", "")
    class_id     = pyq.get("class_id", "")
    stream_id    = pyq.get("stream_id", "")
    subject_id   = pyq.get("subject_id", "")

    # Gemini Vision OCR
    ocr_prompt = (
        "You are an OCR engine for Assam Board (AHSEC/SEBA/Dibrugarh University) question papers.\n"
        "Extract ALL questions from this PDF question paper.\n"
        "Return ONLY valid JSON in this exact shape:\n"
        '{"questions": [{"number": "1", "text": "...", "marks": "5", "sub_parts": []}], '
        '"raw_text": "...", "word_count": 0}\n'
        "- number: question number as a string\n"
        "- text: full question text\n"
        "- marks: marks as string (empty if not shown)\n"
        "- sub_parts: list of sub-question strings (empty list if none)\n"
        "- raw_text: all extracted text concatenated\n"
        "Do not include any markdown fences or extra text outside the JSON."
    )

    try:
        ocr_result_raw = await vertex_services.analyze_image(
            raw, mime_type="application/pdf", prompt=ocr_prompt, max_output_tokens=8192
        )
    except Exception as e:
        _db["pyq_uploads"].update_one(
            {"id": pyq_id}, {"$set": {"processing_status": "ocr_error", "error_msg": str(e)}}
        )
        raise HTTPException(502, f"Gemini OCR failed: {e}")

    if not ocr_result_raw:
        _db["pyq_uploads"].update_one({"id": pyq_id}, {"$set": {"processing_status": "ocr_error"}})
        raise HTTPException(502, "Gemini OCR returned empty response — check GEMINI_API_KEY")

    # Parse OCR JSON
    try:
        cleaned = ocr_result_raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        ocr_data = json.loads(cleaned)
    except Exception:
        ocr_data = {"questions": [], "raw_text": ocr_result_raw, "word_count": len(ocr_result_raw.split())}

    questions = ocr_data.get("questions") or []
    raw_text  = ocr_data.get("raw_text") or ocr_result_raw or ""

    # Build SEO metadata & HTML
    geo_tags  = ["Dhemaji", "Jorhat", "Guwahati", "Assam"]
    slug      = _pyq_html_slug(board_name, subject_name, exam_year, paper_type)
    seo_title = (
        f"{board_name} {subject_name} Previous Year Question Paper {exam_year} "
        f"({paper_type.upper()}) — Dhemaji, Assam"
    ).strip()
    seo_desc = (
        f"Download and study the {board_name} {subject_name} {paper_type.upper()} "
        f"question paper from {exam_year}. Serving students in Dhemaji, Jorhat, "
        f"Guwahati and across Assam."
    )
    schema_json = json.dumps({
        "@context": "https://schema.org", "@type": "ExamPaper",
        "name": seo_title, "description": seo_desc,
        "about": {"@type": "Thing", "name": subject_name},
        "educationalLevel": class_name or "Higher Secondary",
        "provider": {"@type": "Organization", "name": board_name},
        "dateCreated": str(exam_year),
        "contentLocation": {
            "@type": "Place", "name": "Assam, India",
            "containedInPlace": [{"@type": "Place", "name": g} for g in geo_tags],
        },
    }, ensure_ascii=False)

    html_content = _build_pyq_html(
        questions=questions, raw_text=raw_text, seo_title=seo_title, seo_desc=seo_desc,
        schema_json=schema_json, geo_tags=geo_tags, board_name=board_name,
        subject_name=subject_name, exam_year=exam_year, paper_type=paper_type,
    )

    # Persist html page
    now = datetime.utcnow().isoformat()
    page_doc = {
        "slug": slug, "html_content": html_content, "seo_title": seo_title,
        "seo_description": seo_desc, "geo_tags": geo_tags, "schema_json": schema_json,
        "subject_id": subject_id, "subject_name": subject_name, "board_id": board_id,
        "board_name": board_name, "class_id": class_id, "class_name": class_name,
        "stream_id": stream_id, "stream_name": stream_name, "exam_year": exam_year,
        "paper_type": paper_type, "question_count": len(questions),
        "questions": questions, "raw_text": raw_text[:5000],
        "created_at": now, "updated_at": now, "created_by": admin.get("username", "admin"),
    }
    if db is not None:
        await db.pyq_html_pages.update_one({"slug": slug}, {"$set": page_doc}, upsert=True)

    # Index RAG chunks in background
    if raw_text.strip():
        asyncio.create_task(_index_pyq_rag_chunks(
            raw_text=raw_text, questions=questions, subject_id=subject_id,
            board_id=board_id, exam_year=exam_year, paper_type=paper_type, slug=slug,
        ))

    # Update pyq_uploads status to ocr_done
    _db["pyq_uploads"].update_one(
        {"id": pyq_id},
        {"$set": {
            "processing_status": "ocr_done",
            "seo_url":           f"/pyq/{slug}",
            "pyq_html_slug":     slug,
            "question_count":    len(questions),
            "updated_at":        now,
        }},
    )

    return {
        "status":         "ocr_done",
        "seo_url":        f"/pyq/{slug}",
        "slug":           slug,
        "question_count": len(questions),
        "subject_id":     subject_id,
    }


@app.get("/api/admin/pyq/{pyq_id}/status")
async def admin_pyq_get_status(pyq_id: str, admin: dict = Depends(get_admin_user)):
    """Lightweight status polling for the agentic pipeline."""
    _db = _get_db()
    doc = _db["pyq_uploads"].find_one(
        {"id": pyq_id},
        {"_id": 0, "processing_status": 1, "seo_url": 1, "question_count": 1,
         "subject_id": 1, "pyq_html_slug": 1, "error_msg": 1},
    )
    if not doc:
        raise HTTPException(404, "PYQ not found")
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# PYQ HTML REPLICA — Gemini Vision OCR → SEO HTML page
# ─────────────────────────────────────────────────────────────────────────────

def _pyq_html_slug(board_name: str, subject_name: str, exam_year: int, paper_type: str) -> str:
    """Generate a geo-optimised slug for a PYQ replica page."""
    import re as _re
    def _s(t: str) -> str:
        t = t.lower().strip()
        t = _re.sub(r'[^a-z0-9\s-]', '', t)
        t = _re.sub(r'[\s]+', '-', t)
        return _re.sub(r'-+', '-', t).strip('-')

    board_slug   = _s(board_name or "board")
    subject_slug = _s(subject_name or "subject")
    pt_slug      = _s(paper_type or "major") if paper_type and paper_type not in ("major", "") else ""
    geo_slug     = "dhemaji"   # primary geo anchor
    suffix       = f"-{pt_slug}" if pt_slug else ""
    return f"{board_slug}-{subject_slug}-pyq-{exam_year}{suffix}-{geo_slug}"


def _build_pyq_html(
    questions: list,
    raw_text:  str,
    seo_title: str,
    seo_desc:  str,
    schema_json: str,
    geo_tags: list,
    board_name: str,
    subject_name: str,
    exam_year: int,
    paper_type: str,
) -> str:
    """Render the full HTML document for a PYQ replica page."""
    import html as _html

    geo_meta = "".join(
        f'<meta name="geo.placename" content="{_html.escape(g)}">\n    '
        for g in geo_tags
    )

    question_rows = ""
    if questions:
        for q in questions:
            num   = _html.escape(str(q.get("number") or q.get("question_number") or ""))
            text  = _html.escape(str(q.get("text") or q.get("question_text") or q.get("q") or ""))
            marks = _html.escape(str(q.get("marks") or ""))
            sub_parts = q.get("sub_parts") or []

            marks_html = f'<span class="marks">[{marks} marks]</span>' if marks else ""
            sp_html = ""
            if sub_parts:
                sp_html = "<ol class='sub-parts'>" + "".join(
                    f"<li>{_html.escape(str(sp))}</li>" for sp in sub_parts
                ) + "</ol>"

            question_rows += f"""
        <div class="question">
          <p><strong>{num}.</strong> {text} {marks_html}</p>
          {sp_html}
        </div>"""
    else:
        # Fallback: render raw OCR text verbatim
        escaped = _html.escape(raw_text or "")
        question_rows = f'<pre class="raw-text">{escaped}</pre>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_html.escape(seo_title)}</title>
  <meta name="description" content="{_html.escape(seo_desc)}">
  <meta name="robots" content="index, follow">
  <meta property="og:title" content="{_html.escape(seo_title)}">
  <meta property="og:description" content="{_html.escape(seo_desc)}">
  {geo_meta}
  <script type="application/ld+json">{schema_json}</script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #fff;
      color: #000;
      font-family: "Times New Roman", Times, serif;
      font-size: 14px;
      line-height: 1.7;
    }}
    .page-wrapper {{
      max-width: 860px;
      margin: 0 auto;
      padding: 2in 1.5in;
    }}
    @media (max-width: 700px) {{
      .page-wrapper {{ padding: 24px 16px; }}
    }}
    .page-header {{
      text-align: center;
      margin-bottom: 2em;
      border-bottom: 2px solid #000;
      padding-bottom: 0.8em;
    }}
    .page-header h1 {{ font-size: 1.3em; font-weight: bold; }}
    .page-header p  {{ font-size: 0.95em; margin-top: 0.3em; }}
    .questions {{ margin-top: 1.5em; }}
    .question  {{ margin-bottom: 1.2em; }}
    .question p {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }}
    .marks {{ flex-shrink: 0; font-style: italic; }}
    .sub-parts {{ margin-left: 2em; margin-top: 0.4em; }}
    .sub-parts li {{ margin-bottom: 0.4em; }}
    .raw-text {{ white-space: pre-wrap; font-family: inherit; font-size: 13px; }}
    .geo-footer {{ margin-top: 3em; font-size: 11px; color: #666; border-top: 1px solid #ccc; padding-top: 0.6em; }}
  </style>
</head>
<body>
  <div class="page-wrapper">
    <div class="page-header">
      <h1>{_html.escape(seo_title)}</h1>
      <p>{_html.escape(board_name)} · {_html.escape(subject_name)} · {_html.escape(paper_type.upper())} · {exam_year}</p>
    </div>
    <div class="questions">
{question_rows}
    </div>
    <p class="geo-footer">
      Serving students in {", ".join(_html.escape(g) for g in geo_tags)}.
      Study resources for {_html.escape(board_name)} exams at Syrabit.ai
    </p>
  </div>
</body>
</html>"""


@app.post("/api/admin/pyq/html-replica")
async def admin_pyq_html_replica(
    file:        UploadFile = File(...),
    board_id:    str = Form(""),
    class_id:    str = Form(""),
    stream_id:   str = Form(""),
    subject_id:  str = Form(""),
    paper_type:  str = Form("major"),
    exam_year:   int = Form(...),
    admin: dict = Depends(get_admin_user),
):
    """
    OCR a PYQ PDF via Gemini Vision, build an SEO HTML replica, persist to
    pyq_html_pages collection, and index extracted questions into RAG chunks.
    Returns { seo_url: "/pyq/{slug}" }.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")

    # Validate that the uploaded file is actually a PDF
    fname = (file.filename or "").lower()
    mime  = file.content_type or ""
    is_pdf = (
        mime == "application/pdf"
        or fname.endswith(".pdf")
        or raw[:4] == b"%PDF"
    )
    if not is_pdf:
        raise HTTPException(400, "Only PDF files are accepted for HTML replica generation")
    mime = "application/pdf"

    # ── Resolve names (async Motor) ────────────────────────────────────────────
    subject_name = board_name = class_name = stream_name = ""
    try:
        if subject_id and db is not None:
            s = await db.subjects.find_one({"id": subject_id}, {"_id": 0}) or await db.subjects.find_one({"_id": subject_id}, {"_id": 0})
            subject_name = (s or {}).get("name") or (s or {}).get("title") or ""
        if board_id and db is not None:
            b = await db.boards.find_one({"id": board_id}, {"_id": 0}) or await db.boards.find_one({"_id": board_id}, {"_id": 0})
            board_name = (b or {}).get("name") or ""
        if class_id and db is not None:
            c = await db.classes.find_one({"id": class_id}, {"_id": 0}) or await db.classes.find_one({"_id": class_id}, {"_id": 0})
            class_name = (c or {}).get("name") or ""
        if stream_id and db is not None:
            st = await db.streams.find_one({"id": stream_id}, {"_id": 0}) or await db.streams.find_one({"_id": stream_id}, {"_id": 0})
            stream_name = (st or {}).get("name") or ""
    except Exception:
        pass

    # ── Gemini Vision OCR ──────────────────────────────────────────────────────
    ocr_prompt = (
        "You are an OCR engine for Assam Board (AHSEC/SEBA/Dibrugarh University) question papers.\n"
        "Extract ALL questions from this PDF question paper.\n"
        "Return ONLY valid JSON in this exact shape:\n"
        '{"questions": [{"number": "1", "text": "...", "marks": "5", "sub_parts": []}], '
        '"raw_text": "...", "word_count": 0}\n'
        "- number: question number as a string\n"
        "- text: full question text\n"
        "- marks: marks as string (empty if not shown)\n"
        "- sub_parts: list of sub-question strings (empty list if none)\n"
        "- raw_text: all extracted text concatenated\n"
        "Do not include any markdown fences or extra text outside the JSON."
    )

    ocr_result_raw = await vertex_services.analyze_image(raw, mime_type=mime, prompt=ocr_prompt, max_output_tokens=8192)
    if not ocr_result_raw:
        raise HTTPException(502, "Gemini OCR failed — check GEMINI_API_KEY")

    # Parse JSON from Gemini response
    try:
        cleaned = ocr_result_raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        ocr_data = json.loads(cleaned)
    except Exception:
        ocr_data = {"questions": [], "raw_text": ocr_result_raw, "word_count": len(ocr_result_raw.split())}

    questions = ocr_data.get("questions") or []
    raw_text  = ocr_data.get("raw_text") or ocr_result_raw or ""

    # ── Build SEO metadata ─────────────────────────────────────────────────────
    geo_tags  = ["Dhemaji", "Jorhat", "Guwahati", "Assam"]
    slug      = _pyq_html_slug(board_name, subject_name, exam_year, paper_type)
    seo_title = (
        f"{board_name} {subject_name} Previous Year Question Paper {exam_year} "
        f"({paper_type.upper()}) — Dhemaji, Assam"
    ).strip()
    seo_desc  = (
        f"Download and study the {board_name} {subject_name} {paper_type.upper()} "
        f"question paper from {exam_year}. Serving students in Dhemaji, Jorhat, "
        f"Guwahati and across Assam."
    )

    schema_json = json.dumps({
        "@context": "https://schema.org",
        "@type": "ExamPaper",
        "name": seo_title,
        "description": seo_desc,
        "about": {"@type": "Thing", "name": subject_name},
        "educationalLevel": class_name or "Higher Secondary",
        "provider": {"@type": "Organization", "name": board_name},
        "dateCreated": str(exam_year),
        "contentLocation": {
            "@type": "Place",
            "name": "Assam, India",
            "containedInPlace": [{"@type": "Place", "name": g} for g in geo_tags],
        },
    }, ensure_ascii=False)

    # ── Render HTML replica ────────────────────────────────────────────────────
    html_content = _build_pyq_html(
        questions=questions,
        raw_text=raw_text,
        seo_title=seo_title,
        seo_desc=seo_desc,
        schema_json=schema_json,
        geo_tags=geo_tags,
        board_name=board_name,
        subject_name=subject_name,
        exam_year=exam_year,
        paper_type=paper_type,
    )

    # ── Persist to MongoDB (upsert by slug) ───────────────────────────────────
    now = datetime.utcnow().isoformat()
    page_doc = {
        "slug":         slug,
        "html_content": html_content,
        "seo_title":    seo_title,
        "seo_description": seo_desc,
        "geo_tags":     geo_tags,
        "schema_json":  schema_json,
        "subject_id":   subject_id,
        "subject_name": subject_name,
        "board_id":     board_id,
        "board_name":   board_name,
        "class_id":     class_id,
        "class_name":   class_name,
        "stream_id":    stream_id,
        "stream_name":  stream_name,
        "exam_year":    exam_year,
        "paper_type":   paper_type,
        "question_count": len(questions),
        "created_at":   now,
        "updated_at":   now,
        "created_by":   admin.get("username", "admin"),
    }
    if db is not None:
        await db.pyq_html_pages.update_one(
            {"slug": slug},
            {"$set": page_doc},
            upsert=True,
        )

    # ── Index extracted questions into RAG chunks (priority 1 / content_type=pyq) ──
    if raw_text.strip():
        asyncio.create_task(_index_pyq_rag_chunks(
            raw_text=raw_text,
            questions=questions,
            subject_id=subject_id,
            board_id=board_id,
            exam_year=exam_year,
            paper_type=paper_type,
            slug=slug,
        ))

    return {"seo_url": f"/pyq/{slug}", "slug": slug, "question_count": len(questions)}


async def _index_pyq_rag_chunks(
    raw_text: str,
    questions: list,
    subject_id: str,
    board_id: str,
    exam_year: int,
    paper_type: str,
    slug: str,
):
    """Background task: store PYQ question text as RAG chunks tagged content_type=pyq, priority=1.
    Deletes any existing chunks for this slug first to prevent index duplication on re-generation."""
    try:
        # Remove previous chunks for this slug (idempotent re-generation)
        del_res = await db.chunks.delete_many({"pyq_slug": slug, "content_type": "pyq"})
        if del_res.deleted_count:
            logger.info(f"PYQ RAG: removed {del_res.deleted_count} stale chunks for slug={slug}")

        # Build one chunk per question (or fall back to raw_text paragraphs)
        chunks_to_index = []
        if questions:
            for q in questions:
                q_text = str(q.get("text") or q.get("question_text") or "").strip()
                sub    = " ".join(str(s) for s in (q.get("sub_parts") or []) if s)
                full   = f"{q_text} {sub}".strip()
                if len(full) >= 30:
                    chunks_to_index.append(full)
        else:
            paragraphs = [p.strip() for p in raw_text.split('\n') if len(p.strip()) >= 50]
            chunks_to_index = paragraphs[:30]

        now = datetime.utcnow().isoformat()
        for i, chunk_text in enumerate(chunks_to_index):
            embedding = await vertex_services.embed_text(chunk_text, task_type="RETRIEVAL_DOCUMENT")
            chunk_doc = {
                "id":            str(uuid.uuid4()),
                "chapter_id":    f"pyq-{slug}",
                "subject_id":    subject_id,
                "board_id":      board_id,
                "content":       chunk_text,
                "content_type":  "pyq",
                "priority":      1,
                "chunk_index":   i,
                "tags":          _extract_keywords(chunk_text)[:5],
                "geo_tags":      ["Dhemaji", "Jorhat", "Guwahati", "Assam"],
                "exam_year":     exam_year,
                "paper_type":    paper_type,
                "pyq_slug":      slug,
                "char_count":    len(chunk_text),
                "created_at":    now,
            }
            if embedding:
                chunk_doc["embedding"] = embedding
            await db.chunks.insert_one(chunk_doc)

        logger.info(f"PYQ RAG: indexed {len(chunks_to_index)} chunks for slug={slug}")
    except Exception as exc:
        logger.warning(f"PYQ RAG indexing failed for slug={slug}: {exc}")


@app.get("/api/pyq/list")
async def public_pyq_list(
    board_id:   str = "",
    subject_id: str = "",
    exam_year:  int = 0,
):
    """Public list of available PYQ HTML replica pages.

    Intentionally public — used by admin dashboard preview, sitemap generators, and
    public topic-discovery pages. Contains only metadata (title, slug, year), never
    PII or unpublished content.
    """
    if db is None:
        return {"pages": []}
    filt: dict = {}
    if board_id:   filt["board_id"]   = board_id
    if subject_id: filt["subject_id"] = subject_id
    if exam_year:  filt["exam_year"]  = exam_year
    docs = await db.pyq_html_pages.find(
        filt,
        {"_id": 0, "slug": 1, "seo_title": 1, "seo_description": 1,
         "subject_name": 1, "board_name": 1, "exam_year": 1, "paper_type": 1,
         "question_count": 1, "created_at": 1}
    ).sort("created_at", -1).limit(200).to_list(200)
    return {"pages": docs}


async def _serve_pyq_html(slug: str):
    """Shared logic: fetch PYQ doc from MongoDB and return HTMLResponse."""
    from fastapi.responses import HTMLResponse as _HTMLResponse
    if db is None:
        raise HTTPException(503, "Database unavailable")
    doc = await db.pyq_html_pages.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"PYQ page not found: {slug}")
    html_content = doc.get("html_content", "")
    if not html_content:
        raise HTTPException(404, "HTML content not available")
    return _HTMLResponse(
        content=html_content,
        status_code=200,
        headers={
            "Cache-Control": "public, max-age=86400, s-maxage=604800",
            "X-PYQ-Title":   doc.get("seo_title", "")[:120],
        },
    )


@app.get("/pyq/{slug}")
async def public_pyq_page_canonical(slug: str):
    """Canonical SEO URL — serves full HTML document with head/meta/JSON-LD.
    Production-accessible without any Vite/SPA layer."""
    return await _serve_pyq_html(slug)


@app.get("/api/pyq/{slug}")
async def public_pyq_page(slug: str):
    """Return stored HTML replica for a PYQ slug — sets correct content-type."""
    return await _serve_pyq_html(slug)


if __name__ == "__main__":
    import uvicorn
    PORT = int(os.getenv("PORT", 5000))
    logger.info(f"Starting server on port {PORT}")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
