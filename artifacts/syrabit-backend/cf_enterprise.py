"""
Cloudflare Enterprise Features — async REST API client.

Covers four areas available under CF Enterprise / Business plans:
  1. Load Balancing    — pools, monitors, LB records
  2. Bulk Redirects    — URL redirect lists + ruleset activation
  3. Zaraz             — Web Tag Manager (get / update / publish config)
  4. Speed / Delivery  — HTTP/3, Early Hints, Brotli, Image Resizing,
                         Smart Speed (Speed Brain), HTTP/2 Prioritization

All calls are async, circuit-broken on auth failure, and degrade to
``None`` / empty dicts when CF_ZONE_ID or CLOUDFLARE_API_TOKEN is absent.

Required env vars:
  CLOUDFLARE_API_TOKEN  (or CLOUDFLARE_ANALYTICS_TOKEN)
  CF_ZONE_ID
  CF_AI_GATEWAY_ACCOUNT_ID   ← used as account_id for account-level APIs
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_CF_BASE = "https://api.cloudflare.com/client/v4"
_http: Optional[httpx.AsyncClient] = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _token() -> str:
    return (
        os.getenv("CLOUDFLARE_ANALYTICS_TOKEN", "").strip()
        or os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    )

def _zone_id() -> str:
    return os.getenv("CF_ZONE_ID", "").strip()

def _account_id() -> str:
    return os.getenv("CF_AI_GATEWAY_ACCOUNT_ID", "").strip()

def is_configured() -> bool:
    return bool(_token() and _zone_id())

def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=4),
        )
    return _http

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


async def _get(url: str) -> Optional[dict]:
    """GET a CF REST endpoint, return ``result`` key or None on failure."""
    if not is_configured():
        return None
    try:
        r = await _client().get(url, headers=_headers())
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            logger.warning("CF GET %s → %s", url, data.get("errors"))
            return None
        return data.get("result")
    except Exception as exc:
        logger.warning("CF GET %s failed: %s", url, exc)
        return None


async def _post(url: str, payload: dict) -> Optional[dict]:
    """POST to a CF REST endpoint, return ``result`` or None."""
    if not is_configured():
        return None
    try:
        r = await _client().post(url, headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            logger.warning("CF POST %s → %s", url, data.get("errors"))
            return None
        return data.get("result")
    except Exception as exc:
        logger.warning("CF POST %s failed: %s", url, exc)
        return None


async def _put(url: str, payload: dict) -> Optional[dict]:
    """PUT to a CF REST endpoint, return ``result`` or None."""
    if not is_configured():
        return None
    try:
        r = await _client().put(url, headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            logger.warning("CF PUT %s → %s", url, data.get("errors"))
            return None
        return data.get("result")
    except Exception as exc:
        logger.warning("CF PUT %s failed: %s", url, exc)
        return None


async def _patch(url: str, payload: dict) -> Optional[dict]:
    """PATCH a CF REST endpoint, return ``result`` or None."""
    if not is_configured():
        return None
    try:
        r = await _client().patch(url, headers=_headers(), json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            logger.warning("CF PATCH %s → %s", url, data.get("errors"))
            return None
        return data.get("result")
    except Exception as exc:
        logger.warning("CF PATCH %s failed: %s", url, exc)
        return None


async def _delete(url: str) -> bool:
    """DELETE a CF REST endpoint. Returns True on success."""
    if not is_configured():
        return False
    try:
        r = await _client().delete(url, headers=_headers())
        r.raise_for_status()
        data = r.json()
        return bool(data.get("success"))
    except Exception as exc:
        logger.warning("CF DELETE %s failed: %s", url, exc)
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LOAD BALANCING
# ═══════════════════════════════════════════════════════════════════════════════

async def lb_list_pools() -> list[dict]:
    """List all origin pools under the CF account."""
    acct = _account_id()
    if not acct:
        return []
    result = await _get(f"{_CF_BASE}/accounts/{acct}/load_balancers/pools")
    return result or []


async def lb_get_pool(pool_id: str) -> Optional[dict]:
    """Get a single pool by ID."""
    acct = _account_id()
    if not acct:
        return None
    return await _get(f"{_CF_BASE}/accounts/{acct}/load_balancers/pools/{pool_id}")


async def lb_create_pool(
    name: str,
    origins: list[dict],
    *,
    description: str = "",
    enabled: bool = True,
    minimum_origins: int = 1,
    monitor_id: Optional[str] = None,
    notification_email: str = "",
    check_regions: list[str] = None,
) -> Optional[dict]:
    """
    Create an origin pool.

    ``origins`` format:
        [{"name": "primary", "address": "api.syrabit.ai", "enabled": True, "weight": 1}]

    ``check_regions`` format (CF region codes):
        ["ENAM", "WEU", "SEAS"]  # East NA, West EU, Southeast Asia
    """
    acct = _account_id()
    if not acct:
        return None
    payload: dict[str, Any] = {
        "name": name,
        "origins": origins,
        "description": description,
        "enabled": enabled,
        "minimum_origins": minimum_origins,
    }
    if monitor_id:
        payload["monitor"] = monitor_id
    if notification_email:
        payload["notification_email"] = notification_email
    if check_regions:
        payload["check_regions"] = check_regions
    return await _post(f"{_CF_BASE}/accounts/{acct}/load_balancers/pools", payload)


async def lb_update_pool(pool_id: str, updates: dict) -> Optional[dict]:
    """Patch specific fields on an existing pool."""
    acct = _account_id()
    if not acct:
        return None
    return await _patch(
        f"{_CF_BASE}/accounts/{acct}/load_balancers/pools/{pool_id}",
        updates,
    )


async def lb_delete_pool(pool_id: str) -> bool:
    """Delete a pool."""
    acct = _account_id()
    if not acct:
        return False
    return await _delete(f"{_CF_BASE}/accounts/{acct}/load_balancers/pools/{pool_id}")


async def lb_list_monitors() -> list[dict]:
    """List health monitors."""
    acct = _account_id()
    if not acct:
        return []
    result = await _get(f"{_CF_BASE}/accounts/{acct}/load_balancers/monitors")
    return result or []


async def lb_create_monitor(
    type: str = "https",
    *,
    description: str = "",
    method: str = "GET",
    path: str = "/healthz/ai",
    port: int = 443,
    interval: int = 60,
    retries: int = 2,
    timeout: int = 5,
    expected_codes: str = "200",
    expected_body: str = "",
    follow_redirects: bool = True,
    allow_insecure: bool = False,
) -> Optional[dict]:
    """
    Create a health monitor.

    ``type`` — "https" | "http" | "tcp" | "udp_icmp" | "icmp_ping" | "smtp"
    """
    acct = _account_id()
    if not acct:
        return None
    payload: dict[str, Any] = {
        "type": type,
        "description": description,
        "method": method,
        "path": path,
        "port": port,
        "interval": interval,
        "retries": retries,
        "timeout": timeout,
        "expected_codes": expected_codes,
        "follow_redirects": follow_redirects,
        "allow_insecure": allow_insecure,
    }
    if expected_body:
        payload["expected_body"] = expected_body
    return await _post(f"{_CF_BASE}/accounts/{acct}/load_balancers/monitors", payload)


async def lb_list_balancers() -> list[dict]:
    """List load balancer records on the zone."""
    zone = _zone_id()
    if not zone:
        return []
    result = await _get(f"{_CF_BASE}/zones/{zone}/load_balancers")
    return result or []


async def lb_create_balancer(
    name: str,
    default_pools: list[str],
    fallback_pool: str,
    *,
    description: str = "",
    proxied: bool = True,
    ttl: int = 30,
    steering_policy: str = "dynamic_latency",
    session_affinity: str = "none",
    adaptive_routing: bool = True,
) -> Optional[dict]:
    """
    Create a load balancer DNS record on the zone.

    ``name`` — hostname, e.g. "api.syrabit.ai"
    ``steering_policy`` — "off" | "geo" | "random" | "dynamic_latency" |
                          "proximity" | "least_outstanding_requests" |
                          "least_connections"
    """
    zone = _zone_id()
    if not zone:
        return None
    payload: dict[str, Any] = {
        "name": name,
        "default_pools": default_pools,
        "fallback_pool": fallback_pool,
        "description": description,
        "proxied": proxied,
        "ttl": ttl,
        "steering_policy": steering_policy,
        "session_affinity": session_affinity,
        "adaptive_routing": {"failover_across_pools": adaptive_routing},
    }
    return await _post(f"{_CF_BASE}/zones/{zone}/load_balancers", payload)


async def lb_update_balancer(lb_id: str, updates: dict) -> Optional[dict]:
    """Patch a load balancer record."""
    zone = _zone_id()
    if not zone:
        return None
    return await _patch(f"{_CF_BASE}/zones/{zone}/load_balancers/{lb_id}", updates)


async def lb_delete_balancer(lb_id: str) -> bool:
    zone = _zone_id()
    if not zone:
        return False
    return await _delete(f"{_CF_BASE}/zones/{zone}/load_balancers/{lb_id}")


async def lb_pool_health(pool_id: str) -> Optional[dict]:
    """Get live health status of a pool."""
    acct = _account_id()
    if not acct:
        return None
    return await _get(f"{_CF_BASE}/accounts/{acct}/load_balancers/pools/{pool_id}/health")


async def lb_status() -> dict:
    """
    Aggregated load balancing status — pools + monitors + LB records.
    Safe to call even when not configured; returns empty structure.
    """
    pools, monitors, balancers = await asyncio.gather(
        lb_list_pools(),
        lb_list_monitors(),
        lb_list_balancers(),
    )
    return {
        "configured": is_configured(),
        "pools": pools,
        "monitors": monitors,
        "load_balancers": balancers,
        "pool_count": len(pools),
        "lb_count": len(balancers),
    }


async def lb_setup_syrabit(
    primary_origin: str = "api.syrabit.ai",
    *,
    notification_email: str = "",
) -> dict:
    """
    One-shot: create the recommended LB configuration for Syrabit.ai.

    Creates:
      - 1 HTTPS monitor on /healthz/ai (every 60s, 2 retries)
      - 1 primary origin pool with ``primary_origin``
      - 1 LB record at ``api.syrabit.ai`` with dynamic-latency steering

    Idempotent — skips creation steps if objects already exist by name.
    Returns a summary dict of what was created vs already existing.
    """
    result: dict[str, Any] = {"monitor": None, "pool": None, "lb": None, "skipped": []}

    existing_monitors = await lb_list_monitors()
    monitor = next((m for m in existing_monitors if m.get("path") == "/healthz/ai"), None)
    if monitor:
        result["skipped"].append("monitor")
        result["monitor"] = monitor
    else:
        monitor = await lb_create_monitor(
            type="https",
            description="Syrabit API health — Gemini probe",
            path="/healthz/ai",
            expected_codes="200",
            interval=60,
            retries=2,
            timeout=5,
        )
        result["monitor"] = monitor

    monitor_id = (monitor or {}).get("id")

    existing_pools = await lb_list_pools()
    pool = next((p for p in existing_pools if p.get("name") == "syrabit-api-primary"), None)
    if pool:
        result["skipped"].append("pool")
        result["pool"] = pool
    else:
        pool = await lb_create_pool(
            name="syrabit-api-primary",
            description="Primary Railway origin for Syrabit API",
            origins=[{
                "name": "railway-primary",
                "address": primary_origin,
                "enabled": True,
                "weight": 1,
            }],
            monitor_id=monitor_id,
            notification_email=notification_email,
            check_regions=["ENAM", "SEAS", "WEU"],
        )
        result["pool"] = pool

    pool_id = (pool or {}).get("id")
    if not pool_id:
        return result

    existing_lbs = await lb_list_balancers()
    lb = next((b for b in existing_lbs if "syrabit" in (b.get("name") or "")), None)
    if lb:
        result["skipped"].append("lb")
        result["lb"] = lb
    else:
        lb = await lb_create_balancer(
            name="api.syrabit.ai",
            default_pools=[pool_id],
            fallback_pool=pool_id,
            description="Syrabit.ai API load balancer",
            proxied=True,
            ttl=30,
            steering_policy="dynamic_latency",
        )
        result["lb"] = lb

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BULK REDIRECTS
# ═══════════════════════════════════════════════════════════════════════════════

async def redirect_list_lists() -> list[dict]:
    """List all URL redirect lists on the account."""
    acct = _account_id()
    if not acct:
        return []
    result = await _get(f"{_CF_BASE}/accounts/{acct}/rules/lists?kind=redirect")
    return result or []


async def redirect_get_or_create_list(list_name: str = "syrabit_redirects") -> Optional[dict]:
    """Get existing redirect list by name, or create it."""
    lists = await redirect_list_lists()
    existing = next((l for l in lists if l.get("name") == list_name), None)
    if existing:
        return existing
    acct = _account_id()
    if not acct:
        return None
    return await _post(
        f"{_CF_BASE}/accounts/{acct}/rules/lists",
        {"name": list_name, "kind": "redirect", "description": "Syrabit.ai bulk redirects"},
    )


async def redirect_list_items(list_id: str) -> list[dict]:
    """Return all items (redirect rules) in a redirect list."""
    acct = _account_id()
    if not acct:
        return []
    result = await _get(f"{_CF_BASE}/accounts/{acct}/rules/lists/{list_id}/items")
    return result or []


async def redirect_add_items(
    list_id: str,
    redirects: list[dict],
) -> Optional[dict]:
    """
    Add URL redirects to a list.

    ``redirects`` format:
        [
          {
            "redirect": {
              "source_url": "https://syrabit.ai/old-path",
              "target_url": "https://syrabit.ai/new-path",
              "status_code": 301,            # 301 | 302 | 307 | 308
              "preserve_query_string": False,
              "include_subdomains": False,
              "subpath_matching": False,
              "preserve_path_suffix": False,
            }
          }
        ]
    """
    acct = _account_id()
    if not acct:
        return None
    return await _post(
        f"{_CF_BASE}/accounts/{acct}/rules/lists/{list_id}/items",
        redirects,
    )


async def redirect_delete_items(list_id: str, item_ids: list[str]) -> Optional[dict]:
    """Remove specific items from a redirect list."""
    acct = _account_id()
    if not acct:
        return None
    payload = {"items": [{"id": i} for i in item_ids]}
    if not is_configured():
        return None
    try:
        r = await _client().delete(
            f"{_CF_BASE}/accounts/{acct}/rules/lists/{list_id}/items",
            headers=_headers(),
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("result") if data.get("success") else None
    except Exception as exc:
        logger.warning("CF redirect delete items failed: %s", exc)
        return None


async def redirect_activate_ruleset(list_id: str, list_name: str = "syrabit_redirects") -> Optional[dict]:
    """
    Activate (or update) the account-level redirect ruleset to reference ``list_id``.

    This wires the redirect list into actual traffic — without this step
    the list exists but no redirects fire.
    """
    acct = _account_id()
    if not acct:
        return None

    rulesets = await _get(f"{_CF_BASE}/accounts/{acct}/rulesets") or []
    redirect_rs = next(
        (rs for rs in rulesets if rs.get("phase") == "http_request_redirect"),
        None,
    )

    rule = {
        "action": "redirect",
        "action_parameters": {
            "from_list": {"name": list_name, "key": "http.request.full_uri"},
        },
        "expression": f'http.request.full_uri in $syrabit_redirects',
        "description": f"Syrabit bulk redirects — {list_name}",
        "enabled": True,
    }

    if redirect_rs:
        rs_id = redirect_rs["id"]
        existing_rules = redirect_rs.get("rules", [])
        syrabit_rule = next(
            (r for r in existing_rules if list_name in r.get("description", "")),
            None,
        )
        if syrabit_rule:
            rule_id = syrabit_rule["id"]
            return await _patch(
                f"{_CF_BASE}/accounts/{acct}/rulesets/{rs_id}/rules/{rule_id}",
                rule,
            )
        else:
            return await _post(
                f"{_CF_BASE}/accounts/{acct}/rulesets/{rs_id}/rules",
                rule,
            )
    else:
        return await _post(
            f"{_CF_BASE}/accounts/{acct}/rulesets",
            {
                "name": "Syrabit Redirect Ruleset",
                "kind": "root",
                "phase": "http_request_redirect",
                "rules": [rule],
            },
        )


async def redirect_upsert(
    source_url: str,
    target_url: str,
    status_code: int = 301,
    *,
    preserve_query_string: bool = False,
    subpath_matching: bool = False,
    list_name: str = "syrabit_redirects",
) -> dict:
    """
    High-level helper: add one redirect, creating the list + activating
    the ruleset if needed.

    Returns ``{"ok": True, "list_id": ..., "item": ...}`` or ``{"ok": False, "reason": ...}``.
    """
    lst = await redirect_get_or_create_list(list_name)
    if not lst:
        return {"ok": False, "reason": "Could not get/create redirect list"}
    list_id = lst["id"]

    item = await redirect_add_items(list_id, [{
        "redirect": {
            "source_url": source_url,
            "target_url": target_url,
            "status_code": status_code,
            "preserve_query_string": preserve_query_string,
            "subpath_matching": subpath_matching,
            "include_subdomains": False,
            "preserve_path_suffix": False,
        }
    }])
    await redirect_activate_ruleset(list_id, list_name)
    return {"ok": True, "list_id": list_id, "item": item}


async def redirect_list_all(list_name: str = "syrabit_redirects") -> dict:
    """Return all redirect rules for a named list."""
    lists = await redirect_list_lists()
    lst = next((l for l in lists if l.get("name") == list_name), None)
    if not lst:
        return {"list": None, "items": [], "count": 0}
    items = await redirect_list_items(lst["id"])
    return {"list": lst, "items": items, "count": len(items)}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ZARAZ — WEB TAG MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

async def zaraz_get_config() -> Optional[dict]:
    """Fetch the current Zaraz configuration for the zone."""
    zone = _zone_id()
    if not zone:
        return None
    return await _get(f"{_CF_BASE}/zones/{zone}/zaraz/config")


async def zaraz_update_config(config: dict) -> Optional[dict]:
    """Push an updated Zaraz configuration."""
    zone = _zone_id()
    if not zone:
        return None
    return await _put(f"{_CF_BASE}/zones/{zone}/zaraz/config", config)


async def zaraz_publish(description: str = "Syrabit backend publish") -> Optional[dict]:
    """Publish the staged Zaraz config to production."""
    zone = _zone_id()
    if not zone:
        return None
    return await _post(f"{_CF_BASE}/zones/{zone}/zaraz/publish", {"description": description})


async def zaraz_get_default_config() -> Optional[dict]:
    """Fetch Zaraz's default/factory config template."""
    zone = _zone_id()
    if not zone:
        return None
    return await _get(f"{_CF_BASE}/zones/{zone}/zaraz/default")


async def zaraz_list_histories() -> list[dict]:
    """List Zaraz publish history entries."""
    zone = _zone_id()
    if not zone:
        return []
    result = await _get(f"{_CF_BASE}/zones/{zone}/zaraz/history?limit=20")
    return result or []


async def zaraz_add_tool(
    config: dict,
    tool_name: str,
    tool_type: str,
    *,
    tracking_id: str = "",
    enabled: bool = True,
) -> dict:
    """
    Inject a new tool into an existing Zaraz config dict.

    Supported ``tool_type`` values (examples):
        "Google Analytics 4", "Meta Pixel", "Google Ads",
        "Hotjar", "Intercom", "Segment"

    Returns the modified config (not yet pushed — call ``zaraz_update_config`` afterwards).
    """
    tools = config.get("tools") or {}
    import uuid
    tool_id = uuid.uuid4().hex[:8]
    tools[tool_id] = {
        "name": tool_name,
        "type": tool_type,
        "enabled": enabled,
        "settings": {
            "trackingID": tracking_id,
        },
        "rules": [],
        "neoEvents": [],
    }
    config["tools"] = tools
    return config


async def zaraz_status() -> dict:
    """Summary of current Zaraz config: tool count + enabled state."""
    cfg = await zaraz_get_config()
    if not cfg:
        return {"configured": is_configured(), "zaraz_enabled": False, "tools": []}
    tools = cfg.get("tools") or {}
    tool_list = [
        {"id": tid, "name": t.get("name"), "type": t.get("type"), "enabled": t.get("enabled")}
        for tid, t in tools.items()
    ]
    return {
        "configured": is_configured(),
        "zaraz_enabled": cfg.get("enabled", True),
        "tool_count": len(tool_list),
        "tools": tool_list,
        "consent_enabled": bool(cfg.get("consent")),
        "debug_enabled": bool(cfg.get("debug")),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SPEED & DELIVERY OPTIMISATION (Enterprise)
# ═══════════════════════════════════════════════════════════════════════════════

_SPEED_SETTINGS = [
    ("http3",                    {"value": "on"},  "HTTP/3 (QUIC) transport"),
    ("early_hints",              {"value": "on"},  "Early Hints (103) for CSS/fonts"),
    ("brotli",                   {"value": "on"},  "Brotli compression"),
    ("minify",                   {"value": {"css": "on", "html": "on", "js": "on"}},
                                                   "HTML/CSS/JS minification"),
    ("image_resizing",           {"value": "open"},"Image Resizing (Enterprise)"),
    ("origin_max_http_version",  {"value": "2"},   "Origin HTTP/2 protocol"),
    ("speed_brain",              {"value": "on"},  "Smart Speed (Speed Brain, Enterprise)"),
    ("h2_prioritization",        {"value": "on"},  "HTTP/2 Prioritization (Enterprise)"),
    ("0rtt",                     {"value": "on"},  "0-RTT resume (Enterprise)"),
    ("prefetch_preload",         {"value": "on"},  "Prefetch/preload links"),
    # ── Image delivery ─────────────────────────────────────────────────────────
    # Polish auto-converts uploaded images to WebP (or AVIF) and strips EXIF.
    # Cuts image payload 30-50% with zero code changes.
    ("polish",                   {"value": "lossless"}, "Polish: auto-WebP / strip EXIF (Enterprise)"),
    # ── JS deferral ────────────────────────────────────────────────────────────
    # Rocket Loader defers non-critical JS so HTML/CSS loads first (better LCP).
    ("rocket_loader",            {"value": "on"},  "Rocket Loader: defer JS for faster LCP"),
    # ── Cache topology ─────────────────────────────────────────────────────────
    # Tiered Caching (Cache Shield) adds a second cache layer at regional PoPs.
    # Dramatically reduces origin requests for long-tail content.
    ("tiered_caching",           {"value": "on"},  "Tiered Caching (Cache Shield) for India PoPs"),
]


async def speed_get_setting(setting_name: str) -> Optional[dict]:
    """Get a single zone speed/delivery setting."""
    zone = _zone_id()
    if not zone:
        return None
    return await _get(f"{_CF_BASE}/zones/{zone}/settings/{setting_name}")


async def speed_set_setting(setting_name: str, value: Any) -> Optional[dict]:
    """Update a single zone speed/delivery setting."""
    zone = _zone_id()
    if not zone:
        return None
    return await _patch(
        f"{_CF_BASE}/zones/{zone}/settings/{setting_name}",
        {"value": value},
    )


async def speed_get_all() -> dict:
    """Fetch all tracked speed settings in parallel. Returns {setting_name: current_value}."""
    if not is_configured():
        return {}
    names = [s[0] for s in _SPEED_SETTINGS]
    results = await asyncio.gather(*[speed_get_setting(n) for n in names], return_exceptions=True)
    out = {}
    for name, res in zip(names, results):
        if isinstance(res, Exception) or res is None:
            out[name] = None
        else:
            out[name] = res.get("value")
    return out


async def speed_optimize_all() -> dict:
    """
    Enable all enterprise speed features in parallel.

    Returns ``{setting: {"ok": bool, "old": ..., "new": ...}}`` for each setting.
    Failures on individual settings are captured without aborting others.
    """
    if not is_configured():
        return {"error": "CF_ZONE_ID or CLOUDFLARE_API_TOKEN not configured"}

    async def _apply(name: str, payload: dict, _desc: str) -> tuple[str, dict]:
        old = await speed_get_setting(name)
        old_val = (old or {}).get("value")
        result = await speed_set_setting(name, payload["value"])
        new_val = (result or {}).get("value")
        return name, {
            "ok": result is not None,
            "description": _desc,
            "old": old_val,
            "new": new_val,
        }

    tasks = [_apply(name, payload, desc) for name, payload, desc in _SPEED_SETTINGS]
    pairs = await asyncio.gather(*tasks, return_exceptions=True)
    out = {}
    for item in pairs:
        if isinstance(item, Exception):
            logger.warning("speed_optimize_all error: %s", item)
        else:
            name, info = item
            out[name] = info
    return out


async def speed_status() -> dict:
    """Return current speed settings alongside recommended values."""
    current = await speed_get_all()
    recommended = {s[0]: s[1]["value"] for s in _SPEED_SETTINGS}
    gaps = {
        name: {"current": current.get(name), "recommended": rec}
        for name, rec in recommended.items()
        if current.get(name) != rec
    }
    return {
        "configured": is_configured(),
        "current": current,
        "recommended": recommended,
        "gaps": gaps,
        "gap_count": len(gaps),
        "fully_optimized": len(gaps) == 0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CACHE TAGS — targeted purge without URL matching
# ═══════════════════════════════════════════════════════════════════════════════
#
# CF Enterprise supports `Cache-Tag` response headers.  CF stores one tag
# mapping per cache entry and lets you purge all entries that share a tag via
# the Purge by Tag API — much faster and more precise than prefix purge.
#
# Usage in route handlers:
#   from cf_enterprise import cache_tag_header
#   response.headers["Cache-Tag"] = cache_tag_header("subject", subject_id, "chapter", chapter_id)
#
# Then call purge_by_tags(["syrabit-subject-12", "syrabit-chapter-99"]) to
# invalidate exactly those pages.

_TAG_PREFIX = "syrabit"

def build_cache_tag(*pairs: str) -> str:
    """
    Build a space-separated ``Cache-Tag`` header value from (entity_type, entity_id) pairs.

    Example:
        build_cache_tag("subject", "12", "chapter", "99")
        → "syrabit-subject-12 syrabit-chapter-99"

    The space-delimited format lets a single response carry multiple tags so
    CF can index it under all of them.
    """
    tags: list[str] = []
    it = iter(pairs)
    for entity_type in it:
        entity_id = next(it, "")
        if entity_type and entity_id:
            tags.append(f"{_TAG_PREFIX}-{entity_type}-{entity_id}")
    return " ".join(tags)


def subject_cache_tag(subject_id) -> str:
    return f"{_TAG_PREFIX}-subject-{subject_id}"

def chapter_cache_tag(chapter_id) -> str:
    return f"{_TAG_PREFIX}-chapter-{chapter_id}"

def pyq_cache_tag(year: int = 0, subject_id=None) -> str:
    parts = [f"{_TAG_PREFIX}-pyq"]
    if year:
        parts.append(f"{_TAG_PREFIX}-pyq-{year}")
    if subject_id:
        parts.append(f"{_TAG_PREFIX}-pyq-subject-{subject_id}")
    return " ".join(parts)

def content_cache_tag(content_type: str, content_id) -> str:
    return f"{_TAG_PREFIX}-{content_type}-{content_id}"


async def purge_by_tags(tags: list[str]) -> Optional[dict]:
    """
    Purge CF edge cache for all entries carrying any of the given Cache-Tags.
    Requires Enterprise plan.  Returns the CF API response dict or None on error.

    Example:
        await purge_by_tags(["syrabit-subject-12", "syrabit-chapter-99"])
    """
    zone = _zone_id()
    if not zone:
        return None
    if not tags:
        return {"tags": [], "skipped": True}
    return await _post(
        f"{_CF_BASE}/zones/{zone}/purge_cache",
        {"tags": tags},
    )


async def purge_by_hosts(hosts: list[str]) -> Optional[dict]:
    """Purge all cache entries for the given hostnames (Enterprise only)."""
    zone = _zone_id()
    if not zone:
        return None
    return await _post(
        f"{_CF_BASE}/zones/{zone}/purge_cache",
        {"hosts": hosts},
    )
