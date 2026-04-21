# Syrabit Cloud Monitoring alerts

Version-controlled alert policies + a one-shot deploy script for Google
Cloud Monitoring. Firebase Performance alerts (LCP regression on
`/chat*` and `/`) are still configured manually in the Firebase console
because Firebase Performance does not expose a stable alert-policy API.

## Files

| File                            | What it is                                                                          |
| ------------------------------- | ----------------------------------------------------------------------------------- |
| `chat_p95_latency_alert.json`   | Cloud Monitoring alert: chat `total_ms` p95 > 8s on the `main` path, 10-min window. |
| `slack_notification_channel.json` | Slack channel template (`#alerts-syrabit`). The OAuth token is injected at apply time so it stays out of git. |
| `apply_alerts.sh`               | Idempotent `gcloud` deploy: creates the channel + policy if absent, updates them if present. |

## Apply

```bash
gcloud auth login
gcloud config set project "$GCP_PROJECT_ID"
export SLACK_AUTH_TOKEN=xoxb-…              # bot token for #alerts-syrabit
./apply_alerts.sh                            # or --dry-run to preview
```

The script is safe to re-run — it looks up existing resources by
display name and updates them in place, so CI / re-deploys do not
duplicate policies.

## Caveat — required upstream metric

The chat-latency policy targets the custom OTEL metric
`custom.googleapis.com/opentelemetry/syrabit.chat.total_ms`. Today the
backend only ships an OTEL **trace** exporter (`tracing.py`), so this
metric is not yet emitted. Until a Cloud Monitoring metric exporter is
wired in, the policy will be live but will not fire — see the linked
follow-up task.

## Firebase Performance — manual setup

Until a programmatic path lands, configure the LCP regression alert by
hand:

1. Firebase console → **Performance** → **Alerts** → **Create alert**.
2. Trace: `web_vital_LCP` (custom). Threshold: 75th percentile > 2500ms.
3. URL pattern filter: `/chat*` OR `/`.
4. Notification channel: **Slack → #alerts-syrabit**.
5. Auto-close: enabled.

This matches `docs/PERFORMANCE_MONITORING.md` §5.B.
