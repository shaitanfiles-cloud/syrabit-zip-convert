"""Syrabit.ai — ASGI middleware classes."""
import os, re, time as _time_mod, logging, uuid, contextvars, hashlib
from datetime import datetime, timezone
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

from utils import _SEARCH_BOT_UA_RE, _ABUSIVE_SCRAPER_UA_RE

_BOT_RATE_LIMIT = 600


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
            return await call_next(request)

        rid = uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        request.state.request_id = rid
        request.state.start_time = _time_mod.time()

        ua = request.headers.get("user-agent", "")
        is_legit_bot = bool(ua and _SEARCH_BOT_UA_RE.search(ua) and not _ABUSIVE_SCRAPER_UA_RE.search(ua))

        exempt = any(path.startswith(p) for p in self._RATE_LIMIT_EXEMPT_PREFIXES)
        if exempt:
            _metrics.inc_active()
            try:
                response = await call_next(request)
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

        client_ip = request.client.host if request.client else "unknown"
        effective_limit = max(ip_limit, _BOT_RATE_LIMIT) if is_legit_bot else ip_limit
        if not check_rate_limit(f"ip:{client_ip}", max_requests=effective_limit, window_seconds=60):
            from fastapi.responses import JSONResponse
            _metrics.record_request(path, 429)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests — please slow down."},
                headers={"Retry-After": "60", "X-RateLimit-Limit": str(effective_limit), "X-Request-Id": rid}
            )

        _metrics.inc_active()
        try:
            response = await call_next(request)
            _metrics.record_request(path, response.status_code, user_id)
            response.headers["X-Request-Id"] = rid
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
    "/api/", "/static/", "/assets/", "/icons/", "/fonts/",
    "/health", "/docs", "/openapi.json", "/robots.txt", "/sitemap",
    "/__mockup", "/favicon",
)

_SERVER_BOT_RE = re.compile(
    _SEARCH_BOT_UA_RE.pattern + r"|" + _ABUSIVE_SCRAPER_UA_RE.pattern,
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
            return await call_next(request)

        ua = request.headers.get("user-agent", "")
        bot_match = _SERVER_BOT_RE.search(ua) if ua else None
        is_bot = bool(bot_match)
        bot_name = bot_match.group(0).lower() if bot_match else ""
        cf_connecting_ip = request.headers.get("cf-connecting-ip", "")
        x_forwarded = request.headers.get("x-forwarded-for", "")
        client_ip = cf_connecting_ip or (x_forwarded.split(",")[0].strip() if x_forwarded else "") or (request.client.host if request.client else "unknown")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_iso = datetime.now(timezone.utc).isoformat()
        ip_hash_daily = _hash_ip_daily(client_ip, today)
        ip_hash_stable = _hash_ip_stable(client_ip)
        cf_country = request.headers.get("cf-ipcountry", "")

        response = await call_next(request)

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

