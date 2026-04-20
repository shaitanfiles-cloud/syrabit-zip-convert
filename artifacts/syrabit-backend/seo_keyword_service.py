"""Unified SEO keyword + metadata enrichment service.

Purpose:
  Replaces the role users normally hand to "Google Keyword Planner" —
  i.e. given a seed (chapter title, page topic, search intent), produce
  the SEO bundle a marketing team would copy-paste into a CMS:
    * meta_title           (≤ 60 chars)
    * meta_description     (≤ 155 chars)
    * meta_keywords        (deduped, ranked, locale-aware)
    * og_title / og_description / twitter_title / twitter_description
    * geo_tags             (geo.region, geo.placename, ICBM, language)
    * jsonld_keywords      (flat string for `LearningResource` JSON-LD)

Inputs we combine:
  1. `bing_keyword_client.fetch_top_keywords` — Bing-side related terms
     with broad-match impressions (closest free analogue to Keyword
     Planner search-volume ranges).
  2. `google_suggest_client.fetch_india_edu_bundle` — real Google
     autocomplete in en-IN / as-IN / bn-IN. This is what gives us the
     Assam-specific geo/language signal.

Output is then run through `llm.call_llm_api_content` (Gemini 2.5
Flash) with a strict JSON schema so the API stays drop-in for the
CMS / ChapterPage / bot-render middleware. The LLM call is the only
"smart" step; the keyword merge itself is deterministic so a stale or
missing LLM key still produces a usable (template-built) bundle.

Cache: 14-day TTL in `seo_enrichment_cache` keyed by
(seed, country, language). Recomputed lazily on read and refreshed by
the same bot_discovery loop that already refreshes Bing keywords.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SEO_ENRICHMENT_CACHE_COLLECTION = "seo_enrichment_cache"
SEO_ENRICHMENT_CACHE_TTL_DAYS = 14
SEO_ENRICHMENT_LLM_MODEL = "gemini-2.5-flash"
SEO_ENRICHMENT_LLM_MAX_TOKENS = 800

ASSAM_GEO_DEFAULTS: Dict[str, str] = {
    "geo.region": "IN-AS",
    "geo.placename": "Assam, India",
    "icbm": "26.2006, 92.9376",
    "language": "en-IN",
}


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


def _merge_sources(
    seed: str,
    bing: Optional[dict],
    suggest: Optional[dict],
    *,
    cap: int = 25,
) -> List[Dict[str, Any]]:
    """Deterministic merge of Bing-related + Google-Suggest keywords.

    Each entry: {keyword, score, sources:[...], locales:[...]}
    `score` is a normalised 0..1 blend of Bing impressions rank and
    Suggest rank/locale-spread. The list is capped at `cap`.
    """
    seed_l = (seed or "").strip().lower()
    bag: Dict[str, Dict[str, Any]] = {}

    bing_kws = (bing or {}).get("keywords", []) if bing else []
    if bing_kws:
        max_imp = max(((k.get("impressions") or 0) for k in bing_kws), default=1) or 1
        for k in bing_kws:
            kw = (k.get("keyword") or "").strip()
            if not kw or kw.lower() == seed_l:
                continue
            score = (k.get("impressions") or 0) / max_imp
            entry = bag.setdefault(kw.lower(), {
                "keyword": kw, "score": 0.0, "sources": [], "locales": [],
            })
            entry["score"] = max(entry["score"], score * 0.6)
            if "bing" not in entry["sources"]:
                entry["sources"].append("bing")

    sug_kws = (suggest or {}).get("suggestions", []) if suggest else []
    if sug_kws:
        max_rank = max(((s.get("rank") or 0) for s in sug_kws), default=1) or 1
        for s in sug_kws:
            kw = (s.get("keyword") or "").strip()
            if not kw or kw.lower() == seed_l:
                continue
            base = (s.get("rank") or 0) / max_rank
            locale_boost = 0.1 * len(s.get("locales") or [])
            score = min(1.0, base * 0.7 + locale_boost)
            entry = bag.setdefault(kw.lower(), {
                "keyword": kw, "score": 0.0, "sources": [], "locales": [],
            })
            entry["score"] = max(entry["score"], score)
            if "google_suggest" not in entry["sources"]:
                entry["sources"].append("google_suggest")
            for loc in s.get("locales") or []:
                if loc not in entry["locales"]:
                    entry["locales"].append(loc)

    out = sorted(bag.values(), key=lambda x: x["score"], reverse=True)
    # Round scores so the cached doc is diff-friendly.
    for o in out:
        o["score"] = round(o["score"], 4)
    return out[:cap]


def _template_bundle(
    seed: str,
    merged: List[Dict[str, Any]],
    *,
    geo: Dict[str, str],
) -> Dict[str, Any]:
    """Deterministic, no-LLM fallback bundle. Always usable."""
    top_keywords = [m["keyword"] for m in merged[:12]]
    primary = top_keywords[0] if top_keywords else seed
    title = f"{seed} — Notes, PYQs & Study Guide | Syrabit"[:60]
    desc = (
        f"Study {seed} for AHSEC, SEBA & Assam Degree exams. "
        f"Covers {primary} with PYQs, summaries, and Assamese explanations."
    )[:155]
    return {
        "meta_title": title,
        "meta_description": desc,
        "meta_keywords": top_keywords,
        "og_title": title,
        "og_description": desc,
        "twitter_title": title,
        "twitter_description": desc,
        "geo_tags": dict(geo),
        "jsonld_keywords": ", ".join(top_keywords),
        "enriched_by": "template",
    }


_LLM_PROMPT_SYSTEM = (
    "You are an SEO copy engineer for Syrabit.ai, an educational platform "
    "for AHSEC (Higher Secondary), SEBA (Secondary Board) and Degree "
    "students in Assam, India. You write tight, factual SEO metadata. "
    "You never invent facts. You always reply with a single valid JSON "
    "object — no prose, no markdown fences."
)

_LLM_PROMPT_USER_TEMPLATE = """\
Seed topic: {seed}

Top related queries (deduped, ranked by combined Bing + Google Suggest signal):
{kw_block}

Locale signals from Google Suggest: {locales}

Produce a JSON object with EXACTLY these keys:
- meta_title: <= 60 chars, includes the seed and at least one related query
- meta_description: <= 155 chars, mentions Assam / AHSEC / SEBA where natural
- meta_keywords: array of 8 to 14 distinct phrases drawn from the related queries (preserve original casing & language; include any Assamese/Bengali entries verbatim)
- og_title: <= 60 chars
- og_description: <= 155 chars
- twitter_title: <= 60 chars
- twitter_description: <= 155 chars
- geo_tags: object with keys "geo.region" (default "IN-AS"), "geo.placename" (default "Assam, India"), "icbm" (default "26.2006, 92.9376"), and "language" (best fit from the locale signals, e.g. "en-IN", "as-IN", "bn-IN")
- jsonld_keywords: comma-separated string of meta_keywords

Reply with the JSON object only.
"""


def _build_user_prompt(seed: str, merged: List[Dict[str, Any]]) -> str:
    lines = []
    locales: List[str] = []
    for m in merged[:18]:
        srcs = "+".join(m.get("sources") or [])
        locs = ",".join(m.get("locales") or []) or "-"
        for loc in m.get("locales") or []:
            if loc not in locales:
                locales.append(loc)
        lines.append(f"- {m['keyword']}  [score={m['score']:.2f} src={srcs} loc={locs}]")
    return _LLM_PROMPT_USER_TEMPLATE.format(
        seed=seed,
        kw_block="\n".join(lines) or "- (no signals; rely on the seed alone)",
        locales=", ".join(locales) or "en-IN",
    )


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    # Strip code fences if the model added them anyway.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _validate_and_clean_llm_bundle(
    raw: dict,
    *,
    seed: str,
    merged: List[Dict[str, Any]],
    geo: Dict[str, str],
) -> Dict[str, Any]:
    """Force the LLM payload into the shape callers depend on."""
    fallback = _template_bundle(seed, merged, geo=geo)
    if not isinstance(raw, dict):
        return fallback

    def _str(key: str, max_len: int) -> str:
        v = raw.get(key)
        if not isinstance(v, str) or not v.strip():
            return fallback[key]
        return v.strip()[:max_len]

    def _list_of_str(key: str, fb: List[str]) -> List[str]:
        v = raw.get(key)
        if not isinstance(v, list):
            return fb
        out, seen = [], set()
        for x in v:
            s = (x if isinstance(x, str) else str(x or "")).strip()
            if not s:
                continue
            sl = s.lower()
            if sl in seen:
                continue
            seen.add(sl)
            out.append(s)
        return out or fb

    meta_keywords = _list_of_str("meta_keywords", fallback["meta_keywords"])[:14]
    geo_in = raw.get("geo_tags") if isinstance(raw.get("geo_tags"), dict) else {}
    geo_out = dict(geo)
    for k in ("geo.region", "geo.placename", "icbm", "language"):
        v = geo_in.get(k)
        if isinstance(v, str) and v.strip():
            geo_out[k] = v.strip()

    return {
        "meta_title": _str("meta_title", 60),
        "meta_description": _str("meta_description", 155),
        "meta_keywords": meta_keywords,
        "og_title": _str("og_title", 60),
        "og_description": _str("og_description", 155),
        "twitter_title": _str("twitter_title", 60),
        "twitter_description": _str("twitter_description", 155),
        "geo_tags": geo_out,
        "jsonld_keywords": (
            raw.get("jsonld_keywords")
            if isinstance(raw.get("jsonld_keywords"), str) and raw.get("jsonld_keywords").strip()
            else ", ".join(meta_keywords)
        ),
        "enriched_by": "llm",
    }


async def _call_llm_for_bundle(
    seed: str,
    merged: List[Dict[str, Any]],
    *,
    geo: Dict[str, str],
    llm_caller=None,
) -> Optional[Dict[str, Any]]:
    """Run the LLM enricher; on any failure, return None so caller can
    fall back to the deterministic template bundle."""
    if llm_caller is None:
        try:
            from llm import call_llm_api_content as llm_caller  # type: ignore
        except Exception as exc:
            logger.debug("seo_enrichment: llm import failed: %s", exc)
            return None
    messages = [
        {"role": "system", "content": _LLM_PROMPT_SYSTEM},
        {"role": "user", "content": _build_user_prompt(seed, merged)},
    ]
    try:
        text = await llm_caller(
            messages,
            model=SEO_ENRICHMENT_LLM_MODEL,
            max_tokens=SEO_ENRICHMENT_LLM_MAX_TOKENS,
        )
    except Exception as exc:
        logger.info("seo_enrichment: llm call failed for seed=%r: %s", seed, exc)
        return None
    raw = _extract_json(text or "")
    if raw is None:
        logger.info("seo_enrichment: llm returned non-JSON for seed=%r", seed)
        return None
    return _validate_and_clean_llm_bundle(raw, seed=seed, merged=merged, geo=geo)


async def enrich_seo_for_seed(
    seed: str,
    *,
    db: Any = None,
    bing_api_key: str = "",
    country: str = "IN",
    language: str = "en-IN",
    force: bool = False,
    ttl_days: int = SEO_ENRICHMENT_CACHE_TTL_DAYS,
    geo: Optional[Dict[str, str]] = None,
    bing_fetcher=None,
    suggest_fetcher=None,
    llm_caller=None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Full keyword + metadata enrichment for one seed.

    Returns a dict shaped:
        {
          seed, country, language, fetched_at, source,
          merged: [...],
          bundle: {meta_title, meta_description, meta_keywords, og_*,
                   twitter_*, geo_tags, jsonld_keywords, enriched_by},
          counts: {bing, suggest, merged},
        }
    where `source` is one of `cache`, `fresh`, `fresh_template_only`.
    The injectable `bing_fetcher`/`suggest_fetcher`/`llm_caller` are for
    tests; production callers leave them None to use the real clients.
    """
    seed = (seed or "").strip()
    now = now or datetime.now(timezone.utc)
    geo = dict(ASSAM_GEO_DEFAULTS if geo is None else geo)
    key = _cache_key(seed, country, language)

    if db is not None and not force:
        try:
            cached = await db[SEO_ENRICHMENT_CACHE_COLLECTION].find_one({"_id": key})
        except Exception:
            cached = None
        if cached and _is_cache_fresh(cached.get("cached_at"), ttl_days, now):
            return {
                "seed": seed, "country": country, "language": language,
                "fetched_at": (
                    cached["cached_at"].isoformat()
                    if isinstance(cached.get("cached_at"), datetime)
                    else cached.get("cached_at")
                ),
                "source": "cache",
                "merged": cached.get("merged") or [],
                "bundle": cached.get("bundle") or _template_bundle(seed, [], geo=geo),
                "counts": cached.get("counts") or {},
            }

    if bing_fetcher is None:
        from bing_keyword_client import fetch_top_keywords as bing_fetcher  # type: ignore
    if suggest_fetcher is None:
        from google_suggest_client import fetch_india_edu_bundle as suggest_fetcher  # type: ignore

    bing_res: Optional[dict] = None
    suggest_res: Optional[dict] = None

    try:
        bing_res = await bing_fetcher(
            bing_api_key, seed, db=db, country=country.upper(),
            language=language, now=now,
        )
    except Exception as exc:
        logger.info("seo_enrichment: bing fetch failed for seed=%r: %s", seed, exc)

    try:
        suggest_res = await suggest_fetcher(seed, db=db, now=now)
    except Exception as exc:
        logger.info("seo_enrichment: suggest fetch failed for seed=%r: %s", seed, exc)

    merged = _merge_sources(seed, bing_res, suggest_res)
    counts = {
        "bing": len((bing_res or {}).get("keywords", []) if bing_res else []),
        "suggest": len((suggest_res or {}).get("suggestions", []) if suggest_res else []),
        "merged": len(merged),
    }

    bundle = await _call_llm_for_bundle(seed, merged, geo=geo, llm_caller=llm_caller)
    source = "fresh"
    if bundle is None:
        bundle = _template_bundle(seed, merged, geo=geo)
        source = "fresh_template_only"

    if db is not None:
        try:
            await db[SEO_ENRICHMENT_CACHE_COLLECTION].update_one(
                {"_id": key},
                {"$set": {
                    "_id": key, "seed": seed, "country": country,
                    "language": language, "merged": merged, "bundle": bundle,
                    "counts": counts, "cached_at": now,
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.debug("seo_enrichment cache write failed: %s", exc)

    return {
        "seed": seed, "country": country, "language": language,
        "fetched_at": now.isoformat(), "source": source,
        "merged": merged, "bundle": bundle, "counts": counts,
    }
