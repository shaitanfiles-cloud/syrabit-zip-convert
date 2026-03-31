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
from llm import call_llm_api, call_llm_api_stream
from rag import *
from utils import *
from analytics_helpers import *

logger = logging.getLogger(__name__)

router = APIRouter()

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

    prompt = f"""You are an expert academic content writer for Indian university degree students (NEP/FYUGP curriculum).

Generate **detailed, topic-wise summary notes** for the following chapter. These notes will be the primary study material for students.

**Chapter:** {title}
**Subject:** {subject_name or "Degree Course"} ({(paper_type or "").upper()} — {class_name or "FYUGP"})
**Description:** {description or "No additional description provided."}

**Syllabus Topics to cover:**
{topic_block}{seo_seed_block}

---

**INSTRUCTIONS:**
- Write a brief **introduction** (2-3 sentences) about the chapter as a whole.
- For EACH topic listed above, write a dedicated section with:
  - A clear **heading** (use ## for the topic name)
  - A concise explanation of the topic (3-6 sentences) in simple academic language
  - **Key Points** in bullet form (4-6 bullets) covering definitions, significance, and important facts
  - Use **bold** to highlight key terms/definitions
- If SEO keyword seeds are provided, naturally incorporate them in headings and body text.
- End with a brief **Summary** section recapping the chapter's main takeaways.
- Use markdown formatting (##, ###, **, -, etc.)
- Write for degree-level students — clear, precise, and educational
- Do NOT add any disclaimers or preamble. Start directly with the introduction.
- Target length: ~400-700 words total across all topics.
"""

    try:
        generated = await call_llm_api(
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
        await auto_chunk_content(chapter_id=chapter_id, content=generated.strip(), subject_id=chapter.get("subject_id"))
    except Exception:
        pass

    return {
        "chapter_id": chapter_id,
        "title": title,
        "content": generated.strip(),
        "word_count": len(generated.split()),
        "message": "Notes generated successfully",
    }


class BulkNotesRequest(BaseModel):
    skip_existing: bool = False

@router.post("/admin/subjects/{subject_id}/generate-notes-bulk")
async def admin_generate_subject_notes_bulk(subject_id: str, body: BulkNotesRequest = Body(default=None), admin: dict = Depends(get_admin_user)):
    """
    Generate AI topic-wise notes for ALL chapters of a subject.
    Pass skip_existing=true to skip chapters that already have notes (>50 words).
    Runs sequentially to avoid rate-limiting. Returns per-chapter results.
    """
    skip_existing = (body.skip_existing if body else False)
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "message": "No chapters found"}

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")

    results = []
    skipped_count = 0
    for chapter in chapters:
        chapter_id  = chapter.get("id", "")
        title       = (chapter.get("title") or "").strip()
        description = (chapter.get("description") or "").strip()
        topics      = chapter.get("topics") or []

        if not title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue

        # Build topic block — prefer topics list > description > existing content
        existing_content = (chapter.get("content") or "").strip()

        # ── skip_existing: skip chapters that already have sufficient notes ────
        if skip_existing and len(existing_content.split()) > 50:
            results.append({"chapter_id": chapter_id, "title": title, "status": "skipped", "reason": "notes exist"})
            skipped_count += 1
            continue

        if topics:
            topic_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(topics))
        elif description:
            topic_block = f"  {description}"
        elif existing_content:
            topic_block = existing_content[:400]
        else:
            results.append({"chapter_id": chapter_id, "title": title, "status": "skipped", "reason": "no description, topics, or content"})
            continue

        prompt = f"""You are an expert academic content writer for Indian university degree students (NEP/FYUGP curriculum).

Generate **detailed, topic-wise summary notes** for the following chapter. These notes will be the primary study material for students.

**Chapter:** {title}
**Subject:** {subject_name or "Degree Course"} ({(paper_type or "").upper()} — {class_name or "FYUGP"})
**Description:** {description or "No additional description provided."}

**Syllabus Topics to cover (MANDATORY — every topic MUST be covered):**
{topic_block}

---

**INSTRUCTIONS:**
- Write a brief **introduction** (2-3 sentences) about the chapter.
- You MUST cover EVERY topic listed above. For EACH topic listed, write:
  - A **## Heading** matching the topic name
  - 3-5 sentence explanation in simple academic language
  - **Key Points** in 4-6 bullets with definitions/significance/**bold key terms**
- Do NOT skip any topic from the list. If the syllabus lists N topics, your notes must have N corresponding sections.
- End with a **Summary** section.
- Use markdown. Do NOT add disclaimers. Start directly with the introduction.
- Target: ~400-700 words.
"""
        try:
            generated = await call_llm_api([{"role": "user", "content": prompt}], max_tokens=2048)
            if generated and len(generated.strip()) > 50:
                gen_text = generated.strip()
                if topics:
                    cov = _compute_topic_coverage(topics, gen_text)
                    if cov["missing"]:
                        logger.warning(
                            f"Notes generation for '{title}' missing topics ({cov['score']}%): {cov['missing'][:5]}"
                        )
                await db.chapters.update_one(
                    {"id": chapter_id},
                    {"$set": {
                        "content": gen_text,
                        "content_type": "notes",
                        "notes_generated": True,
                        "notes_generated_at": datetime.now(timezone.utc).isoformat(),
                    }}
                )
                try:
                    await auto_chunk_content(chapter_id=chapter_id, content=gen_text, subject_id=subject_id)
                except Exception:
                    pass
                results.append({"chapter_id": chapter_id, "title": title, "status": "ok", "word_count": len(gen_text.split())})
            else:
                results.append({"chapter_id": chapter_id, "title": title, "status": "error", "reason": "empty response"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": title, "status": "error", "reason": str(e)})

    _invalidate_content_cache("chapters")
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    return {
        "subject_id": subject_id,
        "subject_name": subject_name,
        "total": len(chapters),
        "generated": ok_count,
        "skipped": skipped_count,
        "results": results,
    }


@router.post("/admin/subjects/{subject_id}/sync-content-bulk")
async def admin_sync_content_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Final pipeline step: for each chapter, embed all generated assets
    (mark-wise questions + memory-trick flashcards) back into the chapter document.
    Sets has_important_questions, has_flashcards, mark_wise_questions, flashcard_summary,
    and content_synced_at on each chapter.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "synced": 0, "total": 0, "results": []}

    now_iso = datetime.now(timezone.utc).isoformat()
    results = []

    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue

        update_fields: dict = {"content_synced_at": now_iso}

        # Load mark-wise questions for this chapter
        q_doc = await db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0})
        if q_doc:
            update_fields["has_important_questions"] = True
            update_fields["questions_synced"]        = True
            update_fields["mark_wise_questions"]     = q_doc.get("mark_wise", {})
            update_fields["important_questions"]     = q_doc.get("pyqs", [])

        # Load memory-trick flashcards for this chapter
        fc_doc = await db.flashcard_collections.find_one(
            {"chapter_id": chapter_id, "pipeline_generated": True}, {"_id": 0}
        )
        if fc_doc:
            update_fields["has_flashcards"]    = True
            update_fields["flashcards_synced"] = True
            # Embed the full flashcard list into the chapter document
            update_fields["memory_tricks"]     = fc_doc.get("flashcards", [])

        await db.chapters.update_one(
            {"id": chapter_id},
            {"$set": update_fields},
        )

        results.append({
            "chapter_id":   chapter_id,
            "title":        chapter_title,
            "status":       "ok",
            "has_questions": bool(q_doc),
            "has_flashcards": bool(fc_doc),
        })

    synced = sum(1 for r in results if r.get("status") == "ok")
    _invalidate_content_cache("chapters")
    return {
        "subject_id": subject_id,
        "synced":     synced,
        "total":      len(chapters),
        "results":    results,
    }


# ── Subject-scoped content pipeline: notes → questions → flashcards → sync ──

_subject_pipeline_jobs: dict = {}


def _subject_pipeline_job_gc():
    """Remove jobs older than 2 hours."""
    cutoff = datetime.now(timezone.utc).timestamp() - 7200
    stale = [k for k, v in _subject_pipeline_jobs.items() if v.get("started_at", 0) < cutoff]
    for k in stale:
        _subject_pipeline_jobs.pop(k, None)


async def _run_subject_content_pipeline(job_id: str, subject_id: str):
    """
    Sequential background worker: for each chapter in order,
    check notes_generated flag (skip if True), then generate notes → mark-wise
    questions → flashcards → sync back onto the chapter document.
    Updates _subject_pipeline_jobs[job_id] with per-chapter progress.
    """
    import re as _re

    def _update_job(**kwargs):
        if job_id in _subject_pipeline_jobs:
            _subject_pipeline_jobs[job_id].update(kwargs)

    try:
        subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
        if not subject:
            _update_job(status="error", message="Subject not found", progress=100,
                        finished_at=datetime.now(timezone.utc).isoformat())
            return

        subject_name = subject.get("name", "")
        class_name   = subject.get("className", "")
        paper_type   = (subject.get("paper_type") or "").upper()

        chapters = await db.chapters.find(
            {"subject_id": subject_id}, {"_id": 0}
        ).sort("order_index", 1).to_list(100)

        total = len(chapters)
        if not total:
            _update_job(status="complete", progress=100, message="No chapters found",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        chapter_results=[])
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        chapter_results = []

        for idx, chapter in enumerate(chapters):
            chapter_id    = chapter.get("id", "")
            chapter_title = (chapter.get("title") or "").strip()
            pct = int(5 + (idx / total) * 88)
            _update_job(progress=pct, message=f"Processing chapter {idx + 1}/{total}: {chapter_title[:40]}")

            if not chapter_title:
                chapter_results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
                continue

            cr: dict = {"chapter_id": chapter_id, "chapter_title": chapter_title,
                        "notes": None, "questions": None, "flashcards": None, "sync": None}

            # ── Step 1: Notes (skip entire chapter if notes_generated=True) ────
            if chapter.get("notes_generated") is True:
                cr["notes"] = "skipped_existing"
                cr["questions"] = "skipped_existing"
                cr["flashcards"] = "skipped_existing"
                cr["sync"] = "skipped_existing"
                chapter_results.append(cr)
                continue
            else:
                try:
                    generated = await _pipeline_generate_chapter_notes(chapter, subject_name, class_name, paper_type)
                    if generated and len(generated.strip()) > 50:
                        await db.chapters.update_one(
                            {"id": chapter_id},
                            {"$set": {
                                "content": generated.strip(),
                                "content_type": "notes",
                                "notes_generated": True,
                                "notes_generated_at": now_iso,
                            }}
                        )
                        try:
                            await auto_chunk_content(chapter_id=chapter_id, content=generated.strip(), subject_id=subject_id)
                        except Exception:
                            pass
                        notes_content = generated.strip()
                        cr["notes"] = "generated"
                    else:
                        notes_content = (chapter.get("content") or "").strip()
                        cr["notes"] = "skipped_empty"
                except Exception as e:
                    notes_content = (chapter.get("content") or "").strip()
                    cr["notes"] = f"error: {str(e)[:60]}"

            if len(notes_content) < 100:
                cr["questions"] = "skipped_no_content"
                cr["flashcards"] = "skipped_no_content"
                cr["sync"] = "skipped"
                chapter_results.append(cr)
                continue

            try:
                topics     = chapter.get("topics") or []
                description = (chapter.get("description") or "").strip()
                topic_block = ", ".join(str(t) for t in topics[:15]) if topics else (description[:200] if description else chapter_title)
                generate_prompt = f"""You are an expert exam question setter for {class_name} {subject_name}.

Generate the MOST IMPORTANT exam questions for the chapter below, organised strictly by mark weight.
Questions MUST collectively cover ALL of these syllabus topics: {topic_block}

Chapter: {chapter_title}
Topics: {topic_block}

Return ONLY valid JSON in this exact schema (no markdown, no explanation):
{{
  "1_mark": [{{"question": "...", "type": "MCQ/very_short_answer"}},{{"question": "...", "type": "MCQ/very_short_answer"}},{{"question": "...", "type": "MCQ/very_short_answer"}}],
  "2_mark": [{{"question": "...", "type": "short_answer"}},{{"question": "...", "type": "short_answer"}},{{"question": "...", "type": "short_answer"}}],
  "3_mark": [{{"question": "...", "type": "brief_answer"}},{{"question": "...", "type": "brief_answer"}},{{"question": "...", "type": "brief_answer"}}],
  "5_mark": [{{"question": "...", "type": "medium_answer"}},{{"question": "...", "type": "medium_answer"}},{{"question": "...", "type": "medium_answer"}}],
  "10_mark": [{{"question": "...", "type": "long_answer/essay"}},{{"question": "...", "type": "long_answer/essay"}},{{"question": "...", "type": "long_answer/essay"}}]
}}
Rules: 3 questions per mark bucket, total 15 questions. Specific to "{chapter_title}". Every listed topic must be addressed by at least one question. Pure JSON only."""
                raw_resp = await call_llm_api([{"role": "user", "content": generate_prompt}], max_tokens=1600)
                json_match = _re.search(r'\{[\s\S]*\}', raw_resp or "")
                if json_match:
                    parsed = json.loads(json_match.group())
                    mark_wise = {
                        "1":  parsed.get("1_mark",  []),
                        "2":  parsed.get("2_mark",  []),
                        "3":  parsed.get("3_mark",  []),
                        "5":  parsed.get("5_mark",  []),
                        "10": parsed.get("10_mark", []),
                    }
                    flat_questions = []
                    for marks_str, qs in mark_wise.items():
                        for q_obj in qs:
                            text = (q_obj.get("question") if isinstance(q_obj, dict) else str(q_obj)).strip()
                            if text:
                                flat_questions.append({
                                    "question":   text,
                                    "marks":      int(marks_str),
                                    "type":       q_obj.get("type", "") if isinstance(q_obj, dict) else "",
                                    "year":       0,
                                    "paper_type": paper_type,
                                    "source":     "ai_generated",
                                })
                    if flat_questions:
                        if topics:
                            q_cov = _compute_topic_coverage(topics, "", flat_questions)
                            if q_cov["missing"]:
                                logger.warning(
                                    f"Questions for '{chapter_title}' missing topics ({q_cov['score']}%): {q_cov['missing'][:5]}"
                                )
                        pyq_doc = {
                            "id": str(uuid.uuid4()),
                            "subject_id": subject_id, "subject_name": subject_name,
                            "chapter_id": chapter_id, "chapter_title": chapter_title,
                            "pyqs": flat_questions,
                            "mark_wise": {k: [
                                (q.get("question", q) if isinstance(q, dict) else q) for q in v
                            ] for k, v in mark_wise.items()},
                            "total": len(flat_questions),
                            "source": "ai_important_questions", "ai_generated": True,
                            "created_at": now_iso, "updated_at": now_iso,
                        }
                        await db.ai_pyq_collections.update_one(
                            {"chapter_id": chapter_id}, {"$set": pyq_doc}, upsert=True,
                        )
                        cr["questions"] = f"generated:{len(flat_questions)}"
                    else:
                        cr["questions"] = "empty"
                else:
                    cr["questions"] = "no_json"
            except Exception as e:
                cr["questions"] = f"error: {str(e)[:60]}"

            # ── Step 3: Memory-trick flashcards ────────────────────────────────
            try:
                ch_topics = chapter.get("topics") or []
                flashcards = await _pipeline_generate_flashcards(notes_content, subject_name, chapter_title, class_name, count=25, topics=ch_topics or None)
                if flashcards:
                    if ch_topics:
                        fc_cov = _compute_topic_coverage(ch_topics, "", flashcards=flashcards)
                        if fc_cov["missing"]:
                            logger.warning(
                                f"Flashcards for '{chapter_title}' missing topics ({fc_cov['score']}%): {fc_cov['missing'][:5]}"
                            )
                    fc_doc = {
                        "id": str(uuid.uuid4()),
                        "subject_id": subject_id, "subject_name": subject_name,
                        "chapter_id": chapter_id, "chapter_title": chapter_title,
                        "flashcards": flashcards, "total": len(flashcards),
                        "pipeline_generated": True, "created_at": now_iso,
                    }
                    await db.flashcard_collections.update_one(
                        {"chapter_id": chapter_id, "pipeline_generated": True},
                        {"$set": fc_doc}, upsert=True,
                    )
                    cr["flashcards"] = f"generated:{len(flashcards)}"
                else:
                    cr["flashcards"] = "empty"
            except Exception as e:
                cr["flashcards"] = f"error: {str(e)[:60]}"

            # ── Step 4: Sync generated assets back onto chapter document ───────
            try:
                update_fields: dict = {"content_synced_at": now_iso}
                q_doc  = await db.ai_pyq_collections.find_one({"chapter_id": chapter_id}, {"_id": 0})
                fc_doc = await db.flashcard_collections.find_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True}, {"_id": 0}
                )
                if q_doc:
                    update_fields["has_important_questions"] = True
                    update_fields["questions_synced"]        = True
                    update_fields["mark_wise_questions"]     = q_doc.get("mark_wise", {})
                    update_fields["important_questions"]     = q_doc.get("pyqs", [])
                if fc_doc:
                    update_fields["has_flashcards"]    = True
                    update_fields["flashcards_synced"] = True
                    update_fields["memory_tricks"]     = fc_doc.get("flashcards", [])
                await db.chapters.update_one({"id": chapter_id}, {"$set": update_fields})
                cr["sync"] = "ok"
                _invalidate_content_cache("chapters")
            except Exception as e:
                cr["sync"] = f"error: {str(e)[:60]}"

            chapter_results.append(cr)

        _update_job(
            status="complete", progress=100,
            message=f"Pipeline complete: {total} chapters processed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            chapter_results=chapter_results,
        )

    except Exception as exc:
        _subject_pipeline_jobs.get(job_id, {}).update({
            "status": "error", "progress": 100,
            "message": str(exc)[:200],
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.error(f"Subject pipeline job {job_id} failed: {exc}")
    finally:
        _subject_pipeline_job_gc()


@router.post("/admin/subjects/{subject_id}/run-content-pipeline")
async def admin_run_content_pipeline(
    subject_id: str,
    background_tasks: BackgroundTasks,
    admin: dict = Depends(get_admin_user),
):
    """
    Agentic content pipeline: iterates chapters in order, skips any chapter
    where notes_generated=True, then runs notes → mark-wise questions (1/2/3/5/10)
    → memory-trick flashcards → sync back to chapter document — all in one
    sequential background job. Returns job_id immediately; poll status endpoint.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    job_id = str(uuid.uuid4())
    _subject_pipeline_jobs[job_id] = {
        "job_id":       job_id,
        "subject_id":   subject_id,
        "subject_name": subject.get("name", ""),
        "status":       "running",
        "progress":     0,
        "message":      "Pipeline starting…",
        "chapter_results": [],
        "started_at":   datetime.now(timezone.utc).timestamp(),
    }
    background_tasks.add_task(_run_subject_content_pipeline, job_id, subject_id)
    return {"job_id": job_id, "status": "running", "subject_id": subject_id}


@router.get("/admin/subjects/{subject_id}/content-pipeline-status")
async def admin_content_pipeline_status(
    subject_id: str,
    job_id: str,
    admin: dict = Depends(get_admin_user),
):
    """
    Poll the status of a run-content-pipeline background job.
    Returns per-chapter progress and final results when complete.
    """
    job = _subject_pipeline_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired (jobs expire after 2 hours)")
    if job.get("subject_id") != subject_id:
        raise HTTPException(status_code=403, detail="Job does not belong to this subject")
    return job


@router.post("/admin/subjects/{subject_id}/generate-mcqs-bulk")
async def admin_generate_mcqs_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Generate MCQs for ALL chapters of a subject using existing pipeline helper.
    Runs sequentially. Upserts to mcq_collections. Returns per-chapter results.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "total": 0, "generated": 0}

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")
    now_iso      = datetime.now(timezone.utc).isoformat()

    results = []
    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        content       = (chapter.get("content") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue
        if len(content) < 100:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "skipped", "reason": "content too short"})
            continue

        try:
            mcqs = await _pipeline_generate_mcqs(content, subject_name, chapter_title, class_name, count=20)
            if mcqs:
                mcq_doc = {
                    "id": str(uuid.uuid4()),
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "mcqs": mcqs,
                    "total": len(mcqs),
                    "pipeline_generated": True,
                    "created_at": now_iso,
                }
                await db.mcq_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": mcq_doc},
                    upsert=True,
                )
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "ok", "count": len(mcqs)})
            else:
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": "empty response"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": str(e)[:80]})

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    total_mcqs = sum(r.get("count", 0) for r in results)
    return {
        "subject_id": subject_id,
        "subject_name": subject_name,
        "total": len(chapters),
        "generated": ok_count,
        "total_mcqs": total_mcqs,
        "results": results,
    }


@router.post("/admin/subjects/{subject_id}/generate-flashcards-bulk")
async def admin_generate_flashcards_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Generate flashcards for ALL chapters of a subject using existing pipeline helper.
    Runs sequentially. Upserts to flashcard_collections. Returns per-chapter results.
    """
    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "total": 0, "generated": 0}

    subject_name = subject.get("name", "")
    paper_type   = subject.get("paper_type", "")
    class_name   = subject.get("className", "")
    now_iso      = datetime.now(timezone.utc).isoformat()

    results = []
    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        content       = (chapter.get("content") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue
        if len(content) < 100:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "skipped", "reason": "content too short"})
            continue

        try:
            flashcards = await _pipeline_generate_flashcards(content, subject_name, chapter_title, class_name, count=25, topics=chapter.get("topics"))
            if flashcards:
                fc_doc = {
                    "id": str(uuid.uuid4()),
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "flashcards": flashcards,
                    "total": len(flashcards),
                    "pipeline_generated": True,
                    "created_at": now_iso,
                }
                await db.flashcard_collections.update_one(
                    {"chapter_id": chapter_id, "pipeline_generated": True},
                    {"$set": fc_doc},
                    upsert=True,
                )
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "ok", "count": len(flashcards)})
            else:
                results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": "empty response"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": chapter_title, "status": "error", "reason": str(e)[:80]})

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    total_flashcards = sum(r.get("count", 0) for r in results)
    return {
        "subject_id": subject_id,
        "subject_name": subject_name,
        "total": len(chapters),
        "generated": ok_count,
        "total_flashcards": total_flashcards,
        "results": results,
    }


async def _gemini_web_search_pyqs(
    subject_name: str,
    class_name: str,
    paper_type: str,
    gemini_key: str,
) -> list:
    """
    Use Gemini with Google Search grounding to retrieve real PYQs from the web.
    Returns a flat list of {text, marks, year, sub_parts, source} dicts.
    """
    import re as _re

    if not gemini_key:
        return []

    search_prompt = (
        f"Search the web and find REAL previous year exam questions for:\n"
        f"Subject: {subject_name}\n"
        f"Class / Level: {class_name or 'Degree'} ({paper_type or 'Major'} paper)\n"
        f"Board / University: AHSEC / SEBA / Gauhati University / Dibrugarh University (Assam)\n\n"
        f"Collect as many actual board exam questions as you can find from years 2015–2024.\n"
        f"Return ONLY a JSON array — no markdown fences, no explanation:\n"
        f'[{{"question":"...", "year":2022, "marks":5}}, ...]\n'
        f"year must be an integer. marks must be an integer (use 0 if unknown).\n"
        f"Include ONLY real questions from actual exam papers, not practice questions or study notes."
    )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={gemini_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": search_prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 4000, "temperature": 0.1},
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Extract text from Gemini response
        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    text += part["text"]

        if not text.strip():
            return []

        # Find a JSON array in the response
        arr_match = _re.search(r'\[[\s\S]*\]', text)
        if not arr_match:
            return []

        raw_list = json.loads(arr_match.group())
        if not isinstance(raw_list, list):
            return []

        cleaned = []
        for q in raw_list:
            if not isinstance(q, dict):
                continue
            text_val = (q.get("question") or q.get("text") or "").strip()
            if not text_val:
                continue
            year_val = q.get("year", 0)
            if not isinstance(year_val, int) or not (2010 <= year_val <= 2025):
                year_val = 0
            marks_val = q.get("marks", 0)
            try:
                marks_val = int(marks_val)
            except (TypeError, ValueError):
                marks_val = 0
            cleaned.append({
                "text":       text_val,
                "marks":      str(marks_val) if marks_val else "",
                "year":       year_val,
                "sub_parts":  [],
                "source":     "web_search",
            })
        return cleaned

    except Exception as exc:
        logger.warning(f"Gemini web search PYQ failed: {exc}")
        return []


@router.post("/admin/subjects/{subject_id}/generate-pyqs-bulk")
async def admin_generate_pyqs_bulk(subject_id: str, admin: dict = Depends(get_admin_user)):
    """
    Mark-wise Most Important Questions Generator.

    Workflow:
      1. [OPTIONAL] Gemini Google Search grounding → collect real past questions as reference.
      2. [OPTIONAL] pyq_html_pages → questions from locally uploaded PDFs as reference.
      3. Merge reference pool (web first).
      4. Per chapter: AI generates 3×1M + 3×2M + 3×5M + 3×10M most important questions,
         inspired by real PYQ pool (if any) but always generating chapter-specific questions.
      5. Upsert per-chapter results into ai_pyq_collections with mark_wise structure.
    """
    import re as _re

    subject = await db.subjects.find_one({"id": subject_id}, {"_id": 0})
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    chapters = await db.chapters.find(
        {"subject_id": subject_id}, {"_id": 0}
    ).sort("order_index", 1).to_list(100)

    if not chapters:
        return {"subject_id": subject_id, "results": [], "total": 0, "generated": 0,
                "total_pyqs": 0, "message": "No chapters found"}

    subject_name = subject.get("name", "")
    class_name   = subject.get("className", "")
    paper_type   = (subject.get("paper_type") or "").upper()
    now_iso      = datetime.now(timezone.utc).isoformat()

    # ── Step 1 [PRIORITY]: Web search via Gemini Google Search grounding ──────
    web_questions = await _gemini_web_search_pyqs(
        subject_name=subject_name,
        class_name=class_name,
        paper_type=paper_type,
        gemini_key=_GEMINI_KEY,
    )
    logger.info(f"PYQ web search for '{subject_name}': {len(web_questions)} questions found")

    # ── Step 2 [SUPPLEMENT]: Collect questions from locally uploaded papers ────
    local_questions = []

    # Primary: match by subject_id stored on pyq_html_pages
    html_pages = await db.pyq_html_pages.find(
        {"subject_id": subject_id},
        {"_id": 0, "questions": 1, "raw_text": 1, "exam_year": 1, "paper_type": 1, "subject_name": 1, "slug": 1}
    ).sort("exam_year", -1).to_list(50)

    # Fallback: keyword match on subject_name
    if not html_pages and subject_name:
        kw = _re.escape(subject_name.split()[0])
        html_pages = await db.pyq_html_pages.find(
            {"subject_name": {"$regex": kw, "$options": "i"}},
            {"_id": 0, "questions": 1, "raw_text": 1, "exam_year": 1,
             "paper_type": 1, "subject_name": 1, "slug": 1}
        ).sort("exam_year", -1).to_list(50)

    # Fallback 2: look in pyq_uploads for slugs → html_pages
    if not html_pages:
        upload_docs = await db.pyq_uploads.find(
            {"subject_id": subject_id}, {"_id": 0, "slug": 1}
        ).to_list(50)
        slugs = [u["slug"] for u in upload_docs if u.get("slug")]
        if slugs:
            html_pages = await db.pyq_html_pages.find(
                {"slug": {"$in": slugs}},
                {"_id": 0, "questions": 1, "raw_text": 1, "exam_year": 1,
                 "paper_type": 1, "subject_name": 1, "slug": 1}
            ).to_list(50)

    for page in html_pages:
        year  = int(page.get("exam_year") or 0)
        ptype = page.get("paper_type", "")
        for q in (page.get("questions") or []):
            text = (q.get("text") or q.get("question_text") or q.get("q") or "").strip()
            if text:
                local_questions.append({
                    "text":       text,
                    "marks":      str(q.get("marks") or ""),
                    "year":       year,
                    "paper_type": ptype,
                    "sub_parts":  q.get("sub_parts") or [],
                    "source":     "uploaded_paper",
                })
    logger.info(f"PYQ local papers for '{subject_name}': {len(local_questions)} questions from {len(html_pages)} papers")

    # ── Step 3: Merge pools (web first = priority) ────────────────────────────
    # De-duplicate by question text (first 80 chars)
    seen_texts: set = set()
    question_pool = []
    for q in web_questions + local_questions:
        fingerprint = q["text"][:80].lower().strip()
        if fingerprint not in seen_texts:
            seen_texts.add(fingerprint)
            question_pool.append({**q, "idx": len(question_pool)})

    # pool_text helper kept for potential future use (not used in mark-wise generation)
    def _pool_text(pool):
        lines = []
        for q in pool:
            marks_str = f" [{q['marks']} marks]" if q["marks"] else ""
            year_str  = f" [{q['year']}]" if q["year"] else ""
            text_trunc = q["text"][:200]
            lines.append(f"{q['idx']}. {text_trunc}{marks_str}{year_str}")
        return "\n".join(lines)

    # ── Step 3: Per-chapter mark-wise important question generation ───────────
    # Build a reference pool snippet (first 60 real questions) to inspire AI
    pool_snippet = ""
    if question_pool:
        sample = question_pool[:60]
        pool_snippet = "\n".join(
            f"- {q['text'][:180]}" + (f" [{q['marks']}M]" if q.get("marks") else "")
            for q in sample
        )

    results = []
    for chapter in chapters:
        chapter_id    = chapter.get("id", "")
        chapter_title = (chapter.get("title") or "").strip()
        topics        = chapter.get("topics") or []
        description   = (chapter.get("description") or "").strip()

        if not chapter_title:
            results.append({"chapter_id": chapter_id, "status": "skipped", "reason": "no title"})
            continue

        topic_block = ""
        if topics:
            topic_block = ", ".join(str(t) for t in topics[:15])
        elif description:
            topic_block = description[:200]
        else:
            topic_block = chapter_title

        pool_ref = f"\n\nReference questions from past papers (use as inspiration, do NOT copy verbatim):\n{pool_snippet}" if pool_snippet else ""

        generate_prompt = f"""You are an expert exam question setter for {class_name} {subject_name}.

Generate the MOST IMPORTANT exam questions for the chapter below, organised strictly by mark weight.
These should be high-probability questions a student must prepare.

Chapter: {chapter_title}
Topics: {topic_block}{pool_ref}

Return ONLY valid JSON in this exact schema (no markdown, no explanation):
{{
  "1_mark": [
    {{"question": "...", "type": "MCQ/very_short_answer"}},
    {{"question": "...", "type": "MCQ/very_short_answer"}},
    {{"question": "...", "type": "MCQ/very_short_answer"}}
  ],
  "2_mark": [
    {{"question": "...", "type": "short_answer"}},
    {{"question": "...", "type": "short_answer"}},
    {{"question": "...", "type": "short_answer"}}
  ],
  "3_mark": [
    {{"question": "...", "type": "brief_answer"}},
    {{"question": "...", "type": "brief_answer"}},
    {{"question": "...", "type": "brief_answer"}}
  ],
  "5_mark": [
    {{"question": "...", "type": "medium_answer"}},
    {{"question": "...", "type": "medium_answer"}},
    {{"question": "...", "type": "medium_answer"}}
  ],
  "10_mark": [
    {{"question": "...", "type": "long_answer/essay"}},
    {{"question": "...", "type": "long_answer/essay"}},
    {{"question": "...", "type": "long_answer/essay"}}
  ]
}}

Rules:
- 1-mark: MCQ options OR one-word/one-line answers
- 2-mark: short answers (2–3 sentences)
- 3-mark: brief answers with 3 clear points (1 mark each)
- 5-mark: medium answers with points/explanation
- 10-mark: detailed essay or long-answer questions
- Questions must be specific to "{chapter_title}", not generic
- Exactly 3 questions per mark bucket, total 15 questions
- Pure JSON only, no markdown fences"""

        try:
            raw_resp = await call_llm_api(
                [{"role": "user", "content": generate_prompt}],
                max_tokens=1600,
            )
            if not raw_resp:
                results.append({"chapter_id": chapter_id, "title": chapter_title,
                                 "status": "skipped", "reason": "empty generator response"})
                continue

            # Extract JSON object from response
            json_match = _re.search(r'\{[\s\S]*\}', raw_resp)
            if not json_match:
                results.append({"chapter_id": chapter_id, "title": chapter_title,
                                 "status": "skipped", "reason": "no JSON object returned"})
                continue

            parsed = json.loads(json_match.group())

            # Flatten into a flat list with marks field (backward-compatible with LearnPage)
            mark_wise = {
                "1":  parsed.get("1_mark",  []),
                "2":  parsed.get("2_mark",  []),
                "3":  parsed.get("3_mark",  []),
                "5":  parsed.get("5_mark",  []),
                "10": parsed.get("10_mark", []),
            }
            flat_questions = []
            for marks_str, qs in mark_wise.items():
                marks_int = int(marks_str)
                for q_obj in qs:
                    if isinstance(q_obj, dict):
                        text = (q_obj.get("question") or "").strip()
                    else:
                        text = str(q_obj).strip()
                    if text:
                        flat_questions.append({
                            "question":   text,
                            "marks":      marks_int,
                            "type":       q_obj.get("type", "") if isinstance(q_obj, dict) else "",
                            "year":       0,
                            "paper_type": paper_type,
                            "sub_parts":  [],
                            "source":     "ai_generated",
                        })

            if not flat_questions:
                results.append({"chapter_id": chapter_id, "title": chapter_title,
                                 "status": "skipped", "reason": "no questions generated"})
                continue

            pyq_doc = {
                "id":            str(uuid.uuid4()),
                "subject_id":    subject_id,
                "subject_name":  subject_name,
                "chapter_id":    chapter_id,
                "chapter_title": chapter_title,
                "pyqs":          flat_questions,
                "mark_wise":     {k: [
                    (q.get("question", q) if isinstance(q, dict) else q)
                    for q in v
                ] for k, v in mark_wise.items()},
                "total":         len(flat_questions),
                "source":        "ai_important_questions",
                "ai_generated":  True,
                "created_at":    now_iso,
                "updated_at":    now_iso,
            }
            await db.ai_pyq_collections.update_one(
                {"chapter_id": chapter_id},
                {"$set": pyq_doc},
                upsert=True,
            )
            results.append({"chapter_id": chapter_id, "title": chapter_title,
                             "status": "ok", "count": len(flat_questions)})

        except (json.JSONDecodeError, ValueError) as parse_err:
            results.append({"chapter_id": chapter_id, "title": chapter_title,
                             "status": "error", "reason": f"parse: {str(parse_err)[:60]}"})
        except Exception as e:
            results.append({"chapter_id": chapter_id, "title": chapter_title,
                             "status": "error", "reason": str(e)[:80]})

    ok_count   = sum(1 for r in results if r.get("status") == "ok")
    total_pyqs = sum(r.get("count", 0) for r in results)
    web_count   = sum(1 for q in question_pool if q.get("source") == "web_search")
    local_count = sum(1 for q in question_pool if q.get("source") == "uploaded_paper")
    return {
        "subject_id":        subject_id,
        "subject_name":      subject_name,
        "total":             len(chapters),
        "generated":         ok_count,
        "total_pyqs":        total_pyqs,
        "pool_size":         len(question_pool),
        "web_found":         web_count,
        "local_found":       local_count,
        "papers_used":       len(html_pages),
        "results":           results,
    }


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
        raise HTTPException(status_code=404, detail="No chapters found")
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
    # Decrement subject chapter count
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

