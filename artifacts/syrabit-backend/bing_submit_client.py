"""Bing Webmaster URL Submission API client (Phase E, Plan 11).

Pushes the active syllabus URL catalog to Bing nightly via the
SubmitUrlBatch endpoint to lift the anaemic Bingbot crawl pace
(currently 0.05 req/hr / ~3.7% of search-bot traffic).

Bing free-tier quota: 10,000 URLs/day. We batch in 500 URLs/call with a
1-second sleep between batches to be a polite client. On HTTP 429 the
caller is signalled to back off — the daily task halves the next-day
batch size in response.

Docs: https://www.bing.com/webmasters/help/url-submission-api-623f6e3a
"""
import asyncio
import logging
from typing import List, Tuple

import httpx

logger = logging.getLogger(__name__)

BING_SUBMIT_BATCH_URL = (
    "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlBatch"
)
BING_DEFAULT_BATCH_SIZE = 500
BING_INTER_BATCH_SLEEP_S = 1.0
BING_TIMEOUT_S = 30.0


class BingSubmitResult:
    """Aggregate result of a multi-batch submit call."""

    __slots__ = ("submitted", "succeeded", "failed", "rate_limited", "errors")

    def __init__(self) -> None:
        self.submitted: int = 0
        self.succeeded: int = 0
        self.failed: int = 0
        self.rate_limited: bool = False
        self.errors: List[str] = []

    def to_dict(self) -> dict:
        return {
            "submitted": self.submitted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "rate_limited": self.rate_limited,
            "errors": self.errors[:10],
        }


async def submit_url_batch(
    api_key: str,
    site_url: str,
    urls: List[str],
    *,
    batch_size: int = BING_DEFAULT_BATCH_SIZE,
    inter_batch_sleep_s: float = BING_INTER_BATCH_SLEEP_S,
    client: "httpx.AsyncClient | None" = None,
) -> BingSubmitResult:
    """Submit a list of URLs to Bing's SubmitUrlBatch endpoint in batches.

    Returns a `BingSubmitResult` summarising counts. On HTTP 429 the loop
    aborts early with `rate_limited=True` so the caller can back off.

    `client` is optional; supplying one makes mocking trivial in tests.
    """
    result = BingSubmitResult()
    if not api_key or not urls:
        return result

    unique_urls: List[str] = list(dict.fromkeys(u for u in urls if u))
    if not unique_urls:
        return result

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=BING_TIMEOUT_S)

    try:
        for i in range(0, len(unique_urls), batch_size):
            batch = unique_urls[i:i + batch_size]
            result.submitted += len(batch)
            try:
                resp = await client.post(
                    f"{BING_SUBMIT_BATCH_URL}?apikey={api_key}",
                    json={"siteUrl": site_url, "urlList": batch},
                    headers={"Content-Type": "application/json"},
                )
            except Exception as e:
                logger.warning(
                    "Bing submit batch %d-%d failed (transport): %s",
                    i, i + len(batch), e,
                )
                result.failed += len(batch)
                result.errors.append(f"transport: {e}")
                continue

            if resp.status_code == 429:
                result.failed += len(batch)
                result.rate_limited = True
                result.errors.append(f"429 rate-limited at batch {i}")
                logger.warning(
                    "Bing rate-limited at batch %d (URLs %d-%d) — aborting submit",
                    i // batch_size + 1, i, i + len(batch),
                )
                break

            if 200 <= resp.status_code < 300:
                result.succeeded += len(batch)
            else:
                result.failed += len(batch)
                snippet = (resp.text or "")[:200]
                result.errors.append(f"HTTP {resp.status_code}: {snippet}")
                logger.warning(
                    "Bing submit batch %d returned %d: %s",
                    i // batch_size + 1, resp.status_code, snippet,
                )

            if i + batch_size < len(unique_urls):
                await asyncio.sleep(inter_batch_sleep_s)
    finally:
        if owns_client:
            await client.aclose()

    return result


async def get_quota(
    api_key: str,
    site_url: str,
    *,
    client: "httpx.AsyncClient | None" = None,
) -> Tuple[int, int]:
    """Fetch the daily/monthly remaining quota from Bing. Returns
    (daily_remaining, monthly_remaining); (-1, -1) on failure."""
    if not api_key:
        return (-1, -1)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=BING_TIMEOUT_S)
    try:
        resp = await client.get(
            "https://ssl.bing.com/webmaster/api.svc/json/GetUrlSubmissionQuota"
            f"?apikey={api_key}&siteUrl={site_url}",
        )
        if resp.status_code != 200:
            return (-1, -1)
        body = resp.json()
        d = body.get("d") or {}
        return (
            int(d.get("DailyQuota", -1)),
            int(d.get("MonthlyQuota", -1)),
        )
    except Exception as e:
        logger.debug(f"Bing quota fetch failed: {e}")
        return (-1, -1)
    finally:
        if owns_client:
            await client.aclose()
