"""
Cloudflare Analytics API client for Syrabit.
Uses the Cloudflare GraphQL Analytics API to fetch zone-level traffic data.
Falls back gracefully when credentials are missing/invalid.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

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
    start_dt = (now - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    end_dt = now.strftime("%Y-%m-%dT23:59:59Z")

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
