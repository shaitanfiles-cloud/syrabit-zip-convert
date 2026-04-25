#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# workers/edge-proxy: smoke-preview wrapper
#
# Pre-wires the preview hostname so a deploy-then-smoke loop is one command
# instead of "remember the workers.dev subdomain and paste it as an arg".
#
# Hostname resolution order (first non-empty wins):
#   1. $EDGE_PREVIEW_URL                  — full URL override (caller supplies)
#   2. $CF_WORKERS_SUBDOMAIN              — just the subdomain; we build
#                                           https://syrabit-edge-preview.
#                                           ${CF_WORKERS_SUBDOMAIN}.workers.dev
#   3. `wrangler deployments list --env preview` parsed for a *.workers.dev
#      hostname (covers the steady-state case where the preview Worker has
#      already been deployed at least once).
#
# All other env knobs (D1_SYNC_SECRET, AI_FALLBACK_SECRET, SKIP_RATE_LIMIT,
# VERBOSE) are forwarded straight through to scripts/smoke-test.sh.
#
# Usage:
#   pnpm --filter syrabit-edge run smoke:preview
#   EDGE_PREVIEW_URL=https://syrabit-edge-preview.foo.workers.dev \
#     pnpm --filter syrabit-edge run smoke:preview
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

resolve_url() {
  if [[ -n "${EDGE_PREVIEW_URL:-}" ]]; then
    echo "$EDGE_PREVIEW_URL"
    return 0
  fi
  if [[ -n "${CF_WORKERS_SUBDOMAIN:-}" ]]; then
    echo "https://syrabit-edge-preview.${CF_WORKERS_SUBDOMAIN}.workers.dev"
    return 0
  fi
  # Last-ditch: ask wrangler for the most recent preview deployment URL.
  # This requires `wrangler login` (or CLOUDFLARE_API_TOKEN) on the box.
  if command -v wrangler >/dev/null 2>&1 || \
     [[ -x "$WORKER_DIR/node_modules/.bin/wrangler" ]]; then
    local wrangler_bin="wrangler"
    [[ -x "$WORKER_DIR/node_modules/.bin/wrangler" ]] && \
      wrangler_bin="$WORKER_DIR/node_modules/.bin/wrangler"
    local discovered
    # Workers hostnames can be either single-label (`<worker>.workers.dev`)
    # on accounts using the implicit subdomain or, far more commonly,
    # two-label (`<worker>.<account>.workers.dev`) once the account has
    # claimed a workers.dev subdomain. Match both shapes.
    discovered=$(
      cd "$WORKER_DIR" && "$wrangler_bin" deployments list --env preview 2>/dev/null \
        | grep -oE 'https://[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)?\.workers\.dev' \
        | head -n1 || true
    )
    if [[ -n "$discovered" ]]; then
      echo "$discovered"
      return 0
    fi
  fi
  return 1
}

if ! BASE_URL=$(resolve_url); then
  cat >&2 <<EOF
smoke:preview — could not resolve preview hostname.

Set one of:
  EDGE_PREVIEW_URL=https://syrabit-edge-preview.<account>.workers.dev
  CF_WORKERS_SUBDOMAIN=<account>          # builds the URL for you

…or run \`pnpm --filter syrabit-edge run deploy:preview\` once so wrangler
has a deployment to discover, then re-run.
EOF
  exit 64
fi

echo "smoke:preview → $BASE_URL"
exec bash "$SCRIPT_DIR/smoke-test.sh" "$BASE_URL"
