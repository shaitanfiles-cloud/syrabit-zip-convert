"""
One-time migration: Backfill threshold_snapshot for historical alerts
=====================================================================
Reads existing alerts from db.alerts that lack a threshold_snapshot field,
infers threshold data from the alert type and body text, and writes it back.

Usage:
    python migrate_alert_thresholds.py

Environment variables required:
    MONGO_URL   — MongoDB connection string
    DB_NAME     — Database name (default: test_database)

Dry-run mode (preview without writing):
    python migrate_alert_thresholds.py --dry-run
"""

import asyncio
import sys
import os
import re
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate_alert_thresholds")

_ALERT_TYPE_TO_METRIC = {
    "high_error_rate": "error_rate_pct",
    "high_latency": "latency_p95_ms",
    "spoofed_bot_surge": "spoof_rpm",
    "high_fallback_rate": "fallback_rate_pct",
    "endpoint_down": "endpoint_down_minutes",
}

_ALERT_THRESHOLDS_DEFAULT = {
    "latency_p95_ms": 2000,
    "error_rate_pct": 5.0,
    "fallback_rate_pct": 50.0,
    "spoof_rpm": 50,
    "endpoint_down_minutes": 60,
}

_BODY_PARSERS = {
    "high_error_rate": re.compile(r"([\d.]+)%\s*errors"),
    "high_latency": re.compile(r"p95\s*=\s*(\d+)\s*ms", re.IGNORECASE),
    "spoofed_bot_surge": re.compile(r"([\d.]+)\s*spoofed\s*requests/min", re.IGNORECASE),
    "high_fallback_rate": re.compile(r"([\d.]+)%\s*of\s*last"),
    "endpoint_down": re.compile(r"failing\s*for\s*(\d+)\s*min", re.IGNORECASE),
}

_ENDPOINT_PATTERN = re.compile(r"Endpoint\s+(\S+)\s+has\s+been")


def _parse_actual(alert_type: str, body: str):
    pattern = _BODY_PARSERS.get(alert_type)
    if not pattern:
        return None
    m = pattern.search(body or "")
    if not m:
        return None
    try:
        val = float(m.group(1))
        if alert_type in ("high_latency", "spoofed_bot_surge", "endpoint_down"):
            return int(val)
        return round(val, 1)
    except (ValueError, IndexError):
        return None


def _parse_endpoint(body: str):
    m = _ENDPOINT_PATTERN.search(body or "")
    return m.group(1) if m else None


async def main():
    dry_run = "--dry-run" in sys.argv

    from motor.motor_asyncio import AsyncIOMotorClient
    from config import MONGO_URL, DB_NAME

    logger.info(f"Connecting to MongoDB — db={DB_NAME}")
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    db = client[DB_NAME]
    await db.command("ping")
    logger.info("Connected to MongoDB.")

    if dry_run:
        logger.info("DRY-RUN mode — no documents will be modified")

    configured_thresholds = dict(_ALERT_THRESHOLDS_DEFAULT)
    try:
        cfg = await db.api_config.find_one({}, {"_id": 0})
        if cfg and "alert_settings" in cfg:
            saved = cfg["alert_settings"].get("thresholds", {})
            for k in _ALERT_THRESHOLDS_DEFAULT:
                if k in saved:
                    try:
                        configured_thresholds[k] = float(saved[k])
                    except (ValueError, TypeError):
                        pass
        logger.info(f"Active thresholds: {configured_thresholds}")
    except Exception as e:
        logger.warning(f"Could not load saved thresholds, using defaults: {e}")

    query = {"threshold_snapshot": {"$exists": False}}
    total = await db.alerts.count_documents(query)
    logger.info(f"Found {total} alerts without threshold_snapshot")

    if total == 0:
        logger.info("Nothing to migrate — all alerts already have threshold_snapshot")
        client.close()
        return

    updated = 0
    skipped = 0
    by_type = {}

    async for alert in db.alerts.find(query):
        alert_type = alert.get("type", "")
        body = alert.get("body", "")
        metric = _ALERT_TYPE_TO_METRIC.get(alert_type)

        if not metric:
            skipped += 1
            logger.debug(f"Skipping alert _id={alert['_id']} — unknown type '{alert_type}'")
            continue

        threshold_value = configured_thresholds.get(metric, _ALERT_THRESHOLDS_DEFAULT.get(metric))
        actual = _parse_actual(alert_type, body)

        snapshot = {
            "metric": metric,
            "value": threshold_value,
        }
        if actual is not None:
            snapshot["actual"] = actual

        if alert_type == "endpoint_down":
            ep = _parse_endpoint(body)
            if ep:
                snapshot["endpoint"] = ep

        if not dry_run:
            await db.alerts.update_one(
                {"_id": alert["_id"]},
                {"$set": {"threshold_snapshot": snapshot}},
            )

        updated += 1
        by_type[alert_type] = by_type.get(alert_type, 0) + 1

        if updated % 100 == 0:
            logger.info(f"Progress: {updated}/{total} alerts processed")

    logger.info("=" * 60)
    logger.info(f"Migration {'(DRY-RUN) ' if dry_run else ''}complete!")
    logger.info(f"  Updated:  {updated}")
    logger.info(f"  Skipped:  {skipped} (unknown alert types)")
    logger.info(f"  By type:  {by_type}")
    logger.info("=" * 60)

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
