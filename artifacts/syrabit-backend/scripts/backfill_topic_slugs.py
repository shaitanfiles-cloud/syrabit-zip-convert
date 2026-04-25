"""
Backfill `topic_slug` and `definition_status` on every topic in the
`topics` collection. Re-runnable / idempotent.

Background — Task #914 Step 1
-----------------------------
Topic deep-link URLs (`/.../<chapter>/topic/<topic-slug>`) and AI
answer cards both need a stable, unique-per-chapter slug for every
published topic. Today the `topics` documents carry an optional
`slug` field that's only populated for some rows (the SEO pipeline
auto-derives one when generating pages, but never persists it back
to the topic doc itself), so we need a one-shot pass that:

1. Persists a deterministic, slugified-from-title slug into a NEW
   `topic_slug` field. We deliberately don't reuse `slug` so a
   future change to the SEO pipeline can't silently flip the URL
   surface area for a topic.
2. Resolves collisions inside a single chapter by suffixing `-2`,
   `-3`, … on the second-and-later occurrence. Ordered by
   `created_at` so the FIRST topic with a given title keeps the
   bare slug.
3. Audits each topic's `definition` field and stamps a
   `definition_status` of `"ok"` (>= 30 non-whitespace chars after
   strip) or `"definition_missing"`. The new topic-deep-link route
   and AI answer card are gated on `"ok"` so we never ship an
   answer card pointing at an empty definition.

This script is wrapped in an admin endpoint
(`POST /api/admin/topics/backfill-slugs`) so an operator can trigger
the same pass from the panel after editing topic definitions, and
it can also be invoked from the CLI for ops.

Usage
-----
    cd artifacts/syrabit-backend
    python scripts/backfill_topic_slugs.py --dry-run      # report only
    python scripts/backfill_topic_slugs.py                # write changes
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from typing import Any

# Allow running both as `python scripts/backfill_topic_slugs.py` from
# the backend dir AND as `python -m scripts.backfill_topic_slugs`.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from utils import slugify_title  # noqa: E402

# Minimum length (after whitespace strip) for a topic definition to
# count as "usable" for the AI answer card. A single short sentence
# typically reaches 30+ chars; anything shorter risks publishing an
# answer card that crawlers will rightly demote as thin content.
MIN_DEFINITION_CHARS = 30

DEFINITION_STATUS_OK = "ok"
DEFINITION_STATUS_MISSING = "definition_missing"


def _evaluate_definition(text: Any) -> str:
    """Return `"ok"` when the definition is publishable, else missing."""
    if not isinstance(text, str):
        return DEFINITION_STATUS_MISSING
    cleaned = text.strip()
    if len(cleaned) < MIN_DEFINITION_CHARS:
        return DEFINITION_STATUS_MISSING
    return DEFINITION_STATUS_OK


def _allocate_slugs(topics: list[dict]) -> dict[str, str]:
    """Map topic id → final unique-within-chapter slug.

    Topics are bucketed by chapter_id, ordered by created_at then id
    for stability, and collisions are broken with `-2`, `-3`, … on
    the second-and-later occurrence so the earliest topic with a
    given title keeps the bare slug.
    """
    by_chapter: dict[str, list[dict]] = defaultdict(list)
    for t in topics:
        by_chapter[str(t.get("chapter_id") or "")].append(t)

    final: dict[str, str] = {}
    for _chapter_id, bucket in by_chapter.items():
        bucket.sort(key=lambda d: (str(d.get("created_at") or ""), str(d.get("id") or d.get("_id") or "")))
        used: set[str] = set()
        for topic in bucket:
            base = slugify_title(topic.get("title") or "") or "topic"
            slug = base
            n = 2
            while slug in used:
                slug = f"{base}-{n}"
                n += 1
            used.add(slug)
            final[str(topic.get("id") or topic.get("_id"))] = slug
    return final


async def run_backfill(*, dry_run: bool = False) -> dict[str, int]:
    """Apply the backfill in-place. Returns a counters dict.

    Counters:
      - scanned: total topics inspected
      - slugged: topics whose `topic_slug` was created OR rewritten
      - definition_ok / definition_missing: post-pass status counts
      - skipped_no_change: topics already in their target shape
    """
    # Local import — keeps the script importable from the admin route
    # without paying for a Mongo handshake at module load.
    from deps import db, is_mongo_available  # noqa: WPS433

    if not await is_mongo_available():
        raise RuntimeError("mongo unavailable — refusing to backfill")

    topics: list[dict] = await db.topics.find({}, {"_id": 1, "id": 1, "chapter_id": 1, "title": 1, "definition": 1, "created_at": 1, "topic_slug": 1, "definition_status": 1}).to_list(None)
    counters = {
        "scanned": len(topics),
        "slugged": 0,
        "definition_ok": 0,
        "definition_missing": 0,
        "skipped_no_change": 0,
    }
    if not topics:
        return counters

    target_slugs = _allocate_slugs(topics)

    for topic in topics:
        topic_id = topic.get("id") or topic.get("_id")
        target_slug = target_slugs[str(topic_id)]
        target_def_status = _evaluate_definition(topic.get("definition"))

        if target_def_status == DEFINITION_STATUS_OK:
            counters["definition_ok"] += 1
        else:
            counters["definition_missing"] += 1

        existing_slug = topic.get("topic_slug")
        existing_def_status = topic.get("definition_status")
        if existing_slug == target_slug and existing_def_status == target_def_status:
            counters["skipped_no_change"] += 1
            continue

        update: dict[str, Any] = {}
        if existing_slug != target_slug:
            update["topic_slug"] = target_slug
            counters["slugged"] += 1
        if existing_def_status != target_def_status:
            update["definition_status"] = target_def_status

        if dry_run or not update:
            continue
        # Update by `id` first (the canonical app-level identifier),
        # falling back to `_id` for legacy rows that pre-date the
        # uuid-id convention.
        if topic.get("id"):
            await db.topics.update_one({"id": topic["id"]}, {"$set": update})
        else:
            await db.topics.update_one({"_id": topic["_id"]}, {"$set": update})
    return counters


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Backfill topic_slug + definition_status.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing.")
    args = parser.parse_args()
    counters = asyncio.run(run_backfill(dry_run=args.dry_run))
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"[backfill_topic_slugs] {mode}  {counters}")


if __name__ == "__main__":
    _cli()
