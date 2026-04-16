"""Google Indexing API + sitemap-ping client (SEO Phase C).

Why this module exists
----------------------
Google does not consume IndexNow, so every Phase A content-time signal
(IndexNow + Cloudflare cache purge + synthetic Googlebot prewarm) misses
the search engine that drives ~96% of Syrabit's bot traffic. Google
instead relies on natural sitemap polling, which typically takes 3–7 days
before a freshly-generated URL gets indexed.

Phase C adds two Google-side notifications that run alongside the Phase A
fan-out:

1. `notify_url_updated(url)` — POSTs to `urlNotifications:publish` with
   `type=URL_UPDATED`. Authenticated via a service-account JWT minted by
   `google-auth` (already pinned in `requirements.txt`). Token is cached
   for ~50 min to stay well within the 60 min lifetime.

2. `ping_sitemap(sitemap_url)` — GET
   `https://www.google.com/ping?sitemap=<sitemap>`. Free, unauthenticated,
   kept alive by Google for decades.

Safety rails
------------
- 5 s timeout on every outbound call; exceptions are logged but NEVER
  re-raised, so the content generator can't block or fail because of us.
- Daily in-memory quota cap (default 200/day, configurable via env
  `GOOGLE_INDEXING_DAILY_LIMIT`). When the quota is reached the client
  short-circuits further `notify_url_updated` calls for the rest of the
  UTC day.
- Missing `GOOGLE_INDEXING_SERVICE_ACCOUNT` secret is treated as
  "disabled" — we log a one-time warning and every `notify_url_updated`
  call returns a structured "skipped" result. Sitemap-ping still works.
- Killswitch via env `GOOGLE_INDEXING_ENABLED=false`.

Stats exposed via `get_stats()` and surfaced through the admin endpoint
`GET /admin/seo/google-indexing-stats`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants / configuration
# -----------------------------------------------------------------------------

INDEXING_API_URL = "https://indexing.googleapis.com/v3/urlNotifications:publish"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
SITEMAP_PING_URL_TPL = "https://www.google.com/ping?sitemap={sitemap}"
SCOPE = "https://www.googleapis.com/auth/indexing"

# Token lifetime is 3600 s; refresh at 3000 s to leave a safety margin.
_TOKEN_CACHE_TTL_S = 3000
# Outbound network timeout. The task spec mandates 5 s so the content
# generator can't be held up by Google's side.
_HTTP_TIMEOUT_S = 5.0

_DEFAULT_DAILY_LIMIT = 200


def _daily_limit() -> int:
    raw = os.getenv("GOOGLE_INDEXING_DAILY_LIMIT")
    if not raw:
        return _DEFAULT_DAILY_LIMIT
    try:
        v = int(raw)
        return v if v >= 0 else _DEFAULT_DAILY_LIMIT
    except (TypeError, ValueError):
        return _DEFAULT_DAILY_LIMIT


def _enabled() -> bool:
    """Killswitch. Defaults to enabled in prod, disabled under pytest so
    existing test suites don't start making outbound calls."""
    raw = os.getenv("GOOGLE_INDEXING_ENABLED")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return True


# -----------------------------------------------------------------------------
# Service-account loading (lazy, cached, never raises)
# -----------------------------------------------------------------------------

_sa_lock = threading.Lock()
_sa_info: Optional[Dict[str, Any]] = None
_sa_load_attempted = False
_sa_load_error: Optional[str] = None


def _load_service_account() -> Optional[Dict[str, Any]]:
    """Parse `GOOGLE_INDEXING_SERVICE_ACCOUNT` once. The secret may be raw
    JSON or a base64-encoded JSON string (some operators paste it
    that way to avoid newlines-in-env issues)."""
    global _sa_info, _sa_load_attempted, _sa_load_error
    with _sa_lock:
        if _sa_load_attempted:
            return _sa_info
        _sa_load_attempted = True
        raw = os.getenv("GOOGLE_INDEXING_SERVICE_ACCOUNT", "").strip()
        if not raw:
            _sa_load_error = "missing_secret"
            logger.warning(
                "google_indexing_client: GOOGLE_INDEXING_SERVICE_ACCOUNT is "
                "not set — Indexing API calls will be skipped. Sitemap-ping "
                "still works."
            )
            return None
        # Support base64-encoded JSON as a fallback.
        candidate = raw
        if not candidate.lstrip().startswith("{"):
            try:
                import base64
                candidate = base64.b64decode(raw).decode("utf-8")
            except Exception as e:
                _sa_load_error = f"b64_decode_failed:{type(e).__name__}"
                logger.error(
                    "google_indexing_client: secret is neither JSON nor valid "
                    "base64: %s", e,
                )
                return None
        try:
            info = json.loads(candidate)
        except json.JSONDecodeError as e:
            _sa_load_error = f"json_decode_failed:{e.msg}"
            logger.error(
                "google_indexing_client: secret is not valid JSON: %s", e,
            )
            return None
        required = {"client_email", "private_key", "token_uri"}
        missing = required - set(info.keys())
        if missing:
            _sa_load_error = f"missing_fields:{sorted(missing)}"
            logger.error(
                "google_indexing_client: service-account JSON missing fields: %s",
                sorted(missing),
            )
            return None
        _sa_info = info
        return _sa_info


def _reset_state_for_tests() -> None:
    """Reset every bit of module-level cache. Tests use this to get a clean
    slate (fresh counters + fresh service-account cache)."""
    global _sa_info, _sa_load_attempted, _sa_load_error
    global _cached_token, _cached_token_expires_at
    with _sa_lock:
        _sa_info = None
        _sa_load_attempted = False
        _sa_load_error = None
    with _token_lock:
        _cached_token = None
        _cached_token_expires_at = 0.0
    with _stats_lock:
        _stats.clear()
        _stats.update(_fresh_stats())


# -----------------------------------------------------------------------------
# OAuth token cache (JWT-bearer → access_token)
# -----------------------------------------------------------------------------

_token_lock = threading.Lock()
_cached_token: Optional[str] = None
_cached_token_expires_at: float = 0.0  # monotonic epoch-seconds
# Async single-flight lock: during a burst of Phase A fan-outs several
# coroutines may all see an empty cache and race to mint a token. Without
# this guard each one hits oauth2.googleapis.com, which both wastes quota
# and can produce mild thundering-herd latency spikes. We hold this lock
# only around the mint call; the read-side fast path is still lock-free.
_token_refresh_lock: Optional[asyncio.Lock] = None


def _get_refresh_lock() -> asyncio.Lock:
    global _token_refresh_lock
    if _token_refresh_lock is None:
        _token_refresh_lock = asyncio.Lock()
    return _token_refresh_lock


async def _mint_access_token() -> Optional[str]:
    """Mint an OAuth2 access token using the service-account JWT-bearer
    flow. `google.oauth2.service_account.Credentials` builds the signed
    JWT for us; we then exchange it with Google's OAuth token endpoint
    over an async httpx call so we never block the event loop."""
    info = _load_service_account()
    if not info:
        return None
    try:
        # google-auth is pinned in requirements.txt as google-auth==2.49.1.
        from google.oauth2 import service_account
        import google.auth.crypt
        import google.auth.jwt
    except Exception as e:  # pragma: no cover — lib is always installed in prod
        logger.error("google_indexing_client: google-auth import failed: %s", e)
        return None

    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=[SCOPE],
        )
    except Exception as e:
        logger.error("google_indexing_client: bad service-account key: %s", e)
        return None

    # Build the assertion JWT manually so we can do the token exchange
    # over httpx (google-auth's default transport is sync urllib3).
    try:
        signer = creds._signer  # pylint: disable=protected-access
        now = int(datetime.now(timezone.utc).timestamp())
        payload = {
            "iss": info["client_email"],
            "scope": SCOPE,
            "aud": info.get("token_uri", OAUTH_TOKEN_URL),
            "iat": now,
            "exp": now + 3600,
        }
        assertion = google.auth.jwt.encode(signer, payload).decode("utf-8")
    except Exception as e:
        logger.error("google_indexing_client: JWT signing failed: %s", e)
        return None

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.post(
                info.get("token_uri", OAUTH_TOKEN_URL),
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as e:
        logger.warning("google_indexing_client: token endpoint error: %s", e)
        return None

    if resp.status_code != 200:
        logger.warning(
            "google_indexing_client: token exchange failed: %s %s",
            resp.status_code, resp.text[:200],
        )
        return None
    try:
        data = resp.json()
    except Exception as e:
        logger.warning("google_indexing_client: token body parse failed: %s", e)
        return None
    token = data.get("access_token")
    if not token:
        logger.warning("google_indexing_client: token response missing access_token")
        return None
    return token


async def _get_cached_token() -> Optional[str]:
    global _cached_token, _cached_token_expires_at
    loop = asyncio.get_event_loop()
    now = loop.time()
    # Fast path: cache hit, no lock needed — the threading.Lock only guards
    # the pointer write below. A stale read here is harmless; the worst case
    # is that we re-enter the refresh lock and see the fresh token there.
    with _token_lock:
        if _cached_token and now < _cached_token_expires_at:
            return _cached_token

    # Slow path: single-flight refresh. The first coroutine to enter mints
    # a token; subsequent coroutines wait, re-check the cache, and return
    # the freshly-minted token instead of firing their own mint request.
    async with _get_refresh_lock():
        with _token_lock:
            if _cached_token and loop.time() < _cached_token_expires_at:
                return _cached_token
        new_token = await _mint_access_token()
        if not new_token:
            return None
        with _token_lock:
            _cached_token = new_token
            _cached_token_expires_at = loop.time() + _TOKEN_CACHE_TTL_S
        return new_token


# -----------------------------------------------------------------------------
# Daily-quota + stats counters
# -----------------------------------------------------------------------------

_stats_lock = threading.Lock()


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fresh_stats() -> Dict[str, Any]:
    return {
        "day": _today_key(),
        "sent": 0,
        "status_2xx": 0,
        "status_4xx": 0,
        "status_5xx": 0,
        "errors": 0,
        "quota_blocks": 0,
        "skipped_disabled": 0,
        "sitemap_ping_sent": 0,
        "sitemap_ping_2xx": 0,
        "sitemap_ping_errors": 0,
    }


_stats: Dict[str, Any] = _fresh_stats()


def _roll_day_if_needed() -> None:
    today = _today_key()
    if _stats.get("day") != today:
        _stats.clear()
        _stats.update(_fresh_stats())


def _bump(key: str, amount: int = 1) -> None:
    with _stats_lock:
        _roll_day_if_needed()
        _stats[key] = _stats.get(key, 0) + amount


def _record_status_code(status_code: int) -> None:
    with _stats_lock:
        _roll_day_if_needed()
        if 200 <= status_code < 300:
            _stats["status_2xx"] = _stats.get("status_2xx", 0) + 1
        elif 400 <= status_code < 500:
            _stats["status_4xx"] = _stats.get("status_4xx", 0) + 1
        elif 500 <= status_code < 600:
            _stats["status_5xx"] = _stats.get("status_5xx", 0) + 1


def _under_quota_and_reserve() -> bool:
    """Atomic check-and-increment: returns True if a submission slot was
    reserved, False if the daily cap has been hit. The reservation is
    released implicitly — a failed POST still counts against the quota so
    a misconfigured service account can't hammer Google."""
    with _stats_lock:
        _roll_day_if_needed()
        limit = _daily_limit()
        if _stats.get("sent", 0) >= limit:
            _stats["quota_blocks"] = _stats.get("quota_blocks", 0) + 1
            return False
        _stats["sent"] = _stats.get("sent", 0) + 1
        return True


def get_stats() -> Dict[str, Any]:
    """Snapshot of today's counters + config. Admin endpoint wraps this."""
    with _stats_lock:
        _roll_day_if_needed()
        snapshot = dict(_stats)
    limit = _daily_limit()
    snapshot["daily_limit"] = limit
    snapshot["quota_remaining"] = max(0, limit - snapshot.get("sent", 0))
    snapshot["enabled"] = _enabled()
    snapshot["service_account_loaded"] = _load_service_account() is not None
    snapshot["service_account_error"] = _sa_load_error
    return snapshot


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

async def notify_url_updated(url: str, source: str = "content_fanout") -> Dict[str, Any]:
    """Send `type=URL_UPDATED` to the Indexing API for `url`. Returns a
    small result dict so callers (and tests) can verify what happened.
    Never raises."""
    result: Dict[str, Any] = {"url": url, "status": "skipped", "reason": ""}
    if not url or not isinstance(url, str):
        result["reason"] = "empty_url"
        return result
    if not _enabled():
        result["reason"] = "disabled"
        _bump("skipped_disabled")
        return result
    info = _load_service_account()
    if not info:
        result["reason"] = "no_service_account"
        _bump("skipped_disabled")
        return result
    if not _under_quota_and_reserve():
        result["status"] = "quota_blocked"
        result["reason"] = "daily_limit_reached"
        return result

    token = await _get_cached_token()
    if not token:
        result["status"] = "error"
        result["reason"] = "token_mint_failed"
        _bump("errors")
        return result

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.post(
                INDEXING_API_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"url": url, "type": "URL_UPDATED"},
            )
    except Exception as e:
        logger.warning(
            "google_indexing_client: publish error url=%s err=%s", url, e,
        )
        result["status"] = "error"
        result["reason"] = f"{type(e).__name__}"
        _bump("errors")
        return result

    _record_status_code(resp.status_code)
    result["http_status"] = resp.status_code
    result["source"] = source
    if 200 <= resp.status_code < 300:
        result["status"] = "ok"
    elif resp.status_code in (401, 403):
        # Token likely expired mid-call; force a mint on next submission.
        with _token_lock:
            global _cached_token_expires_at
            _cached_token_expires_at = 0.0
        result["status"] = "auth_error"
        result["reason"] = resp.text[:200]
        logger.warning(
            "google_indexing_client: auth error %s for %s: %s",
            resp.status_code, url, resp.text[:200],
        )
    elif resp.status_code == 429:
        result["status"] = "quota_error"
        result["reason"] = "google_quota_exceeded"
        logger.warning("google_indexing_client: Google quota 429 for %s", url)
    else:
        result["status"] = "error"
        result["reason"] = f"http_{resp.status_code}"
        logger.warning(
            "google_indexing_client: publish non-2xx %s url=%s body=%s",
            resp.status_code, url, resp.text[:200],
        )
    return result


async def ping_sitemap(sitemap_url: str = "https://syrabit.ai/sitemap-index.xml") -> Dict[str, Any]:
    """Ping Google's legacy sitemap-ping endpoint. Unauthenticated, free,
    documented at developers.google.com/search/docs. Never raises."""
    result: Dict[str, Any] = {
        "sitemap": sitemap_url,
        "status": "skipped",
        "reason": "",
    }
    if not _enabled():
        result["reason"] = "disabled"
        return result
    ping_url = SITEMAP_PING_URL_TPL.format(sitemap=quote(sitemap_url, safe=""))
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.get(ping_url)
    except Exception as e:
        logger.warning("google_indexing_client: sitemap ping error: %s", e)
        _bump("sitemap_ping_errors")
        result["status"] = "error"
        result["reason"] = f"{type(e).__name__}"
        return result
    _bump("sitemap_ping_sent")
    result["http_status"] = resp.status_code
    if 200 <= resp.status_code < 300:
        _bump("sitemap_ping_2xx")
        result["status"] = "ok"
    else:
        result["status"] = "error"
        result["reason"] = f"http_{resp.status_code}"
        logger.info(
            "google_indexing_client: sitemap ping non-2xx %s for %s",
            resp.status_code, sitemap_url,
        )
    return result
