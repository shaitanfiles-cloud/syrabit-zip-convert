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
            filter: { date_eq: $today }
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
