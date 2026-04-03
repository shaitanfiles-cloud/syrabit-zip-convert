"""Syrabit.ai — ASGI middleware classes."""
import re, time as _time_mod, logging
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from config import SECURE_COOKIES, PLAN_LIMITS
from auth_deps import check_rate_limit, decode_token
from cache import _redis_get_session
from metrics import _metrics

logger = logging.getLogger(__name__)

class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-Content-Type-Options", "nosniff")
                headers.append("X-Frame-Options", "SAMEORIGIN")
                headers.append("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.append("Permissions-Policy", "camera=(), microphone=(), geolocation=(), identity-credentials-get=(self https://accounts.google.com)")
                headers.append("X-XSS-Protection", "1; mode=block")
                if SECURE_COOKIES:
                    headers.append("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
                headers.append("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.googletagmanager.com https://accounts.google.com https://apis.google.com; style-src 'self' 'unsafe-inline' https://accounts.google.com; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-src https://accounts.google.com; frame-ancestors 'self'")
                ct = headers.get("content-type", "")
                if "text/html" in ct:
                    headers.append("Content-Language", "en-IN")
            await send(message)

        await self.app(scope, receive, send_with_security_headers)

_SEARCH_BOT_UA_RE = re.compile(
    r"googlebot|bingbot|yandexbot|duckduckbot|baiduspider|slurp|"
    r"applebot|applebot-extended|facebookexternalhit|facebookbot|"
    r"twitterbot|linkedinbot|telegrambot|whatsapp|"
    r"gptbot|oai-searchbot|chatgpt-user|"
    r"claudebot|anthropic-ai|"
    r"perplexitybot|"
    r"google-extended|meta-externalagent|cohere-ai|bytespider|ccbot|"
    r"ia_archiver|msnbot|petalbot",
    re.IGNORECASE,
)

_ABUSIVE_SCRAPER_UA_RE = re.compile(
    r"scrapy|wget|curl|python-requests|go-http-client|java/|"
    r"ahrefsbot|semrushbot|nmap|masscan|zgrab|heritrix",
    re.IGNORECASE,
)

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

        ua = request.headers.get("user-agent", "")
        is_legit_bot = bool(ua and _SEARCH_BOT_UA_RE.search(ua) and not _ABUSIVE_SCRAPER_UA_RE.search(ua))

        exempt = any(path.startswith(p) for p in self._RATE_LIMIT_EXEMPT_PREFIXES)
        if exempt:
            _metrics.inc_active()
            try:
                response = await call_next(request)
                _metrics.record_request(path, response.status_code)
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
                headers={"Retry-After": "60", "X-RateLimit-Limit": str(effective_limit)}
            )

        _metrics.inc_active()
        try:
            response = await call_next(request)
            _metrics.record_request(path, response.status_code, user_id)
            return response
        finally:
            _metrics.dec_active()

