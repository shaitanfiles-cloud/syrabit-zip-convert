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

## Post-deploy Lighthouse check (per-deploy, Task #131)

In addition to the weekly scheduled runs, a Lighthouse check runs automatically
after **every push to `master`/`main`** via the
`.github/workflows/post-deploy-lighthouse.yml` CI workflow.

### What it does

1. **Correlates to the specific commit being deployed** — the CI workflow passes
   `COMMIT_SHA` (populated from `GITHUB_SHA`) to the script.  The Pages poll
   scans recent production deployments and waits specifically for the deployment
   whose `deployment_trigger.metadata.commit_hash` matches the triggering commit.
   This prevents measuring a previous release that already reached "success"
   before the current commit's Pages build even started.
2. **Waits for that deployment to land** — polls
   `GET /accounts/{id}/pages/projects/syrabit-analytics/deployments?env=production`
   (up to 20 minutes) until the matched deployment reaches `success` status.
   If the deploy reaches `failure`, the job fails immediately (nothing to measure).
   If the poll timeout is exceeded, the job also **fails hard** — running Lighthouse
   against a stale deploy would miss the current commit's regression.  (Re-run
   manually with `skip_pages_wait = true` once the deploy is live.)
3. **Triggers Observatory speed tests** — calls
   `POST /zones/{id}/speed/tests` for the homepage and chapter page (region
   `us-central1`).
4. **Polls for results** — calls
   `GET /zones/{id}/speed/tests?url={url}` every 15 seconds (up to 10 minutes
   per page) until the Lighthouse report is available.
5. **Checks thresholds strictly** — compares LCP, CLS, and INP against the limits
   in the table above and **exits non-zero on any breach or missing metric**.
   A metric that wasn't captured by the Lighthouse run (e.g. the page failed to
   load) is treated as a failure rather than a pass, so a broken page cannot
   produce a false green.

### Blocking future deploys

The CI job does not literally block the Pages deploy that triggered it (Pages
deploys on push independently of GitHub Actions). The check gates *future*
pushes: once branch protection is configured to require the status check
below, subsequent PRs are blocked until the regression is fixed.

**Required status check context** (GitHub Actions format: `workflow name / job name`):

```
post-deploy-lighthouse / Lighthouse post-deploy check (LCP / CLS / INP)
```

#### Applying branch protection automatically (Task #141)

`.github/workflows/enforce-branch-protection.yml` applies the required status
check idempotently via the GitHub REST API.  It runs weekly (Mondays 06:00 UTC)
to re-apply the rule if it is ever accidentally removed, and can be triggered
manually at any time:

1. Open **Actions → enforce-branch-protection → Run workflow**.
2. Leave **Branch** as `master` (or enter `main`).
3. Leave **Dry run** unchecked for a real update (check it to preview the
   payload without writing).
4. Click **Run workflow**.

The underlying script (`scripts/enforce-branch-protection.js`) is idempotent —
running it when the check is already configured exits 0 with no API write.

**PAT requirement:** the workflow uses the `GITHUB_TOKEN` *secret* (a PAT
stored by a repo admin with `repo` scope) — not the automatic Actions token,
which lacks admin permission for branch protection writes.  Set the secret at
**Settings → Secrets and variables → Actions → Secrets → GITHUB_TOKEN**.

#### Applying branch protection manually (dashboard path)

If you prefer to configure branch protection via the GitHub UI rather than
running the workflow:

1. Open **Settings → Branches → Branch protection rules** and edit (or create)
   the rule for `master`.
2. Under **Require status checks to pass before merging**, enable the setting
   and search for:
   ```
   post-deploy-lighthouse / Lighthouse post-deploy check (LCP / CLS / INP)
   ```
3. Add it as a required check and save the rule.

### Disabling for emergency hotfixes

Two ways to bypass the check for an urgent fix:

**Option A — Workflow dispatch (preferred)**

1. Open the repository on GitHub.
2. Go to **Actions → post-deploy-lighthouse → Run workflow**.
3. Set **"Skip Lighthouse threshold checks"** to `true`.
4. Trigger the run — it will exit 0 without calling the Observatory API.

**Option B — Temporary branch protection relaxation**

1. Under **Settings → Branches → Branch protection rules**, temporarily remove
   the `post-deploy-lighthouse / Lighthouse post-deploy check (LCP / CLS / INP)`
   entry from the required status checks.
2. Merge the hotfix.
3. Immediately restore the branch protection rule (or re-run the
   `enforce-branch-protection` workflow — it will re-add the check in seconds).
4. Track the performance regression in the next regular CI run or a manual
   Observatory run (see "Simulating a regression" below).

In both cases, open a follow-up ticket to address the root cause before the
next planned release.

### Running locally

```sh
CLOUDFLARE_API_TOKEN=<tok> \
SKIP_PAGES_WAIT=1 \
node artifacts/syrabit/scripts/post-deploy-lighthouse.js
```

Set `SKIP_PAGES_WAIT=1` to skip the Pages deploy poll when testing against
the already-live version.

### Required API token scopes (post-deploy script)

| Scope | Purpose |
|-------|---------|
| **Speed (Observatory): Edit** | `POST /zones/{id}/speed/tests` |
| **Speed (Observatory): Read** | `GET /zones/{id}/speed/tests?url={url}` |
| **Cloudflare Pages: Read** | Poll Pages deploy status (optional — falls back gracefully) |

The `CLOUDFLARE_API_TOKEN` repo secret must include these scopes in addition to
those already required by the weekly audit and nightly smoke.

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
- **`speed_insights` policy has at least one Slack/webhook mechanism** — hard FAIL if
  missing (Task #139; matches the nightly smoke assertion).
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

#### End-to-end verification log

Each time the steps above are run to completion, record the result here so the
team knows the paging chain has been verified against the live environment.

| Date | Verified by | Outcome | Notes |
|------|-------------|---------|-------|
| 2026-05-01 | automated code review | Code-level PASS; live delivery unconfirmed | All code paths verified correct (Task #130 wires `OBSERVATORY_ALERT_SLACK_WEBHOOK_ID` → `mechanisms.webhooks`; Task #139 makes weekly audit hard-FAIL on missing webhook; Task #140 documents steps). **Live delivery test is still pending** — requires Cloudflare dashboard access + a live Slack workspace to lower a threshold, trigger a manual Lighthouse run, and confirm the POST fires to the channel. Record that result as a new row here once completed. |

---

## Required API token scopes

| Scope | Purpose |
|-------|---------|
| **Speed (Observatory): Edit** | Schedule Lighthouse runs; trigger post-deploy speed tests |
| **Speed (Observatory): Read** | Verify schedules in the smoke and audit scripts; poll post-deploy test results |
| **Account Notifications: Edit** | Create / update the alert policy |
| **Account Notifications: Read** | Verify the alert policy in the smoke and audit scripts |
| **Cloudflare Pages: Read** | Poll deploy status in the post-deploy Lighthouse script (optional — missing scope causes a graceful warning) |

If the token lacks the `Edit` scopes, the apply script falls back to printing
manual-setup instructions and continues without failing.

---

## Environment variables

### Shared

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_API_TOKEN` | Yes | Cloudflare API token (see scopes above) |
| `CLOUDFLARE_ZONE_ID` | No | Zone ID for `syrabit.ai` (defaults to hardcoded value) |
| `CLOUDFLARE_ACCOUNT_ID` | No | Account ID (defaults to hardcoded value) |

### Weekly schedule / alert policy (`cloudflare-phase6-apply.js`)

| Variable | Required | Description |
|----------|----------|-------------|
| `OBSERVATORY_ALERT_EMAIL` | No | Alert email recipient (defaults to `admin@syrabit.ai`) |
| `OBSERVATORY_ALERT_SLACK_WEBHOOK_ID` | No | Cloudflare webhook destination ID for Slack paging |

### Post-deploy Lighthouse check (`post-deploy-lighthouse.js` / CI workflow)

| Variable | Required | Description |
|----------|----------|-------------|
| `COMMIT_SHA` | No (but strongly recommended) | Git SHA of the commit being deployed. Set automatically from `GITHUB_SHA` in CI. Used to correlate the Pages poll to the exact deployment for this commit rather than any previous successful deploy. Without it the script falls back to monitoring the newest deployment (emits a warning). |
| `CLOUDFLARE_PAGES_PROJECT` | No | Pages project name (defaults to `syrabit-analytics`) |
| `SKIP_LIGHTHOUSE` | No | Set to `1` to bypass the entire script (emergency hotfix mode) |
| `SKIP_PAGES_WAIT` | No | Set to `1` to skip polling Pages for deploy completion. Use when the deploy is confirmed live and you want to run Lighthouse immediately without waiting for the Pages poll (e.g. manual re-run after a timeout) |
| `LIGHTHOUSE_REGION` | No | Cloudflare region for speed tests (default: `us-central1`) |
| `LIGHTHOUSE_POLL_TIMEOUT_MS` | No | Max ms to wait for a test result (default: `600000` = 10 min) |
| `LIGHTHOUSE_POLL_INTERVAL_MS` | No | Observatory polling interval in ms (default: `15000`) |
| `PAGES_POLL_TIMEOUT_MS` | No | Max ms to wait for Pages deploy (default: `1200000` = 20 min) |
| `PAGES_POLL_INTERVAL_MS` | No | Pages polling interval in ms (default: `20000`) |

---

## Relevant files

| File | Purpose |
|------|---------|
| `scripts/post-deploy-lighthouse.js`            | Post-deploy Lighthouse trigger + threshold gate (Task #131) |
| `.github/workflows/post-deploy-lighthouse.yml` | CI workflow that runs the post-deploy check on every push to master/main |
| `scripts/enforce-branch-protection.js`         | Idempotent script that adds the Lighthouse check to branch protection (Task #141) |
| `.github/workflows/enforce-branch-protection.yml` | workflow_dispatch + weekly schedule to apply the branch protection rule (Task #141) |
| `scripts/cloudflare-phase6-apply.js`           | Creates Observatory schedules (Step 4) and the alert policy with Slack webhook (Step 4b) |
| `scripts/nightly-smoke.js`                     | Assertion 6d-alert verifies the policy nightly, including Slack webhook presence |
| `scripts/cloudflare-full-audit.js`             | Audit item 19 verifies Zaraz + Observatory weekly |
| `docs/CLOUDFLARE_OBSERVATORY.md`               | This file — on-call runbook |
