"""SEO Phase A — content-time fan-out orchestration.

When the AI content generator persists a freshly-generated page, three
crawler-facing signals must fire so search bots learn about the new
content within seconds (instead of waiting up to 5 min for the next
sitemap-diff loop) and so the first crawler hit lands on a warm edge
cache (instead of the cold first-fetch that drags Googlebot's edge
cache-hit ratio down to ~33%).

Signals fired per page:
  1. IndexNow queue + flush (Bing, Yandex)               — bot_discovery
  2. Cloudflare cache purge for the page + ancestors     — cloudflare_client
  3. Synthetic Googlebot-UA GET to populate BOT_HTML_CACHE — bot_discovery
  4. Google Indexing API URL_UPDATED (Phase C)           — google_indexing_client

All four run as fire-and-forget background tasks; failures are logged
but never raise back to the generator.

A ring buffer of the most recent fan-outs is exposed via
`recent_fanout_events()` and surfaced through the admin endpoint
`GET /admin/seo/fanout-recent` for verification.

The whole layer can be killswitch-disabled by setting the env var
`SEO_FANOUT_ENABLED=false`; in tests it defaults to false unless
explicitly overridden, so existing test suites don't suddenly start
making outbound HTTP calls.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


_RING_MAX = 50
_FANOUT_RING: "deque[dict]" = deque(maxlen=_RING_MAX)


def is_enabled() -> bool:
    """Return whether content-time fan-out is enabled.

    Default: enabled in production-like environments, disabled when
    `PYTEST_CURRENT_TEST` is set (so existing tests don't fire outbound
    HTTP). Either default can be overridden by setting `SEO_FANOUT_ENABLED`
    explicitly to `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off`.
    """
    raw = os.getenv("SEO_FANOUT_ENABLED")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return True


def recent_fanout_events(limit: int = 50) -> list:
    """Most recent fan-out events (oldest → newest), capped at `limit`."""
    if limit <= 0:
        return []
    snapshot = list(_FANOUT_RING)
    if limit >= len(snapshot):
        return snapshot
    return snapshot[-limit:]


def _record_event(event: dict) -> None:
    _FANOUT_RING.append(event)


def _ok(result) -> str:
    """Reduce an async-gather result (bool / int / Exception) to a status."""
    if isinstance(result, BaseException):
        return f"error:{type(result).__name__}"
    if result is None or result is False:
        return "skipped"
    return "ok"


def _parent_subject_url(page_doc: dict) -> Optional[str]:
    try:
        from routes.bot_discovery import BASE_URL
    except Exception:  # pragma: no cover — only fires if import is broken
        return None
    bs = page_doc.get("board_slug") or ""
    cs = page_doc.get("class_slug") or ""
    ss = page_doc.get("subject_slug") or ""
    if bs and cs and ss:
        return f"{BASE_URL}/{bs}/{cs}/{ss}"
    return None


async def _do_indexnow(url: str, source: str) -> bool:
    """Queue + flush this URL through the IndexNow batcher."""
    from routes.bot_discovery import _schedule_indexnow_for_url
    return await _schedule_indexnow_for_url(url, source=source)


async def _do_cache_purge(url: str, parent_subject_url: Optional[str], page_type: str) -> bool:
    from cloudflare_client import purge_for_content_change
    return await purge_for_content_change(
        url, page_type=page_type, parent_subject_url=parent_subject_url
    )


async def _do_prewarm(urls: list[str]) -> bool:
    from routes.bot_discovery import prewarm_bot_cache
    return await prewarm_bot_cache(urls)


async def _do_google_indexing(url: str, source: str) -> bool:
    """Notify Google Indexing API (Phase C). Returns True on 2xx, False on
    any skip/error so the ring-buffer status reflects reality."""
    try:
        from google_indexing_client import notify_url_updated
    except Exception as e:  # pragma: no cover — import is trivially present
        logger.debug(f"seo_fanout: google_indexing_client import failed: {e}")
        return False
    res = await notify_url_updated(url, source=source)
    return (res or {}).get("status") == "ok"


# Task #246 — Delta sitemap ping constants.
_DELTA_SITEMAP_URL = "https://syrabit.ai/api/seo/sitemap-delta.xml"
_GOOGLE_SITEMAP_PING_TPL = "https://www.google.com/ping?sitemap={sitemap}"


async def _do_ping_delta_sitemap() -> bool:
    """Task #246: After a page is published/updated, ping Google with the
    delta sitemap URL so it re-fetches the 48-hour rolling sub-sitemap.
    Also schedules an IndexNow notification for the delta sitemap itself.

    This is a best-effort fire-and-forget helper: failures are logged but
    never propagate back to the content generator.
    """
    import httpx
    from urllib.parse import quote as _quote
    ping_url = _GOOGLE_SITEMAP_PING_TPL.format(sitemap=_quote(_DELTA_SITEMAP_URL, safe=""))
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(ping_url)
        ok = 200 <= resp.status_code < 300
        if not ok:
            logger.debug(
                "seo_fanout: delta sitemap ping returned %d", resp.status_code
            )
        return ok
    except Exception as e:
        logger.debug("seo_fanout: delta sitemap ping failed: %s", e)
        return False


async def _run_fanout(url: str, parent_subject_url: Optional[str],
                      page_type: str, source: str, event: dict) -> None:
    try:
        results = await asyncio.gather(
            _do_indexnow(url, source),
            _do_cache_purge(url, parent_subject_url, page_type),
            _do_prewarm([u for u in [url, parent_subject_url] if u]),
            _do_google_indexing(url, source),
            _do_ping_delta_sitemap(),
            return_exceptions=True,
        )
    except Exception as e:  # defensive: gather() shouldn't raise here
        logger.warning(f"seo_fanout: orchestration error for {url}: {e}")
        event["error"] = str(e)
        event["completed_at"] = datetime.now(timezone.utc).isoformat()
        return

    event["indexnow"] = _ok(results[0])
    event["cache_purge"] = _ok(results[1])
    event["prewarm"] = _ok(results[2])
    event["google_indexing"] = _ok(results[3])
    event["delta_sitemap_ping"] = _ok(results[4])
    event["completed_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        "seo_fanout: url=%s indexnow=%s cache_purge=%s prewarm=%s "
        "google_indexing=%s delta_ping=%s source=%s",
        url, event["indexnow"], event["cache_purge"], event["prewarm"],
        event["google_indexing"], event["delta_sitemap_ping"], source,
    )


def fanout_for_page(page_doc: dict, source: str = "seo_generate") -> Optional[asyncio.Task]:
    """Fire-and-forget: schedule IndexNow + cache purge + bot-cache prewarm
    for a freshly persisted page document. Returns the background Task or
    None if the killswitch is off / there's no running event loop / the
    page document doesn't resolve to a public URL.

    Never raises — all errors are logged.
    """
    if not is_enabled():
        return None
    try:
        from routes.bot_discovery import _page_doc_to_url
        url = _page_doc_to_url(page_doc)
    except Exception as e:
        logger.debug(f"seo_fanout: url resolution failed: {e}")
        return None
    if not url:
        return None

    page_type = page_doc.get("page_type", "notes") or "notes"
    parent_subject_url = _parent_subject_url(page_doc)

    event = {
        "event_id": uuid.uuid4().hex[:10],
        "url": url,
        "parent_subject_url": parent_subject_url,
        "page_type": page_type,
        "source": source,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "indexnow": "pending",
        "cache_purge": "pending",
        "prewarm": "pending",
    }
    _record_event(event)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from a sync context with no event loop — log and skip.
        # The sitemap-diff loop will pick up the URL on its next pass, so
        # signals aren't lost; they're just delayed.
        logger.debug(
            "seo_fanout: no running event loop, deferring fan-out for %s", url
        )
        event["completed_at"] = datetime.now(timezone.utc).isoformat()
        event["indexnow"] = event["cache_purge"] = event["prewarm"] = "deferred"
        return None

    return loop.create_task(_run_fanout(url, parent_subject_url, page_type, source, event))


def fanout_for_url(url: str, source: str = "fanout_url",
                   page_type: str = "notes",
                   parent_subject_url: Optional[str] = None) -> Optional[asyncio.Task]:
    """SEO Phase D — fan-out a *single absolute URL* (rather than an
    `seo_pages` doc) through the same IndexNow + cache purge + prewarm +
    Google-Indexing chain used by `fanout_for_page`.

    Used by the auto-cross-link path (`syllabus_linker.cross_link_for_new_chapter`)
    where the patched targets are subject hubs and chapter pages — neither
    of which lives in `seo_pages` — so we can't reuse `fanout_for_page` as-is.
    Falls back gracefully (returns None) when the killswitch is off, no
    event loop is running, or `url` is empty. Never raises.
    """
    if not is_enabled() or not url:
        return None

    event = {
        "event_id": uuid.uuid4().hex[:10],
        "url": url,
        "parent_subject_url": parent_subject_url,
        "page_type": page_type,
        "source": source,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "indexnow": "pending",
        "cache_purge": "pending",
        "prewarm": "pending",
    }
    _record_event(event)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("seo_fanout: no running event loop, deferring fan-out for %s", url)
        event["completed_at"] = datetime.now(timezone.utc).isoformat()
        event["indexnow"] = event["cache_purge"] = event["prewarm"] = "deferred"
        return None

    return loop.create_task(_run_fanout(url, parent_subject_url, page_type, source, event))


def fanout_for_urls(urls: list[str], source: str = "cross_link") -> list:
    """Convenience wrapper — fan out a batch of URLs in parallel."""
    tasks = []
    for u in urls or []:
        t = fanout_for_url(u, source=source)
        if t is not None:
            tasks.append(t)
    return tasks
