"""Task #750 — Surface the Trustpilot AggregateRating JSON-LD verifier
result on the admin dashboard.

The build-time inject step (Task #748) and the daily scheduled verifier
(`.github/workflows/trustpilot-jsonld-prod.yml`) already protect SERP
star coverage — but failures only land in GitHub Actions email, which
the non-engineering ops/marketing team doesn't watch. This module
exposes a tiny store/serve pair so the verifier can ship its per-URL
result table to the same admin dashboard the team already checks for
delivery + alert health.

Endpoints
---------
* ``POST /api/admin/trustpilot-jsonld/report`` — webhook the scheduled
  workflow (and any future on-demand runs) calls with the JSON the
  verifier produced via ``--json-out=<path>``. Authenticated by the
  shared ``TRUSTPILOT_REFRESH_SECRET`` header (same secret already used
  by the aggregate refresh webhook in ``routes/config.py``) so we don't
  need to provision/leak a second secret. The latest report replaces
  the previous one — we only care about the most recent run.

* ``GET /api/admin/trustpilot-jsonld/report`` — admin-protected read
  used by the AdminHealth tile. Returns ``{configured: false, ...}``
  when no report has been ingested yet so the UI can show a clear
  "no data" state instead of an error.

Storage
-------
A single Mongo doc keyed by ``_id="trustpilot_jsonld_verifier_report"``
in ``db.api_config`` (the same collection ``routes/admin_monetization.py``
uses for similar telemetry rows). One doc, replaced atomically — there
is no history requirement; the GitHub Actions run log is the audit
trail.
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from auth_deps import get_admin_user
from deps import db

logger = logging.getLogger(__name__)
router = APIRouter()

_DOC_ID = "trustpilot_jsonld_verifier_report"

# Reuse the aggregate-refresh secret (Task #749) — the workflow already
# has it in repo secrets and the backend already requires it for the
# sibling Trustpilot webhook, so we avoid a second knob to forget.
_SECRET_ENV = "TRUSTPILOT_REFRESH_SECRET"


def _expected_secret() -> str:
    return (os.environ.get(_SECRET_ENV) or "").strip()


def _coerce_results(raw: Any) -> list[dict[str, Any]]:
    """Defensively normalise the per-URL list — the verifier can emit
    nulls for ratingValue/reviewCount on failure, and we never want a
    single bad row to break the dashboard render."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url") or "").strip()
        if not url:
            continue
        item: dict[str, Any] = {
            "url": url,
            "pass": bool(r.get("pass")),
            "status": r.get("status"),
        }
        if r.get("ratingValue") is not None:
            try:
                item["ratingValue"] = float(r["ratingValue"])
            except (TypeError, ValueError):
                item["ratingValue"] = None
        if r.get("reviewCount") is not None:
            try:
                item["reviewCount"] = int(r["reviewCount"])
            except (TypeError, ValueError):
                item["reviewCount"] = None
        if r.get("reason"):
            item["reason"] = str(r["reason"])[:300]
        out.append(item)
    return out


@router.post("/admin/trustpilot-jsonld/report")
async def ingest_trustpilot_jsonld_report(
    body: dict[str, Any] = Body(...),
    x_trustpilot_refresh_secret: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Persist the latest verifier run so the admin dashboard can render
    pass/fail per URL. Auth: shared ``TRUSTPILOT_REFRESH_SECRET`` header
    (same secret as the aggregate refresh webhook). Returns 503 when the
    secret isn't configured (fail-closed) and 401 on mismatch."""
    expected = _expected_secret()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="trustpilot_refresh_secret_not_configured",
        )
    provided = (x_trustpilot_refresh_secret or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid_refresh_secret")

    results = _coerce_results(body.get("results"))

    def _safe_int(value: Any, default: int) -> int:
        """Coerce summary counters defensively. A malformed webhook
        payload should not 500 — better to fall back to the value we
        can derive from ``results`` so the dashboard still updates."""
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    derived_failed = sum(1 for r in results if not r["pass"])
    total = _safe_int(body.get("totalUrls"), len(results))
    failed = _safe_int(body.get("failed"), derived_failed)
    passed = _safe_int(body.get("passed"), max(total - failed, 0))
    ok_explicit = body.get("ok")
    ok = bool(ok_explicit) if ok_explicit is not None else (failed == 0)

    generated_at = body.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at:
        generated_at = datetime.now(timezone.utc).isoformat()

    doc = {
        "_id": _DOC_ID,
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "ingestedAt": datetime.now(timezone.utc).isoformat(),
        "target": str(body.get("target") or "remote"),
        "origin": body.get("origin") or None,
        "totalUrls": total,
        "passed": passed,
        "failed": failed,
        "ok": ok,
        "results": results,
        # Preserve the GH Actions context so the dashboard can deep-link
        # to the failing run when ops wants the full log.
        "runUrl": (body.get("runUrl") or "") or None,
    }
    await db.api_config.replace_one({"_id": _DOC_ID}, doc, upsert=True)
    logger.info(
        "trustpilot jsonld report ingested: %s/%s pass (target=%s)",
        passed, total, doc["target"],
    )
    return {"ok": True, "stored": True, "passed": passed, "failed": failed}


@router.get("/admin/trustpilot-jsonld/report")
async def get_trustpilot_jsonld_report(
    admin: dict = Depends(get_admin_user),
) -> dict[str, Any]:
    """Return the most recent verifier report for the AdminHealth tile.
    Always 200; the UI branches on ``configured`` / ``ok``."""
    doc = await db.api_config.find_one({"_id": _DOC_ID})
    if not doc:
        return {"configured": False, "report": None}
    doc.pop("_id", None)
    return {"configured": True, "report": doc}
