"""
startup_checks.py — Non-fatal startup checks called from server.py lifespan.

Each check is a standalone async function so it can be imported and tested
independently without dragging in the full server.py module graph.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("syrabit.startup")


async def run_atlas_vs_startup_check() -> dict:
    """Check the Atlas Vector Search index at startup when ATLAS_VS_ENABLED=true.

    Pinecone is the primary vector store (Task #203/208). The Atlas
    $vectorSearch path is an emergency fallback. This check is skipped by
    default (ATLAS_VS_ENABLED not set) to avoid unnecessary Atlas traffic.
    Set ATLAS_VS_ENABLED=true to re-enable the check (e.g. during fallback
    recovery after a Pinecone outage).

    Always returns a status dict — never raises. Errors are logged as
    WARNING so startup continues unblocked.

    Returns
    -------
    dict with keys:
      "skipped"  : True when ATLAS_VS_ENABLED is not set (default off)
      "ok"       : True when ensure_vector_index() succeeded or index exists
      "reason"   : error message when ok=False
    """
    _atlas_vs_enabled = os.environ.get("ATLAS_VS_ENABLED", "").strip().lower() in (
        "1", "true", "yes"
    )
    if not _atlas_vs_enabled:
        logger.debug("Atlas Vector Search index check skipped (ATLAS_VS_ENABLED not set)")
        return {"skipped": True}
    try:
        from retrievers.mongodb_vector import ensure_vector_index as _ensure_vs
        _vs_result = await _ensure_vs()
        logger.info("Atlas Vector Search index check: %s", _vs_result)
        return _vs_result
    except Exception as _vs_err:
        logger.warning(
            "Atlas Vector Search index ensure failed (non-blocking): %s", _vs_err
        )
        return {"ok": False, "reason": str(_vs_err)}
