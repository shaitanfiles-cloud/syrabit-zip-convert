"""
routes.voice — Voice/TTS API endpoints.

POST /api/voice/tts
  Converts text to speech using Cartesia, routed through CF AI Gateway.
  Returns audio/mpeg bytes (mp3).

GET  /api/voice/voices
  Lists available Cartesia voices (for admin UI to pick a voice ID).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth_deps import get_current_user

logger = logging.getLogger("routes.voice")

router = APIRouter(tags=["voice"])


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000, description="Text to synthesize")
    voice_id: Optional[str] = Field(None, description="Cartesia voice UUID (uses CARTESIA_VOICE_ID default if omitted)")
    language: str = Field("en", description="BCP-47 language code (en, hi, as, bn, ...)")
    model_id: Optional[str] = Field(None, description="Cartesia model ID (default: sonic-2)")


@router.post(
    "/voice/tts",
    response_class=Response,
    summary="Text-to-speech via Cartesia",
    description=(
        "Convert text to speech using Cartesia's Sonic-2 model, routed through "
        "the Cloudflare AI Gateway. Returns mp3 audio bytes. "
        "Requires CARTESIA_API_KEY (or CF gateway BYOK) to be configured."
    ),
)
async def text_to_speech(
    body: TtsRequest,
    current_user: dict = Depends(get_current_user),
):
    from providers import cartesia
    if not cartesia.ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Text-to-speech is not available (Cartesia API key not configured).",
        )

    try:
        audio_bytes = await cartesia.synthesize(
            body.text,
            voice_id=body.voice_id or None,
            model_id=body.model_id or None,
            language=body.language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("TTS synthesis failed: %s", exc)
        raise HTTPException(status_code=502, detail="TTS synthesis failed.")

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": 'inline; filename="speech.mp3"',
            "Cache-Control": "public, max-age=3600",
            "X-TTS-Chars": str(len(body.text)),
            "X-TTS-Bytes": str(len(audio_bytes)),
        },
    )


@router.get(
    "/voice/voices",
    summary="List available Cartesia voices",
    description="Returns all voices available in the Cartesia Voice Library.",
)
async def list_voices(current_user: dict = Depends(get_current_user)):
    from providers import cartesia
    if not cartesia.ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Cartesia API key not configured.",
        )
    voices = await cartesia.list_voices()
    return {"voices": voices, "count": len(voices)}


@router.get(
    "/voice/health",
    summary="Voice provider health check",
    description="Reports readiness of Cartesia and Cohere providers.",
)
async def voice_health():
    from providers import cartesia, cohere
    cartesia_health = await cartesia.health_check()
    cohere_health = await cohere.health_check()
    return {
        "cartesia": cartesia_health,
        "cohere": cohere_health,
    }
