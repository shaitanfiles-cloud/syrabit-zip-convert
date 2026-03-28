"""
Vertex AI / Gemini-powered services for Syrabit.ai
All features driven by GEMINI_API_KEY (Google AI Studio key).

Services:
  1. Text Embeddings    — semantic search across topics & pages
  2. Translation        — Assamese + other regional language translation
  3. Vision Analysis    — thumbnail/image analysis via Gemini Vision
  4. Content Enhancer   — improve auto-generated notes/MCQs
  5. Quality Scorer     — score content before publishing
  6. Topic Suggester    — fill syllabus gaps with AI suggestions
  7. SEO Meta Generator — title, description, keywords from content
  8. Content Gap Finder — find missing high-value topics
  9. Long Doc Reader    — summarise / extract from textbook PDFs (Gemini 1.5 Pro 1M)
"""

import os
import json
import logging
import base64
from typing import Optional, List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

GEMINI_KEY   = os.getenv("GEMINI_API_KEY", "").strip()
_BASE        = "https://generativelanguage.googleapis.com/v1beta"
_BASE_V1     = "https://generativelanguage.googleapis.com/v1"
_EMBED_MODEL = "text-embedding-004"
_GEN_MODEL   = "gemini-2.5-flash-preview-05-20"   # highest accuracy Gemini flash
_PRO_MODEL   = "gemini-2.5-flash-preview-05-20"  # long-doc: 1M ctx same model
_VISION_MODEL = "gemini-2.5-flash-preview-05-20"  # multimodal


def _ok() -> bool:
    return bool(GEMINI_KEY)


def _headers() -> dict:
    return {"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY}


# ─────────────────────────────────────────────────────────────────────────────
# 1. TEXT EMBEDDINGS  (text-embedding-004)
# ─────────────────────────────────────────────────────────────────────────────

async def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
    """Return 768-dim embedding vector for text. Returns None on failure."""
    if not _ok() or not text:
        return None
    url = f"{_BASE}/models/{_EMBED_MODEL}:embedContent"
    body = {
        "model": f"models/{_EMBED_MODEL}",
        "content": {"parts": [{"text": text[:8000]}]},
        "taskType": task_type,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(url, json=body, headers=_headers())
            r.raise_for_status()
            return r.json()["embedding"]["values"]
    except Exception as e:
        logger.warning(f"embed_text failed: {e}")
        return None


async def embed_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """Embed a batch of texts. Returns list of vectors (or None per item)."""
    import asyncio
    tasks = [embed_text(t) for t in texts]
    return await asyncio.gather(*tasks)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    return dot / (mag_a * mag_b + 1e-9)


async def semantic_search(query: str, candidates: List[Dict], text_key: str = "title",
                           top_k: int = 10) -> List[Dict]:
    """
    Rank `candidates` by semantic similarity to `query`.
    Each candidate must have a field `text_key`. Returns top_k sorted items
    with an added `score` field.
    """
    if not _ok() or not candidates:
        return candidates[:top_k]

    q_vec = await embed_text(query, task_type="RETRIEVAL_QUERY")
    if not q_vec:
        return candidates[:top_k]

    import asyncio
    texts = [c.get(text_key, "") for c in candidates]
    vecs  = await embed_batch(texts)

    scored = []
    for item, vec in zip(candidates, vecs):
        score = cosine_similarity(q_vec, vec) if vec else 0.0
        scored.append({**item, "score": round(score, 4)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# 2. TRANSLATION  (Gemini multilingual)
# ─────────────────────────────────────────────────────────────────────────────

_LANG_NAMES = {
    "as": "Assamese",
    "hi": "Hindi",
    "bn": "Bengali",
    "en": "English",
    "bho": "Bodo",
}


async def translate(text: str, target_lang: str = "as", source_lang: str = "en") -> Optional[str]:
    """Translate text to target language using Gemini. Default: English → Assamese."""
    if not _ok() or not text:
        return None
    lang_name = _LANG_NAMES.get(target_lang, target_lang)
    prompt = (
        f"Translate the following educational content from {_LANG_NAMES.get(source_lang, source_lang)} "
        f"to {lang_name}. Keep all technical terms, subject names, and proper nouns as-is. "
        f"Return ONLY the translated text, no explanations.\n\n{text[:4000]}"
    )
    return await _generate(prompt, max_tokens=4096)


async def translate_structured(content: dict, fields: List[str], target_lang: str = "as") -> dict:
    """Translate specific fields in a dict. Returns dict with translated fields."""
    import asyncio
    tasks = {f: translate(content.get(f, ""), target_lang) for f in fields if content.get(f)}
    results = await asyncio.gather(*tasks.values())
    out = dict(content)
    for key, result in zip(tasks.keys(), results):
        if result:
            out[f"{key}_{target_lang}"] = result
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. VISION ANALYSIS  (Gemini Vision — replaces Groq vision)
# ─────────────────────────────────────────────────────────────────────────────

async def analyze_image(image_bytes: bytes, mime_type: str = "image/jpeg",
                         prompt: str = "Describe this image in detail.") -> Optional[str]:
    """Analyze an image with Gemini Vision. Returns text description."""
    if not _ok():
        return None
    b64 = base64.b64encode(image_bytes).decode()
    url = f"{_BASE}/models/{_VISION_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime_type, "data": b64}},
        ]}],
        "generationConfig": {"maxOutputTokens": 1024},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, json=body, headers=_headers())
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.warning(f"analyze_image failed: {e}")
        return None


async def analyze_thumbnail(image_bytes: bytes, subject: str = "", topic: str = "") -> dict:
    """Full thumbnail analysis: colors, style, accessibility, improvement suggestions."""
    if not _ok():
        return {}
    prompt = (
        f"Analyze this educational thumbnail for '{topic}' ({subject}). "
        f"Return a JSON object with: dominant_colors (list), style (string), "
        f"accessibility_score (0-10), text_readability (0-10), "
        f"improvement_suggestions (list of strings), overall_score (0-10). "
        f"Return ONLY valid JSON."
    )
    raw = await analyze_image(image_bytes, prompt=prompt)
    if not raw:
        return {}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned)
    except Exception:
        return {"raw_analysis": raw}


# ─────────────────────────────────────────────────────────────────────────────
# 4. CONTENT ENHANCER
# ─────────────────────────────────────────────────────────────────────────────

async def enhance_content(content: str, page_type: str = "notes",
                           subject: str = "", topic: str = "",
                           class_name: str = "Class 11") -> Optional[str]:
    """
    Improve AI-generated educational content.
    page_type: notes | mcqs | definition | important-questions | examples
    """
    if not _ok() or not content:
        return None

    type_hints = {
        "notes":               "Make the notes clearer, add more examples, better structure with headers, and ensure exam relevance.",
        "mcqs":                "Improve MCQ distractors to be more plausible, ensure questions test understanding not just recall.",
        "definition":          "Make the definition precise, include etymology if helpful, and give a real-world analogy.",
        "important-questions": "Ensure questions cover all board exam patterns (2-mark, 5-mark, 10-mark). Add model answer hints.",
        "examples":            "Add more relatable, Assam-context examples that AHSEC students will recognize.",
    }

    prompt = (
        f"You are an expert {subject} teacher for AHSEC {class_name} students in Assam, India.\n"
        f"Improve the following {page_type} content for the topic: {topic}\n\n"
        f"Instruction: {type_hints.get(page_type, 'Make it better and more exam-focused.')}\n\n"
        f"Return ONLY the improved content in the same format (Markdown). Do not add explanatory text.\n\n"
        f"ORIGINAL CONTENT:\n{content[:6000]}"
    )
    return await _generate(prompt, max_tokens=4096)


# ─────────────────────────────────────────────────────────────────────────────
# 5. QUALITY SCORER
# ─────────────────────────────────────────────────────────────────────────────

async def score_content(content: str, page_type: str = "notes",
                         topic: str = "", subject: str = "") -> dict:
    """Score content quality. Returns dict with scores and issues."""
    if not _ok() or not content:
        return {"overall": 0, "error": "No content or API key"}

    prompt = (
        f"Score this {page_type} content about '{topic}' ({subject}) for AHSEC students.\n"
        f"Return a JSON with:\n"
        f"  accuracy (0-10): factual correctness\n"
        f"  completeness (0-10): topic coverage\n"
        f"  clarity (0-10): easy to understand\n"
        f"  exam_relevance (0-10): useful for board exams\n"
        f"  overall (0-10): weighted average\n"
        f"  issues (list of strings): specific problems found\n"
        f"  strengths (list of strings): what's good\n"
        f"Return ONLY valid JSON.\n\nCONTENT:\n{content[:3000]}"
    )
    raw = await _generate(prompt, max_tokens=512)
    if not raw:
        return {"overall": 0, "error": "Generation failed"}
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
        return json.loads(cleaned)
    except Exception:
        return {"overall": 5, "raw": raw}


# ─────────────────────────────────────────────────────────────────────────────
# 6. TOPIC SUGGESTER
# ─────────────────────────────────────────────────────────────────────────────

async def suggest_topics(subject: str, class_name: str,
                          existing_topics: List[str],
                          board: str = "AHSEC") -> List[dict]:
    """Suggest missing high-value topics for a subject."""
    if not _ok():
        return []
    existing_sample = ", ".join(existing_topics[:30])
    prompt = (
        f"You are an expert {board} {class_name} {subject} curriculum designer.\n"
        f"The platform already has content for: {existing_sample}{'...' if len(existing_topics) > 30 else ''}.\n\n"
        f"Suggest 10 important topics that are MISSING and have HIGH search volume from students.\n"
        f"Return a JSON array of objects with: title, priority (high/medium), search_volume_estimate (number/month), reason.\n"
        f"Return ONLY valid JSON array."
    )
    raw = await _generate(prompt, max_tokens=1024)
    if not raw:
        return []
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
        result = json.loads(cleaned)
        return result if isinstance(result, list) else []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 7. SEO META GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

async def generate_seo_meta(topic: str, subject: str, class_name: str,
                             page_type: str, board: str = "AHSEC",
                             content_preview: str = "") -> dict:
    """Generate optimised SEO meta: title, description, keywords, OG tags."""
    if not _ok():
        return {}
    prompt = (
        f"Generate SEO metadata for an educational page about:\n"
        f"  Topic: {topic}\n  Subject: {subject}\n  Class: {class_name}\n"
        f"  Page type: {page_type}\n  Board: {board}\n"
        f"{'Content preview: ' + content_preview[:500] if content_preview else ''}\n\n"
        f"Return JSON with:\n"
        f"  title (max 60 chars, include topic + board + class)\n"
        f"  meta_description (max 160 chars, includes call-to-action)\n"
        f"  keywords (list of 8-12 strings)\n"
        f"  og_title (Open Graph title, can be slightly longer)\n"
        f"  og_description (2 sentences, benefit-focused)\n"
        f"  schema_name (for JSON-LD)\n"
        f"Return ONLY valid JSON."
    )
    raw = await _generate(prompt, max_tokens=512)
    if not raw:
        return {}
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
        return json.loads(cleaned)
    except Exception:
        return {"raw": raw}


# ─────────────────────────────────────────────────────────────────────────────
# 8. CONTENT GAP FINDER
# ─────────────────────────────────────────────────────────────────────────────

async def find_content_gaps(published_slugs: List[str],
                             top_searches: List[str],
                             subjects: List[str]) -> List[dict]:
    """
    Cross-reference published content with top searches to find high-value gaps.
    Returns list of {query, gap_type, priority, suggested_slug, estimated_monthly_searches}.
    """
    if not _ok():
        return []
    prompt = (
        f"Analyse these search queries from students and identify content gaps.\n\n"
        f"Top student search queries:\n{chr(10).join(f'- {q}' for q in top_searches[:20])}\n\n"
        f"Subjects covered: {', '.join(subjects[:10])}\n"
        f"Published pages count: {len(published_slugs)}\n\n"
        f"Return a JSON array of top 10 gaps with:\n"
        f"  query (string), gap_type (missing_topic/incomplete_coverage/wrong_level),\n"
        f"  priority (high/medium), suggested_action (string),\n"
        f"  estimated_monthly_searches (number)\n"
        f"Return ONLY valid JSON array."
    )
    raw = await _generate(prompt, max_tokens=1024)
    if not raw:
        return []
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
        result = json.loads(cleaned)
        return result if isinstance(result, list) else []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 9. LONG DOCUMENT READER  (Gemini 1.5 Pro — 1M token context)
# ─────────────────────────────────────────────────────────────────────────────

async def extract_from_document(pdf_bytes: bytes, task: str = "extract_mcqs") -> dict:
    """
    Process a PDF (textbook, question paper) with Gemini 1.5 Pro.
    task: extract_mcqs | extract_topics | summarise | extract_questions
    """
    if not _ok():
        return {"error": "No API key"}

    b64 = base64.b64encode(pdf_bytes).decode()
    task_prompts = {
        "extract_mcqs":      "Extract all MCQ questions with their options and correct answers. Return a JSON array of {question, options, correct_answer, topic}.",
        "extract_topics":    "List all chapter topics and subtopics covered. Return a JSON array of {chapter, topics: []}.",
        "summarise":         "Summarise each chapter in 3-5 bullet points. Return a JSON array of {chapter, summary_points: []}.",
        "extract_questions": "Extract all exam-style questions (short answer, long answer, numericals). Return a JSON array of {question, type, marks, topic}.",
    }

    prompt = task_prompts.get(task, task_prompts["summarise"])
    url = f"{_BASE}/models/{_PRO_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [
            {"text": prompt + "\n\nReturn ONLY valid JSON."},
            {"inline_data": {"mime_type": "application/pdf", "data": b64}},
        ]}],
        "generationConfig": {"maxOutputTokens": 8192},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=body, headers=_headers())
            r.raise_for_status()
            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
            return {"result": json.loads(cleaned), "task": task}
    except Exception as e:
        logger.warning(f"extract_from_document failed: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL: shared generate helper
# ─────────────────────────────────────────────────────────────────────────────

async def _generate(prompt: str, model: str = _GEN_MODEL,
                    max_tokens: int = 2048, temperature: float = 0.3) -> Optional[str]:
    if not _ok():
        return None
    url = f"{_BASE}/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(url, json=body, headers=_headers())
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.warning(f"vertex _generate failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# STATUS CHECK
# ─────────────────────────────────────────────────────────────────────────────

async def health_check() -> dict:
    """Quick connectivity check — returns service status for all features."""
    if not _ok():
        return {"ok": False, "reason": "GEMINI_API_KEY not set"}
    test = await embed_text("test", task_type="SEMANTIC_SIMILARITY")
    gen_test = await _generate("Reply with just the word: OK", max_tokens=5)
    return {
        "ok": True,
        "embeddings": test is not None,
        "generation": gen_test is not None and "OK" in (gen_test or ""),
        "models": {
            "generation": _GEN_MODEL,
            "embedding":  _EMBED_MODEL,
            "vision":     _VISION_MODEL,
            "long_doc":   _PRO_MODEL,
        },
        "services": [
            "text_embeddings", "semantic_search", "translation",
            "vision_analysis", "content_enhancer", "quality_scorer",
            "topic_suggester", "seo_meta_generator", "content_gap_finder",
            "long_doc_reader",
        ],
    }
