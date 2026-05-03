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
ZONE_ID="${CLOUDFLARE_ZONE_ID:-}"

# Each spec env var is checked for PRESENCE separately from probe success.
# A legacy fallback that happens to work is still a FAIL because Task #534
# acceptance requires all four spec-named secrets to exist.
DEPLOY_TOKEN_SPEC="${CLOUDFLARE_API_TOKEN:-}"
RUNTIME_TOKEN_SPEC="${CLOUDFLARE_ANALYTICS_TOKEN:-}"
PAGES_TOKEN_SPEC="${CLOUDFLARE_PAGES_TOKEN:-}"

# Resolved tokens — used only to confirm the probe URL accepts a credential
# at all (handy when an operator is mid-rotation). Not a substitute for the
# spec presence check above.
DEPLOY_TOKEN="${DEPLOY_TOKEN_SPEC:-}"
RUNTIME_TOKEN="${RUNTIME_TOKEN_SPEC:-${CLOUDFLARE_API_TOKEN:-}}"
PAGES_TOKEN="${PAGES_TOKEN_SPEC:-${CF_PAGES_API_TOKEN:-}}"

fail=0
api="https://api.cloudflare.com/client/v4"

probe() {
  # $1=label  $2=spec_token  $3=resolved_token  $4=url  $5=spec_env_name
  local label="$1" spec="$2" token="$3" url="$4" spec_name="$5"
  if [[ -z "$spec" ]]; then
    if [[ -n "$token" ]]; then
      echo "FAIL  $label  spec env $spec_name not set (legacy fallback present — set $spec_name to comply with Task #534)"
    else
      echo "FAIL  $label  spec env $spec_name not set (no token in env at all)"
    fi
    fail=1
    return 0
  fi
  local code
  code=$(curl -sS -o /tmp/cf-verify-body -w "%{http_code}" \
    -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
    "$url" || echo "000")
  if [[ "$code" =~ ^2 ]]; then
    echo "OK    $label  HTTP $code"
  else
    echo "FAIL  $label  HTTP $code → $(head -c 240 /tmp/cf-verify-body 2>/dev/null)"
    fail=1
  fi
}

echo "── Cloudflare token verification (Task #534) ──"
[[ -z "$ACCOUNT_ID" ]] && { echo "FAIL  CLOUDFLARE_ACCOUNT_ID is not set"; exit 1; }

# 1) Deploy token (CLOUDFLARE_API_TOKEN) — used by Wrangler.
probe "CLOUDFLARE_API_TOKEN       (deploy/Wrangler)     " \
      "$DEPLOY_TOKEN_SPEC" "$DEPLOY_TOKEN" "$api/user/tokens/verify" \
      "CLOUDFLARE_API_TOKEN"

# 2) Runtime token — backend Vectorize REST. Spec name is REQUIRED.
probe "CLOUDFLARE_ANALYTICS_TOKEN (runtime/Vectorize)   " \
      "$RUNTIME_TOKEN_SPEC" "$RUNTIME_TOKEN" \
      "$api/accounts/$ACCOUNT_ID/vectorize/v2/indexes" \
      "CLOUDFLARE_ANALYTICS_TOKEN"

# 3) Pages CI token — Pages dashboard / wrangler pages. Spec name is REQUIRED.
probe "CLOUDFLARE_PAGES_TOKEN     (Pages CI)            " \
      "$PAGES_TOKEN_SPEC" "$PAGES_TOKEN" \
      "$api/accounts/$ACCOUNT_ID/pages/projects" \
      "CLOUDFLARE_PAGES_TOKEN"

# 4) Load Balancer Read scope — Task #76.
#
# The annual review (Task #66) hit a 403 on these endpoints because
# CLOUDFLARE_API_TOKEN lacked the "Load Balancer: Read" permission.
# These probes verify that the scope has been added to the token.
#
# To fix a FAIL here:
#   1. Go to https://dash.cloudflare.com/profile/api-tokens
#   2. Edit the token named for CLOUDFLARE_API_TOKEN
#   3. Under "Permissions" add:
#        Account > Load Balancer: Read
#        Zone > Load Balancer: Read
#   4. Save and re-run this script.
#
# Note: CLOUDFLARE_ZONE_ID is required for the zone-level probe.
# Set it as CLOUDFLARE_ZONE_ID=5b8c97df4431491dc7f60ea72fb61871 (syrabit.ai).
echo ""
echo "── Load Balancer scope check (Task #76) ──"
if [[ -z "$ZONE_ID" ]]; then
  echo "SKIP  LB zone probe — CLOUDFLARE_ZONE_ID is not set (set to the syrabit.ai zone ID)"
else
  probe "CLOUDFLARE_API_TOKEN       (LB read / zone)      " \
        "$DEPLOY_TOKEN_SPEC" "$DEPLOY_TOKEN" \
        "$api/zones/$ZONE_ID/load_balancers" \
        "CLOUDFLARE_API_TOKEN"
fi

probe "CLOUDFLARE_API_TOKEN       (LB read / account)   " \
      "$DEPLOY_TOKEN_SPEC" "$DEPLOY_TOKEN" \
      "$api/accounts/$ACCOUNT_ID/load_balancers/pools" \
      "CLOUDFLARE_API_TOKEN"

rm -f /tmp/cf-verify-body
echo "──"
[[ "$fail" -eq 0 ]] && echo "All probes passed." || echo "One or more probes FAILED."
exit "$fail"
