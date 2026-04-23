"""One-shot backfill: add canonical `amount_inr` (+ FX audit fields) to
every existing row in `payments` that doesn't already have it.

Task #731 — Money truth. Run from the backend dir:

    # write (default):
    cd artifacts/syrabit-backend && python -m scripts.migrate_payments_amount_inr

    # preview only (no writes):
    cd artifacts/syrabit-backend && python -m scripts.migrate_payments_amount_inr --dry-run

NOTE: there is no `--apply` flag — the script writes by default. Pass
`--dry-run` (or `-n`) if you want a preview. See
`docs/PAYMENTS_BACKFILL_RUN.md` for the production execution log.

Behaviour:
  * Idempotent. Rows that already have `amount_inr` are skipped.
  * Razorpay rows (`amount_paise` set): amount_inr = paise / 100.
  * Stripe rows (`amount_cents` + `currency`): converted via the FX
    helper. The rate used is captured per-row as `fx_rate` + `fx_source`
    + `fx_fetched_at` so historical rows are auditable. NOTE: this uses
    *today's* FX rate as a best-effort proxy when the original payment
    date had no archived rate — this is documented on the row via
    `fx_backfilled: True` and `fx_backfilled_at`.
  * Rows with no recognisable amount fields are flagged with
    `amount_inr: 0.0` + `fx_source: "zero"`.
  * Rows with non-USD/non-INR Stripe currency are flagged
    `fx_source: "unsupported_currency"` and amount_inr left None so
    rollups can exclude them safely.

Prints a per-provider summary on completion.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone

# Make the backend package importable when run as a module from the
# backend directory (`python -m scripts.migrate_payments_amount_inr`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("migrate_amount_inr")


async def _build_update(row: dict) -> dict | None:
    """Compute the $set patch for one row, or None if row is fine as-is."""
    if "amount_inr" in row and row.get("amount_inr") is not None:
        return None

    paise = row.get("amount_paise")
    cents = row.get("amount_cents")
    currency = (row.get("currency") or "").lower().strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    if isinstance(paise, (int, float)) and paise:
        return {
            "amount_inr": round(float(paise) / 100.0, 2),
            "currency_original": "INR",
            "amount_original": float(paise) / 100.0,
            "fx_rate": 1.0,
            "fx_source": "inr_native",
            "fx_fetched_at": None,
            "fx_backfilled": True,
            "fx_backfilled_at": now_iso,
        }

    if isinstance(cents, (int, float)) and cents:
        if currency in ("", "usd"):
            from fx import usd_to_inr, FxRateUnavailable
            try:
                conv = await usd_to_inr(float(cents) / 100.0)
            except FxRateUnavailable:
                logger.error("FX unavailable while migrating row %s — skipping", row.get("_id"))
                return None
            return {
                "amount_inr": float(conv["inr"]),
                "currency_original": "USD",
                "amount_original": float(cents) / 100.0,
                "fx_rate": float(conv["rate"]),
                "fx_source": conv["source"],
                "fx_fetched_at": conv["fetched_at"],
                "fx_backfilled": True,
                "fx_backfilled_at": now_iso,
            }
        if currency == "inr":
            return {
                "amount_inr": round(float(cents) / 100.0, 2),
                "currency_original": "INR",
                "amount_original": float(cents) / 100.0,
                "fx_rate": 1.0,
                "fx_source": "inr_native",
                "fx_fetched_at": None,
                "fx_backfilled": True,
                "fx_backfilled_at": now_iso,
            }
        # Unsupported currency — flag, don't guess.
        return {
            "amount_inr": None,
            "currency_original": currency.upper(),
            "amount_original": float(cents) / 100.0,
            "fx_rate": None,
            "fx_source": "unsupported_currency",
            "fx_fetched_at": None,
            "fx_backfilled": True,
            "fx_backfilled_at": now_iso,
        }

    # Zero-amount / activation_skipped / malformed.
    return {
        "amount_inr": 0.0,
        "currency_original": "INR",
        "amount_original": 0.0,
        "fx_rate": 1.0,
        "fx_source": "zero",
        "fx_fetched_at": None,
        "fx_backfilled": True,
        "fx_backfilled_at": now_iso,
    }


async def main(dry_run: bool = False) -> int:
    from deps import db  # type: ignore

    # Pull every row, including ones that already have amount_inr — the
    # _build_update fast-path skips them.
    cursor = db.payments.find({})
    seen = 0
    updated = 0
    skipped = 0
    by_source: Counter[str] = Counter()
    by_provider: Counter[str] = Counter()

    async for row in cursor:
        seen += 1
        patch = await _build_update(row)
        if patch is None:
            skipped += 1
            continue
        provider = row.get("provider") or "unknown"
        by_provider[provider] += 1
        by_source[patch.get("fx_source", "?")] += 1
        if dry_run:
            updated += 1
            if updated <= 5:
                logger.info("[dry-run] %s (%s) -> %s", row.get("_id"), provider, patch)
            continue
        await db.payments.update_one({"_id": row["_id"]}, {"$set": patch})
        updated += 1

    logger.info("=== migrate_payments_amount_inr summary ===")
    logger.info("rows seen:    %d", seen)
    logger.info("rows updated: %d", updated)
    logger.info("rows skipped: %d (already had amount_inr or FX failed)", skipped)
    logger.info("by provider:  %s", dict(by_provider))
    logger.info("by fx_source: %s", dict(by_source))
    if dry_run:
        logger.info("(dry run — no writes were performed)")
    return 0


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    raise SystemExit(asyncio.run(main(dry_run=dry)))
