#!/usr/bin/env python3
"""Cloudflare Ray ID → firing-rule lookup (Task #817).

Given a Cloudflare Ray ID printed on a "Sorry, you have been blocked" /
challenge interstitial, this script queries the Cloudflare GraphQL
``firewallEventsAdaptive`` dataset to retrieve the rule that fired, the
action taken, the requested URL, the client country / ASN, and the
user agent.

Why this exists
---------------
Operators get a Ray ID screenshot from a user every few weeks. Without a
canned procedure they end up clicking through the dashboard's Security
Events page filtered by Ray ID — which is fine, but slow, and impossible
to share. This script gives a one-line CLI answer that goes straight
into the incident channel.

Usage
-----

    python scripts/cf_ray_lookup.py 9f14bccc891a6ebf
    python scripts/cf_ray_lookup.py 9f14bccc891a6ebf --days 2 --json

Required env vars (the same ones the analytics client already uses):
    CF_ZONE_ID                  zone id (hex)
    CLOUDFLARE_ANALYTICS_TOKEN  Bearer token with Zone Analytics:Read
                                (the legacy aliases CF_ANALYTICS_API_TOKEN
                                and CLOUDFLARE_API_TOKEN are also accepted)

The Cloudflare GraphQL API caps a single ``firewallEventsAdaptive`` query
to a 1-day window, so this script walks back day-by-day until either a
matching event is found or ``--days`` is exhausted (default 7).

Exit code is 0 when an event is found, 1 when nothing matches in the
requested window, and 2 on configuration / network errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"

# Time-window cap enforced by Cloudflare for firewallEventsAdaptive.
WINDOW_DAYS = 1

# The set of fields we ask for. Keep this minimal — every additional
# field counts toward Cloudflare's adaptive sampling threshold.
QUERY = """
query RayLookup($zoneTag: String!, $since: Time!, $until: Time!, $ray: String!) {
  viewer {
    zones(filter: { zoneTag: $zoneTag }) {
      firewallEventsAdaptive(
        filter: { datetime_geq: $since, datetime_leq: $until, rayName: $ray }
        limit: 20
        orderBy: [datetime_DESC]
      ) {
        action
        source
        ruleId
        rayName
        datetime
        clientCountryName
        clientASNDescription
        clientRequestPath
        clientRequestHTTPHost
        clientRequestHTTPMethodName
        userAgent
        edgeResponseStatus
        description
      }
    }
  }
}
"""


def _resolve_token() -> Optional[str]:
    for name in (
        "CLOUDFLARE_ANALYTICS_TOKEN",
        "CF_ANALYTICS_API_TOKEN",
        "CLOUDFLARE_API_TOKEN",
    ):
        v = os.environ.get(name)
        if v:
            return v.strip()
    return None


def _query_window(zone_id: str, token: str, ray: str, since: str, until: str) -> dict:
    body = json.dumps(
        {
            "query": QUERY,
            "variables": {"zoneTag": zone_id, "since": since, "until": until, "ray": ray},
        }
    ).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def lookup_ray(ray: str, days: int = 7) -> Optional[dict]:
    """Return the most recent firewall event matching ``ray`` within the
    last ``days`` days, or ``None`` if no event is found."""
    zone_id = os.environ.get("CF_ZONE_ID") or os.environ.get("CLOUDFLARE_ZONE_ID")
    token = _resolve_token()
    if not zone_id or not token:
        raise RuntimeError(
            "CF_ZONE_ID and a Cloudflare API token (CLOUDFLARE_ANALYTICS_TOKEN, "
            "CF_ANALYTICS_API_TOKEN, or CLOUDFLARE_API_TOKEN) must be set"
        )

    now = datetime.now(timezone.utc)
    for d in range(max(1, days)):
        until = (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
        since = (now - timedelta(days=d + WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            payload = _query_window(zone_id, token, ray, since, until)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Cloudflare GraphQL HTTP {exc.code}: "
                f"{exc.read()[:300].decode(errors='replace')}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Cloudflare GraphQL transport error: {exc}") from exc

        errors = payload.get("errors")
        if errors:
            raise RuntimeError(f"Cloudflare GraphQL errors: {errors}")

        zones = (payload.get("data") or {}).get("viewer", {}).get("zones") or []
        events = zones[0].get("firewallEventsAdaptive", []) if zones else []
        if events:
            return events[0]
    return None


def _format_human(event: dict) -> str:
    keys = (
        "datetime",
        "rayName",
        "action",
        "source",
        "ruleId",
        "description",
        "edgeResponseStatus",
        "clientRequestHTTPMethodName",
        "clientRequestHTTPHost",
        "clientRequestPath",
        "clientCountryName",
        "clientASNDescription",
        "userAgent",
    )
    width = max(len(k) for k in keys)
    return "\n".join(f"{k.ljust(width)}  {event.get(k, '')}" for k in keys)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("ray", help="Cloudflare Ray ID (the 16-hex prefix is fine)")
    p.add_argument("--days", type=int, default=7, help="lookback window in days (default 7)")
    p.add_argument("--json", action="store_true", help="emit raw JSON instead of a table")
    args = p.parse_args(argv)

    # CF Ray IDs are sometimes copied with a "-XXX" POP suffix; the
    # rayName field stores only the 16-hex prefix.
    ray = args.ray.split("-", 1)[0].strip().lower()
    if not ray:
        print("ray ID is empty", file=sys.stderr)
        return 2

    try:
        event = lookup_ray(ray, days=args.days)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not event:
        print(
            f"No firewall event found for Ray {ray} in the last {args.days} day(s). "
            "It may be older than CF's retention (~31d on the free plan), or it "
            "may have been an Access challenge / Pages-side block (not in "
            "firewallEventsAdaptive). Check the Cloudflare dashboard → "
            "Security → Events page for a wider view.",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(json.dumps(event, indent=2))
    else:
        print(_format_human(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
