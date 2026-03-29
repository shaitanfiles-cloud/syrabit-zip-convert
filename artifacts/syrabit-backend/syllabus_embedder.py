"""
Syllabus Embedder
=================
Seeds chapter-level embeddings into the `syllabus_embeddings` MongoDB collection
using SEED_DATA (all AHSEC / SEBA / DEGREE chapters) and stores them for fast
in-process cosine-similarity classification.

Features
--------
- One-time seeding (idempotent — safe to call multiple times)
- In-memory LRU cache of embeddings (refreshed every 6 h)
- Async cosine-similarity search returning the best-matching chapter
- Admin trigger: POST /admin/syllabus/seed-embeddings

Usage
-----
    from syllabus_embedder import SyllabusEmbedder
    embedder = SyllabusEmbedder(db)          # db = motor AsyncIOMotorDB
    await embedder.ensure_seeded()            # call once at startup
    result = await embedder.classify(query)  # returns SyllabusMatch | None
"""

from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("syllabus_embedder")

COLLECTION = "syllabus_embeddings"
SIMILARITY_THRESHOLD = 0.72   # minimum cosine similarity to accept a match
CACHE_TTL_SECONDS    = 6 * 3600  # refresh in-memory cache every 6 h


@dataclass
class SyllabusMatch:
    board: str
    class_name: str
    stream: str
    subject_name: str
    chapter_title: str
    chapter_number: int
    subject_id: str
    chapter_id: str
    similarity: float

    def scope_query(self, user_query: str) -> str:
        parts = [self.board, self.class_name, self.stream, self.subject_name, user_query]
        return " ".join(p for p in parts if p)


class SyllabusEmbedder:
    """Manages chapter embeddings and provides vector-based subject classification."""

    def __init__(self, db):
        self._db   = db
        self._col  = db[COLLECTION] if db is not None else None
        self._cache: list[dict] = []          # list of {embedding, meta}
        self._cache_loaded_at: float = 0.0
        self._seed_lock = asyncio.Lock()
        self._seeded    = False

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    async def ensure_seeded(self) -> int:
        """Seed embeddings for all chapters that don't yet have one. Skips if already seeded."""
        if self._col is None:
            return 0
        async with self._seed_lock:
            if self._seeded:
                return 0
            inserted = await self._seed_chapters()
            self._seeded = True
            return inserted

    async def reseed(self) -> int:
        """Re-embed any new chapters not yet in syllabus_embeddings. Non-destructive (upsert). Called after PDF import."""
        if self._col is None:
            return 0
        async with self._seed_lock:
            self._seeded = False
            self._cache = []
            self._cache_loaded_at = 0.0
            inserted = await self._seed_chapters()
            self._seeded = True
        return inserted

    async def classify(self, query: str) -> Optional[SyllabusMatch]:
        """Embed query and return the closest-matching chapter, or None."""
        try:
            from vertex_services import embed_text, cosine_similarity  # type: ignore
        except ImportError:
            logger.warning("vertex_services not available — syllabus vector classify skipped")
            return None

        try:
            q_vec = await asyncio.wait_for(
                embed_text(query, task_type="RETRIEVAL_QUERY"),
                timeout=3.0,
            )
            if not q_vec:
                return None
        except Exception as exc:
            logger.warning(f"Embed query failed: {exc}")
            return None

        entries = await self._get_cache()
        if not entries:
            return None

        best_score = 0.0
        best_entry = None
        for entry in entries:
            vec = entry.get("embedding")
            if not vec:
                continue
            score = cosine_similarity(q_vec, vec)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry and best_score >= SIMILARITY_THRESHOLD:
            logger.info(
                f"SyllabusEmbed match: {best_entry['subject_name']} / "
                f"{best_entry['chapter_title']} (sim={best_score:.3f}) | query: {query[:50]}"
            )
            return SyllabusMatch(
                board          = best_entry.get("board", "AHSEC"),
                class_name     = best_entry.get("class_name", ""),
                stream         = best_entry.get("stream", ""),
                subject_name   = best_entry.get("subject_name", ""),
                chapter_title  = best_entry.get("chapter_title", ""),
                chapter_number = best_entry.get("chapter_number", 0),
                subject_id     = best_entry.get("subject_id", ""),
                chapter_id     = best_entry.get("chapter_id", ""),
                similarity     = round(best_score, 4),
            )
        return None

    async def full_reseed(self) -> dict:
        """Admin trigger: drop collection and re-embed everything from scratch."""
        if self._col is None:
            return {"error": "MongoDB not available"}
        async with self._seed_lock:
            self._seeded = False
            await self._col.drop()
            inserted = await self._seed_chapters()
            self._seeded = True
            self._cache = []
            self._cache_loaded_at = 0.0
        return {"status": "ok", "inserted": inserted}

    async def stats(self) -> dict:
        if self._col is None:
            return {"error": "MongoDB not available"}
        total = await self._col.count_documents({})
        embedded = await self._col.count_documents({"embedding": {"$exists": True}})
        return {"total_chapters": total, "embedded": embedded, "cache_entries": len(self._cache)}

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_cache(self) -> list[dict]:
        now = time.time()
        if self._cache and (now - self._cache_loaded_at) < CACHE_TTL_SECONDS:
            return self._cache
        # Reload from MongoDB
        if self._col is None:
            return []
        cursor  = self._col.find({"embedding": {"$exists": True}}, {"embedding": 1, "board": 1,
            "class_name": 1, "stream": 1, "subject_name": 1, "chapter_title": 1,
            "chapter_number": 1, "subject_id": 1, "chapter_id": 1})
        entries = await cursor.to_list(length=None)
        self._cache = entries
        self._cache_loaded_at = now
        logger.info(f"SyllabusEmbedder cache loaded: {len(entries)} chapter embeddings")
        return entries

    async def _seed_chapters(self) -> int:
        """
        Embed every chapter that isn't already in syllabus_embeddings.
        Sources:
          1. SEED_DATA chapters (static AHSEC/SEBA hardcoded data)
          2. MongoDB `chapters` collection (from PDF imports)
        """
        try:
            from server import SEED_DATA           # type: ignore
            from vertex_services import embed_text  # type: ignore
        except ImportError as exc:
            logger.warning(f"Cannot seed — import error: {exc}")
            return 0

        # Build board/stream/subject lookup from SEED_DATA
        boards   = {b["id"]: b for b in SEED_DATA.get("boards", [])}
        classes_ = {c["id"]: c for c in SEED_DATA.get("classes", [])}
        streams  = {s["id"]: s for s in SEED_DATA.get("streams", [])}
        subjects = {s["id"]: s for s in SEED_DATA.get("subjects", [])}

        # Pre-fetch already-seeded chapter IDs to avoid duplicates
        existing_ids: set = set()
        async for doc in self._col.find({}, {"chapter_id": 1}):
            if doc.get("chapter_id"):
                existing_ids.add(doc["chapter_id"])

        inserted = 0

        # ── 1. Seed SEED_DATA chapters ─────────────────────────────────────────
        for chapter in SEED_DATA.get("chapters", []):
            ch_id   = chapter["id"]
            subj_id = chapter["subject_id"]
            if ch_id in existing_ids:
                continue

            subj   = subjects.get(subj_id, {})
            stream = streams.get(subj.get("stream_id", ""), {})
            cls    = classes_.get(stream.get("class_id", ""), {})
            board  = boards.get(cls.get("board_id", ""), {})

            board_name    = board.get("name", "AHSEC")
            class_name    = cls.get("name", "")
            stream_name   = stream.get("name", "")
            subject_name  = subj.get("name", "")
            chapter_title = chapter.get("title", "")

            embed_text_input = (
                f"{board_name} {class_name} {stream_name} "
                f"{subject_name} — {chapter_title}"
            )
            try:
                vec = await asyncio.wait_for(
                    embed_text(embed_text_input, task_type="RETRIEVAL_DOCUMENT"),
                    timeout=5.0,
                )
            except Exception as exc:
                logger.warning(f"Embed failed for {chapter_title[:40]}: {exc}")
                vec = None

            doc = {
                "chapter_id":     ch_id,
                "subject_id":     subj_id,
                "board":          board_name,
                "class_name":     class_name,
                "stream":         stream_name,
                "subject_name":   subject_name,
                "chapter_title":  chapter_title,
                "chapter_number": chapter.get("chapter_number", 0),
                "embed_text":     embed_text_input,
                "embedding":      vec,
                "status":         "active",
                "created_at":     __import__("datetime").datetime.utcnow().isoformat(),
            }
            await self._col.update_one(
                {"chapter_id": ch_id},
                {"$set": doc},
                upsert=True,
            )
            inserted += 1
            if inserted % 20 == 0:
                logger.info(f"SyllabusEmbedder: {inserted} chapters embedded so far…")

        # ── 2. Seed MongoDB chapters (PDF imports) ─────────────────────────────
        # Query chapters collection for any chapter not yet embedded.
        # Subjects from the linker carry boardName / className / streamName.
        try:
            db = self._db

            # Build subject lookup from MongoDB (only what we need)
            mongo_subjects: dict = {}
            async for s in db.subjects.find({}, {
                "id": 1, "title": 1, "name": 1,
                "boardName": 1, "className": 1, "streamName": 1,
            }):
                sid = s.get("id") or str(s.get("_id", ""))
                mongo_subjects[sid] = s

            # Collect unembedded MongoDB chapters
            async for chapter in db.chapters.find({}):
                ch_id   = chapter.get("id") or str(chapter.get("_id", ""))
                if ch_id in existing_ids:
                    continue

                subj_id = chapter.get("subject_id", "")
                subj    = mongo_subjects.get(subj_id, {})

                board_name    = subj.get("boardName", "")
                class_name    = subj.get("className", "")
                stream_name   = subj.get("streamName", "")
                subject_name  = subj.get("title") or subj.get("name", "")
                chapter_title = chapter.get("title", "")
                description   = (chapter.get("description") or "").strip()
                topics: list  = chapter.get("topics") or []

                # Build a richer embed text using the lesson description
                parts = [board_name, class_name, stream_name, subject_name]
                context = " ".join(p for p in parts if p)
                if description and not description.lower().startswith("chapter "):
                    # Real description from PDF extraction
                    embed_text_input = f"{context} — {chapter_title}: {description}"
                elif topics:
                    embed_text_input = f"{context} — {chapter_title}: {', '.join(topics[:8])}"
                else:
                    embed_text_input = f"{context} — {chapter_title}"

                try:
                    vec = await asyncio.wait_for(
                        embed_text(embed_text_input, task_type="RETRIEVAL_DOCUMENT"),
                        timeout=5.0,
                    )
                except Exception as exc:
                    logger.warning(f"Embed (mongo) failed for {chapter_title[:40]}: {exc}")
                    vec = None

                doc = {
                    "chapter_id":     ch_id,
                    "subject_id":     subj_id,
                    "board":          board_name,
                    "class_name":     class_name,
                    "stream":         stream_name,
                    "subject_name":   subject_name,
                    "chapter_title":  chapter_title,
                    "chapter_number": chapter.get("chapter_number", 0),
                    "embed_text":     embed_text_input,
                    "embedding":      vec,
                    "description":    description,
                    "topics":         topics,
                    "status":         "active",
                    "source":         "pdf_import",
                    "created_at":     __import__("datetime").datetime.utcnow().isoformat(),
                }
                await self._col.update_one(
                    {"chapter_id": ch_id},
                    {"$set": doc},
                    upsert=True,
                )
                existing_ids.add(ch_id)
                inserted += 1
                if inserted % 10 == 0:
                    logger.info(f"SyllabusEmbedder: {inserted} chapters embedded so far (incl. PDF imports)…")

        except Exception as mongo_err:
            logger.warning(f"SyllabusEmbedder: MongoDB chapter seeding failed: {mongo_err}")

        # Create indexes — guard against duplicate-key / race on multi-worker startup
        try:
            await self._col.create_index("subject_id")
            await self._col.create_index("board")
        except Exception as ie:
            logger.debug(f"SyllabusEmbedder: index (non-unique) error (ignored): {ie}")

        try:
            await self._col.create_index("chapter_id", unique=True)
        except Exception as ie:
            # Unique index failed — likely duplicate chapter_ids from previous run.
            # Remove duplicates, keeping only the latest doc for each chapter_id.
            logger.warning(f"SyllabusEmbedder: unique index failed ({ie}); deduplicating…")
            try:
                pipeline = [
                    {"$group": {"_id": "$chapter_id", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
                    {"$match": {"count": {"$gt": 1}}},
                ]
                async for group in self._col.aggregate(pipeline):
                    # Keep the first, delete the rest
                    to_delete = group["ids"][1:]
                    await self._col.delete_many({"_id": {"$in": to_delete}})
                # Retry index creation
                await self._col.create_index("chapter_id", unique=True)
            except Exception as dedup_err:
                logger.warning(f"SyllabusEmbedder: dedup fallback failed: {dedup_err}")

        logger.info(f"SyllabusEmbedder: seeding complete — {inserted} new chapters embedded")
        return inserted
