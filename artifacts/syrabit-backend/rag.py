"""Syrabit.ai — RAG search, vector search, content card fetching, auto-chunking."""
import os, re, asyncio, time, uuid, hashlib, logging
from typing import Optional, Dict
from datetime import datetime, timezone
from fastapi import HTTPException
from deps import db, logger as _dep_logger, _assert_not_cms_context, is_mongo_available, voyage_client
from cache import (
    _rag_cache, _rag_cache_key, _vector_rag_cache, _vector_rag_cache_key,
    _content_card_cache, _content_card_cache_key,
    _cache_key, _redis_get_search, _redis_cache_search,
    _query_embed_cache,
)
from utils import _extract_keywords, _slow_query
import vertex_services

logger = logging.getLogger(__name__)

_voyage_backoff_until: float = 0.0

__all__ = [
    "_HISTORY_MAX_TURNS", "_HISTORY_TOKEN_BUDGET", "_LATENCY_MAX", "_RAG_TELEM_MAX",
    "_chat_latencies", "_ddg_news_search", "_ddg_text_search",
    "_embed_and_store_chapter", "_embed_and_store_page", "_embed_cms_document", "_extract_relevant_sections",
    "_fetch_content_card", "_fetch_enrichment_blocks", "_rag_telemetry", "_record_chat_latency",
    "_record_rag_event", "_sources_from_rag_ctx", "_trim_history",
    "auto_chunk_content", "build_rag_system_prompt", "rag_search", "rechunk_chapter",
    "resolve_rag_context", "syrabit_library_search", "vector_rag_search",
    "web_search_with_fallback",
    "get_vector_search_stats", "get_pipeline_stats", "record_pipeline_run",
    "_record_vector_search",
]

_HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
_CHUNK_TARGET = 600
_CHUNK_MAX = 1200
_CHUNK_MIN = 80
_OVERLAP_SENTENCES = 2
_VECTOR_SIM_THRESHOLD = 0.30

_VECTOR_SIM_METRICS: list = []
_VECTOR_SIM_MAX = 10_000

def _record_vector_search(query: str, num_results: int, scores: list, below_threshold: int, total_candidates: int, reranked: bool = False):
    _VECTOR_SIM_METRICS.append({
        "ts": time.time(),
        "query": query[:120],
        "num_results": num_results,
        "best_score": round(max(scores), 4) if scores else 0.0,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "worst_score": round(min(scores), 4) if scores else 0.0,
        "below_threshold": below_threshold,
        "total_candidates": total_candidates,
        "reranked": reranked,
    })
    if len(_VECTOR_SIM_METRICS) > _VECTOR_SIM_MAX:
        del _VECTOR_SIM_METRICS[:500]

def get_vector_search_stats(window_seconds: int = 3600) -> dict:
    cutoff = time.time() - window_seconds
    recent = [m for m in _VECTOR_SIM_METRICS if m["ts"] >= cutoff]
    if not recent:
        return {"total_searches": 0, "has_data": False}
    all_best = [m["best_score"] for m in recent if m["best_score"] > 0]
    all_avg = [m["avg_score"] for m in recent if m["avg_score"] > 0]
    total_below = sum(m["below_threshold"] for m in recent)
    total_candidates = sum(m["total_candidates"] for m in recent)
    zero_result = sum(1 for m in recent if m["num_results"] == 0)
    return {
        "total_searches": len(recent),
        "avg_best_score": round(sum(all_best) / len(all_best), 4) if all_best else 0,
        "avg_score_overall": round(sum(all_avg) / len(all_avg), 4) if all_avg else 0,
        "pct_below_threshold": round(total_below / max(total_candidates, 1) * 100, 1),
        "zero_result_pct": round(zero_result / len(recent) * 100, 1),
        "window_seconds": window_seconds,
        "has_data": True,
    }

_PIPELINE_RUNS: list = []
_PIPELINE_RUNS_MAX = 500

def record_pipeline_run(action: str, subject: str, success: bool, chapters: int = 0, chunks: int = 0, embeddings: int = 0, duration_ms: float = 0, error: str = ""):
    _PIPELINE_RUNS.append({
        "ts": time.time(),
        "action": action,
        "subject": subject[:100],
        "success": success,
        "chapters": chapters,
        "chunks": chunks,
        "embeddings": embeddings,
        "duration_ms": round(duration_ms, 1),
        "error": error[:200],
    })
    if len(_PIPELINE_RUNS) > _PIPELINE_RUNS_MAX:
        del _PIPELINE_RUNS[:50]

def get_pipeline_stats(window_seconds: int = 86400) -> dict:
    cutoff = time.time() - window_seconds
    recent = [r for r in _PIPELINE_RUNS if r["ts"] >= cutoff]
    if not recent:
        return {"total_runs": 0, "has_data": False}
    successes = sum(1 for r in recent if r["success"])
    return {
        "total_runs": len(recent),
        "successes": successes,
        "failures": len(recent) - successes,
        "success_rate": round(successes / len(recent) * 100, 1),
        "total_chapters": sum(r["chapters"] for r in recent),
        "total_chunks": sum(r["chunks"] for r in recent),
        "total_embeddings": sum(r["embeddings"] for r in recent),
        "recent": recent[-10:],
        "has_data": True,
    }

def _split_into_sections(content: str) -> list[dict]:
    sections = []
    last_end = 0
    current_heading = ""
    for m in _HEADING_RE.finditer(content):
        before = content[last_end:m.start()].strip()
        if before:
            sections.append({"heading": current_heading, "text": before})
        current_heading = m.group(2).strip()
        last_end = m.end()
    trailing = content[last_end:].strip()
    if trailing:
        sections.append({"heading": current_heading, "text": trailing})
    if not sections and content.strip():
        sections.append({"heading": "", "text": content.strip()})
    return sections

def _merge_short_sections(sections: list[dict], target: int = _CHUNK_TARGET) -> list[dict]:
    merged = []
    buf = None
    for sec in sections:
        if buf is None:
            buf = dict(sec)
            continue
        combined_len = len(buf["text"]) + len(sec["text"])
        if combined_len <= target:
            buf["text"] = buf["text"] + "\n\n" + (f"**{sec['heading']}**\n" if sec["heading"] else "") + sec["text"]
        else:
            merged.append(buf)
            buf = dict(sec)
    if buf:
        merged.append(buf)
    return merged

def _sentence_split_with_overlap(text: str, target: int = _CHUNK_TARGET, max_len: int = _CHUNK_MAX, overlap: int = _OVERLAP_SENTENCES) -> list[str]:
    sentences = _SENTENCE_SPLIT_RE.split(text)
    sentences = [s for s in sentences if s.strip()]
    if not sentences:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(sentences):
        current = []
        current_len = 0
        end = start
        while end < len(sentences):
            slen = len(sentences[end])
            if current and current_len + slen + 1 > max_len:
                break
            current.append(sentences[end])
            current_len += slen + (1 if current_len else 0)
            end += 1
            if current_len >= target:
                break
        chunk_text = " ".join(current).strip()
        if chunk_text:
            chunks.append(chunk_text)
        advance = max(1, len(current) - overlap)
        start += advance
    return chunks

def _split_by_topics(content: str, topics: list[str]) -> list[str]:
    """Split content into topic-aligned chunks using topic titles as section markers."""
    if not topics:
        return []
    import difflib
    lines = content.split("\n")
    heading_indices: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        stripped = re.sub(r'^#{1,4}\s*', '', line).strip().rstrip(".").lower()
        stripped = re.sub(r'^\d+[\.\)]\s*', '', stripped).strip()
        if not stripped or len(stripped) < 3:
            continue
        for topic in topics:
            topic_clean = topic.strip().rstrip(".").lower()
            ratio = difflib.SequenceMatcher(None, stripped, topic_clean).ratio()
            if ratio >= 0.6 or topic_clean in stripped or stripped in topic_clean:
                heading_indices.append((i, topic))
                break
    if not heading_indices:
        return []
    chunks: list[str] = []
    intro_lines = lines[:heading_indices[0][0]]
    intro_text = "\n".join(intro_lines).strip()
    if intro_text and len(intro_text) >= 50:
        chunks.append(intro_text)
    for idx, (line_idx, topic_name) in enumerate(heading_indices):
        end_idx = heading_indices[idx + 1][0] if idx + 1 < len(heading_indices) else len(lines)
        section_text = "\n".join(lines[line_idx:end_idx]).strip()
        if section_text:
            chunks.append(section_text)
    return chunks


def _extract_heading_from_chunk(text: str) -> str:
    m = _HEADING_RE.search(text)
    if m:
        return m.group(2).strip()
    first_line = text.split("\n", 1)[0].strip()
    cleaned = re.sub(r'^\*{1,3}', '', first_line).rstrip("*").strip()
    return cleaned if len(cleaned) < 120 else ""


async def auto_chunk_content(chapter_id: str, content: str, subject_id: str = None, syllabus_id: str = None, geo_tags: list = None, chapter_title: str = None, category: str = "notes", topics: list = None) -> list:
    """
    Semantically split chapter content into RAG-optimised chunks.

    Strategy:
    - If topics are provided, split by topic headings (one chunk per topic)
    - Otherwise, split by markdown headings (###) to keep concepts together
    - Merge short sections; split long ones by sentences
    - Target 300-600 chars per chunk for optimal retrieval
    - 2-sentence overlap between consecutive chunks
    - Store chapter_title, geo_tags, keywords per chunk

    Returns: List of created chunk IDs
    """
    if not content or len(content.strip()) < 100:
        logger.warning(f"Content too short for chunking (chapter {chapter_id}): {len(content)} chars")
        return []

    old_chunk_ids = [doc["_id"] async for doc in db.chunks.find({"chapter_id": chapter_id}, {"_id": 1})]

    content = content.strip()

    topic_names = []
    if topics:
        for t in topics:
            if isinstance(t, dict):
                topic_names.append(t.get("title", ""))
            elif isinstance(t, str):
                topic_names.append(t)

    topic_chunks = _split_by_topics(content, topic_names) if topic_names else []

    raw_chunks_with_topic: list[tuple[str, str]] = []
    if topic_chunks:
        for tc in topic_chunks:
            tn = _extract_heading_from_chunk(tc)
            if len(tc) <= _CHUNK_MAX:
                raw_chunks_with_topic.append((tc, tn))
            else:
                sub = _sentence_split_with_overlap(tc)
                for s in sub:
                    raw_chunks_with_topic.append((s, tn))
        logger.info(f"Topic-wise chunking: {len(topic_chunks)} topic sections → {len(raw_chunks_with_topic)} chunks")
    else:
        sections = _split_into_sections(content)
        sections = _merge_short_sections(sections)
        for sec in sections:
            text = sec["text"]
            heading = sec.get("heading", "")
            prefix = f"**{heading}**\n" if heading else ""
            full = (prefix + text).strip()
            if len(full) <= _CHUNK_MAX:
                raw_chunks_with_topic.append((full, heading))
            else:
                sub_chunks = _sentence_split_with_overlap(full)
                for s in sub_chunks:
                    raw_chunks_with_topic.append((s, heading))

    chunks_created = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for idx, (chunk_text, chunk_topic) in enumerate(raw_chunks_with_topic):
        chunk_text = chunk_text.strip()
        if len(chunk_text) < _CHUNK_MIN:
            continue
        chunk_keywords = _extract_keywords(chunk_text)
        _VALID_CATEGORIES = {"notes", "important_questions", "question_paper"}
        _chunk_category = category if category in _VALID_CATEGORIES else "notes"
        chunk = {
            "id": str(uuid.uuid4()),
            "chapter_id": chapter_id,
            "subject_id": subject_id,
            "chapter_title": chapter_title or "",
            "topic_name": chunk_topic or "",
            "content": chunk_text,
            "content_type": _chunk_category,
            "category": _chunk_category,
            "chunk_index": idx,
            "tags": chunk_keywords[:5],
            "char_count": len(chunk_text),
            "created_at": now_iso,
        }
        if syllabus_id:
            chunk["syllabus_id"] = syllabus_id
        if geo_tags:
            chunk["geo_tags"] = geo_tags[:5]
        await db.chunks.insert_one(chunk)
        chunks_created.append(chunk["id"])

    if chunks_created and old_chunk_ids:
        deleted = await db.chunks.delete_many({"_id": {"$in": old_chunk_ids}})
        logger.info(f"Dedup: removed {deleted.deleted_count} old chunks for chapter {chapter_id}")

    logger.info(f"Auto-chunked chapter {chapter_id}: {len(chunks_created)} chunks from {len(content)} chars")
    return chunks_created


async def rechunk_chapter(chapter_id: str) -> dict:
    """
    Re-chunk an existing chapter (useful after content updates or for existing chapters).
    Deletes old chunks and creates new ones.
    """
    # Get chapter
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    content = chapter.get("content", "")
    if not content:
        return {"chapter_id": chapter_id, "chunks_created": 0, "message": "No content to chunk"}
    
    # Delete existing chunks for this chapter
    delete_result = await db.chunks.delete_many({"chapter_id": chapter_id})
    deleted_count = delete_result.deleted_count
    
    # Create new chunks
    chunks_created = await auto_chunk_content(
        chapter_id=chapter_id,
        content=content,
        subject_id=chapter.get("subject_id"),
        category=chapter.get("category", "notes"),
        chapter_title=chapter.get("title", ""),
        topics=chapter.get("topics"),
    )
    
    return {
        "chapter_id": chapter_id,
        "chunks_deleted": deleted_count,
        "chunks_created": len(chunks_created),
        "message": f"Re-chunked successfully"
    }


async def _fetch_content_card(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    intent: Optional[str] = None,
    chapter_title: Optional[str] = None,
) -> Optional[tuple]:
    """
    Search seo_pages + chapters for the most relevant content card.
    Returns (card_text: str, card_slugs: set[str], source_meta: dict) if found, else None.
    Card slugs are used by the grounding builder to deduplicate vector hits.
    source_meta contains card_name, lesson_name, subject_name for chat attribution.
    """
    _ck = _content_card_cache_key(query, subject_id, subject_name, intent, chapter_title=chapter_title)
    if _ck in _content_card_cache:
        logger.info(f"Content card cache hit: query='{query[:40]}'")
        return _content_card_cache[_ck]

    try:
        if not await is_mongo_available():
            return None

        keywords = _extract_keywords(query)
        if not keywords:
            return None

        kw_regex = "|".join(keywords)
        match_filter: dict = {"status": "published"}

        if subject_id:
            subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0, "slug": 1, "name": 1})
            if subj and subj.get("slug"):
                match_filter["subject_slug"] = subj["slug"]

        if not subject_id and subject_name:
            match_filter["subject_name"] = {"$regex": re.escape(subject_name), "$options": "i"}

        if chapter_title:
            match_filter["chapter_title"] = {"$regex": re.escape(chapter_title), "$options": "i"}

        search_str = " ".join(keywords)
        match_filter["$text"] = {"$search": search_str}
        _text_proj = {
            "_id": 0, "content": 1, "topic_title": 1, "subject_name": 1,
            "chapter_title": 1, "page_type": 1, "slug": 1,
            "score": {"$meta": "textScore"},
        }
        seo_task = db.seo_pages.find(
            match_filter, _text_proj,
        ).sort([("score", {"$meta": "textScore"})]).limit(6).to_list(6)

        ch_filter: dict = {"content": {"$exists": True, "$ne": ""}}
        if subject_id:
            ch_filter["subject_id"] = subject_id
        if chapter_title:
            ch_filter["title"] = {"$regex": re.escape(chapter_title), "$options": "i"}
        ch_filter["$text"] = {"$search": search_str}
        _ch_proj = {
            "_id": 0, "title": 1, "slug": 1, "content": 1, "subject_id": 1,
            "score": {"$meta": "textScore"},
        }
        ch_task = db.chapters.find(
            ch_filter, _ch_proj,
        ).sort([("score", {"$meta": "textScore"})]).limit(4).to_list(4)

        cms_filter: dict = {"status": "published", "content": {"$exists": True, "$ne": ""}}
        _cms_proj = {
            "_id": 0, "title": 1, "content": 1, "seo_slug": 1,
            "category": 1, "linked_subject_name": 1, "linked_chapter_title": 1,
            "meta_description": 1,
        }

        def _build_cms_regex_task():
            _cms_regex_filter = dict(cms_filter)
            cms_escaped_kw = "|".join(re.escape(k) for k in keywords)
            cms_kw_or = [
                {"content": {"$regex": cms_escaped_kw, "$options": "i"}},
                {"title":   {"$regex": cms_escaped_kw, "$options": "i"}},
                {"meta_description": {"$regex": cms_escaped_kw, "$options": "i"}},
            ]
            if subject_id:
                _cms_regex_filter["$and"] = [
                    {"$or": [{"linked_subject_id": subject_id}, {"subject_id": subject_id}]},
                    {"$or": cms_kw_or},
                ]
            elif subject_name:
                _cms_regex_filter["$and"] = [
                    {"$or": [
                        {"linked_subject_name": {"$regex": re.escape(subject_name), "$options": "i"}},
                        {"subject_name": {"$regex": re.escape(subject_name), "$options": "i"}},
                    ]},
                    {"$or": cms_kw_or},
                ]
            else:
                async def _empty():
                    return []
                return _empty()
            return db.cms_documents.find(_cms_regex_filter, _cms_proj).limit(4).to_list(4)

        cms_text_filter = dict(cms_filter)
        cms_text_filter["$text"] = {"$search": search_str}
        if subject_id:
            cms_text_filter["$or"] = [{"linked_subject_id": subject_id}, {"subject_id": subject_id}]
        elif subject_name:
            cms_text_filter["$or"] = [
                {"linked_subject_name": {"$regex": re.escape(subject_name), "$options": "i"}},
                {"subject_name": {"$regex": re.escape(subject_name), "$options": "i"}},
            ]

        _cms_text_proj = {**_cms_proj, "score": {"$meta": "textScore"}}
        if subject_id or subject_name:
            cms_task = db.cms_documents.find(cms_text_filter, _cms_text_proj).sort([("score", {"$meta": "textScore"})]).limit(4).to_list(4)
        else:
            async def _empty_cms():
                return []
            cms_task = _empty_cms()

        try:
            pages, chapter_pages, cms_pages = await asyncio.gather(seo_task, ch_task, cms_task)
        except Exception:
            del match_filter["$text"]
            escaped_kw_re = "|".join(re.escape(k) for k in keywords)
            match_filter["$or"] = [
                {"content":     {"$regex": escaped_kw_re, "$options": "i"}},
                {"topic_title": {"$regex": escaped_kw_re, "$options": "i"}},
                {"title":       {"$regex": escaped_kw_re, "$options": "i"}},
            ]
            regex_proj = {"_id": 0, "content": 1, "topic_title": 1, "subject_name": 1,
                          "chapter_title": 1, "page_type": 1, "slug": 1}
            ch_filter_fb: dict = {"content": {"$exists": True, "$ne": ""}}
            if subject_id:
                ch_filter_fb["subject_id"] = subject_id
            if chapter_title:
                ch_filter_fb["title"] = {"$regex": re.escape(chapter_title), "$options": "i"}
            ch_filter_fb["$or"] = [
                {"content": {"$regex": escaped_kw_re, "$options": "i"}},
                {"title":   {"$regex": escaped_kw_re, "$options": "i"}},
            ]
            pages, chapter_pages, cms_pages = await asyncio.gather(
                db.seo_pages.find(match_filter, regex_proj).limit(6).to_list(6),
                db.chapters.find(ch_filter_fb, {"_id": 0, "title": 1, "content": 1, "subject_id": 1}).limit(4).to_list(4),
                _build_cms_regex_task(),
            )

        if not pages and not chapter_pages and not cms_pages:
            return None

        cards = []

        def _page_priority(p: dict) -> int:
            pt = p.get("page_type", "")
            return 0 if pt == "notes" else (1 if pt == "pyq" else (2 if pt == "mcq" else 3))

        _is_syllabus = (intent or "").lower() == "syllabus"
        _page_max = 3500 if _is_syllabus else 2000
        _cms_max = 2500 if _is_syllabus else 1500
        _ch_max = 2000 if _is_syllabus else 1200

        ordered_pages = sorted(pages, key=_page_priority)
        card_slugs: set = set()
        _top_card_name: str = ""
        _top_lesson_name: str = ""
        _top_subject_name: str = ""
        _top_card_slug: str = ""
        _intent_for_extract = (intent or "").lower()
        for p in ordered_pages[:3]:
            content = p.get("content", "")
            if not content:
                continue
            slug = p.get("slug") or p.get("topic_title", "")
            card_slugs.add(slug)
            topic_title = p.get("topic_title") or p.get("chapter_title") or ""
            if not _top_card_name and topic_title:
                _top_card_name = topic_title
                _top_card_slug = p.get("slug") or ""
                _top_lesson_name = p.get("chapter_title") or ""
                _top_subject_name = p.get("subject_name") or subject_name or ""
            page_type = p.get("page_type", "")
            if topic_title:
                header = f"[Content: {topic_title} | type={page_type}]" if page_type else f"[Content: {topic_title}]"
            else:
                header = f"[Content Page | type={page_type}]" if page_type else "[Content Page]"
            relevant = _extract_relevant_sections(content, keywords, max_chars=_page_max, intent=_intent_for_extract, query=query)
            cards.append(f"{header}\n{relevant}")

        for cms in cms_pages[:2]:
            content = cms.get("content", "")
            if not content:
                continue
            slug = cms.get("seo_slug", "")
            card_slugs.add(slug)
            cms_title = cms.get("title") or cms.get("linked_chapter_title") or ""
            if not _top_card_name and cms_title:
                _top_card_name = cms_title
                _top_lesson_name = cms.get("linked_chapter_title") or ""
                _top_subject_name = cms.get("linked_subject_name") or subject_name or ""
            cat = cms.get("category", "article")
            header = f"[CMS {cat}: {cms_title}]" if cms_title else f"[CMS {cat}]"
            relevant = _extract_relevant_sections(content, keywords, max_chars=_cms_max, intent=_intent_for_extract, query=query)
            cards.append(f"{header}\n{relevant}")

        for ch in chapter_pages[:2]:
            content = ch.get("content", "")
            if not content:
                continue
            if not _top_lesson_name:
                _top_lesson_name = ch.get("title") or ""
            header = f"[Chapter: {ch.get('title', '')} | type=lesson]"
            topic_section = _extract_topic_section(content, query, query=query, max_chars=_ch_max + 500)
            if topic_section and len(topic_section) > 50:
                relevant = topic_section
            else:
                relevant = _extract_relevant_sections(content, keywords, max_chars=_ch_max, intent=_intent_for_extract, query=query)
            cards.append(f"{header}\n{relevant}")

        if not cards:
            return None

        source_meta = {
            "card_name": _top_card_name,
            "lesson_name": _top_lesson_name,
            "subject_name": _top_subject_name,
            "card_slug": _top_card_slug,
        }
        result = ("\n\n---\n\n".join(cards), card_slugs, source_meta)
        _content_card_cache[_ck] = result
        return result

    except Exception as e:
        logger.error(f"Content card fetch error: {e}")
        return None


_NOTES_SUB_INTENTS = {
    "definition": {
        "triggers": ["define", "definition", "meaning of", "what is", "what are", "what do you mean"],
        "boost": ["definition", "define", "meaning", "refers to", "is defined as", "known as"],
        "skip_patterns": [r'^\d+\.\s+(?:What|How|Why|Define|Explain|State|Discuss)',
                          r'^\*\*\d+-Mark\s+Questions?\*\*'],
        "header_bonus": 0.8,
    },
    "explanation": {
        "triggers": ["explain", "describe", "discuss", "elaborate", "how does", "why does", "what happens"],
        "boost": ["explain", "because", "therefore", "process", "mechanism", "steps",
                   "occurs when", "leads to", "results in", "due to"],
        "skip_patterns": [r'^\*\*\d+-Mark\s+Questions?\*\*'],
        "header_bonus": 1.0,
    },
    "exam_tips": {
        "triggers": ["tips", "how to score", "how to prepare", "revision", "remember",
                      "trick", "mnemonic", "shortcut", "easy way"],
        "boost": ["remember", "tip", "trick", "mnemonic", "shortcut", "key point",
                   "important", "exam", "revision", "formula"],
        "skip_patterns": [],
        "header_bonus": 0.5,
    },
}


def _detect_notes_sub_intent(query: str) -> str:
    q = query.strip().lower()
    for sub_intent, config in _NOTES_SUB_INTENTS.items():
        for trigger in config["triggers"]:
            if trigger in q:
                return sub_intent
    return ""


_INTENT_SECTION_SIGNALS: dict = {
    "notes": {
        "boost": ["definition", "define", "explain", "meaning", "concept", "theory",
                   "formula", "derivation", "principle", "law", "theorem"],
        "skip_patterns": [r'^\d+\.\s+(?:What|How|Why|Define|Explain|State|Discuss)',
                          r'^\*\*\d+-Mark\s+Questions?\*\*'],
        "header_bonus": 1.0,
    },
    "pyq": {
        "boost": ["mark", "marks", "question", "year", "paper", "solve", "answer",
                   "section", "part"],
        "skip_patterns": [],
        "header_bonus": 0.5,
    },
    "important_questions": {
        "boost": ["important", "question", "mark", "marks", "frequently", "repeated",
                   "weightage", "expected"],
        "skip_patterns": [],
        "header_bonus": 0.5,
    },
    "syllabus": {
        "boost": ["unit", "chapter", "topic", "module", "syllabus", "semester",
                   "course", "outline"],
        "skip_patterns": [],
        "header_bonus": 1.5,
    },
}


def _extract_topic_section(content: str, topic_name: str, query: str = "", max_chars: int = 3000) -> str:
    """Extract a specific topic section from chapter content using heading matching."""
    import difflib
    lines = content.split('\n')
    topic_lower = topic_name.lower().rstrip('.')
    query_lower = (query or topic_name).lower()

    best_start = -1
    best_ratio = 0.0
    for i, line in enumerate(lines):
        stripped = line.strip().lstrip('#').strip().rstrip('.').lower()
        stripped_no_num = re.sub(r'^\d+[\.\)]\s*', '', stripped)
        for candidate in (stripped, stripped_no_num):
            if not candidate:
                continue
            ratio = difflib.SequenceMatcher(None, topic_lower, candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i
            ratio2 = difflib.SequenceMatcher(None, query_lower, candidate).ratio()
            if ratio2 > best_ratio:
                best_ratio = ratio2
                best_start = i

    if best_start < 0 or best_ratio < 0.5:
        return ""

    section_lines = [lines[best_start]]
    heading_level = len(lines[best_start]) - len(lines[best_start].lstrip('#'))
    for j in range(best_start + 1, len(lines)):
        line = lines[j]
        if line.strip().startswith('#'):
            cur_level = len(line) - len(line.lstrip('#'))
            if cur_level <= heading_level and cur_level > 0:
                break
        section_lines.append(line)

    section = '\n'.join(section_lines).strip()
    if len(section) > max_chars:
        section = section[:max_chars]
    return section if len(section) > 30 else ""


def _extract_relevant_sections(content: str, keywords: list, max_chars: int = 2500, intent: str = "", query: str = "") -> str:
    """Extract the most relevant sections from a content page based on keywords, intent, and sub-intent."""
    paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
    if not paragraphs:
        return content[:max_chars]

    if intent == "syllabus":
        return content[:max_chars]

    signals = _INTENT_SECTION_SIGNALS.get(intent, {})
    boost_terms = list(signals.get("boost", []))
    skip_patterns = list(signals.get("skip_patterns", []))
    header_bonus = signals.get("header_bonus", 0.5)

    _sub_intent = ""
    if intent == "notes":
        _sub_intent = _detect_notes_sub_intent(query or " ".join(keywords))
        if not _sub_intent:
            _sub_intent = _detect_notes_sub_intent(" ".join(keywords))
        if _sub_intent and _sub_intent in _NOTES_SUB_INTENTS:
            sub_cfg = _NOTES_SUB_INTENTS[_sub_intent]
            boost_terms = sub_cfg["boost"] + boost_terms
            skip_patterns = sub_cfg["skip_patterns"] + skip_patterns
            header_bonus = sub_cfg.get("header_bonus", header_bonus)

    skip_res = [re.compile(p, re.I) for p in skip_patterns] if skip_patterns else []

    scored = []
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()

        if skip_res and any(r.search(para) for r in skip_res):
            scored.append((-1, i, para))
            continue

        score = sum(1 for kw in keywords if kw in para_lower)

        if boost_terms:
            score += sum(0.5 for bt in boost_terms if bt in para_lower)

        is_header = para.startswith('#') or para.startswith('**')
        if is_header:
            score += header_bonus
        scored.append((score, i, para))

    scored.sort(key=lambda x: (-x[0], x[1]))

    selected = []
    total_chars = 0
    for score, idx, para in scored:
        if score <= 0 and total_chars > 500:
            break
        if score < 0:
            continue
        selected.append((idx, score))
        total_chars += len(paragraphs[idx])
        if total_chars >= max_chars:
            break

    if not selected:
        return content[:max_chars]

    selected.sort(key=lambda x: x[0])

    final_indices = set()
    remaining_budget = max_chars
    for idx, _sc in selected:
        neighbor_start = max(0, idx - 1)
        neighbor_end = min(len(paragraphs), idx + 2)
        for j in range(neighbor_start, neighbor_end):
            if j not in final_indices:
                p_len = len(paragraphs[j])
                if remaining_budget - p_len < 0 and final_indices:
                    continue
                final_indices.add(j)
                remaining_budget -= p_len
        if remaining_budget <= 0:
            break

    if not final_indices:
        return content[:max_chars]

    result = "\n".join(paragraphs[i] for i in sorted(final_indices))
    return result[:max_chars]


async def _embed_and_store_page(page_slug: str, content: str) -> bool:
    """Embed a published seo_page and persist the vector. Called on every publish."""
    try:
        vec = await vertex_services.embed_text(content[:8000], task_type="RETRIEVAL_DOCUMENT")
        if vec:
            await db.seo_pages.update_one(
                {"topic_slug": page_slug},
                {"$set": {"embedding": vec, "embedding_model": vertex_services._EMBED_MODEL}},
            )
            logger.info(f"Page embedded: {page_slug} (dim={len(vec)})")
            return True
    except Exception as e:
        logger.warning(f"Embed-on-publish failed for {page_slug}: {e}")
    return False


async def _embed_and_store_chapter(chapter_id: str, content: str, title: str = "") -> bool:
    """Embed a chapter's content and persist the vector."""
    try:
        text = f"{title}\n\n{content}" if title else content
        vec = await vertex_services.embed_text(text[:8000], task_type="RETRIEVAL_DOCUMENT")
        if vec:
            await db.chapters.update_one(
                {"id": chapter_id},
                {"$set": {"embedding": vec, "embedding_model": vertex_services._EMBED_MODEL}},
            )
            return True
    except Exception as e:
        logger.warning(f"Embed chapter {chapter_id} failed: {e}")
    return False


async def _embed_cms_document(seo_slug: str, content: str, title: str = "") -> bool:
    """Embed a cms_document and persist the vector for RAG vector search."""
    try:
        text = f"{title}\n\n{content}" if title else content
        vec = await vertex_services.embed_text(text[:8000], task_type="RETRIEVAL_DOCUMENT")
        if vec:
            await db.cms_documents.update_one(
                {"seo_slug": seo_slug},
                {"$set": {"embedding": vec, "embedding_model": vertex_services._EMBED_MODEL}},
            )
            logger.info(f"CMS doc embedded: {seo_slug} (dim={len(vec)})")
            return True
    except Exception as e:
        logger.warning(f"Embed cms_document {seo_slug} failed: {e}")
    return False


async def vector_rag_search(
    query: str,
    subject_id: Optional[str] = None,
    top_k: int = 12,
    db_category: Optional[str] = None,
) -> list:
    """
    Vector similarity search over all published seo_pages + chapters.
    Returns top-k results sorted by cosine similarity with [PAGE: slug] metadata.

    Falls back to empty list if embedding fails or no vectors exist yet.
    Caches results for 300 seconds — Gemini embed calls are expensive.
    """
    _vk = _vector_rag_cache_key(query, subject_id, top_k)
    _vk_cat = f"{_vk}:{db_category or ''}"
    if _vk_cat in _vector_rag_cache:
        logger.info(f"Vector RAG cache hit: query='{query[:40]}'")
        return _vector_rag_cache[_vk_cat]

    try:
        return await asyncio.wait_for(
            _vector_rag_search_inner(query, subject_id, top_k, _vk_cat, db_category=db_category),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        logger.warning(f"vector_rag_search timed out (2s budget): query='{query[:40]}'")
        return []
    except Exception as e:
        logger.error(f"vector_rag_search failed: {e}")
        return []


async def _vector_rag_search_inner(
    query: str,
    subject_id: Optional[str],
    top_k: int,
    _vk: str,
    db_category: Optional[str] = None,
) -> list:
    try:
        _embed_key = query.strip().lower()
        query_vec = _query_embed_cache.get(_embed_key)
        if query_vec is None:
            query_vec = await vertex_services.embed_text(query, task_type="RETRIEVAL_QUERY")
            if query_vec:
                _query_embed_cache[_embed_key] = query_vec
        if not query_vec:
            return []

        page_filter: dict = {"status": "published", "embedding": {"$exists": True}, "content": {"$exists": True, "$ne": ""}}
        subj = None
        if subject_id:
            subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0, "slug": 1})
            if subj and subj.get("slug"):
                page_filter["subject_slug"] = subj["slug"]

        _page_proj = {"_id": 0, "topic_slug": 1, "topic_title": 1,
             "chapter_title": 1, "page_type": 1, "embedding": 1, "subject_slug": 1}
        _ch_proj = {"_id": 0, "id": 1, "title": 1, "slug": 1, "subject_id": 1, "embedding": 1}
        _cms_proj = {"_id": 0, "seo_slug": 1, "title": 1, "category": 1, "embedding": 1, "linked_subject_id": 1, "subject_id": 1}

        ch_filter: dict = {"embedding": {"$exists": True}, "content": {"$exists": True, "$ne": ""}}
        if subject_id:
            ch_filter["subject_id"] = subject_id
        if db_category:
            ch_filter["category"] = db_category

        cms_filter: dict = {"status": "published", "embedding": {"$exists": True}, "content": {"$exists": True, "$ne": ""}}
        if subject_id:
            cms_filter["$or"] = [{"linked_subject_id": subject_id}, {"subject_id": subject_id}]

        pages, chapters, cms_docs = await asyncio.gather(
            db.seo_pages.find(page_filter, _page_proj).limit(15).to_list(15),
            db.chapters.find(ch_filter, _ch_proj).limit(10).to_list(10),
            db.cms_documents.find(cms_filter, _cms_proj).limit(5).to_list(5),
        )

        scored = []
        q_dim = len(query_vec)
        _subj_slug_to_id = {}
        if subj and subj.get("slug"):
            _subj_slug_to_id[subj["slug"]] = subject_id

        for p in pages:
            vec = p.get("embedding")
            if vec and len(vec) == q_dim:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                slug = p.get("topic_slug", "")
                title = p.get("topic_title") or p.get("chapter_title") or slug
                _p_subj_slug = p.get("subject_slug", "")
                scored.append({
                    "slug":    slug,
                    "title":   title,
                    "content": title,
                    "score":   sim,
                    "source":  "page",
                    "page_type": p.get("page_type", ""),
                    "subject_id": _subj_slug_to_id.get(_p_subj_slug, ""),
                })
        for ch in chapters:
            vec = ch.get("embedding")
            if vec and len(vec) == q_dim:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                scored.append({
                    "slug":    f"chapter/{ch.get('id', '')}",
                    "title":   ch.get("title", ""),
                    "content": ch.get("title", ""),
                    "score":   sim,
                    "source":  "chapter",
                    "subject_id": ch.get("subject_id", ""),
                })
        for cms in cms_docs:
            vec = cms.get("embedding")
            if vec and len(vec) == q_dim:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                scored.append({
                    "slug":    cms.get("seo_slug", ""),
                    "title":   cms.get("title", ""),
                    "content": cms.get("title", ""),
                    "score":   sim,
                    "source":  "cms",
                    "subject_id": cms.get("linked_subject_id") or cms.get("subject_id", ""),
                })

        scored.sort(key=lambda x: -x["score"])
        top = [r for r in scored if r["score"] >= _VECTOR_SIM_THRESHOLD][:top_k]

        if top:
            _content_fetch_tasks = []
            _content_fetch_indices = []
            for i, hit in enumerate(top):
                if hit["source"] == "page":
                    _page_q = {"topic_slug": hit["slug"], "status": "published"}
                    if hit.get("page_type"):
                        _page_q["page_type"] = hit["page_type"]
                    _content_fetch_tasks.append(
                        db.seo_pages.find_one(_page_q, {"_id": 0, "content": 1})
                    )
                    _content_fetch_indices.append(i)
                elif hit["source"] == "chapter":
                    _ch_id = hit["slug"].replace("chapter/", "")
                    _content_fetch_tasks.append(
                        db.chapters.find_one({"id": _ch_id}, {"_id": 0, "content": 1})
                    )
                    _content_fetch_indices.append(i)
                elif hit["source"] == "cms":
                    _content_fetch_tasks.append(
                        db.cms_documents.find_one({"seo_slug": hit["slug"], "status": "published"}, {"_id": 0, "content": 1})
                    )
                    _content_fetch_indices.append(i)
            if _content_fetch_tasks:
                _fetched = await asyncio.gather(*_content_fetch_tasks, return_exceptions=True)
                for idx, doc in zip(_content_fetch_indices, _fetched):
                    if doc and not isinstance(doc, Exception) and doc.get("content"):
                        top[idx]["content"] = _extract_relevant_sections(doc["content"], [], max_chars=1500)
        all_scores = [r["score"] for r in scored]
        below = sum(1 for s in all_scores if s < _VECTOR_SIM_THRESHOLD)

        reranked = False
        global _voyage_backoff_until
        _voyage_available = voyage_client and top and time.time() >= _voyage_backoff_until
        if _voyage_available:
            pre_rerank_slugs = [r["slug"] for r in top[:3]]
            try:
                _rerank_start = time.time()
                documents = [r.get("content", "") or r.get("title", "") for r in top]
                _rerank_top_k = min(top_k, len(top))
                loop = asyncio.get_running_loop()
                rerank_result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: voyage_client.rerank(
                            query=query,
                            documents=documents,
                            model="rerank-2",
                            top_k=_rerank_top_k,
                        ),
                    ),
                    timeout=1.5,
                )
                _rerank_ms = (time.time() - _rerank_start) * 1000
                reranked_top = []
                for rr in rerank_result.results:
                    item = dict(top[rr.index])
                    item["rerank_score"] = rr.relevance_score
                    reranked_top.append(item)
                post_rerank_slugs = [r["slug"] for r in reranked_top[:3]]
                logger.info(
                    f"Voyage rerank: latency={_rerank_ms:.0f}ms | "
                    f"before={pre_rerank_slugs} → after={post_rerank_slugs} | "
                    f"query='{query[:40]}'"
                )
                top = reranked_top
                reranked = True
            except asyncio.TimeoutError:
                logger.warning(f"Voyage rerank timed out after 1.5s (falling back to cosine): query='{query[:40]}'")
            except Exception as _rerank_err:
                _err_str = str(_rerank_err)
                if "429" in _err_str or "rate" in _err_str.lower() or "Ratelimit" in _err_str or "payment" in _err_str.lower():
                    _voyage_backoff_until = time.time() + 120
                    logger.warning(f"Voyage rerank rate-limited → backing off 120s: {_err_str[:100]}")
                else:
                    logger.warning(f"Voyage rerank failed (falling back to cosine): {_rerank_err}")

        _record_vector_search(query, len(top), [r["score"] for r in top] if top else [], below, len(scored), reranked=reranked)
        logger.info(
            f"Vector RAG: query='{query[:40]}' → {len(top)} results "
            f"(best_sim={top[0]['score']:.3f} [{top[0]['slug']}], threshold={_VECTOR_SIM_THRESHOLD}, reranked={reranked})" if top else
            f"Vector RAG: query='{query[:40]}' → no results above threshold ({_VECTOR_SIM_THRESHOLD})"
        )
        _vector_rag_cache[_vk] = top
        return top
    except Exception as e:
        logger.error(f"vector_rag_search failed: {e}")
        return []


async def rag_search(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
) -> dict:
    """
    Level-1 RAG: search content chunks + subject metadata from DB.

    Returns quality indicator:
      "high"   — at least 1 content chunk found (real indexed text)
      "medium" — no chunks, but matching subjects/chapters found (metadata only)
      "none"   — nothing found in DB at all
    """
    _rag_t0 = time.time()
    # Fast path: 60-second in-memory cache — skips all MongoDB queries on repeat
    _rk = _rag_cache_key(query, subject_id, subject_name)
    if _rk in _rag_cache:
        return _rag_cache[_rk]
    try:
        keywords = _extract_keywords(query)
        if not keywords:
            return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}

        kw_join = "|".join(keywords)
        _text_search_str = " ".join(keywords)
        regex_parts = [{"content": {"$regex": kw, "$options": "i"}} for kw in keywords]
        ch_title_filter = {"$or": [{"title": {"$regex": kw, "$options": "i"}} for kw in keywords]}

        if subject_id:
            sub_chapters = await db.chapters.find(
                {"subject_id": subject_id}, {"_id": 0, "id": 1}
            ).to_list(200)
            chapter_ids = [c["id"] for c in sub_chapters]
            pyq_branch: dict = {"$and": [{"subject_id": subject_id}, {"content_type": {"$in": ["pyq", "question_paper"]}}, {"$or": regex_parts}]}

            try:
                _chunk_text_filter: dict = {"$text": {"$search": _text_search_str}}
                if chapter_ids:
                    _chunk_text_filter["$or"] = [{"chapter_id": {"$in": chapter_ids}}, {"subject_id": subject_id, "content_type": {"$in": ["pyq", "question_paper"]}}]
                else:
                    _chunk_text_filter["subject_id"] = subject_id
                _chunk_proj_text = {"_id": 0, "score": {"$meta": "textScore"}, "chapter_id": 1, "content": 1, "content_type": 1, "subject_id": 1, "priority": 1, "topic_name": 1, "chapter_title": 1}
                chunks = await db.chunks.find(_chunk_text_filter, _chunk_proj_text).sort([("score", {"$meta": "textScore"})]).limit(12).to_list(12)
            except Exception:
                if chapter_ids:
                    chunk_filter: dict = {"$or": [
                        {"$and": [{"chapter_id": {"$in": chapter_ids}}, {"$or": regex_parts}]},
                        pyq_branch,
                    ]}
                else:
                    chunk_filter = {"$or": [{"$or": regex_parts}, pyq_branch]}
                chunks = await db.chunks.find(chunk_filter, {"_id": 0, "chapter_id": 1, "content": 1, "content_type": 1, "subject_id": 1, "priority": 1, "topic_name": 1, "chapter_title": 1}).sort("priority", 1).limit(12).to_list(12)

            subj_kw_filter = {"id": subject_id}
            ch_kw_filter = {"$and": [{"subject_id": subject_id}, ch_title_filter]}
            ch_all_filter = {"subject_id": subject_id}

            subjects_found, chapters_kw, chapters_all = await asyncio.gather(
                db.subjects.find(subj_kw_filter, {"_id": 0, "id": 1, "name": 1, "icon": 1, "gradient": 1}).limit(1).to_list(1),
                db.chapters.find(ch_kw_filter, {"_id": 0, "title": 1, "slug": 1, "description": 1, "content": 1, "order_index": 1}).sort("order_index", 1).limit(8).to_list(8),
                db.chapters.find(ch_all_filter, {"_id": 0, "title": 1, "slug": 1, "description": 1, "content": 1, "order_index": 1}).sort("order_index", 1).limit(25).to_list(25),
            )
            chapters_found = chapters_kw if chapters_kw else chapters_all
        else:
            subj_kw_filter = {"$or": [
                {"name":        {"$regex": kw_join, "$options": "i"}},
                {"description": {"$regex": kw_join, "$options": "i"}},
                {"tags":        {"$elemMatch": {"$regex": kw_join, "$options": "i"}}},
            ], "status": "published"}
            if subject_name:
                subj_kw_filter = {"$and": [
                    {"name": {"$regex": subject_name, "$options": "i"}, "status": "published"},
                ]}

            _subj_proj = {"_id": 0, "id": 1, "name": 1, "description": 1, "tags": 1, "icon": 1, "gradient": 1}
            _ch_proj   = {"_id": 0, "id": 1, "subject_id": 1, "title": 1, "slug": 1, "description": 1, "order_index": 1}

            try:
                _chunk_text_filter_ns: dict = {"$text": {"$search": _text_search_str}}
                _chunk_proj_ns = {"_id": 0, "score": {"$meta": "textScore"}, "chapter_id": 1, "content": 1, "content_type": 1, "subject_id": 1, "priority": 1, "topic_name": 1, "chapter_title": 1}
                chunks, subjects_by_name, chapters_by_title = await asyncio.gather(
                    db.chunks.find(_chunk_text_filter_ns, _chunk_proj_ns).sort([("score", {"$meta": "textScore"})]).limit(15).to_list(15),
                    db.subjects.find(subj_kw_filter, _subj_proj).limit(55).to_list(55),
                    db.chapters.find(ch_title_filter, _ch_proj).sort("order_index", 1).limit(25).to_list(25),
                )
            except Exception:
                chunks, subjects_by_name, chapters_by_title = await asyncio.gather(
                    db.chunks.find({"$or": regex_parts}, {"_id": 0, "chapter_id": 1, "content": 1, "content_type": 1, "subject_id": 1, "priority": 1, "topic_name": 1, "chapter_title": 1}).sort("priority", 1).limit(15).to_list(15),
                    db.subjects.find(subj_kw_filter, _subj_proj).limit(55).to_list(55),
                    db.chapters.find(ch_title_filter, _ch_proj).sort("order_index", 1).limit(25).to_list(25),
                )

            # ── Resolve chunks → parent subjects (via chapter_id) ─────────────────
            chunk_chapter_ids = list({c["chapter_id"] for c in chunks if c.get("chapter_id")})
            chunk_parent_chapters: list = []
            if chunk_chapter_ids:
                chunk_parent_chapters = await db.chapters.find(
                    {"id": {"$in": chunk_chapter_ids}}, {"_id": 0, "id": 1, "subject_id": 1, "title": 1, "slug": 1}
                ).to_list(10)

            # Collect all subject IDs reached via chapters and chunks
            existing_ids = {s["id"] for s in subjects_by_name}
            via_chapter_ids = {c["subject_id"] for c in chapters_by_title if c.get("subject_id")} - existing_ids
            via_chunk_ids   = {c["subject_id"] for c in chunk_parent_chapters if c.get("subject_id")} - existing_ids - via_chapter_ids

            # Fetch the extra subjects (those reached only through chapter/chunk paths)
            extra_ids = list(via_chapter_ids | via_chunk_ids)
            extra_subjects: list = []
            if extra_ids:
                extra_subjects = await db.subjects.find(
                    {"id": {"$in": extra_ids}, "status": "published"},
                    {"_id": 0, "id": 1, "name": 1, "description": 1, "tags": 1, "icon": 1, "gradient": 1}
                ).to_list(20)

            # ── Score & re-rank ALL candidate subjects ────────────────────────────
            # Priority order (user-specified):
            #   1. Chunk content matches  → +5 per matching chunk   (actual study material)
            #   2. Chapter title matches  → +3 per keyword in title (topical chapter signal)
            #   3. Subject name matches   → +1 per keyword in name  (broad category signal)
            #   Bonus: +8 when exact subject name is a substring of the query
            query_lower = query.lower()

            # Per-subject chunk count (how many matching chunks came from each subject)
            chunk_subject_count: dict[str, int] = {}
            for c in chunk_parent_chapters:
                sid = c.get("subject_id", "")
                if sid:
                    chunk_subject_count[sid] = chunk_subject_count.get(sid, 0) + 1

            # Per-subject chapter-title keyword-hit count
            chapter_title_score: dict[str, int] = {}
            for ch in chapters_by_title:
                sid = ch.get("subject_id", "")
                if not sid:
                    continue
                title_lower = ch.get("title", "").lower()
                hits = sum(1 for kw in keywords if kw in title_lower)
                chapter_title_score[sid] = chapter_title_score.get(sid, 0) + hits

            def _subject_score(s: dict) -> int:
                name_lower = s.get("name", "").lower()
                sid = s.get("id", "")
                # Priority 1 — chunk content (highest)
                score  = chunk_subject_count.get(sid, 0) * 5
                # Priority 2 — chapter title keyword density
                score += chapter_title_score.get(sid, 0) * 3
                # Priority 3 — subject name keyword match (lowest)
                score += sum(1 for kw in keywords if kw in name_lower)
                # Exact subject name mentioned in query (strong explicit intent)
                score += 8 if (name_lower and name_lower in query_lower) else 0
                return score

            all_candidates = subjects_by_name + extra_subjects
            if len(all_candidates) > 1:
                all_candidates = sorted(all_candidates, key=_subject_score, reverse=True)
            # Deduplicate by name (keep the highest-scored version of each subject name)
            seen_names: set = set()
            deduped: list = []
            for s in all_candidates:
                n = s.get("name", "").lower()
                if n not in seen_names:
                    seen_names.add(n)
                    deduped.append(s)
            subjects_found = deduped[:3]

            # ── Filter chunks to the dominant subject only ─────────────────────
            # Prevents unrelated subjects (e.g. Indian Constitution appearing when
            # the user asks about Business Studies) from contaminating the answer.
            top_subject_ids = [s["id"] for s in subjects_found]
            if subjects_found and chunk_parent_chapters:
                dominant_sid = subjects_found[0].get("id", "")
                if dominant_sid:
                    dominant_chapter_ids = {
                        cc["id"] for cc in chunk_parent_chapters
                        if cc.get("subject_id") == dominant_sid
                    }
                    filtered_chunks = [c for c in chunks if c.get("chapter_id") in dominant_chapter_ids]
                    if filtered_chunks:  # Only narrow if chunks remain
                        chunks = filtered_chunks
                        chunk_parent_chapters = [
                            cc for cc in chunk_parent_chapters
                            if cc.get("subject_id") == dominant_sid
                        ]

            # ── chapters_found: keyword-matching chapters scoped to top subjects ──
            if top_subject_ids:
                chapters_found = [c for c in chapters_by_title if c.get("subject_id") in top_subject_ids][:5]
                if not chapters_found:
                    chapters_found = chapters_by_title[:5]
            else:
                chapters_found = chapters_by_title[:5]

        # ── Determine quality ─────────────────────────────────────────────────
        if chunks:
            quality = "high"
            source  = "rag"
            logger.info(f"RAG [HIGH]: {len(chunks)} chunks, {len(chapters_found)} chapters | query: {query[:50]}")
        elif subjects_found or chapters_found:
            quality = "medium"
            source  = "rag"
            logger.info(f"RAG [MEDIUM]: 0 chunks, {len(subjects_found)} subjects, {len(chapters_found)} chapters | query: {query[:50]}")
        else:
            quality = "none"
            source  = "none"
            logger.info(f"RAG [NONE]: nothing found | query: {query[:50]}")

        result = {
            "chunks":         chunks,
            "chapters":       chapters_found,
            "chunk_chapters": chunk_parent_chapters,
            "subjects":       subjects_found,
            "source":         source,
            "quality":        quality,
        }
        _rag_cache[_rk] = result
        try:
            _record_rag_event(quality, round((time.time() - _rag_t0) * 1000, 1), query)
        except Exception:
            pass
        return result

    except Exception as e:
        logger.error(f"RAG search error: {e}")
        return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}



async def syrabit_library_search(
    query: str,
    board_slug: str = None,
    class_slug: str = None,
) -> list:
    """Search Syrabit's own SEO pages + subjects library.
    Returns up to 4 dicts: {title, url, snippet} — always clickable syrabit.ai links."""
    if not await is_mongo_available():
        return []

    keywords = _extract_keywords(query)
    if not keywords:
        return []

    search_hash = _cache_key(f"libsearch:{query}:{board_slug}:{class_slug}")
    cached = _redis_get_search(search_hash)
    if cached is not None:
        return cached

    pattern = "|".join(re.escape(kw) for kw in keywords[:5])
    rx = {"$regex": pattern, "$options": "i"}
    results: list = []
    seen: set = set()

    try:
        page_filter: dict = {
            "status": "published",
            "$or": [
                {"topic_title": rx},
                {"meta_description": rx},
                {"subject_name": rx},
            ],
        }
        if board_slug:
            page_filter["board_slug"] = board_slug
        if class_slug:
            page_filter["class_slug"] = class_slug

        async with _slow_query(f"syrabit_library_search q={query[:30]}"):
            pages = await db.seo_pages.find(
                page_filter,
                {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1,
                 "topic_slug": 1, "topic_title": 1, "meta_description": 1, "subject_name": 1},
            ).limit(4).to_list(4)

        for p in pages:
            url = (
                f"https://syrabit.ai/{p['board_slug']}/{p['class_slug']}"
                f"/{p['subject_slug']}/{p['topic_slug']}"
            )
            if url not in seen:
                seen.add(url)
                results.append({
                    "title": p.get("topic_title") or f"{p.get('subject_name', '')} — {p['topic_slug']}",
                    "url": url,
                    "snippet": (p.get("meta_description") or "")[:160],
                })
    except Exception as exc:
        logger.debug(f"syrabit_library_search seo_pages error: {exc}")

    # ── 2. Subjects (fills gaps up to 4 results) ───────────────────────────────
    if len(results) < 4:
        try:
            subj_filter: dict = {
                "status": "published",
                "$or": [{"name": rx}, {"description": rx}, {"tags": rx}],
            }
            subjects = await db.subjects.find(
                subj_filter,
                {"_id": 0, "id": 1, "name": 1, "description": 1},
            ).limit(4 - len(results)).to_list(4)

            for s in subjects:
                url = f"https://syrabit.ai/subject/{s['id']}" if s.get("id") else "https://syrabit.ai/library"
                if url not in seen:
                    seen.add(url)
                    results.append({
                        "title": s.get("name", "Syrabit Library"),
                        "url": url,
                        "snippet": (s.get("description") or "")[:160],
                    })
        except Exception as exc:
            logger.debug(f"syrabit_library_search subjects error: {exc}")

    final = results[:1]
    if final:
        _redis_cache_search(search_hash, final)
    return final


async def _fetch_enrichment_blocks(
    intent: str,
    subject_id: Optional[str] = None,
    chapter_title: Optional[str] = None,
) -> str:
    try:
        if not await is_mongo_available():
            return ""
        blocks = []

        ch_filter: dict = {}
        if subject_id:
            ch_filter["subject_id"] = subject_id
        if chapter_title:
            ch_filter["title"] = {"$regex": re.escape(chapter_title), "$options": "i"}

        if intent in ("important_questions", "lesson_questions", "marks_wise"):
            _proj = {
                "_id": 0, "title": 1, "mark_wise_questions": 1,
                "important_questions": 1, "subject_id": 1,
            }
            all_iq_chapters = await db.chapters.find(
                {**ch_filter, "$or": [
                    {"mark_wise_questions": {"$exists": True, "$ne": {}}},
                    {"important_questions": {"$exists": True, "$ne": []}},
                ]},
                _proj,
            ).to_list(20)

            chapters = all_iq_chapters[:1]
            remaining_ch_names = [c.get("title", "") for c in all_iq_chapters[1:] if c.get("title")]

            for ch in chapters:
                ch_title = ch.get("title", "Chapter")
                mw = ch.get("mark_wise_questions", {})
                imp = ch.get("important_questions", [])
                if not mw and not imp:
                    continue

                unified: dict[int, list[str]] = {}
                if mw and isinstance(mw, dict):
                    for mark_val, questions in mw.items():
                        try:
                            mk = int(mark_val)
                        except (ValueError, TypeError):
                            mk = 0
                        if mk not in unified:
                            unified[mk] = []
                        for q in questions[:10]:
                            q_text = q.get("question", q) if isinstance(q, dict) else str(q)
                            if q_text and q_text not in unified[mk]:
                                unified[mk].append(q_text)
                if imp:
                    for q in imp[:15]:
                        q_text = q.get("question", q) if isinstance(q, dict) else str(q)
                        placed = False
                        if isinstance(q, dict) and q.get("marks"):
                            try:
                                mk = int(q["marks"])
                                if mk not in unified:
                                    unified[mk] = []
                                if q_text not in unified[mk]:
                                    unified[mk].append(q_text)
                                placed = True
                            except (ValueError, TypeError):
                                pass
                        if not placed and q_text:
                            mk = 0
                            if mk not in unified:
                                unified[mk] = []
                            if q_text not in unified[mk]:
                                unified[mk].append(q_text)

                block = f"[Questions: {ch_title}]\n"
                for mk in sorted(unified.keys()):
                    if mk == 0:
                        block += "**General Important Questions**\n"
                    else:
                        block += f"**{mk}-Mark Questions**\n"
                    for qi, q_text in enumerate(unified[mk], 1):
                        block += f"{qi}. {q_text}\n"
                if remaining_ch_names:
                    block += f"\n[OTHER CHAPTERS WITH QUESTIONS: {', '.join(remaining_ch_names)}]\n"
                blocks.append(block)

        if intent == "flashcards":
            _proj = {"_id": 0, "title": 1, "memory_tricks": 1}
            chapters = await db.chapters.find(
                {**ch_filter, "memory_tricks": {"$exists": True, "$ne": []}},
                _proj,
            ).limit(3).to_list(3)

            for ch in chapters:
                ch_title = ch.get("title", "Chapter")
                tricks = ch.get("memory_tricks", [])
                if not tricks:
                    continue
                block = f"**[FLASHCARDS: {ch_title}]**\n"
                for fi, fc in enumerate(tricks[:20], 1):
                    if isinstance(fc, dict):
                        q = fc.get("question", fc.get("front", fc.get("q", "")))
                        a = fc.get("answer", fc.get("back", fc.get("a", "")))
                        block += f"Q{fi}: {q}\nA{fi}: {a}\n\n"
                    else:
                        block += f"{fi}. {fc}\n"
                blocks.append(block)

        if intent in ("pyq", "solved_pyq"):
            pyq_filter: dict = {}
            if subject_id:
                pyq_filter["subject_id"] = subject_id
            pyq_pages = await db.pyq_html_pages.find(
                pyq_filter,
                {"_id": 0, "subject_name": 1, "exam_year": 1, "questions": 1,
                 "paper_type": 1},
            ).sort("exam_year", -1).limit(3).to_list(3)

            for pyq in pyq_pages:
                subj = pyq.get("subject_name", "")
                year = pyq.get("exam_year", "")
                questions = pyq.get("questions", [])
                if not questions:
                    continue
                block = f"**[PYQ PAPER: {subj} {year}]**\n"
                for q in questions[:20]:
                    num = q.get("number", "")
                    text = q.get("text", "")
                    marks = q.get("marks", "")
                    marks_label = f" [{marks} marks]" if marks else ""
                    block += f"{num}. {text}{marks_label}\n"
                    sub_parts = q.get("sub_parts", [])
                    for sp in sub_parts[:5]:
                        block += f"   - {sp}\n"
                blocks.append(block)

        result = "\n\n".join(blocks)
        if result:
            logger.info(f"Enrichment blocks fetched for intent={intent}: {len(blocks)} blocks, {len(result)} chars")
        return result
    except Exception as e:
        logger.error(f"Enrichment block fetch error: {e}")
        return ""


async def resolve_rag_context(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    document_text: Optional[str] = None,
    intent: Optional[str] = None,
    db_category: Optional[str] = None,
) -> dict:
    """
    Master RAG resolver — 4-tier priority chain:

      Tier 0 — Subject document (uploaded .txt file): ALWAYS wins when present
      Tier 1 — DB content chunks (indexed notes/formulas)
      Tier 2 — Subject metadata (descriptions, tags, chapter titles)
    """
    # ── Tier 0: Subject document (uploaded file) ─────────────────────────────
    # When a document is uploaded and the user asks AI from that card,
    # the document is the PRIMARY source — skip all other RAG tiers.
    if document_text and document_text.strip():
        logger.info(f"RAG [TIER 0 — Document]: using uploaded document ({len(document_text)} chars) | query: {query[:50]}")
        # Slice relevant sections: find paragraphs containing query keywords
        keywords = _extract_keywords(query)
        lines = [l.strip() for l in document_text.split('\n') if l.strip()]

        # Score each line by keyword matches
        scored = []
        for i, line in enumerate(lines):
            score = sum(1 for kw in keywords if kw in line.lower())
            scored.append((score, i, line))

        _is_syllabus_intent = (intent or "").lower() == "syllabus"
        _doc_char_limit = 5000 if _is_syllabus_intent else 3000

        scored.sort(key=lambda x: -x[0])
        selected_indices = set()
        for score, idx, _ in scored[:8]:
            if score > 0:
                for j in range(max(0, idx - 1), min(len(lines), idx + 3)):
                    selected_indices.add(j)

        if selected_indices:
            relevant = "\n".join(lines[i] for i in sorted(selected_indices))
            relevant = relevant[:_doc_char_limit]
        else:
            relevant = document_text[:_doc_char_limit]

        _resolved_intent_t0 = intent or "general"
        return {
            "chunks": [],
            "chapters": [],
            "subjects": [],
            "document_text": relevant,
            "document_full": document_text[:_doc_char_limit],
            "source":  "document",
            "quality": "tier0",
            "intent":  _resolved_intent_t0,
        }
    from rag_router import should_trigger_rag, filter_rag_by_category, RAG_RELEVANCE_GATE, HIGH_CONFIDENCE_THRESHOLD
    try:
        _RELEVANCE_GATE = float(os.getenv("RAG_RELEVANCE_GATE", str(RAG_RELEVANCE_GATE)))
    except ValueError:
        _RELEVANCE_GATE = RAG_RELEVANCE_GATE

    from prompts import ENRICHMENT_INTENTS, INTENT_TO_DB_CATEGORY
    _resolved_intent = intent or "notes"
    _db_category = db_category or INTENT_TO_DB_CATEGORY.get(_resolved_intent)
    _want_enrichment = _resolved_intent in ENRICHMENT_INTENTS

    _syllabus_sim = 0.0
    _syllabus_chapter_title = ""
    _syllabus_topic_name = ""
    _syl_match = None
    try:
        import server as _srv
        _embedder = getattr(_srv, "_syllabus_embedder", None)
        if _embedder is not None:
            _syl_match = await asyncio.wait_for(
                _embedder.classify(query, subject_id=subject_id),
                timeout=2.0,
            )
            if _syl_match:
                _syllabus_sim = _syl_match.similarity
                _syllabus_chapter_title = _syl_match.chapter_title or ""
                _syllabus_topic_name = _syl_match.topic or ""
                logger.info(
                    f"RAG resolve: syllabus classify sim={_syllabus_sim:.3f} "
                    f"chapter='{_syllabus_chapter_title}' | query: {query[:50]}"
                )
    except Exception as _syl_exc:
        logger.warning(f"RAG resolve: syllabus classify failed: {_syl_exc}")

    _syllabus_high_conf = _syllabus_sim >= HIGH_CONFIDENCE_THRESHOLD

    if _syllabus_high_conf:
        logger.info(
            f"RAG resolve: SYLLABUS HIGH-CONFIDENCE fast-path "
            f"(syl_sim={_syllabus_sim:.3f} >= {HIGH_CONFIDENCE_THRESHOLD}) — "
            f"skipping vector_rag_search + keyword rag_search, chapter-scoped retrieval "
            f"for '{_syllabus_chapter_title}' | intent={_resolved_intent} | query: {query[:50]}"
        )
        vector_hits = []
        _best_vec_sim = 0.0
        _gather_tasks = [
            _fetch_content_card(
                query, subject_id=subject_id, subject_name=subject_name,
                intent=_resolved_intent, chapter_title=_syllabus_chapter_title,
            ),
        ]
        if _want_enrichment:
            _gather_tasks.append(
                _fetch_enrichment_blocks(
                    _resolved_intent, subject_id=subject_id,
                    chapter_title=_syllabus_chapter_title,
                )
            )
        _results = await asyncio.gather(*_gather_tasks)
        _card_result = _results[0]
        _enrichment_result = _results[1] if _want_enrichment else ""
        _syl_subject_entry = []
        if _syl_match and _syl_match.subject_id:
            _syl_subject_entry = [{"id": _syl_match.subject_id, "name": _syl_match.subject_name}]
        cached_rag = {"chunks": [], "chapters": [], "subjects": _syl_subject_entry, "source": "rag", "quality": "high"}

    else:
        vector_hits = await vector_rag_search(query, subject_id=subject_id, top_k=5, db_category=_db_category)
        _best_vec_sim = max((h.get("score", 0) for h in vector_hits), default=0.0) if vector_hits else 0.0

        _gate_sim = max(_syllabus_sim, _best_vec_sim)
        _rag_should_trigger = should_trigger_rag(_resolved_intent, _gate_sim)

        if not _rag_should_trigger:
            logger.info(
                f"RAG resolve: SKIPPED (early gate) — intent={_resolved_intent}, "
                f"syllabus_sim={_syllabus_sim:.3f}, vec_sim={_best_vec_sim:.3f}, gate={_RELEVANCE_GATE} "
                f"| query: {query[:50]}"
            )
            try:
                _record_rag_event("none", 0, query, intent=_resolved_intent)
            except Exception:
                pass
            return {
                "chunks": [], "chapters": [], "subjects": [], "vector_hits": [],
                "source": "none", "quality": "none", "intent": _resolved_intent,
            }

        _vec_high_conf = (
            _best_vec_sim >= HIGH_CONFIDENCE_THRESHOLD
            and any(h.get("content") and len(h.get("content", "")) > 100 for h in vector_hits)
        )

        if _vec_high_conf:
            logger.info(
                f"RAG resolve: VECTOR HIGH-CONFIDENCE fast-path "
                f"(vec_sim={_best_vec_sim:.3f} >= {HIGH_CONFIDENCE_THRESHOLD}) — "
                f"skipping keyword rag_search | intent={_resolved_intent} | query: {query[:50]}"
            )
            _gather_tasks = [
                _fetch_content_card(query, subject_id=subject_id, subject_name=subject_name, intent=_resolved_intent),
            ]
            if _want_enrichment:
                _gather_tasks.append(
                    _fetch_enrichment_blocks(
                        _resolved_intent, subject_id=subject_id,
                        chapter_title=_syllabus_chapter_title,
                    )
                )
            _results = await asyncio.gather(*_gather_tasks)
            _card_result = _results[0]
            _enrichment_result = _results[1] if _want_enrichment else ""
            _syl_subject_entry2 = []
            if _syl_match and _syl_match.subject_id:
                _syl_subject_entry2 = [{"id": _syl_match.subject_id, "name": _syl_match.subject_name}]
            cached_rag = {"chunks": [], "chapters": [], "subjects": _syl_subject_entry2, "source": "rag", "quality": "high"}
        else:
            _gather_tasks = [
                rag_search(query, subject_id=subject_id, subject_name=subject_name),
                _fetch_content_card(query, subject_id=subject_id, subject_name=subject_name, intent=_resolved_intent),
            ]
            if _want_enrichment:
                _gather_tasks.append(
                    _fetch_enrichment_blocks(_resolved_intent, subject_id=subject_id, chapter_title="")
                )
            _results = await asyncio.gather(*_gather_tasks)
            cached_rag = _results[0]
            _card_result = _results[1]
            _enrichment_result = _results[2] if _want_enrichment else ""

    rag_ctx = dict(cached_rag)

    content_card_text: Optional[str] = None
    content_card_slugs: set = set()
    if _card_result:
        content_card_text, content_card_slugs, _card_source_meta = _card_result
        rag_ctx["content_card"] = content_card_text
        rag_ctx["content_card_slugs"] = content_card_slugs
        rag_ctx["content_card_meta"] = _card_source_meta
        if rag_ctx["quality"] == "none":
            rag_ctx["quality"] = "high"
            rag_ctx["source"] = "rag"
        logger.info(f"RAG resolve: content card found ({len(content_card_text)} chars, {len(content_card_slugs)} slugs) | query: {query[:50]}")

    if vector_hits:
        deduped = [h for h in vector_hits if h.get("slug") not in content_card_slugs]
        rag_ctx["vector_hits"] = deduped
        if rag_ctx["quality"] == "none" and deduped:
            rag_ctx["quality"] = "high"
            rag_ctx["source"] = "rag"
        logger.info(f"RAG resolve: vector hits={len(deduped)} (from {len(vector_hits)}, best_sim={_best_vec_sim:.3f}, cat_filter={'yes' if _db_category else 'no'}) | query: {query[:50]}" if deduped else f"RAG resolve: vector hits=0 (all filtered/deduped)")

    if _enrichment_result:
        rag_ctx["enrichment_blocks"] = _enrichment_result
        if rag_ctx["quality"] == "none":
            rag_ctx["quality"] = "high"
            rag_ctx["source"] = "rag"

    if _db_category and rag_ctx.get("chunks"):
        rag_ctx["chunks"] = filter_rag_by_category(rag_ctx["chunks"], _db_category)

    _has_chunks = bool(rag_ctx.get("chunks"))
    _has_vectors = bool(rag_ctx.get("vector_hits"))
    _has_card = bool(content_card_text)
    _has_enrichment = bool(_enrichment_result)
    if rag_ctx["quality"] == "high" and not (_has_chunks or _has_vectors or _has_card or _has_enrichment):
        if _syllabus_high_conf and _syllabus_chapter_title:
            try:
                _ch_doc = await db.chapters.find_one(
                    {"title": {"$regex": re.escape(_syllabus_chapter_title), "$options": "i"},
                     **({"subject_id": subject_id} if subject_id else {})},
                    {"_id": 0, "content": 1, "title": 1, "topics": 1, "subject_id": 1},
                )
                _ch_content = (_ch_doc or {}).get("content", "") if _ch_doc else ""
                if _ch_content and len(_ch_content) > 50:
                    if _syllabus_topic_name:
                        _topic_section = _extract_topic_section(_ch_content, _syllabus_topic_name, query)
                        if _topic_section:
                            _ch_content = _topic_section
                    rag_ctx["content_card"] = _ch_content
                    content_card_text = _ch_content
                    _has_card = True
                    rag_ctx["quality"] = "high"
                    rag_ctx["source"] = "rag"
                    _fb_title = (_ch_doc or {}).get("title", _syllabus_chapter_title)
                    rag_ctx["content_card_meta"] = {
                        "card_name": _fb_title,
                        "lesson_name": _fb_title,
                        "subject_name": subject_name or "",
                        "board_name": "",
                        "class_name": "",
                        "card_slug": "",
                    }
                    logger.info(
                        f"RAG resolve: chapter content fallback ({len(_ch_content)} chars) "
                        f"for syllabus match '{_syllabus_chapter_title}' | query: {query[:50]}"
                    )
            except Exception as _fb_err:
                logger.warning(f"RAG resolve: chapter fallback error: {_fb_err}")
        if not _has_card:
            rag_ctx["quality"] = "none"
            rag_ctx["source"] = "none"
            logger.info(f"RAG resolve: quality downgraded to NONE after category filtering — intent={_resolved_intent}")

    _final_quality = rag_ctx["quality"]
    rag_ctx["intent"] = _resolved_intent
    rag_ctx["db_category"] = _db_category
    rag_ctx["syllabus_topic_name"] = _syllabus_topic_name

    if _final_quality == "high":
        logger.info(f"RAG resolve: HIGH-QUALITY content (chunks: {len(rag_ctx.get('chunks', []))}, vector: {len(rag_ctx.get('vector_hits', []))}, card: {'yes' if _has_card else 'no'}, best_sim={_best_vec_sim:.3f}, intent: {_resolved_intent}) | query: {query[:50]}")
    elif _final_quality == "medium":
        logger.info(f"RAG resolve: MEDIUM metadata only | intent: {_resolved_intent} | query: {query[:50]}")
    else:
        logger.info(f"RAG resolve: NO CONTEXT — AI uses training knowledge | intent: {_resolved_intent} | query: {query[:50]}")
        rag_ctx = {"chunks": [], "chapters": [], "subjects": [], "vector_hits": [], "source": "none", "quality": "none", "intent": _resolved_intent}

    try:
        _record_rag_event(_final_quality, 0, query, intent=_resolved_intent)
    except Exception:
        pass
    return rag_ctx



# ── Web search helpers ────────────────────────────────────────────────────────

async def _ddg_text_search(query: str, num_results: int) -> list:
    """DuckDuckGo text search — primary browser-style web search."""
    def _run():
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return results
    try:
        loop = asyncio.get_running_loop()
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=1.5)
        logger.info(f"DDG text search: {len(results)} results | query: {query[:60]}")
        return results
    except Exception as exc:
        logger.warning(f"DDG text search failed: {exc}")
        return []


async def _ddg_news_search(query: str, num_results: int) -> list:
    """DuckDuckGo news search — secondary fallback web source."""
    def _run():
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=num_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("url", r.get("href", "")),
                    "snippet": r.get("body", r.get("excerpt", "")),
                })
        return results
    try:
        loop = asyncio.get_running_loop()
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=1.5)
        logger.info(f"DDG news search: {len(results)} results | query: {query[:60]}")
        return results
    except Exception as exc:
        logger.warning(f"DDG news search failed: {exc}")
        return []


async def web_search_with_fallback(
    query: str,
    num_results: int = 8,
    board_name: str = "",
    class_name: str = "",
    subject_name: str = "",
    scoped_query: str = "",   # Pre-built by SubjectRouter (preferred over manual parts)
) -> list:
    """
    Parallel dual-source web search:
      Base layer  — DuckDuckGo text search with curriculum-scoped query.
                    Uses `scoped_query` when provided (from SubjectRouter Tier 0-3),
                    otherwise builds it from board_name / class_name / subject_name.
      Polish layer — DuckDuckGo news search with the raw user query
                     for open-web enrichment, current examples, reasoning.
    Both run simultaneously. Results tagged with _layer for prompt routing.
    """
    _assert_not_cms_context("web search")
    if scoped_query:
        curriculum_query = scoped_query
    else:
        _ctx_parts = [p.strip() for p in [board_name, class_name, subject_name] if p]
        curriculum_query = " ".join(_ctx_parts + [query]) if _ctx_parts else query

    text_results, news_results = await asyncio.gather(
        _ddg_text_search(curriculum_query, num_results),
        _ddg_news_search(query, max(num_results - 2, 4)),
    )
    for r in text_results:
        r["_layer"] = "base"
    for r in news_results:
        r["_layer"] = "polish"
    combined = text_results + news_results
    logger.info(
        f"Dual web search: {len(text_results)} base (scoped: {curriculum_query[:60]!r}) + "
        f"{len(news_results)} polish (open) | raw: {query[:50]}"
    )

    try:
        from web_content import enrich_search_results
        combined = await enrich_search_results(combined)
    except Exception as e:
        logger.warning(f"Web content enrichment failed (using snippets only): {e}")

    return combined


_HISTORY_TOKEN_BUDGET = 1500  # max estimated tokens kept in conversation history
_HISTORY_MAX_TURNS = 8        # max message pairs regardless of token budget


def _trim_history(messages: list, token_budget: int = _HISTORY_TOKEN_BUDGET, max_turns: int = _HISTORY_MAX_TURNS) -> list:
    """
    Return the most recent portion of a conversation history that fits within
    the token budget and max-turn limit.  Oldest turns are dropped first.
    Estimation: 1 token ≈ 4 chars (conservative English approximation).
    """
    # Keep only alternating user/assistant pairs (already filtered upstream)
    # Cap by hard turn limit first
    capped = messages[-(max_turns * 2):]

    # Trim from the front until estimated token count is within budget
    while capped:
        total_chars = sum(len(m.get("content", "")) for m in capped)
        if total_chars // 4 <= token_budget:
            break
        # Drop the two oldest messages (one turn)
        capped = capped[2:]

    return capped


def _sources_from_rag_ctx(rag_ctx: dict) -> list:
    """
    Build a sources list directly from the RAG context that was sent to the LLM.
    This ensures the displayed sources always match the grounding context used in
    the prompt (no mismatch from a separate async library search).

    Returns a list of dicts with keys: slug, title, url (compatible with the
    frontend sources format). URLs are auto-built as /learn/{slug} for SEO pages
    so the frontend can render clickable blue links for [PAGE: X] citations.
    When content_card_meta is present, emits a leading content_card source entry
    with type="content_card", card_name, and lesson_name for clean attribution.
    """
    seen = set()
    sources = []

    _cc_meta = rag_ctx.get("content_card_meta")
    if _cc_meta and (_cc_meta.get("card_name") or _cc_meta.get("lesson_name")):
        _cc_slug = _cc_meta.get("card_slug", "")
        _cc_url = f"/learn/{_cc_slug}" if _cc_slug and not _cc_slug.startswith("chapter/") else ""
        sources.append({
            "type":         "content_card",
            "card_name":    _cc_meta.get("card_name", ""),
            "lesson_name":  _cc_meta.get("lesson_name", ""),
            "subject_name": _cc_meta.get("subject_name", ""),
            "board_name":   _cc_meta.get("board_name", ""),
            "class_name":   _cc_meta.get("class_name", ""),
            "slug":         _cc_slug,
            "title":        _cc_meta.get("card_name", "") or _cc_meta.get("lesson_name", ""),
            "url":          _cc_url,
        })

    def _build_url(slug: str, provided_url: str, subject_id: str = "") -> str:
        """Return the best available URL for a source."""
        if provided_url:
            return provided_url
        # SEO page slugs map to /learn/{slug}
        if slug and not slug.startswith("chapter/"):
            return f"/learn/{slug}"
        # Chapter slugs: link to subject page so the student can browse
        if slug and slug.startswith("chapter/") and subject_id:
            return f"/subject/{subject_id}"
        return ""

    def _add(slug: str, title: str, url: str = "", subject_id: str = ""):
        if slug and slug not in seen:
            seen.add(slug)
            sources.append({
                "slug":  slug,
                "title": title or slug,
                "url":   _build_url(slug, url, subject_id),
            })

    # Build a lookup: chapter_id → chapter info (title, subject_id) from chunk_chapters
    chunk_chapter_map: dict = {}
    for cc in rag_ctx.get("chunk_chapters", []):
        cid = cc.get("id", "")
        if cid:
            chunk_chapter_map[cid] = cc

    # SEO vector hits (have real topic slugs → /learn/...)
    for hit in rag_ctx.get("vector_hits", []):
        _add(hit.get("slug", ""), hit.get("title", ""), hit.get("url", ""))

    # Chunks — group by parent chapter so 15 chunks from 3 chapters show 3 source entries
    for chunk in rag_ctx.get("chunks", []):
        ch_id = chunk.get("chapter_id", "")
        cc = chunk_chapter_map.get(ch_id, {})
        slug = chunk.get("slug", "") or (f"chapter/{ch_id}" if ch_id else "")
        title = chunk.get("title", "") or cc.get("title", chunk.get("content_type", "Study Material"))
        url = chunk.get("url", "")
        _add(slug, title, url, cc.get("subject_id", ""))

    # Keyword-matched chapters (may add extras not covered by chunks above)
    for ch in rag_ctx.get("chapters", []):
        ch_id = ch.get("id", "")
        slug = ch.get("slug", "") or (f"chapter/{ch_id}" if ch_id else "")
        _add(slug, ch.get("title", ""), ch.get("url", ""), ch.get("subject_id", ""))

    for subj in rag_ctx.get("subjects", []):
        _add(subj.get("slug", ""), subj.get("name", ""), subj.get("url", ""))

    return sources


def build_rag_system_prompt(
    context: dict,
    rag_context: dict,
    user_info: dict = None,
    query: str = "",
    syllabus: dict = None,
    web_results: list = None,
    resolved_intent: str = "",
) -> str:
    """
    Selects the adaptive prompt mode (casual / concise / structured) based on
    the student's query, injects their profile, then appends RAG grounding.

    Grounding tiers:
      Tier -1 — syllabus constraints (curriculum boundaries)
      Tier 0 — document (uploaded .txt file — absolute priority)
      Tier 1 — DB content chunks
      Tier 2 — Subject metadata (descriptions, tags, chapter titles)
      Tier 3 — Web search results (fallback when library has no content)
    """
    from prompts import build_system_prompt, _classify_question, classify_intent, _format_board_label as _fbl, get_intent_extraction_rules
    import re as _re
    base_prompt = build_system_prompt(context, user_info=user_info, query=query, resolved_intent=resolved_intent)
    source      = rag_context.get("source",  "none")
    quality     = rag_context.get("quality", "none")

    _has_syllabus_topic = bool(rag_context.get("syllabus_topic_name"))
    if quality == "high" and _has_syllabus_topic:
        base_prompt = _re.sub(
            r'2\. ANSWERING:.*?(?=3\. FOCUS)',
            '2. ANSWERING: The grounding context below contains curriculum content '
            'that matches the student\'s question. You MUST answer from it. '
            'The student\'s wording may differ from the content — always treat the grounding as the correct match.\n',
            base_prompt,
            flags=_re.DOTALL,
        )

    _content_intents = {"notes", "important_questions", "pyq"}
    _incoming_intent = resolved_intent if resolved_intent else (classify_intent(query)[0] if query else "notes")
    if _incoming_intent in _content_intents:
        base_prompt += (
            "\n\nCONTENT RULE: Answer from the grounding context below. "
            "Do NOT invent content. Accuracy over completeness."
        )
    if _incoming_intent == "pyq":
        base_prompt += (
            "\n\nPYQ RULE: The student is asking for a question paper or previous year questions. "
            "If the grounding context contains actual question paper content (numbered questions, marks), "
            "present the EXACT questions as they appear — do NOT paraphrase or summarize them. "
            "Format them clearly with question numbers and marks. Show the full paper content."
        )
    chunks      = rag_context.get("chunks",   [])
    chapters    = rag_context.get("chapters", [])
    subjects    = rag_context.get("subjects", [])
    document_text = rag_context.get("document_text", "")
    vector_hits = rag_context.get("vector_hits", [])

    _ctx_subject_id = (context.get("subject_id") or "").strip()
    if _ctx_subject_id and vector_hits:
        vector_hits = [h for h in vector_hits if not h.get("subject_id") or h["subject_id"] == _ctx_subject_id]
    _board_raw = (context.get("board_name", "") or "").strip().upper()
    _board_label = _fbl(_board_raw) if _board_raw else "AssamBoard"
    _curriculum_label = f"{_board_label} Curriculum"

    _intent = resolved_intent if resolved_intent else (classify_intent(query)[0] if query else "notes")
    _is_casual = _intent in ("casual", "general")

    if not _is_casual:
        _src_chapter = (chapters[0].get("title", "") if chapters else "") or context.get("chapter_name", "")
        _src_subject = (subjects[0].get("name", "") if subjects else "") or context.get("subject_name", "")
        _src_course  = (context.get("stream_name", "") or "").strip()
        _src_board   = _board_label or "AssamBoard"
        _source_parts = []
        if _src_chapter:
            _source_parts.append(f"{_src_chapter} (unit name)")
        if _src_subject:
            _source_parts.append(f"{_src_subject} (subject name)")
        if _src_course:
            _source_parts.append(f"{_src_course} (course name)")
        _source_parts.append(f"{_src_board} (board name)")
        _source_line = " · ".join(_source_parts)
        base_prompt += (
            f"\n\nSOURCE: At the very end of your response, add on its own line:\n"
            f"SOURCE : {_source_line}"
        )

    grounding = ""

    # ── Tier -1: Syllabus constraints (curriculum boundaries) ───────────────────
    if syllabus and syllabus.get("content") and not _is_casual:
        syllabus_content = syllabus.get("content", "")
        syllabus_topics = ", ".join(syllabus.get("topics", [])[:10])
        grounding = (
            "\n\n---\n"
            f"**CURRICULUM ({_curriculum_label}):**\n"
            f"{syllabus_content}\n\n"
        )
        if syllabus_topics:
            grounding += f"**Key topics:** {syllabus_topics}\n\n"
        grounding += "---\n"

    # ── Tier -0.5: Exact chapter list from DB (for syllabus intent) ────────────
    _syl_chapters_list = rag_context.get("_syllabus_chapters", [])
    if _syl_chapters_list:
        _subject_name_for_syl = (subjects[0].get("name", "") if subjects else "") or context.get("subject_name", "")
        grounding += (
            "\n\n---\n"
            f"**SUBJECT CHAPTERS ({_subject_name_for_syl}):**\n"
            "The following is the EXACT chapter list from the database. "
            "Display these chapters EXACTLY as shown — do NOT rename, split, merge, or reformat them.\n\n"
        )
        for _idx, _ch in enumerate(_syl_chapters_list, 1):
            _ch_title = _ch.get("title", f"Chapter {_idx}")
            _ch_desc = _ch.get("description", "")
            grounding += f"**{_ch_title}**"
            if _ch_desc:
                grounding += f" — {_ch_desc}"
            grounding += "\n"
        grounding += "\n---\n"

    _chapter_topics_list = rag_context.get("_chapter_topics", [])
    if _chapter_topics_list and _intent in _content_intents:
        _subject_name_for_topics = (subjects[0].get("name", "") if subjects else "") or context.get("subject_name", "")
        grounding += (
            "\n\n---\n"
            f"**LESSON STRUCTURE ({_subject_name_for_topics}):**\n"
            "Use the following lesson (chapter) structure to organize your answer. "
            "Each entry is a lesson — answer within the scope of the relevant lesson.\n\n"
        )
        for _ct in _chapter_topics_list:
            _ct_title = _ct.get("title", "")
            _ct_desc = _ct.get("description", "")
            if not _ct_title:
                continue
            grounding += f"**{_ct_title}**"
            if _ct_desc:
                grounding += f" — {_ct_desc[:150]}"
            grounding += "\n"
        grounding += "\n---\n"

    # ── Tier 0: Uploaded subject document ────────────────────────────────────
    if source == "document" and document_text:
        grounding += (
            "\n\n---\n"
            "**GROUNDING CONTEXT (Tier 0 — Uploaded Study Document):**\n"
            "The student is asking about content from a specific uploaded study document. "
            "Base your answer **exclusively** on this document. Quote directly when possible.\n\n"
            "**Document content:**\n"
            f"{document_text}\n\n"
            "---\n"
            "*INSTRUCTION: Answer ONLY from the document above. "
            "If the question cannot be answered from this document, say so clearly "
            "and offer to answer from general knowledge instead.*"
        )
        return base_prompt + grounding

    # ── Tier 0-L: Library card context (from Ask AI button) ──────────────────
    if source == "library" and document_text:
        grounding += (
            "\n\n---\n"
            "**GROUNDING CONTEXT (Subject Library Context):**\n"
            "The student opened AI chat from a specific subject in the Syrabit library. "
            "Use this syllabus and chapter context to give accurate, curriculum-aligned answers. "
            "You may supplement with your general knowledge, but prioritize the syllabus content.\n\n"
            "**Subject & syllabus:**\n"
            f"{document_text}\n\n"
            "---\n"
        )
        return base_prompt + grounding

    content_card = rag_context.get("content_card", "")

    # ── Tier 1/2: Curriculum DB context (including vector hits) ─────────────
    if source == "rag" and (chunks or subjects or chapters or content_card or vector_hits):

        if quality == "high":
            _GROUNDING_BUDGET = 8000 if _intent in ("syllabus", "pyq") else 6000
            _budget_used = 0

            _syl_topic = rag_context.get("syllabus_topic_name", "")
            _topic_note = (
                f" The student is asking about the syllabus topic \"{_syl_topic}\" "
                f"(their query: \"{query[:80]}\"). "
                "The student's wording may differ from the content — treat the grounding as the correct match."
            ) if _syl_topic else (
                f" The student asked: \"{query[:80]}\". "
                "The student's wording may differ from the content headings — treat the grounding as the correct match."
            )
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Curriculum Database):**\n"
                f"Verified curriculum content.{_topic_note}\n\n"
            )

            if content_card and _budget_used < _GROUNDING_BUDGET:
                _card_budget = min(len(content_card), _GROUNDING_BUDGET - _budget_used)
                _trimmed_card = content_card[:_card_budget]
                _query_label = f" (answering: {query[:80]})" if query else ""
                grounding += f"**[CONTENT CARD{_query_label} — Full page content]:**\n{_trimmed_card}\n\n"
                _budget_used += len(_trimmed_card)

            if vector_hits and _budget_used < _GROUNDING_BUDGET:
                grounding += "**[VECTOR SEARCH RESULTS — Semantically matched pages]:**\n\n"
                _VH_MAX_HITS = 3
                _seen_titles = set()
                _sorted_hits = sorted(vector_hits, key=lambda h: h.get("score", 0), reverse=True)
                for hit in _sorted_hits[:_VH_MAX_HITS]:
                    if _budget_used >= _GROUNDING_BUDGET:
                        break
                    slug = hit.get("slug", "")
                    title = hit.get("title", slug)
                    if title.lower() in _seen_titles:
                        continue
                    _seen_titles.add(title.lower())
                    _raw_content = hit.get("content", "")
                    _vh_budget = min(1500, _GROUNDING_BUDGET - _budget_used)
                    if _raw_content and _intent == "notes" and query:
                        _raw_content = _extract_relevant_sections(
                            _raw_content, _extract_keywords(query),
                            max_chars=_vh_budget, intent=_intent, query=query,
                        )
                    elif len(_raw_content) > _vh_budget:
                        _raw_content = _raw_content[:_vh_budget] + "…"
                    score = hit.get("score", 0)
                    _pt = hit.get("page_type", "")
                    _pt_label = f" | type={_pt}" if _pt else ""
                    _vh_block = f"[PAGE: {slug}{_pt_label}] — {title} (relevance: {score:.2f})\n{_raw_content}\n\n"
                    grounding += _vh_block
                    _budget_used += len(_vh_block)

            _chunk_base_limit = 3000 if _intent in ("syllabus", "pyq") else 2000
            if chunks and _budget_used < _GROUNDING_BUDGET:
                for i, c in enumerate(chunks[:3], 1):
                    _remaining = _GROUNDING_BUDGET - _budget_used
                    if _remaining < 200:
                        break
                    title = c.get("content_type", "content").capitalize()
                    _per_chunk = min(_chunk_base_limit, _remaining)
                    _c_text = c.get('content', '')[:_per_chunk]
                    _chunk_block = f"**[BLOCK {i} — {title}]:**\n{_c_text}\n\n"
                    grounding += _chunk_block
                    _budget_used += len(_chunk_block)

            _enrichment = rag_context.get("enrichment_blocks", "")
            if _enrichment and _budget_used < _GROUNDING_BUDGET:
                _enr_budget = min(len(_enrichment), _GROUNDING_BUDGET - _budget_used)
                grounding += f"{_enrichment[:_enr_budget]}\n\n"
                _budget_used += _enr_budget

            _extraction_rules = get_intent_extraction_rules(_intent)
            if _extraction_rules:
                grounding += f"\n**INTENT-SPECIFIC GUIDANCE ({_intent}):**\n{_extraction_rules}\n\n"

            grounding += (
                "---\n"
                "**ANSWER RULES (RAG-FIRST):**\n"
                "1. RAG IS PRIMARY (80-90%): Build your answer from the grounding context above — definitions, formulas, explanations, facts from the curriculum database. This is verified content.\n"
                "2. YOUR KNOWLEDGE IS SUPPLEMENTARY (10-20%): Only use your own knowledge to explain concepts more clearly, add simple real-world examples, or bridge minor gaps in the grounding.\n"
                "3. NEVER contradict the RAG content. If grounding says X, your answer must say X.\n"
                "4. ADAPT to the student: Simplify language for board-exam students. Use analogies to make concepts click. Focus on what helps them understand and score well.\n"
                "5. Structure: Direct answer → Explanation with examples → Key points to remember.\n"
                "6. Do NOT add source citations inline — the system appends the SOURCE line automatically.\n"
                "7. NEVER hallucinate or invent facts. When unsure, stick to what the grounding provides.*\n\n"
                "⚠️ MANDATORY: Grounding context IS present above. This means the topic IS in the student's curriculum. "
                "You MUST answer from the grounding. Do NOT say 'outside your syllabus' or decline. Answer the question now."
            )

        else:
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Curriculum Metadata):**\n"
            )
            if content_card:
                grounding += f"**[Content Card — Full Page Content]**\n{content_card}\n\n"
            else:
                grounding += (
                    "The following curriculum metadata is from the syllabus database. "
                    "Use it to frame an accurate, board-aligned answer.\n\n"
                )
            if subjects:
                grounding += "**Matching subjects in database:**\n"
                for s in subjects:
                    desc = s.get("description", "")[:300]
                    tags = ", ".join(s.get("tags", [])[:8])
                    grounding += f"- **{s.get('name', '')}**: {desc}"
                    if tags:
                        grounding += f" *(key topics: {tags})*"
                    grounding += "\n"

            if chapters:
                grounding += "\n**Chapters & content in this subject:**\n"
                for ch in chapters:
                    title = ch.get('title', '')
                    desc = (ch.get('description') or '').strip()
                    ch_content = (ch.get('content') or '').strip()
                    grounding += f"- **{title}**"
                    if desc:
                        grounding += f": {desc[:300]}"
                    if ch_content and not desc:
                        grounding += f": {ch_content[:400]}"
                    grounding += "\n"

            _enrichment_med = rag_context.get("enrichment_blocks", "")
            if _enrichment_med:
                grounding += f"\n{_enrichment_med}\n\n"

            _extraction_rules_med = get_intent_extraction_rules(_intent)
            if _extraction_rules_med:
                grounding += f"\n**INTENT-SPECIFIC GUIDANCE ({_intent}):**\n{_extraction_rules_med}\n\n"

            grounding += (
                "\n---\n"
                "**ANSWER RULES (RAG-FIRST):**\n"
                f"1. RAG IS PRIMARY: Use the {_curriculum_label} metadata above as your factual anchor — subject structure, chapter topics, definitions.\n"
                "2. SUPPLEMENT WITH YOUR KNOWLEDGE: Add explanations, examples, and clarity. But always stay consistent with the curriculum context above.\n"
                "3. ADAPT to the student: Use simple language, relatable examples, and focus on what helps them understand and score well.\n"
                "4. Do NOT add source citations inline. NEVER hallucinate or invent facts.*"
            )

    # ── Live Web Search Results — EQUAL WEIGHTAGE with RAG ──────────────────
    if web_results:
        _has_internal = bool(chunks or subjects or chapters or content_card or vector_hits)
        base_results   = [r for r in web_results if r.get("_layer") != "polish"]
        polish_results = [r for r in web_results if r.get("_layer") == "polish"]

        web_block = "\n\n---\n"

        if _has_internal:
            web_block += (
                "**WEB SEARCH — SUPPLEMENTARY CONTEXT (secondary to RAG):**\n"
                "RAG content above is your PRIMARY source (80-90%). These web results are SUPPLEMENTARY. "
                "Only use web results to add real-world examples, recent updates, or fill gaps NOT covered by RAG. "
                "NEVER let web results override or contradict the RAG grounding.\n\n"
            )
        else:
            web_block += (
                "**WEB SEARCH — PRIMARY SOURCE (outside syllabus topic):**\n"
                "No syllabus content matched this topic. Use these web results as your primary factual base. "
                "Answer the student's question thoroughly using web content + your own knowledge.\n\n"
            )

        _any_enriched = any(r.get("_enriched") for r in web_results)

        for i, r in enumerate(base_results, 1):
            title   = r.get("title", "")
            url     = r.get("url", "")
            content = r.get("full_content") or r.get("snippet", "")
            _tag = "[Full Content]" if r.get("_enriched") else "[Snippet]"
            web_block += f"[Web {i}] {_tag} {title}\n{content}\nSource: {url}\n\n"

        for i, r in enumerate(polish_results, 1):
            title   = r.get("title", "")
            url     = r.get("url", "")
            content = r.get("full_content") or r.get("snippet", "")
            _tag = "[Full Content]" if r.get("_enriched") else "[Snippet]"
            web_block += f"[Web {len(base_results)+i}] {_tag} {title}\n{content}\nSource: {url}\n\n"

        if _has_internal:
            web_block += (
                "---\n"
                "**BLENDING INSTRUCTION (RAG DOMINANT):**\n"
                "*RAG content = PRIMARY authority (80-90%) — definitions, formulas, curriculum facts. "
                "Web results = supplementary only (10-20%) — examples, recent context. "
                "If web contradicts RAG, trust RAG. Build the answer from RAG first, then sprinkle web insights. "
                "Do not add source citations inline — the system appends SOURCE automatically. "
                "NEVER hallucinate or invent facts.*\n"
            )
        else:
            _enriched_note = (
                "Results marked [Full Content] contain detailed page text — rely on these heavily. "
                if _any_enriched else ""
            )
            web_block += (
                "---\n"
                "**ANSWER WEIGHTAGE (WEB + YOUR KNOWLEDGE):**\n"
                f"*{_enriched_note}"
                "1. Use web results as your factual anchor — extract key facts, definitions, explanations.\n"
                "2. Enrich with your own knowledge — deeper context, examples, analogies.\n"
                "3. Answer the student's actual question completely, even if it's outside the syllabus.\n"
                "Blend naturally. Do not fabricate facts.*\n"
            )
        grounding += web_block

    return base_prompt + grounding if grounding else base_prompt



# ── In-memory telemetry ring buffers (process-lifetime) ──────────────────────

_rag_telemetry: list = []          # {"ts", "quality", "latency_ms", "query"}
_RAG_TELEM_MAX = 20_000
_chat_latencies: list = []         # {"ts", "latency_ms"}
_LATENCY_MAX = 10_000

def _record_rag_event(quality: str, latency_ms: float, query: str = "", intent: str = ""):
    """Called from the RAG pipeline to log each retrieval attempt."""
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "quality": quality,
        "latency_ms": round(latency_ms, 1),
        "query": query[:200],
    }
    if intent:
        event["intent"] = intent
    _rag_telemetry.append(event)
    if len(_rag_telemetry) > _RAG_TELEM_MAX:
        _rag_telemetry.pop(0)

def _record_chat_latency(latency_ms: float):
    """Called after each chat request completes to track P95."""
    _chat_latencies.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "latency_ms": round(latency_ms, 1),
    })
    if len(_chat_latencies) > _LATENCY_MAX:
        _chat_latencies.pop(0)
