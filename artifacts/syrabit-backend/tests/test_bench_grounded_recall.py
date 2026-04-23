"""Gate the grounded-answer recall benchmark against the recorded baseline.

Runs the bench against the offline corpus so CI is hermetic (no network).
Asserts every baseline metric holds within a small tolerance so retrieval
regressions are caught in PR review, not after students ask.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

TOLERANCE = 0.02  # allow 2% drop before failing


def _run() -> dict:
    from bench.grounded_recall import load_cases, run_benchmark
    cases = load_cases()
    return asyncio.run(
        run_benchmark(cases, retriever="offline")
    ).to_dict()


def test_fixture_has_enough_cases():
    from bench.grounded_recall import load_cases
    cases = load_cases()
    assert len(cases) >= 100, f"expected at least 100 labelled cases, got {len(cases)}"


def test_every_case_has_wellformed_expected():
    from bench.grounded_recall import load_cases
    for c in load_cases():
        keys = c.expected
        if keys.get("none"):
            # adversarial negative: must NOT also assert positive matchers
            assert not any(keys.get(k) for k in ("domains", "url_substrings", "chapter_slugs")), \
                f"case {c.id}: adversarial negative cannot also declare positive matchers"
            continue
        assert any(keys.get(k) for k in ("domains", "url_substrings", "chapter_slugs")), \
            f"case {c.id}: expected must include at least one of domains/url_substrings/chapter_slugs (or none:true for adversarial)"


def test_fixture_has_adversarial_negatives():
    from bench.grounded_recall import load_cases
    cases = load_cases()
    adv = [c for c in cases if c.expected.get("none")]
    # ~10% adversarial negatives
    assert len(adv) >= max(8, int(0.08 * len(cases))), \
        f"expected ~10% adversarial negatives, got {len(adv)}/{len(cases)}"


def test_score_rewards_correct_no_match():
    from bench.grounded_recall import BenchCase, _score_case
    case = BenchCase(id="adv", query="q", context={}, expected={"none": True})
    # Empty citations → correct.
    r_empty = _score_case(case, [], 1)
    assert r_empty.matched is True
    assert r_empty.is_adversarial is True
    assert r_empty.allow_weak == 0
    assert r_empty.recall_at(1) is True
    # Non-empty citations → incorrect (default allow_weak=0).
    r_full = _score_case(case, [{"url": "https://en.wikipedia.org/x", "domain": "en.wikipedia.org"}], 1)
    assert r_full.matched is False
    assert r_full.recall_at(5) is False


def test_score_honours_allow_weak_floor():
    """Adversarial cases can soft-tolerate up to N weak citations."""
    from bench.grounded_recall import BenchCase, _score_case
    case = BenchCase(
        id="adv-soft",
        query="q",
        context={},
        expected={"none": True, "allow_weak": 1},
    )
    cit = {"url": "https://en.wikipedia.org/x", "domain": "en.wikipedia.org"}
    # Zero citations → still correct.
    assert _score_case(case, [], 1).matched is True
    # One leaked citation → tolerated.
    r1 = _score_case(case, [cit], 1)
    assert r1.matched is True
    assert r1.allow_weak == 1
    assert r1.citations_count == 1
    # Two leaked citations → exceeds the floor, fails.
    r2 = _score_case(case, [cit, cit], 1)
    assert r2.matched is False
    # Garbage / negative values fall back to 0.
    bad = BenchCase(id="adv-bad", query="q", context={}, expected={"none": True, "allow_weak": "lots"})
    assert _score_case(bad, [cit], 1).matched is False
    neg = BenchCase(id="adv-neg", query="q", context={}, expected={"none": True, "allow_weak": -3})
    assert _score_case(neg, [cit], 1).matched is False


def test_run_emits_adversarial_quality_metrics():
    """Aggregator surfaces the strict & mean-leak adversarial signals."""
    report = _run()
    m = report["metrics"]
    assert "adversarial_no_match_rate" in m
    assert "adversarial_clean_rate" in m
    assert "adversarial_mean_citations" in m
    # clean_rate must be <= no_match_rate (clean is the stricter version).
    assert m["adversarial_clean_rate"] <= m["adversarial_no_match_rate"]
    # mean leak must be non-negative.
    assert m["adversarial_mean_citations"] >= 0


def test_fixture_allow_weak_values_are_sane():
    """Any case that opts into a quality floor must pick a non-negative int
    and must also be flagged adversarial — the floor only applies there."""
    from bench.grounded_recall import load_cases
    for c in load_cases():
        if "allow_weak" not in (c.expected or {}):
            continue
        v = c.expected["allow_weak"]
        assert isinstance(v, int) and v >= 0, \
            f"case {c.id}: allow_weak must be a non-negative int, got {v!r}"
        assert c.expected.get("none"), \
            f"case {c.id}: allow_weak only applies to adversarial cases (none:true)"


def test_recall_matches_baseline_within_tolerance():
    from bench.grounded_recall import load_baseline
    baseline = load_baseline()
    assert baseline is not None, "baseline.json missing — regenerate it"
    report = _run()
    for metric, expected in baseline["metrics"].items():
        actual = report["metrics"].get(metric)
        assert actual is not None, f"missing metric {metric}"
        assert actual >= expected - TOLERANCE, (
            f"{metric} regressed: {actual:.4f} < baseline {expected:.4f} (tolerance {TOLERANCE})"
        )


def test_citation_matching_handles_subdomain_and_substring():
    from bench.grounded_recall import citation_matches_expected
    assert citation_matches_expected(
        {"url": "https://en.wikipedia.org/wiki/Foo", "domain": "en.wikipedia.org"},
        {"domains": ["wikipedia.org"]},
    )
    assert not citation_matches_expected(
        {"url": "https://evilwikipedia.org/x", "domain": "evilwikipedia.org"},
        {"domains": ["wikipedia.org"]},
    )
    assert citation_matches_expected(
        {"url": "https://math.iitb.ac.in/notes.pdf", "domain": "math.iitb.ac.in"},
        {"url_substrings": [".ac.in"]},
    )
    assert citation_matches_expected(
        {"url": "/learn/trig", "domain": "syrabit.ai", "anchor": "trigonometric-identities"},
        {"chapter_slugs": ["trigonometric-identities"]},
    )
    assert not citation_matches_expected(
        {"url": "/learn/trig", "domain": "syrabit.ai", "anchor": "trigonometric-identities"},
        {"chapter_slugs": ["some-other-slug"]},
    )
