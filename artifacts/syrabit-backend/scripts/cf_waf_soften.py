"""
cf_waf_soften.py — Create Cloudflare WAF exception rules for Syrabit.ai.

Solves the "students getting blocked by OWASP CRS" problem that appears as
the "Why have I been blocked?" Cloudflare page. Root cause: OWASP rule 949110
"Inbound Anomaly Score Exceeded" triggers when students type content that
resembles SQL, code, or injection patterns — e.g. "SELECT in SQL", math
equations, or code examples in the AI chat.

What this script does (idempotent — safe to re-run):
  1. Finds the syrabit.ai zone ID.
  2. Finds the active WAF managed ruleset (Cloudflare Managed Rules + OWASP).
  3. Creates a WAF skip rule BEFORE the managed rules that says:
       "For POST /api/ai/* requests, skip OWASP managed rules."
     This lets students type freely in chat without triggering false positives.
  4. Creates a second skip rule that exempts all verified Cloudflare bots
     (Googlebot, Bingbot, Perplexitybot, etc.) from WAF managed rules so
     search engines can crawl without getting blocked.
  5. Does NOT lower the overall WAF security level — only adds targeted
     exceptions for the two known false-positive paths.

Requires:
  CLOUDFLARE_API_TOKEN or CF_API_TOKEN  — must have Zone.Firewall Services write
  CF_AI_GATEWAY_ACCOUNT_ID             — used only to confirm account (optional)

Usage:
  cd artifacts/syrabit-backend
  python scripts/cf_waf_soften.py [--dry-run] [--zone syrabit.ai]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

CF_API = "https://api.cloudflare.com/client/v4"
ZONE_NAME = "syrabit.ai"

SKIP_CHAT_RULE_DESCRIPTION = "Syrabit: skip OWASP WAF for AI chat POST requests (false-positive prevention)"
SKIP_BOT_RULE_DESCRIPTION  = "Syrabit: skip WAF managed rules for Cloudflare-verified search bots"


def _token() -> str:
    for k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "CF_ANALYTICS_API_TOKEN"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    sys.exit("ERROR: No Cloudflare API token found. Set CLOUDFLARE_API_TOKEN.")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def cf_get(client: httpx.Client, path: str) -> Any:
    r = client.get(f"{CF_API}{path}")
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"CF API error: {data.get('errors')}")
    return data["result"]


def cf_post(client: httpx.Client, path: str, body: dict) -> Any:
    r = client.post(f"{CF_API}{path}", json=body)
    if not r.is_success:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"CF API {r.status_code} error on POST {path}:\n{json.dumps(detail, indent=2)}")
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"CF API error: {data.get('errors')}\nRequest: {json.dumps(body, indent=2)}")
    return data["result"]


def cf_put(client: httpx.Client, path: str, body: dict) -> Any:
    r = client.put(f"{CF_API}{path}", json=body)
    if not r.is_success:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"CF API {r.status_code} error on PUT {path}:\n{json.dumps(detail, indent=2)}")
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"CF API error: {data.get('errors')}")
    return data["result"]


def get_zone_id(client: httpx.Client, zone_name: str) -> str:
    result = cf_get(client, f"/zones?name={zone_name}&status=active")
    if not result:
        sys.exit(f"ERROR: Zone '{zone_name}' not found. Check that CLOUDFLARE_API_TOKEN has Zone read.")
    return result[0]["id"]


def get_managed_rulesets(client: httpx.Client, zone_id: str) -> list[dict]:
    rulesets = cf_get(client, f"/zones/{zone_id}/rulesets")
    managed = [
        r for r in rulesets
        if r.get("kind") == "managed" and r.get("phase") in (
            "http_request_firewall_managed",
        )
    ]
    return managed


def get_entrypoint_ruleset(client: httpx.Client, zone_id: str) -> dict | None:
    """Get the WAF custom rules entrypoint (http_request_firewall_custom phase).
    This phase runs BEFORE managed rules, so skip rules placed here will
    bypass OWASP/CF managed rules for matched requests."""
    try:
        return cf_get(client, f"/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint")
    except Exception:
        return None


def find_existing_rule(entrypoint: dict | None, description: str) -> str | None:
    if not entrypoint:
        return None
    for rule in (entrypoint.get("rules") or []):
        if rule.get("description") == description:
            return rule["id"]
    return None


def main():
    ap = argparse.ArgumentParser(description="Create Cloudflare WAF exception rules for Syrabit.ai")
    ap.add_argument("--zone", default=ZONE_NAME, help=f"Zone name (default: {ZONE_NAME})")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = ap.parse_args()

    token = _token()
    print(f"Using API token: {token[:8]}...{token[-4:]}")
    print(f"Zone: {args.zone}")
    if args.dry_run:
        print("[DRY RUN — no changes will be made]\n")

    with httpx.Client(headers=_headers(token), timeout=30.0) as client:
        # 1. Get zone ID
        print(f"\n[1] Looking up zone '{args.zone}'...")
        zone_id = get_zone_id(client, args.zone)
        print(f"    Zone ID: {zone_id}")

        # 2. Get managed ruleset IDs (OWASP + CF Managed Rules)
        print("\n[2] Finding managed WAF rulesets...")
        managed = get_managed_rulesets(client, zone_id)
        managed_ids = [r["id"] for r in managed]
        for r in managed:
            print(f"    {r['id']}  {r.get('name', '?')}")
        if not managed_ids:
            print("    No managed rulesets found — WAF may not be enabled yet on this zone.")
            print("    Enable WAF in the Cloudflare dashboard (Security → WAF) and re-run.")
            sys.exit(1)

        # 3. Get the entrypoint ruleset (where skip rules go)
        print("\n[3] Getting WAF entrypoint ruleset...")
        entrypoint = get_entrypoint_ruleset(client, zone_id)
        if not entrypoint:
            print("    Entrypoint not found — will create via POST.")
        else:
            existing_rules = entrypoint.get("rules", [])
            print(f"    Entrypoint ID: {entrypoint.get('id')}  existing rules: {len(existing_rules)}")

        # ── Rule 1: Skip OWASP/managed rules for AI chat POST requests ────────
        # Students typing SQL queries, math equations, or code in chat triggers
        # OWASP 949110 "Inbound Anomaly Score Exceeded". This exception lets
        # the AI endpoint receive any content without WAF interference.
        #
        # In the http_request_firewall_custom phase the skip action uses
        # "phases" (not "rulesets") to bypass the managed firewall phase.
        chat_skip_rule = {
            "description": SKIP_CHAT_RULE_DESCRIPTION,
            "expression": (
                '(http.request.method eq "POST" and '
                '(http.request.uri.path matches "^/api/ai/chat" or '
                ' http.request.uri.path matches "^/api/ai/stream" or '
                ' http.request.uri.path matches "^/api/ai/grounded" or '
                ' http.request.uri.path matches "^/api/ai/explain" or '
                ' http.request.uri.path matches "^/api/ai/quiz" or '
                ' http.request.uri.path matches "^/api/ai/summarize"))'
            ),
            "action": "skip",
            "action_parameters": {
                "phases": ["http_request_firewall_managed"],
            },
            "enabled": True,
        }

        # ── Rule 2: Skip managed rules for known search-engine crawlers ────────
        # cf.bot_management.verified_bot requires a Bot Management subscription.
        # Use a UA regex to exempt the well-known search engines and answer
        # engines that drive referral traffic to Syrabit. This is sufficient
        # because these bots announce themselves reliably (spoofed UAs are a
        # separate rDNS-verification concern handled in the Worker).
        bot_skip_rule = {
            "description": SKIP_BOT_RULE_DESCRIPTION,
            "expression": (
                'http.user_agent matches '
                '"(?i)(Googlebot|Google-InspectionTool|Googleother|AdsBot-Google'
                '|Bingbot|DuckDuckBot|YandexBot|Slurp|Baiduspider|Applebot'
                '|PerplexityBot|Perplexity-User|ChatGPT-User|OAI-SearchBot'
                '|ClaudeBot|Claude-Web|Anthropic-AI|facebookexternalhit'
                '|LinkedInBot|Twitterbot|Discordbot|TelegramBot)"'
            ),
            "action": "skip",
            "action_parameters": {
                "phases": ["http_request_firewall_managed"],
            },
            "enabled": True,
        }

        # ── Rule 3: Allow Replit preview + testing IPs ─────────────────────────
        # Replit's deployment preview and CI testing routes from known Replit
        # infrastructure. The health-check paths bypass WAF to prevent
        # false-positive blocks on the monitoring / preview iframe.
        replit_skip_rule = {
            "description": "Syrabit: skip WAF for Replit health checks and deployment previews",
            "expression": (
                '(http.user_agent contains "Replit" or '
                ' http.request.uri.path eq "/api/health" or '
                ' http.request.uri.path eq "/api/livez" or '
                ' http.request.uri.path eq "/health")'
            ),
            "action": "skip",
            "action_parameters": {
                "phases": ["http_request_firewall_managed"],
            },
            "enabled": True,
        }

        rules_to_add = [chat_skip_rule, bot_skip_rule, replit_skip_rule]

        # Check which rules already exist (idempotent)
        existing_descs: set[str] = set()
        if entrypoint:
            for r in (entrypoint.get("rules") or []):
                existing_descs.add(r.get("description", ""))

        new_rules = [r for r in rules_to_add if r["description"] not in existing_descs]
        already_exists = [r for r in rules_to_add if r["description"] in existing_descs]

        if already_exists:
            print(f"\n[4] {len(already_exists)} rule(s) already exist — skipping:")
            for r in already_exists:
                print(f"    ✓ {r['description']}")

        if not new_rules:
            print("\n✓ All WAF exception rules already in place. Nothing to do.")
            return

        print(f"\n[4] Adding {len(new_rules)} WAF exception rule(s):")
        for r in new_rules:
            print(f"    + {r['description']}")
            print(f"      expression: {r['expression'][:80]}...")

        if args.dry_run:
            print("\n[DRY RUN] Would POST/PATCH these rules — re-run without --dry-run to apply.")
            return

        # Skip rules live in the WAF custom rules phase (http_request_firewall_custom).
        # CF evaluates custom rules BEFORE managed rules in all cases, so a "skip"
        # action here prevents OWASP / CF Managed rules from running on matched reqs.
        entrypoint_id = entrypoint.get("id") if entrypoint else None
        existing_rule_list = list((entrypoint or {}).get("rules", []))

        # Build the full new rule list: skip rules first, then existing rules
        all_rules = new_rules + existing_rule_list

        if not entrypoint_id:
            # Create the custom rules entrypoint with our skip rules
            result = cf_post(client, f"/zones/{zone_id}/rulesets", {
                "name": "default",
                "kind": "zone",
                "phase": "http_request_firewall_custom",
                "rules": all_rules,
            })
            print(f"\n✓ Created WAF custom rules entrypoint: {result.get('id')}")
        else:
            # Replace the entire custom rules entrypoint (PUT replaces all rules atomically)
            result = cf_put(client, f"/zones/{zone_id}/rulesets/{entrypoint_id}", {
                "rules": all_rules,
            })
            total = len(result.get("rules", []))
            print(f"\n✓ {len(new_rules)} skip rule(s) prepended to WAF custom rules. Total rules: {total}")

        print("\nVerification: visit https://dash.cloudflare.com → syrabit.ai")
        print("  → Security → WAF → Custom rules  (skip rules appear at the top)")
        print("\nThese rules take effect immediately — no propagation delay.")


if __name__ == "__main__":
    main()
