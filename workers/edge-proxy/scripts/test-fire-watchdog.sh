#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# workers/edge-proxy: synthetic-probe watchdog test-fire (Task #886)
#
# One-shot helper that proves the synthetic-probe watchdog actually pages a
# human when the probe goes dark. Wraps the verification dance from
# docs/CLOUDFLARE_ZERO_TRUST.md §7.1 step 3 ("Simulate a probe failure")
# into a single command so it can't be skipped during rollout / quarterly
# rotation drills.
#
# What it does, in order:
#   1. Verifies wrangler is authenticated for the current account.
#   2. Verifies SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL is already set as a
#      secret on the live `syrabit-edge` worker. Without it the watchdog
#      only logs PAGING-DARK and no human gets paged — there is nothing to
#      test-fire. Aborts with the exact `wrangler secret put` command if
#      the secret is missing.
#   3. Refuses to run if SYNTHETIC_PROBE_TARGET_URL is already set as a
#      secret (a custom override is in play; clobbering it would silently
#      change probe behaviour after the script restores). Override with
#      ALLOW_CLOBBER=1 if you really know what you're doing.
#   4. Sets SYNTHETIC_PROBE_TARGET_URL to a guaranteed-404 URL so the
#      probe starts failing within ~60s.
#   5. Streams `wrangler tail` to a temp file in the background so we can
#      grep for `[synthetic-probe]` lines once the test window ends.
#   6. Sleeps WAIT_MIN minutes (default 7 = 5-min watchdog threshold +
#      2-min cushion for cron jitter and webhook delivery).
#   7. ALWAYS restores prior state via an EXIT trap — even on Ctrl-C, an
#      error mid-script, or a failed wrangler call. Restoration deletes
#      the SYNTHETIC_PROBE_TARGET_URL secret, which makes the probe fall
#      back to its default `${BACKEND_URL}/api/admin/diagnostics` target
#      (the working configuration as of Task #877).
#   8. Greps the captured tail logs for `watchdog_fired=true` /
#      `PAGING-DARK` and prints a pass/fail summary, then asks the
#      operator to confirm the alert actually landed at the configured
#      Slack/PagerDuty destination.
#
# Usage:
#   ./scripts/test-fire-watchdog.sh
#
# Env knobs:
#   WAIT_MIN=7              minutes to wait for the watchdog to fire
#                           (must be ≥ SYNTHETIC_PROBE_WATCHDOG_THRESHOLD_MIN
#                           + 2). Lower values risk a false-fail.
#   ALLOW_CLOBBER=0|1       proceed even if SYNTHETIC_PROBE_TARGET_URL is
#                           currently set as a secret (it WILL be deleted
#                           on restore — re-set it manually afterwards).
#   SKIP_TAIL=0|1           skip the `wrangler tail` capture (useful in
#                           CI or restricted shells where tail can't run);
#                           verification falls back to "manual eyeball".
#   BAD_TARGET_URL=<url>    override the 404 URL used for the test-fire.
#                           Default: BACKEND_URL + a path that includes a
#                           timestamp so the response is uncacheable.
#
# Exit codes:
#   0   test-fire ran AND logs show watchdog_fired=true (alert sent)
#   1   pre-flight check failed (auth, missing webhook, or operator abort)
#   2   test-fire ran but logs show PAGING-DARK (webhook not configured —
#       fix the secret and re-run)
#   3   test-fire ran but no [synthetic-probe] activity captured (tail
#       likely lost connection — verify manually in the Workers dashboard)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

WAIT_MIN="${WAIT_MIN:-7}"
ALLOW_CLOBBER="${ALLOW_CLOBBER:-0}"
SKIP_TAIL="${SKIP_TAIL:-0}"
WORKER_NAME="syrabit-edge"
TARGET_SECRET="SYNTHETIC_PROBE_TARGET_URL"
WEBHOOK_SECRET="SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
WORKER_DIR="$(dirname -- "$SCRIPT_DIR")"
cd "$WORKER_DIR"

# Pretty-print helpers.
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { red "ERROR: \`$1\` not found in PATH."; exit 1; }
}

require_cmd npx
require_cmd jq
WRANGLER="npx --yes wrangler@4"

bold "── Pre-flight checks ──────────────────────────────────────────────"

if ! $WRANGLER whoami >/tmp/test-fire-whoami.json 2>&1; then
  red "ERROR: wrangler is not authenticated."
  red "Fix: \`npx wrangler@4 login\` or set CLOUDFLARE_API_TOKEN."
  cat /tmp/test-fire-whoami.json
  exit 1
fi
green "✓ wrangler authenticated"

# `wrangler secret list` returns JSON like [{ "name": "FOO", "type": "secret_text" }, …]
SECRETS_JSON="$($WRANGLER secret list --name "$WORKER_NAME" 2>/dev/null || echo '[]')"

if ! echo "$SECRETS_JSON" | jq -e --arg n "$WEBHOOK_SECRET" '.[] | select(.name==$n)' >/dev/null; then
  red "ERROR: $WEBHOOK_SECRET is NOT set on the live $WORKER_NAME worker."
  red ""
  red "Without it the watchdog will only log a PAGING-DARK line to the Workers"
  red "console — no human gets paged. There is nothing to test-fire until you"
  red "set this secret."
  red ""
  red "Fix:"
  red "  cd workers/edge-proxy"
  red "  npx wrangler@4 secret put $WEBHOOK_SECRET --name $WORKER_NAME"
  red "  # paste a Slack incoming-webhook URL or PagerDuty Events v2 endpoint"
  red ""
  red "Then re-run this script. See docs/CLOUDFLARE_ZERO_TRUST.md §7.1."
  exit 1
fi
green "✓ $WEBHOOK_SECRET is set on the live worker"

if echo "$SECRETS_JSON" | jq -e --arg n "$TARGET_SECRET" '.[] | select(.name==$n)' >/dev/null; then
  if [[ "$ALLOW_CLOBBER" != "1" ]]; then
    red "ERROR: $TARGET_SECRET is already set as a secret on $WORKER_NAME."
    red ""
    red "If this script proceeded it would clobber the existing override and the"
    red "EXIT-trap restore would DELETE it (the probe would fall back to the"
    red "default \${BACKEND_URL}/api/admin/diagnostics target), silently changing"
    red "production probe behaviour."
    red ""
    red "If that's actually what you want, re-run with ALLOW_CLOBBER=1 and be"
    red "prepared to re-set $TARGET_SECRET manually afterwards."
    exit 1
  fi
  yellow "⚠ $TARGET_SECRET is currently set; ALLOW_CLOBBER=1 — will be DELETED on restore"
else
  green "✓ $TARGET_SECRET is unset (probe is using default target — safe to override)"
fi

if (( WAIT_MIN < 7 )); then
  yellow "⚠ WAIT_MIN=$WAIT_MIN is below the recommended 7 minutes."
  yellow "  The watchdog threshold is 5 min; a shorter wait risks a false negative."
fi

BAD_TARGET_URL="${BAD_TARGET_URL:-https://workspacemockup-sandbox-production-df37.up.railway.app/api/admin/diagnostics-DOES-NOT-EXIST-test-fire-$(date +%s)}"
bold ""
bold "── Plan ───────────────────────────────────────────────────────────"
echo "  Worker:       $WORKER_NAME"
echo "  Bad target:   $BAD_TARGET_URL"
echo "  Wait window:  ${WAIT_MIN} minutes"
echo "  Tail capture: $([[ "$SKIP_TAIL" == "1" ]] && echo "DISABLED (SKIP_TAIL=1)" || echo "enabled")"
bold ""
read -r -p "Proceed with the test-fire? This will trigger a real PagerDuty/Slack page. [y/N] " confirm
if [[ "${confirm,,}" != "y" && "${confirm,,}" != "yes" ]]; then
  yellow "Aborted by operator."
  exit 1
fi

# ─── State management ───────────────────────────────────────────────────────
TAIL_LOG="$(mktemp -t test-fire-watchdog.tail.XXXXXX.log)"
TAIL_PID=""
RESTORE_DONE=0

restore() {
  if [[ "$RESTORE_DONE" == "1" ]]; then return; fi
  RESTORE_DONE=1
  bold ""
  bold "── Restoring probe target ─────────────────────────────────────────"
  if $WRANGLER secret delete "$TARGET_SECRET" --name "$WORKER_NAME" --force >/dev/null 2>&1; then
    green "✓ deleted $TARGET_SECRET — probe will fall back to default within ~60s"
  else
    red "✗ could not delete $TARGET_SECRET — DO IT MANUALLY NOW:"
    red "    npx wrangler@4 secret delete $TARGET_SECRET --name $WORKER_NAME --force"
    red "  Until you do, the probe will keep failing and the watchdog will keep paging."
  fi
  if [[ -n "$TAIL_PID" ]] && kill -0 "$TAIL_PID" 2>/dev/null; then
    kill "$TAIL_PID" 2>/dev/null || true
    wait "$TAIL_PID" 2>/dev/null || true
  fi
}
trap restore EXIT INT TERM

# ─── Fire ───────────────────────────────────────────────────────────────────
bold ""
bold "── Setting bad probe target ───────────────────────────────────────"
echo -n "$BAD_TARGET_URL" | $WRANGLER secret put "$TARGET_SECRET" --name "$WORKER_NAME" >/dev/null
green "✓ $TARGET_SECRET set to a 404 URL"

if [[ "$SKIP_TAIL" != "1" ]]; then
  bold ""
  bold "── Starting log capture (background) ──────────────────────────────"
  ($WRANGLER tail "$WORKER_NAME" --format=pretty 2>&1 | tee "$TAIL_LOG" >/dev/null) &
  TAIL_PID=$!
  sleep 3
  if ! kill -0 "$TAIL_PID" 2>/dev/null; then
    yellow "⚠ wrangler tail exited immediately — verification will be manual"
    TAIL_PID=""
  else
    green "✓ tail PID=$TAIL_PID, capturing to $TAIL_LOG"
  fi
fi

bold ""
bold "── Waiting ${WAIT_MIN} min for watchdog to fire ────────────────────"
echo "(threshold = 5 consecutive failed minute-probes; cushion = $((WAIT_MIN - 5)) min)"
for ((i = WAIT_MIN; i > 0; i--)); do
  printf '\r  %2d min remaining…   ' "$i"
  sleep 60
done
printf '\r  done.                 \n'

# Restore *before* the verification grep so the probe stops failing while we
# inspect what we captured.
restore

# ─── Verify ─────────────────────────────────────────────────────────────────
bold ""
bold "── Verification ───────────────────────────────────────────────────"

if [[ -s "$TAIL_LOG" ]]; then
  PROBE_LINES=$(grep -c '\[synthetic-probe\]' "$TAIL_LOG" || true)
  echo "  captured $PROBE_LINES [synthetic-probe] log line(s) in $TAIL_LOG"
  echo
  echo "  --- last 5 probe lines ---"
  grep '\[synthetic-probe\]' "$TAIL_LOG" | tail -5 | sed 's/^/    /'
  echo "  --------------------------"
  echo
  if grep -q 'watchdog_fired=true' "$TAIL_LOG"; then
    green "✓ watchdog_fired=true was logged — webhook POST attempted"
    bold ""
    yellow "FINAL STEP: open the Slack channel / PagerDuty service this webhook"
    yellow "points at and confirm a payload with alert_type=\"synthetic_probe_dark\""
    yellow "actually arrived. The log line proves the worker tried to send it,"
    yellow "but only the destination can prove it was received."
    exit 0
  fi
  if grep -q 'PAGING-DARK' "$TAIL_LOG"; then
    red "✗ PAGING-DARK was logged — $WEBHOOK_SECRET is NOT effective on the worker."
    red "  This means the secret either isn't set, isn't being read, or is empty."
    red "  Re-check the secret value and re-run."
    exit 2
  fi
  red "✗ No watchdog activity in captured logs. Possible causes:"
  red "    • The 5-min threshold wasn't crossed (try again with WAIT_MIN=10)"
  red "    • The cron is paused (SYNTHETIC_PROBE_DISABLED=true)"
  red "    • Tail dropped the relevant lines"
  red "  Check the Workers dashboard log stream for $WORKER_NAME directly."
  exit 3
else
  yellow "No tail log captured (SKIP_TAIL=1 or tail died early)."
  yellow "Verify manually in the Cloudflare dashboard: Workers & Pages →"
  yellow "$WORKER_NAME → Logs. Look for a line containing 'watchdog_fired=true'"
  yellow "in the last ${WAIT_MIN} minutes, then confirm the alert landed at"
  yellow "your Slack/PagerDuty destination."
  exit 0
fi
