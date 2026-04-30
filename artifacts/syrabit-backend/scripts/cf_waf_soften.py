"""
cf_waf_soften.py — Comprehensive Cloudflare WAF tuning for Syrabit.ai.

Solves three classes of WAF false-positives that hurt discoverability and
user access:

  SEO  — Search Engine Optimization crawlers (Googlebot, Bingbot, Yandex,
          SEMrush, Ahrefs, Moz) must crawl pages without WAF interference.
  GEO  — Generative Engine Optimization: AI answer engines that index
          content to cite in generated answers (Perplexity, ChatGPT Search,
          Claude web-search, Gemini, Brave Leo, You.com).
  AEO  — Answer Engine Optimization: voice assistants, snippet fetchers,
          and AI-powered search tools that need to read page content.
  Users — Real students, especially on Indian mobile networks (Airtel,
          BSNL, Jio), were blocked by OWASP CRS 949110 on plain GET / (the
          homepage). This was the Ray ID 9f46af9e9ddaf655 incident.

Root cause: OWASP CRS injection rules (SQLi, XSS, RFI) examine request
bodies to detect attacks. They should ONLY run on POST/PUT/PATCH requests
that carry user-controlled input. Firing them on GET page-loads is
categorically incorrect — a GET / has no body, so every match is a false
positive.

What this script sets up (idempotent — safe to re-run, old Syrabit rules
are replaced atomically, third-party rules are preserved):

  Rule A — "GET safe pass"
    Skip OWASP managed rules for ALL GET, HEAD, OPTIONS requests.
    Effect: 100% of page loads, all crawlers, all link-preview bots,
            all monitoring pings pass through without OWASP check.
            Attack surface not increased — no injection is possible via
            GET (no request body).

  Rule B — "SEO + GEO + AEO bot pass"
    Skip OWASP managed rules for POST/PUT by known crawler UAs.
    Covers: traditional SEO bots, GEO indexing bots, AEO answer-engine
            bots, social-preview bots, and monitoring user-agents.
    Effect: All crawlers that occasionally POST (e.g. form-discovery
            during site audit) pass through cleanly.

  Rule C — "AI chat pass"
    Skip OWASP managed rules for POST to /api/ai/* endpoints.
    Effect: Students can type SQL examples, math, code, or programming
            questions in chat without triggering OWASP injection rules.
    Security note: The worker applies its own JWT/rate-limit/content
            checks on these routes, so OWASP is not the primary defense.

  Rule D — "Health + monitoring pass"
    Skip OWASP managed rules for health-check paths and Replit UA.
    Effect: Uptime monitors, Replit preview iframe, and deployment
            health checks pass without WAF interference.

Requires:
  CLOUDFLARE_API_TOKEN or CF_API_TOKEN  — Zone:Firewall Services:Write
  Zone must be on a plan that includes WAF (Pro or above).

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

CF_API   = "https://api.cloudflare.com/client/v4"
ZONE_NAME = "syrabit.ai"

# All rule descriptions are prefixed so the script can identify and
# replace its own rules without touching third-party custom rules.
_PREFIX = "Syrabit:"

RULE_GET_PASS    = f"{_PREFIX} (A) skip OWASP for all GET/HEAD/OPTIONS — no injection possible via page loads"
RULE_BOT_PASS    = f"{_PREFIX} (B) skip OWASP for SEO+GEO+AEO crawlers — SEO/GEO/AEO bot user-agents"
RULE_CHAT_PASS   = f"{_PREFIX} (C) skip OWASP for AI chat POST — students can type code/SQL without block"
RULE_HEALTH_PASS = f"{_PREFIX} (D) skip OWASP for health checks + Replit preview"


def _token() -> str:
    for k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "CF_ANALYTICS_API_TOKEN"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    sys.exit("ERROR: No Cloudflare API token found. Set CLOUDFLARE_API_TOKEN.")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _api(client: httpx.Client, method: str, path: str, body: dict | None = None) -> Any:
    url = f"{CF_API}{path}"
    r = client.request(method, url, json=body)
    if not r.is_success:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(
            f"CF API {r.status_code} on {method} {path}:\n"
            f"{json.dumps(detail, indent=2)}"
        )
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"CF API logic error: {data.get('errors')}")
    return data["result"]


def get_zone_id(client: httpx.Client, zone_name: str) -> str:
    result = _api(client, "GET", f"/zones?name={zone_name}&status=active")
    if not result:
        sys.exit(f"ERROR: Zone '{zone_name}' not found. Check that the API token has Zone read.")
    return result[0]["id"]


def get_managed_ruleset_ids(client: httpx.Client, zone_id: str) -> list[str]:
    rulesets = _api(client, "GET", f"/zones/{zone_id}/rulesets")
    return [
        r["id"] for r in rulesets
        if r.get("kind") == "managed"
        and r.get("phase") == "http_request_firewall_managed"
    ]


def get_custom_entrypoint(client: httpx.Client, zone_id: str) -> dict | None:
    """Return the http_request_firewall_custom entrypoint, or None if not yet created."""
    try:
        return _api(client, "GET",
                    f"/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint")
    except Exception:
        return None


def build_rules() -> list[dict]:
    """Return the canonical ordered list of Syrabit WAF skip rules."""

    # ── Rule A: Skip OWASP for ALL GET / HEAD / OPTIONS ──────────────────────
    # OWASP injection rules (SQLi, XSS, RFI, RCE) detect malicious payloads
    # in request *bodies*. GET, HEAD, and OPTIONS have no request body, so
    # every OWASP match on these methods is a false positive by definition.
    # Skipping managed rules for these methods:
    #   • Fixes real-user blocks on the homepage (Indian mobile, Ray ID 9f46af9e9ddaf655)
    #   • Allows ALL search engine crawlers (SEO) — they exclusively use GET
    #   • Allows ALL AI answer-engine indexers (GEO/AEO) — they exclusively use GET
    #   • Allows ALL social-preview bots — they use GET
    #   • Allows ALL uptime monitors, Lighthouse, PageSpeed — they use GET
    # Security impact: None — GET requests cannot inject via a missing body.
    get_pass = {
        "description": RULE_GET_PASS,
        "expression": 'http.request.method in {"GET" "HEAD" "OPTIONS"}',
        "action": "skip",
        "action_parameters": {"phases": ["http_request_firewall_managed"]},
        "enabled": True,
    }

    # ── Rule B: Skip OWASP for POST by known SEO / GEO / AEO bot UAs ────────
    # Some crawlers POST during site audits, form discovery, or structured-data
    # fetches. This rule covers:
    #   SEO  — Googlebot, Bingbot, Yandex, Baidu, DuckDuckBot, Slurp, Applebot
    #           + SEO audit tools: SEMrush, Ahrefs, Moz, Majestic, SiteAudit,
    #             Screaming Frog (Screamingfrog), SE Ranking, Deepcrawl
    #   GEO  — PerplexityBot / Perplexity-User (answer engine with citations)
    #           ChatGPT-User / OAI-SearchBot (ChatGPT browsing mode)
    #           ClaudeBot / Claude-Web / Anthropic-AI (Claude web-search)
    #           BingPreview / bingbot (Bing Copilot indexer)
    #           Gemini / Google-Extended (Google Gemini indexing)
    #           YouBot (You.com AI)
    #           Brave Search (BraveSearch / brave-search)
    #   AEO  — Amazon Alexa (Amazonbot), Apple Siri (Applebot-Extended)
    #           Google Assistant (Googlebot), voice-search crawlers
    #   Social — facebookexternalhit, LinkedInBot, Twitterbot, Discordbot,
    #             Telegrambot, WhatsApp, Slackbot, Pinterestbot
    #   Monitoring — UptimeRobot, StatusCake, Pingdom, GTmetrix, Lighthouse,
    #                PageSpeed Insights, Chrome-Lighthouse, web-check
    bot_ua_pattern = (
        "(?i)("
        # ── SEO: Major search engines ────────────────────────────────────────
        "Googlebot|Google-InspectionTool|Googleother|AdsBot-Google"
        "|Bingbot|BingPreview|DuckDuckBot|YandexBot|Slurp|Baiduspider"
        "|Applebot|NaverBot|Sogou"
        # ── SEO: Professional audit tools ────────────────────────────────────
        "|SemrushBot|AhrefsBot|MJ12bot|DotBot|Rogerbot|MajesticSEO"
        "|ScreamingFrog|SiteAuditBot|SEOkicks|SERPstatBot|SE-Ranking"
        "|DeepCrawl|Deepcrawl|SiteimproveBot|ContentKingBot|OnCrawl"
        "|CrawlomaticBot|Sistrix|RogerBot|SiteCheckerBot"
        # ── GEO: Generative / AI answer engines ──────────────────────────────
        "|PerplexityBot|Perplexity-User"
        "|ChatGPT-User|OAI-SearchBot|GPTBot"
        "|ClaudeBot|Claude-Web|Anthropic-AI"
        "|Gemini|Google-Extended"
        "|YouBot|Cohere-AI"
        "|BraveSearch|brave-search"
        # ── AEO: Voice + answer assistants ───────────────────────────────────
        "|Amazonbot|Applebot-Extended|Alexa"
        # ── Social / preview bots ────────────────────────────────────────────
        "|facebookexternalhit|FacebookBot|LinkedInBot|Twitterbot"
        "|Discordbot|TelegramBot|WhatsApp|Slackbot|Pinterestbot"
        "|RedditBot|SnapchatEmbed"
        # ── Uptime / performance / CI monitoring ─────────────────────────────
        "|UptimeRobot|StatusCake|Pingdom|GTmetrix|PageSpeed"
        "|Chrome-Lighthouse|Lighthouse|web-check|Site24x7|Datadog"
        "|Catchpoint|NewRelicPinger|Dynatrace|Zabbix"
        ")"
    )
    bot_pass = {
        "description": RULE_BOT_PASS,
        "expression": f'http.user_agent matches "{bot_ua_pattern}"',
        "action": "skip",
        "action_parameters": {"phases": ["http_request_firewall_managed"]},
        "enabled": True,
    }

    # ── Rule C: Skip OWASP for AI chat POST endpoints ────────────────────────
    # OWASP 949110 fires when a student types programming questions, SQL
    # examples, math notation, or code in the chat box. The Worker already
    # applies JWT authentication and per-IP rate limiting on these routes,
    # so OWASP is not the primary security control here.
    chat_pass = {
        "description": RULE_CHAT_PASS,
        "expression": (
            'http.request.method eq "POST" and ('
            'http.request.uri.path matches "^/api/ai/"'
            ')'
        ),
        "action": "skip",
        "action_parameters": {"phases": ["http_request_firewall_managed"]},
        "enabled": True,
    }

    # ── Rule D: Health checks + Replit preview ───────────────────────────────
    # Health-check endpoints, Replit's deployment preview iframe, and uptime
    # monitoring pings must pass without WAF interference so the site is
    # correctly reported as "up" and the Replit preview works.
    health_pass = {
        "description": RULE_HEALTH_PASS,
        "expression": (
            'http.user_agent contains "Replit" or '
            'http.request.uri.path in {"/api/health" "/api/livez" "/health" "/healthz" "/ping"}'
        ),
        "action": "skip",
        "action_parameters": {"phases": ["http_request_firewall_managed"]},
        "enabled": True,
    }

    return [get_pass, bot_pass, chat_pass, health_pass]


def main():
    ap = argparse.ArgumentParser(
        description="Apply comprehensive WAF exception rules for Syrabit.ai (SEO/GEO/AEO/users)"
    )
    ap.add_argument("--zone", default=ZONE_NAME, help=f"Zone name (default: {ZONE_NAME})")
    ap.add_argument("--dry-run", action="store_true", help="Print changes without applying them")
    args = ap.parse_args()

    token = _token()
    print(f"Using API token: {token[:8]}...{token[-4:]}")
    print(f"Zone: {args.zone}")
    if args.dry_run:
        print("[DRY RUN — no changes will be made]\n")

    canonical_rules = build_rules()

    with httpx.Client(headers=_headers(token), timeout=30.0) as client:

        # 1. Zone ID
        print(f"\n[1] Looking up zone '{args.zone}'...")
        zone_id = get_zone_id(client, args.zone)
        print(f"    Zone ID: {zone_id}")

        # 2. Managed ruleset IDs (for reference / reporting)
        print("\n[2] Finding managed WAF rulesets...")
        managed_ids = get_managed_ruleset_ids(client, zone_id)
        all_rulesets = _api(client, "GET", f"/zones/{zone_id}/rulesets")
        for r in all_rulesets:
            if r.get("kind") == "managed" and r.get("phase") == "http_request_firewall_managed":
                print(f"    {r['id']}  {r.get('name', '?')}")
        if not managed_ids:
            print("    No managed rulesets — WAF may not be active on this zone.")
            sys.exit(1)

        # 3. Fetch current custom-rules entrypoint
        print("\n[3] Fetching WAF custom-rules entrypoint...")
        entrypoint = get_custom_entrypoint(client, zone_id)
        existing_rules: list[dict] = list((entrypoint or {}).get("rules", []))
        entrypoint_id: str | None = (entrypoint or {}).get("id")
        print(f"    Entrypoint ID : {entrypoint_id or '(not yet created)'}")
        print(f"    Existing rules: {len(existing_rules)}")

        # 4. Split existing rules into Syrabit-managed vs third-party
        syrabit_rules  = [r for r in existing_rules if r.get("description", "").startswith(_PREFIX)]
        external_rules = [r for r in existing_rules if not r.get("description", "").startswith(_PREFIX)]
        print(f"    Syrabit rules : {len(syrabit_rules)}")
        print(f"    External rules: {len(external_rules)}")

        # 5. Describe intended changes
        existing_desc = {r["description"] for r in syrabit_rules}
        canonical_desc = {r["description"] for r in canonical_rules}

        to_add    = [r for r in canonical_rules if r["description"] not in existing_desc]
        to_remove = [r for r in syrabit_rules   if r["description"] not in canonical_desc]
        unchanged = [r for r in canonical_rules  if r["description"] in  existing_desc]

        print(f"\n[4] Rule diff:")
        for r in unchanged:
            print(f"    = (unchanged) {r['description']}")
        for r in to_add:
            print(f"    + (add)       {r['description']}")
        for r in to_remove:
            print(f"    - (remove)    {r['description']}")

        if not to_add and not to_remove:
            print("\n✓ All Syrabit WAF rules are already up to date. Nothing to do.")
            return

        if args.dry_run:
            print("\n[DRY RUN] Re-run without --dry-run to apply.")
            return

        # 6. Apply: canonical Syrabit rules first, then preserve external rules
        new_rule_list = canonical_rules + external_rules

        if not entrypoint_id:
            result = _api(client, "POST", f"/zones/{zone_id}/rulesets", {
                "name": "default",
                "kind": "zone",
                "phase": "http_request_firewall_custom",
                "rules": new_rule_list,
            })
            print(f"\n✓ Created WAF custom-rules entrypoint: {result.get('id')}")
        else:
            result = _api(client, "PUT",
                          f"/zones/{zone_id}/rulesets/{entrypoint_id}",
                          {"rules": new_rule_list})
            total = len(result.get("rules", []))
            print(f"\n✓ WAF rules updated. Total active rules: {total}")

        print("\nVerification:")
        print("  https://dash.cloudflare.com → syrabit.ai → Security → WAF → Custom rules")
        print("  (Syrabit skip rules appear at the top, external rules below)")
        print("\nAll rules are live immediately — no propagation delay.")


if __name__ == "__main__":
    main()
