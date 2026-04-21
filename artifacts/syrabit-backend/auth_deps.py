"""Syrabit.ai — JWT helpers, authentication dependencies, and rate limiting."""
import time, asyncio, logging
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException, Cookie, Request
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from jwt.exceptions import PyJWTError as JWTError
from config import (
    JWT_SECRET, JWT_ALGORITHM, JWT_ACCESS_EXPIRE_MINUTES,
    JWT_REFRESH_EXPIRE_MINUTES, JWT_EXPIRE_MINUTES,
    ADMIN_JWT_SECRET, PLAN_LIMITS,
)
from deps import security, redis_client, logger as _dep_logger
from cache import _redis_get_session, _redis_cache_session


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
):
    token = creds.credentials if creds else syrabit_admin_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token, secret=ADMIN_JWT_SECRET)
        if not (payload.get("is_admin") or payload.get("role") == "admin"):
            raise HTTPException(status_code=403, detail="Not authorized")
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
    user: Optional[dict] = Depends(get_current_user_optional),
):
    """Like rate_limit_chat but allows anonymous users with IP-based rate limiting."""
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
    ip = (request.client.host if request.client else None) or request.headers.get("x-forwarded-for", "").split(",")[0].strip() or "unknown"
    free_cfg = PLAN_LIMITS["free"]
    if not check_rate_limit(f"chat:ip:{ip}", max_requests=free_cfg["req_per_min"], window_seconds=60):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Sign in for higher limits.",
            headers={"Retry-After": "60"},
        )
    return None
