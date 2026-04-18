"""
Verify that CLOUDFLARE_API_TOKEN has the Vectorize:Edit scope by performing
a no-op upsert + delete against the configured Vectorize index.

Usage (locally or inside the Railway container):
    CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... \
    python scripts/verify_vectorize_token.py [--predeploy]

Flags:
    --predeploy  Suitable for use as Railway's preDeployCommand. A real 401
                 (wrong-scope token) still fails the deploy with exit 1, but
                 transient errors (network, missing index, etc.) downgrade
                 to exit 0 with a warning so a Cloudflare blip can't block
                 a release.

Exit codes:
    0  upsert returned HTTP 200 — token scope is correct
       (or --predeploy and the failure was non-401)
    1  401 Unauthorized — token missing Vectorize:Edit scope (rotate it)
    2  any other failure (network, wrong account id, missing index, etc.)
       — only returned when --predeploy is NOT set
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import httpx

INDEX = os.environ.get("VECTORIZE_INDEX_NAME", "syllabus-index-v2").strip() or "syllabus-index-v2"
try:
    DIMS = int(os.environ.get("VECTORIZE_DIMENSIONS", "1024"))
except ValueError:
    DIMS = 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--predeploy",
        action="store_true",
        help="Downgrade non-401 failures to exit 0 so transient errors don't block a Railway deploy.",
    )
    args = parser.parse_args()
    soft_fail_exit = 0 if args.predeploy else 2

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        print("ERROR: CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must be set", file=sys.stderr)
        if args.predeploy:
            print("WARN: skipping verification (predeploy mode) — deploy not blocked.", file=sys.stderr)
        return soft_fail_exit

    test_id = f"verify-token-{uuid.uuid4()}"
    vector = [0.0] * DIMS
    body = json.dumps({
        "id": test_id,
        "values": vector,
        "metadata": {"source": "verify_vectorize_token"},
    }, ensure_ascii=False).encode("utf-8")

    base = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/vectorize/v2/indexes/{INDEX}"
    headers_upsert = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-ndjson",
    }
    headers_json = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(f"{base}/upsert", content=body, headers=headers_upsert)
            print(f"upsert  -> HTTP {r.status_code}")
            if r.status_code in (401, 403):
                print(
                    f"FAIL: HTTP {r.status_code}. Token is missing Vectorize:Edit scope (or denied).",
                    file=sys.stderr,
                )
                print(f"Body: {r.text[:500]}", file=sys.stderr)
                return 1
            if r.status_code != 200:
                print(f"FAIL: unexpected status. Body: {r.text[:500]}", file=sys.stderr)
                if args.predeploy:
                    print("WARN: non-401 failure in predeploy mode — deploy not blocked.", file=sys.stderr)
                return soft_fail_exit

            # Best-effort cleanup so we don't leave a junk vector behind.
            try:
                d = client.post(
                    f"{base}/delete_by_ids",
                    content=json.dumps({"ids": [test_id]}).encode("utf-8"),
                    headers=headers_json,
                )
                print(f"cleanup -> HTTP {d.status_code}")
            except Exception as exc:  # noqa: BLE001
                print(f"cleanup failed (non-fatal): {exc}")
    except httpx.HTTPError as exc:
        print(f"FAIL: network/HTTP error contacting Cloudflare: {exc}", file=sys.stderr)
        if args.predeploy:
            print("WARN: network error in predeploy mode — deploy not blocked.", file=sys.stderr)
        return soft_fail_exit

    print(f"OK: token has Vectorize:Edit on index '{INDEX}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
