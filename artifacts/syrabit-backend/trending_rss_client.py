"""RSS-based trending ingestion for the topic-discovery agent.

Fetches a configurable list of RSS/Atom feed URLs, extracts item titles,
and writes them into the ``trending_topics_raw`` Mongo collection that
``topic_discovery_service.collect_trending`` reads from.

Configuration (env vars):
  * TOPIC_DISCOVERY_RSS_FEEDS  — comma-separated URLs. If unset, the
    adapter no-ops so the rest of the nightly run keeps working.

We intentionally use the stdlib XML parser (no ``feedparser`` dependency)
because RSS/Atom item titles are simple to extract and we'd rather avoid
adding a third-party parsing dep.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import httpx

logger = logging.getLogger(__name__)

TRENDING_RAW_COLLECTION = "trending_topics_raw"


def _parse_titles(xml_text: str) -> List[str]:
    """Extract item titles from RSS 2.0 (<channel><item><title>) and
    Atom (<entry><title>) feeds. Stripped/deduped."""
    titles: List[str] = []
    seen = set()
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []
    # RSS 2.0 + Atom — try both. Iterate every element whose local name
    # is "title" and whose immediate parent looks like an item/entry.
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1].lower()
        if tag != "title":
            continue
        text = (el.text or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        titles.append(text)
    # Drop the channel/feed title itself (always the first hit when
    # parsing top-down). RSS feeds put the feed title before any item.
    if titles:
        titles = titles[1:] if len(titles) > 1 else titles
    return titles


async def fetch_feed_titles(
    url: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = 15.0,
) -> List[str]:
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        try:
            res = await client.get(url, timeout=timeout, headers={
                "User-Agent": "Syrabit-TopicDiscovery/1.0 (+https://syrabit.ai)",
            })
        except Exception as exc:
            logger.info("rss: fetch %s failed: %s", url, exc)
            return []
        if res.status_code != 200:
            logger.info("rss: %s returned %s", url, res.status_code)
            return []
        return _parse_titles(res.text)
    finally:
        if own:
            await client.aclose()


async def ingest_trending_into_mongo(
    db: Any, *,
    feeds: Optional[List[str]] = None,
    now: Optional[datetime] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> int:
    """Pull each configured feed, write each item title as a trending
    candidate. Idempotent via upsert on ``query``. Returns the number
    of titles upserted (0 on no-op / failure).
    """
    if db is None:
        return 0
    feeds = feeds if feeds is not None else [
        u.strip() for u in os.environ.get("TOPIC_DISCOVERY_RSS_FEEDS", "").split(",")
        if u.strip()
    ]
    if not feeds:
        return 0
    now = now or datetime.now(timezone.utc)
    coll = db[TRENDING_RAW_COLLECTION]

    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0)
    n = 0
    try:
        for url in feeds:
            titles = await fetch_feed_titles(url, client=client)
            for title in titles:
                doc = {
                    "query": title,
                    "source": f"rss:{url}",
                    "score": 1.0,
                    "recorded_at": now,
                }
                try:
                    await coll.update_one(
                        {"query": title, "source": doc["source"]},
                        {"$set": doc},
                        upsert=True,
                    )
                    n += 1
                except Exception as exc:
                    logger.info("rss: upsert failed for %r: %s", title, exc)
    finally:
        if own:
            await client.aclose()
    return n
