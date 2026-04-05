"""
Syrabit.ai — Category-gated RAG router.

Decides whether RAG should be triggered based on intent and embedding score,
and filters RAG chunks by their category metadata to eliminate cross-category noise.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

RAG_RELEVANCE_GATE = 0.55
HIGH_CONFIDENCE_THRESHOLD = 0.60

_RAG_INTENTS = frozenset({"notes", "important_questions", "pyq"})

_SKIP_RAG_INTENTS = frozenset({"casual", "syllabus"})


def should_trigger_rag(intent: str, embedding_score: float = 0.0) -> bool:
    if intent in _SKIP_RAG_INTENTS:
        logger.info(f"RAG router: skip RAG for intent={intent}")
        return False

    if intent in _RAG_INTENTS:
        if embedding_score >= RAG_RELEVANCE_GATE:
            logger.info(f"RAG router: trigger RAG for intent={intent}, score={embedding_score:.3f} >= {RAG_RELEVANCE_GATE}")
            return True
        else:
            logger.info(f"RAG router: skip RAG for intent={intent}, score={embedding_score:.3f} < {RAG_RELEVANCE_GATE}")
            return False

    if embedding_score >= RAG_RELEVANCE_GATE:
        return True

    logger.info(f"RAG router: skip RAG for intent={intent}, score={embedding_score:.3f} below gate")
    return False


def filter_rag_by_category(chunks: list, db_category: Optional[str]) -> list:
    if not db_category or not chunks:
        return chunks

    filtered = []
    for chunk in chunks:
        chunk_cat = chunk.get("category") or chunk.get("content_type") or ""
        if chunk_cat == db_category:
            filtered.append(chunk)

    if not filtered and chunks:
        logger.info(f"RAG router: category filter '{db_category}' removed all {len(chunks)} chunks — no cross-category fallback")

    logger.info(f"RAG router: category filter '{db_category}' kept {len(filtered)}/{len(chunks)} chunks")
    return filtered
