"""
One-time migration: MongoDB syllabus_embeddings → Cloudflare Vectorize
======================================================================
Phase 1: Reads existing vectors from the MongoDB `syllabus_embeddings`
         collection and upserts them to Vectorize (re-embedding at 768 dims
         since the old embeddings may be 3072-dim).
Phase 2: For any chapters/topics in MongoDB that have no corresponding
         embedding record, generates fresh 768-dim embeddings and upserts.

Usage:
    python migrate_vectors.py

Environment variables required:
    MONGO_URL               — MongoDB connection string
    CLOUDFLARE_API_TOKEN    — Cloudflare API token with Vectorize permissions
    CLOUDFLARE_ACCOUNT_ID   — Cloudflare account ID
    GEMINI_API_KEY (or VERTEX_SERVICE_ACCOUNT) — for embedding generation

Before running, create the Vectorize index:
    wrangler vectorize create syllabus-index --dimensions=768 --metric=cosine
"""

import asyncio
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_vectors")


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient
    from config import MONGO_URL, DB_NAME

    logger.info(f"Connecting to MongoDB — db={DB_NAME}")
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    db = client[DB_NAME]
    await db.command("ping")
    logger.info("Connected to MongoDB.")

    import vectorize_client
    if not vectorize_client.is_configured():
        logger.error("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must be set")
        sys.exit(1)

    index_info = await vectorize_client.get_index_info()
    logger.info(f"Vectorize index info: {index_info}")

    try:
        from vertex_services import embed_text, _EMBED_MODEL
    except ImportError as exc:
        logger.error(f"Cannot import vertex_services: {exc}")
        sys.exit(1)

    from syllabus_embedder import (
        _build_rich_embed_text, _build_topic_embed_text, _make_vector_id,
    )

    mongo_subjects: dict = {}
    async for s in db.subjects.find({}, {
        "id": 1, "title": 1, "name": 1,
        "boardName": 1, "className": 1, "streamName": 1,
    }):
        sid = s.get("id") or str(s.get("_id", ""))
        mongo_subjects[sid] = s

    logger.info(f"Loaded {len(mongo_subjects)} subjects from MongoDB")

    migrated_vector_ids: set[str] = set()
    vectors_batch: list[dict] = []
    total_upserted = 0
    embed_failures = 0

    old_count = await db.syllabus_embeddings.count_documents({})
    logger.info(f"Phase 1: Found {old_count} records in syllabus_embeddings")

    if old_count > 0:
        async for doc in db.syllabus_embeddings.find({}):
            ch_id = doc.get("chapter_id", "")
            level = doc.get("level", "chapter")
            topic = doc.get("topic", "")
            embed_text_str = doc.get("embed_text", "")

            if not ch_id or not embed_text_str:
                continue

            vid = _make_vector_id(ch_id, level, topic)

            try:
                vec = await asyncio.wait_for(
                    embed_text(embed_text_str, task_type="RETRIEVAL_DOCUMENT"),
                    timeout=10.0,
                )
            except Exception as exc:
                logger.warning(f"Re-embed failed for {vid}: {exc}")
                embed_failures += 1
                continue

            if not vec:
                continue

            metadata = {
                "chapter_id": ch_id,
                "subject_id": doc.get("subject_id", ""),
                "board": doc.get("board", ""),
                "class_name": doc.get("class_name", ""),
                "stream": doc.get("stream", ""),
                "subject_name": doc.get("subject_name", ""),
                "chapter_title": doc.get("chapter_title", ""),
                "level": level,
                "topic": topic,
                "embed_text": embed_text_str[:500],
                "embedding_model": _EMBED_MODEL,
                "source": "migration_phase1",
            }
            for key in ("chapter_number",):
                if key in doc:
                    metadata[key] = doc[key]

            vectors_batch.append({"id": vid, "values": vec, "metadata": metadata})

            if len(vectors_batch) >= 20:
                pending_ids = [v["id"] for v in vectors_batch]
                result = await vectorize_client.upsert_vectors(vectors_batch)
                upserted = result.get("upserted", 0)
                if upserted > 0 and not result.get("errors"):
                    migrated_vector_ids.update(pending_ids)
                    total_upserted += upserted
                else:
                    logger.warning(f"Phase 1 batch upsert had issues: {result.get('errors', [])}")
                    for pid in pending_ids:
                        migrated_vector_ids.discard(pid)
                vectors_batch = []
                logger.info(f"Phase 1 progress: {len(migrated_vector_ids)} migrated, {total_upserted} upserted")

            await asyncio.sleep(0.05)

    if vectors_batch:
        pending_ids = [v["id"] for v in vectors_batch]
        result = await vectorize_client.upsert_vectors(vectors_batch)
        upserted = result.get("upserted", 0)
        if upserted > 0 and not result.get("errors"):
            migrated_vector_ids.update(pending_ids)
            total_upserted += upserted
        vectors_batch = []

    logger.info(f"Phase 1 complete: {len(migrated_vector_ids)} vectors migrated from syllabus_embeddings")

    total_chapters = await db.chapters.count_documents({})
    logger.info(f"Phase 2: Checking {total_chapters} chapters for missing embeddings")

    chapters_added = 0
    topics_added = 0

    async for chapter in db.chapters.find({}):
        ch_id = chapter.get("id") or str(chapter.get("_id", ""))
        subj_id = chapter.get("subject_id", "")
        subj = mongo_subjects.get(subj_id, {})

        board_name = subj.get("boardName", "")
        class_name = subj.get("className", "")
        stream_name = subj.get("streamName", "")
        subject_name = subj.get("title") or subj.get("name", "")
        chapter_title = chapter.get("title", "")
        description = (chapter.get("description") or "").strip()
        topic_list: list = chapter.get("topics") or []
        content = (chapter.get("content") or "").strip()

        ch_vid = _make_vector_id(ch_id, "chapter")
        if ch_vid not in migrated_vector_ids:
            embed_text_input = _build_rich_embed_text(
                board_name, class_name, stream_name, subject_name,
                chapter_title, description, topic_list, content,
            )
            try:
                vec = await asyncio.wait_for(
                    embed_text(embed_text_input, task_type="RETRIEVAL_DOCUMENT"),
                    timeout=10.0,
                )
            except Exception as exc:
                logger.warning(f"Embed failed for chapter '{chapter_title[:40]}': {exc}")
                vec = None
                embed_failures += 1

            if vec:
                vectors_batch.append({
                    "id": ch_vid,
                    "values": vec,
                    "metadata": {
                        "chapter_id": ch_id,
                        "subject_id": subj_id,
                        "board": board_name,
                        "class_name": class_name,
                        "stream": stream_name,
                        "subject_name": subject_name,
                        "chapter_title": chapter_title,
                        "chapter_number": chapter.get("chapter_number", 0),
                        "level": "chapter",
                        "topic": "",
                        "embed_text": embed_text_input[:500],
                        "embedding_model": _EMBED_MODEL,
                        "source": "migration_phase2",
                    },
                })
                chapters_added += 1

        for topic in topic_list:
            topic_str = str(topic).strip()
            if not topic_str:
                continue
            t_vid = _make_vector_id(ch_id, "topic", topic_str)
            if t_vid not in migrated_vector_ids:
                topic_embed_text = _build_topic_embed_text(
                    board_name, class_name, stream_name,
                    subject_name, chapter_title, topic_str, content,
                )
                try:
                    t_vec = await asyncio.wait_for(
                        embed_text(topic_embed_text, task_type="RETRIEVAL_DOCUMENT"),
                        timeout=10.0,
                    )
                except Exception as exc:
                    logger.warning(f"Topic embed failed for '{topic_str[:30]}': {exc}")
                    t_vec = None
                    embed_failures += 1

                if t_vec:
                    vectors_batch.append({
                        "id": t_vid,
                        "values": t_vec,
                        "metadata": {
                            "chapter_id": ch_id,
                            "subject_id": subj_id,
                            "board": board_name,
                            "class_name": class_name,
                            "stream": stream_name,
                            "subject_name": subject_name,
                            "chapter_title": chapter_title,
                            "chapter_number": chapter.get("chapter_number", 0),
                            "level": "topic",
                            "topic": topic_str,
                            "embed_text": topic_embed_text[:500],
                            "embedding_model": _EMBED_MODEL,
                            "source": "migration_phase2",
                        },
                    })
                    topics_added += 1

        if len(vectors_batch) >= 20:
            result = await vectorize_client.upsert_vectors(vectors_batch)
            total_upserted += result.get("upserted", len(vectors_batch))
            vectors_batch = []
            logger.info(
                f"Phase 2 progress: +{chapters_added} chapters, +{topics_added} topics"
            )

        await asyncio.sleep(0.05)

    if vectors_batch:
        result = await vectorize_client.upsert_vectors(vectors_batch)
        total_upserted += result.get("upserted", len(vectors_batch))

    logger.info("=" * 60)
    logger.info("Migration complete!")
    logger.info(f"  Phase 1 (from syllabus_embeddings): {len(migrated_vector_ids)}")
    logger.info(f"  Phase 2 (new chapters):             {chapters_added}")
    logger.info(f"  Phase 2 (new topics):               {topics_added}")
    logger.info(f"  Total upserted:                     {total_upserted}")
    logger.info(f"  Embed failures:                     {embed_failures}")
    logger.info("=" * 60)

    logger.info("Verification: checking Vectorize index state...")
    post_info = await vectorize_client.get_index_info()
    index_vector_count = post_info.get("vector_count", "unknown")
    expected_count = len(migrated_vector_ids) + chapters_added + topics_added
    logger.info(f"  Vectorize reports:  {index_vector_count} vectors")
    logger.info(f"  Expected (approx):  {expected_count} vectors")
    if isinstance(index_vector_count, int) and index_vector_count < expected_count:
        logger.warning(
            f"  Vector count mismatch: index has {index_vector_count}, "
            f"expected ~{expected_count}. Some vectors may still be processing "
            "(Vectorize indexes asynchronously) or upserts may have failed."
        )

    await vectorize_client.close()
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
