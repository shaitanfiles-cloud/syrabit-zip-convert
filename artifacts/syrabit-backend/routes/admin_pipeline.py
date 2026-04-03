"""Syrabit.ai — Admin pipeline: generate notes, MCQs, flashcards"""
import re, json, asyncio, time, uuid, logging, hashlib, io, csv, os, base64, html as _html_mod, httpx
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
from llm import call_llm_api, call_llm_api_content, call_llm_api_stream
from rag import *
from utils import *
from analytics_helpers import *
from seed import ensure_seeded
from seo_engine import _normalize_headings

logger = logging.getLogger(__name__)

router = APIRouter()


async def _pipeline_generate_mcqs(
    content: str, subject_name: str, chapter_title: str, class_name: str, count: int = 20,
) -> list:
    if not content or len(content.strip()) < 100:
        return []
    prompt = (
        f"You are an expert examiner for AHSEC/SEBA/Degree students in Assam, India.\n"
        f"Generate exactly {count} MCQ questions for:\n"
        f"Subject: {subject_name} ({class_name})\nChapter: {chapter_title}\n\n"
        f"Each MCQ must have exactly 4 options (A, B, C, D), one correct answer, and a brief explanation.\n"
        f"Mix difficulties: 30% easy, 40% medium, 30% hard.\n"
        f"Questions must use exam-style language matching AHSEC/SEBA/Degree paper patterns.\n"
        f"Return ONLY valid JSON (no markdown fences):\n"
        f'[{{"id": 1, "question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, '
        f'"correct_answer": "A", "explanation": "...", "difficulty": "medium", "topic": "...", "marks": 1}}]\n\n'
        f"Chapter content:\n{content[:4500]}"
    )
    try:
        result = await call_llm_api_content([{"role": "user", "content": prompt}], max_tokens=3000)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
        return data.get("mcqs", data.get("questions", []))
    except Exception:
        return []


async def _pipeline_generate_flashcards(
    content: str, subject_name: str, chapter_title: str, class_name: str, count: int = 15,
    topics: list = None,
) -> list:
    if not content or len(content.strip()) < 100:
        return []
    topic_instruction = ""
    if topics:
        topic_list = ", ".join(str(t) for t in topics[:15])
        topic_instruction = f"\nFlashcards MUST collectively cover ALL of these syllabus topics: {topic_list}\nEnsure at least one flashcard per topic.\n"
    prompt = (
        f"You are an expert memory coach for AHSEC/SEBA/Degree students in Assam, India.\n"
        f"Generate exactly {count} HIGH-IMPACT memory-trick flashcards for:\n"
        f"Subject: {subject_name} ({class_name})\nChapter: {chapter_title}\n"
        f"{topic_instruction}\n"
        f"Card types (distribute evenly): mnemonic, mindmap, shortcut, memory_hack, key_fact\n"
        f"Each card should use exam-relevant terms matching AHSEC/SEBA/Degree paper patterns.\n\n"
        f"Return ONLY valid JSON (no markdown fences):\n"
        f'{{"flashcards": [{{"id": 1, "front": "...", "back": "...", "type": "mnemonic", '
        f'"difficulty": "easy", "exam_tip": "...", "tags": ["..."]}}]}}\n\n'
        f"Chapter content:\n{content[:4500]}"
    )
    try:
        result = await call_llm_api_content([{"role": "user", "content": prompt}], max_tokens=3000)
        cleaned = result.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned)
        return data.get("flashcards", [])
    except Exception:
        return []

@router.post("/admin/content/chapters/{chapter_id}/generate-notes")
async def admin_generate_chapter_notes(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """
    Use AI to generate topic-wise summary notes for a chapter.
    Reads: title, description, topics from the chapter + subject context.
    Writes rich markdown notes back to chapter.content and re-chunks.
    """
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    subject = await db.subjects.find_one({"id": chapter.get("subject_id", "")}, {"_id": 0}) or {}
    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")

    title       = chapter.get("title", "").strip()
    description = (chapter.get("description") or "").strip()
    topics      = chapter.get("topics") or []

    if not title:
        raise HTTPException(status_code=400, detail="Chapter has no title")
    if not description and not topics:
        raise HTTPException(
            status_code=422,
            detail="Add a description (or syllabus topics) to this chapter before generating notes."
        )

    # ── Fetch SEO topics for this chapter as keyword seeds ───────────────────
    seo_topic_docs = await db.seo_topics.find(
        {"linked_chapter_id": chapter_id},
        {"_id": 0, "topic": 1, "primary_keyword": 1}
    ).to_list(30)
    seo_keywords = list(dict.fromkeys(
        (d.get("primary_keyword") or d.get("topic") or "").strip()
        for d in seo_topic_docs
        if (d.get("primary_keyword") or d.get("topic") or "").strip()
    ))

    # Build the educational prompt
    topic_block = ""
    if topics:
        topic_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
    else:
        topic_block = f"  {description}"

    seo_seed_block = ""
    if seo_keywords:
        seo_seed_block = (
            "\n\n**SEO Keyword Seeds (naturally weave these phrases into headings and body):**\n"
            + "\n".join(f"  - {kw}" for kw in seo_keywords[:15])
        )

    prompt = f"""You are an expert academic content writer for AHSEC/SEBA/Degree (NEP/FYUGP) students in Assam, India.

Generate **exam-focused, topic-wise study notes** for the chapter below.

**Chapter:** {title}
**Subject:** {subject_name or "Degree Course"} ({(paper_type or "").upper()} — {class_name or "FYUGP"})
**Description:** {description or "No additional description provided."}

**Syllabus Topics to cover (MANDATORY — every topic MUST get its own section):**
{topic_block}{seo_seed_block}

---

**INSTRUCTIONS:**
1. Open with a crisp **introduction** (2-3 sentences) — state the chapter's exam relevance.
2. For EACH topic listed above, write:
   - A ## Heading matching the topic name exactly
   - 3-5 sentence explanation using simple, precise academic language
   - **Key Points** as 4-6 bullets: definitions in **bold**, significance, and facts examiners look for
   - Where applicable, include a brief real-world example or Assam-specific context
3. If SEO keyword seeds are provided, naturally incorporate them in headings and body text.
4. End with a **Summary** section listing the 5-7 most exam-critical takeaways.
5. Use markdown (##, ###, **, -, etc.). NO disclaimers, NO preamble.
6. Quality over length — target 400-700 words of dense, high-value content.
7. Write as though every word costs marks — no filler, no repetition.
"""

    try:
        generated = await call_llm_api_content(
            [{"role": "user", "content": prompt}],
            max_tokens=2048
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {e}")

    if not generated or len(generated.strip()) < 50:
        raise HTTPException(status_code=502, detail="AI returned empty or too-short content")

    # Save generated notes
    await db.chapters.update_one(
        {"id": chapter_id},
        {"$set": {
            "content":      generated.strip(),
            "content_type": "notes",
            "notes_generated": True,
            "notes_generated_at": datetime.now(timezone.utc).isoformat(),
        }}
    )
    _invalidate_content_cache("chapters")

    # Re-chunk for RAG search
    try:
        await auto_chunk_content(chapter_id=chapter_id, content=generated.strip(), subject_id=chapter.get("subject_id"), category=chapter.get("category", "notes"))
    except Exception:
        pass

    return {
        "chapter_id": chapter_id,
        "title": title,
        "content": generated.strip(),
        "word_count": len(generated.split()),
        "message": "Notes generated successfully",
    }


@router.get("/admin/content/thin-chapters")
async def admin_list_thin_chapters(
    min_words: int = Query(default=500, description="Chapters below this word count are thin"),
    admin: dict = Depends(get_admin_user),
):
    pipeline = [
        {"$match": {"content": {"$exists": True, "$ne": ""}}},
        {"$project": {
            "id": 1, "title": 1, "subject_id": 1, "content": 1,
            "needs_review": 1, "order_index": 1, "_id": 0,
        }},
    ]
    chapters = await db.chapters.aggregate(pipeline).to_list(500)

    thin = []
    for ch in chapters:
        wc = len((ch.get("content") or "").split())
        if wc < min_words:
            thin.append({
                "id": ch.get("id"),
                "title": ch.get("title", ""),
                "subject_id": ch.get("subject_id", ""),
                "word_count": wc,
                "needs_review": ch.get("needs_review", False),
            })
    thin.sort(key=lambda x: x["word_count"])
    return {"total": len(thin), "min_words": min_words, "chapters": thin}


@router.post("/admin/content/regenerate-thin")
async def admin_regenerate_thin_chapters(
    min_words: int = Query(default=500, description="Regenerate chapters below this word count"),
    limit: int = Query(default=10, description="Max chapters to regenerate per call"),
    admin: dict = Depends(get_admin_user),
):
    pipeline = [
        {"$match": {"content": {"$exists": True, "$ne": ""}}},
        {"$project": {"id": 1, "title": 1, "subject_id": 1, "content": 1, "topics": 1, "_id": 0}},
    ]
    all_chapters = await db.chapters.aggregate(pipeline).to_list(500)

    thin = [ch for ch in all_chapters if len((ch.get("content") or "").split()) < min_words]
    thin.sort(key=lambda x: len((x.get("content") or "").split()))
    thin = thin[:limit]

    results = []
    for chapter in thin:
        chapter_id = chapter.get("id", "")
        title = (chapter.get("title") or "").strip()
        if not title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue

        subject = await db.subjects.find_one({"id": chapter.get("subject_id", "")}, {"_id": 0}) or {}
        subject_name = subject.get("name", "")
        topics = chapter.get("topics") or []
        topic_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics)) if topics else f"  {title}"

        prompt = f"""You are an expert academic content writer for AHSEC/SEBA/Degree (NEP/FYUGP) students in Assam, India.

Generate detailed study notes for:
**Chapter:** {title}
**Subject:** {subject_name or "Degree Course"}

**Topics to cover:**
{topic_block}

**INSTRUCTIONS:**
1. Write 800-1200 words of detailed, exam-focused notes
2. Use ## headings for each topic (match topic names exactly), ### for subtopics
3. Include key definitions in **bold**, 4-6 bullet points per topic for key facts examiners look for
4. Where applicable, include Assam-specific context or real-world examples
5. End with a **Summary** section listing 5-7 most exam-critical takeaways
6. Use markdown formatting throughout. NO disclaimers, NO preamble.
7. Quality over length — no filler, no repetition"""

        try:
            generated = await call_llm_api_content([{"role": "user", "content": prompt}], max_tokens=4000)
            if generated and len(generated.split()) >= 200:
                generated = _normalize_headings(generated)
                wc = len(generated.split())
                update_fields = {
                    "content": generated.strip(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                if wc >= min_words:
                    update_fields["needs_review"] = False
                else:
                    update_fields["needs_review"] = True
                await db.chapters.update_one({"id": chapter_id}, {"$set": update_fields})
                try:
                    await auto_chunk_content(chapter_id=chapter_id, content=generated.strip(), subject_id=chapter.get("subject_id"), category=chapter.get("category", "notes"))
                except Exception:
                    pass
                results.append({"chapter_id": chapter_id, "title": title, "status": "ok", "word_count": wc})
            else:
                results.append({"chapter_id": chapter_id, "title": title, "status": "error", "reason": "AI returned too-short content"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": title, "status": "error", "reason": str(e)})

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    return {
        "total_thin": len(thin),
        "regenerated": ok_count,
        "results": results,
    }


@router.get("/admin/content/needs-review")
async def admin_needs_review_chapters(admin: dict = Depends(get_admin_user)):
    chapters = await db.chapters.find(
        {"needs_review": True},
        {"_id": 0, "id": 1, "title": 1, "subject_id": 1, "content": 1}
    ).to_list(100)
    items = []
    for ch in chapters:
        items.append({
            "id": ch.get("id"),
            "title": ch.get("title", ""),
            "subject_id": ch.get("subject_id", ""),
            "word_count": len((ch.get("content") or "").split()),
        })
    return {"total": len(items), "chapters": items}


@router.post("/admin/content/chapters/{chapter_id}/approve")
async def admin_approve_chapter(chapter_id: str, admin: dict = Depends(get_admin_user)):
    result = await db.chapters.update_one(
        {"id": chapter_id},
        {"$set": {"needs_review": False, "reviewed_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Chapter not found or already approved")
    return {"chapter_id": chapter_id, "status": "approved"}


@router.post("/admin/content/chapters/{chapter_id}/rechunk")
async def admin_rechunk_chapter(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """
    Manually re-chunk a specific chapter.
    Useful for fixing chunking issues or after manual content edits.
    """
    try:
        result = await rechunk_chapter(chapter_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Re-chunking failed for chapter {chapter_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Re-chunking failed: {str(e)}")


@router.get("/admin/content/chapters/{chapter_id}/stats")
async def get_chapter_stats(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """Get chunk, content, question, flashcard, and SEO stats for a single chapter."""
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    ch_slug = chapter.get("slug", "")
    seo_page_query = {"chapter_slug": ch_slug, "status": "published"} if ch_slug else {"_no_match_": True}
    chunk_count, pyq_doc, fc_doc, geo_blog_count, pyq_html_count, seo_topic_count, seo_pages_list = await asyncio.gather(
        db.chunks.count_documents({"chapter_id": chapter_id}),
        db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1, "mark_wise": 1}),
        db.flashcard_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1, "cards": 1, "flashcards": 1}),
        db.seo_pages.count_documents({"linked_chapter_id": chapter_id, "type": "geo_blog"}),
        db.pyq_html_pages.count_documents({"chapter_id": chapter_id}),
        db.seo_topics.count_documents({"linked_chapter_id": chapter_id}),
        db.seo_pages.find(seo_page_query, {"_id": 0, "page_type": 1, "title": 1, "quality": 1}).to_list(100),
    )
    if not pyq_doc:
        pyq_doc = await db.topic_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0, "total": 1})
    content_len = len(chapter.get("content", "") or "")
    mark_wise = pyq_doc.get("mark_wise", {}) if pyq_doc else {}
    pyq_count = pyq_doc.get("total", 0) if pyq_doc else 0
    if pyq_count == 0 and mark_wise:
        pyq_count = sum(len(v) for v in mark_wise.values())
    fc_total = fc_doc.get("total", 0) if fc_doc else 0
    if fc_total == 0 and fc_doc:
        fc_total = len(fc_doc.get("cards") or fc_doc.get("flashcards") or [])

    seo_page_types = {}
    for sp in seo_pages_list:
        pt = sp.get("page_type", "unknown")
        seo_page_types[pt] = seo_page_types.get(pt, 0) + 1

    linked_topic_ids = chapter.get("linked_topic_ids", [])
    linked_topics = []
    if linked_topic_ids:
        linked_topics = await db.seo_topics.find(
            {"id": {"$in": linked_topic_ids}},
            {"_id": 0, "id": 1, "title": 1, "slug": 1, "status": 1, "primary_keyword": 1}
        ).to_list(50)

    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter.get("title", ""),
        "content_length": content_len,
        "chunk_count": chunk_count,
        "has_slug": bool(chapter.get("slug")),
        "content_type": chapter.get("content_type", "notes"),
        "attached_files": chapter.get("attached_files", []),
        "pyq_count": pyq_count,
        "mark_wise_counts": {k: len(v) for k, v in mark_wise.items()} if mark_wise else {},
        "flashcard_count": fc_total,
        "geo_blog_count": geo_blog_count,
        "pyq_html_count": pyq_html_count,
        "notes_generated": bool(chapter.get("notes_generated") or content_len > 100),
        "seo_topic_count": seo_topic_count,
        "seo_page_types": seo_page_types,
        "seo_pages_published": len(seo_pages_list),
        "linked_topics": linked_topics,
    }


@router.get("/admin/content/subject/{subject_id}/chapter-cards")
async def get_subject_chapter_cards(subject_id: str, admin: dict = Depends(get_admin_user)):
    """Return content-card data for every chapter in a subject — single batch call.

    Each card includes: notes status, mark-wise question counts, flashcard count,
    linked SEO topics, published SEO page types, and blog count.
    """
    chapters = await db.chapters.find(
        {"subject_id": subject_id},
        {"_id": 0, "id": 1, "title": 1, "slug": 1, "content": 1, "notes_generated": 1,
         "linked_topic_ids": 1, "order_index": 1, "description": 1, "coverage_score": 1,
         "content_type": 1}
    ).sort("order_index", 1).to_list(200)
    if not chapters:
        return {"cards": [], "subject_id": subject_id}

    ch_ids = [c["id"] for c in chapters]
    ch_slugs = [c.get("slug", "") for c in chapters if c.get("slug")]

    pyq_docs, fc_docs, seo_topic_docs, seo_pages_raw, blog_counts = await asyncio.gather(
        db.ai_pyq_collections.find(
            {"chapter_id": {"$in": ch_ids}},
            {"_id": 0, "chapter_id": 1, "total": 1, "mark_wise": 1}
        ).to_list(200),
        db.flashcard_collections.find(
            {"chapter_id": {"$in": ch_ids}},
            {"_id": 0, "chapter_id": 1, "total": 1, "cards": 1, "flashcards": 1}
        ).to_list(200),
        db.seo_topics.find(
            {"linked_chapter_id": {"$in": ch_ids}},
            {"_id": 0, "id": 1, "linked_chapter_id": 1, "title": 1, "slug": 1, "status": 1, "primary_keyword": 1}
        ).to_list(1000),
        db.seo_pages.find(
            {"chapter_slug": {"$in": ch_slugs}, "status": "published"},
            {"_id": 0, "chapter_slug": 1, "page_type": 1}
        ).to_list(5000),
        db.seo_pages.aggregate([
            {"$match": {"linked_chapter_id": {"$in": ch_ids}, "type": "geo_blog"}},
            {"$group": {"_id": "$linked_chapter_id", "count": {"$sum": 1}}}
        ]).to_list(200),
    )

    fallback_pyq_ids = [cid for cid in ch_ids if not any(p["chapter_id"] == cid for p in pyq_docs)]
    fallback_pyqs = []
    if fallback_pyq_ids:
        fallback_pyqs = await db.topic_pyq_collections.find(
            {"chapter_id": {"$in": fallback_pyq_ids}},
            {"_id": 0, "chapter_id": 1, "total": 1}
        ).to_list(200)

    pyq_map = {}
    for p in pyq_docs:
        mark_wise = p.get("mark_wise", {})
        total = p.get("total", 0)
        if total == 0 and mark_wise:
            total = sum(len(v) for v in mark_wise.values())
        pyq_map[p["chapter_id"]] = {
            "total": total,
            "mark_wise": {k: len(v) for k, v in mark_wise.items()} if mark_wise else {},
        }
    for fp in fallback_pyqs:
        if fp["chapter_id"] not in pyq_map:
            pyq_map[fp["chapter_id"]] = {"total": fp.get("total", 0), "mark_wise": {}}

    fc_map = {}
    for f in fc_docs:
        total = f.get("total", 0)
        if total == 0:
            total = len(f.get("cards") or f.get("flashcards") or [])
        fc_map[f["chapter_id"]] = total

    topic_map: dict[str, list] = {}
    for t in seo_topic_docs:
        ch_id = t.get("linked_chapter_id", "")
        if ch_id:
            topic_map.setdefault(ch_id, []).append({
                "id": t["id"], "title": t["title"], "slug": t.get("slug", ""),
                "status": t.get("status", ""), "primary_keyword": t.get("primary_keyword", ""),
            })

    seo_pages_by_slug: dict[str, dict] = {}
    for sp in seo_pages_raw:
        slug = sp.get("chapter_slug", "")
        if slug:
            pt = sp.get("page_type", "unknown")
            seo_pages_by_slug.setdefault(slug, {})
            seo_pages_by_slug[slug][pt] = seo_pages_by_slug[slug].get(pt, 0) + 1

    blog_map = {b["_id"]: b["count"] for b in blog_counts}

    cards = []
    for ch in chapters:
        content_len = len(ch.get("content", "") or "")
        has_notes = bool(ch.get("notes_generated") or content_len > 100)
        pyq_info = pyq_map.get(ch["id"], {"total": 0, "mark_wise": {}})
        cards.append({
            "chapter_id": ch["id"],
            "title": ch.get("title", ""),
            "slug": ch.get("slug", ""),
            "description": ch.get("description", ""),
            "order_index": ch.get("order_index", 0),
            "content_type": ch.get("content_type", "notes"),
            "notes_generated": has_notes,
            "word_count": len((ch.get("content", "") or "").split()) if has_notes else 0,
            "coverage_score": ch.get("coverage_score"),
            "pyq_count": pyq_info["total"],
            "mark_wise_counts": pyq_info["mark_wise"],
            "flashcard_count": fc_map.get(ch["id"], 0),
            "blog_count": blog_map.get(ch["id"], 0),
            "seo_topic_count": len(topic_map.get(ch["id"], [])),
            "linked_topics": topic_map.get(ch["id"], []),
            "seo_page_types": seo_pages_by_slug.get(ch.get("slug", ""), {}),
            "seo_pages_published": sum(seo_pages_by_slug.get(ch.get("slug", ""), {}).values()),
        })

    return {"cards": cards, "subject_id": subject_id, "total": len(cards)}


def _compute_topic_coverage(topics: list, content: str, questions: list = None, flashcards: list = None) -> dict:
    """Compute how many listed topics have meaningful representation in generated content."""
    if not topics:
        return {"score": 100, "total_topics": 0, "covered": 0, "missing": []}
    content_lower = (content or "").lower()
    q_text = " ".join(
        (q.get("question", "") if isinstance(q, dict) else str(q))
        for q in (questions or [])
    ).lower()
    fc_text = " ".join(
        ((f.get("front", "") + " " + f.get("back", "")) if isinstance(f, dict) else str(f))
        for f in (flashcards or [])
    ).lower()
    combined = content_lower + " " + q_text + " " + fc_text
    covered = []
    missing = []
    for topic in topics:
        t = str(topic).strip()
        if not t:
            continue
        t_lower = t.lower()
        if t_lower in combined:
            covered.append(t)
            continue
        words = [w for w in re.split(r'\W+', t_lower) if w]
        if not words:
            covered.append(t)
            continue
        matched_words = sum(1 for w in words if w in combined)
        threshold = max(1, len(words) * 0.4)
        if matched_words >= threshold:
            covered.append(t)
        else:
            missing.append(t)
    total = len(covered) + len(missing)
    score = round((len(covered) / total) * 100) if total > 0 else 100
    return {"score": score, "total_topics": total, "covered": len(covered), "missing": missing}


@router.get("/admin/content/chapters/{subject_id}/coverage")
async def admin_subject_coverage(subject_id: str, admin: dict = Depends(get_admin_user)):
    """Compute per-chapter syllabus topic coverage scores for a subject."""
    chapters = await db.chapters.find({"subject_id": subject_id}).sort("order_index", 1).to_list(None)
    if not chapters:
        return {"subject_id": subject_id, "chapters": []}
    chapter_ids = [c["id"] for c in chapters]
    pyq_docs, fc_docs = await asyncio.gather(
        db.ai_pyq_collections.find({"chapter_id": {"$in": chapter_ids}}, {"_id": 0}).to_list(None),
        db.flashcard_collections.find({"chapter_id": {"$in": chapter_ids}}, {"_id": 0}).to_list(None),
    )
    pyq_map = {d["chapter_id"]: d.get("pyqs", []) for d in pyq_docs}
    fc_map = {d["chapter_id"]: d.get("flashcards", []) for d in fc_docs}
    results = []
    for ch in chapters:
        cid = ch["id"]
        ch_questions = ch.get("important_questions") or pyq_map.get(cid, [])
        ch_flashcards = ch.get("memory_tricks") or fc_map.get(cid, [])
        cov = _compute_topic_coverage(
            ch.get("topics", []),
            ch.get("content", ""),
            ch_questions,
            ch_flashcards,
        )
        await db.chapters.update_one({"id": cid}, {"$set": {"coverage_score": cov["score"]}})
        results.append({
            "chapter_id": cid,
            "title": ch.get("title", ""),
            "coverage_score": cov["score"],
            "total_topics": cov["total_topics"],
            "covered": cov["covered"],
            "missing": cov["missing"],
            "flagged": cov["score"] < 60,
        })
    return {"subject_id": subject_id, "chapters": results}


@router.post("/admin/content/chapters/{chapter_id}/attach-file")
async def attach_file_to_chapter(
    chapter_id: str,
    file: UploadFile = File(...),
    admin: dict = Depends(get_admin_user)
):
    """Upload and attach a file (PDF/text) to a chapter."""
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0, "id": 1, "subject_id": 1, "attached_files": 1})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    file_content = await file.read()
    max_file_size = 10 * 1024 * 1024
    if len(file_content) > max_file_size:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'txt'
    if file_ext not in ('pdf', 'txt', 'md'):
        raise HTTPException(status_code=400, detail="Only PDF, TXT, and MD files are supported")
    file_id = str(uuid.uuid4())

    extracted_text = ""
    pdf_url = ""

    if file_ext == 'pdf' and supa:
        import time as _t
        storage_path = f"pdfs/{chapter['subject_id']}/{_t.time():.0f}_{file.filename.replace(' ', '_')}"
        try:
            supa.storage.from_("study-materials").upload(path=storage_path, file=file_content, file_options={"content-type": "application/pdf", "upsert": "false"})
            pdf_url = supa.storage.from_("study-materials").get_public_url(storage_path)
        except Exception as e:
            logger.warning(f"Supabase upload failed, storing base64: {e}")
            import base64
            pdf_url = f"data:application/pdf;base64,{base64.b64encode(file_content).decode()}"
        try:
            from PyPDF2 import PdfReader
            import io
            reader = PdfReader(io.BytesIO(file_content))
            extracted_text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        except Exception:
            pass
    elif file_ext in ('txt', 'md'):
        extracted_text = file_content.decode('utf-8', errors='ignore')

    attachment = {
        "id": file_id,
        "file_name": file.filename,
        "file_ext": file_ext,
        "file_size": len(file_content),
        "url": pdf_url,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }

    existing_files = chapter.get("attached_files", []) or []
    existing_files.append(attachment)
    update_fields = {"attached_files": existing_files}

    if extracted_text and len(extracted_text) > 50:
        old_content = (await db.chapters.find_one({"id": chapter_id}, {"content": 1})).get("content", "") or ""
        separator = "\n\n---\n\n"
        update_fields["content"] = old_content + separator + f"## {file.filename}\n\n{extracted_text}" if old_content else extracted_text
        update_fields["updated_at"] = datetime.now(timezone.utc).isoformat()

    await db.chapters.update_one({"id": chapter_id}, {"$set": update_fields})

    if extracted_text and len(extracted_text) > 100:
        try:
            await rechunk_chapter(chapter_id)
        except Exception:
            pass

    _invalidate_content_cache("chapters")
    return {"attachment": attachment, "text_extracted": len(extracted_text)}


@router.post("/admin/content/bulk-rechunk")
async def admin_bulk_rechunk_all_chapters(
    subject_id: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """
    Bulk re-chunk all chapters (or chapters in a specific subject).
    
    Use cases:
    - Initial setup: chunk all existing chapters that have content
    - After algorithm improvements
    - Database migration
    
    Query params:
    - subject_id (optional): Only rechunk chapters from this subject
    """
    # Find chapters with content
    filter_query = {"content": {"$exists": True, "$ne": ""}}
    if subject_id:
        filter_query["subject_id"] = subject_id
    
    chapters = await db.chapters.find(filter_query, {"_id": 0, "id": 1, "title": 1, "subject_id": 1}).to_list(1000)
    
    if not chapters:
        return {
            "message": "No chapters with content found",
            "total": 0,
            "chunked": 0,
            "failed": 0
        }
    
    total = len(chapters)
    chunked = 0
    failed = 0
    failed_chapters = []
    
    for chapter in chapters:
        try:
            result = await rechunk_chapter(chapter["id"])
            if result["chunks_created"] > 0:
                chunked += 1
                logger.info(f"✅ Bulk rechunked: {chapter['title']} → {result['chunks_created']} chunks")
        except Exception as e:
            failed += 1
            failed_chapters.append({
                "chapter_id": chapter["id"],
                "title": chapter.get("title"),
                "error": str(e)
            })
            logger.error(f"❌ Bulk rechunk failed for {chapter.get('title')}: {e}")
    
    return {
        "message": f"Bulk re-chunking complete",
        "total_chapters": total,
        "successfully_chunked": chunked,
        "failed": failed,
        "failed_chapters": failed_chapters if failed > 0 else []
    }


@router.get("/admin/content/chunks/stats")
async def get_chunking_stats(admin: dict = Depends(get_admin_user)):
    """
    Get statistics about content chunking across the platform.
    Useful for monitoring RAG quality.
    """
    try:
        if not await is_mongo_available():
            return {"total_chunks": 0, "total_chapters": 0, "chapters_with_content": 0, "chapters_with_chunks": 0, "chapters_without_chunks": 0, "coverage_percent": 0, "top_subjects_by_chunks": [], "recommendation": "MongoDB unavailable"}
        total_chunks = await db.chunks.count_documents({})
        pipeline = [
            {"$group": {"_id": "$subject_id", "count": {"$sum": 1}, "avg_size": {"$avg": "$char_count"}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        chunks_by_subject = await db.chunks.aggregate(pipeline).to_list(10)
        if chunks_by_subject:
            subject_ids = [item["_id"] for item in chunks_by_subject if item["_id"]]
            subjects = await db.subjects.find({"id": {"$in": subject_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(20)
            subject_map = {s["id"]: s["name"] for s in subjects}
            for item in chunks_by_subject:
                item["subject_name"] = subject_map.get(item["_id"], "Unknown")
        total_chapters = await db.chapters.count_documents({})
        chapters_with_content = await db.chapters.count_documents({"content": {"$exists": True, "$ne": ""}})
        chunked_chapter_ids = await db.chunks.distinct("chapter_id")
        chapters_with_chunks = len(chunked_chapter_ids)
        chapters_without_chunks = chapters_with_content - chapters_with_chunks
        return {
            "total_chunks": total_chunks,
            "total_chapters": total_chapters,
            "chapters_with_content": chapters_with_content,
            "chapters_with_chunks": chapters_with_chunks,
            "chapters_without_chunks": chapters_without_chunks,
            "coverage_percent": round((chapters_with_chunks / chapters_with_content * 100) if chapters_with_content > 0 else 0, 1),
            "top_subjects_by_chunks": chunks_by_subject,
            "recommendation": "Run /admin/content/bulk-rechunk to chunk all chapters" if chapters_without_chunks > 0 else "All content is chunked"
        }
    except Exception:
        mark_mongo_down()
        return {"total_chunks": 0, "total_chapters": 0, "chapters_with_content": 0, "chapters_with_chunks": 0, "chapters_without_chunks": 0, "coverage_percent": 0, "top_subjects_by_chunks": [], "recommendation": "MongoDB unavailable"}



@router.patch("/admin/content/uploads/{content_id}")
async def update_content_upload(content_id: str, data: dict, admin: dict = Depends(get_admin_user)):
    """Update uploaded content metadata"""
    allowed = {k: v for k, v in data.items() if k in ["title", "description", "content", "tags", "year", "exam_type", "category", "order", "status"]}
    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    result = await db.content_uploads.update_one({"id": content_id}, {"$set": allowed})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Content not found")
    
    updated = await db.content_uploads.find_one({"id": content_id}, {"_id": 0})
    return updated



@router.delete("/admin/content/chapters/{chapter_id}")
async def admin_delete_chapter(chapter_id: str, admin: dict = Depends(get_admin_user)):
    """Delete chapter"""
    chapter = await db.chapters.find_one({"id": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    await db.chapters.delete_one({"id": chapter_id})
    try:
        await db.syllabus_embeddings.delete_many({"chapter_id": chapter_id})
    except Exception:
        pass
    if chapter.get("subject_id"):
        await db.subjects.update_one(
            {"id": chapter["subject_id"]},
            {"$inc": {"chapter_count": -1}}
        )
    _invalidate_content_cache("chapters")
    _invalidate_content_cache("subjects")
    return {"message": "Chapter deleted"}

@router.post("/admin/seed")
async def admin_reseed(admin: dict = Depends(get_admin_user)):
    try:
        if not await is_mongo_available():
            raise HTTPException(status_code=503, detail="MongoDB unavailable in production - seed data is pre-loaded")
        global _seeded
        _seeded = False
        await db.boards.delete_many({})
        await db.classes.delete_many({})
        await db.streams.delete_many({})
        await db.subjects.delete_many({})
        await db.chapters.delete_many({})
        await ensure_seeded()
        return {"message": "Content reseeded successfully"}
    except HTTPException:
        raise
    except Exception as e:
        mark_mongo_down()
        raise HTTPException(status_code=503, detail=f"MongoDB error: {str(e)[:50]}")

