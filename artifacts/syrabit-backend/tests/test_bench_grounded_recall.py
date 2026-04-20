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
    return asyncio.get_event_loop().run_until_complete(
        run_benchmark(cases, retriever="offline")
    ).to_dict()


def test_fixture_has_enough_cases():
    from bench.grounded_recall import load_cases
    cases = load_cases()
    assert len(cases) >= 50, f"expected at least 50 labelled cases, got {len(cases)}"


def test_every_case_has_wellformed_expected():
    from bench.grounded_recall import load_cases
    for c in load_cases():
        keys = c.expected
        assert any(keys.get(k) for k in ("domains", "url_substrings", "chapter_slugs")), \
            f"case {c.id}: expected must include at least one of domains/url_substrings/chapter_slugs"


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
