"""Admin endpoint to drive the SEO keyword + metadata enrichment service.

Exposes:
  GET /api/admin/seo/enrich?seed=<topic>&force=<0|1>&country=IN&language=en-IN

Returns the merged keyword list plus the LLM-enriched (or template-only)
SEO bundle. Designed to be the single endpoint the admin dashboard hits
when a content editor wants to populate `<meta>`, OpenGraph, Twitter
Card, and `LearningResource` JSON-LD for a chapter or topic page.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth_deps import get_admin_user
from deps import db
from seo_keyword_service import enrich_seo_for_seed

router = APIRouter()


@router.get("/api/admin/seo/enrich")
async def admin_seo_enrich(
    seed: str = Query(..., min_length=2, max_length=200,
                      description="Topic / chapter title to enrich."),
    country: str = Query("IN", min_length=2, max_length=2),
    language: str = Query("en-IN", min_length=2, max_length=10),
    force: bool = Query(False, description="Bypass the 14-day cache."),
    admin: dict = Depends(get_admin_user),
):
    bing_api_key = os.environ.get("BING_WEBMASTER_API_KEY", "")
    try:
        result = await enrich_seo_for_seed(
            seed,
            db=db,
            bing_api_key=bing_api_key,
            country=country,
            language=language,
            force=force,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"enrichment failed: {exc}")
    return result
