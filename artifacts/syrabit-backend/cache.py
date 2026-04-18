"""Syrabit.ai — Redis + in-memory caching helpers."""
import asyncio, hashlib, json, logging, time
from typing import Optional, Dict, Any
import cachetools
from deps import redis_client

logger = logging.getLogger(__name__)

REDIS_ANON_CONV_TTL = 604800

__all__ = [
    "CONTENT_CACHE_SECONDS", "REDIS_AI_CACHE_TTL", "REDIS_ANON_CONV_TTL",
    "REDIS_CASUAL_CACHE_TTL",
    "REDIS_CHAT_CACHE_TTL", "REDIS_CONTENT_PREFIX", "REDIS_RATE_WINDOW",
    "REDIS_SEARCH_CACHE_TTL", "REDIS_SESSION_CACHE_TTL",
    "_ai_response_cache", "_cache_key", "_content_cache",
    "_embedding_cache", "_embedding_cache_key", "_query_embed_cache",
    "_content_card_cache", "_content_card_cache_key", "_conv_cache", "_conv_cache_key",
    "_get_content_cache", "_invalidate_content_cache", "_invalidate_conv_cache",
    "_invalidate_user_cache", "_rag_cache", "_rag_cache_key",
    "_redis_cache_conversation", "_redis_cache_search", "_redis_cache_session",
    "_redis_del", "_redis_get", "_redis_get_ai_cache", "_redis_get_ai_cache_async", "_redis_get_conversation",
    "_redis_get_search", "_redis_get_session", "_redis_hit_count",
    "_redis_invalidate_conversation", "_redis_invalidate_session", "_redis_miss_count",
    "_redis_set", "_set_content_cache", "_syllabus_cache", "_syllabus_cache_key",
    "_user_cache", "_vector_rag_cache", "_vector_rag_cache_key",
    "redis_save_anon_conversation", "redis_get_anon_conversation",
    "redis_list_anon_conversations", "redis_list_all_anon_conversations",
    "redis_delete_anon_conversation",
    "get_hierarchy_cache", "set_hierarchy_cache",
]

_ai_response_cache = cachetools.TTLCache(maxsize=1024, ttl=3600)

# ── User Object Cache ─────────────────────────────────────────────────────────
# Keyed by user_id, 120-second TTL — eliminates DB round-trip on every auth'd request
_user_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=2000, ttl=600)

def _invalidate_user_cache(uid: str):
    _user_cache.pop(uid, None)
    _redis_del("session", uid)

# ── Conversation Object Cache ──────────────────────────────────────────────────
# Keyed by "conv_id:uid", 60-second TTL — avoids PG on every chat turn
_conv_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=4000, ttl=600)

def _conv_cache_key(conv_id: str, uid: str) -> str:
    return f"{conv_id}:{uid}"

def _invalidate_conv_cache(conv_id: str, uid: str):
    _conv_cache.pop(_conv_cache_key(conv_id, uid), None)

# ── RAG Result Cache ───────────────────────────────────────────────────────────
# Keyed by (query_hash, subject_id), 600-second TTL — skips 3 MongoDB queries on repeat
_rag_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=2048, ttl=900)

# Vector RAG cache — 300-second TTL (Gemini embed API calls are expensive to re-run)
_vector_rag_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=600)

# Query embedding cache — avoids repeated Gemini embed calls for the same/similar queries
_query_embed_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=900)

# Content card cache — 180-second TTL (avoids duplicate seo_pages + chapters queries)
_content_card_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=600)

def _content_card_cache_key(query: str, subject_id: Optional[str], subject_name: Optional[str], intent: Optional[str] = None, chapter_title: Optional[str] = None) -> str:
    raw = f"{query.strip().lower()}|{subject_id or ''}|{subject_name or ''}|{intent or ''}|{chapter_title or ''}"
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

_embedding_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=1024, ttl=900)

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

async def _redis_get_async(prefix: str, key: str) -> Optional[str]:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _redis_get, prefix, key)

async def _redis_get_ai_cache_async(key: str) -> Optional[str]:
    return await _redis_get_async("ai_cache", key)

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

_hierarchy_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=256, ttl=1800)

def get_hierarchy_cache(stream_id: str):
    return _hierarchy_cache.get(stream_id)

def set_hierarchy_cache(stream_id: str, data: dict):
    _hierarchy_cache[stream_id] = data

_content_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=1024, ttl=1800)
CONTENT_CACHE_SECONDS = 1800
REDIS_CONTENT_PREFIX = "content:"

def _get_content_cache(key: str):
    cached = _content_cache.get(key)
    if cached is not None:
        return cached
    if redis_client:
        try:
            val = redis_client.get(f"{REDIS_CONTENT_PREFIX}{key}")
            if val:
                parsed = json.loads(val) if isinstance(val, str) else val
                _content_cache[key] = parsed
                return parsed
        except Exception:
            pass
    return None

def _invalidate_content_cache(prefix: str):
    _CHAPTER_PREFIXES = ("ch-slug:", "ch-topic-content:", "ch-topic-summary:", "chunks:", "topic-pyqs:", "topic-page:", "flashcards:")
    _LIB_BUNDLE_KEYS = ("library-bundle", "library-bundle:seo", "library-bundle:slim")
    if prefix == "chapters":
        keys_to_del = [k for k in list(_content_cache.keys())
                       if k == prefix or k.startswith(f"{prefix}:")
                       or k in _LIB_BUNDLE_KEYS
                       or any(k.startswith(p) for p in _CHAPTER_PREFIXES)]
    else:
        keys_to_del = [k for k in list(_content_cache.keys())
                       if k == prefix or k.startswith(f"{prefix}:") or k in _LIB_BUNDLE_KEYS]
    for k in keys_to_del:
        _content_cache.pop(k, None)
    _content_card_cache.clear()
    _vector_rag_cache.clear()
    if redis_client:
        try:
            for rk in redis_client.scan_iter(f"{REDIS_CONTENT_PREFIX}{prefix}*"):
                redis_client.delete(rk)
            for lbk in _LIB_BUNDLE_KEYS:
                redis_client.delete(f"{REDIS_CONTENT_PREFIX}{lbk}")
            if prefix == "chapters":
                for cp in _CHAPTER_PREFIXES:
                    for rk in redis_client.scan_iter(f"{REDIS_CONTENT_PREFIX}{cp}*"):
                        redis_client.delete(rk)
        except Exception:
            pass
    _fire_cf_edge_purge(prefix)


_cf_purge_scheduled = False
_cf_purge_prefixes: list = []

def _fire_cf_edge_purge(prefix: str):
    global _cf_purge_scheduled
    _cf_purge_prefixes.append(prefix)
    if _cf_purge_scheduled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _cf_purge_scheduled = True
    try:
        from cloudflare_client import purge_content_prefixes
        loop.create_task(_debounced_cf_purge(purge_content_prefixes))
    except Exception:
        _cf_purge_scheduled = False
        _cf_purge_prefixes.clear()


async def _debounced_cf_purge(fn):
    global _cf_purge_scheduled
    try:
        await asyncio.sleep(0.5)
        prefixes = list(set(_cf_purge_prefixes))
        _cf_purge_prefixes.clear()
        result = await fn(prefixes)
        if result:
            logger.info(f"CF edge purge triggered for prefixes: {prefixes}")
        else:
            logger.warning(f"CF edge purge returned false for prefixes: {prefixes}")
        try:
            from cloudflare_client import purge_worker_cache
            await purge_worker_cache(purge_all=True)
        except Exception as we:
            logger.debug(f"Worker cache purge in debounced flow: {we}")
    except Exception as e:
        logger.warning(f"CF edge purge background error: {e}")
    finally:
        _cf_purge_scheduled = False
        if _cf_purge_prefixes:
            _fire_cf_edge_purge(_cf_purge_prefixes.pop(0))

def _set_content_cache(key: str, value):
    _content_cache[key] = value
    if redis_client:
        try:
            redis_client.set(f"{REDIS_CONTENT_PREFIX}{key}", json.dumps(value, default=str), ex=CONTENT_CACHE_SECONDS)
        except Exception:
            pass


_ANON_CONV_PREFIX = "anon_conv:"
_ANON_INDEX_PREFIX = "anon_idx:"
_ANON_MAX_CONVS = 20

def redis_save_anon_conversation(anon_id: str, conv_id: str, conv_data: dict):
    if not redis_client:
        return
    try:
        key = f"{_ANON_CONV_PREFIX}{anon_id}:{conv_id}"
        redis_client.set(key, json.dumps(conv_data, default=str), ex=REDIS_ANON_CONV_TTL)
        idx_key = f"{_ANON_INDEX_PREFIX}{anon_id}"
        redis_client.zadd(idx_key, {conv_id: time.time()})
        redis_client.expire(idx_key, REDIS_ANON_CONV_TTL)
        count = redis_client.zcard(idx_key)
        if count and count > _ANON_MAX_CONVS:
            old_ids = redis_client.zrange(idx_key, 0, count - _ANON_MAX_CONVS - 1)
            for oid in old_ids:
                oid_str = oid if isinstance(oid, str) else oid.decode()
                redis_client.delete(f"{_ANON_CONV_PREFIX}{anon_id}:{oid_str}")
            redis_client.zremrangebyrank(idx_key, 0, count - _ANON_MAX_CONVS - 1)
    except Exception as e:
        logger.warning(f"redis_save_anon_conversation: {e}")

def redis_get_anon_conversation(anon_id: str, conv_id: str) -> Optional[dict]:
    if not redis_client:
        return None
    try:
        val = redis_client.get(f"{_ANON_CONV_PREFIX}{anon_id}:{conv_id}")
        if val:
            return json.loads(val) if isinstance(val, str) else json.loads(val.decode())
    except Exception as e:
        logger.warning(f"redis_get_anon_conversation: {e}")
    return None

def redis_list_anon_conversations(anon_id: str) -> list:
    if not redis_client:
        return []
    try:
        idx_key = f"{_ANON_INDEX_PREFIX}{anon_id}"
        conv_ids = redis_client.zrevrange(idx_key, 0, _ANON_MAX_CONVS - 1)
        results = []
        for cid in conv_ids:
            cid_str = cid if isinstance(cid, str) else cid.decode()
            val = redis_client.get(f"{_ANON_CONV_PREFIX}{anon_id}:{cid_str}")
            if val:
                data = json.loads(val) if isinstance(val, str) else json.loads(val.decode())
                results.append({
                    "id": data.get("id", cid_str),
                    "title": data.get("title", "Untitled"),
                    "preview": data.get("preview", ""),
                    "subject_name": data.get("subject_name", ""),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(data.get("messages", [])),
                })
        return results
    except Exception as e:
        logger.warning(f"redis_list_anon_conversations: {e}")
    return []

def redis_list_all_anon_conversations() -> list:
    if not redis_client:
        return []
    try:
        idx_keys = []
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=f"{_ANON_INDEX_PREFIX}*", count=200)
            idx_keys.extend(keys)
            if cursor == 0:
                break
        results = []
        for idx_key in idx_keys:
            idx_key_str = idx_key if isinstance(idx_key, str) else idx_key.decode()
            anon_id = idx_key_str[len(_ANON_INDEX_PREFIX):]
            conv_ids = redis_client.zrevrange(idx_key_str, 0, _ANON_MAX_CONVS - 1)
            for cid in conv_ids:
                cid_str = cid if isinstance(cid, str) else cid.decode()
                val = redis_client.get(f"{_ANON_CONV_PREFIX}{anon_id}:{cid_str}")
                if val:
                    data = json.loads(val) if isinstance(val, str) else json.loads(val.decode())
                    results.append({
                        "id": data.get("id", cid_str),
                        "title": data.get("title", "Untitled"),
                        "preview": data.get("preview", ""),
                        "subject_name": data.get("subject_name", ""),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "messages": data.get("messages", []),
                        "is_anonymous": True,
                        "anon_id": anon_id,
                        "user_id": None,
                    })
        return results
    except Exception as e:
        logger.warning(f"redis_list_all_anon_conversations: {e}")
    return []

def redis_delete_anon_conversation(anon_id: str, conv_id: str) -> bool:
    if not redis_client:
        return False
    try:
        redis_client.delete(f"{_ANON_CONV_PREFIX}{anon_id}:{conv_id}")
        redis_client.zrem(f"{_ANON_INDEX_PREFIX}{anon_id}", conv_id)
        return True
    except Exception as e:
        logger.warning(f"redis_delete_anon_conversation: {e}")
    return False

