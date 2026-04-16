"""Syrabit.ai — Chat speed-up impact tracking (Task #303).

Lightweight per-day counters that measure how often the latency optimizations
introduced in Task #282 (early Redis cache hits, instant casual fast-path,
speculative web search, 6-hour cache pre-warm cycle) actually fire in
production. Designed to be cheap (in-memory dict, lock-protected) so the chat
hot path pays effectively zero cost.

The numbers are surfaced via ``GET /api/admin/chat/speedups`` for a per-day
breakdown of cache hit rate, warm-cache hit %, speculative-web fallback %,
average TTFB, and the most recent cache-warm runs.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Deque, Optional

__all__ = [
    "record_chat_started",
    "record_early_cache_hit",
    "record_pre_sse_cache_hit",
    "record_instant_fastpath",
    "record_speculative_web",
    "record_ttfb",
    "record_total_latency",
    "record_warm_run",
    "snapshot",
]

_MAX_DAYS = 30
_MAX_WARM_RUNS = 50

_lock = threading.Lock()
# { "YYYY-MM-DD": {counter_name: int|float, ...} }
_daily: Dict[str, Dict[str, float]] = {}
_warm_runs: Deque[Dict[str, Any]] = deque(maxlen=_MAX_WARM_RUNS)


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _bucket() -> Dict[str, float]:
    key = _today_key()
    bucket = _daily.get(key)
    if bucket is None:
        bucket = {
            "chats_total": 0,
            "early_cache_hits": 0,        # Redis/memory hit before any preprocessing
            "pre_sse_cache_hits": 0,      # cache hit just before SSE stream begins
            "instant_fastpath": 0,        # casual instant-response fast path
            "speculative_web_started": 0, # how often we kicked off the speculative fetch
            "speculative_web_used": 0,    # internal RAG missed → web results used
            "speculative_web_discarded": 0, # internal RAG hit → web results dropped
            "ttfb_ms_sum": 0.0,
            "ttfb_count": 0,
            "total_ms_sum": 0.0,
            "total_count": 0,
        }
        _daily[key] = bucket
        # Trim oldest days
        if len(_daily) > _MAX_DAYS:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=_MAX_DAYS)).strftime("%Y-%m-%d")
            for k in list(_daily.keys()):
                if k < cutoff:
                    _daily.pop(k, None)
    return bucket


def _bump(name: str, delta: float = 1) -> None:
    with _lock:
        b = _bucket()
        b[name] = b.get(name, 0) + delta


def record_chat_started() -> None:
    _bump("chats_total")


def record_early_cache_hit() -> None:
    _bump("early_cache_hits")


def record_pre_sse_cache_hit() -> None:
    _bump("pre_sse_cache_hits")


def record_instant_fastpath() -> None:
    _bump("instant_fastpath")


def record_speculative_web(*, used: bool, discarded: bool) -> None:
    with _lock:
        b = _bucket()
        b["speculative_web_started"] = b.get("speculative_web_started", 0) + 1
        if used:
            b["speculative_web_used"] = b.get("speculative_web_used", 0) + 1
        if discarded:
            b["speculative_web_discarded"] = b.get("speculative_web_discarded", 0) + 1


def record_ttfb(ms: float) -> None:
    if ms < 0:
        return
    with _lock:
        b = _bucket()
        b["ttfb_ms_sum"] = b.get("ttfb_ms_sum", 0.0) + float(ms)
        b["ttfb_count"] = b.get("ttfb_count", 0) + 1


def record_total_latency(ms: float) -> None:
    if ms < 0:
        return
    with _lock:
        b = _bucket()
        b["total_ms_sum"] = b.get("total_ms_sum", 0.0) + float(ms)
        b["total_count"] = b.get("total_count", 0) + 1


def record_warm_run(result: Dict[str, Any]) -> None:
    """Record a cache-warm run result (from _perform_cache_warm)."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "warmed": int(result.get("warmed", 0) or 0),
        "already_cached": int(result.get("already_cached", 0) or 0),
        "failed": int(result.get("failed", 0) or 0),
        "total_queries": int(result.get("total_queries", 0) or 0),
        "source": str(result.get("source", "unknown")),
    }
    with _lock:
        _warm_runs.append(entry)


def _pct(numer: float, denom: float) -> float:
    if denom <= 0:
        return 0.0
    return round((numer / denom) * 100.0, 2)


def _avg(total: float, count: float) -> float:
    if count <= 0:
        return 0.0
    return round(total / count, 1)


def snapshot(days: int = 7) -> Dict[str, Any]:
    """Return a per-day breakdown plus rolled-up totals across the window."""
    days = max(1, min(int(days), _MAX_DAYS))
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days - 1)
    cutoff = cutoff_dt.strftime("%Y-%m-%d")

    with _lock:
        items = sorted(
            ((d, dict(b)) for d, b in _daily.items() if d >= cutoff),
            key=lambda x: x[0],
        )
        warm_runs_snapshot = [dict(r) for r in _warm_runs
                              if r["ts"][:10] >= cutoff]

    daily = []
    totals: Dict[str, float] = {}
    for d, b in items:
        chats = b.get("chats_total", 0) or 0
        early = b.get("early_cache_hits", 0) or 0
        pre_sse = b.get("pre_sse_cache_hits", 0) or 0
        instant = b.get("instant_fastpath", 0) or 0
        spec_started = b.get("speculative_web_started", 0) or 0
        spec_used = b.get("speculative_web_used", 0) or 0
        spec_disc = b.get("speculative_web_discarded", 0) or 0
        cache_hits = early + pre_sse
        daily.append({
            "date": d,
            "chats_total": chats,
            "early_cache_hits": early,
            "pre_sse_cache_hits": pre_sse,
            "instant_fastpath": instant,
            "cache_hit_pct": _pct(cache_hits, chats),
            "warmed_cache_hit_pct": _pct(early, chats),
            "speculative_web_started": spec_started,
            "speculative_web_used": spec_used,
            "speculative_web_discarded": spec_disc,
            "speculative_web_used_pct": _pct(spec_used, chats),
            "speculative_web_useful_pct": _pct(spec_used, spec_started),
            "avg_ttfb_ms": _avg(b.get("ttfb_ms_sum", 0.0), b.get("ttfb_count", 0)),
            "avg_total_ms": _avg(b.get("total_ms_sum", 0.0), b.get("total_count", 0)),
            "ttfb_samples": int(b.get("ttfb_count", 0) or 0),
        })
        for k in (
            "chats_total", "early_cache_hits", "pre_sse_cache_hits",
            "instant_fastpath", "speculative_web_started",
            "speculative_web_used", "speculative_web_discarded",
            "ttfb_ms_sum", "ttfb_count", "total_ms_sum", "total_count",
        ):
            totals[k] = totals.get(k, 0) + (b.get(k, 0) or 0)

    chats = totals.get("chats_total", 0)
    early = totals.get("early_cache_hits", 0)
    pre_sse = totals.get("pre_sse_cache_hits", 0)
    spec_started = totals.get("speculative_web_started", 0)
    spec_used = totals.get("speculative_web_used", 0)
    cache_hits = early + pre_sse

    return {
        "period_days": days,
        "totals": {
            "chats_total": int(chats),
            "early_cache_hits": int(early),
            "pre_sse_cache_hits": int(pre_sse),
            "instant_fastpath": int(totals.get("instant_fastpath", 0)),
            "cache_hit_pct": _pct(cache_hits, chats),
            "warmed_cache_hit_pct": _pct(early, chats),
            "speculative_web_started": int(spec_started),
            "speculative_web_used": int(spec_used),
            "speculative_web_discarded": int(totals.get("speculative_web_discarded", 0)),
            "speculative_web_used_pct": _pct(spec_used, chats),
            "speculative_web_useful_pct": _pct(spec_used, spec_started),
            "avg_ttfb_ms": _avg(totals.get("ttfb_ms_sum", 0.0), totals.get("ttfb_count", 0)),
            "avg_total_ms": _avg(totals.get("total_ms_sum", 0.0), totals.get("total_count", 0)),
            "ttfb_samples": int(totals.get("ttfb_count", 0)),
        },
        "daily": daily,
        "warm_runs": list(reversed(warm_runs_snapshot))[:20],
        "has_data": chats > 0,
    }
