"""Bulk-submit every URL in syrabit.ai sitemaps to Google Indexing API.

Reads GOOGLE_APPLICATION_CREDENTIALS_JSON (service-account JSON) from env,
auto-repairs missing wrapper braces if needed, mints an OAuth2 access token
with the indexing scope, then POSTs URL_UPDATED notifications in parallel.

Usage:
    python3 scripts/google_index_bulk.py
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request as URLReq, urlopen
from urllib.error import HTTPError

import requests
from google.auth.transport.requests import Request as AuthReq
from google.oauth2 import service_account

SITEMAP_INDEX = "https://syrabit.ai/sitemap.xml"
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
SCOPES = ["https://www.googleapis.com/auth/indexing"]
PARALLEL = 8
QPS_DELAY = 0.05


def load_credentials():
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    if not raw:
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS_JSON not set")
    if not raw.startswith("{"):
        raw = "{" + raw.rstrip(", \n\t") + "}"
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"credentials JSON unparseable even after repair: {e}")
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def fetch(url):
    req = URLReq(url, headers={"User-Agent": "syrabit-indexer/1.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def collect_urls():
    body = fetch(SITEMAP_INDEX)
    sub = re.findall(r"<loc>([^<]+)</loc>", body)
    urls = set()
    for sm in sub:
        try:
            for u in re.findall(r"<loc>([^<]+)</loc>", fetch(sm)):
                urls.add(u.strip())
        except HTTPError as e:
            print(f"  ! sub-sitemap {sm} -> HTTP {e.code}", file=sys.stderr)
    return sorted(urls)


def submit(session, token, url):
    r = session.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"url": url, "type": "URL_UPDATED"},
        timeout=20,
    )
    return r.status_code, r.text[:200]


def main():
    print("Loading service-account credentials...")
    creds = load_credentials()
    creds.refresh(AuthReq())
    print(f"  service account: {creds.service_account_email}")

    print(f"Collecting URLs from {SITEMAP_INDEX} ...")
    urls = collect_urls()
    print(f"  {len(urls)} unique URLs")

    if not urls:
        sys.exit("nothing to submit")

    session = requests.Session()
    ok = 0
    fail = 0
    fail_samples = []

    def task(u):
        time.sleep(QPS_DELAY)
        try:
            return u, *submit(session, creds.token, u)
        except Exception as e:
            return u, -1, str(e)[:200]

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futures = [pool.submit(task, u) for u in urls]
        for i, fut in enumerate(as_completed(futures), 1):
            u, code, body = fut.result()
            if 200 <= code < 300:
                ok += 1
            else:
                fail += 1
                if len(fail_samples) < 5:
                    fail_samples.append((u, code, body))
            if i % 50 == 0 or i == len(urls):
                print(f"  [{i}/{len(urls)}] ok={ok} fail={fail}")

    print("\n=== SUMMARY ===")
    print(f"  total : {len(urls)}")
    print(f"  ok    : {ok}")
    print(f"  fail  : {fail}")
    if fail_samples:
        print("  first failures:")
        for u, c, b in fail_samples:
            print(f"    [{c}] {u}\n        {b}")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
