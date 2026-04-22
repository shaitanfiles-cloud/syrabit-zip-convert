"""Shared Cloudflare Turnstile verification helper.

Centralises the siteverify call so every route that wants Turnstile
protection — chat (`routes/ai_chat.py`) and auth (`routes/auth.py`) —
uses the same implementation, error codes, and timeout behaviour.

Behaviour:
- When `CF_TURNSTILE_ENABLED` is False (no secret configured, e.g. dev /
  local), `verify_turnstile_token` returns True so callers can skip the
  check transparently.
- When enabled, posts to Cloudflare's siteverify endpoint with the
  token + remoteip and returns the success bool.
- Network/HTTP failures return False (fail-closed) and are logged.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import HTTPException, Request

from config import CF_TURNSTILE_ENABLED, CF_TURNSTILE_SECRET_KEY

logger = logging.getLogger(__name__)

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_TIMEOUT_SECONDS = 3.0


def client_ip_from_request(request: Request) -> str:
    """Return the best-effort client IP for the siteverify `remoteip`
    field. Prefers the leftmost X-Forwarded-For entry (set by the
    Cloudflare / Replit proxy) and falls back to the socket peer."""
    xff = request.headers.get("x-forwarded-for", "") or ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else ""


async def verify_turnstile_token(token: str, ip: str = "") -> bool:
    """Verify a Turnstile token against Cloudflare siteverify.

    Returns True when verification is disabled or succeeds, False on
    any failure (siteverify rejection, timeout, transport error)."""
    if not CF_TURNSTILE_ENABLED:
        return True
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as tc:
            r = await tc.post(
                _SITEVERIFY_URL,
                data={
                    "secret": CF_TURNSTILE_SECRET_KEY,
                    "response": token,
                    "remoteip": ip,
                },
            )
            if r.status_code != 200:
                logger.warning(f"Turnstile siteverify returned {r.status_code}")
                return False
            return bool(r.json().get("success", False))
    except Exception as e:
        logger.warning(f"Turnstile verification error: {type(e).__name__}: {e}")
        return False


async def require_turnstile(request: Request, *, header: str = "x-turnstile-token") -> None:
    """FastAPI helper: enforce Turnstile on a route.

    No-op when `CF_TURNSTILE_ENABLED` is False. Otherwise reads the
    token from the given header and rejects with HTTP 400
    `{detail: "turnstile_failed"}` on missing or invalid tokens — the
    same shape the build brief specifies for auth surfaces.
    """
    if not CF_TURNSTILE_ENABLED:
        return
    token: Optional[str] = request.headers.get(header, "") or ""
    ip = client_ip_from_request(request)
    if not token or not await verify_turnstile_token(token, ip):
        raise HTTPException(status_code=400, detail="turnstile_failed")
