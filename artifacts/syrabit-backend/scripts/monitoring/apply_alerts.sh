#!/usr/bin/env bash
#
# Idempotently create / update the Syrabit Cloud Monitoring alert policies.
#
# Prerequisites
#   - gcloud CLI authenticated to the Syrabit GCP project
#       gcloud auth login
#       gcloud config set project "$GCP_PROJECT_ID"
#   - SLACK_AUTH_TOKEN env var with the Slack OAuth token (xoxb-…) that
#     is permitted to post to #alerts-syrabit
#       export SLACK_AUTH_TOKEN=xoxb-…
#   - The policies file references the custom OTEL metric
#     `custom.googleapis.com/opentelemetry/syrabit.chat.total_ms`. Ensure
#     a metric exporter is running before relying on this alert (currently
#     tracking as a follow-up — the trace exporter alone does not emit
#     this metric).
#
# Usage
#   ./apply_alerts.sh                # create or update everything
#   ./apply_alerts.sh --dry-run      # print what would happen, do nothing
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

PROJECT="${GCP_PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:-}}"
if [[ -z "$PROJECT" ]]; then
  echo "ERROR: set GCP_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) before running." >&2
  exit 2
fi
if [[ -z "${SLACK_AUTH_TOKEN:-}" ]]; then
  echo "ERROR: SLACK_AUTH_TOKEN must be exported (Slack OAuth token)." >&2
  exit 2
fi

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    echo "+ $*"
    eval "$@"
  fi
}

# ---------------------------------------------------------------------------
# 1. Slack notification channel (idempotent: look up by display name first)
# ---------------------------------------------------------------------------
CHANNEL_DISPLAY="#alerts-syrabit (Slack)"
EXISTING_CHANNEL=$(gcloud alpha monitoring channels list \
  --project "$PROJECT" \
  --filter="displayName=\"$CHANNEL_DISPLAY\"" \
  --format="value(name)" 2>/dev/null | head -n1 || true)

if [[ -n "$EXISTING_CHANNEL" ]]; then
  echo "Slack channel already exists: $EXISTING_CHANNEL"
  CHANNEL_NAME="$EXISTING_CHANNEL"
else
  TMP_CHANNEL=$(mktemp)
  # Inject the auth token into the channel definition (kept out of git).
  python3 - "$SCRIPT_DIR/slack_notification_channel.json" "$TMP_CHANNEL" <<'PY'
import json, os, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    body = json.load(f)
body.setdefault("labels", {})["auth_token"] = os.environ["SLACK_AUTH_TOKEN"]
with open(dst, "w") as f:
    json.dump(body, f)
PY
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] gcloud alpha monitoring channels create --channel-content-from-file=$TMP_CHANNEL"
    CHANNEL_NAME="projects/$PROJECT/notificationChannels/DRY_RUN"
  else
    CHANNEL_NAME=$(gcloud alpha monitoring channels create \
      --project "$PROJECT" \
      --channel-content-from-file="$TMP_CHANNEL" \
      --format="value(name)")
    echo "Created Slack channel: $CHANNEL_NAME"
  fi
  rm -f "$TMP_CHANNEL"
fi

# ---------------------------------------------------------------------------
# 2. chat-p95-latency alert policy (idempotent: look up by displayName)
# ---------------------------------------------------------------------------
POLICY_FILE="$SCRIPT_DIR/chat_p95_latency_alert.json"
POLICY_DISPLAY=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['displayName'])" "$POLICY_FILE")
EXISTING_POLICY=$(gcloud alpha monitoring policies list \
  --project "$PROJECT" \
  --filter="displayName=\"$POLICY_DISPLAY\"" \
  --format="value(name)" 2>/dev/null | head -n1 || true)

# Inject the notification channel into the policy on the fly.
TMP_POLICY=$(mktemp)
python3 - "$POLICY_FILE" "$TMP_POLICY" "$CHANNEL_NAME" <<'PY'
import json, sys
src, dst, channel = sys.argv[1], sys.argv[2], sys.argv[3]
with open(src) as f:
    body = json.load(f)
body["notificationChannels"] = [channel]
with open(dst, "w") as f:
    json.dump(body, f)
PY

if [[ -n "$EXISTING_POLICY" ]]; then
  echo "Updating existing policy: $EXISTING_POLICY"
  run "gcloud alpha monitoring policies update '$EXISTING_POLICY' \
       --project '$PROJECT' \
       --policy-from-file='$TMP_POLICY'"
else
  echo "Creating new policy: $POLICY_DISPLAY"
  run "gcloud alpha monitoring policies create \
       --project '$PROJECT' \
       --policy-from-file='$TMP_POLICY'"
fi
rm -f "$TMP_POLICY"

echo
echo "Done. Verify in https://console.cloud.google.com/monitoring/alerting?project=$PROJECT"
