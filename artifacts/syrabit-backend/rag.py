"""Syrabit.ai — Syllabus-focused web search engine (RAG removed)."""
import os, re, asyncio, time, uuid, hashlib, logging
from typing import Optional, Dict, List
from datetime import datetime, timezone
from fastapi import HTTPException
from deps import db, logger as _dep_logger, _assert_not_cms_context, is_mongo_available
from cache import (
    _cache_key, _redis_get_search, _redis_cache_search,
    _redis_get_ai_cache, _redis_set,
)
from utils import _extract_keywords, _slow_query

logger = logging.getLogger(__name__)

__all__ = [
    "_HISTORY_MAX_TURNS", "_HISTORY_TOKEN_BUDGET",
    "_LATENCY_MAX", "_RAG_TELEM_MAX",
    "_chat_latencies",
    "_extract_relevant_sections",
    "_rag_telemetry", "_record_chat_latency",
    "_record_rag_event", "_sources_from_rag_ctx", "_trim_history",
    "build_rag_system_prompt",
    "get_vector_search_stats", "get_pipeline_stats", "record_pipeline_run",
    "_record_vector_search",
    "resolve_rag_context",
    "auto_chunk_content", "backfill_chunk_embeddings",
    "rag_search", "rechunk_chapter", "vector_rag_search",
    "syrabit_library_search",
    "_fetch_content_card", "_fetch_enrichment_blocks",
    "_embed_and_store_chapter", "_embed_and_store_page", "_embed_cms_document",
    "web_search_with_fallback",
    "_sources_from_web_results",
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
    return []

async def rechunk_chapter(*args, **kwargs) -> dict:
    return {"status": "skipped", "reason": "RAG removed"}

async def backfill_chunk_embeddings(*args, **kwargs) -> dict:
    return {"status": "skipped", "reason": "RAG removed"}

async def vector_rag_search(*args, **kwargs) -> list:
    return []

async def rag_search(*args, **kwargs) -> dict:
    return {"chunks": [], "chapters": [], "subjects": [], "source": "none", "quality": "none"}

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


_WEB_SEARCH_CACHE: dict[str, tuple[float, list]] = {}
_WEB_SEARCH_CACHE_TTL = 300
_WEB_SEARCH_CACHE_MAX = 256

_SYRABIT_DOMAINS = {"syrabit.ai", "www.syrabit.ai"}

_EDUCATIONAL_DOMAINS = {
    "ncert.nic.in", "byjus.com", "vedantu.com", "toppr.com",
    "learncbse.in", "geeksforgeeks.org", "shaalaa.com",
    "doubtnut.com", "askiitians.com", "meritnation.com",
    "brainly.in", "javatpoint.com", "studiestoday.com",
    "tutorialspoint.com", "mathsisfun.com", "khanacademy.org",
    "wikipedia.org", "brilliant.org", "unacademy.com",
}


def _build_search_query(
    query: str,
    board_name: str = "",
    class_name: str = "",
    subject_name: str = "",
    chapter_name: str = "",
) -> str:
    parts = [query]
    if board_name:
        b = board_name.strip().upper()
        if b in ("AHSEC", "SEBA", "DEGREE"):
            parts.append(b)
        else:
            parts.append(board_name.strip())
    if class_name:
        parts.append(class_name.strip())
    if subject_name and subject_name.lower() not in query.lower():
        parts.append(subject_name.strip())
    if chapter_name and chapter_name.lower() not in query.lower():
        parts.append(chapter_name.strip())
    return " ".join(parts)


async def _ddg_search(query: str, max_results: int = 5) -> list:
    try:
        from ddgs import DDGS
        def _do_search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results, region="in-en"))
        results = await asyncio.wait_for(
            asyncio.to_thread(_do_search),
            timeout=3.0,
        )
        return results or []
    except asyncio.TimeoutError:
        logger.warning(f"[WEB_SEARCH] DDG search timed out for: {query[:60]}")
        return []
    except Exception as e:
        logger.warning(f"[WEB_SEARCH] DDG search failed: {e}")
        return []


def _is_safe_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        import ipaddress
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                return False
            if host.endswith(".local") or host.endswith(".internal"):
                return False
        return True
    except Exception:
        return False

_httpx_client = None

def _get_httpx_client():
    global _httpx_client
    if _httpx_client is None:
        import httpx
        _httpx_client = httpx.AsyncClient(
            timeout=3.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _httpx_client

async def _fetch_page_content(url: str, max_chars: int = 3000) -> str:
    if not url or not _is_safe_url(url):
        return ""
    try:
        client = _get_httpx_client()
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 SyrabitBot/1.0"})
        final_url = str(resp.url)
        if not _is_safe_url(final_url):
            return ""
        if resp.status_code != 200:
            return ""
        html = resp.text
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-zA-Z]+;', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) < 50:
            return ""
        return text[:max_chars]
    except Exception:
        return ""


async def web_search_with_fallback(
    query: str,
    *,
    num_results: int = 8,
    board_name: str = "",
    class_name: str = "",
    subject_name: str = "",
    chapter_name: str = "",
    enrich_top_n: int = 2,
) -> list:
    cache_key = hashlib.md5(f"{query}:{board_name}:{class_name}:{subject_name}:{chapter_name}".lower().encode()).hexdigest()
    cached = _WEB_SEARCH_CACHE.get(cache_key)
    if cached:
        ts, results = cached
        if time.time() - ts < _WEB_SEARCH_CACHE_TTL:
            logger.info(f"[WEB_SEARCH] Cache HIT for '{query[:40]}' ({len(results)} results)")
            return results

    t0 = time.perf_counter()
    all_results: list = []
    seen_urls: set = set()

    scoped_query = _build_search_query(query, board_name, class_name, subject_name, chapter_name)

    syrabit_task = _ddg_search(f"site:syrabit.ai {scoped_query}", max_results=3)
    web_task = _ddg_search(scoped_query, max_results=num_results)
    syrabit_raw, web_raw = await asyncio.gather(syrabit_task, web_task, return_exceptions=True)

    if isinstance(syrabit_raw, list):
        for r in syrabit_raw:
            url = r.get("href", r.get("url", ""))
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", r.get("snippet", "")),
                    "url": url,
                    "_layer": "syrabit",
                })
    else:
        logger.warning(f"[WEB_SEARCH] Syrabit layer failed: {syrabit_raw}")

    if isinstance(web_raw, list):
        edu_results = []
        other_results = []
        for r in web_raw:
            url = r.get("href", r.get("url", ""))
            if url and url not in seen_urls:
                seen_urls.add(url)
                entry = {
                    "title": r.get("title", ""),
                    "snippet": r.get("body", r.get("snippet", "")),
                    "url": url,
                    "_layer": "base",
                }
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc.lower().lstrip("www.")
                    if domain in _EDUCATIONAL_DOMAINS:
                        edu_results.append(entry)
                    else:
                        other_results.append(entry)
                except Exception:
                    other_results.append(entry)
        all_results.extend(edu_results)
        all_results.extend(other_results)
    else:
        logger.warning(f"[WEB_SEARCH] Web layer failed: {web_raw}")

    if not all_results:
        logger.warning(f"[WEB_SEARCH] No results for: {query[:60]}")
        return []

    if enrich_top_n > 0 and all_results:
        to_enrich = all_results[:enrich_top_n]
        enrichment_tasks = [_fetch_page_content(r["url"]) for r in to_enrich]
        enriched = await asyncio.gather(*enrichment_tasks, return_exceptions=True)
        for i, content in enumerate(enriched):
            if isinstance(content, str) and content.strip():
                to_enrich[i]["full_content"] = content
                to_enrich[i]["_enriched"] = True

    dur_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        f"[WEB_SEARCH] '{query[:50]}' → {len(all_results)} results "
        f"(syrabit={sum(1 for r in all_results if r.get('_layer')=='syrabit')}, "
        f"edu={sum(1 for r in all_results if r.get('_layer')=='base')}) "
        f"in {dur_ms:.0f}ms"
    )

    if len(_WEB_SEARCH_CACHE) >= _WEB_SEARCH_CACHE_MAX:
        oldest = min(_WEB_SEARCH_CACHE, key=lambda k: _WEB_SEARCH_CACHE[k][0])
        del _WEB_SEARCH_CACHE[oldest]
    _WEB_SEARCH_CACHE[cache_key] = (time.time(), all_results)

    return all_results


async def syrabit_library_search(query: str, *, board_name: str = "", class_name: str = "", subject_name: str = "", limit: int = 10, **kwargs) -> list:
    try:
        results = await web_search_with_fallback(
            query, num_results=limit,
            board_name=board_name, class_name=class_name,
            subject_name=subject_name,
        )
        return [
            {"title": r.get("title", ""), "snippet": r.get("snippet", ""), "url": r.get("url", ""), "source": r.get("_layer", "web")}
            for r in results
        ]
    except Exception as e:
        logger.warning(f"syrabit_library_search web fallback failed: {e}")
        return []


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
        relevant = _extract_relevant_sections(document_text, query)
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


def _sources_from_web_results(web_results: list) -> list:
    sources = []
    seen = set()
    for r in (web_results or []):
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            sources.append({
                "type": "web",
                "title": r.get("title", ""),
                "url": url,
                "layer": r.get("_layer", "web"),
            })
    return sources[:6]


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

    _extraction_rules = get_intent_extraction_rules(_intent)
    if _extraction_rules and not _is_casual:
        base_prompt += f"\n\n{_extraction_rules}"

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
