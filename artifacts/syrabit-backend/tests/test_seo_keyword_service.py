"""Tests for the unified SEO keyword + metadata enrichment service.

Covers:
  * `google_suggest_client.fetch_suggestions` cache hit/miss + normalisation
  * `google_suggest_client.fetch_india_edu_bundle` locale merge
  * `seo_keyword_service._merge_sources` deterministic blend
  * `seo_keyword_service.enrich_seo_for_seed`:
      - cache hit short-circuit
      - LLM-enriched fresh path (with injected fakes)
      - template fallback when LLM returns garbage
      - bing/suggest fetcher exceptions are swallowed (fail-open)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_db(initial_doc=None):
    db = MagicMock()
    coll = MagicMock()
    coll.find_one = AsyncMock(return_value=initial_doc)
    coll.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    db.__getitem__.return_value = coll
    return db, coll


# ---------------------------------------------------------------------------
# google_suggest_client
# ---------------------------------------------------------------------------

def test_suggest_cache_hit_skips_network(monkeypatch):
    import google_suggest_client as gsc
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    fresh = now - timedelta(days=2)
    db, coll = _make_db({
        "suggestions": [{"keyword": "ahsec physics notes", "rank": 20}],
        "cached_at": fresh,
    })

    async def _boom(*a, **kw):
        raise AssertionError("network must not be called on cache hit")
    monkeypatch.setattr(gsc, "_suggest_get", _boom)

    res = _run(gsc.fetch_suggestions("ahsec physics", db=db, now=now))
    assert res["source"] == "cache"
    assert res["cached"] is True
    assert res["suggestions"][0]["keyword"] == "ahsec physics notes"
    coll.update_one.assert_not_called()


def test_suggest_normalises_dedupes_and_drops_seed(monkeypatch):
    import google_suggest_client as gsc
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    db, coll = _make_db(None)

    async def _fake(seed, country, language, client=None):
        return [
            "AHSEC Physics",            # same as seed (case-insensitive) -> drop
            "ahsec physics notes",
            "AHSEC PHYSICS NOTES",      # dup of above -> drop
            "  ",                       # blank -> drop
            "ahsec physics pyq 2024",
        ]
    monkeypatch.setattr(gsc, "_suggest_get", _fake)

    res = _run(gsc.fetch_suggestions("AHSEC Physics", db=db, now=now))
    assert res["source"] == "api"
    kws = [s["keyword"] for s in res["suggestions"]]
    assert kws == ["ahsec physics notes", "ahsec physics pyq 2024"]
    # Higher rank for earlier-returned suggestion.
    assert res["suggestions"][0]["rank"] > res["suggestions"][1]["rank"]
    coll.update_one.assert_awaited()


def test_suggest_api_empty_falls_back_to_stale_cache(monkeypatch):
    import google_suggest_client as gsc
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    stale = now - timedelta(days=30)
    db, _coll = _make_db({
        "suggestions": [{"keyword": "old hit", "rank": 5}],
        "cached_at": stale,
    })

    async def _empty(*a, **kw):
        return []
    monkeypatch.setattr(gsc, "_suggest_get", _empty)

    res = _run(gsc.fetch_suggestions("seed", db=db, now=now))
    assert res["source"] == "cache_stale_fallback"
    assert res["suggestions"][0]["keyword"] == "old hit"


def test_india_edu_bundle_merges_locales(monkeypatch):
    import google_suggest_client as gsc
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    db, _coll = _make_db(None)

    calls = []

    async def _fake(seed, country, language, client=None):
        calls.append((language, country))
        # "common" appears in en+as; "as_only" appears only in as.
        if language == "en":
            return ["common", "en_only"]
        if language == "as":
            return ["common", "as_only"]
        return ["bn_only"]
    monkeypatch.setattr(gsc, "_suggest_get", _fake)

    res = _run(gsc.fetch_india_edu_bundle("magnetism", db=db, now=now))
    assert {(l, c) for l, c in calls} == {("en", "in"), ("as", "in"), ("bn", "in")}
    by_kw = {s["keyword"]: s for s in res["suggestions"]}
    assert sorted(by_kw["common"]["locales"]) == sorted(["en-in", "as-in"])
    # Multi-locale entry should sort above single-locale entries.
    assert res["suggestions"][0]["keyword"] == "common"


# ---------------------------------------------------------------------------
# seo_keyword_service
# ---------------------------------------------------------------------------

def test_merge_sources_blends_bing_and_suggest():
    import seo_keyword_service as sks
    bing = {"keywords": [
        {"keyword": "ahsec physics notes", "impressions": 1000},
        {"keyword": "atom structure", "impressions": 500},
    ]}
    suggest = {"suggestions": [
        {"keyword": "ahsec physics notes", "rank": 20, "locales": ["en-in", "as-in"]},
        {"keyword": "magnetism class 12", "rank": 10, "locales": ["en-in"]},
        # Seed itself must be dropped.
        {"keyword": "ahsec physics", "rank": 25, "locales": ["en-in"]},
    ]}
    merged = sks._merge_sources("ahsec physics", bing, suggest)
    keys = [m["keyword"] for m in merged]
    assert "ahsec physics" not in [k.lower() for k in keys]
    overlap = next(m for m in merged if m["keyword"] == "ahsec physics notes")
    assert set(overlap["sources"]) == {"bing", "google_suggest"}
    assert overlap["locales"] == ["en-in", "as-in"]
    # Overlap entry should outrank single-source entries.
    assert merged[0]["keyword"] == "ahsec physics notes"


def test_enrich_cache_hit(monkeypatch):
    import seo_keyword_service as sks
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    fresh = now - timedelta(days=3)
    cached = {
        "merged": [{"keyword": "k", "score": 0.5, "sources": ["bing"], "locales": []}],
        "bundle": {"meta_title": "cached title", "meta_description": "cached",
                   "meta_keywords": ["k"], "og_title": "cached title",
                   "og_description": "cached", "twitter_title": "cached title",
                   "twitter_description": "cached", "geo_tags": {"geo.region": "IN-AS"},
                   "jsonld_keywords": "k", "enriched_by": "llm"},
        "counts": {"bing": 1, "suggest": 0, "merged": 1},
        "cached_at": fresh,
    }
    db, coll = _make_db(cached)

    async def _boom_bing(*a, **kw):
        raise AssertionError("bing must not be called on cache hit")

    async def _boom_sug(*a, **kw):
        raise AssertionError("suggest must not be called on cache hit")

    res = _run(sks.enrich_seo_for_seed(
        "atom", db=db, now=now,
        bing_fetcher=_boom_bing, suggest_fetcher=_boom_sug,
        llm_caller=None,
    ))
    assert res["source"] == "cache"
    assert res["bundle"]["meta_title"] == "cached title"
    coll.update_one.assert_not_called()


def test_enrich_fresh_path_with_llm(monkeypatch):
    import seo_keyword_service as sks
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    db, coll = _make_db(None)

    async def _bing(api_key, seed, *, db, country, language, now):
        return {"keywords": [
            {"keyword": "atom structure notes", "impressions": 800},
        ]}

    async def _sug(seed, *, db, now):
        return {"suggestions": [
            {"keyword": "atom structure class 11", "rank": 20, "locales": ["en-in"]},
            {"keyword": "পরমাণুর গঠন", "rank": 15, "locales": ["as-in"]},
        ]}

    captured_messages = {}

    async def _llm(messages, model, max_tokens):
        captured_messages["m"] = messages
        return json.dumps({
            "meta_title": "Atom Structure — Class 11 Notes",
            "meta_description": "Concise AHSEC notes on atom structure.",
            "meta_keywords": [
                "atom structure notes", "atom structure class 11",
                "পরমাণুর গঠন",
            ],
            "og_title": "Atom Structure — Class 11 Notes",
            "og_description": "Concise AHSEC notes on atom structure.",
            "twitter_title": "Atom Structure",
            "twitter_description": "Concise AHSEC notes on atom structure.",
            "geo_tags": {"geo.region": "IN-AS", "geo.placename": "Assam, India",
                         "icbm": "26.2006, 92.9376", "language": "as-IN"},
            "jsonld_keywords": "atom structure notes, পরমাণুর গঠন",
        })

    res = _run(sks.enrich_seo_for_seed(
        "atom structure", db=db, now=now,
        bing_fetcher=_bing, suggest_fetcher=_sug, llm_caller=_llm,
    ))
    assert res["source"] == "fresh"
    assert res["bundle"]["enriched_by"] == "llm"
    assert "atom structure class 11" in res["bundle"]["meta_keywords"]
    assert res["bundle"]["geo_tags"]["language"] == "as-IN"
    assert res["counts"] == {"bing": 1, "suggest": 2, "merged": 3}
    coll.update_one.assert_awaited()
    # System prompt must mention Assam audience for the LLM to behave.
    sys_msg = captured_messages["m"][0]["content"]
    assert "Assam" in sys_msg


def test_enrich_falls_back_to_template_when_llm_returns_garbage(monkeypatch):
    import seo_keyword_service as sks
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    db, coll = _make_db(None)

    async def _bing(*a, **kw):
        return {"keywords": [{"keyword": "atom notes", "impressions": 100}]}

    async def _sug(*a, **kw):
        return {"suggestions": [{"keyword": "atom class 11", "rank": 20, "locales": ["en-in"]}]}

    async def _llm(messages, model, max_tokens):
        return "I cannot help with that, sorry."

    res = _run(sks.enrich_seo_for_seed(
        "atom", db=db, now=now,
        bing_fetcher=_bing, suggest_fetcher=_sug, llm_caller=_llm,
    ))
    assert res["source"] == "fresh_template_only"
    assert res["bundle"]["enriched_by"] == "template"
    # Template still includes merged keywords.
    assert "atom notes" in res["bundle"]["meta_keywords"] or \
           "atom class 11" in res["bundle"]["meta_keywords"]
    assert res["bundle"]["geo_tags"]["geo.region"] == "IN-AS"


def test_enrich_swallows_source_exceptions(monkeypatch):
    import seo_keyword_service as sks
    now = datetime(2026, 4, 20, tzinfo=timezone.utc)
    db, _coll = _make_db(None)

    async def _bing_boom(*a, **kw):
        raise RuntimeError("bing down")

    async def _sug_boom(*a, **kw):
        raise RuntimeError("suggest down")

    async def _llm(messages, model, max_tokens):
        # No keyword signals -> tell us via the prompt; still produce a bundle.
        return json.dumps({
            "meta_title": "Atom — Notes",
            "meta_description": "Notes for AHSEC.",
            "meta_keywords": ["atom"],
            "og_title": "Atom — Notes",
            "og_description": "Notes for AHSEC.",
            "twitter_title": "Atom — Notes",
            "twitter_description": "Notes for AHSEC.",
            "geo_tags": {},
            "jsonld_keywords": "atom",
        })

    res = _run(sks.enrich_seo_for_seed(
        "atom", db=db, now=now,
        bing_fetcher=_bing_boom, suggest_fetcher=_sug_boom, llm_caller=_llm,
    ))
    # Both fetchers blew up but we still produced a bundle.
    assert res["counts"] == {"bing": 0, "suggest": 0, "merged": 0}
    assert res["source"] == "fresh"
    assert res["bundle"]["meta_title"] == "Atom — Notes"
    # Defaulted Assam geo tags.
    assert res["bundle"]["geo_tags"]["geo.region"] == "IN-AS"


# ---------------------------------------------------------------------------
# /api/admin/seo/enrich route integration
# ---------------------------------------------------------------------------

import pytest


@pytest.fixture
def _seo_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True, "sub": "admin-1"}


def _build_app(*, authed: bool, admin):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from routes.admin_seo_keywords import router
    from auth_deps import get_admin_user

    app = FastAPI()
    app.include_router(router)
    if authed:
        app.dependency_overrides = {get_admin_user: lambda: admin}
    else:
        def _deny():
            raise HTTPException(status_code=401, detail="Not authenticated")
        app.dependency_overrides = {get_admin_user: _deny}
    return TestClient(app)


def test_admin_seo_enrich_requires_auth(_seo_admin):
    client = _build_app(authed=False, admin=_seo_admin)
    res = client.get("/api/admin/seo/enrich", params={"seed": "atom"})
    assert res.status_code in (401, 403)


def test_admin_seo_enrich_rejects_short_seed(_seo_admin):
    client = _build_app(authed=True, admin=_seo_admin)
    # min_length=2 — single char must 422.
    res = client.get("/api/admin/seo/enrich", params={"seed": "x"})
    assert res.status_code == 422


def test_admin_seo_enrich_returns_bundle(monkeypatch, _seo_admin):
    import seo_keyword_service as sks

    async def _fake_enrich(seed, **kw):
        return {
            "seed": seed, "country": kw.get("country", "IN"),
            "language": kw.get("language", "en-IN"),
            "fetched_at": "2026-04-20T20:00:00+00:00",
            "source": "fresh",
            "merged": [{"keyword": "atom notes", "score": 0.9,
                        "sources": ["bing", "google_suggest"], "locales": ["en-in"]}],
            "bundle": {
                "meta_title": "Atom — Notes",
                "meta_description": "Notes for AHSEC.",
                "meta_keywords": ["atom notes"],
                "og_title": "Atom — Notes", "og_description": "Notes for AHSEC.",
                "twitter_title": "Atom — Notes", "twitter_description": "Notes for AHSEC.",
                "geo_tags": {"geo.region": "IN-AS", "geo.placename": "Assam, India",
                             "icbm": "26.2006, 92.9376", "language": "en-IN"},
                "jsonld_keywords": "atom notes", "enriched_by": "llm",
            },
            "counts": {"bing": 1, "suggest": 1, "merged": 1},
        }
    # Patch the symbol the route imported, not just the source module.
    import routes.admin_seo_keywords as r
    monkeypatch.setattr(r, "enrich_seo_for_seed", _fake_enrich)

    client = _build_app(authed=True, admin=_seo_admin)
    res = client.get("/api/admin/seo/enrich", params={"seed": "atom"})
    assert res.status_code == 200
    body = res.json()
    assert body["seed"] == "atom"
    assert body["source"] == "fresh"
    assert body["bundle"]["meta_title"] == "Atom — Notes"
    assert body["bundle"]["geo_tags"]["geo.region"] == "IN-AS"


def test_admin_seo_enrich_propagates_errors_as_500(monkeypatch, _seo_admin):
    async def _boom(seed, **kw):
        raise RuntimeError("downstream blew up")
    import routes.admin_seo_keywords as r
    monkeypatch.setattr(r, "enrich_seo_for_seed", _boom)

    client = _build_app(authed=True, admin=_seo_admin)
    res = client.get("/api/admin/seo/enrich", params={"seed": "atom"})
    assert res.status_code == 500
    assert "downstream blew up" in res.json().get("detail", "")
