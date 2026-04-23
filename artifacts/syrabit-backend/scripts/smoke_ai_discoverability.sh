#!/usr/bin/env bash
# Pre-deploy smoke test: AI crawler / LLM discoverability.
#
# Runs against a live base URL (default: https://syrabit.ai) and asserts
# every fix from the Phase-B AI-discoverability audit is still healthy:
#
#   D1  AI bot UAs reach origin (CF "Block AI Scrapers" OFF)
#   D2  robots.txt has no "Cloudflare Managed content" block
#   D3  edge worker routes /llms.txt       → backend (not SPA shell)
#   D4  edge worker routes /.well-known/ai-plugin.json → backend
#   D5  edge worker routes /llms-full.txt  → backend (200, not 404)
#   PA  robots.txt policy: GPTBot is the ONLY blanket-blocked UA;
#       answer bots (OAI-SearchBot, PerplexityBot, ClaudeBot, Google-
#       Extended, Applebot-Extended) + training bots (CCBot, anthropic-ai,
#       Bytespider, Cohere-ai, Amazonbot, YouBot, …) are Allow: /
#
# Exit code is non-zero on any failure. Wire this into CI / a post-deploy
# gate so a silent CF-dashboard regression or a worker rollback is caught
# in minutes, not weeks.
#
# Usage:
#   ./scripts/smoke_ai_discoverability.sh                     # prod
#   BASE_URL=https://staging.syrabit.ai ./scripts/smoke_ai_discoverability.sh
#   STRICT_SIZE=1 ./scripts/smoke_ai_discoverability.sh       # also check body size
#
# Requires: curl, python3 (for JSON validation).

set -uo pipefail

BASE_URL="${BASE_URL:-https://syrabit.ai}"
STRICT_SIZE="${STRICT_SIZE:-0}"
MIN_HTML_BYTES="${MIN_HTML_BYTES:-5000}"  # SPA shell is ~30KB; CF block page is ~1KB
TIMEOUT="${TIMEOUT:-15}"

# Cache-buster so we never hit CF's edge cache for a stale verdict.
CB="$(date +%s)-$$"

PASS=0
FAIL=0
FAILURES=()

_pass() { printf "  \033[32m✓\033[0m %s\n" "$1"; PASS=$((PASS+1)); }
_fail() { printf "  \033[31m✗\033[0m %s\n    %s\n" "$1" "$2"; FAIL=$((FAIL+1)); FAILURES+=("$1"); }
_section() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }

# curl helpers — always add a cache-buster, fail-soft (we want to see every
# assertion, not stop at the first network blip).
_fetch()       { curl -fsS --max-time "$TIMEOUT" "$@" 2>/dev/null; }
_status()      { curl -s  --max-time "$TIMEOUT" -o /dev/null -w '%{http_code}' "$@" 2>/dev/null; }
_status_size() { curl -s  --max-time "$TIMEOUT" -o /dev/null -w '%{http_code}|%{size_download}' "$@" 2>/dev/null; }

# ─────────────────────────────────────────────────────────────────────────
_section "D1 — AI bot UAs must reach origin (expect HTTP 200)"
# The six canonical UAs that CF's "Block AI Scrapers" toggle historically
# 403'd. If ANY returns non-200 we've regressed.
for UA in "GPTBot/1.0" "PerplexityBot/1.0" "ClaudeBot/1.0" "CCBot/2.0" \
          "OAI-SearchBot/1.0" "ChatGPT-User/1.0"; do
  res=$(_status_size -A "$UA" "${BASE_URL}/?cb=${CB}")
  code="${res%%|*}"; size="${res##*|}"
  if [ "$code" = "200" ]; then
    if [ "$STRICT_SIZE" = "1" ] && [ "${size:-0}" -lt "$MIN_HTML_BYTES" ]; then
      _fail "$UA reached origin but body is suspiciously small" \
            "got HTTP 200 with ${size}B (< ${MIN_HTML_BYTES}B) — likely a CF block page"
    else
      _pass "$UA → HTTP 200 (${size}B)"
    fi
  else
    _fail "$UA blocked or erroring" "got HTTP ${code:-NO_RESPONSE} — check CF dashboard → Security → Bots → AI Audit"
  fi
done

# ─────────────────────────────────────────────────────────────────────────
_section "D2 — robots.txt must not contain CF managed rewrites"
body="$(_fetch "${BASE_URL}/robots.txt?cb=${CB}")"
if [ -z "$body" ]; then
  _fail "robots.txt fetch failed" "empty body — origin or edge down?"
else
  managed=$(printf "%s" "$body" | grep -c "Cloudflare Managed" || true)
  if [ "$managed" = "0" ]; then
    _pass "no 'Cloudflare Managed' markers (is_robots_txt_managed=false)"
  else
    _fail "robots.txt contains ${managed} 'Cloudflare Managed' block(s)" \
          "CF is rewriting robots.txt — re-run the PATCH: ai_bots.is_robots_txt_managed=false"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────
_section "PA — robots.txt policy (GPTBot-only block, everyone else allowed)"
# The body was already fetched above. Parse it; if empty we already failed D2.
if [ -n "${body:-}" ]; then
  # Helper: extract the lines of a single "User-agent: <ua>" block.
  _block_for() {
    printf "%s\n" "$body" | awk -v want="$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')" '
      BEGIN { in_blk = 0 }
      {
        line = $0
        low  = tolower(line)
        if (low ~ "^user-agent: " want "$") { in_blk = 1; print line; next }
        if (in_blk) {
          if (line ~ /^[[:space:]]*$/) { in_blk = 0 }
          else { print line }
        }
      }
    '
  }

  # 1. GPTBot must be Disallow: /  (and NOT also Allow: /)
  gpt_block="$(_block_for "GPTBot")"
  if [ -z "$gpt_block" ]; then
    _fail "GPTBot block missing from robots.txt" "expected 'User-agent: GPTBot\\nDisallow: /'"
  else
    has_dis=$(printf "%s" "$gpt_block" | grep -c '^Disallow: /$' || true)
    has_all=$(printf "%s" "$gpt_block" | grep -c '^Allow: /$'    || true)
    if [ "$has_dis" -ge 1 ] && [ "$has_all" = "0" ]; then
      _pass "GPTBot → Disallow: / (OpenAI training-only bot blocked)"
    else
      _fail "GPTBot policy wrong" "expected Disallow:/ (no Allow:/), got Disallow=${has_dis} Allow=${has_all}"
    fi
  fi

  # 2. Answer bots (SEO-critical) MUST have Allow: /
  for UA in OAI-SearchBot ChatGPT-User PerplexityBot ClaudeBot \
            Google-Extended Applebot-Extended Meta-ExternalAgent; do
    blk="$(_block_for "$UA")"
    if [ -z "$blk" ]; then
      _fail "$UA block missing" "answer/citation bots must be explicitly Allowed"
    elif printf "%s" "$blk" | grep -q '^Allow: /$'; then
      _pass "$UA → Allow: /"
    else
      _fail "$UA is not Allow: /" "block was:\n$blk"
    fi
  done

  # 3. Training bots (product decision: Allow for max LLM reach). GPTBot
  #    is deliberately excluded — it's the one exception.
  for UA in CCBot anthropic-ai Cohere-ai Bytespider Amazonbot YouBot \
            Diffbot PetalBot AhrefsBot SemrushBot FacebookBot; do
    blk="$(_block_for "$UA")"
    if [ -z "$blk" ]; then
      _fail "$UA block missing"  "expected Allow: / per 'maximum LLM reach' policy"
    elif printf "%s" "$blk" | grep -q '^Allow: /$'; then
      _pass "$UA → Allow: /"
    else
      _fail "$UA is not Allow: /" "expected Allow:/ — product policy is max LLM reach"
    fi
  done

  # 4. Exactly ONE blanket "Disallow: /" in the whole file (GPTBot).
  total_dis=$(printf "%s\n" "$body" | grep -c '^Disallow: /$' || true)
  if [ "$total_dis" = "1" ]; then
    _pass "exactly 1 blanket 'Disallow: /' in entire file (GPTBot only)"
  else
    _fail "found ${total_dis} blanket 'Disallow: /' lines (want 1)" \
          "something other than GPTBot is being blanket-blocked — audit server.py serve_robots_txt()"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────
_section "D3 — /llms.txt must be backend markdown, not SPA shell"
llms="$(_fetch "${BASE_URL}/llms.txt?cb=${CB}")"
first="$(printf "%s" "$llms" | head -1)"
if printf "%s" "$first" | grep -qi "^<!doctype"; then
  _fail "/llms.txt returning SPA HTML shell" \
        "edge worker is not routing — check workers/edge-proxy/src/index.ts BOT_DISCOVERY_PATHS"
elif [ "$first" = "# Syrabit.ai" ]; then
  _pass "/llms.txt → '# Syrabit.ai' markdown (backend served)"
else
  _fail "/llms.txt unexpected first line" "got: ${first:0:80}"
fi

# ─────────────────────────────────────────────────────────────────────────
_section "D4 — /.well-known/ai-plugin.json must be valid JSON"
plugin="$(_fetch "${BASE_URL}/.well-known/ai-plugin.json?cb=${CB}")"
if [ -z "$plugin" ]; then
  _fail "ai-plugin.json empty or errored" "expected JSON with schema_version + name_for_human"
else
  parsed="$(printf "%s" "$plugin" | python3 -c '
import sys, json
try:
    d = json.loads(sys.stdin.read())
    schema = d.get("schema_version")
    name   = d.get("name_for_human")
    print("schema={} name={}".format(schema, name))
except Exception as e:
    print("PARSE_ERROR: {}".format(e))
    sys.exit(1)
' 2>&1)"
  if printf "%s" "$parsed" | grep -q "^schema="; then
    _pass "/.well-known/ai-plugin.json → valid JSON (${parsed})"
  else
    _fail "/.well-known/ai-plugin.json not valid JSON" "$parsed"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────
_section "D5 — /llms-full.txt must return 200 (was 404 pre-fix)"
code=$(_status "${BASE_URL}/llms-full.txt?cb=${CB}")
if [ "$code" = "200" ]; then
  _pass "/llms-full.txt → HTTP 200"
else
  _fail "/llms-full.txt → HTTP ${code:-NO_RESPONSE}" \
        "either worker route missing or routes.bot_discovery.build_llms_full_txt failed to import"
fi

# ─────────────────────────────────────────────────────────────────────────
_section "CT — Content-Type headers must match served body"
# Cloudflare / worker / backend can all mangle Content-Type. Bots parse
# strictly: a JSON file served as text/html will be rejected silently.
_check_ct() {
  local path="$1" want="$2"
  ct=$(curl -sI --max-time "$TIMEOUT" "${BASE_URL}${path}?cb=${CB}" \
        | awk 'tolower($1) == "content-type:" { sub(/^[Cc]ontent-[Tt]ype:[ \t]*/,""); print; exit }' \
        | tr -d '\r\n')
  if printf "%s" "$ct" | grep -qi "$want"; then
    _pass "${path} Content-Type contains '${want}' (got: ${ct:-<empty>})"
  else
    _fail "${path} wrong Content-Type" "want '${want}', got '${ct:-<empty>}'"
  fi
}
_check_ct "/robots.txt"                      "text/plain"
_check_ct "/llms.txt"                        "text/plain"
_check_ct "/llms-full.txt"                   "text/plain"
_check_ct "/.well-known/ai-plugin.json"      "application/json"

# ─────────────────────────────────────────────────────────────────────────
_section "SM — Sitemap must be reachable (XML)"
# Try both /sitemap.xml (legacy) and /sitemap-index.xml (current). At
# least one MUST return 200 with an XML content-type — otherwise AI
# crawlers can't discover the 18+ per-subject sitemaps.
sitemap_ok=0
for path in "/sitemap-index.xml" "/sitemap.xml"; do
  res=$(_status_size "${BASE_URL}${path}?cb=${CB}")
  code="${res%%|*}"; size="${res##*|}"
  if [ "$code" = "200" ] && [ "${size:-0}" -gt 100 ]; then
    body=$(_fetch "${BASE_URL}${path}?cb=${CB}" | head -c 200)
    if printf "%s" "$body" | grep -qi "<?xml\|<urlset\|<sitemapindex"; then
      _pass "${path} → HTTP 200 (${size}B, XML)"
      sitemap_ok=1
    else
      _fail "${path} is 200 but not XML" "first 200 bytes: ${body}"
    fi
  else
    # Not fatal on its own — only one needs to work
    printf "  \033[90m•\033[0m %s → HTTP %s (${size}B) — trying next\n" "$path" "${code:-N/A}"
  fi
done
[ "$sitemap_ok" = "0" ] && _fail "no sitemap reachable" "tried /sitemap-index.xml and /sitemap.xml — both failed"

# ─────────────────────────────────────────────────────────────────────────
_section "SEO — Homepage must expose canonical + JSON-LD + OG tags"
# AI search (Perplexity, ChatGPT browse, Gemini) uses these for grounding
# and citation. Missing any one tanks citation probability.
# Fetch once with a bot UA so prerendered HTML is served.
home_html="$(curl -s --max-time "$TIMEOUT" -A "Googlebot/2.1" "${BASE_URL}/?cb=${CB}")"
if [ -z "$home_html" ]; then
  _fail "homepage fetch failed" "no body returned"
else
  # 1. Canonical link
  if printf "%s" "$home_html" | grep -qiE '<link[^>]+rel=["'\'']canonical["'\'']'; then
    _pass "homepage has <link rel=\"canonical\">"
  else
    _fail "homepage missing <link rel=\"canonical\">" \
          "AI search citations get ambiguous — duplicate URLs compete"
  fi
  # 2. JSON-LD structured data
  if printf "%s" "$home_html" | grep -qiE '<script[^>]+type=["'\'']application/ld\+json["'\'']'; then
    _pass "homepage has JSON-LD <script type=\"application/ld+json\">"
  else
    _fail "homepage missing JSON-LD" \
          "ChatGPT / Perplexity structured-data grounding degraded"
  fi
  # 3. Open Graph tags
  og_count=$(printf "%s" "$home_html" | grep -ciE '<meta[^>]+property=["'\'']og:' || true)
  if [ "${og_count:-0}" -ge 3 ]; then
    _pass "homepage has ${og_count} og:* meta tags (≥3)"
  else
    _fail "homepage has only ${og_count} og:* meta tags" \
          "need ≥3 (og:title, og:description, og:url) for social/AI previews"
  fi
  # 4. <title> non-empty
  if printf "%s" "$home_html" | grep -oE '<title[^>]*>[^<]+</title>' | grep -vq "<title>[ \t]*</title>"; then
    _pass "homepage <title> is non-empty"
  else
    _fail "homepage <title> empty or missing" "AI citation titles will be blank"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────
_section "UA+ — Extra AI bot UAs that became popular post-audit"
# These UAs emerged after the initial audit; verify they also reach
# origin cleanly (CF may have added them to its "Block AI" default list
# in a silent update).
for UA in "MistralAI-User/1.0" "DuckAssistBot/1.0" "Applebot/0.1" \
          "YandexBot/3.0" "Amazonbot/0.1" "meta-externalagent/1.1"; do
  code=$(_status -A "$UA" "${BASE_URL}/?cb=${CB}")
  if [ "$code" = "200" ]; then
    _pass "$UA → HTTP 200"
  else
    _fail "$UA → HTTP ${code:-NO_RESPONSE}" "CF may have added UA to default block list — check AI Audit"
  fi
done

# ─────────────────────────────────────────────────────────────────────────
_section "TLS — HTTP must redirect to HTTPS"
# AI crawlers (especially Perplexity, CCBot) do not always auto-upgrade
# http:// links. A plain-HTTP URL that returns 200 is a known discovery
# leak: crawlers index http://syrabit.ai as a separate (uncanonicalized)
# origin.
http_url="http://$(printf "%s" "$BASE_URL" | sed -E 's#^https?://##')/?cb=${CB}"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$http_url")
if [ "$code" = "301" ] || [ "$code" = "308" ]; then
  _pass "http:// → HTTP ${code} (permanent redirect to HTTPS)"
elif [ "$code" = "302" ] || [ "$code" = "307" ]; then
  _fail "http:// returns temporary redirect ${code}" \
        "crawlers cache 301/308 but may refetch 302/307 — use permanent redirect"
else
  _fail "http:// returns HTTP ${code:-NO_RESPONSE}" \
        "expected 301/308 redirect to HTTPS — duplicate-origin discovery leak"
fi

# ─────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────"
printf "  Passed: \033[32m%d\033[0m   Failed: \033[31m%d\033[0m   Target: %s\n" "$PASS" "$FAIL" "$BASE_URL"
echo "────────────────────────────────────────────────"

if [ "$FAIL" -gt 0 ]; then
  echo "FAILURES:"
  for f in "${FAILURES[@]}"; do echo "  • $f"; done
  exit 1
fi
echo "PASS — AI discoverability surface is healthy."
exit 0
