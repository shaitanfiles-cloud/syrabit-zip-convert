"""Syrabit.ai — Syllabus read + embedding admin routes"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from auth_deps import get_admin_user
from deps import db, is_mongo_available

logger = logging.getLogger(__name__)

def _get_syllabus_embedder():
    import server as _s
    return _s._syllabus_embedder

router = APIRouter()


@router.get("/syllabi/{board_id}/{class_id}")
async def get_syllabus(board_id: str, class_id: str):
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": {"$exists": False}}, {"_id": 0})
        if not syllabus:
            syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        if syllabus:
            return syllabus
        return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "content": "", "chapters": [], "topics": [], "found": False}


@router.get("/syllabi/{board_id}/{class_id}/{stream_id}")
async def get_syllabus_stream(board_id: str, class_id: str, stream_id: str):
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": {"$exists": False}}, {"_id": 0})
        if not syllabus:
            syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id}, {"_id": 0})
        if not syllabus:
            syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        if syllabus:
            return syllabus
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get stream syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "content": "", "chapters": [], "topics": [], "found": False}


@router.get("/syllabi/{board_id}/{class_id}/{stream_id}/{subject_id}")
async def get_syllabus_subject(board_id: str, class_id: str, stream_id: str, subject_id: str):
    try:
        if not await is_mongo_available():
            return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}
        syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id}, {"_id": 0})
        if not syllabus:
            syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id, "stream_id": stream_id}, {"_id": 0})
        if not syllabus:
            syllabus = await db.syllabi.find_one({"board_id": board_id, "class_id": class_id}, {"_id": 0})
        if syllabus:
            return syllabus
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}
    except Exception as e:
        logger.error(f"Get subject syllabus error: {e}")
        return {"board_id": board_id, "class_id": class_id, "stream_id": stream_id, "subject_id": subject_id, "content": "", "chapters": [], "topics": [], "found": False}


# ─────────────────────────────────────────────
# SYLLABUS EMBEDDER — admin endpoints
# ─────────────────────────────────────────────

@router.post("/admin/syllabus/seed-embeddings")
async def admin_seed_syllabus_embeddings(
    admin: dict = Depends(get_admin_user),
    full: bool = Query(False, description="If true, drops all embeddings and re-embeds from scratch"),
):
    """
    Force re-embed of all chapters + topics into the `syllabus_embeddings`
    collection. Use ?full=true to drop existing and rebuild from scratch
    (required after upgrading to enriched embed text / topic-level embeddings).
    Without ?full, only new/missing chapters are embedded incrementally.
    """
    emb = _get_syllabus_embedder()
    if emb is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")
    if full:
        return await emb.full_reseed()
    return await emb.reseed()


@router.post("/admin/syllabus/full-reseed")
async def admin_full_reseed_embeddings(admin: dict = Depends(get_admin_user)):
    """Drop all syllabus embeddings and re-embed everything from scratch with enriched text."""
    emb = _get_syllabus_embedder()
    if emb is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")
    return await emb.full_reseed()


@router.get("/admin/syllabus/embedding-stats")
async def admin_syllabus_embedding_stats(admin: dict = Depends(get_admin_user)):
    """Return detailed stats: total/chapter/topic embeddings, thin embed text, missing topics, avg lengths."""
    emb = _get_syllabus_embedder()
    if emb is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")
    return await emb.stats()


@router.get("/admin/syllabus/test-classify")
async def admin_test_classify(
    q: str = Query(..., description="Query to test against the embedding space"),
    top_n: int = Query(5, ge=1, le=20),
    admin: dict = Depends(get_admin_user),
):
    """
    Diagnostic endpoint: test a query against the syllabus embedding space.
    Returns top-N matches with similarity scores, embed text previews,
    and whether each would pass the classification threshold.
    """
    emb = _get_syllabus_embedder()
    if emb is None:
        raise HTTPException(status_code=503, detail="SyllabusEmbedder not initialised (MongoDB unavailable)")

    from syllabus_embedder import SIMILARITY_THRESHOLD

    results = await emb.classify_top_n(q, top_n=top_n)
    best_match = await emb.classify(q)

    return {
        "query": q,
        "threshold": SIMILARITY_THRESHOLD,
        "best_match": {
            "subject": best_match.subject_name,
            "chapter": best_match.chapter_title,
            "level": best_match.level,
            "topic": best_match.topic,
            "similarity": best_match.similarity,
        } if best_match else None,
        "top_n": results,
    }


# ─────────────────────────────────────────────
# AI CHAT ROUTES
# ─────────────────────────────────────────────

