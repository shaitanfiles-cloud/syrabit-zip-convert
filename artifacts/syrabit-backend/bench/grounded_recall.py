"""Recall benchmark for the grounded-answer pipeline.

Given a hand-labelled fixture of (query, expected-source) pairs, this
module computes recall@K over the citation list that the pipeline would
surface, so retrieval regressions can be caught before students notice.

Two retrievers are supported:

* ``offline`` — feeds each case's embedded ``offline_corpus`` (web
  results, internal chapters, page context) directly into
  ``grounded_answer._build_citations``. Deterministic, hermetic, runs
  in CI with zero network.

* ``live`` — calls the real ``rag.web_search_with_fallback`` and, if a
  subject id is provided, ``rag._fetch_internal_chapters``. Useful for
  nightly monitoring against production indices.

Usage (CLI)::

    python -m bench.grounded_recall                 # offline, pretty JSON
    python -m bench.grounded_recall --live          # hit real retrievers
    python -m bench.grounded_recall --save-results  # archive to results/
    python -m bench.grounded_recall --compare baseline  # gate vs baseline

A tiny admin GET at /api/admin/grounded-recall/latest reads the newest
JSON file under results/ so the metric is observable in the admin UI.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_BENCH_DIR = Path(__file__).resolve().parent
FIXTURE_PATH = _BENCH_DIR / "fixtures" / "grounded_recall.json"
BASELINE_PATH = _BENCH_DIR / "fixtures" / "baseline.json"
RESULTS_DIR = _BENCH_DIR / "results"

K_VALUES = (1, 3, 5)


# ───────────────────────── Data types ─────────────────────────

@dataclass
class BenchCase:
    id: str
    query: str
    context: dict
    expected: dict
    offline_corpus: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "BenchCase":
        return cls(
            id=d["id"],
            query=d["query"],
            context=d.get("context", {}),
            expected=d.get("expected", {}),
            offline_corpus=d.get("offline_corpus", {}),
        )


@dataclass
class CaseResult:
    id: str
    query: str
    citations_count: int
    first_match_rank: Optional[int]  # 1-indexed; None = no match in any citation
    matched: bool
    elapsed_ms: int

    def recall_at(self, k: int) -> bool:
        return self.first_match_rank is not None and self.first_match_rank <= k


@dataclass
class BenchReport:
    started_at: str
    retriever: str
    total_cases: int
    metrics: dict  # {"recall@1": 0.82, "recall@3": ..., "recall@5": ..., ...}
    per_case: list[dict]
    mean_citation_count: float
    mean_latency_ms: float

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "retriever": self.retriever,
            "total_cases": self.total_cases,
            "metrics": self.metrics,
            "mean_citation_count": self.mean_citation_count,
            "mean_latency_ms": self.mean_latency_ms,
            "per_case": self.per_case,
        }


# ───────────────────────── Matching ─────────────────────────

def _domain_of(url: str) -> str:
    try:
        d = (urlparse(url).hostname or "").lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def citation_matches_expected(citation: dict, expected: dict) -> bool:
    """Return True if the citation satisfies *any* of the expected patterns."""
    cit_url = (citation.get("url") or "").lower()
    cit_domain = (citation.get("domain") or _domain_of(citation.get("url", ""))).lower()
    cit_anchor = (citation.get("anchor") or "").lower()

    # Domain match: exact or subdomain of expected.
    for d in expected.get("domains", []) or []:
        d = d.lower().lstrip(".")
        if cit_domain == d or cit_domain.endswith("." + d):
            return True

    # URL substring.
    for s in expected.get("url_substrings", []) or []:
        if s and s.lower() in cit_url:
            return True

    # Chapter slug (internal retrieval).
    for slug in expected.get("chapter_slugs", []) or []:
        if slug and slug.lower() == cit_anchor:
            return True

    return False


# ───────────────────────── Retrievers ─────────────────────────

def _build_offline_citations(case: BenchCase) -> list[dict]:
    """Feed the case's offline corpus through the real citation builder."""
    # Imported here so the module can be imported without the full backend
    # dependency graph (e.g. from CI that doesn't install every extra).
    from grounded_answer import _build_citations  # type: ignore

    corpus = case.offline_corpus or {}
    page_ctx = corpus.get("page_context") or None
    internal = corpus.get("internal_chapters") or []
    web = corpus.get("web_results") or []
    return _build_citations(web, internal, page_ctx)


async def _build_live_citations(case: BenchCase) -> list[dict]:
    """Hit the real retrievers and build citations from what comes back."""
    from grounded_answer import _build_citations  # type: ignore
    from rag import web_search_with_fallback, _fetch_internal_chapters  # type: ignore
    from edu_reader import fetch_and_extract  # type: ignore
    from guardrails.web_safety import filter_web_results, score_text_kid_safety

    ctx = case.context or {}
    page_url = ctx.get("page_url", "")
    subject_id = ctx.get("subject_id", "")
    subject_name = ctx.get("subject_name", "")

    async def _maybe_page():
        if not page_url:
            return None
        try:
            return await fetch_and_extract(page_url, actor="bench", ip_hash="bench")
        except Exception:
            return None

    async def _maybe_internal():
        if not (subject_id or subject_name):
            return []
        try:
            return await _fetch_internal_chapters(
                case.query, subject_id=subject_id, subject_name=subject_name
            )
        except Exception:
            return []

    async def _maybe_web():
        try:
            return await web_search_with_fallback(
                case.query,
                board_name=ctx.get("board_name", ""),
                class_name=ctx.get("class_name", ""),
                subject_name=subject_name,
                chapter_name=ctx.get("chapter_name", ""),
            )
        except Exception:
            return []

    page_ctx, internal, web_raw = await asyncio.gather(
        _maybe_page(), _maybe_internal(), _maybe_web()
    )

    web_kept, _ = filter_web_results(web_raw or [])
    page_payload = None
    if page_ctx and page_ctx.get("ok"):
        safe, _, _ = score_text_kid_safety(page_ctx.get("text", ""))
        if safe:
            page_payload = page_ctx
    return _build_citations(web_kept, internal, page_payload)


# ───────────────────────── Runner ─────────────────────────

def _score_case(case: BenchCase, citations: list[dict], elapsed_ms: int) -> CaseResult:
    first_match = None
    for i, cit in enumerate(citations, start=1):
        if citation_matches_expected(cit, case.expected):
            first_match = i
            break
    return CaseResult(
        id=case.id,
        query=case.query,
        citations_count=len(citations),
        first_match_rank=first_match,
        matched=first_match is not None,
        elapsed_ms=elapsed_ms,
    )


async def run_benchmark(
    cases: list[BenchCase],
    *,
    retriever: str = "offline",
) -> BenchReport:
    """Run every case and return an aggregate report."""
    results: list[CaseResult] = []
    for case in cases:
        t0 = time.perf_counter()
        try:
            if retriever == "offline":
                citations = _build_offline_citations(case)
            elif retriever == "live":
                citations = await _build_live_citations(case)
            else:
                raise ValueError(f"unknown retriever {retriever!r}")
        except Exception as e:
            logger.warning(f"[bench] case {case.id!r} failed: {e}")
            citations = []
        elapsed = int((time.perf_counter() - t0) * 1000)
        results.append(_score_case(case, citations, elapsed))

    total = len(results) or 1
    metrics: dict[str, float] = {}
    for k in K_VALUES:
        hits = sum(1 for r in results if r.recall_at(k))
        metrics[f"recall@{k}"] = round(hits / total, 4)
    metrics["match_rate"] = round(sum(1 for r in results if r.matched) / total, 4)

    mean_cc = round(sum(r.citations_count for r in results) / total, 2)
    mean_lat = round(sum(r.elapsed_ms for r in results) / total, 2)

    return BenchReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        retriever=retriever,
        total_cases=total,
        metrics=metrics,
        per_case=[
            {
                "id": r.id,
                "query": r.query,
                "citations_count": r.citations_count,
                "first_match_rank": r.first_match_rank,
                "matched": r.matched,
                "elapsed_ms": r.elapsed_ms,
            }
            for r in results
        ],
        mean_citation_count=mean_cc,
        mean_latency_ms=mean_lat,
    )


# ───────────────────────── Fixture / baseline I/O ─────────────────────────

def load_cases(path: Path = FIXTURE_PATH) -> list[BenchCase]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [BenchCase.from_dict(c) for c in data["cases"]]


def load_baseline(path: Path = BASELINE_PATH) -> Optional[dict]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_report(report: BenchReport, results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = results_dir / f"grounded_recall-{report.retriever}-{ts}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    # also update "latest.json" for easy admin read
    latest = results_dir / "latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    return filename


def find_latest_result(results_dir: Path = RESULTS_DIR) -> Optional[dict]:
    latest = results_dir / "latest.json"
    if latest.exists():
        with open(latest, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# ───────────────────────── CLI ─────────────────────────

def _format_report(report: BenchReport, baseline: Optional[dict]) -> str:
    lines = [
        f"Grounded-answer recall benchmark — retriever={report.retriever}",
        f"  cases: {report.total_cases}",
        f"  mean citations per case: {report.mean_citation_count}",
        f"  mean latency: {report.mean_latency_ms} ms",
        "  metrics:",
    ]
    for k, v in report.metrics.items():
        line = f"    {k:12s}  {v:.4f}"
        if baseline and "metrics" in baseline and k in baseline["metrics"]:
            delta = v - baseline["metrics"][k]
            sign = "+" if delta >= 0 else ""
            line += f"   ({sign}{delta:+.4f} vs baseline {baseline['metrics'][k]:.4f})"
        lines.append(line)
    misses = [c for c in report.per_case if not c["matched"]]
    if misses:
        lines.append(f"  misses ({len(misses)}):")
        for m in misses[:10]:
            lines.append(f"    - {m['id']}: {m['query'][:60]}")
        if len(misses) > 10:
            lines.append(f"    … and {len(misses) - 10} more")
    return "\n".join(lines)


def _main_cli() -> int:
    _BACKEND = _BENCH_DIR.parent
    if str(_BACKEND) not in sys.path:
        sys.path.insert(0, str(_BACKEND))

    parser = argparse.ArgumentParser(description="Grounded-answer recall benchmark")
    parser.add_argument("--live", action="store_true", help="Use live retrievers instead of the offline corpus")
    parser.add_argument("--fixture", default=str(FIXTURE_PATH))
    parser.add_argument("--save-results", action="store_true", help="Archive results to bench/results/")
    parser.add_argument("--compare-baseline", action="store_true", help="Compare against bench/fixtures/baseline.json")
    parser.add_argument("--gate", type=float, default=None, help="Exit non-zero if recall@5 drops below baseline by more than GATE")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    args = parser.parse_args()

    cases = load_cases(Path(args.fixture))
    retriever = "live" if args.live else "offline"
    report = asyncio.run(run_benchmark(cases, retriever=retriever))

    baseline = load_baseline() if args.compare_baseline or args.gate is not None else None

    if args.save_results:
        saved = save_report(report)
        print(f"Saved results → {saved}", file=sys.stderr)

    if args.json:
        json.dump(report.to_dict(), sys.stdout, indent=2)
        print()
    else:
        print(_format_report(report, baseline))

    # Structured log line (nightly job can grep this)
    logger.info(
        "[bench.grounded_recall] metrics=%s retriever=%s cases=%d mean_latency_ms=%.1f",
        json.dumps(report.metrics), report.retriever, report.total_cases, report.mean_latency_ms,
    )

    if args.gate is not None and baseline:
        b5 = baseline.get("metrics", {}).get("recall@5")
        if b5 is not None:
            drop = b5 - report.metrics["recall@5"]
            if drop > args.gate:
                print(
                    f"GATE FAILED: recall@5 dropped {drop:.4f} (> {args.gate}). "
                    f"current={report.metrics['recall@5']:.4f} baseline={b5:.4f}",
                    file=sys.stderr,
                )
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main_cli())


__all__ = [
    "BenchCase", "CaseResult", "BenchReport",
    "load_cases", "load_baseline", "save_report", "find_latest_result",
    "citation_matches_expected", "run_benchmark",
    "FIXTURE_PATH", "BASELINE_PATH", "RESULTS_DIR", "K_VALUES",
]
