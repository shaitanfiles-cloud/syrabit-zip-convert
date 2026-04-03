"""Syrabit.ai — Conversation management"""
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

@router.get("/conversations")
async def get_conversations(user: Optional[dict] = Depends(get_current_user_optional)):
    if not user:
        return []
    convs = await supa_get_conversations(user["id"])
    return convs

@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, user: Optional[dict] = Depends(get_current_user_optional)):
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to access conversation history")
    conv = await supa_get_conversation(conv_id, user["id"])
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = conv.get("messages", [])
    if isinstance(messages, str):
        import json as _json
        try: messages = _json.loads(messages)
        except: messages = []
    _cache = {}
    for m in messages:
        if m.get("role") != "assistant":
            continue
        if m.get("rag_stream_name"):
            continue
        sid = m.get("rag_subject_id") or conv.get("subject_id")
        if not sid:
            continue
        if sid not in _cache:
            try:
                subj = await db.subjects.find_one({"id": sid}, {"_id": 0, "stream_id": 1})
                if subj and subj.get("stream_id"):
                    stream = await db.streams.find_one({"id": subj["stream_id"]}, {"_id": 0, "name": 1, "class_id": 1})
                    if stream:
                        cls = await db.classes.find_one({"id": stream["class_id"]}, {"_id": 0, "name": 1, "board_id": 1})
                        board = await db.boards.find_one({"id": cls["board_id"]}, {"_id": 0, "name": 1}) if cls else None
                        _cache[sid] = {
                            "stream_name": stream.get("name", ""),
                            "class_name": cls.get("name", "") if cls else "",
                            "board_name": board.get("name", "") if board else "",
                        }
                    else:
                        _cache[sid] = {}
                else:
                    _cache[sid] = {}
            except:
                _cache[sid] = {}
        ctx = _cache.get(sid, {})
        if ctx.get("stream_name"):
            m["rag_stream_name"] = ctx["stream_name"]
        if not m.get("rag_board_name") and ctx.get("board_name"):
            m["rag_board_name"] = ctx["board_name"]
        if not m.get("rag_class_name") and ctx.get("class_name"):
            m["rag_class_name"] = ctx["class_name"]
    conv["messages"] = messages
    return conv

@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: dict = Depends(get_current_user)):
    await supa_delete_conversation(conv_id, user["id"])
    return {"message": "Deleted"}

@router.patch("/conversations/{conv_id}")
async def update_conversation(conv_id: str, data: dict, user: dict = Depends(get_current_user)):
    allowed = {k: v for k, v in data.items() if k in ["title", "starred", "archived"]}
    if not allowed:
        raise HTTPException(status_code=400, detail="No valid fields")
    await supa_update_conversation(conv_id, user["id"], allowed)
    return {"message": "Updated"}

# ─────────────────────────────────────────────
# CHAT FEEDBACK (like / dislike / comment)
# ─────────────────────────────────────────────

class FeedbackPayload(BaseModel):
    conversation_id: Optional[str] = None
    message_index: Optional[int] = None
    message_preview: Optional[str] = None
    reaction: Optional[str] = None
    comment: Optional[str] = None

@router.post("/chat-feedback")
async def post_chat_feedback(payload: FeedbackPayload, user: Optional[dict] = Depends(get_current_user_optional)):
    uid = user["id"] if user else None
    if not payload.reaction and not payload.comment:
        raise HTTPException(status_code=400, detail="Nothing to save")
    if payload.reaction and payload.reaction not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="Invalid reaction")
    preview = (payload.message_preview or "")[:300]
    try:
        if pg_pool:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO chat_feedback (user_id, conversation_id, message_index, message_preview, reaction, comment)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    uid, payload.conversation_id, payload.message_index, preview,
                    payload.reaction, (payload.comment or "")[:1000] if payload.comment else None,
                )
        return {"ok": True}
    except Exception as e:
        logger.error(f"chat-feedback save error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")

@router.get("/chat-feedback")
async def get_chat_feedback(admin: dict = Depends(get_admin_user), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    if not pg_pool:
        return []
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT f.*, u.name as user_name, u.email as user_email
               FROM chat_feedback f LEFT JOIN users u ON f.user_id::text = u.id::text
               ORDER BY f.created_at DESC LIMIT $1 OFFSET $2""",
            limit, offset,
        )
        return [dict(r) for r in rows]

@router.get("/chat-feedback/stats")
async def get_feedback_stats(admin: dict = Depends(get_admin_user)):
    if not pg_pool:
        return {"total": 0, "likes": 0, "dislikes": 0, "comments": 0}
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COUNT(*) as total,
                      COUNT(*) FILTER (WHERE reaction='like') as likes,
                      COUNT(*) FILTER (WHERE reaction='dislike') as dislikes,
                      COUNT(*) FILTER (WHERE comment IS NOT NULL AND comment != '') as comments
               FROM chat_feedback"""
        )
        return dict(row)

# ─────────────────────────────────────────────
# USER PROFILE ROUTES
# ─────────────────────────────────────────────
