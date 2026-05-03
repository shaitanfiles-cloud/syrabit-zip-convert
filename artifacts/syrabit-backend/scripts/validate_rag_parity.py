"""
validate_rag_parity.py — Compare Atlas $vectorSearch vs Pinecone top-K chapter IDs.

Run this after migrate_chunks_to_pinecone.py to verify retrieval parity before
setting PINECONE_ATLAS_FALLBACK=false.  Requires live MongoDB + Pinecone connections.

Usage
-----
    # Run all 5 representative AHSEC/SEBA queries
    python scripts/validate_rag_parity.py

    # Add extra queries
    python scripts/validate_rag_parity.py --queries "What is Ohm's law" "Demand supply"

Exit codes
----------
    0 — all queries achieved >= PASS_THRESHOLD % top-K overlap
    1 — one or more queries failed the overlap threshold

Expected output (parity confirmed)
-----------------------------------
    [1/5] "Faraday law of electromagnetic induction" ...
          Atlas top-3: [ch_physics_12_emf, ch_physics_12_ac, ch_physics_12_mag]
          Pinecone top-3: [ch_physics_12_emf, ch_physics_12_ac, ch_physics_12_mag]
          Overlap: 3/3 = 100.0% ✓
    ...
    PARITY VALIDATED — 5/5 queries above 70% threshold
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("validate_rag_parity")

# Five representative AHSEC/SEBA queries spanning all boards and subjects
REPRESENTATIVE_QUERIES = [
    "Faraday law of electromagnetic induction AHSEC Class 12 Physics",
    "Partnership accounting admission of a partner AHSEC Commerce",
    "Demand supply elasticity AHSEC Class 11 Economics",
    "National income GDP AHSEC 2nd Year Macroeconomics",
    "Consumer protection rights COPRA AHSEC Class 12 Business Studies",
]

TOP_K = 5
PASS_THRESHOLD = 0.70  # 70% top-K overlap = pass


async def _get_mongo_db():
    mongo_url = os.environ.get("MONGO_URL", "").strip()
    if not mongo_url:
        raise RuntimeError("MONGO_URL env var is required")
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=8000)
    await client.admin.command("ping")
    db_name = (mongo_url.rstrip("/").split("/")[-1].split("?")[0]) or "syrabit"
    return client[db_name]


async def _embed_query(query: str) -> Optional[list[float]]:
    """Embed a query using Cohere embed-multilingual-v3.0 (1024-dim)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from providers.cohere import embed_query, ENABLED
        if ENABLED:
            return await embed_query(query)
    except Exception as exc:
        logger.warning("Cohere embed failed: %s", exc)
    return None


async def _atlas_top_k(db, q_vec: list[float], top_k: int) -> list[str]:
    """Return top-K chapter_ids via Atlas $vectorSearch."""
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": q_vec,
                "numCandidates": top_k * 15,
                "limit": top_k,
            }
        },
        {"$addFields": {"_vs_score": {"$meta": "vectorSearchScore"}}},
        {"$project": {"_id": 0, "chapter_id": 1, "_vs_score": 1}},
    ]
    try:
        raw = await db.chunks.aggregate(pipeline).to_list(length=top_k)
        return [r["chapter_id"] for r in raw if r.get("chapter_id")]
    except Exception as exc:
        logger.warning("Atlas $vectorSearch failed: %s", exc)
        return []


async def _pinecone_top_k(q_vec: list[float], top_k: int) -> list[str]:
    """Return top-K chapter_ids via Pinecone."""
    from retrievers.pinecone_vector import PineconeVectorRetriever
    retriever = PineconeVectorRetriever()
    if not retriever.is_configured():
        logger.error("Pinecone not configured")
        return []
    matches = await retriever.query(q_vec, top_k=top_k, return_metadata=True)
    return [m["metadata"].get("chapter_id", "") for m in matches if m.get("metadata", {}).get("chapter_id")]


async def run_parity_check(queries: list[str], top_k: int = TOP_K) -> bool:
    logger.info("Connecting to MongoDB …")
    try:
        db = await _get_mongo_db()
    except Exception as exc:
        logger.error("MongoDB connection failed: %s", exc)
        sys.exit(1)

    passed = 0
    results = []

    for i, query in enumerate(queries, 1):
        logger.info("[%d/%d] %r", i, len(queries), query[:60])
        t0 = time.perf_counter()

        q_vec = await _embed_query(query)
        if not q_vec:
            logger.warning("  Skipping — could not embed query")
            continue

        atlas_ids, pinecone_ids = await asyncio.gather(
            _atlas_top_k(db, q_vec, top_k),
            _pinecone_top_k(q_vec, top_k),
            return_exceptions=True,
        )

        if isinstance(atlas_ids, Exception):
            logger.warning("  Atlas query failed: %s", atlas_ids)
            atlas_ids = []
        if isinstance(pinecone_ids, Exception):
            logger.warning("  Pinecone query failed: %s", pinecone_ids)
            pinecone_ids = []

        overlap = len(set(atlas_ids) & set(pinecone_ids))
        denom = max(len(atlas_ids), len(pinecone_ids), 1)
        pct = overlap / denom

        status = "✓" if pct >= PASS_THRESHOLD else "✗"
        logger.info(
            "  Atlas top-%d:   %s", top_k, atlas_ids[:top_k]
        )
        logger.info(
            "  Pinecone top-%d: %s", top_k, pinecone_ids[:top_k]
        )
        logger.info(
            "  Overlap: %d/%d = %.1f%% %s  (%.0f ms)",
            overlap, denom, pct * 100, status, (time.perf_counter() - t0) * 1000,
        )

        results.append({"query": query, "overlap_pct": pct, "passed": pct >= PASS_THRESHOLD})
        if pct >= PASS_THRESHOLD:
            passed += 1

    total = len(results)
    if total == 0:
        logger.error("No queries were evaluated — check Cohere availability")
        return False

    logger.info("")
    if passed == total:
        logger.info("PARITY VALIDATED — %d/%d queries above %.0f%% threshold", passed, total, PASS_THRESHOLD * 100)
        logger.info("Next step: set PINECONE_ATLAS_FALLBACK=false to go Pinecone-only")
    else:
        logger.warning(
            "PARITY INCOMPLETE — %d/%d queries passed. "
            "Do NOT disable Atlas fallback until all queries pass.",
            passed, total,
        )

    return passed == total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Atlas $vectorSearch vs Pinecone top-K chapter IDs for parity"
    )
    parser.add_argument(
        "--queries", nargs="+", default=None,
        help="Extra queries to test (in addition to the 5 built-in)",
    )
    parser.add_argument(
        "--top-k", type=int, default=TOP_K,
        help=f"Number of top results to compare (default: {TOP_K})",
    )
    args = parser.parse_args()

    queries = REPRESENTATIVE_QUERIES[:]
    if args.queries:
        queries.extend(args.queries)

    ok = asyncio.run(run_parity_check(queries, top_k=args.top_k))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
