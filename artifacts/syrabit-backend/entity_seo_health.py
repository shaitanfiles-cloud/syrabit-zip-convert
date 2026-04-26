"""Task #940 — Entity SEO + Knowledge Graph health.

Tracks the live state of every off-site entity-SEO signal that drives
Knowledge Panel rank, AI Overview citation preference, and LLM-training
corpus presence:

  * Wikidata (SPARQL endpoint) — QID + claim count for the Syrabit.ai
    entity. Drift = a claim removed by another editor.
  * Wikipedia (REST API) — article presence + last-edit date for the
    Syrabit.ai page. Drift = article disappeared / blanked.
  * Crunchbase — profile completeness for the company page. Drift =
    fewer fields completed than last week.
  * `sameAs` profile verification — HEAD probe of every verified social
    profile listed on the Org JSON-LD. Drift = a profile 404s or
    redirects off-site.
  * Google Knowledge Graph API (free tier) — surface presence for
    "Syrabit" / "Syrabit.ai" queries. Drift = the panel stopped
    surfacing.

The collectors are pure async functions accepting an injectable
``http_get`` callable so the contract tests can run them without
network access. They never raise — every adapter returns a structured
``signal`` dict with ``status`` ∈ {ok, missing, error}, plus the raw
fields the admin panel renders.

The weekly background loop (``_entity_seo_loop``) mirrors the lock-doc
pattern used by ``_cf_bot_report_loop`` in ``routes/bot_discovery.py``
exactly: target Mon 04:30 UTC ±15 min, dedup via
``db.job_locks[entity_seo_health_lock]``, with a boot-time catch-up so
a service outage during the Monday window doesn't silently skip a
week.

The drift detector compares the previous and current snapshots and
fires the existing alerter (``metrics._dispatch_alert``) with a
debounce key + persisted lock-doc snapshot, matching the
``seo_health_degraded`` convention in ``_seo_health_alert_loop``.

Out of scope (see Task #940): auto-editing Wikidata or Wikipedia. Both
have strict notability + COI rules; the right artefact is a queue of
proposed edits an admin reviews and files manually. Missing claims are
surfaced as deep-link rows in the admin panel.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────────

ENTITY_SEO_COLLECTION = "entity_seo_health"

# Lock-doc constants (mirrors ``_CF_BOT_REPORT_LOCK_ID`` family).
_ENTITY_LOCK_ID = "entity_seo_health_lock"
_ENTITY_LOCK_KEY = "entity_seo_last_iso_week"

_TARGET_WEEKDAY = 0       # Monday
_TARGET_HOUR_UTC = 4      # 04:30 UTC ≈ 10:00 IST (offset from cf_bot_report at 04:00)
_TARGET_MINUTE_UTC = 30
_TOLERANCE_MINUTES = 15
_LOOP_SLEEP_S = 300       # 5-min poll
_WARMUP_S = 900           # 15-min after boot before first tick

# Drift alerter constants.
_ALERT_TYPE = "entity_seo_drift"
_ALERT_LOCK_ID = "entity_seo_drift_alert_lock"
_ALERT_DEBOUNCE_S = 86400  # 24 h between re-pages while still drifting

# Default Syrabit.ai entity identifiers. Wired at runtime via env so an
# admin can rotate them without a redeploy when the Wikidata QID is
# eventually approved or a Crunchbase URL changes shape.
SYRABIT_NAME = "Syrabit.ai"
SYRABIT_WIKIDATA_QID = os.environ.get("ENTITY_SEO_WIKIDATA_QID", "")  # e.g. "Q123456789"
SYRABIT_WIKIPEDIA_TITLE = os.environ.get(
    "ENTITY_SEO_WIKIPEDIA_TITLE", "Syrabit.ai")
SYRABIT_CRUNCHBASE_PERMALINK = os.environ.get(
    "ENTITY_SEO_CRUNCHBASE_PERMALINK", "syrabit-ai")
SYRABIT_KG_QUERY = "Syrabit.ai"
# Knowledge Panel monitoring tracks BOTH the brand short-name and the
# full domain so we catch the (common) case where Google indexes one
# but not the other. The aggregate google_kg signal is "ok" iff every
# tracked query returns a panel entry.
SYRABIT_KG_QUERIES: Tuple[str, ...] = ("Syrabit", "Syrabit.ai")

# Pages/sites where we *expect* a Syrabit.ai mention to surface but
# don't yet. Each target gets a weekly probe — if the body doesn't
# contain ``expected_term`` (case-insensitive) it's surfaced in the
# admin panel as a "missing mention opportunity" with a deep-link to
# the page so an admin can pitch the editor / file the suggestion.
# Keep this list under code review (not env) so changes are auditable.
MENTION_OPPORTUNITY_TARGETS: Tuple[Dict[str, str], ...] = (
    {"id": "wikipedia_education_in_assam",
     "label": "Wikipedia — Education in Assam",
     "url": "https://en.wikipedia.org/wiki/Education_in_Assam",
     "expected_term": "Syrabit"},
    {"id": "wikipedia_education_in_guwahati",
     "label": "Wikipedia — Education in Guwahati",
     "url": "https://en.wikipedia.org/wiki/Guwahati",
     "expected_term": "Syrabit"},
    {"id": "wikipedia_indian_edtech",
     "label": "Wikipedia — Education technology in India",
     "url": "https://en.wikipedia.org/wiki/Education_in_India",
     "expected_term": "Syrabit"},
)

# Verified founder + organization sameAs profiles. The admin panel
# probes each entry and surfaces a regression when one starts 404'ing.
# Ship as a stable list rather than env so it stays under code review.
VERIFIED_ORG_SAMEAS: Tuple[str, ...] = (
    "https://www.linkedin.com/company/syrabit-ai/",
    "https://twitter.com/SyrabitAI",
    "https://github.com/syrabit",
    "https://www.youtube.com/@syrabit",
)
VERIFIED_FOUNDER_SAMEAS: Tuple[str, ...] = (
    "https://www.linkedin.com/in/dipakrai/",
    "https://github.com/dipakrai",
    "https://twitter.com/dipakraix",
)
FOUNDER_NAME = "Dipak Rai"

# Wikidata claims we *want* the Syrabit.ai entity to have. Each entry
# pairs a property id (P31, P17, …) with a human label and the
# canonical Wikidata edit URL the admin panel deep-links to. When a
# claim is missing from the live entity (or Wikidata returns 404 for
# the QID itself) the panel surfaces a "file this claim" row.
DESIRED_WIKIDATA_CLAIMS: Tuple[Dict[str, str], ...] = (
    {"prop": "P31",  "label": "instance of (educational technology company)", "expected": "Q1077366"},
    {"prop": "P17",  "label": "country (India)",                              "expected": "Q668"},
    {"prop": "P131", "label": "located in (Guwahati / Assam)",                "expected": "Q207749"},
    {"prop": "P856", "label": "official website",                             "expected": "https://syrabit.ai"},
    {"prop": "P112", "label": "founder (Dipak Rai)",                          "expected": ""},
    {"prop": "P571", "label": "inception year",                               "expected": "2024"},
    {"prop": "P1448", "label": "official name",                                "expected": "Syrabit.ai"},
)


def wikidata_edit_url(qid: str, prop: str) -> str:
    """Return the deep link an admin clicks to file a single claim."""
    if qid:
        return f"https://www.wikidata.org/wiki/{qid}#{prop}"
    return f"https://www.wikidata.org/wiki/Special:NewItem?P=&label={SYRABIT_NAME}"


# ── HTTP transport (injectable for tests) ───────────────────────────────────

HttpGet = Callable[..., Awaitable[Dict[str, Any]]]


async def _default_http_get(
    url: str,
    *,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Default transport — uses httpx if available, otherwise returns a
    structured error so the caller's status path is exercised in dev
    without httpx.

    The transport always returns ``{"status_code": int, "json": Any|None,
    "text": str|None, "error": str|None, "final_url": str|None}``. It
    never raises. ``final_url`` is the post-redirect URL so the sameAs
    verifier can detect off-site redirects (e.g. a LinkedIn page that
    quietly 301s to ``/in/page-not-found``).
    """
    try:
        import httpx  # type: ignore
    except Exception as exc:  # pragma: no cover — httpx ships with FastAPI
        return {"status_code": 0, "json": None, "text": None, "error": f"httpx unavailable: {exc}",
                "final_url": None}

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.request(
                method, url, params=params, headers=headers or {})
            payload: Dict[str, Any] = {
                "status_code": resp.status_code,
                "json": None,
                "text": None,
                "error": None,
                "final_url": str(resp.url) if resp.url else None,
            }
            ctype = (resp.headers.get("content-type") or "").lower()
            if "json" in ctype:
                try:
                    payload["json"] = resp.json()
                except Exception:
                    payload["text"] = resp.text
            else:
                # Keep the body small — every adapter only needs a peek.
                payload["text"] = resp.text[:4096] if resp.text else None
            return payload
    except Exception as exc:
        return {"status_code": 0, "json": None, "text": None, "error": str(exc),
                "final_url": None}


# ── Collectors ──────────────────────────────────────────────────────────────


def _signal(
    *,
    name: str,
    status: str,
    summary: str = "",
    fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalised signal envelope. ``status`` ∈ {ok, missing, error}."""
    if status not in {"ok", "missing", "error"}:
        raise ValueError(f"invalid signal status: {status}")
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "fields": dict(fields or {}),
    }


async def fetch_wikidata(
    *,
    qid: str = SYRABIT_WIKIDATA_QID,
    http_get: HttpGet = _default_http_get,
) -> Dict[str, Any]:
    """Look up Syrabit.ai's Wikidata entity and count present claims.

    Returns a signal whose ``fields`` includes ``qid``, ``claim_count``,
    ``present_claims`` (set of P-ids actually filed) and
    ``missing_claims`` (list from ``DESIRED_WIKIDATA_CLAIMS`` that
    aren't yet present, with deep-links).
    """
    if not qid:
        return _signal(
            name="wikidata",
            status="missing",
            summary="No Wikidata QID configured for Syrabit.ai yet — file the entity manually.",
            fields={
                "qid": "",
                "claim_count": 0,
                "present_claims": [],
                "missing_claims": [
                    {**c, "edit_url": wikidata_edit_url("", c["prop"])}
                    for c in DESIRED_WIKIDATA_CLAIMS
                ],
            },
        )

    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    resp = await http_get(url, headers={"User-Agent": "Syrabit.ai/EntitySEOMonitor (+https://syrabit.ai)"})
    if resp.get("error"):
        return _signal(
            name="wikidata", status="error",
            summary=f"Wikidata fetch failed: {resp['error']}",
            fields={"qid": qid},
        )
    if resp.get("status_code") == 404:
        return _signal(
            name="wikidata", status="missing",
            summary=f"Wikidata entity {qid} not found (deleted?).",
            fields={"qid": qid, "claim_count": 0, "present_claims": [],
                    "missing_claims": [
                        {**c, "edit_url": wikidata_edit_url(qid, c["prop"])}
                        for c in DESIRED_WIKIDATA_CLAIMS]},
        )
    if resp.get("status_code", 0) >= 400 or not resp.get("json"):
        return _signal(
            name="wikidata", status="error",
            summary=f"Wikidata returned HTTP {resp.get('status_code')}.",
            fields={"qid": qid},
        )
    entities = (resp["json"] or {}).get("entities") or {}
    ent = entities.get(qid) or {}
    claims = ent.get("claims") or {}
    present_claims = sorted(claims.keys())
    missing = []
    for desired in DESIRED_WIKIDATA_CLAIMS:
        if desired["prop"] not in claims:
            missing.append({**desired, "edit_url": wikidata_edit_url(qid, desired["prop"])})
    label = ((ent.get("labels") or {}).get("en") or {}).get("value") or SYRABIT_NAME
    return _signal(
        name="wikidata",
        status="ok",
        summary=f"{label} ({qid}) — {len(present_claims)} claims, {len(missing)} desired claims missing.",
        fields={
            "qid": qid,
            "label": label,
            "claim_count": len(present_claims),
            "present_claims": present_claims,
            "missing_claims": missing,
            "edit_url": f"https://www.wikidata.org/wiki/{qid}",
        },
    )


async def fetch_wikipedia(
    *,
    title: str = SYRABIT_WIKIPEDIA_TITLE,
    http_get: HttpGet = _default_http_get,
) -> Dict[str, Any]:
    """Check the Syrabit.ai Wikipedia article presence + last-edit date."""
    safe_title = (title or "").strip().replace(" ", "_")
    if not safe_title:
        return _signal(
            name="wikipedia", status="missing",
            summary="No Wikipedia title configured.",
            fields={"title": title})
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_title}"
    resp = await http_get(url, headers={"User-Agent": "Syrabit.ai/EntitySEOMonitor"})
    if resp.get("error"):
        return _signal(
            name="wikipedia", status="error",
            summary=f"Wikipedia fetch failed: {resp['error']}",
            fields={"title": title})
    sc = resp.get("status_code", 0)
    if sc == 404:
        return _signal(
            name="wikipedia", status="missing",
            summary=f"No Wikipedia article exists for {title} yet.",
            fields={"title": title,
                    "draft_url": f"https://en.wikipedia.org/wiki/Draft:{safe_title}"})
    if sc >= 400 or not resp.get("json"):
        return _signal(
            name="wikipedia", status="error",
            summary=f"Wikipedia returned HTTP {sc}.",
            fields={"title": title})
    payload = resp["json"]
    page_url = (payload.get("content_urls") or {}).get("desktop", {}).get("page") \
        or f"https://en.wikipedia.org/wiki/{safe_title}"
    return _signal(
        name="wikipedia", status="ok",
        summary=f"Article live: {payload.get('title') or title}",
        fields={
            "title": payload.get("title") or title,
            "extract": (payload.get("extract") or "")[:280],
            "last_edited_at": payload.get("timestamp"),
            "page_url": page_url,
            "page_id": payload.get("pageid"),
        },
    )


async def fetch_crunchbase(
    *,
    permalink: str = SYRABIT_CRUNCHBASE_PERMALINK,
    http_get: HttpGet = _default_http_get,
) -> Dict[str, Any]:
    """Probe the Crunchbase organization page (no API key needed for the
    public meta-fetch). We can't pull structured fields from the free
    tier, but we *can* assert the page is reachable and infer
    completeness from a small allow-list of strings present in the
    rendered HTML (description, founders, location, website).
    """
    if not permalink:
        return _signal(
            name="crunchbase", status="missing",
            summary="No Crunchbase permalink configured.",
            fields={"permalink": permalink})
    url = f"https://www.crunchbase.com/organization/{permalink}"
    resp = await http_get(url, headers={"User-Agent": "Syrabit.ai/EntitySEOMonitor"})
    if resp.get("error"):
        return _signal(
            name="crunchbase", status="error",
            summary=f"Crunchbase fetch failed: {resp['error']}",
            fields={"permalink": permalink, "page_url": url})
    sc = resp.get("status_code", 0)
    if sc == 404:
        return _signal(
            name="crunchbase", status="missing",
            summary="No Crunchbase profile exists for Syrabit.ai yet.",
            fields={"permalink": permalink,
                    "submit_url": "https://www.crunchbase.com/add-new"})
    if sc >= 400:
        return _signal(
            name="crunchbase", status="error",
            summary=f"Crunchbase returned HTTP {sc}.",
            fields={"permalink": permalink, "page_url": url})
    body = (resp.get("text") or "").lower()
    fields_present = {
        "description": "company description" in body or '"description"' in body,
        "founders":    "founder" in body and FOUNDER_NAME.lower() in body,
        "location":    "guwahati" in body or "assam" in body,
        "website":     "syrabit.ai" in body,
    }
    completeness = round(100.0 * sum(fields_present.values()) / max(1, len(fields_present)), 1)
    return _signal(
        name="crunchbase", status="ok",
        summary=f"Crunchbase profile reachable ({completeness}% of tracked fields detected).",
        fields={
            "permalink": permalink,
            "page_url": url,
            "completeness_pct": completeness,
            "fields_present": fields_present,
        },
    )


def _hostname(url: str) -> str:
    """Best-effort hostname extraction (no scheme, no path, lowercased)."""
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _registrable_host(host: str) -> str:
    """Strip a leading ``www.`` so ``www.linkedin.com`` and
    ``linkedin.com`` compare equal — we only care about the brand
    registrable host, not the subdomain."""
    h = (host or "").lower()
    if h.startswith("www."):
        return h[4:]
    return h


async def verify_sameas_profile(
    url: str,
    *,
    http_get: HttpGet = _default_http_get,
) -> Dict[str, Any]:
    """HEAD-probe a single sameAs URL.

    Live (``ok``) requires:
      * a 2xx response (after following redirects), AND
      * a final URL whose registrable host matches the original — so a
        sneaky 301 from ``linkedin.com/company/syrabit`` to
        ``linkedin.com/in/page-not-found`` (still 200) is still ``ok``,
        but a 301 to ``redirect.example.com/captcha`` is flagged as
        an off-site redirect (``status="missing"``).

    A 4xx response or an off-site redirect both surface as ``missing``
    so the admin panel renders one actionable row.
    """
    if not url:
        return {"url": url, "status": "missing", "http_status": 0,
                "summary": "empty URL"}
    resp = await http_get(url, method="HEAD", timeout=8.0,
                          headers={"User-Agent": "Syrabit.ai/EntitySEOMonitor"})
    if resp.get("error"):
        return {"url": url, "status": "error", "http_status": 0,
                "summary": f"fetch error: {resp['error']}", "final_url": None}
    sc = int(resp.get("status_code") or 0)
    final_url = resp.get("final_url") or url
    expected_host = _registrable_host(_hostname(url))
    actual_host = _registrable_host(_hostname(final_url))
    if 200 <= sc < 400:
        if expected_host and actual_host and expected_host != actual_host:
            return {"url": url, "status": "missing", "http_status": sc,
                    "final_url": final_url,
                    "summary": (f"redirected off-site to {actual_host} "
                                f"— profile likely deleted or relocated")}
        return {"url": url, "status": "ok", "http_status": sc,
                "final_url": final_url, "summary": "live"}
    if 400 <= sc < 500:
        return {"url": url, "status": "missing", "http_status": sc,
                "final_url": final_url,
                "summary": f"profile returned {sc} — broken or removed"}
    return {"url": url, "status": "error", "http_status": sc,
            "final_url": final_url,
            "summary": f"transport HTTP {sc}"}


async def fetch_sameas(
    *,
    org_urls: Tuple[str, ...] = VERIFIED_ORG_SAMEAS,
    founder_urls: Tuple[str, ...] = VERIFIED_FOUNDER_SAMEAS,
    http_get: HttpGet = _default_http_get,
) -> Dict[str, Any]:
    """Aggregate signal for the full sameAs profile list."""
    org = await asyncio.gather(*[
        verify_sameas_profile(u, http_get=http_get) for u in org_urls
    ])
    founder = await asyncio.gather(*[
        verify_sameas_profile(u, http_get=http_get) for u in founder_urls
    ])
    all_results = list(org) + list(founder)
    broken = [r for r in all_results if r["status"] != "ok"]
    status = "ok" if not broken else ("missing" if all(r["status"] == "missing" for r in broken) else "error")
    return _signal(
        name="sameas",
        status=status,
        summary=(f"All {len(all_results)} verified profiles live."
                 if not broken
                 else f"{len(broken)} of {len(all_results)} profiles broken."),
        fields={
            "org_profiles": list(org),
            "founder_profiles": list(founder),
            "broken": broken,
            "total": len(all_results),
        },
    )


async def fetch_google_kg(
    *,
    query: str = SYRABIT_KG_QUERY,
    queries: Optional[Tuple[str, ...]] = None,
    http_get: HttpGet = _default_http_get,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Probe the Google Knowledge Graph Search API for the panel entry.

    When ``queries`` is supplied (e.g. ``("Syrabit", "Syrabit.ai")``)
    each query is probed and the per-query results are surfaced in
    ``fields.queries`` as a list of ``{query, status, kg_id, name,
    score, summary}`` dicts. The aggregate ``status`` is ``ok`` iff
    every query returned a panel; ``missing`` if at least one returned
    no panel; ``error`` if all failed in transport.

    Single-query behaviour (legacy ``query=`` parameter) is preserved
    for backwards compatibility with the existing collector tests.

    Free tier: requires ``GOOGLE_KG_API_KEY``. Returns ``status=missing``
    when the panel has no entry, ``status=error`` for transport faults,
    and ``status=ok`` with the matched entity's ``@id`` + ``description``
    when a panel result exists.
    """
    # Multi-query mode — probe each, then collapse.
    if queries:
        per_query = await asyncio.gather(*[
            fetch_google_kg(query=q, http_get=http_get, api_key=api_key)
            for q in queries
        ])
        rows = []
        for q, sig in zip(queries, per_query):
            f = sig.get("fields") or {}
            rows.append({
                "query":   q,
                "status":  sig.get("status"),
                "summary": sig.get("summary"),
                "kg_id":   f.get("kg_id"),
                "name":    f.get("name"),
                "score":   f.get("result_score"),
            })
        statuses = [r["status"] for r in rows]
        if all(s == "ok" for s in statuses):
            agg, summary = "ok", (
                f"Knowledge Panel present for all {len(rows)} tracked queries.")
        elif all(s == "error" for s in statuses):
            agg, summary = "error", "Knowledge Graph probe failed for all queries."
        else:
            missing_qs = [r["query"] for r in rows if r["status"] != "ok"]
            agg, summary = "missing", (
                f"No Knowledge Panel for: {', '.join(missing_qs)}.")
        return _signal(
            name="google_kg", status=agg, summary=summary,
            fields={
                "queries": rows,
                "configured": all((sig.get("fields") or {}).get("configured", False)
                                  for sig in per_query),
                # Keep the first-query convenience fields for any legacy
                # consumer that only reads the headline.
                "query":   rows[0]["query"] if rows else "",
                "kg_id":   rows[0]["kg_id"] if rows else None,
                "name":    rows[0]["name"]  if rows else None,
                "result_score": rows[0]["score"] if rows else None,
            },
        )
    api_key = (api_key or os.environ.get("GOOGLE_KG_API_KEY") or "").strip()
    if not api_key:
        return _signal(
            name="google_kg", status="error",
            summary="GOOGLE_KG_API_KEY not configured — Knowledge Panel monitoring disabled.",
            fields={"query": query, "configured": False})
    url = "https://kgsearch.googleapis.com/v1/entities:search"
    resp = await http_get(url, params={
        "query": query, "limit": 1, "indent": "true", "key": api_key,
    })
    if resp.get("error"):
        return _signal(
            name="google_kg", status="error",
            summary=f"KG fetch failed: {resp['error']}",
            fields={"query": query, "configured": True})
    if resp.get("status_code", 0) >= 400 or not resp.get("json"):
        return _signal(
            name="google_kg", status="error",
            summary=f"KG returned HTTP {resp.get('status_code')}.",
            fields={"query": query, "configured": True})
    items = (resp["json"] or {}).get("itemListElement") or []
    if not items:
        return _signal(
            name="google_kg", status="missing",
            summary=f'No Knowledge Panel entry surfaced for "{query}".',
            fields={"query": query, "configured": True})
    first = items[0].get("result") or {}
    score = items[0].get("resultScore")
    return _signal(
        name="google_kg", status="ok",
        summary=f'Panel entry: "{first.get("name") or query}" (score {score}).',
        fields={
            "query": query, "configured": True,
            "kg_id": first.get("@id"),
            "name": first.get("name"),
            "description": first.get("description"),
            "result_score": score,
            "url": (first.get("url") or ""),
        },
    )


# ── Mention-opportunity collector ───────────────────────────────────────────


async def fetch_mention_opportunities(
    *,
    targets: Tuple[Dict[str, str], ...] = MENTION_OPPORTUNITY_TARGETS,
    http_get: HttpGet = _default_http_get,
) -> Dict[str, Any]:
    """For each tracked target page, fetch the body and check whether
    ``expected_term`` appears (case-insensitive). Pages without the
    mention surface as actionable rows in the admin panel — these are
    *opportunities* (someone should pitch the editor / file the
    suggestion), not regressions.

    Status semantics:
      * ``ok``      — every target already mentions us.
      * ``missing`` — at least one target is missing the mention.
      * ``error``   — every target probe failed in transport.
    """
    async def _probe(t: Dict[str, str]) -> Dict[str, Any]:
        url = t["url"]
        resp = await http_get(url, method="GET", timeout=10.0,
                              headers={"User-Agent": "Syrabit.ai/EntitySEOMonitor"})
        if resp.get("error"):
            return {**t, "status": "error", "mentioned": False,
                    "summary": f"fetch error: {resp['error']}"}
        sc = int(resp.get("status_code") or 0)
        body = (resp.get("text") or "")
        if not (200 <= sc < 400):
            return {**t, "status": "error", "mentioned": False,
                    "summary": f"target HTTP {sc}"}
        term = (t.get("expected_term") or "").lower()
        mentioned = bool(term and term in body.lower())
        return {**t, "status": "ok" if mentioned else "missing",
                "mentioned": mentioned,
                "summary": "Mention present." if mentioned
                           else f'No mention of "{t.get("expected_term")}" found.'}

    rows = await asyncio.gather(*[_probe(t) for t in targets])
    statuses = [r["status"] for r in rows]
    missing = [r for r in rows if r["status"] == "missing"]
    if not rows:
        agg, summary = "ok", "No mention targets configured."
    elif all(s == "ok" for s in statuses):
        agg, summary = "ok", f"All {len(rows)} mention targets cover us."
    elif all(s == "error" for s in statuses):
        agg, summary = "error", "All mention-target probes failed."
    else:
        agg, summary = "missing", (
            f"{len(missing)} of {len(rows)} mention opportunities still open.")
    return _signal(
        name="mentions", status=agg, summary=summary,
        fields={
            "targets": list(rows),
            "missing": list(missing),
            "total":   len(rows),
        },
    )


# ── Aggregation + diff ──────────────────────────────────────────────────────


async def aggregate_snapshot(
    *,
    http_get: HttpGet = _default_http_get,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Fan-out every collector and return one snapshot doc.

    The Knowledge Panel signal probes BOTH the brand short-name
    (``"Syrabit"``) and the full domain (``"Syrabit.ai"``) — see
    ``SYRABIT_KG_QUERIES`` — so the admin panel can see when one is
    indexed and the other isn't.
    """
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    wikidata, wikipedia, crunchbase, sameas, kg, mentions = await asyncio.gather(
        fetch_wikidata(http_get=http_get),
        fetch_wikipedia(http_get=http_get),
        fetch_crunchbase(http_get=http_get),
        fetch_sameas(http_get=http_get),
        fetch_google_kg(http_get=http_get, queries=SYRABIT_KG_QUERIES),
        fetch_mention_opportunities(http_get=http_get),
    )
    signals = {
        "wikidata":   wikidata,
        "wikipedia":  wikipedia,
        "crunchbase": crunchbase,
        "sameas":     sameas,
        "google_kg":  kg,
        "mentions":   mentions,
    }
    # Aggregate health: ok iff every signal is ok; missing if any
    # tracked signal is missing (no errors); else degraded.
    statuses = [s["status"] for s in signals.values()]
    if all(s == "ok" for s in statuses):
        agg = "ok"
    elif any(s == "error" for s in statuses):
        agg = "degraded"
    else:
        agg = "missing"
    missing_claims: List[Dict[str, Any]] = []
    if wikidata["status"] in {"ok", "missing"}:
        missing_claims = list(wikidata["fields"].get("missing_claims") or [])
    missing_mentions = list((mentions.get("fields") or {}).get("missing") or [])
    kg_queries = list((kg.get("fields") or {}).get("queries") or [])
    kg_present_count = sum(1 for q in kg_queries if q.get("status") == "ok")
    return {
        "generated_at": now_utc,
        "iso_week": _iso_week_tag(now_utc),
        "aggregate_status": agg,
        "signals": signals,
        "missing_claims": missing_claims,
        "missing_mentions": missing_mentions,
        "summary": {
            "wikidata_claims":      int(wikidata["fields"].get("claim_count", 0)),
            "wikidata_missing":     len(missing_claims),
            "sameas_total":         int(sameas["fields"].get("total", 0)),
            "sameas_broken":        len(sameas["fields"].get("broken") or []),
            "wikipedia_present":    wikipedia["status"] == "ok",
            "crunchbase_present":   crunchbase["status"] == "ok",
            "google_kg_present":    kg["status"] == "ok",
            "google_kg_queries_total":   len(kg_queries),
            "google_kg_queries_present": kg_present_count,
            "mentions_total":       int((mentions.get("fields") or {}).get("total", 0)),
            "mentions_missing":     len(missing_mentions),
        },
    }


def _iso_week_tag(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def compute_drift(prev: Optional[Dict[str, Any]],
                  cur: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two snapshots and return drift events.

    Returns a dict with ``regressions`` (signals that got worse) and
    ``improvements`` (signals that recovered) so the alerter only
    pages on real regressions and the admin panel can also celebrate
    a recovery.

    ``had_baseline`` distinguishes "first run" from "no drift".
    """
    out: Dict[str, Any] = {
        "had_baseline": bool(prev),
        "regressions": [],
        "improvements": [],
        "summary_deltas": {},
    }
    cur_signals = (cur or {}).get("signals") or {}
    prev_signals = (prev or {}).get("signals") or {}

    rank = {"ok": 2, "missing": 1, "error": 0}

    for name, sig in cur_signals.items():
        cur_status = sig.get("status", "error")
        prev_sig = prev_signals.get(name) or {}
        prev_status = prev_sig.get("status")
        if prev_status is None:
            # New signal we weren't tracking — only flag if currently bad
            # so a brand-new collector doesn't auto-page.
            continue
        if rank.get(cur_status, 0) < rank.get(prev_status, 0):
            out["regressions"].append({
                "name": name,
                "from": prev_status,
                "to": cur_status,
                "summary": sig.get("summary", ""),
            })
        elif rank.get(cur_status, 0) > rank.get(prev_status, 0):
            out["improvements"].append({
                "name": name,
                "from": prev_status,
                "to": cur_status,
                "summary": sig.get("summary", ""),
            })

    # Per-summary numeric deltas so the admin panel can show
    # "Wikidata claims: 7 → 6 (▼ 1)" style WoW lines.
    cur_sum = (cur or {}).get("summary") or {}
    prev_sum = (prev or {}).get("summary") or {}
    for k in ("wikidata_claims", "wikidata_missing", "sameas_broken"):
        c = int(cur_sum.get(k, 0))
        p = int(prev_sum.get(k, 0))
        out["summary_deltas"][k] = {"current": c, "previous": p, "delta": c - p}

    # Wikidata claim-level drift: list claims that were present last
    # week but vanished this week. Important — another editor may have
    # *removed* a claim and the headline status would still say "ok".
    #
    # Only compare when *both* snapshots actually queried the entity
    # successfully. If the current Wikidata fetch errored (transport
    # failure) or returned ``missing`` (entity deleted / 404), the empty
    # ``present_claims`` list is an artefact of the outage — not a real
    # claim removal — and emitting a per-prop regression here would
    # confuse the on-call (the headline ``wikidata`` regression is
    # already raised above with a clearer message).
    cur_wd = cur_signals.get("wikidata") or {}
    prev_wd = prev_signals.get("wikidata") or {}
    if cur_wd.get("status") == "ok" and prev_wd.get("status") == "ok":
        cur_present = set((cur_wd.get("fields") or {}).get("present_claims") or [])
        prev_present = set((prev_wd.get("fields") or {}).get("present_claims") or [])
        removed = sorted(prev_present - cur_present)
        if removed:
            out["regressions"].append({
                "name": "wikidata_claims_removed",
                "from": "ok", "to": "missing",
                "summary": f"Wikidata claims removed since last week: {', '.join(removed)}",
                "removed_props": removed,
            })

    return out


# ── Lock-doc + scheduling (mirrors _cf_bot_report_loop) ─────────────────────


def _should_run_entity_seo_now(now_utc: datetime, last_iso_week: str) -> bool:
    """Pure gate — Mon 04:30 UTC ±15 min, dedup by ISO week."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if now_utc.weekday() != _TARGET_WEEKDAY:
        return False
    target = now_utc.replace(
        hour=_TARGET_HOUR_UTC, minute=_TARGET_MINUTE_UTC,
        second=0, microsecond=0)
    delta_minutes = abs((now_utc - target).total_seconds()) / 60.0
    if delta_minutes > _TOLERANCE_MINUTES:
        return False
    return _iso_week_tag(now_utc) != (last_iso_week or "")


async def _claim_entity_seo_slot(db, cur_iso_week: str) -> bool:
    """Atomic CAS on ``db.job_locks[entity_seo_health_lock]``."""
    from pymongo.errors import DuplicateKeyError
    try:
        res = await db.job_locks.find_one_and_update(
            {"_id": _ENTITY_LOCK_ID,
             _ENTITY_LOCK_KEY: {"$ne": cur_iso_week}},
            {"$set": {_ENTITY_LOCK_KEY: cur_iso_week}},
            upsert=False,
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug("[entity SEO] CAS update failed: %s", exc)
        return False
    try:
        await db.job_locks.insert_one({
            "_id": _ENTITY_LOCK_ID,
            _ENTITY_LOCK_KEY: cur_iso_week,
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug("[entity SEO] bootstrap insert failed: %s", exc)
        return False


async def _load_prior_entity_seo(db) -> Optional[Dict[str, Any]]:
    """Fetch the most recent snapshot so the next run can diff against it."""
    try:
        doc = await db[ENTITY_SEO_COLLECTION].find_one(
            {}, sort=[("generated_at", -1)],
        )
    except Exception as exc:
        logger.debug("[entity SEO] prior load failed: %s", exc)
        return None
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


async def _maybe_dispatch_drift_alert(db, snapshot: Dict[str, Any],
                                       drift: Dict[str, Any]) -> bool:
    """Fire the drift alert if there are regressions and we're outside
    the per-key debounce window. Returns True iff an alert was sent.

    State persists in ``db.job_locks[_ALERT_LOCK_ID]`` keyed by the
    sorted regression-name fingerprint so a re-page only happens when
    the *set of broken signals* changes (or after the debounce expires
    on the same set).
    """
    regressions = list(drift.get("regressions") or [])
    if not regressions:
        # Recovery — clear any prior fingerprint so the next regression
        # is treated as a fresh page.
        try:
            await db.job_locks.delete_one({"_id": _ALERT_LOCK_ID})
        except Exception:
            pass
        return False

    fingerprint = ",".join(sorted({r.get("name", "") for r in regressions}))
    now_ts = time.time()
    try:
        existing = await db.job_locks.find_one(
            {"_id": _ALERT_LOCK_ID}) or {}
    except Exception:
        existing = {}
    last_fp = existing.get("fingerprint") or ""
    last_ts = float(existing.get("last_paged_at_epoch") or 0.0)
    if last_fp == fingerprint and (now_ts - last_ts) < _ALERT_DEBOUNCE_S:
        # Same broken set, still inside debounce — skip.
        return False

    try:
        from metrics import _dispatch_alert, _alert_last_fired
        # Bypass the global per-type cooldown only when the fingerprint
        # changes — otherwise honour the in-process cooldown so a
        # corrupted lock-doc cannot spam.
        if last_fp != fingerprint:
            _alert_last_fired.pop(_ALERT_TYPE, None)

        body_lines = [
            f"Entity SEO health drifted on Syrabit.ai — {len(regressions)} signal(s) regressed:",
            "",
        ]
        for r in regressions:
            body_lines.append(
                f"  • {r['name']}: {r.get('from')} → {r.get('to')} — {r.get('summary')}"
            )
        body_lines += [
            "",
            f"Aggregate status: {snapshot.get('aggregate_status')}",
            f"Wikidata claims: {snapshot.get('summary', {}).get('wikidata_claims')}",
            f"Open the Entity SEO panel in the admin dashboard to triage.",
        ]
        await _dispatch_alert(
            _ALERT_TYPE,
            f"Entity SEO drift: {len(regressions)} regression(s)",
            "\n".join(body_lines),
            threshold_snapshot={
                "metric": "entity_seo_regressions",
                "value": 0,
                "actual": len(regressions),
                "fingerprint": fingerprint,
            },
        )
    except Exception as exc:
        logger.debug("[entity SEO] alert dispatch failed: %s", exc)
        return False

    try:
        await db.job_locks.update_one(
            {"_id": _ALERT_LOCK_ID},
            {"$set": {
                "fingerprint": fingerprint,
                "last_paged_at_epoch": now_ts,
                "last_paged_at": datetime.now(timezone.utc),
                "regression_count": len(regressions),
            }},
            upsert=True,
        )
    except Exception:
        pass
    return True


async def _try_run_entity_seo_once(db, now_utc: datetime,
                                    *, http_get: HttpGet = _default_http_get,
                                    force: bool = False) -> Dict[str, Any]:
    """One iteration of the weekly loop.

    Returns a small status dict so tests can assert without poking
    Mongo state directly. Pass ``force=True`` to bypass the gate
    (used by the admin "refresh now" route).
    """
    cur_iso_week = _iso_week_tag(now_utc)
    if not force:
        try:
            cfg = await db.job_locks.find_one(
                {"_id": _ENTITY_LOCK_ID},
                {"_id": 0, _ENTITY_LOCK_KEY: 1},
            ) or {}
        except Exception:
            cfg = {}
        last_run = cfg.get(_ENTITY_LOCK_KEY, "")
        if not _should_run_entity_seo_now(now_utc, last_run):
            return {"claimed": False, "stored": False, "reason": "outside_window_or_dedup"}
        if not await _claim_entity_seo_slot(db, cur_iso_week):
            return {"claimed": False, "stored": False, "reason": "lost_race"}

    prev = await _load_prior_entity_seo(db)
    try:
        snapshot = await aggregate_snapshot(http_get=http_get, now=now_utc)
    except Exception as exc:
        logger.warning("[entity SEO] aggregate crashed: %s", exc)
        snapshot = None

    if not snapshot:
        if not force:
            try:
                await db.job_locks.update_one(
                    {"_id": _ENTITY_LOCK_ID,
                     _ENTITY_LOCK_KEY: cur_iso_week},
                    {"$set": {_ENTITY_LOCK_KEY: ""}},
                )
            except Exception:
                pass
        return {"claimed": True, "stored": False, "reason": "aggregate_failed"}

    drift = compute_drift(prev, snapshot)
    snapshot["drift"] = drift
    try:
        await db[ENTITY_SEO_COLLECTION].update_one(
            {"iso_week": cur_iso_week},
            {"$set": snapshot},
            upsert=True,
        )
    except Exception as exc:
        logger.warning("[entity SEO] store failed: %s", exc)
        if not force:
            try:
                await db.job_locks.update_one(
                    {"_id": _ENTITY_LOCK_ID,
                     _ENTITY_LOCK_KEY: cur_iso_week},
                    {"$set": {_ENTITY_LOCK_KEY: ""}},
                )
            except Exception:
                pass
        return {"claimed": True, "stored": False,
                "reason": f"store_error:{type(exc).__name__}"}

    paged = await _maybe_dispatch_drift_alert(db, snapshot, drift)
    logger.info(
        "[entity SEO] stored snapshot for %s (status=%s, regressions=%d, paged=%s)",
        cur_iso_week, snapshot["aggregate_status"],
        len(drift.get("regressions") or []), paged,
    )
    return {
        "claimed": True, "stored": True, "iso_week": cur_iso_week,
        "aggregate_status": snapshot["aggregate_status"],
        "regression_count": len(drift.get("regressions") or []),
        "paged": paged,
    }


def _window_has_passed_this_week(now_utc: datetime) -> bool:
    """True iff the Mon 04:30 UTC ±tolerance window for *this ISO week*
    has already finished (i.e. we are past Mon 04:45 UTC).

    Without this gate, a Monday 03:00 UTC restart would happily run the
    catch-up — and the lock-doc would then dedup the real 04:30
    scheduled run away, drifting us off the contracted cron.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    monday = now_utc - timedelta(days=now_utc.weekday())
    window_end = monday.replace(
        hour=_TARGET_HOUR_UTC, minute=_TARGET_MINUTE_UTC,
        second=0, microsecond=0,
    ) + timedelta(minutes=_TOLERANCE_MINUTES)
    return now_utc >= window_end


async def _entity_seo_catchup_if_missed(db, now_utc: datetime) -> Dict[str, Any]:
    """One-shot recovery: if we missed the Mon 04:30 window for the
    current ISO week (e.g. service was down then), run once on boot.

    Gated on the window having already *finished* this week — running
    early (e.g. Sunday or Mon 03:00 UTC) would create the snapshot
    before the contracted time and the periodic loop would then dedup
    the real 04:30 run via the same iso_week lock.
    """
    cur_iso_week = _iso_week_tag(now_utc)
    if not _window_has_passed_this_week(now_utc):
        return {"ran": False, "reason": "window_not_yet_passed"}
    try:
        existing = await db[ENTITY_SEO_COLLECTION].find_one(
            {"iso_week": cur_iso_week}, {"_id": 1})
    except Exception as exc:
        logger.debug("[entity SEO] catch-up lookup failed: %s", exc)
        return {"ran": False, "reason": "lookup_failed"}
    if existing:
        return {"ran": False, "reason": "already_have_week"}
    if not await _claim_entity_seo_slot(db, cur_iso_week):
        return {"ran": False, "reason": "lost_race"}

    prev = await _load_prior_entity_seo(db)
    try:
        snapshot = await aggregate_snapshot(now=now_utc)
    except Exception as exc:
        logger.warning("[entity SEO] catch-up aggregate crashed: %s", exc)
        snapshot = None
    if not snapshot:
        try:
            await db.job_locks.update_one(
                {"_id": _ENTITY_LOCK_ID,
                 _ENTITY_LOCK_KEY: cur_iso_week},
                {"$set": {_ENTITY_LOCK_KEY: ""}},
            )
        except Exception:
            pass
        return {"ran": False, "reason": "aggregate_failed"}

    drift = compute_drift(prev, snapshot)
    snapshot["drift"] = drift
    snapshot["catch_up"] = True
    try:
        await db[ENTITY_SEO_COLLECTION].update_one(
            {"iso_week": cur_iso_week}, {"$set": snapshot}, upsert=True)
    except Exception as exc:
        logger.warning("[entity SEO] catch-up store failed: %s", exc)
        try:
            await db.job_locks.update_one(
                {"_id": _ENTITY_LOCK_ID,
                 _ENTITY_LOCK_KEY: cur_iso_week},
                {"$set": {_ENTITY_LOCK_KEY: ""}},
            )
        except Exception:
            pass
        return {"ran": False, "reason": "store_failed"}
    await _maybe_dispatch_drift_alert(db, snapshot, drift)
    logger.info("[entity SEO] catch-up ran for missed week %s", cur_iso_week)
    return {"ran": True, "iso_week": cur_iso_week}


async def _entity_seo_loop():
    """Background loop. Boots after a 15-min warmup, runs catch-up once,
    then polls every 5 min and fires inside Mon 04:30 UTC ±15 min."""
    from deps import db, is_mongo_available
    await asyncio.sleep(_WARMUP_S)
    try:
        if await is_mongo_available():
            await _entity_seo_catchup_if_missed(db, datetime.now(timezone.utc))
    except Exception as exc:
        logger.debug("[entity SEO] catch-up error: %s", exc)
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            if await is_mongo_available():
                await _try_run_entity_seo_once(db, now_utc)
        except Exception as exc:
            logger.debug("[entity SEO] loop iteration error: %s", exc)
        await asyncio.sleep(_LOOP_SLEEP_S)
