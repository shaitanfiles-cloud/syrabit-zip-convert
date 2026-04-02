"""
Syrabit.ai Backend - FastAPI + MongoDB
AHSEC AI-Powered Educational Platform

Thin entry point: creates the app, mounts middleware, and includes all route modules.
"""
import os, sys, json, uuid, logging, asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

from config import ROOT_DIR, CORS_ORIGINS, _CORS_ALLOW_CREDENTIALS
import deps
from deps import (
    db, supa, sarvam_client, sarvam_llm_client,
    mongo_client, logger, _rate_cleanup_task, _init_pg_pool,
    is_mongo_available,
)
from auth_deps import _rate_limiter_cleanup
from seed import ensure_seeded
from db_ops import _supa, supa_insert_activity_log
from metrics import _bg_health_loop, _alerting_loop

from prompts import build_system_prompt, _classify_question
from subject_router import build_search_scope
from syllabus_embedder import SyllabusEmbedder

_syllabus_embedder: Optional[SyllabusEmbedder] = None


async def _migrate_supabase_users_to_pg():
    """One-time background task: copy all Supabase users into PG (upsert, safe to re-run)."""
    if not deps.pg_pool or not supa:
        return
    await asyncio.sleep(5)
    try:
        r = await _supa(lambda: supa.table("users").select("*").order("created_at", desc=False).limit(2000).execute())
        users = r.data or []
        imported = 0
        for u in users:
            try:
                saved = json.dumps(u.get("saved_subjects") or [])
                async with deps.pg_pool.acquire() as conn:
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


async def _reseed_syllabus_embeddings():
    global _syllabus_embedder
    if _syllabus_embedder is None:
        return
    try:
        inserted = await _syllabus_embedder.reseed()
        if inserted > 0:
            logger.info(f"SyllabusEmbedder: re-seeded {inserted} new chapter embeddings after PDF import")
    except Exception as exc:
        logger.warning(f"SyllabusEmbedder re-seed failed: {exc}")


@asynccontextmanager
async def lifespan(app):
    import deps as _deps_mod
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

        await db.cms_documents.create_index("id", unique=True, sparse=True)
        await db.cms_documents.create_index("seo_slug", unique=True, sparse=True)
        await db.cms_documents.create_index("status")
        await db.cms_documents.create_index("subject_id")
        await db.cms_documents.create_index([("board_id", 1), ("class_id", 1), ("subject_id", 1), ("status", 1)])
        await db.cms_documents.create_index([("updated_at", -1)])
        await db.cms_documents.create_index("linked_subject_id")
        await db.cms_documents.create_index([("status", 1), ("linked_subject_id", 1)])
        await db.cms_documents.create_index([("status", 1), ("embedding", 1)])
        try:
            await db.cms_documents.create_index(
                [("title", "text"), ("content", "text"), ("meta_description", "text")],
                weights={"title": 10, "content": 1, "meta_description": 5},
                name="cms_docs_text_search",
            )
        except Exception:
            pass

        await db.topic_pyq_collections.create_index("chapter_id")
        await db.topic_pyq_collections.create_index("subject_id")

        await db.ai_pyq_collections.create_index("chapter_id")
        await db.ai_pyq_collections.create_index("subject_id")

        await db.exam_schedule.create_index([("exam_date", 1), ("active", 1)])

        try:
            await db.topics.create_index("chapter_id")
            await db.topics.create_index("status")
            await db.topics.create_index([("board_slug", 1), ("class_slug", 1), ("subject_slug", 1), ("slug", 1)])
            await db.seo_pages.create_index([("topic_id", 1), ("page_type", 1)])
            await db.seo_pages.create_index("status")
            await db.seo_pages.create_index([("board_slug", 1), ("class_slug", 1), ("subject_slug", 1), ("topic_slug", 1), ("page_type", 1)])
            await db.seo_pages.create_index([("generated_at", -1)])
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
    try:
        from qa_engine import ensure_qa_indexes as _ensure_qa_indexes
        await _ensure_qa_indexes()
    except Exception as e:
        logger.warning(f"QA index creation skipped: {e}")
    _deps_mod._rate_cleanup_task = asyncio.create_task(_rate_limiter_cleanup())
    asyncio.create_task(_migrate_supabase_users_to_pg())
    asyncio.create_task(_heal_credits_limit())
    asyncio.create_task(_bg_health_loop())
    global _syllabus_embedder
    if db is not None:
        _syllabus_embedder = SyllabusEmbedder(db)
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
    if sarvam_llm_client:
        await sarvam_llm_client.aclose()
    mongo_client.close()


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

from llm import call_llm_api, call_llm_api_content
from auth_deps import get_admin_user

from seo_engine import router as seo_router, init_seo_engine
init_seo_engine(db, call_llm_api_content, get_admin_user, log_activity_fn=supa_insert_activity_log)
api.include_router(seo_router)

from qa_engine import public_router as qa_public_router, admin_router as qa_admin_router, init_qa_engine, ensure_qa_indexes
init_qa_engine(db, get_admin_user)
api.include_router(qa_public_router)
api.include_router(qa_admin_router)

app.include_router(api)

from routes.pyq import router as pyq_router
app.include_router(pyq_router)

from middleware import SecurityHeadersMiddleware, GlobalRateLimitMiddleware
from routes.cms_sarvam_health import CmsNoIndexMiddleware, BotRenderMiddleware
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

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if any(full_path.startswith(p) for p in _SPA_SKIP_PREFIXES):
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
