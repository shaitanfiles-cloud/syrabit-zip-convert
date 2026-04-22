"""Syrabit.ai — Public Google Reviews proxy with caching.

Exposes GET /api/reviews/google. Pulls reviews from the Google Places
Details API for the configured Place ID, normalises them for the
frontend, and caches the result for ~6 hours. On API failure we return
the last cached payload (if any), or an empty payload with HTTP 200 so
the frontend can hide the section gracefully.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter

import cachetools

from deps import redis_client

logger = logging.getLogger(__name__)
router = APIRouter()

_CACHE_TTL = 6 * 60 * 60  # 6 hours
_REDIS_KEY = "reviews:google:v1"
_REDIS_LAST_GOOD_KEY = "reviews:google:v1:last_good"

_mem_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=4, ttl=_CACHE_TTL)
_last_good_mem: Dict[str, Any] = {}

_PLACES_URL = "https://maps.googleapis.com/maps/api/place/details/json"

EMPTY_PAYLOAD: Dict[str, Any] = {
    "averageRating": 0,
    "totalCount": 0,
    "googleUrl": "",
    "reviews": [],
    "placeId": "",
}


def _redis_get_json(key: str) -> Optional[dict]:
    if not redis_client:
        return None
    try:
        val = redis_client.get(key)
        if not val:
            return None
        if isinstance(val, bytes):
            val = val.decode("utf-8", "ignore")
        return json.loads(val)
    except Exception as e:
        logger.debug(f"reviews redis GET {key} failed: {e}")
    return None


def _redis_set_json(key: str, value: dict, ttl: Optional[int]) -> None:
    if not redis_client:
        return
    try:
        if ttl:
            redis_client.set(key, json.dumps(value), ex=ttl)
        else:
            redis_client.set(key, json.dumps(value))
    except Exception as e:
        logger.debug(f"reviews redis SET {key} failed: {e}")


def _normalize(payload: dict, place_id: str) -> Dict[str, Any]:
    result = (payload or {}).get("result") or {}
    raw_reviews = result.get("reviews") or []
    reviews = []
    for r in raw_reviews:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        reviews.append({
            "author": r.get("author_name") or "Anonymous",
            "photoUrl": r.get("profile_photo_url") or "",
            "rating": int(r.get("rating") or 0),
            "relativeTime": r.get("relative_time_description") or "",
            "text": text,
            "originalLanguage": r.get("original_language") or r.get("language") or "",
            "time": r.get("time") or 0,
            "authorUrl": r.get("author_url") or "",
        })
    google_url = result.get("url") or (
        f"https://search.google.com/local/reviews?placeid={place_id}" if place_id else ""
    )
    write_review_url = (
        f"https://search.google.com/local/writereview?placeid={place_id}" if place_id else ""
    )
    return {
        "averageRating": float(result.get("rating") or 0),
        "totalCount": int(result.get("user_ratings_total") or 0),
        "googleUrl": google_url,
        "writeReviewUrl": write_review_url,
        "reviews": reviews,
        "placeId": place_id,
        "fetchedAt": int(time.time()),
    }


async def _fetch_from_google(api_key: str, place_id: str) -> Optional[Dict[str, Any]]:
    params = {
        "place_id": place_id,
        "fields": "rating,user_ratings_total,reviews,url",
        "reviews_sort": "newest",
        "key": api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(_PLACES_URL, params=params)
        if resp.status_code != 200:
            logger.warning(f"Google Places HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        body = resp.json()
        status = body.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            logger.warning(f"Google Places status={status} msg={body.get('error_message','')[:200]}")
            return None
        return _normalize(body, place_id)
    except Exception as e:
        logger.warning(f"Google Places fetch failed: {e}")
        return None


@router.get("/api/reviews/google")
async def get_google_reviews() -> Dict[str, Any]:
    """Return Google reviews for the configured Place ID, cached ~6h.

    On any failure we degrade to the last successful payload, then to an
    empty payload — always returning HTTP 200 so the frontend can hide.
    """
    api_key = (os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    place_id = (os.environ.get("GOOGLE_PLACE_ID") or "").strip()

    if not api_key or not place_id:
        return dict(EMPTY_PAYLOAD)

    # 1. In-process TTL cache
    cached = _mem_cache.get(_REDIS_KEY)
    if cached:
        return cached

    # 2. Redis (shared across workers)
    redis_cached = _redis_get_json(_REDIS_KEY)
    if redis_cached:
        _mem_cache[_REDIS_KEY] = redis_cached
        return redis_cached

    # 3. Live fetch
    fresh = await _fetch_from_google(api_key, place_id)
    if fresh is not None:
        _mem_cache[_REDIS_KEY] = fresh
        _redis_set_json(_REDIS_KEY, fresh, _CACHE_TTL)
        # Persist the last good payload indefinitely as a graceful-degrade
        # fallback for future Google outages.
        _last_good_mem["data"] = fresh
        _redis_set_json(_REDIS_LAST_GOOD_KEY, fresh, None)
        return fresh

    # 4. Last-known-good fallback (mem then redis)
    last_good = _last_good_mem.get("data") or _redis_get_json(_REDIS_LAST_GOOD_KEY)
    if last_good:
        return last_good

    # 5. Empty payload — frontend hides gracefully
    return dict(EMPTY_PAYLOAD)
