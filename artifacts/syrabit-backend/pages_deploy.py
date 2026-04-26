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
from datetime import datetime, timezone
from typing import Any, Optional

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


# Task #950 — Mongo-backed lease so only ONE replica fires the
# nightly Cloudflare Pages deploy hook. Previously gated by
# ``_is_leader`` in server.py, which is per-machine and double-fires on
# multi-replica Railway deployments — the deploy hook triggers a real
# CF Pages build for each call, so every duplicate run wastes a build
# minute and shows up as a redundant deploy in the dashboard.
#
# Followers poll at a sub-interval cadence (so a leader crash is
# detected within one follower window), but the actual deploy hook is
# only fired when the cycle elapses AND the lease is held. The cycle
# clock is tracked via ``last_fired_at`` on the lease doc, so the
# deploy hook fires at most once per ``NIGHTLY_INTERVAL_SEC`` across
# the replica fleet — and the next replica to win the lease after a
# fail-over picks up exactly where the dead leader left off, no
# matter when in the cycle the death occurred.
_NIGHTLY_DEPLOY_LOCK_ID = "pages_deploy_nightly_lease"
_NIGHTLY_DEPLOY_FOLLOWER_INTERVAL_S = max(60, min(600, NIGHTLY_INTERVAL_SEC // 12 or 60))
_NIGHTLY_DEPLOY_LAST_FIRED_FIELD = "last_fired_at"


def _parse_iso_utc(s: Any) -> Optional[datetime]:
    """Best-effort parse of an ISO-8601 UTC timestamp from Mongo."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str) or not s:
        return None
    try:
        # ``fromisoformat`` accepts both ``+00:00`` and naive strings.
        out = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return out if out.tzinfo else out.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def nightly_loop() -> None:
    """Fire the deploy hook once per `NIGHTLY_INTERVAL_SEC` as a safety net.

    Runs only when configured. Catches its own errors so a bad response
    never kills the loop.

    Cross-replica dedup (Task #950): every replica may run this loop,
    but only the lease-holder may fire the CF Pages deploy hook. The
    loop polls at a follower interval so a leader crash is detected
    quickly, and the deploy itself is gated on a ``last_fired_at``
    marker stored next to the lease so the hook fires at most once
    per ``NIGHTLY_INTERVAL_SEC`` across the fleet — including the
    fail-over case where a follower takes over mid-cycle.
    """
    if not is_configured() or NIGHTLY_INTERVAL_SEC <= 0:
        return
    # Local import keeps the module load order independent of deps/db.
    import background_lease as _bglease
    from deps import db
    owner_id = _bglease.make_owner_id("pages-deploy-nightly")
    ttl_s = max(NIGHTLY_INTERVAL_SEC * 3, 24 * 3600)
    try:
        while True:
            try:
                # Poll at the follower cadence so a leader crash is
                # picked up within one follower interval, not after
                # a full nightly cycle.
                await asyncio.sleep(_NIGHTLY_DEPLOY_FOLLOWER_INTERVAL_S)
                if not await _bglease.try_acquire_lease(
                    db, _NIGHTLY_DEPLOY_LOCK_ID, owner_id, ttl_s,
                ):
                    continue
                # Lease held — check whether the cycle has elapsed.
                # ``last_fired_at`` lives on the lease doc; we use a
                # plain find here (the lease doc was just upserted by
                # try_acquire so it always exists at this point).
                doc = await db.job_locks.find_one(
                    {"_id": _NIGHTLY_DEPLOY_LOCK_ID})
                last_fired = _parse_iso_utc(
                    (doc or {}).get(_NIGHTLY_DEPLOY_LAST_FIRED_FIELD))
                now = datetime.now(timezone.utc)
                if last_fired is not None and (
                    now - last_fired
                ).total_seconds() < NIGHTLY_INTERVAL_SEC:
                    # Still inside the current cycle — peer (or this
                    # replica earlier in its lifetime) already fired.
                    continue
                fired_ok = await _fire_now(["nightly_safety_net"])
                # Stamp the cycle ONLY on a successful fire so a
                # transient deploy-hook failure (CF outage, 5xx, key
                # rotation) is retried on the next follower tick
                # instead of being silently suppressed for the rest
                # of the cycle. ``_fire_now`` already logs the
                # failure path, so we just skip the stamp here.
                if not fired_ok:
                    continue
                try:
                    await db.job_locks.update_one(
                        {"_id": _NIGHTLY_DEPLOY_LOCK_ID},
                        {"$set": {
                            _NIGHTLY_DEPLOY_LAST_FIRED_FIELD:
                                now.isoformat(),
                        }},
                    )
                except Exception:
                    logger.exception(
                        "CF Pages nightly: failed to stamp last_fired_at"
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "CF Pages nightly deploy loop iteration failed")
    finally:
        try:
            await asyncio.shield(_bglease.release_lease(
                db, _NIGHTLY_DEPLOY_LOCK_ID, owner_id,
            ))
        except Exception:
            pass
