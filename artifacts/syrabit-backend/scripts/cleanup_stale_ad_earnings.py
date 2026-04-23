"""Task #731 S5 — purge bogus ad_earnings rows + backfill missing
provenance fields.

Background
----------
Before S4, the AdSense sync wrote `revenue_inr = ESTIMATED_EARNINGS`
where ESTIMATED_EARNINGS is actually USD. That left rows like:
  * adsense  2025-XX-XX  revenue_inr=246.9  impressions=1
  * adpushup 2025-XX-XX  revenue_inr=127.6  impressions=1
…both of which imply a single impression earned ₹246 / ₹127 — about
1000x what's plausible. They were bug artifacts, not real revenue.

This script does TWO things, both idempotent + dry-runnable:

  1. **Quarantine then delete** the obvious anomalies — any row with
     impressions <= 5 AND revenue_inr >= 50 (a single ad almost never
     pays ₹10, let alone ₹50). Each candidate is logged to stdout so
     a human can sanity-check the list before `--apply` runs the
     actual delete.
  2. **Backfill `source` + `currency_original`** on rows that pre-date
     S5's hard requirement, so future analytics queries don't have to
     `coalesce(source, "manual")` everywhere. Defaults: rows with
     `source` already set are left alone; everything else gets
     `source="manual"` and `currency_original="INR"`.

Usage
-----
  # Show what would happen, change nothing:
  python scripts/cleanup_stale_ad_earnings.py --dry-run

  # Actually delete + backfill:
  python scripts/cleanup_stale_ad_earnings.py --apply

Re-run safely; subsequent runs report 0 changes once clean.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

# Make the repo importable when run from anywhere.
_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from deps import db  # noqa: E402

# Anomaly thresholds — chosen so that even an unusually high CPM
# campaign (~₹1000 RPM = ₹1 per impression) doesn't trip the filter.
# A row earning ₹50 from 5 or fewer impressions implies CPM > ₹10000,
# which is two orders of magnitude above any sane benchmark for an
# Indian education-vertical site.
ANOMALY_MAX_IMPRESSIONS = 5
ANOMALY_MIN_REVENUE_INR = 50.0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only")
    parser.add_argument("--apply", action="store_true", help="actually delete + backfill")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("pass --dry-run or --apply")

    # 1. Find anomalies.
    anomalies_q = {
        "impressions": {"$lte": ANOMALY_MAX_IMPRESSIONS, "$gt": 0},
        "revenue_inr": {"$gte": ANOMALY_MIN_REVENUE_INR},
    }
    anomalies = await db.ad_earnings.find(anomalies_q).to_list(1000)
    print(f"[cleanup] found {len(anomalies)} anomaly row(s) "
          f"(impressions <= {ANOMALY_MAX_IMPRESSIONS} "
          f"AND revenue_inr >= ₹{ANOMALY_MIN_REVENUE_INR}):")
    for a in anomalies:
        print(
            f"  - network={a.get('network'):<12} "
            f"date={a.get('date'):<10} "
            f"placement={a.get('placement') or '-':<10} "
            f"impressions={a.get('impressions')} "
            f"revenue_inr=₹{a.get('revenue_inr')} "
            f"source={a.get('source') or '-'} "
            f"_id={a.get('_id')}"
        )

    # 2. Find rows missing the source flag.
    missing_source = await db.ad_earnings.count_documents({
        "$or": [{"source": {"$exists": False}}, {"source": None}, {"source": ""}],
    })
    print(f"[cleanup] {missing_source} row(s) need source backfill")

    if args.dry_run:
        print("[cleanup] DRY RUN — no changes made.")
        return 0

    # 3. Apply.
    if anomalies:
        ids = [a["_id"] for a in anomalies]
        del_res = await db.ad_earnings.delete_many({"_id": {"$in": ids}})
        print(f"[cleanup] deleted {del_res.deleted_count} anomaly row(s)")
    if missing_source:
        upd_res = await db.ad_earnings.update_many(
            {"$or": [{"source": {"$exists": False}}, {"source": None}, {"source": ""}]},
            {"$set": {
                "source": "manual",
                "currency_original": "INR",
                "backfilled_by": "cleanup_stale_ad_earnings.py",
                "backfilled_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        print(f"[cleanup] backfilled source on {upd_res.modified_count} row(s)")
    print("[cleanup] done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
