"""Syrabit.ai — Database seeding logic."""
import uuid, logging
from datetime import datetime, timezone
from config import SEED_DATA, ADMIN_ACCOUNTS
from deps import db, pwd_ctx, is_mongo_available

logger = logging.getLogger(__name__)

from db_ops import supa_get_user, supa_insert_user

_seeded = False

async def ensure_seeded():
    """Seed database with boards/classes/streams - gracefully handles connection failures"""
    global _seeded
    if _seeded:
        return
    
    if not await is_mongo_available():
        return

    # Ensure admin users exist FIRST, independent of the structural-seed
    # early-return below. Without this, adding a new entry to
    # ADMIN_ACCOUNTS (e.g. ENABLE_E2E_ADMIN=true on an existing
    # database) would never insert the row, and login would 401 forever.
    try:
        for admin_acc in ADMIN_ACCOUNTS:
            existing = await supa_get_user(admin_acc["email"])
            if not existing:
                admin_doc = {
                    "id": str(uuid.uuid4()),
                    "name": admin_acc["name"],
                    "email": admin_acc["email"],
                    "password_hash": pwd_ctx.hash(admin_acc["password"]),
                    "plan": "pro",
                    "credits_used": 0,
                    "credits_limit": 4000,
                    "document_access": "full",
                    "onboarding_done": True,
                    "is_admin": True,
                    "status": "active",
                    "bio": "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await supa_insert_user(admin_doc)
                logger.info(f"Seeded admin user: {admin_acc['email']}")
    except Exception as e:
        logger.warning(f"Admin-account seed pass failed (non-fatal): {e}")

    try:
        ahsec_exists  = await db.boards.find_one({"id": "b1"})
        degree_exists = await db.boards.find_one({"id": "b2"})
        seba_exists   = await db.boards.find_one({"id": "b3"})
        seba_class_exists   = await db.classes.find_one({"board_id": "b3"})
        seba_stream_exists  = await db.streams.find_one({"class_id": {"$in": ["c5", "c6"]}})
        fyugp_class_exists  = await db.classes.find_one({"id": {"$in": ["c7", "c8", "c9", "c10"]}})
        fyugp_stream_exists = await db.streams.find_one({"id": {"$in": ["s30", "s36", "s42", "s48"]}})
        ch_count = await db.chapters.count_documents({})
        expected_ch = len(SEED_DATA["chapters"])
        # Check for non-canonical boards (would need cleanup)
        total_boards = await db.boards.count_documents({})
        canonical_count = 3  # b1, b2, b3
        all_canonical = (total_boards <= canonical_count)
        # Check for duplicate classes (e.g. cls_b2_semester-1 AND c7 both slug=semester-1)
        has_dupes = await db.classes.find_one(
            {"id": {"$nin": [c["id"] for c in SEED_DATA["classes"]]},
             "slug": {"$in": ["semester-1","semester-2","semester-3","semester-4"]},
             "board_id": "b2"}
        )
        if (ahsec_exists and degree_exists and seba_exists and
                seba_class_exists and seba_stream_exists and
                fyugp_class_exists and fyugp_stream_exists and
                ch_count >= expected_ch and all_canonical and not has_dupes):
            _seeded = True
            return
    except Exception as e:
        logger.warning(f"Database not available for seeding: {e}")
        return
    logger.info("Seeding structural data (boards/classes/streams only — subjects/chapters managed via Admin)...")
    from pymongo import ReplaceOne
    # Enforce structural skeleton — boards/classes/streams only
    # Subjects and chapters are managed entirely via Admin panel uploads
    canonical_board_ids  = {b["id"] for b in SEED_DATA["boards"]}
    canonical_class_ids  = {c["id"] for c in SEED_DATA["classes"]}
    # Only prune boards whose ID isn't canonical
    await db.boards.delete_many({"id": {"$nin": list(canonical_board_ids)}})
    # Only prune classes whose board isn't canonical (keeps dynamically created DEGREE/AHSEC/SEBA classes)
    await db.classes.delete_many({"board_id": {"$nin": list(canonical_board_ids)}})
    # Protect streams belonging to any class under a canonical board (not just seeded classes)
    dynamic_class_docs = await db.classes.find(
        {"board_id": {"$in": list(canonical_board_ids)}}, {"id": 1}
    ).to_list(2000)
    all_protected_class_ids = canonical_class_ids | {c["id"] for c in dynamic_class_docs}
    await db.streams.delete_many({"class_id": {"$nin": list(all_protected_class_ids)}})
    # NOTE: Do NOT delete subjects or chapters here — they are user-managed
    if SEED_DATA["boards"]:
        ops = [ReplaceOne({"id": b["id"]}, b, upsert=True) for b in SEED_DATA["boards"]]
        await db.boards.bulk_write(ops, ordered=False)
    if SEED_DATA["classes"]:
        ops = [ReplaceOne({"id": c["id"]}, c, upsert=True) for c in SEED_DATA["classes"]]
        await db.classes.bulk_write(ops, ordered=False)
    if SEED_DATA["streams"]:
        ops = [ReplaceOne({"id": s["id"]}, s, upsert=True) for s in SEED_DATA["streams"]]
        await db.streams.bulk_write(ops, ordered=False)
    # ── Deduplicate: remove old dynamically-created classes that share slug+board_id
    # with a canonical class (e.g. cls_b2_semester-1 vs c7 both have slug=semester-1, board_id=b2)
    canonical_class_ids_set = {c["id"] for c in SEED_DATA["classes"]}
    for canon_cls in SEED_DATA["classes"]:
        dupe_docs = await db.classes.find(
            {"board_id": canon_cls["board_id"], "slug": canon_cls["slug"],
             "id": {"$ne": canon_cls["id"]}},
            {"id": 1}
        ).to_list(100)
        for dupe in dupe_docs:
            dupe_id = dupe["id"]
            # Re-point all streams under the dupe class to the canonical class
            dupe_streams = await db.streams.find({"class_id": dupe_id}, {"id": 1, "slug": 1}).to_list(100)
            for dupe_stream in dupe_streams:
                # Check if a canonical stream with same slug exists under canonical class
                canon_stream = await db.streams.find_one(
                    {"class_id": canon_cls["id"], "slug": dupe_stream["slug"]}, {"id": 1}
                )
                if canon_stream:
                    # Move subjects from dupe stream to canonical stream
                    await db.subjects.update_many(
                        {"stream_id": dupe_stream["id"]},
                        {"$set": {"stream_id": canon_stream["id"],
                                  "class_slug": canon_cls["slug"],
                                  "class_id": canon_cls["id"]}}
                    )
                    await db.streams.delete_one({"id": dupe_stream["id"]})
            # Remove the dupe class
            await db.classes.delete_one({"id": dupe_id})
            logger.info(f"Dedup: removed duplicate class {dupe_id} (same as {canon_cls['id']})")
    # Ensure admin user exists for each admin account in ADMIN_ACCOUNTS
    for admin_acc in ADMIN_ACCOUNTS:
        existing = await supa_get_user(admin_acc["email"])
        if not existing:
            admin_doc = {
                "id": str(uuid.uuid4()),
                "name": admin_acc["name"],
                "email": admin_acc["email"],
                "password_hash": pwd_ctx.hash(admin_acc["password"]),
                "plan": "pro",
                "credits_used": 0,
                "credits_limit": 4000,
                "document_access": "full",
                "onboarding_done": True,
                "is_admin": True,
                "status": "active",
                "bio": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await supa_insert_user(admin_doc)
            logger.info(f"Seeded admin user: {admin_acc['email']}")
    _seeded = True
    logger.info("Content seeded successfully")
