"""Syrabit.ai — JWT helpers, authentication dependencies, and rate limiting."""
import time, asyncio, logging
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException, Cookie
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
    if "role" not in user:
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
        user = cached if cached else await supa_get_user_by_id(user_id)
        if user and "role" not in user:
            user["role"] = "admin" if user.get("is_admin") else "student"
        return user if user and user.get("status") not in ["banned", "suspended"] else None
    except:
        return None

async def get_admin_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    syrabit_admin_session: Optional[str] = Cookie(default=None),
):
    token = creds.credentials if creds else syrabit_admin_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
        if not (payload.get("is_admin") or payload.get("role") == "admin"):
            raise HTTPException(status_code=403, detail="Not authorized")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid admin token")

# ─────────────────────────────────────────────
# RATE LIMITER — sliding window, per user/IP
# ─────────────────────────────────────────────
_rate_windows: Dict[str, List[float]] = {}

async def _rate_limiter_cleanup():
    while True:
        await asyncio.sleep(300)
        now = datetime.now(timezone.utc).timestamp()
        stale = [k for k, v in _rate_windows.items() if not v or v[-1] < now - 120]
        for k in stale:
            del _rate_windows[k]

def _check_rate_limit_memory(key: str, max_requests: int, window_seconds: int) -> bool:
    """In-memory sliding window rate limiter."""
    now = datetime.now(timezone.utc).timestamp()
    window_start = now - window_seconds
    if key not in _rate_windows:
        _rate_windows[key] = []
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
