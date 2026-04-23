"""Syrabit.ai — Public client config endpoints.

Exposes configuration values that the frontend needs at runtime but that
must not be hard-coded in the JS bundle (so they can be rotated in
secrets without a rebuild). Currently used for the Trustpilot widget
business unit ID and review URL (Task #724).
"""
from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/config/trustpilot")
async def get_trustpilot_config() -> Dict[str, Any]:
    """Return the Trustpilot business unit + review URL for client widgets.

    All fields are best-effort — when the Trustpilot secret isn't
    configured we return empty strings and the client hides the widget
    gracefully. Always HTTP 200 so the client can branch on payload
    contents rather than network failure.
    """
    business_unit_id = (os.environ.get("TRUSTPILOT_BUSINESS_UNIT_ID") or "").strip()
    domain = (os.environ.get("TRUSTPILOT_DOMAIN") or "syrabit.ai").strip()
    profile_url = (
        os.environ.get("TRUSTPILOT_PROFILE_URL")
        or (f"https://www.trustpilot.com/review/{domain}" if domain else "")
    ).strip()
    review_url = (
        os.environ.get("TRUSTPILOT_REVIEW_URL")
        or (f"https://www.trustpilot.com/evaluate/{domain}" if domain else "")
    ).strip()
    return {
        "businessUnitId": business_unit_id,
        "domain": domain,
        "profileUrl": profile_url,
        "writeReviewUrl": review_url,
        "scriptSrc": "https://widget.trustpilot.com/bootstrap/v5/tp.widget.bootstrap.min.js",
    }
