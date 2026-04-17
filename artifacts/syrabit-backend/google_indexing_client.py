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
    _loaded_days.clear()
    _load_locks.clear()
    global _last_flushed_day, _quota_alert_fired_day
    for k in _COUNTER_KEYS:
        _last_flushed_stats[k] = 0
    _last_flushed_day = ""
    _quota_alert_fired_day = ""


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

# Every counter field in `_stats` that should survive a restart.
# Persistence uses `$inc` with delta tracking (see `_last_flushed_stats`) so
# concurrent gunicorn workers accumulate into a shared per-day total instead
# of clobbering one another. On restart, a worker hydrates by reading the
# shared total and seeding both `_stats` and `_last_flushed_stats` to it, so
# its first flush sends a zero delta and no double-counts occur.
_COUNTER_KEYS = (
    "sent", "status_2xx", "status_4xx", "status_5xx",
    "errors", "quota_blocks", "skipped_disabled",
    "sitemap_ping_sent", "sitemap_ping_2xx", "sitemap_ping_errors",
)

_STORE_COLLECTION = "google_indexing_daily"

# Days we've successfully hydrated from the Mongo store. A rollover to a
# new day clears this so the next touch re-hydrates. Only populated AFTER
# a successful load so a transient Mongo outage on first touch doesn't
# permanently strand a worker with stale zeroed counters.
_loaded_days: set = set()

# Per-day async locks to single-flight the hydrate path: concurrent first
# requests on a fresh process all await the same load instead of racing.
_load_locks: Dict[str, "asyncio.Lock"] = {}
_load_locks_guard = threading.Lock()

# Mirror of `_stats` as of the last successful flush. Used to compute the
# delta for $inc-based persistence so multi-worker totals aggregate
# correctly. Seeded on hydrate with the stored values so the next flush
# sends a zero delta.
_last_flushed_stats: Dict[str, int] = {k: 0 for k in _COUNTER_KEYS}
_last_flushed_day: str = ""

# Daily-quota-exhausted alert dedupe. We fire AT MOST ONCE per UTC day so a
# busy fan-out batch that hits the cap doesn't spam ops with hundreds of
# identical alerts. Stored as the YYYY-MM-DD key of the day we last fired
# for; the day-rollover logic in `_roll_day_if_needed` resets it.
_quota_alert_fired_day: str = ""
_QUOTA_ALERT_TYPE = "google_indexing_quota_exhausted"
_QUOTA_ALERT_DASHBOARD_URL = (
    "https://syrabit.ai/admin/seo/google-indexing-stats"
)
# Mongo-backed cross-worker claim collection. The doc `_id` encodes the
# alert type + UTC day, so an `insert_one` with a duplicate key means a
# sibling worker already won the claim for today and we must NOT re-send.
_QUOTA_ALERT_CLAIM_COLLECTION = "google_indexing_alert_claims"


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
        # New UTC day: reset counters and force a re-hydrate on next read.
        # The previous day's totals stay in Mongo for historical queries.
        _stats.clear()
        _stats.update(_fresh_stats())
        _loaded_days.clear()
        # Allow the quota-exhausted alert to fire once again for the new day.
        global _quota_alert_fired_day
        _quota_alert_fired_day = ""


def _bump(key: str, amount: int = 1) -> None:
    with _stats_lock:
        _roll_day_if_needed()
        _stats[key] = _stats.get(key, 0) + amount
    _schedule_flush()


def _record_status_code(status_code: int) -> None:
    with _stats_lock:
        _roll_day_if_needed()
        if 200 <= status_code < 300:
            _stats["status_2xx"] = _stats.get("status_2xx", 0) + 1
        elif 400 <= status_code < 500:
            _stats["status_4xx"] = _stats.get("status_4xx", 0) + 1
        elif 500 <= status_code < 600:
            _stats["status_5xx"] = _stats.get("status_5xx", 0) + 1
    _schedule_flush()


def _under_quota_and_reserve() -> bool:
    """Atomic check-and-increment: returns True if a submission slot was
    reserved, False if the daily cap has been hit. The reservation is
    released implicitly — a failed POST still counts against the quota so
    a misconfigured service account can't hammer Google."""
    blocked = False
    sent_now = 0
    limit = 0
    day_now = ""
    with _stats_lock:
        _roll_day_if_needed()
        limit = _daily_limit()
        day_now = _stats.get("day", "")
        if _stats.get("sent", 0) >= limit:
            _stats["quota_blocks"] = _stats.get("quota_blocks", 0) + 1
            blocked = True
            sent_now = int(_stats.get("sent", 0))
        else:
            _stats["sent"] = _stats.get("sent", 0) + 1
            sent_now = int(_stats.get("sent", 0))
    _schedule_flush()
    if blocked:
        # Notify ops the very first time we hit the cap today. De-duped
        # under the stats lock so concurrent quota_blocks across coroutines
        # only schedule one alert per UTC day per process. Worker-level
        # de-dup is provided by `metrics._dispatch_alert`'s cooldown.
        _schedule_quota_alert(day_now, sent_now, limit)
    return not blocked


def _schedule_quota_alert(day: str, sent: int, limit: int) -> None:
    """Fire-and-forget the ops alert when today's Google Indexing quota is
    exhausted. At-most-once per UTC day per process. Killswitch-aware so
    the test suite doesn't dispatch alerts."""
    global _quota_alert_fired_day
    if not day:
        return
    if os.getenv("GOOGLE_INDEXING_QUOTA_ALERT_DISABLED", "").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        return
    if os.getenv("PYTEST_CURRENT_TEST") and not os.getenv(
        "GOOGLE_INDEXING_QUOTA_ALERT_IN_TESTS"
    ):
        return
    with _stats_lock:
        if _quota_alert_fired_day == day:
            return
        # Mark fired BEFORE scheduling so a sibling coroutine racing in on
        # the next quota_block doesn't queue a duplicate task.
        _quota_alert_fired_day = day
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Sync context (module imported standalone, tests). Nothing to do —
        # the next async quota_block on a real event loop will catch up if
        # we reset the fired-day below.
        with _stats_lock:
            _quota_alert_fired_day = ""
        return
    loop.create_task(_dispatch_quota_alert(day, sent, limit))


async def _claim_quota_alert_day(day: str) -> bool:
    """Atomic, cross-worker claim for "I will send today's quota alert".

    The first worker to insert `_id="<alert_type>:<day>"` into the claims
    collection wins; siblings hit `DuplicateKeyError` and bail. This is
    the same pattern used by the SEO weekly digest (`_acquire_weekly_digest_claim`).
    Returns True iff this worker should dispatch.

    If Mongo is unavailable we fall back to letting the alert fire — a
    duplicate alert during an outage is far better than silently swallowing
    a real quota-exhaustion event."""
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            logger.info(
                "google_indexing quota alert: Mongo unavailable, "
                "falling back to in-process dedupe only"
            )
            return True
    except Exception as e:
        logger.debug(
            "google_indexing quota alert: deps import failed (%s); "
            "falling back to in-process dedupe only", e,
        )
        return True
    claim_id = f"{_QUOTA_ALERT_TYPE}:{day}"
    try:
        from pymongo.errors import DuplicateKeyError
    except Exception as e:
        logger.debug("google_indexing quota alert: pymongo import failed: %s", e)
        return True
    try:
        await db[_QUOTA_ALERT_CLAIM_COLLECTION].insert_one({
            "_id": claim_id,
            "alert_type": _QUOTA_ALERT_TYPE,
            "day": day,
            "claimed_at": datetime.now(timezone.utc),
        })
        return True
    except DuplicateKeyError:
        logger.info(
            "google_indexing quota alert: another worker already claimed %s",
            claim_id,
        )
        return False
    except Exception as e:
        # Mongo hiccup mid-insert: don't lose the alert.
        logger.debug(
            "google_indexing quota alert: claim insert failed: %s; "
            "falling back to in-process dedupe only", e,
        )
        return True


async def _dispatch_quota_alert(day: str, sent: int, limit: int) -> None:
    """Send the quota-exhausted alert through the shared metrics alert
    pipeline (Resend email + webhook + admin-dashboard banner). Never
    raises — the content generator must not be impacted by alert failures.

    Cross-worker dedupe: before dispatching, race on a Mongo claim doc
    keyed by today's UTC date. Only the first worker to insert wins; the
    rest log and return without sending."""
    won_claim = await _claim_quota_alert_day(day)
    if not won_claim:
        return
    try:
        from metrics import _dispatch_alert
    except Exception as e:
        logger.debug("google_indexing quota alert: metrics import failed: %s", e)
        return
    # `metrics._dispatch_alert` enforces a global per-alert-type cooldown
    # (`_ALERT_COOLDOWN_S`, currently 30 min). Our own dedupe is already
    # day-scoped via the Mongo claim above, so a fresh quota exhaustion on
    # day N+1 just past UTC midnight could otherwise be silently swallowed
    # if day N's alert fired within the cooldown window. Clear the cooldown
    # entry for this alert type so day-boundary alerts always go through —
    # same trick `bot_discovery._seo_health_alert_loop` uses for
    # `seo_health_degraded` and `seo_url_spike`. Best-effort: imported
    # separately so a metrics module without the cooldown table (e.g. test
    # stubs) doesn't block the dispatch.
    try:
        from metrics import _alert_last_fired as _ml
        _ml.pop(_QUOTA_ALERT_TYPE, None)
    except Exception:
        pass
    title = "Google Indexing daily quota exhausted"
    body = (
        f"Google Indexing API submissions reached today's cap of "
        f"{sent}/{limit} for {day} (UTC). Additional fresh URLs will skip "
        f"Google notification until the UTC midnight rollover. To raise "
        f"the cap, set the env var GOOGLE_INDEXING_DAILY_LIMIT and restart "
        f"the API. Dashboard: {_QUOTA_ALERT_DASHBOARD_URL}"
    )
    try:
        await _dispatch_alert(
            _QUOTA_ALERT_TYPE,
            title,
            body,
            threshold_snapshot={
                "metric": "google_indexing_daily_limit",
                "value": limit,
                "actual": sent,
                "day": day,
                "dashboard_url": _QUOTA_ALERT_DASHBOARD_URL,
            },
        )
    except Exception as e:
        logger.debug("google_indexing quota alert dispatch failed: %s", e)
        # Roll back the dedupe so the next quota_block can retry the alert.
        global _quota_alert_fired_day
        with _stats_lock:
            if _quota_alert_fired_day == day:
                _quota_alert_fired_day = ""


# -----------------------------------------------------------------------------
# Persistence: load-on-first-use + $inc-delta upsert per mutation.
# Every helper here is async and never raises back to the caller; Mongo
# being down should NEVER stop the content generator from running.
# -----------------------------------------------------------------------------

async def _load_day_from_store(day: str) -> bool:
    """Hydrate `_stats` with the persisted counters for `day`. Returns
    True if the load reached Mongo (regardless of whether a doc existed
    for the day), False on Mongo-unavailable / error — caller uses this
    to decide whether to mark the day loaded."""
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return False
        doc = await db[_STORE_COLLECTION].find_one(
            {"day": day}, {"_id": 0},
        )
    except Exception as e:
        logger.debug("google_indexing store load failed: %s", e)
        return False
    global _last_flushed_day
    with _stats_lock:
        # Guard against rollover racing with the load.
        if _stats.get("day") != day:
            return True
        if doc:
            for k in _COUNTER_KEYS:
                v = doc.get(k)
                if isinstance(v, int) and v > _stats.get(k, 0):
                    _stats[k] = v
        # Seed `_last_flushed_stats` to the current in-memory view so the
        # next `_flush_to_store` sends a zero delta for anything already
        # persisted (no double-counting after restart).
        for k in _COUNTER_KEYS:
            _last_flushed_stats[k] = int(_stats.get(k, 0))
        _last_flushed_day = day
    return True


def _get_load_lock(day: str) -> "asyncio.Lock":
    with _load_locks_guard:
        lock = _load_locks.get(day)
        if lock is None:
            lock = asyncio.Lock()
            _load_locks[day] = lock
        # Opportunistic cleanup: keep only the last 3 days' locks.
        if len(_load_locks) > 3:
            stale = sorted(_load_locks.keys())[:-3]
            for s in stale:
                _load_locks.pop(s, None)
        return lock


async def _ensure_loaded() -> None:
    """Load today's counters from the store exactly once per day per
    process. Concurrent callers single-flight through a per-day lock so
    none proceed with stale zeros while hydration is in flight. If the
    load fails (Mongo unavailable or transient error) the day is NOT
    marked loaded — the next call retries."""
    with _stats_lock:
        _roll_day_if_needed()
        day = _stats.get("day")
    if not day or day in _loaded_days:
        return
    lock = _get_load_lock(day)
    async with lock:
        # Re-check under the lock in case a sibling coroutine loaded it
        # while we were waiting.
        if day in _loaded_days:
            return
        ok = await _load_day_from_store(day)
        if ok:
            _loaded_days.add(day)


async def _flush_to_store() -> None:
    """Upsert today's counters into Mongo using `$inc` on per-field
    deltas so concurrent gunicorn workers sum into a shared total
    instead of overwriting each other. Safe to call concurrently — each
    worker only reports its own uncommitted delta, and `_last_flushed_stats`
    is updated under `_stats_lock` right after the Mongo call succeeds."""
    global _last_flushed_day
    try:
        from deps import db, is_mongo_available
        if not await is_mongo_available():
            return
    except Exception as e:
        logger.debug("google_indexing store flush: deps import failed: %s", e)
        return
    with _stats_lock:
        day = _stats.get("day")
        if not day:
            return
        # Day rolled over under us: start a fresh delta baseline.
        if _last_flushed_day != day:
            for k in _COUNTER_KEYS:
                _last_flushed_stats[k] = 0
            _last_flushed_day = day
        current = {k: int(_stats.get(k, 0)) for k in _COUNTER_KEYS}
        delta = {
            k: current[k] - _last_flushed_stats.get(k, 0)
            for k in _COUNTER_KEYS
        }
        # Filter to positive deltas only; counters are monotonic within a
        # day so a negative delta means a reset we don't want to propagate.
        inc = {k: v for k, v in delta.items() if v > 0}
        if not inc:
            return
        # Optimistically advance the baseline so concurrent flushers on
        # the same worker don't double-report the same delta. If the
        # Mongo write fails below, the counters we lose are bounded to
        # one flush window (sub-second) which is acceptable for stats.
        for k in inc:
            _last_flushed_stats[k] = current[k]
    try:
        await db[_STORE_COLLECTION].update_one(
            {"day": day},
            {
                "$inc": inc,
                "$set": {
                    "day": day,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
    except Exception as e:
        logger.debug("google_indexing store flush failed: %s", e)
        # Roll the baseline back so the next flush retries this delta.
        with _stats_lock:
            if _last_flushed_day == day:
                for k, v in inc.items():
                    _last_flushed_stats[k] = max(
                        0, _last_flushed_stats.get(k, 0) - v
                    )


def _schedule_flush() -> None:
    """Fire-and-forget the persistence write. If there's no running event
    loop (module imported from a sync context, or tests) we skip silently —
    the next async mutation will catch up. Killswitch-aware."""
    if os.getenv("GOOGLE_INDEXING_PERSIST_DISABLED", "").strip().lower() in (
        "1", "true", "yes", "on"
    ):
        return
    if os.getenv("PYTEST_CURRENT_TEST") and not os.getenv(
        "GOOGLE_INDEXING_PERSIST_IN_TESTS"
    ):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_flush_to_store())


def get_stats() -> Dict[str, Any]:
    """Synchronous snapshot of today's in-memory counters + config. Does
    NOT include yesterday's totals — for the admin dashboard history view,
    use the async `get_stats_with_history` instead."""
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


async def get_stats_with_history() -> Dict[str, Any]:
    """Async variant that first hydrates today's counters from the store
    (so a fresh process shows correct values immediately), then pulls
    yesterday's persisted totals for the admin dashboard history panel."""
    await _ensure_loaded()
    snapshot = get_stats()
    # Fetch yesterday's row. Best-effort; Mongo unavailability returns None.
    from datetime import timedelta
    yesterday_key = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    yesterday: Optional[Dict[str, Any]] = None
    try:
        from deps import db, is_mongo_available
        if await is_mongo_available():
            doc = await db[_STORE_COLLECTION].find_one(
                {"day": yesterday_key}, {"_id": 0},
            )
            if doc:
                yesterday = {k: int(doc.get(k, 0)) for k in _COUNTER_KEYS}
                yesterday["day"] = yesterday_key
    except Exception as e:
        logger.debug("google_indexing yesterday fetch failed: %s", e)
    snapshot["yesterday"] = yesterday
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
    # Hydrate today's counters from Mongo on first call per day per process
    # so the quota cap survives a restart. Never raises.
    await _ensure_loaded()
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
    await _ensure_loaded()
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
