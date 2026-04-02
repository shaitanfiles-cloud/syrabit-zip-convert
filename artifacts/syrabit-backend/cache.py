"""Syrabit.ai — Redis + in-memory caching helpers."""
import hashlib, json, logging, time
from typing import Optional, Dict, Any
import cachetools
from deps import redis_client

logger = logging.getLogger(__name__)

__all__ = [
    "CONTENT_CACHE_SECONDS", "REDIS_AI_CACHE_TTL", "REDIS_CASUAL_CACHE_TTL",
    "REDIS_CHAT_CACHE_TTL", "REDIS_CONTENT_PREFIX", "REDIS_RATE_WINDOW",
    "REDIS_SEARCH_CACHE_TTL", "REDIS_SESSION_CACHE_TTL",
    "_ai_response_cache", "_cache_key", "_content_cache", "_content_cache_ttl",
    "_content_card_cache", "_content_card_cache_key", "_conv_cache", "_conv_cache_key",
    "_get_content_cache", "_invalidate_content_cache", "_invalidate_conv_cache",
    "_invalidate_user_cache", "_rag_cache", "_rag_cache_key",
    "_redis_cache_conversation", "_redis_cache_search", "_redis_cache_session",
    "_redis_del", "_redis_get", "_redis_get_ai_cache", "_redis_get_conversation",
    "_redis_get_search", "_redis_get_session", "_redis_hit_count",
    "_redis_invalidate_conversation", "_redis_invalidate_session", "_redis_miss_count",
    "_redis_set", "_set_content_cache", "_syllabus_cache", "_syllabus_cache_key",
    "_user_cache", "_vector_rag_cache", "_vector_rag_cache_key",
]

_ai_response_cache = cachetools.TTLCache(maxsize=512, ttl=3600)

# ── User Object Cache ─────────────────────────────────────────────────────────
# Keyed by user_id, 120-second TTL — eliminates DB round-trip on every auth'd request
_user_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=2000, ttl=300)

def _invalidate_user_cache(uid: str):
    _user_cache.pop(uid, None)
    _redis_del("session", uid)

# ── Conversation Object Cache ──────────────────────────────────────────────────
# Keyed by "conv_id:uid", 60-second TTL — avoids PG on every chat turn
_conv_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=4000, ttl=300)

def _conv_cache_key(conv_id: str, uid: str) -> str:
    return f"{conv_id}:{uid}"

def _invalidate_conv_cache(conv_id: str, uid: str):
    _conv_cache.pop(_conv_cache_key(conv_id, uid), None)

# ── RAG Result Cache ───────────────────────────────────────────────────────────
# Keyed by (query_hash, subject_id), 600-second TTL — skips 3 MongoDB queries on repeat
_rag_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=1024, ttl=600)

# Vector RAG cache — 300-second TTL (Gemini embed API calls are expensive to re-run)
_vector_rag_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=600)

# Content card cache — 180-second TTL (avoids duplicate seo_pages + chapters queries)
_content_card_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=600)

def _content_card_cache_key(query: str, subject_id: Optional[str], subject_name: Optional[str], intent: Optional[str] = None) -> str:
    raw = f"{query.strip().lower()}|{subject_id or ''}|{subject_name or ''}|{intent or ''}"
    return hashlib.md5(raw.encode()).hexdigest()

# Syllabus cache — 30-minute TTL; syllabi almost never change between requests
_syllabus_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=256, ttl=3600)

def _syllabus_cache_key(board_id: str, class_id: str, stream_id: Optional[str], subject_id: Optional[str] = None) -> str:
    return f"{board_id}|{class_id}|{stream_id or ''}|{subject_id or ''}"

def _rag_cache_key(query: str, subject_id: Optional[str], subject_name: Optional[str]) -> str:
    raw = f"{query.strip().lower()}|{subject_id or ''}|{subject_name or ''}"
    return hashlib.md5(raw.encode()).hexdigest()

def _vector_rag_cache_key(query: str, subject_id: Optional[str], top_k: int) -> str:
    raw = f"{query.strip().lower()}|{subject_id or ''}|{top_k}"
    return hashlib.md5(raw.encode()).hexdigest()

_embedding_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=600)

def _embedding_cache_key(text: str, task_type: str) -> str:
    raw = f"{text[:200].strip().lower()}|{task_type}"
    return hashlib.md5(raw.encode()).hexdigest()

REDIS_AI_CACHE_TTL = 3600
REDIS_CASUAL_CACHE_TTL = 300
REDIS_CHAT_CACHE_TTL = 600
REDIS_SEARCH_CACHE_TTL = 300
REDIS_SESSION_CACHE_TTL = 1800
REDIS_RATE_WINDOW = 60

_redis_miss_count = 0
_redis_hit_count = 0

def _cache_key(query: str, subject_id: str = "", board_id: str = "", conversation_id: str = "") -> str:
    normalized = f"{query.lower().strip()}|{subject_id or ''}|{board_id or ''}|{conversation_id or ''}"
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

