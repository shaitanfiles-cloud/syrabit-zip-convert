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

import hmac

import httpx
from fastapi import APIRouter, Body, Header, HTTPException

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
    "fail_ts": 0.0,    # timestamp of the *most recent* failure (throttles retries)
    "first_fail_ts": 0.0,  # timestamp of the *first* failure since the last success
    "last_error": None,  # short string describing the most recent fetch failure
}
_tp_aggregate_lock = asyncio.Lock()


def get_trustpilot_aggregate_health() -> Dict[str, Any]:
    """Return monitoring snapshot of the Trustpilot aggregate cache.

    Used by the admin health endpoint and the >24h alerting loop
    (Task #728). Always returns a plain dict; never raises.

    Fields:
      * ``configured``: both the API key and business unit ID are set.
      * ``has_payload``: a previously-successful fetch is cached.
      * ``last_success_ts`` / ``last_success_age_seconds``: when the
        last good fetch happened (None if we never succeeded).
      * ``last_error_ts`` / ``last_error_age_seconds`` / ``last_error``:
        most recent failure, if any.
      * ``stale``: the cached payload is past its TTL (or absent).
    """
    now = time.time()
    business_unit_id = (os.environ.get("TRUSTPILOT_BUSINESS_UNIT_ID") or "").strip()
    api_key = (os.environ.get("TRUSTPILOT_API_KEY") or "").strip()
    cached = _tp_aggregate_cache.get("payload")
    cached_ts = float(_tp_aggregate_cache.get("ts") or 0.0)
    fail_ts = float(_tp_aggregate_cache.get("fail_ts") or 0.0)
    first_fail_ts = float(_tp_aggregate_cache.get("first_fail_ts") or 0.0)
    last_error = _tp_aggregate_cache.get("last_error")
    last_success_age = int(now - cached_ts) if cached_ts else None
    last_error_age = int(now - fail_ts) if fail_ts else None
    first_error_age = int(now - first_fail_ts) if first_fail_ts else None
    return {
        "configured": bool(business_unit_id and api_key),
        "businessUnitId": business_unit_id or None,
        "ttlSeconds": _TP_AGGREGATE_TTL_S,
        "hasPayload": bool(cached),
        "lastSuccessTs": cached_ts or None,
        "lastSuccessAgeSeconds": last_success_age,
        "lastErrorTs": fail_ts or None,
        "lastErrorAgeSeconds": last_error_age,
        "firstErrorTs": first_fail_ts or None,
        "firstErrorAgeSeconds": first_error_age,
        "lastError": last_error,
        "stale": (not cached) or (last_success_age is not None
                                  and last_success_age >= _TP_AGGREGATE_TTL_S),
        "cachedPayload": cached,
    }


def _load_aggregate_override() -> Optional[Dict[str, Any]]:
    """Operator escape hatch (Task #747).

    When the production container's egress is blocked by Trustpilot's
    CloudFront/WAF (the failure mode that motivated this task), the
    operator can set ``TRUSTPILOT_AGGREGATE_OVERRIDE_JSON`` to a JSON
    blob ``{"ratingValue": 4.1, "ratingCount": 7}`` (optionally
    ``bestRating`` / ``worstRating``) and the API will serve those
    numbers as if they came from a successful upstream fetch. Returns
    ``None`` when the env var is unset or unparseable.

    Intentionally kept synchronous and dependency-free so it can be
    called from the request path without blocking on httpx/Mongo.
    """
    raw = (os.environ.get("TRUSTPILOT_AGGREGATE_OVERRIDE_JSON") or "").strip()
    if not raw:
        return None
    try:
        import json
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning(
            "TRUSTPILOT_AGGREGATE_OVERRIDE_JSON is not valid JSON: %s", exc
        )
        return None
    try:
        rv = float(parsed.get("ratingValue"))
        rc = int(parsed.get("ratingCount"))
    except (TypeError, ValueError):
        logger.warning(
            "TRUSTPILOT_AGGREGATE_OVERRIDE_JSON missing ratingValue/ratingCount: %r",
            parsed,
        )
        return None
    if not (rv > 0 and rc > 0):
        return None
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return {
        "ratingValue": round(rv, 2),
        "ratingCount": rc,
        "bestRating": _safe_int(parsed.get("bestRating"), 5),
        "worstRating": _safe_int(parsed.get("worstRating"), 1),
    }


async def _fetch_trustpilot_aggregate_remote() -> Optional[Dict[str, Any]]:
    """Call the Trustpilot Business API for the configured business unit.

    Returns ``None`` when the API key/business unit isn't configured or
    when the upstream call fails for any reason — callers fall back to
    the previously cached payload (or to omitting the JSON-LD entirely).
    """
    # Honour the env-var override BEFORE attempting the upstream call.
    # This lets the operator keep stars on the SERP even when the
    # backend container can't reach api.trustpilot.com (Task #747).
    override = _load_aggregate_override()
    if override is not None:
        return override

    business_unit_id = (os.environ.get("TRUSTPILOT_BUSINESS_UNIT_ID") or "").strip()
    api_key = (os.environ.get("TRUSTPILOT_API_KEY") or "").strip()
    if not business_unit_id or not api_key:
        _tp_aggregate_cache["last_error"] = "not_configured"
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
            _tp_aggregate_cache["last_error"] = (
                f"http_{resp.status_code}: {resp.text[:120]}"
            )
            return None
        data = resp.json()
    except Exception as exc:
        logger.exception("trustpilot aggregate API call failed")
        _tp_aggregate_cache["last_error"] = (
            f"{type(exc).__name__}: {str(exc)[:120]}"
        )
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
        _tp_aggregate_cache["last_error"] = (
            f"unparseable_response: rating={rating_value!r} count={rating_count!r}"
        )
        return None

    if rating_count_i <= 0:
        _tp_aggregate_cache["last_error"] = (
            f"non_positive_review_count: {rating_count_i}"
        )
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
            # Set first_fail_ts only on the *first* failure since the last
            # successful refresh — that's the timestamp the alerter uses to
            # decide whether the outage has crossed the >24h threshold. If
            # we overwrote this on every retry, the age would reset every
            # ~5 min (the retry throttle) and the alert would never fire.
            if not _tp_aggregate_cache.get("first_fail_ts"):
                _tp_aggregate_cache["first_fail_ts"] = _tp_aggregate_cache["fail_ts"]
            # Mirror this replica's failure into the shared health doc so
            # the alerter has a global view (Task #728). Fire-and-forget;
            # never block the request path on the DB.
            asyncio.create_task(_persist_tp_health_failure(
                _tp_aggregate_cache["fail_ts"],
                _tp_aggregate_cache.get("last_error"),
            ))
            if cached:
                # Serve stale rather than dropping stars from search results
                # the moment Trustpilot has a hiccup.
                return {**cached, "cached": True, "stale": True,
                        "ageSeconds": int(time.time() - cached_ts)}
            return {"ratingValue": None, "ratingCount": None, "cached": False}

        # Mirror success into the shared health doc so the alerter sees
        # a fresh global last-success even if the leader replica's local
        # cache is cold (Task #728). Fire-and-forget inside the helper.
        _store_aggregate_in_cache(
            fresh["ratingValue"], fresh["ratingCount"],
            fresh.get("bestRating", 5), fresh.get("worstRating", 1),
        )
        return {**fresh, "cached": False, "ageSeconds": 0}


# ─── Shared health doc (Task #728) ─────────────────────────────────────────
#
# The aggregate cache itself is per-process, but the alerter needs a
# *global* view to decide whether the feed has been broken everywhere
# for >24h. We mirror each replica's most recent fetch outcome into a
# single Mongo doc with $max semantics:
#
#   * any successful fetch on any replica advances ``last_success_ts``;
#   * the first failure (since the last global success) records
#     ``first_fail_ts`` — never bumped while it's already set.
#
# This way:
#
#   * If even one replica is succeeding, ``last_success_ts`` stays
#     fresh and the alerter does not page (correct — the SERP stars
#     are being served from somewhere).
#   * If every replica is failing, ``last_success_ts`` ages out and
#     the alerter eventually fires (correct — the feed is dead).
#   * The recovery transition can never be claimed by a replica with
#     a stale local view of "healthy" while another replica is still
#     failing, because the alerter reads the GLOBAL doc.

_TP_HEALTH_DOC_ID = "trustpilot_feed_health"


async def _persist_tp_health_success(success_ts: float) -> None:
    """Bump the global last-success timestamp and clear first_fail_ts.

    Uses ``$max`` so concurrent writes from multiple replicas can't
    accidentally regress the timestamp. Best-effort — never raises."""
    try:
        from deps import db, is_mongo_available  # type: ignore
        if not await is_mongo_available():
            return
        await db.job_locks.update_one(
            {"_id": _TP_HEALTH_DOC_ID},
            {
                "$max": {"last_success_ts": float(success_ts)},
                "$set": {
                    "first_fail_ts": 0.0,
                    "last_error": None,
                    "updated_at": time.time(),
                },
            },
            upsert=True,
        )
    except Exception:
        logger.debug("trustpilot health success persist failed", exc_info=True)


async def _persist_tp_health_failure(
    fail_ts: float, last_error: Optional[str],
) -> None:
    """Record a failure in the shared health doc.

    ``first_fail_ts`` is set only when missing/zero (preserved across
    retries — the same invariant the in-process cache holds). Best-effort
    — never raises."""
    try:
        from deps import db, is_mongo_available  # type: ignore
        if not await is_mongo_available():
            return
        await db.job_locks.update_one(
            {"_id": _TP_HEALTH_DOC_ID},
            {"$set": {
                "last_fail_ts": float(fail_ts),
                "last_error": last_error,
                "updated_at": time.time(),
            }},
            upsert=True,
        )
        # Set first_fail_ts only when absent/zero. A two-step write keeps
        # the semantics clear without needing $cond / aggregation pipeline
        # updates (which require Mongo 4.2+ and add complexity).
        await db.job_locks.update_one(
            {"_id": _TP_HEALTH_DOC_ID,
             "$or": [
                 {"first_fail_ts": {"$in": [None, 0, 0.0]}},
                 {"first_fail_ts": {"$exists": False}},
             ]},
            {"$set": {"first_fail_ts": float(fail_ts)}},
        )
    except Exception:
        logger.debug("trustpilot health failure persist failed", exc_info=True)


async def get_trustpilot_global_health() -> Dict[str, Any]:
    """Return the *global* (cross-replica) Trustpilot feed health doc.

    Falls back to the in-process snapshot when Mongo is unavailable so
    the alerter degrades gracefully. The returned dict has the same
    shape as :func:`get_trustpilot_aggregate_health`.
    """
    local = get_trustpilot_aggregate_health()
    try:
        from deps import db, is_mongo_available  # type: ignore
        if not await is_mongo_available():
            return local
        doc = await db.job_locks.find_one({"_id": _TP_HEALTH_DOC_ID})
    except Exception:
        return local
    if not doc:
        return local
    now = time.time()
    last_success_ts = float(doc.get("last_success_ts") or 0.0)
    last_fail_ts = float(doc.get("last_fail_ts") or 0.0)
    first_fail_ts = float(doc.get("first_fail_ts") or 0.0)
    return {
        **local,
        "lastSuccessTs": last_success_ts or None,
        "lastSuccessAgeSeconds": (
            int(now - last_success_ts) if last_success_ts else None
        ),
        "lastErrorTs": last_fail_ts or None,
        "lastErrorAgeSeconds": (
            int(now - last_fail_ts) if last_fail_ts else None
        ),
        "firstErrorTs": first_fail_ts or None,
        "firstErrorAgeSeconds": (
            int(now - first_fail_ts) if first_fail_ts else None
        ),
        "lastError": doc.get("last_error"),
        "global": True,
    }


def _store_aggregate_in_cache(
    rating_value: float,
    rating_count: int,
    best_rating: int = 5,
    worst_rating: int = 1,
) -> Dict[str, Any]:
    """Write a fresh aggregate into the in-process cache.

    Used by both the live-fetch path and the off-host refresh webhook
    (Task #749 — when this container's egress is WAF-blocked, an
    external cron POSTs values it fetched from a non-blocked IP).
    Resets failure bookkeeping and mirrors success into the shared
    health doc so the >24h staleness alert clears.
    """
    payload = {
        "ratingValue": round(float(rating_value), 2),
        "ratingCount": int(rating_count),
        "bestRating": int(best_rating),
        "worstRating": int(worst_rating),
    }
    _tp_aggregate_cache["payload"] = payload
    _tp_aggregate_cache["ts"] = time.time()
    _tp_aggregate_cache["fail_ts"] = 0.0
    _tp_aggregate_cache["first_fail_ts"] = 0.0
    _tp_aggregate_cache["last_error"] = None
    asyncio.create_task(_persist_tp_health_success(_tp_aggregate_cache["ts"]))
    return payload


@router.post("/api/config/trustpilot/aggregate/refresh")
async def refresh_trustpilot_aggregate(
    body: Dict[str, Any] = Body(...),
    x_trustpilot_refresh_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Externally-triggered refresh of the in-process Trustpilot cache.

    Task #749 — the production container's egress is WAF-blocked from
    Trustpilot's CloudFront, so the backend's own
    :func:`_fetch_trustpilot_aggregate_remote` always fails and the
    >24h staleness alert fires. A scheduled job that runs from a host
    Trustpilot does not block (GitHub Actions runner) fetches the
    Business API itself and POSTs the values here so this replica's
    cache (and the shared health doc) stay current.

    Auth: shared secret in the ``X-Trustpilot-Refresh-Secret`` header,
    matched against ``TRUSTPILOT_REFRESH_SECRET``. Returns 503 when the
    secret env var isn't configured (so a forgotten-secret deploy
    fails closed instead of accepting anonymous writes), 401 on
    mismatch, 422 on invalid payload.
    """
    expected = (os.environ.get("TRUSTPILOT_REFRESH_SECRET") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="trustpilot_refresh_secret_not_configured",
        )
    provided = (x_trustpilot_refresh_secret or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid_refresh_secret")

    try:
        rating_value = float(body.get("ratingValue"))
        rating_count = int(body.get("ratingCount"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="ratingValue (number) and ratingCount (int) are required",
        )
    if not (rating_value > 0 and rating_count > 0):
        raise HTTPException(
            status_code=422,
            detail="ratingValue and ratingCount must be positive",
        )

    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    best = _safe_int(body.get("bestRating"), 5)
    worst = _safe_int(body.get("worstRating"), 1)

    payload = _store_aggregate_in_cache(rating_value, rating_count, best, worst)
    logger.info(
        "trustpilot aggregate refreshed via webhook: %s★ (%d reviews) source=%s",
        payload["ratingValue"], payload["ratingCount"],
        (body.get("source") or "external_webhook"),
    )
    return {
        "ok": True,
        **payload,
        "ageSeconds": 0,
        "source": body.get("source") or "external_webhook",
    }


# ─── Refresh-cron heartbeat (Task #751) ────────────────────────────────────
#
# The /api/config/trustpilot/aggregate/refresh webhook above is fed by a
# daily GitHub Actions cron (.github/workflows/trustpilot-aggregate-
# refresh.yml). If THAT workflow itself silently stops running
# (disabled, repo-renamed, secret expired, GitHub-side outage), nothing
# notices for >24h until the data-staleness alerter (Task #728) fires —
# but that alert is also the only signal that the upstream Trustpilot
# fetch is broken, so on-call can't tell which problem they have.
#
# We give the cron a separate, unconditional heartbeat channel: the
# workflow POSTs here on every run regardless of the Trustpilot fetch
# outcome. A dedicated alerter (routes/admin_trustpilot_cron_alerts.py)
# pages when no heartbeat has arrived in >36h, distinct from the
# data-staleness alert.

_TP_REFRESH_CRON_HEALTH_DOC_ID = "trustpilot_refresh_cron_health"


async def get_trustpilot_refresh_cron_health() -> Dict[str, Any]:
    """Return the heartbeat snapshot for the daily refresh cron.

    Always returns a plain dict; never raises. Falls back to a
    not-configured shape when Mongo is unavailable so the alerter
    degrades gracefully (treats it as "unknown" → never pages).
    """
    expected_secret = bool((os.environ.get("TRUSTPILOT_REFRESH_SECRET") or "").strip())
    base = {
        "configured": expected_secret,
        "lastHeartbeatTs": None,
        "lastHeartbeatAgeSeconds": None,
        "lastSuccessHeartbeatTs": None,
        "lastSuccessHeartbeatAgeSeconds": None,
        "lastStatus": None,
        "lastRc": None,
        "lastRunUrl": None,
        "lastSuccessRunUrl": None,
        "lastWorkflowUrl": None,
        "lastRunId": None,
        "firstObservedTs": None,
    }
    try:
        from deps import db, is_mongo_available  # type: ignore
        if not await is_mongo_available():
            return base
        doc = await db.job_locks.find_one(
            {"_id": _TP_REFRESH_CRON_HEALTH_DOC_ID}
        )
    except Exception:
        return base
    if not doc:
        return base
    now = time.time()
    last_hb_ts = float(doc.get("last_heartbeat_ts") or 0.0) or None
    last_success_hb_ts = (
        float(doc.get("last_success_heartbeat_ts") or 0.0) or None
    )
    first_obs_ts = float(doc.get("first_observed_ts") or 0.0) or None
    return {
        **base,
        "lastHeartbeatTs": last_hb_ts,
        "lastHeartbeatAgeSeconds": (
            int(now - last_hb_ts) if last_hb_ts else None
        ),
        "lastSuccessHeartbeatTs": last_success_hb_ts,
        "lastSuccessHeartbeatAgeSeconds": (
            int(now - last_success_hb_ts) if last_success_hb_ts else None
        ),
        "lastStatus": doc.get("last_status"),
        "lastRc": doc.get("last_rc"),
        "lastRunUrl": doc.get("last_run_url"),
        "lastSuccessRunUrl": doc.get("last_success_run_url"),
        "lastWorkflowUrl": doc.get("last_workflow_url"),
        "lastRunId": doc.get("last_run_id"),
        "firstObservedTs": first_obs_ts,
    }


@router.post("/api/config/trustpilot/refresh-cron-heartbeat")
async def refresh_trustpilot_cron_heartbeat(
    body: Dict[str, Any] = Body(default={}),
    x_trustpilot_refresh_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Heartbeat ping from the daily refresh GitHub Actions workflow.

    Task #751 — the workflow calls this on every run (success OR
    failure of the inner Trustpilot fetch) so the >36h "cron silent"
    alert can distinguish between "Trustpilot is down" and "our cron
    has been disabled".

    Auth: same shared secret as the refresh webhook
    (``TRUSTPILOT_REFRESH_SECRET`` header). Returns 503 when the
    secret env var isn't configured (fails closed). Always 200 on
    success. Body fields (all optional, best-effort recorded):

      * ``status``: ``"success"`` | ``"partial"`` | ``"failure"``
      * ``rc``: integer exit code from refresh-trustpilot-aggregate.mjs
      * ``runUrl``: link to the specific GitHub Actions run page
      * ``workflowUrl``: link to the workflow's run history
      * ``runId``: ``${{ github.run_id }}``
    """
    expected = (os.environ.get("TRUSTPILOT_REFRESH_SECRET") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="trustpilot_refresh_secret_not_configured",
        )
    provided = (x_trustpilot_refresh_secret or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid_refresh_secret")

    status = (body.get("status") or "").strip() or None
    if status and status not in {"success", "partial", "failure"}:
        # Be permissive — record what we got but don't 422 the workflow.
        status = status[:32]
    rc_raw = body.get("rc")
    try:
        rc = int(rc_raw) if rc_raw is not None else None
    except (TypeError, ValueError):
        rc = None
    run_url = (str(body.get("runUrl") or "").strip() or None)
    workflow_url = (str(body.get("workflowUrl") or "").strip() or None)
    run_id = (str(body.get("runId") or "").strip() or None)
    now_ts = time.time()

    try:
        from deps import db, is_mongo_available  # type: ignore
        if await is_mongo_available():
            # Track BOTH a "last heartbeat of any kind" timestamp (so the
            # dashboard can distinguish "cron ran but failed" from "cron
            # is silent") AND a "last successful heartbeat" timestamp
            # (status=success only) — the silence alerter uses the
            # latter so a perpetually-failing cron still pages after
            # >36h of no successful runs, matching the task spec wording
            # of "last-success age > 36h".
            max_payload: Dict[str, Any] = {"last_heartbeat_ts": float(now_ts)}
            set_payload: Dict[str, Any] = {
                "last_status": status,
                "last_rc": rc,
                "last_run_url": run_url,
                "last_workflow_url": workflow_url,
                "last_run_id": run_id,
                "updated_at": now_ts,
            }
            if status == "success":
                max_payload["last_success_heartbeat_ts"] = float(now_ts)
                set_payload["last_success_run_url"] = run_url
            await db.job_locks.update_one(
                {"_id": _TP_REFRESH_CRON_HEALTH_DOC_ID},
                {
                    "$max": max_payload,
                    "$set": set_payload,
                    "$setOnInsert": {"first_observed_ts": float(now_ts)},
                },
                upsert=True,
            )
    except Exception:
        logger.debug(
            "trustpilot refresh-cron heartbeat persist failed", exc_info=True
        )

    logger.info(
        "trustpilot refresh-cron heartbeat: status=%s rc=%s run=%s",
        status, rc, run_url,
    )
    return {"ok": True, "ts": now_ts}


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
