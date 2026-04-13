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
import cachetools
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
    get_current_user_optional, rate_limit_chat_optional,
)
from db_ops import *
from llm import call_llm_api, call_llm_api_chat, call_llm_api_stream
from rag import *
from utils import *
from analytics_helpers import *
from prompts import _classify_intent, classify_intent, _is_out_of_scope_response, extract_semester_number
from followup_context import detect_followup, build_followup_context, merge_followup_into_query
from pipeline import should_use_pipeline, stage1_resolve_topic, apply_stage1_to_intent, build_enhanced_query, run_pipeline_stream, get_instant_response

_CONTENT_INTENTS_SET = {"notes", "important_questions", "pyq"}

def _tune_response_stream(chunk_text: str, intent: str, _buf: dict) -> str:
    _buf["total"] += chunk_text
    _buf["chars"] += len(chunk_text)

    text = chunk_text
    if _buf["chars"] < 100:
        text = re.sub(r'^(Sure!|Of course!|Absolutely!|Great question!|Hello!)\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r"^(Let me explain|Here's|I'd be happy to)\s*[.!,]?\s*", '', text, flags=re.IGNORECASE)

    text = re.sub(r'\n{3,}', '\n\n', text)

    return text

def _safe_metadata(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}
from qa_engine import log_chat_message as _log_chat_message
from guardrails.prompt_safety import evaluate_prompt_safety, validate_llm_output

logger = logging.getLogger(__name__)

def _record_llm_cost(model, prompt_tokens, completion_tokens, provider="gemini", user_id=""):
    from routes.admin_advanced import record_llm_cost
    record_llm_cost(model, prompt_tokens, completion_tokens, provider, user_id)

router = APIRouter()

_subject_ctx_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=256, ttl=3600)

async def _resolve_subject_context(subject_id: str) -> dict:
    if not subject_id:
        return {}
    cached = _subject_ctx_cache.get(subject_id)
    if cached is not None:
        return cached
    try:
        subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
        if not subj:
            subj = await db.subjects.find_one({"slug": subject_id}, {"_id": 0})
        if not subj:
            _subject_ctx_cache[subject_id] = {}
            return {}
        ctx = {
            "board_id":      subj.get("board_id") or subj.get("boardId") or "",
            "board_name":    subj.get("boardName") or "",
            "board_slug":    subj.get("board_slug") or "",
            "class_id":      subj.get("class_id") or "",
            "class_name":    subj.get("className") or "",
            "class_slug":    subj.get("class_slug") or "",
            "stream_id":     subj.get("stream_id") or "",
            "stream_name":   subj.get("streamName") or "",
            "stream_slug":   subj.get("stream_slug") or "",
            "subject_name":  subj.get("name") or "",
            "subject_slug":  subj.get("slug") or "",
        }
        if ctx["board_slug"] and ctx["class_slug"]:
            _subject_ctx_cache[subject_id] = ctx
            return ctx
        _sid = subj.get("stream_id")
        if _sid:
            stream = await db.streams.find_one({"id": _sid}, {"_id": 0, "id": 1, "name": 1, "slug": 1, "class_id": 1})
            if stream:
                ctx["stream_id"] = stream.get("id", "")
                ctx["stream_name"] = ctx["stream_name"] or stream.get("name", "")
                ctx["stream_slug"] = ctx["stream_slug"] or stream.get("slug", "")
                _cid = stream.get("class_id")
                if _cid:
                    cls = await db.classes.find_one({"id": _cid}, {"_id": 0, "id": 1, "name": 1, "slug": 1, "board_id": 1})
                    if cls:
                        ctx["class_id"] = cls.get("id", "")
                        ctx["class_name"] = ctx["class_name"] or cls.get("name", "")
                        ctx["class_slug"] = ctx["class_slug"] or cls.get("slug", "")
                        _bid = cls.get("board_id")
                        if _bid:
                            board = await db.boards.find_one({"id": _bid}, {"_id": 0, "id": 1, "name": 1, "slug": 1})
                            if board:
                                ctx["board_id"] = board.get("id", "")
                                ctx["board_name"] = ctx["board_name"] or board.get("name", "")
                                ctx["board_slug"] = ctx["board_slug"] or board.get("slug", "")
        _subject_ctx_cache[subject_id] = ctx
        return ctx
    except Exception as e:
        logger.warning(f"_resolve_subject_context({subject_id}) failed: {e}")
        return {}

async def _resolve_semester_class_id(query: str, ctx_board_id: str) -> str | None:
    sem_num = extract_semester_number(query)
    if not sem_num:
        return None
    sem_slugs = [f"semester-{sem_num}", f"{sem_num}th-sem", f"{sem_num}nd-sem", f"{sem_num}st-sem", f"{sem_num}rd-sem"]
    try:
        cls = await db.classes.find_one(
            {"board_id": ctx_board_id, "slug": {"$in": sem_slugs}},
            {"_id": 0, "id": 1},
        )
        if cls:
            logger.info(f"Semester {sem_num} resolved to class_id={cls['id']} for board {ctx_board_id}")
            return cls["id"]
    except Exception as e:
        logger.warning(f"_resolve_semester_class_id failed: {e}")
    return None

@router.post("/ai/chat")
async def chat(msg: ChatMessage, user: Optional[dict] = Depends(rate_limit_chat_optional)):
    _chat_t0 = _time_mod.time()
    is_anon = user is None

    plan = user.get("plan", "free") if user else "free"
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]
    conv_id = msg.conversation_id
    user_id = user["id"] if user else None

    _detected_intent, _detected_db_category = classify_intent(msg.message)

    _ns_resp_lang = (msg.response_lang or "").lower().strip()
    _instant = get_instant_response(msg.message) if (_detected_intent == "casual" and _ns_resp_lang in ("", "en")) else None
    if _instant:
        credits_info = None
        if not is_anon:
            credits_info = await get_user_credits(user)
            if credits_info["remaining"] <= 0:
                raise HTTPException(status_code=402, detail=f"Daily credit limit reached ({credits_info['limit']} credits/day). Resets at midnight UTC. Upgrade your plan for more.")
        logger.info(f"[NON-STREAM] INSTANT casual fast-path: '{msg.message[:30]}' → {len(_instant)} chars (0 LLM calls)")
        return {
            "answer": _instant,
            "conversation_id": conv_id,
            "credits_remaining": credits_info["remaining"] if credits_info else None,
            "credits_used": 0 if not is_anon else None,
            "rag_source": "none",
            "rag_chunks_used": 0,
            "sources": [],
        }

    if not is_anon:
        credits_info = await get_user_credits(user)
        if credits_info["remaining"] <= 0:
            raise HTTPException(status_code=402, detail=f"Daily credit limit reached ({credits_info['limit']} credits/day). Resets at midnight UTC. Upgrade your plan for more.")

    _is_card_context = bool(msg.card_context and msg.card_context.strip())

    async def _ns_fetch_doc():
        if _is_card_context:
            logger.info(f"Chat [NON-STREAM]: card_context ({len(msg.card_context)} chars) used as grounding")
            return msg.card_context
        if not msg.document_id:
            return None
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        return (subj or {}).get("document_text")

    async def _ns_fetch_stage1_early():
        if not should_use_pipeline(_detected_intent, msg.message):
            return None
        result = await stage1_resolve_topic(msg.message)
        return result if result else {}

    async def _ns_fetch_followup():
        if not (conv_id and user_id):
            return None
        try:
            _conv_for_followup = await supa_get_conversation(conv_id, user_id)
            if _conv_for_followup:
                _conv_meta = _safe_metadata(_conv_for_followup.get("metadata"))
                return detect_followup(msg.message, _conv_meta)
        except Exception as _fu_err:
            logger.warning(f"Follow-up detection failed: {_fu_err}")
        return None

    async def _ns_prefetch_history():
        if not conv_id:
            return None
        if user_id:
            return await supa_get_conversation(conv_id, user_id)
        return None

    _t_phase0 = _time_mod.time()
    _phase0_results = await asyncio.gather(
        _resolve_subject_context(msg.subject_id),
        _resolve_semester_class_id(msg.message, msg.board_id) if msg.board_id else asyncio.sleep(0),
        _ns_fetch_doc(),
        _ns_fetch_stage1_early(),
        _ns_fetch_followup(),
        _ns_prefetch_history(),
        return_exceptions=True,
    )
    _subj_ctx_result = _phase0_results[0] if not isinstance(_phase0_results[0], BaseException) else {}
    _sem_class_result = _phase0_results[1] if not isinstance(_phase0_results[1], BaseException) else None
    document_text = _phase0_results[2] if not isinstance(_phase0_results[2], BaseException) else None
    _topic_metadata = _phase0_results[3] if not isinstance(_phase0_results[3], BaseException) else None
    _followup_info = _phase0_results[4] if not isinstance(_phase0_results[4], BaseException) else None
    _prefetched_conv = _phase0_results[5] if not isinstance(_phase0_results[5], BaseException) else None
    for _i, _r in enumerate(_phase0_results):
        if isinstance(_r, BaseException):
            logger.warning(f"[NON-STREAM] Phase 0 task {_i} failed (degrading gracefully): {_r}")

    subj_ctx = _subj_ctx_result
    ctx_board_id   = subj_ctx.get("board_id")   or msg.board_id
    ctx_class_id   = subj_ctx.get("class_id")   or msg.class_id
    ctx_stream_id  = subj_ctx.get("stream_id")  or getattr(msg, 'stream_id', None)
    ctx_board_name = subj_ctx.get("board_name") or msg.board_name or (user.get("board_name", "") if user else "")
    ctx_class_name = subj_ctx.get("class_name") or msg.class_name or (user.get("class_name", "") if user else "")
    ctx_stream_name= subj_ctx.get("stream_name") or getattr(msg, 'stream_name', None) or (user.get("stream_name", "") if user else "")
    if subj_ctx:
        logger.info(f"Chat [NON-STREAM]: Subject context resolved → {ctx_board_name} / {ctx_class_name} / {ctx_stream_name}")

    if not _sem_class_result and ctx_board_id and ctx_board_id != msg.board_id:
        _sem_class_result = await _resolve_semester_class_id(msg.message, ctx_board_id)

    _syl_class_id = _sem_class_result or ctx_class_id
    if _sem_class_result:
        logger.info(f"Chat [NON-STREAM]: Semester override class_id={_sem_class_result} (from query)")

    if _followup_info:
        _detected_intent = _followup_info["prev_intent"]
        _detected_db_category = {"notes": "notes", "important_questions": "important_questions", "pyq": "question_paper"}.get(_detected_intent)
        msg.message = merge_followup_into_query(
            msg.message, _followup_info,
            subject_name=msg.subject_name or "",
            chapter_name=msg.chapter_name or "",
        )
        logger.info(f"[NON-STREAM] Follow-up detected: intent={_detected_intent}, rewritten query='{msg.message[:60]}'")

    if not _followup_info and _topic_metadata and _topic_metadata.get("intent"):
        _detected_intent, _detected_db_category = apply_stage1_to_intent(
            _topic_metadata, _detected_intent, _detected_db_category
        )
        logger.info(f"[PIPELINE][S1] Intent resolved: {_detected_intent} (Stage 1 primary)")

    _q_lower_ns = msg.message.lower()
    if _detected_intent == "syllabus" and _topic_metadata and _topic_metadata.get("search_keywords") and "syllabus" not in _q_lower_ns and "curriculum" not in _q_lower_ns and "subject list" not in _q_lower_ns:
        _detected_intent = "notes"
        _detected_db_category = "notes"
        logger.info(f"[NON-STREAM] Intent upgrade: syllabus → notes (Stage 1 has search_keywords, query is content-seeking)")

    _is_casual_sync = _detected_intent in ("casual", "general")

    _rag_query = msg.message
    if _topic_metadata and _topic_metadata.get("search_keywords"):
        _rag_query = build_enhanced_query(msg.message, _topic_metadata)
        if _rag_query != msg.message:
            logger.info(f"[PIPELINE][S1] Enhanced search query: '{_rag_query[:80]}'")

    async def _ns_fetch_syllabus():
        if not (ctx_board_id and _syl_class_id):
            return None
        _sck = _syllabus_cache_key(ctx_board_id, _syl_class_id, ctx_stream_id, msg.subject_id)
        if _sck in _syllabus_cache:
            return _syllabus_cache[_sck]
        try:
            queries = []
            if ctx_stream_id and msg.subject_id:
                queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id, "stream_id": ctx_stream_id, "subject_id": msg.subject_id}, {"_id": 0}))
            if ctx_stream_id:
                queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id, "stream_id": ctx_stream_id}, {"_id": 0}))
            queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id, "stream_id": {"$exists": False}}, {"_id": 0}))
            queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id}, {"_id": 0}))
            results = await asyncio.gather(*queries, return_exceptions=True)
            s = None
            for r in results:
                if r and not isinstance(r, Exception):
                    s = r
                    break
            if s:
                _syllabus_cache[_sck] = s
            return s
        except Exception:
            return None

    async def _ns_fetch_history():
        if _prefetched_conv:
            raw = [
                {"role": m.get("role", ""), "content": m.get("content") or ""}
                for m in _prefetched_conv.get("messages", [])
                if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
            ]
            return _trim_history(raw)
        if conv_id and user_id:
            conv = await supa_get_conversation(conv_id, user_id)
            if conv:
                raw = [
                    {"role": m.get("role", ""), "content": m.get("content") or ""}
                    for m in conv.get("messages", [])
                    if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
                ]
                return _trim_history(raw)
        return []

    _t_phase0_done = _time_mod.time()
    logger.info(f"[NON-STREAM][TIMING] Phase 0 (parallel context): {_t_phase0_done - _t_phase0:.3f}s")

    rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
               "vector_hits": [], "source": "none", "quality": "none",
               "_general_knowledge_fallback": True}
    _s1_subject_str = (_topic_metadata.get("subject", "") if _topic_metadata else "").strip()
    if _s1_subject_str:
        rag_ctx["_stage1_subject"] = _s1_subject_str

    if document_text:
        rag_ctx = await resolve_rag_context(
            _rag_query, subject_id=msg.subject_id, subject_name=msg.subject_name,
            document_text=document_text, intent=_detected_intent,
        )

    async def _ns_fetch_web():
        if _is_casual_sync or document_text:
            return []
        try:
            return await web_search_with_fallback(
                _rag_query,
                board_name=ctx_board_name or "",
                class_name=ctx_class_name or "",
                subject_name=msg.subject_name or "",
                chapter_name=msg.chapter_name or "",
                enrich_top_n=2,
            )
        except Exception as _ws_err:
            logger.warning(f"[NON-STREAM] Web search failed (non-fatal): {_ws_err}")
            return []

    _ns_phase2 = await asyncio.gather(
        _ns_fetch_history(),
        _ns_fetch_syllabus(),
        _ns_fetch_web(),
        return_exceptions=True,
    )
    history_messages = _ns_phase2[0] if not isinstance(_ns_phase2[0], BaseException) else []
    syllabus = _ns_phase2[1] if not isinstance(_ns_phase2[1], BaseException) else None
    web_results = _ns_phase2[2] if not isinstance(_ns_phase2[2], BaseException) else []
    for _pi, _pr in enumerate(_ns_phase2):
        if isinstance(_pr, BaseException):
            logger.warning(f"[NON-STREAM] Phase 2 task {_pi} failed: {_pr}")

    # ── Build system prompt with web search context ───────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name":  ctx_board_name,
            "class_name":  ctx_class_name,
            "stream_name": ctx_stream_name,
            "subject_name": msg.subject_name,
            "subject_id":  msg.subject_id,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        (user.get("name", "") if user else ""),
            "board_name":  ctx_board_name or (user.get("board_name", "") if user else ""),
            "class_name":  ctx_class_name or (user.get("class_name", "") if user else ""),
            "stream_name": ctx_stream_name or (user.get("stream_name", "") if user else ""),
            "plan":        (user.get("plan", "free") if user else "free"),
        },
        query=msg.message,
        syllabus=syllabus,
        web_results=web_results or None,
        resolved_intent=_detected_intent,
    )
    if not conv_id and user_id:
        conv_id = str(uuid.uuid4())
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        conv_doc = {
            "id": conv_id,
            "user_id": user_id,
            "title": title,
            "subject_id": msg.subject_id,
            "subject_name": msg.subject_name,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await supa_upsert_conversation(conv_doc)
    elif not user_id:
        conv_id = None

    _MAX_PROMPT_CHARS_NS = 100_000
    _total_chars_ns = len(system_prompt) + sum(len(m.get("content", "")) for m in history_messages) + len(msg.message)
    if _total_chars_ns > _MAX_PROMPT_CHARS_NS:
        _overhead_ns = len(system_prompt) - (_total_chars_ns - _MAX_PROMPT_CHARS_NS)
        if _overhead_ns > 2000:
            system_prompt = system_prompt[:_overhead_ns]
            logger.warning(f"[CHAT] System prompt truncated from {_total_chars_ns} to ~{_MAX_PROMPT_CHARS_NS} chars to fit provider limits")

    messages = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": msg.message}]

    # ── Cache check (Non-streaming) — Redis first, in-memory fallback ───────
    is_casual = _detected_intent in ("casual", "general")
    cache_key = _cache_key(msg.message, subject_id=msg.subject_id or "", board_id=ctx_board_id or "", conversation_id=conv_id or "")
    _cache_ttl = REDIS_CASUAL_CACHE_TTL if is_casual else REDIS_AI_CACHE_TTL
    answer = None
    _ns_cache_hit = False

    answer = _redis_get_ai_cache(cache_key)
    if answer:
        _ns_cache_hit = True
        logger.info(f"Redis cache HIT: {cache_key}")
    elif cache_key in _ai_response_cache:
        answer = _ai_response_cache[cache_key]
        _ns_cache_hit = True
        logger.info(f"Memory cache HIT: {cache_key}")

    if answer is None:
        _t_llm_start = _time_mod.time()
        try:
            answer = await call_llm_api_chat(messages, model=msg.model or "meta-llama/llama-4-scout-17b-16e-instruct", max_tokens=max_tokens)
            _redis_set("ai_cache", cache_key, answer, _cache_ttl)
            if not redis_client:
                _ai_response_cache[cache_key] = answer
            _t_llm_done = _time_mod.time()
            logger.info(f"[NON-STREAM][TIMING] LLM call: {_t_llm_done - _t_llm_start:.3f}s | Cache MISS → stored (ttl={_cache_ttl}s): {cache_key}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"AI chat error: {e}")
            raise HTTPException(status_code=503, detail="AI service temporarily unavailable")

    lib_sources = _sources_from_rag_ctx(rag_ctx)
    if web_results:
        lib_sources.extend(_sources_from_web_results(web_results))

    now = datetime.now(timezone.utc).isoformat()
    _rag_subject_ids = list({s["id"] for s in rag_ctx.get("subjects", []) if s.get("id")})
    _rag_subject_names = list({s.get("name","") for s in rag_ctx.get("subjects", []) if s.get("name")})
    _src_sid = _rag_subject_ids[0] if _rag_subject_ids else msg.subject_id
    if _src_sid and _src_sid == msg.subject_id and subj_ctx:
        _src_ctx = subj_ctx
    else:
        _src_ctx = await _resolve_subject_context(_src_sid) if _src_sid else {}
    _src_board = _src_ctx.get("board_name") or ctx_board_name or ""
    _src_class = _src_ctx.get("class_name") or ctx_class_name or ""
    _src_stream = _src_ctx.get("stream_name") or ctx_stream_name or ""
    _src_board_slug_nr = _src_ctx.get("board_slug") or ""
    _src_class_slug_nr = _src_ctx.get("class_slug") or ""
    _src_subject_slug_nr = _src_ctx.get("subject_slug") or ""
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
         "rag_stream_name": _src_stream,
         "rag_board_slug": _src_board_slug_nr,
         "rag_class_slug": _src_class_slug_nr,
         "rag_subject_slug": _src_subject_slug_nr},
    ]
    new_used = 0
    if user_id:
        conv = await supa_get_conversation(conv_id, user_id)
        if conv:
            existing_msgs = conv.get("messages", [])
            if isinstance(existing_msgs, str):
                try: existing_msgs = json.loads(existing_msgs)
                except: existing_msgs = []
            updated_msgs = existing_msgs + new_messages
            _update_payload = {
                "messages": json.dumps(updated_msgs) if supa else updated_msgs,
                "updated_at": now,
                "preview": answer[:100],
                "tokens": len(answer.split()),
            }
            if _detected_intent in ("notes", "important_questions", "pyq"):
                _existing_meta = _safe_metadata(conv.get("metadata"))
                _prev_followup = _existing_meta.get("followup_context") or {}
                _completed = list(_prev_followup.get("completed", []))
                _current = _prev_followup.get("current_item", "")
                if _current and _current not in _completed:
                    _completed.append(_current)
                _remaining = list(_prev_followup.get("remaining", []))
                if _current in _remaining:
                    _remaining.remove(_current)
                if not _remaining:
                    if _detected_intent == "pyq":
                        _remaining = [m for m in ["1m", "2m", "3m", "5m", "10m"] if m not in _completed]
                    else:
                        _rag_chapters = rag_ctx.get("chapters", [])
                        _remaining = [
                            ch.get("title", "") for ch in _rag_chapters
                            if ch.get("title", "") and ch.get("title", "") not in _completed
                        ]
                _new_current = msg.chapter_name or _current
                if _new_current in _remaining:
                    _remaining.remove(_new_current)
                _new_followup = build_followup_context(
                    intent=_detected_intent,
                    current_item=_new_current,
                    completed=_completed,
                    remaining=_remaining,
                )
                _existing_meta["followup_context"] = _new_followup
                _update_payload["metadata"] = _existing_meta
            await supa_update_conversation(conv_id, user_id, _update_payload)

        deducted = await atomic_deduct_credit(user_id, credits_info["used"], credits_info["limit"])
        if not deducted:
            raise HTTPException(status_code=402, detail="Credit limit reached. Upgrade your plan for more.")
        new_used = credits_info["used"] + 1

        asyncio.create_task(_log_chat_message(
            user_id=user_id,
            question=msg.message,
            raw_ai_answer=answer,
            subject_id=msg.subject_id,
            subject_name=msg.subject_name,
            board_name=ctx_board_name,
            class_name=ctx_class_name,
            conversation_id=conv_id,
        ))

    _ns_total_ms = (_time_mod.time() - _chat_t0) * 1000
    try:
        from middleware import request_id_var
        _ns_rid = request_id_var.get("")
    except Exception:
        _ns_rid = ""
    logger.info(
        f"[NON-STREAM][TIMING][SUMMARY] "
        f"rid={_ns_rid} | "
        f"total={_ns_total_ms:.0f}ms | "
        f"intent={_detected_intent} | "
        f"rag_quality={rag_ctx.get('quality', 'none')} | "
        f"words={len(answer.split()) if answer else 0}"
    )
    try:
        _record_chat_latency(_ns_total_ms)
    except Exception:
        pass

    try:
        _prompt_chars = sum(len(m.get("content", "")) for m in messages)
        _compl_chars  = len(answer) if answer else 0
        _actual_provider = "cache" if _ns_cache_hit else getattr(answer, "provider", "unknown")
        _record_llm_cost(
            model=msg.model or LLM_MODEL,
            prompt_tokens=max(1, _prompt_chars // 4),
            completion_tokens=max(1, _compl_chars // 4),
            provider=_actual_provider,
            user_id=str(user_id) if user_id else "anonymous",
        )
    except Exception:
        pass

    return {
        "answer": answer,
        "conversation_id": conv_id,
        "credits_remaining": max(0, credits_info["remaining"] - 1) if not is_anon else None,
        "credits_used": new_used if not is_anon else None,
        "rag_source": rag_ctx.get("source", "none"),
        "rag_chunks_used": len(rag_ctx.get("chunks", [])),
        "sources": lib_sources,
        "rag_subject_id": _rag_subject_ids[0] if _rag_subject_ids else None,
        "rag_subject_name": _rag_subject_names[0] if _rag_subject_names else msg.subject_name,
        "rag_board_name": _src_board,
        "rag_class_name": _src_class,
        "rag_stream_name": _src_stream,
        "rag_board_slug": _src_board_slug_nr,
        "rag_class_slug": _src_class_slug_nr,
        "rag_subject_slug": _src_subject_slug_nr,
    }

async def _refund_credit(uid: str, credits_used: int) -> None:
    """Refund 1 daily credit (decrement credits_used_today and credits_used) when streaming fails/empty answer."""
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if deps.pg_pool:
            async with deps.pg_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET credits_used_today = GREATEST(0, credits_used_today - 1), credits_used = GREATEST(0, credits_used - 1) WHERE id = $1",
                    uid,
                )
            return
        if redis_client:
            redis_key = f"daily_credits:{uid}:{today_str}"
            refunded_count = redis_client.decr(redis_key)
            if refunded_count is not None and refunded_count >= 0:
                user_data = await supa_get_user_by_id(uid)
                lifetime_used = max(0, (user_data.get("credits_used", 0) if user_data else 0) - 1)
                await supa_update_user(uid, {"credits_used_today": int(refunded_count), "credits_used": lifetime_used})
            return
        if credits_used > 0:
            user_data = await supa_get_user_by_id(uid)
            lifetime_used = max(0, (user_data.get("credits_used", 0) if user_data else 0) - 1)
            await supa_update_user(uid, {"credits_used_today": credits_used - 1, "credits_used": lifetime_used})
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
    rag_board_slug: str | None = None,
    rag_class_slug: str | None = None,
    rag_subject_slug: str | None = None,
    rag_chapter_name: str | None = None,
    rag_chapter_slug: str | None = None,
    rag_topic_name: str | None = None,
    rag_chunk_snippet: str | None = None,
    followup_context: dict | None = None,
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
        if rag_board_slug:
            assistant_msg["rag_board_slug"] = rag_board_slug
        if rag_class_slug:
            assistant_msg["rag_class_slug"] = rag_class_slug
        if rag_subject_slug:
            assistant_msg["rag_subject_slug"] = rag_subject_slug
        if rag_chapter_name:
            assistant_msg["rag_chapter_name"] = rag_chapter_name
        if rag_chapter_slug:
            assistant_msg["rag_chapter_slug"] = rag_chapter_slug
        if rag_topic_name:
            assistant_msg["rag_topic_name"] = rag_topic_name
        if rag_chunk_snippet:
            assistant_msg["rag_chunk_snippet"] = rag_chunk_snippet
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
            _persist_payload = {
                "messages": json.dumps(updated) if supa else updated,
                "updated_at": now,
                "preview": answer[:100],
                "tokens": len(answer.split()),
            }
            if followup_context:
                _existing_meta = _safe_metadata(conv.get("metadata"))
                _existing_meta["followup_context"] = followup_context
                _persist_payload["metadata"] = _existing_meta
            await supa_update_conversation(conv_id, user_id, _persist_payload)
        if deduct_credit:
            await atomic_deduct_credit(user_id, credits_used_before, 999999)
    except Exception as e:
        logger.warning(f"_persist_chat_turn failed: {e}")

@router.post("/ai/chat/stream")
async def chat_stream(msg: ChatMessage, request: Request, user: Optional[dict] = Depends(rate_limit_chat_optional)):
    _stream_t0 = _time_mod.time()
    is_anon = user is None
    user_id = user["id"] if user else None
    anon_id = None
    if is_anon:
        _raw_anon = request.headers.get("x-anon-id", "")
        if _raw_anon and re.match(r"^anon_[a-f0-9]{32}$", _raw_anon):
            anon_id = _raw_anon

    safe_prompt, fallback_msg, guardrail_tag = evaluate_prompt_safety(msg.message)
    _stream_intent, _stream_db_category = classify_intent(msg.message)

    credits_info = None
    if not is_anon:
        credits_info = await get_user_credits(user)
        if credits_info["remaining"] <= 0:
            raise HTTPException(status_code=402, detail=f"Daily credit limit reached ({credits_info['limit']} credits/day). Resets at midnight UTC. Upgrade your plan for more.")
        deducted = await atomic_deduct_credit(user_id, credits_info["used"], credits_info["limit"])
        if not deducted:
            raise HTTPException(status_code=402, detail="Credit limit reached. Upgrade your plan for more.")

    if fallback_msg:
        logger.info(f"[guardrails] Prompt blocked ({guardrail_tag}) for user {user_id or 'anon'}: {msg.message[:80]!r}")
        async def _blocked_stream():
            yield f"data: {json.dumps({'conversation_id': msg.conversation_id or '', 'rag_source': 'none', 'rag_quality': 'none', 'rag_chunks': 0, 'guardrail_blocked': True})}\n\n"
            _CHUNK = 40
            for i in range(0, len(fallback_msg), _CHUNK):
                yield f"data: {json.dumps({'content': fallback_msg[i:i+_CHUNK]})}\n\n"
                await asyncio.sleep(0.01)
            yield f"data: {json.dumps({'event': 'syrabit_done', 'conversation_id': msg.conversation_id or '', 'guardrail_tag': guardrail_tag})}\n\n"
            yield "data: [DONE]\n\n"
        if not is_anon and credits_info:
            asyncio.create_task(_refund_credit(user_id, credits_info["used"] + 1))
        return StreamingResponse(_blocked_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    plan = user.get("plan", "free") if user else "free"
    max_tokens = PLAN_LIMITS[plan]["max_tokens"]

    _t_auth_done = _time_mod.time()
    _auth_elapsed = _t_auth_done - _stream_t0

    _SARVAM_LANG_MAP = {"as": "as-IN"}
    _resp_lang = (msg.response_lang or "").lower().strip()
    _sarvam_target = _SARVAM_LANG_MAP.get(_resp_lang)
    _want_translate = bool(_sarvam_target and _resp_lang != "en")

    _instant_s = get_instant_response(msg.message) if (_stream_intent == "casual" and not _want_translate) else None
    if _instant_s:
        logger.info(f"[STREAM] INSTANT casual fast-path: '{msg.message[:30]}' → {len(_instant_s)} chars (0 LLM calls)")
        async def _instant_stream():
            nonlocal _instant_s
            yield f"data: {json.dumps({'conversation_id': msg.conversation_id or '', 'rag_source': 'none', 'rag_quality': 'none', 'rag_chunks': 0})}\n\n"
            yield f"data: {json.dumps({'content': _instant_s})}\n\n"
            yield f"data: {json.dumps({'event': 'syrabit_done', 'conversation_id': msg.conversation_id or ''})}\n\n"
            yield "data: [DONE]\n\n"
        if not is_anon and credits_info:
            asyncio.create_task(_refund_credit(user_id, credits_info["used"] + 1))
        return StreamingResponse(_instant_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    _s_should_pipeline, _s_stage1, _s_apply_s1, _s_enhance_q = should_use_pipeline, stage1_resolve_topic, apply_stage1_to_intent, build_enhanced_query

    _cache_msg_key_early = f"{msg.message}::lang={_resp_lang}" if _want_translate else msg.message
    _cache_key_early = _cache_key(_cache_msg_key_early, subject_id=msg.subject_id or "", board_id=msg.board_id or "", conversation_id=msg.conversation_id or "")
    _early_cached_answer = _redis_get_ai_cache(_cache_key_early)
    if not _early_cached_answer and _cache_key_early in _ai_response_cache:
        _early_cached_answer = _ai_response_cache[_cache_key_early]
    if _early_cached_answer:
        logger.info(f"[STREAM] EARLY cache HIT — skipping all preprocessing (key={_cache_key_early})")
        _conv_id_early = msg.conversation_id
        if not _conv_id_early and (user_id or anon_id):
            _conv_id_early = str(uuid.uuid4())
            _title_early = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
            _now_early = datetime.now(timezone.utc).isoformat()
            _conv_doc_early = {
                "id": _conv_id_early,
                "user_id": user_id or anon_id,
                "title": _title_early,
                "subject_id": msg.subject_id or "",
                "subject_name": msg.subject_name or "",
                "messages": [],
                "created_at": _now_early,
                "updated_at": _now_early,
            }
            if is_anon and anon_id:
                _conv_doc_early["is_anonymous"] = True
                _conv_doc_early["anon_id"] = anon_id
                from cache import redis_save_anon_conversation
                redis_save_anon_conversation(anon_id, _conv_id_early, _conv_doc_early)
            asyncio.create_task(supa_upsert_conversation(_conv_doc_early))

        async def _early_cache_persist():
            try:
                _answer_e = _early_cached_answer
                _now_e = datetime.now(timezone.utc).isoformat()
                _uid_e = user_id or anon_id
                if _conv_id_early and _uid_e:
                    await _persist_chat_turn(
                        _conv_id_early, _uid_e,
                        msg.message, _answer_e,
                        "cache", 0, credits_info["used"] if credits_info else 0,
                    )
            except Exception as _pe:
                logger.warning(f"[STREAM] Early cache persist failed (non-fatal): {_pe}")

        async def _early_cache_stream():
            yield f"data: {json.dumps({'conversation_id': _conv_id_early or '', 'rag_source': 'cache', 'rag_quality': 'none', 'rag_chunks': 0, 'web_search_used': False, 'ctx_board_name': msg.board_name or '', 'ctx_class_name': msg.class_name or ''})}\n\n"
            logger.info(f"[STREAM][TIMING] TTFT (early cache): {_time_mod.time() - _stream_t0:.3f}s")
            _CHUNK_SIZE = 120
            for _ci in range(0, len(_early_cached_answer), _CHUNK_SIZE):
                yield f"data: {json.dumps({'content': _early_cached_answer[_ci:_ci + _CHUNK_SIZE]})}\n\n"
                if _ci % (_CHUNK_SIZE * 5) == 0:
                    await asyncio.sleep(0)
            _answer_words = len(_early_cached_answer.split())
            yield f"data: {json.dumps({'event': 'syrabit_done', 'conversation_id': _conv_id_early or '', 'rag_source': 'cache', 'words': _answer_words, 'web_search_used': False})}\n\n"
            yield "data: [DONE]\n\n"
            asyncio.create_task(_early_cache_persist())
            try:
                _record_chat_latency((_time_mod.time() - _stream_t0) * 1000)
            except Exception:
                pass
        if not is_anon and credits_info:
            asyncio.create_task(_refund_credit(user_id, credits_info["used"] + 1))
        return StreamingResponse(_early_cache_stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Phase 0+1 fully parallel: context, semester, doc, search scope, Stage 1, follow-up all at once ──
    _t_phase0 = _time_mod.time()

    _is_card_context = bool(msg.card_context and msg.card_context.strip())

    async def _fetch_doc():
        if _is_card_context:
            logger.info(f"Chat [STREAM]: card_context ({len(msg.card_context)} chars) used as grounding (library source)")
            return msg.card_context
        if not msg.document_id:
            return None
        subj = await db.subjects.find_one({"id": msg.document_id}, {"_id": 0, "document_text": 1})
        return (subj or {}).get("document_text")

    _is_casual = _stream_intent in ("casual", "general")

    _stage1_task = None
    if _s_should_pipeline(_stream_intent, msg.message):
        _s1_timeout = 0.4 if _want_translate else 0.8
        async def _stage1_wrapper():
            try:
                result = await asyncio.wait_for(_s_stage1(msg.message), timeout=_s1_timeout)
                return result if result else {}
            except asyncio.TimeoutError:
                logger.info(f"[STREAM] Stage 1 timeout ({_s1_timeout}s) — proceeding without")
                return {}
        _stage1_task = asyncio.create_task(_stage1_wrapper())

    async def _fetch_followup_info():
        if is_anon or _is_casual:
            return None
        if not (msg.conversation_id and user_id):
            return None
        try:
            _conv_for_fu_s = await supa_get_conversation(msg.conversation_id, user_id)
            if _conv_for_fu_s:
                _conv_meta_s = _safe_metadata(_conv_for_fu_s.get("metadata"))
                return detect_followup(msg.message, _conv_meta_s)
        except Exception as _fu_err_s:
            logger.warning(f"[STREAM] Follow-up detection failed: {_fu_err_s}")
        return None

    async def _prefetch_history():
        try:
            if not msg.conversation_id:
                return None
            if user_id:
                return await supa_get_conversation(msg.conversation_id, user_id)
            if anon_id:
                from cache import redis_get_anon_conversation
                return redis_get_anon_conversation(anon_id, msg.conversation_id)
        except Exception as _hist_err:
            logger.warning(f"[STREAM] History prefetch failed (non-fatal): {_hist_err}")
        return None

    async def _early_web_search():
        if _is_card_context or msg.document_id:
            return []
        if _is_casual:
            return []
        try:
            return await web_search_with_fallback(
                msg.message,
                board_name=msg.board_name or "",
                class_name=msg.class_name or "",
                subject_name=msg.subject_name or "",
                chapter_name=msg.chapter_name or "",
                enrich_top_n=0,
            )
        except Exception as _ews_err:
            logger.warning(f"[STREAM] Early web search failed (non-fatal): {_ews_err}")
            return []

    _skip_semester = _is_casual or is_anon

    _subj_ctx_result, _sem_class_result, document_text, _stream_followup_info, _prefetched_conv, _early_web = await asyncio.gather(
        _resolve_subject_context(msg.subject_id),
        _resolve_semester_class_id(msg.message, msg.board_id) if (msg.board_id and not _skip_semester) else asyncio.sleep(0),
        _fetch_doc(),
        _fetch_followup_info(),
        _prefetch_history(),
        _early_web_search(),
    )

    _s_topic_meta = None
    if _stage1_task:
        if _stage1_task.done():
            try:
                _s_topic_meta = _stage1_task.result()
            except Exception:
                _s_topic_meta = None
        else:
            try:
                _s_topic_meta = await asyncio.wait_for(_stage1_task, timeout=0.15)
            except asyncio.TimeoutError:
                logger.info("[STREAM] Stage 1 still pending after gather — proceeding without it")
                _s_topic_meta = None
            except Exception:
                _s_topic_meta = None

    _is_followup_s = False
    if _stream_followup_info:
        _is_followup_s = True
        _stream_intent = _stream_followup_info["prev_intent"]
        _stream_db_category = {"notes": "notes", "important_questions": "important_questions", "pyq": "question_paper"}.get(_stream_intent)
        msg.message = merge_followup_into_query(
            msg.message, _stream_followup_info,
            subject_name=msg.subject_name or "",
            chapter_name=msg.chapter_name or "",
        )
        logger.info(f"[STREAM] Follow-up detected: intent={_stream_intent}, rewritten query='{msg.message[:60]}'")

    if not _is_followup_s and _s_topic_meta and _s_topic_meta.get("intent"):
        _stream_intent, _stream_db_category = _s_apply_s1(
            _s_topic_meta, _stream_intent, _stream_db_category
        )
        logger.info(f"[PIPELINE][S1][STREAM] Intent resolved: {_stream_intent} (Stage 1 primary)")

    _q_lower_s = msg.message.lower()
    if _stream_intent == "syllabus" and _s_topic_meta and _s_topic_meta.get("search_keywords") and "syllabus" not in _q_lower_s and "curriculum" not in _q_lower_s and "subject list" not in _q_lower_s:
        _stream_intent = "notes"
        _stream_db_category = "notes"
        logger.info(f"[STREAM] Intent upgrade: syllabus → notes (Stage 1 has search_keywords, query is content-seeking)")

    _is_casual = _stream_intent in ("casual", "general")

    subj_ctx = _subj_ctx_result
    ctx_board_id   = subj_ctx.get("board_id")   or msg.board_id
    ctx_class_id   = subj_ctx.get("class_id")   or msg.class_id
    ctx_stream_id  = subj_ctx.get("stream_id")  or getattr(msg, 'stream_id', None)
    ctx_board_name = subj_ctx.get("board_name") or msg.board_name or (user.get("board_name", "") if user else "")
    ctx_class_name = subj_ctx.get("class_name") or msg.class_name or (user.get("class_name", "") if user else "")
    ctx_stream_name= subj_ctx.get("stream_name") or getattr(msg, 'stream_name', None) or (user.get("stream_name", "") if user else "")

    if not _is_casual and not _sem_class_result and ctx_board_id and ctx_board_id != msg.board_id:
        _sem_class_result = await _resolve_semester_class_id(msg.message, ctx_board_id)

    _syl_class_id_s = _sem_class_result or ctx_class_id

    if subj_ctx:
        logger.info(f"Chat [STREAM]: Subject context resolved → {ctx_board_name} / {ctx_class_name} / {ctx_stream_name}")
    if _sem_class_result:
        logger.info(f"Chat [STREAM]: Semester override class_id={_sem_class_result} (from query)")

    async def _fetch_syllabus_async():
        if not (ctx_board_id and _syl_class_id_s):
            return None
        _sck = _syllabus_cache_key(ctx_board_id, _syl_class_id_s, ctx_stream_id, msg.subject_id)
        if _sck in _syllabus_cache:
            return _syllabus_cache[_sck]
        try:
            queries = []
            if ctx_stream_id and msg.subject_id:
                queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id_s, "stream_id": ctx_stream_id, "subject_id": msg.subject_id}, {"_id": 0}))
            if ctx_stream_id:
                queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id_s, "stream_id": ctx_stream_id}, {"_id": 0}))
            queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id_s, "stream_id": {"$exists": False}}, {"_id": 0}))
            queries.append(db.syllabi.find_one({"board_id": ctx_board_id, "class_id": _syl_class_id_s}, {"_id": 0}))
            results = await asyncio.gather(*queries, return_exceptions=True)
            for r in results:
                if r and not isinstance(r, Exception):
                    _syllabus_cache[_sck] = r
                    return r
        except Exception:
            pass
        return None
    _syllabus_task = asyncio.create_task(_fetch_syllabus_async())

    _t_phase1_done = _time_mod.time()
    logger.info(f"[STREAM][TIMING] Phase 0+1 (context+doc+scope): {_t_phase1_done - _t_phase0:.3f}s")

    # ── Phase 2: Web search + history + syllabus (all parallel) ──
    _t_phase2 = _time_mod.time()

    _s_rag_query = msg.message
    if _s_topic_meta and _s_topic_meta.get("search_keywords"):
        _s_rag_query = _s_enhance_q(msg.message, _s_topic_meta)
        if _s_rag_query != msg.message:
            logger.info(f"[PIPELINE][S1][STREAM] Enhanced search query: '{_s_rag_query[:80]}'")

    _rag_quality = "none"

    rag_ctx = {"chunks": [], "chapters": [], "chunk_chapters": [], "subjects": [],
               "vector_hits": [], "source": "none", "quality": "none",
               "_general_knowledge_fallback": True}
    _s1_subject_str = (_s_topic_meta.get("subject", "") if _s_topic_meta else "").strip()
    if _s1_subject_str:
        rag_ctx["_stage1_subject"] = _s1_subject_str
    raw_conv = _prefetched_conv

    if document_text:
        rag_ctx = await resolve_rag_context(
            _s_rag_query, subject_id=msg.subject_id, subject_name=msg.subject_name,
            document_text=document_text, intent=_stream_intent,
        )

    web_results = _early_web if isinstance(_early_web, list) else []

    try:
        syllabus = await asyncio.wait_for(_syllabus_task, timeout=1.0)
    except (asyncio.TimeoutError, Exception):
        syllabus = None

    _t_phase2_done = _time_mod.time()
    logger.info(f"[STREAM][TIMING] Phase 2 (web+syllabus): {_t_phase2_done - _t_phase2:.3f}s | web_results={len(web_results)} | total pre-LLM: {_t_phase2_done - _stream_t0:.3f}s")

    # ── Build prompt ───────────────────────────────────────────────────────────
    system_prompt = build_rag_system_prompt(
        {
            "board_name":  ctx_board_name,
            "class_name":  ctx_class_name,
            "stream_name": ctx_stream_name,
            "subject_name": msg.subject_name,
            "subject_id":  msg.subject_id,
            "chapter_name": msg.chapter_name,
        },
        rag_ctx,
        user_info={
            "name":        (user.get("name", "") if user else ""),
            "board_name":  ctx_board_name or (user.get("board_name", "") if user else ""),
            "class_name":  ctx_class_name or (user.get("class_name", "") if user else ""),
            "stream_name": ctx_stream_name or (user.get("stream_name", "") if user else ""),
            "plan":        (user.get("plan", "free") if user else "free"),
        },
        query=msg.message,
        syllabus=syllabus,
        web_results=web_results or None,
        resolved_intent=_stream_intent,
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
    elif not conv_id and user_id:
        conv_id = str(uuid.uuid4())
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        conv_doc = {
            "id": conv_id,
            "user_id": user_id,
            "title": title,
            "subject_id": msg.subject_id,
            "subject_name": msg.subject_name,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        asyncio.create_task(supa_upsert_conversation(conv_doc))
    elif not conv_id and anon_id:
        conv_id = str(uuid.uuid4())
        title = msg.message[:50] + ("..." if len(msg.message) > 50 else "")
        _now_ts = datetime.now(timezone.utc).isoformat()
        _anon_conv_doc = {
            "id": conv_id,
            "anon_id": anon_id,
            "user_id": anon_id,
            "title": title,
            "subject_id": msg.subject_id or "",
            "subject_name": msg.subject_name or "",
            "messages": [],
            "is_anonymous": True,
            "created_at": _now_ts,
            "updated_at": _now_ts,
        }
        from cache import redis_save_anon_conversation
        redis_save_anon_conversation(anon_id, conv_id, _anon_conv_doc)
        asyncio.create_task(supa_upsert_conversation(_anon_conv_doc))
    elif not conv_id:
        conv_id = None

    _MAX_PROMPT_CHARS = 24_000
    _sys_len = len(system_prompt)
    _hist_len = sum(len(m.get("content", "")) for m in history_messages)
    _user_len = len(msg.message)
    _total_chars = _sys_len + _hist_len + _user_len
    logger.info(f"[STREAM] Payload chars: system={_sys_len}, history={_hist_len} ({len(history_messages)} msgs), user={_user_len}, total={_total_chars}")
    if _total_chars > _MAX_PROMPT_CHARS:
        _target_sys = max(2000, _MAX_PROMPT_CHARS - _hist_len - _user_len)
        if _sys_len > _target_sys:
            system_prompt = system_prompt[:_target_sys]
            logger.warning(f"[STREAM] System prompt truncated: {_sys_len} → {_target_sys} chars (total was {_total_chars})")
        _total_chars = len(system_prompt) + _hist_len + _user_len
        if _total_chars > _MAX_PROMPT_CHARS and history_messages:
            history_messages = history_messages[-4:]
            _hist_len = sum(len(m.get("content", "")) for m in history_messages)
            logger.warning(f"[STREAM] History trimmed to last 4 messages ({_hist_len} chars)")

    _LANG_NAME_MAP = {"as": "Assamese"}
    _target_lang_name = _LANG_NAME_MAP.get(_resp_lang)
    if _want_translate and _target_lang_name:
        _indic_system_prompt = (
            "You are Syra, AI tutor. Reply ONLY in Assamese (অসমীয়া). "
            "Technical terms/formulas in English OK. Be concise: 30-60 words, max 200.\n"
        )
        if system_prompt:
            _ctx_markers = ["**GROUNDING CONTEXT", "**CURRICULUM", "**SUBJECT CHAPTERS", "REFERENCE MATERIAL:", "CONTEXT:", "RELEVANT CONTENT:"]
            _ctx_section = ""
            for _marker in _ctx_markers:
                _idx = system_prompt.find(_marker)
                if _idx != -1:
                    _ctx_section = system_prompt[_idx:]
                    break
            if _ctx_section:
                _indic_system_prompt += f"\n{_ctx_section}"
            else:
                _content_lines = [l for l in system_prompt.split('\n') if l.strip() and not l.strip().startswith(('You are', 'IMPORTANT:', 'RULES:', 'Format'))]
                if _content_lines:
                    _indic_system_prompt += "\nCONTEXT:\n" + "\n".join(_content_lines[-15:])

        system_prompt = _indic_system_prompt
        logger.info(f"[STREAM] Indic-first prompt built for {_target_lang_name} ({len(system_prompt)} chars)")

    messages_payload = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": msg.message}]

    user_msg_saved   = msg.message
    rag_source_saved = rag_ctx.get("source",  "none")
    if _is_card_context and rag_source_saved == "document":
        rag_source_saved = "library"
        rag_ctx["source"] = "library"
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
    rag_chapter_slug = (_rag_chaps[0].get("slug", "") if _rag_chaps else None) or None
    full_response = []

    _rag_raw_chunks = rag_ctx.get("chunks", [])
    rag_chunk_snippet = ""
    _chunk_topic_name = ""
    if _rag_raw_chunks:
        _first = _rag_raw_chunks[0]
        _chunk_topic_name = (_first.get("topic_name") or "").strip()
        _snippet = (_first.get("content") or "").strip()
        _snippet = re.sub(r'#{1,6}\s+', '', _snippet)
        _snippet = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', _snippet)
        _snippet = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', _snippet)
        _snippet = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', _snippet)
        _snippet = re.sub(r'`([^`]+)`', r'\1', _snippet)
        _snippet = re.sub(r'^\s*[-*+]\s+', '', _snippet, flags=re.MULTILINE)
        _snippet = re.sub(r'^\s*\d+\.\s+', '', _snippet, flags=re.MULTILINE)
        _snippet = re.sub(r'\s+', ' ', _snippet).strip()
        if len(_snippet) > 250:
            _snippet = _snippet[:250]
        rag_chunk_snippet = _snippet

    _router_subject = None
    _router_chapter = None
    _router_board   = None
    _router_subject_id = None
    if _router_chapter and not rag_chapter_name:
        rag_chapter_name = _router_chapter
    if _router_subject and not rag_subject_name:
        rag_subject_name = _router_subject
    if _router_subject_id and not rag_subject_id:
        rag_subject_id = _router_subject_id

    _syl_topic_name = None
    _syl_level      = "chapter"
    if _syl_topic_name and _syl_level == "topic":
        rag_topic_name = _syl_topic_name
    elif _chunk_topic_name:
        rag_topic_name = _chunk_topic_name
    elif rag_chapter_name and msg.message and msg.message.strip():
        rag_topic_name = msg.message.strip()
    else:
        rag_topic_name = None

    async def _resolve_chapter_slug_bg():
        nonlocal rag_chapter_slug
        if rag_chapter_name and not rag_chapter_slug:
            try:
                _slug_sid = rag_subject_id or msg.subject_id or None
                _slug_filter: dict = {"title": {"$regex": f"^{re.escape(rag_chapter_name)}$", "$options": "i"}}
                if _slug_sid:
                    _slug_filter["subject_id"] = _slug_sid
                _slug_ch = await db.chapters.find_one(_slug_filter, {"_id": 0, "slug": 1})
                if _slug_ch and _slug_ch.get("slug"):
                    rag_chapter_slug = _slug_ch["slug"]
            except Exception:
                pass

    async def _resolve_source_ctx_bg():
        _src_sid_s = rag_subject_id or msg.subject_id
        if _src_sid_s and _src_sid_s == msg.subject_id and subj_ctx:
            return subj_ctx
        return await _resolve_subject_context(_src_sid_s) if _src_sid_s else {}

    _slug_task = asyncio.create_task(_resolve_chapter_slug_bg())
    _src_ctx_task = asyncio.create_task(_resolve_source_ctx_bg())

    rag_sources = _sources_from_rag_ctx(rag_ctx)
    if web_results:
        rag_sources.extend(_sources_from_web_results(web_results))

    _cache_is_casual = _stream_intent in ("casual", "general")
    _cache_msg_key = f"{msg.message}::lang={_resp_lang}" if _want_translate else msg.message
    _cache_key_val = _cache_key(_cache_msg_key, subject_id=msg.subject_id or "", board_id=ctx_board_id or "", conversation_id=conv_id or "")
    _cache_ttl_val = REDIS_CASUAL_CACHE_TTL if _cache_is_casual else REDIS_AI_CACHE_TTL
    _cached_answer = _redis_get_ai_cache(_cache_key_val)
    if _cached_answer:
        logger.info(f"Redis cache HIT (pre-SSE): {_cache_key_val}")
    elif _cache_key_val in _ai_response_cache:
        _cached_answer = _ai_response_cache[_cache_key_val]
        logger.info(f"Memory cache HIT (pre-SSE): {_cache_key_val}")

    async def event_stream():
        nonlocal full_response
        _credit_saved = False  # set True when answer is committed; controls refund in finally
        try:
            _meta_event = {'conversation_id': conv_id, 'rag_source': rag_source_saved, 'rag_quality': rag_quality_saved, 'rag_chunks': rag_chunks_count, 'rag_subjects': rag_subjects_count, 'rag_subject_id': rag_subject_id, 'rag_subject_name': rag_subject_name, 'rag_subject_icon': rag_subject_icon or '', 'rag_subject_gradient': rag_subject_gradient or '', 'rag_chapter_name': rag_chapter_name, 'rag_chapter_slug': rag_chapter_slug or '', 'rag_topic_name': rag_topic_name or '', 'rag_chunk_snippet': rag_chunk_snippet, 'router_subject': _router_subject, 'router_chapter': _router_chapter, 'router_board': _router_board, 'web_search_used': web_search_used, 'ctx_board_name': ctx_board_name or '', 'ctx_class_name': ctx_class_name or '', 'ctx_stream_name': ctx_stream_name or ''}
            if content_card_meta:
                _meta_event['content_card_name'] = content_card_meta.get('card_name', '')
                _meta_event['content_card_lesson'] = content_card_meta.get('lesson_name', '')
                _meta_event['content_card_subject'] = content_card_meta.get('subject_name', '')
            yield f"data: {json.dumps(_meta_event)}\n\n"

            cached_answer = _cached_answer
            _stream_provider = "unknown"
            if cached_answer:
                logger.info(f"[STREAM][TIMING] TTFT (cache hit): {_time_mod.time() - _stream_t0:.3f}s")
                _CHUNK_SIZE = 120
                for _ci in range(0, len(cached_answer), _CHUNK_SIZE):
                    yield f"data: {json.dumps({'content': cached_answer[_ci:_ci + _CHUNK_SIZE]})}\n\n"
                    if _ci % (_CHUNK_SIZE * 5) == 0:
                        await asyncio.sleep(0)
                full_response.append(cached_answer)
            else:
                _bp_count = 0
                _first_token_logged = False
                _output_buf = ""
                _output_violation = False
                _tune_buf = {"total": "", "chars": 0}

                _pipeline_stream = None
                try:
                    if should_use_pipeline(_stream_intent, user_msg_saved):
                        _pipeline_ctx = {
                            "board_name": ctx_board_name,
                            "class_name": ctx_class_name,
                            "stream_name": ctx_stream_name,
                            "subject_name": msg.subject_name,
                            "chapter_name": msg.chapter_name,
                        }
                        _pipeline_ui = {
                            "name": (user.get("name", "") if user else ""),
                            "board_name": ctx_board_name or (user.get("board_name", "") if user else ""),
                            "class_name": ctx_class_name or (user.get("class_name", "") if user else ""),
                            "plan": (user.get("plan", "free") if user else "free"),
                        }
                        _pipeline_stream = await run_pipeline_stream(
                            query=user_msg_saved,
                            rag_ctx=rag_ctx,
                            context=_pipeline_ctx,
                            user_info=_pipeline_ui,
                            max_tokens=max_tokens,
                            regex_intent=_stream_intent,
                            intent=_stream_intent,
                            topic_metadata=_s_topic_meta,
                        )
                        if _pipeline_stream:
                            logger.info("[PIPELINE] Using multi-LLM pipeline for stream response")
                except Exception as _pipe_stream_err:
                    logger.warning(f"[PIPELINE] Stream pipeline setup failed, falling back: {_pipe_stream_err}")
                    _pipeline_stream = None

                _stream_model = None if _want_translate else (msg.model or "openai/gpt-oss-20b")
                _slm_fallback_stream = lambda: call_llm_api_stream(messages_payload, model=_stream_model, max_tokens=max_tokens, intent=_stream_intent, response_lang=_resp_lang)
                if _want_translate:
                    _pipeline_stream = None

                def _is_sse_error(sse_chunk: str) -> bool:
                    if '"error"' in sse_chunk and sse_chunk.startswith("data: "):
                        try:
                            d = json.loads(sse_chunk[6:])
                            return bool(d.get("error"))
                        except Exception:
                            pass
                    return False

                async def _resilient_pipeline_stream():
                    _emitted_any = False
                    _failed = False
                    try:
                        async for c in _pipeline_stream:
                            if _is_sse_error(c):
                                logger.warning(f"[PIPELINE] Stage 3 stream emitted error — falling back to single-LLM")
                                _failed = True
                                break
                            _emitted_any = True
                            yield c
                    except Exception as _mid_err:
                        logger.warning(f"[PIPELINE] Stage 3 stream raised — falling back to single-LLM: {_mid_err}")
                        _failed = True

                    if _failed and not _emitted_any:
                        async for c in _slm_fallback_stream():
                            yield c
                    elif _failed and _emitted_any:
                        yield f"data: {json.dumps({'content': ' ...[response interrupted, please retry]'})}\n\n"

                _active_stream = _slm_fallback_stream() if _want_translate else (_resilient_pipeline_stream() if _pipeline_stream else _slm_fallback_stream())

                async for chunk in _active_stream:
                    if '"__provider"' in chunk and chunk.startswith("data: "):
                        try:
                            _pdata = json.loads(chunk[6:])
                            if isinstance(_pdata, dict) and "__provider" in _pdata and len(_pdata) == 1:
                                _stream_provider = _pdata["__provider"]
                                continue
                        except Exception:
                            pass
                    if '"content"' in chunk:
                        if not _first_token_logged:
                            logger.info(f"[STREAM][TIMING] TTFT (first LLM token): {_time_mod.time() - _stream_t0:.3f}s")
                            _first_token_logged = True
                        try:
                            data = json.loads(chunk[6:])
                            _piece = data.get("content", "")
                            _tuned = _tune_response_stream(_piece, _stream_intent, _tune_buf)
                            full_response.append(_tuned)
                            _output_buf += _tuned
                            if _tuned != _piece:
                                chunk = f"data: {json.dumps({'content': _tuned})}\n\n"
                            if len(_output_buf) > 200:
                                _out_safe, _out_tag = validate_llm_output(_output_buf)
                                if not _out_safe:
                                    _output_violation = True
                                    logger.warning(f"[guardrails] LLM output violation mid-stream ({_out_tag})")
                                    break
                                _output_buf = _output_buf[-80:]
                        except:
                            pass
                    if _output_violation:
                        break
                    yield chunk
                    _bp_count += 1
                    if _bp_count % 40 == 0:
                        await asyncio.sleep(0)
                if _output_violation:
                    full_response.clear()
                    _fallback = "I need to stop here — my response was heading in a direction that doesn't align with my guidelines. Please try rephrasing your question."
                    full_response.append(_fallback)
                    yield f"data: {json.dumps({'content': _fallback})}\n\n"

                if full_response:
                    answer_str = "".join(full_response)
                    if answer_str:
                        _redis_set("ai_cache", _cache_key_val, answer_str, _cache_ttl_val)
                        if not redis_client:
                            _ai_response_cache[_cache_key_val] = answer_str
                        logger.info(f"Cache MISS → stored (STREAM, ttl={_cache_ttl_val}s): {_cache_key_val}")

            # Yield DONE immediately — DB writes happen in background
            answer = "".join(full_response)
            new_used_optimistic = (credits_info["used"] + 1 if answer else credits_info["used"]) if credits_info else 0

            # ── Resolve deferred source card slugs (ran in parallel with LLM) ────
            try:
                await asyncio.wait_for(_slug_task, timeout=0.5)
            except (asyncio.TimeoutError, Exception):
                pass
            try:
                _src_ctx_s = await asyncio.wait_for(_src_ctx_task, timeout=0.5)
            except (asyncio.TimeoutError, Exception):
                _src_ctx_s = subj_ctx or {}
            _src_board_s = _src_ctx_s.get("board_name") or ctx_board_name or ""
            _src_class_s = _src_ctx_s.get("class_name") or ctx_class_name or ""
            _src_stream_s = _src_ctx_s.get("stream_name") or ctx_stream_name or ""
            _src_board_slug = _src_ctx_s.get("board_slug") or ""
            _src_class_slug = _src_ctx_s.get("class_slug") or ""
            _src_subject_slug = _src_ctx_s.get("subject_slug") or ""

            # ── syrabit_done event with credits metadata + RAG-derived sources + slugs ────
            done_payload = {
                "event": "syrabit_done",
                "conversation_id": conv_id,
                "credits_used": 1 if not is_anon else None,
                "credits_used_total": new_used_optimistic if not is_anon else None,
                "remaining_credits": max(0, credits_info["remaining"] - 1) if credits_info else None,
                "rag_source": rag_source_saved,
                "rag_chunks": rag_chunks_count,
                "words": len(answer.split()) if answer else 0,
                "sources": rag_sources,
                "web_search_used": web_search_used,
                "rag_chapter_slug": rag_chapter_slug or "",
                "ctx_board_name": _src_board_s,
                "ctx_class_name": _src_class_s,
                "ctx_stream_name": _src_stream_s,
                "ctx_board_slug": _src_board_slug,
                "ctx_class_slug": _src_class_slug,
                "ctx_subject_slug": _src_subject_slug,
            }
            if content_card_meta:
                done_payload["content_card_name"] = content_card_meta.get("card_name", "")
                done_payload["content_card_lesson"] = content_card_meta.get("lesson_name", "")
                done_payload["content_card_subject"] = content_card_meta.get("subject_name", "")
                done_payload["content_card_board"] = content_card_meta.get("board_name", "")
                done_payload["content_card_class"] = content_card_meta.get("class_name", "")
            yield f"data: {json.dumps(done_payload)}\n\n"
            yield "data: [DONE]\n\n"

            _t_stream_end = _time_mod.time()
            _total_stream_time = _t_stream_end - _stream_t0
            _rid = getattr(request.state, "request_id", "") if request else ""
            logger.info(
                f"[STREAM][TIMING][SUMMARY] "
                f"rid={_rid} | "
                f"auth={_auth_elapsed:.3f}s | "
                f"phase0+1={_t_phase1_done - _t_phase0:.3f}s | "
                f"phase2(RAG+web)={_t_phase2_done - _t_phase2:.3f}s | "
                f"pre-LLM={_t_phase2_done - _stream_t0:.3f}s | "
                f"total={_total_stream_time:.3f}s | "
                f"cached={'yes' if cached_answer else 'no'} | "
                f"model={msg.model or 'openai/gpt-oss-20b'} | "
                f"intent={_stream_intent} | "
                f"rag_quality={_rag_quality} | "
                f"web_used={web_search_used} | "
                f"words={len(answer.split()) if answer else 0}"
            )

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
                    provider=_stream_provider if not cached_answer else "cache",
                    user_id=str(user_id) if user_id else "anonymous",
                )
            except Exception:
                pass

            if answer and _is_out_of_scope_response(answer) and rag_source_saved == "none":
                logger.info(f"[GUARD] Out-of-scope response detected — refunding credit for user {user_id or 'anon'}")
                _credit_saved = False

            if answer and (not _is_out_of_scope_response(answer) or rag_source_saved != "none"):
                _credit_saved = True
                if user_id:
                    _stream_followup_ctx = None
                    if _stream_intent in ("notes", "important_questions", "pyq"):
                        _prev_fu_completed = []
                        _prev_fu_remaining = []
                        _prev_fu_current = msg.chapter_name or ""
                        if _stream_followup_info:
                            _prev_fu_completed = list(_stream_followup_info.get("completed", []))
                            _next = _stream_followup_info.get("next_item", "")
                            if _next:
                                if _next not in _prev_fu_completed:
                                    _prev_fu_completed.append(_next)
                                _prev_fu_current = _next
                            _prev_fu_remaining = [r for r in _stream_followup_info.get("remaining", []) if r not in _prev_fu_completed]
                        if not _prev_fu_remaining:
                            if _stream_intent == "pyq":
                                _prev_fu_remaining = [m for m in ["1m", "2m", "3m", "5m", "10m"] if m not in _prev_fu_completed]
                            else:
                                _s_rag_chapters = rag_ctx.get("chapters", [])
                                _prev_fu_remaining = [
                                    ch.get("title", "") for ch in _s_rag_chapters
                                    if ch.get("title", "") and ch.get("title", "") not in _prev_fu_completed
                                ]
                        if _prev_fu_current in _prev_fu_remaining:
                            _prev_fu_remaining.remove(_prev_fu_current)
                        _stream_followup_ctx = build_followup_context(
                            intent=_stream_intent,
                            current_item=_prev_fu_current,
                            completed=_prev_fu_completed,
                            remaining=_prev_fu_remaining,
                        )
                    asyncio.create_task(_persist_chat_turn(
                        conv_id, user_id,
                        user_msg_saved, answer,
                        rag_source_saved, rag_chunks_count,
                        credits_info["used"],
                        sources=rag_sources,
                        rag_subject_id=rag_subject_id,
                        rag_subject_name=rag_subject_name,
                        rag_board_name=_src_board_s,
                        rag_class_name=_src_class_s,
                        rag_stream_name=_src_stream_s,
                        rag_board_slug=_src_board_slug,
                        rag_class_slug=_src_class_slug,
                        rag_subject_slug=_src_subject_slug,
                        rag_chapter_name=rag_chapter_name,
                        rag_chapter_slug=rag_chapter_slug,
                        rag_topic_name=rag_topic_name,
                        rag_chunk_snippet=rag_chunk_snippet,
                        followup_context=_stream_followup_ctx,
                    ))
                    asyncio.create_task(_log_chat_message(
                        user_id=user_id,
                        question=user_msg_saved,
                        raw_ai_answer=answer,
                        subject_id=msg.subject_id,
                        subject_name=msg.subject_name,
                        board_name=ctx_board_name,
                        class_name=ctx_class_name,
                        conversation_id=conv_id,
                    ))
                elif anon_id and conv_id:
                    try:
                        from cache import redis_get_anon_conversation, redis_save_anon_conversation
                        _now = datetime.now(timezone.utc).isoformat()
                        _existing = redis_get_anon_conversation(anon_id, conv_id)
                        if not _existing:
                            _existing = await supa_get_conversation(conv_id, anon_id)
                        _prev_msgs = (_existing.get("messages") or []) if _existing else []
                        _prev_msgs.append({"role": "user", "content": user_msg_saved, "timestamp": _now})
                        _asst_msg = {"role": "assistant", "content": answer, "timestamp": _now,
                                     "rag_source": rag_source_saved, "rag_chunks": rag_chunks_count}
                        if rag_sources:
                            _asst_msg["sources"] = rag_sources
                        if rag_subject_id:
                            _asst_msg["rag_subject_id"] = rag_subject_id
                        if rag_subject_name:
                            _asst_msg["rag_subject_name"] = rag_subject_name
                        if rag_chapter_name:
                            _asst_msg["rag_chapter_name"] = rag_chapter_name
                        if rag_chapter_slug:
                            _asst_msg["rag_chapter_slug"] = rag_chapter_slug
                        if rag_topic_name:
                            _asst_msg["rag_topic_name"] = rag_topic_name
                        if rag_chunk_snippet:
                            _asst_msg["rag_chunk_snippet"] = rag_chunk_snippet
                        if _src_board_s:
                            _asst_msg["rag_board_name"] = _src_board_s
                        if _src_class_s:
                            _asst_msg["rag_class_name"] = _src_class_s
                        if _src_stream_s:
                            _asst_msg["rag_stream_name"] = _src_stream_s
                        if _src_board_slug:
                            _asst_msg["rag_board_slug"] = _src_board_slug
                        if _src_class_slug:
                            _asst_msg["rag_class_slug"] = _src_class_slug
                        if _src_subject_slug:
                            _asst_msg["rag_subject_slug"] = _src_subject_slug
                        _prev_msgs.append(_asst_msg)
                        _anon_doc = _existing or {}
                        _anon_doc.update({
                            "id": conv_id, "anon_id": anon_id,
                            "user_id": anon_id,
                            "messages": _prev_msgs,
                            "preview": answer[:100],
                            "updated_at": _now,
                            "is_anonymous": True,
                        })
                        redis_save_anon_conversation(anon_id, conv_id, _anon_doc)
                        asyncio.create_task(supa_upsert_conversation({
                            "id": conv_id, "user_id": anon_id,
                            "title": _anon_doc.get("title", user_msg_saved[:50]),
                            "preview": answer[:100],
                            "subject_id": msg.subject_id or "",
                            "subject_name": msg.subject_name or "",
                            "messages": _prev_msgs,
                            "tokens": len(answer.split()),
                            "created_at": _anon_doc.get("created_at", _now),
                            "updated_at": _now,
                            "is_anonymous": True,
                            "anon_id": anon_id,
                        }))
                        asyncio.create_task(_log_chat_message(
                            user_id=anon_id,
                            question=user_msg_saved,
                            raw_ai_answer=answer,
                            subject_id=msg.subject_id,
                            subject_name=msg.subject_name,
                            board_name=ctx_board_name,
                            class_name=ctx_class_name,
                            conversation_id=conv_id,
                        ))
                    except Exception as _anon_err:
                        logger.warning(f"anon persist failed: {_anon_err}")
        finally:
            if not _credit_saved and user_id and credits_info:
                asyncio.create_task(_refund_credit(user_id, credits_info["used"] + 1))

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
