"""
Bing Webmaster Tools — Keyword Research API client
===================================================
Wraps Bing Webmaster Tools' free Keyword Research endpoints so the SEO
engine can target real-world search demand instead of guessing keywords.

Why this matters for Syrabit:
  * Bing's index powers ChatGPT search, Copilot and Perplexity. Optimising
    for Bing keywords -> getting cited by AI engines (the "GEO" play).
  * Bing's data is also a useful proxy for Indian education search demand —
    "AHSEC physics chapter X" patterns surface here clearly.
  * Free with API key from bing.com/webmasters (Settings -> API Access).

Two endpoints we use:
  GetKeyword          -> historical impression volume for an exact phrase
  GetRelatedKeywords  -> related queries Bing's index has seen

Both endpoints are GET, return JSON, and are wrapped here as small async
methods. Country/language defaults to en-IN since Syrabit's audience is
Assam/India. The module also keeps a small in-memory LRU so repeated
lookups inside one batch run don't burn API quota.

Auth: BING_WEBMASTER_API_KEY environment variable.
"""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger("bing_webmaster")

BASE_URL = "https://ssl.bing.com/webmaster/api.svc/json"
DEFAULT_COUNTRY = "IN"
DEFAULT_LANGUAGE = "en-IN"

CACHE_TTL_SECONDS = 60 * 60 * 12  # 12h
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = asyncio.Lock()
_MAX_CACHE_ENTRIES = 5000

_http_client: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=8.0,
            http2=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


def is_configured() -> bool:
    return bool(os.environ.get("BING_WEBMASTER_API_KEY", "").strip())


async def _cached_get(key: tuple, fetcher) -> dict:
    now = time.time()
    async with _cache_lock:
        entry = _cache.get(key)
        if entry and (now - entry[0]) < CACHE_TTL_SECONDS:
            return entry[1]

    data = await fetcher()

    async with _cache_lock:
        if len(_cache) >= _MAX_CACHE_ENTRIES:
            cutoff = now - CACHE_TTL_SECONDS
            for k in [k for k, (ts, _) in _cache.items() if ts < cutoff]:
                _cache.pop(k, None)
            if len(_cache) >= _MAX_CACHE_ENTRIES:
                # Evict oldest 10% if still full
                victims = sorted(_cache.items(), key=lambda kv: kv[1][0])[: _MAX_CACHE_ENTRIES // 10]
                for k, _ in victims:
                    _cache.pop(k, None)
        _cache[key] = (now, data)
    return data


async def _get(path: str, params: dict) -> dict:
    api_key = os.environ.get("BING_WEBMASTER_API_KEY", "").strip()
    if not api_key:
        return {}
    full_params = {"apikey": api_key, **params}
    try:
        resp = await _client().get(f"{BASE_URL}/{path}", params=full_params)
        if resp.status_code == 401:
            logger.error("Bing Webmaster 401 — BING_WEBMASTER_API_KEY invalid or domain not verified.")
            return {}
        if resp.status_code == 429:
            logger.warning("Bing Webmaster 429 rate-limited. Returning empty result.")
            return {}
        resp.raise_for_status()
        return resp.json() or {}
    except httpx.HTTPError as exc:
        logger.warning(f"Bing Webmaster {path} failed: {type(exc).__name__}: {exc}")
        return {}
    except Exception as exc:
        logger.warning(f"Bing Webmaster {path} unexpected error: {exc}")
        return {}


async def get_keyword_stats(query: str, country: str = DEFAULT_COUNTRY,
                            language: str = DEFAULT_LANGUAGE) -> dict:
    """Return historical impression data for `query`.
    Result shape (best-effort, Bing returns a list of monthly buckets):
      {"query": str, "total_impressions": int, "monthly": [{"date": "...", "impressions": int}, ...]}
    Returns {} on failure.
    """
    if not query or not is_configured():
        return {}
    q = query.strip()
    cache_key = ("stats", q.lower(), country, language)

    async def _fetch():
        params = {"q": q, "country": country, "language": language}
        raw = await _get("GetKeyword", params)
        if not raw:
            return {}
        # Bing returns { "d": [ { "Date": "/Date(.../)", "Impressions": 123, "Query": "..." }, ... ] }
        rows = raw.get("d") or raw.get("D") or []
        if isinstance(rows, dict):
            rows = [rows]
        monthly = []
        total = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            impressions = int(r.get("Impressions") or r.get("impressions") or 0)
            total += impressions
            monthly.append({
                "date": str(r.get("Date") or r.get("date") or ""),
                "impressions": impressions,
            })
        return {"query": q, "total_impressions": total, "monthly": monthly}

    return await _cached_get(cache_key, _fetch)


async def get_related_keywords(query: str, country: str = DEFAULT_COUNTRY,
                               language: str = DEFAULT_LANGUAGE) -> list[dict]:
    """Return related keyword suggestions for `query`.
    Each suggestion: {"query": str, "impressions": int}
    Returns [] on failure.
    """
    if not query or not is_configured():
        return []
    q = query.strip()
    cache_key = ("related", q.lower(), country, language)

    async def _fetch():
        params = {"q": q, "country": country, "language": language}
        raw = await _get("GetRelatedKeywords", params)
        if not raw:
            return []
        rows = raw.get("d") or raw.get("D") or []
        if isinstance(rows, dict):
            rows = [rows]
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            kw = (r.get("Query") or r.get("query") or "").strip()
            if not kw:
                continue
            out.append({
                "query": kw,
                "impressions": int(r.get("Impressions") or r.get("impressions") or 0),
            })
        out.sort(key=lambda d: d["impressions"], reverse=True)
        return out

    cached = await _cached_get(cache_key, _fetch)
    return cached if isinstance(cached, list) else []


async def keyword_brief(query: str, max_related: int = 8) -> dict:
    """One-shot helper for the SEO engine. Returns:
      {
        "query": str,
        "total_impressions": int,
        "related": [{"query": str, "impressions": int}, ...],
        "top_related_phrases": [str, ...],   # ready to inject into LLM prompts
      }
    Always returns a dict (possibly with zeros / empty lists) so callers can
    safely template the result without None-checking.
    """
    if not is_configured():
        return {"query": query, "total_impressions": 0, "related": [], "top_related_phrases": []}

    stats_task = asyncio.create_task(get_keyword_stats(query))
    related_task = asyncio.create_task(get_related_keywords(query))

    stats, related = await asyncio.gather(stats_task, related_task, return_exceptions=False)

    related = (related or [])[:max_related]
    return {
        "query": query,
        "total_impressions": (stats or {}).get("total_impressions", 0),
        "related": related,
        "top_related_phrases": [r["query"] for r in related[:5]],
    }


async def aclose():
    global _http_client
    if _http_client is not None:
        try:
            await _http_client.aclose()
        except Exception:
            pass
        _http_client = None
