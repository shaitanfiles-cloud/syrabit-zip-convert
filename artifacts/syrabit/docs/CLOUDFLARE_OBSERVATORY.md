# Cloudflare Observatory — Core Web Vitals Alerts

This document explains how the Cloudflare Observatory alert thresholds are
configured for `syrabit.ai` and how the on-call engineer can reproduce or
update them.

---

## Alert thresholds

| Metric | Threshold | Recipients |
|--------|-----------|------------|
| **LCP** (Largest Contentful Paint) | > 2.5 s (2 500 ms) | admin@syrabit.ai + Slack |
| **CLS** (Cumulative Layout Shift)  | > 0.1              | admin@syrabit.ai + Slack |
| **INP** (Interaction to Next Paint)| > 200 ms           | admin@syrabit.ai + Slack |

These match the [Core Web Vitals "needs improvement" boundaries](https://web.dev/vitals/).

---

## Paging channel — Slack

When a weekly Lighthouse run breaches any threshold above, Cloudflare
immediately POSTs the alert to the **on-call Slack channel** via a Cloudflare
notification webhook destination, in addition to sending email to
`admin@syrabit.ai`.  Email can sit unread overnight or go to spam; the Slack
page ensures the on-call is notified within seconds.

### Setting up the Slack webhook destination

1. Create a **Slack Incoming Webhook** for the `#oncall-alerts` channel (or
   equivalent) at <https://api.slack.com/messaging/webhooks>.
2. Register the webhook URL as a **Cloudflare notification destination**:
   - Open **dash.cloudflare.com → Notifications → Destinations → Webhooks →
     Add**.
   - Paste the Slack Incoming Webhook URL.
   - Note the destination **ID** that Cloudflare assigns (a UUID).
3. Export the destination ID as an environment variable and re-run the apply
   script to attach it to the alert policy:

   ```
   CLOUDFLARE_API_TOKEN=<tok> \
   OBSERVATORY_ALERT_SLACK_WEBHOOK_ID=<destination-uuid> \
   node artifacts/syrabit/scripts/cloudflare-phase6-apply.js
   ```

   The script adds `mechanisms.webhooks: [{ id: "<destination-uuid>" }]` to
   the `speed_insights` notification policy alongside the existing email
   mechanism.

### Manual dashboard path

If you prefer to add the webhook manually instead of re-running the script:

1. Open **dash.cloudflare.com → Notifications**.
2. Find the **Observatory Core Web Vitals regression — syrabit.ai** policy and
   click **Edit**.
3. Under **Destinations**, click **Add destination → Webhooks** and select the
   Slack destination created above.
4. Save the policy.

---

## How alerts are created

### Automatic (preferred)

`scripts/cloudflare-phase6-apply.js` — **Step 4b** creates (or re-creates) the
notification policy via the Cloudflare Notifications API:

```
CLOUDFLARE_API_TOKEN=<tok> \
OBSERVATORY_ALERT_SLACK_WEBHOOK_ID=<destination-uuid> \
node artifacts/syrabit/scripts/cloudflare-phase6-apply.js
```

The script:
1. Lists existing `speed_insights` policies on the account.
2. Skips creation if a matching policy already exists (and reports whether a
   Slack/webhook destination is attached).
3. Creates a new policy named **"Observatory Core Web Vitals regression — syrabit.ai"**
   with the thresholds above, scoped to the `syrabit.ai` zone, and delivers
   alerts to:
   - Email: `admin@syrabit.ai`
   - Slack: Cloudflare webhook destination `OBSERVATORY_ALERT_SLACK_WEBHOOK_ID`

The API token must include the **Account Notifications: Edit** scope.  If it
is missing, the script prints a manual-fallback link and continues.

### Manual (dashboard fallback)

1. Open **dash.cloudflare.com → Notifications → Add notification**.
2. Choose **Speed Insights** as the alert type.
3. Set the thresholds:
   - LCP > 2.5 s
   - CLS > 0.1
   - INP > 200 ms
4. Add `admin@syrabit.ai` as the email recipient.
5. Add the Slack webhook destination (see "Paging channel — Slack" above).
6. Scope the alert to the `syrabit.ai` zone.
7. Save the policy.

Alternatively, navigate directly via **Speed → Observatory → Scheduled reports →
Alert settings** in the Cloudflare dashboard.

---

## Scheduled Lighthouse runs

Weekly Lighthouse runs are also configured by `cloudflare-phase6-apply.js`
(Step 4).  They target:

| Page | URL |
|------|-----|
| Homepage     | `https://syrabit.ai/` |
| Chapter page | `https://syrabit.ai/ahsec/class-12/physics` |

- Region: `us-central1`
- Frequency: weekly

When a run completes and a metric breaches the threshold above, Cloudflare
fires the alert policy — email to `admin@syrabit.ai` and a Slack page to the
on-call channel simultaneously.

---

## Verifying alerts are in place

### Nightly smoke check (automated)

The nightly smoke runner (`scripts/nightly-smoke.js`) includes assertion **6d-alert**
which:

- Calls `GET /accounts/{id}/alerting/v3/policies` and finds the `speed_insights` policy.
- Asserts the policy is enabled and has at least one email recipient.
- **Asserts the policy has at least one Slack/webhook mechanism** — fails (not
  just warns) if no webhook destination is attached, because email-only means
  the on-call will not be paged immediately.
- Asserts the LCP, CLS, and INP threshold values match the table above.

If any assertion fails the smoke exits with code 1 and CI surfaces the failure.

```
CLOUDFLARE_API_TOKEN=<tok> node artifacts/syrabit/scripts/nightly-smoke.js
```

### Weekly full audit (automated)

The weekly full audit (`scripts/cloudflare-full-audit.js`) covers **audit item 19
(Zaraz GA4 + Observatory)** and checks:

- Zaraz GA4 tool configured.
- `speed_insights` alert policy present, enabled, and has an email recipient.
- Observatory schedules exist for the homepage and chapter page.

```
CLOUDFLARE_API_TOKEN=<tok> node artifacts/syrabit/scripts/cloudflare-full-audit.js
```

### Simulating a regression (manual alert test)

To verify that an alert is actually delivered (email + Slack) when a threshold is
breached:

1. Open the alert policy in the Cloudflare dashboard.
2. Temporarily lower a threshold (e.g., LCP > 0.1 s) to guarantee the next run fails.
3. Go to **Speed → Observatory** and trigger a **manual Lighthouse run** on the homepage.
4. Confirm:
   - An email arrives at `admin@syrabit.ai`.
   - A Slack message appears in the on-call channel.
5. Restore the threshold to its production value:
   - LCP > 2.5 s, CLS > 0.1, INP > 200 ms.
6. Re-run `cloudflare-phase6-apply.js` (step 4b) to programmatically restore
   the policy if you prefer not to edit via the dashboard.

---

## Required API token scopes

| Scope | Purpose |
|-------|---------|
| **Speed (Observatory): Edit** | Schedule Lighthouse runs |
| **Account Notifications: Edit** | Create / update the alert policy |
| **Speed (Observatory): Read** | Verify schedules in the smoke and audit scripts |
| **Account Notifications: Read** | Verify the alert policy in the smoke and audit scripts |

If the token lacks the `Edit` scopes, the apply script falls back to printing
manual-setup instructions and continues without failing.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token (see scopes above) |
| `CLOUDFLARE_ZONE_ID` | No | Zone ID for `syrabit.ai` (defaults to hardcoded value) |
| `CLOUDFLARE_ACCOUNT_ID` | No | Account ID (defaults to hardcoded value) |
| `OBSERVATORY_ALERT_EMAIL` | No | Alert email recipient (defaults to `admin@syrabit.ai`) |
| `OBSERVATORY_ALERT_SLACK_WEBHOOK_ID` | No | Cloudflare webhook destination ID for Slack paging |

---

## Relevant files

| File | Purpose |
|------|---------|
| `scripts/cloudflare-phase6-apply.js` | Creates Observatory schedules (Step 4) and the alert policy with Slack webhook (Step 4b) |
| `scripts/nightly-smoke.js`           | Assertion 6d-alert verifies the policy nightly, including Slack webhook presence |
| `scripts/cloudflare-full-audit.js`   | Audit item 19 verifies Zaraz + Observatory weekly |
| `docs/CLOUDFLARE_OBSERVATORY.md`     | This file — on-call runbook |
