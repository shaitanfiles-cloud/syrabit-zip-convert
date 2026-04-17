"""
Cloudflare Analytics API client for Syrabit.
Uses the Cloudflare GraphQL Analytics API to fetch zone-level traffic data.
Also provides edge cache purge functionality.
Falls back gracefully when credentials are missing/invalid.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

logger = logging.getLogger(__name__)

_cf_http: Optional["httpx.AsyncClient"] = None


def _get_cf_client():
    global _cf_http
    if _cf_http is None:
        import httpx
        _cf_http = httpx.AsyncClient(
            timeout=15,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
    return _cf_http


def _cfg():
    return {
        "api_token": os.getenv("CF_ANALYTICS_API_TOKEN", "").strip(),
        "zone_id": os.getenv("CF_ZONE_ID", "").strip(),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["api_token"] and c["zone_id"])


async def _graphql_query(query: str, variables: dict = None) -> Optional[dict]:
    if not is_configured():
        return None
    c = _cfg()
    try:
        body = {"query": query}
        if variables:
            body["variables"] = variables
        r = await _get_cf_client().post(
            "https://api.cloudflare.com/client/v4/graphql",
            json=body,
            headers={
                "Authorization": f"Bearer {c['api_token']}",
                "Content-Type": "application/json",
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            logger.warning(f"CF GraphQL errors: {data['errors']}")
            return None
        return data.get("data")
    except Exception as e:
        logger.warning(f"Cloudflare GraphQL query failed: {e}")
        return None


async def get_visitor_stats_cf(days: int = 7) -> Optional[dict]:
    if not is_configured():
        return None

    zone_id = _cfg()["zone_id"]
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")
    today_str = now.strftime("%Y-%m-%d")

    query = """
    query ZoneAnalytics($zoneTag: String!, $since: String!, $until: String!, $today: String!) {
      viewer {
        zones(filter: { zoneTag: $zoneTag }) {
          todayData: httpRequests1dGroups(
            filter: { date_geq: $today, date_leq: $today }
            limit: 1
          ) {
            sum {
              requests
              pageViews
            }
            uniq {
              uniques
            }
          }
          daily: httpRequests1dGroups(
            filter: { date_geq: $since, date_leq: $until }
            orderBy: [date_ASC]
            limit: 100
          ) {
            dimensions {
              date
            }
            sum {
              requests
              pageViews
            }
            uniq {
              uniques
            }
          }
        }
      }
    }
    """
    variables = {
        "zoneTag": zone_id,
        "since": start_date,
        "until": end_date,
        "today": today_str,
    }
    data = await _graphql_query(query, variables)
    if not data:
        return None

    try:
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return None
        zone = zones[0]

        today_data = zone.get("todayData", [{}])[0] if zone.get("todayData") else {}
        visitors_today = today_data.get("uniq", {}).get("uniques", 0)
        page_views_today = today_data.get("sum", {}).get("pageViews", 0)

        daily_visitors = []
        total_visitors = 0
        total_page_views = 0
        total_requests = 0
        for day in zone.get("daily", []):
            dims = day.get("dimensions", {})
            day_visitors = day.get("uniq", {}).get("uniques", 0)
            day_page_views = day.get("sum", {}).get("pageViews", 0)
            day_requests = day.get("sum", {}).get("requests", 0)
            total_visitors += day_visitors
            total_page_views += day_page_views
            total_requests += day_requests
            daily_visitors.append({
                "date": dims.get("date", ""),
                "visitors": day_visitors,
                "page_views": day_page_views,
                "requests": day_requests,
            })

        return {
            "total_visitors": total_visitors,
            "visitors_today": visitors_today,
            "page_views_today": page_views_today,
            "total_page_views": total_page_views,
            "total_requests": total_requests,
            "daily_visitors": daily_visitors,
            "source": "cloudflare",
        }
    except Exception as e:
        logger.warning(f"CF stats parsing failed: {e}")
        return None


async def get_historical_daily(days: int = 90) -> Optional[list]:
    if not is_configured():
        return None

    zone_id = _cfg()["zone_id"]
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    query = """
    query ZoneHistorical($zoneTag: String!, $since: String!, $until: String!) {
      viewer {
        zones(filter: { zoneTag: $zoneTag }) {
          httpRequests1dGroups(
            filter: { date_geq: $since, date_leq: $until }
            orderBy: [date_ASC]
            limit: 366
          ) {
            dimensions {
              date
            }
            sum {
              requests
              pageViews
            }
            uniq {
              uniques
            }
          }
        }
      }
    }
    """
    variables = {
        "zoneTag": zone_id,
        "since": start_date,
        "until": end_date,
    }
    data = await _graphql_query(query, variables)
    if not data:
        return None

    try:
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return None
        results = []
        for day in zones[0].get("httpRequests1dGroups", []):
            dims = day.get("dimensions", {})
            results.append({
                "date": dims.get("date", ""),
                "visitors": day.get("uniq", {}).get("uniques", 0),
                "page_views": day.get("sum", {}).get("pageViews", 0),
                "requests": day.get("sum", {}).get("requests", 0),
                "source": "cloudflare",
            })
        return results
    except Exception as e:
        logger.warning(f"CF historical parsing failed: {e}")
        return None


async def get_verified_bot_traffic_cf(since: datetime, until: datetime) -> Optional[dict]:
    """Pull Cloudflare's verified-bot breakdown for the zone between ``since``
    and ``until`` (both UTC-aware datetimes). Used by the Monday weekly
    bot-traffic report (Task #314) — see ``routes/bot_traffic_report.py``.

    Returns ``{"by_category": {...}, "bot_total": int, "bot_5xx": int,
    "source": "cloudflare"}``. Returns ``None`` if Cloudflare is not
    configured or the query fails (the caller treats ``None`` as a signal
    to fire a fallback admin alert)."""
    if not is_configured():
        return None

    zone_id = _cfg()["zone_id"]
    # Normalize both naive and timezone-aware inputs to UTC before
    # formatting, so a caller passing IST/PST times still produces a
    # correct UTC ISO string for Cloudflare.
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    else:
        since = since.astimezone(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    else:
        until = until.astimezone(timezone.utc)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_str = until.strftime("%Y-%m-%dT%H:%M:%SZ")

    query = """
    query VerifiedBots($zoneTag: String!, $since: Time!, $until: Time!) {
      viewer {
        zones(filter: { zoneTag: $zoneTag }) {
          categories: httpRequestsAdaptiveGroups(
            filter: {
              datetime_geq: $since,
              datetime_lt: $until,
              verifiedBotCategory_neq: ""
            }
            limit: 50
            orderBy: [count_DESC]
          ) {
            count
            dimensions { verifiedBotCategory }
          }
          bot_5xx: httpRequestsAdaptiveGroups(
            filter: {
              datetime_geq: $since,
              datetime_lt: $until,
              verifiedBotCategory_neq: "",
              edgeResponseStatus_geq: 500,
              edgeResponseStatus_lt: 600
            }
            limit: 1
          ) {
            count
          }
        }
      }
    }
    """
    variables = {"zoneTag": zone_id, "since": since_str, "until": until_str}
    data = await _graphql_query(query, variables)
    if not data:
        return None
    try:
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return None
        zone = zones[0]
        by_category: dict = {}
        total = 0
        for row in zone.get("categories", []) or []:
            name = (row.get("dimensions", {}) or {}).get("verifiedBotCategory") or ""
            count = int(row.get("count", 0) or 0)
            if not name:
                continue
            by_category[name] = by_category.get(name, 0) + count
            total += count
        bot_5xx = 0
        for row in zone.get("bot_5xx", []) or []:
            bot_5xx += int(row.get("count", 0) or 0)
        return {
            "by_category": by_category,
            "bot_total": total,
            "bot_5xx": bot_5xx,
            "window_start": since_str,
            "window_end": until_str,
            "source": "cloudflare",
        }
    except Exception as e:
        logger.warning(f"CF verified-bot parsing failed: {e}")
        return None


async def get_top_pages_cf(days: int = 30, limit: int = 20) -> Optional[list]:
    if not is_configured():
        return None

    zone_id = _cfg()["zone_id"]
    now = datetime.now(timezone.utc)
    start_dt = (now - timedelta(hours=23, minutes=59)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_dt = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    query = """
    query TopPaths($zoneTag: String!, $since: String!, $until: String!, $limit: Int!) {
      viewer {
        zones(filter: { zoneTag: $zoneTag }) {
          httpRequestsAdaptiveGroups(
            filter: {
              datetime_geq: $since
              datetime_leq: $until
              requestSource: "eyeball"
              edgeResponseContentTypeName: "html"
            }
            limit: $limit
            orderBy: [count_DESC]
          ) {
            count
            dimensions {
              clientRequestPath
            }
          }
        }
      }
    }
    """
    variables = {
        "zoneTag": zone_id,
        "since": start_dt,
        "until": end_dt,
        "limit": limit,
    }
    data = await _graphql_query(query, variables)
    if not data:
        return None

    try:
        zones = data.get("viewer", {}).get("zones", [])
        if not zones:
            return None
        pages = []
        for row in zones[0].get("httpRequestsAdaptiveGroups", []):
            path = row.get("dimensions", {}).get("clientRequestPath", "")
            pages.append({
                "path": path,
                "views": row.get("count", 0),
                "source": "cloudflare",
            })
        return pages
    except Exception as e:
        logger.warning(f"CF top pages parsing failed: {e}")
        return None


_CONTENT_PREFIX_TO_URLS = {
    "boards":   ["/api/content/boards", "/api/content/library-bundle"],
    "classes":  ["/api/content/classes", "/api/content/library-bundle"],
    "streams":  ["/api/content/streams", "/api/content/library-bundle"],
    "subjects": ["/api/content/subjects", "/api/content/library-bundle"],
    "chapters": [
        "/api/content/chapters/",
        "/api/content/library-bundle",
        "/api/content/chapter-by-slug/",
        "/api/content/chunks/",
        "/api/content/topic/",
        "/api/content/syllabus/",
        "/api/notes/public",
        "/api/mcq/",
        "/api/flashcards/",
        "/api/pyq/",
    ],
}

_ALL_CONTENT_URLS = list(set(
    url for urls in _CONTENT_PREFIX_TO_URLS.values() for url in urls
))


def _purge_cfg():
    return {
        "api_token": os.getenv("CF_API_TOKEN", "").strip() or os.getenv("CF_ANALYTICS_API_TOKEN", "").strip(),
        "zone_id": os.getenv("CF_ZONE_ID", "").strip(),
    }


def is_purge_configured() -> bool:
    c = _purge_cfg()
    return bool(c["api_token"] and c["zone_id"])


_CF_API_DOMAIN = os.getenv("CF_API_DOMAIN", "https://api.syrabit.ai").strip().rstrip("/")


async def _cf_purge_request(payload: dict) -> bool:
    c = _purge_cfg()
    try:
        client = _get_cf_client()
        resp = await client.post(
            f"https://api.cloudflare.com/client/v4/zones/{c['zone_id']}/purge_cache",
            json=payload,
            headers={
                "Authorization": f"Bearer {c['api_token']}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                return True
            logger.warning(f"CF cache purge failed: {data.get('errors')}")
            return False
        logger.warning(f"CF cache purge HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.warning(f"CF cache purge error: {e}")
        return False


async def _purge_by_prefix(url_prefixes: List[str]) -> bool:
    ok = await _cf_purge_request({"prefixes": url_prefixes})
    if ok:
        logger.info(f"CF prefix purge OK: {url_prefixes}")
    return ok


async def _purge_by_files(urls: List[str]) -> bool:
    all_ok = True
    batch_size = 30
    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]
        ok = await _cf_purge_request({"files": batch})
        if ok:
            logger.info(f"CF file purge OK: {len(batch)} URLs")
        else:
            all_ok = False
    return all_ok


async def _purge_everything() -> bool:
    ok = await _cf_purge_request({"purge_everything": True})
    if ok:
        logger.info("CF purge_everything: success")
    return ok


async def purge_content_prefixes(prefixes: List[str]) -> bool:
    if not is_purge_configured():
        return False
    url_paths = set()
    for prefix in prefixes:
        cf_urls = _CONTENT_PREFIX_TO_URLS.get(prefix, [])
        for url_path in cf_urls:
            url_paths.add(url_path)
    if not url_paths:
        return False

    full_prefixes = [f"{_CF_API_DOMAIN}{p}" for p in url_paths]
    ok = await _purge_by_prefix(full_prefixes)
    if ok:
        return True
    logger.info("CF prefix purge unavailable, falling back to file purge")

    exact_urls = [f"{_CF_API_DOMAIN}{p}" for p in url_paths if not p.endswith("/")]
    has_parameterized = any(p.endswith("/") for p in url_paths)
    if exact_urls:
        file_ok = await _purge_by_files(exact_urls)
    else:
        file_ok = True
    if has_parameterized:
        logger.info("Parameterized routes detected, using purge_everything as fallback")
        everything_ok = await _purge_everything()
        return file_ok and everything_ok
    return file_ok


async def purge_worker_cache(prefixes: list = None, purge_all: bool = False) -> bool:
    edge_url = os.getenv("CF_EDGE_PROXY_URL", "https://api.syrabit.ai").strip().rstrip("/")
    sync_secret = os.getenv("D1_SYNC_SECRET", "").strip()
    if not sync_secret:
        logger.debug("Worker cache purge skipped — D1_SYNC_SECRET not set")
        return False
    try:
        payload = {}
        if purge_all:
            payload["purge_all"] = True
        elif prefixes:
            payload["prefixes"] = prefixes
        else:
            return False
        client = _get_cf_client()
        resp = await client.post(
            f"{edge_url}/api/edge/purge",
            json=payload,
            headers={
                "Authorization": f"Bearer {sync_secret}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"Worker cache purge OK: purged={data.get('purged', 0)}")
            return True
        logger.warning(f"Worker cache purge HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.warning(f"Worker cache purge error: {e}")
        return False


async def purge_all_content_cache() -> bool:
    zone_ok = False
    if is_purge_configured():
        zone_ok = await _purge_everything()
    worker_ok = await purge_worker_cache(purge_all=True)
    return zone_ok or worker_ok


# ---------------------------------------------------------------------------
# SEO Phase A — content-time cache purge fan-out.
#
# `purge_content_prefixes` (above) targets API JSON endpoints used by the
# SPA shell. The crawler-facing assets are different: the public HTML page,
# its parent subject hub, the library landing, and the two sitemap files
# served at the public origin (`syrabit.ai`). When a brand-new chapter
# lands, all of these still serve cached responses that omit the new URL,
# which delays Googlebot from discovering it. `purge_for_content_change`
# fans the purge out across that whole set.
# ---------------------------------------------------------------------------

_PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://syrabit.ai").strip().rstrip("/")
_LIBRARY_LANDING_PATH = "/library"
_SITEMAP_PATHS = ("/sitemap-chapters.xml", "/sitemap-index.xml")


def _normalize_to_full_url(url_or_path: str) -> Optional[str]:
    if not url_or_path:
        return None
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        return url_or_path
    if not url_or_path.startswith("/"):
        url_or_path = "/" + url_or_path
    return f"{_PUBLIC_ORIGIN}{url_or_path}"


def urls_to_purge_for_content_change(
    url: str,
    page_type: str = "notes",
    parent_subject_url: Optional[str] = None,
) -> List[str]:
    """Return the deduped list of public URLs that should be purged when
    a content URL changes (the URL itself, parent subject hub, library
    landing, both sitemap files). Pure function — no side effects.
    Exported for testing and so callers can preview the purge set.
    """
    out: List[str] = []
    seen: set = set()

    def _add(candidate: Optional[str]):
        full = _normalize_to_full_url(candidate) if candidate else None
        if full and full not in seen:
            seen.add(full)
            out.append(full)

    _add(url)
    _add(parent_subject_url)
    _add(_LIBRARY_LANDING_PATH)
    for sp in _SITEMAP_PATHS:
        _add(sp)
    return out


async def purge_for_content_change(
    url: str,
    page_type: str = "notes",
    parent_subject_url: Optional[str] = None,
) -> bool:
    """Purge the page URL plus parent subject hub, library landing, and
    sitemap files at the public origin. Best-effort: returns True if at
    least one of the (zone, worker) layers acknowledged the purge.

    Failures are logged but never raised — this is called from a
    fire-and-forget fan-out task.
    """
    targets = urls_to_purge_for_content_change(url, page_type, parent_subject_url)
    if not targets:
        return False

    zone_ok = False
    if is_purge_configured():
        try:
            zone_ok = await _purge_by_files(targets)
        except Exception as e:
            logger.warning(f"purge_for_content_change zone purge error: {e}")

    # Also purge the path-prefix list on the worker cache so the
    # bot-render KV is invalidated for these public paths.
    worker_ok = False
    try:
        prefixes = []
        for t in targets:
            try:
                from urllib.parse import urlparse
                p = urlparse(t).path
                if p:
                    prefixes.append(p)
            except Exception:
                continue
        if prefixes:
            worker_ok = await purge_worker_cache(prefixes=prefixes)
    except Exception as e:
        logger.warning(f"purge_for_content_change worker purge error: {e}")

    if zone_ok or worker_ok:
        logger.info(
            "purge_for_content_change ok: url=%s targets=%d zone=%s worker=%s",
            url, len(targets), zone_ok, worker_ok,
        )
    return zone_ok or worker_ok
