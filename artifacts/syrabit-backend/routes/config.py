"""Syrabit.ai — Public client config endpoints.

Exposes configuration values that the frontend needs at runtime but that
must not be hard-coded in the JS bundle (so they can be rotated in
secrets without a rebuild). Currently used for the Trustpilot widget
business unit ID, review URL (Task #724), and the live aggregate rating
served from the Trustpilot Business API for JSON-LD rich snippets in
Google search results (Task #725).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/config/trustpilot")
async def get_trustpilot_config() -> Dict[str, Any]:
    """Return the Trustpilot business unit + review URL for client widgets.

    All fields are best-effort — when the Trustpilot secret isn't
    configured we return empty strings and the client hides the widget
    gracefully. Always HTTP 200 so the client can branch on payload
    contents rather than network failure.
    """
    business_unit_id = (os.environ.get("TRUSTPILOT_BUSINESS_UNIT_ID") or "").strip()
    domain = (os.environ.get("TRUSTPILOT_DOMAIN") or "syrabit.ai").strip()
    profile_url = (
        os.environ.get("TRUSTPILOT_PROFILE_URL")
        or (f"https://www.trustpilot.com/review/{domain}" if domain else "")
    ).strip()
    review_url = (
        os.environ.get("TRUSTPILOT_REVIEW_URL")
        or (f"https://www.trustpilot.com/evaluate/{domain}" if domain else "")
    ).strip()
    return {
        "businessUnitId": business_unit_id,
        "domain": domain,
        "profileUrl": profile_url,
        "writeReviewUrl": review_url,
        "scriptSrc": "https://widget.trustpilot.com/bootstrap/v5/tp.widget.bootstrap.min.js",
    }


# ─── Trustpilot aggregate rating (Task #725) ────────────────────────────────
#
# Trustpilot's embed widgets do not surface aggregate ratings to the
# DOM, so Google can't extract stars from them for search results. To
# restore the rich-snippet stars we removed in Task #724 we hit the
# official Trustpilot Business API server-side, cache the result for
# several hours (the score moves slowly, and the API is rate-limited),
# and feed the value into the JSON-LD wrapper that already exists on
# every content page.
#
# Cache is in-process; we intentionally do not push this through Redis
# because (a) it's tiny, (b) it's safe for each replica to refresh on
# its own schedule, and (c) we want to fail closed if Redis is down.

_TP_AGGREGATE_TTL_S = int(os.environ.get("TRUSTPILOT_AGGREGATE_TTL_S") or 6 * 3600)
_TP_AGGREGATE_FAIL_TTL_S = 300  # short retry window when the upstream API errors
_TP_AGGREGATE_TIMEOUT_S = 8.0

_tp_aggregate_cache: Dict[str, Any] = {
    "payload": None,   # last successful payload (dict with ratingValue/ratingCount/...)
    "ts": 0.0,         # timestamp of last successful fetch
    "fail_ts": 0.0,    # timestamp of last failure (used to throttle retries)
}
_tp_aggregate_lock = asyncio.Lock()


async def _fetch_trustpilot_aggregate_remote() -> Optional[Dict[str, Any]]:
    """Call the Trustpilot Business API for the configured business unit.

    Returns ``None`` when the API key/business unit isn't configured or
    when the upstream call fails for any reason — callers fall back to
    the previously cached payload (or to omitting the JSON-LD entirely).
    """
    business_unit_id = (os.environ.get("TRUSTPILOT_BUSINESS_UNIT_ID") or "").strip()
    api_key = (os.environ.get("TRUSTPILOT_API_KEY") or "").strip()
    if not business_unit_id or not api_key:
        return None

    url = f"https://api.trustpilot.com/v1/business-units/{business_unit_id}"
    try:
        async with httpx.AsyncClient(timeout=_TP_AGGREGATE_TIMEOUT_S) as client:
            resp = await client.get(
                url,
                params={"apikey": api_key},
                headers={
                    "apikey": api_key,
                    "Accept": "application/json",
                    # Trustpilot's edge WAF rejects the default httpx UA
                    # with a 403 HTML page; spoof a generic UA so the
                    # request is treated as a normal API client.
                    "User-Agent": "Syrabit.ai-Backend/1.0 (+https://syrabit.ai)",
                },
            )
        if resp.status_code != 200:
            logger.warning(
                "trustpilot aggregate API returned status=%s body=%s",
                resp.status_code, resp.text[:200],
            )
            return None
        data = resp.json()
    except Exception:
        logger.exception("trustpilot aggregate API call failed")
        return None

    # The Business API has historically returned trustScore/stars at the
    # top level, but newer responses nest them under "score". Cover both.
    score_block = data.get("score") if isinstance(data.get("score"), dict) else {}
    rating_value = (
        data.get("trustScore")
        if isinstance(data.get("trustScore"), (int, float))
        else score_block.get("trustScore")
    )
    if not isinstance(rating_value, (int, float)):
        rating_value = data.get("stars") or score_block.get("stars")

    nr = data.get("numberOfReviews")
    if isinstance(nr, dict):
        rating_count = nr.get("total")
    else:
        rating_count = nr

    try:
        rating_value_f = float(rating_value)
        rating_count_i = int(rating_count)
    except (TypeError, ValueError):
        logger.warning(
            "trustpilot aggregate API returned unparseable rating=%r count=%r",
            rating_value, rating_count,
        )
        return None

    if rating_count_i <= 0:
        return None

    return {
        "ratingValue": round(rating_value_f, 2),
        "ratingCount": rating_count_i,
        "bestRating": 5,
        "worstRating": 1,
    }


async def _get_trustpilot_aggregate_cached() -> Dict[str, Any]:
    """Return the cached Trustpilot aggregate, refreshing when stale.

    Always returns a dict so the client can branch on ``ratingValue``
    being null without worrying about request failures.
    """
    now = time.time()
    cached = _tp_aggregate_cache["payload"]
    cached_ts = _tp_aggregate_cache["ts"]
    if cached and (now - cached_ts) < _TP_AGGREGATE_TTL_S:
        return {**cached, "cached": True, "ageSeconds": int(now - cached_ts)}

    # Throttle retries after an upstream failure so we don't hammer
    # Trustpilot during an outage. Applied whether or not we have a
    # stale cached payload — when stale, we keep serving it; when not,
    # we serve nulls.
    fail_ts = _tp_aggregate_cache["fail_ts"]
    if fail_ts and (now - fail_ts) < _TP_AGGREGATE_FAIL_TTL_S:
        if cached:
            return {**cached, "cached": True, "stale": True,
                    "ageSeconds": int(now - cached_ts)}
        return {"ratingValue": None, "ratingCount": None, "cached": False}

    async with _tp_aggregate_lock:
        # Re-check after acquiring the lock — another coroutine may have
        # refreshed the cache while we were waiting.
        now = time.time()
        cached = _tp_aggregate_cache["payload"]
        cached_ts = _tp_aggregate_cache["ts"]
        if cached and (now - cached_ts) < _TP_AGGREGATE_TTL_S:
            return {**cached, "cached": True, "ageSeconds": int(now - cached_ts)}

        fresh = await _fetch_trustpilot_aggregate_remote()
        if fresh is None:
            _tp_aggregate_cache["fail_ts"] = time.time()
            if cached:
                # Serve stale rather than dropping stars from search results
                # the moment Trustpilot has a hiccup.
                return {**cached, "cached": True, "stale": True,
                        "ageSeconds": int(time.time() - cached_ts)}
            return {"ratingValue": None, "ratingCount": None, "cached": False}

        _tp_aggregate_cache["payload"] = fresh
        _tp_aggregate_cache["ts"] = time.time()
        _tp_aggregate_cache["fail_ts"] = 0.0
        return {**fresh, "cached": False, "ageSeconds": 0}


@router.get("/api/config/trustpilot/aggregate")
async def get_trustpilot_aggregate() -> Dict[str, Any]:
    """Return the live aggregate Trustpilot rating for JSON-LD snippets.

    Shape::

        {
          "ratingValue": 4.7,        # 1..5, null when unavailable
          "ratingCount": 312,        # total reviews, null when unavailable
          "bestRating": 5,
          "worstRating": 1,
          "cached": true,
          "ageSeconds": 1234
        }

    Always HTTP 200 — the client is expected to render the JSON-LD only
    when ``ratingValue`` and ``ratingCount`` are both non-null.
    """
    return await _get_trustpilot_aggregate_cached()
