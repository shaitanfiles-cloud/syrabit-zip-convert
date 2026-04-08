"""One-off MongoDB cleanup script — drops non-essential collections & frees storage.

Usage: python db_cleanup.py
Keeps analytics collections per user request.
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, DB_NAME

COLLECTIONS_TO_DROP = [
    "conversations", "chat_messages",
    "seo_pages", "cms_documents", "qa_pairs", "topics",
    "pyq_uploads", "pyq_html_pages", "topic_pyq_collections", "ai_pyq_collections",
    "flashcard_collections", "syllabus_embeddings", "content_uploads",
    "payments", "refund_requests",
    "roadmap", "exam_schedule", "push_subscriptions", "alerts", "rate_policies",
]

CORE_COLLECTIONS = [
    "boards", "classes", "streams", "subjects", "chapters", "syllabi", "chunks",
    "users", "api_config", "settings",
    "analytics", "analytics_daily_totals", "page_views", "server_hits", "sessions", "pwa_installs",
]


async def get_collection_stats(db, name):
    try:
        stats = await db.command("collStats", name)
        return {
            "name": name,
            "count": stats.get("count", 0),
            "size_bytes": stats.get("size", 0),
            "storage_bytes": stats.get("storageSize", 0),
            "index_bytes": stats.get("totalIndexSize", 0),
        }
    except Exception as e:
        return {"name": name, "count": 0, "size_bytes": 0, "storage_bytes": 0, "index_bytes": 0, "error": str(e)}


def fmt(b):
    if b >= 1024**2:
        return f"{b / 1024**2:.2f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


async def trim_retained_collections(db):
    """Remove orphaned/stale records from retained collections."""
    trimmed = {}

    valid_chapter_ids = set()
    async for ch in db.chapters.find({}, {"id": 1}):
        valid_chapter_ids.add(ch.get("id"))

    if valid_chapter_ids:
        result = await db.chunks.delete_many({
            "chapter_id": {"$nin": list(valid_chapter_ids), "$exists": True, "$ne": None}
        })
        if result.deleted_count:
            trimmed["chunks (orphaned chapter refs)"] = result.deleted_count

    valid_subject_ids = set()
    async for s in db.subjects.find({}, {"id": 1}):
        valid_subject_ids.add(s.get("id"))

    if valid_subject_ids:
        result = await db.chunks.delete_many({
            "subject_id": {"$nin": list(valid_subject_ids), "$exists": True, "$ne": None}
        })
        if result.deleted_count:
            trimmed["chunks (orphaned subject refs)"] = result.deleted_count

    orphan_user_count = await db.users.count_documents({
        "$or": [{"email": {"$exists": False}}, {"email": None}, {"email": ""}]
    })
    if orphan_user_count:
        trimmed[f"users (no/empty email) — {orphan_user_count} found, skipped (review manually)"] = 0

    return trimmed


async def main():
    log_lines = []
    def log(msg):
        print(msg)
        log_lines.append(msg)

    log(f"Connecting to MongoDB — db={DB_NAME}")
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    db = client[DB_NAME]
    await db.command("ping")
    log("Connected.\n")

    all_names = sorted(await db.list_collection_names())
    log(f"Total collections found: {len(all_names)}")

    log("\n" + "=" * 80)
    log("BEFORE — Collection audit")
    log("=" * 80)
    before_stats = {}
    total_storage_before = 0
    for name in all_names:
        s = await get_collection_stats(db, name)
        before_stats[name] = s
        total_storage_before += s["storage_bytes"] + s["index_bytes"]
        tag = "[DROP]" if name in COLLECTIONS_TO_DROP else "[KEEP]"
        log(f"  {tag} {name:40s}  docs={s['count']:>8,}  data={fmt(s['size_bytes']):>10}  storage={fmt(s['storage_bytes']):>10}  idx={fmt(s['index_bytes']):>10}")

    log(f"\nTotal storage before: {fmt(total_storage_before)}")

    log("\n" + "=" * 80)
    log("Trimming stale records from retained collections")
    log("=" * 80)
    trimmed = await trim_retained_collections(db)
    if trimmed:
        for desc, count in trimmed.items():
            log(f"  Trimmed {count} from {desc}")
    else:
        log("  No stale/orphaned records found")

    log("\n" + "=" * 80)
    log("Dropping non-essential collections")
    log("=" * 80)
    dropped = []
    skipped = []
    for name in COLLECTIONS_TO_DROP:
        if name in all_names:
            s = before_stats.get(name, {})
            log(f"  Dropping {name} ({s.get('count', 0):,} docs, {fmt(s.get('storage_bytes', 0))} storage)...")
            await db.drop_collection(name)
            dropped.append(name)
        else:
            skipped.append(name)
            log(f"  {name} — not found, skipping")

    unknown = [n for n in all_names if n not in COLLECTIONS_TO_DROP and n not in CORE_COLLECTIONS]
    if unknown:
        log(f"\nOther collections (kept, not in core list): {unknown}")

    log("\n" + "=" * 80)
    log("Compacting retained collections")
    log("=" * 80)
    remaining = sorted(await db.list_collection_names())
    for name in remaining:
        if name.startswith("system."):
            continue
        try:
            await db.command("compact", name)
            log(f"  Compacted {name}")
        except Exception as e:
            log(f"  Compact {name} skipped: {e}")

    log("\n" + "=" * 80)
    log("AFTER — Collection audit")
    log("=" * 80)
    remaining = sorted(await db.list_collection_names())
    total_storage_after = 0
    for name in remaining:
        s = await get_collection_stats(db, name)
        total_storage_after += s["storage_bytes"] + s["index_bytes"]
        log(f"  [KEEP] {name:40s}  docs={s['count']:>8,}  data={fmt(s['size_bytes']):>10}  storage={fmt(s['storage_bytes']):>10}  idx={fmt(s['index_bytes']):>10}")

    log(f"\nTotal storage after:  {fmt(total_storage_after)}")
    freed = total_storage_before - total_storage_after
    log(f"Storage freed:        {fmt(freed)}")
    log(f"\nDropped {len(dropped)} collections: {dropped}")
    if skipped:
        log(f"Skipped (not found):  {skipped}")
    log(f"Remaining collections: {len(remaining)}")

    log("\n" + "=" * 80)
    log("Verifying core collections")
    log("=" * 80)
    all_ok = True
    for name in ["boards", "classes", "streams", "subjects", "chapters", "syllabi", "chunks"]:
        if name in remaining:
            count = await db[name].count_documents({})
            log(f"  {name}: {count:,} documents — OK")
        else:
            log(f"  {name}: MISSING!")
            all_ok = False

    if all_ok:
        log("\nAll core collections intact. Cleanup complete.")
    else:
        log("\nWARNING: Some core collections are missing!")

    client.close()

    log_path = os.path.join(os.path.dirname(__file__), "db_cleanup_results.log")
    with open(log_path, "w") as f:
        f.write("\n".join(log_lines) + "\n")
    print(f"\nResults saved to {log_path}")


if __name__ == "__main__":
    asyncio.run(main())
