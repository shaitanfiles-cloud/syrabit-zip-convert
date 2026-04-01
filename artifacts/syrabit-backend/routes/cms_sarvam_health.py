"""Syrabit.ai — CMS documents, Sarvam AI, health checks, studio"""
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
from starlette.requests import Request as StarletteRequest
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field, EmailStr
import cachetools, httpx
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
from routes.admin_monetization import merge_subject_content, _md_to_html as _blog_md_to_html, _extract_headings_json, preprocess_markdown
from auth_deps import (
    get_current_user, get_admin_user, create_access_token, create_refresh_token,
    decode_token, check_rate_limit, get_user_credits, rate_limit_chat,
    get_current_user_optional,
)
from db_ops import *
from llm import call_llm_api, call_llm_api_stream, _LLM_PROVIDERS, _llm_batcher
from cache import _content_cache, _ai_response_cache, _redis_hit_count, _redis_miss_count
import metrics as _metrics_mod
from metrics import (
    _metrics, _health_deps_cache, _health_deps_cache_at, _HEALTH_CACHE_TTL_S,
    _metrics_history, _metrics_history_lock, _METRICS_HISTORY_MAX,
    _snapshot_metrics, _start_metrics_collector, _startup_time,
    _check_health_deps, _dispatch_alert, _alerting_loop,
    _ALERT_COOLDOWN_S, _alert_last_fired, _ALERT_THRESHOLDS,
)
from rag import *
from seo_engine import _md_to_html
from utils import *
from analytics_helpers import *
import ga4_client
import vertex_services

logger = logging.getLogger(__name__)

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text

router = APIRouter()

class CMSDocument(BaseModel):
    title: str
    content: str = ""           # raw markdown (content_raw)
    content_html: Optional[str] = ""   # processed HTML (auto-generated if empty)
    meta_description: Optional[str] = ""  # 160 char SEO description
    description: Optional[str] = ""  # Long description (2000 char)
    seo_tags: Optional[str] = ""
    primary_keyword: Optional[str] = ""
    seo_slug: Optional[str] = ""
    thumbnail_url: Optional[str] = ""
    alt_text: Optional[str] = ""
    category: Optional[str] = ""  # e.g., ahsec/class12/pcm/physics
    headings: Optional[str] = ""  # JSON string of extracted headings
    geo_tags: Optional[str] = ""  # board/class/subject/topic for GEO targeting
    schema_type: Optional[str] = "Article"  # Article, FAQPage, HowTo
    canonical_url: Optional[str] = ""
    status: str = "draft"

class CMSDocumentUpdate(BaseModel):
    """Partial-update model for PATCH — all fields optional."""
    title: Optional[str] = None
    content: Optional[str] = None
    content_html: Optional[str] = None
    meta_description: Optional[str] = None
    description: Optional[str] = None
    seo_tags: Optional[str] = None
    primary_keyword: Optional[str] = None
    seo_slug: Optional[str] = None
    thumbnail_url: Optional[str] = None
    alt_text: Optional[str] = None
    category: Optional[str] = None
    headings: Optional[str] = None
    geo_tags: Optional[str] = None
    schema_type: Optional[str] = None
    canonical_url: Optional[str] = None
    status: Optional[str] = None
    is_published: Optional[bool] = None

@router.get("/admin/content/cms-documents/merged-subject-ids")
async def get_merged_subject_ids(admin: dict = Depends(get_admin_user)):
    """Return the set of subject IDs that already have a cms_documents entry."""
    try:
        if not await is_mongo_available():
            return []
        cursor = db.cms_documents.find({"subject_id": {"$exists": True, "$ne": ""}}, {"_id": 0, "subject_id": 1})
        docs = await cursor.to_list(10000)
        return list({d["subject_id"] for d in docs if d.get("subject_id")})
    except Exception:
        mark_mongo_down()
        return []

@router.get("/admin/content/cms-documents/seo-topics-subject-ids")
async def get_seo_topics_subject_ids(admin: dict = Depends(get_admin_user)):
    """Return subject IDs that have at least one SEO topic in the topics collection."""
    try:
        if not await is_mongo_available():
            return []
        ids = await db.topics.distinct("subject_id", {"subject_id": {"$exists": True, "$ne": ""}})
        return [sid for sid in ids if sid]
    except Exception:
        mark_mongo_down()
        return []

@router.get("/admin/content/cms-documents/assets-generated-subject-ids")
async def get_assets_generated_subject_ids(admin: dict = Depends(get_admin_user)):
    """Return subject IDs where all chapters have notes generated or content > 100 chars,
    OR where pipeline artifacts (PYQs, flashcards, blogs) exist for that subject."""
    try:
        if not await is_mongo_available():
            return []
        chapter_pipeline = [
            {"$match": {"subject_id": {"$exists": True, "$ne": ""}}},
            {"$project": {
                "subject_id": 1,
                "has_notes": {"$or": [
                    {"$eq": ["$notes_generated", True]},
                    {"$gt": [{"$strLenCP": {"$trim": {"input": {"$ifNull": ["$content", ""]}}}}, 100]}
                ]}
            }},
            {"$group": {
                "_id": "$subject_id",
                "total": {"$sum": 1},
                "with_notes": {"$sum": {"$cond": ["$has_notes", 1, 0]}}
            }},
            {"$match": {"$expr": {"$eq": ["$total", "$with_notes"]}, "total": {"$gt": 0}}}
        ]
        chapter_results, pyq_sids, fc_sids, ai_pyq_sids = await asyncio.gather(
            db.chapters.aggregate(chapter_pipeline).to_list(10000),
            db.topic_pyq_collections.distinct("subject_id", {"subject_id": {"$exists": True, "$ne": ""}}),
            db.flashcard_collections.distinct("subject_id", {"subject_id": {"$exists": True, "$ne": ""}}),
            db.ai_pyq_collections.distinct("subject_id", {"subject_id": {"$exists": True, "$ne": ""}}),
        )
        result_set = set()
        for r in chapter_results:
            if r.get("_id"):
                result_set.add(r["_id"])
        for sid in pyq_sids:
            if sid:
                result_set.add(sid)
        for sid in fc_sids:
            if sid:
                result_set.add(sid)
        for sid in ai_pyq_sids:
            if sid:
                result_set.add(sid)
        return list(result_set)
    except Exception:
        mark_mongo_down()
        return []

@router.get("/admin/content/cms-documents")
async def get_cms_documents(admin: dict = Depends(get_admin_user)):
    """Get all CMS documents for admin"""
    try:
        if not await is_mongo_available():
            return []
        docs = await db.cms_documents.find({}, {"_id": 0}).sort("updated_at", -1).limit(100).to_list(100)
        return docs
    except Exception:
        mark_mongo_down()
        return []

@router.post("/admin/content/cms-documents")
async def create_cms_document(doc: CMSDocument, admin: dict = Depends(get_admin_user)):
    """Create new SEO-optimized CMS document with auto markdown→HTML processing"""
    doc_id = str(uuid.uuid4())
    raw_md = doc.content or ""
    content_html = doc.content_html or _md_to_html(raw_md)
    headings_json = doc.headings or _extract_headings_json(raw_md)
    word_count = len(re.sub(r'<[^>]+>', '', content_html).split())
    now = datetime.now(timezone.utc).isoformat()
    
    doc_data = {
        "id": doc_id,
        "title": doc.title,
        "content": raw_md,          # raw markdown
        "content_html": content_html,  # processed HTML
        "meta_description": doc.meta_description,
        "description": doc.description,
        "seo_tags": doc.seo_tags,
        "geo_tags": doc.geo_tags,
        "primary_keyword": doc.primary_keyword,
        "seo_slug": doc.seo_slug,
        "thumbnail_url": doc.thumbnail_url,
        "alt_text": doc.alt_text,
        "category": doc.category,
        "headings": headings_json,
        "schema_type": doc.schema_type,
        "canonical_url": doc.canonical_url,
        "status": doc.status,
        "word_count": word_count,
        "rag_processed": False,
        "created_at": now,
        "updated_at": now,
        "created_by": admin.get("email"),
    }
    
    await db.cms_documents.insert_one(doc_data)
    doc_data.pop("_id", None)
    return doc_data

@router.patch("/admin/content/cms-documents/{doc_id}")
async def update_cms_document(doc_id: str, doc: CMSDocumentUpdate, admin: dict = Depends(get_admin_user)):
    """Partial update of a CMS document — only non-None fields are written."""
    # Fetch existing doc to preserve fields not supplied in this request
    existing = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")

    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}

    # Apply only the fields explicitly provided in the request body
    patch = doc.model_dump(exclude_none=True)

    # Content-derived fields (re-process if content is being updated)
    if "content" in patch:
        raw_md = patch["content"]
        updates["content"] = raw_md
        updates["content_html"] = patch.pop("content_html", None) or _md_to_html(raw_md)
        updates["headings"] = patch.pop("headings", None) or _extract_headings_json(raw_md)
        content_html_for_wc = updates["content_html"]
        updates["word_count"] = len(re.sub(r'<[^>]+>', '', content_html_for_wc).split())
    elif "content_html" in patch:
        updates["content_html"] = patch.pop("content_html")
    if "headings" in patch:
        updates["headings"] = patch.pop("headings")

    # Handle is_published → status mapping
    if "is_published" in patch:
        updates["status"] = "published" if patch.pop("is_published") else "draft"

    # Copy all remaining patch fields directly
    for k, v in patch.items():
        updates[k] = v

    await db.cms_documents.update_one({"id": doc_id}, {"$set": updates})
    updated = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    return updated


@router.put("/admin/content/cms-documents/{doc_id}")
async def put_cms_document(doc_id: str, doc: CMSDocumentUpdate, admin: dict = Depends(get_admin_user)):
    """PUT alias for PATCH /admin/content/cms-documents/{doc_id} — partial update."""
    return await update_cms_document(doc_id, doc, admin)


@router.post("/admin/content/cms-documents/{doc_id}/publish")
async def publish_cms_document(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Toggle document status between published/draft. Auto-generates JSON-LD breadcrumb on publish."""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    new_status = "published" if doc.get("status") != "published" else "draft"
    now = datetime.now(timezone.utc).isoformat()
    updates = {"status": new_status, "updated_at": now}
    if new_status == "published":
        updates["published_at"] = now
        breadcrumb_items = [{"@type": "ListItem", "position": 1, "name": "Home", "item": "https://syrabit.ai"}]
        pos = 2
        if doc.get("linked_board_name"):
            breadcrumb_items.append({"@type": "ListItem", "position": pos, "name": doc["linked_board_name"],
                                     "item": f"https://syrabit.ai/{_slugify(doc['linked_board_name'])}"})
            pos += 1
        if doc.get("linked_class_name"):
            class_path = f"https://syrabit.ai/{_slugify(doc.get('linked_board_name', ''))}/{_slugify(doc['linked_class_name'])}"
            breadcrumb_items.append({"@type": "ListItem", "position": pos, "name": doc["linked_class_name"], "item": class_path})
            pos += 1
        if doc.get("linked_subject_name"):
            subject_path = f"https://syrabit.ai/{_slugify(doc.get('linked_board_name', ''))}/{_slugify(doc.get('linked_class_name', ''))}/{_slugify(doc['linked_subject_name'])}"
            breadcrumb_items.append({"@type": "ListItem", "position": pos, "name": doc["linked_subject_name"], "item": subject_path})
            pos += 1
        breadcrumb_items.append({"@type": "ListItem", "position": pos, "name": doc.get("title", "")})
        updates["json_ld_breadcrumb"] = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": breadcrumb_items,
        }
        schema_type = doc.get("schema_type", "Article")
        updates["json_ld_article"] = {
            "@context": "https://schema.org",
            "@type": schema_type,
            "headline": doc.get("title", ""),
            "description": doc.get("meta_description", ""),
            "author": {"@type": "Organization", "name": "Syrabit.ai"},
            "publisher": {"@type": "Organization", "name": "Syrabit.ai"},
            "datePublished": now,
            "dateModified": now,
        }
        if doc.get("canonical_url"):
            updates["json_ld_article"]["mainEntityOfPage"] = doc["canonical_url"]
        if doc.get("thumbnail_url"):
            updates["json_ld_article"]["image"] = doc["thumbnail_url"]
    await db.cms_documents.update_one({"id": doc_id}, {"$set": updates})
    return {"status": new_status}


@router.post("/admin/content/cms-documents/{doc_id}/link-syllabus")
async def link_cms_syllabus(doc_id: str, data: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Link a CMS document to a syllabus scope. Auto-populates canonical URL and geo_tags."""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    board_id   = data.get("board_id", "")
    class_id   = data.get("class_id", "")
    stream_id  = data.get("stream_id", "")
    subject_id = data.get("subject_id", "")
    board_doc   = await db.boards.find_one({"id": board_id},   {"_id": 0}) or {}
    class_doc   = await db.classes.find_one({"id": class_id},  {"_id": 0}) or {}
    stream_doc  = await db.streams.find_one({"id": stream_id}, {"_id": 0}) or {}
    subject_doc = await db.subjects.find_one({"id": subject_id}, {"_id": 0}) or {}
    board_name   = board_doc.get("name",   board_id)
    class_name   = class_doc.get("name",   class_id)
    stream_name  = stream_doc.get("name",  stream_id)
    subject_name = subject_doc.get("name", subject_id)
    canonical = f"/{_slugify(board_name)}/{_slugify(class_name)}/{_slugify(subject_name)}"
    geo_phrase = ", ".join(filter(None, [class_name, board_name, stream_name]))
    updates = {
        "linked_subject_id":   subject_id,
        "linked_board_id":     board_id,
        "linked_class_id":     class_id,
        "linked_stream_id":    stream_id,
        "linked_subject_name": subject_name,
        "linked_board_name":   board_name,
        "linked_class_name":   class_name,
        "linked_stream_name":  stream_name,
        "linked_scope":        f"{board_id}/{class_id}/{stream_id}/{subject_id}",
        "canonical_url":       canonical,
        "geo_tags":            geo_phrase,
        "updated_at":          datetime.now(timezone.utc).isoformat(),
    }
    await db.cms_documents.update_one({"id": doc_id}, {"$set": updates})
    logger.info(f"CMS doc {doc_id} linked to scope {board_id}/{class_id}/{stream_id}/{subject_id}")
    return {"message": "Linked to syllabus scope", "canonical_url": canonical, "geo_tags": geo_phrase,
            "board_name": board_name, "class_name": class_name, "stream_name": stream_name, "subject_name": subject_name}


@router.post("/admin/content/cms-documents/{doc_id}/revisions")
async def save_cms_revision(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Create a dated draft revision duplicate of a CMS document."""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    from datetime import date as _date
    date_str  = _date.today().strftime("%Y-%m-%d")
    rev_id    = f"{doc_id}-rev-{uuid.uuid4().hex[:6]}"
    base_slug = doc.get("seo_slug", _slugify(doc.get("title", "doc")))
    rev_slug  = f"{base_slug}-rev-{date_str}"
    revision  = {
        **doc,
        "id":             rev_id,
        "title":          f"{doc.get('title', 'Untitled')} — Rev {date_str}",
        "seo_slug":       rev_slug,
        "status":         "draft",
        "is_revision":    True,
        "source_doc_id":  doc_id,
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }
    revision.pop("_id", None)
    await db.cms_documents.insert_one(revision)
    logger.info(f"Revision created: {rev_id} from {doc_id}")
    return {"id": rev_id, "title": revision["title"], "seo_slug": rev_slug}


@router.post("/admin/content/extract-pdf-text")
async def extract_pdf_text(file: UploadFile = File(...), admin: dict = Depends(get_admin_user)):
    """Extract text from a PDF upload (no Supabase needed) for pasting into the editor."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")
    try:
        import io
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(raw))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        extracted = "\n\n".join(pages)
        return {"text": extracted, "pages": len(reader.pages), "chars": len(extracted)}
    except ImportError:
        # Fallback to PyPDF2 if pypdf not available
        try:
            import PyPDF2, io
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            pages = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text.strip())
            extracted = "\n\n".join(pages)
            return {"text": extracted, "pages": len(reader.pages), "chars": len(extracted)}
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"PDF extraction failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"PDF extraction failed: {e}")

@router.delete("/admin/content/cms-documents/{doc_id}")
async def delete_cms_document(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Delete CMS document"""
    await db.cms_documents.delete_one({"id": doc_id})
    # Also delete from RAG index
    await db.cms_rag_chunks.delete_many({"document_id": doc_id})
    return {"message": "Document deleted"}

@router.post("/admin/content/cms-documents/{doc_id}/process-rag")
async def process_cms_rag(doc_id: str, admin: dict = Depends(get_admin_user)):
    """Process document for RAG indexing"""
    doc = await db.cms_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Extract text content (strip HTML tags)
    import re
    text_content = re.sub(r'<[^>]+>', '', doc["content"])
    
    # Split into chunks (500-word chunks with 100-word overlap)
    words = text_content.split()
    chunk_size = 500
    overlap = 100
    chunks = []
    
    for i in range(0, len(words), chunk_size - overlap):
        chunk_words = words[i:i + chunk_size]
        if chunk_words:
            chunk_text = ' '.join(chunk_words)
            chunks.append({
                "id": str(uuid.uuid4()),
                "document_id": doc_id,
                "document_title": doc["title"],
                "chunk_text": chunk_text,
                "chunk_index": len(chunks),
                "word_count": len(chunk_words),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    
    # Delete old chunks
    await db.cms_rag_chunks.delete_many({"document_id": doc_id})
    
    # Insert new chunks
    if chunks:
        await db.cms_rag_chunks.insert_many(chunks)
    
    # Mark document as processed
    result = await db.cms_documents.update_one(
        {"id": doc_id},
        {"$set": {"rag_processed": True, "chunk_count": len(chunks)}}
    )
    
    if result.matched_count == 0:
        logger.warning(f"CMS RAG: Document {doc_id} not found for RAG status update")
    
    logger.info(f"CMS RAG: Processed document {doc_id} into {len(chunks)} chunks")
    return {"message": f"Processed {len(chunks)} chunks", "chunks": len(chunks)}

@router.post("/admin/upload/image")
async def upload_image(file: UploadFile = File(...), admin: dict = Depends(get_admin_user)):
    """Upload image — returns a base64 data URL for immediate use."""
    import base64 as _b64
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"}
    content_type = (file.content_type or "").lower()
    if content_type not in allowed_types:
        raise HTTPException(400, f"Unsupported file type '{content_type}'. Use JPEG, PNG, GIF, WebP, or SVG.")
    max_size = 5 * 1024 * 1024  # 5 MB
    raw = await file.read()
    if len(raw) > max_size:
        raise HTTPException(413, "Image too large — maximum size is 5 MB.")
    b64 = _b64.b64encode(raw).decode()
    data_url = f"data:{content_type};base64,{b64}"
    # Also store in MongoDB for future retrieval
    image_id = str(uuid.uuid4())[:12]
    try:
        await db.uploaded_images.insert_one({
            "id": image_id,
            "filename": file.filename,
            "content_type": content_type,
            "size": len(raw),
            "data_url": data_url,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "uploaded_by": admin.get("email", "admin"),
        })
    except Exception:
        pass  # data_url still returned even if MongoDB insert fails
    return {"url": data_url, "id": image_id, "filename": file.filename}

# Public CMS endpoints (no auth required)
@router.get("/content/cms-library")
async def get_public_cms_library():
    """Get published CMS documents for public library"""
    try:
        if not await is_mongo_available():
            return []
        docs = await db.cms_documents.find(
            {"status": "published"},
            {"_id": 0, "content": 0}
        ).sort("updated_at", -1).limit(50).to_list(50)
        return docs
    except Exception:
        mark_mongo_down()
        return []

@router.get("/content/cms-documents/{doc_id}")
async def get_public_cms_document(doc_id: str):
    """Get single CMS document for public view (PYQs and notes are freely scrapable)."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="Content service unavailable")
        doc = await db.cms_documents.find_one(
            {"$or": [{"id": doc_id}, {"seo_slug": doc_id}], "status": "published"},
            {"_id": 0}
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Content service unavailable")


# ──────────────────────────────────────────────────────────────────────────────
# PERSONALIZED CMS — private, paid, un-scrapable study plans
# GET  /cms/{user_id}/{slug}   — view a personal study plan (auth + paid plan)
# GET  /cms/{user_id}          — list all personal plans for user
# POST /cms/personalize        — generate a new personalized plan via Gemini
# ──────────────────────────────────────────────────────────────────────────────

def _sanitize_mongo_doc(doc):
    """Convert non-JSON-serializable MongoDB field values to strings."""
    if not isinstance(doc, dict):
        return doc
    cleaned = {}
    for k, v in doc.items():
        if isinstance(v, datetime):
            cleaned[k] = v.isoformat()
        elif hasattr(v, '__str__') and type(v).__name__ == 'ObjectId':
            cleaned[k] = str(v)
        elif isinstance(v, dict):
            cleaned[k] = _sanitize_mongo_doc(v)
        elif isinstance(v, list):
            cleaned[k] = [
                _sanitize_mongo_doc(i) if isinstance(i, dict)
                else i.isoformat() if isinstance(i, datetime)
                else str(i) if hasattr(i, '__str__') and type(i).__name__ == 'ObjectId'
                else i
                for i in v
            ]
        else:
            cleaned[k] = v
    return cleaned


@router.get("/cms/posts")
async def list_cms_posts(
    board:      Optional[str] = None,
    class_slug: Optional[str] = None,
    subject_id: Optional[str] = None,
    limit:      int = 20,
    skip:       int = 0,
):
    """Paginated published cms content for Library infinite scroll — reads from cms_documents."""
    try:
        if not await is_mongo_available():
            return JSONResponse(content={"items": [], "total": 0})
        query: dict = {"status": "published", "subject_id": {"$exists": True, "$ne": None}}
        if board:      query["board_slug"]  = board
        if class_slug: query["class_slug"]  = class_slug
        if subject_id: query["subject_id"]  = subject_id
        limit = min(max(limit, 1), 50)
        try:
            items = await asyncio.wait_for(
                db.cms_documents.find(
                    query, {"_id": 0, "merged_md": 0, "content": 0}
                ).sort("updated_at", -1).skip(skip).limit(limit).to_list(limit),
                timeout=10.0,
            )
            total = await asyncio.wait_for(
                db.cms_documents.count_documents(query),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning("CMS posts query timed out after 10s")
            return JSONResponse(content={"items": [], "total": 0})
        items = [_sanitize_mongo_doc(item) for item in items]
        return JSONResponse(content={"items": items, "total": total})
    except Exception as exc:
        logger.warning(f"CMS posts endpoint error: {exc}")
        mark_mongo_down()
        return JSONResponse(content={"items": [], "total": 0})


@router.get("/cms/post/{subject_id}")
async def get_cms_post_by_subject(subject_id: str):
    """Get merged blog post for a subject (public). Returns cache or generates on-the-fly."""
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="Content service unavailable")
        doc = await db.cms_documents.find_one(
            {"subject_id": subject_id, "status": "published"},
            {"_id": 0, "merged_md": 0}
        )
        if doc:
            return {
                "subject_id": subject_id,
                "title":      doc.get("title", ""),
                "subject_merged_html": doc.get("content", ""),
                "headings":   doc.get("headings", ""),
                "word_count": doc.get("word_count", 0),
                "status":     "published",
                "seo_slug":   doc.get("seo_slug", ""),
            }
        merged_md = await merge_subject_content(subject_id)
        if not merged_md:
            raise HTTPException(status_code=404, detail="Subject not found or empty")
        content_html = _blog_md_to_html(merged_md)
        headings     = _extract_headings_json(merged_md)
        word_count   = len(re.sub(r'<[^>]+>', '', content_html).split())
        subject      = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
        return {
            "subject_id": subject_id,
            "title":      (subject.get("name", "") if subject else ""),
            "subject_merged_html": content_html,
            "headings":   headings,
            "word_count": word_count,
            "status":     "live",
        }
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Content service unavailable")


_PLAN_IS_PAID = {"starter", "pro"}

@router.get("/cms/{user_id}")
async def list_personal_plans(user_id: str, response: Response, user: dict = Depends(get_current_user)):
    """List all personalized study plans that belong to this user (paid plan required)."""
    if str(user["id"]) != str(user_id):
        raise HTTPException(403, "Access denied")
    if user.get("plan", "free") not in _PLAN_IS_PAID:
        raise HTTPException(402, "Upgrade to Starter or Pro to access personalized study plans.")
    if not await is_mongo_available():
        raise HTTPException(503, "Content service unavailable")
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "private, no-store"
    docs = await db.cms_documents.find(
        {"user_id": user_id, "doc_type": "personalized", "status": "published"},
        {"_id": 0, "id": 1, "slug": 1, "title": 1, "created_at": 1, "subject_name": 1}
    ).sort("created_at", -1).limit(50).to_list(50)
    return {"plans": docs, "total": len(docs)}

@router.get("/cms/{user_id}/{slug}")
async def get_personal_plan(
    user_id: str,
    slug: str,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Fetch a single personalized study plan. Auth + paid plan required. No-index headers applied."""
    if str(user["id"]) != str(user_id):
        raise HTTPException(403, "This plan belongs to another account.")
    if user.get("plan", "free") not in _PLAN_IS_PAID:
        raise HTTPException(
            402,
            detail={
                "error": "upgrade_required",
                "message": "Personalized study plans require Starter or Pro.",
                "upgrade_url": "/pricing",
            }
        )
    if not await is_mongo_available():
        raise HTTPException(503, "Content service unavailable")
    doc = await db.cms_documents.find_one(
        {"user_id": user_id, "$or": [{"id": slug}, {"slug": slug}], "doc_type": "personalized"},
        {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Study plan not found.")
    if response is not None:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "private, no-store"
    return doc


class PersonalizePlanRequest(BaseModel):
    subject_name: str = ""
    chapter_name: str = ""
    weak_topics: List[str] = []
    context: str = ""          # e.g. "I'm weak in Motion and Gravitation"
    days: int = 7              # sprint length


@router.post("/cms/personalize")
async def generate_personalized_plan(body: PersonalizePlanRequest, user: dict = Depends(get_current_user)):
    """Generate a personalized study plan using Gemini and store it as a private CMS doc."""
    if user.get("plan", "free") not in _PLAN_IS_PAID:
        raise HTTPException(
            402,
            detail={
                "error": "upgrade_required",
                "message": "Personalized plans require a paid plan (Starter/Pro).",
                "upgrade_url": "/pricing",
            }
        )
    if not await is_mongo_available():
        raise HTTPException(503, "Content service unavailable")

    user_id = str(user["id"])
    subject  = body.subject_name or "your subject"
    chapter  = body.chapter_name or ""
    days     = max(1, min(body.days, 30))
    weak     = ", ".join(body.weak_topics) if body.weak_topics else body.context or "general gaps"

    prompt = (
        f"You are a personalised exam coach for AHSEC/SEBA students in Assam (NEP 2020).\n"
        f"Student: {user.get('name', 'Student')} | Subject: {subject}"
        + (f" | Chapter focus: {chapter}" if chapter else "") +
        f"\nWeak areas identified: {weak}\n\n"
        f"Create a detailed, actionable {days}-day study sprint plan:\n"
        f"- Day-by-day schedule (topics, activities, timed blocks)\n"
        f"- Specific PYQ practice recommendations from AHSEC board papers\n"
        f"- Short-answer and long-answer question targets per day\n"
        f"- Revision checkpoints and self-assessment tips\n"
        f"- Exam-day strategy summary\n\n"
        f"Format: Clean Markdown with ## Day headers. Be specific and motivating."
    )

    try:
        plan_md = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=2000)
    except Exception as e:
        logger.error(f"Personalize plan generation failed: {e}")
        raise HTTPException(500, "Plan generation failed. Please try again.")

    plan_html = _md_to_html(plan_md)
    word_count = len(plan_md.split())
    slug_base  = re.sub(r"[^a-z0-9]+", "-", f"{subject} {days}-day plan".lower()).strip("-")
    slug       = f"{slug_base}-{int(time.time())}"
    doc_id     = str(uuid.uuid4())
    now        = datetime.now(timezone.utc).isoformat()
    title      = f"Your {days}-Day {subject.title()} Sprint" + (f": {chapter}" if chapter else "")

    doc = {
        "id":           doc_id,
        "slug":         slug,
        "user_id":      user_id,
        "doc_type":     "personalized",
        "category":     "study_plan",
        "title":        title,
        "content":      plan_md,
        "content_html": plan_html,
        "word_count":   word_count,
        "subject_name": subject,
        "chapter_name": chapter,
        "weak_topics":  body.weak_topics,
        "days":         days,
        "status":       "published",
        "created_at":   now,
        "updated_at":   now,
        "meta": {
            "robots":    "noindex, nofollow",
            "is_private": True,
        },
    }

    await db.cms_documents.insert_one(doc)
    doc.pop("_id", None)
    logger.info(f"Personalized plan generated for user {user_id}: {doc_id}")
    return {
        "id":    doc_id,
        "slug":  slug,
        "title": title,
        "url":   f"/cms/{user_id}/{slug}",
        "doc":   {k: v for k, v in doc.items() if k != "_id"},
    }


@router.post("/admin/cms/merge/{subject_id}")
async def admin_merge_subject(subject_id: str, admin: dict = Depends(get_admin_user)):
    """Merge subject chapters+chunks → cms_documents. Returns word count + headings."""
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="Content service unavailable")
    merged_md = await merge_subject_content(subject_id)
    if not merged_md:
        raise HTTPException(status_code=404, detail="Subject not found or has no chapters")
    content_html  = _blog_md_to_html(merged_md)
    headings_json = _extract_headings_json(merged_md)
    word_count    = len(re.sub(r'<[^>]+>', '', content_html).split())
    subject       = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    now           = datetime.now(timezone.utc).isoformat()
    subject_name  = subject.get("name", "") if subject else ""
    subject_slug  = subject.get("slug", subject_id) if subject else subject_id

    # ── Primary: write to cms_documents ─────────────────────────────────────
    cms_doc_data = {
        "subject_id":          subject_id,
        "title":               subject_name,
        "seo_slug":            subject_slug,
        "board_slug":          (subject.get("board_slug", "") if subject else ""),
        "class_slug":          (subject.get("class_slug", "") if subject else ""),
        "content":             content_html,
        "merged_md":           merged_md,
        "headings":            headings_json,
        "word_count":          word_count,
        "status":              "published",
        "schema_type":         "Article",
        "primary_keyword":     subject_name,
        "updated_at":          now,
    }
    existing_doc = await db.cms_documents.find_one({"subject_id": subject_id}, {"_id": 0, "id": 1})
    if existing_doc:
        await db.cms_documents.update_one(
            {"subject_id": subject_id},
            {"$set": cms_doc_data},
        )
        doc_id = existing_doc.get("id", "")
    else:
        cms_doc_data["id"] = str(uuid.uuid4())
        cms_doc_data["created_at"] = now
        await db.cms_documents.insert_one(cms_doc_data)
        doc_id = cms_doc_data["id"]

    headings = json.loads(headings_json) if headings_json else []
    return {
        "subject_id":  subject_id,
        "doc_id":      doc_id,
        "word_count":  word_count,
        "headings":    headings,
        "slug":        subject_slug,
        "title":       subject_name,
        "merged_md":   merged_md,
        "content":     content_html,
        "board_slug":  subject.get("board_slug", "")   if subject else "",
        "class_slug":  subject.get("class_slug", "")   if subject else "",
        "class_name":  subject.get("class_name", "")   if subject else "",
        "stream_name": subject.get("stream_name", "")  if subject else "",
        "stream_slug": subject.get("stream_slug", "")  if subject else "",
    }


@router.post("/admin/cms/merge-by-chapter/{subject_id}")
async def admin_merge_by_chapter(subject_id: str, admin: dict = Depends(get_admin_user)):
    """Create one CMS document per chapter — thick, syllabus-focused pages."""
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="Content service unavailable")
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("chapter_number", 1).to_list(100)
    if not chapters:
        raise HTTPException(status_code=404, detail="Subject has no chapters")

    subject_name = subject.get("name", "")
    board_slug = subject.get("board_slug", "")
    class_slug = subject.get("class_slug", "")
    class_name = subject.get("class_name", "")
    stream_name = subject.get("stream_name", "")
    stream_slug = subject.get("stream_slug", "")
    now = datetime.now(timezone.utc).isoformat()
    created_docs = []

    for chapter in chapters:
        ch_id = chapter.get("id", "")
        ch_num = chapter.get("chapter_number", "")
        ch_title = chapter.get("title", "")
        ch_heading = f"Chapter {ch_num}: {ch_title}" if ch_num else ch_title

        parts = [f"# {ch_heading}\n\n"]
        ch_desc = (chapter.get("description") or "").strip()
        if ch_desc:
            parts.append(f"{ch_desc}\n\n")

        cks = await db.chunks.find(
            {"chapter_id": ch_id}, {"_id": 0}
        ).sort("order", 1).to_list(500)
        seen_content = set()
        if ch_desc:
            seen_content.add(ch_desc.lower().strip()[:300])
        for ck in cks:
            content = (ck.get("content") or "").strip()
            if not content:
                continue
            content_key = content.lower().strip()[:300]
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            ctype = (ck.get("type") or "").lower()
            if ctype == "pyq":
                parts.append(f"> **Past Year Question**\n>\n> {content}\n\n")
            elif ctype == "summary":
                parts.append(f"### Summary\n\n{content}\n\n")
            elif ctype == "formula":
                parts.append(f"### Formula\n\n{content}\n\n")
            else:
                parts.append(f"{content}\n\n")

        chapter_md = preprocess_markdown("".join(parts))
        if len(chapter_md.strip()) < 50:
            continue

        content_html = _blog_md_to_html(chapter_md)
        headings_json = _extract_headings_json(chapter_md)
        word_count = len(re.sub(r'<[^>]+>', '', content_html).split())
        ch_slug = _slugify(f"{ch_title} {subject_name} chapter {ch_num}" if ch_num else f"{ch_title} {subject_name}")

        cms_doc_data = {
            "subject_id":      subject_id,
            "chapter_id":      ch_id,
            "title":           f"{ch_title} — {subject_name}",
            "seo_slug":        ch_slug,
            "board_slug":      board_slug,
            "class_slug":      class_slug,
            "content":         content_html,
            "merged_md":       chapter_md,
            "headings":        headings_json,
            "word_count":      word_count,
            "status":          "draft",
            "schema_type":     "Article",
            "primary_keyword": f"{ch_title} {subject_name} Assamboard notes",
            "updated_at":      now,
        }
        existing = await db.cms_documents.find_one(
            {"subject_id": subject_id, "chapter_id": ch_id}, {"_id": 0, "id": 1}
        )
        if existing:
            await db.cms_documents.update_one(
                {"subject_id": subject_id, "chapter_id": ch_id},
                {"$set": cms_doc_data},
            )
            doc_id = existing.get("id", "")
        else:
            doc_id = str(uuid.uuid4())
            cms_doc_data["id"] = doc_id
            cms_doc_data["created_at"] = now
            await db.cms_documents.insert_one(cms_doc_data)

        created_docs.append({
            "doc_id":     doc_id,
            "chapter_id": ch_id,
            "title":      cms_doc_data["title"],
            "seo_slug":   ch_slug,
            "word_count": word_count,
            "merged_md":  chapter_md,
        })

    logger.info(f"Chapter-wise merge: {len(created_docs)} docs for subject {subject_id}")
    return {
        "subject_id":   subject_id,
        "subject_name": subject_name,
        "board_slug":   board_slug,
        "class_slug":   class_slug,
        "class_name":   class_name,
        "stream_name":  stream_name,
        "stream_slug":  stream_slug,
        "chapters":     created_docs,
        "total":        len(created_docs),
    }


@router.post("/admin/content/regenerate-sitemap")
async def regenerate_sitemap(admin: dict = Depends(get_admin_user)):
    """Regenerate sitemap.xml — reads from cms_documents only."""
    try:
        sitemap_entries = []
        # All published CMS documents (standalone + subject-merged)
        docs = await db.cms_documents.find(
            {"status": "published"},
            {"_id": 0, "seo_slug": 1, "id": 1, "category": 1, "subject_id": 1, "updated_at": 1}
        ).to_list(3000)
        for doc in docs:
            slug = doc.get("seo_slug") or doc.get("id", "")
            # Subject-merged docs use /subject/ path; standalone blogs use /learn/
            if doc.get("subject_id") and not doc.get("category"):
                path = f"/subject/{doc.get('subject_id', slug)}"
                priority = "0.7"
            else:
                path = f"/learn/{slug}"
                priority = "0.8"
            sitemap_entries.append({
                "url":     path,
                "lastmod": doc.get("updated_at", ""),
                "priority": priority,
            })
        logger.info(f"Sitemap regenerated: {len(sitemap_entries)} entries")
        return {"message": f"Sitemap generated with {len(sitemap_entries)} entries", "count": len(sitemap_entries)}
    except Exception as e:
        logger.error(f"Sitemap generation error: {e}")
        raise HTTPException(status_code=500, detail="Sitemap generation failed")


# ─────────────────────────────────────────────
# PDF DOCUMENT UPLOAD & VIEWER
# ─────────────────────────────────────────────

@router.post("/admin/content/upload-pdf")
async def upload_pdf_document(
    file: UploadFile = File(...),
    subject_id: str = Form(...),
    title: str = Form(None),
    admin: dict = Depends(get_admin_user)
):
    """
    Upload PDF document for a subject to Supabase Storage.
    Extracts text for RAG and stores PDF URL from Supabase.
    """
    # Validate Supabase is configured
    if not supa:
        raise HTTPException(status_code=503, detail="Supabase storage not configured")
    
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Enforce size limit (10MB)
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF file too large (max 10MB)")
    
    # Extract text from PDF for RAG
    extracted_text = ""
    page_count = 0
    is_scanned = False
    
    try:
        from PyPDF2 import PdfReader
        import io
        
        pdf_reader = PdfReader(io.BytesIO(content))
        page_count = len(pdf_reader.pages)
        
        for page in pdf_reader.pages:
            extracted_text += page.extract_text() + "\n"
        
        # Clean extracted text
        extracted_text = extracted_text.strip()
        
        # Check if this is a scanned document (image-based PDF)
        if len(extracted_text) < 50:
            is_scanned = True
            extracted_text = f"[Scanned Document - {file.filename}]\nThis is an image-based PDF (scanned question paper or document). Text extraction not available. OCR may be needed for text search."
            logger.info(f"Scanned/image-based PDF detected: {file.filename}")
        
    except Exception as e:
        logger.error(f"PDF processing failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to process PDF: {str(e)}")
    
    # Upload to Supabase Storage
    try:
        # Create unique filename with timestamp
        import time
        timestamp = int(time.time())
        safe_filename = file.filename.replace(' ', '_').replace('/', '_')
        storage_path = f"pdfs/{subject_id}/{timestamp}_{safe_filename}"
        
        # Ensure bucket exists (create if not)
        try:
            supa.storage.get_bucket("study-materials")
        except:
            try:
                supa.storage.create_bucket("study-materials", options={"public": True})
                logger.info("Created 'study-materials' bucket")
            except Exception as bucket_err:
                logger.warning(f"Bucket creation failed (may already exist): {bucket_err}")
        
        # Upload file to Supabase Storage
        response = supa.storage.from_("study-materials").upload(
            path=storage_path,
            file=content,
            file_options={
                "content-type": "application/pdf",
                "cache-control": "3600",
                "upsert": "false"
            }
        )
        
        # Get public URL
        pdf_url = supa.storage.from_("study-materials").get_public_url(storage_path)
        
        logger.info(f"✅ PDF uploaded to Supabase: {storage_path}")
        
    except Exception as storage_err:
        logger.error(f"Supabase storage upload failed: {storage_err}")
        raise HTTPException(status_code=500, detail=f"Failed to upload to storage: {str(storage_err)}")
    
    # Create document record in MongoDB
    doc_id = str(uuid.uuid4())
    doc_title = title or file.filename
    
    document = {
        "id": doc_id,
        "subject_id": subject_id,
        "title": doc_title,
        "file_name": file.filename,
        "file_size": file_size,
        "content_type": "application/pdf",
        "pdf_url": pdf_url,  # Supabase Storage URL
        "storage_path": storage_path,  # For deletion
        "extracted_text": extracted_text,  # For RAG (or placeholder for scanned)
        "is_scanned": is_scanned,  # Flag for image-based PDFs
        "page_count": page_count,
        "uploaded_by": admin.get("email"),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.content_uploads.insert_one(document)
    
    # Update subject to mark it has a document
    await db.subjects.update_one(
        {"id": subject_id},
        {"$set": {"has_document": True}}
    )
    
    logger.info(f"✅ PDF metadata saved: {file.filename} for subject {subject_id} ({file_size} bytes, {page_count} pages, scanned: {is_scanned})")
    
    return {
        "document_id": doc_id,
        "title": doc_title,
        "file_name": file.filename,
        "file_size": file_size,
        "page_count": page_count,
        "pdf_url": pdf_url,
        "is_scanned": is_scanned,
        "text_length": len(extracted_text),
        "message": "PDF uploaded successfully to Supabase Storage" + (" (scanned document - no text extracted)" if is_scanned else "")
    }


@router.get("/content/documents/{document_id}")
async def get_document(document_id: str):
    """
    Get document details including PDF URL.
    Supports both legacy base64 and new Supabase Storage URLs.
    """
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="Content service unavailable")
        doc = await db.content_uploads.find_one({"id": document_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc
    except HTTPException:
        raise
    except Exception:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail="Content service unavailable")


@router.get("/content/subject-documents/{subject_id}")
async def get_subject_documents(subject_id: str, include_pdf: bool = False):
    """
    Get all documents for a subject.
    """
    try:
        if not await is_mongo_available():
            return []
        projection = {"_id": 0}
        if not include_pdf:
            projection["extracted_text"] = 0
            projection["pdf_data_url"] = 0
            projection["pdf_url"] = 0
        else:
            projection["extracted_text"] = 0
        
        docs = await db.content_uploads.find(
            {"subject_id": subject_id},
            projection
        ).to_list(20)
        return docs
    except Exception:
        mark_mongo_down()
        return []


@router.delete("/admin/content/documents/{document_id}")
async def delete_document(document_id: str, admin: dict = Depends(get_admin_user)):
    """Delete uploaded document from both MongoDB and Supabase Storage"""
    # Get document first to get storage path
    doc = await db.content_uploads.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Delete from Supabase Storage if it exists there
    if doc.get("storage_path") and supa:
        try:
            supa.storage.from_("study-materials").remove([doc["storage_path"]])
            logger.info(f"✅ Deleted PDF from Supabase: {doc['storage_path']}")
        except Exception as e:
            logger.warning(f"Failed to delete from Supabase storage: {e}")
    
    # Delete from MongoDB
    result = await db.content_uploads.delete_one({"id": document_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {"message": "Document deleted successfully from both storage and database"}


# ─────────────────────────────────────────────
# ENHANCED HEALTH
# ─────────────────────────────────────────────
import time as _time_mod
import threading as _threading
from collections import defaultdict as _defaultdict


@router.get("/ready", response_model=ReadyOut)
async def readiness():
    checks = {"mongodb": False, "postgresql": False}
    try:
        if db is not None:
            await db.command("ping")
            checks["mongodb"] = True
    except Exception:
        pass
    try:
        if deps.pg_pool:
            async with deps.pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["postgresql"] = True
    except Exception:
        pass
    all_ok = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )

@router.get("/health", response_model=HealthOut)
async def health():
    kv_ok = await is_mongo_available()
    kv_latency = 0
    if kv_ok:
        try:
            t0 = _time_mod.time()
            await db.boards.find_one({})
            kv_latency = int((_time_mod.time() - t0) * 1000)
        except Exception:
            kv_ok = False

    redis_ok = False
    if redis_client:
        try:
            redis_client.ping()
            redis_ok = True
        except Exception:
            pass

    mongo_status = "ok" if kv_ok else "unavailable"

    pg_ok = False
    pg_latency = 0
    if deps.pg_pool:
        try:
            t1 = _time_mod.time()
            async with deps.pg_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            pg_latency = int((_time_mod.time() - t1) * 1000)
            pg_ok = True
        except Exception:
            pass

    # Razorpay — check if keys are configured (no live HTTP call; avoids cost)
    rp_cfg = await db.api_config.find_one({}, {"payment": 1}) or {}
    rp_payment = rp_cfg.get("payment", {})
    rp_key_id = (rp_payment.get("razorpay_key_id") or os.environ.get("RAZORPAY_KEY_ID", "")).strip()
    rp_key_secret = (rp_payment.get("razorpay_key_secret") or os.environ.get("RAZORPAY_KEY_SECRET", "")).strip()
    rp_status = "configured" if (rp_key_id and rp_key_secret) else "not_configured"

    # Overall status: degraded if any critical dependency is down
    critical_ok = kv_ok and pg_ok
    overall = "ok" if critical_ok else "degraded"

    return {
        "status": overall,
        "version": "2.0.0",
        "service": "Syrabit.ai API",
        "workers": int(os.environ.get("GUNICORN_WORKERS", 3)),
        "uptime_seconds": int(_time_mod.time() - _startup_time),
        "dependencies": {
            "mongodb": {"status": mongo_status, "latencyMs": kv_latency},
            "postgresql": {"status": "ok" if pg_ok else "unavailable", "latencyMs": pg_latency},
            "redis": {"status": "ok" if redis_ok else "not_connected"},
            "llm": {
                "status": "ok" if OPENAI_API_KEY else "not_configured",
                "provider": LLM_PROVIDER,
                "model": LLM_MODEL,
                "providers": [p["provider"] for p in _LLM_PROVIDERS],
                "fallback": len(_LLM_PROVIDERS) > 1,
            },
            "supabase": {"status": "ok" if supa else "not_configured"},
            "razorpay": {"status": rp_status},
        }
    }

@router.get("/metrics")
async def prometheus_metrics():
    import os as _os
    mem_rss_mb = 0
    mem_vms_mb = 0
    cpu = 0
    try:
        with open(f"/proc/{_os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    mem_rss_mb = int(line.split()[1]) / 1024
                elif line.startswith("VmSize:"):
                    mem_vms_mb = int(line.split()[1]) / 1024
        with open(f"/proc/{_os.getpid()}/stat") as f:
            fields = f.read().split()
            utime = int(fields[13])
            stime = int(fields[14])
            total_ticks = utime + stime
            hz = _os.sysconf("SC_CLK_TCK")
            cpu_seconds = total_ticks / hz
            cpu = round(cpu_seconds / max(1, _time_mod.time() - _startup_time) * 100, 1)
    except Exception:
        pass

    content_cache_size = len(_content_cache)
    ai_cache_size = len(_ai_response_cache)
    uptime = int(_time_mod.time() - _startup_time)
    rps = _metrics.get_rps()
    active_users_5m = _metrics.get_active_users(300)
    active_users_15m = _metrics.get_active_users(900)
    active_users_60m = _metrics.get_active_users(3600)
    top_endpoints = _metrics.get_top_endpoints(10)

    lines = [
        f'# HELP syrabit_uptime_seconds Server uptime in seconds',
        f'# TYPE syrabit_uptime_seconds gauge',
        f'syrabit_uptime_seconds {uptime}',
        f'# HELP syrabit_memory_rss_mb Resident memory in MB',
        f'# TYPE syrabit_memory_rss_mb gauge',
        f'syrabit_memory_rss_mb {mem_rss_mb:.1f}',
        f'# HELP syrabit_memory_vms_mb Virtual memory in MB',
        f'# TYPE syrabit_memory_vms_mb gauge',
        f'syrabit_memory_vms_mb {mem_vms_mb:.1f}',
        f'# HELP syrabit_cpu_percent CPU usage percentage',
        f'# TYPE syrabit_cpu_percent gauge',
        f'syrabit_cpu_percent {cpu:.1f}',
        f'# HELP syrabit_requests_total Total requests handled by this worker',
        f'# TYPE syrabit_requests_total counter',
        f'syrabit_requests_total {_metrics.request_count}',
        f'# HELP syrabit_errors_total Total error responses (4xx/5xx)',
        f'# TYPE syrabit_errors_total counter',
        f'syrabit_errors_total {_metrics.error_count}',
        f'# HELP syrabit_requests_in_flight Requests currently being processed',
        f'# TYPE syrabit_requests_in_flight gauge',
        f'syrabit_requests_in_flight {_metrics.active_requests}',
        f'# HELP syrabit_rps Requests per second (60s window)',
        f'# TYPE syrabit_rps gauge',
        f'syrabit_rps {rps}',
        f'# HELP syrabit_chat_requests_total Total AI chat requests',
        f'# TYPE syrabit_chat_requests_total counter',
        f'syrabit_chat_requests_total {_metrics.chat_count}',
        f'# HELP syrabit_active_users_5m Unique authenticated users in last 5 minutes',
        f'# TYPE syrabit_active_users_5m gauge',
        f'syrabit_active_users_5m {active_users_5m}',
        f'# HELP syrabit_active_users_15m Unique authenticated users in last 15 minutes',
        f'# TYPE syrabit_active_users_15m gauge',
        f'syrabit_active_users_15m {active_users_15m}',
        f'# HELP syrabit_active_users_60m Unique authenticated users in last 60 minutes',
        f'# TYPE syrabit_active_users_60m gauge',
        f'syrabit_active_users_60m {active_users_60m}',
        f'# HELP syrabit_content_cache_entries Content cache entries',
        f'# TYPE syrabit_content_cache_entries gauge',
        f'syrabit_content_cache_entries {content_cache_size}',
        f'# HELP syrabit_ai_cache_entries AI response cache entries',
        f'# TYPE syrabit_ai_cache_entries gauge',
        f'syrabit_ai_cache_entries {ai_cache_size}',
        f'# HELP syrabit_workers Configured worker count',
        f'# TYPE syrabit_workers gauge',
        f'syrabit_workers {int(_os.environ.get("GUNICORN_WORKERS", 3))}',
        f'# HELP syrabit_redis_connected Redis connection status',
        f'# TYPE syrabit_redis_connected gauge',
        f'syrabit_redis_connected {1 if redis_client else 0}',
        f'# HELP syrabit_redis_hits Redis cache hits',
        f'# TYPE syrabit_redis_hits counter',
        f'syrabit_redis_hits {_redis_hit_count}',
        f'# HELP syrabit_redis_misses Redis cache misses',
        f'# TYPE syrabit_redis_misses counter',
        f'syrabit_redis_misses {_redis_miss_count}',
    ]
    batch_stats = _llm_batcher.stats
    lines.extend([
        f'# HELP syrabit_llm_batched Total LLM requests processed via batcher',
        f'# TYPE syrabit_llm_batched counter',
        f'syrabit_llm_batched {batch_stats["batched"]}',
        f'# HELP syrabit_llm_deduped Requests served by piggy-backing on in-flight call',
        f'# TYPE syrabit_llm_deduped counter',
        f'syrabit_llm_deduped {batch_stats["deduped"]}',
        f'# HELP syrabit_llm_errors LLM call errors',
        f'# TYPE syrabit_llm_errors counter',
        f'syrabit_llm_errors {batch_stats["errors"]}',
        f'# HELP syrabit_llm_pending Currently in-flight LLM requests',
        f'# TYPE syrabit_llm_pending gauge',
        f'syrabit_llm_pending {batch_stats["pending"]}',
    ])
    for status_code, count in sorted(_metrics.status_counts.items()):
        lines.append(f'syrabit_responses_by_status{{code="{status_code}"}} {count}')
    for endpoint, count in top_endpoints:
        safe = endpoint.replace('"', '\\"')
        lines.append(f'syrabit_endpoint_hits{{path="{safe}"}} {count}')
    from starlette.responses import Response
    return Response(content='\n'.join(lines) + '\n', media_type='text/plain; version=0.0.4; charset=utf-8')

@router.get("/ai/cache/stats")
async def get_cache_stats(admin: dict = Depends(get_admin_user)):
    """Return cache statistics (admin only)."""
    return {
        "size": len(_ai_response_cache),
        "maxsize": _ai_response_cache.maxsize,
        "ttl": _ai_response_cache.ttl
    }

@router.get("/metrics/history")
async def metrics_history(minutes: int = 60, admin: dict = Depends(get_admin_user)):
    """Return time-series metrics history for graphing (admin only)."""
    minutes = min(max(minutes, 1), _METRICS_HISTORY_MAX)
    cutoff = _time_mod.time() - (minutes * 60)
    _snapshot_metrics()
    with _metrics_history_lock:
        data = [s for s in _metrics_history if s["ts"] >= cutoff]

    peak_5m = max((s["active_5m"] for s in data), default=0)
    peak_15m = max((s["active_15m"] for s in data), default=0)
    peak_60m = max((s["active_60m"] for s in data), default=0)
    peak_rps = max((s["rps"] for s in data), default=0)

    return {
        "history": data,
        "peaks": {
            "active_users_5m": peak_5m,
            "active_users_15m": peak_15m,
            "active_users_60m": peak_60m,
            "rps": peak_rps,
        },
        "current": data[-1] if data else None,
        "points": len(data),
        "window_minutes": minutes,
    }

from qa_engine import log_chat_message as _log_chat_message

# ─────────────────────────────────────────────
# SARVAM AI — Translate, TTS, Transliterate
# ─────────────────────────────────────────────

_SARVAM_LANG_CODES = {
    "en", "en-IN", "as", "as-IN", "bn", "bn-IN",
    "hi", "hi-IN", "gu", "gu-IN", "kn", "kn-IN",
    "ml", "ml-IN", "mr", "mr-IN", "od", "od-IN",
    "pa", "pa-IN", "ta", "ta-IN", "te", "te-IN",
}

def _normalise_lang(code: str) -> str:
    """Ensure language code has -IN suffix (sarvam requires it)."""
    code = code.strip()
    if '-' not in code:
        return f"{code}-IN"
    return code

def _sarvam_cache_key(op: str, payload: dict) -> str:
    import hashlib, json
    raw = json.dumps(payload, sort_keys=True)
    return f"sarvam:{op}:{hashlib.md5(raw.encode()).hexdigest()}"

@router.get("/sarvam/status")
async def sarvam_status():
    return {
        "enabled": sarvam_client is not None,
        "supported_languages": sorted(_SARVAM_LANG_CODES),
    }

_LANG_LABELS = {
    "as": "Assamese (অসমীয়া)", "as-IN": "Assamese (অসমীয়া)",
    "bn": "Bengali (বাংলা)", "bn-IN": "Bengali (বাংলা)",
    "en": "English", "en-IN": "English (India)",
    "gu": "Gujarati (ગુજરાતી)", "gu-IN": "Gujarati (ગુજરાતી)",
    "hi": "Hindi (हिन्दी)", "hi-IN": "Hindi (हिन्दी)",
    "kn": "Kannada (ಕನ್ನಡ)", "kn-IN": "Kannada (ಕನ್ನಡ)",
    "ml": "Malayalam (മലയാളം)", "ml-IN": "Malayalam (മലയാളം)",
    "mr": "Marathi (मराठी)", "mr-IN": "Marathi (मराठी)",
    "od": "Odia (ଓଡ଼ିଆ)", "od-IN": "Odia (ଓଡ଼ିଆ)",
    "pa": "Punjabi (ਪੰਜਾਬੀ)", "pa-IN": "Punjabi (ਪੰਜਾਬੀ)",
    "ta": "Tamil (தமிழ்)", "ta-IN": "Tamil (தமிழ்)",
    "te": "Telugu (తెలుగు)", "te-IN": "Telugu (తెలుగు)",
}

@router.get("/admin/translation/languages")
async def admin_translation_languages(admin: dict = Depends(get_admin_user)):
    """Return supported translation languages as {code, label} list."""
    seen_base = set()
    result = []
    for code in sorted(_SARVAM_LANG_CODES):
        base = code.split("-")[0]
        if base in seen_base:
            continue
        seen_base.add(base)
        label = _LANG_LABELS.get(code) or _LANG_LABELS.get(base) or code
        result.append({"code": base, "label": label})
    return result

@router.post("/sarvam/translate")
async def sarvam_translate(data: dict):
    """Translate text between Indian languages via Sarvam AI."""
    if not sarvam_client:
        raise HTTPException(status_code=503, detail="Sarvam AI not configured")
    text = (data.get("text") or data.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    src = _normalise_lang(data.get("source_language_code", "en-IN"))
    tgt = _normalise_lang(data.get("target_language_code", "as-IN"))

    # Check cache first
    cache_key = _sarvam_cache_key("translate", {"text": text, "src": src, "tgt": tgt})
    cached = _get_content_cache(cache_key)
    if cached:
        return {**cached, "cached": True}

    # mayura:v1 supports: hi, bn, mr, te, kn, ml, ta, gu, pa
    # sarvam-translate:v1 supports all Indic langs including as, od
    _MAYURA_LANGS = {"hi-IN", "bn-IN", "mr-IN", "te-IN", "kn-IN", "ml-IN", "ta-IN", "gu-IN", "pa-IN"}
    model = "mayura:v1" if (src in _MAYURA_LANGS and tgt in _MAYURA_LANGS) else "sarvam-translate:v1"
    payload = {
        "input": text,
        "source_language_code": src,
        "target_language_code": tgt,
        "speaker_gender": data.get("speaker_gender", "Female"),
        "mode": data.get("mode", "formal"),
        "model": model,
        "enable_preprocessing": False,
    }
    try:
        resp = await sarvam_client.post("/translate", json=payload)
        resp.raise_for_status()
        result = resp.json()
        out = {"translated_text": result.get("translated_text", ""), "source": src, "target": tgt}
        _set_content_cache(cache_key, out)
        return out
    except httpx.HTTPStatusError as e:
        logger.error(f"Sarvam translate error {e.response.status_code} [{src}->{tgt}]")
        raise HTTPException(status_code=e.response.status_code, detail="Sarvam translation failed")
    except Exception as e:
        logger.error(f"Sarvam translate exception: {type(e).__name__} [{src}->{tgt}]")
        raise HTTPException(status_code=502, detail="Sarvam AI unreachable")

@router.post("/sarvam/tts")
async def sarvam_tts(data: dict):
    """Convert text to speech in Indian languages via Sarvam AI (Bulbul model)."""
    if not sarvam_client:
        raise HTTPException(status_code=503, detail="Sarvam AI not configured")
    text = (data.get("text") or data.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    # Sarvam TTS max input ~500 chars per request
    if len(text) > 500:
        text = text[:500]
    lang = _normalise_lang(data.get("target_language_code", "en-IN"))

    # Cache audio as base64
    cache_key = _sarvam_cache_key("tts", {"text": text, "lang": lang,
        "speaker": data.get("speaker", "meera"), "pace": data.get("pace", 1.0)})
    cached = _get_content_cache(cache_key)
    if cached:
        return {**cached, "cached": True}

    # Valid Sarvam TTS speakers (updated list)
    _VALID_SPEAKERS = {
        "anushka", "abhilash", "manisha", "vidya", "arya", "karun", "hitesh",
        "aditya", "ritu", "priya", "neha", "rahul", "pooja", "rohan", "simran",
        "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun", "manan",
        "sumit", "roopa", "kabir", "aayan", "shubh", "ashutosh", "advait",
        "amelia", "sophia", "anand", "tanya", "tarun", "sunny", "mani", "gokul",
        "vijay", "shruti", "suhani", "mohit", "kavitha", "rehan", "soham", "rupali",
    }
    speaker = data.get("speaker", "anushka")
    if speaker not in _VALID_SPEAKERS:
        speaker = "anushka"
    payload = {
        "inputs": [text],
        "target_language_code": lang,
        "speaker": speaker,
        "model": data.get("model", "bulbul:v2"),
        "pitch": data.get("pitch", 0),
        "pace": data.get("pace", 1.0),
        "loudness": data.get("loudness", 1.5),
        "speech_sample_rate": data.get("speech_sample_rate", 22050),
        "enable_preprocessing": False,
    }
    try:
        resp = await sarvam_client.post("/text-to-speech", json=payload)
        resp.raise_for_status()
        result = resp.json()
        audios = result.get("audios", [])
        if not audios:
            raise HTTPException(status_code=502, detail="Sarvam TTS returned no audio")
        out = {
            "audio_base64": audios[0],
            "language": lang,
            "format": "wav",
            "sample_rate": payload["speech_sample_rate"],
        }
        _set_content_cache(cache_key, out)
        return out
    except httpx.HTTPStatusError as e:
        logger.error(f"Sarvam TTS error {e.response.status_code} [{lang}]")
        raise HTTPException(status_code=e.response.status_code, detail="Sarvam TTS failed")
    except Exception as e:
        logger.error(f"Sarvam TTS exception: {type(e).__name__} [{lang}]")
        raise HTTPException(status_code=502, detail="Sarvam AI unreachable")

@router.post("/sarvam/transliterate")
async def sarvam_transliterate(data: dict):
    """Transliterate text between scripts via Sarvam AI."""
    if not sarvam_client:
        raise HTTPException(status_code=503, detail="Sarvam AI not configured")
    text = (data.get("text") or data.get("input") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    src = _normalise_lang(data.get("source_language_code", "en-IN"))
    tgt = _normalise_lang(data.get("target_language_code", "as-IN"))

    cache_key = _sarvam_cache_key("transliterate", {"text": text, "src": src, "tgt": tgt})
    cached = _get_content_cache(cache_key)
    if cached:
        return {**cached, "cached": True}

    payload = {
        "input": text,
        "source_language_code": src,
        "target_language_code": tgt,
        "spoken_language_code": src,
        "with_timestamps": False,
        "numerals_format": "international",
    }
    try:
        resp = await sarvam_client.post("/transliterate", json=payload)
        resp.raise_for_status()
        result = resp.json()
        out = {"transliterated_text": result.get("transliterated_text", ""), "source": src, "target": tgt}
        _set_content_cache(cache_key, out)
        return out
    except httpx.HTTPStatusError as e:
        logger.error(f"Sarvam transliterate error {e.response.status_code} [{src}->{tgt}]")
        raise HTTPException(status_code=e.response.status_code, detail="Sarvam transliteration failed")
    except Exception as e:
        logger.error(f"Sarvam transliterate exception: {type(e).__name__} [{src}->{tgt}]")
        raise HTTPException(status_code=502, detail="Sarvam AI unreachable")

# ─────────────────────────────────────────────
# BOT RENDER MIDDLEWARE (production SSR for AI crawlers)
# ─────────────────────────────────────────────
_BOT_UA_RE = re.compile(
    r"googlebot|bingbot|yandexbot|yandex|duckduckbot|slurp|baiduspider|"
    r"facebookexternalhit|twitterbot|linkedinbot|telegrambot|whatsapp|applebot|"
    r"ia_archiver|msnbot|ahrefsbot|semrushbot|petalbot|gptbot|oai-searchbot|"
    r"chatgpt-user|claudebot|anthropic-ai|perplexitybot|google-extended|"
    r"facebookbot|meta-externalagent|cohere-ai|bytespider|ccbot|applebot-extended",
    re.IGNORECASE,
)

_BOT_SKIP_PREFIXES = (
    "/api/", "/admin", "/chat", "/history", "/profile", "/static/",
    "/health", "/docs", "/openapi.json", "/assets/", "/icons/",
    "/fonts/", "/robots.txt", "/sitemap",
)

_VALID_PAGE_TYPES = {"notes", "definition", "important-questions", "mcqs", "examples"}

_bot_html_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=512, ttl=3600)


def _bot_html_response(html: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content=html, status_code=200,
        headers={
            "Cache-Control": "public, max-age=3600, s-maxage=86400",
            "X-Bot-Rendered": "1",
            "Vary": "User-Agent",
        },
    )


class BotRenderMiddleware(BaseHTTPMiddleware):
    """Intercept requests from bot user-agents and return pre-rendered HTML.

    Handles:
    - /                                  → homepage
    - /library                           → homepage (same listing)
    - /pyq/{slug}                        → PYQ HTML replica (html only)
    - /{board}/{class}/{subject}         → subject landing page
    - /{board}/{class}/{subject}/{topic}      → topic page (notes)
    - /{board}/{class}/{subject}/{topic}/{type} → topic page (typed)
    """

    async def _safe_call_next(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            logger.warning(f"BotRenderMiddleware downstream error: {exc}")
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    async def dispatch(self, request: StarletteRequest, call_next):
        ua = request.headers.get("user-agent", "")
        if not _BOT_UA_RE.search(ua):
            return await self._safe_call_next(request, call_next)

        path = request.url.path.rstrip("/") or "/"
        for prefix in _BOT_SKIP_PREFIXES:
            if path.startswith(prefix):
                return await self._safe_call_next(request, call_next)

        if "." in path.split("/")[-1]:
            return await self._safe_call_next(request, call_next)

        parts = [p for p in path.split("/") if p]
        n = len(parts)

        if n == 0 or (n == 1 and parts[0] == "library"):
            cache_key = "_homepage_"
        elif n == 2 and parts[0] == "pyq":
            cache_key = f"_pyq_/{parts[1]}"
        elif n == 3:
            cache_key = f"_subj_/{parts[0]}/{parts[1]}/{parts[2]}"
        elif n in (4, 5):
            page_type_part = parts[4] if n == 5 else None
            if page_type_part and page_type_part not in _VALID_PAGE_TYPES:
                return await self._safe_call_next(request, call_next)
            current_type = page_type_part or "notes"
            cache_key = f"{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/{current_type}"
        else:
            return await self._safe_call_next(request, call_next)

        cached_html = _bot_html_cache.get(cache_key)
        if cached_html:
            return _bot_html_response(cached_html)

        try:
            _seo_port = int(os.environ.get("PORT", "8000"))
            api_base = f"http://localhost:{_seo_port}/api/seo"

            if cache_key == "_homepage_":
                api_url = f"{api_base}/html/homepage"
            elif cache_key.startswith("_pyq_/"):
                slug = parts[1]
                api_url = f"http://localhost:{_seo_port}/api/pyq/{slug}"
            elif cache_key.startswith("_subj_/"):
                api_url = f"{api_base}/html/subject/{parts[0]}/{parts[1]}/{parts[2]}"
            else:
                current_type = parts[4] if n == 5 else "notes"
                api_url = f"{api_base}/html/{parts[0]}/{parts[1]}/{parts[2]}/{parts[3]}/{current_type}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                html_resp = await client.get(api_url)
            if html_resp.status_code != 200:
                return await self._safe_call_next(request, call_next)
            ct = html_resp.headers.get("content-type", "")
            if "text/html" not in ct and "text/xml" not in ct:
                return await self._safe_call_next(request, call_next)
            html_content = html_resp.text
            _bot_html_cache[cache_key] = html_content
            return _bot_html_response(html_content)
        except Exception as _bot_err:
            logger.debug(f"BotRenderMiddleware fallthrough: {_bot_err}")
            return await self._safe_call_next(request, call_next)


class CmsNoIndexMiddleware(BaseHTTPMiddleware):
    """
    Hard scraper block for all /cms/{user_id}/* routes.
    - Adds X-Robots-Tag: noindex, nofollow on every CMS response.
    - Adds Cache-Control: private, no-store on every CMS response.
    - Blocks known scraper/bot user-agents with 403.
    Outbound web-search calls are structurally impossible in CMS handlers
    (they only call call_slm / MongoDB). This middleware provides defence-in-depth.
    """
    _CMS_BOT_UA_RE = re.compile(
        r"scrapy|wget|curl|python-requests|go-http-client|java/|"
        r"ahrefsbot|semrushbot|gptbot|claudebot|perplexitybot|"
        r"bingbot|googlebot|yandexbot|duckduckbot",
        re.IGNORECASE,
    )
    _CMS_PUBLIC_PATHS = ("/api/cms/posts", "/api/cms/post/")

    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if not path.startswith("/api/cms/"):
            return await call_next(request)
        if any(path.startswith(p) for p in self._CMS_PUBLIC_PATHS):
            return await call_next(request)
        ua = request.headers.get("user-agent", "")
        if ua and self._CMS_BOT_UA_RE.search(ua):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Automated access to personalized content is not permitted."},
                headers={
                    "X-Robots-Tag": "noindex, nofollow",
                    "Cache-Control": "private, no-store",
                },
            )
        # Set CMS context flag so that web-search/scrape functions raise 403 if called
        token = _cms_request_ctx.set(True)
        try:
            response = await call_next(request)
        finally:
            _cms_request_ctx.reset(token)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "private, no-store"
        return response






# ─────────────────────────────────────────────
# PHASE A: ENHANCED DASHBOARD METRICS
# ─────────────────────────────────────────────
@router.get("/admin/dashboard/metrics")
async def admin_dashboard_metrics(admin: dict = Depends(get_admin_user)):
    start = time.time()
    health_data = {}
    try:
        # Use the background-warmed cache if it is fresh (≤ 30 s old).
        # This avoids the 500 ms+ Supabase round-trip on every dashboard load.
        cache_age = time.time() - _health_deps_cache_at
        if _health_deps_cache and cache_age < _HEALTH_CACHE_TTL_S:
            h_resp = _health_deps_cache
        else:
            # Cache is cold (first load or stale) — fetch live with a 5 s guard
            h_resp = await asyncio.wait_for(_check_health_deps(), timeout=5)
        health_data = h_resp if isinstance(h_resp, dict) else {}
    except Exception:
        pass

    deps_status = {}
    if isinstance(health_data, dict):
        for k, v in health_data.items():
            if isinstance(v, dict):
                deps_status[k] = {
                    "status": v.get("status", "unknown"),
                    "latency_ms": v.get("latencyMs", 0),
                }

    users = await supa_list_users()
    total_users = len(users)
    paid_users = sum(1 for u in users if u.get("plan") in ("starter", "pro"))
    free_users = total_users - paid_users

    payments = await db.payments.find({}, {"_id": 0}).sort("verified_at", -1).to_list(500)
    total_revenue_inr = sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe") / 100
    total_revenue_usd = sum(p.get("amount_cents", 0) for p in payments if p.get("provider") == "stripe") / 100

    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    recent_payments = [p for p in payments if p.get("verified_at", "") >= thirty_days_ago]
    mrr_inr = sum(p.get("amount_paise", 0) for p in recent_payments if p.get("provider") != "stripe") / 100

    seo_count = await db.seo_topics.count_documents({}) if await is_mongo_available() else 0
    seo_published = await db.seo_pages.count_documents({"status": "published"}) if await is_mongo_available() else 0

    elapsed = round((time.time() - start) * 1000, 1)

    return {
        "dependencies": deps_status,
        "response_time_ms": elapsed,
        "users": {"total": total_users, "paid": paid_users, "free": free_users},
        "revenue": {"total_inr": total_revenue_inr, "total_usd": total_revenue_usd, "mrr_inr": mrr_inr},
        "seo": {"topics": seo_count, "published_pages": seo_published},
        "payments_count": len(payments),
    }



# Admin endpoints for alert management
@router.get("/admin/alerts")
async def admin_list_alerts(limit: int = 50, admin: dict = Depends(get_admin_user)):
    """List recent alerts."""
    items = await db.alerts.find({}).sort("fired_at", -1).limit(limit).to_list(limit)
    for i in items:
        i["id"] = str(i.pop("_id"))
    return {"alerts": items, "thresholds": _ALERT_THRESHOLDS}

@router.patch("/admin/alerts/{alert_id}/acknowledge")
async def admin_acknowledge_alert(alert_id: str, admin: dict = Depends(get_admin_user)):
    from bson import ObjectId as _ObjId
    try:
        oid = _ObjId(alert_id)
    except Exception:
        raise HTTPException(400, "Invalid alert_id")
    await db.alerts.update_one({"_id": oid}, {"$set": {"acknowledged": True}})
    return {"ok": True}

@router.put("/admin/alerts/thresholds")
async def admin_update_alert_thresholds(data: dict, admin: dict = Depends(get_admin_user)):
    """Update alert thresholds at runtime. Keys: latency_p95_ms, error_rate_pct, fallback_rate_pct."""
    for key in ("latency_p95_ms", "error_rate_pct", "fallback_rate_pct"):
        if key in data:
            _ALERT_THRESHOLDS[key] = float(data[key])
    return {"thresholds": _ALERT_THRESHOLDS}


# ─────────────────────────────────────────────
# PHASE B: AI CONTENT STUDIO
# ─────────────────────────────────────────────
class StudioParseRequest(BaseModel):
    raw_text: str
    subject: str = ""
    chapter: str = ""

@router.post("/admin/studio/parse")
async def admin_studio_parse(body: StudioParseRequest, admin: dict = Depends(get_admin_user)):
    if not body.raw_text.strip():
        raise HTTPException(400, "Empty text")
    prompt = f"""You are an educational content parser and GEO (Generative Engine Optimization) specialist for AssamBoard students (AHSEC, DEGREE, SEBA) in Assam.
Analyze the following raw educational text and categorize it into structured blocks.
Return a JSON array of blocks, each with: type (one of: "summary", "definition", "example", "pyq", "formula", "note", "faq"), title, content.

GEO REQUIREMENTS — weave these naturally into every block:
- Cite AHSEC board exam frequency (e.g. "Asked in AHSEC 2019, 2021, 2023")
- Include authoritative references (textbook name, author, page when available)
- Add "According to the AHSEC syllabus..." or "As per NCERT..." framing
- For definitions, start with the canonical textbook wording
- For PYQ blocks, note mark allocation and year
- Generate 1-2 FAQ blocks with question+answer pairs students commonly search for

Subject: {body.subject or 'General'}
Chapter: {body.chapter or 'General'}

Raw text:
---
{body.raw_text[:8000]}
---

Return ONLY valid JSON array. Example:
[{{"type":"summary","title":"Chapter Overview","content":"..."}},{{"type":"definition","title":"Term Name","content":"..."}},{{"type":"faq","title":"FAQ: What is...?","content":"Q: What is...?\\nA: According to NCERT, ..."}}]"""

    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=4096)
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            blocks = json.loads(json_match.group())
            return {"blocks": blocks, "raw_length": len(body.raw_text), "block_count": len(blocks)}
        return {"blocks": [{"type": "note", "title": "Parsed Content", "content": result}], "raw_length": len(body.raw_text), "block_count": 1}
    except Exception as e:
        logger.error(f"Studio parse error: {e}")
        raise HTTPException(500, "AI parsing failed")

class StudioPublishRequest(BaseModel):
    title: str
    slug: str
    blocks: list
    subject_id: str = ""
    chapter_id: str = ""
    board: str = "ahsec"
    class_slug: str = "class-12"
    subject_slug: str = ""
    meta_description: str = ""
    keywords: list = []
    board_id: str = ""
    class_id: str = ""
    stream_id: str = ""
    is_revision: bool = False
    parent_revision_id: str = ""


@router.post("/admin/studio/publish")
async def admin_studio_publish(body: StudioPublishRequest, admin: dict = Depends(get_admin_user)):
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. Resolve board / class slugs from DB if IDs supplied ────────────────
    board_slug = body.board
    class_slug_resolved = body.class_slug
    if body.board_id:
        bd = await db.boards.find_one({"id": body.board_id}, {"_id": 0})
        if bd:
            board_slug = bd.get("slug") or _slugify(bd.get("name", body.board))
    if body.class_id:
        cd = await db.classes.find_one({"id": body.class_id}, {"_id": 0})
        if cd:
            class_slug_resolved = cd.get("slug") or _slugify(cd.get("name", body.class_slug))

    subject_slug_resolved = body.subject_slug or body.slug.split("-")[0]
    publish_url = f"/{board_slug}/{class_slug_resolved}/{subject_slug_resolved}/{body.slug}"

    # ── 2. Build HTML from blocks ──────────────────────────────────────────────
    html_parts = []
    for block in body.blocks:
        btype = re.sub(r'[^a-z]', '', block.get("type", "note"))
        btitle  = _html_mod.escape(str(block.get("title", "")))
        bcontent = _html_mod.escape(str(block.get("content", "")))
        html_parts.append(f'<section class="content-block {btype}"><h3>{btitle}</h3><div>{bcontent}</div></section>')
    page_html = "\n".join(html_parts)

    # ── 3. Upsert SEO topic ────────────────────────────────────────────────────
    topic_doc = {
        "title": body.title,
        "slug": body.slug,
        "board": board_slug,
        "class_slug": class_slug_resolved,
        "subject_slug": subject_slug_resolved,
        "meta_description": body.meta_description or body.title,
        "keywords": body.keywords,
        "status": "published",
        "board_id": body.board_id,
        "class_id": body.class_id,
        "stream_id": body.stream_id,
        "updated_at": now_iso,
        "source": "studio",
    }
    # Persist subject_id and chapter_id linkage when provided — required for
    # SEO topic → chapter cross-linking and AI chat source navigation.
    if body.subject_id:
        topic_doc["subject_id"] = body.subject_id
    if hasattr(body, "chapter_id") and body.chapter_id:
        topic_doc["chapter_id"] = body.chapter_id
    existing_topic = await db.seo_topics.find_one({"slug": body.slug}, {"_id": 0, "created_at": 1})
    if not existing_topic:
        topic_doc["created_at"] = now_iso
    await db.seo_topics.update_one({"slug": body.slug}, {"$set": topic_doc}, upsert=True)

    # ── 4. Upsert SEO page (or create revision copy) ───────────────────────────
    page_doc = {
        "topic_slug": body.slug,
        "board": board_slug,
        "class_slug": class_slug_resolved,
        "subject_slug": subject_slug_resolved,
        "html": page_html,
        "blocks": body.blocks,
        "status": "published",
        "page_type": "notes",
        "updated_at": now_iso,
        "source": "studio",
    }
    if body.is_revision and body.parent_revision_id:
        from datetime import date as _date
        rev_slug = f"{body.slug}-rev-{_date.today().isoformat()}"
        revision_doc = {
            **page_doc,
            "topic_slug": rev_slug,
            "is_revision": True,
            "parent_revision_id": body.parent_revision_id,
            "created_at": now_iso,
        }
        await db.seo_pages.insert_one(revision_doc)
        logger.info(f"Studio revision created: {rev_slug} ← {body.parent_revision_id}")
    else:
        existing_page = await db.seo_pages.find_one({"topic_slug": body.slug, "page_type": "notes"}, {"_id": 0, "created_at": 1})
        if not existing_page:
            page_doc["created_at"] = now_iso
        await db.seo_pages.update_one(
            {"topic_slug": body.slug, "page_type": "notes"},
            {"$set": page_doc},
            upsert=True,
        )

    # ── 4b. Embed page for vector search ─────────────────────────────────────
    # Run fire-and-forget so publish response is never delayed by embedding
    _embed_content = " ".join(
        (b.get("content") or b.get("text") or "")
        for b in (body.blocks or []) if isinstance(b, dict)
    )
    if not _embed_content:
        _embed_content = body.title or ""
    asyncio.create_task(_embed_and_store_page(body.slug, _embed_content))

    # ── 5. Auto-create syllabus CMS stub when syllabus block detected ──────────
    syllabus_block = next((b for b in body.blocks if b.get("type") == "syllabus"), None)
    if syllabus_block and body.subject_id:
        syl_title = f"{body.title} — Syllabus Scope"
        syl_slug  = f"{body.slug}-syllabus"
        syl_id    = str(uuid.uuid4())
        syl_doc = {
            "id":               syl_id,
            "title":            syl_title,
            "seo_slug":         syl_slug,
            "content":          syllabus_block.get("content", ""),
            "type":             "syllabus",
            "status":           "draft",
            "linked_subject_id": body.subject_id,
            "linked_board_id":  body.board_id,
            "linked_class_id":  body.class_id,
            "linked_stream_id": body.stream_id,
            "source":           "studio-auto",
            "created_at":       now_iso,
            "updated_at":       now_iso,
        }
        await db.cms_documents.update_one(
            {"seo_slug": syl_slug},
            {"$set": syl_doc},
            upsert=True,
        )
        logger.info(f"Syllabus CMS stub auto-created: {syl_slug}")

    logger.info(f"Studio published: {body.slug} → {publish_url}")
    return {"success": True, "slug": body.slug, "url": publish_url}


# ── SEO / GEO Metadata Generator ──────────────────────────────────────────────

@router.post("/admin/seo/generate")
async def generate_seo_metadata(data: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Generate syllabus-anchored, thick-page SEO + GEO metadata using AI."""
    title          = (data.get("title") or "").strip()
    content_snippet= (data.get("content") or "")[:3000].strip()
    primary_keyword= (data.get("primary_keyword") or "").strip()
    seo_tags       = (data.get("seo_tags") or "").strip()
    linked_scope   = (data.get("linked_scope") or "").strip()
    board          = (data.get("board") or "Assamboard").strip()
    class_name     = (data.get("class_name") or "").strip()
    subject        = (data.get("subject") or "").strip()

    prompt = f"""You are an expert SEO + GEO (Generative Engine Optimization) strategist for Syrabit.ai, the educational browser for Assamboard students (AHSEC Class 11-12, SEBA, Degree: B.Com/B.A/B.Sc) in Assam, India.

GOAL: Generate high-impact, syllabus-anchored SEO & GEO metadata. Every page must be THICK and authoritative — no thin pages. One page should comprehensively cover one syllabus topic with notes + definitions + PYQ patterns + solved examples + MCQs so it ranks as the single best result for that topic.

Page context:
- Title/Topic:       {title or '(not set)'}
- Primary Keyword:   {primary_keyword or '(derive from topic)'}
- Subject/Chapter:   {subject or '(educational content)'}
- Board:             {board}
- Class:             {class_name or '(not specified)'}
- Syllabus scope:    {linked_scope or '(not linked)'}
- Existing tags:     {seo_tags or '(none)'}
- Content snippet:   {content_snippet[:600] or '(not provided)'}

BRAND RULE: Use "Assamboard" (one word, capital A) as the primary brand term in titles and descriptions. Use "AHSEC" / "SEBA" / "Degree" only as secondary qualifiers for search matching.

Rules for SEO Title (55-65 characters):
- Primary keyword FIRST — match exactly what Assam students search
- Include "Assamboard" as the board identifier
- Include content depth signal: "Complete Notes" / "Full Chapter" / "Solved PYQ" / "Detailed Guide"
- Power word: Complete, Free, Detailed, Solved, Official, Comprehensive
- End exactly with " | Syrabit"
- Total: 55-65 characters, never truncated by Google
- Example: "Photosynthesis Complete Notes Assamboard Class 12 | Syrabit"

Rules for Meta Description (148-158 characters):
- Open with the primary syllabus topic + what the page covers comprehensively
- Signal page depth: "covers definitions, derivations, solved PYQ, MCQs, and board exam tips"
- Include authority signal: "per Assamboard syllabus" or "NCERT + Assamboard aligned"
- End with CTA: "Free on Syrabit." or "Study free on Syrabit."
- 148-158 characters EXACTLY (count carefully)

Rules for Primary Keyword (4-7 words):
- Exact-match what Assam students type in Google
- Format: "[topic] [subject] Assamboard [class] notes" or "[topic] class 12 Assamboard notes"
- Must be syllabus-anchored — the topic must exist in the official syllabus

Rules for SEO Tags (8-12 comma-separated):
- Mix: syllabus topic exact match, "Assamboard [subject] notes", "[topic] class [X]", "[topic] PYQ", "[topic] MCQ", "Assam board exam", long-tail question variants
- Always include: Assamboard, the class, the subject, "notes", "Assam"

Rules for GEO Authority Phrases (3 phrases for AI citation):
- Must sound like authoritative syllabus citations an AI engine would quote
- Reference real curriculum sources: "As per Assamboard {class_name or ''} syllabus 2024-25", "According to NCERT/SCERT Assam prescribed textbook", "Based on AHSEC board exam pattern analysis"
- These phrases get embedded in content for Perplexity/ChatGPT citation eligibility

Rules for Schema Type:
- "Article" for chapter notes/guides
- "FAQPage" for PYQ/FAQ-heavy pages
- "HowTo" for step-by-step derivations/solved problems
- "Course" for full subject overview pages
- Choose the BEST fit based on content type

Return ONLY valid JSON — no markdown fences, no commentary:
{{"seo_title":"...","meta_description":"...","primary_keyword":"...","seo_tags":"tag1, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9, tag10","geo_phrases":["...","...","..."],"schema_type":"Article","char_counts":{{"title":0,"meta":0}}}}"""

    try:
        result = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=700)
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON in LLM response")
        obj = json.loads(json_match.group())
        # Enforce hard limits
        seo_title = (obj.get("seo_title") or title or "Educational Notes | Syrabit")[:70]
        meta_desc = (obj.get("meta_description") or "")[:160]
        obj["seo_title"]       = seo_title
        obj["meta_description"]= meta_desc
        obj["char_counts"]     = {"title": len(seo_title), "meta": len(meta_desc)}
        logger.info(f"SEO generate: title={len(seo_title)}ch meta={len(meta_desc)}ch")
        return obj
    except Exception as e:
        logger.error(f"SEO generate error: {e}")
        raise HTTPException(500, "AI SEO generation failed — check logs")


# ── Studio Draft CRUD ─────────────────────────────────────────────────────────

@router.get("/admin/studio/drafts")
async def list_studio_drafts(admin: dict = Depends(get_admin_user)):
    """List all studio drafts, newest first."""
    drafts = await db.studio_drafts.find({}, {"_id": 0}).sort("updated_at", -1).limit(50).to_list(50)
    return drafts


@router.post("/admin/studio/drafts")
async def save_studio_draft(data: dict = Body(...), admin: dict = Depends(get_admin_user)):
    """Save or update a studio draft by slug."""
    slug = data.get("slug", "").strip()
    draft_id = data.get("id") or str(uuid.uuid4())
    now_iso  = datetime.now(timezone.utc).isoformat()
    draft = {
        "id":           draft_id,
        "title":        data.get("title", "Untitled"),
        "slug":         slug,
        "blocks":       data.get("blocks", []),
        "subject_id":   data.get("subject_id", ""),
        "board_id":     data.get("board_id", ""),
        "class_id":     data.get("class_id", ""),
        "stream_id":    data.get("stream_id", ""),
        "subject_slug": data.get("subject_slug", ""),
        "updated_at":   now_iso,
    }
    existing = await db.studio_drafts.find_one({"slug": slug} if slug else {"id": draft_id}, {"_id": 0, "created_at": 1})
    if not existing:
        draft["created_at"] = now_iso
    filter_q = {"slug": slug} if slug else {"id": draft_id}
    await db.studio_drafts.update_one(filter_q, {"$set": draft}, upsert=True)
    logger.info(f"Studio draft saved: {draft_id} ({slug})")
    return {"id": draft_id, "message": "Draft saved"}


@router.delete("/admin/studio/drafts/{draft_id}")
async def delete_studio_draft(draft_id: str, admin: dict = Depends(get_admin_user)):
    await db.studio_drafts.delete_one({"id": draft_id})
    return {"message": "Draft deleted"}


@router.post("/admin/studio/drafts/{draft_id}/publish")
async def publish_studio_draft(draft_id: str, data: dict = Body(default={}), admin: dict = Depends(get_admin_user)):
    """Publish a saved draft. Optional body overrides: board_id, class_id, is_revision, parent_revision_id."""
    draft = await db.studio_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    pub_body = StudioPublishRequest(
        title            = draft.get("title", "Untitled"),
        slug             = draft.get("slug", draft_id),
        blocks           = draft.get("blocks", []),
        subject_id       = draft.get("subject_id", ""),
        board_id         = data.get("board_id", draft.get("board_id", "")),
        class_id         = data.get("class_id", draft.get("class_id", "")),
        stream_id        = data.get("stream_id", draft.get("stream_id", "")),
        subject_slug     = draft.get("subject_slug", ""),
        is_revision      = data.get("is_revision", False),
        parent_revision_id = data.get("parent_revision_id", ""),
    )
    result = await admin_studio_publish(pub_body, admin)
    await db.studio_drafts.update_one({"id": draft_id}, {"$set": {"last_published_at": datetime.now(timezone.utc).isoformat()}})
    return {**result, "draft_id": draft_id}


# ─────────────────────────────────────────────
# PHASE C: ADVANCED ANALYTICS
# ─────────────────────────────────────────────
@router.get("/admin/analytics/funnel")
async def admin_analytics_funnel(admin: dict = Depends(get_admin_user)):
    users = await supa_list_users()
    total = len(users)
    chatted = 0
    paid = 0
    for u in users:
        if u.get("credits_used", 0) > 0:
            chatted += 1
        if u.get("plan") in ("starter", "pro"):
            paid += 1

    payments = await db.payments.find({}, {"_id": 0}).to_list(5000)
    total_revenue = sum(p.get("amount_paise", 0) for p in payments if p.get("provider") != "stripe") / 100

    return {
        "funnel": [
            {"stage": "Signed Up", "count": total, "pct": 100},
            {"stage": "Used Chat", "count": chatted, "pct": round(chatted / max(total, 1) * 100, 1)},
            {"stage": "Paid User", "count": paid, "pct": round(paid / max(total, 1) * 100, 1)},
        ],
        "revenue_per_user": round(total_revenue / max(paid, 1), 2),
        "conversion_rate": round(paid / max(total, 1) * 100, 2),
    }

@router.get("/admin/analytics/content-heatmap")
async def admin_analytics_content_heatmap(admin: dict = Depends(get_admin_user)):
    pipeline = [
        {"$group": {"_id": "$subject_name", "views": {"$sum": 1}}},
        {"$sort": {"views": -1}},
        {"$limit": 30},
    ]
    try:
        results = await db.analytics.aggregate(pipeline).to_list(30)
    except Exception:
        results = []

    top_searches = []
    try:
        search_pipeline = [
            {"$match": {"type": "search"}},
            {"$group": {"_id": "$query", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]
        top_searches = await db.analytics.aggregate(search_pipeline).to_list(20)
    except Exception:
        pass

    return {
        "top_subjects": [{"name": r["_id"] or "Unknown", "views": r["views"]} for r in results if r["_id"]],
        "top_searches": [{"query": r["_id"] or "Unknown", "count": r["count"]} for r in top_searches if r["_id"]],
    }

@router.get("/admin/analytics/revenue")
async def admin_analytics_revenue(days: int = 30, admin: dict = Depends(get_admin_user)):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    payments = await db.payments.find(
        {"verified_at": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("verified_at", 1).to_list(5000)

    daily = {}
    for p in payments:
        day = p.get("verified_at", "")[:10]
        if not day:
            continue
        if day not in daily:
            daily[day] = {"date": day, "revenue_inr": 0, "count": 0}
        daily[day]["revenue_inr"] += p.get("amount_paise", 0) / 100
        daily[day]["count"] += 1

    users = await supa_list_users()
    cohorts = {"free": 0, "starter": 0, "pro": 0}
    for u in users:
        plan = u.get("plan", "free")
        cohorts[plan] = cohorts.get(plan, 0) + 1

    return {
        "daily_revenue": sorted(daily.values(), key=lambda x: x["date"]),
        "cohorts": cohorts,
        "total_payments": len(payments),
    }

@router.get("/admin/analytics/predictor")
async def admin_analytics_predictor(admin: dict = Depends(get_admin_user)):
    now = datetime.now(timezone.utc)
    thirty_ago = (now - timedelta(days=30)).isoformat()
    sixty_ago = (now - timedelta(days=60)).isoformat()

    recent = await db.payments.count_documents({"verified_at": {"$gte": thirty_ago}})
    prior = await db.payments.count_documents({"verified_at": {"$gte": sixty_ago, "$lt": thirty_ago}})

    recent_rev = 0
    async for p in db.payments.find({"verified_at": {"$gte": thirty_ago}}, {"_id": 0}):
        recent_rev += p.get("amount_paise", 0) / 100

    growth_rate = ((recent - prior) / max(prior, 1)) if prior > 0 else 0
    predicted_mrr = round(recent_rev * (1 + growth_rate * 0.5), 2)

    users_this_month = await db.users.count_documents({"created_at": {"$gte": thirty_ago}})
    users_last_month = await db.users.count_documents({"created_at": {"$gte": sixty_ago, "$lt": thirty_ago}})

    return {
        "current_mrr_inr": recent_rev,
        "predicted_mrr_inr": predicted_mrr,
        "growth_rate_pct": round(growth_rate * 100, 1),
        "payments_this_month": recent,
        "payments_last_month": prior,
        "signups_this_month": users_this_month,
        "signups_last_month": users_last_month,
    }


@router.get("/admin/analytics/daily")
async def admin_analytics_daily(
    days: int = 30,
    admin: dict = Depends(get_admin_user),
):
    """
    Per-day analytics for the Daily Analytics panel.
    Returns visitors, page_views, signups, messages, and AI interactions
    for each day in the requested range (default: last 30 days).
    Prefers GA4 for visitor/page-view data and falls back to MongoDB.
    """
    now = datetime.now(timezone.utc)

    # Build a lookup dict indexed by YYYY-MM-DD for easy merging
    day_keys = [(now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d") for i in range(days)]
    daily: dict[str, dict] = {
        d: {
            "date": d,
            "visitors": 0,
            "page_views": 0,
            "signups": 0,
            "messages": 0,
            "ai_interactions": 0,
            "sessions": 0,
            "bounce_rate": None,
            "avg_session_duration": None,
        }
        for d in day_keys
    }

    # ── 1. Visitor / page-view data ──────────────────────────────────────────
    # Try GA4 first
    try:
        ga4_resp = await ga4_client.run_report(
            dimensions=["date"],
            metrics=["activeUsers", "screenPageViews", "sessions", "bounceRate", "averageSessionDuration"],
            date_ranges=[{"startDate": f"{days}daysAgo", "endDate": "today"}],
            order_bys=[{"dimension": {"dimensionName": "date"}}],
            limit=days + 1,
        )
        if ga4_resp and ga4_resp.get("rows"):
            for row in ga4_resp["rows"]:
                raw_date = row["dimensionValues"][0]["value"]
                d = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
                if d in daily:
                    mv = row["metricValues"]
                    daily[d]["visitors"] = int(mv[0]["value"]) if mv[0]["value"] else 0
                    daily[d]["page_views"] = int(mv[1]["value"]) if mv[1]["value"] else 0
                    daily[d]["sessions"] = int(mv[2]["value"]) if mv[2]["value"] else 0
                    try:
                        daily[d]["bounce_rate"] = round(float(mv[3]["value"]) * 100, 1)
                    except Exception:
                        pass
                    try:
                        daily[d]["avg_session_duration"] = round(float(mv[4]["value"]), 1)
                    except Exception:
                        pass
    except Exception:
        # Fall back to MongoDB page_views collection
        try:
            cutoff_str = day_keys[0]
            pipeline = [
                {"$match": {"date": {"$gte": cutoff_str}}},
                {
                    "$group": {
                        "_id": "$date",
                        "visitors": {"$addToSet": "$visitor_id"},
                        "page_views": {"$sum": 1},
                    }
                },
            ]
            rows = await db.page_views.aggregate(pipeline).to_list(days + 5)
            for row in rows:
                d = row["_id"]
                if d in daily:
                    daily[d]["visitors"] = len(row["visitors"])
                    daily[d]["page_views"] = row["page_views"]
        except Exception:
            pass

    # ── 2. Signups (Supabase users by created_at date) ───────────────────────
    try:
        users = await supa_list_users()
        for u in users:
            d = (u.get("created_at") or "")[:10]
            if d in daily:
                daily[d]["signups"] += 1
    except Exception:
        pass

    # ── 3. Messages (conversations collection) ──────────────────────────────
    try:
        cutoff_dt = (now - timedelta(days=days)).isoformat()
        pipeline_msgs = [
            {"$match": {"created_at": {"$gte": cutoff_dt}}},
            {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "count": {"$sum": "$message_count"}}},
        ]
        msg_rows = await db.conversations.aggregate(pipeline_msgs).to_list(days + 5)
        for row in msg_rows:
            d = row["_id"]
            if d in daily:
                daily[d]["messages"] = row["count"] or 0
    except Exception:
        pass

    # ── 4. AI interactions (analytics events of type ask_ai_click) ───────────
    try:
        cutoff_dt = (now - timedelta(days=days)).isoformat()
        pipeline_ai = [
            {"$match": {"type": "ask_ai_click", "created_at": {"$gte": cutoff_dt}}},
            {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "count": {"$sum": 1}}},
        ]
        ai_rows = await db.analytics.aggregate(pipeline_ai).to_list(days + 5)
        for row in ai_rows:
            d = row["_id"]
            if d in daily:
                daily[d]["ai_interactions"] = row["count"]
    except Exception:
        pass

    result = sorted(daily.values(), key=lambda x: x["date"])

    # Compute day-over-day deltas for summary cards (last day vs second-to-last)
    def pct_change(a, b):
        if b == 0:
            return None
        return round((a - b) / b * 100, 1)

    today_data = result[-1] if result else {}
    prev_data = result[-2] if len(result) >= 2 else {}

    summary = {
        "visitors": {
            "today": today_data.get("visitors", 0),
            "change_pct": pct_change(today_data.get("visitors", 0), prev_data.get("visitors", 0)),
        },
        "page_views": {
            "today": today_data.get("page_views", 0),
            "change_pct": pct_change(today_data.get("page_views", 0), prev_data.get("page_views", 0)),
        },
        "signups": {
            "today": today_data.get("signups", 0),
            "change_pct": pct_change(today_data.get("signups", 0), prev_data.get("signups", 0)),
        },
        "messages": {
            "today": today_data.get("messages", 0),
            "change_pct": pct_change(today_data.get("messages", 0), prev_data.get("messages", 0)),
        },
        "ai_interactions": {
            "today": today_data.get("ai_interactions", 0),
            "change_pct": pct_change(today_data.get("ai_interactions", 0), prev_data.get("ai_interactions", 0)),
        },
    }

    return {"daily": result, "summary": summary, "days": days}


# ─────────────────────────────────────────────
# GOOGLE ANALYTICS 4 OAUTH SETUP
# ─────────────────────────────────────────────
@router.get("/admin/ga4/status")
async def ga4_status(admin: dict = Depends(get_admin_user)):
    token_env = os.getenv("GA4_REFRESH_TOKEN", "")
    # Also check db.api_config in case token was persisted there
    token_db = ""
    try:
        cfg = await db.api_config.find_one({}, {"ga4": 1})
        token_db = (cfg or {}).get("ga4", {}).get("refresh_token", "")
    except Exception:
        pass
    connected = bool(token_env or token_db)
    return {
        "connected": connected,
        "token_source": "env" if token_env else ("db" if token_db else "none"),
        "property_id": os.getenv("GA4_PROPERTY_ID", ""),
        "client_id_set": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")),
        "client_secret_set": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
    }


@router.get("/admin/ga4/auth-url")
async def ga4_auth_url(redirect_uri: str, admin: dict = Depends(get_admin_user)):
    url = ga4_client.get_oauth_url(redirect_uri)
    return {"url": url}


@router.post("/admin/ga4/connect")
async def ga4_connect(
    code: str = Body(...),
    redirect_uri: str = Body(...),
    admin: dict = Depends(get_admin_user),
):
    tokens = await ga4_client.exchange_code_for_tokens(code, redirect_uri)
    if not tokens or "refresh_token" not in tokens:
        raise HTTPException(status_code=400, detail="Failed to exchange code — ensure you selected the correct Google account with GA4 access and that you clicked 'Allow'.")
    refresh_token = tokens["refresh_token"]
    # Persist to MongoDB so it survives process restarts
    await db.api_config.update_one({}, {"$set": {"ga4.refresh_token": refresh_token}}, upsert=True)
    # Also update current process env so GA4 works immediately without restart
    os.environ["GA4_REFRESH_TOKEN"] = refresh_token
    ga4_client._db_token_cache["token"] = refresh_token
    ga4_client._db_token_cache["loaded"] = True
    logger.info("GA4 refresh token stored in db.api_config and os.environ")
    return {
        "status": "connected",
        "message": "GA4 connected. Token persisted to database — no Replit Secret needed.",
    }


@router.get("/admin/ga4/test")
async def ga4_test(admin: dict = Depends(get_admin_user)):
    stats = await ga4_client.get_visitor_stats_ga4(days=7)
    if stats is None:
        return {"ok": False, "reason": "GA4 not configured or refresh token missing"}
    return {"ok": True, "stats": stats}


# ─────────────────────────────────────────────
# VERTEX AI / GEMINI POWERED SERVICES
# ─────────────────────────────────────────────

@router.get("/admin/vertex/health")
async def vertex_health(admin: dict = Depends(get_admin_user)):
    """Check status of all Vertex AI / Gemini services."""
    return await vertex_services.health_check()


@router.post("/admin/vertex/translate")
async def vertex_translate(
    text: str = Body(...),
    target_lang: str = Body("as"),
    source_lang: str = Body("en"),
    admin: dict = Depends(get_admin_user),
):
    """Translate educational content to Assamese or other regional languages."""
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    result = await vertex_services.translate(text, target_lang=target_lang, source_lang=source_lang)
    if result is None:
        raise HTTPException(status_code=503, detail="Translation failed — check GEMINI_API_KEY")
    return {"translated": result, "target_lang": target_lang, "source_lang": source_lang}


@router.post("/admin/vertex/semantic-search")
async def vertex_semantic_search(
    query: str = Body(...),
    top_k: int = Body(10),
    admin: dict = Depends(get_admin_user),
):
    """Semantic search across all published SEO topics using text embeddings."""
    topics = await db.seo_topics.find(
        {}, {"_id": 0, "slug": 1, "title": 1, "subject_name": 1, "class_name": 1, "status": 1}
    ).to_list(5000)
    results = await vertex_services.semantic_search(query, topics, text_key="title", top_k=top_k)
    return {"query": query, "results": results, "total_searched": len(topics)}


@router.post("/admin/vertex/enhance")
async def vertex_enhance_content(
    content: str = Body(...),
    page_type: str = Body("notes"),
    subject: str = Body(""),
    topic: str = Body(""),
    class_name: str = Body("Class 11"),
    admin: dict = Depends(get_admin_user),
):
    """Improve AI-generated content with Gemini."""
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    enhanced = await vertex_services.enhance_content(content, page_type, subject, topic, class_name)
    if enhanced is None:
        raise HTTPException(status_code=503, detail="Enhancement failed")
    return {"enhanced": enhanced, "original_length": len(content), "enhanced_length": len(enhanced)}


@router.post("/admin/vertex/quality-score")
async def vertex_quality_score(
    content: str = Body(...),
    page_type: str = Body("notes"),
    topic: str = Body(""),
    subject: str = Body(""),
    admin: dict = Depends(get_admin_user),
):
    """Score the quality of educational content with Gemini."""
    return await vertex_services.score_content(content, page_type, topic, subject)


@router.post("/admin/vertex/suggest-topics")
async def vertex_suggest_topics(
    subject: str = Body(...),
    class_name: str = Body("Class 11"),
    board: str = Body("AHSEC"),
    admin: dict = Depends(get_admin_user),
):
    """Suggest missing high-value topics for a subject using AI."""
    existing = await db.seo_topics.distinct(
        "title",
        {"subject_name": subject, "class_name": class_name}
    )
    suggestions = await vertex_services.suggest_topics(subject, class_name, existing, board)
    return {"subject": subject, "class_name": class_name, "suggestions": suggestions, "existing_count": len(existing)}


@router.post("/admin/vertex/seo-meta")
async def vertex_seo_meta(
    topic: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    page_type: str = Body("notes"),
    board: str = Body("AHSEC"),
    content_preview: str = Body(""),
    admin: dict = Depends(get_admin_user),
):
    """Generate optimised SEO metadata (title, description, keywords, OG tags)."""
    meta = await vertex_services.generate_seo_meta(topic, subject, class_name, page_type, board, content_preview)
    if not meta:
        raise HTTPException(status_code=503, detail="SEO meta generation failed")
    return meta


@router.get("/admin/vertex/content-gaps")
async def vertex_content_gaps(admin: dict = Depends(get_admin_user)):
    """Identify high-value content gaps by cross-referencing searches with published content."""
    published = await db.seo_topics.distinct("slug", {"status": "published"})

    search_pipeline = [
        {"$match": {"type": "search"}},
        {"$group": {"_id": "$query", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 30},
    ]
    top_searches = []
    try:
        raw = await db.analytics.aggregate(search_pipeline).to_list(30)
        top_searches = [r["_id"] for r in raw if r.get("_id")]
    except Exception:
        pass

    subjects = await db.seo_topics.distinct("subject_name")
    gaps = await vertex_services.find_content_gaps(published, top_searches, subjects)
    return {"gaps": gaps, "published_count": len(published), "search_queries_analyzed": len(top_searches)}


@router.post("/admin/vertex/extract-document")
async def vertex_extract_document(
    file: UploadFile = File(...),
    task: str = "extract_topics",
    admin: dict = Depends(get_admin_user),
):
    """Extract structured data from PDF textbooks/question papers using Gemini 1.5 Pro."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > 20 * 1024 * 1024:  # 20MB limit
        raise HTTPException(status_code=400, detail="PDF too large — max 20MB")
    result = await vertex_services.extract_from_document(pdf_bytes, task=task)
    return result


@router.delete("/admin/syllabus/reset-all")
async def admin_syllabus_reset_all(admin: dict = Depends(get_admin_user)):
    """Wipe all subjects and chapters so a fresh syllabus can be uploaded."""
    sub_result = await db.subjects.delete_many({})
    ch_result  = await db.chapters.delete_many({})
    logger.info(f"Syllabus reset by {admin.get('email','?')} — deleted {sub_result.deleted_count} subjects, {ch_result.deleted_count} chapters")
    return {
        "deleted_subjects": sub_result.deleted_count,
        "deleted_chapters":  ch_result.deleted_count,
        "message": "All subjects and chapters cleared. Upload new syllabus via Admin → Syllabus Manager.",
    }


@router.post("/admin/vertex/ocr")
async def vertex_ocr(
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user),
):
    """Cloud Vision equivalent — extract text from AHSEC question paper/textbook images using Gemini Vision."""
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    ct = file.content_type or ""
    if ct not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ct}. Use JPEG, PNG, or WebP.")
    img_bytes = await file.read()
    if len(img_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large — max 10MB")
    result = await vertex_services.ocr_image(img_bytes, mime_type=ct)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.post("/admin/vertex/nlp-concepts")
async def vertex_nlp_concepts(
    text: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    admin: dict = Depends(get_admin_user),
):
    """Cloud Natural Language equivalent — extract key concepts, entities and difficulty from educational text."""
    if not text or len(text.strip()) < 50:
        raise HTTPException(status_code=400, detail="text must be at least 50 characters")
    result = await vertex_services.extract_key_concepts(text, subject=subject, class_name=class_name)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.post("/admin/vertex/flashcards")
async def vertex_flashcards(
    text: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    count: int = Body(10),
    admin: dict = Depends(get_admin_user),
):
    """Generate revision flashcards from chapter content for students."""
    if not text or len(text.strip()) < 100:
        raise HTTPException(status_code=400, detail="text must be at least 100 characters")
    count = max(5, min(count, 20))
    result = await vertex_services.generate_flashcards(text, subject=subject, count=count, class_name=class_name)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.post("/admin/vertex/mcq-generator")
async def vertex_mcq_generator(
    text: str = Body(...),
    subject: str = Body(""),
    class_name: str = Body("Class 11"),
    count: int = Body(10),
    difficulty: str = Body("mixed"),
    admin: dict = Depends(get_admin_user),
):
    """Generate AHSEC-pattern MCQ questions from chapter text."""
    if not text or len(text.strip()) < 100:
        raise HTTPException(status_code=400, detail="text must be at least 100 characters")
    count = max(5, min(count, 20))
    result = await vertex_services.generate_mcqs(text, subject=subject, class_name=class_name,
                                                  count=count, difficulty=difficulty)
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


# ─────────────────────────────────────────────
# PHASE D: AUTOMATION ENGINE
# ─────────────────────────────────────────────
@router.get("/admin/automation/insights")
async def admin_automation_insights(admin: dict = Depends(get_admin_user)):
    seo_topics = await db.seo_topics.find({}, {"_id": 0, "slug": 1, "title": 1, "status": 1}).to_list(5000)
    published_slugs = {t["slug"] for t in seo_topics if t.get("status") == "published"}

    chat_topics = []
    try:
        pipeline = [
            {"$unwind": "$messages"},
            {"$match": {"messages.role": "user"}},
            {"$group": {"_id": "$messages.content", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 50},
        ]
        chat_topics = await db.conversations.aggregate(pipeline).to_list(50)
    except Exception:
        pass

    content_gaps = []
    for ct in chat_topics[:20]:
        query = ct.get("_id", "")
        if query and len(query) > 10:
            slug_candidate = re.sub(r'[^a-z0-9]+', '-', query.lower().strip())[:60]
            if slug_candidate not in published_slugs:
                content_gaps.append({"query": query[:100], "count": ct["count"], "suggested_slug": slug_candidate})

    low_content_subjects = []
    try:
        subjects = await db.subjects.find({}, {"_id": 0, "name": 1, "id": 1}).to_list(100)
        for subj in subjects[:30]:
            topic_count = await db.seo_topics.count_documents({"subject_slug": {"$regex": re.sub(r'[^a-z0-9]+', '-', subj.get("name", "").lower())}})
            if topic_count < 3:
                low_content_subjects.append({"name": subj.get("name", ""), "id": subj.get("id", ""), "seo_pages": topic_count})
    except Exception:
        pass

    high_quality_chats = []
    try:
        qa_pipeline = [
            {"$unwind": "$messages"},
            {"$match": {"messages.role": "assistant"}},
            {"$project": {"content": "$messages.content", "msg_id": "$messages.id", "conv_id": "$_id"}},
            {"$match": {"content": {"$regex": ".{200,}"}}},
            {"$limit": 10},
        ]
        high_quality_chats = await db.conversations.aggregate(qa_pipeline).to_list(10)
    except Exception:
        pass

    return {
        "content_gaps": content_gaps[:15],
        "low_content_subjects": low_content_subjects[:10],
        "promotable_chats": len(high_quality_chats),
        "total_seo_topics": len(seo_topics),
        "published_count": len(published_slugs),
    }

@router.post("/admin/automation/auto-generate")
async def admin_automation_auto_generate(admin: dict = Depends(get_admin_user)):
    insights = await admin_automation_insights(admin)
    gaps = insights.get("content_gaps", [])[:5]
    generated = []
    for gap in gaps:
        slug = gap["suggested_slug"]
        title = gap["query"].title()
        now_iso = datetime.now(timezone.utc).isoformat()
        geo_meta = {
            "geo_source": "auto-generated from content gap",
            "geo_query_count": gap.get("count", 0),
            "geo_suggested_sections": [
                "Summary (cite AHSEC syllabus)",
                "Definition (NCERT/SCERT reference)",
                "Explanation (curriculum-aligned)",
                "PYQs (with year and marks)",
                "FAQs (3 common student questions)",
            ],
        }
        await db.seo_topics.update_one(
            {"slug": slug},
            {"$set": {
                "title": title,
                "slug": slug,
                "status": "draft",
                "source": "auto-generated",
                "geo_meta": geo_meta,
                "created_at": now_iso,
            }},
            upsert=True,
        )
        generated.append({"slug": slug, "title": title, "geo_meta": geo_meta})
    return {"generated": generated, "count": len(generated)}


# ─────────────────────────────────────────────
# CMS SCRAPER STATUS — surfaces scraper blockers
# GET /admin/cms/scraper-status
# ─────────────────────────────────────────────

@router.get("/admin/cms/scraper-status")
async def admin_cms_scraper_status(admin: dict = Depends(get_admin_user)):
    """
    Surfaces the status of the personalized CMS scraper pipeline and any blockers.
    Checks:
      1. CmsNoIndexMiddleware anti-scraper UA blocklist (python-requests, wget, curl, etc.)
      2. _cms_request_ctx context-var scraper-prevention flag (no web-search from within CMS)
      3. Paid-gate enforcement — users on free plan receive 402
      4. cms_documents collection — total personal plans, recent failures, empty content
      5. LLM connectivity — new plans fail silently if LLM is down
    Returns a status summary + prioritised blocker list for the admin Automation panel.
    """
    blockers = []
    stats = {
        "total_plans": 0,
        "published_plans": 0,
        "error_plans": 0,
        "empty_plans": 0,
        "paid_users": 0,
        "free_users": 0,
        "scraper_status": "ok",
    }

    # ── Structural/architectural blocker checks (always run, no DB required) ──
    # 1. CmsNoIndexMiddleware UA blocklist — automated HTTP clients are blocked 403
    blocked_ua_patterns = [
        "python-requests", "wget", "curl", "scrapy", "go-http-client",
        "ahrefsbot", "semrushbot", "gptbot", "claudebot", "perplexitybot",
        "bingbot", "googlebot", "yandexbot", "duckduckbot",
    ]
    blockers.append({
        "type": "ua_blocklist_active",
        "message": (
            "CmsNoIndexMiddleware is ACTIVE on all /api/cms/* routes. "
            f"The following User-Agent patterns are blocked with 403: {', '.join(blocked_ua_patterns[:6])} (and {len(blocked_ua_patterns)-6} more). "
            "Any external scraper using these clients will receive 403 Forbidden — use a browser-like UA or authenticated SDK client."
        ),
        "severity": "warning",
        "detail": {
            "middleware": "CmsNoIndexMiddleware",
            "path_prefix": "/api/cms/",
            "blocked_uas": blocked_ua_patterns,
            "response_headers": ["X-Robots-Tag: noindex, nofollow", "Cache-Control: private, no-store"],
        },
    })

    # 2. Context-var web-search prevention — outbound web calls raise 403 from within CMS handlers
    blockers.append({
        "type": "cms_request_ctx_guard",
        "message": (
            "_cms_request_ctx context variable is set to True for all /api/cms/* requests. "
            "This structurally prevents outbound web-search/firecrawl calls from executing inside CMS handlers — "
            "any scraper that relies on web fetching will silently get a 403 from the guard. "
            "CMS content generation uses only call_slm + MongoDB (no external fetching)."
        ),
        "severity": "info",
        "detail": {
            "guard_var": "_cms_request_ctx",
            "effect": "Raises HTTP 403 if any outbound web/scrape call is attempted from CMS handlers",
        },
    })

    try:
        if not await is_mongo_available():
            blockers.insert(0, {
                "type": "db_unavailable",
                "message": "MongoDB unavailable — CMS scraper cannot read/write personalized plans",
                "severity": "critical",
            })
            stats["scraper_status"] = "critical"
            return {"status": "critical", "blockers": blockers, "stats": stats, "recent_plans": []}

        # Count all personalized plans
        stats["total_plans"]     = await db.cms_documents.count_documents({"doc_type": "personalized"})
        stats["published_plans"] = await db.cms_documents.count_documents({"doc_type": "personalized", "status": "published"})
        stats["error_plans"]     = await db.cms_documents.count_documents({"doc_type": "personalized", "status": "error"})

        # Detect plans with empty/too-short content (generation truncation blocker)
        sample_plans = await db.cms_documents.find(
            {"doc_type": "personalized", "status": "published"},
            {"_id": 0, "id": 1, "title": 1, "user_id": 1, "content": 1, "word_count": 1, "created_at": 1}
        ).sort("created_at", -1).limit(50).to_list(50)

        for plan in sample_plans:
            wc = plan.get("word_count") or len((plan.get("content") or "").split())
            if wc < 50:
                stats["empty_plans"] += 1

        if stats["error_plans"] > 0:
            blockers.append({
                "type": "generation_errors",
                "message": f"{stats['error_plans']} personalized plan(s) failed during generation (LLM timeout or prompt error). "
                           "Check recent error documents and verify LLM key health below.",
                "severity": "high",
                "count": stats["error_plans"],
            })

        if stats["empty_plans"] > 0:
            blockers.append({
                "type": "empty_content",
                "message": f"{stats['empty_plans']} published plan(s) have fewer than 50 words — "
                           "content generation may have been truncated by LLM token limit or rate limit.",
                "severity": "medium",
                "count": stats["empty_plans"],
            })

        # Check paid/free user breakdown — free users get 402 from /cms/personalize
        try:
            all_users = await supa_list_users()
            paid_users = [u for u in all_users if u.get("plan", "free") in {"starter", "pro"}]
            free_users = [u for u in all_users if u.get("plan", "free") == "free"]
            stats["paid_users"] = len(paid_users)
            stats["free_users"] = len(free_users)
            if len(paid_users) == 0 and stats["total_plans"] > 0:
                blockers.append({
                    "type": "no_paid_users",
                    "message": (
                        f"Plans exist in DB but 0 users are on Starter/Pro — "
                        "POST /api/cms/personalize will return 402 for ALL users. "
                        f"Total users: {len(all_users)}, all on free plan."
                    ),
                    "severity": "warning",
                })
        except Exception:
            pass

        # Check LLM connectivity — quick probe (new plan generation fails if LLM is down)
        llm_ok = True
        try:
            test_resp = await call_llm_api([{"role": "user", "content": "Say OK"}], max_tokens=5)
            if not test_resp or len(test_resp.strip()) == 0:
                llm_ok = False
        except Exception:
            llm_ok = False

        if not llm_ok:
            blockers.append({
                "type": "llm_unavailable",
                "message": "LLM provider is unreachable — new personalized plans will fail at generation step. "
                           "Existing published plans are still served from MongoDB.",
                "severity": "critical",
            })

        # Overall status
        if any(b["severity"] == "critical" for b in blockers):
            stats["scraper_status"] = "critical"
        elif any(b["severity"] == "high" for b in blockers):
            stats["scraper_status"] = "degraded"
        elif any(b["severity"] in ("medium", "warning") for b in blockers):
            stats["scraper_status"] = "warning"
        else:
            stats["scraper_status"] = "ok"

        return {
            "status": stats["scraper_status"],
            "blockers": blockers,
            "stats": stats,
            "recent_plans": [
                {
                    "id": p.get("id"), "title": p.get("title"), "user_id": p.get("user_id"),
                    "word_count": p.get("word_count") or len((p.get("content") or "").split()),
                    "created_at": p.get("created_at"),
                }
                for p in sample_plans[:5]
            ],
        }

    except Exception as exc:
        logger.error(f"admin_cms_scraper_status error: {exc}")
        return {
            "status": "error",
            "blockers": [{"type": "internal_error", "message": str(exc)[:200], "severity": "critical"}],
            "stats": stats,
        }


# ─────────────────────────────────────────────
# PHASE E: MONETIZATION ANALYTICS
# ─────────────────────────────────────────────
