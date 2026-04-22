"""Task #678 — module-level cache for the most recent Vertex/Gemini probe.

The startup probe (Task #667) and the periodic re-probe (Task #677) in
``server.py`` write their last result + timestamp here. The
``/healthz/ai`` route reads this cache so Railway's automatic healthcheck
can refuse to mark a bad rollout as healthy — without it the deploy logs
are the only signal that Gemini is broken, and Railway happily serves
502s to users.

Kept in its own module (instead of inside ``server.py``) so a unit test
can import the cache + response helper without dragging in the full
server boot path (Mongo, Vertex, CF clients, ``sys.exit`` on missing
prod env vars, etc.).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional


_DEFAULT_PROBE_INTERVAL_S = max(
    30, int(os.environ.get("VERTEX_PROBE_INTERVAL_S", "600") or 600)
)


def _default_ttl_s() -> int:
    """How stale a cached probe result is allowed to be before
    ``/healthz/ai`` flips to 503.

    Defaults to ``2 * VERTEX_PROBE_INTERVAL_S`` so a single missed probe
    tick (network blip, GC pause) doesn't immediately fail the
    healthcheck. Override with ``VERTEX_HEALTH_TTL_S`` if you want a
    tighter / looser window.
    """
    raw = os.environ.get("VERTEX_HEALTH_TTL_S")
    if raw:
        try:
            return max(30, int(raw))
        except ValueError:
            pass
    return 2 * _DEFAULT_PROBE_INTERVAL_S


_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "ok": None,                  # None = no probe has run yet
    "last_check_ts": None,       # unix seconds
    "reason": None,              # human-readable failure reason, if any
    "auth_mode": None,
    "via_cf_gateway": None,
    "source": None,              # "startup" | "periodic"
    "consecutive_failures": 0,   # Task #689 — surfaced in admin dashboard
}


def record(
    ok: bool,
    *,
    reason: Optional[str] = None,
    auth_mode: Optional[str] = None,
    via_cf_gateway: Optional[bool] = None,
    source: str = "startup",
    ts: Optional[float] = None,
    consecutive_failures: Optional[int] = None,
) -> None:
    """Write the latest probe outcome into the cache.

    ``consecutive_failures`` is the count maintained by the periodic
    probe loop in ``server.py`` (resets to 0 on any successful probe).
    When omitted, we auto-derive it: success resets to 0, failure
    increments the previous value. This keeps the cache module honest
    even if a caller forgets to pass the count explicitly.
    """
    with _LOCK:
        _STATE["ok"] = bool(ok)
        _STATE["last_check_ts"] = float(ts) if ts is not None else time.time()
        _STATE["reason"] = reason
        _STATE["auth_mode"] = auth_mode
        _STATE["via_cf_gateway"] = via_cf_gateway
        _STATE["source"] = source
        if consecutive_failures is not None:
            _STATE["consecutive_failures"] = max(0, int(consecutive_failures))
        else:
            if ok:
                _STATE["consecutive_failures"] = 0
            else:
                _STATE["consecutive_failures"] = (
                    int(_STATE.get("consecutive_failures") or 0) + 1
                )


def snapshot() -> dict[str, Any]:
    """Return a copy of the current cache state."""
    with _LOCK:
        return dict(_STATE)


def reset() -> None:
    """Test-only helper: clear the cache back to its initial state."""
    with _LOCK:
        _STATE["ok"] = None
        _STATE["last_check_ts"] = None
        _STATE["reason"] = None
        _STATE["auth_mode"] = None
        _STATE["via_cf_gateway"] = None
        _STATE["source"] = None
        _STATE["consecutive_failures"] = 0


def dashboard_snapshot(
    *,
    now: Optional[float] = None,
    ttl_s: Optional[int] = None,
) -> dict[str, Any]:
    """Task #689 — admin-dashboard view of the most recent probe.

    Returns the same status semantics as ``healthz_ai_response`` (ok /
    unknown / stale / unhealthy) plus the raw cache fields the admin UI
    needs (``consecutive_failures``, ``last_check_ts``, ``reason``,
    ``auth_mode``, ``via_cf_gateway``, ``source``, ``probe_interval_s``).
    Always returns a 200-shaped body — admins inspecting status do not
    need a 503 from the JSON payload itself; they just need to see what
    the latest probe said and how long ago.
    """
    snap = snapshot()
    _, body = healthz_ai_response(now=now, ttl_s=ttl_s)
    body["consecutive_failures"] = int(snap.get("consecutive_failures") or 0)
    # Raw fields admins want even when the helper returned an "unknown"
    # body (no probe yet) — last_check_ts is None, but that's fine.
    body.setdefault("last_check_ts", snap.get("last_check_ts"))
    body.setdefault("auth_mode", snap.get("auth_mode"))
    body.setdefault("via_cf_gateway", snap.get("via_cf_gateway"))
    body.setdefault("source", snap.get("source"))
    body["probe_interval_s"] = _DEFAULT_PROBE_INTERVAL_S
    return body


def healthz_ai_response(
    *,
    now: Optional[float] = None,
    ttl_s: Optional[int] = None,
) -> tuple[int, dict[str, Any]]:
    """Compute the (status_code, body) for ``GET /healthz/ai``.

    * 200 + ``{"status": "ok", ...}`` when the cached probe is healthy
      and was recorded within the TTL window.
    * 503 + ``{"status": "unknown", ...}`` when no probe has run yet
      (e.g. the worker just booted and the startup probe hasn't returned).
    * 503 + ``{"status": "stale", ...}`` when the last successful probe
      is older than the TTL — Gemini may have gone quiet without us
      noticing.
    * 503 + ``{"status": "unhealthy", ...}`` when the last probe
      explicitly reported a failure.
    """
    snap = snapshot()
    now = float(now) if now is not None else time.time()
    ttl = int(ttl_s) if ttl_s is not None else _default_ttl_s()

    last_ts = snap.get("last_check_ts")
    if snap.get("ok") is None or last_ts is None:
        return 503, {
            "status": "unknown",
            "reason": "vertex startup probe has not completed yet",
            "ttl_s": ttl,
        }

    age_s = max(0.0, now - float(last_ts))
    body: dict[str, Any] = {
        "last_check_ts": last_ts,
        "age_s": round(age_s, 3),
        "ttl_s": ttl,
        "auth_mode": snap.get("auth_mode"),
        "via_cf_gateway": snap.get("via_cf_gateway"),
        "source": snap.get("source"),
    }

    if not snap.get("ok"):
        body["status"] = "unhealthy"
        body["reason"] = snap.get("reason") or "vertex probe reported failure"
        return 503, body

    if age_s > ttl:
        body["status"] = "stale"
        body["reason"] = (
            f"last successful vertex probe is {age_s:.0f}s old "
            f"(ttl={ttl}s) — periodic re-probe may be stuck"
        )
        return 503, body

    body["status"] = "ok"
    return 200, body
