"""Task #460 — unit tests for the Task #457 SEO/GEO quality pipeline.

Covers:
  * ``_eligible_topic_filter``  (loose-by-default vs ``only_published``)
  * ``_resolve_hierarchy``      (lenient fallbacks when board/class/stream
                                 chain is broken; hard fail on missing
                                 chapter or subject)
  * ``_compute_geo_score``      (rewards: answer summary, key-facts,
                                 citations, freshness year, attribution,
                                 Q/A pairs, definition heading, anchor)
  * ``_combined_quality_score`` (70/30 weighted blend, integer rounding)

These functions are the silent gate keepers for whether the 991-topic
backfill actually publishes pages. A regression here would re-create the
"0 pages produced" outage that Task #457 fixed, so guard them in CI.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import seo_engine  # noqa: E402
from seo_engine import (  # noqa: E402
    _TOPIC_INELIGIBLE_STATUSES,
    _combined_quality_score,
    _compute_geo_score,
    _eligible_topic_filter,
    _resolve_hierarchy,
)


def _run(coro):
    """Robust against test ordering that may have closed the default
    event loop (some upstream tests do). asyncio.run creates a fresh
    loop for every call."""
    return asyncio.run(coro)


# ─── _eligible_topic_filter ──────────────────────────────────────────────────


def test_eligible_topic_filter_default_loose_includes_legacy_statuses():
    """Default (only_published=False) must accept missing/null/empty
    statuses AND any non-ineligible value (draft, suggested, legacy, …)
    so the 991 legacy topics get picked up by auto-run."""
    f = _eligible_topic_filter()
    assert "$or" in f, "default filter must be a loose $or clause"
    branches = f["$or"]
    # The four expected branches: missing, None, empty, $nin ineligible.
    assert {"status": {"$exists": False}} in branches
    assert {"status": None} in branches
    assert {"status": ""} in branches
    nin_branch = next(b for b in branches if isinstance(b.get("status"), dict)
                      and "$nin" in b["status"])
    nin_set = set(nin_branch["status"]["$nin"])
    # Every ineligible status from the constant must be present in $nin.
    assert nin_set == _TOPIC_INELIGIBLE_STATUSES
    # Sanity: well-known ineligible terms are listed.
    for bad in ("archived", "rejected", "deleted", "hidden"):
        assert bad in nin_set


def test_eligible_topic_filter_only_published_is_strict():
    """only_published=True must collapse to the single strict equality so
    callers that want production-ready topics never accidentally pick up
    drafts."""
    assert _eligible_topic_filter(only_published=True) == {"status": "published"}


def test_eligible_topic_filter_default_and_strict_differ():
    """Belt-and-braces: regression guard against someone collapsing the
    default branch to the strict one."""
    assert _eligible_topic_filter() != _eligible_topic_filter(only_published=True)


# ─── _resolve_hierarchy ──────────────────────────────────────────────────────


def _install_fake_db(*, chapter=None, subject=None, stream=None,
                     cls=None, board=None) -> MagicMock:
    """Wire seo_engine._db with async find_one stubs that return the
    provided documents. Each lookup is by collection.find_one(query)."""
    db = MagicMock()
    db.chapters.find_one = AsyncMock(return_value=chapter)
    db.subjects.find_one = AsyncMock(return_value=subject)
    db.streams.find_one = AsyncMock(return_value=stream)
    db.classes.find_one = AsyncMock(return_value=cls)
    db.boards.find_one = AsyncMock(return_value=board)
    seo_engine._db = db
    return db


def test_resolve_hierarchy_returns_empty_without_db():
    seo_engine._db = None
    assert _run(_resolve_hierarchy({"chapter_id": "c1"})) == {}


def test_resolve_hierarchy_empty_when_chapter_missing():
    """Missing chapter is a real blocker — must short-circuit to {}."""
    _install_fake_db(chapter=None)
    assert _run(_resolve_hierarchy({"chapter_id": "missing"})) == {}


def test_resolve_hierarchy_empty_when_subject_missing():
    """Without a subject we cannot build URLs → must still return {}."""
    _install_fake_db(
        chapter={"id": "c1", "subject_id": "s1", "title": "Chapter 1"},
        subject=None,
    )
    assert _run(_resolve_hierarchy({"chapter_id": "c1"})) == {}


def test_resolve_hierarchy_lenient_fallback_when_upstream_chain_broken():
    """When chapter+subject exist but stream/class/board chain is
    incomplete, hierarchy must still resolve with synthesised fallbacks
    (board='DEGREE', class='General') so the page actually generates."""
    _install_fake_db(
        chapter={"id": "c1", "subject_id": "s1", "title": "Atoms",
                 "slug": "atoms"},
        subject={"id": "s1", "name": "Physics", "slug": "physics"},
        stream=None, cls=None, board=None,
    )
    h = _run(_resolve_hierarchy({"chapter_id": "c1"}))
    assert h, "lenient resolution must NOT return empty when c+s present"
    assert h["chapter"]["title"] == "Atoms"
    assert h["subject"]["slug"] == "physics"
    # Synthesised fallbacks
    assert h["board"]["name"] == "DEGREE"
    assert h["class"]["name"] == "General"
    # Slugs derived from fallback names
    assert h["board"]["slug"] == "degree"
    assert h["class"]["slug"] == "general"
    assert h["chapter_slug"] == "atoms"


def test_resolve_hierarchy_prefers_topic_overrides_for_fallbacks():
    """When the topic doc carries explicit board_name/class_name those
    should beat the generic 'DEGREE'/'General' fallbacks so admin-set
    overrides survive a broken chain."""
    _install_fake_db(
        chapter={"id": "c1", "subject_id": "s1", "title": "Algebra"},
        subject={"id": "s1", "name": "Maths", "slug": "maths"},
    )
    h = _run(_resolve_hierarchy({
        "chapter_id": "c1",
        "board_name": "AHSEC",
        "class_name": "Class 12",
    }))
    assert h["board"]["name"] == "AHSEC"
    assert h["class"]["name"] == "Class 12"


def test_resolve_hierarchy_full_chain_uses_real_docs():
    """When the full board/class/stream chain resolves, the real docs
    must be returned untouched (not overwritten by fallbacks)."""
    _install_fake_db(
        chapter={"id": "c1", "subject_id": "s1", "title": "Cells",
                 "slug": "cells"},
        subject={"id": "s1", "name": "Biology", "slug": "biology",
                 "stream_id": "st1"},
        stream={"id": "st1", "class_id": "cl1", "name": "Science",
                "slug": "science"},
        cls={"id": "cl1", "board_id": "b1", "name": "Class 12",
             "slug": "class-12"},
        board={"id": "b1", "name": "AHSEC", "slug": "ahsec"},
    )
    h = _run(_resolve_hierarchy({"chapter_id": "c1"}))
    assert h["board"]["slug"] == "ahsec"
    assert h["class"]["slug"] == "class-12"
    assert h["stream"]["slug"] == "science"
    assert h["subject_slug"] == "biology"


# ─── _compute_geo_score ──────────────────────────────────────────────────────


_CURRENT_YEAR = datetime.now(timezone.utc).year


def _high_quality_geo_content(year: int = _CURRENT_YEAR) -> str:
    """A markdown page that should hit every GEO reward."""
    summary = (
        "Photosynthesis is the biochemical process by which green plants and "
        "some other organisms convert light energy from the sun into chemical "
        "energy stored in glucose. It is essential for plant growth and "
        "underpins almost every food chain on Earth, making it a cornerstone "
        "concept in NCERT Class 10 Biology."
    )
    return f"""# Photosynthesis Notes

{summary}

## Definition
Photosynthesis is defined in the NCERT prescribed textbook as the conversion
of carbon dioxide and water into glucose using sunlight, occurring in the
chloroplasts of plant cells. According to the SCERT syllabus this topic is a
high-yield exam area.

## Key Points
- Photosynthesis happens primarily in the chloroplasts of leaf cells.
- The overall reaction uses carbon dioxide, water and light energy.
- Chlorophyll absorbs mainly red and blue wavelengths of sunlight.
- Glucose produced is stored as starch in plant tissues for later use.
- Oxygen is released as a by-product of the light-dependent reactions.

## Exam Questions
**Q1:** Define photosynthesis in one line.
A1: It is the process by which plants make food using sunlight.
**Q2:** Why is chlorophyll important?
A2: It absorbs the light energy needed to drive the reaction.

Reviewed by Dr. A. Sharma. Last updated on {year}.
"""


def test_geo_score_zero_for_empty_content():
    assert _compute_geo_score("", "notes") == {"score": 0}


def test_geo_score_high_for_well_structured_page():
    """A page with summary + key facts + citations + freshness +
    attribution + Q/A + definition + anchor should clear the 90-point
    publish threshold comfortably."""
    ctx = {
        "topic_title": "Photosynthesis",
        "subject_name": "Biology",
        "chapter_title": "Life Processes",
    }
    geo = _compute_geo_score(_high_quality_geo_content(), "notes", ctx)
    assert geo["score"] >= 90, f"expected high GEO score, got {geo['score']}"
    assert geo["answer_summary_words"] >= 40
    assert geo["key_facts_count"] >= 3
    assert geo["citations"] >= 1
    assert geo["has_freshness"] is True
    assert geo["has_attribution"] is True
    assert geo["has_qa_pairs"] is True
    assert geo["has_definition"] is True
    assert geo["anchored"] is True
    assert geo["missing"] == []


def test_geo_score_reports_missing_signals_for_thin_content():
    """A barebones page should score low and enumerate the specific
    GEO signals it is missing — that drives the admin diagnostic UI."""
    geo = _compute_geo_score("# Title\n\nShort body.", "notes",
                             {"topic_title": "Quantum"})
    assert geo["score"] < 50
    for expected in ("answer_summary", "key_facts", "citations",
                     "freshness_year", "attribution", "topic_anchor"):
        assert expected in geo["missing"], f"{expected!r} should be flagged missing"


def test_geo_score_flags_missing_qa_pairs_only_for_important_questions():
    """qa_pairs is only required when the page_type is
    important-questions; for notes/definition pages it must NOT be in
    the missing list even when absent."""
    body = "# T\n\nSome paragraph long enough to mention things and stuff."
    notes_geo = _compute_geo_score(body, "notes", {"topic_title": "T"})
    iq_geo = _compute_geo_score(body, "important-questions",
                                {"topic_title": "T"})
    assert "qa_pairs" not in notes_geo["missing"]
    assert "qa_pairs" in iq_geo["missing"]


def test_geo_score_freshness_recognises_previous_year():
    """Pages mentioning either current year or previous year must be
    counted as 'fresh' — handles the early-January edge case."""
    body = f"# T\n\nSyllabus updated for {_CURRENT_YEAR - 1} academic session."
    geo = _compute_geo_score(body, "notes", {"topic_title": "T"})
    assert geo["has_freshness"] is True


def test_geo_score_caps_at_100():
    """Reward sum must be clamped at 100 even if every signal fires."""
    ctx = {"topic_title": "Photosynthesis", "subject_name": "Biology",
           "chapter_title": "Life Processes"}
    # Repeat citations many times to push raw sum above 100.
    body = _high_quality_geo_content() + "\n\n" + ("NCERT syllabus. " * 50)
    assert _compute_geo_score(body, "notes", ctx)["score"] <= 100


# ─── _combined_quality_score ────────────────────────────────────────────────


def test_combined_quality_score_70_30_weighting():
    """0.7 * SEO + 0.3 * GEO, rounded to nearest integer."""
    assert _combined_quality_score({"score": 100}, {"score": 100}) == 100
    assert _combined_quality_score({"score": 0}, {"score": 0}) == 0
    # 0.7*80 + 0.3*60 = 56 + 18 = 74
    assert _combined_quality_score({"score": 80}, {"score": 60}) == 74
    # 0.7*90 + 0.3*40 = 63 + 12 = 75
    assert _combined_quality_score({"score": 90}, {"score": 40}) == 75


def test_combined_quality_score_handles_missing_or_none_inputs():
    """Either sub-score may be missing (defaults to 0). None must not
    crash — the gate has to be defensive against mid-pipeline bugs."""
    assert _combined_quality_score({}, {"score": 50}) == 15  # 0.3*50
    assert _combined_quality_score({"score": 50}, {}) == 35  # 0.7*50
    assert _combined_quality_score({"score": None}, {"score": None}) == 0


def test_combined_quality_score_rounds_half_to_even_or_up():
    """Whatever Python's round() does, the result must be an int in [0, 100]."""
    out = _combined_quality_score({"score": 81}, {"score": 50})  # 56.7+15 = 71.7
    assert isinstance(out, int)
    assert 0 <= out <= 100
