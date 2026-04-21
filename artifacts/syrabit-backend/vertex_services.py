"""
vertex_services — DISABLED STUB (2026-04-19)

The original 890-line module wrapped Google Vertex AI / Gemini for
embeddings, vision OCR, translation, content enhancement and ~15 other
services. It has been retired per user request alongside the Gemini
chat-LLM removal.

This stub is kept (instead of deleting the file) so that every
`import vertex_services` and `from vertex_services import X` site
across the codebase still resolves at module-load time. Route modules
like `routes/pyq.py`, `routes/admin_advanced.py` and
`routes/cms_sarvam_health.py` do `import vertex_services` at the top —
removing the file would crash the entire FastAPI app on startup.

Behaviour:
  • Embedding functions return [] / 0.0 so semantic-search and
    syllabus-seed loops degrade to "no results" instead of crashing.
    Callers in syllabus_embedder.py already log a warning and skip
    the chunk on empty embeddings.
  • All generation / OCR / translate functions raise RuntimeError
    with the standard message. Existing try/except blocks in routes
    convert this to HTTP 502, e.g. PYQ upload returns "Gemini OCR
    failed".
  • Constants (_EMBED_MODEL) keep stable string values so equality
    checks against cached embeddings still work.

To restore the original module, `git checkout cedd1e06^ -- artifacts/syrabit-backend/vertex_services.py`.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

_DISABLED_MSG = "vertex_services has been disabled — Gemini-backed feature unavailable"
_warned_once = False


def _warn_once() -> None:
    global _warned_once
    if not _warned_once:
        logger.warning(_DISABLED_MSG)
        _warned_once = True


# ── Constants kept for callers that read them ────────────────────────────────
_EMBED_MODEL = "disabled-embed-model"
_EMBED_DIM = 768


# ── Embedding API ────────────────────────────────────────────────────────────
# Vertex is disabled in this build, so the historical behaviour was "return
# empty so loops skip cleanly". Task #636 wires Cloudflare Workers AI
# (`@cf/baai/bge-base-en-v1.5`, 768-dim) as a transparent fallback so document
# indexing and RAG queries actually work in production. The fallback is
# gated by the same kill-switch + secret as the chat fallback; if disabled
# we revert to the original "return []" so the existing skip-on-empty
# code paths still work.
async def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
    if not text or not isinstance(text, str):
        return []
    try:
        from providers import workers_ai as _wai
        if _wai.is_enabled("embed"):
            # We synthesise a "primary disabled" exception so attempt_fallback's
            # policy treats it as retryable. Without this the embed cap stays
            # idle even though there's no real primary to wait on.
            class _VertexDisabled(TimeoutError):
                pass
            err = _VertexDisabled("vertex_embed_disabled")
            ok, val, _label = await _wai.attempt_fallback(
                "embed", err, 0,
                lambda: _wai.call_embed(text),
            )
            if ok and val:
                # bge-base-en returns a list of vectors even for a single input.
                vec = val[0] if isinstance(val, list) and val and isinstance(val[0], list) else val
                return list(vec) if vec else []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[workers-ai] embed fallback failed: {type(e).__name__}: {str(e)[:150]}")
    _warn_once()
    return []


async def embed_batch(texts: List[str]) -> List[List[float]]:
    texts = [t for t in (texts or []) if t and isinstance(t, str)]
    if not texts:
        return []
    try:
        from providers import workers_ai as _wai
        if _wai.is_enabled("embed"):
            class _VertexDisabled(TimeoutError):
                pass
            err = _VertexDisabled("vertex_embed_disabled")
            ok, val, _label = await _wai.attempt_fallback(
                "embed", err, 0,
                lambda: _wai.call_embed(texts),
            )
            if ok and isinstance(val, list) and val:
                # Pad with empty vectors if Workers AI returned fewer rows
                # than we sent — caller code expects len(out) == len(texts).
                out = [list(v) if isinstance(v, list) else [] for v in val]
                while len(out) < len(texts):
                    out.append([])
                return out[: len(texts)]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[workers-ai] embed_batch fallback failed: {type(e).__name__}: {str(e)[:150]}")
    _warn_once()
    return []


def cosine_similarity(a: List[float], b: List[float]) -> float:
    return 0.0


# ── Generation / OCR / Vision (raise — caught by route try/except) ───────────
async def _generate(prompt: str, max_tokens: int = 1024, temperature: float = 0.7, **_kw: Any) -> str:
    raise RuntimeError(_DISABLED_MSG)


async def analyze_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    prompt: str = "",
    max_output_tokens: int = 4096,
    **_kw: Any,
) -> str:
    raise RuntimeError(_DISABLED_MSG)


async def ocr_image(img_bytes: bytes, mime_type: str = "image/jpeg", **_kw: Any) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


async def extract_from_document(pdf_bytes: bytes, task: str = "summary", **_kw: Any) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


# ── Translation / Content services ──────────────────────────────────────────
async def translate(
    text: str,
    target_lang: str = "en",
    source_lang: Optional[str] = None,
    **_kw: Any,
) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


async def semantic_search(
    query: str,
    items: List[Dict[str, Any]],
    text_key: str = "title",
    top_k: int = 10,
    **_kw: Any,
) -> List[Dict[str, Any]]:
    _warn_once()
    return []


async def enhance_content(
    content: str,
    page_type: str = "",
    subject: str = "",
    topic: str = "",
    class_name: str = "",
    **_kw: Any,
) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


async def score_content(
    content: str,
    page_type: str = "",
    topic: str = "",
    subject: str = "",
    **_kw: Any,
) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


async def suggest_topics(
    subject: str,
    class_name: str = "",
    existing: Optional[List[str]] = None,
    board: str = "",
    **_kw: Any,
) -> List[Dict[str, Any]]:
    raise RuntimeError(_DISABLED_MSG)


async def generate_seo_meta(
    topic: str,
    subject: str = "",
    class_name: str = "",
    page_type: str = "",
    board: str = "",
    content_preview: str = "",
    **_kw: Any,
) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


async def find_content_gaps(
    published: List[str],
    top_searches: List[str],
    subjects: List[str],
    **_kw: Any,
) -> List[Dict[str, Any]]:
    raise RuntimeError(_DISABLED_MSG)


async def extract_key_concepts(
    text: str,
    subject: str = "",
    class_name: str = "",
    **_kw: Any,
) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


async def generate_flashcards(
    text: str,
    subject: str = "",
    count: int = 10,
    class_name: str = "",
    **_kw: Any,
) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


async def generate_mcqs(
    text: str,
    subject: str = "",
    class_name: str = "",
    **_kw: Any,
) -> Dict[str, Any]:
    raise RuntimeError(_DISABLED_MSG)


# ── Health probe ────────────────────────────────────────────────────────────
async def health_check() -> Dict[str, Any]:
    return {
        "status": "disabled",
        "message": _DISABLED_MSG,
        "embed_model": _EMBED_MODEL,
    }


logger.info("vertex_services: stub loaded — all Gemini features disabled")
