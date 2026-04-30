"""Staff content management routes.

Staff users (role == 'staff') can read all content and update chapter
notes / description / status. They cannot create or delete subjects,
boards, classes, or streams (those remain admin-only operations).
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from auth_deps import get_staff_user
from deps import db

router = APIRouter()


# ── Taxonomy reads ──────────────────────────────────────────────────────────

@router.get("/staff/content/boards")
async def staff_list_boards(staff: dict = Depends(get_staff_user)):
    boards = await db.boards.find({}, {"_id": 0}).to_list(500)
    return boards


@router.get("/staff/content/classes")
async def staff_list_classes(staff: dict = Depends(get_staff_user)):
    classes = await db.classes.find({}, {"_id": 0}).to_list(1000)
    return classes


@router.get("/staff/content/streams")
async def staff_list_streams(staff: dict = Depends(get_staff_user)):
    streams = await db.streams.find({}, {"_id": 0}).to_list(1000)
    return streams


@router.get("/staff/content/subjects")
async def staff_list_subjects(staff: dict = Depends(get_staff_user)):
    subjects = await db.subjects.find({}, {"_id": 0}).to_list(2000)
    for s in subjects:
        if "thumbnail_url" in s and "thumbnailUrl" not in s:
            s["thumbnailUrl"] = s.pop("thumbnail_url")
    return subjects


# ── Chapter reads ───────────────────────────────────────────────────────────

@router.get("/staff/content/chapters/{subject_id}")
async def staff_list_chapters(subject_id: str, staff: dict = Depends(get_staff_user)):
    chapters = await db.chapters.find(
        {"subject_id": subject_id},
        {"_id": 0}
    ).sort("order_index", 1).to_list(500)
    return chapters


@router.get("/staff/content/chapter/{chapter_id}")
async def staff_get_chapter(chapter_id: str, staff: dict = Depends(get_staff_user)):
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


# ── Chapter write (limited field set) ──────────────────────────────────────

_STAFF_EDITABLE_FIELDS = {"title", "description", "content", "status"}


@router.patch("/staff/content/chapter/{chapter_id}")
async def staff_update_chapter(
    chapter_id: str,
    data: dict,
    staff: dict = Depends(get_staff_user),
):
    """Update chapter fields. Staff may only touch title / description /
    content / status.  Content rechunking and IndexNow pings are admin
    operations and are not triggered here."""
    allowed = {k: v for k, v in data.items() if k in _STAFF_EDITABLE_FIELDS}
    if not allowed:
        raise HTTPException(status_code=400, detail="No editable fields provided")

    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    allowed["updated_by_staff"] = staff.get("id", "")

    result = await db.chapters.update_one({"id": chapter_id}, {"$set": allowed})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chapter not found")

    updated = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    return {"message": "Chapter updated", "chapter": updated}
