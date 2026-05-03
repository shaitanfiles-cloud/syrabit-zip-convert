"""
providers.baseten — Baseten LLM inference via Cloudflare AI Gateway (BYOK).

All requests route through the CF AI Gateway at:
  {gateway_base}/baseten/v1/chat/completions

Baseten exposes an OpenAI-compatible ``/chat/completions`` endpoint, so this
module uses the same ``openai.AsyncOpenAI`` client pattern used by other
providers. The "model" field in the request body is the Baseten deployment ID
(shown in the Baseten dashboard as a short alphanumeric slug, e.g. "xyz123abc").

BYOK mode: when CF_GATEWAY_ENABLED is true, the local BASETEN_API_KEY is
optional — register it in the Cloudflare AI Gateway dashboard under the
"Baseten" provider and the backend sends a placeholder so CF injects the key.
BASETEN_MODEL_ID must always be set explicitly (CF cannot derive it).

Configuration:
  BASETEN_API_KEY       — Baseten API key (optional when CF BYOK is configured)
  BASETEN_MODEL_ID      — Baseten deployment ID, e.g. "xyz123abc" (required)
  BASETEN_MAX_TOKENS    — default max_tokens for chat completions (default: 1024)
  BASETEN_TEMPERATURE   — default temperature (default: 0.3 for EdTech accuracy)
  BASETEN_TIMEOUT_S     — HTTP timeout in seconds (default: 60)

Usage:
  from providers import baseten
  if baseten.ENABLED:
      reply = await baseten.chat([{"role": "user", "content": "Explain photosynthesis"}])
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import openai as _oai

from config import (
    _BASETEN_KEY,
    BASETEN_MODEL_ID,
    CF_GATEWAY_ENABLED,
    CF_CACHE_TTL,
    CF_AI_GATEWAY_TOKEN,
    is_cf_gateway_up,
    get_provider_base_url,
    byok_headers,
    BYOK_PLACEHOLDER,
)

logger = logging.getLogger("providers.baseten")

_API_KEY       = _BASETEN_KEY
_MODEL_ID      = BASETEN_MODEL_ID
_MAX_TOKENS    = int(os.environ.get("BASETEN_MAX_TOKENS", "1024") or "1024")
_TEMPERATURE   = float(os.environ.get("BASETEN_TEMPERATURE", "0.3") or "0.3")
_TIMEOUT       = float(os.environ.get("BASETEN_TIMEOUT_S", "60") or "60")

ENABLED: bool = bool(_API_KEY and _MODEL_ID)

_using_byok = CF_GATEWAY_ENABLED and _API_KEY == BYOK_PLACEHOLDER

if ENABLED:
    logger.info(
        "Baseten ready — model=%s byok=%s max_tokens=%d",
        _MODEL_ID, _using_byok, _MAX_TOKENS,
    )
elif _API_KEY and not _MODEL_ID:
    logger.warning(
        "Baseten key is set but BASETEN_MODEL_ID is missing — provider disabled. "
        "Set BASETEN_MODEL_ID to your deployment ID from the Baseten dashboard."
    )
else:
    logger.info(
        "Baseten disabled (BASETEN_API_KEY / BASETEN_MODEL_ID not set)"
    )


def _base_url() -> str:
    url = get_provider_base_url("baseten")
    return url or "https://api.baseten.co/v1"


def _get_client() -> _oai.AsyncOpenAI:
    via_gateway = bool(is_cf_gateway_up())
    base = _base_url()
    extra_headers: dict = {}
    if via_gateway:
        bh = byok_headers(include_ttl=True, clear_upstream_auth=True)
        extra_headers.update(bh)
    return _oai.AsyncOpenAI(
        api_key=_API_KEY,
        base_url=base,
        default_headers=extra_headers,
        timeout=_oai.Timeout(_TIMEOUT, connect=10.0),
        max_retries=1,
    )


async def chat(
    messages: List[Dict[str, str]],
    *,
    model_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    stream: bool = False,
    extra_body: Optional[Dict[str, Any]] = None,
) -> str:
    """Send a chat completion request to the Baseten deployed model.

    Args:
        messages:     OpenAI-format messages list.
        model_id:     Baseten deployment ID. Defaults to BASETEN_MODEL_ID.
        max_tokens:   Override max output tokens.
        temperature:  Override sampling temperature.
        stream:       Not yet supported — always False.
        extra_body:   Extra fields forwarded to the API body (e.g. top_p).

    Returns:
        The assistant message content as a string.

    Raises:
        RuntimeError if not enabled.
        openai.APIError on API failures.
    """
    if not ENABLED:
        raise RuntimeError(
            "Baseten provider is not enabled. "
            "Set BASETEN_API_KEY and BASETEN_MODEL_ID environment variables."
        )

    mdl = model_id or _MODEL_ID
    t0 = time.perf_counter()
    try:
        client = _get_client()
        kwargs: Dict[str, Any] = {
            "model": mdl,
            "messages": messages,
            "max_tokens": max_tokens or _MAX_TOKENS,
            "temperature": temperature if temperature is not None else _TEMPERATURE,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body

        response = await client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        latency = round((time.perf_counter() - t0) * 1000)
        logger.info(
            "Baseten chat: model=%s tokens_in=%s tokens_out=%s %dms",
            mdl,
            getattr(response.usage, "prompt_tokens", "?"),
            getattr(response.usage, "completion_tokens", "?"),
            latency,
        )
        return text
    except _oai.APIError as exc:
        logger.error("Baseten API error: %s", exc)
        raise
    except Exception as exc:
        logger.error("Baseten chat failed: %s", exc)
        raise


async def health_check() -> dict:
    if not ENABLED:
        if _API_KEY and not _MODEL_ID:
            return {"ok": False, "reason": "BASETEN_MODEL_ID not set"}
        return {"ok": False, "reason": "BASETEN_API_KEY / BASETEN_MODEL_ID not set"}
    t0 = time.perf_counter()
    try:
        reply = await chat(
            [{"role": "user", "content": "Reply with only the word: ok"}],
            max_tokens=10,
            temperature=0.0,
        )
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "model": _MODEL_ID,
            "byok": _using_byok,
            "reply_preview": reply[:50],
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
