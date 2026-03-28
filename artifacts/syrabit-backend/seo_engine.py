"""
Syrabit.ai — Programmatic SEO Engine
Generates thousands of search-indexed educational pages from MongoDB academic data.

Collections:
  - topics:     granular concepts under chapters (auto-extracted or admin-created)
  - seo_pages:  AI-generated study content per topic × page_type

URL pattern (4-segment):
  /{board}/{class}/{subject}/{topic}
  /{board}/{class}/{subject}/{topic}/{page_type}
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import Response, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from typing import Any, Callable, Coroutine, List, Optional
from datetime import datetime, timezone
import asyncio, uuid, re, logging, json, html as html_mod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/seo", tags=["SEO Engine"])

_db: Optional[AsyncIOMotorDatabase] = None
_call_llm: Optional[Callable[..., Coroutine[Any, Any, str]]] = None
_get_admin_fn: Optional[Callable[..., Coroutine[Any, Any, dict]]] = None
_security = HTTPBearer(auto_error=False)


def init_seo_engine(db: AsyncIOMotorDatabase, call_llm_api: Callable, get_admin_user_fn: Callable):
    global _db, _call_llm, _get_admin_fn
    _db = db
    _call_llm = call_llm_api
    _get_admin_fn = get_admin_user_fn


async def _require_admin(creds: Optional[HTTPAuthorizationCredentials] = Depends(_security)):
    if _get_admin_fn is None:
        raise HTTPException(status_code=503, detail="Auth not initialized")
    return await _get_admin_fn(creds=creds)


def _slug(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s]+', '-', s)
    return re.sub(r'-+', '-', s).strip('-')


PAGE_TYPES = ["notes", "definition", "important-questions", "mcqs", "examples"]

PROMPTS = {
    "notes": """You are an expert {board} teacher for {class_name} and a GEO (Generative Engine Optimization) specialist.

Topic: {topic}
Subject: {subject} | Class: {class_name} | Board: {board}

Write study notes using EXACTLY this structure — all sections required:

## Summary
[40-60 words: what {topic} is, why it matters, and its importance for {board} exam. Start with "According to the {board} syllabus..."]

## Definition
[Precise academic definition in 2-3 sentences using standard {board} terminology. Cite the textbook: "As defined in NCERT/SCERT {subject}..."]

## Explanation
[Detailed explanation 250-350 words. Cover core concepts, sub-topics, and connections. Include at least one citation like "As per the {board} {class_name} curriculum..."]

## Solved Examples
Example 1: [Complete step-by-step solution]
Example 2: [Complete step-by-step solution]
Example 3: [Complete step-by-step solution]

## Previous Year Questions (PYQs)
[5 questions that appear in {board} {class_name} exams, with model answers — include 1-mark, 2-mark, and 3-5 mark types. Format: "Q (AHSEC 20XX, X marks): ..."]

## Key Points
[6-8 bullet points for last-minute revision before the {board} exam]

## Frequently Asked Questions
Q1: What is {topic} in {subject}?
A1: [Concise answer citing {board} syllabus]
Q2: Why is {topic} important for {board} exams?
A2: [Answer with exam frequency data]
Q3: [Common student question about {topic}]
A3: [Clear answer]

Language: simple and clear for {class_name} students in Assam. Every section must be complete and exam-focused. Use authoritative framing throughout.""",

    "definition": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Class: {class_name} | Board: {board}

Write a definition article using EXACTLY this structure:

## Summary
[40-60 words: what {topic} means, its significance, and when students encounter it in {board} exams]

## Definition of {topic}
[Precise, exam-ready academic definition in 2-3 sentences]

## Meaning and Explanation
[Explain in simple terms — what it means, why it matters, how it connects to the syllabus]

## Characteristics / Properties
[4-6 key characteristics or properties as a bullet list]

## Real-World Examples
[3-4 relatable, easy-to-understand examples]

## Related Concepts
[3-4 related topics from the {board} {class_name} {subject} syllabus]

## Exam Questions on This Definition
[3 commonly asked questions in {board} exams with concise model answers]

Keep language simple for {class_name} students in Assam.""",

    "important-questions": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Class: {class_name} | Board: {board}

Create a question bank using EXACTLY this structure:

## Summary
[40-60 words: overview of {topic} and which types of questions appear in {board} exams]

## 1-Mark Questions
[5 questions with one-line answers — test basic recall]

## 2-Mark Questions
[5 questions with 2-3 sentence answers — test understanding]

## 3-Mark Questions
[4 questions with structured answers — test application]

## 5-Mark Questions (Long Answer)
[3 questions with detailed, exam-ready answers — test analysis]

## Previous Year Questions (PYQs)
[4-5 actual-style questions from past {board} exams on {topic}, with complete answers]

All answers must follow {board} marking scheme. Use exam-standard language.""",

    "mcqs": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Class: {class_name} | Board: {board}

Create 15 MCQs using EXACTLY this structure:

## Summary
[40-60 words: what {topic} concepts these MCQs test, aligned with {board} exam pattern]

## Easy Level (MCQs 1-5)
[Test basic recall and definitions — each with 4 options A/B/C/D, correct answer, brief explanation]

## Medium Level (MCQs 6-10)
[Test understanding and application — each with 4 options, correct answer, explanation]

## Hard Level (MCQs 11-15)
[Test analysis and problem-solving — each with 4 options, correct answer, detailed explanation]

Format each MCQ as:
Q: [question]
A) B) C) D)
Answer: [letter]
Explanation: [1-2 sentences]

Match {board} exam pattern and difficulty level.""",

    "examples": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Class: {class_name} | Board: {board}

Create a solved examples guide using EXACTLY this structure:

## Summary
[40-60 words: what types of problems on {topic} appear in {board} exams and what skills they test]

## Basic Examples
Example 1: [Problem statement] → [Complete step-by-step solution]
Example 2: [Problem statement] → [Complete step-by-step solution]
Example 3: [Problem statement] → [Complete step-by-step solution]

## Intermediate Examples
Example 4: [Problem statement] → [Complete step-by-step solution]
Example 5: [Problem statement] → [Complete step-by-step solution]

## Exam-Level Examples
Example 6: [Problem matching {board} exam difficulty] → [Complete solution with all steps]
Example 7: [Problem matching {board} exam difficulty] → [Complete solution with all steps]

## Practice Problems (Try Yourself)
[5 unsolved problems with answers only — for student practice]

Show complete working for all solved examples. Use {board} exam-standard notation and methods.""",
}


class TopicCreate(BaseModel):
    chapter_id: str
    title: str
    definition: Optional[str] = ""
    examples: Optional[str] = ""
    order: Optional[int] = 0

class TopicUpdate(BaseModel):
    title: Optional[str] = None
    definition: Optional[str] = None
    examples: Optional[str] = None
    order: Optional[int] = None
    status: Optional[str] = None

class GenerateRequest(BaseModel):
    topic_id: Optional[str] = None
    page_types: Optional[List[str]] = None
    batch: Optional[bool] = False


async def _resolve_hierarchy(topic: dict) -> dict:
    if _db is None:
        return {}
    chapter = await _db.chapters.find_one({"id": topic.get("chapter_id", "")}, {"_id": 0})
    if not chapter:
        return {}
    subject = await _db.subjects.find_one({"id": chapter.get("subject_id", "")}, {"_id": 0})
    if not subject:
        return {}
    stream = await _db.streams.find_one({"id": subject.get("stream_id", "")}, {"_id": 0})
    cls = await _db.classes.find_one({"id": stream.get("class_id", "")}, {"_id": 0}) if stream else None
    board = await _db.boards.find_one({"id": cls.get("board_id", "")}, {"_id": 0}) if cls else None
    return {
        "chapter": chapter,
        "subject": subject,
        "stream": stream,
        "class": cls,
        "board": board,
        "board_slug": board.get("slug", "") if board else "",
        "class_slug": cls.get("slug", "") if cls else "",
        "stream_slug": stream.get("slug", "") if stream else "",
        "subject_slug": subject.get("slug", ""),
        "chapter_slug": _slug(chapter.get("title", "")),
    }


# ─── ADMIN: Topic CRUD ──────────────────────────────────────────────────────

@router.get("/topics")
async def list_topics(chapter_id: Optional[str] = None, _admin: dict = Depends(_require_admin)):
    query = {"chapter_id": chapter_id} if chapter_id else {}
    topics = await _db.topics.find(query, {"_id": 0}).sort("order", 1).to_list(1000)
    return topics


@router.post("/topics")
async def create_topic(data: TopicCreate, _admin: dict = Depends(_require_admin)):
    chapter = await _db.chapters.find_one({"id": data.chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    topic = {
        "id": f"topic-{uuid.uuid4().hex[:8]}",
        "chapter_id": data.chapter_id,
        "subject_id": chapter.get("subject_id", ""),
        "title": data.title,
        "slug": _slug(data.title),
        "definition": data.definition or "",
        "examples": data.examples or "",
        "order": data.order or 0,
        "status": "published",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db.topics.insert_one(topic)
    topic.pop("_id", None)
    return topic


@router.patch("/topics/{topic_id}")
async def update_topic(topic_id: str, data: TopicUpdate, _admin: dict = Depends(_require_admin)):
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if "title" in updates:
        updates["slug"] = _slug(updates["title"])
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await _db.topics.update_one({"id": topic_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"message": "Updated"}


@router.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str, _admin: dict = Depends(_require_admin)):
    await _db.topics.delete_one({"id": topic_id})
    await _db.seo_pages.delete_many({"topic_id": topic_id})
    return {"message": "Deleted"}


# ─── ADMIN: Auto-extract topics from chapters ───────────────────────────────

@router.post("/extract-topics")
async def extract_topics_from_chapters(subject_id: Optional[str] = None, _admin: dict = Depends(_require_admin)):
    query = {"subject_id": subject_id} if subject_id else {}
    chapters = await _db.chapters.find(query, {"_id": 0}).to_list(500)

    created = 0
    for ch in chapters:
        existing = await _db.topics.count_documents({"chapter_id": ch["id"]})
        if existing > 0:
            continue

        title = ch.get("title", "")
        if not title:
            continue

        topic = {
            "id": f"topic-{uuid.uuid4().hex[:8]}",
            "chapter_id": ch["id"],
            "subject_id": ch.get("subject_id", ""),
            "title": title,
            "slug": _slug(title),
            "definition": ch.get("description", ""),
            "examples": "",
            "order": ch.get("order_index", ch.get("chapter_number", 0)),
            "status": "published",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await _db.topics.insert_one(topic)
        created += 1

    return {"message": f"Extracted {created} topics from {len(chapters)} chapters", "created": created}


# ─── ADMIN: AI Content Generation ───────────────────────────────────────────

async def _generate_single_page(topic: dict, page_type: str, hierarchy: dict):
    board_name = hierarchy.get("board", {}).get("name", "AHSEC")
    class_name = hierarchy.get("class", {}).get("name", "Class 12")
    subject_name = hierarchy.get("subject", {}).get("name", "")
    chapter_title = hierarchy.get("chapter", {}).get("title", "")

    prompt_template = PROMPTS.get(page_type)
    if not prompt_template:
        return None

    prompt = prompt_template.format(
        board=board_name,
        class_name=class_name,
        subject=subject_name,
        chapter=chapter_title,
        topic=topic["title"],
    )

    messages = [
        {"role": "system", "content": f"You are an expert {board_name} teacher specializing in {subject_name} for {class_name}. Create educational content that is comprehensive, exam-focused, and easy to understand for students in Assam, India."},
        {"role": "user", "content": prompt},
    ]

    try:
        content = await asyncio.wait_for(_call_llm(messages, max_tokens=2048), timeout=120)
    except asyncio.TimeoutError:
        logger.error(f"LLM timeout generating {page_type} for {topic['title']}")
        return None
    except Exception as e:
        logger.error(f"LLM error generating {page_type} for {topic['title']}: {type(e).__name__}")
        return None

    word_count = len(content.split())
    if word_count < 100:
        logger.warning(f"Generated content too short ({word_count} words) for {topic['title']} / {page_type}")
        return None

    type_title_labels = {
        "notes": "Notes",
        "definition": "Definition & Meaning",
        "important-questions": "Important Questions",
        "mcqs": "MCQ Practice",
        "examples": "Solved Examples",
    }

    grade_match = re.search(r'\d+', class_name)
    grade_str = f"Class {grade_match.group()}" if grade_match else class_name

    h = hierarchy
    title = f"{topic['title']} {type_title_labels.get(page_type, page_type.title())} – {board_name} {grade_str} {subject_name}"
    meta_desc = (
        f"Study {topic['title']} with comprehensive {type_title_labels.get(page_type, 'notes').lower()} "
        f"for {board_name} {grade_str} {subject_name}. Covers definitions, examples, and important "
        f"questions aligned with {board_name} syllabus for Assam students."
    )

    page = {
        "id": f"seo-{uuid.uuid4().hex[:8]}",
        "topic_id": topic["id"],
        "topic_slug": topic["slug"],
        "chapter_slug": h.get("chapter_slug", ""),
        "subject_slug": h.get("subject_slug", ""),
        "stream_slug": h.get("stream_slug", ""),
        "class_slug": h.get("class_slug", ""),
        "board_slug": h.get("board_slug", ""),
        "page_type": page_type,
        "title": title,
        "content": content,
        "meta_description": meta_desc[:160],
        "word_count": word_count,
        "subject_name": subject_name,
        "class_name": class_name,
        "board_name": board_name,
        "chapter_title": h.get("chapter", {}).get("title", ""),
        "topic_title": topic["title"],
        "status": "published",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    await _db.seo_pages.replace_one(
        {"topic_id": topic["id"], "page_type": page_type},
        page,
        upsert=True,
    )
    return page


@router.post("/generate")
async def generate_seo_content(data: GenerateRequest, background_tasks: BackgroundTasks, _admin: dict = Depends(_require_admin)):
    page_types = data.page_types or PAGE_TYPES

    if data.batch:
        topics = await _db.topics.find({"status": "published"}, {"_id": 0}).to_list(5000)
        if not topics:
            raise HTTPException(status_code=404, detail="No topics found. Run extract-topics first.")

        background_tasks.add_task(_batch_generate, topics, page_types)
        return {
            "message": f"Batch generation started for {len(topics)} topics × {len(page_types)} page types",
            "total_pages": len(topics) * len(page_types),
        }

    if not data.topic_id:
        raise HTTPException(status_code=400, detail="Provide topic_id or set batch=true")

    topic = await _db.topics.find_one({"id": data.topic_id}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    hierarchy = await _resolve_hierarchy(topic)
    if not hierarchy:
        raise HTTPException(status_code=404, detail="Could not resolve topic hierarchy")

    results = []
    for pt in page_types:
        page = await _generate_single_page(topic, pt, hierarchy)
        if page:
            results.append({"page_type": pt, "word_count": page["word_count"], "id": page["id"]})

    return {"message": f"Generated {len(results)} pages", "pages": results}


async def _batch_generate(topics: list, page_types: list):
    total = 0
    errors = 0
    for topic in topics:
        try:
            hierarchy = await _resolve_hierarchy(topic)
            if not hierarchy:
                continue
            for pt in page_types:
                existing = await _db.seo_pages.find_one(
                    {"topic_id": topic["id"], "page_type": pt},
                    {"_id": 0, "id": 1}
                )
                if existing:
                    continue
                try:
                    page = await _generate_single_page(topic, pt, hierarchy)
                    if page:
                        total += 1
                except Exception as e:
                    logger.error(f"Generation error for {topic['title']}/{pt}: {e}")
                    errors += 1
        except Exception as e:
            logger.error(f"Hierarchy error for topic {topic.get('id')}: {e}")
            errors += 1

    logger.info(f"Batch generation complete: {total} pages generated, {errors} errors")
    await _db.seo_generation_log.insert_one({
        "id": f"genlog-{uuid.uuid4().hex[:8]}",
        "total_generated": total,
        "errors": errors,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })


# ─── ADMIN: Stats ───────────────────────────────────────────────────────────

@router.get("/stats")
async def seo_stats(_admin: dict = Depends(_require_admin)):
    total_topics = await _db.topics.count_documents({})
    published_topics = await _db.topics.count_documents({"status": "published"})
    total_pages = await _db.seo_pages.count_documents({})
    published_pages = await _db.seo_pages.count_documents({"status": "published"})

    by_type = {}
    for pt in PAGE_TYPES:
        by_type[pt] = await _db.seo_pages.count_documents({"page_type": pt})

    last_log = await _db.seo_generation_log.find_one(
        {}, {"_id": 0}, sort=[("completed_at", -1)]
    )

    return {
        "topics": {"total": total_topics, "published": published_topics},
        "pages": {"total": total_pages, "published": published_pages, "by_type": by_type},
        "last_generation": last_log,
    }


# ─── ADMIN: Page management ─────────────────────────────────────────────────

@router.get("/pages")
async def list_seo_pages(
    topic_id: Optional[str] = None,
    page_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _admin: dict = Depends(_require_admin),
):
    query = {}
    if topic_id:
        query["topic_id"] = topic_id
    if page_type:
        query["page_type"] = page_type
    if status:
        query["status"] = status

    pages = await _db.seo_pages.find(query, {"_id": 0, "content": 0}).sort("generated_at", -1).skip(offset).limit(limit).to_list(limit)
    total = await _db.seo_pages.count_documents(query)
    return {"pages": pages, "total": total}


@router.patch("/pages/{page_id}/status")
async def update_page_status(page_id: str, status: str = "published", _admin: dict = Depends(_require_admin)):
    if status not in ("published", "draft", "archived"):
        raise HTTPException(status_code=400, detail="Invalid status")
    result = await _db.seo_pages.update_one(
        {"id": page_id},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"message": f"Status updated to {status}"}


# ─── PUBLIC: Serve SEO pages ────────────────────────────────────────────────

async def _inject_qa(page: dict) -> dict:
    """Attach published QA pairs to a page dict (best-effort)."""
    try:
        qa = await _db.qa_pairs.find(
            {
                "board_slug": page.get("board_slug", ""),
                "class_slug": page.get("class_slug", ""),
                "subject_slug": page.get("subject_slug", ""),
                "topic_slug": page.get("topic_slug", ""),
                "status": "published",
            },
            {"_id": 0},
        ).sort("upvotes", -1).limit(20).to_list(20)
        page["qa_pairs"] = qa
    except Exception:
        page["qa_pairs"] = []
    return page


@router.get("/page/{board}/{class_slug}/{subject_slug}/{topic_slug}")
async def get_seo_page_default(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    page = await _db.seo_pages.find_one(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "topic_slug": topic_slug,
            "page_type": "notes",
            "status": "published",
        },
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return await _inject_qa(page)


@router.get("/page/{board}/{class_slug}/{subject_slug}/{topic_slug}/{page_type}")
async def get_seo_page_typed(board: str, class_slug: str, subject_slug: str, topic_slug: str, page_type: str):
    if page_type not in PAGE_TYPES:
        raise HTTPException(status_code=404, detail="Invalid page type")
    page = await _db.seo_pages.find_one(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "topic_slug": topic_slug,
            "page_type": page_type,
            "status": "published",
        },
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return await _inject_qa(page)


def _md_to_html(text: str) -> str:
    if not text:
        return ""
    h = html_mod.escape(text)
    h = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', h, flags=re.MULTILINE)
    h = re.sub(r'^### (.+)$', r'<h3>\1</h3>', h, flags=re.MULTILINE)
    h = re.sub(r'^## (.+)$', r'<h2>\1</h2>', h, flags=re.MULTILINE)
    h = re.sub(r'^# (.+)$', r'<h1>\1</h1>', h, flags=re.MULTILINE)
    h = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', h)
    h = re.sub(r'\*(.+?)\*', r'<em>\1</em>', h)
    h = re.sub(r'^- (.+)$', r'<li>\1</li>', h, flags=re.MULTILINE)
    h = re.sub(r'\n\n', '</p><p>', h)
    return f"<p>{h}</p>"


def _render_seo_html(page: dict, page_url: str) -> str:
    title = html_mod.escape(page.get("title", ""))
    desc = html_mod.escape(page.get("meta_description", ""))
    topic = html_mod.escape(page.get("topic_title", ""))
    subject = html_mod.escape(page.get("subject_name", ""))
    board = html_mod.escape(page.get("board_name", ""))
    cls = html_mod.escape(page.get("class_name", ""))
    chapter = html_mod.escape(page.get("chapter_title", ""))
    content_html = _md_to_html(page.get("content", ""))
    generated = page.get("generated_at", "")
    updated = page.get("updated_at", generated)

    graph_nodes = [
        {
            "@type": "Article",
            "headline": page.get("title", ""),
            "description": page.get("meta_description", ""),
            "author": {"@type": "Organization", "name": "Syrabit.ai", "url": "https://syrabit.ai"},
            "publisher": {
                "@type": "Organization",
                "name": "Syrabit.ai",
                "url": "https://syrabit.ai",
                "logo": {"@type": "ImageObject", "url": "https://syrabit.ai/icons/icon-192x192.png"},
            },
            "datePublished": generated,
            "dateModified": updated,
            "image": "https://syrabit.ai/opengraph.jpg",
            "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
            "educationalLevel": f"{cls} {board}".strip(),
            "about": {"@type": "Thing", "name": page.get("topic_title", "")},
            "isPartOf": {"@type": "WebSite", "@id": "https://syrabit.ai", "name": "Syrabit.ai"},
            "inLanguage": "en-IN",
        },
        {
            "@type": "Course",
            "name": f"{topic} — {cls} {board}".strip(),
            "description": page.get("meta_description", ""),
            "provider": {"@type": "Organization", "name": "Syrabit.ai", "sameAs": "https://syrabit.ai"},
            "educationalLevel": f"{cls} {board}".strip(),
            "url": page_url,
            "inLanguage": "en-IN",
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://syrabit.ai"},
                {"@type": "ListItem", "position": 2, "name": "Library", "item": "https://syrabit.ai/library"},
                {"@type": "ListItem", "position": 3, "name": subject, "item": "https://syrabit.ai/library"},
                {"@type": "ListItem", "position": 4, "name": topic, "item": page_url},
            ],
        },
    ]

    qa_pairs = page.get("qa_pairs", [])
    faq_items = []
    if qa_pairs:
        for qp in qa_pairs[:10]:
            faq_items.append({
                "@type": "Question",
                "name": qp.get("question", ""),
                "acceptedAnswer": {"@type": "Answer", "text": qp.get("answer", "")},
            })
    else:
        raw_content = page.get("content", "")
        lines = raw_content.split("\n") if raw_content else []
        current_q = None
        for line in lines:
            stripped = line.strip().lstrip("#").strip().replace("**", "").strip()
            if stripped.endswith("?") and len(stripped) > 15:
                current_q = stripped
            elif current_q and len(stripped) > 20:
                faq_items.append({
                    "@type": "Question",
                    "name": current_q,
                    "acceptedAnswer": {"@type": "Answer", "text": stripped},
                })
                current_q = None
                if len(faq_items) >= 10:
                    break

    if len(faq_items) >= 2:
        graph_nodes.append({"@type": "FAQPage", "mainEntity": faq_items})

    ld_json = json.dumps({"@context": "https://schema.org", "@graph": graph_nodes}, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en-IN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Syrabit.ai</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{html_mod.escape(page_url)}">
<meta property="og:site_name" content="Syrabit.ai">
<meta property="og:locale" content="en_IN">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{html_mod.escape(page_url)}">
<meta property="og:image" content="https://syrabit.ai/opengraph.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="article:published_time" content="{html_mod.escape(generated)}">
<meta property="article:modified_time" content="{html_mod.escape(updated)}">
<meta property="article:section" content="{subject}">
<meta property="article:tag" content="{topic}">
<meta property="article:tag" content="{subject}">
<meta property="article:tag" content="{board}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@SyrabitAI">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="https://syrabit.ai/opengraph.jpg">
<meta name="citation_title" content="{title}">
<meta name="citation_author" content="Syrabit.ai">
<meta name="citation_publication_date" content="{html_mod.escape(generated[:10] if generated else '')}">
<meta name="citation_online_date" content="{html_mod.escape(updated[:10] if updated else '')}">
<meta name="citation_publisher" content="Syrabit.ai">
<meta name="citation_public_url" content="{html_mod.escape(page_url)}">
<meta name="dc.title" content="{title}">
<meta name="dc.creator" content="Syrabit.ai">
<meta name="dc.subject" content="{subject} — {board} {cls}">
<meta name="dc.description" content="{desc}">
<meta name="dc.publisher" content="Syrabit.ai">
<meta name="dc.type" content="Text">
<meta name="dc.language" content="en-IN">
<meta name="dc.source" content="https://syrabit.ai">
<script type="application/ld+json">{ld_json}</script>
</head>
<body>
<header>
<nav aria-label="Breadcrumb">
<a href="https://syrabit.ai">Home</a> &rsaquo;
<a href="https://syrabit.ai/library">Library</a> &rsaquo;
<span>{subject}</span> &rsaquo;
<span>{topic}</span>
</nav>
<p><strong>{board}</strong> &middot; {cls} &middot; {subject} &middot; {chapter}</p>
</header>
<main>
<article>
<h1>{topic} — {board} {cls} {subject}</h1>
<p><em>{desc}</em></p>
{content_html}
</article>
<footer>
<p>Source: <a href="{html_mod.escape(page_url)}">Syrabit.ai — {topic}</a></p>
<p>&copy; Syrabit.ai — AI-powered exam prep for Assam Board students</p>
</footer>
</main>
</body>
</html>"""


@router.get("/html/{board}/{class_slug}/{subject_slug}/{topic_slug}", response_class=HTMLResponse)
async def get_seo_html_default(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    page = await _db.seo_pages.find_one(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "page_type": "notes", "status": "published"},
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    page = await _inject_qa(page)
    page_url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{topic_slug}"
    return HTMLResponse(content=_render_seo_html(page, page_url))


@router.get("/html/{board}/{class_slug}/{subject_slug}/{topic_slug}/{page_type}", response_class=HTMLResponse)
async def get_seo_html_typed(board: str, class_slug: str, subject_slug: str, topic_slug: str, page_type: str):
    if page_type not in PAGE_TYPES:
        raise HTTPException(status_code=404, detail="Invalid page type")
    page = await _db.seo_pages.find_one(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "page_type": page_type, "status": "published"},
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    page = await _inject_qa(page)
    page_url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{topic_slug}/{page_type}"
    return HTMLResponse(content=_render_seo_html(page, page_url))


@router.get("/page-types/{board}/{class_slug}/{subject_slug}/{topic_slug}")
async def get_available_page_types(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    pages = await _db.seo_pages.find(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "topic_slug": topic_slug,
            "status": "published",
        },
        {"_id": 0, "page_type": 1, "title": 1, "word_count": 1, "id": 1},
    ).to_list(10)
    return pages


@router.get("/related/{topic_slug}")
async def get_related_topics(topic_slug: str, chapter_id: Optional[str] = None, subject_id: Optional[str] = None):
    query = {"slug": topic_slug}
    if chapter_id:
        query["chapter_id"] = chapter_id
    if subject_id:
        query["subject_id"] = subject_id
    topic = await _db.topics.find_one(query, {"_id": 0})
    if not topic:
        return {"related": [], "prev": None, "next": None}

    same_chapter = await _db.topics.find(
        {"chapter_id": topic["chapter_id"], "id": {"$ne": topic["id"]}, "status": "published"},
        {"_id": 0}
    ).sort("order", 1).limit(5).to_list(5)

    chapter = await _db.chapters.find_one({"id": topic["chapter_id"]}, {"_id": 0})
    adjacent_topics = []
    if chapter:
        adj_chapters = await _db.chapters.find(
            {
                "subject_id": chapter["subject_id"],
                "id": {"$ne": chapter["id"]},
            },
            {"_id": 0, "id": 1, "title": 1},
        ).sort("order_index", 1).limit(3).to_list(3)

        for ac in adj_chapters:
            t = await _db.topics.find_one(
                {"chapter_id": ac["id"], "status": "published"},
                {"_id": 0}
            )
            if t:
                adjacent_topics.append(t)

    all_in_chapter = await _db.topics.find(
        {"chapter_id": topic["chapter_id"], "status": "published"},
        {"_id": 0}
    ).sort("order", 1).to_list(100)

    prev_topic = None
    next_topic = None
    for i, t in enumerate(all_in_chapter):
        if t["id"] == topic["id"]:
            if i > 0:
                prev_topic = all_in_chapter[i - 1]
            if i < len(all_in_chapter) - 1:
                next_topic = all_in_chapter[i + 1]
            break

    for t in same_chapter + adjacent_topics:
        hierarchy = await _resolve_hierarchy(t)
        t["seo_path"] = f"/{hierarchy.get('board_slug', '')}/{hierarchy.get('class_slug', '')}/{hierarchy.get('subject_slug', '')}/{t['slug']}" if hierarchy else ""

    if prev_topic:
        h = await _resolve_hierarchy(prev_topic)
        prev_topic["seo_path"] = f"/{h.get('board_slug', '')}/{h.get('class_slug', '')}/{h.get('subject_slug', '')}/{prev_topic['slug']}" if h else ""
    if next_topic:
        h = await _resolve_hierarchy(next_topic)
        next_topic["seo_path"] = f"/{h.get('board_slug', '')}/{h.get('class_slug', '')}/{h.get('subject_slug', '')}/{next_topic['slug']}" if h else ""

    return {
        "related": same_chapter + adjacent_topics,
        "prev": prev_topic,
        "next": next_topic,
    }


# ─── PUBLIC: Sitemap entries (JSON) ─────────────────────────────────────────

@router.get("/sitemap-entries")
async def get_sitemap_entries():
    pages = await _db.seo_pages.find(
        {"status": "published"},
        {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1, "chapter_slug": 1, "topic_slug": 1, "page_type": 1, "updated_at": 1},
    ).to_list(10000)

    entries = []
    for p in pages:
        path = f"/{p['board_slug']}/{p['class_slug']}/{p['subject_slug']}/{p['topic_slug']}"
        if p["page_type"] != "notes":
            path += f"/{p['page_type']}"
        entries.append({
            "url": path,
            "lastmod": p.get("updated_at", ""),
            "priority": "0.7" if p["page_type"] != "notes" else "0.8",
        })

    return {"entries": entries, "total": len(entries)}


# ─── PUBLIC: Dynamic sitemap XML ────────────────────────────────────────────

CORE_URLS = [
    ("https://syrabit.ai/", "weekly", "1.0"),
    ("https://syrabit.ai/pricing", "monthly", "0.8"),
    ("https://syrabit.ai/signup", "monthly", "0.9"),
    ("https://syrabit.ai/library", "weekly", "0.9"),
    ("https://syrabit.ai/curriculum", "weekly", "0.8"),
    ("https://syrabit.ai/exam-routine", "weekly", "0.8"),
    ("https://syrabit.ai/terms", "yearly", "0.3"),
    ("https://syrabit.ai/privacy", "yearly", "0.3"),
]

@router.get("/sitemap.xml", response_class=Response)
async def get_dynamic_sitemap():
    BASE = "https://syrabit.ai"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
                 ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">')

    for loc, freq, pri in CORE_URLS:
        lines.append(f"  <url><loc>{loc}</loc><changefreq>{freq}</changefreq>"
                     f"<priority>{pri}</priority><lastmod>{today}</lastmod></url>")

    pages = []
    try:
        pages = await _db.seo_pages.find(
            {"status": "published"},
            {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1,
             "chapter_slug": 1, "topic_slug": 1, "page_type": 1, "updated_at": 1},
        ).to_list(50000)
    except Exception:
        pass

    seen_topics = set()
    for p in pages:
        bs = p.get("board_slug")
        cs = p.get("class_slug")
        ss = p.get("subject_slug")
        ts = p.get("topic_slug")
        pt = p.get("page_type", "notes")
        if not all([bs, cs, ss, ts]):
            continue
        base_path = f"/{bs}/{cs}/{ss}/{ts}"
        path = base_path if pt == "notes" else f"{base_path}/{pt}"
        loc = f"{BASE}{path}"
        pri = "0.8" if pt == "notes" else "0.7"
        try:
            raw = p.get("updated_at", "")
            lastmod = raw[:10] if raw else today
        except Exception:
            lastmod = today
        lines.append(f"  <url><loc>{loc}</loc><changefreq>monthly</changefreq>"
                     f"<priority>{pri}</priority><lastmod>{lastmod}</lastmod></url>")
        html_loc = f"{BASE}/api/seo/html{path}"
        lines.append(f"  <url><loc>{html_loc}</loc><changefreq>monthly</changefreq>"
                     f"<priority>0.6</priority><lastmod>{lastmod}</lastmod></url>")
        seen_topics.add(base_path)

    lines.append("</urlset>")
    xml = "\n".join(lines)
    return Response(content=xml, media_type="application/xml; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600"})


# ─── PUBLIC: Browse by subject ──────────────────────────────────────────────

@router.get("/browse/{board}/{class_slug}/{subject_slug}")
async def browse_subject_topics(board: str, class_slug: str, subject_slug: str):
    pages = await _db.seo_pages.find(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "status": "published",
        },
        {"_id": 0, "content": 0},
    ).sort("chapter_slug", 1).to_list(5000)

    chapters = {}
    for p in pages:
        key = p["chapter_slug"]
        if key not in chapters:
            chapters[key] = {
                "chapter_slug": key,
                "chapter_title": p.get("chapter_title", key),
                "topics": {},
            }
        t_key = p["topic_slug"]
        if t_key not in chapters[key]["topics"]:
            chapters[key]["topics"][t_key] = {
                "topic_slug": t_key,
                "topic_title": p.get("topic_title", t_key),
                "page_types": [],
            }
        chapters[key]["topics"][t_key]["page_types"].append(p["page_type"])

    result = []
    for ch in chapters.values():
        ch["topics"] = list(ch["topics"].values())
        result.append(ch)

    return {"chapters": result, "total_topics": sum(len(ch["topics"]) for ch in result)}


# ─── ADMIN: Pilot content generation (AHSEC Class 11 – first N chapters) ─────

@router.post("/pilot")
async def generate_pilot_content(
    board_name: str = "AHSEC",
    class_name: str = "Class 11",
    subject_keyword: str = "maths",
    chapter_limit: int = 3,
    _admin: dict = Depends(_require_admin),
):
    """Generate seed content for the first `chapter_limit` chapters of a subject.
    Used to bootstrap pilot SEO pages before batch generation."""
    board = await _db.boards.find_one(
        {"name": {"$regex": board_name, "$options": "i"}}, {"_id": 0}
    )
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{board_name}' not found")

    cls = await _db.classes.find_one(
        {"board_id": board["id"], "name": {"$regex": class_name, "$options": "i"}}, {"_id": 0}
    )
    if not cls:
        raise HTTPException(status_code=404, detail=f"Class '{class_name}' not found under {board_name}")

    streams = await _db.streams.find({"class_id": cls["id"]}, {"_id": 0}).to_list(20)
    stream_ids = [s["id"] for s in streams]

    subject = await _db.subjects.find_one(
        {"stream_id": {"$in": stream_ids}, "name": {"$regex": subject_keyword, "$options": "i"}},
        {"_id": 0},
    )
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject matching '{subject_keyword}' not found")

    chapters = await _db.chapters.find(
        {"subject_id": subject["id"]}, {"_id": 0}
    ).sort("order_index", 1).limit(chapter_limit).to_list(chapter_limit)

    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found for this subject")

    created_topics = 0
    generated_pages = 0
    errors = 0

    for ch in chapters:
        existing = await _db.topics.find_one({"chapter_id": ch["id"]}, {"_id": 0, "id": 1})
        if existing:
            topic = await _db.topics.find_one({"chapter_id": ch["id"]}, {"_id": 0})
        else:
            topic = {
                "id": f"topic-{uuid.uuid4().hex[:8]}",
                "chapter_id": ch["id"],
                "subject_id": ch.get("subject_id", subject["id"]),
                "title": ch.get("title", ""),
                "slug": _slug(ch.get("title", "")),
                "definition": ch.get("description", ""),
                "examples": "",
                "order": ch.get("order_index", 0),
                "status": "published",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await _db.topics.insert_one(topic)
            topic.pop("_id", None)
            created_topics += 1

        if not topic or not topic.get("id"):
            continue

        hierarchy = await _resolve_hierarchy(topic)
        if not hierarchy:
            errors += 1
            continue

        for pt in PAGE_TYPES:
            existing_page = await _db.seo_pages.find_one(
                {"topic_id": topic["id"], "page_type": pt}, {"_id": 0, "id": 1}
            )
            if existing_page:
                continue
            try:
                page = await _generate_single_page(topic, pt, hierarchy)
                if page:
                    generated_pages += 1
            except Exception as e:
                logger.error(f"Pilot error {topic['title']}/{pt}: {e}")
                errors += 1

    return {
        "board": board_name,
        "class": class_name,
        "subject": subject.get("name"),
        "chapters_processed": len(chapters),
        "topics_created": created_topics,
        "pages_generated": generated_pages,
        "errors": errors,
        "message": f"Pilot complete: {generated_pages} pages generated for {len(chapters)} chapters",
    }
