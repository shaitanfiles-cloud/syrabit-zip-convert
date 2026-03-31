"""Syrabit.ai — Referral share tracking routes"""
import uuid, logging, string, secrets, re
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Body, Depends, Request
from fastapi.responses import RedirectResponse
from pymongo.errors import DuplicateKeyError

from deps import db, is_mongo_available
from auth_deps import get_current_user_optional, get_admin_user

logger = logging.getLogger(__name__)

router = APIRouter()

_CODE_CHARS = string.ascii_lowercase + string.digits
_CODE_LENGTH = 7

_SAFE_PATH_RE = re.compile(r"^/[a-zA-Z0-9_.~:/?#\[\]@!$&'()*+,;=%-]+$")


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LENGTH))


def _sanitize_path(path: str) -> str:
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/"
    if not _SAFE_PATH_RE.match(path):
        return "/"
    return path


@router.post("/shares")
async def create_share(
    subject_id: str = Body(..., max_length=200),
    subject_name: str = Body("", max_length=500),
    subject_path: str = Body("", max_length=500),
    user: dict = Depends(get_current_user_optional),
):
    if not await is_mongo_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    user_id = user.get("id") if user else None
    safe_path = _sanitize_path(subject_path)

    for attempt in range(10):
        code = _generate_code()
        share_doc = {
            "id": str(uuid.uuid4()),
            "code": code,
            "subject_id": subject_id,
            "subject_name": subject_name[:500],
            "subject_path": safe_path,
            "user_id": user_id,
            "share_count": 1,
            "click_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_clicked_at": None,
        }
        try:
            await db.shares.insert_one(share_doc)
            break
        except DuplicateKeyError:
            if attempt == 9:
                raise HTTPException(status_code=503, detail="Failed to generate unique share code")
            continue

    logger.info(f"Share created: code={code} subject={subject_id} user={user_id}")
    return {"code": code, "referral_url": f"https://syrabit.ai/r/{code}"}


@router.get("/admin/analytics/shares")
async def get_share_analytics(
    days: int = 30,
    admin: dict = Depends(get_admin_user),
):
    if not await is_mongo_available():
        return {"total_shares": 0, "total_clicks": 0, "subjects": []}

    try:
        from datetime import timedelta
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        start_iso = start_date.isoformat()

        total_shares = await db.shares.count_documents({"created_at": {"$gte": start_iso}})

        click_pipeline = [
            {"$match": {"created_at": {"$gte": start_iso}}},
            {"$group": {"_id": None, "total_clicks": {"$sum": "$click_count"}}},
        ]
        click_result = await db.shares.aggregate(click_pipeline).to_list(1)
        total_clicks = click_result[0]["total_clicks"] if click_result else 0

        subject_pipeline = [
            {"$match": {"created_at": {"$gte": start_iso}}},
            {"$group": {
                "_id": "$subject_id",
                "subject_name": {"$first": "$subject_name"},
                "shares": {"$sum": 1},
                "clicks": {"$sum": "$click_count"},
            }},
            {"$sort": {"shares": -1}},
            {"$limit": 20},
        ]
        subject_rows = await db.shares.aggregate(subject_pipeline).to_list(20)

        subjects = [
            {
                "subject_id": r["_id"],
                "name": r.get("subject_name") or "Unknown",
                "shares": r["shares"],
                "clicks": r["clicks"],
            }
            for r in subject_rows
        ]

        return {
            "total_shares": total_shares,
            "total_clicks": total_clicks,
            "subjects": subjects,
        }
    except Exception as e:
        logger.error(f"Share analytics error: {e}")
        return {"total_shares": 0, "total_clicks": 0, "subjects": []}


share_redirect_router = APIRouter()


@share_redirect_router.get("/r/{code}")
async def referral_redirect(code: str):
    if not await is_mongo_available():
        return RedirectResponse(url="/", status_code=302)

    share = await db.shares.find_one({"code": code})
    if not share:
        return RedirectResponse(url="/", status_code=302)

    await db.shares.update_one(
        {"code": code},
        {
            "$inc": {"click_count": 1},
            "$set": {"last_clicked_at": datetime.now(timezone.utc).isoformat()},
        },
    )

    target_path = _sanitize_path(share.get("subject_path") or "/")
    return RedirectResponse(url=target_path, status_code=302)
