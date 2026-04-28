"""Syrabit.ai — Google Analytics 4 OAuth setup (admin).

Carved out of ``cms_sarvam_health.py`` (Task #5 of the admin-panel
audit) so the routes live in a file whose name reflects what they do.
The 4 endpoints here own the GA4 OAuth handshake + connection test
that the admin dashboard's "Analytics → GA4" panel calls.

Routes (all ``/api/admin/ga4/*``):
  * GET  /status     — is a refresh token configured (env or db)?
  * GET  /auth-url   — start the OAuth consent flow
  * POST /connect    — exchange the auth code for a refresh token + persist
  * GET  /test       — call GA4 with the stored token to prove it works
"""
import logging

from fastapi import APIRouter, Body, Depends, HTTPException

import ga4_client
from auth_deps import get_admin_user
from config import Configurator
from deps import db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/admin/ga4/status")
async def ga4_status(admin: dict = Depends(get_admin_user)):
    token_env = Configurator.get("GA4_REFRESH_TOKEN", "")
    # Also check db.api_config in case token was persisted there
    token_db = ""
    try:
        cfg = await db.api_config.find_one({}, {"ga4": 1})
        token_db = (cfg or {}).get("ga4", {}).get("refresh_token", "")
    except Exception:
        pass
    connected = bool(token_env or token_db)
    return {
        "connected": connected,
        "token_source": "env" if token_env else ("db" if token_db else "none"),
        "property_id": Configurator.get("GA4_PROPERTY_ID", ""),
        "client_id_set": bool(Configurator.get("GOOGLE_OAUTH_CLIENT_ID")),
        "client_secret_set": bool(Configurator.get("GOOGLE_CLIENT_SECRET")),
    }


@router.get("/admin/ga4/auth-url")
async def ga4_auth_url(redirect_uri: str, admin: dict = Depends(get_admin_user)):
    url = ga4_client.get_oauth_url(redirect_uri)
    return {"url": url}


@router.post("/admin/ga4/connect")
async def ga4_connect(
    code: str = Body(...),
    redirect_uri: str = Body(...),
    admin: dict = Depends(get_admin_user),
):
    tokens = await ga4_client.exchange_code_for_tokens(code, redirect_uri)
    if not tokens or "refresh_token" not in tokens:
        raise HTTPException(status_code=400, detail="Failed to exchange code — ensure you selected the correct Google account with GA4 access and that you clicked 'Allow'.")
    refresh_token = tokens["refresh_token"]
    # Persist to MongoDB so it survives process restarts
    await db.api_config.update_one({}, {"$set": {"ga4.refresh_token": refresh_token}}, upsert=True)
    # Also update current process env so GA4 works immediately without restart
    from config import Configurator
    Configurator.set_runtime_env("GA4_REFRESH_TOKEN", refresh_token)
    ga4_client._db_token_cache["token"] = refresh_token
    ga4_client._db_token_cache["loaded"] = True
    logger.info("GA4 refresh token stored in db.api_config and via Configurator")
    return {
        "status": "connected",
        "message": "GA4 connected. Token persisted to database — no Replit Secret needed.",
    }


@router.get("/admin/ga4/test")
async def ga4_test(admin: dict = Depends(get_admin_user)):
    stats = await ga4_client.get_visitor_stats_ga4(days=7)
    if stats is None:
        return {"ok": False, "reason": "GA4 not configured or refresh token missing"}
    return {"ok": True, "stats": stats}
