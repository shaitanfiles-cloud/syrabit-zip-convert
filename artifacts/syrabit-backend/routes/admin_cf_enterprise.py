"""
Admin routes — Cloudflare Enterprise Features.

Exposes load balancing, bulk redirects, Zaraz, and speed optimisation
via authenticated admin endpoints.  All write operations require admin auth.

Endpoints:
  GET  /admin/cf/status             — combined enterprise health snapshot
  GET  /admin/cf/load-balancing     — pools + monitors + LB records
  POST /admin/cf/load-balancing/setup    — one-shot setup for Syrabit
  POST /admin/cf/load-balancing/pools   — create a pool
  PATCH /admin/cf/load-balancing/pools/{pool_id}  — update a pool
  DELETE /admin/cf/load-balancing/pools/{pool_id} — delete a pool
  GET  /admin/cf/load-balancing/pools/{pool_id}/health  — live health
  POST /admin/cf/load-balancing/balancers   — create LB record
  DELETE /admin/cf/load-balancing/balancers/{lb_id} — delete LB

  GET  /admin/cf/bulk-redirects          — list redirects
  POST /admin/cf/bulk-redirects          — add a redirect
  DELETE /admin/cf/bulk-redirects/items  — delete redirect items

  GET  /admin/cf/zaraz            — current Zaraz status
  GET  /admin/cf/zaraz/config     — full Zaraz config JSON
  PUT  /admin/cf/zaraz/config     — push updated config
  POST /admin/cf/zaraz/publish    — publish staged config
  POST /admin/cf/zaraz/tools      — add a tag/tool

  GET  /admin/cf/speed            — current vs recommended speed settings
  POST /admin/cf/speed/optimize   — apply all enterprise speed optimisations
  PATCH /admin/cf/speed/{setting} — update a single setting
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_deps import get_admin_user
import cf_enterprise as cfe

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class OriginModel(BaseModel):
    name: str
    address: str
    enabled: bool = True
    weight: float = 1.0


class CreatePoolRequest(BaseModel):
    name: str
    origins: List[OriginModel]
    description: str = ""
    enabled: bool = True
    minimum_origins: int = 1
    monitor_id: Optional[str] = None
    notification_email: str = ""
    check_regions: Optional[List[str]] = None


class UpdatePoolRequest(BaseModel):
    origins: Optional[List[OriginModel]] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    minimum_origins: Optional[int] = None


class CreateBalancerRequest(BaseModel):
    name: str
    default_pools: List[str]
    fallback_pool: str
    description: str = ""
    proxied: bool = True
    ttl: int = 30
    steering_policy: str = "dynamic_latency"
    session_affinity: str = "none"
    adaptive_routing: bool = True


class SetupLbRequest(BaseModel):
    primary_origin: str = "api.syrabit.ai"
    notification_email: str = ""


class RedirectItem(BaseModel):
    source_url: str
    target_url: str
    status_code: int = Field(default=301, ge=301, le=308)
    preserve_query_string: bool = False
    subpath_matching: bool = False


class AddRedirectRequest(BaseModel):
    redirects: List[RedirectItem]
    list_name: str = "syrabit_redirects"


class DeleteRedirectItemsRequest(BaseModel):
    list_id: str
    item_ids: List[str]


class ZarazConfigRequest(BaseModel):
    config: dict


class ZarazPublishRequest(BaseModel):
    description: str = "Syrabit backend publish"


class ZarazAddToolRequest(BaseModel):
    tool_name: str
    tool_type: str
    tracking_id: str = ""
    enabled: bool = True


class SpeedSettingRequest(BaseModel):
    value: Any


# ── combined status ───────────────────────────────────────────────────────────

@router.get("/admin/cf/status")
async def cf_enterprise_status(admin: dict = Depends(get_admin_user)):
    """Combined snapshot of all CF Enterprise subsystems."""
    lb, zaraz, speed = await _run_parallel(
        cfe.lb_status(),
        cfe.zaraz_status(),
        cfe.speed_status(),
    )
    return {
        "configured": cfe.is_configured(),
        "load_balancing": lb,
        "zaraz": zaraz,
        "speed": speed,
    }


# ── load balancing ────────────────────────────────────────────────────────────

@router.get("/admin/cf/load-balancing")
async def cf_lb_status(admin: dict = Depends(get_admin_user)):
    return await cfe.lb_status()


@router.post("/admin/cf/load-balancing/setup")
async def cf_lb_setup(req: SetupLbRequest, admin: dict = Depends(get_admin_user)):
    """One-shot idempotent LB setup for Syrabit.ai."""
    result = await cfe.lb_setup_syrabit(
        primary_origin=req.primary_origin,
        notification_email=req.notification_email,
    )
    return result


@router.post("/admin/cf/load-balancing/pools")
async def cf_lb_create_pool(req: CreatePoolRequest, admin: dict = Depends(get_admin_user)):
    origins = [o.model_dump() for o in req.origins]
    result = await cfe.lb_create_pool(
        name=req.name,
        origins=origins,
        description=req.description,
        enabled=req.enabled,
        minimum_origins=req.minimum_origins,
        monitor_id=req.monitor_id,
        notification_email=req.notification_email,
        check_regions=req.check_regions,
    )
    if not result:
        raise HTTPException(502, "Failed to create pool — check CF credentials and plan")
    return result


@router.patch("/admin/cf/load-balancing/pools/{pool_id}")
async def cf_lb_update_pool(pool_id: str, req: UpdatePoolRequest, admin: dict = Depends(get_admin_user)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if "origins" in updates:
        updates["origins"] = [o.model_dump() for o in req.origins]
    result = await cfe.lb_update_pool(pool_id, updates)
    if not result:
        raise HTTPException(502, "Failed to update pool")
    return result


@router.delete("/admin/cf/load-balancing/pools/{pool_id}")
async def cf_lb_delete_pool(pool_id: str, admin: dict = Depends(get_admin_user)):
    ok = await cfe.lb_delete_pool(pool_id)
    return {"ok": ok}


@router.get("/admin/cf/load-balancing/pools/{pool_id}/health")
async def cf_lb_pool_health(pool_id: str, admin: dict = Depends(get_admin_user)):
    result = await cfe.lb_pool_health(pool_id)
    if result is None:
        raise HTTPException(404, "Pool not found or CF not configured")
    return result


@router.post("/admin/cf/load-balancing/balancers")
async def cf_lb_create_balancer(req: CreateBalancerRequest, admin: dict = Depends(get_admin_user)):
    result = await cfe.lb_create_balancer(
        name=req.name,
        default_pools=req.default_pools,
        fallback_pool=req.fallback_pool,
        description=req.description,
        proxied=req.proxied,
        ttl=req.ttl,
        steering_policy=req.steering_policy,
        session_affinity=req.session_affinity,
        adaptive_routing=req.adaptive_routing,
    )
    if not result:
        raise HTTPException(502, "Failed to create load balancer")
    return result


@router.delete("/admin/cf/load-balancing/balancers/{lb_id}")
async def cf_lb_delete_balancer(lb_id: str, admin: dict = Depends(get_admin_user)):
    ok = await cfe.lb_delete_balancer(lb_id)
    return {"ok": ok}


# ── bulk redirects ────────────────────────────────────────────────────────────

@router.get("/admin/cf/bulk-redirects")
async def cf_redirect_list(
    list_name: str = "syrabit_redirects",
    admin: dict = Depends(get_admin_user),
):
    return await cfe.redirect_list_all(list_name)


@router.post("/admin/cf/bulk-redirects")
async def cf_redirect_add(req: AddRedirectRequest, admin: dict = Depends(get_admin_user)):
    """Add one or more URL redirects. Creates the list + activates the ruleset if needed."""
    lst = await cfe.redirect_get_or_create_list(req.list_name)
    if not lst:
        raise HTTPException(502, "Could not create/retrieve redirect list — check CF credentials")
    list_id = lst["id"]

    items = [{
        "redirect": {
            "source_url": r.source_url,
            "target_url": r.target_url,
            "status_code": r.status_code,
            "preserve_query_string": r.preserve_query_string,
            "subpath_matching": r.subpath_matching,
            "include_subdomains": False,
            "preserve_path_suffix": False,
        }
    } for r in req.redirects]

    result = await cfe.redirect_add_items(list_id, items)
    await cfe.redirect_activate_ruleset(list_id, req.list_name)
    return {"ok": True, "list_id": list_id, "added": result}


@router.delete("/admin/cf/bulk-redirects/items")
async def cf_redirect_delete_items(req: DeleteRedirectItemsRequest, admin: dict = Depends(get_admin_user)):
    result = await cfe.redirect_delete_items(req.list_id, req.item_ids)
    return {"ok": result is not None, "result": result}


# ── zaraz / web tag management ────────────────────────────────────────────────

@router.get("/admin/cf/zaraz")
async def cf_zaraz_status(admin: dict = Depends(get_admin_user)):
    return await cfe.zaraz_status()


@router.get("/admin/cf/zaraz/config")
async def cf_zaraz_get_config(admin: dict = Depends(get_admin_user)):
    cfg = await cfe.zaraz_get_config()
    if cfg is None:
        raise HTTPException(503, "Zaraz config unavailable — check CF_ZONE_ID and token scopes")
    return cfg


@router.put("/admin/cf/zaraz/config")
async def cf_zaraz_update_config(req: ZarazConfigRequest, admin: dict = Depends(get_admin_user)):
    result = await cfe.zaraz_update_config(req.config)
    if not result:
        raise HTTPException(502, "Failed to update Zaraz config")
    return result


@router.post("/admin/cf/zaraz/publish")
async def cf_zaraz_publish(req: ZarazPublishRequest, admin: dict = Depends(get_admin_user)):
    result = await cfe.zaraz_publish(req.description)
    if not result:
        raise HTTPException(502, "Failed to publish Zaraz config")
    return result


@router.post("/admin/cf/zaraz/tools")
async def cf_zaraz_add_tool(req: ZarazAddToolRequest, admin: dict = Depends(get_admin_user)):
    """Add a new tag/tool to Zaraz. Fetches current config, injects tool, pushes + publishes."""
    cfg = await cfe.zaraz_get_config()
    if cfg is None:
        raise HTTPException(503, "Cannot fetch Zaraz config")
    cfg = await cfe.zaraz_add_tool(
        cfg,
        tool_name=req.tool_name,
        tool_type=req.tool_type,
        tracking_id=req.tracking_id,
        enabled=req.enabled,
    )
    result = await cfe.zaraz_update_config(cfg)
    if not result:
        raise HTTPException(502, "Failed to save Zaraz tool")
    publish = await cfe.zaraz_publish(f"Added tool: {req.tool_name}")
    return {"ok": True, "config_saved": result, "published": publish}


@router.get("/admin/cf/zaraz/history")
async def cf_zaraz_history(admin: dict = Depends(get_admin_user)):
    return await cfe.zaraz_list_histories()


# ── speed & delivery optimisation ────────────────────────────────────────────

@router.get("/admin/cf/speed")
async def cf_speed_status(admin: dict = Depends(get_admin_user)):
    return await cfe.speed_status()


@router.post("/admin/cf/speed/optimize")
async def cf_speed_optimize(admin: dict = Depends(get_admin_user)):
    """Enable all enterprise speed features in parallel."""
    result = await cfe.speed_optimize_all()
    applied = sum(1 for v in result.values() if isinstance(v, dict) and v.get("ok"))
    return {
        "ok": True,
        "applied": applied,
        "total": len(result),
        "details": result,
    }


@router.patch("/admin/cf/speed/{setting_name}")
async def cf_speed_set(
    setting_name: str,
    req: SpeedSettingRequest,
    admin: dict = Depends(get_admin_user),
):
    """Update a single CF zone speed setting by name."""
    known = {s[0] for s in cfe._SPEED_SETTINGS}
    if setting_name not in known:
        raise HTTPException(
            400,
            f"Unknown setting '{setting_name}'. Valid: {sorted(known)}",
        )
    result = await cfe.speed_set_setting(setting_name, req.value)
    if not result:
        raise HTTPException(502, f"Failed to update CF setting '{setting_name}'")
    return result


# ── helpers ───────────────────────────────────────────────────────────────────

async def _run_parallel(*coros):
    import asyncio
    return await asyncio.gather(*coros, return_exceptions=True)
