"""
Vertex AI / Gemini-powered services for Syrabit.ai.

Three auth modes detected at import time:
  A) Vertex AI service-account JSON  → VERTEX_SERVICE_ACCOUNT (or
     GEMINI_API_KEY containing JSON), uses {region}-aiplatform.googleapis.com.
  B) Google AI Studio API key        → GEMINI_API_KEY=AIza..., uses
     generativelanguage.googleapis.com.
  C) BYOK via CF AI Gateway          → no local credential, but
     CF_AI_GATEWAY_ACCOUNT_ID + CF_AI_GATEWAY_ID set with a BYOK binding.

When CF_AI_GATEWAY_ACCOUNT_ID + CF_AI_GATEWAY_ID are configured, every
call is routed through the gateway by URL rewriting plus
cf-aig-authorization / cf-aig-cache-ttl headers.

Services: embeddings, semantic_search, translate, analyze_image,
ocr_image, extract_key_concepts, generate_flashcards, generate_mcqs,
enhance_content, score_content, suggest_topics, generate_seo_meta,
find_content_gaps, extract_from_document, health_check.
"""

import os
import json
import asyncio
import logging
import base64
from typing import Optional, List, Dict

import httpx

logger = logging.getLogger(__name__)

# ── Cloudflare AI Gateway (optional) ─────────────────────────────────────────
_CF_ACCT = os.environ.get("CF_AI_GATEWAY_ACCOUNT_ID", "").strip()
_CF_GW   = os.environ.get("CF_AI_GATEWAY_ID", "").strip()
_CF_TOK  = os.environ.get("CF_AI_GATEWAY_TOKEN", "").strip()
_CF_TTL  = int(os.environ.get("CF_AI_GATEWAY_CACHE_TTL", "3600"))
_CF_GW_BASE = (
    f"https://gateway.ai.cloudflare.com/v1/{_CF_ACCT}/{_CF_GW}"
    if (_CF_ACCT and _CF_GW) else ""
)
_CF_GW_ENABLED = bool(_CF_GW_BASE)
_CF_GW_BYOK = (
    _CF_GW_ENABLED
    and os.environ.get("CF_AI_GATEWAY_BYOK", "1").strip().lower() not in ("0", "false", "no", "off")
)


# ── HTTP client (embed path) ────────────────────────────────────────────────
_embed_http_client: Optional[httpx.AsyncClient] = None
_EMBED_MAX_CONCURRENT = int(os.environ.get("EMBED_MAX_CONCURRENT", "8"))
_EMBED_SEMAPHORE: Optional[asyncio.Semaphore] = None


def _get_embed_semaphore() -> asyncio.Semaphore:
    global _EMBED_SEMAPHORE
    if _EMBED_SEMAPHORE is None:
        _EMBED_SEMAPHORE = asyncio.Semaphore(_EMBED_MAX_CONCURRENT)
    return _EMBED_SEMAPHORE


def _get_embed_client() -> httpx.AsyncClient:
    global _embed_http_client
    if _embed_http_client is None or _embed_http_client.is_closed:
        _embed_http_client = httpx.AsyncClient(
            timeout=15,
            http2=True,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
        )
    return _embed_http_client


_EMBED_RETRY_MAX_ATTEMPTS = int(os.environ.get("EMBED_RETRY_MAX_ATTEMPTS", "3"))
_EMBED_RETRY_BASE_MS = int(os.environ.get("EMBED_RETRY_BASE_MS", "400"))


def _is_transient_embed_error(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.CancelledError):
        return False
    msg = str(exc).lower()
    if any(s in msg for s in (
        "ssl", "timeout", "timed out", "connection", "remote",
        "semaphore released too many times",
        "rate limit", "429", "500", "502", "503", "504",
    )):
        return True
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    return False


# ── Models ──────────────────────────────────────────────────────────────────
# Generation/vision/long-doc models can be overridden via env. Embedding
# model is locked to gemini-embedding-001 because Vectorize
# syllabus-index-v2 expects 1024-dim vectors from this exact model.
_EMBED_MODEL  = "gemini-embedding-001"
_GEN_MODEL    = os.environ.get("VERTEX_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
_PRO_MODEL    = os.environ.get("VERTEX_GEMINI_PRO_MODEL", _GEN_MODEL).strip() or _GEN_MODEL
_VISION_MODEL = os.environ.get("VERTEX_GEMINI_VISION_MODEL", _GEN_MODEL).strip() or _GEN_MODEL
_EMBED_DIMENSIONS = 1024


# ── Auth detection ──────────────────────────────────────────────────────────
_KEY_RAW = (
    os.getenv("VERTEX_SERVICE_ACCOUNT", "").strip()
    or os.getenv("GEMINI_API_KEY", "").strip()
)

_SA_CREDS         = None
_VERTEX_PROJECT   = os.environ.get("VERTEX_PROJECT_ID", "").strip()
_VERTEX_LOCATION  = os.environ.get("VERTEX_LOCATION", "us-central1").strip() or "us-central1"
_VERTEX_BASE      = ""
_API_KEY: str     = ""
_USE_BYOK: bool   = False

_BASE    = "https://generativelanguage.googleapis.com/v1beta"
_BASE_V1 = "https://generativelanguage.googleapis.com/v1"

GEMINI_KEY = _KEY_RAW

if _KEY_RAW.startswith("{"):
    try:
        from google.oauth2 import service_account as _sa_mod
        _sa_info = json.loads(_KEY_RAW)
        if not _VERTEX_PROJECT:
            _VERTEX_PROJECT = _sa_info.get("project_id", "")
        _SA_CREDS = _sa_mod.Credentials.from_service_account_info(
            _sa_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        _VERTEX_BASE = (
            f"https://{_VERTEX_LOCATION}-aiplatform.googleapis.com/v1"
            f"/projects/{_VERTEX_PROJECT}/locations/{_VERTEX_LOCATION}"
            f"/publishers/google/models"
        )
    except Exception as _sa_err:
        logger.error(f"vertex_services: failed to parse service-account JSON — {_sa_err}")
        _SA_CREDS = None
elif _KEY_RAW:
    _API_KEY = _KEY_RAW
elif _CF_GW_BYOK:
    _USE_BYOK = True

# Fallback wiring: when VERTEX_SERVICE_ACCOUNT is present but malformed
# (SA parse failed) OR a runtime 403 disables it, fall back to
# GEMINI_API_KEY if separately set. Without this, prod sat in "disabled"
# mode for the whole session even though a working API key was available.
_GEMINI_API_KEY_FALLBACK = os.getenv("GEMINI_API_KEY", "").strip()
if _SA_CREDS is None and not _API_KEY and not _USE_BYOK and _GEMINI_API_KEY_FALLBACK:
    _API_KEY = _GEMINI_API_KEY_FALLBACK
    GEMINI_KEY = _GEMINI_API_KEY_FALLBACK
    logger.warning(
        "vertex_services: VERTEX_SERVICE_ACCOUNT unusable — falling back to "
        "GEMINI_API_KEY (Google AI Studio direct mode)."
    )

_GEMINI_FORBIDDEN = False


def _auth_mode_label() -> str:
    if _SA_CREDS is not None:
        return "vertex_ai_service_account"
    if _API_KEY:
        return "google_ai_studio_api_key"
    if _USE_BYOK:
        return "cf_ai_gateway_byok"
    return "disabled"


_AUTH_MODE = _auth_mode_label()

# Fail-loud: when no credentials are available, log at ERROR so the
# misconfiguration is visible in deploy logs (the previous WARNING
# made an entire stub-mode regression silent for days).
if _AUTH_MODE == "disabled":
    logger.error(
        "vertex_services: NO credentials configured. Set VERTEX_SERVICE_ACCOUNT or "
        "GEMINI_API_KEY, or configure CF_AI_GATEWAY_ACCOUNT_ID + CF_AI_GATEWAY_ID "
        "with a BYOK binding. Every Gemini-backed feature will return None / 503."
    )
    if os.environ.get("VERTEX_REQUIRED", "").strip().lower() in ("1", "true", "yes", "on"):
        # Opt-in hard-fail for deploys that want boot to error rather
        # than start in a degraded state.
        raise RuntimeError(
            "vertex_services: VERTEX_REQUIRED=1 but no credentials are configured."
        )
else:
    _gw_note = (
        f" via_cf_gateway=acct={_CF_ACCT[:6]}…/{_CF_GW}"
        if _CF_GW_ENABLED else ""
    )
    logger.info(
        f"vertex_services: ready auth_mode={_AUTH_MODE} "
        f"embed_model={_EMBED_MODEL} gen_model={_GEN_MODEL} "
        f"project={_VERTEX_PROJECT or 'n/a'}{_gw_note}"
    )


def _ok() -> bool:
    if _GEMINI_FORBIDDEN:
        return False
    return bool(_API_KEY) or _SA_CREDS is not None or _USE_BYOK


def _mark_forbidden() -> None:
    """When Gemini upstream returns 403, attempt one runtime fallback to
    GEMINI_API_KEY (Google AI Studio direct mode) before disabling. This
    rescues prod from a bad VERTEX_SERVICE_ACCOUNT (e.g. SA lacks Vertex
    AI User role) when a working API key is also configured."""
    global _GEMINI_FORBIDDEN, _SA_CREDS, _API_KEY, _USE_BYOK, _AUTH_MODE, GEMINI_KEY
    if _GEMINI_FORBIDDEN:
        return
    fallback_key = os.getenv("GEMINI_API_KEY", "").strip()
    if (_SA_CREDS is not None or _USE_BYOK) and fallback_key and fallback_key != _API_KEY:
        _SA_CREDS = None
        _USE_BYOK = False
        _API_KEY = fallback_key
        GEMINI_KEY = fallback_key
        _AUTH_MODE = "google_ai_studio_api_key"
        logger.warning(
            "Gemini 403 on previous auth mode — switching to GEMINI_API_KEY "
            "(Google AI Studio direct) for the rest of this session."
        )
        return
    _GEMINI_FORBIDDEN = True
    logger.error(
        "Gemini upstream returned 403 Forbidden — credential is invalid or the "
        "model is not accessible. Disabling Gemini calls for this session."
    )


# ── URL + headers (gateway-aware) ───────────────────────────────────────────
def _gw_extra_headers() -> dict:
    if not _CF_GW_ENABLED:
        return {}
    h: dict = {"cf-aig-cache-ttl": str(_CF_TTL)}
    if _CF_TOK:
        h["cf-aig-authorization"] = f"Bearer {_CF_TOK}"
    if _USE_BYOK:
        h["cf-aig-byok-key"] = "true"
    return h


def _wrap_gateway(url: str) -> str:
    if not _CF_GW_ENABLED:
        return url
    if "generativelanguage.googleapis.com" in url:
        idx = url.find(".com/")
        if idx == -1:
            return url
        path = url[idx + len(".com/"):]
        return f"{_CF_GW_BASE}/google-ai-studio/{path}"
    if "aiplatform.googleapis.com" in url:
        idx = url.find(".com/")
        if idx == -1:
            return url
        path = url[idx + len(".com/"):]
        return f"{_CF_GW_BASE}/google-vertex-ai/{path}"
    return url


async def _auth_headers() -> dict:
    base: dict
    if _SA_CREDS is not None:
        from google.auth.transport.requests import Request as _GReq
        def _refresh():
            if not _SA_CREDS.valid:
                _SA_CREDS.refresh(_GReq())
            return _SA_CREDS.token
        token = await asyncio.get_event_loop().run_in_executor(None, _refresh)
        base = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    elif _API_KEY:
        base = {"Content-Type": "application/json", "x-goog-api-key": _API_KEY}
    else:
        # BYOK: empty upstream auth so CF injects its stored key.
        base = {"Content-Type": "application/json", "Authorization": ""}
    base.update(_gw_extra_headers())
    return base


def _gen_url(model: str) -> str:
    if _SA_CREDS is not None:
        url = f"{_VERTEX_BASE}/{model}:generateContent"
    else:
        url = f"{_BASE}/models/{model}:generateContent"
    return _wrap_gateway(url)


def _embed_url() -> str:
    if _SA_CREDS is not None:
        url = f"{_VERTEX_BASE}/{_EMBED_MODEL}:predict"
    else:
        url = f"{_BASE}/models/{_EMBED_MODEL}:embedContent"
    return _wrap_gateway(url)


def _alt_embed_url(model: str) -> str:
    return _wrap_gateway(f"{_BASE}/models/{model}:embedContent")


def _headers() -> dict:
    return {"Content-Type": "application/json", "x-goog-api-key": _API_KEY}


# ─────────────────────────────────────────────────────────────────────────────
# 1. TEXT EMBEDDINGS  — gemini-embedding-001 @ 1024 dims
# ─────────────────────────────────────────────────────────────────────────────


async def _post_embed_with_retry(
    url: str, body: dict, headers: dict, label: str,
) -> Optional[httpx.Response]:
    c = _get_embed_client()
    last_exc: Optional[BaseException] = None
    for attempt in range(1, _EMBED_RETRY_MAX_ATTEMPTS + 1):
        try:
            r = await c.post(url, json=body, headers=headers)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                if attempt == _EMBED_RETRY_MAX_ATTEMPTS:
                    return r
                wait_ms = _EMBED_RETRY_BASE_MS * (2 ** (attempt - 1))
                logger.info(
                    f"gemini embed ({label}) HTTP {r.status_code} "
                    f"attempt {attempt}/{_EMBED_RETRY_MAX_ATTEMPTS}; retrying in {wait_ms}ms"
                )
                await asyncio.sleep(wait_ms / 1000.0)
                continue
            return r
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_transient_embed_error(exc) or attempt == _EMBED_RETRY_MAX_ATTEMPTS:
                logger.warning(f"gemini embed ({label}) failed: {exc}")
                return None
            wait_ms = _EMBED_RETRY_BASE_MS * (2 ** (attempt - 1))
            logger.info(
                f"gemini embed ({label}) transient {type(exc).__name__} "
                f"attempt {attempt}/{_EMBED_RETRY_MAX_ATTEMPTS}; retrying in {wait_ms}ms"
            )
            await asyncio.sleep(wait_ms / 1000.0)
    if last_exc:
        logger.warning(f"gemini embed ({label}) exhausted retries: {last_exc}")
    return None


async def _embed_one(text: str, task_type: str) -> Optional[List[float]]:
    if not _ok() or not text:
        return None
    headers = await _auth_headers()

    async with _get_embed_semaphore():
        if _SA_CREDS is not None:
            url  = _embed_url()
            body = {
                "instances": [{"content": text[:8000], "task_type": task_type}],
                "parameters": {"outputDimensionality": _EMBED_DIMENSIONS},
            }
            r = await _post_embed_with_retry(url, body, headers, "Vertex")
            if r is None:
                return None
            if r.status_code == 403:
                _mark_forbidden()
                return None
            try:
                r.raise_for_status()
                return r.json()["predictions"][0]["embeddings"]["values"]
            except Exception as e:
                logger.warning(f"gemini embed (Vertex) parse failed: {e}")
                return None

        for model in (_EMBED_MODEL, "text-embedding-004"):
            url  = _alt_embed_url(model)
            body = {
                "model":   f"models/{model}",
                "content": {"parts": [{"text": text[:8000]}]},
                "taskType": task_type,
                "outputDimensionality": _EMBED_DIMENSIONS,
            }
            r = await _post_embed_with_retry(url, body, headers, model)
            if r is None:
                continue
            if r.status_code == 403:
                _mark_forbidden()
                return None
            if r.status_code == 404:
                continue
            try:
                r.raise_for_status()
                return r.json()["embedding"]["values"]
            except Exception as e:
                logger.warning(f"gemini embed ({model}) parse failed: {e}")
                continue
        return None


async def _workers_ai_fallback(text: str) -> Optional[List[float]]:
    """Workers AI safety net (Task #636). Only returns a vector when its
    dimension matches `_EMBED_DIMENSIONS` so the 1024-dim Vectorize
    index never receives a dimension-mismatched embedding. The current
    Workers AI default (bge-base-en-v1.5) emits 768-dim, so in the
    default deployment this path attempts the fallback (and surfaces
    failure metrics in providers.workers_ai) but returns None — which
    callers already handle. Set `WORKERS_AI_EMBED_MODEL` to a
    1024-compatible model on Cloudflare to actually use the fallback.
    """
    if not text:
        return None
    try:
        from providers import workers_ai as _wai
        if not _wai.is_enabled("embed"):
            return None
        class _VertexFailed(TimeoutError):
            pass
        ok, val, _ = await _wai.attempt_fallback(
            "embed", _VertexFailed("vertex_primary_failed"), 0,
            lambda: _wai.call_embed(text),
        )
        if not ok or not val:
            return None
        vec = val[0] if isinstance(val, list) and val and isinstance(val[0], list) else val
        if not vec:
            return None
        if len(vec) != _EMBED_DIMENSIONS:
            logger.warning(
                f"workers-ai fallback returned {len(vec)}-dim vector; "
                f"Vectorize index expects {_EMBED_DIMENSIONS}. Dropping to None "
                "to preserve dimension safety. Set WORKERS_AI_EMBED_MODEL to a "
                f"{_EMBED_DIMENSIONS}-dim model to enable the fallback."
            )
            return None
        return list(vec)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"workers-ai embed fallback failed: {type(e).__name__}: {str(e)[:150]}")
        return None


async def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
    """Return a 1024-dim Gemini embedding vector, or None on failure.

    Tries Gemini primary path first; if it fails, attempts the Workers
    AI fallback (Task #636 safety net). The fallback is dimension-gated
    — only vectors matching `_EMBED_DIMENSIONS` (1024) are returned so
    Vectorize syllabus-index-v2 never receives a dim-mismatched vector.
    Callers must handle None.
    """
    if not text:
        return None

    try:
        from cache import _embedding_cache, _embedding_cache_key
        _ek = _embedding_cache_key(text, task_type)
        cached = _embedding_cache.get(_ek)
        if cached:
            return cached
    except Exception:
        _ek = None
        _embedding_cache = None  # type: ignore[assignment]

    vec = await _embed_one(text, task_type)
    if vec is None:
        vec = await _workers_ai_fallback(text)

    try:
        if _ek and vec and _embedding_cache is not None:
            _embedding_cache[_ek] = vec
    except Exception:
        pass
    return vec


async def embed_batch(texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[Optional[List[float]]]:
    """Embed a batch. Returns one Optional[List[float]] per input."""
    if not texts:
        return []
    results = await asyncio.gather(*[embed_text(t, task_type) for t in texts])
    return list(results)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    return dot / (mag_a * mag_b + 1e-9)


async def semantic_search(query: str, candidates: List[Dict], text_key: str = "title",
                           top_k: int = 10) -> List[Dict]:
    if not _ok() or not candidates:
        return candidates[:top_k]

    q_vec = await embed_text(query, task_type="RETRIEVAL_QUERY")
    if not q_vec:
        return candidates[:top_k]

    texts = [c.get(text_key, "") for c in candidates]
    vecs  = await embed_batch(texts)

    scored = []
    for item, vec in zip(candidates, vecs):
        score = cosine_similarity(q_vec, vec) if vec else 0.0
        scored.append({**item, "score": round(score, 4)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# 2. TRANSLATION
# ─────────────────────────────────────────────────────────────────────────────

_LANG_NAMES = {
    "as": "Assamese", "hi": "Hindi", "bn": "Bengali",
    "en": "English",  "bho": "Bodo",
}


async def translate(text: str, target_lang: str = "as", source_lang: str = "en") -> Optional[str]:
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
    tasks = {f: translate(content.get(f, ""), target_lang) for f in fields if content.get(f)}
    results = await asyncio.gather(*tasks.values())
    out = dict(content)
    for key, result in zip(tasks.keys(), results):
        if result:
            out[f"{key}_{target_lang}"] = result
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. VISION ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────


async def analyze_image(image_bytes: bytes, mime_type: str = "image/jpeg",
                         prompt: str = "Describe this image in detail.",
                         max_output_tokens: int = 1024) -> Optional[str]:
    if not _ok():
        return None
    b64 = base64.b64encode(image_bytes).decode()
    url = _gen_url(_VISION_MODEL)
    headers = await _auth_headers()
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime_type, "data": b64}},
        ]}],
        "generationConfig": {"maxOutputTokens": max_output_tokens},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, json=body, headers=headers)
            if r.status_code == 403:
                _mark_forbidden()
                return None
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.warning(f"analyze_image failed: {e}")
        return None


async def analyze_thumbnail(image_bytes: bytes, subject: str = "", topic: str = "") -> dict:
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
# 3b. VISION OCR
# ─────────────────────────────────────────────────────────────────────────────


async def ocr_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    if not _ok():
        return {"error": "vertex_services not configured"}
    prompt = (
        "You are an OCR engine for AHSEC/SEBA educational content. "
        "Extract ALL visible text from this image exactly as written, preserving "
        "question numbers, sub-parts, mathematical notation, and formatting. "
        "Structure the output as:\n"
        "- Detected content type (question paper / textbook / notes)\n"
        "- Extracted text (verbatim)\n"
        "- Structured questions list (if applicable): [{number, text, marks, sub_parts:[]}]\n"
        "Return JSON: {content_type, raw_text, questions, word_count}"
    )
    raw = await analyze_image(image_bytes, mime_type=mime_type, prompt=prompt)
    if not raw:
        return {"error": "OCR failed"}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned)
    except Exception:
        return {"raw_text": raw, "content_type": "extracted", "questions": [], "word_count": len(raw.split())}


# ─────────────────────────────────────────────────────────────────────────────
# 3c. NLP KEY CONCEPTS
# ─────────────────────────────────────────────────────────────────────────────


async def extract_key_concepts(text: str, subject: str = "", class_name: str = "Class 11") -> dict:
    if not _ok():
        return {"error": "vertex_services not configured"}
    prompt = (
        f"You are an educational NLP engine for {subject} ({class_name}, AHSEC/SEBA board). "
        f"Analyse this chapter/passage and extract:\n"
        f"1. key_terms: top 10-15 important terms as [{{term, definition, importance: high/medium/low}}]\n"
        f"2. entities: named entities (laws, formulas, people, places, events) as [{{name, type, context}}]\n"
        f"3. difficulty_level: easy/medium/hard/advanced\n"
        f"4. chapter_summary: 2-3 sentence summary\n"
        f"5. exam_weightage: estimated marks weightage (low/medium/high)\n"
        f"6. prerequisite_topics: list of topics students need to know first\n\n"
        f"TEXT:\n{text[:4000]}\n\n"
        f"Return ONLY valid JSON."
    )
    raw = await _generate(prompt, max_tokens=2048, temperature=0.1)
    if not raw:
        return {"error": "NLP analysis failed"}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned)
    except Exception:
        return {"raw": raw}


# ─────────────────────────────────────────────────────────────────────────────
# 3d. FLASHCARD GENERATOR
# ─────────────────────────────────────────────────────────────────────────────


async def generate_flashcards(text: str, subject: str = "", count: int = 10,
                               class_name: str = "Class 11") -> dict:
    if not _ok():
        return {"error": "vertex_services not configured"}
    prompt = (
        f"Generate {count} high-quality revision flashcards for {subject} ({class_name}, AHSEC board).\n"
        f"Based on this content:\n{text[:4000]}\n\n"
        f"Mix card types:\n"
        f"- Definition cards (What is X?)\n"
        f"- Concept cards (Explain Y)\n"
        f"- Application cards (How does Z work?)\n"
        f"- Formula/fact cards\n"
        f"- True/False cards\n\n"
        f"For each card: {{id, front, back, type, difficulty: easy/medium/hard, tags: []}}\n"
        f"Return ONLY a JSON object: {{flashcards: [...], subject, total_cards}}"
    )
    raw = await _generate(prompt, max_tokens=3000, temperature=0.1)
    if not raw:
        return {"error": "Flashcard generation failed"}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned)
    except Exception:
        return {"raw": raw, "flashcards": [], "subject": subject}


# ─────────────────────────────────────────────────────────────────────────────
# 3e. MCQ GENERATOR
# ─────────────────────────────────────────────────────────────────────────────


async def generate_mcqs(text: str, subject: str = "", class_name: str = "Class 11",
                         count: int = 10, difficulty: str = "mixed") -> dict:
    if not _ok():
        return {"error": "vertex_services not configured"}
    prompt = (
        f"Generate {count} AHSEC-pattern MCQ questions for {subject} ({class_name}) with {difficulty} difficulty.\n"
        f"Based on content:\n{text[:4000]}\n\n"
        f"Each MCQ must have exactly 4 options (A, B, C, D).\n"
        f"Format: [{{id, question, options: {{A, B, C, D}}, correct_answer, explanation, difficulty, topic, marks: 1}}]\n"
        f"Make distractors plausible. Ensure correct_answer is one of A/B/C/D.\n"
        f"Return ONLY valid JSON: {{mcqs: [...], subject, total, difficulty}}"
    )
    raw = await _generate(prompt, max_tokens=3000, temperature=0.1)
    if not raw:
        return {"error": "MCQ generation failed"}
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned)
    except Exception:
        return {"raw": raw, "mcqs": [], "subject": subject}


# ─────────────────────────────────────────────────────────────────────────────
# 4. CONTENT ENHANCER
# ─────────────────────────────────────────────────────────────────────────────


async def enhance_content(content: str, page_type: str = "notes",
                           subject: str = "", topic: str = "",
                           class_name: str = "Class 11") -> Optional[str]:
    if not _ok() or not content:
        return None
    type_hints = {
        "notes":               "Make the notes clearer, add more examples, better structure with headers, and ensure exam relevance.",
        "mcqs":                "Improve MCQ distractors to be more plausible, ensure questions test understanding not just recall.",
        "definition":          "Make the definition precise, include etymology if helpful, and give a real-world analogy.",
        "important-questions": "Ensure questions cover all mark categories in ascending order (1-mark, 2-mark, 3-mark, 5-mark, 10-mark). Use AHSEC/SEBA/Degree exam-style language. Add model answer hints.",
        "examples":            "Add more relatable, Assam-context examples that AssamBoard students will recognize.",
    }
    prompt = (
        f"You are an expert {subject} teacher for AssamBoard ({class_name}) students in Assam, India.\n"
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
    if not _ok() or not content:
        return {"overall": 0, "error": "vertex_services not configured"}
    prompt = (
        f"Score this {page_type} content about '{topic}' ({subject}) for AssamBoard students.\n"
        f"Return a JSON with:\n"
        f"  accuracy (0-10), completeness (0-10), clarity (0-10),\n"
        f"  exam_relevance (0-10), overall (0-10),\n"
        f"  issues (list of strings), strengths (list of strings)\n"
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
    if not _ok():
        return {}
    prompt = (
        f"Generate SEO metadata for an educational page about:\n"
        f"  Topic: {topic}\n  Subject: {subject}\n  Class: {class_name}\n"
        f"  Page type: {page_type}\n  Board: {board}\n"
        f"{'Content preview: ' + content_preview[:500] if content_preview else ''}\n\n"
        f"Return JSON with:\n"
        f"  title (max 60 chars), meta_description (max 160 chars),\n"
        f"  keywords (list of 8-12 strings), og_title, og_description,\n"
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
    if not _ok():
        return []
    prompt = (
        f"Analyse these search queries from students and identify content gaps.\n\n"
        f"Top student search queries:\n{chr(10).join(f'- {q}' for q in top_searches[:20])}\n\n"
        f"Subjects covered: {', '.join(subjects[:10])}\n"
        f"Published pages count: {len(published_slugs)}\n\n"
        f"Return a JSON array of top 10 gaps with:\n"
        f"  query, gap_type (missing_topic/incomplete_coverage/wrong_level),\n"
        f"  priority (high/medium), suggested_action,\n"
        f"  estimated_monthly_searches\n"
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
# 9. LONG DOCUMENT READER
# ─────────────────────────────────────────────────────────────────────────────


async def extract_from_document(pdf_bytes: bytes, task: str = "extract_mcqs") -> dict:
    if not _ok():
        return {"error": "vertex_services not configured"}

    b64 = base64.b64encode(pdf_bytes).decode()
    task_prompts = {
        "extract_mcqs":      "Extract all MCQ questions with their options and correct answers. Return a JSON array of {question, options, correct_answer, topic}.",
        "extract_topics":    "List all chapter topics and subtopics covered. Return a JSON array of {chapter, topics: []}.",
        "summarise":         "Summarise each chapter in 3-5 bullet points. Return a JSON array of {chapter, summary_points: []}.",
        "extract_questions": "Extract all exam-style questions (short answer, long answer, numericals). Return a JSON array of {question, type, marks, topic}.",
    }

    prompt = task_prompts.get(task, task_prompts["summarise"])
    url = _gen_url(_PRO_MODEL)
    headers = await _auth_headers()
    body = {
        "contents": [{"parts": [
            {"text": prompt + "\n\nReturn ONLY valid JSON."},
            {"inline_data": {"mime_type": "application/pdf", "data": b64}},
        ]}],
        "generationConfig": {"maxOutputTokens": 8192},
    }
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(url, json=body, headers=headers)
            if r.status_code == 403:
                _mark_forbidden()
                return {"error": "Gemini upstream returned 403 — check credentials"}
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
                    max_tokens: int = 2048, temperature: float = 0.1) -> Optional[str]:
    if not _ok():
        return None
    url = _gen_url(model)
    headers = await _auth_headers()
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(url, json=body, headers=headers)
            if r.status_code == 403:
                _mark_forbidden()
                return None
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.warning(f"vertex _generate failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# STATUS CHECK
# ─────────────────────────────────────────────────────────────────────────────


async def health_check() -> dict:
    if not _ok():
        return {
            "ok": False,
            "auth_mode": _AUTH_MODE,
            "reason": "No credential available (set VERTEX_SERVICE_ACCOUNT, GEMINI_API_KEY, or CF AI Gateway BYOK).",
        }
    test = await embed_text("test", task_type="SEMANTIC_SIMILARITY")
    gen_test = await _generate("Reply with just the word: OK", max_tokens=5)
    embed_ok = test is not None and len(test) == _EMBED_DIMENSIONS
    gen_ok = gen_test is not None and "OK" in (gen_test or "")
    # `ok` reflects actual probe success (not just credential presence)
    # so health dashboards can't show green when calls are silently
    # failing upstream.
    return {
        "ok": embed_ok and gen_ok,
        "auth_mode": _AUTH_MODE,
        "via_cf_gateway": _CF_GW_ENABLED,
        "byok": _USE_BYOK,
        "project": _VERTEX_PROJECT or None,
        "location": _VERTEX_LOCATION,
        "embeddings": embed_ok,
        "embed_dimensions": len(test) if test else 0,
        "generation": gen_ok,
        "models": {
            "generation": _GEN_MODEL,
            "embedding":  _EMBED_MODEL,
            "vision":     _VISION_MODEL,
            "long_doc":   _PRO_MODEL,
        },
    }
