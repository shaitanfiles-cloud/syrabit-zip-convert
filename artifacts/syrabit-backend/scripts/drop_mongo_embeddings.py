"""
drop_mongo_embeddings.py — Remove the `embedding` field from all MongoDB chunks
after Pinecone migration has been validated.

Each 1024-float embedding array is ~8 KB per chunk document. With Pinecone now
serving all semantic queries, the MongoDB copy is archived storage that inflates
document reads. This script removes it with cursor-streaming batches so it never
holds a large lock.

Pre-flight checklist (required before running)
----------------------------------------------
1. Pinecone parity validated:
   python scripts/validate_rag_parity.py
   → "PARITY VALIDATED — N/N queries above 70% threshold"
2. PINECONE_WRITE=true in environment (chunks now dual-write; no new embeddings
   will be lost if we drop the MongoDB copies).
3. PINECONE_ATLAS_FALLBACK should be set to "false" first (or be ready to set it
   right after), so Atlas $vectorSearch is not accidentally re-queried after drop.
4. Take a MongoDB backup / confirm Atlas continuous backup is active.

Usage
-----
    # Dry run — prints what would be unset, no writes
    python scripts/drop_mongo_embeddings.py --dry-run

    # Real run — drops embedding field, confirms counts
    python scripts/drop_mongo_embeddings.py

    # Scope to one subject (recommended: validate on a small batch first)
    python scripts/drop_mongo_embeddings.py --subject-id <subject_id> --dry-run
    python scripts/drop_mongo_embeddings.py --subject-id <subject_id>

    # Skip the PINECONE_WRITE guard (e.g. already off after cutover)
    python scripts/drop_mongo_embeddings.py --skip-guard

Exit codes
----------
    0 — success (or dry-run completed)
    1 — pre-flight check failed; no writes were made
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("drop_mongo_embeddings")

_BATCH_SIZE = 500  # updateMany per batch via cursor to avoid long-lock ops


async def _get_db():
    mongo_url = os.environ.get("MONGO_URL", "").strip()
    if not mongo_url:
        logger.error("MONGO_URL env var is required")
        sys.exit(1)
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=8000)
    await client.admin.command("ping")
    db_name = (mongo_url.rstrip("/").split("/")[-1].split("?")[0]) or "syrabit"
    logger.info("Connected to MongoDB database: %s", db_name)
    return client[db_name]


async def run_drop(
    *,
    dry_run: bool,
    subject_id: str | None,
    skip_guard: bool,
) -> bool:
    # ── Pre-flight guard ────────────────────────────────────────────────────
    pinecone_write = os.environ.get("PINECONE_WRITE", "").strip().lower() in ("1", "true", "yes")
    if not skip_guard and not pinecone_write:
        logger.error(
            "ABORT: PINECONE_WRITE is not set to true. Set it (or use --skip-guard) "
            "to confirm Pinecone is the active vector store before dropping MongoDB embeddings."
        )
        return False

    db = await _get_db()

    # ── Count scope ─────────────────────────────────────────────────────────
    filter_q: dict = {"embedding": {"$exists": True}}
    if subject_id:
        filter_q["subject_id"] = subject_id

    total = await db.chunks.count_documents(filter_q)
    logger.info(
        "Chunks with embedding field%s: %d",
        f" (subject_id={subject_id})" if subject_id else "",
        total,
    )
    if total == 0:
        logger.info("Nothing to drop — embedding field already absent on all matching chunks.")
        return True

    if dry_run:
        logger.info("[DRY RUN] Would unset embedding on %d chunk documents.", total)
        logger.info("[DRY RUN] Re-run without --dry-run to execute.")
        return True

    # ── Stream-batch updateMany ─────────────────────────────────────────────
    # Fetch _id pages and issue targeted updateMany calls per batch so we
    # never hold a collection-wide write lock for the full duration.
    t0 = time.perf_counter()
    dropped = 0
    failed = 0
    last_id = None

    logger.info("Starting batch drop (batch_size=%d) …", _BATCH_SIZE)
    while True:
        page_filter: dict = dict(filter_q)
        if last_id is not None:
            page_filter["_id"] = {"$gt": last_id}

        page = await db.chunks.find(
            page_filter, {"_id": 1}
        ).sort("_id", 1).limit(_BATCH_SIZE).to_list(length=_BATCH_SIZE)

        if not page:
            break

        ids = [r["_id"] for r in page]
        last_id = ids[-1]

        try:
            result = await db.chunks.update_many(
                {"_id": {"$in": ids}},
                {"$unset": {"embedding": ""}},
            )
            dropped += result.modified_count
            logger.info(
                "Progress: %d/%d dropped (batch of %d, modified=%d)",
                dropped, total, len(ids), result.modified_count,
            )
        except Exception as exc:
            logger.error("Batch update failed for %d ids: %s", len(ids), exc)
            failed += len(ids)

        await asyncio.sleep(0.05)  # brief yield to avoid starving other ops

    duration = round(time.perf_counter() - t0, 2)
    remaining = await db.chunks.count_documents({"embedding": {"$exists": True}})

    logger.info(
        "Done in %.1fs — dropped=%d failed=%d remaining_with_embedding=%d",
        duration, dropped, failed, remaining,
    )

    if remaining > 0:
        logger.warning(
            "%d chunks still have an embedding field. "
            "Re-run the script to continue.",
            remaining,
        )
    else:
        logger.info(
            "All embedding arrays removed. "
            "Next: drop the Atlas Vector Search index in the Atlas UI, "
            "then set ATLAS_VS_ENABLED=false in your environment if not already set."
        )

    return failed == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove the embedding field from MongoDB chunks after Pinecone cutover"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be changed without writing anything",
    )
    parser.add_argument(
        "--subject-id", default=None,
        help="Scope to a single subject_id (recommended for first validation run)",
    )
    parser.add_argument(
        "--skip-guard", action="store_true",
        help="Skip the PINECONE_WRITE=true pre-flight check",
    )
    args = parser.parse_args()

    ok = asyncio.run(run_drop(
        dry_run=args.dry_run,
        subject_id=args.subject_id,
        skip_guard=args.skip_guard,
    ))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
