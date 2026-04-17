#!/usr/bin/env python3
"""One-shot backfill for `pyq_html_pages.created_at` / `updated_at` (Task #341).

Many legacy PYQ replica rows were uploaded before `created_at` was reliably
written, so `/api/pyq/{slug}/meta` returns an empty `published_at` for them
and `pyqDatasetSchema` (correctly) omits `datePublished` / `dateModified`.
That costs us freshness signals in Google's Dataset / Quiz cards.

This script walks every `pyq_html_pages` document and fills the timestamps
using the best available signal, in priority order:

  1. Existing `created_at` / `updated_at` strings (already populated — skip).
  2. The Mongo `_id` ObjectId generation time (present on every document
     since insertion — most reliable proxy for "when did we ingest this").
  3. `exam_year` → ISO timestamp at YYYY-06-30T00:00:00Z (mid-year so it
     reflects the academic cycle, not Jan 1 which is misleading).

`updated_at` is mirrored from `created_at` when missing — these are legacy
rows we never edited.

Usage:

    # safe preview, no writes
    MONGO_URL=... DB_NAME=... python scripts/backfill_pyq_dates.py --dry-run

    # apply
    MONGO_URL=... DB_NAME=... python scripts/backfill_pyq_dates.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from config import MONGO_URL, DB_NAME  # noqa: E402

COLLECTION = "pyq_html_pages"


def _to_iso(dt: datetime) -> str:
    """Mongo's ObjectId generation_time is tz-aware UTC. Strip microseconds
    so the value matches the ISO strings produced by `datetime.utcnow().isoformat()`
    elsewhere in the codebase."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def _derive_created_at(doc: dict) -> tuple[str, str]:
    """Return (iso_timestamp, source_label). Never returns empty."""
    oid = doc.get("_id")
    if oid is not None and hasattr(oid, "generation_time"):
        try:
            return _to_iso(oid.generation_time), "objectid"
        except Exception:
            pass
    year = doc.get("exam_year")
    try:
        y = int(year) if year else 0
    except (TypeError, ValueError):
        y = 0
    if y >= 1990 and y <= 2100:
        return _to_iso(datetime(y, 6, 30, tzinfo=timezone.utc)), "exam_year"
    # Last-resort fallback: today. Never expected in practice because every
    # doc has an _id; kept so the script can never produce an empty value.
    return _to_iso(datetime.now(timezone.utc)), "now_fallback"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N docs (0 = all). Useful for smoke tests.")
    args = parser.parse_args()

    raw_url = (MONGO_URL or "").strip().strip('"').strip("'")
    if not raw_url.startswith(("mongodb://", "mongodb+srv://")):
        print(f"ERROR: MONGO_URL invalid: {raw_url[:30]!r}", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(raw_url)
    db = client[DB_NAME]
    coll = db[COLLECTION]

    total = await coll.count_documents({})
    print(f"[backfill] {COLLECTION}: {total} total documents")

    sources = {"objectid": 0, "exam_year": 0, "now_fallback": 0}
    skipped = 0
    updated_created = 0
    updated_updated = 0
    processed = 0

    cursor = coll.find(
        {},
        {"_id": 1, "slug": 1, "exam_year": 1, "created_at": 1, "updated_at": 1},
    )
    async for doc in cursor:
        processed += 1
        if args.limit and processed > args.limit:
            break

        update: dict[str, str] = {}
        existing_created = doc.get("created_at")
        existing_updated = doc.get("updated_at")

        if _is_empty(existing_created):
            iso, source = _derive_created_at(doc)
            update["created_at"] = iso
            sources[source] += 1
            updated_created += 1
            existing_created = iso  # so the updated_at branch below sees it

        if _is_empty(existing_updated):
            update["updated_at"] = existing_created
            updated_updated += 1

        if not update:
            skipped += 1
            continue

        if not args.dry_run:
            await coll.update_one({"_id": doc["_id"]}, {"$set": update})

        if processed % 500 == 0:
            print(f"  …processed {processed}/{total}", flush=True)

    print()
    print("[backfill] done.")
    print(f"  scanned:                 {processed}")
    print(f"  already populated:       {skipped}")
    print(f"  filled created_at:       {updated_created}")
    print(f"    via ObjectId time:     {sources['objectid']}")
    print(f"    via exam_year:         {sources['exam_year']}")
    print(f"    via now() fallback:    {sources['now_fallback']}")
    print(f"  filled updated_at:       {updated_updated}")
    if args.dry_run:
        print()
        print("  (DRY RUN — no writes performed. Re-run without --dry-run to apply.)")

    # Coverage check: how many rows still have an empty created_at after this run?
    if not args.dry_run:
        remaining = await coll.count_documents({
            "$or": [
                {"created_at": {"$exists": False}},
                {"created_at": None},
                {"created_at": ""},
            ]
        })
        print(f"  coverage:                {total - remaining}/{total} have created_at "
              f"({((total - remaining) / total * 100) if total else 0:.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
