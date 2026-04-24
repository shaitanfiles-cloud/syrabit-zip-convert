"""Syrabit.ai — JWT helpers, authentication dependencies, and rate limiting."""
import time, asyncio, logging
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException, Cookie, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import PyJWTError as JWTError
from config import (
    JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_EXPIRE_MINUTES,
    JWT_REFRESH_EXPIRE_MINUTES, JWT_EXPIRE_MINUTES,
    ADMIN_JWT_SECRET, PLAN_LIMITS,
    COOKIE_DOMAIN, COOKIE_SAMESITE, SECURE_COOKIES,
    IP_COARSE_DAILY_CAP,
)
from deps import security, redis_client
from cache import _redis_get_session, _redis_cache_session
from cf_access import require_cf_access_admin
from device_token import (
    DEVICE_COOKIE_NAME, DEVICE_COOKIE_MAX_AGE_SECONDS,
    mint_device_token, device_token_id,
)


def _real_client_ip(request: Request) -> str:
    """Return the best-effort real client IP for rate limiting.

    Header preference order (Task #793):

    1. ``cf-connecting-ip`` — Cloudflare always sets this on requests
       it forwards to origin, and it always carries the **real**
       client IP (not the CF edge POP). This is the highest-trust
       source when traffic actually comes from the CF edge.
    2. ``x-forwarded-for`` (first comma-separated entry) — what our
       own ``workers/edge-proxy`` rewrites onto the upstream request
       after stripping CF-Connecting-IP, and the de-facto standard
       header that any HTTP-aware proxy in front of us will set.
    3. ``request.client.host`` — the immediate peer the ASGI server
       sees, which behind any proxy will be the proxy's address (a
       Replit gateway, the Cloud Run frontend, etc.) and is therefore
       the worst signal of "who is actually talking to us". Used only
       as a last resort.

    Previously :func:`rate_limit_chat_optional` checked
    ``request.client.host`` *first*, which on Replit/Cloud Run pinned
    the entire daily quota to a single shared upstream IP and made
    every test environment look like an exhausted attacker.
    """
    cf_ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf_ip:
        return cf_ip
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return (request.client.host if request.client else "") or "unknown"


def _set_device_cookie(request: Request, response: Response, value: str) -> None:
    """Attach the signed device-token cookie to ``response`` *and* stash
    the value on ``request.state`` so the
    :class:`middleware.DeviceCookieMiddleware` fall-back can re-apply
    it when the route handler returns its own ``Response`` instance
    (FastAPI discards the dependency-injected ``Response`` object in
    that case — the most common path here is ``StreamingResponse`` on
    ``/ai/chat/stream``, which is the user-facing chat endpoint).

    Cookie attributes mirror the existing ``syrabit_session`` cookie
    set by :mod:`routes.auth`: HttpOnly (so client JS cannot read or
    tamper with it), Secure when running over HTTPS, SameSite=Lax (so
    ordinary navigations from search results / WhatsApp link previews
    still send the cookie and the user keeps their device-keyed
    quota), and a 400-day max-age (the longest browsers will honour).
    """
    cookie_kwargs = dict(
        key=DEVICE_COOKIE_NAME,
        value=value,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=DEVICE_COOKIE_MAX_AGE_SECONDS,
        path="/",
    )
    if COOKIE_DOMAIN:
        cookie_kwargs["domain"] = COOKIE_DOMAIN
    response.set_cookie(**cookie_kwargs)
    # Stash for the middleware fall-back. Using ``request.state`` (an
    # arbitrary attribute namespace per Starlette docs) keeps the
    # cookie payload bound to this single request and avoids any
    # global mutable state that could leak between concurrent
    # requests.
    try:
        request.state.device_cookie_to_set = value
    except Exception:
        # ``request.state`` is always available on a real Starlette
        # request; the only way this raises is in unit tests that
        # pass a hand-rolled stub without a ``state`` attribute. The
        # tests that exercise the dependency directly read the cookie
        # off ``response.headers`` so they don't need the stash, and
        # the middleware fall-back is irrelevant for them.
        pass


logger = logging.getLogger(__name__)

async def get_user_credits(user: dict) -> dict:
    """
    Daily-resetting credits with backwards-compatible legacy balance bridge.
    Each plan gets a fixed credits_per_day allowance that resets at midnight UTC.
    If the stored credits_reset_date is before today (UTC), usage is treated as 0
    and the counter will be reset on next deduction.

    Legacy bridge: if a user has a credits_limit (from top-ups / admin adjustments /
    referral bonuses) that exceeds the plan's base daily allowance, the effective
    daily limit is raised to honour those purchased credits until they are consumed.
    """
    plan      = user.get("plan", "free")
    plan_cfg  = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    daily_limit = plan_cfg["credits_per_day"]

    legacy_limit = user.get("credits_limit")
    legacy_used  = user.get("credits_used", 0) or 0
    if legacy_limit is not None:
        legacy_remaining = max(0, legacy_limit - legacy_used)
        if legacy_remaining > daily_limit:
            daily_limit = legacy_remaining

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reset_date = user.get("credits_reset_date") or ""
    if isinstance(reset_date, datetime):
        reset_date = reset_date.strftime("%Y-%m-%d")
    elif hasattr(reset_date, "isoformat"):
        reset_date = str(reset_date)[:10]
    if reset_date == today_str:
        used = user.get("credits_used_today", 0) or 0
    else:
        used = 0
    return {
        "used": used,
        "limit": daily_limit,
        "remaining": max(0, daily_limit - used),
        "document_access": plan_cfg["document_access"],
        "resets_at": "midnight UTC",
    }


def create_token(data: dict, secret: str = JWT_SECRET, expires_delta: int = JWT_EXPIRE_MINUTES) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expires_delta)
    return jwt.encode(to_encode, secret, algorithm=JWT_ALGORITHM)

def create_access_token(user_id: str, role: str = "student", plan: str = "free") -> str:
    return create_token({"sub": user_id, "role": role, "type": "access", "plan": plan}, expires_delta=JWT_ACCESS_EXPIRE_MINUTES)

def create_refresh_token(user_id: str) -> str:
    return create_token({"sub": user_id, "type": "refresh"}, expires_delta=JWT_REFRESH_EXPIRE_MINUTES)

def decode_token(token: str, secret: str = JWT_SECRET) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_session: Optional[str] = Cookie(default=None),
):
    token = creds.credentials if creds else syrabit_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
        if payload.get("type") == "refresh":
            raise HTTPException(status_code=401, detail="Refresh tokens cannot be used for API access")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    cached = _redis_get_session(user_id)
    if cached:
        user = cached
    else:
        from db_ops import supa_get_user_by_id
        user = await supa_get_user_by_id(user_id)
        if user:
            _redis_cache_session(user_id, user)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Account banned")
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended")
    # Task #591: role column may exist but be empty string for legacy rows;
    # treat blank as the default ('admin' for admins, 'student' otherwise) so
    # the get_educator_user dependency can rely on user["role"] == 'educator'.
    if not user.get("role"):
        user["role"] = "admin" if user.get("is_admin") else "student"
    return user

async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_session: Optional[str] = Cookie(default=None),
):
    token = creds.credentials if creds else syrabit_session
    if not token:
        return None
    try:
        payload = decode_token(token)
        if payload.get("type") == "refresh":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        cached = _redis_get_session(user_id)
        if cached:
            user = cached
        else:
            from db_ops import supa_get_user_by_id
            user = await supa_get_user_by_id(user_id)
            if user:
                _redis_cache_session(user_id, user)
        if user and not user.get("role"):
            user["role"] = "admin" if user.get("is_admin") else "student"
        return user if user and user.get("status") not in ["banned", "suspended"] else None
    except:
        return None

async def get_educator_user(user=Depends(get_current_user)):
    """Require the caller to be an educator (or an admin).

    Used by the educator self-serve allowlist flow so verified teachers
    can admit new educational sites after an automated safety probe
    passes. Admins always satisfy this dependency.
    """
    role = (user or {}).get("role", "")
    if role == "educator" or role == "admin" or (user or {}).get("is_admin"):
        return user
    raise HTTPException(status_code=403, detail="Educator role required")


async def get_admin_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_admin_session: Optional[str] = Cookie(default=None),
    cf_access_claims: Optional[dict] = Depends(require_cf_access_admin),
):
    """Admin auth = Cloudflare Access (Zero Trust) gate + admin JWT.

    Task #637 layers Cloudflare Access on top of the existing admin JWT so
    a request must (a) transit the Access proxy on the admin team domain
    AND (b) carry a valid admin JWT. The CF Access dependency is a no-op
    until ``CF_ACCESS_ENFORCE=true`` is set in production env, so this
    change is safe to merge before operators provision Access.
    """
    token = creds.credentials if creds else syrabit_admin_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token, secret=ADMIN_JWT_SECRET)
        if not (payload.get("is_admin") or payload.get("role") == "admin"):
            raise HTTPException(status_code=403, detail="Not authorized")
        if cf_access_claims:
            # Surface CF Access identity to admin handlers (audit logs).
            payload["cf_access_email"] = cf_access_claims.get("email")
            payload["cf_access_sub"] = cf_access_claims.get("sub")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid admin token")

# ─────────────────────────────────────────────
# RATE LIMITER — sliding window, per user/IP
# ─────────────────────────────────────────────
_rate_windows: Dict[str, List[float]] = {}
# Task #615: remember the widest window any caller has used for a key so
# the periodic cleanup does not GC daily-quota buckets after only a couple
# minutes of idle time (which would silently reset a 24h cap in fallback
# mode whenever Redis is unavailable).
_rate_window_horizon: Dict[str, int] = {}

async def _rate_limiter_cleanup():
    while True:
        await asyncio.sleep(300)
        now = datetime.now(timezone.utc).timestamp()
        stale: list[str] = []
        for k, v in _rate_windows.items():
            horizon = _rate_window_horizon.get(k, 120)
            # Keep the bucket alive while any timestamp could still be
            # inside its declared window (plus a small grace period).
            if not v or v[-1] < now - horizon - 60:
                stale.append(k)
        for k in stale:
            _rate_windows.pop(k, None)
            _rate_window_horizon.pop(k, None)

def _check_rate_limit_memory(key: str, max_requests: int, window_seconds: int) -> bool:
    """In-memory sliding window rate limiter."""
    now = datetime.now(timezone.utc).timestamp()
    window_start = now - window_seconds
    if key not in _rate_windows:
        _rate_windows[key] = []
    # Track the widest window seen so the GC doesn't prune long-window keys.
    if window_seconds > _rate_window_horizon.get(key, 0):
        _rate_window_horizon[key] = window_seconds
    _rate_windows[key] = [t for t in _rate_windows[key] if t > window_start]
    if len(_rate_windows[key]) >= max_requests:
        return False
    _rate_windows[key].append(now)
    return True

def check_rate_limit(key: str, max_requests: int = 100, window_seconds: int = 60) -> bool:
    """Returns True if allowed, False if rate-limited.
    Uses Redis fixed-window counter when available (multi-worker safe), in-memory fallback otherwise.
    """
    if redis_client:
        try:
            redis_key = f"rl2:{key}:{int(time.time() // window_seconds)}"
            count = redis_client.incr(redis_key)
            if count == 1:
                redis_client.expire(redis_key, window_seconds + 5)
            if count > max_requests:
                return False
            return True
        except Exception as e:
            logger.debug(f"Redis rate limit failed, falling back to memory: {e}")
    return _check_rate_limit_memory(key, max_requests, window_seconds)


def get_rate_limit_count(key: str, window_seconds: int) -> int:
    """Best-effort read of the *current* fixed-window count for a rl2 key.

    Used by the admin quiz-quota tile so operators can see how much of a
    user's daily quota is consumed without burning another increment.
    Returns 0 if the bucket is missing or the backend is unreachable.
    """
    if redis_client:
        try:
            redis_key = f"rl2:{key}:{int(time.time() // window_seconds)}"
            v = redis_client.get(redis_key)
            return int(v) if v is not None else 0
        except Exception as e:
            logger.debug(f"Redis rate limit read failed, falling back to memory: {e}")
    bucket = _rate_windows.get(key) or []
    cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
    return sum(1 for t in bucket if t > cutoff)


def reset_rate_limit(key: str, window_seconds: int) -> int:
    """Drop the *current-window* counter for a rl2 key. Returns the count
    that was cleared (best-effort)."""
    cleared = 0
    if redis_client:
        try:
            redis_key = f"rl2:{key}:{int(time.time() // window_seconds)}"
            v = redis_client.get(redis_key)
            cleared = int(v) if v is not None else 0
            redis_client.delete(redis_key)
        except Exception as e:
            logger.debug(f"Redis rate limit reset failed: {e}")
    if key in _rate_windows:
        cleared = max(cleared, len(_rate_windows[key]))
        _rate_windows[key] = []
    return cleared

async def rate_limit_chat(user: dict = Depends(get_current_user)):
    """Dependency: plan-aware chat rate limiting (Free 5, Starter 10, Pro 15 req/min)."""
    user_id = user.get("id", "anonymous")
    plan = user.get("plan", "free")
    plan_cfg = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    limit = plan_cfg["req_per_min"]
    if not check_rate_limit(f"chat:{user_id}", max_requests=limit, window_seconds=60):
        raise HTTPException(
            status_code=429,
            detail=f"Chat rate limit exceeded — {limit} messages/minute ({plan} plan). Upgrade for higher limits.",
            headers={"Retry-After": "60", "X-RateLimit-Limit": str(limit)},
        )
    return user

async def rate_limit_chat_optional(
    request: Request,
    response: Response,
    user: Optional[dict] = Depends(get_current_user_optional),
    syrabit_device: Optional[str] = Cookie(default=None),
):
    """Anonymous-friendly chat rate limiter.

    Logged-in users keep their plan-aware per-minute limit (unchanged
    since Task #768).

    For anonymous users (Task #793), the daily 30-message budget is
    keyed on a **signed HttpOnly device-token cookie**, not on the
    public IP. The IP is kept only as a coarse abuse cap.

    The change exists to fix the single biggest funnel-killer on the
    site: AHSEC/SEBA students almost always reach us through shared
    egress IPs (Jio/Airtel mobile CGNAT, school/college WiFi,
    hostel/cyber-café WiFi). When the daily budget was per-IP, the
    first ~30 messages from any one of those networks drained the
    pool for every other student behind the same NAT, so the second
    visitor saw "Daily free quota exhausted" before sending a single
    message.

    Per-anonymous-request logic, top to bottom:

    1. **Per-minute throttle** — sliding-window rate limit, keyed on
       the device-token id when one is present, else on the IP. This
       mirrors the previous behaviour (a fresh device on a busy NAT
       still doesn't get throttled because each device gets its own
       per-minute window once the cookie is issued).

    2. **Coarse per-IP daily ceiling** — ``IP_COARSE_DAILY_CAP``
       requests/day per real client IP. Set high enough (default
       1500/day) that a classroom or hostel of students sharing one
       NAT never hits it; meant only to stop a single host from
       scripting thousands of requests.

    3. **Per-device daily quota** — 30/day from the free-plan config,
       enforced via :func:`db_ops.atomic_deduct_device_credit` (the
       same atomic Lua script used by the user credit ledger so
       concurrent abusers can't push a counter past its limit). The
       counter is keyed on either the verified incoming token or the
       freshly minted one (see (4) below), so the very first request
       counts toward the device's daily budget — preserving the
       documented contract that anonymous browsers get exactly 30
       successful messages a day, with the 31st blocked.

    4. **Cookie issuance** — every anonymous response that comes
       through here either re-confirms the existing valid cookie or
       mints a fresh one (and stashes it on ``request.state`` for
       :class:`middleware.DeviceCookieMiddleware` to apply onto any
       ``StreamingResponse`` the route returns). A brand-new browser
       therefore receives its cookie *and* is charged 1 against that
       fresh token's 30/day budget on the same request — never let a
       missing cookie produce a hard 429 outside of the per-device
       cap, but never give it a free ride either.
    """
    if user:
        user_id = user.get("id", "anonymous")
        plan = user.get("plan", "free")
        plan_cfg = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
        limit = plan_cfg["req_per_min"]
        if not check_rate_limit(f"chat:{user_id}", max_requests=limit, window_seconds=60):
            raise HTTPException(
                status_code=429,
                detail=f"Chat rate limit exceeded — {limit} messages/minute ({plan} plan). Upgrade for higher limits.",
                headers={"Retry-After": "60", "X-RateLimit-Limit": str(limit)},
            )
        return user

    free_cfg = PLAN_LIMITS["free"]
    daily_cap = int(free_cfg.get("credits_per_day") or 30)
    per_min_cap = int(free_cfg.get("req_per_min") or 15)
    ip = _real_client_ip(request)

    # ── 1. Resolve / mint device cookie ──────────────────────────────
    # ``device_token_id`` returns a printable hex id when the signed
    # cookie verifies, else None. When the incoming cookie is missing
    # or forged we mint a fresh one and use *its* token id for the
    # rest of this request — so a brand-new browser still gets a
    # valid token id keyed counter and is charged 1 against the
    # 30/day device cap on its very first message (preserving the
    # "30 successful, 31st blocked" UX contract).
    token_id = device_token_id(syrabit_device)
    if token_id is None:
        new_cookie = mint_device_token()
        _set_device_cookie(request, response, new_cookie)
        token_id = device_token_id(new_cookie)

    # ── 2. Per-minute throttle (device-scoped when possible) ─────────
    rl_key = f"chat:dev:{token_id}" if token_id else f"chat:ip:{ip}"
    if not check_rate_limit(rl_key, max_requests=per_min_cap, window_seconds=60):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Sign in for higher limits.",
            headers={"Retry-After": "60"},
        )

    # ── 3. Coarse per-IP abuse cap ───────────────────────────────────
    # Skip on truly unknown IPs so we don't lock out the loopback /
    # offline test paths; in production cf-connecting-ip / xff are
    # always populated upstream of this dependency.
    if ip and ip != "unknown":
        from db_ops import atomic_deduct_ip_credit
        if not atomic_deduct_ip_credit(ip, daily_limit=IP_COARSE_DAILY_CAP):
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Hourly request ceiling reached for this network "
                    f"(>{IP_COARSE_DAILY_CAP} requests/day). Sign in or try again "
                    "later — resets at midnight UTC."
                ),
                headers={"Retry-After": "3600", "X-RateLimit-Limit": str(IP_COARSE_DAILY_CAP)},
            )

    # ── 4. Per-device daily quota (30/day) ───────────────────────────
    # Always charged. ``token_id`` here is either the verified
    # incoming cookie's id, or — on first visit — the freshly-minted
    # token id from step (1). Either way, the request consumes 1
    # against this device's daily budget; the 31st request from the
    # same device on the same day will trip the cap.
    if token_id:
        from db_ops import atomic_deduct_device_credit
        if not atomic_deduct_device_credit(token_id, daily_limit=daily_cap):
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Daily free quota exhausted ({daily_cap} requests/day). "
                    "Sign in for higher limits — resets at midnight UTC."
                ),
                headers={"Retry-After": "3600", "X-RateLimit-Limit": str(daily_cap)},
            )

    return None
