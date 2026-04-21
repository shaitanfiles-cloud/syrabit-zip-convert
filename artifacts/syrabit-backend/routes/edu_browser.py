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

import time

from auth_deps import (
    get_admin_user, check_rate_limit, get_current_user_optional,
    get_educator_user,
)
from edu_allowlist import (
    effective_allowlist, list_overrides, upsert_override,
    remove_override, list_blocked_requests, _refresh_overrides_cache,
    BASE_ALLOWLIST, EDU_REQUESTED_SITES_COLLECTION, EDU_USER_STATE_COLLECTION,
    _normalize_domain, is_allowed_url, is_domain_hard_blocked,
)
from edu_reader import fetch_and_extract, get_reader_stats, probe_site_safety
from grounded_answer import stream_grounded_answer, get_grounded_pipeline_stats
from cache import _redis_hit_count, _redis_miss_count
from deps import db, is_mongo_available

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


class RequestSiteReq(BaseModel):
    domain: str = Field(..., min_length=3, max_length=253)
    reason: str = Field("", max_length=500)


class StateSaveReq(BaseModel):
    tabs: list = Field(default_factory=list)
    bookmarks: list = Field(default_factory=list)
    history: list = Field(default_factory=list)


class AllowlistUpsertReq(BaseModel):
    domain: str = Field(..., min_length=3, max_length=253)
    status: str = "allowed"  # allowed | blocked
    note: str = ""


class EducatorSubmitReq(BaseModel):
    domain: str = Field(..., min_length=3, max_length=253)
    note: str = Field("", max_length=280)


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


# ───────────────────────── Public: allowlist & site requests ─────────────────────────

@router.get("/edu/allowlist")
async def public_allowlist():
    """Public snapshot of allowed domains for the address-bar UI."""
    await _refresh_overrides_cache()
    snap = effective_allowlist()
    base = sorted(set(snap.get("base", [])) | set(snap.get("operator_allowed", [])))
    blocked = sorted(set(snap.get("operator_blocked", [])) | set(snap.get("hard_denied", [])))
    return {
        "ok": True,
        "domains": base,
        "blocked": blocked,
        "edu_suffixes": snap.get("edu_suffixes", []),
    }


@router.post("/edu/check-url")
async def public_check_url(payload: dict):
    """Lightweight allow check used by the browser shell before fetching."""
    url = (payload or {}).get("url", "")
    allowed, reason = await is_allowed_url(url)
    return {"ok": True, "allowed": allowed, "reason": reason}


@router.post("/edu/request-site")
async def request_site(req: RequestSiteReq, request: Request, user=Depends(get_current_user_optional)):
    ip = _client_ip(request)
    if not check_rate_limit(f"edu_req_site:{ip}", max_requests=10, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many requests; try again later.")
    domain = _normalize_domain(req.domain)
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="storage_unavailable")
    actor = (user or {}).get("email", "") or (user or {}).get("id", "") or _ip_hash(ip)
    try:
        await db[EDU_REQUESTED_SITES_COLLECTION].update_one(
            {"domain": domain},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {"domain": domain, "first_at": time.time()},
                "$set": {"last_at": time.time(), "last_actor": actor[:120], "last_reason": req.reason[:500]},
            },
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[edu_browser] request-site insert failed: {e}")
        raise HTTPException(status_code=500, detail="storage_failed")
    return {"ok": True, "domain": domain}


# ───────────────────────── Educator: self-serve allowlist ─────────────────────

_RATE_EDUCATOR_SUBMIT_PER_USER = 12  # req / hour


@router.post("/edu/educator/submit-site")
async def educator_submit_site(
    req: EducatorSubmitReq, request: Request, educator=Depends(get_educator_user),
):
    """Educator self-serve: submit a domain that auto-approves after a
    kid-safe + robots.txt safety probe. Admins can always revoke later
    via the existing allowlist management endpoints.
    """
    actor = (educator or {}).get("email", "") or (educator or {}).get("id", "")
    rl_key = f"edu_edu_submit:{(educator or {}).get('id', _client_ip(request))}"
    if not check_rate_limit(rl_key, max_requests=_RATE_EDUCATOR_SUBMIT_PER_USER, window_seconds=3600):
        raise HTTPException(
            status_code=429,
            detail=f"Educator submission limit reached ({_RATE_EDUCATOR_SUBMIT_PER_USER}/hour).",
            headers={"Retry-After": "300"},
        )

    domain = _normalize_domain(req.domain)
    if not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="Invalid domain")

    # Cheap fast-path: if the domain is already allowed (base list, edu
    # suffix, or an operator_allowed override) we short-circuit without
    # burning a network fetch.
    allowed_already, reason_already = await is_allowed_url(f"https://{domain}/")
    if allowed_already:
        return {
            "ok": True,
            "domain": domain,
            "status": "already_allowed",
            "detail": reason_already,
        }

    # Refuse anything admin has hard-blocked / operator-blocked outright.
    blocked, why = await is_domain_hard_blocked(domain)
    if blocked:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "domain": domain, "error": why,
                     "detail": "Domain is blocked and cannot be auto-approved."},
        )

    probe = await probe_site_safety(domain)
    if not probe.get("ok"):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "domain": domain,
                "error": probe.get("reason", "probe_failed"),
                "probe": probe,
                "detail": "Safety probe failed — site was not auto-approved.",
            },
        )

    note = req.note.strip()[:240] if req.note else ""
    auto_note = f"Auto-approved by educator {actor or 'unknown'}"
    if note:
        auto_note = f"{auto_note}: {note}"
    try:
        entry = await upsert_override(
            domain,
            status="allowed",
            note=auto_note,
            actor=actor[:120] or "educator",
            source="educator",
            extra={
                "kid_safe_density": probe.get("kid_safe_density"),
                "http_status": probe.get("http_status"),
                "robots_ok": probe.get("robots_ok"),
                "text_chars": probe.get("text_chars"),
            },
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=503, detail=str(re))

    return {
        "ok": True,
        "domain": domain,
        "status": "auto_approved",
        "entry": entry,
        "probe": {
            "kid_safe": probe.get("kid_safe"),
            "kid_safe_density": probe.get("kid_safe_density"),
            "robots_ok": probe.get("robots_ok"),
            "http_status": probe.get("http_status"),
        },
    }


# ───────────────────────── Public: per-user state (tabs/bookmarks/history) ────

_STATE_MAX_TABS = 30
_STATE_MAX_BOOKMARKS = 200
_STATE_MAX_HISTORY = 200


def _trim_state(payload: StateSaveReq) -> dict:
    return {
        "tabs": (payload.tabs or [])[:_STATE_MAX_TABS],
        "bookmarks": (payload.bookmarks or [])[:_STATE_MAX_BOOKMARKS],
        "history": (payload.history or [])[:_STATE_MAX_HISTORY],
    }


def _state_actor(request: Request, user) -> tuple[str, str]:
    if user and user.get("id"):
        return "user", user["id"]
    anon = request.headers.get("x-anon-id", "").strip()[:80]
    if anon:
        return "anon", anon
    return "ip", _ip_hash(_client_ip(request))


@router.get("/edu/state")
async def get_state(request: Request, user=Depends(get_current_user_optional)):
    if not await is_mongo_available():
        return {"ok": True, "state": None, "stored": False}
    kind, actor = _state_actor(request, user)
    try:
        doc = await db[EDU_USER_STATE_COLLECTION].find_one(
            {"actor_kind": kind, "actor": actor}, {"_id": 0},
        )
    except Exception as e:
        logger.warning(f"[edu_browser] state load failed: {e}")
        return {"ok": True, "state": None, "stored": False}
    return {
        "ok": True,
        "state": doc.get("state") if doc else None,
        "stored": bool(doc),
        "scope": kind,
    }


@router.post("/edu/state")
async def save_state(payload: StateSaveReq, request: Request, user=Depends(get_current_user_optional)):
    ip = _client_ip(request)
    if not check_rate_limit(f"edu_state:{ip}", max_requests=60, window_seconds=60):
        raise HTTPException(status_code=429, detail="Save rate limit exceeded.")
    if not await is_mongo_available():
        return {"ok": False, "error": "storage_unavailable"}
    kind, actor = _state_actor(request, user)
    state = _trim_state(payload)
    try:
        await db[EDU_USER_STATE_COLLECTION].update_one(
            {"actor_kind": kind, "actor": actor},
            {"$set": {"state": state, "updated_at": time.time(),
                      "actor_kind": kind, "actor": actor}},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[edu_browser] state save failed: {e}")
        raise HTTPException(status_code=500, detail="storage_failed")
    return {"ok": True, "scope": kind, "saved": {
        "tabs": len(state["tabs"]), "bookmarks": len(state["bookmarks"]),
        "history": len(state["history"]),
    }}


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
async def admin_grounded_recall_latest(
    language: str | None = None,
    _admin=Depends(get_admin_user),
):
    """Return the most recent grounded-answer recall benchmark run + baseline.

    The nightly job writes `bench/results/latest.json` (global) and
    `bench/results/latest_<lang>.json` (per-language subsets, e.g.
    Assamese — Task #599); this endpoint surfaces them (plus the
    matching committed baseline) so the admin UI can render a
    retrieval-quality tile without running the bench in-process.

    Pass ``?language=as`` to read the Assamese-only subset.
    """
    try:
        from bench.grounded_recall import find_latest_result, load_baseline
        lang = (language or "").strip().lower() or None
        latest = find_latest_result(language=lang)
        baseline = load_baseline(language=lang)
        return {
            "ok": True,
            "language": lang,
            "latest": latest,
            "baseline": baseline,
            "has_results": latest is not None,
        }
    except Exception as e:
        logger.warning(f"[admin] grounded-recall fetch failed: {e}")
        return {"ok": False, "error": str(e)[:200], "latest": None, "baseline": None}


# ───────────────────────── Admin: requested-sites review queue ─────────────────────────

@router.get("/admin/edu/requested-sites")
async def admin_requested_sites(limit: int = 200, _admin=Depends(get_admin_user)):
    """Review queue for user-submitted "request this site" entries."""
    if not await is_mongo_available():
        return {"ok": True, "items": [], "count": 0}
    try:
        cur = db[EDU_REQUESTED_SITES_COLLECTION].find(
            {}, {"_id": 0}
        ).sort("last_at", -1).limit(max(1, min(limit, 1000)))
        items = [doc async for doc in cur]
    except Exception as e:
        logger.warning(f"[edu_browser] requested-sites list failed: {e}")
        items = []
    return {"ok": True, "items": items, "count": len(items)}


@router.delete("/admin/edu/requested-sites/{domain}")
async def admin_dismiss_requested_site(domain: str, _admin=Depends(get_admin_user)):
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="storage_unavailable")
    d = _normalize_domain(domain)
    if not d:
        raise HTTPException(status_code=400, detail="Invalid domain")
    try:
        await db[EDU_REQUESTED_SITES_COLLECTION].delete_one({"domain": d})
    except Exception as e:
        logger.warning(f"[edu_browser] requested-sites delete failed: {e}")
        raise HTTPException(status_code=500, detail="storage_failed")
    return {"ok": True, "domain": d}


__all__ = ["router"]
