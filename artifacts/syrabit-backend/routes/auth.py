"""Syrabit.ai — Authentication routes"""
import re, json, asyncio, time, uuid, logging, hashlib, io, csv, os, base64, html as _html_mod
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

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/auth/signup", response_model=TokenOut)
async def signup(data: UserCreate, response: Response):
    existing = await supa_get_user(data.email.lower())
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    settings = await supa_get_settings()
    if not settings.get("registrations_open", True):
        raise HTTPException(status_code=403, detail="Registrations are currently closed")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
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
    }
    await supa_insert_user(user)
    token = create_access_token(user_id, role="student")
    refresh = create_refresh_token(user_id)
    user_out = UserOut(
        id=user_id, name=data.name, email=data.email.lower(),
        plan="free", credits_used=0, credits_limit=30,
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
    return TokenOut(access_token=token, user=user_out)

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
