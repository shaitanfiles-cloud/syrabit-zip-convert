"""
vertex_chat — Gemini streaming chat client (Task #607, updated Task #34+).

Supports two auth modes, detected at import time in priority order:

  1. Direct Gemini API key  — GEMINI_API_KEY=AIza...
     Calls generativelanguage.googleapis.com directly. No GCP project or
     service account required. This is the preferred mode for Railway
     deployments that do not have a GCP project attached.

  2. Vertex AI service account — VERTEX_PROJECT_ID + optional
     VERTEX_SERVICE_ACCOUNT_JSON (falls back to ADC).
     Calls the regional aiplatform.googleapis.com endpoint. Only active
     when VERTEX_PROJECT_ID is set AND GEMINI_API_KEY is absent.

Configuration (env):
  GEMINI_API_KEY               AIza-style key from Google AI Studio (mode 1)
  VERTEX_PROJECT_ID            GCP project (mode 2 — leave unset to use mode 1)
  VERTEX_LOCATION              GCP region (default: us-central1, mode 2 only)
  VERTEX_GEMINI_MODEL          Model id (default: gemini-2.5-flash)
  VERTEX_SERVICE_ACCOUNT_JSON  Service-account JSON blob (mode 2, optional)

Yields plain text deltas from `async for token in stream_chat(...)`.
Raises RuntimeError on misconfiguration; httpx exceptions on network/auth
errors so callers can fall back to the SLM pool.
"""
from __future__ import annotations

import os
import json
import time
import logging
import asyncio
from typing import AsyncIterator, List, Dict, Any, Optional

import httpx

from vertex_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

VERTEX_PROJECT_ID = os.environ.get("VERTEX_PROJECT_ID", "").strip()
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1").strip() or "us-central1"
VERTEX_GEMINI_MODEL = os.environ.get("VERTEX_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
_SERVICE_ACCOUNT_JSON = os.environ.get("VERTEX_SERVICE_ACCOUNT_JSON", "").strip()

_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

_GEMINI_STREAM_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_USE_API_KEY = bool(_GEMINI_API_KEY and not VERTEX_PROJECT_ID)

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_TOKEN_REFRESH_MARGIN_S = 120

_creds = None
_creds_err: Optional[str] = None
_token_lock = asyncio.Lock()

_CHAT_BREAKER_THRESHOLD = max(1, int(os.environ.get("VERTEX_CHAT_BREAKER_THRESHOLD", "3")))
_CHAT_BREAKER_COOLDOWN_S = max(1.0, float(os.environ.get("VERTEX_CHAT_BREAKER_COOLDOWN_S", "180")))

_breaker = CircuitBreaker(
    name="vertex_chat",
    failure_threshold=_CHAT_BREAKER_THRESHOLD,
    cooldown_s=_CHAT_BREAKER_COOLDOWN_S,
)


def auth_mode() -> str:
    if _USE_API_KEY:
        return "gemini_api_key"
    if VERTEX_PROJECT_ID:
        return "vertex_ai"
    return "unconfigured"


def is_configured() -> bool:
    """True iff at least one auth mode is available.

    Accepts either a Gemini API key (direct AI Studio) or a GCP project
    id for Vertex AI. Does NOT check runtime breaker state.
    """
    return bool(_GEMINI_API_KEY or VERTEX_PROJECT_ID)


def is_available() -> bool:
    """True iff configured AND the circuit breaker currently allows traffic."""
    return is_configured() and _breaker.allow()


def breaker_snapshot() -> dict:
    return _breaker.snapshot()


def force_breaker_close() -> None:
    _breaker.force_close()


def _load_credentials():
    """Lazily load google-auth credentials (Vertex mode only)."""
    global _creds, _creds_err
    if _creds is not None or _creds_err is not None:
        return _creds
    try:
        from google.oauth2 import service_account
        import google.auth

        if _SERVICE_ACCOUNT_JSON:
            try:
                info = json.loads(_SERVICE_ACCOUNT_JSON)
            except json.JSONDecodeError as e:
                _creds_err = f"VERTEX_SERVICE_ACCOUNT_JSON is not valid JSON: {e}"
                logger.error(_creds_err)
                return None
            _creds = service_account.Credentials.from_service_account_info(
                info, scopes=[_SCOPE]
            )
            logger.info("Vertex chat: loaded credentials from VERTEX_SERVICE_ACCOUNT_JSON")
        else:
            try:
                _creds, _ = google.auth.default(scopes=[_SCOPE])
                logger.info("Vertex chat: loaded Application Default Credentials")
            except Exception as e:
                _creds_err = f"google.auth.default() failed: {e}"
                logger.warning(_creds_err)
                return None
        return _creds
    except ImportError as e:
        _creds_err = f"google-auth not installed: {e}"
        logger.error(_creds_err)
        return None


async def _get_access_token() -> str:
    """Return a valid OAuth2 access token (Vertex mode only)."""
    creds = _load_credentials()
    if creds is None:
        raise RuntimeError(_creds_err or "Vertex chat: no credentials available")

    async with _token_lock:
        needs_refresh = (
            not getattr(creds, "token", None)
            or not getattr(creds, "expiry", None)
            or (creds.expiry.timestamp() - time.time()) < _TOKEN_REFRESH_MARGIN_S
        )
        if needs_refresh:
            from google.auth.transport.requests import Request as _GAuthRequest
            await asyncio.to_thread(creds.refresh, _GAuthRequest())
    return creds.token


def _convert_messages(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Convert OpenAI-format chat messages → Gemini contents payload."""
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    for m in messages:
        role = (m.get("role") or "user").lower()
        text = m.get("content") or ""
        if not text:
            continue
        if role == "system":
            system_parts.append(text)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": text}]})
    payload: Dict[str, Any] = {"contents": contents}
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    return payload


async def stream_chat(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
    timeout_s: float = 60.0,
) -> AsyncIterator[str]:
    """Stream text deltas from Gemini (direct API key or Vertex AI).

    Yields raw text chunks. Raises RuntimeError / httpx exceptions on
    failure so callers can fall back to a different provider.
    """
    if not is_configured():
        raise RuntimeError(
            "Gemini chat not configured: set GEMINI_API_KEY or VERTEX_PROJECT_ID"
        )

    use_model = (model or VERTEX_GEMINI_MODEL).strip() or VERTEX_GEMINI_MODEL
    body = _convert_messages(messages)
    body["generationConfig"] = {
        "temperature": float(temperature),
        "maxOutputTokens": int(max_tokens),
    }
    timeout = httpx.Timeout(timeout_s, connect=10.0)

    if _USE_API_KEY:
        url = (
            f"{_GEMINI_STREAM_BASE}/{use_model}"
            f":streamGenerateContent?alt=sse&key={_GEMINI_API_KEY}"
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
    else:
        try:
            token = await _get_access_token()
        except Exception as e:
            _breaker.record_failure(f"auth_{type(e).__name__}")
            raise
        base = f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1"
        url = (
            f"{base}/projects/{VERTEX_PROJECT_ID}/locations/{VERTEX_LOCATION}"
            f"/publishers/google/models/{use_model}:streamGenerateContent?alt=sse"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    success_recorded = False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    err_text = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                    _breaker.record_failure(f"http_{resp.status_code}")
                    raise RuntimeError(
                        f"Gemini {resp.status_code}: {err_text}"
                    )
                _breaker.record_success()
                success_recorded = True
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    candidates = evt.get("candidates") or []
                    if not candidates:
                        continue
                    parts = (candidates[0].get("content") or {}).get("parts") or []
                    for p in parts:
                        txt = p.get("text")
                        if txt:
                            yield txt
    except RuntimeError:
        raise
    except httpx.HTTPError as e:
        if not success_recorded:
            _breaker.record_failure(f"network_{type(e).__name__}")
        raise
