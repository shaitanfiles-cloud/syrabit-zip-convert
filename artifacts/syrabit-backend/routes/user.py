"""Syrabit.ai — User profile & account routes"""
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
import deps
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional,
)
from db_ops import (
    supa_get_conversations,
    supa_update_user,
)
from llm import call_llm_api, call_llm_api_stream

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/user/onboarding")
async def save_onboarding(data: OnboardingData, user: dict = Depends(get_current_user)):
    update_data = {
        "onboarding_done": True,
        "board_id": data.board_id,
        "board_name": data.board_name,
        "class_id": data.class_id,
        "class_name": data.class_name,
    }
    if data.stream_id:
        update_data["stream_id"] = data.stream_id
    if data.stream_name:
        update_data["stream_name"] = data.stream_name
    if data.course_type:
        update_data["course_type"] = data.course_type
    if data.selected_subjects:
        update_data["selected_subjects"] = data.selected_subjects
    await supa_update_user(user["id"], update_data)
    return {"message": "Onboarding complete"}

@router.get("/user/profile")
async def get_profile(user: Optional[dict] = Depends(get_current_user_optional)):
    if not user:
        return {"user": None}
    credits_info = await get_user_credits(user)
    return {
        "id": user["id"],
        "name": user.get("name", ""),
        "email": user["email"],
        "bio": user.get("bio", ""),
        "phone": user.get("phone", ""),
        "plan": user.get("plan", "free"),
        "credits_used": credits_info["used"],
        "credits_limit": credits_info["limit"],
        "credits_remaining": credits_info["remaining"],
        "document_access": credits_info["document_access"],
        "onboarding_done": user.get("onboarding_done", False),
        "is_admin": user.get("is_admin", False),
        "board_id": user.get("board_id", ""),
        "board_name": user.get("board_name", ""),
        "class_id": user.get("class_id", ""),
        "class_name": user.get("class_name", ""),
        "stream_id": user.get("stream_id", ""),
        "stream_name": user.get("stream_name", ""),
        "course_type": user.get("course_type", ""),
        "selected_subjects": user.get("selected_subjects", []),
        "saved_subjects": user.get("saved_subjects", []),
        "created_at": user.get("created_at", ""),
        "avatar_url": user.get("avatar_url", ""),
        "status": user.get("status", "active"),
        "deletion_requested_at": user.get("deletion_requested_at"),
        "deletion_hard_at": user.get("deletion_hard_at"),
        "ads_opt_out": bool(user.get("ads_opt_out", False)),
    }

@router.patch("/user/profile")
async def update_profile(data: ProfileUpdate, user: dict = Depends(get_current_user)):
    update = {}
    if data.name:        update["name"]  = data.name
    if data.bio is not None: update["bio"] = data.bio
    if data.phone is not None: update["phone"] = data.phone
    if data.board_name is not None: update["board_name"] = data.board_name
    if data.class_name is not None: update["class_name"] = data.class_name
    if data.stream_name is not None: update["stream_name"] = data.stream_name
    if data.course_type is not None: update["course_type"] = data.course_type
    if data.selected_subjects is not None: update["selected_subjects"] = data.selected_subjects
    if data.ads_opt_out is not None: update["ads_opt_out"] = bool(data.ads_opt_out)
    if data.avatar_url is not None:
        if data.avatar_url and not data.avatar_url.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="Invalid avatar URL format")
        if data.avatar_url and len(data.avatar_url) > 3 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Avatar data too large")
        update["avatar_url"] = data.avatar_url
    if update:
        await supa_update_user(user["id"], update)
    return {"message": "Profile updated"}

@router.post("/user/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}")
    file_content = await file.read()
    max_size = 2 * 1024 * 1024
    if len(file_content) > max_size:
        raise HTTPException(status_code=400, detail="Image must be under 2 MB")
    import base64
    b64 = base64.b64encode(file_content).decode("utf-8")
    data_url = f"data:{file.content_type};base64,{b64}"
    await supa_update_user(user["id"], {"avatar_url": data_url})
    return {"avatar_url": data_url}

@router.get("/user/saved-subjects")
async def get_saved_subjects(user: dict = Depends(get_current_user)):
    return {"saved_subjects": user.get("saved_subjects", [])}

@router.post("/user/saved-subjects/{subject_id}")
async def toggle_saved_subject(subject_id: str, user: dict = Depends(get_current_user)):
    saved = user.get("saved_subjects", [])
    if subject_id in saved:
        saved.remove(subject_id)
        action = "removed"
    else:
        saved.append(subject_id)
        action = "added"
    await supa_update_user(user["id"], {"saved_subjects": saved})
    return {"message": action, "saved_subjects": saved}

@router.get("/user/credits")
async def get_credits(user: Optional[dict] = Depends(get_current_user_optional)):
    if not user:
        return {"used": 0, "limit": 30, "remaining": 30, "document_access": False}
    credits_info = await get_user_credits(user)
    return credits_info

@router.get("/user/stats")
async def get_user_stats(user: Optional[dict] = Depends(get_current_user_optional)):
    """Returns aggregated usage stats for the profile page."""
    if not user:
        return {"conversations": 0, "saved_subjects": 0, "total_tokens": 0, "credits_used": 0}
    conv_count = 0
    # Fast path: single COUNT query — much faster than fetching all conversations
    if deps.pg_pool:
        try:
            async with deps.pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM conversations WHERE user_id = $1", user["id"]
                )
                if row:
                    conv_count = int(row["cnt"])
        except Exception as e:
            logger.warning(f"pg conv count failed: {e}")
            convs = await supa_get_conversations(user["id"])
            conv_count = len(convs) if convs else 0
    else:
        convs = await supa_get_conversations(user["id"])
        conv_count = len(convs) if convs else 0
    saved_count = len(user.get("saved_subjects", []))
    total_tokens = user.get("credits_used", 0) * 300
    return {
        "conversations": conv_count,
        "saved_subjects": saved_count,
        "total_tokens": total_tokens,
        "credits_used": user.get("credits_used", 0),
    }

@router.delete("/user/account")
async def delete_account(user: dict = Depends(get_current_user)):
    """Soft-delete: marks account for deletion after 72 hours."""
    hard_delete_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
    await supa_update_user(user["id"], {
        "status": "pending_deletion",
        "deletion_requested_at": datetime.now(timezone.utc).isoformat(),
        "deletion_hard_at": hard_delete_at,
    })
    return {"message": "Account scheduled for deletion", "hard_delete_at": hard_delete_at}

@router.post("/user/account/cancel-delete")
async def cancel_delete_account(user: dict = Depends(get_current_user)):
    """Cancels a pending soft-delete within the 72h grace period."""
    await supa_update_user(user["id"], {
        "status": "active",
        "deletion_requested_at": None,
        "deletion_hard_at": None,
    })
    return {"message": "Account deletion cancelled"}

# ─────────────────────────────────────────────
# ADMIN AUTH
# ─────────────────────────────────────────────
