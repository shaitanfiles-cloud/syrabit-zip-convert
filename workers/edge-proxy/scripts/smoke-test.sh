#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# workers/edge-proxy smoke-test
#
# Exercises every binding declared in wrangler.toml against a deployed Worker
# (preview or prod) so a promote can be done by "run this script, eyeball
# output" instead of remembering N curls.
#
# Usage:
#   ./scripts/smoke-test.sh https://syrabit-edge-preview.<account>.workers.dev
#   ./scripts/smoke-test.sh https://syrabit.ai
#
# Optional env knobs:
#   SKIP_RATE_LIMIT=1   skip the rate-limit burst (saves ~10 s, but leaves
#                       RATE_LIMIT KV unverified end-to-end)
#   D1_SYNC_SECRET      if set, sent as X-Edge-Admin-Secret to unlock
#                       /api/edge/kv-usage so we can enumerate KV bindings
#                       (specifically BOT_HTML_CACHE, which has no
#                       externally-reachable read path because the
#                       bot-cache lookup requires cf.verifiedBot===true).
#                       Without it the BOT_HTML_CACHE binding check is
#                       skipped with a warning.
#   AI_FALLBACK_SECRET  if set, the AI fallback test sends this as
#                       X-CF-AI-Fallback-Secret and expects a 200 instead
#                       of the gate's 401 (proves the AI binding actually
#                       reaches Workers AI; without it we only prove the
#                       gate is wired)
#   VERBOSE=1           print full response bodies on failure
#
# Exits non-zero on the first failed check. Each check prints a single
# pass/fail line, and a summary line is printed at the end. Designed to be
# CI-droppable as-is.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <base-url>" >&2
  echo "  e.g. $0 https://syrabit-edge-preview.<account>.workers.dev" >&2
  exit 64
fi

BASE_URL="${1%/}" # strip trailing slash
PASSED=0
FAILED=0
TOTAL=0
START_TS=$(date +%s)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# ── helpers ─────────────────────────────────────────────────────────────────
fail() {
  local check="$1"; shift
  local detail="$*"
  FAILED=$((FAILED + 1))
  echo "  ✗ [$check] $detail"
  if [[ "${VERBOSE:-0}" == "1" && -f "$TMP_DIR/body" ]]; then
    echo "    --- response body ---"
    head -c 2000 "$TMP_DIR/body" | sed 's/^/    /'
    echo
    echo "    --- end body ---"
  fi
}

pass() {
  PASSED=$((PASSED + 1))
  echo "  ✓ [$1] $2"
}

# Capture status, headers, body separately so we can assert on each.
# Sets globals: HTTP_STATUS, HTTP_TIME, HEADERS_PATH, BODY_PATH.
http_get() {
  local url="$1"; shift
  local extra=("$@")
  HEADERS_PATH="$TMP_DIR/headers"
  BODY_PATH="$TMP_DIR/body"
  HTTP_STATUS=$(
    curl -sS -o "$BODY_PATH" -D "$HEADERS_PATH" \
      -w '%{http_code}' \
      --max-time 15 \
      "${extra[@]}" \
      "$url" || echo "000"
  )
  HTTP_TIME=$(awk 'END{print NR}' "$BODY_PATH" 2>/dev/null || echo 0)
}

http_post() {
  local url="$1"; shift
  HEADERS_PATH="$TMP_DIR/headers"
  BODY_PATH="$TMP_DIR/body"
  HTTP_STATUS=$(
    curl -sS -o "$BODY_PATH" -D "$HEADERS_PATH" \
      -w '%{http_code}' \
      --max-time 15 \
      -X POST \
      "$@" \
      "$url" || echo "000"
  )
}

header_value() {
  # Case-insensitive header lookup; returns empty if absent.
  awk -v IGNORECASE=1 -v h="$1" -F': *' '
    tolower($1) == tolower(h) { sub(/\r$/, "", $2); print $2; exit }
  ' "$HEADERS_PATH"
}

# ── 1) /api/health — proves worker is up + reports CONTENT_DB binding ──────
TOTAL=$((TOTAL + 1))
echo "[1/5] GET /api/health"
http_get "$BASE_URL/api/health"
if [[ "$HTTP_STATUS" != "200" ]]; then
  fail "health" "expected 200, got $HTTP_STATUS"
elif ! grep -q '"status":"ok"' "$BODY_PATH"; then
  fail "health" "body missing status:ok"
elif ! grep -q '"edge":true' "$BODY_PATH"; then
  fail "health" "body missing edge:true (request did not flow through worker)"
elif ! grep -q '"d1":true' "$BODY_PATH"; then
  fail "health" "body has d1:false — CONTENT_DB binding NOT wired in this env"
else
  src=$(header_value "X-Source")
  pass "health" "200, X-Source=${src:-(missing)}, d1=true"
fi

# ── 2) /api/edge/kv-usage — enumerates BOTH KV bindings ─────────────────────
# We can't realistically end-to-end test BOT_HTML_CACHE from a non-CF IP
# (the bot UA → KV cache path requires cf.verifiedBot===true OR a source IP
# in Google's bot ranges; spoofed bot UAs are filtered out before the KV
# lookup). The kv-monitor snapshot endpoint enumerates every KV binding the
# worker can see, so a present-and-accounted-for assertion proves the
# binding is wired without needing CF's bot infrastructure. The endpoint
# is gated by D1_SYNC_SECRET (X-Edge-Admin-Secret header).
if [[ -z "${D1_SYNC_SECRET:-}" ]]; then
  echo "[2/5] SKIPPED — D1_SYNC_SECRET unset (BOT_HTML_CACHE binding NOT verified)"
  echo "       export D1_SYNC_SECRET=… to unlock /api/edge/kv-usage"
else
  TOTAL=$((TOTAL + 1))
  echo "[2/5] GET /api/edge/kv-usage (with X-Edge-Admin-Secret)"
  http_get "$BASE_URL/api/edge/kv-usage" \
    -H "X-Edge-Admin-Secret: ${D1_SYNC_SECRET}"
  if [[ "$HTTP_STATUS" != "200" ]]; then
    fail "kv-usage" "expected 200, got $HTTP_STATUS (D1_SYNC_SECRET wrong for this env?)"
  elif ! grep -q '"RATE_LIMIT"' "$BODY_PATH"; then
    fail "kv-usage" "snapshot missing RATE_LIMIT — KV binding NOT wired"
  elif ! grep -q '"BOT_HTML_CACHE"' "$BODY_PATH"; then
    fail "kv-usage" "snapshot missing BOT_HTML_CACHE — KV binding NOT wired"
  else
    pass "kv-usage" "both RATE_LIMIT and BOT_HTML_CACHE bindings enumerated"
  fi
fi

# ── 3) /api/content/subjects — D1 read with content assertion ──────────────
# CONTENT_DB binding being wired (verified in test 1) is necessary but not
# sufficient — the D1 database also has to actually have data. This test
# proves the read path returns >=1 row, which is the contract the frontend
# depends on.
TOTAL=$((TOTAL + 1))
echo "[3/5] GET /api/content/subjects"
http_get "$BASE_URL/api/content/subjects"
if [[ "$HTTP_STATUS" != "200" ]]; then
  fail "d1-subjects" "expected 200, got $HTTP_STATUS"
else
  src=$(header_value "X-Source")
  byte_len=$(wc -c < "$BODY_PATH" | tr -d ' ')
  # Body shape: either {"subjects":[...]} or a raw [...] array. Either way
  # the substring `"id"` appears once per row, so checking for at least one
  # `"id"` is enough to prove the response is non-empty.
  if ! grep -q '"id"' "$BODY_PATH"; then
    fail "d1-subjects" "body has no rows (X-Source=${src:-(missing)}, ${byte_len} bytes)"
  elif [[ "$src" != "d1" && "$src" != "cf-cache" && "$src" != "backend" ]]; then
    fail "d1-subjects" "unexpected X-Source=${src:-(missing)} (want d1|cf-cache|backend)"
  else
    pass "d1-subjects" "200, X-Source=$src, ${byte_len} bytes, has rows"
  fi
fi

# ── 4) Rate-limit burst against /api/content/boards ────────────────────────
# RATE_LIMIT_RPM = 120 IP requests / 60 s. We send 130 sequential requests
# from one IP and expect at least one 429 with X-RateLimit-Limit=120.
#
# CRITICAL: append ?nocache=<unique> to every request. Without it, the
# Cloudflare HTTP cache (cf-cache) intercepts identical-URL requests
# BEFORE the worker runs (cacheable response sets Cache-Control: max-age=
# 3600), so the rate-limit gate is never entered and the burst returns
# 200/200/200/... forever. The worker's `nocache` query param skips both
# the CF cache lookup AND the worker's own caches.default lookup, forcing
# every request through the rate-limit check at src/index.ts:1855.
# Each request also gets a unique nocache value so even CF's URL-keyed
# cache can't collapse them.
if [[ "${SKIP_RATE_LIMIT:-0}" == "1" ]]; then
  echo "[4/5] SKIPPED (SKIP_RATE_LIMIT=1)"
else
  TOTAL=$((TOTAL + 1))
  echo "[4/5] burst 130x GET /api/content/boards?nocache=… (expect ≥1 429)"
  burst_429=0
  burst_other=0
  burst_first_429_at=0
  cb_seed="$$-$(date +%s)"
  for i in $(seq 1 130); do
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
      "$BASE_URL/api/content/boards?nocache=${cb_seed}-${i}" || echo "000")
    if [[ "$code" == "429" ]]; then
      burst_429=$((burst_429 + 1))
      [[ "$burst_first_429_at" == "0" ]] && burst_first_429_at=$i
    elif [[ "$code" != "200" && "$code" != "304" ]]; then
      burst_other=$((burst_other + 1))
    fi
  done
  if [[ "$burst_429" -eq 0 ]]; then
    fail "rate-limit" "0/130 requests returned 429 — RATE_LIMIT KV NOT counting (other=${burst_other})"
  elif [[ "$burst_first_429_at" -lt 100 || "$burst_first_429_at" -gt 130 ]]; then
    # We expect first 429 around request 121 (limit=120). Allow some slack
    # for clock skew and concurrent traffic from other clients hitting the
    # same IP-based bucket; flag if it's wildly off.
    fail "rate-limit" "first 429 at #${burst_first_429_at} (expected ~121); got ${burst_429} 429s, ${burst_other} other"
  else
    pass "rate-limit" "${burst_429}/130 returned 429, first at #${burst_first_429_at}"
  fi
fi

# ── 5) AI fallback gate — proves AI binding is wired ───────────────────────
# Without AI_FALLBACK_SECRET we expect 401 (proves the gate is wired but
# does NOT prove Workers AI itself works on this env).
# With AI_FALLBACK_SECRET set we expect 200 (proves the AI binding actually
# reaches Workers AI). Use the latter on preview after running
# `wrangler secret put CF_AI_FALLBACK_DEV_SECRET --env preview`.
TOTAL=$((TOTAL + 1))
echo "[5/5] POST /api/ai/fallback/chat (gate check)"
ai_payload='{"messages":[{"role":"user","content":"reply with the single word: ok"}],"max_tokens":8}'
if [[ -n "${AI_FALLBACK_SECRET:-}" ]]; then
  http_post "$BASE_URL/api/ai/fallback/chat" \
    -H 'Content-Type: application/json' \
    -H "X-CF-AI-Fallback-Secret: ${AI_FALLBACK_SECRET}" \
    --data "$ai_payload"
  if [[ "$HTTP_STATUS" != "200" ]]; then
    fail "ai-fallback" "expected 200 with secret, got $HTTP_STATUS"
  else
    src=$(header_value "X-Source")
    pass "ai-fallback" "200 with secret, X-Source=${src:-(missing)} (Workers AI reachable)"
  fi
else
  http_post "$BASE_URL/api/ai/fallback/chat" \
    -H 'Content-Type: application/json' \
    --data "$ai_payload"
  if [[ "$HTTP_STATUS" != "401" && "$HTTP_STATUS" != "403" ]]; then
    fail "ai-fallback" "expected 401/403 (gate), got $HTTP_STATUS — set AI_FALLBACK_SECRET to test the binding end-to-end"
  else
    pass "ai-fallback" "${HTTP_STATUS} (gate wired; set AI_FALLBACK_SECRET=… to test Workers AI end-to-end)"
  fi
fi

# ── summary ─────────────────────────────────────────────────────────────────
ELAPSED=$(( $(date +%s) - START_TS ))
echo
if [[ "$FAILED" -eq 0 ]]; then
  echo "✓ ${PASSED}/${TOTAL} passed in ${ELAPSED}s — $BASE_URL"
  exit 0
else
  echo "✗ ${FAILED}/${TOTAL} FAILED (${PASSED} passed) in ${ELAPSED}s — $BASE_URL"
  echo "  Re-run with VERBOSE=1 to see response bodies."
  exit 1
fi
