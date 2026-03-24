"""
Syrabit.ai Celery Worker
Background task processing with Upstash Redis broker
"""
import os
import hashlib
import logging
from celery import Celery
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def _build_broker_url():
    redis_proto_url = os.environ.get("UPSTASH_REDIS_URL", "").strip()
    if "redis://" in redis_proto_url:
        redis_proto_url = redis_proto_url[redis_proto_url.index("redis://"):]
    if redis_proto_url.startswith("redis://"):
        redis_proto_url = "rediss://" + redis_proto_url[len("redis://"):]
    if redis_proto_url.startswith("rediss://"):
        return redis_proto_url
    if not REDIS_URL or not REDIS_TOKEN:
        logger.warning("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN not set — Celery disabled")
        return "memory://"
    host = REDIS_URL.replace("https://", "").replace("http://", "").rstrip("/").strip('"').strip("'")
    return f"rediss://default:{REDIS_TOKEN}@{host}:6379"


BROKER_URL = _build_broker_url()

import ssl
_ssl_params = {"ssl_cert_reqs": ssl.CERT_NONE}

celery_app = Celery(
    "syrabit_worker",
    broker=BROKER_URL,
    backend=BROKER_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_use_ssl=_ssl_params,
    redis_backend_use_ssl=_ssl_params,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)


def _get_supabase():
    from supabase import create_client
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def _get_redis():
    from upstash_redis import Redis
    return Redis(url=REDIS_URL, token=REDIS_TOKEN)


@celery_app.task(
    name="syrabit.cleanup_expired_resets",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def cleanup_expired_resets():
    supabase = _get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    result = (
        supabase.table("password_resets")
        .delete()
        .lt("expires", now)
        .execute()
    )
    deleted = len(result.data) if result.data else 0
    logger.info(f"Cleaned up {deleted} expired password reset(s)")
    return {"deleted": deleted}


@celery_app.task(
    name="syrabit.aggregate_analytics",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def aggregate_analytics():
    supabase = _get_supabase()
    redis = _get_redis()

    users_resp = supabase.table("users").select("id", count="exact").execute()
    total_users = users_resp.count or 0

    convos_resp = supabase.table("conversations").select("id", count="exact").execute()
    total_conversations = convos_resp.count or 0

    plan_resp = supabase.table("users").select("plan").execute()
    plan_dist = {}
    for u in (plan_resp.data or []):
        p = u.get("plan", "free")
        plan_dist[p] = plan_dist.get(p, 0) + 1

    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "total_users": total_users,
        "total_conversations": total_conversations,
        "plan_distribution": plan_dist,
        "aggregated_at": now,
    }

    import json
    redis.set("analytics:snapshot", json.dumps(snapshot), ex=86400)
    logger.info(f"Analytics aggregation completed: {total_users} users, {total_conversations} conversations")
    return snapshot


@celery_app.task(
    name="syrabit.cleanup_stale_cache",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def cleanup_stale_cache():
    redis = _get_redis()
    keys = redis.keys("ai_cache:*")
    expired_count = 0
    for key in (keys or []):
        ttl = redis.ttl(key)
        if ttl is not None and ttl <= 0:
            redis.delete(key)
            expired_count += 1
    logger.info(f"Cleaned up {expired_count} stale AI cache entries out of {len(keys or [])} total")
    return {"cleaned": expired_count, "total": len(keys or [])}


celery_app.conf.beat_schedule = {
    "cleanup-resets-hourly": {
        "task": "syrabit.cleanup_expired_resets",
        "schedule": 3600.0,
    },
    "aggregate-analytics-daily": {
        "task": "syrabit.aggregate_analytics",
        "schedule": 86400.0,
    },
    "cleanup-stale-cache-6h": {
        "task": "syrabit.cleanup_stale_cache",
        "schedule": 21600.0,
    },
}
