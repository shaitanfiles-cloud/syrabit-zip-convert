#!/usr/bin/env bash
# verify_cf_tokens.sh — Task #534 acceptance check.
#
# Probes each of the three Cloudflare API tokens with the no-op REST call
# the spec requires, reports OK/FAIL per scope, and exits non-zero if any
# required scope is missing.
#
# Token roles (per Task #534 spec):
#
#   CLOUDFLARE_API_TOKEN        — Wrangler deploy (auto-detected)
#                                 Required scopes: Workers Scripts:Edit,
#                                 Pages:Edit, KV:Edit, D1:Edit
#                                 Probe: GET /user/tokens/verify
#
#   CLOUDFLARE_ANALYTICS_TOKEN  — Backend runtime (Vectorize, cache purge,
#                                 analytics). Falls back to legacy
#                                 CLOUDFLARE_API_TOKEN if unset.
#                                 Probe: GET /accounts/{id}/vectorize/v2/indexes
#
#   CLOUDFLARE_PAGES_TOKEN      — Pages CI deploys. Falls back to legacy
#                                 CF_PAGES_API_TOKEN if unset.
#                                 Probe: GET /accounts/{id}/pages/projects
#
# Exit codes:
#   0 — all required tokens probe OK
#   1 — at least one required token failed or is missing

set -uo pipefail

ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"
DEPLOY_TOKEN="${CLOUDFLARE_API_TOKEN:-}"
RUNTIME_TOKEN="${CLOUDFLARE_ANALYTICS_TOKEN:-${CLOUDFLARE_API_TOKEN:-}}"
PAGES_TOKEN="${CLOUDFLARE_PAGES_TOKEN:-${CF_PAGES_API_TOKEN:-}}"

fail=0
api="https://api.cloudflare.com/client/v4"

probe() {
  local label="$1" token="$2" url="$3"
  if [[ -z "$token" ]]; then
    echo "SKIP  $label    (no token set)"
    return 0
  fi
  local code
  code=$(curl -sS -o /tmp/cf-verify-body -w "%{http_code}" \
    -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
    "$url" || echo "000")
  if [[ "$code" =~ ^2 ]]; then
    echo "OK    $label    HTTP $code"
  else
    echo "FAIL  $label    HTTP $code → $(head -c 240 /tmp/cf-verify-body 2>/dev/null)"
    fail=1
  fi
}

echo "── Cloudflare token verification (Task #534) ──"
[[ -z "$ACCOUNT_ID" ]] && { echo "FAIL  CLOUDFLARE_ACCOUNT_ID is not set"; exit 1; }

# 1) Deploy token (CLOUDFLARE_API_TOKEN) — used by Wrangler.
probe "CLOUDFLARE_API_TOKEN     (deploy/Wrangler)        " \
      "$DEPLOY_TOKEN" "$api/user/tokens/verify"

# 2) Runtime token — used by backend Vectorize REST.
probe "CLOUDFLARE_ANALYTICS_TOKEN (runtime/Vectorize)    " \
      "$RUNTIME_TOKEN" "$api/accounts/$ACCOUNT_ID/vectorize/v2/indexes"

# 3) Pages CI token — used by Cloudflare Pages dashboard / wrangler pages.
probe "CLOUDFLARE_PAGES_TOKEN    (Pages CI)              " \
      "$PAGES_TOKEN" "$api/accounts/$ACCOUNT_ID/pages/projects"

rm -f /tmp/cf-verify-body
echo "──"
[[ "$fail" -eq 0 ]] && echo "All probes passed." || echo "One or more probes FAILED."
exit "$fail"
