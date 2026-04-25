#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# workers/edge-proxy: D1 schema-drift guard (Task #880)
#
# Compares the applied-migration list of the prod and preview D1 databases
# (`syrabit-content` and `syrabit-content-preview`) and exits non-zero if
# they diverge from each other or from the local `migrations/` directory.
#
# Wired into package.json as the first half of the `deploy` and `deploy:preview`
# scripts (chained with `&&`, not as an npm pre-hook — pnpm 10 disables
# `pre*` lifecycle scripts by default, so chaining is the only way to
# guarantee the check runs). A forgotten `wrangler d1 migrations apply
# … --env preview` (or vice-versa) is therefore caught before the Worker
# code that depends on the new schema is shipped.
#
# What "drift" means here:
#   1. The set of `name` rows in `d1_migrations` on prod must equal the set
#      on preview. Anything else is divergence and blocks the deploy.
#   2. Both sets must equal the list of `*.sql` filenames in `migrations/`.
#      If either DB is behind the local dir, the operator forgot to apply
#      the migration to that environment — also blocks the deploy.
#
# Operator escape hatches (use sparingly, log a follow-up if you do):
#   SKIP_D1_DRIFT_CHECK=1   bypass entirely (e.g. urgent rollback where the
#                           drift is the *intended* remediation).
#   D1_DRIFT_PROD_ONLY=1    only verify prod is at HEAD; useful when preview
#                           is intentionally being held back / re-bootstrapped.
#
# Auth: relies on the same wrangler credentials `wrangler deploy` uses
# (CLOUDFLARE_API_TOKEN, or `wrangler login` cache). If the check cannot
# reach the API, it fails closed — which is the correct behaviour because
# `wrangler deploy` would also fail in that case.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

if [[ "${SKIP_D1_DRIFT_CHECK:-0}" == "1" ]]; then
  echo "check-d1-drift: SKIP_D1_DRIFT_CHECK=1 — skipping (operator override)" >&2
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$WORKER_DIR/migrations"

WRANGLER_BIN="wrangler"
if [[ -x "$WORKER_DIR/node_modules/.bin/wrangler" ]]; then
  WRANGLER_BIN="$WORKER_DIR/node_modules/.bin/wrangler"
fi

PROD_DB="syrabit-content"
PREVIEW_DB="syrabit-content-preview"

# Local source-of-truth: every *.sql file in migrations/, sorted.
local_migrations() {
  ( cd "$MIGRATIONS_DIR" && ls -1 *.sql 2>/dev/null | LC_ALL=C sort )
}

# Query the d1_migrations table on a remote D1 DB and emit one migration
# name per line, sorted. Uses node (always present in this repo) instead
# of jq so the script has no extra system deps.
remote_applied_migrations() {
  local db="$1"
  local raw
  local stderr_sink="/dev/null"
  if [[ "${VERBOSE:-0}" == "1" ]]; then
    # In verbose mode, surface wrangler's stderr to our own stderr so the
    # operator can see auth errors, rate-limit messages, etc.
    stderr_sink="/dev/stderr"
  fi
  if ! raw=$(
    cd "$WORKER_DIR" && \
    "$WRANGLER_BIN" d1 execute "$db" --remote --json \
      --command "SELECT name FROM d1_migrations ORDER BY name" 2>"$stderr_sink"
  ); then
    echo "check-d1-drift: ERROR — wrangler d1 execute failed for $db" >&2
    echo "  Re-run with VERBOSE=1 for the full wrangler output, or run:" >&2
    echo "    $WRANGLER_BIN d1 execute $db --remote --command 'SELECT 1'" >&2
    echo "  to confirm wrangler can reach the DB at all." >&2
    return 1
  fi
  printf '%s' "$raw" | node -e '
    let data = "";
    process.stdin.on("data", (chunk) => { data += chunk; });
    process.stdin.on("end", () => {
      try {
        const parsed = JSON.parse(data);
        const rows = (parsed[0] && parsed[0].results) || [];
        const names = rows.map((r) => r.name).filter(Boolean);
        names.sort();
        for (const n of names) console.log(n);
      } catch (e) {
        console.error("check-d1-drift: failed to parse wrangler JSON output:", e.message);
        process.exit(2);
      }
    });
  '
}

echo "check-d1-drift: comparing applied migrations on $PROD_DB vs $PREVIEW_DB"

LOCAL=$(local_migrations || true)
if [[ -z "$LOCAL" ]]; then
  echo "check-d1-drift: ERROR — no *.sql files found in $MIGRATIONS_DIR" >&2
  exit 1
fi

PROD=$(remote_applied_migrations "$PROD_DB")
echo "  $PROD_DB → $(printf '%s' "$PROD" | grep -c . || true) applied"

if [[ "${D1_DRIFT_PROD_ONLY:-0}" == "1" ]]; then
  PREVIEW="$PROD"  # collapse the comparison so only PROD-vs-LOCAL matters
  echo "  $PREVIEW_DB → SKIPPED (D1_DRIFT_PROD_ONLY=1)"
else
  PREVIEW=$(remote_applied_migrations "$PREVIEW_DB")
  echo "  $PREVIEW_DB → $(printf '%s' "$PREVIEW" | grep -c . || true) applied"
fi

fail=0

if [[ "$PROD" != "$PREVIEW" ]]; then
  echo "check-d1-drift: ✗ PROD vs PREVIEW migrations DIVERGE" >&2
  diff <(printf '%s\n' "$PROD") <(printf '%s\n' "$PREVIEW") \
    --label "$PROD_DB" --label "$PREVIEW_DB" -u >&2 || true
  fail=1
fi

if [[ "$PROD" != "$LOCAL" ]]; then
  echo "check-d1-drift: ✗ PROD is not at HEAD of migrations/" >&2
  diff <(printf '%s\n' "$LOCAL") <(printf '%s\n' "$PROD") \
    --label "migrations/ (local)" --label "$PROD_DB" -u >&2 || true
  echo "  Fix: $WRANGLER_BIN d1 migrations apply $PROD_DB --remote" >&2
  fail=1
fi

if [[ "${D1_DRIFT_PROD_ONLY:-0}" != "1" && "$PREVIEW" != "$LOCAL" ]]; then
  echo "check-d1-drift: ✗ PREVIEW is not at HEAD of migrations/" >&2
  diff <(printf '%s\n' "$LOCAL") <(printf '%s\n' "$PREVIEW") \
    --label "migrations/ (local)" --label "$PREVIEW_DB" -u >&2 || true
  echo "  Fix: $WRANGLER_BIN d1 migrations apply $PREVIEW_DB --remote" >&2
  fail=1
fi

if [[ $fail -ne 0 ]]; then
  echo "check-d1-drift: FAILED — refusing to deploy until D1 schemas are in lockstep." >&2
  echo "  Override (emergency only): SKIP_D1_DRIFT_CHECK=1 pnpm --filter syrabit-edge run deploy[:preview]" >&2
  exit 1
fi

echo "check-d1-drift: ✓ both D1 databases at HEAD ($(printf '%s' "$LOCAL" | grep -c . || true) migrations)"
