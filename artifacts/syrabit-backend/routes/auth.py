"""Syrabit.ai — Authentication routes"""
import re, json, asyncio, time, uuid, logging, hashlib, io, csv, os, base64, html as _html_mod
from pymongo.errors import DuplicateKeyError
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timezone, timedelta
from fastapi import (
    APIRouter, HTTPException, Depends, Query, Body, Path,
    File, UploadFile, Response, Request, Cookie, BackgroundTasks,
    Form, Header, status,
)
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, EmailStr
import mistune as _mistune

from models import (
    UserCreate, UserLogin, UserOut, TokenOut, OnboardingData, ChatMessage,
    ConversationCreate, AdminLoginReq, SubjectCreate, ChapterCreate, ChunkCreate,
    DocumentUpload, ProfileUpdate, PasswordResetReq, PasswordResetConfirm,
    UserStatusUpdate, UserPlanUpdate, UserCreditsUpdate, SettingsUpdate, RoadmapItemCreate,
    LibraryBundleOut, ChatResponseOut, SearchResultOut, HealthOut, ReadyOut, ErrorOut,
)
from config import *
from deps import *
from cache import *
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional,
)
from db_ops import *
from llm import call_llm_api, call_llm_api_stream
from rag import *
from utils import *
from analytics_helpers import *
import email_templates

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/auth/signup")
async def signup(data: UserCreate, response: Response):
    existing = await supa_get_user(data.email.lower())
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    settings = await supa_get_settings()
    if not settings.get("registrations_open", True):
        raise HTTPException(status_code=403, detail="Registrations are currently closed")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    raw_ref = (data.referral_code or "").strip()[:20]
    referred_by_code = None
    referred_by_user_id = None
    referrer_share = None
    if raw_ref and re.fullmatch(r"[a-z0-9]{7}", raw_ref) and await is_mongo_available():
        referrer_share = await db.shares.find_one({"code": raw_ref})
        if referrer_share and referrer_share.get("user_id"):
            if referrer_share["user_id"] != user_id:
                referred_by_code = raw_ref
                referred_by_user_id = referrer_share["user_id"]
            else:
                logger.warning(f"Self-referral blocked: user_id={user_id} code={raw_ref}")

    # Free users get 30 lifetime credits (ONE-TIME, no reset)
    user = {
        "id": user_id,
        "name": data.name,
        "email": data.email.lower(),
        "password_hash": pwd_ctx.hash(data.password),
        "plan": "free",
        "credits_used": 0,
        "credits_limit": 30,     # Free = 30 lifetime credits
        "document_access": "zero",
        "onboarding_done": False,
        "is_admin": False,
        "status": "active",
        "bio": "",
        "phone": "",
        "saved_subjects": [],
        "has_free_credits_issued": True,
        "created_at": now,
        "referred_by_code": referred_by_code,
        "referred_by_user_id": referred_by_user_id,
    }
    await supa_insert_user(user)

    referral_bonus = 0
    if referred_by_code and referrer_share and await is_mongo_available():
        try:
            cfg_doc = await db.api_config.find_one({}, {"_id": 0})
            ref_cfg = (cfg_doc or {}).get("referral", {})
            if ref_cfg.get("enabled"):
                reward_credits = ref_cfg.get("reward_credits", 10)
                referrer_credits = ref_cfg.get("referrer_credits", 10)

                try:
                    await db.referral_rewards.insert_one({
                        "id": str(uuid.uuid4()),
                        "referral_code": referred_by_code,
                        "new_user_id": user_id,
                        "referrer_user_id": referred_by_user_id,
                        "reward_credits": reward_credits,
                        "referrer_credits": referrer_credits,
                        "created_at": now,
                    })
                except DuplicateKeyError:
                    logger.info(f"Referral reward already exists for user={user_id} code={referred_by_code}")
                else:
                    if reward_credits > 0:
                        referral_bonus = reward_credits
                        user["credits_limit"] = 30 + reward_credits
                        await supa_update_user(user_id, {"credits_limit": user["credits_limit"]})

                    if referrer_credits > 0 and referred_by_user_id:
                        referrer = await supa_get_user_by_id(referred_by_user_id)
                        if referrer:
                            new_limit = (referrer.get("credits_limit") or 0) + referrer_credits
                            await supa_update_user(referred_by_user_id, {"credits_limit": new_limit})
        except Exception as e:
            logger.warning(f"Referral reward error: {e}")

    token = create_access_token(user_id, role="student")
    refresh = create_refresh_token(user_id)
    user_out = UserOut(
        id=user_id, name=data.name, email=data.email.lower(),
        plan="free", credits_used=0, credits_limit=user.get("credits_limit", 30),
        onboarding_done=False, is_admin=False, created_at=now
    )
    response.set_cookie(
        key="syrabit_session",
        value=token,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=JWT_ACCESS_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="syrabit_refresh",
        value=refresh,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        path="/api/auth/refresh",
        max_age=JWT_REFRESH_EXPIRE_MINUTES * 60,
    )
    result = {"access_token": token, "token_type": "bearer", "user": user_out.dict()}
    if referral_bonus > 0:
        result["referral_bonus"] = referral_bonus
    return result

@router.post("/auth/login", response_model=TokenOut)
async def login(data: UserLogin, response: Response):
    user = await supa_get_user(data.email.lower())
    if not user or not pwd_ctx.verify(data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Account banned")

    credits_info = await get_user_credits(user)
    role = "admin" if user.get("is_admin") else "student"
    token = create_access_token(user["id"], role=role)
    refresh = create_refresh_token(user["id"])
    user_out = UserOut(
        id=user["id"], name=user["name"], email=user["email"],
        plan=user.get("plan", "free"),
        credits_used=credits_info["used"],
        credits_limit=credits_info["limit"],
        onboarding_done=user.get("onboarding_done", False),
        is_admin=user.get("is_admin", False),
        created_at=user.get("created_at", ""),
        avatar_url=user.get("avatar_url", ""),
    )
    response.set_cookie(
        key="syrabit_session",
        value=token,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        max_age=JWT_ACCESS_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="syrabit_refresh",
        value=refresh,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=COOKIE_SAMESITE,
        path="/api/auth/refresh",
        max_age=JWT_REFRESH_EXPIRE_MINUTES * 60,
    )
    return TokenOut(access_token=token, user=user_out)

async def _send_password_reset_email(email: str, token: str):
    """Send password reset email via email_templates (Resend SDK)."""
    reset_url = f"{FRONTEND_URL}/reset-password"
    await email_templates.send_password_reset(email=email, token=token, reset_url=reset_url)

@router.post("/auth/reset-request")
async def reset_request(data: PasswordResetReq):
    user = await supa_get_user_for_reset(data.email.lower())
    if user:
        token = str(uuid.uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        await supa_create_password_reset(token, data.email.lower(), expires)
        await _send_password_reset_email(data.email.lower(), token)
    return {"message": "If the email exists, a reset link has been sent"}

@router.post("/auth/reset-confirm")
async def reset_confirm(data: PasswordResetConfirm):
    record = await supa_get_password_reset(data.token)
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    expires = datetime.fromisoformat(record["expires"])
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=400, detail="Reset token expired")
    await supa_update_user_password(record["email"], pwd_ctx.hash(data.new_password))
    await supa_delete_password_reset(data.token)
    return {"message": "Password updated successfully"}

@router.get("/auth/me", response_model=UserOut)
async def get_me(user: dict = Depends(get_current_user)):
    credits_info = await get_user_credits(user)
    return UserOut(
        id=user["id"], name=user["name"], email=user["email"],
        plan=user.get("plan", "free"),
        credits_used=credits_info["used"],
        credits_limit=credits_info["limit"],
        onboarding_done=user.get("onboarding_done", False),
        is_admin=user.get("is_admin", False),
        created_at=user.get("created_at", ""),
        avatar_url=user.get("avatar_url", ""),
    )

# ─────────────────────────────────────────────
# CONTENT ROUTES
