"""Task #944 — Unified log explorer admin routes + ingest endpoint
+ Cloudflare GraphQL pull loop.

Endpoints
---------
* ``POST /api/logs/ingest``                       — token-auth (edge worker)
* ``GET  /api/admin/logs``                        — admin filter / list
* ``GET  /api/admin/logs/export``                 — admin streaming export
* ``GET  /api/admin/logs/trace/{cid}``            — admin trace lookup
* ``GET  /api/admin/logs/status``                 — admin config snapshot
* ``POST /api/admin/logs/pause``                  — admin kill-switch on
* ``POST /api/admin/logs/resume``                 — admin kill-switch off
* ``POST /api/admin/logs/rotate-token``           — admin token rotation
* ``DELETE /api/admin/logs``                      — admin destructive purge
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import random
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from auth_deps import get_admin_user
from deps import db
import unified_logs_dao as _dao
from db_ops import supa_insert_activity_log

logger = logging.getLogger(__name__)
router = APIRouter()

LOG_INGEST_TOKEN_HEADER = "x-logs-ingest-token"
LOG_INGEST_API_CONFIG_KEY = "unified_logs_ingest_token"
LOG_PAUSE_API_CONFIG_KEY = "unified_logs_paused"

CF_PULL_LOCK_ID = "unified_logs_cf_pull_lock"
CF_PULL_CURSOR_FIELD = "cursor"
CF_PULL_INTERVAL_S = int(os.environ.get("UNIFIED_LOGS_CF_PULL_INTERVAL_S", "60") or "60")
CF_PULL_LOOKBACK_MIN = int(os.environ.get("UNIFIED_LOGS_CF_PULL_LOOKBACK_MIN", "5") or "5")
CF_PULL_MAX_LOOKBACK_MIN = 60
CF_PULL_LIMIT = int(os.environ.get("UNIFIED_LOGS_CF_PULL_LIMIT", "200") or "200")


# ─────────────────────────────────────────────────────────────────────────────
# Token storage — env first, then api_config (admin can rotate at runtime)
# ─────────────────────────────────────────────────────────────────────────────


async def _resolve_ingest_token() -> Optional[str]:
    """Effective ingest token: api_config override beats env."""
    if db is not None:
        try:
            doc = await db.api_config.find_one({"_id": LOG_INGEST_API_CONFIG_KEY})
            if doc and isinstance(doc.get("token"), str) and doc["token"].strip():
                return doc["token"].strip()
        except Exception:
            pass
    raw = (os.environ.get("LOG_INGEST_TOKEN") or "").strip()
    return raw or None


async def _persist_ingest_token(token: str) -> None:
    if db is None:
        return
    await db.api_config.update_one(
        {"_id": LOG_INGEST_API_CONFIG_KEY},
        {"$set": {
            "token": token,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def _persist_pause_state(paused: bool) -> None:
    if db is None:
        return
    await db.api_config.update_one(
        {"_id": LOG_PAUSE_API_CONFIG_KEY},
        {"$set": {
            "paused": bool(paused),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def _hydrate_pause_state_from_db() -> None:
    """Boot-time pause hydration so a runtime toggle survives restarts."""
    if db is None:
        return
    try:
        doc = await db.api_config.find_one({"_id": LOG_PAUSE_API_CONFIG_KEY})
    except Exception:
        return
    if doc and "paused" in doc:
        _dao.set_runtime_pause(bool(doc["paused"]))


# ─────────────────────────────────────────────────────────────────────────────
# Ingest
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/logs/ingest")
async def ingest_logs(request: Request) -> JSONResponse:
    """Token-authenticated bulk ingest endpoint for the edge worker.

    Body shape::
        {
            "source": "edge",   # optional; defaults applied per-record
            "logs":   [ {...}, ... ]
        }

    Returns ``{accepted, dropped, paused}``. When the kill switch is
    on, every record is counted as ``dropped`` and ``paused=True`` so
    the worker stops retrying instantly.

    Auth: ``X-Logs-Ingest-Token`` header must equal the resolved token.
    The endpoint is intentionally NOT behind admin JWT — the worker
    cannot mint admin tokens. Defense in depth: the worker also passes
    ``X-Origin-Auth`` (the Cloud Run origin secret), which must already
    succeed before this handler runs.
    """
    token_provided = (request.headers.get(LOG_INGEST_TOKEN_HEADER) or "").strip()
    expected = await _resolve_ingest_token()
    if not expected:
        # No token configured → ingest is closed (fail-secure).
        raise HTTPException(status_code=503, detail="Ingest token not configured")
    if not token_provided or not secrets.compare_digest(token_provided, expected):
        raise HTTPException(status_code=401, detail="Invalid ingest token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    raw_logs = payload.get("logs")
    if not isinstance(raw_logs, list):
        raise HTTPException(status_code=400, detail="`logs` must be an array")
    if len(raw_logs) > _dao.MAX_INGEST_BATCH:
        raise HTTPException(
            status_code=413,
            detail=f"Batch too large (max {_dao.MAX_INGEST_BATCH})",
        )
    default_source = (payload.get("source") or "edge").strip() or "edge"
    if default_source not in _dao.ALLOWED_SOURCES:
        default_source = "edge"

    if _dao._logs_paused_env():
        return JSONResponse(
            status_code=202,
            content={"accepted": 0, "dropped": len(raw_logs), "paused": True},
        )

    result = await _dao.insert_logs(db, raw_logs, default_source=default_source)
    return JSONResponse(
        status_code=202,
        content={"accepted": result["accepted"], "dropped": result["dropped"],
                 "paused": False},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Admin filter / list
# ─────────────────────────────────────────────────────────────────────────────


def _parse_csv_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [s.strip().lower() for s in value.split(",") if s.strip()]


@router.get("/api/admin/logs")
async def admin_list_logs(
    sources: Optional[str] = Query(None, description="comma-sep source filter"),
    levels: Optional[str] = Query(None, description="comma-sep level filter"),
    status_min: Optional[int] = Query(None, ge=0, le=999),
    status_max: Optional[int] = Query(None, ge=0, le=999),
    route_prefix: Optional[str] = Query(None),
    correlation_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    before: Optional[str] = Query(None, description="cursor: timestamp from prev page"),
    limit: int = Query(_dao.DEFAULT_QUERY_LIMIT, ge=1, le=_dao.MAX_QUERY_LIMIT),
    admin: dict = Depends(get_admin_user),
):
    filters = {
        "sources": _parse_csv_list(sources),
        "levels": _parse_csv_list(levels),
        "status_min": status_min,
        "status_max": status_max,
        "route_prefix": route_prefix,
        "correlation_id": correlation_id,
        "q": q,
        "since": since,
        "until": until,
    }
    rows = await _dao.query_logs(db, filters=filters, limit=limit, before=before)
    total = await _dao.count_logs(db, filters)
    next_before = rows[-1]["timestamp"] if rows and len(rows) >= limit else None
    return {
        "logs": rows,
        "total": total,
        "total_capped": total >= _dao.MAX_COUNT,
        "next_before": next_before,
        "limit": limit,
    }


@router.get("/api/admin/logs/trace/{correlation_id}")
async def admin_trace_logs(correlation_id: str, admin: dict = Depends(get_admin_user)):
    rows = await _dao.fetch_trace(db, correlation_id)
    return {"correlation_id": correlation_id, "logs": rows, "total": len(rows)}


@router.get("/api/admin/logs/export")
async def admin_export_logs(
    fmt: str = Query("ndjson", regex="^(csv|ndjson)$"),
    sources: Optional[str] = Query(None),
    levels: Optional[str] = Query(None),
    status_min: Optional[int] = Query(None, ge=0, le=999),
    status_max: Optional[int] = Query(None, ge=0, le=999),
    route_prefix: Optional[str] = Query(None),
    correlation_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(5000, ge=1, le=50_000),
    admin: dict = Depends(get_admin_user),
):
    filters = {
        "sources": _parse_csv_list(sources),
        "levels": _parse_csv_list(levels),
        "status_min": status_min,
        "status_max": status_max,
        "route_prefix": route_prefix,
        "correlation_id": correlation_id,
        "q": q,
        "since": since,
        "until": until,
    }
    if fmt == "csv":
        return StreamingResponse(
            _stream_csv(filters, limit),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=unified_logs_{int(time.time())}.csv",
                "Cache-Control": "no-store",
            },
        )
    return StreamingResponse(
        _stream_ndjson(filters, limit),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f"attachment; filename=unified_logs_{int(time.time())}.ndjson",
            "Cache-Control": "no-store",
        },
    )


_CSV_FIELDS = (
    "timestamp", "source", "level", "status", "duration_ms", "method",
    "route", "country", "colo", "cache", "ray_id", "correlation_id",
    "user_agent", "message",
)


async def _stream_csv(filters: Dict[str, Any], limit: int):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    yield buf.getvalue().encode("utf-8")
    buf.seek(0); buf.truncate(0)
    async for doc in _dao.iter_export(db, filters, limit=limit):
        writer.writerow({k: doc.get(k) for k in _CSV_FIELDS})
        yield buf.getvalue().encode("utf-8")
        buf.seek(0); buf.truncate(0)


async def _stream_ndjson(filters: Dict[str, Any], limit: int):
    async for doc in _dao.iter_export(db, filters, limit=limit):
        # Drop the datetime-only ``expire_at`` (already excluded by
        # iter_export's projection) and serialize defensively.
        yield (json.dumps(doc, default=str) + "\n").encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Status / pause / rotate-token / clear
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/admin/logs/status")
async def admin_logs_status(admin: dict = Depends(get_admin_user)):
    shipper = _dao.get_backend_shipper()
    paused = _dao._logs_paused_env()
    last_cf_pull: Optional[str] = None
    cf_cursor: Optional[str] = None
    if db is not None:
        try:
            lock = await db.job_locks.find_one({"_id": CF_PULL_LOCK_ID})
            if lock:
                last_cf_pull = lock.get("updated_at")
                cf_cursor = lock.get(CF_PULL_CURSOR_FIELD)
        except Exception:
            pass
    counts: Dict[str, Any] = {}
    if db is not None:
        try:
            for src in _dao.ALLOWED_SOURCES:
                counts[src] = await db[_dao.UNIFIED_LOGS_COLLECTION].count_documents(
                    {"source": src}, limit=_dao.MAX_COUNT,
                )
        except Exception:
            pass
    expected_token = await _resolve_ingest_token()
    return {
        "paused": paused,
        "ttl_days": _dao._ttl_days(),
        "max_ingest_batch": _dao.MAX_INGEST_BATCH,
        "edge_sample_rate_env": "EDGE_LOG_SAMPLE_RATE",
        "backend_sample_rate": shipper.sample_rate,
        "ingest_token_configured": bool(expected_token),
        "cf_pull_interval_s": CF_PULL_INTERVAL_S,
        "cf_pull_last_run": last_cf_pull,
        "cf_pull_cursor": cf_cursor,
        "shipper_stats": {
            "accepted": shipper.accepted,
            "flushed": shipper.flushed,
            "dropped_full": shipper.dropped_full,
            "dropped_paused": shipper.dropped_paused,
        },
        "counts": counts,
    }


@router.get("/api/admin/logs/sources/stats")
async def admin_logs_sources_stats(admin: dict = Depends(get_admin_user)):
    """Per-source counters (lighter than ``/status`` — used by the live
    tail header to show how many records each producer has ingested
    without re-fetching the full status payload)."""
    counts: Dict[str, Any] = {}
    last_seen: Dict[str, Optional[str]] = {}
    if db is not None:
        for src in _dao.ALLOWED_SOURCES:
            try:
                counts[src] = await db[_dao.UNIFIED_LOGS_COLLECTION].count_documents(
                    {"source": src}, limit=_dao.MAX_COUNT,
                )
            except Exception:
                counts[src] = 0
            try:
                doc = await db[_dao.UNIFIED_LOGS_COLLECTION].find_one(
                    {"source": src}, sort=[("timestamp", -1)],
                    projection={"timestamp": 1, "_id": 0},
                )
                last_seen[src] = (doc or {}).get("timestamp") if doc else None
            except Exception:
                last_seen[src] = None
    return {"counts": counts, "last_seen": last_seen}


@router.post("/api/admin/logs/cf/pull")
async def admin_logs_cf_pull(admin: dict = Depends(get_admin_user)):
    """Manual trigger of one Cloudflare GraphQL pull tick. Useful when
    debugging or after rotating the CF token — the admin doesn't have
    to wait for the next scheduled iteration of the background loop."""
    res = await _try_run_cf_pull_once()
    await supa_insert_activity_log({
        "id": str(uuid.uuid4()),
        "action": "unified_logs_cf_pull_manual",
        "details": (
            f"Manual CF pull: ok={res.get('ok')} accepted={res.get('accepted', 0)} "
            f"dropped={res.get('dropped', 0)} reason={res.get('reason') or '-'}"
        ),
        "level": "info",
        "admin_name": admin.get("name") or admin.get("username") or "Admin",
        "admin_email": admin.get("email", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return res


@router.post("/api/admin/logs/pause")
async def admin_logs_pause(admin: dict = Depends(get_admin_user)):
    _dao.set_runtime_pause(True)
    await _persist_pause_state(True)
    await supa_insert_activity_log({
        "id": str(uuid.uuid4()),
        "action": "unified_logs_paused",
        "details": "Unified logs ingest paused via admin panel",
        "level": "warning",
        "admin_name": admin.get("name") or admin.get("username") or "Admin",
        "admin_email": admin.get("email", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"paused": True}


@router.post("/api/admin/logs/resume")
async def admin_logs_resume(admin: dict = Depends(get_admin_user)):
    _dao.set_runtime_pause(False)
    await _persist_pause_state(False)
    await supa_insert_activity_log({
        "id": str(uuid.uuid4()),
        "action": "unified_logs_resumed",
        "details": "Unified logs ingest resumed via admin panel",
        "level": "info",
        "admin_name": admin.get("name") or admin.get("username") or "Admin",
        "admin_email": admin.get("email", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"paused": False}


@router.post("/api/admin/logs/rotate-token")
async def admin_logs_rotate_token(admin: dict = Depends(get_admin_user)):
    """Generate + persist a new ingest token. The plaintext is returned
    ONCE — there is no read-back endpoint, so the admin must copy it
    to the worker secret store right away.

    The activity-log breadcrumb records WHO rotated the token, not the
    token itself, so the audit trail does not leak the secret.
    """
    new_token = secrets.token_urlsafe(48)
    await _persist_ingest_token(new_token)
    await supa_insert_activity_log({
        "id": str(uuid.uuid4()),
        "action": "unified_logs_token_rotated",
        "details": "Rotated unified-logs ingest token; copy to edge worker now",
        "level": "warning",
        "admin_name": admin.get("name") or admin.get("username") or "Admin",
        "admin_email": admin.get("email", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"token": new_token, "rotated_at": datetime.now(timezone.utc).isoformat()}


@router.delete("/api/admin/logs")
async def admin_clear_logs(
    sources: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user),
):
    """Destructive purge. Optionally scope by ``sources`` so an admin
    can clear (e.g.) only ``edge`` while keeping ``backend`` history.
    Drops a self-audit breadcrumb in activity_log.

    SAFETY: if the caller supplied ``sources=`` but every value was
    rejected (typo, unknown name), we 400 instead of silently
    broadening to a full purge. A full purge requires explicitly
    omitting the parameter altogether — never ``sources=garbage``.
    """
    parsed_sources = _parse_csv_list(sources)
    # Distinguish "user passed nothing → full purge is intentional"
    # from "user passed a value that we couldn't honour → accidental
    # full purge". The raw query string is the source of truth, NOT
    # whether the parsed list is empty (which the same for both cases).
    if sources is not None and sources.strip():
        valid_sources = [s for s in parsed_sources if s in _dao.ALLOWED_SOURCES]
        invalid_sources = [s for s in parsed_sources if s not in _dao.ALLOWED_SOURCES]
        if not valid_sources:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Refusing destructive purge: 'sources' was supplied but "
                    f"none of {invalid_sources or [sources]} are recognised. "
                    f"Allowed values: {sorted(_dao.ALLOWED_SOURCES)}. "
                    f"To purge ALL sources, omit the 'sources' query param entirely."
                ),
            )
        # Drop unknown values silently from this point on so the DAO
        # only ever sees recognised source names.
        parsed_sources = valid_sources
    filters = {"sources": parsed_sources}
    deleted = await _dao.clear_logs(db, filters=filters)
    await supa_insert_activity_log({
        "id": str(uuid.uuid4()),
        "action": "unified_logs_cleared",
        "details": (
            f"Cleared {deleted} unified-log entr{'y' if deleted == 1 else 'ies'}"
            + (f" (sources={sources})" if sources else "")
        ),
        "level": "danger",
        "admin_name": admin.get("name") or admin.get("username") or "Admin",
        "admin_email": admin.get("email", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"deleted": deleted, "sources": _parse_csv_list(sources)}


# ─────────────────────────────────────────────────────────────────────────────
# Cloudflare GraphQL pull loop
# ─────────────────────────────────────────────────────────────────────────────


def normalize_cf_http_request_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a single ``httpRequestsAdaptiveGroups`` row into the
    unified record shape (without inserting it).

    Pulled out into a pure helper so unit tests can lock down the
    field mapping without spinning up Mongo.
    """
    dim = row.get("dimensions") or {}
    avg = (row.get("avg") or {})
    # ``httpRequestsAdaptiveGroups`` exposes the per-bucket request count
    # at the **top level** as ``count`` (not under ``sum.requests`` — that
    # field does not exist in the adaptive sampling schema and yields a
    # GraphQL validation error). We tolerate either shape so older callers
    # don't break, but the live CF response uses ``count``.
    request_count = row.get("count")
    if request_count is None:
        request_count = (row.get("sum") or {}).get("requests")
    status = dim.get("edgeResponseStatus") or dim.get("originResponseStatus")
    cache_status = (dim.get("cacheStatus") or "").lower() or None
    cache: Optional[str]
    if cache_status in ("hit", "miss", "bypass", "expired", "stale"):
        cache = cache_status
    elif cache_status in ("dynamic", "none"):
        cache = "dynamic"
    else:
        cache = None
    minute_iso = (dim.get("datetime") or dim.get("datetimeMinute")
                  or dim.get("date") or "")
    method = (dim.get("clientRequestHTTPMethodName")
              or dim.get("clientRequestHTTPMethod") or "")
    path = dim.get("clientRequestPath") or dim.get("requestPath") or ""
    colo = dim.get("coloCode") or dim.get("colo") or ""
    # The idempotency key MUST include every dimension the GraphQL
    # ``httpRequestsAdaptiveGroups`` query groups by — otherwise two
    # legitimately-distinct buckets (e.g. same minute+path+status from
    # two different countries or hosts) would collide on the same _id
    # and the second one would be silently dropped as an E11000
    # duplicate. The dimensions list MUST stay in lockstep with the
    # ``dimensions`` block in ``_CF_QUERY``.
    host = dim.get("clientRequestHTTPHost") or dim.get("host") or ""
    country = dim.get("clientCountryName") or dim.get("countryName") or ""
    edge_status = dim.get("edgeResponseStatus")
    origin_status = dim.get("originResponseStatus")
    cache_status_raw = dim.get("cacheStatus") or ""
    idem = (f"cf|{minute_iso}|{method}|{path}|{host}|{country}|{colo}"
            f"|{edge_status}|{origin_status}|{cache_status_raw}")
    rec_id = "cf_" + hashlib.sha1(idem.encode("utf-8")).hexdigest()
    return {
        "_id": rec_id,
        "source": "cloudflare",
        "level": _level_for_status_int(status),
        "timestamp": dim.get("datetime") or dim.get("datetimeMinute") or dim.get("date"),
        "message": _cf_message(dim, status, request_count or 1),
        "status": status,
        "duration_ms": _coerce_origin_duration(avg.get("originResponseDurationMs")
                                               or dim.get("originResponseDurationMs")),
        "method": dim.get("clientRequestHTTPMethodName") or dim.get("clientRequestHTTPMethod"),
        "route": dim.get("clientRequestPath") or dim.get("requestPath"),
        "country": dim.get("clientCountryName") or dim.get("countryName"),
        "colo": dim.get("coloCode") or dim.get("colo"),
        "cache": cache,
        # NOTE: ``httpRequestsAdaptiveGroups`` is an *aggregated* dataset
        # so per-request ray identifiers are not exposed by the schema
        # (the field ``rayName`` only exists on the per-event Logpush
        # dataset, which requires Enterprise). Leave the cid empty for
        # cloudflare rows — correlation comes from the worker shipper
        # which DOES have access to ``cf-ray`` per request.
        "ray_id": None,
        "correlation_id": None,
        "extra": {
            "host": dim.get("clientRequestHTTPHost") or dim.get("host"),
            "edge_status": dim.get("edgeResponseStatus"),
            "origin_status": dim.get("originResponseStatus"),
            "request_count": request_count,
        },
    }


def _level_for_status_int(status: Any) -> str:
    try:
        s = int(status)
    except (TypeError, ValueError):
        return "info"
    if s >= 500:
        return "error"
    if s >= 400:
        return "warn"
    return "info"


def _coerce_origin_duration(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _cf_message(dim: Dict[str, Any], status: Any, count: Any) -> str:
    method = dim.get("clientRequestHTTPMethodName") or "GET"
    path = dim.get("clientRequestPath") or "/"
    suffix = f" → {status}" if status else ""
    if count and int(count) > 1:
        suffix += f" ×{count}"
    return f"{method} {path}{suffix}"


_CF_QUERY = """
query UnifiedLogsPull($zone: String!, $since: Time!, $until: Time!, $limit: Int!) {
  viewer {
    zones(filter: {zoneTag: $zone}) {
      httpRequestsAdaptiveGroups(
        limit: $limit,
        filter: {datetime_geq: $since, datetime_lt: $until},
        orderBy: [datetimeMinute_DESC]
      ) {
        dimensions {
          datetimeMinute
          edgeResponseStatus
          originResponseStatus
          cacheStatus
          clientRequestPath
          clientRequestHTTPMethodName
          clientRequestHTTPHost
          clientCountryName
          coloCode
        }
        avg { originResponseDurationMs }
        count
      }
    }
  }
}
""".strip()


async def _try_run_cf_pull_once(now_utc: Optional[datetime] = None,
                                graphql_callable=None) -> Dict[str, Any]:
    """One iteration of the Cloudflare pull. Factored out so tests can
    inject a fake ``_graphql_query`` and assert on the return shape.

    Returns ``{ok, accepted, dropped, since, until, reason?}``.
    """
    if db is None:
        return {"ok": False, "reason": "no_db"}
    from config import CF_ZONE_ID, CF_ANALYTICS_API_TOKEN
    if not CF_ZONE_ID or not CF_ANALYTICS_API_TOKEN:
        return {"ok": False, "reason": "cf_not_configured"}
    if graphql_callable is None:
        from cloudflare_client import _graphql_query
        graphql_callable = _graphql_query

    now = now_utc or datetime.now(timezone.utc)
    # Cursor in Mongo so an isolate restart doesn't re-pull a window.
    try:
        lock = await db.job_locks.find_one({"_id": CF_PULL_LOCK_ID}) or {}
    except Exception:
        lock = {}
    cursor_iso = lock.get(CF_PULL_CURSOR_FIELD)
    if cursor_iso:
        try:
            since = datetime.fromisoformat(cursor_iso.replace("Z", "+00:00"))
        except Exception:
            since = now - timedelta(minutes=CF_PULL_LOOKBACK_MIN)
    else:
        since = now - timedelta(minutes=CF_PULL_LOOKBACK_MIN)
    # CF aggregates by minute. Stop the window at the previous minute
    # to avoid double-counting an in-flight bucket.
    until = now.replace(second=0, microsecond=0)
    if until <= since:
        return {"ok": True, "accepted": 0, "dropped": 0,
                "since": since.isoformat(), "until": until.isoformat(),
                "reason": "empty_window"}
    # Cap lookback so a long isolate sleep doesn't pull a huge window.
    if (until - since) > timedelta(minutes=CF_PULL_MAX_LOOKBACK_MIN):
        since = until - timedelta(minutes=CF_PULL_MAX_LOOKBACK_MIN)

    try:
        resp = await graphql_callable(_CF_QUERY, {
            "zone": CF_ZONE_ID,
            "since": since.isoformat().replace("+00:00", "Z"),
            "until": until.isoformat().replace("+00:00", "Z"),
            "limit": CF_PULL_LIMIT,
        })
    except Exception as exc:
        logger.warning("[unified_logs] CF pull GraphQL failed: %s", exc)
        return {"ok": False, "reason": "graphql_error"}
    rows: List[Dict[str, Any]] = []
    try:
        zones = (((resp or {}).get("data") or {}).get("viewer") or {}).get("zones") or []
        for z in zones:
            for grp in (z.get("httpRequestsAdaptiveGroups") or []):
                rows.append(normalize_cf_http_request_row(grp))
    except Exception as exc:
        logger.warning("[unified_logs] CF pull parse failed: %s", exc)
        return {"ok": False, "reason": "parse_error"}

    result = {"accepted": 0, "dropped": 0}
    if rows:
        result = await _dao.insert_logs(db, rows, default_source="cloudflare")
    # Advance cursor to ``until`` so the next iteration picks up only
    # new data.
    try:
        await db.job_locks.update_one(
            {"_id": CF_PULL_LOCK_ID},
            {"$set": {
                CF_PULL_CURSOR_FIELD: until.isoformat(),
                "updated_at": now.isoformat(),
                "last_accepted": result["accepted"],
                "last_dropped": result["dropped"],
            }},
            upsert=True,
        )
    except Exception as exc:
        logger.warning("[unified_logs] CF pull cursor write failed: %s", exc)

    return {
        "ok": True,
        "accepted": result["accepted"],
        "dropped": result["dropped"],
        "since": since.isoformat(),
        "until": until.isoformat(),
    }


async def _unified_logs_cf_pull_loop():
    """Periodic Cloudflare pull. Runs every ``CF_PULL_INTERVAL_S``
    seconds, idempotent across multiple isolates via the cursor doc.

    On consecutive failures (raised exceptions OR ``ok=False`` results
    that aren't a benign no-op like ``empty_window``/``cf_not_configured``)
    we back off exponentially with jitter so a flapping CF endpoint
    doesn't burn the analytics quota. The backoff is capped at 30 min
    and resets to the base interval on the next successful tick.
    """
    # 30s warmup so the loop doesn't race ensure_indexes during
    # cold-start.
    await asyncio.sleep(30)
    consecutive_failures = 0
    base_interval = max(15, int(CF_PULL_INTERVAL_S))
    max_backoff = 30 * 60  # 30 min ceiling
    while True:
        try:
            res = await _try_run_cf_pull_once()
            reason = (res or {}).get("reason")
            # ``empty_window`` and ``cf_not_configured`` are not actual
            # failures — treat them as success for backoff purposes so
            # we don't punish a quiet zone or a deployment without CF.
            if (res or {}).get("ok") or reason in ("empty_window", "cf_not_configured"):
                consecutive_failures = 0
            else:
                consecutive_failures += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            consecutive_failures += 1
            logger.warning("[unified_logs] CF pull loop tick failed: %s", exc)

        if consecutive_failures == 0:
            sleep_for = base_interval
        else:
            # 2^n backoff, capped, with ±25% jitter to spread retries
            # across replicas.
            backoff = min(max_backoff, base_interval * (2 ** min(consecutive_failures, 8)))
            jitter = backoff * 0.25 * (random.random() * 2 - 1)
            sleep_for = max(base_interval, int(backoff + jitter))
            logger.info(
                "[unified_logs] CF pull backoff: failures=%d sleeping=%ds",
                consecutive_failures, sleep_for,
            )
        await asyncio.sleep(sleep_for)


# Test-only knob: lets pytest force the loop body without actually
# starting the periodic task.
_run_cf_pull_once = _try_run_cf_pull_once
