"""D1 Edge Database Sync — export content from MongoDB for D1 ingestion and trigger edge sync."""
import os
import logging
import asyncio
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

_d1_http: Optional["httpx.AsyncClient"] = None

D1_SYNC_SECRET = os.getenv("D1_SYNC_SECRET", "").strip()
EDGE_WORKER_URL = os.getenv("EDGE_WORKER_URL", "https://api.syrabit.ai").strip().rstrip("/")


def _get_http():
    global _d1_http
    if _d1_http is None:
        import httpx
        _d1_http = httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=5))
    return _d1_http


def is_d1_configured() -> bool:
    return bool(D1_SYNC_SECRET and D1_SYNC_SECRET != "REPLACE_WITH_SECURE_RANDOM_SECRET")


async def export_content_catalog(db) -> Dict[str, Any]:
    if db is None:
        return {}

    try:
        boards, classes, streams, subjects, chapters, topics, seo_pages = await asyncio.wait_for(
            asyncio.gather(
                db.boards.find({}, {"_id": 0}).to_list(200),
                db.classes.find({}, {"_id": 0}).to_list(200),
                db.streams.find({}, {"_id": 0}).to_list(500),
                db.subjects.find({"status": "published"}, {"_id": 0}).to_list(1000),
                db.chapters.find({}, {"_id": 0}).sort("order_index", 1).to_list(5000),
                db.topics.find({"status": "published"}, {"_id": 0}).sort("order", 1).to_list(20000),
                db.seo_pages.find(
                    {"status": "published"},
                    {"_id": 0, "id": 1, "slug": 1, "topic_id": 1, "page_type": 1,
                     "status": 1, "title": 1, "meta_description": 1,
                     "html_content": 1, "content": 1,
                     "board_slug": 1, "class_slug": 1, "subject_slug": 1,
                     "chapter_slug": 1, "topic_slug": 1, "word_count": 1,
                     "created_at": 1, "updated_at": 1}
                ).to_list(50000),
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.warning("D1 export: MongoDB query timed out after 30s")
        return {}
    except Exception as e:
        logger.error(f"D1 export error: {e}")
        return {}

    return {
        "boards": boards,
        "classes": classes,
        "streams": streams,
        "subjects": subjects,
        "chapters": chapters,
        "topics": topics,
        "seo_pages": seo_pages,
    }


async def trigger_d1_sync(payload: Dict[str, Any]) -> bool:
    if not is_d1_configured():
        logger.info("D1 sync not configured — skipping")
        return False

    try:
        client = _get_http()
        resp = await client.post(
            f"{EDGE_WORKER_URL}/api/edge/d1-sync",
            json=payload,
            headers={
                "Authorization": f"Bearer {D1_SYNC_SECRET}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                logger.info(f"D1 sync success: {data.get('synced', {})}")
                return True
            logger.warning(f"D1 sync returned errors: {data.get('errors', [])}")
            return False
        logger.warning(f"D1 sync HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.warning(f"D1 sync trigger error: {e}")
        return False


async def sync_full(db) -> Dict[str, Any]:
    payload = await export_content_catalog(db)
    if not payload:
        return {"success": False, "error": "Export returned empty"}
    ok = await trigger_d1_sync(payload)
    return {"success": ok, "tables_exported": list(payload.keys()), "row_counts": {k: len(v) for k, v in payload.items()}}


async def sync_tables(db, tables: List[str]) -> Dict[str, Any]:
    full = await export_content_catalog(db)
    if not full:
        return {"success": False, "error": "Export returned empty"}
    payload = {k: v for k, v in full.items() if k in tables}
    if not payload:
        return {"success": False, "error": f"No matching tables: {tables}"}
    ok = await trigger_d1_sync(payload)
    return {"success": ok, "tables_synced": list(payload.keys()), "row_counts": {k: len(v) for k, v in payload.items()}}
