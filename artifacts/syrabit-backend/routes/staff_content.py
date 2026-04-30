"""Staff content management routes.

Staff users (role == 'staff') can read all content and update chapter
notes / description / status. They cannot create or delete subjects,
boards, classes, or streams (those remain admin-only operations).
"""

import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth_deps import get_staff_user
from deps import db, pwd_ctx
import nh3 as _nh3

router = APIRouter()


# ── Auth ─────────────────────────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/staff/auth/change-password")
async def staff_change_password(
    data: ChangePasswordRequest,
    staff: dict = Depends(get_staff_user),
):
    """Allow a staff member to change their own password.

    Verifies the current password before writing the new bcrypt hash.
    Minimum 8 characters enforced server-side.
    """
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    user = await db.users.find_one({"id": staff["id"]}, {"_id": 0, "password_hash": 1})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    pw_hash = user.get("password_hash", "")
    if not pw_hash or not await asyncio.to_thread(pwd_ctx.verify, data.current_password, pw_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_hash = await asyncio.to_thread(pwd_ctx.hash, data.new_password)
    await db.users.update_one(
        {"id": staff["id"]},
        {"$set": {"password_hash": new_hash, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"message": "Password changed successfully"}


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

_SAFE_MD_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "del", "div", "em",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd",
    "li", "mark", "ol", "p", "pre", "q", "s", "small", "span", "strike",
    "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "u", "ul",
}

_SAFE_MD_ATTRS = {
    "*": {"id", "class"},
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "width", "height", "loading"},
    "td": {"colspan", "rowspan", "align"},
    "th": {"colspan", "rowspan", "align", "scope"},
}


def _sanitize_markdown_content(text: str) -> str:
    """Strip dangerous HTML embedded in markdown before storing.

    This is a defense-in-depth measure. The frontend also refuses to execute
    raw HTML in markdown (rehypeRaw removed), but we strip dangerous tags at
    write time so the stored value is clean regardless of the renderer.
    """
    if not text:
        return text
    return _nh3.clean(
        text,
        tags=_SAFE_MD_TAGS,
        attributes=_SAFE_MD_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel=None,
        strip_comments=True,
    )


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

    if "content" in allowed and isinstance(allowed["content"], str):
        allowed["content"] = _sanitize_markdown_content(allowed["content"])

    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    allowed["updated_by_staff"] = staff.get("id", "")

    result = await db.chapters.update_one({"id": chapter_id}, {"$set": allowed})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chapter not found")

    updated = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    return {"message": "Chapter updated", "chapter": updated}
