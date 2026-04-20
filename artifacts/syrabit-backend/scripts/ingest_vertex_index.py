"""
ingest_vertex_index.py — populate the Vertex AI Vector Search index with
embeddings for every chapter + topic in MongoDB.

Run alongside the existing Vectorize index (it stays the source of truth
until the toggle flips). The script reuses `_build_rich_embed_text` and
`_build_topic_embed_text` from `syllabus_embedder` so the two indexes
embed the same text and apples-to-apples comparison is valid.

Usage:
    cd artifacts/syrabit-backend
    python -m scripts.ingest_vertex_index --batch 50 [--limit 200] [--dry-run]

Required env vars (see docs/VERTEX_RETRIEVER.md):
    VERTEX_PROJECT_ID, VERTEX_LOCATION, VERTEX_INDEX_ID,
    VERTEX_INDEX_ENDPOINT_ID, VERTEX_DEPLOYED_INDEX_ID,
    VERTEX_SERVICE_ACCOUNT (raw JSON or path)

Embeddings come from `vertex_services.embed_text` (same as the live
syllabus embedder) — when that module is in stub mode the script exits
with a clear error rather than uploading zero-vectors.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

logger = logging.getLogger("ingest_vertex_index")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(batch_size: int, limit: int | None, dry_run: bool) -> int:
    from deps import db
    if db is None:
        logger.error("MongoDB not configured (deps.db is None)")
        return 2

    from retrievers import get_retriever_by_name
    retriever = get_retriever_by_name("vertex")
    if not retriever.is_configured():
        logger.error(
            "Vertex retriever not configured — set VERTEX_PROJECT_ID, "
            "VERTEX_LOCATION, VERTEX_INDEX_ID, VERTEX_INDEX_ENDPOINT_ID, "
            "VERTEX_DEPLOYED_INDEX_ID, VERTEX_SERVICE_ACCOUNT."
        )
        return 2

    from syllabus_embedder import (
        _build_rich_embed_text,
        _build_topic_embed_text,
        _make_vector_id,
    )
    try:
        from vertex_services import embed_text, _EMBED_MODEL  # type: ignore
    except ImportError:
        logger.error("vertex_services unavailable — embeddings cannot be generated")
        return 2

    # Probe — refuse to run if the embedder is in stub mode (returns []).
    probe = await embed_text("syrabit retriever ingestion probe", task_type="RETRIEVAL_DOCUMENT")
    if not probe:
        logger.error(
            "vertex_services.embed_text returned [] — module is in stub mode. "
            "Restore the Vertex embedding integration before running this script."
        )
        return 2

    mongo_subjects: dict[str, dict] = {}
    async for s in db.subjects.find({}, {
        "id": 1, "title": 1, "name": 1,
        "boardName": 1, "className": 1, "streamName": 1,
    }):
        sid = s.get("id") or str(s.get("_id", ""))
        mongo_subjects[sid] = s

    total_uploaded = 0
    embed_failures = 0
    pending: list[dict] = []
    chapter_count = 0
    t0 = time.monotonic()

    cursor = db.chapters.find({})
    async for chapter in cursor:
        if limit is not None and chapter_count >= limit:
            break
        chapter_count += 1
        ch_id = chapter.get("id") or str(chapter.get("_id", ""))
        subj_id = chapter.get("subject_id", "")
        subj = mongo_subjects.get(subj_id, {})
        board_name = subj.get("boardName", "")
        class_name = subj.get("className", "")
        stream_name = subj.get("streamName", "")
        subject_name = subj.get("title") or subj.get("name", "")
        title = chapter.get("title", "")
        description = (chapter.get("description") or "").strip()
        topic_list = chapter.get("topics") or []
        content = (chapter.get("content") or "").strip()
        chapter_number = chapter.get("chapter_number", 0)

        embed_text_input = _build_rich_embed_text(
            board_name, class_name, stream_name, subject_name,
            title, description, topic_list, content,
        )
        try:
            vec = await asyncio.wait_for(
                embed_text(embed_text_input, task_type="RETRIEVAL_DOCUMENT"),
                timeout=20.0,
            )
        except Exception as exc:
            logger.warning("embed failed for %s: %s", title[:40], exc)
            vec = None
        if vec:
            pending.append({
                "id": _make_vector_id(ch_id, "chapter"),
                "values": vec,
                "metadata": {
                    "chapter_id": ch_id, "subject_id": subj_id,
                    "board": board_name, "class_name": class_name,
                    "stream": stream_name, "subject_name": subject_name,
                    "chapter_title": title, "chapter_number": chapter_number,
                    "level": "chapter", "topic": "",
                    "embedding_model": _EMBED_MODEL,
                    "source": "ingest_vertex_index",
                },
            })
        else:
            embed_failures += 1

        for t in topic_list:
            ts = str(t).strip()
            if not ts:
                continue
            topic_input = _build_topic_embed_text(
                board_name, class_name, stream_name,
                subject_name, title, ts, content,
            )
            try:
                tvec = await asyncio.wait_for(
                    embed_text(topic_input, task_type="RETRIEVAL_DOCUMENT"),
                    timeout=20.0,
                )
            except Exception as exc:
                logger.warning("topic embed failed for %s: %s", ts[:30], exc)
                tvec = None
            if tvec:
                pending.append({
                    "id": _make_vector_id(ch_id, "topic", ts),
                    "values": tvec,
                    "metadata": {
                        "chapter_id": ch_id, "subject_id": subj_id,
                        "board": board_name, "class_name": class_name,
                        "stream": stream_name, "subject_name": subject_name,
                        "chapter_title": title, "chapter_number": chapter_number,
                        "level": "topic", "topic": ts,
                        "embedding_model": _EMBED_MODEL,
                        "source": "ingest_vertex_index",
                    },
                })
            else:
                embed_failures += 1

        if len(pending) >= batch_size:
            uploaded = await _flush(retriever, pending, dry_run)
            total_uploaded += uploaded
            pending = []
            logger.info(
                "progress: %d chapters, %d vectors uploaded (failures=%d, elapsed=%.1fs)",
                chapter_count, total_uploaded, embed_failures, time.monotonic() - t0,
            )

    if pending:
        uploaded = await _flush(retriever, pending, dry_run)
        total_uploaded += uploaded

    logger.info(
        "DONE chapters=%d uploaded=%d embed_failures=%d elapsed=%.1fs%s",
        chapter_count, total_uploaded, embed_failures,
        time.monotonic() - t0, " (DRY-RUN)" if dry_run else "",
    )
    return 0


async def _flush(retriever, pending: list[dict], dry_run: bool) -> int:
    if dry_run:
        logger.info("[dry-run] would upsert %d vectors", len(pending))
        return len(pending)
    res = await retriever.upsert(pending)
    if res.get("errors"):
        logger.warning("upsert returned errors: %s", res["errors"])
    return int(res.get("upserted", 0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=int(os.environ.get("INGEST_BATCH", "50")))
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap chapters processed (for smoke tests).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Embed and log batch sizes but skip uploads.")
    args = parser.parse_args()
    _setup_logging()
    try:
        return asyncio.run(_run(args.batch, args.limit, args.dry_run))
    except KeyboardInterrupt:
        logger.warning("interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
