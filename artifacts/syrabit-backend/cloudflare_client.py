"""
Cloudflare Analytics API client for Syrabit.
Uses the Cloudflare GraphQL Analytics API to fetch zone-level traffic data.
Also provides edge cache purge functionality.
Falls back gracefully when credentials are missing/invalid.
"""
import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

logger = logging.getLogger(__name__)

_cf_http: Optional["httpx.AsyncClient"] = None

# ── Auth-failure circuit breaker ──────────────────────────────────────────────
# When we detect a CF auth error (401 or GraphQL error code 10000), we mark the
# token as broken and short-circuit all subsequent calls for AUTH_FAIL_TTL_SEC
# seconds. This prevents log-spam and removes Cloudflare API latency from every
# admin page load when the token has been revoked or its scopes are wrong.
AUTH_FAIL_TTL_SEC = 300  # 5 minutes

# ── Task #455: alert dispatch debounce ────────────────────────────────────────
# When the analytics token starts being rejected, fire a single alert through
# `metrics._dispatch_alert` so admins hear about it on email / Slack / push
# without having to load the admin Analytics page. Debounced so that a 401
# burst (or a sustained outage) doesn't spam the channels — at most one
# "rejected" alert per `_ALERT_DEBOUNCE_SEC` window. The matching one-shot
# "recovered" alert fires on the failure → success transition.
_ALERT_DEBOUNCE_SEC = 24 * 3600
_last_alert_at: dict = {"failed": 0.0}

_auth_state: dict = {
    "ok": None,                # None = unknown, True = working, False = broken
    "last_check_at": None,     # ISO timestamp (str)
    "last_error": None,        # human-readable error string
    "blocked_until": None,     # epoch seconds; calls short-circuit until then
    "consecutive_failures": 0,
    # Task #455: set by `reset_auth_state()` when the operator clicks
    # "Re-check now" after a known failure, so the next successful probe
    # still fires the one-shot recovery alert even though the explicit
    # `ok=False` state was cleared by the reset.
    "_pending_recovery_alert": False,
}


def _now_epoch() -> float:
    import time
    return time.time()


async def _send_alert_async(alert_type: str, title: str, body: str):
    """Lazy-imported wrapper around ``metrics._dispatch_alert`` so this
    module stays import-cycle-free. ``force=True`` because we run our own
    24h debounce in `_last_alert_at` (Task #455) — the global 30-minute
    cooldown in metrics is too short for token-rotation paging."""
    try:
        from metrics import _dispatch_alert
        await _dispatch_alert(alert_type, title, body, force=True)
    except Exception as exc:
        logger.debug(f"CF auth alert dispatch failed ({alert_type}): {exc}")


def _schedule_alert(alert_type: str, title: str, body: str):
    """Fire-and-forget alert dispatch. Safe to call from sync code paths
    that run inside an async event loop (every CF call originates from
    `_graphql_query`, which is async). If somehow invoked outside a loop
    (e.g. unit tests) we silently drop instead of crashing the breaker."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_send_alert_async(alert_type, title, body))


def _mark_auth_failed(error_msg: str):
    """Trip the circuit breaker. Subsequent calls return None without hitting CF."""
    _auth_state["ok"] = False
    _auth_state["last_check_at"] = datetime.now(timezone.utc).isoformat()
    _auth_state["last_error"] = error_msg[:240]
    _auth_state["blocked_until"] = _now_epoch() + AUTH_FAIL_TTL_SEC
    _auth_state["consecutive_failures"] += 1
    # Log at WARN once per breaker-trip (not on every short-circuited call)
    if _auth_state["consecutive_failures"] <= 3 or _auth_state["consecutive_failures"] % 50 == 0:
        logger.warning(
            f"CF_ANALYTICS token rejected ({error_msg[:120]}). "
            f"Suppressing further calls for {AUTH_FAIL_TTL_SEC}s. "
            f"Rotate token in Cloudflare dashboard with scopes: "
            f"Account Analytics:Read, Zone Analytics:Read, Zone:Read."
        )

    # Task #455: page admins on email / Slack / push via the existing
    # alert pipeline so the dashboard isn't the only place this surfaces.
    # 24h debounce so a sustained outage doesn't repeatedly spam channels.
    now = _now_epoch()
    if now - _last_alert_at.get("failed", 0) >= _ALERT_DEBOUNCE_SEC:
        _last_alert_at["failed"] = now
        status_obj = get_auth_status()
        hint = status_obj.get("rotation_hint") or (
            "Create a new Cloudflare API token with scopes: "
            "Account Analytics:Read, Zone Analytics:Read, Zone:Read. "
            "Then update CLOUDFLARE_ANALYTICS_TOKEN (Task #534 spec name; "
            "legacy alias CLOUDFLARE_API_TOKEN still accepted) on Railway "
            "and restart the service."
        )
        body = (
            f"Cloudflare rejected the analytics token: {error_msg[:200]}\n\n"
            f"{hint}\n\n"
            f"Calls are short-circuited for {AUTH_FAIL_TTL_SEC}s after each "
            f"failure burst. After rotating, click 'Re-check now' on "
            f"/admin/analytics, or open /admin/notifications (Delivery tab) "
            f"to confirm channel health."
        )
        _schedule_alert(
            "cf_analytics_token_rejected",
            "Cloudflare analytics token rejected",
            body,
        )


def _mark_auth_ok():
    was_failed = (
        _auth_state["ok"] is False
        or _auth_state.get("_pending_recovery_alert", False)
    )
    _auth_state["ok"] = True
    _auth_state["last_check_at"] = datetime.now(timezone.utc).isoformat()
    _auth_state["last_error"] = None
    _auth_state["blocked_until"] = None
    _auth_state["consecutive_failures"] = 0
    _auth_state["_pending_recovery_alert"] = False

    # Task #455: one-shot recovery alert on the failure → success edge so
    # admins know rotation worked without checking the dashboard. Reset
    # the failure-debounce timer so a fresh outage after recovery pages
    # immediately rather than waiting out the old 24h window.
    if was_failed:
        _last_alert_at["failed"] = 0.0
        _schedule_alert(
            "cf_analytics_token_recovered",
            "Cloudflare analytics token recovered",
            "Cloudflare analytics calls are succeeding again. If you just "
            "rotated CLOUDFLARE_ANALYTICS_TOKEN (or its legacy alias "
            "CLOUDFLARE_API_TOKEN), the rotation worked.\n\n"
            "Channel health: /admin/notifications (Delivery tab)."
        )


def _is_auth_blocked() -> bool:
    bu = _auth_state.get("blocked_until")
    return bool(bu and bu > _now_epoch())


def get_auth_status() -> dict:
    """Public status surface for admin UI. Safe to expose (no token leakage)."""
    blocked_for = None
    if _is_auth_blocked():
        blocked_for = int(_auth_state["blocked_until"] - _now_epoch())
    return {
        "configured": is_configured(),
        "auth_ok": _auth_state["ok"],
        "last_check_at": _auth_state["last_check_at"],
        "last_error": _auth_state["last_error"],
        "consecutive_failures": _auth_state["consecutive_failures"],
        "blocked_for_seconds": blocked_for,
        "needs_rotation": _auth_state["ok"] is False,
        "rotation_hint": (
            "Create a new Cloudflare API token with scopes: "
            "Account Analytics:Read, Zone Analytics:Read, Zone:Read. "
            "Then update CLOUDFLARE_ANALYTICS_TOKEN (Task #534 spec name; "
            "legacy alias CLOUDFLARE_API_TOKEN still accepted) on Railway "
            "and restart the service."
        ) if _auth_state["ok"] is False else None,
    }


def reset_auth_state():
    """Force re-check of token on next call. Call after operator rotates token."""
    # Task #455: if we were in a known-failed state, remember that across
    # the reset so the next successful probe (typically the
    # `get_visitor_stats_cf(days=1)` re-probe in `admin_cf_recheck`) still
    # fires the one-shot recovery alert. Without this, clearing `ok` here
    # would mask the failure → success transition from `_mark_auth_ok`.
    if _auth_state.get("ok") is False:
        _auth_state["_pending_recovery_alert"] = True
    _auth_state["ok"] = None
    _auth_state["blocked_until"] = None
    _auth_state["consecutive_failures"] = 0
    _auth_state["last_error"] = None


def _get_cf_client():
    global _cf_http
    if _cf_http is None:
        import httpx
        _cf_http = httpx.AsyncClient(
            timeout=15,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
    return _cf_http


_LEGACY_CF_WARNING_EMITTED = False


def _runtime_cf_token() -> str:
    """Resolve the runtime Cloudflare REST token (Task #534).

    Strict role boundary — only two env vars are accepted so a leaked
    runtime token can never collapse into the deploy or Pages role:
      1. CLOUDFLARE_ANALYTICS_TOKEN  ← Task #534 spec name (preferred)
      2. CLOUDFLARE_API_TOKEN        ← legacy fallback, one-shot WARNING

    CF_PAGES_API_TOKEN / CF_API_TOKEN / CF_ANALYTICS_API_TOKEN are
    intentionally NOT accepted here — Pages-scoped or undifferentiated
    legacy names must not be used at runtime.
    """
    global _LEGACY_CF_WARNING_EMITTED
    spec = os.getenv("CLOUDFLARE_ANALYTICS_TOKEN", "").strip()
    if spec:
        return spec
    legacy = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if legacy and not _LEGACY_CF_WARNING_EMITTED:
        _LEGACY_CF_WARNING_EMITTED = True
        print(
            "[cloudflare_client] WARNING: runtime CF REST is using legacy "
            "CLOUDFLARE_API_TOKEN; set CLOUDFLARE_ANALYTICS_TOKEN (Task "
            "#534 spec name) to complete the migration and retire the "
            "deploy-scoped token from runtime use.",
            flush=True,
        )
    return legacy


def _cfg():
    return {
        "api_token": _runtime_cf_token(),
        "zone_id": os.getenv("CF_ZONE_ID", "").strip(),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["api_token"] and c["zone_id"])


def _looks_like_auth_error(data: dict, status_code: int = 200) -> Optional[str]:
    """Detect a CF auth/permission failure. Returns the error string or None."""
    if status_code in (401, 403):
        return f"HTTP {status_code} from Cloudflare API"
    errs = data.get("errors") if isinstance(data, dict) else None
    if not errs:
        return None
    for e in errs:
        code = e.get("code") if isinstance(e, dict) else None
        msg = (e.get("message") if isinstance(e, dict) else str(e)) or ""
        # CF auth error codes: 10000 (Auth error), 9109 (Unauthorized), 9106
        if code in (10000, 9109, 9106) or "Authentication error" in msg or "Unauthorized" in msg:
            return f"code={code} msg={msg}"
    return None


async def _graphql_query(query: str, variables: dict = None) -> Optional[dict]:
    if not is_configured():
        return None
    if _is_auth_blocked():
        # Circuit breaker open — fail fast, no log, no API hit
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
        # Detect auth failure before raise_for_status
        if r.status_code in (401, 403):
            _mark_auth_failed(f"HTTP {r.status_code} from Cloudflare GraphQL")
            return None
        r.raise_for_status()
        data = r.json()
        auth_err = _looks_like_auth_error(data, r.status_code)
        if auth_err:
            _mark_auth_failed(auth_err)
            return None
        if data.get("errors"):
            # Non-auth GraphQL errors — log normally without tripping breaker
            logger.warning(f"CF GraphQL errors: {data['errors']}")
            return None
        _mark_auth_ok()
        return data.get("data")
    except Exception as e:
        # Network/parse error — log once, do not trip breaker
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
              bytes
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
              bytes
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
        # NOTE: `sum.visits` was removed from the CF GraphQL schema for
        # `httpRequests1dGroups`/`httpRequests1hGroups`. We now use
        # `uniq.uniques` (unique visitors per bucket) for the "visitors"
        # metric. This matches the Cloudflare dashboard's *Unique visitors*
        # tile rather than *Visits* (sessions).
        visitors_today = today_data.get("uniq", {}).get("uniques", 0)
        page_views_today = today_data.get("sum", {}).get("pageViews", 0)
        requests_today = today_data.get("sum", {}).get("requests", 0)
        bytes_today = today_data.get("sum", {}).get("bytes", 0)

        daily_visitors = []
        total_visitors = 0
        total_page_views = 0
        total_requests = 0
        total_bytes = 0
        for day in zone.get("daily", []):
            dims = day.get("dimensions", {})
            day_visitors = day.get("uniq", {}).get("uniques", 0)  # CF "Unique visitors"
            day_page_views = day.get("sum", {}).get("pageViews", 0)
            day_requests = day.get("sum", {}).get("requests", 0)
            day_bytes = day.get("sum", {}).get("bytes", 0)
            total_visitors += day_visitors
            total_page_views += day_page_views
            total_requests += day_requests
            total_bytes += day_bytes
            daily_visitors.append({
                "date": dims.get("date", ""),
                "visitors": day_visitors,
                "page_views": day_page_views,
                "requests": day_requests,
                "bytes": day_bytes,
            })

        return {
            "total_visitors": total_visitors,
            "visitors_today": visitors_today,
            "page_views_today": page_views_today,
            "total_page_views": total_page_views,
            "total_requests": total_requests,
            "requests_today": requests_today,
            "total_bytes": total_bytes,
            "bytes_today": bytes_today,
            "daily_visitors": daily_visitors,
            "source": "cloudflare",
        }
    except Exception as e:
        logger.warning(f"CF stats parsing failed: {e}")
        return None


async def _fetch_visits_series(zone_id: str, range_key: str) -> Optional[dict]:
    """Task #741 — best-effort total-visits (sessions) per bucket.

    `sum.visits` was removed from `httpRequests1dGroups`/`httpRequests1hGroups`,
    so unique-visitors and total-sessions can no longer be fetched in a
    single query. We mirror the same window the main overview uses but
    pull from `httpRequestsAdaptiveGroups` (which still exposes
    `sum { visits }`) and return ``{bucket_ts: visits}``.

    Returns `None` on ANY failure (token rejected, schema change, account
    plan without adaptive access). The caller then sets per-row visits to
    None and the UI tile renders "—" instead of breaking the whole card.
    """
    if not is_configured():
        return None
    now = datetime.now(timezone.utc)
    if range_key == "24h":
        since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        query CfVisitsHourly($zoneTag: String!, $since: Time!, $until: Time!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              series: httpRequestsAdaptiveGroups(
                filter: { datetime_geq: $since, datetime_lt: $until }
                orderBy: [datetimeHour_ASC]
                limit: 48
              ) {
                dimensions { datetimeHour }
                sum { visits }
              }
            }
          }
        }
        """
        variables = {"zoneTag": zone_id, "since": since, "until": until}
    else:
        days = 30 if range_key == "30d" else 7
        since_d = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        until_d = now.strftime("%Y-%m-%d")
        query = """
        query CfVisitsDaily($zoneTag: String!, $since: Date!, $until: Date!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              series: httpRequestsAdaptiveGroups(
                filter: { date_geq: $since, date_leq: $until }
                orderBy: [date_ASC]
                limit: 100
              ) {
                dimensions { date }
                sum { visits }
              }
            }
          }
        }
        """
        variables = {"zoneTag": zone_id, "since": since_d, "until": until_d}

    data = await _graphql_query(query, variables)
    if not data:
        return None
    try:
        zones = data.get("viewer", {}).get("zones", []) or []
        if not zones:
            return None
        rows = zones[0].get("series", []) or []
        out: dict = {}
        for row in rows:
            dims = row.get("dimensions", {}) or {}
            ts = dims.get("date") or dims.get("datetimeHour") or ""
            v = int((row.get("sum", {}) or {}).get("visits", 0) or 0)
            if ts:
                out[ts] = v
        return out
    except Exception as e:
        logger.debug(f"CF visits-series parsing failed: {e}")
        return None


_CONTENT_TYPE_FRIENDLY = {
    # Map raw Cloudflare edgeResponseContentTypeName values to short,
    # admin-friendly keywords shown as chips under the Interactions tile.
    "html": "pages",
    "json": "API",
    "javascript": "scripts", "js": "scripts",
    "css": "styles",
    # CF reports "empty" for HEAD requests, 204/304 responses, redirects,
    # health checks etc — group as "other" so the chip is meaningful.
    "empty": "other", "": "other",
    "jpeg": "images", "jpg": "images", "png": "images", "webp": "images",
    "gif": "images", "svg": "images", "avif": "images", "ico": "images",
    "woff": "fonts", "woff2": "fonts", "ttf": "fonts", "otf": "fonts",
    "xml": "feeds", "rss": "feeds",
    "mp4": "video", "webm": "video", "mov": "video",
    "mp3": "audio", "wav": "audio",
    "pdf": "docs",
    "plain": "text", "octet-stream": "downloads",
}


async def _fetch_interaction_types(zone_id: str, range_key: str) -> Optional[list]:
    """Task #741 follow-up: top edge content-type categories for the chosen
    window, so the Interactions tile can show *what kinds* of interactions
    they are (pages / API / images / scripts / ...). Best-effort —
    returns None on any failure; caller renders no chips in that case.
    """
    if not is_configured():
        return None
    now = datetime.now(timezone.utc)
    if range_key == "24h":
        since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        query CfTypesHourly($zoneTag: String!, $since: Time!, $until: Time!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              groups: httpRequestsAdaptiveGroups(
                filter: { datetime_geq: $since, datetime_lt: $until }
                orderBy: [count_DESC]
                limit: 25
              ) {
                count
                dimensions { edgeResponseContentTypeName }
              }
            }
          }
        }
        """
        variables = {"zoneTag": zone_id, "since": since, "until": until}
    else:
        days = 30 if range_key == "30d" else 7
        since_d = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        until_d = now.strftime("%Y-%m-%d")
        query = """
        query CfTypesDaily($zoneTag: String!, $since: Date!, $until: Date!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              groups: httpRequestsAdaptiveGroups(
                filter: { date_geq: $since, date_leq: $until }
                orderBy: [count_DESC]
                limit: 25
              ) {
                count
                dimensions { edgeResponseContentTypeName }
              }
            }
          }
        }
        """
        variables = {"zoneTag": zone_id, "since": since_d, "until": until_d}

    data = await _graphql_query(query, variables)
    if not data:
        return None
    try:
        zones = data.get("viewer", {}).get("zones", []) or []
        if not zones:
            return None
        rows = zones[0].get("groups", []) or []
        # Collapse raw mime subtypes ("jpeg" + "png" -> "images" etc).
        bucket: dict = {}
        total = 0
        for row in rows:
            raw = ((row.get("dimensions", {}) or {}).get("edgeResponseContentTypeName") or "").strip().lower()
            count = int(row.get("count", 0) or 0)
            if not raw or count <= 0:
                continue
            label = _CONTENT_TYPE_FRIENDLY.get(raw, raw)
            bucket[label] = bucket.get(label, 0) + count
            total += count
        if total <= 0:
            return None
        # Top 5, drop slices < 1% to keep chips meaningful.
        ranked = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)
        out = []
        for label, count in ranked[:5]:
            pct = round((count / total) * 100, 1)
            if pct < 1.0:
                continue
            out.append({"label": label, "count": count, "pct": pct})
        return out or None
    except Exception as e:
        logger.debug(f"CF interaction-types parsing failed: {e}")
        return None


async def get_cf_overview(range_key: str = "7d") -> Optional[dict]:
    """Cloudflare-mirror analytics overview with selectable time range.

    Returns ``{requests, bytes, visitors, page_views}`` totals and a uniform
    ``series`` list (one entry per bucket: hour for 24h, day for 7d/30d) with
    ``{ts, requests, bytes, visitors, page_views}`` fields. ``range_key`` is
    one of ``"24h"``, ``"7d"``, ``"30d"`` (anything else falls back to 7d).

    For ``24h`` we use the hourly dataset (``httpRequests1hGroups``) so the
    sparkline shows 24 buckets. For ``7d``/``30d`` we use the daily dataset
    that matches what the Cloudflare account-analytics dashboard renders.
    """
    if not is_configured():
        return None

    zone_id = _cfg()["zone_id"]
    now = datetime.now(timezone.utc)

    if range_key == "24h":
        # Hourly buckets, exact 24-hour rolling window. Cloudflare aligns
        # hourly buckets to the top of the hour, so a naive `now - 24h`
        # range may straddle 25 buckets. We over-fetch slightly and then
        # slice to the last 24 entries below for a precise window.
        since = now - timedelta(hours=24)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        until_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        query CfOverviewHourly($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              series: httpRequests1hGroups(
                filter: { datetime_geq: $since, datetime_lt: $until }
                orderBy: [datetime_ASC]
                limit: 48
              ) {
                dimensions { datetime }
                sum { requests pageViews bytes }
                uniq { uniques }
              }
            }
          }
        }
        """
        variables = {"zoneTag": zone_id, "since": since_str, "until": until_str}
        period_label = "Previous 24 hours"
        bucket = "hour"
    else:
        days = 30 if range_key == "30d" else 7
        # `date_geq` + `date_leq` is inclusive on both ends, so to get
        # exactly N daily buckets we step back (days - 1) from today.
        since_d = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        until_d = now.strftime("%Y-%m-%d")
        query = """
        query CfOverviewDaily($zoneTag: String!, $since: String!, $until: String!) {
          viewer {
            zones(filter: { zoneTag: $zoneTag }) {
              series: httpRequests1dGroups(
                filter: { date_geq: $since, date_leq: $until }
                orderBy: [date_ASC]
                limit: 100
              ) {
                dimensions { date }
                sum { requests pageViews bytes }
                uniq { uniques }
              }
            }
          }
        }
        """
        variables = {"zoneTag": zone_id, "since": since_d, "until": until_d}
        period_label = f"Previous {days} days"
        bucket = "day"

    # Task #741 — fetch the per-bucket visits (sessions) series in
    # parallel with the main overview query so the new "Total Visitors"
    # tile can render alongside "Unique Visitors". The visits fetch is
    # best-effort: if it returns None, we degrade the visits tile to "—"
    # without touching the rest of the card.
    _safe_range = range_key if range_key in ("24h", "7d", "30d") else "7d"
    data, visits_map, interaction_types = await asyncio.gather(
        _graphql_query(query, variables),
        _fetch_visits_series(zone_id, _safe_range),
        _fetch_interaction_types(zone_id, _safe_range),
    )
    if not data:
        return None

    try:
        zones = data.get("viewer", {}).get("zones", []) or []
        if not zones:
            return None
        rows = zones[0].get("series", []) or []
        # Trim to exact bucket count for the requested range.
        max_buckets = 24 if bucket == "hour" else (30 if range_key == "30d" else 7)
        if len(rows) > max_buckets:
            rows = rows[-max_buckets:]
        series = []
        visits_available = isinstance(visits_map, dict)
        # NOTE: `sum.visits` was removed from the CF GraphQL schema for the
        # `httpRequests1dGroups` / `httpRequests1hGroups` datasets, so the
        # old "visitors == sum.visits (sessions)" mapping started failing
        # with `unknown field "visits"` errors. We now map "visitors" to
        # `uniq.uniques` (unique visitors per bucket) — the closest
        # still-available equivalent. This matches the Cloudflare
        # dashboard's *Unique visitors* tile rather than *Visits*
        # (sessions); if the exact session count is needed in the future
        # the right move is to migrate to `httpRequestsAdaptiveGroups`
        # which still exposes `sum { visits }`.
        totals = {"requests": 0, "bytes": 0, "visitors": 0, "page_views": 0, "visits": (0 if visits_available else None)}
        for row in rows:
            dims = row.get("dimensions", {}) or {}
            ts = dims.get("datetime") or dims.get("date") or ""
            s = row.get("sum", {}) or {}
            u = row.get("uniq", {}) or {}
            req = int(s.get("requests", 0) or 0)
            byt = int(s.get("bytes", 0) or 0)
            pv = int(s.get("pageViews", 0) or 0)
            uniques = int(u.get("uniques", 0) or 0)        # CF "Unique visitors"
            vis = uniques                                  # back-compat alias
            # Task #741: total visits/sessions per bucket from the
            # parallel adaptive-groups query. None when unavailable
            # so the UI can render "—" per bucket.
            visits_count = visits_map.get(ts) if visits_available else None
            totals["requests"] += req
            totals["bytes"] += byt
            totals["page_views"] += pv
            totals["visitors"] += vis
            if visits_available and isinstance(visits_count, int):
                totals["visits"] += visits_count
            series.append({
                "ts": ts,
                "requests": req,
                "bytes": byt,
                "page_views": pv,
                "visitors": vis,
                "uniques": uniques,
                "visits": visits_count,
            })
        return {
            "range": _safe_range,
            "bucket": bucket,
            "period_label": period_label,
            "totals": totals,
            "series": series,
            # Top edge content-type breakdown (e.g. pages / API / images /
            # scripts / styles) for the same window, used by the
            # Interactions tile chip row. None when unavailable.
            "interaction_types": interaction_types,
            "source": "cloudflare",
        }
    except Exception as e:
        logger.warning(f"CF overview parsing failed: {e}")
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
    # Task #534: cache-purge is a runtime concern, so it shares the strict
    # runtime resolver — only CLOUDFLARE_ANALYTICS_TOKEN with a single
    # CLOUDFLARE_API_TOKEN fallback. Pages/legacy CF_* names are NOT
    # accepted at runtime.
    return {
        "api_token": _runtime_cf_token(),
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
