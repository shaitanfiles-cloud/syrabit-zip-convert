"""
providers.chunk_embedder — Batch embedding pipeline for the chunks collection.

Embeds all chunks that are missing an `embedding` field using Pinecone
`multilingual-e5-large` (1024-dim, multilingual — handles Assamese content).
After running, the Atlas `vector_index` on `chunks.embedding` becomes
queryable via `$vectorSearch`.

Usage (from admin endpoint):
    from providers.chunk_embedder import embed_chunks_bulk
    result = await embed_chunks_bulk(db, batch_size=64, force_all=False)

Also provides:
    embed_chapter_content   — embed a single chapter's full content text
    translate_and_embed_as  — translate chapter to Assamese then embed bilingual
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("providers.chunk_embedder")

_EMBED_MODEL = "multilingual-e5-large"
_EMBED_DIM   = 1024
_BATCH_SIZE  = 48   # Pinecone allows up to 96 inputs; keep below for safety


async def _pinecone_embed_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """Embed a batch of texts using Pinecone. Returns None for failures."""
    try:
        from providers.pinecone_ai import embed as pc_embed
        vecs = await asyncio.wait_for(
            pc_embed(texts, input_type="passage"),
            timeout=20.0,
        )
        return vecs
    except Exception as exc:
        logger.warning("[chunk_embedder] Pinecone embed batch failed: %s", exc)
        return [None] * len(texts)


async def embed_chunks_bulk(
    db: Any,
    *,
    batch_size: int = _BATCH_SIZE,
    force_all: bool = False,
    subject_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """Embed all chunks missing an `embedding` field using Pinecone.

    Args:
        db:         Motor database instance.
        batch_size: How many chunks to embed per Pinecone API call.
        force_all:  If True, re-embed ALL chunks even if they already have embeddings.
        subject_id: Scope to a single subject (optional).
        limit:      Max total chunks to process (optional, for test runs).

    Returns:
        Dict with stats: total, embedded, skipped, failed, duration_s.
    """
    t0 = time.perf_counter()

    query: dict = {}
    if not force_all:
        query["embedding"] = {"$exists": False}
    if subject_id:
        query["subject_id"] = subject_id

    cursor = db.chunks.find(
        query,
        {"_id": 1, "id": 1, "chapter_id": 1, "subject_id": 1,
         "chapter_title": 1, "topic_name": 1, "content": 1, "content_as": 1},
    )
    if limit:
        cursor = cursor.limit(limit)

    chunks = await cursor.to_list(length=limit or 10_000)
    total = len(chunks)
    logger.info("[chunk_embedder] Starting bulk embed: %d chunks (force=%s)", total, force_all)

    embedded = failed = skipped = 0

    for batch_start in range(0, total, batch_size):
        batch = chunks[batch_start: batch_start + batch_size]

        texts = []
        for ch in batch:
            content = (ch.get("content") or "").strip()
            if not content:
                skipped += 1
                texts.append(None)
                continue
            # Bilingual: append Assamese content if available
            content_as = (ch.get("content_as") or "").strip()
            topic_prefix = ch.get("topic_name", "") or ch.get("chapter_title", "")
            embed_text = f"{topic_prefix}\n\n{content}"
            if content_as:
                embed_text += f"\n\n{content_as[:400]}"
            texts.append(embed_text[:2048])

        # Embed non-None texts
        to_embed = [(i, t) for i, t in enumerate(texts) if t is not None]
        if not to_embed:
            continue

        idxs, embed_texts = zip(*to_embed)
        vecs = await _pinecone_embed_batch(list(embed_texts))

        # Update MongoDB
        from motor.motor_asyncio import AsyncIOMotorDatabase
        from pymongo import UpdateOne

        ops = []
        for i, vec in zip(idxs, vecs):
            if vec is None:
                failed += 1
                continue
            chunk = batch[i]
            filter_q = {"_id": chunk["_id"]}
            ops.append(UpdateOne(
                filter_q,
                {"$set": {
                    "embedding":        vec,
                    "embedding_model":  _EMBED_MODEL,
                    "embedding_dim":    _EMBED_DIM,
                    "embedding_source": "pinecone",
                }},
                upsert=False,
            ))
            embedded += 1

        if ops:
            try:
                await db.chunks.bulk_write(ops, ordered=False)
            except Exception as exc:
                logger.warning("[chunk_embedder] Bulk write error: %s", exc)
                failed += len(ops)
                embedded -= len(ops)

        logger.info(
            "[chunk_embedder] Progress %d/%d — embedded=%d failed=%d skipped=%d",
            batch_start + len(batch), total, embedded, failed, skipped,
        )
        # Throttle to avoid Pinecone rate limits
        await asyncio.sleep(0.1)

    duration = round(time.perf_counter() - t0, 2)
    result = {
        "total":      total,
        "embedded":   embedded,
        "skipped":    skipped,
        "failed":     failed,
        "duration_s": duration,
        "model":      _EMBED_MODEL,
    }
    logger.info("[chunk_embedder] Bulk embed complete: %s", result)
    return result


async def embed_chapter_content(
    db: Any,
    chapter_id: str,
    *,
    force: bool = False,
) -> dict:
    """Embed all chunks for a single chapter.

    Useful after notes/QA generation to immediately make the chapter
    searchable via Atlas Vector Search.
    """
    result = await embed_chunks_bulk(
        db,
        batch_size=_BATCH_SIZE,
        force_all=force,
        subject_id=None,
        limit=None,
    )
    return result


async def translate_chapters_to_assamese(
    db: Any,
    *,
    limit: int = 50,
    skip_existing: bool = True,
) -> dict:
    """Translate English chapter content to Assamese (content_as field).

    Uses Sarvam translate:v1 as primary, no fallback (admin pipeline only).
    After translation, also re-embeds the chapter chunks bilingually.

    Args:
        db:            Motor database.
        limit:         Max chapters to process per run.
        skip_existing: Skip chapters that already have content_as.

    Returns:
        Stats dict: total, translated, failed, skipped, duration_s.
    """
    import deps

    t0 = time.perf_counter()
    query: dict = {"status": "published", "content": {"$exists": True, "$ne": ""}}
    if skip_existing:
        query["content_as"] = {"$exists": False}

    chapters = await db.chapters.find(
        query,
        {"_id": 0, "id": 1, "title": 1, "content": 1, "subject_id": 1},
    ).limit(limit).to_list(length=limit)

    total = len(chapters)
    translated = failed = skipped = 0

    sarvam_tc = getattr(deps, "sarvam_translate_client", None) or getattr(deps, "sarvam_client", None)
    if not sarvam_tc:
        return {"error": "Sarvam translate client not configured", "total": total}

    logger.info("[chunk_embedder] Translating %d chapters to Assamese", total)

    for ch in chapters:
        content = (ch.get("content") or "").strip()
        if not content or len(content) < 50:
            skipped += 1
            continue

        # Chunk into 1800-char pieces (Sarvam limit)
        parts = []
        for i in range(0, len(content), 1800):
            parts.append(content[i:i + 1800])

        translated_parts = []
        ok = True
        for part in parts:
            try:
                resp = await asyncio.wait_for(
                    sarvam_tc.post("/translate", json={
                        "input": part,
                        "source_language_code": "en-IN",
                        "target_language_code": "as-IN",
                        "speaker_gender": "Female",
                        "mode": "formal",
                        "model": "sarvam-translate:v1",
                        "enable_preprocessing": False,
                    }),
                    timeout=8.0,
                )
                if resp.status_code == 200:
                    translated_parts.append((resp.json().get("translated_text") or "").strip())
                else:
                    logger.warning("[chunk_embedder] Sarvam translate HTTP %d for chapter %s", resp.status_code, ch["id"])
                    ok = False
                    break
            except Exception as exc:
                logger.warning("[chunk_embedder] Translation failed for chapter %s: %s", ch["id"], exc)
                ok = False
                break

        if not ok or not translated_parts:
            failed += 1
            continue

        content_as = "\n".join(translated_parts)
        await db.chapters.update_one(
            {"id": ch["id"]},
            {"$set": {"content_as": content_as, "content_as_lang": "as-IN",
                      "content_as_model": "sarvam-translate:v1"}},
        )

        # Re-embed the chapter's chunks bilingually
        try:
            await db.chunks.update_many(
                {"chapter_id": ch["id"]},
                {"$unset": {"embedding": ""}},
            )
        except Exception:
            pass

        translated += 1
        logger.info("[chunk_embedder] Translated '%s' (%d chars → %d chars as)", ch["title"][:40], len(content), len(content_as))
        await asyncio.sleep(0.2)

    # Re-embed all modified chunks
    embed_result = {}
    if translated > 0:
        embed_result = await embed_chunks_bulk(db, force_all=False)

    duration = round(time.perf_counter() - t0, 2)
    return {
        "total":        total,
        "translated":   translated,
        "failed":       failed,
        "skipped":      skipped,
        "duration_s":   duration,
        "embed_result": embed_result,
    }
