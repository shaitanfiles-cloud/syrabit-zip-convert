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

import asyncio
import hmac
import logging
import os
import uuid
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

    # Task #753 — load prior report BEFORE replacing so we can diff
    # per-URL pass/fail state and fan out a regression / recovery email
    # without ops having to actively poll the dashboard. The verifier
    # webhook only fires once per scheduled GitHub Actions run, so the
    # window between the read and write here is negligible — best-effort
    # is fine, and the alert path itself never raises into the ingest.
    prior_doc: dict[str, Any] = {}
    try:
        prior_doc = await db.api_config.find_one({"_id": _DOC_ID}) or {}
    except Exception as exc:
        logger.debug("trustpilot jsonld prior load failed: %s", exc)
        prior_doc = {}

    new_failed_urls = sorted({r["url"] for r in results if not r["pass"]})

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
        # Per-URL dedup ledger for Task #753: which URLs we've already
        # paged ops about in the *current* failing streak. Cleared the
        # moment a URL flips back to pass, so the next regression on
        # the same URL re-pages.
        "alertedFailedUrls": new_failed_urls,
    }
    await db.api_config.replace_one({"_id": _DOC_ID}, doc, upsert=True)
    logger.info(
        "trustpilot jsonld report ingested: %s/%s pass (target=%s)",
        passed, total, doc["target"],
    )

    # Best-effort fan-out — never fail ingest if the alert path errors.
    try:
        await _maybe_dispatch_jsonld_alerts(prior_doc, doc)
    except Exception as exc:
        logger.warning("trustpilot jsonld alert dispatch errored: %s", exc)

    return {"ok": True, "stored": True, "passed": passed, "failed": failed}


# ─── Task #753 — regression / recovery email + in-app notifications ────────
#
# Mirrors the helper shape used by ``routes/admin_trustpilot_alerts.py``
# (Task #728) so the inbox looks consistent across all Trustpilot alert
# channels. We deliberately reuse:
#
# * ``email_templates._send`` for the SMTP/Resend send (same path the
#   existing aggregate-feed alerter uses);
# * ``db_ops.supa_insert_notification`` for the in-app notification —
#   which is also what powers the existing Slack/webhook fan-out for
#   admin alerts (the notification record is the single source of
#   truth that downstream channels subscribe to).
#
# Dedup contract (per the task spec):
# * regression email: sent the first time a URL flips PASS→FAIL, then
#   suppressed for that URL until it flips back to pass. The set of
#   "currently alerted" URLs is persisted on the report doc itself
#   (``alertedFailedUrls``) so we don't need a second collection.
# * recovery email: sent exactly once when the previously-non-empty
#   alerted set returns to empty (i.e. all URLs pass again).


async def _maybe_dispatch_jsonld_alerts(
    prior_doc: dict[str, Any], new_doc: dict[str, Any],
) -> None:
    """Diff prior vs new per-URL state and emit regression / recovery
    notifications. Best-effort: callers swallow exceptions."""
    prior_alerted = set(
        (prior_doc or {}).get("alertedFailedUrls") or []
    )
    new_failed = {r["url"] for r in new_doc.get("results", []) if not r["pass"]}
    newly_failed = new_failed - prior_alerted

    if newly_failed:
        failing_rows = [
            r for r in new_doc["results"] if r["url"] in newly_failed
        ]
        await _send_jsonld_regression_alert(failing_rows, new_doc)

    if prior_alerted and not new_failed:
        await _send_jsonld_recovery_alert(new_doc)


def _format_failing_row(row: dict[str, Any]) -> str:
    bits: list[str] = [row.get("url") or "?"]
    rv = row.get("ratingValue")
    rc = row.get("reviewCount")
    if rv is not None:
        bits.append(f"ratingValue={rv}")
    if rc is not None:
        bits.append(f"reviewCount={rc}")
    if row.get("reason"):
        bits.append(str(row["reason"]))
    return "  - " + " — ".join(bits)


async def _send_jsonld_regression_alert(
    failing_rows: list[dict[str, Any]], new_doc: dict[str, Any],
) -> None:
    title = (
        "Trustpilot JSON-LD regression: AggregateRating missing on "
        f"{len(failing_rows)} production URL(s)"
    )
    lines = [_format_failing_row(r) for r in failing_rows]
    msg = (
        "The Trustpilot AggregateRating JSON-LD verifier reports the "
        "following URL(s) flipped PASS→FAIL on the live production "
        "origin. SERP star rich-snippets will disappear from these "
        "pages on Google's next crawl.\n\n"
        + "\n".join(lines)
    )
    run_url = new_doc.get("runUrl")
    if run_url:
        msg += f"\n\nGitHub Actions run: {run_url}"
    await _emit_jsonld_alert(
        title=title,
        message=msg,
        kind="regression",
        run_url=run_url,
        urls=[r["url"] for r in failing_rows],
    )


async def _send_jsonld_recovery_alert(new_doc: dict[str, Any]) -> None:
    title = (
        "Trustpilot JSON-LD recovered: AggregateRating present on all URLs"
    )
    msg = (
        "All previously-failing Trustpilot AggregateRating JSON-LD URLs "
        "are passing again on the production origin. SERP stars should "
        "reappear on Google's next crawl. No further action required."
    )
    run_url = new_doc.get("runUrl")
    if run_url:
        msg += f"\n\nGitHub Actions run: {run_url}"
    await _emit_jsonld_alert(
        title=title,
        message=msg,
        kind="recovery",
        run_url=run_url,
        urls=[],
    )


async def _emit_jsonld_alert(
    title: str, message: str, kind: str,
    run_url: Optional[str], urls: list[str],
) -> None:
    """Insert the in-app notification (which the existing Slack/webhook
    fan-out subscribes to) and email every admin. Both legs are
    best-effort and isolated so a failure in one channel does not
    suppress the other."""
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        from db_ops import supa_insert_notification
        await supa_insert_notification({
            "id": str(uuid.uuid4()),
            "title": title,
            "message": message,
            "type": "error" if kind == "regression" else "info",
            "channel": "in_app",
            "audience": "admins",
            "status": "sent",
            "created_at": now_iso,
            "sent_at": now_iso,
            "meta": {
                "kind": "trustpilot_jsonld_alert",
                "state": kind,
                "urls": urls,
                "runUrl": run_url,
            },
        })
    except Exception as exc:
        logger.debug(
            "[trustpilot-jsonld-alerts] notification persist failed: %s", exc,
        )

    asyncio.create_task(_email_admins_about_jsonld(title, message, kind))


async def _email_admins_about_jsonld(
    title: str, message: str, kind: str,
) -> None:
    """Email every admin (best-effort). Mirrors the helper shape used
    by ``routes/admin_trustpilot_alerts.py`` (Task #728) so the inbox
    looks consistent across all Trustpilot alert channels."""
    try:
        from email_templates import _send  # internal helper, intentional
    except Exception as exc:
        logger.debug(
            "[trustpilot-jsonld-alerts] email helper unavailable: %s", exc,
        )
        return
    admins: list[str] = []
    try:
        if db is not None:
            cursor = db.users.find(
                {"is_admin": True}, {"_id": 0, "email": 1}
            )
            async for u in cursor:
                e = (u.get("email") or "").strip()
                if e:
                    admins.append(e)
    except Exception as exc:
        logger.debug(
            "[trustpilot-jsonld-alerts] admin lookup failed: %s", exc,
        )
    color = "#16a34a" if kind == "recovery" else "#dc2626"
    safe_msg = (message or "").replace("<", "&lt;").replace(">", "&gt;")
    html = (
        f"<h2 style='color:{color};margin:0 0 8px;'>{title}</h2>"
        f"<p style='font-size:14px;line-height:1.6;color:#374151;"
        f"white-space:pre-line;'>{safe_msg}</p>"
        f"<p style='font-size:12px;color:#6b7280;'>This is an automated "
        f"alert from the Syrabit Trustpilot JSON-LD verifier "
        f"(Task #753).</p>"
    )
    for email in admins:
        try:
            await _send(email, title, html)
        except Exception as exc:
            logger.debug(
                "[trustpilot-jsonld-alerts] email send failed for %s: %s",
                email, exc,
            )


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
