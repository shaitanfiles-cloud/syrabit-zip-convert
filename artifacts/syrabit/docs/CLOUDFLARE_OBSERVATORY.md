# Cloudflare Observatory — Core Web Vitals Alerts

This document explains how the Cloudflare Observatory alert thresholds are
configured for `syrabit.ai` and how the on-call engineer can reproduce or
update them.

---

## Alert thresholds

| Metric | Threshold | Recipient |
|--------|-----------|-----------|
| **LCP** (Largest Contentful Paint) | > 2.5 s (2 500 ms) | admin@syrabit.ai |
| **CLS** (Cumulative Layout Shift)  | > 0.1              | admin@syrabit.ai |
| **INP** (Interaction to Next Paint)| > 200 ms           | admin@syrabit.ai |

These match the [Core Web Vitals "needs improvement" boundaries](https://web.dev/vitals/).

---

## How alerts are created

### Automatic (preferred)

`scripts/cloudflare-phase6-apply.js` — **Step 4b** creates (or re-creates) the
notification policy via the Cloudflare Notifications API:

```
CLOUDFLARE_API_TOKEN=<tok> node artifacts/syrabit/scripts/cloudflare-phase6-apply.js
```

The script:
1. Lists existing `speed_insights` policies on the account.
2. Skips creation if a matching policy already exists.
3. Creates a new policy named **"Observatory Core Web Vitals regression — syrabit.ai"**
   with the thresholds above, scoped to the `syrabit.ai` zone, and sends email
   to `admin@syrabit.ai`.

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
5. Scope the alert to the `syrabit.ai` zone.
6. Save the policy.

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
sends an alert email to `admin@syrabit.ai`.

---

## Verifying alerts are in place

### Nightly smoke check (automated)

The nightly smoke runner (`scripts/nightly-smoke.js`) includes assertion **6d-alert**
which:

- Calls `GET /accounts/{id}/alerting/v3/policies` and finds the `speed_insights` policy.
- Asserts the policy is enabled and has at least one email recipient.
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

To verify that an alert email is actually sent when a threshold is breached:

1. Open the alert policy in the Cloudflare dashboard.
2. Temporarily lower a threshold (e.g., LCP > 0.1 s) to guarantee the next run fails.
3. Go to **Speed → Observatory** and trigger a **manual Lighthouse run** on the homepage.
4. Confirm an email arrives at `admin@syrabit.ai`.
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

## Relevant files

| File | Purpose |
|------|---------|
| `scripts/cloudflare-phase6-apply.js` | Creates Observatory schedules (Step 4) and the alert policy (Step 4b) |
| `scripts/nightly-smoke.js`           | Assertion 6d-alert verifies the policy nightly |
| `scripts/cloudflare-full-audit.js`   | Audit item 19 verifies Zaraz + Observatory weekly |
| `docs/CLOUDFLARE_OBSERVATORY.md`     | This file — on-call runbook |
