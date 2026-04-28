"""Google Suggest (autocomplete) keyword client.

Hits Google's free, public, key-less autocomplete endpoint to expand a
seed query into the actual phrases real users type into Google. Used by
`seo_keyword_service` alongside `bing_keyword_client` so we get both
Bing-side volume signals and Google-side phrasing/intent signals.

Why this instead of Google Ads "Keyword Planner":
  * Keyword Planner ships only via the Google Ads API which requires a
    manually-approved developer token, an Ads account, and (for exact
    volumes) active ad spend. None of that is in place for Syrabit.
  * Google Suggest is the same data source that powers the dropdown on
    google.com, has no key, no quota in practice, and supports
    `gl=` (geo) + `hl=` (language) so we can specifically target
    "as-IN" (Assamese in India) and "en-IN" (English in India) — which
    is exactly the geo/language intent the SEO ask boils down to.

Endpoint:
    https://suggestqueries.google.com/complete/search
        ?client=firefox&q=<seed>&hl=<lang>&gl=<country>

`client=firefox` is the cleanest payload shape: returns
`[seed, [suggestion1, suggestion2, ...]]` as a flat JSON array (no JSONP
padding, no nested objects).

Cache: 7-day TTL Mongo doc per (seed, country, language) — Suggest is
free but we still avoid hammering it from the request path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from internal_user_agents import google_suggest_headers as _google_suggest_headers

logger = logging.getLogger(__name__)

GOOGLE_SUGGEST_URL = "https://suggestqueries.google.com/complete/search"
GOOGLE_SUGGEST_TIMEOUT_S = 8.0
GOOGLE_SUGGEST_DEFAULT_COUNTRY = "in"
GOOGLE_SUGGEST_DEFAULT_LANGUAGE = "en"
GOOGLE_SUGGEST_CACHE_COLLECTION = "google_suggest_cache"
GOOGLE_SUGGEST_CACHE_TTL_DAYS = 7
GOOGLE_SUGGEST_TOP_N = 20

# Geo/language pairs we always probe for an Indian-education seed:
#   en-IN: the dominant query language
#   as-IN: native Assamese phrasings (অসমীয়া) for our core audience
#   bn-IN: Bengali — common second language in lower Assam / NE
INDIA_EDU_VARIANTS: List[Dict[str, str]] = [
    {"hl": "en", "gl": "in"},
    {"hl": "as", "gl": "in"},
    {"hl": "bn", "gl": "in"},
]


def _cache_key(seed: str, country: str, language: str) -> str:
    return f"{(seed or '').strip().lower()}|{country.lower()}|{language.lower()}"


def _is_cache_fresh(cached_at, ttl_days: int, now: datetime) -> bool:
    if not cached_at:
        return False
    if isinstance(cached_at, str):
        try:
            cached_at = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
        except Exception:
            return False
    if not isinstance(cached_at, datetime):
        return False
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    return (now - cached_at) < timedelta(days=ttl_days)


def _format_cached_at(cached_at) -> Optional[str]:
    if cached_at is None:
        return None
    if isinstance(cached_at, datetime):
        return cached_at.isoformat()
    return str(cached_at)


async def _suggest_get(
    seed: str,
    country: str,
    language: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> List[str]:
    """Single Google Suggest call. Returns the suggestion list or []."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=GOOGLE_SUGGEST_TIMEOUT_S)
    try:
        resp = await client.get(
            GOOGLE_SUGGEST_URL,
            params={"client": "firefox", "q": seed, "hl": language, "gl": country},
            headers=_google_suggest_headers(),
        )
        if resp.status_code != 200:
            logger.debug(
                "google suggest %s/%s returned %d",
                language, country, resp.status_code,
            )
            return []
        try:
            payload = resp.json()
        except Exception:
            return []
        # Firefox client shape: ["seed", ["sugg1", "sugg2", ...]]
        if isinstance(payload, list) and len(payload) >= 2 and isinstance(payload[1], list):
            return [str(x) for x in payload[1] if isinstance(x, (str, bytes))]
        return []
    except Exception as exc:
        logger.debug("google suggest transport error: %s", exc)
        return []
    finally:
        if owns_client:
            await client.aclose()


def _normalize_suggestions(seed: str, raw: List[str], top_n: int) -> List[Dict[str, Any]]:
    """Dedup, drop the seed itself, cap to top_n, attach a tiny rank."""
    seed_l = (seed or "").strip().lower()
    out: List[Dict[str, Any]] = []
    seen = set()
    for idx, kw in enumerate(raw or []):
        s = (kw or "").strip()
        if not s:
            continue
        sl = s.lower()
        if sl == seed_l or sl in seen:
            continue
        seen.add(sl)
        # Higher rank = stronger signal (Google returns them in relevance order).
        out.append({"keyword": s, "rank": max(1, top_n - idx)})
        if len(out) >= top_n:
            break
    return out


async def fetch_suggestions(
    seed: str,
    *,
    db: Any = None,
    country: str = GOOGLE_SUGGEST_DEFAULT_COUNTRY,
    language: str = GOOGLE_SUGGEST_DEFAULT_LANGUAGE,
    top_n: int = GOOGLE_SUGGEST_TOP_N,
    ttl_days: int = GOOGLE_SUGGEST_CACHE_TTL_DAYS,
    client: Optional[httpx.AsyncClient] = None,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Cached Google Suggest fetch for one (country, language) pair.

    Returns dict shaped:
        {seed, country, language, suggestions, cached, fetched_at, source}
    where `source` is one of `cache`, `api`, `cache_stale_fallback`,
    `api_empty`.
    """
    seed = (seed or "").strip()
    now = now or datetime.now(timezone.utc)
    key = _cache_key(seed, country, language)

    cached_doc: Optional[dict] = None
    if db is not None and not force:
        try:
            cached_doc = await db[GOOGLE_SUGGEST_CACHE_COLLECTION].find_one({"_id": key})
        except Exception:
            cached_doc = None
        if cached_doc and _is_cache_fresh(cached_doc.get("cached_at"), ttl_days, now):
            return {
                "seed": seed,
                "country": country,
                "language": language,
                "suggestions": cached_doc.get("suggestions") or [],
                "cached": True,
                "fetched_at": _format_cached_at(cached_doc.get("cached_at")),
                "source": "cache",
            }

    if not seed:
        return {
            "seed": seed, "country": country, "language": language,
            "suggestions": [], "cached": False, "fetched_at": None,
            "source": "api_empty",
        }

    raw = await _suggest_get(seed, country, language, client=client)
    suggestions = _normalize_suggestions(seed, raw, top_n)

    if not suggestions and cached_doc:
        return {
            "seed": seed, "country": country, "language": language,
            "suggestions": cached_doc.get("suggestions") or [],
            "cached": True,
            "fetched_at": _format_cached_at(cached_doc.get("cached_at")),
            "source": "cache_stale_fallback",
        }

    if not suggestions:
        return {
            "seed": seed, "country": country, "language": language,
            "suggestions": [], "cached": False, "fetched_at": now.isoformat(),
            "source": "api_empty",
        }

    if db is not None:
        try:
            await db[GOOGLE_SUGGEST_CACHE_COLLECTION].update_one(
                {"_id": key},
                {"$set": {
                    "_id": key, "seed": seed, "country": country,
                    "language": language, "suggestions": suggestions,
                    "cached_at": now,
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.debug("google suggest cache write failed: %s", exc)

    return {
        "seed": seed, "country": country, "language": language,
        "suggestions": suggestions, "cached": False,
        "fetched_at": now.isoformat(), "source": "api",
    }


async def fetch_india_edu_bundle(
    seed: str,
    *,
    db: Any = None,
    top_n: int = GOOGLE_SUGGEST_TOP_N,
    client: Optional[httpx.AsyncClient] = None,
    force: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Fetch Suggest for all `INDIA_EDU_VARIANTS` and merge into one bundle.

    The merged keyword list is deduped (case-insensitive, trimmed) and
    each entry carries the set of `(language, country)` pairs Google
    returned it for — that locale-spread is the real geo signal we hand
    to the LLM enricher.
    """
    seed = (seed or "").strip()
    now = now or datetime.now(timezone.utc)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=GOOGLE_SUGGEST_TIMEOUT_S)
    per_variant: List[dict] = []
    try:
        for v in INDIA_EDU_VARIANTS:
            r = await fetch_suggestions(
                seed, db=db, country=v["gl"], language=v["hl"],
                top_n=top_n, client=client, force=force, now=now,
            )
            per_variant.append(r)
    finally:
        if owns_client:
            await client.aclose()

    merged: Dict[str, Dict[str, Any]] = {}
    for r in per_variant:
        tag = f"{r['language']}-{r['country']}"
        for s in r.get("suggestions", []):
            kw = s.get("keyword", "").strip()
            if not kw:
                continue
            kl = kw.lower()
            if kl not in merged:
                merged[kl] = {"keyword": kw, "rank": s.get("rank", 0), "locales": []}
            else:
                merged[kl]["rank"] = max(merged[kl]["rank"], s.get("rank", 0))
            if tag not in merged[kl]["locales"]:
                merged[kl]["locales"].append(tag)

    # Sort: presence in more locales first, then rank.
    out = sorted(
        merged.values(),
        key=lambda x: (len(x["locales"]), x["rank"]),
        reverse=True,
    )

    return {
        "seed": seed,
        "variants": [
            {"language": r["language"], "country": r["country"],
             "source": r["source"], "count": len(r.get("suggestions", []))}
            for r in per_variant
        ],
        "suggestions": out,
        "fetched_at": now.isoformat(),
    }
