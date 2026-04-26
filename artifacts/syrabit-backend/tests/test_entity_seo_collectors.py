"""Task #940 — adapter contract tests for the entity SEO collectors.

Each collector is given a deterministic in-process ``http_get`` mock so
the test never touches the real Wikidata / Wikipedia / Crunchbase /
Knowledge Graph endpoints. We assert that:

  * the happy path returns ``status="ok"`` with the expected fields,
  * a 404 returns ``status="missing"``,
  * a transport error returns ``status="error"``,
  * the missing-claim list (Wikidata) deep-links to the correct edit URL
    and only contains props that are *not* in the live entity.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

import entity_seo_health as esh


# ─── tiny mock transport ───────────────────────────────────────────────


class _MockTransport:
    """Returns a queued response matched by URL substring."""

    def __init__(self, route_table: Dict[str, Dict[str, Any]]):
        self._routes = route_table
        self.calls: List[str] = []

    async def __call__(self, url, *, method="GET", params=None, headers=None, timeout=10.0):
        self.calls.append(url)
        for substr, resp in self._routes.items():
            if substr in url:
                return dict(resp)
        return {"status_code": 404, "json": None, "text": "", "error": None}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── fetch_wikidata ────────────────────────────────────────────────────


def test_fetch_wikidata_ok_with_some_missing_claims():
    # Live entity has P31 + P17 + P856 but is missing P131, P112, P571, P1448.
    payload = {
        "entities": {
            "Q42": {
                "labels": {"en": {"value": "Syrabit.ai"}},
                "claims": {"P31": [{}], "P17": [{}], "P856": [{}]},
            },
        },
    }
    mock = _MockTransport({"Q42": {"status_code": 200, "json": payload, "text": None, "error": None}})
    sig = _run(esh.fetch_wikidata(qid="Q42", http_get=mock))
    assert sig["status"] == "ok"
    assert sig["fields"]["claim_count"] == 3
    assert set(sig["fields"]["present_claims"]) == {"P31", "P17", "P856"}
    missing_props = [c["prop"] for c in sig["fields"]["missing_claims"]]
    assert "P131" in missing_props and "P112" in missing_props
    # Each missing claim deep-links to the per-property anchor.
    for c in sig["fields"]["missing_claims"]:
        assert c["edit_url"].startswith("https://www.wikidata.org/wiki/Q42#")


def test_fetch_wikidata_404_returns_missing():
    mock = _MockTransport({"Q42": {"status_code": 404, "json": None, "text": "", "error": None}})
    sig = _run(esh.fetch_wikidata(qid="Q42", http_get=mock))
    assert sig["status"] == "missing"
    # All desired claims surfaced as missing so the panel can deep-link.
    assert len(sig["fields"]["missing_claims"]) == len(esh.DESIRED_WIKIDATA_CLAIMS)


def test_fetch_wikidata_no_qid_configured():
    sig = _run(esh.fetch_wikidata(qid="", http_get=_MockTransport({})))
    assert sig["status"] == "missing"
    # Special:NewItem deep-link when no QID exists.
    assert sig["fields"]["missing_claims"][0]["edit_url"].startswith(
        "https://www.wikidata.org/wiki/Special:NewItem")


def test_fetch_wikidata_transport_error():
    mock = _MockTransport({"Q42": {"status_code": 0, "json": None, "text": None, "error": "boom"}})
    sig = _run(esh.fetch_wikidata(qid="Q42", http_get=mock))
    assert sig["status"] == "error"
    assert "boom" in sig["summary"]


# ─── fetch_wikipedia ───────────────────────────────────────────────────


def test_fetch_wikipedia_ok():
    payload = {
        "title": "Syrabit.ai",
        "extract": "Syrabit.ai is an Indian education-technology company.",
        "timestamp": "2026-04-01T00:00:00Z",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Syrabit.ai"}},
    }
    mock = _MockTransport({"page/summary": {"status_code": 200, "json": payload, "text": None, "error": None}})
    sig = _run(esh.fetch_wikipedia(title="Syrabit.ai", http_get=mock))
    assert sig["status"] == "ok"
    assert sig["fields"]["page_url"] == "https://en.wikipedia.org/wiki/Syrabit.ai"


def test_fetch_wikipedia_missing():
    mock = _MockTransport({"page/summary": {"status_code": 404, "json": None, "text": "", "error": None}})
    sig = _run(esh.fetch_wikipedia(title="Syrabit.ai", http_get=mock))
    assert sig["status"] == "missing"
    assert sig["fields"]["draft_url"].startswith("https://en.wikipedia.org/wiki/Draft:")


# ─── fetch_crunchbase ──────────────────────────────────────────────────


def test_fetch_crunchbase_ok_with_completeness():
    body = (
        '<html><body>company description founder Dipak Rai based in Guwahati Assam '
        'website https://syrabit.ai</body></html>'
    )
    mock = _MockTransport({"crunchbase.com": {"status_code": 200, "json": None, "text": body, "error": None}})
    sig = _run(esh.fetch_crunchbase(permalink="syrabit-ai", http_get=mock))
    assert sig["status"] == "ok"
    assert sig["fields"]["completeness_pct"] == 100.0
    assert sig["fields"]["fields_present"]["founders"] is True


def test_fetch_crunchbase_missing():
    mock = _MockTransport({"crunchbase.com": {"status_code": 404, "json": None, "text": "", "error": None}})
    sig = _run(esh.fetch_crunchbase(permalink="syrabit-ai", http_get=mock))
    assert sig["status"] == "missing"
    assert sig["fields"]["submit_url"]


# ─── verify_sameas_profile / fetch_sameas ──────────────────────────────


def test_verify_sameas_profile_ok_and_broken():
    mock = _MockTransport({
        "linkedin.com": {"status_code": 200, "json": None, "text": None,
                         "error": None, "final_url": "https://www.linkedin.com/x"},
        "twitter.com":  {"status_code": 404, "json": None, "text": None,
                         "error": None, "final_url": "https://twitter.com/x"},
    })
    ok = _run(esh.verify_sameas_profile("https://www.linkedin.com/x", http_get=mock))
    bad = _run(esh.verify_sameas_profile("https://twitter.com/x", http_get=mock))
    assert ok["status"] == "ok" and ok["http_status"] == 200
    assert bad["status"] == "missing" and bad["http_status"] == 404


def test_verify_sameas_profile_offsite_redirect_flagged_as_missing():
    """A 200 from a URL that 301'd to a different brand host is still
    a broken profile from an SEO perspective — the canonical link is
    no longer ours. Sub-host changes (www.linkedin.com vs linkedin.com)
    must NOT trip this check."""
    mock = _MockTransport({
        # 200 OK but the response landed on captcha.example.com
        "linkedin.com/company/syrabit": {
            "status_code": 200, "json": None, "text": None, "error": None,
            "final_url": "https://captcha.example.com/blocked",
        },
        # 200 OK and stayed on the same brand host (www. stripped) — fine.
        "linkedin.com/in/syrabit": {
            "status_code": 200, "json": None, "text": None, "error": None,
            "final_url": "https://www.linkedin.com/in/syrabit",
        },
    })
    bad = _run(esh.verify_sameas_profile("https://linkedin.com/company/syrabit", http_get=mock))
    ok  = _run(esh.verify_sameas_profile("https://linkedin.com/in/syrabit",     http_get=mock))
    assert bad["status"] == "missing"
    assert "off-site" in bad["summary"]
    assert ok["status"] == "ok"


def test_fetch_sameas_aggregate_status():
    mock = _MockTransport({
        "linkedin.com": {"status_code": 200, "json": None, "text": None, "error": None},
        "twitter.com":  {"status_code": 200, "json": None, "text": None, "error": None},
        "github.com":   {"status_code": 200, "json": None, "text": None, "error": None},
        "youtube.com":  {"status_code": 404, "json": None, "text": None, "error": None},
    })
    sig = _run(esh.fetch_sameas(http_get=mock))
    # One of the org profiles 404'd → aggregate is "missing".
    assert sig["status"] == "missing"
    assert any(b["http_status"] == 404 for b in sig["fields"]["broken"])


# ─── fetch_google_kg ───────────────────────────────────────────────────


def test_fetch_google_kg_no_api_key_returns_error_with_configured_false():
    # No API key + no env: surfaces as configurable-but-disabled.
    sig = _run(esh.fetch_google_kg(api_key="", http_get=_MockTransport({})))
    assert sig["status"] == "error"
    assert sig["fields"]["configured"] is False


def test_fetch_google_kg_panel_present():
    payload = {
        "itemListElement": [
            {"resultScore": 950,
             "result": {"@id": "kg:/m/syrabit", "name": "Syrabit.ai",
                        "description": "Education-technology company"}},
        ],
    }
    mock = _MockTransport({"kgsearch": {"status_code": 200, "json": payload, "text": None, "error": None}})
    sig = _run(esh.fetch_google_kg(api_key="abc", http_get=mock))
    assert sig["status"] == "ok"
    assert sig["fields"]["kg_id"] == "kg:/m/syrabit"
    assert sig["fields"]["result_score"] == 950


def test_fetch_google_kg_no_panel_entry():
    mock = _MockTransport({"kgsearch": {"status_code": 200, "json": {"itemListElement": []}, "text": None, "error": None}})
    sig = _run(esh.fetch_google_kg(api_key="abc", http_get=mock))
    assert sig["status"] == "missing"


# ─── aggregate_snapshot wires everything ──────────────────────────────


def test_aggregate_snapshot_combines_signal_statuses():
    mock = _MockTransport({
        "Special:EntityData": {"status_code": 404, "json": None, "text": "", "error": None},
        "page/summary":       {"status_code": 200, "json": {"title": "Syrabit.ai", "content_urls": {"desktop": {"page": "x"}}}, "text": None, "error": None},
        "crunchbase.com":     {"status_code": 200, "json": None, "text": "company description founder Dipak Rai Guwahati syrabit.ai", "error": None},
        "linkedin.com":       {"status_code": 200, "json": None, "text": None, "error": None},
        "twitter.com":        {"status_code": 200, "json": None, "text": None, "error": None},
        "github.com":         {"status_code": 200, "json": None, "text": None, "error": None},
        "youtube.com":        {"status_code": 200, "json": None, "text": None, "error": None},
        "kgsearch":           {"status_code": 200, "json": {"itemListElement": []}, "text": None, "error": None},
    })
    snap = _run(esh.aggregate_snapshot(http_get=mock))
    # Wikidata QID isn't configured by default in tests → "missing".
    assert snap["signals"]["wikidata"]["status"] == "missing"
    assert snap["signals"]["wikipedia"]["status"] == "ok"
    # No GOOGLE_KG_API_KEY in test env → error path.
    assert snap["signals"]["google_kg"]["status"] in {"missing", "error"}
    assert snap["aggregate_status"] in {"missing", "degraded"}
    assert snap["summary"]["wikipedia_present"] is True
