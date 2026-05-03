"""
providers.cartesia — Cartesia Voice AI (TTS) via Cloudflare AI Gateway (BYOK).

All requests route through the CF AI Gateway at:
  {gateway_base}/cartesia/v1/tts/bytes

BYOK mode: when CF_GATEWAY_ENABLED is true, the local CARTESIA_API_KEY is
optional — register it in the Cloudflare AI Gateway dashboard under the
"Cartesia" provider and the backend sends a placeholder with cf-aig-byok-key.

Cartesia auth uses X-API-Key (not Authorization: Bearer). BYOK for Cartesia
means sending an empty X-API-Key so CF injects its stored key. The
byok_headers() helper clears Authorization; we handle X-API-Key separately.

Key models:
  sonic-2          — Cartesia's latest, lowest latency (default)
  sonic-2-2025-03  — pinned version for reproducibility

Output formats:
  mp3 / 44100 Hz (default)  — best for web/mobile playback
  pcm / 24000 Hz            — raw PCM for real-time streaming pipelines

Configuration:
  CARTESIA_API_KEY    — Cartesia API key (optional when CF BYOK is configured)
  CARTESIA_MODEL_ID   — TTS model (default: sonic-2)
  CARTESIA_VOICE_ID   — default voice UUID from Cartesia Voice Library
  CARTESIA_TIMEOUT_S  — HTTP timeout in seconds (default: 30)

Finding voice IDs: https://play.cartesia.ai/voices (or GET /v1/voices)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from config import (
    _CARTESIA_KEY,
    CARTESIA_MODEL_ID,
    CARTESIA_DEFAULT_VOICE_ID,
    CF_GATEWAY_ENABLED,
    CF_CACHE_TTL,
    CF_AI_GATEWAY_TOKEN,
    is_cf_gateway_up,
    get_provider_base_url,
    BYOK_PLACEHOLDER,
)

logger = logging.getLogger("providers.cartesia")

_API_KEY          = _CARTESIA_KEY
_MODEL_ID         = CARTESIA_MODEL_ID
_DEFAULT_VOICE_ID = CARTESIA_DEFAULT_VOICE_ID
_TIMEOUT          = float(30)

ENABLED: bool = bool(_API_KEY)

_using_byok = CF_GATEWAY_ENABLED and _API_KEY == BYOK_PLACEHOLDER

CARTESIA_API_VERSION = "2024-06-10"

if ENABLED:
    logger.info(
        "Cartesia TTS ready — model=%s default_voice=%s byok=%s",
        _MODEL_ID,
        _DEFAULT_VOICE_ID or "(not set — voice_id required per call)",
        _using_byok,
    )
else:
    logger.info(
        "Cartesia TTS disabled (CARTESIA_API_KEY not set and CF gateway BYOK not active)"
    )


def _base_url() -> str:
    url = get_provider_base_url("cartesia")
    return url or "https://api.cartesia.ai/v1"


def _request_headers(*, via_gateway: bool) -> dict:
    """Build request headers for Cartesia.

    Cartesia uses ``X-API-Key`` (not ``Authorization: Bearer``).
    In BYOK mode we send an empty ``X-API-Key`` so CF AI Gateway injects
    the stored key; we explicitly do NOT clear ``Authorization`` because
    Cartesia doesn't use it (clearing it would be a no-op, but keeping
    intent clear matters).
    """
    h: dict = {
        "Content-Type": "application/json",
        "Cartesia-Version": CARTESIA_API_VERSION,
    }
    if via_gateway:
        h["X-API-Key"] = ""
        h["cf-aig-byok-key"] = "true"
        h["cf-aig-cache-ttl"] = str(CF_CACHE_TTL)
        if CF_AI_GATEWAY_TOKEN:
            h["cf-aig-authorization"] = f"Bearer {CF_AI_GATEWAY_TOKEN}"
    else:
        h["X-API-Key"] = _API_KEY
    return h


_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(_TIMEOUT),
            http2=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


async def close() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def synthesize(
    text: str,
    *,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    language: str = "en",
    output_format: Optional[dict] = None,
) -> bytes:
    """Convert ``text`` to speech and return raw audio bytes (mp3).

    Args:
        text:          Text to synthesize (keep under ~1000 chars for low latency).
        voice_id:      Cartesia voice UUID. Falls back to CARTESIA_VOICE_ID env var.
        model_id:      Cartesia model. Defaults to CARTESIA_MODEL_ID (sonic-2).
        language:      BCP-47 language code (default: "en").
                       Cartesia supports: en, fr, de, es, pt, zh, ja, hi, it, ko, nl, pl, ru, sv, tr.
        output_format: Dict with container/encoding/sample_rate.
                       Default: {"container": "mp3", "encoding": "mp3", "sample_rate": 44100}

    Returns:
        Raw audio bytes (mp3 by default) — raise on error.
    """
    if not ENABLED:
        raise RuntimeError("Cartesia TTS is not enabled (CARTESIA_API_KEY not set)")

    vid = voice_id or _DEFAULT_VOICE_ID
    if not vid:
        raise ValueError(
            "voice_id is required — set CARTESIA_VOICE_ID env var or pass voice_id per call. "
            "Browse voices at https://play.cartesia.ai/voices"
        )

    mdl = model_id or _MODEL_ID
    fmt = output_format or {
        "container": "mp3",
        "encoding": "mp3",
        "sample_rate": 44100,
    }

    via_gateway = bool(is_cf_gateway_up())
    base = _base_url()

    payload = {
        "model_id": mdl,
        "transcript": text,
        "voice": {"mode": "id", "id": vid},
        "output_format": fmt,
        "language": language,
    }

    t0 = time.perf_counter()
    try:
        client = _get_client()
        response = await client.post(
            f"{base}/tts/bytes",
            headers=_request_headers(via_gateway=via_gateway),
            json=payload,
        )
        response.raise_for_status()
        audio = response.content
        latency = round((time.perf_counter() - t0) * 1000)
        logger.info(
            "Cartesia TTS: %d chars → %d bytes, model=%s voice=%s lang=%s %dms",
            len(text), len(audio), mdl, vid, language, latency,
        )
        return audio
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Cartesia TTS HTTP %d: %s", exc.response.status_code, exc.response.text[:300]
        )
        raise
    except Exception as exc:
        logger.error("Cartesia TTS failed: %s", exc)
        raise


async def list_voices() -> list:
    """Return all available voices from Cartesia.

    Useful for letting admins browse and set the default voice ID.
    Returns [] on error.
    """
    if not ENABLED:
        return []
    via_gateway = bool(is_cf_gateway_up())
    base = _base_url()
    try:
        client = _get_client()
        response = await client.get(
            f"{base}/voices",
            headers=_request_headers(via_gateway=via_gateway),
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("Cartesia list_voices failed: %s", exc)
        return []


async def health_check() -> dict:
    if not ENABLED:
        return {"ok": False, "reason": "CARTESIA_API_KEY not set"}
    if not _DEFAULT_VOICE_ID:
        return {
            "ok": True,
            "ready": False,
            "reason": "CARTESIA_VOICE_ID not set — voice_id required per /api/voice/tts call",
            "model": _MODEL_ID,
            "byok": _using_byok,
        }
    t0 = time.perf_counter()
    try:
        audio = await synthesize("Hello", voice_id=_DEFAULT_VOICE_ID)
        return {
            "ok": True,
            "ready": True,
            "latency_ms": round((time.perf_counter() - t0) * 1000),
            "bytes": len(audio),
            "model": _MODEL_ID,
            "byok": _using_byok,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}
