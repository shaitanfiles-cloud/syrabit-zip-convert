"""Syrabit.ai — ASGI middleware classes."""
import time as _time_mod, logging
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from config import SECURE_COOKIES
from auth_deps import check_rate_limit, decode_token
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
                headers.append("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                headers.append("X-XSS-Protection", "1; mode=block")
                if SECURE_COOKIES:
                    headers.append("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
                headers.append("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://www.googletagmanager.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'self'")
            await send(message)

        await self.app(scope, receive, send_with_security_headers)

class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """200 req/min per IP for all /api routes + request tracking."""
    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            client_ip = request.client.host if request.client else "unknown"
            if not check_rate_limit(f"ip:{client_ip}", max_requests=600, window_seconds=60):
                from fastapi.responses import JSONResponse
                _metrics.record_request(path, 429)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — please slow down."},
                    headers={"Retry-After": "60", "X-RateLimit-Limit": "200"}
                )
        _metrics.inc_active()
        try:
            response = await call_next(request)
            user_id = None
            if path.startswith("/api/"):
                try:
                    token = None
                    auth = request.headers.get("authorization", "")
                    if auth.startswith("Bearer "):
                        token = auth[7:]
                    else:
                        token = request.cookies.get("syrabit_session")
                    if token:
                        _pl = decode_token(token)
                        user_id = _pl.get("sub") or _pl.get("user_id")
                except Exception:
                    pass
                _metrics.record_request(path, response.status_code, user_id)
            return response
        finally:
            _metrics.dec_active()

