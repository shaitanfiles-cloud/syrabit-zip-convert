"""Task #466 — end-to-end SEO generate/publish pipeline regression test.

Covers the gap left after Task #460: the unit tests in
``test_seo_quality_scoring.py`` exercise the individual scorers and the
admin diagnostic endpoints in ``test_seo_diagnose_backfill.py``, but the
full publish pipeline — ``_auto_run_bg`` driving ``_generate_single_page``,
which in turn combines SEO + GEO sub-scores against
``_QUALITY_PUBLISH_THRESHOLD`` and routes the page through
``seo_writes.upsert_seo_page`` — is still uncovered.

A regression in how the gate combines the two sub-scores would silently
flip every freshly-generated page back to ``draft`` (the Task #457
outage). These tests pin the contract end-to-end against a mocked Mongo
and a mocked LLM:

* High-quality LLM response → ``seo_pages`` doc upserted with
  ``status="published"`` and empty ``fail_reasons``.
* Low-quality LLM response   → ``seo_pages`` doc upserted with
  ``status="draft"`` and ``fail_reasons`` populated with both the
  ``seo_below_threshold`` and ``geo_below_threshold`` markers.

The fake Mongo plumbing follows the same pattern as
``test_seo_diagnose_backfill.py`` so the suite stays consistent. No real
LLM, network, or Mongo connection is touched; the test runs in well
under a second.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import seo_engine  # noqa: E402


def _run(coro):
    """asyncio.run gives us a fresh loop per call so test ordering
    cannot poison this module."""
    return asyncio.run(coro)


# ─── Fake Mongo plumbing ────────────────────────────────────────────────────


class _FakeCursor:
    """Minimal motor-like async cursor used by both find() shapes the
    pipeline issues (chapters scan, eligible topics, sibling lookup,
    existing-page probe via find_one is handled separately)."""

    def __init__(self, items):
        self._items = list(items)

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    async def to_list(self, _n=None):
        return list(self._items)


_CHAPTER = {
    "id": "c1", "subject_id": "s1",
    "title": "Life Processes", "slug": "life-processes",
    "description": "Plant and animal life processes.",
}
_SUBJECT = {"id": "s1", "name": "Biology", "slug": "biology"}
_TOPIC = {
    "id": "t-photo", "chapter_id": "c1", "subject_id": "s1",
    "title": "Photosynthesis", "slug": "photosynthesis",
    "status": "published", "order": 1,
}


def _make_pipeline_db(*, upserts: list, gen_log: list):
    """Build a MagicMock DB that supports every collection access made
    by ``_auto_run_bg`` → ``_generate_single_page`` →
    ``seo_writes.upsert_seo_page``.

    ``upserts`` and ``gen_log`` are mutable lists the test inspects
    after the run.
    """
    db = MagicMock()

    # _auto_run_bg step 1: chapters scan + topic-existence probe.
    db.chapters.find = MagicMock(return_value=_FakeCursor([_CHAPTER]))
    db.topics.count_documents = AsyncMock(return_value=1)  # topic exists

    # Both topic.find call sites (eligible-topic scan and per-topic
    # sibling lookup inside _generate_single_page) hit the same mock;
    # returning [_TOPIC] satisfies both — siblings just resolves to a
    # single-entry list.
    db.topics.find = MagicMock(return_value=_FakeCursor([_TOPIC]))
    db.topics.insert_one = AsyncMock()

    # Hierarchy resolution: chapter + subject present, upstream chain
    # absent (exercises the lenient fallback path Task #457 added).
    db.chapters.find_one = AsyncMock(
        side_effect=lambda q, _p=None: _CHAPTER if q.get("id") == "c1" else None
    )
    db.subjects.find_one = AsyncMock(
        side_effect=lambda q, _p=None: _SUBJECT if q.get("id") == "s1" else None
    )
    db.streams.find_one = AsyncMock(return_value=None)
    db.classes.find_one = AsyncMock(return_value=None)
    db.boards.find_one = AsyncMock(return_value=None)

    # Existing seo_pages probe → None so generation proceeds.
    db.seo_pages.find_one = AsyncMock(return_value=None)

    # Capture every upsert (seo_writes.upsert_seo_page calls update_one
    # with $set/$setOnInsert).
    async def _capture_upsert(filt, update, upsert=False):
        # ``seo_writes.upsert_seo_page`` always wraps the page document in
        # ``{"$set": ..., "$setOnInsert": ...}`` so the publish-date stamps
        # land on insert-only. Unwrap to the document fields the test
        # actually asserts on.
        body = dict(update.get("$set") or {})
        body.update(update.get("$setOnInsert") or {})
        upserts.append({"filter": dict(filt), "body": body, "upsert": upsert})

    db.seo_pages.update_one = AsyncMock(side_effect=_capture_upsert)

    # Run summary log.
    async def _capture_log(doc):
        gen_log.append(doc)

    db.seo_generation_log.insert_one = AsyncMock(side_effect=_capture_log)

    return db


# ─── LLM response builders ──────────────────────────────────────────────────


_CTX = {
    "board_name": "AHSEC", "subject_name": "Biology",
    "chapter_title": "Life Processes", "topic_title": "Photosynthesis",
}


def _high_quality_response() -> str:
    """Markdown that hits every SEO + GEO reward and clears the 90-point
    publish threshold on both sub-scores. The bias toward Biology /
    Photosynthesis matches the topic the test seeds so the curriculum
    anchor signal fires.
    """
    year = datetime.now(timezone.utc).year
    return (
        "# Photosynthesis Notes — AHSEC Class 12 Biology\n\n"
        "Photosynthesis is the biochemical process through which green plants, "
        "algae, and several photosynthetic bacteria convert solar radiation "
        "into chemical energy stored inside glucose molecules. It powers "
        "nearly every food chain and lies at the heart of NCERT Class 12 "
        "Biology under the chapter Life Processes.\n\n"
        "## What is Photosynthesis? (Quick Answer)\n\n"
        "Photosynthesis denotes the conversion of carbon dioxide and water "
        "into glucose using sunlight, occurring inside chloroplasts of leaf "
        "mesophyll cells. According to the AHSEC Biology syllabus and the "
        "prescribed NCERT textbook, this process is fundamental for "
        "understanding plant nutrition, energy transfer, and ecosystem "
        "productivity.\n\n"
        "## Photosynthesis — Detailed Explanation for AHSEC Class 12 Biology\n\n"
        "Photosynthesis happens primarily in chloroplasts, double-membrane "
        "organelles densely packed inside palisade mesophyll cells of green "
        "leaves. Chlorophyll, the principal pigment, absorbs predominantly "
        "red and blue wavelengths of visible sunlight while reflecting green "
        "light, lending leaves their characteristic colour. Accessory "
        "pigments such as carotenoids, xanthophylls, and phycobilins broaden "
        "the absorption spectrum, ensuring efficient harvesting under varied "
        "environmental conditions.\n\n"
        "The overall stoichiometric equation summarises six molecules of "
        "carbon dioxide and six molecules of water yielding one glucose "
        "molecule and six molecules of oxygen, driven by photonic energy. "
        "Although the reaction looks deceptively simple, it actually proceeds "
        "through dozens of enzyme-mediated micro-steps distributed across "
        "the thylakoid membranes and the chloroplast stroma.\n\n"
        "### Light-Dependent Reactions\n\n"
        "Light-dependent reactions occur on thylakoid membranes where "
        "photosystems II and I capture photons sequentially. Photosystem II "
        "splits water molecules in a step termed photolysis, releasing "
        "oxygen as a by-product, donating electrons to the electron "
        "transport chain, and pumping protons into the thylakoid lumen. The "
        "accumulated proton gradient drives ATP synthase, generating ATP "
        "through chemiosmosis, while photosystem I energises electrons "
        "further so they reduce NADP+ into NADPH.\n\n"
        "Cyclic electron flow can supplement non-cyclic transport whenever "
        "the chloroplast requires additional ATP without further NADPH. "
        "This flexibility is highlighted in many AHSEC question papers "
        "because it illustrates how plants regulate energetic demands "
        "during fluctuating illumination.\n\n"
        "### Light-Independent Reactions (Calvin Cycle)\n\n"
        "Light-independent reactions, traditionally called the Calvin "
        "cycle, unfold within the stroma and convert atmospheric carbon "
        "dioxide into stable organic compounds. Ribulose bisphosphate "
        "carboxylase oxygenase, abbreviated RuBisCO, catalyses the "
        "carboxylation step where carbon dioxide attaches to ribulose "
        "1,5-bisphosphate. The resulting six-carbon intermediate "
        "immediately splits into two molecules of 3-phosphoglycerate.\n\n"
        "Subsequent reduction consumes ATP and NADPH generated upstream, "
        "producing glyceraldehyde 3-phosphate. Some triose-phosphate "
        "molecules exit toward sucrose biosynthesis while the remainder "
        "regenerate ribulose 1,5-bisphosphate, sustaining the cycle. Three "
        "turns of the cycle yield a net gain of one glyceraldehyde "
        "3-phosphate, equivalent to half a glucose molecule.\n\n"
        "### C4 and CAM Adaptations\n\n"
        "Tropical grasses such as sugarcane, maize, and sorghum employ the "
        "C4 pathway, spatially separating initial carbon fixation in "
        "mesophyll cells from the Calvin cycle inside bundle-sheath cells. "
        "Phosphoenolpyruvate carboxylase concentrates carbon dioxide near "
        "RuBisCO, suppressing wasteful photorespiration during hot, arid "
        "afternoons.\n\n"
        "Crassulacean acid metabolism plants, including pineapple, agave, "
        "and various succulents, separate carbon fixation temporally "
        "instead. Stomata open at night to capture carbon dioxide, storing "
        "it as malic acid inside vacuoles, then release it during daytime "
        "when stomata close to conserve precious water. Examiners "
        "frequently highlight these adaptations as exam-style comparison "
        "questions.\n\n"
        "### Importance Within Life Processes\n\n"
        "Photosynthesis underpins respiration, transpiration, nutrient "
        "cycling, and biomass accumulation across every terrestrial and "
        "aquatic ecosystem. Without continuous photosynthetic productivity, "
        "atmospheric oxygen would gradually deplete, the carbon cycle "
        "would unbalance, and the entire trophic pyramid of consumers from "
        "herbivores to apex predators would collapse within decades.\n\n"
        "## Key Points for Revision\n\n"
        "- Photosynthesis happens primarily inside chloroplasts of leaf "
        "mesophyll cells.\n"
        "- Chlorophyll absorbs red and blue wavelengths while reflecting "
        "green light efficiently.\n"
        "- Light reactions split water, releasing oxygen and producing ATP "
        "plus NADPH energy carriers.\n"
        "- The Calvin cycle fixes carbon dioxide using ATP and NADPH to "
        "synthesise glucose.\n"
        "- C4 plants concentrate carbon dioxide spatially, suppressing "
        "photorespiration during heat stress.\n"
        "- CAM plants separate carbon dioxide uptake temporally, "
        "conserving water in arid environments.\n"
        "- Photosynthesis is essential for atmospheric oxygen, the carbon "
        "cycle, and trophic ecosystems.\n\n"
        "## Important Concepts & Applications\n\n"
        "Example 1: A maize farmer in Assam observes higher grain yields "
        "during early monsoon weeks. The increased cloud cover diffuses "
        "sunlight, allowing deeper canopy layers to photosynthesise "
        "efficiently, raising overall productivity beyond the bright "
        "afternoon hours. This illustrates how light intensity, rather "
        "than mere duration, governs daily photosynthetic output.\n\n"
        "Example 2: Aquaculture engineers maintain phytoplankton blooms "
        "inside hatcheries because photosynthetic algae release dissolved "
        "oxygen, sustain juvenile fish respiration, and remove ammoniacal "
        "waste through nitrogen assimilation. Properly tuned lighting "
        "cycles boost biomass accumulation, lowering operating expenses "
        "for commercial fingerling farms across northeastern India.\n\n"
        "Example 3: Greenhouse horticulturists supplement red and blue "
        "LED arrays during winter to maintain steady photosynthetic rates "
        "when natural sunlight diminishes. Selecting wavelengths matching "
        "chlorophyll absorption peaks maximises efficiency while reducing "
        "electricity consumption, demonstrating elegant translation of "
        "plant physiology into agricultural engineering.\n\n"
        "## Exam-Style Questions with Answers\n\n"
        "Q1 (2-mark question): Define photosynthesis and name two pigments "
        "involved.\n"
        "Answer: Photosynthesis is the conversion of carbon dioxide and "
        "water into glucose using sunlight inside chloroplasts. The "
        "principal pigments are chlorophyll a and chlorophyll b, "
        "supplemented by accessory pigments like carotenoids.\n\n"
        "Q2 (2-mark question): Differentiate cyclic and non-cyclic "
        "photophosphorylation in one sentence each.\n"
        "Answer: Cyclic photophosphorylation involves only photosystem I "
        "and produces ATP without forming NADPH or releasing oxygen. "
        "Non-cyclic photophosphorylation involves both photosystems, "
        "generates ATP plus NADPH, and releases oxygen via water "
        "photolysis.\n\n"
        "Q3 (5-mark answer): Describe the Calvin cycle steps and explain "
        "how three turns yield one glyceraldehyde 3-phosphate.\n"
        "Answer: The Calvin cycle proceeds through carboxylation, "
        "reduction, and regeneration phases. Carboxylation attaches carbon "
        "dioxide to ribulose 1,5-bisphosphate via RuBisCO, producing two "
        "3-phosphoglycerate molecules. Reduction consumes ATP and NADPH, "
        "converting 3-phosphoglycerate into glyceraldehyde 3-phosphate. "
        "Regeneration recycles five glyceraldehyde 3-phosphate molecules "
        "into three ribulose 1,5-bisphosphate molecules using additional "
        "ATP. After three full turns, six glyceraldehyde 3-phosphate "
        "molecules form, five regenerate the substrate, and one exits "
        "toward glucose biosynthesis, representing the net productive "
        "yield.\n\n"
        "Q4 (5-mark answer): Compare C4 and CAM adaptations with respect "
        "to spatial and temporal separation, water use efficiency, and "
        "representative species.\n"
        "Answer: C4 plants like sugarcane, maize, and sorghum separate "
        "fixation spatially: PEP carboxylase concentrates carbon dioxide "
        "in mesophyll cells while the Calvin cycle proceeds inside "
        "bundle-sheath cells, suppressing photorespiration. CAM plants "
        "like pineapple, agave, and succulents separate fixation "
        "temporally: stomata open nocturnally to capture carbon dioxide "
        "as malic acid, which releases during daytime when stomata close. "
        "CAM offers superior water use efficiency, while C4 supports "
        "faster growth in tropical climates.\n\n"
        "Q5 (long answer 10 marks): Discuss factors influencing "
        "photosynthetic rate and outline one experimental method to "
        "measure it.\n"
        "Answer: Photosynthetic rate depends on light intensity, carbon "
        "dioxide concentration, temperature, water availability, "
        "chlorophyll concentration, and pollutants. Light intensity "
        "follows a saturation curve, beyond which additional photons "
        "cannot be utilised. Carbon dioxide concentration similarly "
        "saturates around 0.1 percent under field conditions. Temperature "
        "influences enzyme kinetics; rates rise to an optimum near 30 "
        "degrees Celsius and decline as denaturation begins. Water deficit "
        "forces stomatal closure, restricting carbon dioxide entry. "
        "Chlorophyll concentration and pigment health govern light "
        "absorption. Pollutants such as sulphur dioxide and ozone damage "
        "thylakoid membranes.\n\n"
        "A classic measurement uses Wilmott's bubbler apparatus where "
        "Hydrilla shoots release oxygen bubbles in sodium bicarbonate "
        "solution under controlled illumination. Counting bubbles per "
        "minute under varying light intensities yields a quantitative "
        "response curve, illustrating how plant physiology responds to "
        "environmental modulation. Examiners often request labelled "
        "diagrams of this apparatus alongside graphical interpretation.\n\n"
        "## Frequently Asked Questions (FAQ)\n\n"
        "Q: Why does photosynthesis require sunlight specifically rather "
        "than artificial heat?\n"
        "A: Sunlight delivers photons whose quantised energy excites "
        "chlorophyll electrons, initiating electron transport. Heat alone "
        "cannot achieve the photochemical excitation required for "
        "photolysis or NADP reduction.\n\n"
        "Q: Can photosynthesis occur underwater?\n"
        "A: Yes, aquatic plants and algae photosynthesise efficiently "
        "provided that sunlight penetrates the water column. Dissolved "
        "carbon dioxide and bicarbonate ions serve as carbon sources, "
        "while oxygen accumulates as dissolved gas.\n\n"
        "Q: How does photorespiration reduce photosynthetic efficiency?\n"
        "A: Photorespiration occurs when RuBisCO mistakenly fixes oxygen "
        "instead of carbon dioxide, producing a wasteful pathway that "
        "consumes ATP without yielding sugars. C4 and CAM adaptations "
        "evolved partly to minimise this loss.\n\n"
        "Q: Are mitochondria involved in photosynthesis?\n"
        "A: No, mitochondria perform cellular respiration, which oxidises "
        "glucose to release energy. Photosynthesis happens exclusively "
        "inside chloroplasts, although the two organelles cooperate "
        "metabolically by exchanging substrates.\n\n"
        "Q: Is photosynthesis affected by climate change?\n"
        "A: Rising carbon dioxide concentrations may temporarily boost "
        "photosynthesis in C3 plants, yet accompanying heat stress, "
        "drought, and altered precipitation patterns frequently offset "
        "gains, threatening agricultural productivity worldwide.\n\n"
        "## Citations and Curriculum Alignment\n\n"
        "As per the AHSEC Biology syllabus prescribed for Class 12, "
        "photosynthesis appears under the chapter Life Processes, aligned "
        "with the corresponding NCERT chapter and SCERT supplementary "
        "readers. The prescribed textbook recommends additional reference "
        "reading from chapter 12 and chapter 13 of the standard "
        "curriculum guide to deepen conceptual clarity. This page also "
        "follows board guideline marking schemes for short answer, long "
        "answer, and very short answer formats commonly tested in "
        "examinations.\n\n"
        "Exam tip: Always remember to label diagrams clearly, since "
        "labelled illustrations frequently carry one or two bonus marks "
        "in AHSEC marking schemes. Revision tip: practice writing the "
        "chemical equation accurately, paying attention to stoichiometric "
        "coefficients. Important note: students preparing for competitive "
        "entrance examinations should additionally study quantum "
        "requirements and Emerson enhancement.\n\n"
        f"Reviewed by Dr. A. Sharma, Syrabit Academic Team. "
        f"Last updated on {year}.\n"
    )


def _low_quality_response() -> str:
    """Word count clears the 1500-word ``min_words['notes']`` gate so the
    pipeline reaches the score-based publish decision, but the prose
    has none of the structural signals (no FAQ, no exam-style
    questions, no key points, no citations, no Q/A pairs, no freshness
    year, no attribution) — both SEO and GEO sub-scores land far below
    the 90-point publish threshold.
    """
    sentence = (
        "The topic is discussed briefly with general information and a bit "
        "of context for students. "
    )
    return "# Photosynthesis\n\n" + (sentence * 220)


# ─── End-to-end publish/draft pipeline ──────────────────────────────────────


def _seed_job(job_id: str):
    """``_auto_run_bg`` mutates the in-memory job ledger via
    ``_job_update`` / ``_job_record_outcome``; both are no-ops unless an
    entry already exists, so seed one before the run."""
    seo_engine._seo_jobs[job_id] = {
        "status": "queued", "total": 0, "done": 0, "errors": 0,
        "skipped": 0, "current": "", "started_at": "now",
        "finished_at": None, "kind": "test", "page_types": ["notes"],
        "outcomes": [], "reasons": {},
    }


def _run_pipeline_with_llm(llm_response: str):
    """Run ``_auto_run_bg`` once with a mocked LLM and a mocked Mongo,
    returning the captured upserts and run-log entries."""
    upserts: list = []
    gen_log: list = []
    seo_engine._db = _make_pipeline_db(upserts=upserts, gen_log=gen_log)
    original_llm = seo_engine._call_llm
    seo_engine._call_llm = AsyncMock(return_value=llm_response)
    job_id = "job-e2e-test"
    _seed_job(job_id)
    try:
        _run(seo_engine._auto_run_bg(job_id, ["notes"]))
    finally:
        seo_engine._call_llm = original_llm
        seo_engine._seo_jobs.pop(job_id, None)
    return upserts, gen_log


def test_high_quality_llm_response_publishes_seo_page_end_to_end():
    """Full ``_auto_run_bg`` → ``_generate_single_page`` →
    ``upsert_seo_page`` round-trip: a high-quality LLM response must
    yield a single ``seo_pages`` upsert with ``status='published'``,
    empty ``fail_reasons``, ``in_sitemap=True``, and both quality
    sub-scores at or above the 90-point publish threshold."""
    upserts, gen_log = _run_pipeline_with_llm(_high_quality_response())

    assert len(upserts) == 1, "expected exactly one seo_pages upsert"
    upsert = upserts[0]
    assert upsert["filter"] == {"topic_id": "t-photo", "page_type": "notes"}
    body = upsert["body"]

    assert body["status"] == "published"
    assert body["fail_reasons"] == []
    assert body["in_sitemap"] is True

    quality = body["quality"]
    assert quality["score"] >= seo_engine._QUALITY_PUBLISH_THRESHOLD
    assert quality["geo_score"] >= seo_engine._QUALITY_PUBLISH_THRESHOLD
    # 70/30 weighted blend of two passing sub-scores must also clear the
    # threshold — the gate that Task #466 is guarding.
    assert body["combined_score"] >= seo_engine._QUALITY_PUBLISH_THRESHOLD

    # Topic / hierarchy plumbing reaches the persisted document.
    assert body["topic_id"] == "t-photo"
    assert body["page_type"] == "notes"
    assert body["subject_slug"] == "biology"
    assert body["chapter_slug"] == "life-processes"
    assert body["word_count"] >= 1500

    # Run summary reflects the success.
    assert len(gen_log) == 1
    log = gen_log[0]
    assert log["job_id"] == "job-e2e-test"
    assert log["errors"] == 0
    assert log["page_types"] == ["notes"]
    assert log["avg_seo_score"] >= seo_engine._QUALITY_PUBLISH_THRESHOLD
    assert log["avg_geo_score"] >= seo_engine._QUALITY_PUBLISH_THRESHOLD


def test_low_quality_llm_response_saves_draft_with_fail_reasons_end_to_end():
    """A low-quality LLM response (clears the word-count floor but
    misses every structural signal) must NOT be published. The pipeline
    must persist the page as a draft with both threshold markers
    (``seo_below_threshold`` AND ``geo_below_threshold``) recorded in
    ``fail_reasons`` so editors can review — and ``in_sitemap`` must be
    False so the sitemap stays clean. This is the regression that would
    re-create the Task #457 outage if the publish gate ever flipped."""
    upserts, gen_log = _run_pipeline_with_llm(_low_quality_response())

    assert len(upserts) == 1
    body = upserts[0]["body"]

    assert body["status"] == "draft"
    assert body["in_sitemap"] is False

    # Both reason markers must be present — a regression that dropped
    # the GEO check would let pure-keyword pages slip through, and a
    # regression that dropped the SEO check would re-publish the
    # structureless content the Task #457 outage exposed.
    reasons = body["fail_reasons"]
    assert any(r.startswith("seo_below_threshold") for r in reasons), (
        f"missing seo_below_threshold marker: {reasons}"
    )
    assert any(r.startswith("geo_below_threshold") for r in reasons), (
        f"missing geo_below_threshold marker: {reasons}"
    )

    # Sub-scores actually fell below the gate (defends against a future
    # change that loosens the threshold without updating this test).
    quality = body["quality"]
    assert quality["score"] < seo_engine._QUALITY_PUBLISH_THRESHOLD
    assert quality["geo_score"] < seo_engine._QUALITY_PUBLISH_THRESHOLD

    # Run summary still records the attempt — drafts count as generated,
    # not as errors.
    assert len(gen_log) == 1
    assert gen_log[0]["errors"] == 0
