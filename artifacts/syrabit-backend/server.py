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
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pathlib import Path
import os, uuid, logging, hashlib, json, re, asyncio, httpx, warnings
warnings.filterwarnings("ignore", message=".*__about__.*")
import cachetools
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

MONGO_URL    = os.environ.get('MONGO_URL', 'mongodb://localhost:27017').strip().strip('"').strip("'")
DB_NAME      = os.environ.get('DB_NAME', 'test_database')
JWT_SECRET   = os.environ.get('JWT_SECRET') or os.urandom(48).hex()  # Must be set in .env for production
JWT_ALGORITHM    = 'HS256'
JWT_EXPIRE_MINUTES = 60 * 24 * 30
ADMIN_JWT_SECRET = os.environ.get('ADMIN_JWT_SECRET') or os.urandom(48).hex()  # Must be set in .env for production

# ── LLM Configuration ─────────────────────────────────────────────────────────
_GROQ_KEY = os.environ.get('GROQ_API_KEY', '')
_OPENAI_KEY = os.environ.get('OPENAI_API_KEY', '')
_FIREWORKS_KEY = os.environ.get('FIREWORKS_API_KEY', '')
_SARVAM_LLM_KEY = os.environ.get('SARVAM_API_KEY', '').strip()
_EXPLICIT_PROVIDER = os.environ.get('LLM_PROVIDER', '').strip().lower()

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
REDIS_URL   = os.environ.get('UPSTASH_REDIS_REST_URL', '').strip().strip('"').strip("'")
REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN', '').strip().strip('"').strip("'")
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

REDIS_AI_CACHE_TTL = 3600
REDIS_CHAT_CACHE_TTL = 600
REDIS_RATE_WINDOW = 60

def _cache_key(query: str) -> str:
    """Normalized query hash for caching."""
    normalized = query.lower().strip()
    return hashlib.md5(normalized.encode()).hexdigest()

def _redis_get_ai_cache(key: str) -> Optional[str]:
    if redis_client:
        try:
            val = redis_client.get(f"ai_cache:{key}")
            return val
        except Exception:
            pass
    return None

def _redis_set_ai_cache(key: str, value: str):
    if redis_client:
        try:
            redis_client.set(f"ai_cache:{key}", value, ex=REDIS_AI_CACHE_TTL)
        except Exception:
            pass

def _redis_cache_conversation(conv_id: str, user_id: str, conv_data: dict):
    if redis_client:
        try:
            redis_client.set(
                f"chat:{conv_id}:{user_id}",
                json.dumps(conv_data, default=str),
                ex=REDIS_CHAT_CACHE_TTL
            )
        except Exception:
            pass

def _redis_get_conversation(conv_id: str, user_id: str) -> Optional[dict]:
    if redis_client:
        try:
            val = redis_client.get(f"chat:{conv_id}:{user_id}")
            if val:
                return json.loads(val) if isinstance(val, str) else val
        except Exception:
            pass
    return None

def _redis_invalidate_conversation(conv_id: str, user_id: str):
    if redis_client:
        try:
            redis_client.delete(f"chat:{conv_id}:{user_id}")
        except Exception:
            pass

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL         = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '') or os.environ.get('SUPABASE_KEY', '')
SUPABASE_ANON_KEY    = os.environ.get('SUPABASE_ANON_KEY', '') or os.environ.get('SUPABASE_KEY', '')

# ── Cookie security (set SECURE_COOKIES=false in dev to allow HTTP) ───────────
SECURE_COOKIES  = os.environ.get('SECURE_COOKIES', 'true').lower() not in ('false', '0', 'no')
COOKIE_SAMESITE = "none" if SECURE_COOKIES else "lax"

_cors_raw = os.environ.get('CORS_ORIGINS', '*').strip().strip('"').strip("'")
if _cors_raw == '*':
    CORS_ORIGINS = ["*"]
    _CORS_ALLOW_CREDENTIALS = False
else:
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(',') if o.strip()]
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
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
        maxPoolSize=50,
        minPoolSize=5,
        maxIdleTimeMS=60000,
        waitQueueTimeoutMS=5000,
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
        pg_pool = await _asyncpg.create_pool(_PG_DSN, min_size=2, max_size=10)
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
SARVAM_THINK_BUFFER = 800    # safety headroom for the <think> block (prompt caps it at ~80 words)

# ── Sarvam AI — two persistent pooled HTTP/2 clients ─────────────────────────
# Client A: translation / TTS / transliterate (short read timeout, 30s)
# Client B: LLM chat (sarvam-m: ~124ms TTFT, full stream < 30s for 4096 tokens)
_sarvam_pool_limits = httpx.Limits(
    max_keepalive_connections=50,
    max_connections=100,
    keepalive_expiry=60,
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

_rate_cleanup_task = None

@asynccontextmanager
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
        # Analytics indexes
        await db.analytics.create_index([("event_type", 1), ("timestamp", -1)])
        await db.analytics.create_index([("subject_id", 1), ("event_type", 1)])
        await db.analytics.create_index("user_id")
    except Exception as e:
        logger.warning(f"Seeding/indexing skipped (MongoDB may not be ready): {e}")
    _rate_cleanup_task = asyncio.create_task(_rate_limiter_cleanup())
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
api = APIRouter(prefix="/api")

_content_cache: Dict[str, Any] = {}
_content_cache_ttl: Dict[str, float] = {}
CONTENT_CACHE_SECONDS = 300
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
            for rk in redis_client.scan_iter(f"{REDIS_CONTENT_PREFIX}{prefix}:*"):
                redis_client.delete(rk)
            # Also always delete library-bundle from Redis
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
    print("[WARN] Supabase not configured — using MongoDB for users")

if redis_client:
    logger.info("Redis (Upstash) client ready")
else:
    print("[WARN] Redis not configured — using in-memory caching/rate-limiting")

def supa_table(table: str):
    """Return Supabase table builder, or raise if unavailable."""
    if supa is None:
        raise RuntimeError("Supabase not configured")
    return supa.table(table)

async def get_user_credits(user: dict) -> dict:
    """
    Lifetime credits — NO daily/monthly reset.
    Free: 30 one-time. Starter: 300. Pro: 4000.
    Credits are cumulative (never reset unless admin adjusts).
    """
    plan     = user.get("plan", "free")
    plan_cfg = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    limit    = plan_cfg["lifetime_credits"]
    used     = user.get("credits_used", 0)
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
)


# ─────────────────────────────────────────────
# JWT HELPERS
# ─────────────────────────────────────────────
def create_token(data: dict, secret: str = JWT_SECRET, expires_delta: int = JWT_EXPIRE_MINUTES) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expires_delta)
    return jwt.encode(to_encode, secret, algorithm=JWT_ALGORITHM)

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
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await supa_get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Account banned")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended")
    return user

async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_session: Optional[str] = Cookie(default=None),
):
    """Get current user if authenticated, otherwise return None"""
    token = creds.credentials if creds else syrabit_session
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        user = await supa_get_user_by_id(user_id)
        return user if user and user.get("status") not in ["banned", "suspended"] else None
    except:
        return None

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
    """Returns True if allowed, False if rate-limited. Uses in-memory for speed (per-worker)."""
    return _check_rate_limit_memory(key, max_requests, window_seconds)

async def rate_limit_user(user: dict = Depends(get_current_user)):
    """Dependency: 100 req/min per user. Returns 429 if exceeded."""
    user_id = user.get("id", "anonymous")
    if not check_rate_limit(f"user:{user_id}", max_requests=100, window_seconds=60):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded — 100 requests/minute. Please wait.",
            headers={"Retry-After": "60", "X-RateLimit-Limit": "100"},
        )
    return user

async def rate_limit_chat(user: dict = Depends(get_current_user)):
    """Dependency: 30 chat req/min per user (stricter for AI)."""
    user_id = user.get("id", "anonymous")
    if not check_rate_limit(f"chat:{user_id}", max_requests=30, window_seconds=60):
        raise HTTPException(
            status_code=429,
            detail="Chat rate limit exceeded — 30 messages/minute. Upgrade for higher limits.",
            headers={"Retry-After": "60", "X-RateLimit-Limit": "30"},
        )
    return user

# ── Security headers middleware ─────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """200 req/min per IP for all /api routes + request tracking."""
    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            client_ip = request.client.host if request.client else "unknown"
            if not check_rate_limit(f"ip:{client_ip}", max_requests=200, window_seconds=60):
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
        {"id": "b1", "name": "AHSEC", "slug": "ahsec", "description": "Assam Higher Secondary Education Council", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "b2", "name": "DEGREE", "slug": "degree", "description": "Degree Level Education (B.A / B.Com / B.Sc)", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "classes": [
        # AHSEC classes
        {"id": "c1", "board_id": "b1", "name": "Class 11", "slug": "class-11", "description": "Higher Secondary First Year", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c2", "board_id": "b1", "name": "Class 12", "slug": "class-12", "description": "Higher Secondary Second Year", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE classes
        {"id": "c3", "board_id": "b2", "name": "2nd Sem", "slug": "2nd-sem", "description": "Degree 2nd Semester", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c4", "board_id": "b2", "name": "4th Sem", "slug": "4th-sem", "description": "Degree 4th Semester", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "streams": [
        # AHSEC Class 11 streams
        {"id": "s1", "class_id": "c1", "name": "Science (PCM)", "slug": "science-pcm", "description": "Physics, Chemistry, Mathematics", "icon": "⚗️", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s2", "class_id": "c1", "name": "Science (PCB)", "slug": "science-pcb", "description": "Physics, Chemistry, Biology", "icon": "🌿", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s3", "class_id": "c1", "name": "Arts", "slug": "arts", "description": "Political Science, Economics, History", "icon": "📜", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s13","class_id": "c1", "name": "Commerce",      "slug": "commerce", "description": "Accountancy, Business Studies, Economics", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        # AHSEC Class 12 streams
        {"id": "s4", "class_id": "c2", "name": "Science (PCM)", "slug": "science-pcm", "description": "Physics, Chemistry, Mathematics", "icon": "⚗️", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s5", "class_id": "c2", "name": "Science (PCB)", "slug": "science-pcb", "description": "Physics, Chemistry, Biology", "icon": "🌿", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s6", "class_id": "c2", "name": "Arts", "slug": "arts", "description": "Political Science, Economics, History", "icon": "📜", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s14","class_id": "c2", "name": "Commerce",      "slug": "commerce", "description": "Accountancy, Business Studies, Economics, Mathematics", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE 2nd Sem streams
        {"id": "s7",  "class_id": "c3", "name": "B.Com", "slug": "bcom", "description": "Bachelor of Commerce", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s8",  "class_id": "c3", "name": "B.A",   "slug": "ba",   "description": "Bachelor of Arts",     "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s9",  "class_id": "c3", "name": "B.Sc",  "slug": "bsc",  "description": "Bachelor of Science",  "icon": "🔬", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE 4th Sem streams
        {"id": "s10", "class_id": "c4", "name": "B.Com", "slug": "bcom", "description": "Bachelor of Commerce", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s11", "class_id": "c4", "name": "B.A",   "slug": "ba",   "description": "Bachelor of Arts",     "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s12", "class_id": "c4", "name": "B.Sc",  "slug": "bsc",  "description": "Bachelor of Science",  "icon": "🔬", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "subjects": [
        # ── AHSEC Class 11 – Science (PCM) ──────────────────────────────────
        {"id": "sub1",  "stream_id": "s1", "name": "Mathematics",       "slug": "mathematics",       "description": "Sets, Relations, Trigonometry, Algebra, Calculus",                            "tags": ["Algebra", "Calculus", "Trigonometry"], "icon": "📐", "gradient": "math",      "chapter_count": 16, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub2",  "stream_id": "s1", "name": "Physics",           "slug": "physics",           "description": "Mechanics, Thermodynamics, Optics, Electrostatics",                          "tags": ["Mechanics", "Optics", "Waves"],        "icon": "⚡", "gradient": "physics",   "chapter_count": 15, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub3",  "stream_id": "s1", "name": "Chemistry",         "slug": "chemistry",         "description": "Atomic Structure, Chemical Bonding, Organic Chemistry",                      "tags": ["Organic", "Inorganic", "Physical"],    "icon": "🧪", "gradient": "chemistry","chapter_count": 14, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── AHSEC Class 11 – Science (PCB) ──────────────────────────────────
        {"id": "sub4",  "stream_id": "s2", "name": "Physics",           "slug": "physics",           "description": "Mechanics, Thermodynamics, Optics, Electrostatics",                          "tags": ["Mechanics", "Waves", "Optics"],        "icon": "⚡", "gradient": "physics",   "chapter_count": 15, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub5",  "stream_id": "s2", "name": "Chemistry",         "slug": "chemistry",         "description": "Atomic Structure, Chemical Bonding, Organic Chemistry",                      "tags": ["Organic", "Inorganic"],               "icon": "🧪", "gradient": "chemistry","chapter_count": 14, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub6",  "stream_id": "s2", "name": "Biology",           "slug": "biology",           "description": "Cell Biology, Genetics, Ecology, Plant Physiology",                          "tags": ["Genetics", "Ecology", "Cell Biology"], "icon": "🌱", "gradient": "biology",  "chapter_count": 22, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── AHSEC Class 11 – Arts ────────────────────────────────────────────
        {"id": "sub7",  "stream_id": "s3", "name": "Political Science", "slug": "political-science", "description": "Indian Constitution, Political Theory, International Relations",              "tags": ["Constitution", "Politics", "Rights"],  "icon": "🏛️", "gradient": "arts",     "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub8",  "stream_id": "s3", "name": "History",           "slug": "history",           "description": "Ancient India, Medieval History, Modern India, World History",                "tags": ["Ancient", "Medieval", "Modern"],       "icon": "📜", "gradient": "arts",     "chapter_count": 11, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub9",  "stream_id": "s3", "name": "Economics",         "slug": "economics",         "description": "Microeconomics, Macroeconomics, Indian Economy",                              "tags": ["Micro", "Macro", "Statistics"],        "icon": "📊", "gradient": "arts",     "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── AHSEC Class 12 – Science (PCM) ──────────────────────────────────
        {"id": "sub10", "stream_id": "s4", "name": "Mathematics",       "slug": "mathematics",       "description": "Relations, Inverse Trig, Matrices, Determinants, Integration, Differential Equations", "tags": ["Calculus", "Algebra", "Vectors"],      "icon": "📐", "gradient": "math",      "chapter_count": 13, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub11", "stream_id": "s4", "name": "Physics",           "slug": "physics",           "description": "Electric Charges, Current Electricity, Magnetism, Modern Physics",            "tags": ["Electricity", "Magnetism", "Optics"],  "icon": "⚡", "gradient": "physics",   "chapter_count": 15, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub12", "stream_id": "s4", "name": "Chemistry",         "slug": "chemistry",         "description": "Solid State, Solutions, Electrochemistry, Chemical Kinetics, Polymers",      "tags": ["Organic", "Inorganic", "Physical"],    "icon": "🧪", "gradient": "chemistry","chapter_count": 16, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── AHSEC Class 12 – Science (PCB) ──────────────────────────────────
        {"id": "sub13", "stream_id": "s5", "name": "Physics",           "slug": "physics",           "description": "Electric Charges, Current Electricity, Magnetism, Modern Physics",            "tags": ["Electricity", "Magnetism"],            "icon": "⚡", "gradient": "physics",   "chapter_count": 15, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub14", "stream_id": "s5", "name": "Chemistry",         "slug": "chemistry",         "description": "Solid State, Solutions, Electrochemistry, Chemical Kinetics, Polymers",      "tags": ["Organic", "Physical"],                "icon": "🧪", "gradient": "chemistry","chapter_count": 16, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub15", "stream_id": "s5", "name": "Biology",           "slug": "biology",           "description": "Reproduction, Genetics, Biotechnology, Ecology, Evolution",                   "tags": ["Genetics", "Biotechnology", "Ecology"],"icon": "🌱", "gradient": "biology",  "chapter_count": 16, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── AHSEC Class 12 – Arts ────────────────────────────────────────────
        {"id": "sub16", "stream_id": "s6", "name": "Political Science", "slug": "political-science", "description": "Indian Government, Electoral Politics, Social Movements, International Relations", "tags": ["Constitution", "Elections", "Federalism"], "icon": "🏛️", "gradient": "arts", "chapter_count": 9, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub17", "stream_id": "s6", "name": "History",           "slug": "history",           "description": "Themes in World History, Indian Civilisation, Colonial Society, Partition",   "tags": ["World History", "Colonialism", "Partition"], "icon": "📜", "gradient": "arts", "chapter_count": 15, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub18", "stream_id": "s6", "name": "Economics",         "slug": "economics",         "description": "National Income, Money and Banking, Balance of Payments, Indian Economy",     "tags": ["Macro", "Indian Economy", "Development"], "icon": "📊", "gradient": "arts", "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},

        # ── AHSEC Class 11 – Commerce ────────────────────────────────────────────
        {"id": "sub43", "stream_id": "s13","name": "Accountancy",          "slug": "accountancy",       "description": "Journal, Ledger, Trial Balance, Final Accounts, Bank Reconciliation Statement",  "tags": ["Journal", "Ledger", "Balance Sheet"],  "icon": "💰", "gradient": "arts",    "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub44", "stream_id": "s13","name": "Business Studies",      "slug": "business-studies",  "description": "Nature of Business, Forms of Organisation, Business Services, Trade",           "tags": ["Management", "Organisation", "Trade"], "icon": "🏢", "gradient": "arts",    "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub45", "stream_id": "s13","name": "Economics",             "slug": "economics",         "description": "Introduction to Microeconomics, Indian Economic Development, Statistics",      "tags": ["Micro", "Statistics", "Development"],  "icon": "📊", "gradient": "arts",    "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub46", "stream_id": "s13","name": "Mathematics (Commerce)","slug": "mathematics",       "description": "Sets, Relations, Functions, Trigonometry, Algebra for Commerce",               "tags": ["Algebra", "Sets", "Probability"],      "icon": "📐", "gradient": "math",    "chapter_count": 12, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── AHSEC Class 12 – Commerce ────────────────────────────────────────────
        {"id": "sub47", "stream_id": "s14","name": "Accountancy",          "slug": "accountancy",       "description": "Company Accounts, Analysis of Financial Statements, Cash Flow Statement",      "tags": ["Company Accounts", "Analysis", "Cash"],"icon": "💰", "gradient": "arts",    "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub48", "stream_id": "s14","name": "Business Studies",      "slug": "business-studies",  "description": "Management, Organising, Staffing, Directing, Controlling, Marketing, Finance", "tags": ["Management", "Marketing", "Finance"],  "icon": "🏢", "gradient": "arts",    "chapter_count": 12, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub49", "stream_id": "s14","name": "Economics",             "slug": "economics",         "description": "Macroeconomics — National Income, Money, Banking, Government Budget, BOP",    "tags": ["National Income", "Money", "Budget"],  "icon": "📊", "gradient": "arts",    "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub50", "stream_id": "s14","name": "Mathematics (Commerce)","slug": "mathematics",       "description": "Relations, Matrices, Determinants, Calculus, Linear Programming for Commerce", "tags": ["Matrices", "Calculus", "LP"],           "icon": "📐", "gradient": "math",    "chapter_count": 11, "status": "published", "created_at": "2024-01-01T00:00:00Z"},

        # ── DEGREE 2nd Sem – B.Com ────────────────────────────────────────────
        {"id": "sub19", "stream_id": "s7", "name": "Business Economics",          "slug": "business-economics",    "description": "Micro & Macro Economics for Commerce, Demand, Supply, Market Structures", "tags": ["Micro", "Macro", "Market"],                 "icon": "📈", "gradient": "arts",     "chapter_count": 8,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub20", "stream_id": "s7", "name": "Financial Accounting",        "slug": "financial-accounting",  "description": "Journal Entries, Ledger, Trial Balance, Final Accounts, Bank Reconciliation", "tags": ["Accounts", "Journal", "Balance Sheet"],     "icon": "💰", "gradient": "arts",     "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub21", "stream_id": "s7", "name": "Business Mathematics",        "slug": "business-mathematics",  "description": "Arithmetic, Algebra, Matrices, Statistics for Commerce",                    "tags": ["Algebra", "Statistics", "Matrices"],        "icon": "📐", "gradient": "math",     "chapter_count": 7,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub22", "stream_id": "s7", "name": "Business Communication",      "slug": "business-communication","description": "Communication Skills, Business Letters, Reports, Presentations",              "tags": ["Communication", "Writing", "Soft Skills"],  "icon": "📝", "gradient": "arts",     "chapter_count": 6,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── DEGREE 2nd Sem – B.A ─────────────────────────────────────────────
        {"id": "sub23", "stream_id": "s8", "name": "English Literature",          "slug": "english-literature",    "description": "Prose, Poetry, Drama — British and Indian Literature",                      "tags": ["Prose", "Poetry", "Drama"],                 "icon": "📚", "gradient": "arts",     "chapter_count": 8,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub24", "stream_id": "s8", "name": "Political Science",           "slug": "political-science",     "description": "Political Theory, Indian Constitution, Comparative Politics",                "tags": ["Constitution", "Political Theory"],         "icon": "🏛️", "gradient": "arts",    "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub25", "stream_id": "s8", "name": "History",                     "slug": "history",               "description": "Ancient, Medieval and Modern History; World History",                       "tags": ["Ancient", "Medieval", "World"],              "icon": "🏺", "gradient": "arts",     "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub26", "stream_id": "s8", "name": "Economics",                   "slug": "economics",             "description": "Introduction to Micro & Macro Economics, Indian Economic Development",      "tags": ["Micro", "Macro", "Development"],            "icon": "📊", "gradient": "arts",     "chapter_count": 8,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── DEGREE 2nd Sem – B.Sc ────────────────────────────────────────────
        {"id": "sub27", "stream_id": "s9", "name": "Physics",                     "slug": "physics",               "description": "Mechanics, Waves, Thermodynamics, Optics at Degree Level",                  "tags": ["Mechanics", "Waves", "Optics"],             "icon": "⚡", "gradient": "physics",  "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub28", "stream_id": "s9", "name": "Chemistry",                   "slug": "chemistry",             "description": "Physical, Organic and Inorganic Chemistry at Degree Level",                 "tags": ["Organic", "Inorganic", "Physical"],         "icon": "🧪", "gradient": "chemistry","chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub29", "stream_id": "s9", "name": "Mathematics",                 "slug": "mathematics",           "description": "Calculus, Linear Algebra, Differential Equations at Degree Level",          "tags": ["Calculus", "Algebra", "Differential Eq"],  "icon": "📐", "gradient": "math",     "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub30", "stream_id": "s9", "name": "Computer Science",            "slug": "computer-science",      "description": "C Programming, Data Structures, DBMS, Operating Systems",                   "tags": ["Programming", "Data Structures", "DBMS"],  "icon": "💻", "gradient": "physics",  "chapter_count": 8,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},

        # ── DEGREE 4th Sem – B.Com ────────────────────────────────────────────
        {"id": "sub31", "stream_id": "s10","name": "Cost Accounting",             "slug": "cost-accounting",       "description": "Cost Concepts, Job Costing, Process Costing, Standard Costing, Marginal Costing", "tags": ["Costing", "Marginal", "Standard"],          "icon": "💰", "gradient": "arts",     "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub32", "stream_id": "s10","name": "Income Tax",                  "slug": "income-tax",            "description": "Income Tax Act, Heads of Income, Deductions, Assessment, Tax Computation",    "tags": ["Tax", "Income", "Deductions"],              "icon": "📋", "gradient": "arts",     "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub33", "stream_id": "s10","name": "Business Law",                "slug": "business-law",          "description": "Indian Contract Act, Sale of Goods Act, Company Law, Consumer Protection",    "tags": ["Contract Law", "Company Law", "Legal"],     "icon": "⚖️", "gradient": "arts",     "chapter_count": 8,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub34", "stream_id": "s10","name": "Principles of Management",    "slug": "management",            "description": "Functions of Management, Planning, Organising, Leading, Controlling",        "tags": ["Planning", "Organising", "Leadership"],     "icon": "🏢", "gradient": "arts",     "chapter_count": 8,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── DEGREE 4th Sem – B.A ─────────────────────────────────────────────
        {"id": "sub35", "stream_id": "s11","name": "English Communication",       "slug": "english-communication", "description": "Advanced Writing, Comprehension, Communication for BA Final Year",           "tags": ["Writing", "Communication", "Grammar"],      "icon": "📝", "gradient": "arts",     "chapter_count": 7,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub36", "stream_id": "s11","name": "Indian Government & Politics","slug": "indian-politics",       "description": "Federal System, Parliament, Judiciary, Election Commission, Local Governance", "tags": ["Parliament", "Judiciary", "Federalism"],    "icon": "🗳️", "gradient": "arts",    "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub37", "stream_id": "s11","name": "Modern Indian History",       "slug": "modern-history",        "description": "Freedom Struggle, Partition, Post-Independence India, Economic Development",   "tags": ["Freedom Struggle", "Partition", "Modern"],  "icon": "🏺", "gradient": "arts",     "chapter_count": 10, "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub38", "stream_id": "s11","name": "Indian Economy",              "slug": "indian-economy",        "description": "Five-Year Plans, Economic Reforms 1991, Poverty, Agriculture, Industry",     "tags": ["Economy", "Reforms", "Development"],        "icon": "🇮🇳", "gradient": "arts",    "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        # ── DEGREE 4th Sem – B.Sc ────────────────────────────────────────────
        {"id": "sub39", "stream_id": "s12","name": "Physics",                     "slug": "physics",               "description": "Electrodynamics, Quantum Mechanics, Nuclear Physics, Solid State Physics",   "tags": ["Quantum", "Nuclear", "Electrodynamics"],   "icon": "⚡", "gradient": "physics",  "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub40", "stream_id": "s12","name": "Chemistry",                   "slug": "chemistry",             "description": "Organic Synthesis, Coordination Chemistry, Thermodynamics, Spectroscopy",    "tags": ["Synthesis", "Coordination", "Thermo"],     "icon": "🧪", "gradient": "chemistry","chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub41", "stream_id": "s12","name": "Mathematics",                 "slug": "mathematics",           "description": "Abstract Algebra, Complex Analysis, Numerical Methods, Statistics",           "tags": ["Abstract Algebra", "Analysis", "Stats"],   "icon": "📐", "gradient": "math",     "chapter_count": 9,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "sub42", "stream_id": "s12","name": "Computer Science",            "slug": "computer-science",      "description": "Java Programming, Web Technology, Computer Networks, Software Engineering",   "tags": ["Java", "Networking", "Web"],               "icon": "💻", "gradient": "physics",  "chapter_count": 8,  "status": "published", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "chapters": [],
}

def _generate_chapters():
    _CH = {
        "sub1": ["Sets","Relations and Functions","Trigonometric Functions","Mathematical Induction","Complex Numbers and Quadratic Equations","Linear Inequalities","Permutations and Combinations","Binomial Theorem","Sequences and Series","Straight Lines","Conic Sections","Introduction to Three Dimensional Geometry","Limits and Derivatives","Statistics","Probability"],
        "sub2": ["Physical World","Units and Measurements","Motion in a Straight Line","Motion in a Plane","Laws of Motion","Work, Energy and Power","System of Particles and Rotational Motion","Gravitation","Mechanical Properties of Solids","Mechanical Properties of Fluids","Thermal Properties of Matter","Thermodynamics","Kinetic Theory","Oscillations","Waves"],
        "sub3": ["Some Basic Concepts of Chemistry","Structure of Atom","Classification of Elements and Periodicity","Chemical Bonding and Molecular Structure","Thermodynamics","Equilibrium","Redox Reactions","Organic Chemistry: Some Basic Principles","Hydrocarbons","Environmental Chemistry"],
        "sub4": ["Physical World","Units and Measurements","Motion in a Straight Line","Motion in a Plane","Laws of Motion","Work, Energy and Power","Gravitation","Mechanical Properties of Solids","Mechanical Properties of Fluids","Thermodynamics","Kinetic Theory","Oscillations","Waves"],
        "sub5": ["Some Basic Concepts of Chemistry","Structure of Atom","Classification of Elements","Chemical Bonding","Thermodynamics","Equilibrium","Redox Reactions","Organic Chemistry Basics","Hydrocarbons","Environmental Chemistry"],
        "sub6": ["The Living World","Biological Classification","Plant Kingdom","Animal Kingdom","Morphology of Flowering Plants","Anatomy of Flowering Plants","Cell: The Unit of Life","Cell Division","Biomolecules","Transport in Plants","Mineral Nutrition","Photosynthesis","Respiration in Plants","Plant Growth and Development","Digestion and Absorption","Breathing and Exchange of Gases","Body Fluids and Circulation","Excretory Products","Locomotion and Movement","Neural Control and Coordination","Chemical Coordination and Integration"],
        "sub7": ["Constitution: Why and How?","Rights in the Indian Constitution","Election and Representation","Executive","Legislature","Judiciary","Federalism","Local Governments","Philosophy of the Constitution"],
        "sub8": ["From the Beginning of Time","Writing and City Life","An Empire Across Three Continents","The Central Islamic Lands","Nomadic Empires","Three Orders","Changing Cultural Traditions","Confrontation of Cultures","The Industrial Revolution","Displacing Indigenous Peoples","Paths to Modernisation"],
        "sub9": ["Introduction to Micro Economics","Consumer Behaviour","Demand","Elasticity of Demand","Production","Cost and Revenue","Supply","Market Equilibrium","Statistics for Economics","Indian Economic Development"],
        "sub10": ["Relations and Functions","Inverse Trigonometric Functions","Matrices","Determinants","Continuity and Differentiability","Application of Derivatives","Integrals","Application of Integrals","Differential Equations","Vector Algebra","Three Dimensional Geometry","Linear Programming","Probability"],
        "sub11": ["Electric Charges and Fields","Electrostatic Potential and Capacitance","Current Electricity","Moving Charges and Magnetism","Magnetism and Matter","Electromagnetic Induction","Alternating Current","Electromagnetic Waves","Ray Optics","Wave Optics","Dual Nature of Radiation and Matter","Atoms","Nuclei","Semiconductor Electronics","Communication Systems"],
        "sub12": ["The Solid State","Solutions","Electrochemistry","Chemical Kinetics","Surface Chemistry","General Principles of Isolation of Elements","The p-Block Elements","The d- and f-Block Elements","Coordination Compounds","Haloalkanes and Haloarenes","Alcohols, Phenols and Ethers","Aldehydes, Ketones and Carboxylic Acids","Amines","Biomolecules","Polymers","Chemistry in Everyday Life"],
        "sub13": ["Electric Charges and Fields","Electrostatic Potential and Capacitance","Current Electricity","Moving Charges and Magnetism","Electromagnetic Induction","Alternating Current","Ray Optics","Wave Optics","Dual Nature of Radiation","Atoms","Nuclei","Semiconductor Electronics"],
        "sub14": ["The Solid State","Solutions","Electrochemistry","Chemical Kinetics","Surface Chemistry","p-Block Elements","d- and f-Block Elements","Coordination Compounds","Haloalkanes and Haloarenes","Alcohols, Phenols and Ethers","Aldehydes, Ketones and Carboxylic Acids","Amines","Biomolecules","Polymers"],
        "sub15": ["Reproduction in Organisms","Sexual Reproduction in Flowering Plants","Human Reproduction","Reproductive Health","Principles of Inheritance and Variation","Molecular Basis of Inheritance","Evolution","Human Health and Disease","Strategies for Enhancement in Food Production","Microbes in Human Welfare","Biotechnology: Principles and Processes","Biotechnology and Its Applications","Organisms and Populations","Ecosystem","Biodiversity and Conservation","Environmental Issues"],
        "sub16": ["Challenges of Nation Building","Era of One-Party Dominance","Politics of Planned Development","India's External Relations","Challenges to the Congress System","Crisis of Democratic Order","Rise of Popular Movements","Regional Aspirations","Recent Developments in Indian Politics"],
        "sub17": ["Bricks, Beads and Bones","Kings, Farmers and Towns","Kinship, Caste and Class","Thinkers, Beliefs and Buildings","Through the Eyes of Travellers","Bhakti-Sufi Traditions","An Imperial Capital: Vijayanagara","Peasants, Zamindars and the State","Colonialism and the Countryside","Rebels and the Raj","Mahatma Gandhi and the Nationalist Movement","Framing the Constitution","Understanding Partition"],
        "sub18": ["National Income and Related Aggregates","Money and Banking","Determination of Income and Employment","Government Budget and the Economy","Balance of Payments","Indian Economy: Current Challenges","Development Experience of India","Liberalisation, Privatisation and Globalisation","Poverty"],
        "sub19": ["Nature and Scope of Business Economics","Theory of Demand","Elasticity of Demand","Theory of Production","Theory of Costs","Market Structures","Pricing Under Different Markets","National Income"],
        "sub20": ["Introduction to Accounting","Journal Entries","Ledger","Trial Balance","Final Accounts of Sole Trader","Depreciation","Bank Reconciliation Statement","Rectification of Errors","Consignment Accounts","Joint Venture"],
        "sub21": ["Ratio and Proportion","Arithmetic Progressions","Simple and Compound Interest","Matrices","Set Theory","Probability","Statistics"],
        "sub22": ["Introduction to Business Communication","Business Letters","Report Writing","Presentation Skills","Meetings and Minutes","Non-Verbal Communication"],
        "sub23": ["Prose — Selected Essays","Poetry — Romantic to Modern","Drama — Shakespeare","Indian Literature in English","Literary Criticism Basics","Grammar and Composition","Comprehension and Précis","Creative Writing"],
        "sub24": ["Political Theory","Indian Constitution","Fundamental Rights and Duties","Union Government","State Government","Local Self-Government","Electoral System","Political Parties","Comparative Politics"],
        "sub25": ["Indus Valley Civilisation","Vedic Age","Mauryan Empire","Gupta Empire","Medieval India — Delhi Sultanate","Medieval India — Mughal Empire","Modern India — Company Rule","Indian National Movement","Post-Independence India","World History — French Revolution"],
        "sub26": ["Introduction to Economics","Theory of Demand and Supply","Consumer Behaviour","Production and Costs","Market Forms","National Income Accounting","Money and Banking","Indian Economy"],
        "sub27": ["Mechanics","Properties of Matter","Heat and Thermodynamics","Waves and Oscillations","Optics","Electrostatics","Current Electricity","Magnetism","Modern Physics"],
        "sub28": ["Atomic Structure","Chemical Bonding","Thermodynamics","Solutions","Chemical Equilibrium","Electrochemistry","Organic Chemistry Fundamentals","Coordination Chemistry","Spectroscopy"],
        "sub29": ["Differential Calculus","Integral Calculus","Differential Equations","Linear Algebra","Analytical Geometry","Vector Analysis","Sequences and Series","Complex Numbers","Numerical Methods"],
        "sub30": ["Introduction to C Programming","Control Structures","Functions and Recursion","Arrays and Strings","Pointers","Structures and Unions","File Handling","Data Structures"],
        "sub31": ["Introduction to Cost Accounting","Material Cost","Labour Cost","Overheads","Job Costing","Process Costing","Marginal Costing","Standard Costing","Budget and Budgetary Control","Cost Audit"],
        "sub32": ["Basic Concepts of Income Tax","Residential Status","Income from Salary","Income from House Property","Profits and Gains of Business","Capital Gains","Income from Other Sources","Deductions","Assessment of Individuals"],
        "sub33": ["Indian Contract Act 1872","Special Contracts","Sale of Goods Act 1930","Companies Act","Partnership Act","Consumer Protection Act","Negotiable Instruments Act","Arbitration and Conciliation"],
        "sub34": ["Nature and Significance of Management","Planning","Organising","Staffing","Directing","Controlling","Financial Management","Marketing Management"],
        "sub35": ["Communication Theory","Business Correspondence","Report Writing","Comprehension Skills","Grammar and Usage","Technical Writing","Presentation Skills"],
        "sub36": ["Indian Constitution","Parliament","Executive","Judiciary","Federalism","Local Government","Election Commission","Political Parties","Social Movements"],
        "sub37": ["Revolt of 1857","Social Reform Movements","Indian National Congress","Gandhian Era","Subhas Chandra Bose","Partition of India","Making of the Constitution","Nehru Era","Economic Development Post-1947","India After 1991"],
        "sub38": ["Indian Economy Overview","Five-Year Plans","Agriculture Sector","Industrial Development","Economic Reforms 1991","Poverty and Unemployment","Human Development","Foreign Trade","Sustainable Development"],
        "sub39": ["Electrostatics","Current and Electricity","Electrodynamics","Optics","Quantum Mechanics","Nuclear Physics","Solid State Physics","Statistical Mechanics","Electronics"],
        "sub40": ["Organic Reaction Mechanisms","Stereochemistry","Coordination Chemistry","Thermodynamics","Electrochemistry","Spectroscopy","Polymer Chemistry","Environmental Chemistry","Analytical Chemistry"],
        "sub41": ["Abstract Algebra — Groups","Abstract Algebra — Rings","Real Analysis","Complex Analysis","Topology Basics","Numerical Methods","Linear Programming","Statistics","Probability Theory"],
        "sub42": ["Java Programming Fundamentals","Object-Oriented Programming","Web Technology — HTML/CSS/JS","Database Management Systems","Computer Networks","Software Engineering","Operating Systems","Data Structures and Algorithms"],
        "sub43": ["Introduction to Accounting","Accounting Standards","Journal and Ledger","Trial Balance and Errors","Depreciation Accounting","Final Accounts","Bank Reconciliation","Bills of Exchange","Capital and Revenue","Not-for-Profit Organisations"],
        "sub44": ["Nature and Purpose of Business","Forms of Business Organisation","Public, Private and Global Enterprises","Business Services","Emerging Modes of Business","Social Responsibility of Business","Formation of a Company","Sources of Business Finance","Small Business"],
        "sub45": ["Introduction to Micro Economics","Consumer Equilibrium","Demand and Supply","Elasticity","Production Function","Cost and Revenue","Market Equilibrium","Statistics for Economics","Collection of Data","Measures of Central Tendency"],
        "sub46": ["Sets","Relations and Functions","Trigonometric Functions","Sequences and Series","Straight Lines","Probability","Permutations and Combinations","Binomial Theorem","Linear Inequalities","Complex Numbers","Limits","Statistics"],
        "sub47": ["Accounting for Not-for-Profit Organisations","Accounting for Partnership — Basics","Goodwill","Change in Profit-Sharing Ratio","Admission of a Partner","Retirement and Death of a Partner","Dissolution of Partnership Firm","Company Accounts — Share Capital","Company Accounts — Debentures"],
        "sub48": ["Nature and Significance of Management","Principles of Management","Business Environment","Planning","Organising","Staffing","Directing","Controlling","Financial Management","Financial Markets","Marketing Management","Consumer Protection"],
        "sub49": ["National Income and Related Aggregates","Money and Banking","Determination of Income and Employment","Government Budget","Balance of Payments","Development Experience: India and Neighbours","Indian Economy 1950-1990","Economic Reforms since 1991","Current Challenges","Sustainable Development"],
        "sub50": ["Relations and Functions","Inverse Trigonometric Functions","Matrices","Determinants","Continuity and Differentiability","Application of Derivatives","Integrals","Application of Integrals","Differential Equations","Linear Programming","Probability"],
    }
    chapters = []
    ch_id = 1
    for subj_id, titles in _CH.items():
        for idx, title in enumerate(titles, 1):
            chapters.append({"id": f"ch_{ch_id}", "subject_id": subj_id, "title": title, "chapter_number": idx, "order_index": idx, "status": "published", "created_at": "2024-01-01T00:00:00Z"})
            ch_id += 1
    return chapters

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
        existing = await db.boards.count_documents({})
        degree_exists = await db.boards.find_one({"id": "b2"})
        ch_count = await db.chapters.count_documents({})
        expected_ch = len(SEED_DATA["chapters"])
        if existing > 0 and degree_exists and ch_count == expected_ch:
            _seeded = True
            return
    except Exception as e:
        logger.warning(f"Database not available for seeding: {e}")
        return
    logger.info("Seeding content data...")
    from pymongo import ReplaceOne
    if SEED_DATA["boards"]:
        ops = [ReplaceOne({"id": b["id"]}, b, upsert=True) for b in SEED_DATA["boards"]]
        await db.boards.bulk_write(ops, ordered=False)
    if SEED_DATA["classes"]:
        ops = [ReplaceOne({"id": c["id"]}, c, upsert=True) for c in SEED_DATA["classes"]]
        await db.classes.bulk_write(ops, ordered=False)
    if SEED_DATA["streams"]:
        ops = [ReplaceOne({"id": s["id"]}, s, upsert=True) for s in SEED_DATA["streams"]]
        await db.streams.bulk_write(ops, ordered=False)
    if SEED_DATA["subjects"]:
        ops = [ReplaceOne({"id": s["id"]}, s, upsert=True) for s in SEED_DATA["subjects"]]
        await db.subjects.bulk_write(ops, ordered=False)
    await db.chapters.delete_many({})
    if SEED_DATA["chapters"]:
        await db.chapters.insert_many(SEED_DATA["chapters"], ordered=False)
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
from prompts import build_system_prompt, _THINK_BRIEF, _classify_question

# ─────────────────────────────────────────────
# RAG SEARCH + WEB SEARCH FALLBACK
# Priority chain:
#   Level 1 — Content chunks from DB (best — actual indexed syllabus text)
#   Level 2 — Subject descriptions + tags + chapter titles (medium — metadata)
#   Level 3 — DuckDuckGo web search (fallback — when DB has nothing useful)
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
    return [w for w in raw if len(w) >= 3 and w not in stop_words][:6]


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


# ─────────────────────────────────────────────
# AUTO-CHUNKING FOR RAG
# ─────────────────────────────────────────────

async def auto_chunk_content(chapter_id: str, content: str, subject_id: str = None) -> list:
    """
    Automatically split chapter content into searchable chunks.
    
    Strategy:
    - Split by double newlines (paragraphs)
    - Each chunk: 100-800 chars (optimal for RAG)
    - Extract keywords for each chunk
    - Store in 'chunks' collection for fast retrieval
    
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
                    await db.chunks.insert_one(chunk)
                    chunks_created.append(chunk["id"])
        else:
            # Paragraph is good size, create chunk
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
    try:
        keywords = _extract_keywords(query)
        if not keywords:
            return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}

        # ── 1. Search content chunks ──────────────────────────────────────────
        regex_parts = [{"content": {"$regex": kw, "$options": "i"}} for kw in keywords]
        chunk_filter: dict = {"$or": regex_parts}

        if subject_id:
            sub_chapters = await db.chapters.find(
                {"subject_id": subject_id}, {"_id": 0, "id": 1}
            ).to_list(200)
            chapter_ids = [c["id"] for c in sub_chapters]
            if chapter_ids:
                chunk_filter = {"$and": [{"chapter_id": {"$in": chapter_ids}}, {"$or": regex_parts}]}

        chunks = await db.chunks.find(chunk_filter, {"_id": 0}).limit(5).to_list(5)

        # ── 2. Search subjects by name / description / tags ───────────────────
        subj_kw_filter = {"$or": [
            {"name":        {"$regex": "|".join(keywords), "$options": "i"}},
            {"description": {"$regex": "|".join(keywords), "$options": "i"}},
            {"tags":        {"$elemMatch": {"$regex": "|".join(keywords), "$options": "i"}}},
        ], "status": "published"}
        if subject_id:
            subj_kw_filter = {"$and": [{"id": subject_id}, {"status": "published"}]}
        elif subject_name:
            subj_kw_filter = {"$and": [
                {"name": {"$regex": subject_name, "$options": "i"}, "status": "published"},
            ]}

        subjects_found = await db.subjects.find(subj_kw_filter, {"_id": 0}).limit(3).to_list(3)

        # ── 3. Search chapters by title ───────────────────────────────────────
        ch_filter = {"$or": [{"title": {"$regex": kw, "$options": "i"}} for kw in keywords]}
        if subject_id:
            ch_filter = {"$and": [{"subject_id": subject_id}, ch_filter]}
        elif subjects_found:
            subject_ids = [s["id"] for s in subjects_found]
            ch_filter = {"$and": [{"subject_id": {"$in": subject_ids}}, ch_filter]}

        chapters_found = await db.chapters.find(ch_filter, {"_id": 0}).limit(5).to_list(5)

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

        return {
            "chunks":   chunks,
            "chapters": chapters_found,
            "subjects": subjects_found,
            "source":   source,
            "quality":  quality,
        }

    except Exception as e:
        logger.error(f"RAG search error: {e}")
        return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}


# ─────────────────────────────────────────────────────────────────────────────
# WEB SEARCH — Assam-Education Priority Scoring
#
# Trusted domain tiers (higher score = more trustworthy):
#   Tier 1 (score +30): Official Assam boards — SEBA, AHSEC, Assam Govt
#   Tier 2 (score +20): Assam universities — Gauhati, Dibrugarh, Cotton, etc.
#   Tier 3 (score +10): National boards — NCERT, NIOS, CBSE academic
#   Any Assam keyword in URL (+3) or body text (+1)
# ─────────────────────────────────────────────────────────────────────────────

_ASSAM_TRUSTED_DOMAINS: dict[str, int] = {
    # Tier 1 — Official Assam education boards / government
    "sebaonline.org":          3,
    "ahsec.assam.gov.in":      3,
    "ahsec.nic.in":            3,
    "assam.gov.in":            3,
    "ssa.assam.gov.in":        3,
    # Tier 2 — Assam universities
    "gauhati.ac.in":           2,
    "dibru.ac.in":             2,
    "cottonuniversity.ac.in":  2,
    "rnbguwahati.ac.in":       2,
    "dispur.ac.in":            2,
    "kkhsou.ac.in":            2,   # Krishna Kanta Handiqui State Open University
    "aus.ac.in":               2,   # Assam University Silchar
    # Tier 3 — National boards / syllabus portals
    "ncert.nic.in":            1,
    "ncert.gov.in":            1,
    "nios.ac.in":              1,
    "cbseacademic.nic.in":     1,
    "cbse.gov.in":             1,
}

_ASSAM_BODY_KEYWORDS = {
    'ahsec', 'seba', 'assam board', 'hs exam', 'hslc', 'gauhati university',
    'dibrugarh university', 'assam higher secondary', 'hs 1st year', 'hs 2nd year',
    'tdc', 'ba 1st semester', 'bcom 1st semester', 'bsc 1st semester',
    'assam', 'guwahati', 'assamese',
}


def _score_web_result(url: str, title: str, body: str) -> int:
    """Score a search result by Assam-education relevance and domain trust."""
    url_lower  = url.lower()
    text_lower = (title + " " + body).lower()
    score = 0

    # Domain trust tier score
    for domain, tier in _ASSAM_TRUSTED_DOMAINS.items():
        if domain in url_lower:
            score += tier * 10
            break

    # Assam keywords in URL
    for kw in ('assam', 'ahsec', 'seba', 'gauhati', 'dibrugarh', 'guwahati'):
        if kw in url_lower:
            score += 3

    # Assam education keywords in body/title
    for kw in _ASSAM_BODY_KEYWORDS:
        if kw in text_lower:
            score += 1

    return score


def _tier_label(score: int) -> str:
    """Human-readable trust label for a result score."""
    if score >= 30: return "Official Assam Board"
    if score >= 20: return "Assam University"
    if score >= 10: return "National Board"
    if score >= 5:  return "Assam-related"
    return "General"


async def web_search_fallback(query: str) -> dict:
    """
    Level-3 fallback: DuckDuckGo full-text search (duckduckgo-search package).

    Query is augmented with AHSEC/SEBA/Assam terms to bias results toward
    Assam education sources. Results are scored and ranked by domain trust:

      Tier 1 — SEBA, AHSEC, Assam Govt portals
      Tier 2 — Gauhati, Dibrugarh, and other Assam universities
      Tier 3 — NCERT, NIOS, CBSE national boards
      General — any result mentioning Assam education keywords

    Returns:
      {"results": str, "source": "web", "web_sources": [...]}  on success
      {"results": "", "source": "none"}                        on failure
    """
    from concurrent.futures import ThreadPoolExecutor

    # Augment query with Assam board context to bias search ranking
    augmented_query = f"{query} AHSEC SEBA Assam board exam"

    def _run_ddgs_search() -> list:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                return list(ddgs.text(augmented_query, max_results=10))
        except Exception as ddgs_err:
            logger.warning(f"DDGS search error: {type(ddgs_err).__name__}: {str(ddgs_err)[:100]}")
            return []

    try:
        loop = asyncio.get_event_loop()
        results = await asyncio.wait_for(
            loop.run_in_executor(_THREAD_POOL, _run_ddgs_search),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Web search (DDGS): Timeout for query: {augmented_query[:60]}")
        return await _web_search_instant_fallback(query)
    except Exception as e:
        logger.warning(f"Web search (DDGS): Executor error: {type(e).__name__}: {str(e)[:100]}")
        return await _web_search_instant_fallback(query)

    if not results:
        logger.info(f"Web search (DDGS): 0 results → trying instant-answer fallback")
        return await _web_search_instant_fallback(query)

    # Score and sort results by Assam-education relevance
    scored = []
    for r in results:
        url   = r.get("href", r.get("url", ""))
        title = r.get("title", "")
        body  = r.get("body", r.get("snippet", ""))
        if not body.strip():
            continue
        score = _score_web_result(url, title, body)
        scored.append((score, url, title, body))

    scored.sort(key=lambda x: -x[0])

    # Format top 5 results with trust labels for the AI
    parts   = []
    sources = []
    for score, url, title, body in scored[:5]:
        label = _tier_label(score)
        tag   = f"[Source: {label}]" if score >= 5 else ""
        parts.append(f"{tag} {title}\n{body[:350]}".strip())
        sources.append({"title": title, "url": url, "score": score, "tier": label})

    if not parts:
        return {"results": "", "source": "none"}

    combined = "\n\n".join(parts)
    top_score = scored[0][0] if scored else 0
    logger.info(
        f"Web search (DDGS): {len(parts)} results ranked | "
        f"top tier: {_tier_label(top_score)} (score {top_score}) | "
        f"query: {augmented_query[:50]}"
    )
    return {
        "results":     combined[:2500],
        "source":      "web",
        "web_sources": sources,
    }


async def _web_search_instant_fallback(query: str) -> dict:
    """
    Legacy DuckDuckGo instant-answer API — used as fallback when DDGS fails.
    Returns {"results": str, "source": "web"} or {"results": "", "source": "none"}.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers={"User-Agent": "Syrabit.ai Educational Assistant 1.0"},
            )
            if resp.status_code != 200:
                return {"results": "", "source": "none"}
            data = resp.json()
            parts = []
            if data.get("AbstractText"):
                parts.append(data["AbstractText"])
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    parts.append(topic["Text"])
            if data.get("Answer"):
                parts.append(data["Answer"])
            if parts:
                return {"results": "\n\n".join(parts)[:1800], "source": "web", "web_sources": []}
            return {"results": "", "source": "none"}
    except Exception:
        return {"results": "", "source": "none"}



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
      Tier 3 — DuckDuckGo web search (only when DB has nothing)
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
        else:
            # No keyword match → use first 3000 chars of document
            relevant = document_text[:3000]

        return {
            "chunks": [],
            "chapters": [],
            "subjects": [],
            "document_text": relevant,
            "document_full": document_text[:3000],
            "source":  "document",
            "quality": "tier0",
        }
    # Step 1: RAG DB lookup
    rag_ctx = await rag_search(query, subject_id=subject_id, subject_name=subject_name)

    # Step 2: High quality — real chunks found → trust RAG, skip web
    if rag_ctx["quality"] == "high":
        logger.info(f"RAG resolve: HIGH-QUALITY database content found (chunks: {len(rag_ctx.get('chunks', []))}) | query: {query[:50]}")
        return rag_ctx

    # Step 3: Medium/None — supplement with web search
    # Skip web search for very short or conversational messages (greetings, etc.)
    # to avoid injecting irrelevant web results (e.g. "hii" → H II regions in astronomy)
    _conversational = {
        'hi', 'hii', 'hiii', 'hello', 'hey', 'helo', 'hiya', 'howdy', 'greetings',
        'thanks', 'thank you', 'ok', 'okay', 'bye', 'goodbye', 'good morning',
        'good afternoon', 'good evening', 'good night', 'namaste', 'sup', 'yo',
    }
    query_clean = query.strip().lower().rstrip('!?.')
    if len(query_clean) < 4 or query_clean in _conversational:
        logger.info(f"RAG resolve: SKIPPING web search for short/conversational query: '{query[:30]}'")
        return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}

    web_query = " ".join(filter(None, [subject_name, query]))
    web_ctx   = await web_search_fallback(web_query)

    has_rag = rag_ctx["quality"] == "medium"   # has subjects/chapters
    has_web = web_ctx.get("source") == "web"

    if has_rag and has_web:
        # Merge both — best possible context; preserve web_sources for trust-label display
        merged = {
            **rag_ctx,
            "web_results":  web_ctx["results"],
            "web_sources":  web_ctx.get("web_sources", []),
            "source":       "rag+web",
            "quality":      "medium+web",
        }
        logger.info(f"RAG resolve: MERGED database + web search | query: {query[:50]}")
        return merged

    if has_rag and not has_web:
        # Only curriculum metadata (no chunks, no web) — still useful
        logger.info(f"RAG resolve: MEDIUM database metadata only (no web results) | query: {query[:50]}")
        return {**rag_ctx, "quality": "medium"}

    if not has_rag and has_web:
        # Nothing in DB, web-only
        final = {**rag_ctx, **web_ctx}   # overrides source → "web"
        logger.info(f"RAG resolve: WEB-ONLY (no database matches) | query: {query[:50]}")
        return final

    # Both empty — AI will answer from training knowledge
    logger.info(f"RAG resolve: NO CONTEXT (no database or web results, using AI training only) | query: {query[:50]}")
    return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}


def build_rag_system_prompt(
    context: dict,
    rag_context: dict,
    user_info: dict = None,
    query: str = "",
    syllabus: dict = None,
) -> str:
    """
    Selects the adaptive prompt mode (casual / concise / structured) based on
    the student's query, injects their profile, then appends RAG grounding.

    Grounding tiers:
      Tier -1 — syllabus constraints (curriculum boundaries)
      Tier 0 — document (uploaded .txt file — absolute priority)
      Tier 1 — DB content chunks
      Tier 2 — Subject metadata (descriptions, tags, chapter titles)
      Tier 3 — Web search (fallback)
    """
    base_prompt = build_system_prompt(context, user_info=user_info, query=query)
    source      = rag_context.get("source",  "none")
    quality     = rag_context.get("quality", "none")
    chunks      = rag_context.get("chunks",   [])
    chapters    = rag_context.get("chapters", [])
    subjects    = rag_context.get("subjects", [])
    web_results = rag_context.get("results", "") or rag_context.get("web_results", "")
    document_text = rag_context.get("document_text", "")

    grounding = ""

    # ── Tier -1: Syllabus constraints (curriculum boundaries) ───────────────────
    if syllabus and syllabus.get("content"):
        syllabus_content = syllabus.get("content", "")
        syllabus_topics = ", ".join(syllabus.get("topics", [])[:10])
        grounding = (
            "\n\n---\n"
            "**CURRICULUM CONSTRAINTS (Tier -1 — Board Syllabus):**\n"
            "You are helping a student from the AHSEC/Degree curriculum. "
            "The following represents what this student is expected to know:\n\n"
            f"{syllabus_content}\n\n"
        )
        if syllabus_topics:
            grounding += f"**Key topics:** {syllabus_topics}\n\n"
        grounding += (
            "---\n"
            "*INSTRUCTION: Keep your answer within the scope of this curriculum. "
            "Do not introduce concepts beyond the standard curriculum unless explicitly requested. "
            "Prioritize accuracy over breadth.*\n"
        )

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

    # ── Tier 1/2: Curriculum DB context ──────────────────────────────────────
    if source in ("rag", "rag+web") and (chunks or subjects or chapters):

        if quality == "high":
            # Tier 1 — Real chunks (perfect RAG)
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Tier 1 — Syllabus Content):**\n"
                "The following content is from the student's actual syllabus database. "
                "Base your answer **primarily** on this. Quote directly when possible.\n\n"
            )
            for i, c in enumerate(chunks, 1):
                title = c.get("content_type", "content").capitalize()
                grounding += f"**[Block {i} — {title}]**\n{c.get('content', '')[:400]}\n\n"
            grounding += (
                "---\n"
                "*INSTRUCTION: Prioritise the above syllabus blocks. "
                "Supplement with your training knowledge only where the blocks are incomplete.*"
            )

        else:
            # Tier 2 — Metadata only (subject descriptions + chapter titles)
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Tier 2 — Curriculum Metadata):**\n"
                "No specific content blocks were found, but the following curriculum "
                "information is available from the syllabus database.\n\n"
            )
            if subjects:
                grounding += "**Matching subjects:**\n"
                for s in subjects:
                    desc = s.get("description", "")[:200]
                    tags = ", ".join(s.get("tags", [])[:5])
                    grounding += f"- **{s.get('name', '')}**: {desc}"
                    if tags:
                        grounding += f" *(topics: {tags})*"
                    grounding += "\n"

            if chapters:
                grounding += "\n**Relevant chapters in this subject:**\n"
                for ch in chapters:
                    grounding += f"- {ch.get('title', '')}\n"

            grounding += (
                "\n---\n"
                "*INSTRUCTION: Use the curriculum metadata above to keep your answer "
                "syllabus-aligned. Draw on your training knowledge for the full answer.*"
            )

    # ── Tier 3: Web search context ────────────────────────────────────────────
    if web_results:
        # Build source-trust legend from web_sources if available
        web_sources = rag_context.get("web_sources", [])
        source_legend = ""
        if web_sources:
            lines = []
            for s in web_sources[:5]:
                tier  = s.get("tier", "General")
                title = s.get("title", "")[:60]
                url   = s.get("url", "")
                lines.append(f"  • [{tier}] {title} — {url}")
            source_legend = "\nSources retrieved (ranked by trust):\n" + "\n".join(lines) + "\n"

        source_trust_instruction = (
            "\n\nSOURCE TRUST HIERARCHY for this answer:\n"
            "  1. [Official Assam Board] — SEBA / AHSEC / Assam Govt portals: HIGHEST trust. "
            "Quote directly when available.\n"
            "  2. [Assam University] — Gauhati University / Dibrugarh University / other Assam "
            "universities: HIGH trust. Use as primary reference for Degree-level questions.\n"
            "  3. [National Board] — NCERT / NIOS / CBSE: MEDIUM trust. Use only when no "
            "Assam-specific source covers the topic.\n"
            "  4. [General] — Other web sources: LOW trust. Use only to fill factual gaps; "
            "always cross-check with syllabus knowledge.\n"
            "\nIf results tagged [Official Assam Board] or [Assam University] are present, "
            "base your answer primarily on those. Discard or downweight [General] results "
            "if Assam-specific content is available."
        )

        if source == "rag+web":
            grounding += (
                "\n\n---\n"
                "**SUPPLEMENTARY WEB CONTEXT (Assam-Education Priority Search):**\n"
                "The following results were retrieved and ranked by relevance to SEBA / AHSEC / "
                "Gauhati University / Dibrugarh University. Use to fill gaps in the syllabus content above.\n"
                + source_legend
                + "\n"
                + web_results
                + "\n\n---\n"
                + source_trust_instruction
                + "\n\n*INSTRUCTION: Prioritise the Tier 1/2 syllabus content above. "
                "Use web context only to supplement where the syllabus blocks are incomplete.*"
            )
        else:
            # Web-only (nothing in DB)
            grounding += (
                "\n\n---\n"
                "**WEB SEARCH CONTEXT — Assam-Education Priority Search**\n"
                "(No matching content found in the syllabus database. "
                "Results below are ranked by Assam-board relevance.)\n"
                + source_legend
                + "\n"
                + web_results
                + "\n\n---\n"
                + source_trust_instruction
                + "\n\n*INSTRUCTION: Base your answer on [Official Assam Board] and "
                "[Assam University] sources first. Supplement with training knowledge. "
                "Mention if the information is not from the specific board syllabus.*"
            )

    return base_prompt + grounding if grounding else base_prompt


_LLM_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("LLM_MAX_CONCURRENT", 20)))
_LLM_BATCH_WINDOW_MS = int(os.environ.get("LLM_BATCH_WINDOW_MS", 50))

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
if _SARVAM_LLM_KEY:
    _LLM_PROVIDERS.append({"provider": "sarvam", "key": _SARVAM_LLM_KEY, "default_model": "sarvam-m"})
if _FIREWORKS_KEY:
    _LLM_PROVIDERS.append({"provider": "fireworksai", "key": _FIREWORKS_KEY, "default_model": "accounts/fireworks/models/qwen2p5-72b-instruct"})
if _GROQ_KEY and _GROQ_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "groq", "key": _GROQ_KEY, "default_model": "llama-3.1-8b-instant"})
if _OPENAI_KEY and _OPENAI_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "openai", "key": _OPENAI_KEY, "default_model": "gpt-4o-mini"})

_MODEL_PROVIDER_MAP = {
    "sarvam-m": "sarvam",
    "sarvam-30b": "sarvam",
    "sarvam-30b-16k": "sarvam",
    "sarvam-105b": "sarvam",
    "sarvam-105b-32k": "sarvam",
    "accounts/fireworks/models/qwen2p5-72b-instruct": "fireworksai",
    "accounts/fireworks/models/qwen3-235b-a22b": "fireworksai",
    "llama-3.3-70b-versatile": "groq",
    "llama-3.1-8b-instant": "groq",
}

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
        "temperature": 0.3,
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
    use_model = model or LLM_MODEL
    primary_provider, primary_key = _resolve_provider_for_model(use_model)

    if not primary_key and not _LLM_PROVIDERS:
        raise HTTPException(status_code=503, detail="LLM API key not configured")

    tried = set()
    last_err = None

    provider, key = primary_provider, primary_key
    try_model = use_model
    try:
        tried.add(provider)
        logger.info(f"LLM call: provider={provider}, model={try_model}")
        return await _call_single_provider(messages, provider, key, try_model, max_tokens)
    except Exception as e:
        last_err = e
        logger.warning(f"LLM primary failed ({provider}/{try_model}): {type(e).__name__}: {str(e)[:150]}")

    for fallback in _LLM_PROVIDERS:
        if fallback["provider"] in tried:
            continue
        tried.add(fallback["provider"])
        fb_model = fallback["default_model"]
        logger.info(f"LLM fallback: provider={fallback['provider']}, model={fb_model}")
        try:
            return await _call_single_provider(messages, fallback["provider"], fallback["key"], fb_model, max_tokens)
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

async def _stream_sarvam(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token SSE streaming from Sarvam — reuses persistent sarvam_llm_client (zero TCP overhead).
    Adds SARVAM_THINK_BUFFER so <think> reasoning never crowds out the user's answer budget."""
    api_max = max_tokens + SARVAM_THINK_BUFFER  # thinking tokens don't count toward user quota
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": api_max,
        "temperature": 0.3,
        "stream": True,
    }
    client = sarvam_llm_client
    if client is None:
        raise HTTPException(status_code=503, detail="Sarvam LLM client not initialised")
    async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            try:
                chunk = json.loads(raw)
                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                # Only yield content — sarvam-m embeds <think> in content (filtered in call_llm_api_stream)
                token = delta.get("content") or ""
                if token:
                    yield token
            except Exception:
                continue

async def call_llm_api_stream(messages: list, model: str = None, max_tokens: int = 2048):
    """
    Real token-by-token streaming from the LLM provider.
    Uses native streaming APIs for instant first-token delivery.
    Supports: Sarvam, Groq, Fireworks, OpenAI.
    If the requested model name is not in _MODEL_PROVIDER_MAP (e.g. a display-only alias
    like 'openai/gpt-oss-20b'), the resolved provider's default model is used instead.
    """
    use_model_raw = model or LLM_MODEL
    provider, key = _resolve_provider_for_model(use_model_raw)
    # If the requested model is not a known API model, use the provider's own default
    if use_model_raw not in _MODEL_PROVIDER_MAP:
        matched = next((p for p in _LLM_PROVIDERS if p["provider"] == provider), None)
        use_model = matched["default_model"] if matched else LLM_MODEL
        logger.info(f"Model alias '{use_model_raw}' → using provider default '{use_model}' ({provider})")
    else:
        use_model = use_model_raw

    if not key and provider != "sarvam":
        yield f"data: {json.dumps({'error': 'LLM API key not configured'})}\n\n"
        return

    in_think = False
    buf = ""

    async def _emit_tokens(token_source):
        nonlocal in_think, buf
        # max chars to keep at end of buffer so a split </think> tag is not lost
        _CLOSE_KEEP = len('</think>') - 1  # 7
        async for token in token_source:
            buf += token
            while buf:
                if in_think:
                    close_idx = buf.find('</think>')
                    if close_idx != -1:
                        buf = buf[close_idx + 8:]
                        in_think = False
                        # continue while-loop: process any content after </think>
                    else:
                        # Keep the last 7 chars: they might be a partial </think>
                        # that will complete when the next token arrives.
                        buf = buf[-_CLOSE_KEEP:] if len(buf) > _CLOSE_KEEP else buf
                        break
                else:
                    open_idx = buf.find('<think>')
                    if open_idx != -1:
                        before = buf[:open_idx]
                        if before:
                            yield f"data: {json.dumps({'content': before})}\n\n"
                        buf = buf[open_idx + 7:]
                        in_think = True
                    elif buf.endswith(('<', '<t', '<th', '<thi', '<thin', '<think')):
                        partial_start = buf.rfind('<')
                        candidate = buf[partial_start:]
                        if '<think>'[:len(candidate)] == candidate:
                            before = buf[:partial_start]
                            if before:
                                yield f"data: {json.dumps({'content': before})}\n\n"
                            buf = candidate
                            break
                        else:
                            yield f"data: {json.dumps({'content': buf})}\n\n"
                            buf = ""
                    else:
                        yield f"data: {json.dumps({'content': buf})}\n\n"
                        buf = ""
                        break
        if buf and not in_think:
            yield f"data: {json.dumps({'content': buf})}\n\n"

    try:
        if provider == "sarvam":
            async for chunk in _emit_tokens(_stream_sarvam(messages, key, use_model, max_tokens)):
                yield chunk
        else:
            logger.info(f"LLM stream: provider={provider}, model={use_model}")
            chat = LlmChat(
                api_key=key or OPENAI_API_KEY,
                session_id=str(uuid.uuid4()),
            ).with_model(provider, use_model)
            async def _legacy_tokens():
                async for token in chat.stream_messages(messages, max_tokens=max_tokens):
                    yield token
            async for chunk in _emit_tokens(_legacy_tokens()):
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
_THREAD_POOL = _cf.ThreadPoolExecutor(max_workers=30)

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
                return _pg_row(row)
        except Exception as e:
            logger.warning(f"pg supa_get_user failed: {e}")
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("*").eq("email", email.lower()).limit(1).execute())
            if r.data: return r.data[0]
        except Exception: pass
    try:
        return await db.users.find_one({"email": email.lower()}, {"_id": 0})
    except Exception:
        return None

async def supa_get_user_by_id(uid: str):
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_pg_user_cols()} FROM users WHERE id = $1 LIMIT 1", uid
                )
                return _pg_row(row)
        except Exception as e:
            logger.warning(f"pg supa_get_user_by_id failed: {e}")
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("*").eq("id", uid).limit(1).execute())
            if r.data: return r.data[0]
        except Exception: pass
    try:
        return await db.users.find_one({"id": uid}, {"_id": 0})
    except Exception:
        return None

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

async def supa_update_user(uid: str, updates: dict):
    if pg_pool and updates:
        try:
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

async def supa_list_users():
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT {_pg_user_cols()} FROM users WHERE is_admin = FALSE ORDER BY created_at DESC LIMIT 1000"
                )
                return _pg_rows(rows)
        except Exception as e:
            logger.warning(f"pg supa_list_users failed: {e}")
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("*").neq("is_admin", True).order("created_at", desc=True).limit(1000).execute())
            return r.data
        except Exception: pass
    try:
        return await db.users.find({"is_admin": {"$ne": True}}, {"_id": 0}).to_list(1000)
    except Exception:
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
    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                return await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_admin = FALSE")
        except Exception: pass
    if supa:
        try:
            r = await _supa(lambda: supa.table("users").select("id", count="exact").neq("is_admin", True).execute())
            return r.count if r.count is not None else len(r.data)
        except Exception: pass
    try:
        return await db.users.count_documents({"is_admin": {"$ne": True}})
    except Exception:
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
    cached = _redis_get_conversation(conv_id, uid)
    if cached:
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
        _redis_cache_conversation(conv_id, uid, result)
    return result

async def supa_upsert_conversation(conv: dict):
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
    _redis_invalidate_conversation(conv_id, uid)
    if pg_pool and updates:
        try:
            allowed = {"title","preview","subject_id","subject_name","starred","archived","messages","tokens","updated_at"}
            u = {k: v for k, v in updates.items() if k in allowed}
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
    await ensure_seeded()
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
    token = create_token({"sub": user_id})
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
        max_age=JWT_EXPIRE_MINUTES * 60,
    )
    return TokenOut(access_token=token, user=user_out)

@api.post("/auth/login", response_model=TokenOut)
async def login(data: UserLogin, response: Response):
    await ensure_seeded()
    user = await supa_get_user(data.email.lower())
    if not user or not pwd_ctx.verify(data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Account banned")

    credits_info = await get_user_credits(user)
    token = create_token({"sub": user["id"]})
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
        max_age=JWT_EXPIRE_MINUTES * 60,
    )
    return TokenOut(access_token=token, user=user_out)

@api.post("/auth/reset-request")
async def reset_request(data: PasswordResetReq):
    user = await supa_get_user_for_reset(data.email.lower())
    if user:
        token = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        await supa_create_password_reset(token, data.email.lower(), expires)
        logger.info(f"Password reset token for {data.email}: {token}")
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
@api.get("/content/library-bundle")
async def get_library_bundle(nocache: Optional[str] = None):
    if not nocache:
        cached = _get_content_cache("library-bundle")
        if cached: return cached
    await ensure_seeded()
    try:
        if not await is_mongo_available():
            return {"boards": [], "classes": [], "streams": [], "subjects": []}
        boards_data = await db.boards.find({}, {"_id": 0}).to_list(100)
        classes_data = await db.classes.find({}, {"_id": 0}).to_list(100)
        streams_data = await db.streams.find({}, {"_id": 0}).to_list(100)
        subjects_data = await db.subjects.find({"status": "published"}, {"_id": 0}).to_list(500)
        for s in subjects_data:
            if "thumbnail_url" in s and "thumbnailUrl" not in s:
                s["thumbnailUrl"] = s.pop("thumbnail_url")
        bundle = {"boards": boards_data, "classes": classes_data, "streams": streams_data, "subjects": subjects_data}
        _set_content_cache("library-bundle", bundle)
        return bundle
    except Exception:
        return {"boards": [], "classes": [], "streams": [], "subjects": []}

@api.get("/content/boards")
async def get_boards(nocache: Optional[str] = None):
    if not nocache:
        cached = _get_content_cache("boards")
        if cached: return cached
    await ensure_seeded()
    try:
        if not await is_mongo_available():
            return []
        boards = await db.boards.find({}, {"_id": 0}).to_list(100)
        _set_content_cache("boards", boards)
        return boards
    except Exception:
        return []

@api.get("/content/classes")
async def get_classes(board_id: Optional[str] = None, nocache: Optional[str] = None):
    ck = f"classes:{board_id or 'all'}"
    if not nocache:
        cached = _get_content_cache(ck)
        if cached: return cached
    await ensure_seeded()
    try:
        if not await is_mongo_available():
            return []
        query = {"board_id": board_id} if board_id else {}
        classes = await db.classes.find(query, {"_id": 0}).to_list(100)
        _set_content_cache(ck, classes)
        return classes
    except Exception:
        return []

@api.get("/content/streams")
async def get_streams(class_id: Optional[str] = None, nocache: Optional[str] = None):
    ck = f"streams:{class_id or 'all'}"
    if not nocache:
        cached = _get_content_cache(ck)
        if cached: return cached
    await ensure_seeded()
    try:
        if not await is_mongo_available():
            return []
        query = {"class_id": class_id} if class_id else {}
        streams = await db.streams.find(query, {"_id": 0}).to_list(100)
        _set_content_cache(ck, streams)
        return streams
    except Exception:
        return []

@api.get("/content/subjects")
async def get_subjects(stream_id: Optional[str] = None, class_id: Optional[str] = None, nocache: Optional[str] = None):
    ck = f"subjects:{stream_id or ''}:{class_id or ''}"
    if not nocache:
        cached = _get_content_cache(ck)
        if cached: return cached
    await ensure_seeded()
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
        return subjects
    except Exception:
        return []

@api.get("/content/resolve-subject/{board_slug}/{class_slug}/{stream_slug}/{subject_slug}")
async def resolve_subject(board_slug: str, class_slug: str, stream_slug: str, subject_slug: str):
    ck = f"resolve:{board_slug}:{class_slug}:{stream_slug}:{subject_slug}"
    cached = _get_content_cache(ck)
    if cached: return cached
    await ensure_seeded()
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
    return result

@api.get("/content/subjects/{subject_id}")
async def get_subject(subject_id: str):
    ck = f"subject:{subject_id}"
    cached = _get_content_cache(ck)
    if cached: return cached
    await ensure_seeded()
    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")
    subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found")
    if "thumbnail_url" in subj and "thumbnailUrl" not in subj:
        subj["thumbnailUrl"] = subj.pop("thumbnail_url")
    _set_content_cache(ck, subj)
    return subj

# ── Document endpoints (upload / read / delete) ─────────────────────────────

@api.get("/content/subjects/{subject_id}/document")
async def get_subject_document(subject_id: str):
    """Return document/chapters for a subject - checks multiple sources"""
    await ensure_seeded()
    
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
async def get_chapters(subject_id: str):
    ck = f"chapters:{subject_id}"
    cached = _get_content_cache(ck)
    if cached: return cached
    await ensure_seeded()
    try:
        if not await is_mongo_available():
            return []
        chapters = await db.chapters.find({"subject_id": subject_id}, {"_id": 0}).sort("order_index", 1).to_list(100)
        _set_content_cache(ck, chapters)
        return chapters
    except Exception:
        return []

@api.get("/content/chunks/{chapter_id}")
async def get_chunks(chapter_id: str):
    ck = f"chunks:{chapter_id}"
    cached = _get_content_cache(ck)
    if cached: return cached
    await ensure_seeded()
    try:
        if not await is_mongo_available():
            return []
        chunks = await db.chunks.find({"chapter_id": chapter_id}, {"_id": 0}).to_list(200)
        _set_content_cache(ck, chunks)
        return chunks
    except Exception:
        return []

@api.get("/content/search")
async def search_content(q: str):
    await ensure_seeded()
    if len(q) < 2:
        return []
    try:
        if not await is_mongo_available():
            return []
        ck = f"search:{q.lower().strip()}"
        cached = _get_content_cache(ck)
        if cached: return cached
        regex = re.compile(q, re.IGNORECASE)
        subjects = await db.subjects.find(
            {"$or": [{"name": regex}, {"description": regex}, {"tags": regex}], "status": "published"},
            {"_id": 0}
        ).to_list(20)
        _set_content_cache(ck, subjects)
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
    await ensure_seeded()
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

# ─────────────────────────────────────────────
# AI CHAT ROUTES
# ─────────────────────────────────────────────
@api.post("/ai/chat")
async def chat(msg: ChatMessage, user: dict = Depends(rate_limit_chat)):
    await ensure_seeded()
    credits_info = await get_user_credits(user)
    if credits_info["remaining"] <= 0:
        raise HTTPException(status_code=402, detail=f"Credit limit reached ({credits_info['limit']} lifetime credits). Upgrade your plan for more.")

    plan = user.get("plan", "free")
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]

    # ── Tier 0: fetch uploaded document if document_id is provided ────────────
    document_text: Optional[str] = None
    if msg.document_id:
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        if subj and subj.get("document_text"):
            document_text = subj["document_text"]
            logger.info(f"Chat [NON-STREAM]: Tier 0 doc loaded from subject {msg.document_id}")

    # ── Fetch syllabus (stream-specific → board+class fallback) ─────────────
    syllabus = None
    if msg.board_id and msg.class_id:
        try:
            stream_id = getattr(msg, 'stream_id', None)
            if stream_id:
                syllabus = await db.syllabi.find_one({"board_id": msg.board_id, "class_id": msg.class_id, "stream_id": stream_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Stream syllabus loaded for {msg.board_id}/{msg.class_id}/{stream_id}")
            if not syllabus:
                syllabus = await db.syllabi.find_one({"board_id": msg.board_id, "class_id": msg.class_id, "stream_id": {"$exists": False}}, {"_id": 0})
                if not syllabus:
                    syllabus = await db.syllabi.find_one({"board_id": msg.board_id, "class_id": msg.class_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Board+class syllabus loaded for {msg.board_id}/{msg.class_id}")
        except Exception as e:
            logger.error(f"Failed to fetch syllabus: {e}")

    # ── RAG → Web priority chain ──────────────────────────────────────────────
    rag_ctx = await resolve_rag_context(
        msg.message,
        subject_id=msg.subject_id,
        subject_name=msg.subject_name,
        document_text=document_text,
    )

    # ── Build RAG-enriched system prompt ─────────────────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name": msg.board_name,
            "class_name": msg.class_name,
            "stream_name": getattr(msg, 'stream_name', ''),
            "subject_name": msg.subject_name,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        user.get("name", ""),
            "board_name":  user.get("board_name",  msg.board_name  or ""),
            "class_name":  user.get("class_name",  msg.class_name  or ""),
            "stream_name": user.get("stream_name", getattr(msg, 'stream_name', '') or ""),
            "plan":        user.get("plan", "free"),
        },
        query=msg.message,
        syllabus=syllabus,
    )

    conv_id = msg.conversation_id
    history_messages = []

    if conv_id:
        conv = await supa_get_conversation(conv_id, user["id"])
        if conv:
            for m in conv.get("messages", [])[-6:]:
                history_messages.append({"role": m["role"], "content": m["content"]})
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
    cache_key = _cache_key(msg.message)
    is_casual = _classify_question(msg.message) == "casual"
    answer = None

    if not is_casual:
        answer = _redis_get_ai_cache(cache_key)
        if answer:
            logger.info(f"Redis cache HIT: {cache_key}")
        elif cache_key in _ai_response_cache:
            answer = _ai_response_cache[cache_key]
            logger.info(f"Memory cache HIT: {cache_key}")

    if answer is None:
        try:
            answer = await call_llm_api(messages, model=msg.model or LLM_MODEL, max_tokens=max_tokens)
            if not is_casual:
                _redis_set_ai_cache(cache_key, answer)
                _ai_response_cache[cache_key] = answer
                logger.info(f"Cache MISS → stored: {cache_key}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"AI chat error: {e}")
            raise HTTPException(status_code=503, detail="AI service temporarily unavailable")

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

    # Deduct 1 credit (lifetime, no reset)
    new_used = credits_info["used"] + 1
    await supa_update_user(user["id"], {"credits_used": new_used})

    return {
        "answer": answer,
        "conversation_id": conv_id,
        "credits_remaining": max(0, credits_info["remaining"] - 1),
        "credits_used": new_used,
        "rag_source": rag_ctx.get("source", "none"),
        "rag_chunks_used": len(rag_ctx.get("chunks", [])),
    }

@api.post("/ai/chat/stream")
async def chat_stream(msg: ChatMessage, user: dict = Depends(rate_limit_chat)):
    await ensure_seeded()
    credits_info = await get_user_credits(user)
    if credits_info["remaining"] <= 0:
        raise HTTPException(status_code=402, detail=f"Credit limit reached ({credits_info['limit']} lifetime credits). Upgrade your plan for more.")

    plan = user.get("plan", "free")
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]

    # ── Phase 1: document + syllabus in parallel ──────────────────────────────
    async def _fetch_doc():
        if not msg.document_id:
            return None
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        return (subj or {}).get("document_text")

    async def _fetch_syllabus():
        if not (msg.board_id and msg.class_id):
            return None
        try:
            sid = getattr(msg, 'stream_id', None)
            if sid:
                s = await db.syllabi.find_one({"board_id": msg.board_id, "class_id": msg.class_id, "stream_id": sid}, {"_id": 0})
                if s:
                    return s
            s = await db.syllabi.find_one({"board_id": msg.board_id, "class_id": msg.class_id, "stream_id": {"$exists": False}}, {"_id": 0})
            if not s:
                s = await db.syllabi.find_one({"board_id": msg.board_id, "class_id": msg.class_id}, {"_id": 0})
            return s
        except Exception:
            return None

    document_text, syllabus = await asyncio.gather(_fetch_doc(), _fetch_syllabus())

    # ── Phase 2: RAG + conversation history in parallel ───────────────────────
    async def _fetch_history():
        if not msg.conversation_id:
            return None
        return await supa_get_conversation(msg.conversation_id, user["id"])

    rag_ctx, raw_conv = await asyncio.gather(
        resolve_rag_context(msg.message, subject_id=msg.subject_id,
                            subject_name=msg.subject_name, document_text=document_text),
        _fetch_history(),
    )

    # ── Build prompt ───────────────────────────────────────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name": msg.board_name,
            "class_name": msg.class_name,
            "stream_name": getattr(msg, 'stream_name', ''),
            "subject_name": msg.subject_name,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        user.get("name", ""),
            "board_name":  user.get("board_name",  msg.board_name  or ""),
            "class_name":  user.get("class_name",  msg.class_name  or ""),
            "stream_name": user.get("stream_name", getattr(msg, 'stream_name', '') or ""),
            "plan":        user.get("plan", "free"),
        },
        query=msg.message,
        syllabus=syllabus,
    )

    conv_id = msg.conversation_id
    history_messages = []

    if conv_id and raw_conv:
        for m in raw_conv.get("messages", [])[-6:]:
            history_messages.append({"role": m["role"], "content": m["content"]})
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
        await supa_upsert_conversation(conv_doc)

    messages_payload = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": msg.message}]

    user_msg_saved   = msg.message
    rag_source_saved = rag_ctx.get("source",  "none")
    rag_quality_saved = rag_ctx.get("quality", "none")
    rag_chunks_count = len(rag_ctx.get("chunks",   []))
    rag_subjects_count = len(rag_ctx.get("subjects", []))
    full_response = []

    async def event_stream():
        nonlocal full_response
        # Send RAG metadata with full quality info
        yield f"data: {json.dumps({'conversation_id': conv_id, 'rag_source': rag_source_saved, 'rag_quality': rag_quality_saved, 'rag_chunks': rag_chunks_count, 'rag_subjects': rag_subjects_count})}\n\n"

        # ── Cache check (Streaming) — Redis first, in-memory fallback ────────
        cache_key = _cache_key(msg.message)
        is_casual = _classify_question(msg.message) == "casual"
        cached_answer = None

        if not is_casual:
            cached_answer = _redis_get_ai_cache(cache_key)
            if cached_answer:
                logger.info(f"Redis cache HIT (STREAM): {cache_key}")
            elif cache_key in _ai_response_cache:
                cached_answer = _ai_response_cache[cache_key]
                logger.info(f"Memory cache HIT (STREAM): {cache_key}")

        if cached_answer:
            yield f"data: {json.dumps({'content': cached_answer})}\n\n"
            full_response.append(cached_answer)
        else:
            async for chunk in call_llm_api_stream(messages_payload, model=msg.model or LLM_MODEL, max_tokens=max_tokens):
                if '"content"' in chunk:
                    try:
                        data = json.loads(chunk[6:])
                        full_response.append(data.get("content", ""))
                    except:
                        pass
                yield chunk

            if not is_casual and full_response:
                answer_str = "".join(full_response)
                if answer_str:
                    _redis_set_ai_cache(cache_key, answer_str)
                    _ai_response_cache[cache_key] = answer_str
                    logger.info(f"Cache MISS → stored (STREAM): {cache_key}")

        # Persist conversation after stream ends
        answer = "".join(full_response)
        new_used = credits_info["used"]
        if answer:
            now = datetime.now(timezone.utc).isoformat()
            new_msgs = [
                {"role": "user", "content": user_msg_saved, "timestamp": now},
                {"role": "assistant", "content": answer, "timestamp": now,
                 "rag_source": rag_source_saved, "rag_chunks": rag_chunks_count},
            ]
            # Update conversation in Supabase
            conv = await supa_get_conversation(conv_id, user["id"])
            if conv:
                existing = conv.get("messages", [])
                if isinstance(existing, str):
                    try: existing = json.loads(existing)
                    except: existing = []
                updated = existing + new_msgs
                await supa_update_conversation(conv_id, user["id"], {
                    "messages": json.dumps(updated) if supa else updated,
                    "updated_at": now,
                    "preview": answer[:100],
                    "tokens": len(answer.split()),
                })
            # Deduct credit (lifetime)
            new_used = credits_info["used"] + 1
            await supa_update_user(user["id"], {"credits_used": new_used})

        # ── syrabit_done event with credits metadata ─────────────────────
        done_payload = {
            "event": "syrabit_done",
            "conversation_id": conv_id,
            "credits_used": 1,
            "credits_used_total": new_used,
            "remaining_credits": max(0, credits_info["remaining"] - 1),
            "rag_source": rag_source_saved,
            "rag_chunks": rag_chunks_count,
            "words": len(answer.split()),
        }
        yield f"data: {json.dumps(done_payload)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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
    # Get conversations from Supabase
    convs = await supa_get_conversations(user["id"])
    conv_count = len(convs) if convs else 0
    saved_count = len(user.get("saved_subjects", []))
    # Estimate tokens from credits_used (rough: 1 credit ≈ 300 tokens)
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
    await ensure_seeded()

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
        expires_delta=60 * 8,   # 8-hour session
    )
    response.set_cookie(
        key="syrabit_admin_session",
        value=token,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=60 * 8 * 60,
    )
    return {
        "access_token": token,
        "token_type":   "bearer",
        "email":        matched["email"],
        "name":         matched["name"],
    }

@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="syrabit_session", samesite=COOKIE_SAMESITE, secure=SECURE_COOKIES)
    return {"message": "Logged out"}

@api.post("/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie(key="syrabit_admin_session", samesite=COOKIE_SAMESITE, secure=SECURE_COOKIES)
    return {"message": "Logged out"}

@api.get("/admin/verify")
async def admin_verify(admin: dict = Depends(get_admin_user)):
    return {"valid": True, "email": admin.get("email"), "name": admin.get("name", "Admin")}

# ─────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────
@api.get("/admin/dashboard")
async def admin_dashboard(admin: dict = Depends(get_admin_user)):
    await ensure_seeded()
    total_users = await supa_count_users()
    total_convs = await supa_count_conversations()
    all_convs = await supa_get_all_conversations(1000)
    total_messages = sum(len(c.get("messages", [])) for c in all_convs)
    try:
        total_subjects = await db.subjects.count_documents({}) if await is_mongo_available() else 0
    except Exception:
        total_subjects = 0
    users = await supa_list_users()
    plan_dist = {}
    for u in users:
        p = u.get("plan", "free")
        plan_dist[p] = plan_dist.get(p, 0) + 1
    return {
        "total_users": total_users,
        "total_conversations": total_convs,
        "total_messages": total_messages,
        "total_subjects": total_subjects,
        "plan_distribution": plan_dist,
    }

@api.get("/admin/users")
async def admin_get_users(admin: dict = Depends(get_admin_user)):
    users = await supa_list_users()
    result = []
    for u in users:
        u.pop("password_hash", None)
        credits_info = await get_user_credits(u)
        result.append({**u, "credits_used": credits_info["used"], "credits_limit": credits_info["limit"]})
    return result

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
    new_credits = user.get("credits_used", 0) + data.credits_delta
    await supa_update_user(user_id, {"credits_used": max(0, new_credits)})
    return {"message": "Credits updated"}

@api.get("/admin/conversations")
async def admin_get_conversations(admin: dict = Depends(get_admin_user)):
    convs = await supa_get_all_conversations(200)
    user_ids = list({c.get("user_id") for c in convs if c.get("user_id")})
    users_map = {}
    if user_ids:
        users = await supa_get_users_by_ids(user_ids)
        users_map = {u["id"]: u for u in users}
    for c in convs:
        uid = c.get("user_id")
        u = users_map.get(uid, {})
        c["user_name"] = u.get("name", "")
        c["user_email"] = u.get("email", c.get("user_email", ""))
        c["user_plan"] = u.get("plan", "free")
        c["user_avatar"] = u.get("avatar_url", "")
        c["user_board"] = u.get("board_name", "")
        c["user_class"] = u.get("class_name", "")
        c["user_stream"] = u.get("stream_name", "")
    return convs

@api.get("/admin/analytics")
async def admin_analytics(days: int = 30, admin: dict = Depends(get_admin_user)):
    """
    Enhanced admin analytics dashboard with library interaction tracking
    
    Query params:
    - days: Number of days to look back (default: 30)
    """
    await ensure_seeded()
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
    
    # Library analytics
    library_stats = await get_library_analytics(days=days)
    
    return {
        "daily_signups": daily_signups,
        "plan_usage": plan_usage,
        "library": library_stats,
        "total_users": len(users),
        "active_users": sum(1 for u in users if u.get("credits_used", 0) > 0),
    }


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
# ADMIN CONTENT MANAGEMENT — Subjects
# ─────────────────────────────────────────────
@api.post("/admin/content/subjects")
async def admin_create_subject(data: SubjectCreate, admin: dict = Depends(get_admin_user)):
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable - cannot create content")
        await ensure_seeded()
        
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
    chap = {
        "id": chapter_id,
        "subject_id": data.subject_id,
        "title": data.title,
        "description": data.description,
        "content": data.content,
        "chapter_number": data.chapter_number,
        "order": data.order or data.order_index or 1,
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
This chapter covers fundamental concepts and provides a strong foundation for understanding {subject.get('name', 'this subject')}. We'll explore key definitions, important principles, and practical applications that are crucial for AHSEC Class 11-12 students.

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
    allowed = {k: v for k, v in data.items() if k in ["title", "description", "content", "order", "status"]}
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
    update = {k: v for k, v in data.dict().items() if v is not None}
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
        "audience": data.get("audience", "all"),
        "status": data.get("status", "draft"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sent_at": datetime.now(timezone.utc).isoformat() if data.get("status") == "sent" else None,
    }
    await supa_insert_notification(notif)
    return notif

@api.delete("/admin/notifications/{notif_id}")
async def admin_delete_notification(notif_id: str, admin: dict = Depends(get_admin_user)):
    await supa_delete_notification(notif_id)
    return {"message": "Deleted"}

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

# ─────────────────────────────────────────────
# API CONFIG
# ─────────────────────────────────────────────
DEFAULT_API_CONFIG = {
    "groq":        {"key": ""},
    "payment":     {"razorpay_key_id": "", "razorpay_key_secret": ""},
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

class CMSDocument(BaseModel):
    title: str
    content: str
    meta_description: Optional[str] = ""  # 160 char SEO description
    description: Optional[str] = ""  # Long description (2000 char)
    seo_tags: Optional[str] = ""
    primary_keyword: Optional[str] = ""
    seo_slug: Optional[str] = ""
    thumbnail_url: Optional[str] = ""
    alt_text: Optional[str] = ""
    category: Optional[str] = ""  # e.g., ahsec/class12/pcm/physics
    headings: Optional[str] = ""  # JSON string of extracted headings
    status: str = "draft"

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
    """Create new SEO-optimized CMS document"""
    doc_id = str(uuid.uuid4())
    word_count = len(doc.content.split())
    now = datetime.now(timezone.utc).isoformat()
    
    doc_data = {
        "id": doc_id,
        "title": doc.title,
        "content": doc.content,
        "meta_description": doc.meta_description,
        "description": doc.description,
        "seo_tags": doc.seo_tags,
        "primary_keyword": doc.primary_keyword,
        "seo_slug": doc.seo_slug,
        "thumbnail_url": doc.thumbnail_url,
        "alt_text": doc.alt_text,
        "category": doc.category,
        "headings": doc.headings,
        "status": doc.status,
        "word_count": word_count,
        "rag_processed": False,
        "created_at": now,
        "updated_at": now,
        "created_by": admin.get("email"),
    }
    
    await db.cms_documents.insert_one(doc_data)
    return doc_data

@api.patch("/admin/content/cms-documents/{doc_id}")
async def update_cms_document(doc_id: str, doc: CMSDocument, admin: dict = Depends(get_admin_user)):
    """Update existing SEO-optimized CMS document"""
    word_count = len(doc.content.split())
    updates = {
        "title": doc.title,
        "content": doc.content,
        "meta_description": doc.meta_description,
        "description": doc.description,
        "seo_tags": doc.seo_tags,
        "primary_keyword": doc.primary_keyword,
        "seo_slug": doc.seo_slug,
        "thumbnail_url": doc.thumbnail_url,
        "alt_text": doc.alt_text,
        "category": doc.category,
        "headings": doc.headings,
        "status": doc.status,
        "word_count": word_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    result = await db.cms_documents.update_one({"id": doc_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    
    updated = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    return updated

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
async def upload_image(file: bytes = File(...), admin: dict = Depends(get_admin_user)):
    """Upload image to Supabase Storage"""
    # For now, return a placeholder. Full Supabase Storage implementation can be added later.
    # This is a stub that returns a data URL or external URL
    import base64
    image_id = str(uuid.uuid4())[:8]
    # In production, upload to Supabase Storage bucket
    # For MVP, we'll use a placeholder
    return {"url": f"https://via.placeholder.com/400x300?text={image_id}"}

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
    """Get single CMS document for public view"""
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

@api.post("/admin/content/regenerate-sitemap")
async def regenerate_sitemap(admin: dict = Depends(get_admin_user)):
    """Regenerate sitemap.xml with all published CMS documents"""
    try:
        docs = await db.cms_documents.find(
            {"status": "published"},
            {"_id": 0, "seo_slug": 1, "category": 1, "updated_at": 1}
        ).to_list(1000)
        
        sitemap_entries = []
        for doc in docs:
            url_path = f"/library/{doc.get('category', '')}/{doc.get('seo_slug', doc['id'])}".replace('//', '/')
            sitemap_entries.append({
                "url": url_path,
                "lastmod": doc.get("updated_at", ""),
                "priority": "0.8"
            })
        
        logger.info(f"Sitemap regenerated: {len(sitemap_entries)} CMS documents")
        return {"message": f"Sitemap generated with {len(sitemap_entries)} documents", "count": len(sitemap_entries)}
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

@api.get("/ready")
async def readiness():
    return {"status": "ok"}

@api.get("/health")
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

    return {
        "status": "ok",
        "version": "2.0.0",
        "service": "Syrabit.ai API",
        "workers": int(os.environ.get("GUNICORN_WORKERS", 3)),
        "uptime_seconds": int(_time_mod.time() - _startup_time),
        "dependencies": {
            "mongodb": {"status": mongo_status, "latencyMs": kv_latency},
            "redis": {"status": "ok" if redis_ok else "not_connected"},
            "llm": {
                "status": "ok" if OPENAI_API_KEY else "not_configured",
                "provider": LLM_PROVIDER,
                "model": LLM_MODEL,
                "providers": [p["provider"] for p in _LLM_PROVIDERS],
                "fallback": len(_LLM_PROVIDERS) > 1,
            },
            "supabase": {"status": "ok" if supa else "not_configured"},
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

@api.get("/")
async def root():
    return {"message": "Syrabit.ai API", "version": "1.0.0"}

# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────
from seo_engine import router as seo_router, init_seo_engine
init_seo_engine(db, call_llm_api, get_admin_user)
api.include_router(seo_router)

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

app.include_router(api)

app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=_CORS_ALLOW_CREDENTIALS,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
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

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = FRONTEND_BUILD / full_path
        if full_path and file_path.is_file():
            if full_path in ("sw.js", "index.html"):
                return FileResponse(str(file_path), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_BUILD / "index.html"),
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

# ─────────────────────────────────────────────
# STANDALONE
# ─────────────────────────────────────────────
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
