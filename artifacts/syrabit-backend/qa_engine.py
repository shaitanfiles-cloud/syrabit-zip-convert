"""
Syrabit.ai — Phase 2: Chat Logging + QA Pairs Engine

Collections:
  - chat_messages:  Every Q+A turn from the AI chat (for QA curation)
  - qa_pairs:       Curated, publishable Q&A pairs linked to SEO topic pages

Public routes  (prefix /seo):
  GET  /seo/qa/{board}/{class_slug}/{subject_slug}/{topic_slug}

Admin routes   (prefix /admin):
  GET  /admin/chat-messages
  GET  /admin/qa
  POST /admin/qa
  POST /admin/qa/from-chat/{msg_id}
  PATCH /admin/qa/{qa_id}/status
  DELETE /admin/qa/{qa_id}
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from typing import Any, Callable, Coroutine, Optional
from datetime import datetime, timezone
import uuid, logging

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/seo",   tags=["QA Public"])
admin_router  = APIRouter(prefix="/admin", tags=["QA Admin"])

_db: Optional[AsyncIOMotorDatabase] = None
_get_admin_fn: Optional[Callable[..., Coroutine[Any, Any, dict]]] = None
_security = HTTPBearer(auto_error=False)


def init_qa_engine(db: AsyncIOMotorDatabase, get_admin_user_fn: Callable):
    global _db, _get_admin_fn
    _db = db
    _get_admin_fn = get_admin_user_fn


async def _require_admin(creds: Optional[HTTPAuthorizationCredentials] = Depends(_security)):
    if _get_admin_fn is None:
        raise HTTPException(status_code=503, detail="Auth not initialized")
    return await _get_admin_fn(creds=creds)


# ── Pydantic models ────────────────────────────────────────────────────────────

class QaPairCreate(BaseModel):
    question: str
    answer: str
    board_slug: Optional[str] = ""
    class_slug: Optional[str] = ""
    subject_slug: Optional[str] = ""
    topic_slug: Optional[str] = ""
    language: str = "en"


class QaStatusUpdate(BaseModel):
    status: str  # "published" | "draft" | "deleted"


# ── Helpers ────────────────────────────────────────────────────────────────────

async def log_chat_message(
    *,
    user_id: str,
    question: str,
    raw_ai_answer: str,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    board_name: Optional[str] = None,
    class_name: Optional[str] = None,
    conversation_id: Optional[str] = None,
):
    """Fire-and-forget: persist a chat turn to chat_messages for QA curation."""
    if _db is None:
        return
    try:
        doc = {
            "id": str(uuid.uuid4()),
            "session_id": conversation_id or str(uuid.uuid4()),
            "user_id": user_id,
            "question": question[:2000],
            "raw_ai_answer": raw_ai_answer[:4000],
            "subject_id": subject_id or "",
            "subject_name": subject_name or "",
            "board_name": board_name or "",
            "class_name": class_name or "",
            "is_promoted": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _db.chat_messages.insert_one(doc)
    except Exception as e:
        logger.warning(f"log_chat_message failed: {e}")


async def ensure_qa_indexes():
    """Create indexes on qa_pairs and chat_messages if not already present."""
    if _db is None:
        return
    try:
        await _db.qa_pairs.create_index(
            [("board_slug", 1), ("class_slug", 1), ("subject_slug", 1), ("topic_slug", 1)]
        )
        await _db.qa_pairs.create_index([("status", 1)])
        await _db.chat_messages.create_index([("timestamp", -1)])
        await _db.chat_messages.create_index([("subject_id", 1)])
        await _db.chat_messages.create_index([("is_promoted", 1)])
        logger.info("QA engine indexes ensured")
    except Exception as e:
        logger.warning(f"ensure_qa_indexes failed: {e}")


# ── Public routes ──────────────────────────────────────────────────────────────

@public_router.get("/qa/{board}/{class_slug}/{subject_slug}/{topic_slug}")
async def get_topic_qa(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    """Return published QA pairs for a topic page (used by SeoTopicPage)."""
    if _db is None:
        return {"qa_pairs": [], "total": 0}
    pairs = await _db.qa_pairs.find(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "topic_slug": topic_slug,
            "status": "published",
        },
        {"_id": 0},
    ).sort("upvotes", -1).limit(20).to_list(20)
    return {"qa_pairs": pairs, "total": len(pairs)}


# ── Admin routes ───────────────────────────────────────────────────────────────

@admin_router.get("/chat-messages")
async def list_chat_messages(
    limit: int = 50,
    subject_id: Optional[str] = None,
    promoted: Optional[bool] = None,
    search: Optional[str] = None,
    _admin: dict = Depends(_require_admin),
):
    """List recent chat messages for QA curation (admin only)."""
    query: dict = {}
    if subject_id:
        query["subject_id"] = subject_id
    if promoted is not None:
        query["is_promoted"] = promoted
    if search:
        query["$or"] = [
            {"question": {"$regex": search, "$options": "i"}},
            {"subject_name": {"$regex": search, "$options": "i"}},
        ]
    msgs = await _db.chat_messages.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return {"messages": msgs, "total": len(msgs)}


@admin_router.get("/qa")
async def list_qa_pairs(
    status: Optional[str] = None,
    board: Optional[str] = None,
    topic_slug: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    _admin: dict = Depends(_require_admin),
):
    """List all QA pairs with optional filters (admin only)."""
    query: dict = {}
    if status:
        query["status"] = status
    if board:
        query["board_slug"] = board
    if topic_slug:
        query["topic_slug"] = topic_slug
    if search:
        query["$or"] = [
            {"question": {"$regex": search, "$options": "i"}},
            {"answer": {"$regex": search, "$options": "i"}},
        ]
    pairs = await _db.qa_pairs.find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"qa_pairs": pairs, "total": len(pairs)}


@admin_router.post("/qa")
async def create_qa_pair(body: QaPairCreate, _admin: dict = Depends(_require_admin)):
    """Manually create a QA pair (admin only)."""
    doc = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "status": "draft",
        "upvotes": 0,
        "views": 0,
        "is_promoted": False,
        "source": "manual",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "published_at": None,
    }
    await _db.qa_pairs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@admin_router.post("/qa/from-chat/{msg_id}")
async def promote_chat_to_qa(msg_id: str, _admin: dict = Depends(_require_admin)):
    """Promote a chat_message to a draft QA pair (admin only)."""
    msg = await _db.chat_messages.find_one({"id": msg_id}, {"_id": 0})
    if not msg:
        raise HTTPException(status_code=404, detail="Chat message not found")
    if msg.get("is_promoted"):
        raise HTTPException(status_code=409, detail="Already promoted to QA pair")

    doc = {
        "id": str(uuid.uuid4()),
        "question": msg["question"],
        "answer": msg["raw_ai_answer"],
        "board_slug": "",
        "class_slug": "",
        "subject_slug": "",
        "topic_slug": "",
        "subject_name": msg.get("subject_name", ""),
        "language": "en",
        "status": "draft",
        "upvotes": 0,
        "views": 0,
        "is_promoted": True,
        "source_chat_id": msg_id,
        "source": "chat",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "published_at": None,
    }
    await _db.qa_pairs.insert_one(doc)
    doc.pop("_id", None)
    await _db.chat_messages.update_one({"id": msg_id}, {"$set": {"is_promoted": True}})
    return doc


@admin_router.patch("/qa/{qa_id}/status")
async def update_qa_status(qa_id: str, body: QaStatusUpdate, _admin: dict = Depends(_require_admin)):
    """Publish, unpublish, or mark deleted (admin only)."""
    if body.status not in ("published", "draft", "deleted"):
        raise HTTPException(status_code=400, detail="status must be published, draft, or deleted")
    update = {"status": body.status}
    if body.status == "published":
        update["published_at"] = datetime.now(timezone.utc).isoformat()
    result = await _db.qa_pairs.update_one({"id": qa_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="QA pair not found")
    return {"ok": True, "status": body.status}


@admin_router.delete("/qa/{qa_id}")
async def delete_qa_pair(qa_id: str, _admin: dict = Depends(_require_admin)):
    """Hard-delete a QA pair (admin only)."""
    result = await _db.qa_pairs.delete_one({"id": qa_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="QA pair not found")
    return {"ok": True}
