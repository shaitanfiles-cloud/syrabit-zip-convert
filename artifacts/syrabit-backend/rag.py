"""Syrabit.ai — RAG search, vector search, content card fetching, auto-chunking."""
import re, asyncio, time, uuid, hashlib, logging
from typing import Optional, Dict
from datetime import datetime, timezone
from fastapi import HTTPException
from deps import db, logger as _dep_logger, _assert_not_cms_context, is_mongo_available
from cache import (
    _rag_cache, _rag_cache_key, _vector_rag_cache, _vector_rag_cache_key,
    _content_card_cache, _content_card_cache_key,
    _cache_key, _redis_get_search, _redis_cache_search,
)
from utils import _extract_keywords, _slow_query
import vertex_services

logger = logging.getLogger(__name__)

__all__ = [
    "_HISTORY_MAX_TURNS", "_HISTORY_TOKEN_BUDGET", "_LATENCY_MAX", "_RAG_TELEM_MAX",
    "_chat_latencies", "_ddg_news_search", "_ddg_text_search",
    "_embed_and_store_chapter", "_embed_and_store_page", "_embed_cms_document", "_extract_relevant_sections",
    "_fetch_content_card", "_rag_telemetry", "_record_chat_latency",
    "_record_rag_event", "_sources_from_rag_ctx", "_trim_history",
    "auto_chunk_content", "build_rag_system_prompt", "rag_search", "rechunk_chapter",
    "resolve_rag_context", "syrabit_library_search", "vector_rag_search",
    "web_search_with_fallback",
]

_HEADING_RE = re.compile(r'^#{1,4}\s+', re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
_CHUNK_TARGET = 600
_CHUNK_MAX = 1200
_CHUNK_MIN = 80
_OVERLAP_SENTENCES = 2

def _split_into_sections(content: str) -> list[dict]:
    parts = _HEADING_RE.split(content)
    headings = _HEADING_RE.findall(content)
    sections = []
    for i, part in enumerate(parts):
        text = part.strip()
        if not text:
            continue
        heading = headings[i - 1].strip().strip('#').strip() if i > 0 and i - 1 < len(headings) else ""
        sections.append({"heading": heading, "text": text})
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
    if not sentences:
        return [text] if text.strip() else []
    chunks = []
    i = 0
    while i < len(sentences):
        current = []
        current_len = 0
        while i < len(sentences) and current_len + len(sentences[i]) <= max_len:
            current.append(sentences[i])
            current_len += len(sentences[i]) + 1
            i += 1
            if current_len >= target:
                break
        if not current and i < len(sentences):
            current.append(sentences[i])
            i += 1
        chunk_text = " ".join(current).strip()
        if chunk_text:
            chunks.append(chunk_text)
        if overlap and i < len(sentences):
            i = max(i - overlap, i - len(current) + 1) if len(current) > overlap else i
            if i <= len(chunks) - 1:
                i = max(i, len(chunks))
    return chunks

async def auto_chunk_content(chapter_id: str, content: str, subject_id: str = None, syllabus_id: str = None, geo_tags: list = None, chapter_title: str = None) -> list:
    """
    Semantically split chapter content into RAG-optimised chunks.

    Strategy:
    - Split by markdown headings (###) to keep concepts together
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
    sections = _split_into_sections(content)
    sections = _merge_short_sections(sections)

    raw_chunks: list[str] = []
    for sec in sections:
        text = sec["text"]
        prefix = f"**{sec['heading']}**\n" if sec.get("heading") else ""
        full = (prefix + text).strip()
        if len(full) <= _CHUNK_MAX:
            raw_chunks.append(full)
        else:
            sub_chunks = _sentence_split_with_overlap(full)
            raw_chunks.extend(sub_chunks)

    chunks_created = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for idx, chunk_text in enumerate(raw_chunks):
        chunk_text = chunk_text.strip()
        if len(chunk_text) < _CHUNK_MIN:
            continue
        chunk_keywords = _extract_keywords(chunk_text)
        chunk = {
            "id": str(uuid.uuid4()),
            "chapter_id": chapter_id,
            "subject_id": subject_id,
            "chapter_title": chapter_title or "",
            "content": chunk_text,
            "content_type": "notes",
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
        subject_id=chapter.get("subject_id")
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
) -> Optional[tuple]:
    """
    Search seo_pages + chapters for the most relevant content card.
    Returns (card_text: str, card_slugs: set[str], source_meta: dict) if found, else None.
    Card slugs are used by the grounding builder to deduplicate vector hits.
    source_meta contains card_name, lesson_name, subject_name for chat attribution.
    """
    _ck = _content_card_cache_key(query, subject_id, subject_name)
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
        ch_filter["$text"] = {"$search": search_str}
        _ch_proj = {
            "_id": 0, "title": 1, "content": 1, "subject_id": 1,
            "score": {"$meta": "textScore"},
        }
        ch_task = db.chapters.find(
            ch_filter, _ch_proj,
        ).sort([("score", {"$meta": "textScore"})]).limit(4).to_list(4)

        cms_filter: dict = {"status": "published", "content": {"$exists": True, "$ne": ""}}
        cms_escaped_kw = "|".join(re.escape(k) for k in keywords)
        cms_kw_or = [
            {"content": {"$regex": cms_escaped_kw, "$options": "i"}},
            {"title":   {"$regex": cms_escaped_kw, "$options": "i"}},
            {"meta_description": {"$regex": cms_escaped_kw, "$options": "i"}},
        ]
        if subject_id:
            cms_filter["$and"] = [
                {"$or": [{"linked_subject_id": subject_id}, {"subject_id": subject_id}]},
                {"$or": cms_kw_or},
            ]
        elif subject_name:
            cms_filter["$and"] = [
                {"$or": [
                    {"linked_subject_name": {"$regex": re.escape(subject_name), "$options": "i"}},
                    {"subject_name": {"$regex": re.escape(subject_name), "$options": "i"}},
                ]},
                {"$or": cms_kw_or},
            ]
        else:
            cms_filter["$or"] = cms_kw_or
        _cms_proj = {
            "_id": 0, "title": 1, "content": 1, "seo_slug": 1,
            "category": 1, "linked_subject_name": 1, "linked_chapter_title": 1,
            "meta_description": 1,
        }
        cms_task = db.cms_documents.find(cms_filter, _cms_proj).limit(4).to_list(4)

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
            ch_filter_fb["$or"] = [
                {"content": {"$regex": escaped_kw_re, "$options": "i"}},
                {"title":   {"$regex": escaped_kw_re, "$options": "i"}},
            ]
            pages, chapter_pages, cms_pages = await asyncio.gather(
                db.seo_pages.find(match_filter, regex_proj).limit(6).to_list(6),
                db.chapters.find(ch_filter_fb, {"_id": 0, "title": 1, "content": 1, "subject_id": 1}).limit(4).to_list(4),
                db.cms_documents.find(cms_filter, _cms_proj).limit(4).to_list(4),
            )

        if not pages and not chapter_pages and not cms_pages:
            return None

        cards = []

        def _page_priority(p: dict) -> int:
            pt = p.get("page_type", "")
            return 0 if pt == "notes" else (1 if pt == "pyq" else (2 if pt == "mcq" else 3))

        ordered_pages = sorted(pages, key=_page_priority)
        card_slugs: set = set()
        _top_card_name: str = ""
        _top_lesson_name: str = ""
        _top_subject_name: str = ""
        for p in ordered_pages[:3]:
            content = p.get("content", "")
            if not content:
                continue
            slug = p.get("slug") or p.get("topic_title", "")
            card_slugs.add(slug)
            topic_title = p.get("topic_title") or p.get("chapter_title") or ""
            if not _top_card_name and topic_title:
                _top_card_name = topic_title
                _top_lesson_name = p.get("chapter_title") or ""
                _top_subject_name = p.get("subject_name") or subject_name or ""
            header = f"[Content: {topic_title}]" if topic_title else "[Content Page]"
            relevant = _extract_relevant_sections(content, keywords, max_chars=2000)
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
            relevant = _extract_relevant_sections(content, keywords, max_chars=1500)
            cards.append(f"{header}\n{relevant}")

        for ch in chapter_pages[:2]:
            content = ch.get("content", "")
            if not content:
                continue
            if not _top_lesson_name:
                _top_lesson_name = ch.get("title") or ""
            header = f"[Chapter: {ch.get('title', '')}]"
            relevant = _extract_relevant_sections(content, keywords, max_chars=1200)
            cards.append(f"{header}\n{relevant}")

        if not cards:
            return None

        source_meta = {
            "card_name": _top_card_name,
            "lesson_name": _top_lesson_name,
            "subject_name": _top_subject_name,
        }
        result = ("\n\n---\n\n".join(cards), card_slugs, source_meta)
        _content_card_cache[_ck] = result
        return result

    except Exception as e:
        logger.error(f"Content card fetch error: {e}")
        return None


def _extract_relevant_sections(content: str, keywords: list, max_chars: int = 2500) -> str:
    """Extract the most relevant sections from a content page based on keywords."""
    paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
    if not paragraphs:
        return content[:max_chars]

    scored = []
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        score = sum(1 for kw in keywords if kw in para_lower)
        is_header = para.startswith('#') or para.startswith('**')
        if is_header:
            score += 0.5
        scored.append((score, i, para))

    scored.sort(key=lambda x: (-x[0], x[1]))

    selected_indices = set()
    total_chars = 0
    for score, idx, para in scored:
        if score <= 0 and total_chars > 500:
            break
        for j in range(max(0, idx - 1), min(len(paragraphs), idx + 2)):
            if j not in selected_indices:
                selected_indices.add(j)
                total_chars += len(paragraphs[j])
        if total_chars >= max_chars:
            break

    if not selected_indices:
        return content[:max_chars]

    result = "\n".join(paragraphs[i] for i in sorted(selected_indices))
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
) -> list:
    """
    Vector similarity search over all published seo_pages + chapters.
    Returns top-k results sorted by cosine similarity with [PAGE: slug] metadata.

    Falls back to empty list if embedding fails or no vectors exist yet.
    Caches results for 300 seconds — Gemini embed calls are expensive.
    """
    # Fast path: in-memory cache (skips Gemini API call + 300-doc MongoDB fetch)
    _vk = _vector_rag_cache_key(query, subject_id, top_k)
    if _vk in _vector_rag_cache:
        logger.info(f"Vector RAG cache hit: query='{query[:40]}'")
        return _vector_rag_cache[_vk]

    try:
        query_vec = await vertex_services.embed_text(query, task_type="RETRIEVAL_QUERY")
        if not query_vec:
            return []

        # Build page filter
        page_filter: dict = {"status": "published", "embedding": {"$exists": True}}
        if subject_id:
            subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0, "slug": 1})
            if subj and subj.get("slug"):
                page_filter["subject_slug"] = subj["slug"]

        # Fetch candidates (limit high to allow good ranking)
        pages = await db.seo_pages.find(
            page_filter,
            {"_id": 0, "topic_slug": 1, "content": 1, "topic_title": 1,
             "chapter_title": 1, "page_type": 1, "embedding": 1},
        ).limit(200).to_list(200)

        ch_filter: dict = {"embedding": {"$exists": True}, "content": {"$exists": True, "$ne": ""}}
        if subject_id:
            ch_filter["subject_id"] = subject_id
        chapters = await db.chapters.find(
            ch_filter,
            {"_id": 0, "id": 1, "title": 1, "content": 1, "subject_id": 1, "embedding": 1},
        ).limit(100).to_list(100)

        cms_filter: dict = {"status": "published", "embedding": {"$exists": True}, "content": {"$exists": True, "$ne": ""}}
        if subject_id:
            cms_filter["$or"] = [{"linked_subject_id": subject_id}, {"subject_id": subject_id}]
        cms_docs = await db.cms_documents.find(
            cms_filter,
            {"_id": 0, "seo_slug": 1, "title": 1, "content": 1, "category": 1, "embedding": 1},
        ).limit(100).to_list(100)

        scored = []
        q_dim = len(query_vec)
        for p in pages:
            vec = p.get("embedding")
            if vec and len(vec) == q_dim:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                slug = p.get("topic_slug", "")
                title = p.get("topic_title") or p.get("chapter_title") or slug
                content_snippet = _extract_relevant_sections(p.get("content", ""), [], max_chars=1500)
                scored.append({
                    "slug":    slug,
                    "title":   title,
                    "content": content_snippet,
                    "score":   sim,
                    "source":  "page",
                })
        for ch in chapters:
            vec = ch.get("embedding")
            if vec and len(vec) == q_dim:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                content_snippet = _extract_relevant_sections(ch.get("content", ""), [], max_chars=1500)
                scored.append({
                    "slug":    f"chapter/{ch.get('id', '')}",
                    "title":   ch.get("title", ""),
                    "content": content_snippet,
                    "score":   sim,
                    "source":  "chapter",
                })
        for cms in cms_docs:
            vec = cms.get("embedding")
            if vec and len(vec) == q_dim:
                sim = vertex_services.cosine_similarity(query_vec, vec)
                content_snippet = _extract_relevant_sections(cms.get("content", ""), [], max_chars=1500)
                scored.append({
                    "slug":    cms.get("seo_slug", ""),
                    "title":   cms.get("title", ""),
                    "content": content_snippet,
                    "score":   sim,
                    "source":  "cms",
                })

        scored.sort(key=lambda x: -x["score"])
        # 0.25 cosine threshold — filter out low-relevance noise before sending to AI
        top = [r for r in scored if r["score"] >= 0.25][:top_k]
        logger.info(
            f"Vector RAG: query='{query[:40]}' → {len(top)} results "
            f"(best_sim={top[0]['score']:.3f} [{top[0]['slug']}], threshold=0.25)" if top else
            f"Vector RAG: query='{query[:40]}' → no results above threshold (0.25)"
        )
        # Store in cache — future identical/similar queries skip the embed API call
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
        regex_parts = [{"content": {"$regex": kw, "$options": "i"}} for kw in keywords]
        ch_title_filter = {"$or": [{"title": {"$regex": kw, "$options": "i"}} for kw in keywords]}

        if subject_id:
            # ── Fast path: subject is known — pre-fetch chapter IDs then run all 3 queries in parallel ──
            sub_chapters = await db.chapters.find(
                {"subject_id": subject_id}, {"_id": 0, "id": 1}
            ).to_list(200)
            chapter_ids = [c["id"] for c in sub_chapters]
            # Include PYQ chunks linked by subject_id directly (they use synthetic chapter IDs)
            pyq_branch: dict = {"$and": [{"subject_id": subject_id}, {"content_type": "pyq"}, {"$or": regex_parts}]}
            if chapter_ids:
                chunk_filter: dict = {"$or": [
                    {"$and": [{"chapter_id": {"$in": chapter_ids}}, {"$or": regex_parts}]},
                    pyq_branch,
                ]}
            else:
                chunk_filter = {"$or": [{"$or": regex_parts}, pyq_branch]}
            subj_kw_filter = {"id": subject_id}
            # Fetch keyword-matching chapters AND all chapters for this subject
            ch_kw_filter = {"$and": [{"subject_id": subject_id}, ch_title_filter]}
            ch_all_filter = {"subject_id": subject_id}

            chunks, subjects_found, chapters_kw, chapters_all = await asyncio.gather(
                db.chunks.find(chunk_filter, {"_id": 0}).sort("priority", 1).limit(12).to_list(12),
                db.subjects.find(subj_kw_filter, {"_id": 0, "id": 1, "name": 1, "icon": 1, "gradient": 1}).limit(1).to_list(1),
                db.chapters.find(ch_kw_filter, {"_id": 0, "title": 1, "description": 1, "content": 1, "order_index": 1}).sort("order_index", 1).limit(8).to_list(8),
                db.chapters.find(ch_all_filter, {"_id": 0, "title": 1, "description": 1, "content": 1, "order_index": 1}).sort("order_index", 1).limit(25).to_list(25),
            )
            # Use keyword-matching chapters when available; otherwise use the full chapter list
            chapters_found = chapters_kw if chapters_kw else chapters_all
        else:
            # ── No subject: 3-way parallel search across name, chapters, and chunks ──
            subj_kw_filter = {"$or": [
                {"name":        {"$regex": kw_join, "$options": "i"}},
                {"description": {"$regex": kw_join, "$options": "i"}},
                {"tags":        {"$elemMatch": {"$regex": kw_join, "$options": "i"}}},
            ], "status": "published"}
            if subject_name:
                subj_kw_filter = {"$and": [
                    {"name": {"$regex": subject_name, "$options": "i"}, "status": "published"},
                ]}

            # Run 3 searches in parallel:
            #   (1) subjects by name/desc/tags
            #   (2) ALL chapters whose title matches keywords → backtrack to subject
            #   (3) chunks whose content matches keywords → backtrack to subject via chapter_id
            _subj_proj = {"_id": 0, "id": 1, "name": 1, "description": 1, "tags": 1, "icon": 1, "gradient": 1}
            _ch_proj   = {"_id": 0, "id": 1, "subject_id": 1, "title": 1, "description": 1, "order_index": 1}
            chunks, subjects_by_name, chapters_by_title = await asyncio.gather(
                db.chunks.find({"$or": regex_parts}, {"_id": 0}).sort("priority", 1).limit(15).to_list(15),
                db.subjects.find(subj_kw_filter, _subj_proj).limit(55).to_list(55),
                db.chapters.find(ch_title_filter, _ch_proj).sort("order_index", 1).limit(25).to_list(25),
            )

            # ── Resolve chunks → parent subjects (via chapter_id) ─────────────────
            chunk_chapter_ids = list({c["chapter_id"] for c in chunks if c.get("chapter_id")})
            chunk_parent_chapters: list = []
            if chunk_chapter_ids:
                chunk_parent_chapters = await db.chapters.find(
                    {"id": {"$in": chunk_chapter_ids}}, {"_id": 0, "id": 1, "subject_id": 1, "title": 1}
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


async def resolve_rag_context(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    document_text: Optional[str] = None,   # Tier 0 — uploaded document (highest)
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

        # Keep top-scoring lines + surrounding context, up to 3000 chars
        scored.sort(key=lambda x: -x[0])
        selected_indices = set()
        for score, idx, _ in scored[:8]:
            if score > 0:
                for j in range(max(0, idx - 1), min(len(lines), idx + 3)):
                    selected_indices.add(j)

        if selected_indices:
            relevant = "\n".join(lines[i] for i in sorted(selected_indices))
            relevant = relevant[:3000]
        else:
            relevant = document_text[:3000]

        return {
            "chunks": [],
            "chapters": [],
            "subjects": [],
            "document_text": relevant,
            "document_full": document_text[:3000],
            "source":  "document",
            "quality": "tier0",
        }
    cached_rag, _card_result, vector_hits = await asyncio.gather(
        rag_search(query, subject_id=subject_id, subject_name=subject_name),
        _fetch_content_card(query, subject_id=subject_id, subject_name=subject_name),  # returns (text, slug_set) or None
        vector_rag_search(query, subject_id=subject_id, top_k=8),
    )

    rag_ctx = dict(cached_rag)

    # Unpack content card tuple → (text, slug_set used for dedup, source_meta)
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

    # Vector hits: deduplicate against content card slugs before injecting
    if vector_hits:
        deduped = [h for h in vector_hits if h.get("slug") not in content_card_slugs]
        rag_ctx["vector_hits"] = deduped
        if rag_ctx["quality"] == "none":
            rag_ctx["quality"] = "high"
            rag_ctx["source"] = "rag"
        logger.info(f"RAG resolve: vector hits={len(deduped)} (deduped from {len(vector_hits)}, best_sim={deduped[0]['score']:.3f}) | query: {query[:50]}" if deduped else f"RAG resolve: vector hits=0 (all deduped by content card)")

    if rag_ctx["quality"] == "high":
        logger.info(f"RAG resolve: HIGH-QUALITY content (chunks: {len(rag_ctx.get('chunks', []))}, vector: {len(rag_ctx.get('vector_hits', []))}, card: {'yes' if content_card_text else 'no'}) | query: {query[:50]}")
        return rag_ctx

    if rag_ctx["quality"] == "medium":
        logger.info(f"RAG resolve: MEDIUM metadata only | query: {query[:50]}")
        return rag_ctx

    logger.info(f"RAG resolve: NO CONTEXT — AI uses training knowledge | query: {query[:50]}")
    return {"chunks": [], "chapters": [], "subjects": [], "vector_hits": [], "source": "none", "quality": "none"}



# ── Web search helpers ────────────────────────────────────────────────────────

async def _ddg_text_search(query: str, num_results: int) -> list:
    """DuckDuckGo text search — primary browser-style web search."""
    def _run():
        from duckduckgo_search import DDGS
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
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=5.0)
        logger.info(f"DDG text search: {len(results)} results | query: {query[:60]}")
        return results
    except Exception as exc:
        logger.warning(f"DDG text search failed: {exc}")
        return []


async def _ddg_news_search(query: str, num_results: int) -> list:
    """DuckDuckGo news search — secondary fallback web source."""
    def _run():
        from duckduckgo_search import DDGS
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
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=5.0)
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
        sources.append({
            "type":         "content_card",
            "card_name":    _cc_meta.get("card_name", ""),
            "lesson_name":  _cc_meta.get("lesson_name", ""),
            "subject_name": _cc_meta.get("subject_name", ""),
            "board_name":   _cc_meta.get("board_name", ""),
            "class_name":   _cc_meta.get("class_name", ""),
            "slug":         "",
            "title":        _cc_meta.get("card_name", "") or _cc_meta.get("lesson_name", ""),
            "url":          "",
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
    from prompts import build_system_prompt, _classify_question, _format_board_label as _fbl
    base_prompt = build_system_prompt(context, user_info=user_info, query=query)
    source      = rag_context.get("source",  "none")
    quality     = rag_context.get("quality", "none")
    chunks      = rag_context.get("chunks",   [])
    chapters    = rag_context.get("chapters", [])
    subjects    = rag_context.get("subjects", [])
    document_text = rag_context.get("document_text", "")
    vector_hits = rag_context.get("vector_hits", [])
    _board_raw = (context.get("board_name", "") or "").strip().upper()
    _board_label = _fbl(_board_raw) if _board_raw else "AssamBoard"
    _curriculum_label = f"{_board_label} Curriculum"

    _is_casual = _classify_question(query) == "casual" if query else False

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
            f"\n\nSOURCE CITATION RULE: Do NOT mention source, subject name, unit name, "
            f"course name, or board name anywhere in your answer body. Answer the question directly first. "
            f"Then, at the very end of your response, on its own line, add:\n"
            f"SOURCE : {_source_line}"
        )

    grounding = ""

    # ── Tier -1: Syllabus constraints (curriculum boundaries) ───────────────────
    if syllabus and syllabus.get("content"):
        syllabus_content = syllabus.get("content", "")
        syllabus_topics = ", ".join(syllabus.get("topics", [])[:10])
        geo_phrases = syllabus.get("geo_phrases", [])
        grounding = (
            "\n\n---\n"
            f"**CURRICULUM CONSTRAINTS (Tier -1 — {_curriculum_label}):**\n"
            f"You are helping a student from the {_curriculum_label}. "
            "The following represents what this student is expected to know:\n\n"
            f"{syllabus_content}\n\n"
        )
        if syllabus_topics:
            grounding += f"**Key topics:** {syllabus_topics}\n\n"
        grounding += (
            "---\n"
            f"*INSTRUCTION: Keep your answer within the scope of the {_curriculum_label}. "
            "Do not introduce concepts beyond the standard curriculum unless explicitly requested. "
            "Prioritize accuracy over breadth. "
            f"When referencing the curriculum by name, always call it '{_curriculum_label}'. "
            "When relevant, cite specific board exam stats, PYQ frequency data, and authoritative syllabus references.*\n"
        )
        if geo_phrases:
            grounding += (
                "\n**NOTE:** After delivering your factual answer, you may append a brief "
                "closing phrase from the list below — only if it fits naturally and does NOT "
                "alter or qualify any factual statement in your answer:\n"
            )
            for gp in geo_phrases[:5]:
                grounding += f"- {gp}\n"
            grounding += "\n"

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

    content_card = rag_context.get("content_card", "")

    # ── Tier 1/2: Curriculum DB context (including vector hits) ─────────────
    if source == "rag" and (chunks or subjects or chapters or content_card or vector_hits):

        if quality == "high":
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Syrabit Library — 97% Accuracy Mode):**\n"
                "The following is the COMPLETE content from the student's actual curriculum database. "
                "Answer the question directly from this content. "
                "Quote verbatim where possible.\n\n"
            )
            # Vector hits — highest confidence (semantic similarity ranked)
            if vector_hits:
                grounding += "**[VECTOR SEARCH RESULTS — Semantically matched pages]:**\n\n"
                for hit in vector_hits:
                    slug = hit.get("slug", "")
                    title = hit.get("title", slug)
                    content = hit.get("content", "")
                    score = hit.get("score", 0)
                    grounding += f"[PAGE: {slug}] — {title} (relevance: {score:.2f})\n{content}\n\n"

            if content_card:
                grounding += f"**[CONTENT CARD — Full page content]:**\n{content_card}\n\n"
            for i, c in enumerate(chunks, 1):
                title = c.get("content_type", "content").capitalize()
                grounding += f"**[BLOCK {i} — {title}]:**\n{c.get('content', '')[:1500]}\n\n"
            grounding += (
                "---\n"
                "**ACCURACY LOCK:**\n"
                "1. Answer ONLY from the grounding above. Structure: Explanation → Key Points → Examples.\n"
                "2. Do NOT add source citations inline — the system appends the SOURCE line automatically.\n"
                "3. If the answer is NOT in the grounding: check for Tier 3 web search results below — "
                "use those. If those are absent, answer from general curriculum knowledge. Never stop without an answer.\n"
                "4. NEVER hallucinate. NEVER invent facts not present in the grounding or web results.\n"
                "5. Be deterministic and precise — prioritize accuracy over creativity.*"
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

            grounding += (
                "\n---\n"
                f"*ACCURACY INSTRUCTION: Answer using the {_curriculum_label} context above as the primary source. "
                f"Cross-reference with your training knowledge for the {_curriculum_label} in Assam. "
                f"When referencing the curriculum by name, always call it '{_curriculum_label}'. "
                "If you are unsure about any specific fact, state it clearly rather than guessing. "
                "Do not add examples or exam tips unless the student explicitly asks.*"
            )

    # ── Live Web Search Results (dual-layer: base + polish) ─────────────────
    if web_results:
        _has_internal = bool(chunks or subjects or chapters or content_card or vector_hits)
        base_results   = [r for r in web_results if r.get("_layer") != "polish"]
        polish_results = [r for r in web_results if r.get("_layer") == "polish"]

        web_block = "\n\n---\n"

        if _has_internal:
            web_block += (
                "**WEB SEARCH — SUPPLEMENTARY (external sources):**\n"
                "Internal Syrabit content above is the PRIMARY source. "
                "Use these web results ONLY to supplement or enrich your answer. "
                "Always prefer citing internal [PAGE: slug] sources over external web links.\n\n"
            )

        if base_results:
            if not _has_internal:
                web_block += (
                    "**WEB SEARCH — BASE LAYER (browser results, primary facts):**\n"
                    "Build the core of your answer from these results. "
                    "Use them as the factual foundation — definitions, explanations, data points.\n\n"
                )
            for i, r in enumerate(base_results, 1):
                title   = r.get("title", "")
                url     = r.get("url", "")
                snippet = r.get("snippet", "")
                web_block += f"[Base {i}] {title}\n{snippet}\nSource: {url}\n\n"

        if polish_results:
            if not _has_internal:
                web_block += (
                    "**WEB SEARCH — POLISH LAYER (news/open web, enrichment):**\n"
                    "Use these to add current context, recent examples, or relevance to the student's "
                    "specific situation. Blend naturally into the answer — do not list them separately.\n\n"
                )
            for i, r in enumerate(polish_results, 1):
                title   = r.get("title", "")
                url     = r.get("url", "")
                snippet = r.get("snippet", "")
                web_block += f"[Polish {i}] {title}\n{snippet}\nSource: {url}\n\n"

        if _has_internal:
            web_block += (
                "---\n"
                "*INSTRUCTION: Your answer MUST prioritize internal Syrabit content above. "
                "Web results are supplementary — use them only to fill gaps or add context. "
                "Do not add source citations inline — the system appends the SOURCE line automatically. "
                "Do not fabricate facts beyond what the sources contain.*\n"
            )
        else:
            web_block += (
                "---\n"
                "*INSTRUCTION: Build the answer from the Base layer first. "
                "Then enrich it with relevant details from the Polish layer. "
                "Do not fabricate facts beyond what the results contain.*\n"
            )
        grounding += web_block

    return base_prompt + grounding if grounding else base_prompt



# ── In-memory telemetry ring buffers (process-lifetime) ──────────────────────

_rag_telemetry: list = []          # {"ts", "quality", "latency_ms", "query"}
_RAG_TELEM_MAX = 20_000
_chat_latencies: list = []         # {"ts", "latency_ms"}
_LATENCY_MAX = 10_000

def _record_rag_event(quality: str, latency_ms: float, query: str = ""):
    """Called from the RAG pipeline to log each retrieval attempt."""
    _rag_telemetry.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "quality": quality,       # "high" | "medium" | "none"
        "latency_ms": round(latency_ms, 1),
        "query": query[:200],
    })
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
