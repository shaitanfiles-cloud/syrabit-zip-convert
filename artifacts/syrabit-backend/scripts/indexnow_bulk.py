"""Bulk IndexNow submission for every URL in syrabit.ai sitemaps.

IndexNow accepts up to 10,000 URLs per batch; we send in chunks of 500
to stay well under any per-request limit. Pings api.indexnow.org which
fans out to Bing, Yandex, Seznam, Naver, and Yep.

Usage:
    python3 scripts/indexnow_bulk.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from urllib.request import Request as URLReq, urlopen
from urllib.error import HTTPError

import requests

BASE_URL = "https://syrabit.ai"
SITEMAP_INDEX = f"{BASE_URL}/sitemap.xml"
INDEXNOW_KEY = os.environ.get(
    "INDEXNOW_KEY", hashlib.sha256(b"syrabit-indexnow-2026").hexdigest()[:32]
)
KEY_LOCATION = f"{BASE_URL}/{INDEXNOW_KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH_SIZE = 500


def fetch(url: str) -> str:
    req = URLReq(url, headers={"User-Agent": "syrabit-indexnow/1.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def collect_urls() -> list[str]:
    body = fetch(SITEMAP_INDEX)
    sub = re.findall(r"<loc>([^<]+)</loc>", body)
    urls: set[str] = set()
    for sm in sub:
        try:
            for u in re.findall(r"<loc>([^<]+)</loc>", fetch(sm)):
                urls.add(u.strip())
        except HTTPError as e:
            print(f"  ! sub-sitemap {sm} -> HTTP {e.code}", file=sys.stderr)
    return sorted(urls)


def main() -> int:
    print(f"IndexNow key: {INDEXNOW_KEY}")
    print(f"Key location: {KEY_LOCATION}")

    print("\nVerifying key file is publicly accessible...")
    try:
        served = fetch(KEY_LOCATION).strip()
        if served != INDEXNOW_KEY:
            print(f"  ✗ key file body mismatch: served {served[:60]!r}, expected {INDEXNOW_KEY!r}")
            return 1
        print("  ✓ key file serves the correct key")
    except Exception as e:
        print(f"  ✗ key file fetch failed: {e}")
        return 1

    print(f"\nCollecting URLs from {SITEMAP_INDEX} ...")
    urls = collect_urls()
    print(f"  {len(urls)} unique URLs")
    if not urls:
        return 1

    print(f"\nSubmitting in batches of {BATCH_SIZE} ...")
    session = requests.Session()
    ok_total = 0
    fail_batches: list[tuple[int, int, str]] = []

    for i in range(0, len(urls), BATCH_SIZE):
        chunk = urls[i : i + BATCH_SIZE]
        payload = {
            "host": "syrabit.ai",
            "key": INDEXNOW_KEY,
            "keyLocation": KEY_LOCATION,
            "urlList": chunk,
        }
        try:
            r = session.post(
                ENDPOINT,
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(payload),
                timeout=30,
            )
        except Exception as e:
            fail_batches.append((i, -1, str(e)[:200]))
            print(f"  batch {i}-{i+len(chunk)}: EXCEPTION {e}")
            continue

        if 200 <= r.status_code < 300:
            ok_total += len(chunk)
            print(f"  batch {i}-{i+len(chunk)}: ✓ HTTP {r.status_code} ({len(chunk)} URLs)")
        else:
            fail_batches.append((i, r.status_code, r.text[:200]))
            print(f"  batch {i}-{i+len(chunk)}: ✗ HTTP {r.status_code} — {r.text[:200]}")

    print("\n=== SUMMARY ===")
    print(f"  total submitted   : {len(urls)}")
    print(f"  successfully sent : {ok_total}")
    print(f"  failed            : {len(urls) - ok_total}")
    print(f"  fanout            : Bing, Yandex, Seznam, Naver, Yep (via api.indexnow.org)")
    if fail_batches:
        print("\n  failed batches:")
        for offset, code, body in fail_batches:
            print(f"    [{code}] starting at index {offset}: {body}")

    return 0 if not fail_batches else 1


if __name__ == "__main__":
    sys.exit(main())
