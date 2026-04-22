"""
Vertex AI / Gemini-powered services for Syrabit.ai (Task #663 — restored).

Restored from commit cedd1e06^ on 2026-04-22 after the disabled stub
(2026-04-19) left every Gemini-backed feature returning HTTP 502 in
production. The user has now provisioned Gemini/Vertex credentials at
the Cloudflare AI Gateway layer, so this module additionally routes
its requests through the gateway when one is configured.

Three auth modes, detected at import time in priority order:
  A) Vertex AI service-account JSON (VERTEX_SERVICE_ACCOUNT or
     GEMINI_API_KEY containing a JSON blob) → OAuth bearer +
     {region}-aiplatform.googleapis.com endpoints.
  B) Google AI Studio API key (GEMINI_API_KEY=AIza…) → x-goog-api-key
     + generativelanguage.googleapis.com endpoints.
  C) BYOK via Cloudflare AI Gateway (no local credential at all but
     CF_AI_GATEWAY_ACCOUNT_ID + CF_AI_GATEWAY_ID set, with a BYOK
     binding configured for google-ai-studio in the dashboard).

When CF_AI_GATEWAY_ACCOUNT_ID + CF_AI_GATEWAY_ID are configured, all
calls (regardless of which auth mode is active) are routed through
  https://gateway.ai.cloudflare.com/v1/{ACCT}/{GW}/google-ai-studio/...
or
  https://gateway.ai.cloudflare.com/v1/{ACCT}/{GW}/google-vertex-ai/...
so we get the gateway's logging / caching / spend-control / BYOK
substitution.

Embeddings continue to fall back to Cloudflare Workers AI when the
primary path errors transiently — same safety net as Task #636. We
prefer real Gemini embeddings (1024-dim gemini-embedding-001 to match
syllabus-index-v2) but a transient outage degrades to 768-dim
bge-base-en-v1.5 rather than crashing the seed loop.

Services exposed:
  1.  Text Embeddings    — semantic search across topics & pages
  2.  Translation        — Assamese + other regional language translation
  3.  Vision Analysis    — image / PDF page analysis via Gemini Vision
  3b. Vision OCR         — clean text extraction from question papers
  3c. NLP Key Concepts   — entity / definition / difficulty extraction
  3d. Flashcard Generator
  3e. MCQ Generator
  4.  Content Enhancer   — improve auto-generated notes / MCQs
  5.  Quality Scorer     — score content before publishing
  6.  Topic Suggester    — fill syllabus gaps with AI suggestions
  7.  SEO Meta Generator
  8.  Content Gap Finder
  9.  Long Doc Reader    — Gemini 1.5 Pro for textbook PDFs
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
# Read directly from env (not from config.py) so this module never imports
# the rest of the FastAPI bootstrap surface — keeps it usable from offline
# scripts like scripts/ingest_vertex_index.py.
_CF_ACCT = os.environ.get("CF_AI_GATEWAY_ACCOUNT_ID", "").strip()
_CF_GW   = os.environ.get("CF_AI_GATEWAY_ID", "").strip()
_CF_TOK  = os.environ.get("CF_AI_GATEWAY_TOKEN", "").strip()
_CF_TTL  = int(os.environ.get("CF_AI_GATEWAY_CACHE_TTL", "3600"))
_CF_GW_BASE = (
    f"https://gateway.ai.cloudflare.com/v1/{_CF_ACCT}/{_CF_GW}"
    if (_CF_ACCT and _CF_GW) else ""
)
_CF_GW_ENABLED = bool(_CF_GW_BASE)

# Whether the CF AI Gateway has a BYOK binding for google-ai-studio /
# google-vertex-ai. When true and we have no local credential, we still
# attempt requests — CF will inject its stored key. Default ON when the
# gateway is enabled and the user hasn't explicitly disabled BYOK.
_CF_GW_BYOK = (
    _CF_GW_ENABLED
    and os.environ.get("CF_AI_GATEWAY_BYOK", "1").strip().lower() not in ("0", "false", "no", "off")
)


# ── HTTP client (embed path) ────────────────────────────────────────────────
_embed_http_client: Optional[httpx.AsyncClient] = None

# Bounded concurrency for the embed path (Task #545). See original module
# header for why this matters — short version: prevents httpx pool semaphore
# from desynchronising under wait_for-driven cancellation pressure.
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
_EMBED_MODEL  = "gemini-embedding-001"
_GEN_MODEL    = "gemini-2.5-flash"
_PRO_MODEL    = "gemini-2.5-flash"
_VISION_MODEL = "gemini-2.5-flash"
_EMBED_DIMENSIONS = 1024


# ── Auth detection ──────────────────────────────────────────────────────────
_KEY_RAW = (
    os.getenv("VERTEX_SERVICE_ACCOUNT", "").strip()
    or os.getenv("GEMINI_API_KEY", "").strip()
)

# Mode A: Vertex AI service account
_SA_CREDS         = None
_VERTEX_PROJECT   = os.environ.get("VERTEX_PROJECT_ID", "").strip()
_VERTEX_LOCATION  = os.environ.get("VERTEX_LOCATION", "us-central1").strip() or "us-central1"
_VERTEX_BASE      = ""

# Mode B: simple API key
_API_KEY: str = ""

# Mode C: BYOK (no local creds, CF Gateway injects)
_USE_BYOK: bool = False

# Direct (non-gateway) endpoints
_BASE    = "https://generativelanguage.googleapis.com/v1beta"
_BASE_V1 = "https://generativelanguage.googleapis.com/v1"

GEMINI_KEY = _KEY_RAW  # legacy export for any external readers

if _KEY_RAW.startswith("{"):
    try:
        from google.oauth2 import service_account as _sa_mod
        _sa_info = json.loads(_KEY_RAW)
        # An explicit VERTEX_PROJECT_ID env var overrides the project_id in
        # the SA blob — handy when one SA is shared across projects.
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
        logger.error(f"vertex_services: Failed to parse service-account JSON — {_sa_err}")
        _SA_CREDS = None
elif _KEY_RAW:
    _API_KEY = _KEY_RAW
elif _CF_GW_BYOK:
    # No local credential, but the gateway can inject one. We still need
    # a project / location for the Vertex URL path if the BYOK is
    # configured against google-vertex-ai. Default to AI-Studio mode
    # (which doesn't need a project id) when none is provided.
    _USE_BYOK = True

_GEMINI_FORBIDDEN = False  # set on permanent 403 from upstream


# ── Startup banner ──────────────────────────────────────────────────────────
def _auth_mode_label() -> str:
    if _SA_CREDS is not None:
        return "vertex_ai_service_account"
    if _API_KEY:
        return "google_ai_studio_api_key"
    if _USE_BYOK:
        return "cf_ai_gateway_byok"
    return "disabled"


_AUTH_MODE = _auth_mode_label()

if _AUTH_MODE == "disabled":
    # Loud at WARN — unlike the old stub which logged INFO and silently
    # broke every dependent feature. Operators searching for "vertex" in
    # production logs will now see this immediately.
    logger.warning(
        "vertex_services: NO credentials available (set VERTEX_SERVICE_ACCOUNT or "
        "GEMINI_API_KEY, or configure CF_AI_GATEWAY_ACCOUNT_ID + CF_AI_GATEWAY_ID "
        "with a BYOK binding) — every Gemini-backed feature will return None / 503"
    )
else:
    _gw_note = ""
    if _CF_GW_ENABLED:
        _gw_note = (
            f" [routing via Cloudflare AI Gateway "
            f"acct={_CF_ACCT[:6]}…/{_CF_GW}, byok={'yes' if _USE_BYOK or _CF_GW_BYOK else 'no'}]"
        )
    logger.info(
        f"vertex_services: ready — auth_mode={_AUTH_MODE} "
        f"embed_model={_EMBED_MODEL} gen_model={_GEN_MODEL} "
        f"project={_VERTEX_PROJECT or 'n/a'}{_gw_note}"
    )


def _ok() -> bool:
    """True when this module can attempt a real call.

    BYOK mode is "OK" because CF will inject the credential downstream;
    we don't need a local key to make the request fly.
    """
    if _GEMINI_FORBIDDEN:
        return False
    return bool(_API_KEY) or _SA_CREDS is not None or _USE_BYOK


def _mark_forbidden() -> None:
    global _GEMINI_FORBIDDEN
    if not _GEMINI_FORBIDDEN:
        _GEMINI_FORBIDDEN = True
        logger.error(
            "Gemini upstream returned 403 Forbidden — credential is invalid or the "
            "model is not accessible. Disabling Gemini calls for this session. "
            "Check VERTEX_SERVICE_ACCOUNT / GEMINI_API_KEY or the CF AI Gateway "
            "BYOK binding."
        )


# ── URL + headers (gateway-aware) ───────────────────────────────────────────
def _gw_extra_headers() -> dict:
    """Headers the gateway needs (auth + caching + BYOK opt-in).

    Returns {} when the gateway isn't configured so callers can
    unconditionally splat the result into their headers dict.
    """
    if not _CF_GW_ENABLED:
        return {}
    h: dict = {"cf-aig-cache-ttl": str(_CF_TTL)}
    if _CF_TOK:
        # Authenticated Gateway bearer (separate from the upstream
        # provider auth, which lives in Authorization / x-goog-api-key).
        h["cf-aig-authorization"] = f"Bearer {_CF_TOK}"
    if _USE_BYOK:
        # Tell CF to substitute its stored credential for this provider.
        # We MUST send empty Authorization (not "Bearer x") for BYOK to
        # fire — verified live against gateway `syrabit` 2026-04-20.
        h["cf-aig-byok-key"] = "true"
    return h


def _wrap_gateway(url: str) -> str:
    """Rewrite a direct Google endpoint URL to go through the CF AI Gateway.

    Maps:
      https://generativelanguage.googleapis.com/v1beta/<rest>
        → {gw}/google-ai-studio/v1beta/<rest>
      https://{region}-aiplatform.googleapis.com/v1/<rest>
        → {gw}/google-vertex-ai/v1/<rest>

    When the gateway isn't enabled, returns the URL unchanged.
    """
    if not _CF_GW_ENABLED:
        return url
    if "generativelanguage.googleapis.com" in url:
        # Path component after the host
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
    """Upstream provider auth + gateway headers, merged."""
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
        # BYOK mode — empty upstream auth so CF injects its stored key.
        base = {"Content-Type": "application/json", "Authorization": ""}
    base.update(_gw_extra_headers())
    return base


def _gen_url(model: str) -> str:
    """Resolve the generateContent URL for the active auth mode."""
    if _SA_CREDS is not None:
        url = f"{_VERTEX_BASE}/{model}:generateContent"
    else:
        url = f"{_BASE}/models/{model}:generateContent"
    return _wrap_gateway(url)


def _embed_url() -> str:
    """Resolve the Gemini embedding URL for the active auth mode."""
    if _SA_CREDS is not None:
        url = f"{_VERTEX_BASE}/{_EMBED_MODEL}:predict"
    else:
        url = f"{_BASE}/models/{_EMBED_MODEL}:embedContent"
    return _wrap_gateway(url)


def _alt_embed_url(model: str) -> str:
    """Fallback embed URL builder for the API-key model walk."""
    return _wrap_gateway(f"{_BASE}/models/{model}:embedContent")


def _headers() -> dict:
    """Sync header helper kept for any legacy API-key callsites."""
    return {"Content-Type": "application/json", "x-goog-api-key": _API_KEY}


# ─────────────────────────────────────────────────────────────────────────────
# 1. TEXT EMBEDDINGS  — gemini-embedding-001 @ 1024 dims, with Workers AI fallback
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


async def _embed_one_primary(text: str, task_type: str) -> Optional[List[float]]:
    """Primary Gemini embedding path (no fallback)."""
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

        # API-key OR BYOK mode — same endpoint shape, walk a list of
        # model names so a 404 on the new id falls back to the old one.
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


async def _embed_with_workers_ai_fallback(text: str) -> Optional[List[float]]:
    """Workers AI safety-net invoked only when the primary Gemini path
    has already returned None. Mirrors the policy from the previous
    stub so chunk-indexing keeps moving during Vertex outages.

    Note dimensionality difference: Workers AI bge-base-en-v1.5 emits
    768-dim vectors, while Vectorize syllabus-index-v2 expects 1024.
    Callers that mix both must dimension-check before upserting; the
    syllabus_embedder already does so via `_current_embed_model`.
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
        if ok and val:
            vec = val[0] if isinstance(val, list) and val and isinstance(val[0], list) else val
            return list(vec) if vec else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[workers-ai] embed fallback failed: {type(e).__name__}: {str(e)[:150]}")
    return None


async def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
    """Return an embedding vector or None on failure.

    Tries Gemini primary path first (preserving the historical 1024-dim
    contract); falls through to Workers AI on transient failure when
    the per-capability kill-switch is enabled.
    """
    if not text:
        return None

    # Local LRU cache (process-resident; safe across modes)
    try:
        from cache import _embedding_cache, _embedding_cache_key
        _ek = _embedding_cache_key(text, task_type)
        cached = _embedding_cache.get(_ek)
        if cached:
            return cached
    except Exception:
        _ek = None
        _embedding_cache = None  # type: ignore[assignment]

    vec = await _embed_one_primary(text, task_type)
    if vec is None:
        vec = await _embed_with_workers_ai_fallback(text)

    try:
        if _ek and vec and _embedding_cache is not None:
            _embedding_cache[_ek] = vec
    except Exception:
        pass
    return vec


async def embed_batch(texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[Optional[List[float]]]:
    """Embed a batch of texts. Returns one Optional[List[float]] per input
    (preserves input ordering — None marks an item that couldn't be
    embedded so callers can skip it without realigning).
    """
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
    """Rank `candidates` by cosine similarity to `query`. Each candidate
    must carry `text_key`. Returns the top-k items with a `score` field.
    """
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
# 3. VISION ANALYSIS  (Gemini Vision)
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
# 3b. VISION OCR  (replaces Cloud Vision)
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
        return {"error": "OCR failed — Gemini returned no content"}
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
            "reason": (
                "No credential available. Set VERTEX_SERVICE_ACCOUNT or GEMINI_API_KEY, "
                "or configure CF_AI_GATEWAY_ACCOUNT_ID + CF_AI_GATEWAY_ID with a BYOK binding."
            ),
        }
    test = await embed_text("test", task_type="SEMANTIC_SIMILARITY")
    gen_test = await _generate("Reply with just the word: OK", max_tokens=5)
    return {
        "ok": True,
        "auth_mode": _AUTH_MODE,
        "via_cf_gateway": _CF_GW_ENABLED,
        "byok": _USE_BYOK,
        "project": _VERTEX_PROJECT or None,
        "location": _VERTEX_LOCATION,
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
            "vision_analysis", "vision_ocr", "nlp_key_concepts",
            "flashcards", "mcqs", "content_enhancer", "quality_scorer",
            "topic_suggester", "seo_meta_generator", "content_gap_finder",
            "long_doc_reader",
        ],
    }
