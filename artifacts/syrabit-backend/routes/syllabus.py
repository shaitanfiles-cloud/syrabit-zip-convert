"""Syrabit.ai — Syllabus CRUD routes"""
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
from seo_engine import _md_to_html, _smart_board_display, _smart_grade_label
from utils import *
from analytics_helpers import *

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/syllabi/{board_id}/{class_id}")
async def get_syllabus(board_id: str, class_id: str):
    """Fetch syllabus for a board+class. Returns structured syllabus content to inject into LLM prompts."""
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}
        
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": {"$exists": False}}, {"_id": 0})
        if not syllabus:
            syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        
        if syllabus:
            logger.info(f"Syllabus found: {board_id}/{class_id}")
            return syllabus
        else:
            return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}


@router.post("/admin/syllabi/{board_id}/{class_id}")
async def create_or_update_syllabus(
    board_id: str,
    class_id: str,
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user)
):
    """Create or update syllabus for a board+class."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        
        syllabus_doc = {
            "board_id": board_id,
            "class_id": class_id,
            "content": data.get("content", ""),
            "chapters": data.get("chapters", []),
            "topics": data.get("topics", []),
            "guidelines": data.get("guidelines", ""),
            "geo_phrases": data.get("geo_phrases", []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        await db.syllabi.update_one(
            {"board_id": board_id, "class_id": class_id},
            {"$set": syllabus_doc},
            upsert=True
        )
        
        logger.info(f"Syllabus saved: {board_id}/{class_id}")
        return {"message": "Syllabus saved successfully", "board_id": board_id, "class_id": class_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Save syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving syllabus: {e}")


@router.delete("/admin/syllabi/{board_id}/{class_id}")
async def delete_syllabus(
    board_id: str,
    class_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Delete syllabus for a board+class."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        
        await db.syllabi.delete_one({"board_id": board_id, "class_id": class_id})
        logger.info(f"Syllabus deleted: {board_id}/{class_id}")
        return {"message": "Syllabus deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting syllabus: {e}")

@router.get("/syllabi/{board_id}/{class_id}/{stream_id}")
async def get_syllabus_stream(board_id: str, class_id: str, stream_id: str):
    """Fetch syllabus for a board+class+stream. Falls back to board+class if stream-specific not found."""
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id}, {"_id": 0})
        if syllabus:
            logger.info(f"Stream syllabus found: {board_id}/{class_id}/{stream_id}")
            return syllabus
        # Fall back to board+class level
        fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": {"$exists": False}}, {"_id": 0})
        if not fallback:
            fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        if fallback:
            logger.info(f"Using board+class fallback syllabus for {board_id}/{class_id}/{stream_id}")
            return {**fallback, "is_fallback": True}
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get stream syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}

@router.post("/admin/syllabi/{board_id}/{class_id}/{stream_id}")
async def create_or_update_syllabus_stream(
    board_id: str,
    class_id: str,
    stream_id: str,
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user)
):
    """Create or update syllabus for a board+class+stream."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        syllabus_doc = {
            "board_id": board_id,
            "class_id": class_id,
            "stream_id": stream_id,
            "content": data.get("content", ""),
            "chapters": data.get("chapters", []),
            "topics": data.get("topics", []),
            "guidelines": data.get("guidelines", ""),
            "geo_phrases": data.get("geo_phrases", []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.syllabi.update_one(
            {"board_id": board_id, "class_id": class_id, "stream_id": stream_id},
            {"$set": syllabus_doc},
            upsert=True
        )
        logger.info(f"Stream syllabus saved: {board_id}/{class_id}/{stream_id}")
        return {"message": "Syllabus saved successfully", "board_id": board_id, "class_id": class_id, "stream_id": stream_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Save stream syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving syllabus: {e}")

@router.delete("/admin/syllabi/{board_id}/{class_id}/{stream_id}")
async def delete_syllabus_stream(
    board_id: str,
    class_id: str,
    stream_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Delete syllabus for a board+class+stream."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        await db.syllabi.delete_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id})
        logger.info(f"Stream syllabus deleted: {board_id}/{class_id}/{stream_id}")
        return {"message": "Syllabus deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete stream syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting syllabus: {e}")


@router.get("/syllabi/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def get_syllabus_subject(board_id: str, class_id: str, stream_id: str, subject_id: str):
    """Fetch syllabus for a specific subject. Fallback: stream → board+class."""
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id}, {"_id": 0})
        if syllabus:
            logger.info(f"Subject syllabus found: {board_id}/{class_id}/{stream_id}/{subject_id}")
            return syllabus
        # Fall back to stream level
        fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": {"$exists": False}}, {"_id": 0})
        if not fallback:
            fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": {"$exists": False}}, {"_id": 0})
        if not fallback:
            fallback = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        if fallback:
            logger.info(f"Using fallback syllabus for subject {subject_id}")
            return {**fallback, "is_fallback": True}
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get subject syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}


@router.post("/admin/syllabi/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def create_or_update_syllabus_subject(
    board_id: str,
    class_id: str,
    stream_id: str,
    subject_id: str,
    data: dict = Body(...),
    admin: dict = Depends(get_admin_user)
):
    """Create or update syllabus for a specific subject."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        syllabus_doc = {
            "board_id": board_id,
            "class_id": class_id,
            "stream_id": stream_id,
            "subject_id": subject_id,
            "content": data.get("content", ""),
            "chapters": data.get("chapters", []),
            "topics": data.get("topics", []),
            "guidelines": data.get("guidelines", ""),
            "geo_phrases": data.get("geo_phrases", []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.syllabi.update_one(
            {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id},
            {"$set": syllabus_doc},
            upsert=True
        )
        logger.info(f"Subject syllabus saved: {board_id}/{class_id}/{stream_id}/{subject_id}")
        return {"message": "Syllabus saved successfully", "subject_id": subject_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Save subject syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving syllabus: {e}")


@router.delete("/admin/syllabi/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def delete_syllabus_subject(
    board_id: str,
    class_id: str,
    stream_id: str,
    subject_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Delete syllabus for a specific subject."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable")
        await db.syllabi.delete_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id})
        logger.info(f"Subject syllabus deleted: {board_id}/{class_id}/{stream_id}/{subject_id}")
        return {"message": "Syllabus deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete subject syllabus error: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting syllabus: {e}")


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    import re as _re
    text = text.lower().strip()
    text = _re.sub(r'[^\w\s-]', '', text)
    text = _re.sub(r'[\s_]+', '-', text)
    text = _re.sub(r'-+', '-', text).strip('-')
    return text


@router.post("/admin/syllabus/publish/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def publish_syllabus_as_card(
    board_id: str,
    class_id: str,
    stream_id: str,
    subject_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Publish a subject-level syllabus as a cms_documents card visible in the library."""
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    # ── 1. Load syllabus (with fallback chain) ────────────────────────────────
    syllabus = await db.syllabi.find_one(
        {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id},
        {"_id": 0}
    )
    if not syllabus:
        syllabus = await db.syllabi.find_one(
            {"board_id": board_id, "class_id": class_id, "stream_id": stream_id},
            {"_id": 0}
        )
    if not syllabus:
        raise HTTPException(status_code=404, detail="No syllabus found for this scope")

    # ── 2. Resolve names / slugs ──────────────────────────────────────────────
    board_doc   = await db.boards.find_one({"id": board_id}, {"_id": 0})
    class_doc   = await db.classes.find_one({"id": class_id}, {"_id": 0})
    stream_doc  = await db.streams.find_one({"id": stream_id}, {"_id": 0})
    subject_doc = await db.subjects.find_one({"id": subject_id}, {"_id": 0})

    board_name   = (board_doc  or {}).get("name",  board_id)
    class_name   = (class_doc  or {}).get("name",  class_id)
    stream_name  = (stream_doc or {}).get("name",  stream_id)
    subject_name = (subject_doc or {}).get("name", subject_id)
    board_slug   = (board_doc  or {}).get("slug",  _slugify(board_name))
    class_slug   = (class_doc  or {}).get("slug",  _slugify(class_name))
    subject_slug = (subject_doc or {}).get("slug", _slugify(subject_name))

    _grade_disp   = _smart_grade_label(class_name, board_name)
    _board_disp   = _smart_board_display(board_name)

    title       = f"{subject_name} Syllabus — {_board_disp} {_grade_disp}"
    seo_slug    = f"{board_slug}-{class_slug}-{_slugify(subject_name)}-syllabus"
    geo_tags    = f"{_grade_disp}, {_board_disp}, {stream_name}"
    seo_tags    = f"Syllabus,{subject_name},{_board_disp},{_grade_disp}"
    meta_desc   = (
        f"Complete {subject_name} syllabus for {_board_disp} {_grade_disp} ({stream_name}). "
        f"Covers key topics, chapters, and learning guidelines as per the {_board_disp} board."
    )

    # ── 3. Build structured markdown ──────────────────────────────────────────
    chapters    = syllabus.get("chapters", [])
    topics      = syllabus.get("topics", [])
    guidelines  = syllabus.get("guidelines", "").strip()
    geo_phrases = syllabus.get("geo_phrases", [])
    content_desc = syllabus.get("content", "").strip()

    md_parts = [f"# {title}\n"]
    if content_desc:
        md_parts.append(f"{content_desc}\n")
    if topics:
        md_parts.append("## Key Topics\n")
        for t in topics:
            md_parts.append(f"- {t}")
        md_parts.append("")
    if chapters:
        md_parts.append("## Chapters\n")
        for i, ch in enumerate(chapters, 1):
            md_parts.append(f"{i}. {ch}")
        md_parts.append("")
    if guidelines:
        md_parts.append("## Learning Guidelines\n")
        md_parts.append(guidelines)
        md_parts.append("")
    if geo_phrases:
        md_parts.append("## Board Authority Notes\n")
        for phrase in geo_phrases:
            md_parts.append(f"> {phrase}")
        md_parts.append("")

    raw_md       = "\n".join(md_parts)
    content_html = _md_to_html(raw_md)
    headings_json = _extract_headings_json(raw_md)
    word_count   = len(re.sub(r'<[^>]+>', '', content_html).split())
    now          = datetime.now(timezone.utc).isoformat()

    # ── 4. Upsert into cms_documents ──────────────────────────────────────────
    existing = await db.cms_documents.find_one({"seo_slug": seo_slug}, {"_id": 0, "id": 1})
    doc_id   = (existing or {}).get("id") or str(uuid.uuid4())

    doc_data = {
        "id":              doc_id,
        "type":            "syllabus",
        "title":           title,
        "content":         raw_md,
        "content_html":    content_html,
        "meta_description": meta_desc,
        "description":     content_desc,
        "seo_tags":        seo_tags,
        "geo_tags":        geo_tags,
        "primary_keyword": f"{subject_name} Syllabus",
        "seo_slug":        seo_slug,
        "category":        "syllabus",
        "schema_type":     "Course",
        "headings":        headings_json,
        "word_count":      word_count,
        "status":          "published",
        "linked_subject_id": subject_id,
        "linked_scope":    f"{board_id}/{class_id}/{stream_id}/{subject_id}",
        "rag_processed":   False,
        "updated_at":      now,
        "created_by":      admin.get("email", "admin"),
    }
    await db.cms_documents.update_one(
        {"seo_slug": seo_slug},
        {"$set": doc_data, "$setOnInsert": {"created_at": now}},
        upsert=True
    )
    logger.info(f"Syllabus card published: {seo_slug} (subject={subject_id})")
    return {"id": doc_id, "seo_slug": seo_slug, "title": title, "url": f"/learn/{seo_slug}"}


# ─────────────────────────────────────────────
# SYLLABUS EMBEDDER — admin endpoints
# ─────────────────────────────────────────────

@router.post("/admin/syllabus/seed-embeddings")
async def admin_seed_syllabus_embeddings(admin: dict = Depends(get_admin_user)):
    """
    Force a full re-embed of all SEED_DATA chapters into the `syllabus_embeddings`
    collection. Safe to run multiple times — drops existing and re-seeds.
    On first run after deployment this happens automatically in the background;
    call this endpoint to trigger it manually or force a refresh.
    """
    global _syllabus_embedder
    if _syllabus_embedder is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")
    result = await _syllabus_embedder.reseed()
    return result


@router.get("/admin/syllabus/embedding-stats")
async def admin_syllabus_embedding_stats(admin: dict = Depends(get_admin_user)):
    """Return counts for the syllabus_embeddings collection and in-memory cache."""
    global _syllabus_embedder
    if _syllabus_embedder is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")
    return await _syllabus_embedder.stats()


# ─────────────────────────────────────────────
# AI CHAT ROUTES
# ─────────────────────────────────────────────

