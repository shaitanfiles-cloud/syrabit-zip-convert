"""Syrabit.ai — AI chat & search routes"""
import re, json, asyncio, time, time as _time_mod, uuid, logging, hashlib, io, csv, os, base64, html as _html_mod
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
import deps
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
from prompts import _classify_intent, _is_out_of_scope_response
from subject_router import build_search_scope
from qa_engine import log_chat_message as _log_chat_message

logger = logging.getLogger(__name__)

def _get_syllabus_embedder():
    import server as _s
    return _s._syllabus_embedder

def _record_llm_cost(model, prompt_tokens, completion_tokens, provider="gemini", user_id=""):
    from routes.admin_advanced import record_llm_cost
    record_llm_cost(model, prompt_tokens, completion_tokens, provider, user_id)

router = APIRouter()

async def _resolve_subject_context(subject_id: str) -> dict:
    """
    Given a subject_id, walk subject → stream → class → board and return
    the resolved board/class/stream IDs and names.  Returns an empty dict
    if subject_id is absent or any lookup fails.
    """
    if not subject_id:
        return {}
    try:
        subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0, "stream_id": 1})
        if not subj or not subj.get("stream_id"):
            return {}
        stream = await db.streams.find_one({"id": subj["stream_id"]}, {"_id": 0, "id": 1, "name": 1, "class_id": 1})
        if not stream:
            return {}
        cls = await db.classes.find_one({"id": stream["class_id"]}, {"_id": 0, "id": 1, "name": 1, "board_id": 1})
        if not cls:
            return {}
        board = await db.boards.find_one({"id": cls["board_id"]}, {"_id": 0, "id": 1, "name": 1})
        if not board:
            return {}
        return {
            "board_id":   board["id"],
            "board_name": board["name"],
            "class_id":   cls["id"],
            "class_name": cls["name"],
            "stream_id":  stream["id"],
            "stream_name": stream["name"],
        }
    except Exception as e:
        logger.warning(f"_resolve_subject_context({subject_id}) failed: {e}")
        return {}
@router.post("/ai/chat")
async def chat(msg: ChatMessage, user: dict = Depends(rate_limit_chat)):
    _chat_t0 = _time_mod.time()
    credits_info = await get_user_credits(user)
    if credits_info["remaining"] <= 0:
        raise HTTPException(status_code=402, detail=f"Credit limit reached ({credits_info['limit']} lifetime credits). Upgrade your plan for more.")

    plan = user.get("plan", "free")
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]

    # ── Tier 0: card_context (library scrape) → document_id (PDF upload) ──────
    document_text: Optional[str] = None
    if msg.card_context and msg.card_context.strip():
        document_text = msg.card_context
        logger.info(f"Chat [NON-STREAM]: Tier 0 card_context ({len(document_text)} chars) used as grounding")
    elif msg.document_id:
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        if subj and subj.get("document_text"):
            document_text = subj["document_text"]
            logger.info(f"Chat [NON-STREAM]: Tier 0 doc loaded from subject {msg.document_id}")

    # ── Resolve subject's own board/class/stream (overrides user profile) ────
    subj_ctx = await _resolve_subject_context(msg.subject_id)
    ctx_board_id   = subj_ctx.get("board_id")   or msg.board_id
    ctx_class_id   = subj_ctx.get("class_id")   or msg.class_id
    ctx_stream_id  = subj_ctx.get("stream_id")  or getattr(msg, 'stream_id', None)
    ctx_board_name = subj_ctx.get("board_name") or msg.board_name or user.get("board_name", "")
    ctx_class_name = subj_ctx.get("class_name") or msg.class_name or user.get("class_name", "")
    ctx_stream_name= subj_ctx.get("stream_name") or getattr(msg, 'stream_name', None) or user.get("stream_name", "")
    if subj_ctx:
        logger.info(f"Chat [NON-STREAM]: Subject context resolved → {ctx_board_name} / {ctx_class_name} / {ctx_stream_name}")

    # ── Fetch syllabus (subject → stream → board+class fallback) ────────────
    syllabus = None
    if ctx_board_id and ctx_class_id:
        try:
            if ctx_stream_id and msg.subject_id:
                syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id, "subject_id": msg.subject_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Subject syllabus loaded for {ctx_board_id}/{ctx_class_id}/{ctx_stream_id}/{msg.subject_id}")
            if not syllabus and ctx_stream_id:
                syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Stream syllabus loaded for {ctx_board_id}/{ctx_class_id}/{ctx_stream_id}")
            if not syllabus:
                syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": {"$exists": False}}, {"_id": 0})
                if not syllabus:
                    syllabus = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id}, {"_id": 0})
                if syllabus:
                    logger.info(f"Chat [NON-STREAM]: Board+class syllabus loaded for {ctx_board_id}/{ctx_class_id}")
        except Exception as e:
            logger.error(f"Failed to fetch syllabus: {e}")

    # ── Internal-content-first: MongoDB RAG → web fallback ──────────────
    _detected_intent = _classify_intent(msg.message)
    _is_casual_sync = _detected_intent == "casual"

    if _is_casual_sync:
        web_results = []
        _ns_route = None
        rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                   "vector_hits": [], "source": "none", "quality": "none"}
    else:
        _ns_scoped_query, _ns_route = await build_search_scope(
            msg.message,
            board_name=ctx_board_name,
            class_name=ctx_class_name,
            subject_name=msg.subject_name or "",
            embedder=_get_syllabus_embedder(),
        )
        rag_ctx = await resolve_rag_context(
            msg.message,
            subject_id=msg.subject_id,
            subject_name=msg.subject_name,
            document_text=document_text,
            intent=_detected_intent,
        )
        _ns_rag_quality = rag_ctx.get("quality", "none")
        if _ns_rag_quality in ("high", "tier0"):
            logger.info(f"[NON-STREAM][INTERNAL-FIRST] RAG quality={_ns_rag_quality} | web search skipped")
            web_results = []
        elif _ns_rag_quality == "medium":
            logger.info(f"[NON-STREAM][INTERNAL-FIRST] RAG quality=medium | running web search as supplement")
            web_results = await web_search_with_fallback(
                msg.message, num_results=8,
                board_name=ctx_board_name,
                class_name=ctx_class_name,
                subject_name=msg.subject_name or "",
                scoped_query=_ns_scoped_query,
            )
            if web_results:
                logger.info(f"[NON-STREAM][INTERNAL-FIRST] Merged: internal medium + {len(web_results)} web results")
        else:
            logger.info("[NON-STREAM][INTERNAL-FIRST] RAG quality=none | [WEB-FALLBACK] running web search")
            web_results = await web_search_with_fallback(
                msg.message, num_results=8,
                board_name=ctx_board_name,
                class_name=ctx_class_name,
                subject_name=msg.subject_name or "",
                scoped_query=_ns_scoped_query,
            )
            if web_results:
                logger.info(f"[NON-STREAM][WEB-FALLBACK] {len(web_results)} web results found")
                rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                           "vector_hits": [], "source": "web", "quality": "web"}
            else:
                logger.info("[NON-STREAM][WEB-FALLBACK] Web search also empty — AI uses training knowledge")

    # ── Build RAG-enriched system prompt ─────────────────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name":  ctx_board_name,
            "class_name":  ctx_class_name,
            "stream_name": ctx_stream_name,
            "subject_name": msg.subject_name,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        user.get("name", ""),
            "board_name":  ctx_board_name or user.get("board_name", ""),
            "class_name":  ctx_class_name or user.get("class_name", ""),
            "stream_name": ctx_stream_name or user.get("stream_name", ""),
            "plan":        user.get("plan", "free"),
        },
        query=msg.message,
        syllabus=syllabus,
        web_results=web_results or None,
    )

    conv_id = msg.conversation_id
    history_messages = []

    if conv_id:
        conv = await supa_get_conversation(conv_id, user["id"])
        if conv:
            raw_history = [
                {"role": m.get("role", ""), "content": m.get("content") or ""}
                for m in conv.get("messages", [])
                if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
            ]
            history_messages = _trim_history(raw_history)
    else:
        conv_id = str(uuid.uuid4())
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        conv_doc = {
            "id": conv_id,
            "user_id": user["id"],
            "title": title,
            "subject_id": msg.subject_id,
            "subject_name": msg.subject_name,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await supa_upsert_conversation(conv_doc)

    messages = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": msg.message}]

    # ── Cache check (Non-streaming) — Redis first, in-memory fallback ───────
    is_casual = _detected_intent == "casual"
    cache_key = _cache_key(msg.message, subject_id=msg.subject_id or "", board_id=ctx_board_id or "", conversation_id=conv_id or "")
    _cache_ttl = REDIS_CASUAL_CACHE_TTL if is_casual else REDIS_AI_CACHE_TTL
    answer = None

    answer = _redis_get_ai_cache(cache_key)
    if answer:
        logger.info(f"Redis cache HIT: {cache_key}")
    elif cache_key in _ai_response_cache:
        answer = _ai_response_cache[cache_key]
        logger.info(f"Memory cache HIT: {cache_key}")

    if answer is None:
        try:
            answer = await call_llm_api(messages, model=msg.model or LLM_MODEL, max_tokens=max_tokens)
            _redis_set("ai_cache", cache_key, answer, _cache_ttl)
            if not redis_client:
                _ai_response_cache[cache_key] = answer
            logger.info(f"Cache MISS → stored (ttl={_cache_ttl}s): {cache_key}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"AI chat error: {e}")
            raise HTTPException(status_code=503, detail="AI service temporarily unavailable")

    # Derive sources from the same RAG context sent to the LLM (no mismatch)
    lib_sources = _sources_from_rag_ctx(rag_ctx)

    now = datetime.now(timezone.utc).isoformat()
    _rag_subject_ids = list({s["id"] for s in rag_ctx.get("subjects", []) if s.get("id")})
    _rag_subject_names = list({s.get("name","") for s in rag_ctx.get("subjects", []) if s.get("name")})
    _src_sid = _rag_subject_ids[0] if _rag_subject_ids else msg.subject_id
    _src_ctx = await _resolve_subject_context(_src_sid) if _src_sid else {}
    _src_board = _src_ctx.get("board_name") or ctx_board_name or ""
    _src_class = _src_ctx.get("class_name") or ctx_class_name or ""
    _src_stream = _src_ctx.get("stream_name") or ctx_stream_name or ""
    new_messages = [
        {"role": "user", "content": msg.message, "timestamp": now},
        {"role": "assistant", "content": answer, "timestamp": now,
         "rag_source": rag_ctx.get("source", "none"),
         "rag_chunks": len(rag_ctx.get("chunks", [])),
         "sources": lib_sources,
         "rag_subject_id": _rag_subject_ids[0] if _rag_subject_ids else None,
         "rag_subject_name": _rag_subject_names[0] if _rag_subject_names else msg.subject_name,
         "rag_board_name": _src_board,
         "rag_class_name": _src_class,
         "rag_stream_name": _src_stream},
    ]
    # Update conversation in Supabase
    conv = await supa_get_conversation(conv_id, user["id"])
    if conv:
        existing_msgs = conv.get("messages", [])
        if isinstance(existing_msgs, str):
            try: existing_msgs = json.loads(existing_msgs)
            except: existing_msgs = []
        updated_msgs = existing_msgs + new_messages
        await supa_update_conversation(conv_id, user["id"], {
            "messages": json.dumps(updated_msgs) if supa else updated_msgs,
            "updated_at": now,
            "preview": answer[:100],
            "tokens": len(answer.split()),
        })

    # Deduct 1 credit atomically (guards against parallel request exploitation)
    deducted = await atomic_deduct_credit(user["id"], credits_info["used"], credits_info["limit"])
    if not deducted:
        raise HTTPException(status_code=402, detail="Credit limit reached. Upgrade your plan for more.")
    new_used = credits_info["used"] + 1

    # Fire-and-forget: log chat turn for QA curation
    asyncio.create_task(_log_chat_message(
        user_id=user["id"],
        question=msg.message,
        raw_ai_answer=answer,
        subject_id=msg.subject_id,
        subject_name=msg.subject_name,
        board_name=ctx_board_name,
        class_name=ctx_class_name,
        conversation_id=conv_id,
    ))

    try:
        _record_chat_latency((_time_mod.time() - _chat_t0) * 1000)
    except Exception:
        pass

    try:
        _prompt_chars = sum(len(m.get("content", "")) for m in messages)
        _compl_chars  = len(answer) if answer else 0
        _record_llm_cost(
            model=msg.model or LLM_MODEL,
            prompt_tokens=max(1, _prompt_chars // 4),
            completion_tokens=max(1, _compl_chars // 4),
            provider="gemini",
            user_id=str(user["id"]),
        )
    except Exception:
        pass

    return {
        "answer": answer,
        "conversation_id": conv_id,
        "credits_remaining": max(0, credits_info["remaining"] - 1),
        "credits_used": new_used,
        "rag_source": rag_ctx.get("source", "none"),
        "rag_chunks_used": len(rag_ctx.get("chunks", [])),
        "sources": lib_sources,
    }

async def _refund_credit(uid: str, credits_used: int) -> None:
    """Refund 1 credit (decrement credits_used) when streaming fails/empty answer."""
    try:
        if deps.pg_pool:
            async with deps.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET credits_used = GREATEST(0, credits_used - 1) WHERE id = $1",
                    uid,
                )
            return
        if redis_client:
            redis_key = f"credits:{uid}"
            refunded_count = redis_client.decr(redis_key)
            # Persist refunded count back to authoritative Supabase store (best-effort)
            if refunded_count is not None and refunded_count >= 0:
                await supa_update_user(uid, {"credits_used": int(refunded_count)})
            return
        if credits_used > 0:
            await supa_update_user(uid, {"credits_used": credits_used - 1})
    except Exception as e:
        logger.warning(f"_refund_credit failed: {e}")

async def _persist_chat_turn(
    conv_id: str, user_id: str,
    user_msg: str, answer: str,
    rag_source: str, rag_chunks: int,
    credits_used_before: int,
    deduct_credit: bool = False,
    sources: list | None = None,
    rag_subject_id: str | None = None,
    rag_subject_name: str | None = None,
    rag_board_name: str | None = None,
    rag_class_name: str | None = None,
    rag_stream_name: str | None = None,
):
    """Background: save conversation messages. Optionally deduct 1 credit. Non-blocking."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        assistant_msg = {
            "role": "assistant", "content": answer, "timestamp": now,
            "rag_source": rag_source, "rag_chunks": rag_chunks,
        }
        if sources:
            assistant_msg["sources"] = sources
        if rag_subject_id:
            assistant_msg["rag_subject_id"] = rag_subject_id
        if rag_subject_name:
            assistant_msg["rag_subject_name"] = rag_subject_name
        if rag_board_name:
            assistant_msg["rag_board_name"] = rag_board_name
        if rag_class_name:
            assistant_msg["rag_class_name"] = rag_class_name
        if rag_stream_name:
            assistant_msg["rag_stream_name"] = rag_stream_name
        new_msgs = [
            {"role": "user", "content": user_msg, "timestamp": now},
            assistant_msg,
        ]
        conv = await supa_get_conversation(conv_id, user_id)
        if conv:
            existing = conv.get("messages", [])
            if isinstance(existing, str):
                try: existing = json.loads(existing)
                except: existing = []
            updated = existing + new_msgs
            await supa_update_conversation(conv_id, user_id, {
                "messages": json.dumps(updated) if supa else updated,
                "updated_at": now,
                "preview": answer[:100],
                "tokens": len(answer.split()),
            })
        if deduct_credit:
            await atomic_deduct_credit(user_id, credits_used_before, 999999)
    except Exception as e:
        logger.warning(f"_persist_chat_turn failed: {e}")

@router.post("/ai/chat/stream")
async def chat_stream(msg: ChatMessage, user: dict = Depends(rate_limit_chat)):
    _stream_t0 = _time_mod.time()
    credits_info = await get_user_credits(user)
    if credits_info["remaining"] <= 0:
        raise HTTPException(status_code=402, detail=f"Credit limit reached ({credits_info['limit']} lifetime credits). Upgrade your plan for more.")

    # Atomically reserve 1 credit before streaming begins to prevent parallel bypass
    deducted = await atomic_deduct_credit(user["id"], credits_info["used"], credits_info["limit"])
    if not deducted:
        raise HTTPException(status_code=402, detail="Credit limit reached. Upgrade your plan for more.")

    plan = user.get("plan", "free")
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]

    # ── Resolve subject's own board/class/stream (overrides user profile) ────
    subj_ctx = await _resolve_subject_context(msg.subject_id)
    ctx_board_id   = subj_ctx.get("board_id")   or msg.board_id
    ctx_class_id   = subj_ctx.get("class_id")   or msg.class_id
    ctx_stream_id  = subj_ctx.get("stream_id")  or getattr(msg, 'stream_id', None)
    ctx_board_name = subj_ctx.get("board_name") or msg.board_name or user.get("board_name", "")
    ctx_class_name = subj_ctx.get("class_name") or msg.class_name or user.get("class_name", "")
    ctx_stream_name= subj_ctx.get("stream_name") or getattr(msg, 'stream_name', None) or user.get("stream_name", "")
    if subj_ctx:
        logger.info(f"Chat [STREAM]: Subject context resolved → {ctx_board_name} / {ctx_class_name} / {ctx_stream_name}")

    # ── Phase 1: document + syllabus in parallel ──────────────────────────────
    async def _fetch_doc():
        # card_context (library card scrape) takes highest priority — same as PDF Tier 0
        if msg.card_context and msg.card_context.strip():
            logger.info(f"Chat [STREAM]: Tier 0 card_context ({len(msg.card_context)} chars) used as grounding")
            return msg.card_context
        if not msg.document_id:
            return None
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        return (subj or {}).get("document_text")

    async def _fetch_syllabus():
        if not (ctx_board_id and ctx_class_id):
            return None
        _sck = _syllabus_cache_key(ctx_board_id, ctx_class_id, ctx_stream_id, msg.subject_id)
        if _sck in _syllabus_cache:
            return _syllabus_cache[_sck]
        try:
            s = None
            if ctx_stream_id and msg.subject_id:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id, "subject_id": msg.subject_id}, {"_id": 0})
            if not s and ctx_stream_id:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": ctx_stream_id}, {"_id": 0})
            if not s:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id, "stream_id": {"$exists": False}}, {"_id": 0})
            if not s:
                s = await db.syllabi.find_one({"board_id": ctx_board_id, "class_id": ctx_class_id}, {"_id": 0})
            if s:
                _syllabus_cache[_sck] = s
            return s
        except Exception:
            return None

    document_text, syllabus = await asyncio.gather(_fetch_doc(), _fetch_syllabus())

    # ── Phase 2: RAG + conversation history in parallel ───────────────────────
    async def _fetch_history():
        if not msg.conversation_id:
            return None
        return await supa_get_conversation(msg.conversation_id, user["id"])

    _stream_intent = _classify_intent(msg.message)
    _is_casual = _stream_intent == "casual"

    if _is_casual:
        web_results = []
        _sr_route = None
        raw_conv = await _fetch_history()
        rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                   "vector_hits": [], "source": "none", "quality": "none"}
    else:
        _sr_scoped_query, _sr_route = await build_search_scope(
            msg.message,
            board_name=ctx_board_name,
            class_name=ctx_class_name,
            subject_name=msg.subject_name or "",
            embedder=_get_syllabus_embedder(),
        )
        # Step 1: Internal RAG first (content cards, vector hits, DB chunks) + history
        rag_ctx, raw_conv = await asyncio.gather(
            resolve_rag_context(
                msg.message, subject_id=msg.subject_id,
                subject_name=msg.subject_name, document_text=document_text,
                intent=_stream_intent,
            ),
            _fetch_history(),
        )
        _rag_quality = rag_ctx.get("quality", "none")
        # Step 2: Web search only when internal content is insufficient
        if _rag_quality in ("high", "tier0"):
            logger.info(f"[STREAM][INTERNAL-FIRST] RAG quality={_rag_quality} | web search skipped")
            web_results = []
        elif _rag_quality == "medium":
            logger.info(f"[STREAM][INTERNAL-FIRST] RAG quality=medium | running web search as supplement")
            web_results = await web_search_with_fallback(
                msg.message, num_results=8,
                board_name=ctx_board_name,
                class_name=ctx_class_name,
                subject_name=msg.subject_name or "",
                scoped_query=_sr_scoped_query,
            )
            if web_results:
                logger.info(f"[STREAM][INTERNAL-FIRST] Merged: internal medium + {len(web_results)} web results")
        else:
            logger.info("[STREAM][INTERNAL-FIRST] RAG quality=none | [WEB-FALLBACK] running web search")
            web_results = await web_search_with_fallback(
                msg.message, num_results=8,
                board_name=ctx_board_name,
                class_name=ctx_class_name,
                subject_name=msg.subject_name or "",
                scoped_query=_sr_scoped_query,
            )
            if web_results:
                logger.info(f"[STREAM][WEB-FALLBACK] {len(web_results)} web results found")
                rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
                           "vector_hits": [], "source": "web", "quality": "web"}
            else:
                logger.info("[STREAM][WEB-FALLBACK] Web search also empty — AI uses training knowledge")

    # ── Build prompt ───────────────────────────────────────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name":  ctx_board_name,
            "class_name":  ctx_class_name,
            "stream_name": ctx_stream_name,
            "subject_name": msg.subject_name,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        user.get("name", ""),
            "board_name":  ctx_board_name or user.get("board_name", ""),
            "class_name":  ctx_class_name or user.get("class_name", ""),
            "stream_name": ctx_stream_name or user.get("stream_name", ""),
            "plan":        user.get("plan", "free"),
        },
        query=msg.message,
        syllabus=syllabus,
        web_results=web_results or None,
    )

    conv_id = msg.conversation_id
    history_messages = []

    if conv_id and raw_conv:
        raw_history = [
            {"role": m.get("role", ""), "content": m.get("content") or ""}
            for m in raw_conv.get("messages", [])
            if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
        ]
        history_messages = _trim_history(raw_history)
    elif not conv_id:
        conv_id = str(uuid.uuid4())
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        conv_doc = {
            "id": conv_id,
            "user_id": user["id"],
            "title": title,
            "subject_id": msg.subject_id,
            "subject_name": msg.subject_name,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        asyncio.create_task(supa_upsert_conversation(conv_doc))

    messages_payload = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": msg.message}]

    user_msg_saved   = msg.message
    rag_source_saved = rag_ctx.get("source",  "none")
    rag_quality_saved = rag_ctx.get("quality", "none")
    rag_chunks_count = len(rag_ctx.get("chunks",   []))
    rag_subjects_count = len(rag_ctx.get("subjects", []))
    web_search_used  = bool(web_results)
    content_card_meta = rag_ctx.get("content_card_meta") or None
    # Resolve the primary subject this answer came from (for frontend badge link)
    _rag_subjs = rag_ctx.get("subjects", [])
    _rag_has_real_subject = bool(_rag_subjs and _rag_subjs[0].get("id"))
    rag_subject_id   = (_rag_subjs[0].get("id")   if _rag_has_real_subject else None) or msg.subject_id   or None
    rag_subject_name = (_rag_subjs[0].get("name") if _rag_has_real_subject else None) or msg.subject_name or None
    rag_subject_icon = (_rag_subjs[0].get("icon") if _rag_has_real_subject else None) or None
    rag_subject_gradient = (_rag_subjs[0].get("gradient") if _rag_has_real_subject else None) or None
    _rag_chaps       = rag_ctx.get("chunk_chapters") or rag_ctx.get("chapters", [])
    rag_chapter_name = (_rag_chaps[0].get("title", "") if _rag_chaps else None) or msg.chapter_name or None
    full_response = []

    # Pull router classification for metadata (prefer router chapter over RAG chapter)
    _router_subject = getattr(_sr_route, "subject", None) if _sr_route else None
    _router_chapter = getattr(_sr_route, "chapter_hint", None) if _sr_route else None
    _router_board   = getattr(_sr_route, "board", None) if _sr_route else None
    # Use router chapter as rag_chapter_name when RAG was not the source
    if _router_chapter and not rag_chapter_name:
        rag_chapter_name = _router_chapter
    if _router_subject and not rag_subject_name:
        rag_subject_name = _router_subject

    # Derive sources from the same RAG context sent to the LLM (no mismatch)
    rag_sources = _sources_from_rag_ctx(rag_ctx)

    _src_sid_s = rag_subject_id or msg.subject_id
    _src_ctx_s = await _resolve_subject_context(_src_sid_s) if _src_sid_s else {}
    _src_board_s = _src_ctx_s.get("board_name") or ctx_board_name or ""
    _src_class_s = _src_ctx_s.get("class_name") or ctx_class_name or ""
    _src_stream_s = _src_ctx_s.get("stream_name") or ctx_stream_name or ""

    async def event_stream():
        nonlocal full_response
        _credit_saved = False  # set True when answer is committed; controls refund in finally
        try:
            # Send RAG metadata with full quality info + subject link data + web search flag
            _meta_event = {'conversation_id': conv_id, 'rag_source': rag_source_saved, 'rag_quality': rag_quality_saved, 'rag_chunks': rag_chunks_count, 'rag_subjects': rag_subjects_count, 'rag_subject_id': rag_subject_id, 'rag_subject_name': rag_subject_name, 'rag_subject_icon': rag_subject_icon or '', 'rag_subject_gradient': rag_subject_gradient or '', 'rag_chapter_name': rag_chapter_name, 'router_subject': _router_subject, 'router_chapter': _router_chapter, 'router_board': _router_board, 'web_search_used': web_search_used, 'ctx_board_name': _src_board_s, 'ctx_class_name': _src_class_s, 'ctx_stream_name': _src_stream_s}
            if content_card_meta:
                _meta_event['content_card_name'] = content_card_meta.get('card_name', '')
                _meta_event['content_card_lesson'] = content_card_meta.get('lesson_name', '')
                _meta_event['content_card_subject'] = content_card_meta.get('subject_name', '')
            yield f"data: {json.dumps(_meta_event)}\n\n"

            # ── Cache check (Streaming) — Redis first, in-memory fallback ────────
            is_casual = _stream_intent == "casual"
            cache_key = _cache_key(msg.message, subject_id=msg.subject_id or "", board_id=ctx_board_id or "", conversation_id=conv_id or "")
            _cache_ttl = REDIS_CASUAL_CACHE_TTL if is_casual else REDIS_AI_CACHE_TTL
            cached_answer = None

            cached_answer = _redis_get_ai_cache(cache_key)
            if cached_answer:
                logger.info(f"Redis cache HIT (STREAM): {cache_key}")
            elif cache_key in _ai_response_cache:
                cached_answer = _ai_response_cache[cache_key]
                logger.info(f"Memory cache HIT (STREAM): {cache_key}")

            if cached_answer:
                # Yield in small chunks to preserve streaming UX for cache hits
                _CHUNK_SIZE = 50
                for _ci in range(0, len(cached_answer), _CHUNK_SIZE):
                    yield f"data: {json.dumps({'content': cached_answer[_ci:_ci + _CHUNK_SIZE]})}\n\n"
                    await asyncio.sleep(0.008)
                full_response.append(cached_answer)
            else:
                _bp_count = 0
                async for chunk in call_llm_api_stream(messages_payload, model=msg.model or LLM_MODEL, max_tokens=max_tokens):
                    if '"content"' in chunk:
                        try:
                            data = json.loads(chunk[6:])
                            full_response.append(data.get("content", ""))
                        except:
                            pass
                    yield chunk
                    _bp_count += 1
                    if _bp_count % 20 == 0:
                        await asyncio.sleep(0)

                if full_response:
                    answer_str = "".join(full_response)
                    if answer_str:
                        _redis_set("ai_cache", cache_key, answer_str, _cache_ttl)
                        if not redis_client:
                            _ai_response_cache[cache_key] = answer_str
                        logger.info(f"Cache MISS → stored (STREAM, ttl={_cache_ttl}s): {cache_key}")

            # Yield DONE immediately — DB writes happen in background
            answer = "".join(full_response)
            new_used_optimistic = credits_info["used"] + 1 if answer else credits_info["used"]

            # ── syrabit_done event with credits metadata + RAG-derived sources ────
            done_payload = {
                "event": "syrabit_done",
                "conversation_id": conv_id,
                "credits_used": 1,
                "credits_used_total": new_used_optimistic,
                "remaining_credits": max(0, credits_info["remaining"] - 1),
                "rag_source": rag_source_saved,
                "rag_chunks": rag_chunks_count,
                "words": len(answer.split()) if answer else 0,
                "sources": rag_sources,
                "web_search_used": web_search_used,
            }
            if content_card_meta:
                done_payload["content_card_name"] = content_card_meta.get("card_name", "")
                done_payload["content_card_lesson"] = content_card_meta.get("lesson_name", "")
            yield f"data: {json.dumps(done_payload)}\n\n"
            yield "data: [DONE]\n\n"

            try:
                _record_chat_latency((_time_mod.time() - _stream_t0) * 1000)
            except Exception:
                pass

            try:
                _pc = sum(len(m.get("content", "")) for m in messages_payload)
                _record_llm_cost(
                    model=msg.model or LLM_MODEL,
                    prompt_tokens=max(1, _pc // 4),
                    completion_tokens=max(1, len(answer) // 4) if answer else 1,
                    provider="gemini",
                    user_id=str(user["id"]),
                )
            except Exception:
                pass

            if answer and _is_out_of_scope_response(answer) and rag_source_saved == "none":
                logger.info(f"[GUARD] Out-of-scope response detected — refunding credit for user {user['id']}")
                _credit_saved = False

            if answer and (not _is_out_of_scope_response(answer) or rag_source_saved != "none"):
                _credit_saved = True
                asyncio.create_task(_persist_chat_turn(
                    conv_id, user["id"],
                    user_msg_saved, answer,
                    rag_source_saved, rag_chunks_count,
                    credits_info["used"],
                    sources=rag_sources,
                    rag_subject_id=rag_subject_id,
                    rag_subject_name=rag_subject_name,
                    rag_board_name=_src_board_s,
                    rag_class_name=_src_class_s,
                    rag_stream_name=_src_stream_s,
                ))
                asyncio.create_task(_log_chat_message(
                    user_id=user["id"],
                    question=user_msg_saved,
                    raw_ai_answer=answer,
                    subject_id=msg.subject_id,
                    subject_name=msg.subject_name,
                    board_name=ctx_board_name,
                    class_name=ctx_class_name,
                    conversation_id=conv_id,
                ))
        finally:
            # Guaranteed refund if credit was pre-deducted but no answer was committed
            if not _credit_saved:
                asyncio.create_task(_refund_credit(user["id"], credits_info["used"] + 1))

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ─────────────────────────────────────────────
# PUBLIC SEARCH API  — /api/v1/search
# ─────────────────────────────────────────────
@router.get("/v1/search", response_model=SearchResultOut)
async def public_library_search(q: str = "", board: Optional[str] = None, class_num: Optional[str] = None):
    """Public search endpoint: returns matching syrabit.ai library pages.
    Example: GET /api/v1/search?q=limits+class+11+ahsec
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="q parameter is required")
    results = await syrabit_library_search(q.strip(), board_slug=board, class_slug=class_num)
    return {"query": q, "results": results, "count": len(results)}


# ─────────────────────────────────────────────
# CONVERSATION ROUTES
