"""
vertex_chat — Vertex AI Gemini Flash streaming chat client (Task #607).

Provides token-by-token streaming from Google Vertex AI's
`streamGenerateContent` REST endpoint using Application Default
Credentials (ADC) or a service-account JSON blob.

This module is intentionally separate from the disabled
`vertex_services.py` stub: that one wraps the legacy embeddings /
OCR / generation surface, while this one is scoped strictly to chat
streaming as required by Task #607.

Configuration (env):
  VERTEX_PROJECT_ID            GCP project (REQUIRED to enable)
  VERTEX_LOCATION              GCP region (default: us-central1)
  VERTEX_GEMINI_MODEL          Model id (default: gemini-2.5-flash)
  VERTEX_SERVICE_ACCOUNT_JSON  Service-account JSON blob (string).
                               Optional — falls back to ADC
                               (GOOGLE_APPLICATION_CREDENTIALS).

Returns plain text deltas from `async for token in stream(...)`.
Raises RuntimeError on misconfiguration; httpx exceptions on
network/auth errors so callers can fall back.
"""
from __future__ import annotations

import os
import json
import time
import logging
import asyncio
from typing import AsyncIterator, List, Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)

VERTEX_PROJECT_ID = os.environ.get("VERTEX_PROJECT_ID", "").strip()
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1").strip() or "us-central1"
VERTEX_GEMINI_MODEL = os.environ.get("VERTEX_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
_SERVICE_ACCOUNT_JSON = os.environ.get("VERTEX_SERVICE_ACCOUNT_JSON", "").strip()

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_TOKEN_REFRESH_MARGIN_S = 120  # refresh ~2 min before expiry

_creds = None
_creds_err: Optional[str] = None
_token_lock = asyncio.Lock()


def is_configured() -> bool:
    """True iff the Vertex chat client can be used."""
    return bool(VERTEX_PROJECT_ID)


def _load_credentials():
    """Lazily load google-auth credentials. Returns None if unavailable."""
    global _creds, _creds_err
    if _creds is not None or _creds_err is not None:
        return _creds
    try:
        from google.oauth2 import service_account  # type: ignore
        import google.auth  # type: ignore

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
    """Return a valid OAuth2 access token, refreshing as needed."""
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
            from google.auth.transport.requests import Request as _GAuthRequest  # type: ignore
            await asyncio.to_thread(creds.refresh, _GAuthRequest())
    return creds.token


def _convert_messages(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Convert OpenAI-format chat messages → Vertex Gemini contents payload."""
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
    """Stream text deltas from Vertex AI Gemini Flash.

    Yields raw text chunks. Raises RuntimeError / httpx exceptions on
    failure so callers can fall back to a different provider.
    """
    if not is_configured():
        raise RuntimeError("Vertex chat is not configured (VERTEX_PROJECT_ID missing)")

    use_model = (model or VERTEX_GEMINI_MODEL).strip() or VERTEX_GEMINI_MODEL
    token = await _get_access_token()

    base = f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1"
    url = (
        f"{base}/projects/{VERTEX_PROJECT_ID}/locations/{VERTEX_LOCATION}"
        f"/publishers/google/models/{use_model}:streamGenerateContent?alt=sse"
    )
    body = _convert_messages(messages)
    body["generationConfig"] = {
        "temperature": float(temperature),
        "maxOutputTokens": int(max_tokens),
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    timeout = httpx.Timeout(timeout_s, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                err_text = (await resp.aread()).decode("utf-8", errors="replace")[:500]
                raise RuntimeError(
                    f"Vertex Gemini Flash {resp.status_code}: {err_text}"
                )
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
