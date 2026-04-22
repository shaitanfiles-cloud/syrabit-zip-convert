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
from db_ops import supa_insert_activity_log
from metrics import _bg_health_loop, _alerting_loop
from routes.bot_discovery import _endpoint_health_alert_loop, _seo_health_alert_loop, _seo_weekly_digest_loop, _cf_bot_report_loop
from routes.bot_traffic_report import _bot_traffic_report_loop

from prompts import build_system_prompt, _classify_question
from syllabus_embedder import SyllabusEmbedder

_syllabus_embedder: Optional[SyllabusEmbedder] = None


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

            # Task #333: Bing Keyword Research cache. TTL index expires
            # cached entries 30 days after `cached_at` so the collection
            # cannot grow unbounded — `bing_keyword_client` also re-fetches
            # past TTL but the DB-level expiry is the durable guarantee.
            try:
                from bing_keyword_client import (
                    BING_KEYWORD_CACHE_COLLECTION,
                    BING_KEYWORD_CACHE_TTL_DAYS,
                )
                await db[BING_KEYWORD_CACHE_COLLECTION].create_index(
                    "cached_at",
                    expireAfterSeconds=BING_KEYWORD_CACHE_TTL_DAYS * 24 * 3600,
                    name="cached_at_ttl",
                )
            except Exception as _idx_exc:
                logger.debug(f"bing_keyword_cache TTL index ensure failed: {_idx_exc}")

            await db.blocked_ips.create_index("ip_hash", unique=True)
            await db.blocked_ips.create_index(
                "expires_at", expireAfterSeconds=0,
                name="expires_at_ttl",
                partialFilterExpression={"expires_at": {"$exists": True}},
            )

            await db.server_hits.create_index([("date", 1), ("is_bot", 1)])
            await db.server_hits.create_index([("ip_hash", 1), ("date", 1)])
            await db.server_hits.create_index([("is_bot", 1), ("ip_hash", 1)])
            await db.server_hits.create_index([("is_bot", 1), ("ip_hash_stable", 1)])
            await db.server_hits.create_index([("is_bot", 1), ("bot_name", 1)])
            await db.server_hits.create_index([("timestamp", -1)])

            await db.users.create_index("email", unique=True, sparse=True)
            await db.users.create_index("id", unique=True)
            await db.password_resets.create_index("token", unique=True)
            await db.password_resets.create_index("expires_at", expireAfterSeconds=0)
            await db.activity_log.create_index([("created_at", -1)])
            await db.notifications.create_index([("created_at", -1)])
            await db.push_subscriptions.create_index(
                [("role", 1), ("user_id", 1)],
                name="role_user_id",
            )
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

            try:
                from datetime import datetime as _dt, timezone as _tz
                from pymongo import UpdateOne as _PushLogUpdateOne
                _pl_cursor = db.indexnow_push_log.find(
                    {"pushed_at": {"$type": "string"}},
                    {"_id": 1, "pushed_at": 1},
                )
                _pl_batch: list = []
                _pl_total = 0
                _BATCH_SIZE = 500
                _epoch = _dt(2000, 1, 1, tzinfo=_tz.utc)
                async for doc in _pl_cursor:
                    raw = doc.get("pushed_at", "")
                    try:
                        cleaned = raw.replace("Z", "+00:00") if raw else ""
                        parsed = _dt.fromisoformat(cleaned) if cleaned else _epoch
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=_tz.utc)
                    except (ValueError, TypeError):
                        parsed = _epoch
                    _pl_batch.append(
                        _PushLogUpdateOne({"_id": doc["_id"]}, {"$set": {"pushed_at": parsed}})
                    )
                    if len(_pl_batch) >= _BATCH_SIZE:
                        await db.indexnow_push_log.bulk_write(_pl_batch)
                        _pl_total += len(_pl_batch)
                        _pl_batch = []
                if _pl_batch:
                    await db.indexnow_push_log.bulk_write(_pl_batch)
                    _pl_total += len(_pl_batch)
                if _pl_total:
                    logger.info(f"Migrated pushed_at string->datetime for {_pl_total} indexnow_push_log docs")
                _remaining = await db.indexnow_push_log.count_documents({"pushed_at": {"$type": "string"}})
                if _remaining:
                    logger.warning(f"indexnow_push_log: {_remaining} docs still have string pushed_at after migration")

                _null_filter = {"$or": [
                    {"pushed_at": None},
                    {"pushed_at": {"$exists": False}},
                ]}
                _null_count = await db.indexnow_push_log.count_documents(_null_filter)
                if _null_count:
                    _now = _dt.now(_tz.utc)
                    await db.indexnow_push_log.update_many(
                        _null_filter,
                        {"$set": {"pushed_at": _now}},
                    )
                    logger.info(f"Set pushed_at to now for {_null_count} indexnow_push_log docs with missing/null pushed_at")
            except Exception as e:
                logger.warning(f"indexnow_push_log pushed_at migration skipped: {e}")

            await db.indexnow_endpoint_health.create_index(
                "endpoint", unique=True, name="endpoint_unique",
            )

            await db.indexnow_health_log.create_index(
                "timestamp", expireAfterSeconds=30 * 24 * 3600,
                name="timestamp_ttl_30d",
            )
            await db.indexnow_health_log.create_index(
                [("endpoint", 1), ("timestamp", -1)],
                name="endpoint_timestamp",
            )

            await db.indexnow_smoke_log.create_index(
                "ran_at",
                expireAfterSeconds=180 * 24 * 3600,
                name="ran_at_ttl_180d",
            )
            await db.indexnow_smoke_log.create_index(
                [("ran_at", -1)],
                name="ran_at_desc",
            )

            await db.collection_size_history.create_index(
                [("collection", 1), ("date", 1)],
                unique=True,
                name="collection_date_unique",
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
                [("ip_hash", 1), ("timestamp", -1)],
                name="ip_hash_timestamp_desc",
            )
            await db.bot_spoof_attempts.create_index(
                "timestamp", expireAfterSeconds=90 * 24 * 3600,
                name="timestamp_ttl_90d",
            )

            try:
                from datetime import datetime as _dt2, timezone as _tz2
                from pymongo import UpdateOne as _SpoofUpdateOne
                _sp_cursor = db.bot_spoof_attempts.find(
                    {"timestamp": {"$type": "string"}},
                    {"_id": 1, "timestamp": 1},
                )
                _sp_batch: list = []
                _sp_total = 0
                _SP_BATCH_SIZE = 500
                _sp_epoch = _dt2(2000, 1, 1, tzinfo=_tz2.utc)
                async for doc in _sp_cursor:
                    raw = doc.get("timestamp", "")
                    try:
                        cleaned = raw.replace("Z", "+00:00") if raw else ""
                        parsed = _dt2.fromisoformat(cleaned) if cleaned else _sp_epoch
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=_tz2.utc)
                    except (ValueError, TypeError):
                        parsed = _sp_epoch
                    _sp_batch.append(
                        _SpoofUpdateOne({"_id": doc["_id"]}, {"$set": {"timestamp": parsed}})
                    )
                    if len(_sp_batch) >= _SP_BATCH_SIZE:
                        await db.bot_spoof_attempts.bulk_write(_sp_batch)
                        _sp_total += len(_sp_batch)
                        _sp_batch = []
                if _sp_batch:
                    await db.bot_spoof_attempts.bulk_write(_sp_batch)
                    _sp_total += len(_sp_batch)
                if _sp_total:
                    logger.info(f"Migrated timestamp string->datetime for {_sp_total} bot_spoof_attempts docs")
                _sp_remaining = await db.bot_spoof_attempts.count_documents({"timestamp": {"$type": "string"}})
                if _sp_remaining:
                    logger.warning(f"bot_spoof_attempts: {_sp_remaining} docs still have string timestamp after migration")
            except Exception as e:
                logger.warning(f"bot_spoof_attempts timestamp migration skipped: {e}")

            try:
                await db.chapters.create_index(
                    [("title", "text"), ("content", "text")],
                    name="chapters_content_text",
                    weights={"title": 10, "content": 1},
                )
            except Exception:
                pass

            try:
                # Task #327: Persist Google Indexing API daily counters so
                # the 200/day cap survives a backend restart. One doc per
                # day, keyed by `day` (YYYY-MM-DD UTC). Unique index keeps
                # the upsert-with-$inc aggregation correct across workers.
                await db.google_indexing_daily.create_index(
                    "day", unique=True, name="google_indexing_daily_day",
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
    asyncio.create_task(_bg_health_loop())
    asyncio.create_task(_prewarm_library_cache())
    global _syllabus_embedder
    if db is not None:
        _syllabus_embedder = SyllabusEmbedder(db)
        if _is_leader:
            asyncio.create_task(_seed_syllabus_embeddings())
    asyncio.create_task(_load_ga4_from_db())
    from routes.admin_notifications import (
        _exam_reminder_loop,
        ensure_synthetic_alerts_ttl_index,
        _synthetic_alert_cleanup_loop,
        _push_prune_loop,
    )
    asyncio.create_task(_exam_reminder_loop())
    # Task #435: auto-prune browser push subscriptions that hit a long
    # streak of non-recoverable failures so the per-channel push
    # health signal (Task #427) reflects live subscribers only. Loop
    # is leader-gated so we don't double-write across replicas.
    if _is_leader:
        asyncio.create_task(_push_prune_loop())
    # Task #433: TTL index + periodic sweep so synthetic test alerts
    # (from the "Test alert delivery" admin button) auto-expire after
    # ~7d instead of accumulating in db.alerts forever. Index creation
    # is leader-gated to avoid duplicate-key races; the sweep is per-
    # worker so the safety-net runs even if the leader is unhealthy.
    if _is_leader:
        asyncio.create_task(ensure_synthetic_alerts_ttl_index())
    asyncio.create_task(_synthetic_alert_cleanup_loop())
    asyncio.create_task(_alerting_loop())
    asyncio.create_task(_endpoint_health_alert_loop())
    # Task #412 — periodically check hydrate_telemetry and fire admin
    # alerts (email + webhook + persisted) when stale-build failures
    # spike or auto-reload recovery rate falls. Leader-gated so we don't
    # double-fire across replicas.
    if _is_leader:
        from routes.analytics import _hydrate_alert_loop
        asyncio.create_task(_hydrate_alert_loop())
    # Task #656 — periodically check review_prompt_events and fire admin
    # alerts (email + webhook + persisted) when the 7-day click-through
    # rate collapses below the configured floor (UI regression /
    # `writeReviewUrl` broken). Leader-gated so we don't double-fire
    # across replicas.
    if _is_leader:
        from routes.admin_review_prompts import _review_prompt_alert_loop
        asyncio.create_task(_review_prompt_alert_loop())
    # Task #655 — weekly review-prompt summary email (Monday ~09:00 IST).
    # Leader-gated so multiple replicas don't double-fire; the loop also
    # holds an atomic per-ISO-week lock as a belt-and-braces guard.
    if _is_leader:
        from routes.admin_review_prompts import _review_prompt_weekly_digest_loop
        asyncio.create_task(_review_prompt_weekly_digest_loop())
    if _is_leader:
        from routes.bot_discovery import _sitemap_indexnow_diff_loop
        asyncio.create_task(_sitemap_indexnow_diff_loop())
    if _is_leader:
        # Phase E (Plan 11): daily Bing URL Submission API push so Bingbot
        # learns about our 1k+ syllabus URLs without waiting for organic
        # discovery (current crawl pace 0.05 req/hr is too slow). Leader-
        # gated so we don't spend our 10k/day quota N× across replicas.
        from routes.bot_discovery import _bing_submit_daily_loop
        asyncio.create_task(_bing_submit_daily_loop())
        # Task #333: monthly Bing keyword refresh — leader-elected so we
        # only spend the free Keyword Research quota on one replica.
        from routes.bot_discovery import _bing_keyword_refresh_loop
        asyncio.create_task(_bing_keyword_refresh_loop())
    asyncio.create_task(_seo_health_alert_loop())
    asyncio.create_task(_seo_weekly_digest_loop())
    # Task #587 — nightly live grounded-recall benchmark + alerting.
    # Runs once per UTC day (configurable via GROUNDED_RECALL_NIGHTLY_*),
    # writes bench/results/latest.json so the admin tile reflects the
    # production retrievers (not the committed offline baseline), and
    # fires `_dispatch_alert` when recall@5 drops more than the gate
    # versus the committed baseline. Cross-replica dedup via
    # db.job_locks atomic CAS so multi-worker deployments do not run
    # the bench (or page admins) N×.
    try:
        from bench.grounded_recall import _grounded_recall_nightly_loop
        asyncio.create_task(_grounded_recall_nightly_loop())
    except Exception as _gr_err:
        logger.warning(f"grounded-recall nightly loop not started: {_gr_err}")
    # Tasks #599 / #618 — per-language live-retriever nightly subsets.
    # Each Indian-language subset has only ~5–8 tagged cases vs >100
    # globally, so a total coverage drop on e.g. as.wikipedia or
    # hi.wikipedia barely moves the global recall@5 and never trips
    # the global gate. Each subset owns its lock + baseline_<code>.json
    # + alert_type so it cannot interfere with (or be masked by) the
    # global nightly or another language. Boot staggers inside each
    # loop prevent all three from double-hitting the live retrievers
    # in the same minute.
    try:
        from bench.grounded_recall import (
            PER_LANGUAGE_NIGHTLY_SUBSETS,
            per_language_nightly_loops,
        )
        # Iterate the registry so adding a language (tagged fixtures +
        # baseline_<code>.json) is a one-line change in grounded_recall.py
        # — no risk of the server.py wiring drifting out of sync.
        for _lang, _loop in per_language_nightly_loops().items():
            asyncio.create_task(_loop())
        logger.info(
            "grounded-recall per-language nightly loops started: %s",
            ",".join(PER_LANGUAGE_NIGHTLY_SUBSETS),
        )
    except Exception as _gr_lang_err:
        logger.warning(f"grounded-recall per-language nightly loops not started: {_gr_lang_err}")
    # Task #458 — daily/weekly auto-publish of SEO pages so the 991 syllabus
    # topics steadily fill in without admin clicks. Cross-replica dedup is
    # handled inside the loop via atomic CAS on db.job_locks, so it does not
    # need a leader gate. No-op when SEO_AUTO_PUBLISH_ENABLED=false.
    try:
        from seo_engine import _seo_auto_publish_loop
        asyncio.create_task(_seo_auto_publish_loop())
    except Exception as _sap_err:
        logger.warning(f"seo auto-publish loop not started: {_sap_err}")
    # Task #471 — proactive staleness monitor for the auto-publish job.
    # Hourly check; emails admins + drops an in-app notification when the
    # cron has not completed a run within 36h (daily) / 8d (weekly).
    # Debounced to at most one alert per 24h while stale, plus exactly
    # one recovery notification when the job runs again.
    try:
        from seo_engine import _seo_auto_publish_staleness_loop
        asyncio.create_task(_seo_auto_publish_staleness_loop())
    except Exception as _sap_stale_err:
        logger.warning(
            f"seo auto-publish staleness loop not started: {_sap_stale_err}")
    # Task #491 — liveness heartbeat for the staleness monitor itself.
    # Every 6h, verify the monitor's lock-doc ``updated_at`` is younger
    # than ~3h (2x its 1h cadence) and page admins exactly once if not.
    # Leader-gated so a multi-replica deployment doesn't N×-page when
    # the monitor goes quiet; the per-doc CAS inside the loop is a
    # defense-in-depth against leader fail-over mid-iteration.
    if _is_leader:
        try:
            from seo_engine import _seo_staleness_heartbeat_loop
            asyncio.create_task(_seo_staleness_heartbeat_loop())
        except Exception as _sap_hb_err:
            logger.warning(
                f"seo staleness heartbeat loop not started: {_sap_hb_err}")
    # Task #484 — poll GitHub Actions every 10 min and email admins +
    # drop an in-app notification when the latest main-branch run for
    # backend-tests/frontend-tests flips to failure (or stays red past
    # the 6h re-page window). Recovery alert fires once on red→green.
    # Leader-gated so multi-replica deployments don't burn the GitHub
    # API quota N×; the per-workflow CAS inside the loop is a defense
    # in depth in case leadership fails over mid-poll. No-ops cleanly
    # when GITHUB_REPO is unset (e.g. local dev).
    if _is_leader:
        try:
            from routes.admin_ci_alerts import _ci_alert_loop
            asyncio.create_task(_ci_alert_loop())
        except Exception as _ci_alert_err:
            logger.warning(
                f"ci alert loop not started: {_ci_alert_err}")
    if _is_leader:
        # Single-leader: only one replica should query the CF GraphQL API
        # and write the per-UA report each Monday.
        asyncio.create_task(_cf_bot_report_loop())
    # Task #387 — leader-gated nightly Cloudflare Pages deploy hook so the
    # prerendered subject/chapter HTML stays current even when no admin
    # edits trigger a debounced refresh. No-ops if CF_PAGES_DEPLOY_HOOK_URL
    # is unset.
    if _is_leader:
        try:
            import pages_deploy as _pages_deploy
            asyncio.create_task(_pages_deploy.nightly_loop())
        except Exception as _pd_err:
            logger.warning(f"pages_deploy nightly loop not started: {_pd_err}")

    # Task #314 uses atomic Mongo CAS via db.job_locks for dedup across
    # replicas, so it does not need a leader gate.
    asyncio.create_task(_bot_traffic_report_loop())
    from middleware import _init_blocked_ip_cache
    asyncio.create_task(_init_blocked_ip_cache())
    from routes.admin_advanced import _collection_size_snapshot_loop, _cache_warm_loop
    asyncio.create_task(_collection_size_snapshot_loop())
    # Auto pre-warm AI response cache for the most common queries (Task #282 T004)
    # Leader-gated so multi-worker deployments don't run the warm cycle N times
    # and burn N× the LLM budget every 6h.
    if _is_leader:
        asyncio.create_task(_cache_warm_loop())

    # Task #310 — rehydrate chat speed-up metrics from Redis and start the
    # periodic flush so the per-day counters and warm-run history survive
    # API restarts/redeploys. Runs on EVERY worker (not leader-gated) so any
    # request that lands on any worker sees the historical aggregate; the
    # underlying Redis ops are atomic HINCRBY/HINCRBYFLOAT against per-day
    # hashes, so concurrent flushes from multiple workers add correctly.
    import chat_speedup_metrics as _speedup
    try:
        await asyncio.to_thread(_speedup.load_from_store)
    except Exception as _sp_load_err:
        logger.warning(f"chat_speedup_metrics startup load failed: {_sp_load_err}")
    _speedup_flush_task = asyncio.create_task(_speedup.periodic_flush_loop())

    # Task #422: re-apply persisted Assamese-purity admin override (if
    # any) so behaviour/threshold survive api restarts without needing
    # a redeploy. Runs on every worker so each one sees the override
    # in-memory.
    try:
        from routes.cms_sarvam_health import (
            apply_persisted_assamese_purity_override,
            _assamese_purity_refresh_loop,
            ensure_assamese_runs_index,
            ensure_assamese_audit_index,
        )
        await apply_persisted_assamese_purity_override()
        # Per-worker refresher so a PATCH/DELETE done on one gunicorn
        # worker propagates to all sibling workers within ~15s without
        # needing pub/sub infra.
        asyncio.create_task(_assamese_purity_refresh_loop())
        # Task #423: TTL index on the per-run stats collection so old
        # docs auto-expire after 14 days and the dashboard stays cheap.
        asyncio.create_task(ensure_assamese_runs_index())
        # Task #424: ts-desc index on the override-edit audit collection
        # so the history panel's `find().sort(ts,-1).limit(20)` is cheap.
        asyncio.create_task(ensure_assamese_audit_index())
    except Exception as _asm_load_err:
        logger.warning(f"[INDIC-SANITIZE] startup override load failed: {_asm_load_err}")

    # Task #609 — initialise the managed AI response cache. Safe no-op when
    # MEMORYSTORE_REDIS_URL is unset; the cache transparently falls back to
    # the existing Upstash REST client and finally to the in-memory L1.
    try:
        import ai_cache as _ai_cache
        await _ai_cache.init_async_client()
    except Exception as _ai_cache_err:
        logger.warning(f"ai_cache init failed (continuing with fallback): {_ai_cache_err}")

    logger.info("Syrabit.ai API started")
    if sarvam_client:
        logger.info("Sarvam AI client ready")
    yield
    # Task #310 — final flush of speed-up metrics before shutting down so the
    # most recent counters survive the restart.
    try:
        _speedup_flush_task.cancel()
        try:
            await _speedup_flush_task
        except (asyncio.CancelledError, Exception):
            pass
        await asyncio.to_thread(_speedup.flush_to_store)
    except Exception as _sp_shutdown_err:
        logger.warning(f"chat_speedup_metrics shutdown flush failed: {_sp_shutdown_err}")
    try:
        import ai_cache as _ai_cache_close
        await _ai_cache_close.close_async_client()
    except Exception:
        pass
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

# Task #610 — OpenTelemetry distributed tracing. Wired immediately after
# FastAPI() so the auto-instrumentor can register its ASGI middleware
# before any other middleware is added (excluded URLs cover health/metrics).
# No-op when TRACING_ENABLED is unset, so dev / Railway origins are
# unaffected. See tracing.py for env contract.
try:
    from tracing import init_tracing as _init_tracing
    _init_tracing(app)
except Exception as _trc_err:
    logger.warning(f"[tracing] init_tracing failed (non-fatal): {_trc_err}")

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
from routes.admin_retriever import router as admin_retriever_router
from routes.admin_benchmark import router as admin_benchmark_router
from routes.admin_kv_health import router as admin_kv_health_router
from routes.admin_ci_status import router as admin_ci_status_router
from routes.admin_ads import router as admin_ads_router
from routes.admin_review_prompts import router as admin_review_prompts_router
from routes.edu_browser import router as edu_browser_router
from routes.edu_study import router as edu_study_router
from routes.admin_seo_keywords import router as admin_seo_keywords_router

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
api.include_router(admin_retriever_router)
api.include_router(admin_benchmark_router)
api.include_router(admin_kv_health_router)
api.include_router(admin_ci_status_router)
api.include_router(admin_ads_router)
api.include_router(admin_review_prompts_router)
api.include_router(edu_browser_router)
api.include_router(edu_study_router)
api.include_router(admin_seo_keywords_router)

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
from routes.bot_traffic_report import router as bot_traffic_report_router
api.include_router(bot_traffic_report_router)

app.include_router(api)

from routes.pyq import router as pyq_router
app.include_router(pyq_router)

from routes.reviews import router as reviews_router
app.include_router(reviews_router)

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
Disallow: /history
Disallow: /profile
Disallow: /cms/

User-agent: Yandexbot
Allow: /
Allow: /api/seo/
Disallow: /admin/
Disallow: /history
Disallow: /profile

User-agent: DuckDuckBot
Allow: /
Allow: /api/seo/
Disallow: /admin/

User-agent: Applebot
Allow: /
Allow: /api/seo/
Disallow: /admin/

User-agent: Applebot-Extended
Allow: /
Allow: /api/seo/
Disallow: /admin/

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
Disallow: /api/auth/
Disallow: /api/ai/

User-agent: Meta-ExternalAgent
Allow: /
Allow: /api/seo/
Allow: /api/seo/keyword-index
Allow: /api/seo/keyword-index.txt
Disallow: /admin/
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


# Task #365: Expose every dynamic sitemap that the SEO Manager / Google
# Search Console probes at the *root* of the domain (e.g.
# ``https://syrabit.ai/sitemap-pages.xml``). The actual generators live
# on the seo_engine router under ``/api/seo/...``; we delegate to them
# rather than duplicate the XML build logic so the two paths cannot
# drift. Without these aliases the SPA catch-all returned the React
# shell as text/html and external sitemap validators / Googlebot
# rejected every entry as "not XML". Each route is registered for
# both GET and HEAD so HEAD probes (used by the internal spot-checker
# and many crawlers) report 200 with ``application/xml`` instead of
# 404 ``application/json`` from the catch-all.
_DYNAMIC_SITEMAP_ALIASES = (
    ("sitemap-pages.xml",       "get_sitemap_pages"),
    ("sitemap-subjects.xml",    "get_sitemap_subjects"),
    ("sitemap-chapters.xml",    "get_sitemap_chapters"),
    ("sitemap-learn.xml",       "get_sitemap_learn"),
    ("sitemap-notes.xml",       "get_sitemap_notes"),
    ("sitemap-mcqs.xml",        "get_sitemap_mcqs"),
    ("sitemap-pyqs.xml",        "get_sitemap_pyqs"),
    ("sitemap-examples.xml",    "get_sitemap_examples"),
    ("sitemap-definitions.xml", "get_sitemap_definitions"),
)


def _register_root_sitemap_aliases():
    import seo_engine as _seo
    for filename, handler_name in _DYNAMIC_SITEMAP_ALIASES:
        handler = getattr(_seo, handler_name, None)
        if handler is None:
            continue
        # Capture handler in a default arg so each closure binds its own
        async def _proxy(handler=handler):
            return await handler()
        _proxy.__name__ = f"serve_root_{handler_name}"
        app.add_api_route(
            f"/{filename}",
            _proxy,
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )


_register_root_sitemap_aliases()


# Task #365: HEAD-vs-GET parity. FastAPI's ``app.get`` registers the
# route for the GET method only — HEAD requests fall through and our
# default exception handler emits ``404 application/json`` with
# ``x-source: backend``. Search engines (and our own SEO health probe)
# use HEAD as the cheap pre-check, so every SPA route was being
# counted as broken even though GET returned 200. This middleware
# rewrites the ASGI scope so HEAD is processed by the matching GET
# handler, then drops the response body before flushing — preserving
# correct HEAD semantics (headers only, content-length=0).
class HeadAsGetMiddleware:
    """Pure-ASGI middleware: HEAD → GET, body stripped on the way out.

    Installed as the *outermost* middleware so the rewritten method is
    visible to every downstream layer (auth, rate limit, bot render,
    routing). Non-HEAD requests are forwarded unchanged with zero
    overhead.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "HEAD":
            await self.app(scope, receive, send)
            return
        new_scope = {**scope, "method": "GET", "_original_method": "HEAD"}

        async def _send(message):
            mtype = message.get("type")
            if mtype == "http.response.start":
                # Drop content-length; HEAD carries no body. Leave
                # every other header (cache-control, content-type,
                # x-source, etc.) intact so HEAD reports the same
                # shape as GET.
                headers = [
                    (k, v) for (k, v) in message.get("headers", [])
                    if k.lower() != b"content-length"
                ]
                await send({**message, "headers": headers})
            elif mtype == "http.response.body":
                # Coalesce streaming bodies into a single empty body
                # message. We only emit the terminator (more_body
                # False) — intermediate chunks are swallowed.
                if not message.get("more_body", False):
                    await send({
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    })
            else:
                await send(message)

        await self.app(new_scope, receive, _send)


from middleware import (
    SecurityHeadersMiddleware,
    GlobalRateLimitMiddleware,
    ServerSideTrackingMiddleware,
    OriginSharedSecretMiddleware,
)
from routes.cms_sarvam_health import CmsNoIndexMiddleware, BotRenderMiddleware
app.add_middleware(CmsNoIndexMiddleware)
app.add_middleware(BotRenderMiddleware)
app.add_middleware(ServerSideTrackingMiddleware)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# Task #606: When deployed on Cloud Run behind Cloudflare, require the
# shared-secret header injected by the edge worker so direct hits to the
# Cloud Run URL (e.g. `https://syrabit-backend-xyz.a.run.app/api/...`) are
# rejected. No-op when ORIGIN_SHARED_SECRET env var is unset, so the
# Railway origin keeps working until cutover.
app.add_middleware(OriginSharedSecretMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=_CORS_ALLOW_CREDENTIALS,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With", "x-anon-id", "x-turnstile-token", "traceparent", "tracestate", "baggage"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After", "X-Request-Id", "traceparent"],
    max_age=600,
)
# Task #365: Outermost layer — convert HEAD → GET before any other
# middleware (CORS, security headers, rate limit, bot render) sees it.
app.add_middleware(HeadAsGetMiddleware)

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
            _pub = {"$or": [{"status": {"$exists": False}}, {"status": "published"}]}
            board = await db.boards.find_one({"$and": [{"slug": parts[0]}, _pub]}, {"_id": 0, "id": 1})
            if not board:
                return False
            cls = await db.classes.find_one({"$and": [{"slug": parts[1], "board_id": board["id"]}, _pub]}, {"_id": 0, "id": 1})
            if not cls:
                return False
            streams = await db.streams.find({"$and": [{"class_id": cls["id"]}, _pub]}, {"_id": 0, "id": 1}).to_list(100)
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

            _pub = {"$or": [{"status": {"$exists": False}}, {"status": "published"}]}
            board = await db.boards.find_one({"$and": [{"slug": board_slug}, _pub]}, {"_id": 0, "id": 1, "name": 1})
            if not board:
                return None
            cls = await db.classes.find_one({"$and": [{"slug": class_slug, "board_id": board["id"]}, _pub]}, {"_id": 0, "id": 1, "name": 1})
            if not cls:
                return None
            streams = await db.streams.find({"$and": [{"class_id": cls["id"]}, _pub]}, {"_id": 0, "id": 1}).to_list(100)
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
