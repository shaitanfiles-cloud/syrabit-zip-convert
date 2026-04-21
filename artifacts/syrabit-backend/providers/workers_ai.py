"""Workers AI fallback client (Task #636).

The edge worker exposes /api/ai/fallback/{chat,embed,tts,stt} backed by
Cloudflare Workers AI. We hit it ONLY after a primary provider
(Vertex/Gemini for chat & embed, Sarvam for TTS/STT) has failed with a
retryable class of error: timeout, 5xx, 429, or quota.

Hard rules baked into `should_fallback()` below:
- 4xx other than 429 NEVER triggers fallback (bad input is the same
  upstream regardless of provider — flipping providers would just hide
  the bug from us).
- Each capability has its own kill-switch. An admin can disable
  Workers AI per-capability without disabling the others.
- All fallback events are recorded in `_state` so the admin health
  panel can render counts + last-fallback timestamp without us having
  to scrape logs.

The shared secret WORKERS_AI_FALLBACK_SECRET is required: the worker
rejects any /api/ai/fallback/* call without a matching X-Edge-AI-Secret.
This stops the worker AI quota from being burned by external scrapers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Capabilities ──────────────────────────────────────────────────────────
CAPABILITIES = ("chat", "embed", "tts", "stt")
Capability = str  # one of CAPABILITIES

# ─── Config (read once) ────────────────────────────────────────────────────
def _edge_url() -> str:
    """Where to send fallback calls. Defaults to the production worker.

    For local dev set WORKERS_AI_EDGE_URL=http://localhost:8000 and run
    `wrangler dev --remote` so the AI binding is reachable.
    """
    return os.environ.get("WORKERS_AI_EDGE_URL", "https://api.syrabit.ai").rstrip("/")


def _shared_secret() -> str:
    return os.environ.get("WORKERS_AI_FALLBACK_SECRET", "")


def _enabled_globally() -> bool:
    """Master switch. Defaults ON when the secret is set, OFF otherwise.

    A missing secret means the worker would 401 every call, so there's
    no point even attempting the round-trip.
    """
    if not _shared_secret():
        return False
    val = os.environ.get("WORKERS_AI_FALLBACK_ENABLED", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


# ─── Per-capability runtime state (kill-switch + counters) ─────────────────
@dataclass
class _CapState:
    enabled: bool = True
    last_fallback_at: float = 0.0
    last_outcome: str = ""  # "ok" | "error" | ""
    last_error: str = ""
    last_primary_error: str = ""
    last_primary_latency_ms: int = 0
    last_fallback_latency_ms: int = 0
    # rolling 24h event log (capped) for the admin panel
    events: Deque[dict] = field(default_factory=lambda: deque(maxlen=200))

    def record(self, *, ok: bool, primary_error: str, primary_ms: int,
               fallback_ms: int, error: str = "") -> None:
        now = time.time()
        self.last_fallback_at = now
        self.last_outcome = "ok" if ok else "error"
        self.last_primary_error = primary_error
        self.last_primary_latency_ms = primary_ms
        self.last_fallback_latency_ms = fallback_ms
        self.last_error = error if not ok else ""
        self.events.append({
            "ts": now,
            "ok": ok,
            "primary_error": primary_error,
            "primary_ms": primary_ms,
            "fallback_ms": fallback_ms,
            "error": error,
        })


_state: Dict[str, _CapState] = {c: _CapState() for c in CAPABILITIES}
_state_lock = threading.Lock()


# Durable kill-switch persistence (MongoDB). The in-memory `_state` is the
# hot path used by every fallback decision; we sync it from / to the DB so
# (a) toggles survive restarts and (b) every API instance picks up the
# new value within `_PERSIST_REFRESH_SEC` of an admin flip.
_PERSIST_COLLECTION = "admin_workers_ai_killswitch"
_PERSIST_REFRESH_SEC = 30.0
_persist_last_load = 0.0
_persist_lock = threading.Lock()


async def _persist_load_if_stale() -> None:
    """Refresh `_state[*].enabled` from Mongo if our cached copy is older
    than `_PERSIST_REFRESH_SEC`. Failures are logged and swallowed —
    we'd rather use the cached/default value than return 500 because
    the DB is briefly unreachable.
    """
    global _persist_last_load
    if time.time() - _persist_last_load < _PERSIST_REFRESH_SEC:
        return
    try:
        from deps import db as _db
        if _db is None:
            return
        docs = await _db[_PERSIST_COLLECTION].find({}).to_list(length=20)
        with _state_lock:
            for d in docs:
                cap = d.get("capability")
                if cap in _state:
                    _state[cap].enabled = bool(d.get("enabled", True))
            _persist_last_load = time.time()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[workers-ai] kill-switch DB load failed: {type(e).__name__}: {str(e)[:150]}")


async def _persist_save(capability: Capability, enabled: bool, actor: str = "") -> None:
    """Upsert a single capability flip into Mongo so other API instances
    pick it up on their next `_persist_load_if_stale()` cycle."""
    try:
        from deps import db as _db
        if _db is None:
            return
        await _db[_PERSIST_COLLECTION].update_one(
            {"capability": capability},
            {"$set": {
                "capability": capability,
                "enabled": bool(enabled),
                "updated_at": time.time(),
                "actor": actor or "system",
            }},
            upsert=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[workers-ai] kill-switch DB save failed: {type(e).__name__}: {str(e)[:150]}")


def is_enabled(capability: Capability) -> bool:
    """Worker AI fallback enabled globally AND for this capability.

    Sync wrapper used by hot paths — does NOT touch the DB. The DB
    refresh happens out of band in `attempt_fallback()` (which is async)
    so admins see their toggles take effect within ~30s without slowing
    every primary-success path.
    """
    if capability not in _state:
        return False
    if not _enabled_globally():
        return False
    return _state[capability].enabled


async def set_enabled_async(capability: Capability, enabled: bool, actor: str = "") -> bool:
    """Admin per-capability kill switch (durable). Returns the new value.

    Persists to Mongo so the toggle survives restarts and propagates to
    other API instances. Returns False (no-op) for unknown capabilities.
    """
    if capability not in _state:
        return False
    with _state_lock:
        _state[capability].enabled = bool(enabled)
    await _persist_save(capability, enabled, actor)
    logger.info(
        f"[workers-ai] capability={capability} kill_switch={'on' if enabled else 'off'} actor={actor or 'system'}"
    )
    return _state[capability].enabled


def set_enabled(capability: Capability, enabled: bool) -> bool:
    """In-memory kill switch toggle. Used by tests and for synchronous
    contexts; production admin endpoints should use the async variant
    so the change is durable."""
    if capability not in _state:
        return False
    with _state_lock:
        _state[capability].enabled = bool(enabled)
    logger.info(
        f"[workers-ai] capability={capability} kill_switch={'on' if enabled else 'off'} (memory-only)"
    )
    return _state[capability].enabled


def snapshot() -> dict:
    """Snapshot for the admin health panel — counts in last 24h, etc.

    Counts are derived on-demand from the rolling event log so the data
    structure never gets out of sync with itself.
    """
    cutoff = time.time() - 86400.0
    out: Dict[str, Any] = {
        "enabled_globally": _enabled_globally(),
        "edge_url": _edge_url(),
        "secret_configured": bool(_shared_secret()),
        "capabilities": {},
    }
    for cap, st in _state.items():
        with _state_lock:
            recent = [e for e in st.events if e["ts"] >= cutoff]
        out["capabilities"][cap] = {
            "enabled": st.enabled,
            "last_fallback_at": st.last_fallback_at or None,
            "last_outcome": st.last_outcome or None,
            "last_error": st.last_error or None,
            "last_primary_error": st.last_primary_error or None,
            "last_primary_latency_ms": st.last_primary_latency_ms or None,
            "last_fallback_latency_ms": st.last_fallback_latency_ms or None,
            "fallbacks_24h": len(recent),
            "successes_24h": sum(1 for e in recent if e["ok"]),
            "failures_24h": sum(1 for e in recent if not e["ok"]),
        }
    return out


# ─── Fallback policy ───────────────────────────────────────────────────────
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def should_fallback(error: BaseException) -> bool:
    """Decide whether `error` from the primary provider warrants a
    Workers AI fallback attempt.

    NEVER fall back on:
      - 4xx (other than 429) — this is bad input from us, the same
        request would fail on Workers AI too and we'd hide the real bug.
      - asyncio.CancelledError — the caller bailed.
    DO fall back on:
      - asyncio.TimeoutError / httpx.TimeoutException
      - httpx.HTTPStatusError with status in RETRYABLE_STATUSES
      - httpx.ConnectError / TransportError (network blip)
      - Any non-HTTP runtime error tagged in its name as quota/timeout
    """
    if isinstance(error, asyncio.CancelledError):
        return False
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return True
    if isinstance(error, httpx.TimeoutException):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUSES
    if isinstance(error, (httpx.ConnectError, httpx.TransportError)):
        return True
    name = type(error).__name__.lower()
    msg = str(error).lower()
    if "quota" in name or "ratelimit" in name or "rate_limit" in msg:
        return True
    if "timeout" in name:
        return True
    # Unknown class: be conservative — don't burn the fallback quota on
    # what might be a permanent 4xx wrapped in a generic Exception.
    return False


def classify_primary_error(error: BaseException) -> str:
    """Stable short label for logs and the admin dashboard."""
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return f"http_{error.response.status_code}"
    if isinstance(error, (httpx.ConnectError, httpx.TransportError)):
        return "network"
    return type(error).__name__


# ─── Edge fan-out (the only network I/O in this module) ────────────────────
_FALLBACK_TIMEOUT = float(os.environ.get("WORKERS_AI_TIMEOUT_SEC", "20"))
_client: Optional[httpx.AsyncClient] = None
_client_lock = threading.Lock()


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(
                    base_url=_edge_url(),
                    timeout=_FALLBACK_TIMEOUT,
                )
    return _client


async def _post(capability: Capability, payload: Mapping[str, Any]) -> dict:
    headers = {"X-Edge-AI-Secret": _shared_secret()}
    client = _get_client()
    resp = await client.post(
        f"/api/ai/fallback/{capability}", json=payload, headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


async def call_chat(messages: Iterable[Mapping[str, str]], *, max_tokens: int = 1024,
                    temperature: float = 0.3) -> str:
    out = await _post("chat", {
        "messages": list(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
    })
    if not out.get("ok"):
        raise RuntimeError(f"workers_ai_chat_failed: {out.get('error')}")
    return out.get("text", "") or ""


async def call_embed(text: str | list[str]) -> list[list[float]]:
    out = await _post("embed", {"text": text})
    if not out.get("ok"):
        raise RuntimeError(f"workers_ai_embed_failed: {out.get('error')}")
    return out.get("vectors", []) or []


async def call_tts(text: str, *, lang: str = "en") -> dict:
    out = await _post("tts", {"text": text, "lang": lang})
    if not out.get("ok"):
        raise RuntimeError(f"workers_ai_tts_failed: {out.get('error')}")
    # { audio_base64, format }
    return {"audio_base64": out.get("audio_base64", ""), "format": out.get("format", "wav")}


async def call_stt(audio_base64: str) -> str:
    out = await _post("stt", {"audio_base64": audio_base64})
    if not out.get("ok"):
        raise RuntimeError(f"workers_ai_stt_failed: {out.get('error')}")
    return out.get("text", "") or ""


# ─── High-level wrapper used by call sites ─────────────────────────────────
async def attempt_fallback(
    capability: Capability,
    primary_error: BaseException,
    primary_latency_ms: int,
    runner,  # async callable returning the normalised value
) -> tuple[bool, Any, str]:
    """Run `runner()` (one of call_chat/embed/tts/stt) under the policy.

    Returns (ok, value_or_none, fallback_label) where fallback_label is
    "workers-ai" on success, "" on failure or when fallback was skipped.

    The caller is responsible for raising the *original* primary error
    if (ok is False) — we never re-raise here so the existing error
    handling stays in one place upstream.
    """
    # Refresh durable kill-switch state opportunistically (no-op if cached
    # within the last 30s). Called here — not in is_enabled() — because
    # this path is already async and only fires on the slow primary-failure
    # branch, so we don't add latency to successful primary calls.
    await _persist_load_if_stale()
    if not is_enabled(capability):
        return False, None, ""
    if not should_fallback(primary_error):
        logger.info(
            f"[workers-ai] capability={capability} skip_reason=non_retryable "
            f"primary_error={type(primary_error).__name__}"
        )
        return False, None, ""

    primary_label = classify_primary_error(primary_error)
    t0 = time.perf_counter()
    try:
        value = await runner()
    except Exception as e:  # noqa: BLE001 — log + record, propagate False
        dur = int((time.perf_counter() - t0) * 1000)
        with _state_lock:
            _state[capability].record(
                ok=False, primary_error=primary_label,
                primary_ms=primary_latency_ms, fallback_ms=dur,
                error=type(e).__name__,
            )
        logger.warning(
            f"[workers-ai] capability={capability} fallback=workers-ai "
            f"outcome=error primary_error={primary_label} primary_ms={primary_latency_ms} "
            f"fallback_ms={dur} err={type(e).__name__}: {str(e)[:200]}"
        )
        return False, None, ""
    dur = int((time.perf_counter() - t0) * 1000)
    with _state_lock:
        _state[capability].record(
            ok=True, primary_error=primary_label,
            primary_ms=primary_latency_ms, fallback_ms=dur,
        )
    logger.info(
        f"[workers-ai] capability={capability} fallback=workers-ai outcome=ok "
        f"primary_error={primary_label} primary_ms={primary_latency_ms} fallback_ms={dur}"
    )
    return True, value, "workers-ai"


__all__ = [
    "CAPABILITIES",
    "is_enabled",
    "set_enabled",
    "snapshot",
    "should_fallback",
    "classify_primary_error",
    "attempt_fallback",
    "call_chat",
    "call_embed",
    "call_tts",
    "call_stt",
]
