"""Syrabit.ai — Syllabus-focused web search engine (RAG removed)."""
import os, re, asyncio, time, uuid, hashlib, logging
from typing import Optional, Dict
from datetime import datetime, timezone
from fastapi import HTTPException
from deps import db, logger as _dep_logger, _assert_not_cms_context, is_mongo_available
from cache import (
    _cache_key, _redis_get_search, _redis_cache_search,
)
from utils import _extract_keywords, _slow_query

logger = logging.getLogger(__name__)

__all__ = [
    "_HISTORY_MAX_TURNS", "_HISTORY_TOKEN_BUDGET",
    "_LATENCY_MAX", "_RAG_TELEM_MAX",
    "_chat_latencies", "_ddg_news_search", "_ddg_text_search",
    "_extract_relevant_sections",
    "_rag_telemetry", "_record_chat_latency",
    "_record_rag_event", "_sources_from_rag_ctx", "_trim_history",
    "build_rag_system_prompt",
    "web_search_with_fallback",
    "get_vector_search_stats", "get_pipeline_stats", "record_pipeline_run",
    "_record_vector_search",
    "resolve_rag_context",
    "auto_chunk_content", "backfill_chunk_embeddings",
    "rag_search", "rechunk_chapter", "vector_rag_search",
    "syrabit_library_search",
    "_fetch_content_card", "_fetch_enrichment_blocks",
    "_embed_and_store_chapter", "_embed_and_store_page", "_embed_cms_document",
]


def _record_vector_search(*args, **kwargs):
    pass

def get_vector_search_stats(window_seconds: int = 3600) -> dict:
    return {"total_searches": 0, "has_data": False, "info": "RAG removed — web search only"}

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


async def auto_chunk_content(*args, **kwargs) -> list:
    logger.info("auto_chunk_content: RAG removed — no-op")
    return []

async def rechunk_chapter(*args, **kwargs) -> dict:
    return {"status": "skipped", "reason": "RAG removed"}

async def backfill_chunk_embeddings(*args, **kwargs) -> dict:
    return {"status": "skipped", "reason": "RAG removed"}

async def vector_rag_search(*args, **kwargs) -> list:
    return []

async def rag_search(*args, **kwargs) -> dict:
    return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}

async def syrabit_library_search(query: str, *, board_name: str = "", class_name: str = "", subject_name: str = "", limit: int = 10, **kwargs) -> list:
    try:
        results = await web_search_with_fallback(
            query, num_results=limit,
            board_name=board_name, class_name=class_name,
            subject_name=subject_name,
        )
        return [
            {"title": r.get("title", ""), "snippet": r.get("body", r.get("snippet", "")), "url": r.get("href", r.get("url", "")), "source": r.get("_layer", "web")}
            for r in results
        ]
    except Exception as e:
        logger.warning(f"syrabit_library_search web fallback failed: {e}")
        return []

async def _fetch_content_card(*args, **kwargs):
    return None

async def _fetch_enrichment_blocks(*args, **kwargs) -> str:
    return ""

async def _embed_and_store_chapter(*args, **kwargs):
    return True

async def _embed_and_store_page(*args, **kwargs):
    return True

async def _embed_cms_document(*args, **kwargs):
    return {}


def _extract_relevant_sections(document_text: str, query: str, char_limit: int = 3000) -> str:
    keywords = _extract_keywords(query)
    lines = [l.strip() for l in document_text.split('\n') if l.strip()]
    scored = []
    for i, line in enumerate(lines):
        score = sum(1 for kw in keywords if kw in line.lower())
        scored.append((score, i, line))
    scored.sort(key=lambda x: -x[0])
    selected_indices = set()
    for score, idx, _ in scored[:8]:
        if score > 0:
            for j in range(max(0, idx - 1), min(len(lines), idx + 3)):
                selected_indices.add(j)
    if selected_indices:
        relevant = "\n".join(lines[i] for i in sorted(selected_indices))
        return relevant[:char_limit]
    return document_text[:char_limit]


async def resolve_rag_context(
    query: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    document_text: Optional[str] = None,
    intent: Optional[str] = None,
    db_category: Optional[str] = None,
    pre_syl_match=None,
    topic_metadata: Optional[dict] = None,
) -> dict:
    if document_text and document_text.strip():
        keywords = _extract_keywords(query)
        lines = [l.strip() for l in document_text.split('\n') if l.strip()]
        scored = []
        for i, line in enumerate(lines):
            score = sum(1 for kw in keywords if kw in line.lower())
            scored.append((score, i, line))
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
            "chunks": [], "chapters": [], "subjects": [],
            "document_text": relevant,
            "document_full": document_text[:5000],
            "source": "document", "quality": "tier0",
            "intent": intent or "general",
        }
    return {
        "chunks": [], "chapters": [], "subjects": [],
        "vector_hits": [], "source": "none", "quality": "none",
        "intent": intent or "general",
        "_general_knowledge_fallback": True,
    }


async def _ddg_text_search(query: str, num_results: int) -> list:
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
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=1.2)
        logger.info(f"DDG text search: {len(results)} results | query: {query[:60]}")
        return results
    except Exception as exc:
        logger.warning(f"DDG text search failed: {exc}")
        return []


async def _ddg_news_search(query: str, num_results: int) -> list:
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
        results = await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=1.2)
        logger.info(f"DDG news search: {len(results)} results | query: {query[:60]}")
        return results
    except Exception as exc:
        logger.warning(f"DDG news search failed: {exc}")
        return []


_SYRABIT_SITE = "syrabit.ai"

async def web_search_with_fallback(
    query: str,
    num_results: int = 8,
    board_name: str = "",
    class_name: str = "",
    subject_name: str = "",
    scoped_query: str = "",
    topic_metadata: dict = None,
) -> list:
    _assert_not_cms_context("web search")

    _s1_subject = ""
    _s1_chapter = ""
    if topic_metadata:
        _s1_subject = (topic_metadata.get("subject", "") or "").strip()
        _s1_chapter = (topic_metadata.get("chapter", "") or "").strip()

    _short_query = query[:120]

    if scoped_query:
        curriculum_query = scoped_query[:150]
    else:
        _ctx_parts = [p.strip() for p in [_s1_subject or subject_name] if p]
        if _s1_chapter:
            _ctx_parts.append(_s1_chapter)
        curriculum_query = " ".join(_ctx_parts + [_short_query]) if _ctx_parts else _short_query

    syrabit_query = f"site:{_SYRABIT_SITE} {_s1_subject or subject_name or ''} {_short_query}".strip()

    syrabit_results, text_results, news_results = await asyncio.gather(
        _ddg_text_search(syrabit_query, 3),
        _ddg_text_search(curriculum_query, num_results),
        _ddg_news_search(_short_query, 4),
    )

    for r in syrabit_results:
        r["_layer"] = "syrabit"
        r["_priority"] = True
    for r in text_results:
        r["_layer"] = "base"
    for r in news_results:
        r["_layer"] = "polish"

    seen_urls = set()
    combined = []
    for r in syrabit_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            combined.append(r)
    for r in text_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            combined.append(r)
    for r in news_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            combined.append(r)

    logger.info(
        f"Web search: {len(syrabit_results)} syrabit + {len(text_results)} base (scoped: {curriculum_query[:60]!r}) + "
        f"{len(news_results)} polish | raw: {query[:50]}"
    )

    try:
        from web_content import enrich_search_results
        combined = await enrich_search_results(combined)
    except Exception as e:
        logger.warning(f"Web content enrichment failed (using snippets only): {e}")

    return combined


_HISTORY_TOKEN_BUDGET = 1500
_HISTORY_MAX_TURNS = 8


def _trim_history(messages: list, token_budget: int = _HISTORY_TOKEN_BUDGET, max_turns: int = _HISTORY_MAX_TURNS) -> list:
    capped = messages[-(max_turns * 2):]
    while capped:
        total_chars = sum(len(m.get("content", "")) for m in capped)
        if total_chars // 4 <= token_budget:
            break
        capped = capped[2:]
    return capped


def _sources_from_rag_ctx(rag_ctx: dict) -> list:
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

    for subj in rag_ctx.get("subjects", []):
        slug = subj.get("slug", "")
        if slug and slug not in seen:
            seen.add(slug)
            sources.append({"slug": slug, "title": subj.get("name", ""), "url": subj.get("url", "")})

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
    from prompts import build_system_prompt, classify_intent, _format_board_label as _fbl, get_intent_extraction_rules
    import re as _re
    base_prompt = build_system_prompt(context, user_info=user_info, query=query, resolved_intent=resolved_intent)
    source = rag_context.get("source", "none")

    _intent = resolved_intent if resolved_intent else (classify_intent(query)[0] if query else "notes")
    _is_casual = _intent in ("casual", "general")

    _board_raw = (context.get("board_name", "") or "").strip().upper()
    _board_label = _fbl(_board_raw) if _board_raw else "AssamBoard"
    _curriculum_label = f"{_board_label} Curriculum"

    _content_intents = {"notes", "important_questions", "pyq"}

    base_prompt += (
        "\n\nSPEED RULE: Be extremely concise. "
        "Use bullet points, not paragraphs. 50-100 words default. "
        "No filler, no introductions, no 'Great question!'. Start with the answer directly."
    )

    if _intent in _content_intents:
        base_prompt += (
            "\n\nCONTENT RULE: Answer using the web search results below as your primary source. "
            "Supplement with your knowledge. Accuracy over completeness."
        )
    if _intent == "pyq":
        base_prompt += (
            "\n\nPYQ RULE: The student is asking for previous year questions. "
            "If the web results contain actual question paper content (numbered questions, marks), "
            "present the EXACT questions as they appear — do NOT paraphrase or summarize them."
        )

    if not _is_casual:
        _src_subject = context.get("subject_name", "")
        _src_course  = (context.get("stream_name", "") or "").strip()
        _src_board   = _board_label or "AssamBoard"
        _source_parts = []
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

    if syllabus and syllabus.get("content") and not _is_casual:
        syllabus_content = syllabus.get("content", "")
        syllabus_topics = ", ".join(syllabus.get("topics", [])[:10])
        grounding = (
            "\n\n---\n"
            f"**CURRICULUM ({_curriculum_label}):**\n"
            f"The student's curriculum covers the following topics. "
            f"Keep your answer within this academic scope:\n\n"
            f"{syllabus_content}\n\n"
        )
        if syllabus_topics:
            grounding += f"**Key topics:** {syllabus_topics}\n\n"
        grounding += "---\n"

    _syl_chapters_list = rag_context.get("_syllabus_chapters", [])
    if _syl_chapters_list:
        _subject_name_for_syl = context.get("subject_name", "")
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

    if source == "document":
        document_text = rag_context.get("document_text", "")
        if document_text:
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Uploaded Study Document):**\n"
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

    if source == "library":
        document_text = rag_context.get("document_text", "")
        if document_text:
            grounding += (
                "\n\n---\n"
                "**GROUNDING CONTEXT (Subject Library Context):**\n"
                "The student opened AI chat from a specific subject in the Syrabit library. "
                "Use this syllabus and chapter context to give accurate, curriculum-aligned answers.\n\n"
                "**Subject & syllabus:**\n"
                f"{document_text}\n\n"
                "---\n"
            )
            return base_prompt + grounding

    if web_results:
        syrabit_results = [r for r in web_results if r.get("_layer") == "syrabit"]
        base_results   = [r for r in web_results if r.get("_layer") == "base"]
        polish_results = [r for r in web_results if r.get("_layer") == "polish"]

        web_block = "\n\n---\n"
        web_block += (
            "**WEB SEARCH RESULTS — PRIMARY SOURCE:**\n"
            "Use the following web search results as your primary factual base to answer the student's question. "
            "Prioritize results from syrabit.ai (marked [Syrabit]) as they contain curriculum-aligned content. "
            "Supplement with your own knowledge for deeper explanations and examples.\n\n"
        )

        _any_enriched = any(r.get("_enriched") for r in web_results)
        _idx = 1

        if syrabit_results:
            for r in syrabit_results:
                title   = r.get("title", "")
                url     = r.get("url", "")
                content = r.get("full_content") or r.get("snippet", "")
                _tag = "[Full Content]" if r.get("_enriched") else "[Snippet]"
                web_block += f"[Syrabit {_idx}] {_tag} {title}\n{content}\nSource: {url}\n\n"
                _idx += 1

        for r in base_results:
            title   = r.get("title", "")
            url     = r.get("url", "")
            content = r.get("full_content") or r.get("snippet", "")
            _tag = "[Full Content]" if r.get("_enriched") else "[Snippet]"
            web_block += f"[Web {_idx}] {_tag} {title}\n{content}\nSource: {url}\n\n"
            _idx += 1

        for r in polish_results:
            title   = r.get("title", "")
            url     = r.get("url", "")
            content = r.get("full_content") or r.get("snippet", "")
            _tag = "[Full Content]" if r.get("_enriched") else "[Snippet]"
            web_block += f"[Web {_idx}] {_tag} {title}\n{content}\nSource: {url}\n\n"
            _idx += 1

        _enriched_note = (
            "Results marked [Full Content] contain detailed page text — rely on these heavily. "
            if _any_enriched else ""
        )
        web_block += (
            "---\n"
            "**ANSWER RULES (WEB SEARCH + YOUR KNOWLEDGE):**\n"
            f"*{_enriched_note}"
            "1. Syrabit results are HIGHEST PRIORITY — they contain curriculum-aligned content for Assam board students.\n"
            "2. Use web results as your factual anchor — extract key facts, definitions, explanations.\n"
            "3. Enrich with your own knowledge — deeper context, examples, analogies.\n"
            "4. Answer the student's actual question completely and accurately.\n"
            "5. ADAPT to the student: Use simple language, relatable examples, focus on what helps them score well.\n"
            "6. Do NOT add source citations inline — the system appends SOURCE automatically.\n"
            "7. NEVER hallucinate or invent facts.*\n"
        )
        grounding += web_block
    elif not _is_casual:
        _s1_subject_hint = rag_context.get("_stage1_subject", "")
        if _s1_subject_hint:
            grounding += (
                f"\n\nThe student appears to be asking about {_s1_subject_hint}. "
                f"Answer from your general knowledge about this subject. "
                f"Be accurate, educational, and helpful."
            )

    return base_prompt + grounding if grounding else base_prompt


_rag_telemetry: list = []
_RAG_TELEM_MAX = 20_000
_chat_latencies: list = []
_LATENCY_MAX = 10_000

def _record_rag_event(quality: str, latency_ms: float, query: str = "", intent: str = ""):
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
    _chat_latencies.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "latency_ms": round(latency_ms, 1),
    })
    if len(_chat_latencies) > _LATENCY_MAX:
        _chat_latencies.pop(0)
