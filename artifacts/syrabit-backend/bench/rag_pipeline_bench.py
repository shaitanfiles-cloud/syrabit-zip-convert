"""
rag_pipeline_bench.py — Direct RAG pipeline speed benchmark.

Tests every stage of the RAG stack:
  Stage 1 — Workers AI embedding latency (@cf/baai/bge-large-en-v1.5, 1024-dim)
  Stage 2 — MongoDB vector search (ANN nearest-neighbour)
  Stage 3 — Workers AI reranking (@cf/baai/bge-reranker-base)
  Stage 4 — Full _fetch_internal_chapters() (keyword → CF rerank) across 10 AHSEC questions

Usage:
    cd artifacts/syrabit-backend
    python -m bench.rag_pipeline_bench
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

QUERIES = [
    ("What is photosynthesis?",                        "Biology"),
    ("Explain Newton's third law of motion",            "Physics"),
    ("What causes acid rain?",                          "Chemistry"),
    ("Describe the structure of DNA",                   "Biology"),
    ("What is the significance of the 1857 revolt?",   "History"),
    ("Explain the Indian independence movement",        "History"),
    ("What is an ecosystem?",                           "Biology"),
    ("Define the law of conservation of energy",        "Physics"),
    ("What are the causes of World War 1?",             "History"),
    ("Explain ionic bonding with examples",             "Chemistry"),
]

C = {
    "g": "\033[92m", "y": "\033[93m", "r": "\033[91m",
    "c": "\033[96m", "b": "\033[1m",  "x": "\033[0m",
}


def fg(text, col): return f"{C[col]}{text}{C['x']}"
def bold(t):        return fg(t, "b")
def sep(char="─", n=64): return bold(char * n)


async def stage1_embed() -> dict:
    """Measure single-query embedding latency via Workers AI bge-large-en-v1.5."""
    from providers.cloudflare_ai import embed, _ENABLED
    print(f"\n{sep()}")
    print(bold("  Stage 1 — Workers AI Embedding (@cf/baai/bge-large-en-v1.5)"))
    print(sep())

    if not _ENABLED:
        print(fg("  SKIP — Cloudflare AI not configured (missing CLOUDFLARE_API_TOKEN)", "r"))
        return {"enabled": False}

    warmup_t = time.perf_counter()
    try:
        await embed(["warmup"])
        warmup_ms = round((time.perf_counter() - warmup_t) * 1000)
        print(f"  Warm-up (first call):  {fg(str(warmup_ms)+'ms', 'c')}")
    except Exception as e:
        warmup_ms = round((time.perf_counter() - warmup_t) * 1000)
        print(f"  Warm-up (first call):  {fg('rate-limited / error — '+str(e)[:60], 'y')}")

    times = []
    for q, subj in QUERIES[:5]:
        await asyncio.sleep(0.3)
        t0 = time.perf_counter()
        try:
            vecs = await embed([q])
        except Exception as e:
            print(f"  [{subj:10s}] {q[:45]:<45}  {fg('rate-limited: '+str(e)[:50], 'y')}")
            continue
        ms = round((time.perf_counter() - t0) * 1000)
        if not vecs or not vecs[0]:
            print(f"  [{subj:10s}] {q[:45]:<45}  {fg('no vector returned', 'y')}")
            continue
        times.append(ms)
        dims = len(vecs[0])
        print(f"  [{subj:10s}] {q[:45]:<45}  {fg(str(ms)+'ms', 'c')}  {dims}d")

    if not times:
        print(fg("  No successful embed calls", "r"))
        return {"enabled": True, "p50_ms": 0}
    p50 = round(statistics.median(times))
    p95 = round(sorted(times)[int(len(times) * 0.95)] if len(times) > 1 else times[0])
    print(f"\n  p50={fg(str(p50)+'ms','c')}  p95={fg(str(p95)+'ms','c')}  mean={fg(str(round(statistics.mean(times)))+'ms','c')}")
    return {"enabled": True, "p50_ms": p50, "p95_ms": p95, "warmup_ms": warmup_ms}


async def stage2_mongo_vector_search() -> dict:
    """Measure raw MongoDB vector-search latency using Workers AI query embedding."""
    print(f"\n{sep()}")
    print(bold("  Stage 2 — MongoDB Vector Search (ANN, query via Workers AI)"))
    print(sep())

    try:
        from deps import db as mongo_db, is_mongo_available
        from providers.cloudflare_ai import embed as cf_embed, _ENABLED

        if not _ENABLED:
            print(fg("  SKIP — Cloudflare AI not configured", "r"))
            return {"enabled": False}
        if not await is_mongo_available():
            print(fg("  SKIP — MongoDB not reachable", "r"))
            return {}

        times = []
        hits = []
        for q, subj in QUERIES[:5]:
            t0 = time.perf_counter()
            try:
                vecs = await cf_embed([q])
                vec = vecs[0] if vecs else None
            except Exception as e:
                print(f"  [{subj:10s}] {q[:40]:<40}  {fg('embed error: '+str(e)[:40], 'r')}")
                continue
            embed_ms = round((time.perf_counter() - t0) * 1000)
            if not vec:
                print(f"  [{subj:10s}] {q[:40]:<40}  {fg('no vector', 'y')}")
                continue

            t1 = time.perf_counter()
            pipeline = [
                {"$vectorSearch": {
                    "index": "chunk_embedding_index",
                    "path": "embedding",
                    "queryVector": vec,
                    "numCandidates": 50,
                    "limit": 8,
                }},
                {"$project": {"_id": 1, "text": 1, "chapter_id": 1, "score": {"$meta": "vectorSearchScore"}}},
            ]
            try:
                cursor = mongo_db.chapter_chunks.aggregate(pipeline)
                docs = await cursor.to_list(length=8)
                search_ms = round((time.perf_counter() - t1) * 1000)
                total_ms = embed_ms + search_ms
                times.append(total_ms)
                hits.append(len(docs))
                score = f"{docs[0]['score']:.3f}" if docs else "—"
                print(f"  [{subj:10s}] {q[:40]:<40}  embed={fg(str(embed_ms)+'ms','c')}  search={fg(str(search_ms)+'ms','c')}  hits={fg(str(len(docs)),'g')}  top_score={score}")
            except Exception as e:
                print(f"  [{subj:10s}] {q[:40]:<40}  {fg('SEARCH ERROR: '+str(e)[:60], 'r')}")
                times.append(embed_ms)
                hits.append(0)

        if times:
            p50 = round(statistics.median(times))
            avg_hits = round(statistics.mean(hits), 1)
            print(f"\n  p50 total (embed+search)={fg(str(p50)+'ms','c')}  avg hits={fg(str(avg_hits),'g')}")
            return {"p50_ms": p50, "avg_hits": avg_hits}
    except Exception as e:
        print(fg(f"  ERROR: {e}", "r"))
    return {}


async def stage3_rerank() -> dict:
    """Measure Workers AI reranking speed (bge-reranker-base)."""
    print(f"\n{sep()}")
    print(bold("  Stage 3 — Workers AI Reranking (@cf/baai/bge-reranker-base)"))
    print(sep())

    try:
        from providers.cloudflare_ai import rerank as cf_rerank, _ENABLED

        if not _ENABLED:
            print(fg("  SKIP — Cloudflare AI not configured", "r"))
            return {"enabled": False}

        dummy_docs = [
            "Photosynthesis is the process by which green plants convert sunlight into food.",
            "Plants absorb carbon dioxide and release oxygen during photosynthesis.",
            "The light-dependent reactions occur in the thylakoid membranes.",
            "Chlorophyll absorbs light primarily in the red and blue wavelengths.",
            "The Calvin cycle is the light-independent stage of photosynthesis.",
        ]
        q = "What is photosynthesis?"

        times = []
        for run in range(3):
            t0 = time.perf_counter()
            try:
                scores = await cf_rerank(q, dummy_docs)
                ms = round((time.perf_counter() - t0) * 1000)
                if scores:
                    times.append(ms)
                    top_score = max(scores)
                    print(f"  Run {run+1}: {fg(str(ms)+'ms', 'c')}  top_score={top_score:.4f}")
                else:
                    print(f"  Run {run+1}: {fg('no scores returned', 'y')}")
            except Exception as e:
                ms = round((time.perf_counter() - t0) * 1000)
                print(f"  Run {run+1}: {fg('ERROR: '+str(e)[:60], 'r')}")

        if not times:
            print(fg("  No successful rerank calls", "r"))
            return {}
        p50 = round(statistics.median(times))
        print(f"\n  p50={fg(str(p50)+'ms','c')}  (5 docs scored by bge-reranker-base)")
        return {"p50_ms": p50}
    except Exception as e:
        print(fg(f"  ERROR: {e}", "r"))
    return {}


async def stage4_full_rag() -> dict:
    """Full RAG pipeline: _fetch_internal_chapters (keyword→rerank) + resolve_rag_context."""
    print(f"\n{sep()}")
    print(bold("  Stage 4 — Full RAG Pipeline (10 AHSEC/SEBA questions)"))
    print(bold("  Flow: keywords → MongoDB match → CF bge-reranker → context"))
    print(sep())

    try:
        from rag import _fetch_internal_chapters, resolve_rag_context
        from deps import is_mongo_available

        if not await is_mongo_available():
            print(fg("  SKIP — MongoDB not reachable", "r"))
            return {}

        times = []
        results = []
        for q, subj in QUERIES:
            t0 = time.perf_counter()
            try:
                # Step 1: fetch + rerank internal chapters (the slow part)
                chapters = await asyncio.wait_for(
                    _fetch_internal_chapters(q, subject_name=subj),
                    timeout=15.0,
                )
                # Step 2: resolve full RAG context dict
                ctx = await resolve_rag_context(
                    q,
                    subject_name=subj,
                    prefetched_chapters=chapters,
                    intent="notes",
                )
            except asyncio.TimeoutError:
                ms = round((time.perf_counter() - t0) * 1000)
                print(f"  [{subj:10s}] {q[:42]:<42}  {fg('TIMEOUT >15s', 'r')}")
                times.append(ms); results.append({"ok": False}); continue
            except Exception as e:
                ms = round((time.perf_counter() - t0) * 1000)
                print(f"  [{subj:10s}] {q[:42]:<42}  {fg('ERR: '+str(e)[:50], 'r')}")
                times.append(ms); results.append({"ok": False}); continue

            ms = round((time.perf_counter() - t0) * 1000)
            times.append(ms)

            source  = ctx.get("source", "none")
            chunks  = len(ctx.get("chunks") or [])
            quality = ctx.get("quality", "?")

            if source in ("internal", "document"):
                src_str = fg(f"✓ internal", "g")
            elif source == "web":
                src_str = fg(f"~ web     ", "y")
            else:
                src_str = fg(f"✗ no-rag  ", "r")

            print(f"  [{subj:10s}] {q[:40]:<40}  {fg(str(ms)+'ms','c'):>8}  {src_str}  {chunks} chunks  q={quality}")
            results.append({"ok": True, "source": source, "ms": ms, "chunks": chunks})

        ok = [r for r in results if r.get("ok")]
        if ok and times:
            good_times = [r["ms"] for r in ok]
            p50  = round(statistics.median(good_times))
            p95  = round(sorted(good_times)[int(len(good_times) * 0.95)] if len(good_times) > 1 else good_times[0])
            mean = round(statistics.mean(good_times))
            internal_hits = sum(1 for r in ok if r.get("source") in ("internal", "document"))
            no_rag        = sum(1 for r in ok if r.get("source") in ("none", ""))
            avg_ch        = round(statistics.mean(r.get("chunks", 0) for r in ok), 1)

            print(f"\n  Speed    p50={fg(str(p50)+'ms','c')}  p95={fg(str(p95)+'ms','c')}  mean={fg(str(mean)+'ms','c')}")
            print(f"  Internal RAG hits : {fg(str(internal_hits),'g')} / {len(results)}")
            print(f"  No-RAG fallbacks  : {fg(str(no_rag),'r')} / {len(results)}")
            print(f"  Avg chunks/query  : {fg(str(avg_ch),'c')}")

            rag_pct = round(internal_hits / len(results) * 100)
            grade = (
                fg("A — Excellent", "g") if rag_pct >= 80
                else fg("B — Good",      "g") if rag_pct >= 60
                else fg("C — Fair",      "y") if rag_pct >= 40
                else fg("D — Needs work","r")
            )
            print(f"  RAG coverage : {rag_pct}%  →  {grade}")
            return {"p50_ms": p50, "p95_ms": p95, "internal_hits": internal_hits, "rag_pct": rag_pct}
    except Exception as e:
        import traceback
        print(fg(f"  FATAL: {e}", "r"))
        traceback.print_exc()
    return {}


async def main():
    print(bold("\n" + "═" * 64))
    print(bold("  Syrabit.ai — Full RAG Stack Speed Benchmark"))
    print(bold("  Tests: embed → vector-search → rerank → _fetch_internal_chapters"))
    print(bold("═" * 64))

    r1 = await stage1_embed()
    r3 = await stage3_rerank()
    r4 = await stage4_full_rag()

    # Final scorecard
    print(f"\n{sep('═')}")
    print(bold("  FINAL SCORECARD"))
    print(sep("═"))

    if r1.get("enabled"):
        print(f"  Embed latency p50  : {fg(str(r1.get('p50_ms','?'))+'ms', 'c')}")
        print(f"  Embed latency p95  : {fg(str(r1.get('p95_ms','?'))+'ms', 'c')}")

    if r3.get("p50_ms"):
        print(f"  Rerank latency p50 : {fg(str(r3.get('p50_ms','?'))+'ms', 'c')}")

    if r4.get("p50_ms"):
        print(f"  Full RAG p50       : {fg(str(r4.get('p50_ms','?'))+'ms', 'c')}")
        print(f"  Full RAG p95       : {fg(str(r4.get('p95_ms','?'))+'ms', 'c')}")
        print(f"  RAG coverage       : {fg(str(r4.get('rag_pct','?'))+'%', 'g' if r4.get('rag_pct',0)>=60 else 'y')}")

    print(sep("═") + "\n")


if __name__ == "__main__":
    asyncio.run(main())
