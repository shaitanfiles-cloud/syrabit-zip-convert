"""Cloudflare Pages deploy hook trigger (Task #387).

When admins edit subject/chapter content, the prerendered HTML emitted by
`artifacts/syrabit/scripts/prerender-routes.mjs` (Task #385) becomes
stale until the next manual deploy. This module fires the Cloudflare
Pages deploy hook to rebuild the prerendered surface on demand, with
two safety features:

  1. Debounce / coalesce: many edits in a short window collapse into a
     single deploy. We wait `CF_PAGES_DEPLOY_COALESCE` seconds after the
     last queued event before firing, then enforce a
     `CF_PAGES_DEPLOY_MIN_INTERVAL` cooldown between fires.
  2. Nightly safety net: even with no edits, fire the hook once a day
     so chapters that bypassed admin write paths (bulk imports, manual
     DB edits) eventually get refreshed.

The deploy hook URL is read from `CF_PAGES_DEPLOY_HOOK_URL`. When it is
unset the module no-ops so dev/test environments are unaffected.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Invalid int for %s=%r; using default %d", name, raw, default)
        return default


DEPLOY_HOOK_URL = os.environ.get("CF_PAGES_DEPLOY_HOOK_URL", "").strip()
MIN_DEPLOY_INTERVAL_SEC = _env_int("CF_PAGES_DEPLOY_MIN_INTERVAL", 300)
COALESCE_WINDOW_SEC = _env_int("CF_PAGES_DEPLOY_COALESCE", 60)
NIGHTLY_INTERVAL_SEC = _env_int("CF_PAGES_DEPLOY_NIGHTLY_INTERVAL", 86400)
HTTP_TIMEOUT_SEC = _env_int("CF_PAGES_DEPLOY_TIMEOUT", 15)

_state = {
    "last_triggered_at": 0.0,
    "last_status": None,           # "ok" | "http_NNN" | "error" | "not_configured"
    "last_reason": None,           # comma-joined reasons for last fire
    "last_error": None,            # short error string, if any
    "last_response_body": None,    # short response snippet
    "pending_reasons": set(),
    "pending_task": None,          # asyncio.Task for the coalesce loop
    "trigger_count": 0,
}

_lock: Optional[asyncio.Lock] = None


def is_configured() -> bool:
    return bool(DEPLOY_HOOK_URL)


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def _fire_now(reasons: list) -> bool:
    """Fire the deploy hook once. Updates _state regardless of outcome."""
    if not DEPLOY_HOOK_URL:
        _state["last_status"] = "not_configured"
        logger.debug("CF Pages deploy hook not configured; skipping")
        return False

    reason_str = ",".join(sorted(set(reasons)))[:300] or "unspecified"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SEC) as client:
            resp = await client.post(DEPLOY_HOOK_URL)
        body_snippet = (resp.text or "")[:300]
        _state["last_triggered_at"] = time.time()
        _state["last_reason"] = reason_str
        _state["last_response_body"] = body_snippet
        _state["trigger_count"] += 1
        if 200 <= resp.status_code < 300:
            _state["last_status"] = "ok"
            _state["last_error"] = None
            logger.info(
                "CF Pages deploy hook fired ok (reason=%s, body=%s)",
                reason_str, body_snippet[:120],
            )
            return True
        _state["last_status"] = f"http_{resp.status_code}"
        _state["last_error"] = body_snippet
        logger.warning(
            "CF Pages deploy hook returned HTTP %d: %s",
            resp.status_code, body_snippet[:200],
        )
        return False
    except Exception as exc:
        _state["last_triggered_at"] = time.time()
        _state["last_reason"] = reason_str
        _state["last_status"] = "error"
        _state["last_error"] = str(exc)[:300]
        logger.warning("CF Pages deploy hook error: %s", exc)
        return False


async def _coalesce_loop() -> None:
    """Wait for the coalesce window + cooldown, then fire pending reasons."""
    try:
        # Phase 1: batch additional edits that arrive in the next few seconds.
        await asyncio.sleep(COALESCE_WINDOW_SEC)
        # Phase 2: respect MIN_DEPLOY_INTERVAL_SEC since the previous fire.
        while True:
            elapsed = time.time() - _state["last_triggered_at"]
            if elapsed >= MIN_DEPLOY_INTERVAL_SEC:
                break
            await asyncio.sleep(MIN_DEPLOY_INTERVAL_SEC - elapsed + 1)
        async with _get_lock():
            reasons = list(_state["pending_reasons"])
            _state["pending_reasons"].clear()
            _state["pending_task"] = None
        if reasons:
            await _fire_now(reasons)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("CF Pages coalesce loop crashed")
        _state["pending_task"] = None


def schedule_refresh(reason: str = "content_update") -> bool:
    """Queue a debounced CF Pages deploy.

    Safe to call from any FastAPI handler. Returns True if a refresh was
    queued (or was already pending), False if the hook is not configured
    or no event loop is running.
    """
    if not is_configured():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _state["pending_reasons"].add(reason[:80])
    task = _state["pending_task"]
    if task is None or task.done():
        _state["pending_task"] = loop.create_task(_coalesce_loop())
    return True


async def trigger_now(reason: str = "manual_admin") -> bool:
    """Force-fire the deploy hook immediately, bypassing debounce."""
    return await _fire_now([reason])


def status() -> dict:
    task = _state["pending_task"]
    pending = bool(task and not task.done())
    return {
        "configured": is_configured(),
        "last_triggered_at": _state["last_triggered_at"] or None,
        "last_status": _state["last_status"],
        "last_reason": _state["last_reason"],
        "last_error": _state["last_error"],
        "last_response_body": _state["last_response_body"],
        "trigger_count": _state["trigger_count"],
        "pending_reasons": sorted(_state["pending_reasons"]),
        "pending": pending,
        "min_interval_sec": MIN_DEPLOY_INTERVAL_SEC,
        "coalesce_window_sec": COALESCE_WINDOW_SEC,
        "nightly_interval_sec": NIGHTLY_INTERVAL_SEC,
    }


async def nightly_loop() -> None:
    """Fire the deploy hook once per `NIGHTLY_INTERVAL_SEC` as a safety net.

    Runs only when configured. Catches its own errors so a bad response
    never kills the loop.
    """
    if not is_configured() or NIGHTLY_INTERVAL_SEC <= 0:
        return
    while True:
        try:
            await asyncio.sleep(NIGHTLY_INTERVAL_SEC)
            await _fire_now(["nightly_safety_net"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("CF Pages nightly deploy loop iteration failed")
