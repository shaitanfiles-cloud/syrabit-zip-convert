"""Google Search Console (Search Analytics API) ingestion for the
topic-discovery agent.

Fetches per-query rows for the configured site and writes "near-miss"
candidates (avg position 11–20, the second-page slice that ranks just
out of click range) into the ``gsc_near_miss_queries`` Mongo collection
that ``topic_discovery_service.collect_gsc_near_misses`` reads from.

Auth: service account via ``GOOGLE_INDEXING_SERVICE_ACCOUNT`` (same
secret format as ``google_indexing_client.py`` — raw JSON or base64 of
JSON), with the ``https://www.googleapis.com/auth/webmasters.readonly``
scope.

Configuration (env vars, all optional — adapter no-ops if site URL or
service account is missing so the rest of the nightly run keeps working):
  * GSC_SITE_URL                      — e.g. ``sc-domain:syrabit.ai``
  * GSC_LOOKBACK_DAYS    (default 7)  — window for the analytics query
  * GSC_NEAR_MISS_MIN_POS (default 11)
  * GSC_NEAR_MISS_MAX_POS (default 20)
  * GSC_ROW_LIMIT        (default 5000)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GSC_NEAR_MISS_COLLECTION = "gsc_near_miss_queries"
_GSC_API = "https://searchconsole.googleapis.com/webmasters/v3"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def _load_service_account() -> Optional[Dict[str, Any]]:
    """Reuses the same secret format as google_indexing_client (raw
    JSON or base64-of-JSON) to avoid forcing operators to maintain two
    copies of the same key."""
    raw = os.getenv("GOOGLE_INDEXING_SERVICE_ACCOUNT", "").strip()
    if not raw:
        return None
    candidate = raw
    if not candidate.lstrip().startswith("{"):
        try:
            candidate = base64.b64decode(raw).decode("utf-8")
        except Exception as exc:
            logger.warning("gsc: secret base64 decode failed: %s", exc)
            return None
    try:
        info = json.loads(candidate)
    except Exception as exc:
        logger.warning("gsc: secret JSON decode failed: %s", exc)
        return None
    if not all(k in info for k in ("client_email", "private_key", "token_uri")):
        return None
    return info


async def _mint_access_token(client: httpx.AsyncClient,
                             sa: Dict[str, Any]) -> Optional[str]:
    """JWT-bearer flow → access token. Defers cryptography imports to
    call time so the module loads even on hosts without the package."""
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception as exc:
        logger.warning("gsc: cryptography unavailable: %s", exc)
        return None
    iat = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": sa["client_email"], "scope": _SCOPE,
        "aud": sa.get("token_uri") or _TOKEN_URI,
        "iat": iat, "exp": iat + 3600,
    }

    def _b64(d: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(d, separators=(",", ":")).encode("utf-8"),
        ).rstrip(b"=").decode("ascii")
    signing_input = f"{_b64(header)}.{_b64(payload)}".encode("ascii")
    try:
        key = serialization.load_pem_private_key(
            sa["private_key"].encode("utf-8"), password=None,
        )
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        logger.warning("gsc: jwt sign failed: %s", exc)
        return None
    jwt = signing_input.decode("ascii") + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    try:
        res = await client.post(
            sa.get("token_uri") or _TOKEN_URI,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt,
            },
            timeout=10.0,
        )
        if res.status_code != 200:
            logger.warning("gsc: token endpoint %s: %s",
                           res.status_code, res.text[:200])
            return None
        return res.json().get("access_token")
    except Exception as exc:
        logger.warning("gsc: token mint failed: %s", exc)
        return None


async def fetch_near_miss_rows(
    *,
    site_url: str,
    lookback_days: int = 7,
    row_limit: int = 5000,
    min_pos: float = 11.0,
    max_pos: float = 20.0,
    client: Optional[httpx.AsyncClient] = None,
    now: Optional[datetime] = None,
    sa_loader=_load_service_account,
    token_minter=_mint_access_token,
) -> List[Dict[str, Any]]:
    """Hit the Search Analytics API and return near-miss query rows.

    Returns a list of dicts shaped to match the schema
    ``collect_gsc_near_misses`` expects:
    ``{query, position, impressions, clicks, ctr, recorded_at}``.
    Empty list on any failure (auth missing, network error, etc.).
    """
    sa = sa_loader()
    if not sa or not site_url:
        return []
    now = now or datetime.now(timezone.utc)
    end_date = now.date()
    start_date = (now - timedelta(days=max(1, int(lookback_days)))).date()

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        token = await token_minter(client, sa)
        if not token:
            return []
        path = f"/sites/{site_url}/searchAnalytics/query"
        body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": ["query"],
            "rowLimit": int(row_limit),
            "type": "web",
        }
        try:
            res = await client.post(
                _GSC_API + path, json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
        except Exception as exc:
            logger.warning("gsc: API call failed: %s", exc)
            return []
        if res.status_code != 200:
            logger.warning("gsc: API %s: %s", res.status_code, res.text[:200])
            return []
        rows = (res.json() or {}).get("rows") or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            pos = float(r.get("position") or 0.0)
            if pos < min_pos or pos > max_pos:
                continue
            keys = r.get("keys") or []
            query = keys[0] if keys else ""
            if not query:
                continue
            out.append({
                "query": str(query),
                "position": pos,
                "impressions": int(r.get("impressions") or 0),
                "clicks": int(r.get("clicks") or 0),
                "ctr": float(r.get("ctr") or 0.0),
                "recorded_at": now,
            })
        return out
    finally:
        if own_client:
            await client.aclose()


async def ingest_near_miss_into_mongo(
    db: Any, *, now: Optional[datetime] = None, **fetch_kwargs,
) -> int:
    """End-to-end: fetch from GSC → upsert into the Mongo collection
    that the discovery agent reads. Returns the number of rows
    upserted (0 on no-op / failure).
    """
    if db is None:
        return 0
    site_url = fetch_kwargs.pop("site_url", None) or os.environ.get("GSC_SITE_URL", "")
    if not site_url:
        return 0
    lookback = int(os.environ.get("GSC_LOOKBACK_DAYS",
                                  fetch_kwargs.pop("lookback_days", 7)))
    min_pos = float(os.environ.get("GSC_NEAR_MISS_MIN_POS",
                                   fetch_kwargs.pop("min_pos", 11)))
    max_pos = float(os.environ.get("GSC_NEAR_MISS_MAX_POS",
                                   fetch_kwargs.pop("max_pos", 20)))
    row_limit = int(os.environ.get("GSC_ROW_LIMIT",
                                   fetch_kwargs.pop("row_limit", 5000)))
    rows = await fetch_near_miss_rows(
        site_url=site_url, lookback_days=lookback,
        row_limit=row_limit, min_pos=min_pos, max_pos=max_pos,
        now=now, **fetch_kwargs,
    )
    if not rows:
        return 0
    coll = db[GSC_NEAR_MISS_COLLECTION]
    n = 0
    for row in rows:
        try:
            await coll.update_one(
                {"query": row["query"]},
                {"$set": row},
                upsert=True,
            )
            n += 1
        except Exception as exc:
            logger.info("gsc: upsert failed for %r: %s", row["query"], exc)
    return n
