#!/usr/bin/env python3
"""
Idempotent normalizer for legacy naive PYQ timestamps.

Background
----------
Task #738 converted every naive UTC timestamp call site in
`routes/pyq.py` to `datetime.now(timezone.utc).isoformat()`. New writes
now produce ISO-8601 strings with a `+00:00` suffix.

Historical rows still on disk carry naive ISO strings (no suffix).
MongoDB sorts strings lexicographically: at the same wall-clock instant
an aware string sorts after the naive one (longer string with same
prefix), which makes ordering self-consistent enough for "latest first"
listings — but range queries (e.g. `created_at >= "2024-01-15"`) and
mixed-format equality checks can drift in subtle ways.

This script normalizes every legacy naive timestamp on these fields by
appending `+00:00`, so the entire collection speaks the same dialect
the new code writes.

Safety
------
- **Idempotent**: rows that already end with a timezone suffix
  (`+00:00`, `Z`, `+05:30`, etc.) are skipped. Re-running is a no-op.
- **Dry-run by default? No** — to match the existing
  `migrate_payments_amount_inr.py` convention, this script writes by
  default. Pass `--dry-run` to preview what would change.
- **Bounded**: only touches fields known to be string-formatted
  timestamps written by `routes/pyq.py`: `created_at`, `updated_at`.
  Does not invent new fields, does not delete anything.

Usage
-----
    python -m scripts.migrate_pyq_timestamps_to_aware            # apply
    python -m scripts.migrate_pyq_timestamps_to_aware --dry-run  # preview

Output
------
Prints `{rows_seen, rows_updated, by_field}` summary at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from typing import Any, Dict

# Allow running as `python -m scripts.migrate_pyq_timestamps_to_aware`
# from the syrabit-backend directory.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("migrate_pyq_timestamps")

# An ISO-8601 string is "already aware" if it ends with Z or with a
# numeric offset like +HH:MM / -HH:MM. Anything else (e.g.
# "2024-01-15T10:30:00" or "2024-01-15T10:30:00.123456") is naive and
# needs `+00:00` appended.
_AWARE_SUFFIX_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")

# Collections that the PYQ pipeline writes timestamps to. Kept narrow on
# purpose — this script's promise is "normalize PYQ timestamps", not
# "normalize the whole database". The list mirrors the PYQ-owned
# collections enumerated in `db_cleanup.py` plus the legacy
# `pyq_papers` / `pyq_questions` names that may exist in older
# environments.
_PYQ_COLLECTIONS = (
    "pyq_uploads",
    "pyq_html_pages",
    "topic_pyq_collections",
    "ai_pyq_collections",
    "pyq_papers",
    "pyq_questions",
)
_TIMESTAMP_FIELDS = ("created_at", "updated_at")


def _needs_normalization(value: Any) -> bool:
    """True if `value` is a non-empty string that looks like a naive
    ISO-8601 timestamp (no trailing Z or offset)."""
    if not isinstance(value, str) or not value:
        return False
    # Cheap shape check: must contain a 'T' separator and at least the
    # date prefix "YYYY-MM-DD" (10 chars).
    if len(value) < 11 or value[4] != "-" or value[7] != "-":
        return False
    return _AWARE_SUFFIX_RE.search(value) is None


async def _migrate(dry_run: bool) -> Dict[str, Any]:
    # Import lazily so `--help` works without a Mongo connection.
    from deps import db  # noqa: WPS433

    summary: Dict[str, Any] = {
        "dry_run": dry_run,
        "rows_seen": 0,
        "rows_updated": 0,
        "by_field": {f: 0 for f in _TIMESTAMP_FIELDS},
        "by_collection": {},
    }

    for coll_name in _PYQ_COLLECTIONS:
        coll = db[coll_name]
        # Bounded scan: only fetch the timestamp fields plus _id.
        proj = {f: 1 for f in _TIMESTAMP_FIELDS}
        try:
            cursor = coll.find({}, proj)
        except Exception as exc:  # collection may not exist
            log.warning("skip %s (find failed): %s", coll_name, exc)
            continue

        coll_seen = 0
        coll_updated = 0
        async for doc in cursor:
            coll_seen += 1
            updates = {}
            for field in _TIMESTAMP_FIELDS:
                if _needs_normalization(doc.get(field)):
                    updates[field] = f"{doc[field]}+00:00"
                    summary["by_field"][field] += 1
            if updates:
                coll_updated += 1
                if not dry_run:
                    await coll.update_one(
                        {"_id": doc["_id"]},
                        {"$set": updates},
                    )

        summary["rows_seen"] += coll_seen
        summary["rows_updated"] += coll_updated
        summary["by_collection"][coll_name] = {
            "seen": coll_seen,
            "updated": coll_updated,
        }
        log.info(
            "%s: seen=%d updated=%d (dry_run=%s)",
            coll_name, coll_seen, coll_updated, dry_run,
        )

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )
    args = parser.parse_args()

    summary = asyncio.run(_migrate(dry_run=args.dry_run))
    log.info("DONE: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
