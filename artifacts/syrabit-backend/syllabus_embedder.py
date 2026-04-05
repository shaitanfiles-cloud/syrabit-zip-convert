"""
Syllabus Embedder
=================
Seeds chapter-level AND topic-level embeddings into the `syllabus_embeddings`
MongoDB collection using MongoDB `chapters` data (from PDF imports) and stores
them for fast in-process cosine-similarity classification.

Features
--------
- Enriched embed text: title + description + full topic list + keywords (~2000 chars)
- Topic-level embeddings: one embedding per topic (or small group) for precise matching
- Configurable similarity thresholds via environment variables
- Top-3 match score logging for every classify() call
- In-memory LRU cache of embeddings (refreshed every 6 h)
- Async cosine-similarity search returning the best-matching chapter
- Admin triggers: POST /admin/syllabus/seed-embeddings
- Admin diagnostics: GET /admin/syllabus/test-classify?q=...
- Admin stats: GET /admin/syllabus/embedding-stats (enriched)

Usage
-----
    from syllabus_embedder import SyllabusEmbedder
    embedder = SyllabusEmbedder(db)          # db = motor AsyncIOMotorDB
    await embedder.ensure_seeded()            # call once at startup
    result = await embedder.classify(query)  # returns SyllabusMatch | None
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("syllabus_embedder")

COLLECTION = "syllabus_embeddings"
EMBED_TEXT_MAX_CHARS = 2000
CACHE_TTL_SECONDS    = 6 * 3600


def _safe_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"Invalid float for env {name}={raw!r}, using default {default}")
        return default


SIMILARITY_THRESHOLD = _safe_float_env("SYLLABUS_CLASSIFY_THRESHOLD", 0.65)
SUBJECT_MATCH_BONUS = _safe_float_env("SYLLABUS_SUBJECT_MATCH_BONUS", 0.05)
SUBJECT_MISMATCH_PENALTY = _safe_float_env("SYLLABUS_SUBJECT_MISMATCH_PENALTY", 0.08)


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
    level: str = "chapter"
    topic: str = ""

    def scope_query(self, user_query: str) -> str:
        parts = [self.board, self.class_name, self.stream, self.subject_name, user_query]
        return " ".join(p for p in parts if p)


def _build_rich_embed_text(
    board_name: str,
    class_name: str,
    stream_name: str,
    subject_name: str,
    chapter_title: str,
    description: str = "",
    topics: list = None,
    content: str = "",
) -> str:
    context_parts = [p for p in [board_name, class_name, stream_name, subject_name] if p]
    context = " ".join(context_parts)

    sections = [f"{context} — {chapter_title}"]

    clean_desc = (description or "").strip()
    if clean_desc and not clean_desc.lower().startswith("chapter "):
        sections.append(clean_desc)

    if topics:
        sections.append("Topics: " + ", ".join(topics))

    if content:
        keywords = _extract_content_keywords(content)
        if keywords:
            sections.append("Key terms: " + ", ".join(keywords))

    result = ". ".join(sections)
    return result[:EMBED_TEXT_MAX_CHARS]


def _extract_content_keywords(content: str, max_keywords: int = 20) -> list[str]:
    import re
    if not content:
        return []
    bold_terms = re.findall(r'\*\*([^*]{2,40})\*\*', content)
    heading_terms = re.findall(r'^#{1,4}\s+(.+)$', content, re.MULTILINE)
    terms = []
    seen = set()
    for t in bold_terms + heading_terms:
        t_clean = t.strip().lower()
        if t_clean not in seen and len(t_clean) > 2:
            seen.add(t_clean)
            terms.append(t.strip())
    return terms[:max_keywords]


def _build_topic_embed_text(
    board_name: str,
    class_name: str,
    stream_name: str,
    subject_name: str,
    chapter_title: str,
    topic: str,
) -> str:
    context_parts = [p for p in [board_name, class_name, stream_name, subject_name] if p]
    context = " ".join(context_parts)
    return f"{context} — {chapter_title} — {topic}"[:EMBED_TEXT_MAX_CHARS]


class SyllabusEmbedder:
    """Manages chapter + topic embeddings and provides vector-based subject classification."""

    def __init__(self, db):
        self._db   = db
        self._col  = db[COLLECTION] if db is not None else None
        self._cache: list[dict] = []
        self._cache_loaded_at: float = 0.0
        self._seed_lock = asyncio.Lock()
        self._seeded    = False

    async def embed_chapter(
        self,
        chapter_id: str,
        subject_id: str,
        title: str,
        description: str = "",
        topics: list = None,
        content: str = "",
    ) -> int:
        if self._col is None:
            return 0
        try:
            from vertex_services import embed_text as _embed_fn
        except ImportError:
            logger.warning("vertex_services unavailable — skipping chapter embedding")
            return 0

        db = self._db
        subj = await db.subjects.find_one({"id": subject_id}, {"_id": 0}) or {}
        board_name = subj.get("boardName", "")
        class_name = subj.get("className", "")
        stream_name = subj.get("streamName", "")
        subject_name = subj.get("title") or subj.get("name", "")

        try:
            from vertex_services import _EMBED_MODEL as _current_embed_model
        except ImportError:
            _current_embed_model = "unknown"

        embed_text_input = _build_rich_embed_text(
            board_name, class_name, stream_name, subject_name,
            title, description, topics or [], content,
        )

        try:
            vec = await asyncio.wait_for(
                _embed_fn(embed_text_input, task_type="RETRIEVAL_DOCUMENT"),
                timeout=5.0,
            )
        except Exception as exc:
            logger.warning(f"Embed chapter failed for {title[:40]}: {exc}")
            vec = None

        now = __import__("datetime").datetime.utcnow().isoformat()
        doc = {
            "chapter_id": chapter_id,
            "subject_id": subject_id,
            "board": board_name,
            "class_name": class_name,
            "stream": stream_name,
            "subject_name": subject_name,
            "chapter_title": title,
            "chapter_number": 0,
            "embed_text": embed_text_input,
            "embedding": vec,
            "embedding_model": _current_embed_model,
            "level": "chapter",
            "description": description,
            "topics": topics or [],
            "status": "active",
            "source": "content_editor",
            "created_at": now,
        }
        await self._col.update_one(
            {"chapter_id": chapter_id, "level": "chapter"},
            {"$set": doc},
            upsert=True,
        )
        inserted = 1

        await self._col.delete_many(
            {"chapter_id": chapter_id, "level": "topic"}
        )
        inserted += await self._seed_topic_embeddings(
            chapter_id, subject_id, board_name, class_name, stream_name,
            subject_name, title, 0, topics or [], _embed_fn,
            _current_embed_model, set(),
        )

        self._cache = []
        self._cache_loaded_at = 0.0
        logger.info(f"Embedded chapter '{title[:40]}' + {inserted - 1} topics on save")
        return inserted

    async def remove_chapter_embeddings(self, chapter_id: str) -> int:
        if self._col is None:
            return 0
        result = await self._col.delete_many({"chapter_id": chapter_id})
        self._cache = []
        self._cache_loaded_at = 0.0
        return result.deleted_count

    async def ensure_seeded(self) -> int:
        if self._col is None:
            return 0
        async with self._seed_lock:
            if self._seeded:
                return 0
            inserted = await self._seed_chapters()
            self._seeded = True
            return inserted

    async def reseed(self) -> int:
        if self._col is None:
            return 0
        async with self._seed_lock:
            self._seeded = False
            self._cache = []
            self._cache_loaded_at = 0.0
            inserted = await self._seed_chapters()
            self._seeded = True
        return inserted

    async def classify(self, query: str, subject_id: Optional[str] = None) -> Optional[SyllabusMatch]:
        try:
            from vertex_services import embed_text, cosine_similarity
        except ImportError:
            logger.warning("vertex_services not available — syllabus vector classify skipped")
            return None

        try:
            from cache import _query_embed_cache
        except ImportError:
            _query_embed_cache = None

        _embed_key = query.strip().lower()
        q_vec = _query_embed_cache.get(_embed_key) if _query_embed_cache is not None else None

        if q_vec is None:
            try:
                q_vec = await asyncio.wait_for(
                    embed_text(query, task_type="RETRIEVAL_QUERY"),
                    timeout=1.5,
                )
                if not q_vec:
                    return None
                if _query_embed_cache is not None:
                    _query_embed_cache[_embed_key] = q_vec
            except Exception as exc:
                logger.warning(f"Embed query failed: {exc}")
                return None
        else:
            logger.info(f"SyllabusEmbed: reusing cached query embedding for '{query[:40]}'")

        entries = await self._get_cache()
        if not entries:
            return None

        scored = []
        for entry in entries:
            vec = entry.get("embedding")
            if not vec:
                continue
            score = cosine_similarity(q_vec, vec)
            if subject_id:
                entry_sid = entry.get("subject_id", "")
                if entry_sid == subject_id:
                    score += SUBJECT_MATCH_BONUS
                elif entry_sid:
                    score -= SUBJECT_MISMATCH_PENALTY
            scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])

        top3 = scored[:3]
        top3_log = " | ".join(
            f"{e.get('chapter_title', '?')}"
            f"{'/' + e.get('topic', '') if e.get('level') == 'topic' else ''}"
            f" ({s:.3f})"
            for s, e in top3
        )
        logger.info(f"SyllabusEmbed top-3: [{top3_log}] | query: {query[:60]}")

        if not scored:
            return None

        best_score, best_entry = scored[0]

        if best_score >= SIMILARITY_THRESHOLD:
            logger.info(
                f"SyllabusEmbed match: {best_entry.get('subject_name', '')} / "
                f"{best_entry.get('chapter_title', '')} "
                f"(level={best_entry.get('level', 'chapter')}, sim={best_score:.3f}) | query: {query[:50]}"
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
                level          = best_entry.get("level", "chapter"),
                topic          = best_entry.get("topic", ""),
            )
        return None

    async def classify_top_n(self, query: str, top_n: int = 5) -> list[dict]:
        try:
            from vertex_services import embed_text, cosine_similarity
        except ImportError:
            return []

        try:
            q_vec = await asyncio.wait_for(
                embed_text(query, task_type="RETRIEVAL_QUERY"),
                timeout=3.0,
            )
            if not q_vec:
                return []
        except Exception:
            return []

        entries = await self._get_cache()
        if not entries:
            return []

        scored = []
        for entry in entries:
            vec = entry.get("embedding")
            if not vec:
                continue
            score = cosine_similarity(q_vec, vec)
            scored.append({
                "board": entry.get("board", ""),
                "class_name": entry.get("class_name", ""),
                "stream": entry.get("stream", ""),
                "subject_name": entry.get("subject_name", ""),
                "chapter_title": entry.get("chapter_title", ""),
                "chapter_number": entry.get("chapter_number", 0),
                "subject_id": entry.get("subject_id", ""),
                "chapter_id": entry.get("chapter_id", ""),
                "level": entry.get("level", "chapter"),
                "topic": entry.get("topic", ""),
                "embed_text_preview": (entry.get("embed_text", ""))[:200],
                "similarity": round(score, 4),
                "passes_threshold": score >= SIMILARITY_THRESHOLD,
            })

        scored.sort(key=lambda x: -x["similarity"])
        return scored[:top_n]

    async def full_reseed(self) -> dict:
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
        chapter_count = await self._col.count_documents({"level": {"$ne": "topic"}})
        topic_count = await self._col.count_documents({"level": "topic"})

        pipeline_thin = [
            {"$match": {"embedding": {"$exists": True}}},
            {"$project": {"embed_text": 1, "len": {"$strLenCP": {"$ifNull": ["$embed_text", ""]}}}},
            {"$match": {"len": {"$lt": 100}}},
            {"$count": "thin"},
        ]
        thin_result = await self._col.aggregate(pipeline_thin).to_list(1)
        thin_count = thin_result[0]["thin"] if thin_result else 0

        pipeline_no_topics = [
            {"$match": {"level": {"$ne": "topic"}}},
            {"$match": {"$or": [{"topics": {"$exists": False}}, {"topics": {"$size": 0}}]}},
            {"$count": "missing"},
        ]
        no_topics_result = await self._col.aggregate(pipeline_no_topics).to_list(1)
        missing_topics = no_topics_result[0]["missing"] if no_topics_result else 0

        pipeline_avg = [
            {"$match": {"embedding": {"$exists": True}}},
            {"$project": {"len": {"$strLenCP": {"$ifNull": ["$embed_text", ""]}}}},
            {"$group": {"_id": None, "avg_len": {"$avg": "$len"}, "max_len": {"$max": "$len"}, "min_len": {"$min": "$len"}}},
        ]
        avg_result = await self._col.aggregate(pipeline_avg).to_list(1)
        avg_info = avg_result[0] if avg_result else {}

        return {
            "total_embeddings": total,
            "embedded": embedded,
            "chapter_embeddings": chapter_count,
            "topic_embeddings": topic_count,
            "thin_embed_text_lt_100_chars": thin_count,
            "chapters_missing_topics": missing_topics,
            "avg_embed_text_length": round(avg_info.get("avg_len", 0), 1),
            "max_embed_text_length": avg_info.get("max_len", 0),
            "min_embed_text_length": avg_info.get("min_len", 0),
            "cache_entries": len(self._cache),
            "similarity_threshold": SIMILARITY_THRESHOLD,
        }

    async def _get_cache(self) -> list[dict]:
        now = time.time()
        if self._cache and (now - self._cache_loaded_at) < CACHE_TTL_SECONDS:
            return self._cache
        if self._col is None:
            return []
        cursor = self._col.find(
            {"embedding": {"$exists": True}},
            {
                "embedding": 1, "board": 1, "class_name": 1, "stream": 1,
                "subject_name": 1, "chapter_title": 1, "chapter_number": 1,
                "subject_id": 1, "chapter_id": 1, "level": 1, "topic": 1,
                "embed_text": 1,
            },
        )
        entries = await cursor.to_list(length=None)
        self._cache = entries
        self._cache_loaded_at = now
        ch_count = sum(1 for e in entries if e.get("level", "chapter") != "topic")
        tp_count = sum(1 for e in entries if e.get("level") == "topic")
        logger.info(f"SyllabusEmbedder cache loaded: {ch_count} chapter + {tp_count} topic embeddings")
        return entries

    async def _seed_chapters(self) -> int:
        try:
            from config import SEED_DATA
            from vertex_services import embed_text
        except ImportError as exc:
            logger.warning(f"Cannot seed — import error: {exc}")
            return 0

        boards   = {b["id"]: b for b in SEED_DATA.get("boards", [])}
        classes_ = {c["id"]: c for c in SEED_DATA.get("classes", [])}
        streams  = {s["id"]: s for s in SEED_DATA.get("streams", [])}
        subjects = {s["id"]: s for s in SEED_DATA.get("subjects", [])}

        existing_ids: set = set()
        async for doc in self._col.find({}, {"chapter_id": 1, "level": 1, "topic": 1}):
            cid = doc.get("chapter_id", "")
            level = doc.get("level", "chapter")
            topic = doc.get("topic", "")
            existing_ids.add(f"{cid}::{level}::{topic}")

        inserted = 0

        try:
            from vertex_services import _EMBED_MODEL as _current_embed_model
        except ImportError:
            _current_embed_model = "unknown"

        for chapter in SEED_DATA.get("chapters", []):
            ch_id   = chapter["id"]
            subj_id = chapter["subject_id"]
            cache_key = f"{ch_id}::chapter::"
            if cache_key in existing_ids:
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
            description   = (chapter.get("description") or "").strip()
            topics: list  = chapter.get("topics") or []

            embed_text_input = _build_rich_embed_text(
                board_name, class_name, stream_name, subject_name,
                chapter_title, description, topics,
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
                "embedding_model": _current_embed_model,
                "level":          "chapter",
                "topics":         topics,
                "description":    description,
                "status":         "active",
                "created_at":     __import__("datetime").datetime.utcnow().isoformat(),
            }
            await self._col.update_one(
                {"chapter_id": ch_id, "level": "chapter"},
                {"$set": doc},
                upsert=True,
            )
            existing_ids.add(cache_key)
            inserted += 1

            inserted += await self._seed_topic_embeddings(
                ch_id, subj_id, board_name, class_name, stream_name,
                subject_name, chapter_title, chapter.get("chapter_number", 0),
                topics, embed_text, _current_embed_model, existing_ids,
            )

            if inserted % 20 == 0:
                logger.info(f"SyllabusEmbedder: {inserted} embeddings so far…")

        try:
            db = self._db
            mongo_subjects: dict = {}
            async for s in db.subjects.find({}, {
                "id": 1, "title": 1, "name": 1,
                "boardName": 1, "className": 1, "streamName": 1,
            }):
                sid = s.get("id") or str(s.get("_id", ""))
                mongo_subjects[sid] = s

            async for chapter in db.chapters.find({}):
                ch_id   = chapter.get("id") or str(chapter.get("_id", ""))
                cache_key = f"{ch_id}::chapter::"
                if cache_key in existing_ids:
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
                content       = (chapter.get("content") or "").strip()

                embed_text_input = _build_rich_embed_text(
                    board_name, class_name, stream_name, subject_name,
                    chapter_title, description, topics, content,
                )

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
                    "embedding_model": _current_embed_model,
                    "level":          "chapter",
                    "description":    description,
                    "topics":         topics,
                    "status":         "active",
                    "source":         "pdf_import",
                    "created_at":     __import__("datetime").datetime.utcnow().isoformat(),
                }
                await self._col.update_one(
                    {"chapter_id": ch_id, "level": "chapter"},
                    {"$set": doc},
                    upsert=True,
                )
                existing_ids.add(cache_key)
                inserted += 1

                inserted += await self._seed_topic_embeddings(
                    ch_id, subj_id, board_name, class_name, stream_name,
                    subject_name, chapter_title, chapter.get("chapter_number", 0),
                    topics, embed_text, _current_embed_model, existing_ids,
                )

                if inserted % 10 == 0:
                    logger.info(f"SyllabusEmbedder: {inserted} embeddings so far (incl. PDF imports)…")

        except Exception as mongo_err:
            logger.warning(f"SyllabusEmbedder: MongoDB chapter seeding failed: {mongo_err}")

        try:
            await self._col.create_index("subject_id")
            await self._col.create_index("board")
            await self._col.create_index("level")
        except Exception as ie:
            logger.debug(f"SyllabusEmbedder: index (non-unique) error (ignored): {ie}")

        try:
            existing_indexes = await self._col.index_information()
            for idx_name, idx_info in existing_indexes.items():
                key = idx_info.get("key", [])
                if key == [("chapter_id", 1)] and idx_info.get("unique"):
                    logger.info(f"SyllabusEmbedder: dropping legacy unique index '{idx_name}' on chapter_id")
                    await self._col.drop_index(idx_name)
                    break
        except Exception as drop_err:
            logger.warning(f"SyllabusEmbedder: legacy index drop failed (non-fatal): {drop_err}")

        try:
            await self._col.create_index(
                [("chapter_id", 1), ("level", 1), ("topic", 1)],
                unique=True,
            )
        except Exception as ie:
            logger.warning(f"SyllabusEmbedder: compound unique index failed ({ie}); deduplicating…")
            try:
                pipeline = [
                    {"$group": {
                        "_id": {"chapter_id": "$chapter_id", "level": "$level", "topic": "$topic"},
                        "ids": {"$push": "$_id"},
                        "count": {"$sum": 1},
                    }},
                    {"$match": {"count": {"$gt": 1}}},
                ]
                async for group in self._col.aggregate(pipeline):
                    to_delete = group["ids"][1:]
                    await self._col.delete_many({"_id": {"$in": to_delete}})
                await self._col.create_index(
                    [("chapter_id", 1), ("level", 1), ("topic", 1)],
                    unique=True,
                )
            except Exception as dedup_err:
                logger.warning(f"SyllabusEmbedder: dedup fallback failed: {dedup_err}")

        logger.info(f"SyllabusEmbedder: seeding complete — {inserted} new embeddings (chapters + topics)")
        return inserted

    async def _seed_topic_embeddings(
        self,
        chapter_id: str,
        subject_id: str,
        board_name: str,
        class_name: str,
        stream_name: str,
        subject_name: str,
        chapter_title: str,
        chapter_number: int,
        topics: list,
        embed_text_fn,
        embed_model: str,
        existing_ids: set,
    ) -> int:
        if not topics:
            return 0

        inserted = 0
        for topic in topics:
            topic_str = str(topic).strip()
            if not topic_str:
                continue

            cache_key = f"{chapter_id}::topic::{topic_str}"
            if cache_key in existing_ids:
                continue

            topic_embed_text = _build_topic_embed_text(
                board_name, class_name, stream_name,
                subject_name, chapter_title, topic_str,
            )

            try:
                vec = await asyncio.wait_for(
                    embed_text_fn(topic_embed_text, task_type="RETRIEVAL_DOCUMENT"),
                    timeout=5.0,
                )
            except Exception as exc:
                logger.warning(f"Topic embed failed for {topic_str[:30]}: {exc}")
                vec = None

            doc = {
                "chapter_id":     chapter_id,
                "subject_id":     subject_id,
                "board":          board_name,
                "class_name":     class_name,
                "stream":         stream_name,
                "subject_name":   subject_name,
                "chapter_title":  chapter_title,
                "chapter_number": chapter_number,
                "level":          "topic",
                "topic":          topic_str,
                "embed_text":     topic_embed_text,
                "embedding":      vec,
                "embedding_model": embed_model,
                "status":         "active",
                "created_at":     __import__("datetime").datetime.utcnow().isoformat(),
            }
            await self._col.update_one(
                {"chapter_id": chapter_id, "level": "topic", "topic": topic_str},
                {"$set": doc},
                upsert=True,
            )
            existing_ids.add(cache_key)
            inserted += 1

        return inserted
