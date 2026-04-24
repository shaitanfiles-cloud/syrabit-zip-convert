"""Syrabit.ai — ASGI middleware classes."""
import os, re, time as _time_mod, logging, uuid, contextvars, hashlib, asyncio
from datetime import datetime, timezone, timedelta
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from config import SECURE_COOKIES, PLAN_LIMITS
from auth_deps import check_rate_limit, decode_token
from cache import _redis_get_session
from metrics import _metrics

logger = logging.getLogger(__name__)

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


# ── BaseHTTPMiddleware "No response returned." race guard ───────────────────
#
# Starlette's BaseHTTPMiddleware wraps the inner ASGI app in an anyio
# TaskGroup. When a client (CF Worker, browser, Railway healthcheck) closes
# the connection between when `call_next` is awaited and when the inner
# handler tries to send the response, the inner task is cancelled and exits
# without producing a Response. BaseHTTPMiddleware then raises:
#
#     RuntimeError("No response returned.")
#
# This is a benign race — the client is already gone, so there is nothing
# to send a response to. But Starlette surfaces it as an unhandled
# exception, which pollutes the error log and (on some platforms) trips
# alerts. We wrap every `call_next` site through this helper, which
# downgrades the race to a single INFO line and returns a sentinel 499
# Response. The sentinel is never delivered (no client to deliver it to)
# but lets each middleware's bookkeeping (`response.headers`, status_code
# recording, finally blocks) execute without secondary exceptions.
#
# Real handler errors (anything other than this exact RuntimeError text)
# continue to propagate untouched.
async def _safe_call_next(call_next, request: StarletteRequest):
    from starlette.responses import Response
    try:
        return await call_next(request)
    except RuntimeError as exc:
        if str(exc) == "No response returned.":
            rid = getattr(request.state, "request_id", "") or "-"
            logger.info(
                f"[client-disconnect] {request.method} {request.url.path} "
                f"rid={rid} (BaseHTTPMiddleware race; client closed connection)"
            )
            return Response(status_code=499)
        raise

def _env_bool(key: str, default: bool = True) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")

_SEC_HSTS = _env_bool("SEC_HSTS", True)
_SEC_XCTO = _env_bool("SEC_XCTO", True)
_SEC_XFRAME = _env_bool("SEC_XFRAME", True)
_SEC_REFERRER = _env_bool("SEC_REFERRER", True)
_SEC_PERM = _env_bool("SEC_PERM", True)
_SEC_CSP_REPORT_ONLY = _env_bool("SEC_CSP_REPORT_ONLY", False)

_CSP_VALUE = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.googletagmanager.com https://accounts.google.com https://apis.google.com https://widget.trustpilot.com https://challenges.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://accounts.google.com https://widget.trustpilot.com; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' https:; "
    "frame-src https://accounts.google.com https://widget.trustpilot.com https://challenges.cloudflare.com; "
    "frame-ancestors 'self'; "
    "report-uri /api/security/csp-report"
)


_ORIGIN_SHARED_SECRET = os.environ.get("ORIGIN_SHARED_SECRET", "").strip()
_ORIGIN_AUTH_HEADER = os.environ.get("ORIGIN_SHARED_SECRET_HEADER", "X-Origin-Auth").strip() or "X-Origin-Auth"
# Paths that must remain reachable without the shared-secret header so Cloud
# Run's own startup/liveness probes keep working. Kept deliberately tiny:
# /docs and /openapi.json used to be open during early bring-up but were
# removed so the *.run.app URL exposes nothing more than health to the
# unauthenticated public — every other endpoint requires the edge-injected
# header when ORIGIN_SHARED_SECRET is set.
_ORIGIN_AUTH_OPEN_PATHS = (
    "/api/health",
    "/health",
)


class OriginSharedSecretMiddleware:
    """Reject requests that did not flow through the Cloudflare edge worker.

    When ``ORIGIN_SHARED_SECRET`` is set in the environment, every non-open
    request must carry a matching header (default ``X-Origin-Auth``). The
    edge worker injects this header on every backend fetch. This is the
    application-layer equivalent of authenticated origin pull and is what
    keeps the Cloud Run URL from being directly reachable by the public
    internet (in addition to the Cloud Run ingress allowlist).

    Disabled (no enforcement, no overhead) when the env var is empty so the
    backend keeps working unchanged on the legacy Railway origin until the
    cutover is complete.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or not _ORIGIN_SHARED_SECRET:
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path == p or path.startswith(p) for p in _ORIGIN_AUTH_OPEN_PATHS):
            await self.app(scope, receive, send)
            return
        # Header lookup: scope["headers"] is a list of (bytes, bytes) tuples.
        wanted = _ORIGIN_AUTH_HEADER.lower().encode("latin-1")
        provided = b""
        for k, v in scope.get("headers", []):
            if k == wanted:
                provided = v
                break
        if provided and provided.decode("latin-1", "ignore") == _ORIGIN_SHARED_SECRET:
            await self.app(scope, receive, send)
            return
        from fastapi.responses import JSONResponse
        resp = JSONResponse(
            status_code=403,
            content={"detail": "Direct origin access denied — must traverse the edge worker."},
        )
        await resp(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if _SEC_XCTO:
                    headers.append("X-Content-Type-Options", "nosniff")
                if _SEC_XFRAME:
                    headers.append("X-Frame-Options", "SAMEORIGIN")
                if _SEC_REFERRER:
                    headers.append("Referrer-Policy", "strict-origin-when-cross-origin")
                if _SEC_PERM:
                    headers.append("Permissions-Policy", "camera=(), microphone=(), geolocation=(), identity-credentials-get=(self https://accounts.google.com)")
                headers.append("X-XSS-Protection", "1; mode=block")
                if _SEC_HSTS and SECURE_COOKIES:
                    headers.append("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
                if _SEC_CSP_REPORT_ONLY:
                    headers.append("Content-Security-Policy-Report-Only", _CSP_VALUE)
                else:
                    headers.append("Content-Security-Policy", _CSP_VALUE)
                ct = headers.get("content-type", "")
                if "text/html" in ct:
                    headers.append("Content-Language", "en-IN")
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


# ── DeviceCookieMiddleware (Task #793) ────────────────────────────────
# The chat rate-limit dependency (``auth_deps.rate_limit_chat_optional``)
# may need to mint a fresh ``syrabit_device`` cookie for first-visit
# anonymous traffic. It tries to do so by calling ``set_cookie`` on
# the ``Response`` parameter FastAPI injects into the dependency.
#
# That works fine when the route handler returns a JSON-serialisable
# value (FastAPI builds the response from the injected ``Response``
# object), but it does **not** work when the route handler returns a
# concrete ``Response`` instance of its own — the most common case
# here is ``StreamingResponse`` on ``/ai/chat/stream``, which is the
# user-facing chat path. In that case FastAPI uses the route's
# response and discards the dependency-injected one, so the freshly
# minted device cookie is silently dropped on the floor and the
# client never persists it. Effective behaviour collapses back to
# coarse per-IP enforcement, which defeats the entire point of
# Task #793.
#
# This middleware is the safety net: when the dependency mints a
# cookie it also stashes the value on ``request.state.device_cookie_to_set``;
# we read that back on the way out and append the ``Set-Cookie``
# header to whichever response the handler ultimately produced — but
# only if no ``syrabit_device`` cookie is already on the response (so
# we don't double-set when FastAPI's normal merge actually did work,
# e.g. on the JSON ``/ai/chat`` path).
class DeviceCookieMiddleware:
    """Re-apply the freshly-minted device cookie to whatever response
    the route handler returned. See module-level comment above for
    the failure mode this guards against.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Lazy import so this module stays importable even when
        # device_token / auth_deps haven't been initialised yet (e.g.
        # in test bootstrap).
        from device_token import DEVICE_COOKIE_NAME
        from auth_deps import _set_device_cookie  # type: ignore
        from starlette.responses import Response as _Response

        # Build a real Starlette request once so we can read its
        # ``state`` after the inner app has run. ``state`` is a plain
        # attribute namespace shared between the request and any
        # ASGI-level code that pulls a Request out of the scope.
        request = StarletteRequest(scope, receive)

        async def send_with_device_cookie(message):
            if message["type"] == "http.response.start":
                pending = getattr(request.state, "device_cookie_to_set", None)
                if pending:
                    headers = MutableHeaders(scope=message)
                    # Skip if the route handler already set the same
                    # cookie (e.g. JSON /ai/chat where the injected
                    # Response did get merged in normally) so we
                    # never double-emit Set-Cookie.
                    already = any(
                        v.startswith(f"{DEVICE_COOKIE_NAME}=")
                        for v in headers.getlist("set-cookie")
                    )
                    if not already:
                        # Use a throwaway Response purely to format
                        # the Set-Cookie value with the same flags
                        # (HttpOnly / Secure / SameSite / max-age /
                        # domain) the dependency uses, then transplant
                        # it onto the live outgoing headers.
                        scratch = _Response()
                        try:
                            _set_device_cookie(request, scratch, pending)
                            for cookie_value in scratch.headers.getlist("set-cookie"):
                                headers.append("set-cookie", cookie_value)
                        except Exception as exc:  # pragma: no cover — defensive
                            logger.warning(
                                f"DeviceCookieMiddleware: failed to apply pending cookie: {exc}"
                            )
            await send(message)

        await self.app(scope, receive, send_with_device_cookie)


from utils import _SEARCH_BOT_UA_RE, _ABUSIVE_SCRAPER_UA_RE, _TRAINING_SCRAPER_UA_RE, verify_bot_ip

_BOT_RATE_LIMIT = 1200

_blocked_ip_hashes: set[str] = set()
_blocked_ip_lock = __import__("threading").Lock()


async def _refresh_blocked_ip_cache():
    try:
        from deps import db, is_mongo_available
        if await is_mongo_available():
            docs = await db.blocked_ips.find({}, {"ip_hash": 1, "expires_at": 1, "_id": 0}).to_list(10000)
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc)
            new_set = set()
            for d in docs:
                if not d.get("ip_hash"):
                    continue
                ea = d.get("expires_at")
                if ea is not None and ea <= now:
                    continue
                new_set.add(d["ip_hash"])
            with _blocked_ip_lock:
                changed = new_set != _blocked_ip_hashes
                _blocked_ip_hashes.clear()
                _blocked_ip_hashes.update(new_set)
            if changed:
                logger.info(f"Blocked IP cache updated: {len(new_set)} entries")
    except Exception as e:
        logger.debug(f"blocked IP cache refresh failed: {e}")


_BLOCKED_IP_REFRESH_INTERVAL = 10
_EXPIRED_IP_CLEANUP_COUNTER = 0

async def _cleanup_expired_blocked_ips():
    try:
        from deps import db, is_mongo_available
        if await is_mongo_available():
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc)
            expired_docs = await db.blocked_ips.find(
                {"expires_at": {"$lte": now}, "auto_blocked": True},
                {"ip_hash": 1, "_id": 1},
            ).to_list(500)
            if expired_docs:
                ids = [d["_id"] for d in expired_docs]
                result = await db.blocked_ips.delete_many({"_id": {"$in": ids}})
                count = result.deleted_count
                if count > 0:
                    logger.info(f"Cleaned up {count} expired auto-blocked IP(s)")
                    await _refresh_blocked_ip_cache()
                    try:
                        from metrics import _dispatch_alert
                        hashes = ", ".join(d.get("ip_hash", "?")[:12] + "..." for d in expired_docs[:5])
                        suffix = f" and {count - 5} more" if count > 5 else ""
                        await _dispatch_alert(
                            "auto_block_expired",
                            "Auto-blocked IPs expired",
                            f"{count} auto-blocked IP(s) have been automatically unblocked after their cooldown expired: {hashes}{suffix}.",
                            {"count": count, "ip_hashes": [d.get("ip_hash") for d in expired_docs[:10]]},
                        )
                    except Exception as e:
                        logger.debug(f"auto-block expiry alert dispatch failed: {e}")
    except Exception as e:
        logger.debug(f"expired IP cleanup failed: {e}")

async def _blocked_ip_refresh_loop():
    global _EXPIRED_IP_CLEANUP_COUNTER
    while True:
        try:
            await _refresh_blocked_ip_cache()
            _EXPIRED_IP_CLEANUP_COUNTER += 1
            if _EXPIRED_IP_CLEANUP_COUNTER >= 30:
                _EXPIRED_IP_CLEANUP_COUNTER = 0
                await _cleanup_expired_blocked_ips()
        except Exception as e:
            logger.debug(f"blocked IP refresh loop error: {e}")
        await asyncio.sleep(_BLOCKED_IP_REFRESH_INTERVAL)


async def _init_blocked_ip_cache():
    await _refresh_blocked_ip_cache()
    asyncio.create_task(_blocked_ip_refresh_loop())


def _is_ip_blocked(ip_hash: str) -> bool:
    with _blocked_ip_lock:
        return ip_hash in _blocked_ip_hashes

_spoof_counter_lock = __import__("threading").Lock()
_spoof_minute_counts: dict[str, int] = {}
_SPOOF_ALERT_THRESHOLD = 50

def _get_auto_block_threshold() -> int:
    try:
        from metrics import _ALERT_THRESHOLDS
        return int(_ALERT_THRESHOLDS.get("auto_block_threshold", 100))
    except Exception:
        return 100

async def _check_auto_block(db, ip_hash: str, now: datetime):
    threshold = _get_auto_block_threshold()
    if threshold <= 0:
        return
    if _is_ip_blocked(ip_hash):
        return
    try:
        cutoff = now - timedelta(hours=24)
        count = await db.bot_spoof_attempts.count_documents({
            "ip_hash": ip_hash,
            "timestamp": {"$gte": cutoff},
        })
        if count >= threshold:
            existing = await db.blocked_ips.find_one({"ip_hash": ip_hash})
            if existing:
                return
            doc = {
                "ip_hash": ip_hash,
                "reason": "auto_threshold",
                "blocked_at": now,
                "blocked_by": "system/auto-block",
                "auto_blocked": True,
                "threshold_at_block": threshold,
                "spoof_count_24h": count,
            }
            try:
                from metrics import _ALERT_THRESHOLDS
                expiry_h = float(_ALERT_THRESHOLDS.get("auto_block_expiry_hours", 168))
            except Exception:
                expiry_h = 168
            if expiry_h > 0:
                doc["expires_at"] = now + timedelta(hours=expiry_h)
            await db.blocked_ips.insert_one(doc)
            await _refresh_blocked_ip_cache()
            logger.warning(
                f"AUTO_BLOCK ip_hash={ip_hash} spoof_count_24h={count} threshold={threshold}"
            )
            try:
                from metrics import _dispatch_alert
                await _dispatch_alert(
                    "auto_block_ip",
                    "IP Auto-Blocked",
                    f"IP {ip_hash[:12]}... was automatically blocked after {count} spoofing attempts in 24h (threshold: {threshold}).",
                    {"ip_hash": ip_hash, "spoof_count_24h": count, "threshold": threshold},
                )
            except Exception as e:
                logger.debug(f"auto-block alert dispatch failed: {e}")
    except Exception as e:
        logger.debug(f"auto-block check failed: {e}")


_BOT_OPEN_PREFIXES = (
    "/api/content/library-bundle",
    "/api/content/boards",
    "/api/content/classes",
    "/api/content/streams",
    "/api/content/subjects",
    "/api/content/chapters/",
    "/api/content/chapter-by-slug/",
    "/api/content/chapter/",
    "/api/content/search",
    "/api/seo/",
)


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Plan-aware IP rate limiting for all /api routes + request tracking.
    Plan is read from JWT claim (refreshed on login, plan change invalidates session).
    JWT is decoded once and reused for both rate-limiting and metrics."""
    _RATE_LIMIT_EXEMPT_PREFIXES = (
        "/api/auth/me",
        "/api/analytics/",
        "/api/health",
    )

    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await _safe_call_next(call_next, request)

        rid = uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        request.state.request_id = rid
        request.state.start_time = _time_mod.time()

        ua = request.headers.get("user-agent", "")
        ua_claims_bot = bool(ua and _SEARCH_BOT_UA_RE.search(ua) and not _ABUSIVE_SCRAPER_UA_RE.search(ua) and not _TRAINING_SCRAPER_UA_RE.search(ua))
        request.state.is_search_bot = False

        cf_ip = request.headers.get("cf-connecting-ip", "")
        xff = request.headers.get("x-forwarded-for", "")
        client_ip = cf_ip or (xff.split(",")[0].strip() if xff else "") or (request.client.host if request.client else "unknown")

        ip_hash_check = _hash_ip_stable(client_ip)
        if _is_ip_blocked(ip_hash_check):
            from fastapi.responses import JSONResponse
            _metrics.record_request(path, 403)
            logger.warning(f"BLOCKED_IP ip_hash={ip_hash_check} path={path} rid={rid}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied."},
                headers={"X-Request-Id": rid},
            )

        exempt = any(path.startswith(p) for p in self._RATE_LIMIT_EXEMPT_PREFIXES)
        if exempt:
            _metrics.inc_active()
            try:
                response = await _safe_call_next(call_next, request)
                _metrics.record_request(path, response.status_code)
                response.headers["X-Request-Id"] = rid
                return response
            finally:
                _metrics.dec_active()

        user_id = None
        ip_limit = PLAN_LIMITS["free"]["req_per_min_ip"]
        try:
            token = None
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
            else:
                token = request.cookies.get("syrabit_session")
            if token:
                payload = decode_token(token)
                user_id = payload.get("sub") or payload.get("user_id")
                user_plan = payload.get("plan", "free")
                if user_id:
                    cached_user = _redis_get_session(user_id)
                    if cached_user:
                        user_plan = cached_user.get("plan", user_plan)
                plan_cfg = PLAN_LIMITS.get(user_plan, PLAN_LIMITS["free"])
                ip_limit = plan_cfg["req_per_min_ip"]
        except Exception:
            pass

        is_legit_bot = False
        if ua_claims_bot:
            try:
                is_legit_bot = await asyncio.to_thread(verify_bot_ip, client_ip, ua)
            except Exception:
                is_legit_bot = False
        request.state.is_search_bot = is_legit_bot
        if ua_claims_bot and not is_legit_bot:
            ip_hash = _hash_ip_stable(client_ip)
            bot_match = _SEARCH_BOT_UA_RE.search(ua)
            claimed_bot = bot_match.group(0).lower() if bot_match else "unknown"
            logger.warning(
                f"SPOOFED_BOT ip_hash={ip_hash} claimed={claimed_bot} "
                f"ua=\"{ua[:150]}\" path={path} rid={rid}"
            )
            _metrics.record_spoof(claimed_bot)
            minute_key = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
            with _spoof_counter_lock:
                _spoof_minute_counts[minute_key] = _spoof_minute_counts.get(minute_key, 0) + 1
                count = _spoof_minute_counts[minute_key]
                if len(_spoof_minute_counts) > 10:
                    stale = [k for k in _spoof_minute_counts if k < minute_key]
                    for k in stale:
                        _spoof_minute_counts.pop(k, None)
            if count == _SPOOF_ALERT_THRESHOLD:
                logger.error(
                    f"SPOOF_ALERT threshold={_SPOOF_ALERT_THRESHOLD}/min reached | "
                    f"minute={minute_key}"
                )
            async def _bg_persist_spoof():
                try:
                    from deps import db, is_mongo_available
                    if await is_mongo_available():
                        _now = datetime.now(timezone.utc)
                        await db.bot_spoof_attempts.insert_one({
                            "ip_hash": ip_hash,
                            "claimed_bot": claimed_bot,
                            "user_agent": ua[:500],
                            "path": path,
                            "timestamp": _now,
                            "date": _now.strftime("%Y-%m-%d"),
                            "request_id": rid,
                        })
                        await _check_auto_block(db, ip_hash, _now)
                except Exception as e:
                    logger.debug(f"spoof persist failed: {e}")
            asyncio.create_task(_bg_persist_spoof())
        if not is_legit_bot:
            if not check_rate_limit(f"ip:{client_ip}", max_requests=ip_limit, window_seconds=60):
                from fastapi.responses import JSONResponse
                _metrics.record_request(path, 429)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — please slow down."},
                    headers={"Retry-After": "60", "X-RateLimit-Limit": str(ip_limit), "X-Request-Id": rid}
                )

        _metrics.inc_active()
        try:
            response = await _safe_call_next(call_next, request)
            _metrics.record_request(path, response.status_code, user_id)
            response.headers["X-Request-Id"] = rid
            if is_legit_bot and any(path.startswith(p) for p in _BOT_OPEN_PREFIXES):
                response.headers["X-Robots-Tag"] = "noarchive"
                response.headers["X-Content-Source"] = "Syrabit Browser"
                response.headers["X-Attribution"] = "Source: Syrabit Browser - https://syrabit.ai"
                if "Cache-Control" not in response.headers:
                    response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400"
            if is_legit_bot:
                response.headers["X-Bot-Served"] = "true"
            elapsed = _time_mod.time() - request.state.start_time
            if elapsed > 1.0:
                logger.info(f"[SLOW] {path} took {elapsed*1000:.0f}ms | rid={rid} uid={user_id or 'anon'}")
            return response
        finally:
            _metrics.dec_active()


_STATIC_ASSET_RE = re.compile(
    r"\.(js|css|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot|map|webp|avif|mp4|webm)$",
    re.IGNORECASE,
)

_SKIP_TRACKING_PREFIXES = (
    "/api/auth/", "/api/admin/", "/api/ai/", "/api/analytics/",
    "/api/health", "/api/billing/",
    "/static/", "/assets/", "/icons/", "/fonts/",
    "/health", "/docs", "/openapi.json", "/robots.txt", "/sitemap",
    "/__mockup", "/favicon",
)

_SERVER_BOT_RE = re.compile(
    _SEARCH_BOT_UA_RE.pattern + r"|" + _TRAINING_SCRAPER_UA_RE.pattern + r"|" + _ABUSIVE_SCRAPER_UA_RE.pattern,
    re.IGNORECASE,
)

_IP_HASH_SALT = os.environ.get("IP_HASH_SALT", "syrabit-ss-tracking-2026")


def _hash_ip_daily(ip: str, date: str) -> str:
    raw = f"{_IP_HASH_SALT}:{ip}:{date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _hash_ip_stable(ip: str) -> str:
    raw = f"{_IP_HASH_SALT}:{ip}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ServerSideTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path

        if (
            any(path.startswith(p) for p in _SKIP_TRACKING_PREFIXES)
            or _STATIC_ASSET_RE.search(path)
        ):
            return await _safe_call_next(call_next, request)

        ua = request.headers.get("user-agent", "")
        bot_match = _SERVER_BOT_RE.search(ua) if ua else None
        is_bot = bool(bot_match)
        # Use the canonical classifier so e.g. "Googlebot-Image/1.0" is
        # stored as "Googlebot-Image" (not just "googlebot"), and so AI
        # crawlers (GPTBot, PerplexityBot, ClaudeBot, OAI-SearchBot,
        # Google-Extended, Applebot-Extended, …) get readable names in
        # the admin dashboard's top_bots / per_bot_pages aggregations.
        # Fall back to the raw regex match for UAs that match the bot
        # regex but aren't in the canonical patterns list.
        if bot_match:
            try:
                from cf_bot_report import _classify_ua as _classify_bot_ua
                _canonical = _classify_bot_ua(ua)
            except Exception:
                _canonical = None
            bot_name = _canonical or bot_match.group(0)
        else:
            bot_name = ""
        cf_connecting_ip = request.headers.get("cf-connecting-ip", "")
        x_forwarded = request.headers.get("x-forwarded-for", "")
        client_ip = cf_connecting_ip or (x_forwarded.split(",")[0].strip() if x_forwarded else "") or (request.client.host if request.client else "unknown")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_iso = datetime.now(timezone.utc).isoformat()
        ip_hash_daily = _hash_ip_daily(client_ip, today)
        ip_hash_stable = _hash_ip_stable(client_ip)
        cf_country = request.headers.get("cf-ipcountry", "")

        response = await _safe_call_next(call_next, request)

        import asyncio
        async def _bg_track():
            try:
                from deps import db, is_mongo_available
                if await is_mongo_available():
                    await db.server_hits.insert_one({
                        "path": path,
                        "ip_hash": ip_hash_daily,
                        "ip_hash_stable": ip_hash_stable,
                        "user_agent": ua[:500],
                        "is_bot": is_bot,
                        "bot_name": bot_name,
                        "date": today,
                        "timestamp": now_iso,
                        "status_code": response.status_code,
                        "country": cf_country,
                    })
            except Exception as e:
                logger.debug(f"server-side tracking failed: {e}")
        asyncio.create_task(_bg_track())

        return response

