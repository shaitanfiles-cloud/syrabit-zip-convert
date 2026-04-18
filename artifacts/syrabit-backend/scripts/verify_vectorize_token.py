"""
Verify that CLOUDFLARE_API_TOKEN has the Vectorize:Edit scope by performing
a no-op upsert + delete against the configured Vectorize index.

Usage (locally or inside the Railway container):
    CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... \
    python scripts/verify_vectorize_token.py

Exit codes:
    0  upsert returned HTTP 200 — token scope is correct
    1  401 Unauthorized — token missing Vectorize:Edit scope (rotate it)
    2  any other failure (network, wrong account id, missing index, etc.)
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

INDEX = os.environ.get("VECTORIZE_INDEX_NAME", "syllabus-index-v2").strip() or "syllabus-index-v2"
DIMS = int(os.environ.get("VECTORIZE_DIMENSIONS", "1024"))


def main() -> int:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        print("ERROR: CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must be set", file=sys.stderr)
        return 2

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

    with httpx.Client(timeout=30) as client:
        r = client.post(f"{base}/upsert", content=body, headers=headers_upsert)
        print(f"upsert  -> HTTP {r.status_code}")
        if r.status_code == 401:
            print("FAIL: 401 Unauthorized. Token is missing Vectorize:Edit scope.", file=sys.stderr)
            print(f"Body: {r.text[:500]}", file=sys.stderr)
            return 1
        if r.status_code != 200:
            print(f"FAIL: unexpected status. Body: {r.text[:500]}", file=sys.stderr)
            return 2

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

    print(f"OK: token has Vectorize:Edit on index '{INDEX}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
