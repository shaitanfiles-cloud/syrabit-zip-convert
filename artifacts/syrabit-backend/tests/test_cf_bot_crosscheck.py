"""Tests for cf_bot_crosscheck (Task #316).

Covers:
  * JSON sidecar loading (missing file, malformed, happy path).
  * Comparison row shape + divergence flagging at the 15% threshold.
  * Googlebot variants roll up correctly.
  * Markdown rendering with and without external totals, and the
    expected systematic-gap paragraph always present.
  * End-to-end: the generated weekly report embeds the cross-check.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from cf_bot_crosscheck import (
    DIVERGENCE_THRESHOLD,
    build_crosscheck_section,
    compute_comparison,
    format_crosscheck_markdown,
    load_external_totals,
)


def _sample_cf_data(googlebot=1000, googlebot_image=0, bingbot=200,
                    adsbot=0):
    per_bot = {}
    if googlebot:
        per_bot["Googlebot"] = {"requests": googlebot, "bytes": 0,
                                "by_status": {"2xx": googlebot, "3xx": 0,
                                              "4xx": 0, "5xx": 0},
                                "by_cache": {}, "hit_pct": 0.0,
                                "error_rate": 0.0}
    if googlebot_image:
        per_bot["Googlebot-Image"] = {"requests": googlebot_image,
                                       "bytes": 0, "by_status": {},
                                       "by_cache": {}, "hit_pct": 0.0,
                                       "error_rate": 0.0}
    if bingbot:
        per_bot["Bingbot"] = {"requests": bingbot, "bytes": 0,
                              "by_status": {}, "by_cache": {},
                              "hit_pct": 0.0, "error_rate": 0.0}
    if adsbot:
        per_bot["AdsBot-Google"] = {"requests": adsbot, "bytes": 0,
                                    "by_status": {}, "by_cache": {},
                                    "hit_pct": 0.0, "error_rate": 0.0}
    totals = {"requests": sum(b["requests"] for b in per_bot.values()),
              "bytes": 0, "bots": len(per_bot)}
    return {"totals": totals, "per_bot": per_bot}


# ── load_external_totals ─────────────────────────────────────────────────────

def test_load_missing_file_returns_empty(tmp_path):
    assert load_external_totals("2026-W16", path=tmp_path / "nope.json") == {}


def test_load_malformed_json_returns_empty(tmp_path):
    p = tmp_path / "external.json"
    p.write_text("{not json")
    assert load_external_totals("2026-W16", path=p) == {}


def test_load_week_absent_returns_empty(tmp_path):
    p = tmp_path / "external.json"
    p.write_text(json.dumps({"weeks": {"2026-W15": {"googlebot": {"requests": 100}}}}))
    assert load_external_totals("2026-W16", path=p) == {}


def test_load_happy_path_normalises_shape(tmp_path):
    p = tmp_path / "external.json"
    p.write_text(json.dumps({"weeks": {"2026-W16": {
        "googlebot": {"requests": 4200, "source": "GSC"},
        "bingbot":   {"requests":  900, "source": "BWT"},
    }}}))
    got = load_external_totals("2026-W16", path=p)
    assert got == {
        "googlebot": {"requests": 4200, "source": "GSC"},
        "bingbot":   {"requests": 900,  "source": "BWT"},
    }


def test_load_skips_zero_or_negative_entries(tmp_path):
    p = tmp_path / "external.json"
    p.write_text(json.dumps({"weeks": {"2026-W16": {
        "googlebot": {"requests": 0, "source": "GSC"},
        "bingbot":   {"requests": -5, "source": "BWT"},
    }}}))
    assert load_external_totals("2026-W16", path=p) == {}


# ── compute_comparison ───────────────────────────────────────────────────────

def test_compute_comparison_rolls_up_google_variants():
    cf = _sample_cf_data(googlebot=1000, googlebot_image=100, adsbot=50)
    ext = {"googlebot": {"requests": 1100, "source": "GSC"}}
    rows = compute_comparison(cf, ext)
    goog = next(r for r in rows if r["crawler"] == "Googlebot")
    # 1000 + 100 + 50 = 1150 vs 1100 → +4.5% which is within tolerance.
    assert goog["cf_requests"] == 1150
    assert goog["external_requests"] == 1100
    assert goog["delta_pct"] == pytest.approx(4.5, abs=0.1)
    assert goog["divergent"] is False


def test_compute_comparison_flags_divergence_above_15_pct():
    cf = _sample_cf_data(googlebot=1500)
    ext = {"googlebot": {"requests": 1000, "source": "GSC"}}
    rows = compute_comparison(cf, ext)
    goog = next(r for r in rows if r["crawler"] == "Googlebot")
    assert goog["delta_pct"] == pytest.approx(50.0, abs=0.1)
    assert goog["divergent"] is True


def test_compute_comparison_not_divergent_at_exactly_threshold():
    # 15% delta → NOT flagged (strict > comparison).
    cf = _sample_cf_data(googlebot=1150)
    ext = {"googlebot": {"requests": 1000, "source": "GSC"}}
    rows = compute_comparison(cf, ext)
    goog = next(r for r in rows if r["crawler"] == "Googlebot")
    assert abs(goog["delta_pct"] - DIVERGENCE_THRESHOLD * 100) < 0.01
    assert goog["divergent"] is False


def test_compute_comparison_missing_external_yields_none():
    cf = _sample_cf_data(googlebot=500, bingbot=200)
    rows = compute_comparison(cf, {})
    for r in rows:
        assert r["external_requests"] is None
        assert r["delta_pct"] is None
        assert r["divergent"] is False
        # Raw CF side still populated so the table shows real data.
        assert r["cf_requests"] > 0


def test_compute_comparison_handles_negative_divergence():
    # CF total is SMALLER than external → UA filter is missing traffic.
    cf = _sample_cf_data(googlebot=500)
    ext = {"googlebot": {"requests": 1000, "source": "GSC"}}
    rows = compute_comparison(cf, ext)
    goog = next(r for r in rows if r["crawler"] == "Googlebot")
    assert goog["delta_pct"] == pytest.approx(-50.0, abs=0.1)
    assert goog["divergent"] is True


# ── format_crosscheck_markdown ───────────────────────────────────────────────

def test_markdown_includes_systematic_gap_paragraph_always():
    cf = _sample_cf_data(googlebot=1000, bingbot=200)
    rows = compute_comparison(cf, {})
    md = format_crosscheck_markdown(rows, iso_week="2026-W16",
                                      any_externals=False)
    assert "Cross-check vs. Google / Bing webmaster tools" in md
    assert "Expected systematic gap" in md
    assert "HTTP request" in md
    # Stub row message for unpopulated externals.
    assert "not supplied" in md
    # And the action callout so operators know what to do.
    assert "Action" in md


def test_markdown_flags_divergent_row_with_x():
    cf = _sample_cf_data(googlebot=2000)
    ext = {"googlebot": {"requests": 1000, "source": "GSC"}}
    rows = compute_comparison(cf, ext)
    md = format_crosscheck_markdown(rows, iso_week="2026-W16",
                                      any_externals=True)
    assert "❌" in md
    assert "+100.0%" in md


def test_markdown_shows_within_tolerance_for_small_delta():
    cf = _sample_cf_data(googlebot=1050)
    ext = {"googlebot": {"requests": 1000, "source": "GSC"}}
    rows = compute_comparison(cf, ext)
    md = format_crosscheck_markdown(rows, iso_week="2026-W16",
                                      any_externals=True)
    # Check only the table row, not the explanation paragraph (which
    # mentions `❌ diverges` as a literal label).
    table_rows = [ln for ln in md.splitlines()
                  if ln.startswith("| Googlebot")]
    assert table_rows, md
    assert "✅" in table_rows[0]
    assert "❌" not in table_rows[0]


# ── build_crosscheck_section (integration) ───────────────────────────────────

def test_build_section_reads_json_sidecar(tmp_path):
    p = tmp_path / "external.json"
    p.write_text(json.dumps({"weeks": {"2026-W16": {
        "googlebot": {"requests": 1000, "source": "GSC"},
    }}}))
    cf = _sample_cf_data(googlebot=1050)
    section = build_crosscheck_section(cf, "2026-W16", path=p)
    assert section["externals"]["googlebot"]["requests"] == 1000
    assert any(r["crawler"] == "Googlebot" and r["divergent"] is False
               for r in section["rows"])


def test_build_section_with_explicit_externals_skips_file(tmp_path):
    # File exists but is for a DIFFERENT week — passing externals= should
    # bypass the loader entirely.
    p = tmp_path / "external.json"
    p.write_text(json.dumps({"weeks": {"2026-W15": {"googlebot": {"requests": 9}}}}))
    cf = _sample_cf_data(googlebot=500)
    section = build_crosscheck_section(
        cf, "2026-W16", path=p,
        externals={"bingbot": {"requests": 150, "source": "inline"}},
    )
    bing = next(r for r in section["rows"] if r["crawler"] == "Bingbot")
    assert bing["external_requests"] == 150


# ── End-to-end: weekly report embeds the cross-check ─────────────────────────

def test_generate_per_ua_report_embeds_crosscheck(tmp_path, monkeypatch):
    """Full `generate_per_ua_report` path writes the cross-check section
    into the rendered markdown and the returned payload."""
    from cf_bot_report import generate_per_ua_report

    # Seed external totals file so the comparison has numbers.
    (tmp_path / "reports").mkdir()
    ext_file = tmp_path / "reports" / "external-crawler-totals.json"
    ext_file.write_text(json.dumps({"weeks": {"2026-W16": {
        "googlebot": {"requests": 1000, "source": "GSC Crawl stats"},
        "bingbot":   {"requests":  200, "source": "BWT Crawl info"},
    }}}))

    async def fake_buckets(*_a, **_k):
        # Two CF rows, one per bot, well-above the GSC/BWT totals.
        return [
            {"count": 1500, "sum": {"edgeResponseBytes": 0},
             "dimensions": {"userAgent": "Googlebot/2.1",
                            "cacheStatus": "hit",
                            "edgeResponseStatus": 200}},
            {"count": 250, "sum": {"edgeResponseBytes": 0},
             "dimensions": {"userAgent": "bingbot/2.0",
                            "cacheStatus": "miss",
                            "edgeResponseStatus": 200}},
        ]

    monkeypatch.setenv("CF_ANALYTICS_API_TOKEN", "x")
    monkeypatch.setenv("CF_ZONE_ID", "z")

    with patch("cf_bot_report._fetch_per_ua_buckets",
               new=AsyncMock(side_effect=fake_buckets)):
        # Mid-week of ISO 2026-W16 (2026-04-16 is a Thursday).
        now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
        result = asyncio.run(generate_per_ua_report(
            now=now, externals_path=str(ext_file)))

    assert result is not None
    md = result["markdown"]
    assert "Cross-check vs. Google / Bing webmaster tools" in md
    # Googlebot: 1500 vs 1000 = +50% → diverges ❌
    assert "❌" in md
    # Bingbot:   250 vs 200 = +25% → diverges ❌ too
    assert md.count("❌") >= 2
    # Crosscheck persisted in payload for Mongo storage.
    assert result["crosscheck"]["iso_week"] == "2026-W16"
    assert result["crosscheck"]["externals"]["googlebot"]["requests"] == 1000


def test_generate_per_ua_report_renders_stub_without_externals(monkeypatch,
                                                                 tmp_path):
    """When no externals file exists, the report still renders the
    cross-check section with the "how to populate" stub — so the reader
    always sees the comparison panel, per task's 'comparison table
    exists alongside the report' requirement."""
    from cf_bot_report import generate_per_ua_report

    async def fake_buckets(*_a, **_k):
        return [
            {"count": 100, "sum": {"edgeResponseBytes": 0},
             "dimensions": {"userAgent": "Googlebot/2.1",
                            "cacheStatus": "hit",
                            "edgeResponseStatus": 200}},
        ]

    monkeypatch.setenv("CF_ANALYTICS_API_TOKEN", "x")
    monkeypatch.setenv("CF_ZONE_ID", "z")
    missing = tmp_path / "does-not-exist.json"

    with patch("cf_bot_report._fetch_per_ua_buckets",
               new=AsyncMock(side_effect=fake_buckets)):
        now = datetime(2026, 4, 16, 12, 0, tzinfo=timezone.utc)
        result = asyncio.run(generate_per_ua_report(
            now=now, externals_path=str(missing)))

    md = result["markdown"]
    assert "Cross-check vs. Google / Bing webmaster tools" in md
    assert "not supplied" in md
    assert "Expected systematic gap" in md
