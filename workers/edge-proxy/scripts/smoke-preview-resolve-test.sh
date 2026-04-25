#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Lightweight regression test for `smoke-preview.sh`'s URL-resolution
# branches. Pure bash, zero deps — safe to run anywhere `bash` exists.
#
# Covers:
#   1. EDGE_PREVIEW_URL set                  → echoed verbatim
#   2. CF_WORKERS_SUBDOMAIN set              → builds the canonical URL
#   3. wrangler discovery, two-label form    → matches <worker>.<acct>.workers.dev
#   4. wrangler discovery, single-label form → matches <worker>.workers.dev
#   5. nothing set, no wrangler              → exits non-zero with help text
#
# Usage:  bash scripts/smoke-preview-resolve-test.sh
# Exit:   0 = all pass, non-zero = first failure (with detail to stderr).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREVIEW_SH="$SCRIPT_DIR/smoke-preview.sh"

if [[ ! -f "$PREVIEW_SH" ]]; then
  echo "FATAL: $PREVIEW_SH not found" >&2
  exit 2
fi

PASS=0
FAIL=0

# We isolate the preview script from real curl/smoke runs by stubbing
# scripts/smoke-test.sh at the END of the resolved URL line. We achieve this
# by overriding the `exec` step: each test runs the resolver function only.
# To do that we extract the resolver into a sourced shim that mimics what
# smoke-preview.sh does up to (but not including) the `exec` line.
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Copy preview script and replace the trailing `exec ...` with a plain echo
# so the resolver logic can be exercised without invoking smoke-test.sh.
sed -E 's|^exec bash .*$|echo "$BASE_URL"; exit 0|' "$PREVIEW_SH" > "$TMP_DIR/preview-shim.sh"
chmod +x "$TMP_DIR/preview-shim.sh"

assert_eq() {
  local name="$1" want="$2" got="$3"
  if [[ "$got" == "$want" ]]; then
    PASS=$((PASS + 1))
    echo "  ✓ [$name] $got"
  else
    FAIL=$((FAIL + 1))
    echo "  ✗ [$name]" >&2
    echo "      want: $want" >&2
    echo "      got:  $got" >&2
  fi
}

assert_nonzero_exit() {
  local name="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    FAIL=$((FAIL + 1))
    echo "  ✗ [$name] expected non-zero exit, got 0 with output:" >&2
    echo "      $out" >&2
  else
    PASS=$((PASS + 1))
    echo "  ✓ [$name] exited non-zero"
  fi
}

# 1) EDGE_PREVIEW_URL takes precedence
got=$(env -i HOME="$HOME" PATH="$PATH" \
  EDGE_PREVIEW_URL="https://my-override.example.workers.dev" \
  bash "$TMP_DIR/preview-shim.sh" 2>&1 | tail -n1)
assert_eq "edge-preview-url" "https://my-override.example.workers.dev" "$got"

# 2) CF_WORKERS_SUBDOMAIN builds canonical URL
got=$(env -i HOME="$HOME" PATH="$PATH" \
  CF_WORKERS_SUBDOMAIN="myacct" \
  bash "$TMP_DIR/preview-shim.sh" 2>&1 | tail -n1)
assert_eq "cf-workers-subdomain" \
  "https://syrabit-edge-preview.myacct.workers.dev" "$got"

# 3+4) wrangler discovery — stub a fake `wrangler` on PATH that prints both
# hostname forms; the resolver should pick the first match.
WRANGLER_STUB="$TMP_DIR/bin"
mkdir -p "$WRANGLER_STUB"
# Two-label form first (the common case)
cat > "$WRANGLER_STUB/wrangler" <<'EOF'
#!/usr/bin/env bash
echo "Created Worker syrabit-edge-preview"
echo "URL: https://syrabit-edge-preview.testacct.workers.dev"
echo "Version: abc123"
EOF
chmod +x "$WRANGLER_STUB/wrangler"
got=$(env -i HOME="$HOME" PATH="$WRANGLER_STUB:$PATH" \
  bash "$TMP_DIR/preview-shim.sh" 2>&1 | tail -n1)
assert_eq "wrangler-discovery-two-label" \
  "https://syrabit-edge-preview.testacct.workers.dev" "$got"

# Single-label form
cat > "$WRANGLER_STUB/wrangler" <<'EOF'
#!/usr/bin/env bash
echo "Created Worker syrabit-edge-preview"
echo "URL: https://syrabit-edge-preview.workers.dev"
EOF
chmod +x "$WRANGLER_STUB/wrangler"
got=$(env -i HOME="$HOME" PATH="$WRANGLER_STUB:$PATH" \
  bash "$TMP_DIR/preview-shim.sh" 2>&1 | tail -n1)
assert_eq "wrangler-discovery-single-label" \
  "https://syrabit-edge-preview.workers.dev" "$got"

# 5) Nothing set, no wrangler → non-zero exit + helpful error
EMPTY_PATH="$TMP_DIR/empty-bin"
mkdir -p "$EMPTY_PATH"
# Need basic shell utilities (bash, head, grep, etc.) — pull from a tiny
# allow-list so command -v wrangler genuinely fails without breaking the
# script's own dependencies. /usr/bin and /bin cover coreutils + bash.
assert_nonzero_exit "no-resolver-source" \
  env -i HOME="$HOME" PATH="$EMPTY_PATH:/usr/bin:/bin" \
  bash "$TMP_DIR/preview-shim.sh"

echo
TOTAL=$((PASS + FAIL))
if [[ "$FAIL" -eq 0 ]]; then
  echo "✓ ${PASS}/${TOTAL} passed"
  exit 0
else
  echo "✗ ${FAIL}/${TOTAL} FAILED (${PASS} passed)" >&2
  exit 1
fi
