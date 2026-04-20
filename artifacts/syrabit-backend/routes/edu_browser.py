"""Syrabit.ai — Educational browser routes.

Public endpoints:
  POST /api/edu/reader/fetch          → return clean article text for a URL
  POST /api/edu/grounded-answer       → SSE stream: RAG + web + LLM answer
  GET  /api/edu/health                → reader / pipeline / cache snapshot

Admin endpoints (require admin JWT):
  GET    /api/admin/edu/allowlist            → effective allowlist + overrides
  POST   /api/admin/edu/allowlist            → add/update an override
  DELETE /api/admin/edu/allowlist/{domain}   → remove an override
  GET    /api/admin/edu/blocked-log          → recent blocked-request log
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from auth_deps import get_admin_user, check_rate_limit
from edu_allowlist import (
    effective_allowlist, list_overrides, upsert_override,
    remove_override, list_blocked_requests, _refresh_overrides_cache,
)
from edu_reader import fetch_and_extract, get_reader_stats
from grounded_answer import stream_grounded_answer, get_grounded_pipeline_stats
from cache import _redis_hit_count, _redis_miss_count

logger = logging.getLogger(__name__)
router = APIRouter()

_RATE_READER_PER_IP = 30  # req / 60s
_RATE_GROUNDED_PER_IP = 12  # req / 60s


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ip_hash(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


# ───────────────────────── Models ─────────────────────────

class ReaderFetchReq(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    bypass_cache: bool = False


class GroundedAnswerReq(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    page_url: str = ""
    subject_id: str = ""
    subject_name: str = ""
    chapter_name: str = ""
    board_name: str = ""
    class_name: str = ""
    response_lang: str = "en"
    model: str = ""
    max_tokens: int = 1024
    message_id: Optional[str] = None


class AllowlistUpsertReq(BaseModel):
    domain: str = Field(..., min_length=3, max_length=253)
    status: str = "allowed"  # allowed | blocked
    note: str = ""


# ───────────────────────── Public: reader ─────────────────────────

@router.post("/edu/reader/fetch")
async def reader_fetch(req: ReaderFetchReq, request: Request):
    ip = _client_ip(request)
    if not check_rate_limit(f"edu_reader:{ip}", max_requests=_RATE_READER_PER_IP, window_seconds=60):
        raise HTTPException(status_code=429, detail="Reader rate limit exceeded — try again in a minute.",
                            headers={"Retry-After": "60"})
    payload = await fetch_and_extract(
        req.url, actor=ip, ip_hash=_ip_hash(ip), bypass_cache=req.bypass_cache,
    )
    if not payload.get("ok"):
        # Map internal error codes to HTTP statuses so callers can branch.
        err = payload.get("error", "fetch_failed")
        if err in ("not_allowed", "redirect_not_allowed"):
            return JSONResponse(status_code=403, content=payload)
        if err == "robots_disallow":
            return JSONResponse(status_code=451, content=payload)
        if err == "timeout":
            return JSONResponse(status_code=504, content=payload)
        if err.startswith("http_"):
            return JSONResponse(status_code=502, content=payload)
        return JSONResponse(status_code=400, content=payload)
    return payload


# ───────────────────────── Public: grounded answer ─────────────────────────

@router.post("/edu/grounded-answer")
async def grounded_answer(req: GroundedAnswerReq, request: Request):
    ip = _client_ip(request)
    if not check_rate_limit(f"edu_grounded:{ip}", max_requests=_RATE_GROUNDED_PER_IP, window_seconds=60):
        raise HTTPException(status_code=429, detail="Answer rate limit exceeded — try again in a minute.",
                            headers={"Retry-After": "60"})

    cancel_event = asyncio.Event()

    async def _stream_with_disconnect_watch():
        watcher = asyncio.create_task(_watch_disconnect(request, cancel_event))
        try:
            async for chunk in stream_grounded_answer(
                query=req.query,
                page_url=req.page_url,
                subject_id=req.subject_id,
                subject_name=req.subject_name,
                chapter_name=req.chapter_name,
                board_name=req.board_name,
                class_name=req.class_name,
                response_lang=req.response_lang or "en",
                model=req.model or "",
                max_tokens=int(req.max_tokens or 1024),
                actor=ip,
                ip_hash=_ip_hash(ip),
                message_id=req.message_id,
                cancel_event=cancel_event,
            ):
                yield chunk
        finally:
            watcher.cancel()

    return StreamingResponse(
        _stream_with_disconnect_watch(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _watch_disconnect(request: Request, cancel_event: asyncio.Event) -> None:
    """Set `cancel_event` if the client closes the connection mid-stream."""
    try:
        while not cancel_event.is_set():
            if await request.is_disconnected():
                cancel_event.set()
                return
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.debug(f"[edu_browser] disconnect watcher: {e}")


# ───────────────────────── Public: health ─────────────────────────

@router.get("/edu/health")
async def edu_health():
    """Smoke endpoint: reader stats + pipeline stats + redis cache stats."""
    total = _redis_hit_count + _redis_miss_count
    redis_hit_rate = (_redis_hit_count / total * 100) if total else 0.0
    return {
        "ok": True,
        "reader": get_reader_stats(),
        "pipeline": get_grounded_pipeline_stats(),
        "redis_cache": {
            "hits": _redis_hit_count,
            "misses": _redis_miss_count,
            "hit_rate_pct": round(redis_hit_rate, 1),
        },
    }


# ───────────────────────── Admin: allowlist CRUD ─────────────────────────

@router.get("/admin/edu/allowlist")
async def admin_allowlist_list(_admin=Depends(get_admin_user)):
    await _refresh_overrides_cache(force=True)
    return {
        "effective": effective_allowlist(),
        "overrides": await list_overrides(),
    }


@router.post("/admin/edu/allowlist")
async def admin_allowlist_upsert(req: AllowlistUpsertReq, admin=Depends(get_admin_user)):
    try:
        doc = await upsert_override(
            req.domain, status=req.status, note=req.note,
            actor=admin.get("email", admin.get("id", "admin")),
        )
        return {"ok": True, "entry": doc}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=503, detail=str(re))


@router.delete("/admin/edu/allowlist/{domain}")
async def admin_allowlist_delete(domain: str, _admin=Depends(get_admin_user)):
    removed = await remove_override(domain)
    return {"ok": True, "removed": removed}


@router.get("/admin/edu/blocked-log")
async def admin_blocked_log(limit: int = 200, _admin=Depends(get_admin_user)):
    items = await list_blocked_requests(limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


# ───────────────────────── Admin: grounded-recall bench ─────────────────────────

@router.get("/admin/grounded-recall/latest")
async def admin_grounded_recall_latest(_admin=Depends(get_admin_user)):
    """Return the most recent grounded-answer recall benchmark run + baseline.

    The nightly job writes `bench/results/latest.json`; this endpoint
    surfaces it (plus the committed baseline) so the admin UI can render
    a retrieval-quality tile without running the bench in-process.
    """
    try:
        from bench.grounded_recall import find_latest_result, load_baseline
        latest = find_latest_result()
        baseline = load_baseline()
        return {
            "ok": True,
            "latest": latest,
            "baseline": baseline,
            "has_results": latest is not None,
        }
    except Exception as e:
        logger.warning(f"[admin] grounded-recall fetch failed: {e}")
        return {"ok": False, "error": str(e)[:200], "latest": None, "baseline": None}


__all__ = ["router"]
