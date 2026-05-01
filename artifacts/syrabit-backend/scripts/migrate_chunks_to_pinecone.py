"""
migrate_chunks_to_pinecone.py — One-shot migration of MongoDB chunks to Pinecone.

Reads all chunks that have a non-null `embedding` field from the MongoDB
`chunks` collection, batches them in groups of 100, and upserts to the
Pinecone `syrabit-ahsec` index.

Prerequisites
-------------
1. Set env vars: MONGO_URL, PINECONE_KEY (or PINECONE_API_KEY), PINECONE_INDEX
2. Run `embed_chunks_bulk` first to ensure all chunks have embeddings.
3. The Pinecone index must exist (call ensure_pinecone_index() or run with
   --ensure-index).

Usage
-----
    # Dry run (no writes to Pinecone)
    python scripts/migrate_chunks_to_pinecone.py --dry-run

    # Real migration (all embedded chunks)
    python scripts/migrate_chunks_to_pinecone.py

    # Scope to a single subject
    python scripts/migrate_chunks_to_pinecone.py --subject-id sub_physics_ahsec12

    # Limit to first N chunks (for smoke testing)
    python scripts/migrate_chunks_to_pinecone.py --limit 200 --dry-run

    # Force re-upsert even if already in Pinecone (default: upsert all)
    python scripts/migrate_chunks_to_pinecone.py --batch-size 50

Exit codes
----------
    0 — success (even partial — check logs for per-batch failures)
    1 — fatal error (cannot connect to MongoDB or Pinecone)
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
logger = logging.getLogger("migrate_chunks_to_pinecone")

_BATCH_SIZE = 100


async def _get_mongo_db():
    """Connect to MongoDB and return the database instance."""
    mongo_url = os.environ.get("MONGO_URL", "").strip()
    if not mongo_url:
        raise RuntimeError("MONGO_URL env var is required")
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=8000)
        await client.admin.command("ping")
        db_name = (mongo_url.rstrip("/").split("/")[-1].split("?")[0]) or "syrabit"
        return client[db_name]
    except Exception as exc:
        raise RuntimeError(f"MongoDB connection failed: {exc}") from exc


async def migrate(
    *,
    dry_run: bool = False,
    batch_size: int = _BATCH_SIZE,
    subject_id: Optional[str] = None,
    limit: Optional[int] = None,
    ensure_index: bool = False,
) -> dict:
    t0 = time.perf_counter()

    # ── Connect to MongoDB ──────────────────────────────────────────────────
    logger.info("Connecting to MongoDB …")
    try:
        db = await _get_mongo_db()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    # ── Ensure Pinecone index exists ────────────────────────────────────────
    if ensure_index:
        logger.info("Ensuring Pinecone index …")
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from retrievers.pinecone_vector import ensure_pinecone_index
            result = await ensure_pinecone_index()
            logger.info("Pinecone index: %s", result)
            if not result.get("ok"):
                logger.error("Could not ensure Pinecone index: %s", result)
                sys.exit(1)
        except Exception as exc:
            logger.error("ensure_pinecone_index failed: %s", exc)
            sys.exit(1)

    # ── Load PineconeVectorRetriever ─────────────────────────────────────────
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from retrievers.pinecone_vector import PineconeVectorRetriever
        retriever = PineconeVectorRetriever()
        if not retriever.is_configured():
            logger.error(
                "PINECONE_KEY (or PINECONE_API_KEY) is not set — cannot proceed"
            )
            sys.exit(1)
    except Exception as exc:
        logger.error("Failed to load PineconeVectorRetriever: %s", exc)
        sys.exit(1)

    # ── Query MongoDB for chunks with embeddings ──────────────────────────────
    query: dict = {"embedding": {"$exists": True, "$ne": None}}
    if subject_id:
        query["subject_id"] = subject_id
        logger.info("Scoped to subject_id=%s", subject_id)

    projection = {
        "_id": 1,
        "chapter_id": 1,
        "subject_id": 1,
        "chapter_title": 1,
        "topic_name": 1,
        "embedding": 1,
        "embedding_model": 1,
    }

    cursor = db.chunks.find(query, projection)
    if limit:
        cursor = cursor.limit(limit)
        logger.info("Limiting to first %d chunks", limit)

    logger.info("Fetching chunks from MongoDB …")
    chunks = await cursor.to_list(length=limit or 100_000)
    total = len(chunks)
    logger.info("Found %d chunks with embeddings", total)

    if total == 0:
        logger.warning("No embedded chunks found — run embed_chunks_bulk first")
        return {"total": 0, "upserted": 0, "failed": 0, "duration_s": 0}

    # ── Batch upsert to Pinecone ─────────────────────────────────────────────
    upserted = 0
    failed = 0
    batch_num = 0

    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        batch_num += 1

        vectors = []
        for ch in batch:
            emb = ch.get("embedding")
            if not emb or not isinstance(emb, list):
                logger.warning("Chunk %s has invalid embedding — skipping", ch.get("_id"))
                failed += 1
                continue
            vectors.append({
                "id": str(ch["_id"]),
                "values": emb,
                "metadata": {
                    "chapter_id":      ch.get("chapter_id", ""),
                    "subject_id":      ch.get("subject_id", ""),
                    "chapter_title":   ch.get("chapter_title", ""),
                    "topic_name":      ch.get("topic_name", ""),
                    "embedding_model": ch.get("embedding_model", "embed-multilingual-v3.0"),
                },
            })

        if not vectors:
            continue

        logger.info(
            "Batch %d/%d — upserting %d vectors [%d/%d] …",
            batch_num, -(-total // batch_size), len(vectors), i + len(batch), total,
        )

        if dry_run:
            logger.info("  [DRY RUN] Would upsert %d vectors — skipping", len(vectors))
            upserted += len(vectors)
            continue

        try:
            result = await retriever.upsert(vectors)
            n = result.get("upserted", 0)
            errs = result.get("errors", [])
            upserted += n
            if errs:
                logger.warning("  Batch %d partial failure: %s", batch_num, errs)
                failed += len(vectors) - n
            else:
                logger.info("  Batch %d OK — upserted %d", batch_num, n)
        except Exception as exc:
            logger.error("  Batch %d FAILED: %s", batch_num, exc)
            failed += len(vectors)

        # Brief throttle to stay under Pinecone rate limits
        await asyncio.sleep(0.2)

    duration = round(time.perf_counter() - t0, 2)
    summary = {
        "total":      total,
        "upserted":   upserted,
        "failed":     failed,
        "duration_s": duration,
        "dry_run":    dry_run,
    }
    logger.info("Migration complete: %s", summary)

    if failed > 0:
        logger.warning("%d chunks failed to upsert — check logs above", failed)
    else:
        logger.info("All chunks migrated successfully")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate MongoDB chunk embeddings to Pinecone syrabit-ahsec index"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print progress without writing to Pinecone",
    )
    parser.add_argument(
        "--batch-size", type=int, default=_BATCH_SIZE,
        help=f"Vectors per Pinecone upsert request (default: {_BATCH_SIZE})",
    )
    parser.add_argument(
        "--subject-id", type=str, default=None,
        help="Scope migration to a single subject_id",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max total chunks to process (for smoke tests)",
    )
    parser.add_argument(
        "--ensure-index", action="store_true",
        help="Create the Pinecone index if it doesn't exist before migrating",
    )
    args = parser.parse_args()

    asyncio.run(migrate(
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        subject_id=args.subject_id,
        limit=args.limit,
        ensure_index=args.ensure_index,
    ))


if __name__ == "__main__":
    main()
