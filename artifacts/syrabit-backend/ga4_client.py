"""
GA4 Analytics Data API helper for Syrabit.
Uses service-account-less OAuth with the Analytics Data API.
Falls back gracefully when credentials are missing/invalid.
"""
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

GA4_PROPERTY_ID = os.getenv("GA4_PROPERTY_ID", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GA4_REFRESH_TOKEN = os.getenv("GA4_REFRESH_TOKEN", "")


def _is_configured() -> bool:
    return bool(GA4_PROPERTY_ID and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GA4_REFRESH_TOKEN)


async def _get_access_token() -> Optional[str]:
    """Exchange refresh token for access token."""
    if not GA4_REFRESH_TOKEN:
        return None
    try:
        import httpx
        r = await httpx.AsyncClient().post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": GA4_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        logger.warning(f"GA4 token refresh failed: {e}")
        return None


async def run_report(dimensions: list, metrics: list,
                     date_ranges: list, order_bys: list = None,
                     limit: int = 30) -> Optional[dict]:
    """Run a GA4 Data API report. Returns raw response or None."""
    if not _is_configured():
        return None
    token = await _get_access_token()
    if not token:
        return None
    try:
        import httpx
        body = {
            "dimensions": [{"name": d} for d in dimensions],
            "metrics": [{"name": m} for m in metrics],
            "dateRanges": date_ranges,
            "limit": limit,
        }
        if order_bys:
            body["orderBys"] = order_bys
        url = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY_ID}:runReport"
        r = await httpx.AsyncClient().post(url, json=body,
            headers={"Authorization": f"Bearer {token}"}, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"GA4 report failed: {e}")
        return None


async def get_visitor_stats_ga4(days: int = 7) -> Optional[dict]:
    """
    Fetch daily visitors + page views from GA4.
    Returns None if GA4 not configured.
    """
    if not _is_configured():
        return None

    today = datetime.now(timezone.utc)
    date_ranges = [{"startDate": f"{days}daysAgo", "endDate": "today"}]

    # Daily breakdown
    daily_resp = await run_report(
        dimensions=["date"],
        metrics=["activeUsers", "screenPageViews"],
        date_ranges=date_ranges,
        order_bys=[{"dimension": {"dimensionName": "date"}}],
        limit=days + 1,
    )

    # Totals
    total_resp = await run_report(
        dimensions=[],
        metrics=["activeUsers", "screenPageViews", "newUsers"],
        date_ranges=[{"startDate": "365daysAgo", "endDate": "today"}],
        limit=1,
    )

    # Today
    today_resp = await run_report(
        dimensions=[],
        metrics=["activeUsers", "screenPageViews"],
        date_ranges=[{"startDate": "today", "endDate": "today"}],
        limit=1,
    )

    daily_visitors = []
    if daily_resp:
        for row in daily_resp.get("rows", []):
            raw_date = row["dimensionValues"][0]["value"]
            formatted = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            daily_visitors.append({
                "date": formatted,
                "visitors": int(row["metricValues"][0]["value"]),
                "page_views": int(row["metricValues"][1]["value"]),
            })

    total_visitors = 0
    if total_resp and total_resp.get("rows"):
        total_visitors = int(total_resp["rows"][0]["metricValues"][0]["value"])

    visitors_today = 0
    page_views_today = 0
    if today_resp and today_resp.get("rows"):
        visitors_today = int(today_resp["rows"][0]["metricValues"][0]["value"])
        page_views_today = int(today_resp["rows"][0]["metricValues"][1]["value"])

    return {
        "total_visitors": total_visitors,
        "visitors_today": visitors_today,
        "page_views_today": page_views_today,
        "daily_visitors": daily_visitors,
        "source": "ga4",
    }


async def get_top_pages_ga4(limit: int = 20) -> Optional[list]:
    """Fetch top pages from GA4 by page views."""
    if not _is_configured():
        return None
    resp = await run_report(
        dimensions=["pagePath"],
        metrics=["screenPageViews", "activeUsers"],
        date_ranges=[{"startDate": "30daysAgo", "endDate": "today"}],
        order_bys=[{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        limit=limit,
    )
    if not resp:
        return None
    pages = []
    for row in resp.get("rows", []):
        pages.append({
            "path": row["dimensionValues"][0]["value"],
            "views": int(row["metricValues"][0]["value"]),
            "unique_visitors": int(row["metricValues"][1]["value"]),
        })
    return pages


async def get_top_referrers_ga4(limit: int = 15) -> Optional[list]:
    """Fetch top traffic sources from GA4."""
    if not _is_configured():
        return None
    resp = await run_report(
        dimensions=["sessionSource"],
        metrics=["sessions"],
        date_ranges=[{"startDate": "30daysAgo", "endDate": "today"}],
        order_bys=[{"metric": {"metricName": "sessions"}, "desc": True}],
        limit=limit,
    )
    if not resp:
        return None
    refs = []
    for row in resp.get("rows", []):
        src = row["dimensionValues"][0]["value"]
        if src and src != "(direct)":
            refs.append({
                "source": src,
                "count": int(row["metricValues"][0]["value"]),
            })
    return refs


def get_oauth_url(redirect_uri: str) -> str:
    """Generate the GA4 OAuth consent URL."""
    from urllib.parse import urlencode
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/analytics.readonly",
        "access_type": "offline",
        "prompt": "consent",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


async def exchange_code_for_tokens(code: str, redirect_uri: str) -> Optional[dict]:
    """Exchange OAuth code for access + refresh tokens."""
    try:
        import httpx
        r = await httpx.AsyncClient().post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"GA4 code exchange failed: {e}")
        return None
