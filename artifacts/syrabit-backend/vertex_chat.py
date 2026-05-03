"""
vertex_chat — Workers AI streaming chat client.

Previously called Vertex AI / Gemini directly. Now delegates all
streaming to providers/cloudflare_ai.py (Workers AI via CF AI Gateway)
so the entire LLM stack runs on a single provider with no external API
keys needed.

The public interface (is_configured, is_available, stream_chat,
breaker_snapshot, force_breaker_close) is unchanged so llm.py and
routes/edu_study.py keep working without modification.
"""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator, List, Dict, Optional

from vertex_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

_ACCOUNT_ID = os.environ.get("CF_AI_GATEWAY_ACCOUNT_ID", "").strip()
_API_TOKEN   = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
_CF_ENABLED  = bool(_ACCOUNT_ID and _API_TOKEN)

_DEFAULT_MODEL = os.environ.get(
    "VERTEX_GEMINI_MODEL",
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
).strip() or "@cf/meta/llama-3.3-70b-instruct-fp8-fast"

_CHAT_BREAKER_THRESHOLD = max(1, int(os.environ.get("VERTEX_CHAT_BREAKER_THRESHOLD", "3")))
_CHAT_BREAKER_COOLDOWN_S = max(1.0, float(os.environ.get("VERTEX_CHAT_BREAKER_COOLDOWN_S", "180")))

_breaker = CircuitBreaker(
    name="vertex_chat",
    failure_threshold=_CHAT_BREAKER_THRESHOLD,
    cooldown_s=_CHAT_BREAKER_COOLDOWN_S,
)


def auth_mode() -> str:
    return "workers_ai" if _CF_ENABLED else "unconfigured"


def is_configured() -> bool:
    return _CF_ENABLED


def is_available() -> bool:
    return is_configured() and _breaker.allow()


def breaker_snapshot() -> dict:
    return _breaker.snapshot()


def force_breaker_close() -> None:
    _breaker.force_close()


async def stream_chat(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
    timeout_s: float = 60.0,
) -> AsyncIterator[str]:
    """Stream text deltas from Workers AI (Cloudflare).

    Yields raw text chunks. Raises RuntimeError / httpx exceptions on
    failure so callers can fall back to the SLM pool.
    """
    if not _CF_ENABLED:
        raise RuntimeError(
            "Workers AI not configured: set CF_AI_GATEWAY_ACCOUNT_ID and CLOUDFLARE_API_TOKEN"
        )

    from providers import cloudflare_ai as _cf

    use_model = (model or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    if not use_model.startswith("@cf/"):
        use_model = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"

    # chat_stream's model_key falls back to the raw value when the key is not
    # in the MODELS dict — passing the full model path directly works fine.
    success_recorded = False
    try:
        async for chunk in _cf.chat_stream(
            messages,
            model_key=use_model,
            max_tokens=max_tokens,
        ):
            if not success_recorded:
                _breaker.record_success()
                success_recorded = True
            yield chunk
    except Exception as e:
        if not success_recorded:
            _breaker.record_failure(f"{type(e).__name__}")
        raise
