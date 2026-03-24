"""
Syrabit.ai — Programmatic SEO Engine
Generates thousands of search-indexed educational pages from MongoDB academic data.

Collections:
  - topics:     granular concepts under chapters (auto-extracted or admin-created)
  - seo_pages:  AI-generated study content per topic × page_type

URL pattern:
  /{board}/{class}/{subject}/{chapter}/{topic}
  /{board}/{class}/{subject}/{chapter}/{topic}/{page_type}
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from typing import Any, Callable, Coroutine, List, Optional
from datetime import datetime, timezone
import asyncio, uuid, re, logging

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
    "notes": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Chapter: {chapter}
Subject: {subject}
Class: {class_name}
Board: {board}

Create comprehensive study notes with this exact structure:

## Definition
[Clear, exam-ready definition in 2-3 sentences]

## Detailed Explanation
[Thorough explanation with key concepts, 300+ words]

## Key Points to Remember
[Bullet list of 5-8 essential points]

## Solved Examples
[2-3 worked examples with step-by-step solutions]

## Exam Tips
[3-4 specific tips for scoring marks on this topic in {board} exams]

## Common Mistakes to Avoid
[3-4 mistakes students frequently make]

Keep language simple and accessible for Assam students. Use exam-relevant terminology.""",

    "definition": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Chapter: {chapter}
Subject: {subject}

Write a comprehensive definition article:

## Definition of {topic}
[Precise academic definition, 2-3 sentences]

## Meaning and Explanation
[Explain in simple terms what this concept means, why it matters]

## Characteristics / Properties
[List 4-6 key characteristics or properties]

## Real-World Examples
[3-4 relatable examples]

## Related Concepts
[Brief mention of 3-4 related topics students should also study]

## Frequently Asked Exam Questions
[3 commonly asked questions about this definition in {board} exams with brief answers]

Keep language simple for Assam students.""",

    "important-questions": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Chapter: {chapter}
Subject: {subject}

Create a comprehensive question bank:

## 1-Mark Questions (Very Short Answer)
[5 questions with brief answers]

## 2-Mark Questions (Short Answer)
[5 questions with concise answers]

## 3-Mark Questions
[3 questions with structured answers]

## 5-Mark Questions (Long Answer)
[3 questions with detailed, exam-ready answers]

## Previous Year Questions
[Note: Include 3-4 sample questions that typically appear in {board} exams for this topic]

All answers should be exam-ready and follow {board} marking scheme guidelines.""",

    "mcqs": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Chapter: {chapter}
Subject: {subject}

Create 15 Multiple Choice Questions:

## Easy Level (5 MCQs)
[Questions testing basic recall and definitions]

## Medium Level (5 MCQs)
[Questions testing understanding and application]

## Hard Level (5 MCQs)
[Questions testing analysis and problem-solving]

For each question provide:
- The question with 4 options (A, B, C, D)
- Correct answer
- Brief explanation of why that answer is correct

These should match {board} exam pattern and difficulty.""",

    "examples": """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Chapter: {chapter}
Subject: {subject}

Create a comprehensive examples guide:

## Basic Examples
[3-4 simple examples with step-by-step solutions]

## Intermediate Examples
[3-4 moderately difficult examples]

## Advanced / Exam-Level Examples
[2-3 examples matching {board} exam difficulty]

## Practice Problems
[5 unsolved problems for student practice, with answers at the end]

Show complete working for each solved example. Use exam-standard notation and methods.""",
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

    type_labels = {
        "notes": "Notes",
        "definition": "Definition",
        "important-questions": "Important Questions",
        "mcqs": "MCQs",
        "examples": "Examples",
    }

    h = hierarchy
    title = f"{topic['title']} — {type_labels.get(page_type, page_type.title())} | {subject_name} {class_name} {board_name}"
    meta_desc = f"{type_labels.get(page_type, '')} for {topic['title']} in {subject_name} ({class_name}, {board_name}). Comprehensive study material for AHSEC exam preparation."

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

@router.get("/page/{board}/{class_slug}/{subject_slug}/{chapter_slug}/{topic_slug}")
async def get_seo_page_default(board: str, class_slug: str, subject_slug: str, chapter_slug: str, topic_slug: str):
    page = await _db.seo_pages.find_one(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "chapter_slug": chapter_slug,
            "topic_slug": topic_slug,
            "page_type": "notes",
            "status": "published",
        },
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.get("/page/{board}/{class_slug}/{subject_slug}/{chapter_slug}/{topic_slug}/{page_type}")
async def get_seo_page_typed(board: str, class_slug: str, subject_slug: str, chapter_slug: str, topic_slug: str, page_type: str):
    page = await _db.seo_pages.find_one(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "chapter_slug": chapter_slug,
            "topic_slug": topic_slug,
            "page_type": page_type,
            "status": "published",
        },
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.get("/page-types/{board}/{class_slug}/{subject_slug}/{chapter_slug}/{topic_slug}")
async def get_available_page_types(board: str, class_slug: str, subject_slug: str, chapter_slug: str, topic_slug: str):
    pages = await _db.seo_pages.find(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "chapter_slug": chapter_slug,
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
        t["seo_path"] = f"/{hierarchy.get('board_slug', '')}/{hierarchy.get('class_slug', '')}/{hierarchy.get('subject_slug', '')}/{hierarchy.get('chapter_slug', '')}/{t['slug']}" if hierarchy else ""

    if prev_topic:
        h = await _resolve_hierarchy(prev_topic)
        prev_topic["seo_path"] = f"/{h.get('board_slug', '')}/{h.get('class_slug', '')}/{h.get('subject_slug', '')}/{h.get('chapter_slug', '')}/{prev_topic['slug']}" if h else ""
    if next_topic:
        h = await _resolve_hierarchy(next_topic)
        next_topic["seo_path"] = f"/{h.get('board_slug', '')}/{h.get('class_slug', '')}/{h.get('subject_slug', '')}/{h.get('chapter_slug', '')}/{next_topic['slug']}" if h else ""

    return {
        "related": same_chapter + adjacent_topics,
        "prev": prev_topic,
        "next": next_topic,
    }


# ─── PUBLIC: Sitemap entries ────────────────────────────────────────────────

@router.get("/sitemap-entries")
async def get_sitemap_entries():
    pages = await _db.seo_pages.find(
        {"status": "published"},
        {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1, "chapter_slug": 1, "topic_slug": 1, "page_type": 1, "updated_at": 1},
    ).to_list(10000)

    entries = []
    for p in pages:
        path = f"/{p['board_slug']}/{p['class_slug']}/{p['subject_slug']}/{p['chapter_slug']}/{p['topic_slug']}"
        if p["page_type"] != "notes":
            path += f"/{p['page_type']}"
        entries.append({
            "url": path,
            "lastmod": p.get("updated_at", ""),
            "priority": "0.7" if p["page_type"] != "notes" else "0.8",
        })

    return {"entries": entries, "total": len(entries)}


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
