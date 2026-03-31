"""Syrabit.ai — Referral share tracking routes"""
import uuid, logging, string, secrets, re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Body, Depends, Request
from fastapi.responses import RedirectResponse
from pymongo.errors import DuplicateKeyError

from config import FRONTEND_URL
import deps as _deps_mod
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


def _base_url() -> str:
    return FRONTEND_URL or "https://syrabit.ai"


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
            "unique_clicks": 0,
            "visitors": [],
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

    base = _base_url()
    logger.info(f"Share created: code={code} subject={subject_id} user={user_id}")
    return {"code": code, "referral_url": f"{base}/r/{code}"}


@router.get("/admin/analytics/shares")
async def get_share_analytics(
    days: int = 30,
    admin: dict = Depends(get_admin_user),
):
    if not await is_mongo_available():
        return {
            "total_shares": 0, "total_clicks": 0, "unique_clicks": 0,
            "conversions": 0, "subjects": [], "daily": [],
        }

    try:
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        start_iso = start_date.isoformat()

        total_shares = await db.shares.count_documents({"created_at": {"$gte": start_iso}})

        click_pipeline = [
            {"$match": {"created_at": {"$gte": start_iso}}},
            {"$group": {
                "_id": None,
                "total_clicks": {"$sum": "$click_count"},
                "unique_clicks": {"$sum": {"$ifNull": ["$unique_clicks", 0]}},
            }},
        ]
        click_result = await db.shares.aggregate(click_pipeline).to_list(1)
        total_clicks = click_result[0]["total_clicks"] if click_result else 0
        unique_clicks = click_result[0]["unique_clicks"] if click_result else 0

        subject_pipeline = [
            {"$match": {"created_at": {"$gte": start_iso}}},
            {"$group": {
                "_id": "$subject_id",
                "subject_name": {"$first": "$subject_name"},
                "shares": {"$sum": 1},
                "clicks": {"$sum": "$click_count"},
                "unique_clicks": {"$sum": {"$ifNull": ["$unique_clicks", 0]}},
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
                "unique_clicks": r.get("unique_clicks", 0),
            }
            for r in subject_rows
        ]

        daily_pipeline = [
            {"$match": {"created_at": {"$gte": start_iso}}},
            {"$addFields": {"date_str": {"$substr": ["$created_at", 0, 10]}}},
            {"$group": {
                "_id": "$date_str",
                "shares": {"$sum": 1},
                "clicks": {"$sum": "$click_count"},
                "unique_clicks": {"$sum": {"$ifNull": ["$unique_clicks", 0]}},
            }},
            {"$sort": {"_id": 1}},
        ]
        daily_rows = await db.shares.aggregate(daily_pipeline).to_list(days + 1)
        daily = [
            {"date": r["_id"], "shares": r["shares"], "clicks": r["clicks"], "unique_clicks": r.get("unique_clicks", 0)}
            for r in daily_rows
        ]

        conversions = 0
        if _deps_mod.pg_pool:
            try:
                async with _deps_mod.pg_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT COUNT(*) AS cnt FROM users WHERE referred_by_code IS NOT NULL AND created_at >= $1",
                        start_iso,
                    )
                    conversions = row["cnt"] if row else 0
            except Exception:
                pass
        else:
            try:
                conversions = await db.users.count_documents({
                    "referred_by_code": {"$ne": None, "$exists": True},
                    "created_at": {"$gte": start_iso},
                })
            except Exception:
                pass

        return {
            "total_shares": total_shares,
            "total_clicks": total_clicks,
            "unique_clicks": unique_clicks,
            "conversions": conversions,
            "subjects": subjects,
            "daily": daily,
        }
    except Exception as e:
        logger.error(f"Share analytics error: {e}")
        return {
            "total_shares": 0, "total_clicks": 0, "unique_clicks": 0,
            "conversions": 0, "subjects": [], "daily": [],
        }


share_redirect_router = APIRouter()


@share_redirect_router.get("/r/{code}")
async def referral_redirect(code: str, request: Request):
    if not await is_mongo_available():
        return RedirectResponse(url="/", status_code=302)

    share = await db.shares.find_one({"code": code})
    if not share:
        return RedirectResponse(url="/", status_code=302)

    visitor_id = request.cookies.get("syrabit_vid")
    is_new_visitor = False
    if not visitor_id:
        visitor_id = str(uuid.uuid4())
        is_new_visitor = True

    existing_visitors = share.get("visitors") or []
    is_unique = visitor_id not in existing_visitors

    update_ops = {
        "$inc": {"click_count": 1},
        "$set": {"last_clicked_at": datetime.now(timezone.utc).isoformat()},
    }
    if is_unique:
        update_ops["$inc"]["unique_clicks"] = 1
        update_ops["$addToSet"] = {"visitors": visitor_id}

    await db.shares.update_one({"code": code}, update_ops)

    target_path = _sanitize_path(share.get("subject_path") or "/")
    separator = "&" if "?" in target_path else "?"
    redirect_url = f"{target_path}{separator}ref={code}"

    redirect_response = RedirectResponse(url=redirect_url, status_code=302)
    if is_new_visitor:
        redirect_response.set_cookie(
            key="syrabit_vid",
            value=visitor_id,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="lax",
        )
    return redirect_response
