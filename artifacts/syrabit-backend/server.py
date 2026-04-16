"""
Syrabit.ai Backend - FastAPI + MongoDB
AHSEC AI-Powered Educational Platform

Thin entry point: creates the app, mounts middleware, and includes all route modules.
"""
import os, sys, json, uuid, logging, asyncio, fcntl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException as _StarletteHTTPException
from pydantic import ValidationError as _PydanticValidationError
from fastapi.exceptions import RequestValidationError as _RequestValidationError


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
        try:
            from middleware import request_id_var
            rid = request_id_var.get("")
            if rid:
                log_entry["request_id"] = rid
        except Exception:
            pass
        if hasattr(record, "request_id") and record.request_id:
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

    _llm_keys = {
        "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", "").strip(),
        "GROQ_API_KEY_2": os.environ.get("GROQ_API_KEY_2", "").strip(),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "").strip(),
        "GEMINI_API_KEY_2": os.environ.get("GEMINI_API_KEY_2", "").strip(),
        "XAI_API_KEY": os.environ.get("XAI_API_KEY", "").strip(),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "").strip(),
        "SARVAM_API_KEY": os.environ.get("SARVAM_API_KEY", "").strip(),
        "CEREBRAS_API_KEY": os.environ.get("CEREBRAS_API_KEY", "").strip(),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "").strip(),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", "").strip(),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip(),
    }
    _log.info("─── LLM Provider Key Diagnostic ───")
    for name, val in _llm_keys.items():
        status = "SET" if val else "NOT SET"
        _log.info(f"  {name}: {status}")
    _log.info("───────────────────────────────────")


_validate_env()

from config import ROOT_DIR, CORS_ORIGINS, CORS_ORIGIN_REGEX, _CORS_ALLOW_CREDENTIALS
import deps
from deps import (
    db, supa, sarvam_client, sarvam_translate_client, sarvam_llm_client,
    sarvam_client_direct, sarvam_llm_client_direct,
    mongo_client, logger, _rate_cleanup_task, _init_pg_pool,
    is_mongo_available,
)
from auth_deps import _rate_limiter_cleanup
from seed import ensure_seeded
from db_ops import _supa, supa_insert_activity_log
from metrics import _bg_health_loop, _alerting_loop

from prompts import build_system_prompt, _classify_question
from syllabus_embedder import SyllabusEmbedder

_syllabus_embedder: Optional[SyllabusEmbedder] = None


async def _migrate_supabase_users_to_pg():
    """One-time background task: copy all Supabase users into PG (upsert, safe to re-run)."""
    if not deps.pg_pool or not supa:
        return
    await asyncio.sleep(2)
    t0 = asyncio.get_event_loop().time()
    try:
        r = await _supa(lambda: supa.table("users").select("*").order("created_at", desc=False).limit(2000).execute())
        users = r.data or []
        if not users:
            logger.info("[migration] Supabase→PG: no users to migrate")
            return
        _insert_sql = """INSERT INTO users (id, name, email, password_hash, plan, credits_used,
                   credits_limit, document_access, onboarding_done, is_admin, status,
                   bio, phone, avatar_url, saved_subjects, has_free_credits_issued,
                   board_id, board_name, class_id, class_name, stream_id, stream_name,
                   created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16,$17,$18,$19,$20,$21,$22,$23)
                   ON CONFLICT (id) DO NOTHING"""
        imported = 0
        async with deps.pg_pool.acquire() as conn:
            for u in users:
                try:
                    await conn.execute(
                        _insert_sql,
                        u.get("id"), u.get("name",""), u.get("email","").lower(), u.get("password_hash",""),
                        u.get("plan","free"), u.get("credits_used",0) or 0, u.get("credits_limit",30) or 30,
                        u.get("document_access","zero"), bool(u.get("onboarding_done",False)),
                        bool(u.get("is_admin",False)), u.get("status","active") or "active",
                        u.get("bio","") or "", u.get("phone","") or "", u.get("avatar_url","") or "",
                        json.dumps(u.get("saved_subjects") or []), bool(u.get("has_free_credits_issued",True)),
                        u.get("board_id"), u.get("board_name"), u.get("class_id"),
                        u.get("class_name"), u.get("stream_id"), u.get("stream_name"),
                        u.get("created_at"),
                    )
                    imported += 1
                except Exception:
                    pass
        elapsed = int((asyncio.get_event_loop().time() - t0) * 1000)
        logger.info(f"[migration] Supabase→PG: processed {len(users)} users, inserted {imported} new rows in {elapsed}ms")
    except Exception as e:
        logger.warning(f"[migration] Supabase→PG migration failed: {e}")


async def _heal_credits_limit():
    if not deps.pg_pool:
        return
    await asyncio.sleep(8)
    try:
        async with deps.pg_pool.acquire() as conn:
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


async def _migrate_consent_columns():
    if not deps.pg_pool:
        return
    try:
        async with deps.pg_pool.acquire() as conn:
            await conn.execute(
                """DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='consent_dpdp') THEN
                        ALTER TABLE users ADD COLUMN consent_dpdp BOOLEAN DEFAULT FALSE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='consent_dpdp_version') THEN
                        ALTER TABLE users ADD COLUMN consent_dpdp_version TEXT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='consent_dpdp_at') THEN
                        ALTER TABLE users ADD COLUMN consent_dpdp_at TEXT;
                    END IF;
                END $$;"""
            )
        logger.info("[migration] consent_dpdp columns ensured")
    except Exception as e:
        logger.warning(f"[migration] consent columns migration failed: {e}")


async def _load_ga4_from_db():
    try:
        if not os.getenv("GA4_REFRESH_TOKEN"):
            cfg = await db.api_config.find_one({}, {"ga4": 1})
            token = (cfg or {}).get("ga4", {}).get("refresh_token", "")
            if token:
                os.environ["GA4_REFRESH_TOKEN"] = token
                logger.info("GA4 refresh token loaded from db.api_config")
    except Exception as e:
        logger.warning(f"GA4 db-load skipped: {e}")


async def _seed_syllabus_embeddings():
    global _syllabus_embedder
    if _syllabus_embedder is None:
        return
    try:
        inserted = await _syllabus_embedder.ensure_seeded()
        if inserted > 0:
            logger.info(f"SyllabusEmbedder: seeded {inserted} chapter embeddings in background")
    except Exception as exc:
        logger.warning(f"SyllabusEmbedder background seed failed: {exc}")


async def _prewarm_library_cache():
    await asyncio.sleep(3)
    from routes.content import get_library_bundle
    for attempt in range(3):
        try:
            await get_library_bundle(nocache="1", include_seo=None, response=None)
            logger.info("Library-bundle cache pre-warmed")
            return
        except Exception as e:
            logger.warning(f"Library-bundle pre-warm attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))

@asynccontextmanager
async def lifespan(app):
    import deps as _deps_mod
    await _init_pg_pool()

    _is_leader = False
    _lock_fd = None
    try:
        _lock_fd = open("/tmp/.syrabit_startup.lock", "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _is_leader = True
        logger.info("Worker acquired startup lock — running migrations/indexes")
    except (IOError, OSError):
        logger.info("Worker skipping migrations/indexes (another worker owns lock)")

    try:
        if _is_leader:
            await ensure_seeded()
            await db.chapters.create_index("subject_id")
            await db.chapters.create_index("order_index")
            await db.chapters.create_index([("slug", 1), ("subject_id", 1)])
            await db.subjects.create_index("stream_id")
            await db.subjects.create_index("status")
            await db.subjects.create_index([("slug", 1), ("stream_id", 1)])
            await db.boards.create_index("slug")
            await db.classes.create_index([("slug", 1), ("board_id", 1)])
            await db.streams.create_index("class_id")
            await db.classes.create_index("board_id")
            await db.chunks.create_index("chapter_id")
            await db.chunks.create_index("subject_id")
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

            await db.server_hits.create_index([("date", 1), ("is_bot", 1)])
            await db.server_hits.create_index([("ip_hash", 1), ("date", 1)])
            await db.server_hits.create_index([("is_bot", 1), ("ip_hash", 1)])
            await db.server_hits.create_index([("is_bot", 1), ("ip_hash_stable", 1)])
            await db.server_hits.create_index([("is_bot", 1), ("bot_name", 1)])
            await db.server_hits.create_index([("timestamp", -1)])

            try:
                from middleware import _SERVER_BOT_RE
                from pymongo import UpdateOne
                empty_bot_cursor = db.server_hits.find(
                    {"is_bot": True, "$or": [{"bot_name": ""}, {"bot_name": {"$exists": False}}]},
                    {"_id": 1, "user_agent": 1},
                )
                _batch = []
                _total_backfilled = 0
                _BATCH_SIZE = 500
                async for doc in empty_bot_cursor:
                    ua = doc.get("user_agent", "")
                    m = _SERVER_BOT_RE.search(ua) if ua else None
                    name = m.group(0).lower() if m else "unknown"
                    _batch.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"bot_name": name}}))
                    if len(_batch) >= _BATCH_SIZE:
                        await db.server_hits.bulk_write(_batch)
                        _total_backfilled += len(_batch)
                        _batch = []
                if _batch:
                    await db.server_hits.bulk_write(_batch)
                    _total_backfilled += len(_batch)
                if _total_backfilled:
                    logger.info(f"Backfilled bot_name for {_total_backfilled} server_hits records")
            except Exception as e:
                logger.warning(f"bot_name backfill skipped: {e}")

            try:
                from utils import slugify_title as _slugify_title
                from pymongo import UpdateOne as _SlugUpdateOne
                _slug_cursor = db.chapters.find(
                    {"$or": [{"slug": ""}, {"slug": {"$exists": False}}, {"slug": None}]},
                    {"_id": 1, "title": 1},
                )
                _slug_batch = []
                _slug_total = 0
                async for doc in _slug_cursor:
                    title = doc.get("title", "")
                    if not title:
                        continue
                    generated = _slugify_title(title)
                    if generated:
                        _slug_batch.append(_SlugUpdateOne({"_id": doc["_id"]}, {"$set": {"slug": generated}}))
                    if len(_slug_batch) >= 500:
                        await db.chapters.bulk_write(_slug_batch)
                        _slug_total += len(_slug_batch)
                        _slug_batch = []
                if _slug_batch:
                    await db.chapters.bulk_write(_slug_batch)
                    _slug_total += len(_slug_batch)
                if _slug_total:
                    logger.info(f"Backfilled slug for {_slug_total} chapters")
            except Exception as e:
                logger.warning(f"chapter slug backfill skipped: {e}")

            await db.users.create_index("email", unique=True, sparse=True)
            await db.users.create_index("id", unique=True)
            await db.password_resets.create_index("token", unique=True)
            await db.password_resets.create_index("expires_at", expireAfterSeconds=0)
            await db.activity_log.create_index([("created_at", -1)])
            await db.notifications.create_index([("created_at", -1)])
            await db.settings.create_index("id", unique=True, sparse=True)

            await db.syllabi.create_index([("board_id", 1), ("class_id", 1)])
            await db.syllabi.create_index([("board_id", 1), ("class_id", 1), ("stream_id", 1)])
            await db.syllabi.create_index([("board_id", 1), ("class_id", 1), ("stream_id", 1), ("subject_id", 1)])

            await db.analytics_daily_totals.create_index([("date", 1), ("source", 1)], unique=True)

            await db.indexnow_push_log.create_index(
                "pushed_at", expireAfterSeconds=90 * 24 * 3600,
                name="pushed_at_ttl_90d",
            )
            await db.indexnow_push_log.create_index(
                [("source", 1), ("pushed_at", -1)],
                name="source_pushed_at",
            )

            await db.indexnow_endpoint_health.create_index(
                "endpoint", unique=True, name="endpoint_unique",
            )

            await db.bot_spoof_attempts.create_index(
                [("date", 1), ("claimed_bot", 1)],
                name="date_claimed_bot",
            )
            await db.bot_spoof_attempts.create_index(
                [("ip_hash", 1), ("date", 1)],
                name="ip_hash_date",
            )
            await db.bot_spoof_attempts.create_index(
                "timestamp", expireAfterSeconds=90 * 24 * 3600,
                name="timestamp_ttl_90d",
            )

            try:
                await db.chapters.create_index(
                    [("title", "text"), ("content", "text")],
                    name="chapters_content_text",
                    weights={"title": 10, "content": 1},
                )
            except Exception:
                pass

            logger.info("MongoDB indexes ensured")

    except Exception as e:
        logger.warning(f"Seeding/indexing skipped (MongoDB may not be ready): {e}")
    if _is_leader:
        try:
            from qa_engine import ensure_qa_indexes as _ensure_qa_indexes
            await _ensure_qa_indexes()
        except Exception as e:
            logger.warning(f"QA index creation skipped: {e}")
    try:
        from routes.bot_discovery import load_endpoint_health_from_db
        await load_endpoint_health_from_db()
    except Exception as _eh_err:
        logger.warning("IndexNow endpoint health load skipped: %s", _eh_err)
    _deps_mod._rate_cleanup_task = asyncio.create_task(_rate_limiter_cleanup())
    if _is_leader:
        asyncio.create_task(_migrate_supabase_users_to_pg())
        asyncio.create_task(_heal_credits_limit())
        try:
            await asyncio.wait_for(_migrate_consent_columns(), timeout=10)
        except Exception as _mc_err:
            logger.warning(f"consent columns migration deferred: {_mc_err}")
    asyncio.create_task(_bg_health_loop())
    asyncio.create_task(_prewarm_library_cache())
    global _syllabus_embedder
    if db is not None:
        _syllabus_embedder = SyllabusEmbedder(db)
        if _is_leader:
            asyncio.create_task(_seed_syllabus_embeddings())
    asyncio.create_task(_load_ga4_from_db())
    from routes.admin_notifications import _exam_reminder_loop
    asyncio.create_task(_exam_reminder_loop())
    asyncio.create_task(_alerting_loop())
    logger.info("Syrabit.ai API started")
    if sarvam_client:
        logger.info("Sarvam AI client ready")
    yield
    if _deps_mod._rate_cleanup_task:
        _deps_mod._rate_cleanup_task.cancel()
    if sarvam_client:
        await sarvam_client.aclose()
    if sarvam_translate_client:
        await sarvam_translate_client.aclose()
    if sarvam_llm_client:
        await sarvam_llm_client.aclose()
    if sarvam_client_direct:
        await sarvam_client_direct.aclose()
    if sarvam_llm_client_direct:
        await sarvam_llm_client_direct.aclose()
    try:
        from ga4_client import _ga4_http
        if _ga4_http:
            await _ga4_http.aclose()
    except Exception:
        pass
    try:
        import vectorize_client
        await vectorize_client.close()
    except Exception:
        pass
    mongo_client.close()
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        except Exception:
            pass


app = FastAPI(title="Syrabit.ai API", version="2.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.exception_handler(_StarletteHTTPException)
async def _starlette_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": True, "status": exc.status_code, "detail": exc.detail, "path": str(request.url.path)},
    )

@app.exception_handler(HTTPException)
async def _http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": True, "status": exc.status_code, "detail": exc.detail, "path": str(request.url.path)},
    )

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": True, "status": 500, "detail": "Internal server error", "path": str(request.url.path)},
    )

@app.exception_handler(_PydanticValidationError)
async def _validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": True, "status": 422, "detail": "Validation error",
            "errors": [{"field": ".".join(str(l) for l in e["loc"]), "message": e["msg"]} for e in exc.errors()],
            "path": str(request.url.path),
        },
    )

@app.exception_handler(_RequestValidationError)
async def _request_validation_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": True, "status": 422, "detail": "Request validation error",
            "errors": [{"field": ".".join(str(l) for l in e["loc"]), "message": e["msg"]} for e in exc.errors()],
            "path": str(request.url.path),
        },
    )


api = APIRouter(prefix="/api")

from routes.auth import router as auth_router
from routes.content import router as content_router
from routes.syllabus import router as syllabus_router
from routes.ai_chat import router as ai_chat_router
from routes.conversations import router as conversations_router
from routes.user import router as user_router
from routes.admin_auth_users import router as admin_auth_users_router
from routes.analytics import router as analytics_router
from routes.admin_content import router as admin_content_router
from routes.admin_pipeline import router as admin_pipeline_router
from routes.admin_settings import router as admin_settings_router
from routes.admin_notifications import router as admin_notifications_router
from routes.admin_monetization import router as admin_monetization_router
from routes.cms_sarvam_health import router as cms_sarvam_health_router
from routes.admin_advanced import router as admin_advanced_router
from routes.admin_benchmark import router as admin_benchmark_router

api.include_router(auth_router)
api.include_router(content_router)
api.include_router(syllabus_router)
api.include_router(ai_chat_router)
api.include_router(conversations_router)
api.include_router(user_router)
api.include_router(admin_auth_users_router)
api.include_router(analytics_router)

api.include_router(admin_content_router)
api.include_router(admin_pipeline_router)
api.include_router(admin_settings_router)
api.include_router(admin_notifications_router)
api.include_router(admin_monetization_router)
api.include_router(cms_sarvam_health_router)
api.include_router(admin_advanced_router)
api.include_router(admin_benchmark_router)

from llm import call_llm_api, call_llm_api_content
from auth_deps import get_admin_user

from seo_engine import router as seo_router, init_seo_engine
init_seo_engine(db, call_llm_api_content, get_admin_user, log_activity_fn=supa_insert_activity_log)
api.include_router(seo_router)

from qa_engine import public_router as qa_public_router, admin_router as qa_admin_router, init_qa_engine, ensure_qa_indexes
init_qa_engine(db, get_admin_user)
api.include_router(qa_public_router)
api.include_router(qa_admin_router)

from routes.bot_discovery import router as bot_discovery_router
api.include_router(bot_discovery_router)

app.include_router(api)

from routes.pyq import router as pyq_router
app.include_router(pyq_router)

@app.get("/robots.txt", response_class=Response)
async def serve_robots_txt():
    txt = """# Syrabit.ai — robots.txt

# ── Search & Answer Bots (welcome) ──────────────────────────────────────
User-agent: Googlebot
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Disallow: /admin/
Disallow: /chat
Disallow: /history
Disallow: /profile
Disallow: /cms/

User-agent: Googlebot-Image
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: GoogleOther
Allow: /

User-agent: Bingbot
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Disallow: /admin/
Disallow: /chat
Disallow: /history
Disallow: /profile
Disallow: /cms/

User-agent: Yandexbot
Allow: /
Allow: /api/seo/
Disallow: /admin/
Disallow: /chat
Disallow: /history
Disallow: /profile

User-agent: DuckDuckBot
Allow: /
Allow: /api/seo/
Disallow: /admin/
Disallow: /chat

User-agent: Applebot
Allow: /
Allow: /api/seo/
Disallow: /admin/
Disallow: /chat

User-agent: Applebot-Extended
Allow: /
Allow: /api/seo/
Disallow: /admin/
Disallow: /chat

# ── AI Search/Answer Bots (send traffic, welcome) ──────────────────────
User-agent: ChatGPT-User
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Allow: /api/content/library-bundle
Allow: /api/content/chapters/
Allow: /llms.txt
Allow: /llms-full.txt
Allow: /feed.xml
Disallow: /admin/
Disallow: /chat
Disallow: /api/auth/
Disallow: /api/ai/
Disallow: /api/admin/

User-agent: OAI-SearchBot
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /admin/
Disallow: /chat
Disallow: /api/auth/
Disallow: /api/ai/

User-agent: PerplexityBot
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Allow: /api/content/library-bundle
Allow: /llms.txt
Allow: /llms-full.txt
Allow: /feed.xml
Disallow: /admin/
Disallow: /chat
Disallow: /api/auth/
Disallow: /api/ai/

User-agent: ClaudeBot
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /admin/
Disallow: /chat
Disallow: /api/auth/
Disallow: /api/ai/

User-agent: Meta-ExternalAgent
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Disallow: /admin/
Disallow: /chat
Disallow: /api/auth/
Disallow: /api/ai/

# ── Training / Scraping Bots (BLOCKED) ──────────────────────────────────
User-agent: GPTBot
Disallow: /

User-agent: CCBot
Disallow: /

User-agent: anthropic-ai
Disallow: /

User-agent: Cohere-ai
Disallow: /

User-agent: Bytespider
Disallow: /

User-agent: PetalBot
Disallow: /

User-agent: Scrapy
Disallow: /

User-agent: AhrefsBot
Disallow: /

User-agent: SemrushBot
Disallow: /

User-agent: MJ12bot
Disallow: /

User-agent: DotBot
Disallow: /

User-agent: Amazonbot
Disallow: /

User-agent: YouBot
Disallow: /

User-agent: Diffbot
Disallow: /

User-agent: img2dataset
Disallow: /

User-agent: omgili
Disallow: /

User-agent: FacebookBot
Disallow: /

# ── Default (all other bots) ────────────────────────────────────────────
User-agent: *
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Allow: /llms.txt
Allow: /llms-full.txt
Allow: /feed.xml
Disallow: /admin/
Disallow: /chat
Disallow: /history
Disallow: /profile
Disallow: /cms/
Disallow: /api/auth/
Disallow: /api/ai/
Disallow: /api/admin/

# ── Sitemaps & Feeds ────────────────────────────────────────────────────
Sitemap: https://syrabit.ai/sitemap.xml
Sitemap: https://syrabit.ai/sitemap-index.xml

# RSS feeds
# https://syrabit.ai/feed.xml
# https://syrabit.ai/feed/notes.xml
# https://syrabit.ai/feed/mcqs.xml
# https://syrabit.ai/feed/blog.xml
# Atom feeds
# https://syrabit.ai/feed/atom.xml
# https://syrabit.ai/feed/notes-atom.xml
# https://syrabit.ai/feed/mcqs-atom.xml
# https://syrabit.ai/feed/blog-atom.xml
"""
    return Response(content=txt.strip(), media_type="text/plain")

@app.get("/ads.txt", response_class=Response)
async def serve_ads_txt():
    txt = "google.com, pub-8958003374183515, DIRECT, f08c47fec0942fa0"
    return Response(content=txt, media_type="text/plain")

@app.get("/", include_in_schema=False)
async def root_redirect(request: Request):
    import re as _rr_re
    _ROOT_BOT_RE = _rr_re.compile(
        r"googlebot|bingbot|yandexbot|slurp|duckduckbot|baiduspider|"
        r"facebookexternalhit|facebookbot|twitterbot|linkedinbot|applebot|"
        r"gptbot|oai-searchbot|chatgpt-user|claudebot|anthropic-ai|perplexitybot",
        _rr_re.IGNORECASE,
    )
    ua = request.headers.get("user-agent", "")
    if _ROOT_BOT_RE.search(ua):
        try:
            _seo_port = int(os.environ.get("PORT", "8000"))
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"http://localhost:{_seo_port}/api/seo/html/homepage")
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                return Response(content=resp.text, media_type="text/html; charset=utf-8")
        except Exception as _root_err:
            logger.warning(f"root_redirect bot render failed: {_root_err}")
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/chat", status_code=302)

@app.get("/llms.txt", response_class=Response)
async def serve_llms_txt_root():
    from routes.admin_advanced import _build_llms_txt
    txt = await _build_llms_txt()
    return Response(content=txt, media_type="text/plain; charset=utf-8")

@app.get("/llms-full.txt", response_class=Response)
async def serve_llms_full_txt():
    from routes.bot_discovery import build_llms_full_txt
    txt = await build_llms_full_txt()
    return Response(content=txt, media_type="text/plain; charset=utf-8", headers={"Cache-Control": "public, max-age=3600, s-maxage=86400"})

@app.get("/feed.xml", response_class=Response)
async def serve_main_feed():
    from routes.bot_discovery import build_rss_feed
    xml = await build_rss_feed("all")
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/feed/notes.xml", response_class=Response)
async def serve_notes_feed():
    from routes.bot_discovery import build_rss_feed
    xml = await build_rss_feed("notes")
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/feed/mcqs.xml", response_class=Response)
async def serve_mcqs_feed():
    from routes.bot_discovery import build_rss_feed
    xml = await build_rss_feed("mcqs")
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/feed/blog.xml", response_class=Response)
async def serve_blog_feed():
    from routes.bot_discovery import build_rss_feed
    xml = await build_rss_feed("blog")
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/feed/atom.xml", response_class=Response)
async def serve_atom_feed():
    from routes.bot_discovery import build_atom_feed
    xml = await build_atom_feed("all")
    return Response(content=xml, media_type="application/atom+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/feed/notes-atom.xml", response_class=Response)
async def serve_notes_atom_feed():
    from routes.bot_discovery import build_atom_feed
    xml = await build_atom_feed("notes")
    return Response(content=xml, media_type="application/atom+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/feed/mcqs-atom.xml", response_class=Response)
async def serve_mcqs_atom_feed():
    from routes.bot_discovery import build_atom_feed
    xml = await build_atom_feed("mcqs")
    return Response(content=xml, media_type="application/atom+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/feed/blog-atom.xml", response_class=Response)
async def serve_blog_atom_feed():
    from routes.bot_discovery import build_atom_feed
    xml = await build_atom_feed("blog")
    return Response(content=xml, media_type="application/atom+xml; charset=utf-8", headers={"Cache-Control": "public, max-age=1800, s-maxage=3600"})

@app.get("/.well-known/ai-plugin.json", response_class=Response)
async def serve_ai_plugin_json():
    from routes.bot_discovery import build_ai_plugin_json
    data = build_ai_plugin_json()
    return Response(content=data, media_type="application/json; charset=utf-8", headers={"Cache-Control": "public, max-age=86400"})

from routes.bot_discovery import INDEXNOW_KEY as _INDEXNOW_KEY

@app.get(f"/{_INDEXNOW_KEY}.txt", response_class=Response)
async def serve_indexnow_key_root():
    return Response(content=_INDEXNOW_KEY, media_type="text/plain")

@app.get("/sitemap.xml")
async def serve_root_sitemap():
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/api/seo/sitemap.xml", status_code=301)

@app.get("/sitemap-index.xml")
async def serve_root_sitemap_index():
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/api/seo/sitemap-index.xml", status_code=301)

from middleware import SecurityHeadersMiddleware, GlobalRateLimitMiddleware, ServerSideTrackingMiddleware
from routes.cms_sarvam_health import CmsNoIndexMiddleware, BotRenderMiddleware
app.add_middleware(CmsNoIndexMiddleware)
app.add_middleware(BotRenderMiddleware)
app.add_middleware(ServerSideTrackingMiddleware)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=_CORS_ALLOW_CREDENTIALS,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With", "x-anon-id"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After", "X-Request-Id"],
    max_age=600,
)

FRONTEND_BUILD = ROOT_DIR / "frontend" / "build"
if FRONTEND_BUILD.is_dir():
    class CachedStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    static_dir = FRONTEND_BUILD / "static"
    if static_dir.is_dir():
        app.mount("/static", CachedStaticFiles(directory=str(static_dir)), name="static-assets")

    _SPA_SKIP_PREFIXES = ("api/", "docs", "openapi.json", "health")

    import re as _spa_re
    _OG_BOT_RE = _spa_re.compile(
        r"facebookexternalhit|facebookbot|whatsapp|twitterbot|linkedinbot|"
        r"telegrambot|slackbot|discordbot|pinterest|snapchat|skype",
        _spa_re.IGNORECASE,
    )
    _SUBJECT_PATH_RE = _spa_re.compile(
        r"^(?P<board>[^/]+)/(?P<class>[^/]+)(?:/(?P<stream>[^/]+))?/(?P<subject>[^/]+)/?$"
    )
    _CHAPTER_PATH_RE = _spa_re.compile(
        r"^(?P<board>[^/]+)/(?P<class>[^/]+)/(?P<subject>[^/]+)/(?P<chapter>[^/]+)/?$"
    )
    _SEO_BOT_RE = _spa_re.compile(
        r"googlebot|bingbot|yandexbot|slurp|duckduckbot|baiduspider|"
        r"facebookexternalhit|facebookbot|twitterbot|linkedinbot|applebot|"
        r"gptbot|oai-searchbot|chatgpt-user|claudebot|anthropic-ai|perplexitybot",
        _spa_re.IGNORECASE,
    )
    _VALID_SEO_PAGE_TYPES = {"mcqs", "important-questions", "examples", "definition"}
    _KNOWN_FIRST_SEGMENTS = {
        "api", "docs", "openapi.json", "health", "static",
        "home", "about", "pricing", "signup", "login", "reset-password",
        "library", "curriculum", "chat", "history", "profile", "admin",
        "onboarding", "terms", "privacy", "status", "exam-routine",
        "learn", "pyq", "subject", "subscribe", "payment", "cms",
    }

    async def _check_seo_content_exists(full_path: str) -> bool | None:
        parts = [p for p in full_path.split("/") if p]
        n = len(parts)
        if n < 3 or n > 5:
            return None
        if parts[0] in _KNOWN_FIRST_SEGMENTS:
            return None
        if n == 5 and parts[4] not in _VALID_SEO_PAGE_TYPES:
            return False
        try:
            from deps import db
            if not db:
                return None
            board = await db.boards.find_one({"slug": parts[0]}, {"_id": 0, "id": 1})
            if not board:
                return False
            cls = await db.classes.find_one({"slug": parts[1], "board_id": board["id"]}, {"_id": 0, "id": 1})
            if not cls:
                return False
            streams = await db.streams.find({"class_id": cls["id"]}, {"_id": 0, "id": 1}).to_list(100)
            stream_ids = [s["id"] for s in streams]
            if not stream_ids:
                return None
            subj = await db.subjects.find_one(
                {"slug": parts[2], "stream_id": {"$in": stream_ids}, "status": "published"},
                {"_id": 0, "id": 1},
            )
            if not subj:
                subj_any = await db.subjects.find_one(
                    {"slug": parts[2], "stream_id": {"$in": stream_ids}},
                    {"_id": 0, "id": 1},
                )
                if subj_any:
                    return None
                return False
            if n == 3:
                return True
            chapter = await db.chapters.find_one(
                {"slug": parts[3], "subject_id": subj["id"]},
                {"_id": 0, "id": 1},
            )
            if chapter:
                return True
            import re as _re_chk
            all_chapters = await db.chapters.find({"subject_id": subj["id"]}, {"_id": 0, "title": 1}).to_list(200)
            for c in all_chapters:
                auto_slug = _re_chk.sub(r'[^a-z0-9]+', '-', c.get("title", "").lower()).strip('-')
                if auto_slug == parts[3]:
                    return True
            return False
        except Exception:
            return None

    def _build_og_html(title: str, desc: str, page_url: str, og_image: str) -> str:
        from html import escape
        return (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8">'
            f'<title>{escape(title)} | Syrabit.ai</title>'
            f'<meta name="description" content="{escape(desc)}">'
            f'<meta property="og:site_name" content="Syrabit.ai">'
            f'<meta property="og:title" content="{escape(title)}">'
            f'<meta property="og:description" content="{escape(desc)}">'
            f'<meta property="og:type" content="article">'
            f'<meta property="og:url" content="{escape(page_url)}">'
            f'<meta property="og:image" content="{escape(og_image)}">'
            '<meta property="og:image:width" content="1200">'
            '<meta property="og:image:height" content="630">'
            '<meta name="twitter:card" content="summary_large_image">'
            f'<meta name="twitter:title" content="{escape(title)}">'
            f'<meta name="twitter:description" content="{escape(desc)}">'
            f'<meta name="twitter:image" content="{escape(og_image)}">'
            f'<link rel="canonical" href="{escape(page_url)}">'
            f'<meta http-equiv="refresh" content="0;url={escape(page_url)}">'
            '</head><body></body></html>'
        )

    async def _og_html_for_chapter(path: str) -> Optional[str]:
        m = _CHAPTER_PATH_RE.match(path)
        if not m:
            return None
        try:
            from deps import db
            if not db:
                return None
            board_slug = m.group("board")
            class_slug = m.group("class")
            subject_slug = m.group("subject")
            chapter_slug = m.group("chapter")

            board = await db.boards.find_one({"slug": board_slug}, {"_id": 0, "id": 1, "name": 1})
            if not board:
                return None
            cls = await db.classes.find_one({"slug": class_slug, "board_id": board["id"]}, {"_id": 0, "id": 1, "name": 1})
            if not cls:
                return None
            streams = await db.streams.find({"class_id": cls["id"]}, {"_id": 0, "id": 1}).to_list(100)
            stream_ids = [s["id"] for s in streams]
            subj = await db.subjects.find_one(
                {"slug": subject_slug, "stream_id": {"$in": stream_ids}, "status": "published"},
                {"_id": 0, "id": 1, "name": 1},
            )
            if not subj:
                return None
            chapter = await db.chapters.find_one(
                {"slug": chapter_slug, "subject_id": subj["id"]},
                {"_id": 0, "title": 1, "description": 1},
            )
            if not chapter:
                import re as _re_inner
                all_chapters = await db.chapters.find({"subject_id": subj["id"]}, {"_id": 0, "title": 1, "description": 1}).to_list(200)
                for c in all_chapters:
                    auto_slug = _re_inner.sub(r'[^a-z0-9]+', '-', c.get("title", "").lower()).strip('-')
                    if auto_slug == chapter_slug:
                        chapter = c
                        break
            if not chapter:
                return None

            ch_title = chapter.get("title", chapter_slug)
            subj_name = subj.get("name", "")
            board_name = board.get("name", "")
            class_name = cls.get("name", "")

            title = f"{ch_title} — {subj_name} | {board_name} {class_name} Notes"
            desc = chapter.get("description") or f"{ch_title} notes for {subj_name}. Complete study material for {board_name} {class_name} students."
            page_url = f"https://syrabit.ai/{path}"
            og_image = "https://syrabit.ai/opengraph.jpg"

            return _build_og_html(title, desc, page_url, og_image)
        except Exception as _og_err:
            logger.warning(f"OG chapter tag injection error: {_og_err}")
            return None

    async def _og_html_for_subject(path: str) -> Optional[str]:
        m = _SUBJECT_PATH_RE.match(path)
        if not m:
            return None
        try:
            from deps import db
            if not db:
                return None
            board_slug = m.group("board")
            subject_slug = m.group("subject")
            stream_slug = m.group("stream") or m.group("class")

            subj = await db.subjects.find_one(
                {"slug": subject_slug, "status": "published"},
                {"_id": 0, "id": 1, "name": 1, "description": 1, "slug": 1,
                 "thumbnailUrl": 1, "thumbnail_url": 1, "board_name": 1,
                 "class_name": 1, "stream_name": 1, "chapter_count": 1},
            )
            if not subj:
                return None

            name = subj.get("name", "")
            desc = subj.get("description") or f"Complete {name} notes, chapters, and AI explanations for Assam board students."
            thumb = subj.get("thumbnailUrl") or subj.get("thumbnail_url") or ""
            subj_id = subj.get("id", "")
            board = subj.get("board_name", "")
            cls = subj.get("class_name", "")
            stream = subj.get("stream_name", "")
            label = f"{cls} {board} {stream}".strip() or "Assam Board"

            title = f"{name} Notes — {label}"
            page_url = f"https://syrabit.ai/{path}"

            if thumb and subj_id:
                og_image = f"https://syrabit.ai/api/content/subjects/{subj_id}/og-image.png"
            else:
                og_image = "https://syrabit.ai/opengraph.jpg"

            return _build_og_html(title, desc, page_url, og_image)
        except Exception as _og_err:
            logger.warning(f"OG tag injection error: {_og_err}")
            return None

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        if any(full_path.startswith(p) for p in _SPA_SKIP_PREFIXES):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        ua = (request.headers.get("user-agent") or "").lower()
        if _OG_BOT_RE.search(ua) and full_path and "/" in full_path:
            og_html = await _og_html_for_chapter(full_path) or await _og_html_for_subject(full_path)
            if og_html:
                return Response(content=og_html, media_type="text/html")

        if _SEO_BOT_RE.search(ua) and full_path:
            exists = await _check_seo_content_exists(full_path)
            if exists is False:
                return JSONResponse(status_code=404, content={"detail": "Not found"})

        index_file = FRONTEND_BUILD / "index.html"
        if index_file.exists():
            from fastapi.responses import FileResponse
            return FileResponse(str(index_file), media_type="text/html")
        return JSONResponse(status_code=404, content={"detail": "Frontend not built"})


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
