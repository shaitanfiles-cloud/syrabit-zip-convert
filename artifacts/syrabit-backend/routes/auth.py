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
    GoogleAuthRequest,
)
from config import (
    COOKIE_DOMAIN,
    COOKIE_SAMESITE,
    FRONTEND_URL,
    JWT_ACCESS_EXPIRE_MINUTES,
    JWT_REFRESH_EXPIRE_MINUTES,
    SECURE_COOKIES,
)
from deps import pwd_ctx
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional,
)
from db_ops import (
    supa_create_password_reset,
    supa_delete_password_reset,
    supa_get_password_reset,
    supa_get_settings,
    supa_get_user,
    supa_get_user_for_reset,
    supa_insert_user,
    supa_update_user,
    supa_update_user_password,
)
from llm import call_llm_api, call_llm_api_stream
import email_templates

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/auth/signup")
async def signup(data: UserCreate, response: Response):
    existing = await supa_get_user(data.email.lower())
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if not data.consent_dpdp:
        raise HTTPException(status_code=400, detail="You must consent to data processing under the DPDP Act to create an account")

    settings = await supa_get_settings()
    if not settings.get("registrations_open", True):
        raise HTTPException(status_code=403, detail="Registrations are currently closed")

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    user = {
        "id": user_id,
        "name": data.name,
        "email": data.email.lower(),
        "password_hash": await asyncio.to_thread(pwd_ctx.hash, data.password),
        "plan": "free",
        "credits_used": 0,
        "credits_limit": 30,
        "document_access": "zero",
        "onboarding_done": False,
        "is_admin": False,
        "status": "active",
        "bio": "",
        "phone": "",
        "saved_subjects": [],
        "has_free_credits_issued": True,
        "consent_dpdp": data.consent_dpdp,
        "consent_dpdp_version": "1.0" if data.consent_dpdp else None,
        "consent_dpdp_at": now if data.consent_dpdp else None,
        "created_at": now,
    }
    await supa_insert_user(user)
    if data.consent_dpdp:
        try:
            await supa_update_user(user_id, {
                "consent_dpdp": True,
                "consent_dpdp_version": "1.0",
                "consent_dpdp_at": now,
            })
        except Exception:
            pass

    token = create_access_token(user_id, role="student", plan="free")
    refresh = create_refresh_token(user_id)
    user_out = UserOut(
        id=user_id, name=data.name, email=data.email.lower(),
        plan="free", credits_used=0, credits_limit=user.get("credits_limit", 30),
        onboarding_done=False, is_admin=False, created_at=now
    )
    _session_kwargs = dict(key="syrabit_session", value=token, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, max_age=JWT_ACCESS_EXPIRE_MINUTES * 60)
    _refresh_kwargs = dict(key="syrabit_refresh", value=refresh, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, path="/api/auth/refresh", max_age=JWT_REFRESH_EXPIRE_MINUTES * 60)
    if COOKIE_DOMAIN:
        _session_kwargs["domain"] = COOKIE_DOMAIN
        _refresh_kwargs["domain"] = COOKIE_DOMAIN
    response.set_cookie(**_session_kwargs)
    response.set_cookie(**_refresh_kwargs)
    return {"access_token": token, "token_type": "bearer", "user": user_out.dict()}

@router.post("/auth/login", response_model=TokenOut)
async def login(data: UserLogin, response: Response):
    user = await supa_get_user(data.email.lower())
    pw_hash = user.get("password_hash", "") if user else ""
    if not user or not pw_hash or not await asyncio.to_thread(pwd_ctx.verify, data.password, pw_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("status") == "banned":
        raise HTTPException(status_code=403, detail="Account banned")

    credits_info = await get_user_credits(user)
    role = "admin" if user.get("is_admin") else "student"
    token = create_access_token(user["id"], role=role, plan=user.get("plan", "free"))
    refresh = create_refresh_token(user["id"])
    user_out = UserOut(
        id=user["id"], name=user["name"], email=user["email"],
        plan=user.get("plan", "free"),
        credits_used=credits_info["used"],
        credits_limit=credits_info["limit"],
        onboarding_done=user.get("onboarding_done", False),
        is_admin=user.get("is_admin", False),
        board_id=user.get("board_id"),
        class_id=user.get("class_id"),
        stream_id=user.get("stream_id"),
        created_at=user.get("created_at", ""),
        avatar_url=user.get("avatar_url", ""),
        ads_opt_out=bool(user.get("ads_opt_out", False)),
    )
    _session_kwargs = dict(key="syrabit_session", value=token, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, max_age=JWT_ACCESS_EXPIRE_MINUTES * 60)
    _refresh_kwargs = dict(key="syrabit_refresh", value=refresh, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, path="/api/auth/refresh", max_age=JWT_REFRESH_EXPIRE_MINUTES * 60)
    if COOKIE_DOMAIN:
        _session_kwargs["domain"] = COOKIE_DOMAIN
        _refresh_kwargs["domain"] = COOKIE_DOMAIN
    response.set_cookie(**_session_kwargs)
    response.set_cookie(**_refresh_kwargs)
    return TokenOut(access_token=token, user=user_out)

@router.get("/auth/google/client-id")
async def google_client_id():
    from config import GOOGLE_CLIENT_ID
    if not GOOGLE_CLIENT_ID:
        return {"client_id": None}
    return {"client_id": GOOGLE_CLIENT_ID}


@router.post("/auth/google")
async def google_auth(data: GoogleAuthRequest, response: Response):
    from config import GOOGLE_CLIENT_ID

    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
    except ImportError:
        logger.error("google-auth library not installed")
        raise HTTPException(status_code=503, detail="Google sign-in is temporarily unavailable")

    try:
        idinfo = google_id_token.verify_oauth2_token(
            data.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except ValueError as e:
        logger.warning(f"Google token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google credential")
    except Exception as e:
        logger.error(f"Google token verification error: {e}")
        raise HTTPException(status_code=502, detail="Failed to verify Google credential")

    google_email = idinfo.get("email", "").lower()
    google_name = idinfo.get("name", "")
    google_sub = idinfo.get("sub", "")
    google_avatar = idinfo.get("picture", "")

    if not google_email or not idinfo.get("email_verified"):
        raise HTTPException(status_code=400, detail="Google account email not verified")

    existing = await supa_get_user(google_email)

    if existing:
        if existing.get("status") == "banned":
            raise HTTPException(status_code=403, detail="Account banned")

        stored_google_id = existing.get("google_id")
        if stored_google_id and stored_google_id != google_sub:
            logger.warning(f"Google ID mismatch for {google_email}: stored={stored_google_id}, incoming={google_sub}")
            raise HTTPException(status_code=409, detail="This email is linked to a different Google account")

        if not stored_google_id:
            await supa_update_user(existing["id"], {
                "google_id": google_sub,
                "auth_provider": existing.get("auth_provider") or "google",
            })

        credits_info = await get_user_credits(existing)
        role = "admin" if existing.get("is_admin") else "student"
        token = create_access_token(existing["id"], role=role, plan=existing.get("plan", "free"))
        refresh = create_refresh_token(existing["id"])
        user_out = UserOut(
            id=existing["id"], name=existing["name"], email=existing["email"],
            plan=existing.get("plan", "free"),
            credits_used=credits_info["used"],
            credits_limit=credits_info["limit"],
            onboarding_done=existing.get("onboarding_done", False),
            is_admin=existing.get("is_admin", False),
            board_id=existing.get("board_id"),
            class_id=existing.get("class_id"),
            stream_id=existing.get("stream_id"),
            created_at=existing.get("created_at", ""),
            avatar_url=existing.get("avatar_url", ""),
            ads_opt_out=bool(existing.get("ads_opt_out", False)),
        )
    else:
        settings = await supa_get_settings()
        if not settings.get("registrations_open", True):
            raise HTTPException(status_code=403, detail="Registrations are currently closed")

        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        user = {
            "id": user_id,
            "name": google_name,
            "email": google_email,
            "password_hash": "",
            "plan": "free",
            "credits_used": 0,
            "credits_limit": 30,
            "document_access": "zero",
            "onboarding_done": False,
            "is_admin": False,
            "status": "active",
            "bio": "",
            "phone": "",
            "saved_subjects": [],
            "has_free_credits_issued": True,
            "created_at": now,
            "google_id": google_sub,
            "auth_provider": "google",
            "avatar_url": google_avatar,
        }
        await supa_insert_user(user)

        role = "student"
        token = create_access_token(user_id, role=role, plan="free")
        refresh = create_refresh_token(user_id)
        user_out = UserOut(
            id=user_id, name=google_name, email=google_email,
            plan="free", credits_used=0, credits_limit=30,
            onboarding_done=False, is_admin=False, created_at=now,
            avatar_url=google_avatar,
        )

    _session_kwargs = dict(key="syrabit_session", value=token, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, max_age=JWT_ACCESS_EXPIRE_MINUTES * 60)
    _refresh_kwargs = dict(key="syrabit_refresh", value=refresh, httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE, path="/api/auth/refresh", max_age=JWT_REFRESH_EXPIRE_MINUTES * 60)
    if COOKIE_DOMAIN:
        _session_kwargs["domain"] = COOKIE_DOMAIN
        _refresh_kwargs["domain"] = COOKIE_DOMAIN
    response.set_cookie(**_session_kwargs)
    response.set_cookie(**_refresh_kwargs)
    return {"access_token": token, "token_type": "bearer", "user": user_out.dict()}


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
    await supa_update_user_password(record["email"], await asyncio.to_thread(pwd_ctx.hash, data.new_password))
    await supa_delete_password_reset(data.token)
    return {"message": "Password updated successfully"}

@router.get("/auth/me")
async def get_me(user: Optional[dict] = Depends(get_current_user_optional)):
    if not user:
        return {"user": None}
    credits_info = await get_user_credits(user)
    return UserOut(
        id=user["id"], name=user["name"], email=user["email"],
        plan=user.get("plan", "free"),
        credits_used=credits_info["used"],
        credits_limit=credits_info["limit"],
        onboarding_done=user.get("onboarding_done", False),
        is_admin=user.get("is_admin", False),
        board_id=user.get("board_id"),
        class_id=user.get("class_id"),
        stream_id=user.get("stream_id"),
        created_at=user.get("created_at", ""),
        avatar_url=user.get("avatar_url", ""),
        ads_opt_out=bool(user.get("ads_opt_out", False)),
    )


class _ConsentWithdrawReq(BaseModel):
    withdraw: bool = True


@router.get("/privacy/consent")
async def get_consent(user: dict = Depends(get_current_user)):
    return {
        "consent_dpdp": user.get("consent_dpdp", False),
        "consent_dpdp_version": user.get("consent_dpdp_version"),
        "consent_dpdp_at": user.get("consent_dpdp_at"),
    }


@router.post("/privacy/consent")
async def update_consent(body: _ConsentWithdrawReq, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    if body.withdraw:
        updates = {
            "consent_dpdp": False,
            "consent_dpdp_version": None,
            "consent_dpdp_at": None,
        }
        await supa_update_user(user["id"], updates)
        logger.info(f"[privacy] User {user['id']} withdrew DPDP consent")
        return {"status": "withdrawn", "consent_dpdp": False, "withdrawn_at": now}
    else:
        updates = {
            "consent_dpdp": True,
            "consent_dpdp_version": "1.0",
            "consent_dpdp_at": now,
        }
        await supa_update_user(user["id"], updates)
        logger.info(f"[privacy] User {user['id']} granted DPDP consent v1.0")
        return {"status": "granted", "consent_dpdp": True, "consent_dpdp_version": "1.0", "consent_dpdp_at": now}


@router.post("/security/csp-report")
async def csp_report(request: Request):
    try:
        body = await request.json()
        report = body.get("csp-report", body)
        logger.warning(f"[CSP-VIOLATION] {json.dumps(report, default=str)[:500]}")
    except Exception:
        pass
    return JSONResponse(status_code=204, content=None)


# ─────────────────────────────────────────────
# CONTENT ROUTES
