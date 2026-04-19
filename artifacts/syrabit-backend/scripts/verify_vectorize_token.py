"""
Verify that the Cloudflare API tokens used by Syrabit have every scope the
backend needs. Each scope is probed with a minimal, real API call. A 401/403
(or GraphQL ``code=10000`` "Authentication error") on any probe means the
token is missing that scope and the deploy is blocked.

Scopes probed (Task #534 env-name precedence)
---------------------------------------------
* ``Vectorize:Edit``         — runtime token resolved by ``_runtime_token()``
                               (``CLOUDFLARE_ANALYTICS_TOKEN`` preferred, falls
                               back to ``CLOUDFLARE_API_TOKEN``); upserts +
                               deletes a throwaway vector against the
                               configured index.
* ``Zone:Read``              — analytics token resolved by
                               ``_analytics_token()``
                               (``CLOUDFLARE_ANALYTICS_TOKEN`` →
                               ``CF_ANALYTICS_API_TOKEN`` → legacy CF_*);
                               reads the zone object via
                               ``GET /zones/{zone_id}``.
* ``Zone Analytics:Read``    — analytics token runs a tiny
                               ``httpRequests1dGroups`` GraphQL query on
                               the zone.
* ``Account Analytics:Read`` — analytics token runs a tiny
                               ``httpRequestsAdaptiveGroups`` GraphQL query
                               against the account.
* ``Pages:Read`` (probe)     — Pages token resolved by ``_pages_token()``
                               (``CLOUDFLARE_PAGES_TOKEN`` →
                               ``CF_PAGES_API_TOKEN``); lists Pages projects
                               on the account so a future Pages-CI rotation
                               is pre-validated.

Usage (locally or inside the Railway container)::

    CLOUDFLARE_API_TOKEN=...        \\
    CLOUDFLARE_ANALYTICS_TOKEN=...  \\
    CLOUDFLARE_PAGES_TOKEN=...      \\
    CLOUDFLARE_ACCOUNT_ID=...       \\
    CF_ZONE_ID=...                  \\
    python scripts/verify_vectorize_token.py [--predeploy]

Flags
-----
``--predeploy``
    Suitable for use as Railway's ``preDeployCommand``. A real auth failure
    (401/403 or GraphQL ``code=10000``) on any probe still fails the deploy
    with exit 1, but transient errors (network, missing zone, schema drift,
    etc.) and missing env vars downgrade to exit 0 with a warning so a
    Cloudflare blip or an as-yet-unconfigured probe can't block a release.

Exit codes
----------
``0``
    Every probe whose env was supplied returned a non-auth result, OR
    ``--predeploy`` is set and the only failures were transient/non-auth.
``1``
    At least one probe got 401/403/auth-error — the matching scope is
    missing from the token. Rotate it. The log line tells you which
    scope failed.
``2``
    Any other failure (network, wrong account id, missing index, etc.) —
    only returned when ``--predeploy`` is NOT set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

# The analytics token can live under any of these env var names — we resolve
# in priority order so operators don't have to duplicate secrets when the
# same Cloudflare API token is reused for Pages deploy + analytics access.
_ANALYTICS_TOKEN_ENV_NAMES = (
    "CLOUDFLARE_ANALYTICS_TOKEN",
    "CF_ANALYTICS_API_TOKEN",
    "CLOUDFLARE_API_TOKEN",
)
_RUNTIME_TOKEN_ENV_NAMES = (
    "CLOUDFLARE_ANALYTICS_TOKEN",
    "CLOUDFLARE_API_TOKEN",
)
_PAGES_TOKEN_ENV_NAMES = (
    "CLOUDFLARE_PAGES_TOKEN",
    "CF_PAGES_API_TOKEN",
)


def _analytics_token() -> str:
    for _name in _ANALYTICS_TOKEN_ENV_NAMES:
        _val = os.environ.get(_name, "").strip()
        if _val:
            return _val
    return ""


def _runtime_token() -> str:
    """Vectorize / Cache-Purge token (Task #534 spec name first)."""
    for _name in _RUNTIME_TOKEN_ENV_NAMES:
        _val = os.environ.get(_name, "").strip()
        if _val:
            return _val
    return ""


def _pages_token() -> str:
    """Pages CI / Wrangler deploy token (Task #534 spec name first)."""
    for _name in _PAGES_TOKEN_ENV_NAMES:
        _val = os.environ.get(_name, "").strip()
        if _val:
            return _val
    return ""


_ANALYTICS_TOKEN_HINT = " / ".join(_ANALYTICS_TOKEN_ENV_NAMES)


INDEX = os.environ.get("VECTORIZE_INDEX_NAME", "syllabus-index-v2").strip() or "syllabus-index-v2"
try:
    DIMS = int(os.environ.get("VECTORIZE_DIMENSIONS", "1024"))
except ValueError:
    DIMS = 1024

# CF "auth error" codes — see cloudflare_client._looks_like_auth_error.
# These appear in both the GraphQL `errors[].code` field and the REST
# envelope `errors[].code` field, so we use the same set for both.
AUTH_ERROR_CODES = {10000, 9109, 9106, 9103}


@dataclass
class ProbeResult:
    scope: str               # human-readable scope name, e.g. "Vectorize:Edit"
    status: str              # "ok" | "auth_fail" | "transient" | "skipped"
    detail: str              # short explanation for the deploy log


def _classify_cf_errors(payload: dict) -> Optional[str]:
    """Return a short description if the CF response payload (REST envelope
    or GraphQL) carries an auth/permission error, else ``None``. Mirrors
    ``cloudflare_client._looks_like_auth_error``."""
    errs = payload.get("errors") if isinstance(payload, dict) else None
    if not errs:
        return None
    for e in errs:
        code = e.get("code") if isinstance(e, dict) else None
        msg = (e.get("message") if isinstance(e, dict) else str(e)) or ""
        if (
            code in AUTH_ERROR_CODES
            or "Authentication error" in msg
            or "Unauthorized" in msg
            or "Invalid access token" in msg
            or "permission" in msg.lower()
        ):
            return f"code={code} msg={msg[:160]}"
    return None


def _probe_vectorize_edit(client: httpx.Client) -> ProbeResult:
    scope = "Vectorize:Edit"
    # Task #534: route through the runtime-token resolver so we exercise the
    # exact code path the backend uses (CLOUDFLARE_ANALYTICS_TOKEN preferred,
    # legacy CLOUDFLARE_API_TOKEN fallback).
    token = _runtime_token()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        return ProbeResult(scope, "skipped",
                           "CLOUDFLARE_ANALYTICS_TOKEN / CLOUDFLARE_API_TOKEN "
                           "or CLOUDFLARE_ACCOUNT_ID not set")

    test_id = f"verify-token-{uuid.uuid4()}"
    body = json.dumps({
        "id": test_id,
        "values": [0.0] * DIMS,
        "metadata": {"source": "verify_vectorize_token"},
    }, ensure_ascii=False).encode("utf-8")

    base = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/vectorize/v2/indexes/{INDEX}"
    )
    try:
        r = client.post(
            f"{base}/upsert",
            content=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-ndjson",
            },
        )
    except httpx.HTTPError as exc:
        return ProbeResult(scope, "transient", f"network/HTTP error: {exc}")

    if r.status_code in (401, 403):
        return ProbeResult(scope, "auth_fail",
                           f"HTTP {r.status_code} on /vectorize upsert — body: {r.text[:240]}")
    if r.status_code != 200:
        return ProbeResult(scope, "transient",
                           f"HTTP {r.status_code} (non-auth) — body: {r.text[:240]}")

    # Best-effort cleanup so we don't leave a junk vector behind.
    try:
        client.post(
            f"{base}/delete_by_ids",
            content=json.dumps({"ids": [test_id]}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return ProbeResult(scope, "ok", f"upsert+cleanup against index '{INDEX}' OK")


def _probe_pages_read(client: httpx.Client) -> ProbeResult:
    """Lists Pages projects on the account. Validates the Pages CI token
    independently from runtime/analytics so a Pages-token rotation can be
    pre-flighted by the same script (Task #534)."""
    scope = "Pages:Read"
    token = _pages_token()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        return ProbeResult(scope, "skipped",
                           "CLOUDFLARE_PAGES_TOKEN / CF_PAGES_API_TOKEN "
                           "or CLOUDFLARE_ACCOUNT_ID not set")
    try:
        r = client.get(
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects",
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": 1},
        )
    except httpx.HTTPError as exc:
        return ProbeResult(scope, "transient", f"network/HTTP error: {exc}")
    if r.status_code in (401, 403):
        return ProbeResult(scope, "auth_fail",
                           f"HTTP {r.status_code} on GET /pages/projects — body: {r.text[:240]}")
    if r.status_code != 200:
        return ProbeResult(scope, "transient",
                           f"HTTP {r.status_code} (non-auth) — body: {r.text[:240]}")
    return ProbeResult(scope, "ok", "GET /pages/projects returned 200")


def _probe_zone_read(client: httpx.Client) -> ProbeResult:
    scope = "Zone:Read"
    token = _analytics_token()
    zone_id = os.environ.get("CF_ZONE_ID", "").strip()
    if not token or not zone_id:
        return ProbeResult(scope, "skipped",
                           f"{_ANALYTICS_TOKEN_HINT} / CF_ZONE_ID not set")
    try:
        r = client.get(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        return ProbeResult(scope, "transient", f"network/HTTP error: {exc}")

    if r.status_code in (401, 403):
        return ProbeResult(scope, "auth_fail",
                           f"HTTP {r.status_code} on GET /zones/{{id}} — body: {r.text[:240]}")
    if r.status_code != 200:
        return ProbeResult(scope, "transient",
                           f"HTTP {r.status_code} (non-auth) — body: {r.text[:240]}")
    try:
        payload = r.json()
    except ValueError:
        return ProbeResult(scope, "transient", f"non-JSON body: {r.text[:240]}")
    auth_err = _classify_cf_errors(payload)
    if auth_err:
        return ProbeResult(scope, "auth_fail", f"REST auth error: {auth_err}")
    if not payload.get("success", False):
        # `success: false` from the REST envelope without a recognized
        # auth/permission code — treat as transient (resource/config issue,
        # not a missing scope) so we don't false-positive a deploy block.
        return ProbeResult(scope, "transient",
                           f"success=false (non-auth) — errors: {payload.get('errors')}")
    return ProbeResult(scope, "ok", "GET /zones/{id} returned 200")


def _probe_graphql(
    client: httpx.Client,
    *,
    scope: str,
    token: str,
    query: str,
    variables: dict,
    skip_reason: Optional[str],
) -> ProbeResult:
    if skip_reason:
        return ProbeResult(scope, "skipped", skip_reason)
    try:
        r = client.post(
            "https://api.cloudflare.com/client/v4/graphql",
            json={"query": query, "variables": variables},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
    except httpx.HTTPError as exc:
        return ProbeResult(scope, "transient", f"network/HTTP error: {exc}")

    if r.status_code in (401, 403):
        return ProbeResult(scope, "auth_fail",
                           f"HTTP {r.status_code} on GraphQL — body: {r.text[:240]}")
    if r.status_code != 200:
        return ProbeResult(scope, "transient",
                           f"HTTP {r.status_code} (non-auth) — body: {r.text[:240]}")
    try:
        payload = r.json()
    except ValueError:
        return ProbeResult(scope, "transient", f"non-JSON body: {r.text[:240]}")

    auth_err = _classify_cf_errors(payload)
    if auth_err:
        return ProbeResult(scope, "auth_fail", f"GraphQL auth error: {auth_err}")
    if payload.get("errors"):
        # Non-auth GraphQL errors (schema drift etc.) — treat as transient
        # so a CF schema deprecation doesn't block deploys, but log loudly.
        return ProbeResult(scope, "transient",
                           f"GraphQL non-auth errors: {payload['errors']}")
    return ProbeResult(scope, "ok", "GraphQL probe returned data")


def _probe_zone_analytics(client: httpx.Client) -> ProbeResult:
    token = _analytics_token()
    zone_id = os.environ.get("CF_ZONE_ID", "").strip()
    skip = None if (token and zone_id) else f"{_ANALYTICS_TOKEN_HINT} / CF_ZONE_ID not set"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    query = """
    query VerifyZoneAnalytics($zoneTag: String!, $day: String!) {
      viewer {
        zones(filter: { zoneTag: $zoneTag }) {
          httpRequests1dGroups(
            filter: { date_geq: $day, date_leq: $day }
            limit: 1
          ) {
            sum { requests }
          }
        }
      }
    }
    """
    return _probe_graphql(
        client,
        scope="Zone Analytics:Read",
        token=token,
        query=query,
        variables={"zoneTag": zone_id, "day": today},
        skip_reason=skip,
    )


def _probe_account_analytics(client: httpx.Client) -> ProbeResult:
    token = _analytics_token()
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    skip = None if (token and account_id) else (
        f"{_ANALYTICS_TOKEN_HINT} / CLOUDFLARE_ACCOUNT_ID not set"
    )
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # `httpRequestsAdaptiveGroups` at the account scope requires
    # Account Analytics:Read; if the scope is missing CF returns
    # `code=10000 Authentication error`.
    query = """
    query VerifyAccountAnalytics($acct: String!, $since: Time!, $until: Time!) {
      viewer {
        accounts(filter: { accountTag: $acct }) {
          httpRequestsAdaptiveGroups(
            filter: { datetime_geq: $since, datetime_lt: $until }
            limit: 1
          ) {
            count
          }
        }
      }
    }
    """
    return _probe_graphql(
        client,
        scope="Account Analytics:Read",
        token=token,
        query=query,
        variables={"acct": account_id, "since": since, "until": until},
        skip_reason=skip,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--predeploy",
        action="store_true",
        help=("Downgrade non-auth failures (network, missing env, schema drift) "
              "to exit 0 so transient errors don't block a Railway deploy. Real "
              "auth failures (401/403/code=10000) still fail with exit 1."),
    )
    args = parser.parse_args()
    soft_fail_exit = 0 if args.predeploy else 2

    probes = [
        _probe_vectorize_edit,
        _probe_pages_read,
        _probe_zone_read,
        _probe_zone_analytics,
        _probe_account_analytics,
    ]

    auth_failures: list[ProbeResult] = []
    transient_failures: list[ProbeResult] = []
    skipped: list[ProbeResult] = []
    ok: list[ProbeResult] = []

    with httpx.Client(timeout=30) as client:
        for probe in probes:
            result = probe(client)
            tag = {
                "ok": "OK     ",
                "auth_fail": "FAIL   ",
                "transient": "WARN   ",
                "skipped": "SKIP   ",
            }.get(result.status, "?      ")
            print(f"{tag} {result.scope:<25} {result.detail}")
            if result.status == "auth_fail":
                auth_failures.append(result)
            elif result.status == "transient":
                transient_failures.append(result)
            elif result.status == "skipped":
                skipped.append(result)
            else:
                ok.append(result)

    print()
    print(
        f"Summary: {len(ok)} ok, {len(auth_failures)} auth-fail, "
        f"{len(transient_failures)} transient, {len(skipped)} skipped."
    )

    if auth_failures:
        missing = ", ".join(p.scope for p in auth_failures)
        print(
            f"FAIL: token is missing scope(s): {missing}. "
            "Rotate the affected Cloudflare API token (see "
            "cloudflare_client.get_auth_status().rotation_hint for the full "
            "scope list).",
            file=sys.stderr,
        )
        # Auth failures always block, even in --predeploy mode.
        return 1

    if transient_failures:
        details = "; ".join(f"{p.scope}: {p.detail}" for p in transient_failures)
        print(f"WARN: transient probe failures: {details}", file=sys.stderr)
        if args.predeploy:
            print("WARN: predeploy mode — transient failures do not block the deploy.",
                  file=sys.stderr)
        return soft_fail_exit if not args.predeploy else 0

    if skipped:
        details = "; ".join(f"{p.scope}: {p.detail}" for p in skipped)
        print(f"NOTE: skipped probes (env not set): {details}", file=sys.stderr)
        if not ok:
            # Nothing actually verified.
            if args.predeploy:
                print("WARN: no probes ran — predeploy mode, deploy not blocked.",
                      file=sys.stderr)
                return 0
            return soft_fail_exit

    print("OK: all probed Cloudflare token scopes are present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
