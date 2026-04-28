# Revenue Verification Runbook (Task #736 / money-truth S10)

This is the manual end-to-end verification pass that proves the full chain
**payment → admin dashboard → email receipt → analytics event → AdSense sync → admin status panel**
behaves correctly on production. Run it whenever the payment, email, analytics,
or AdSense sync code is touched.

The code paths below are all wired and confirmed in source. What this runbook
captures is the live, on-prod observation that the wiring works end-to-end.

---

## Pre-flight

- [ ] You have admin login for the production site
- [ ] You have a real card and are willing to charge a small amount
- [ ] You have access to the inbox of the email you'll buy under
- [ ] You have access to the PostHog (or GA4) project receiving prod events
- [ ] You have access to the prod env vars (to swap the AdSense token for the failure test)

Pick a **non-round amount** for the purchase so the rupee/paise formatting is
actually exercised. The recommended amount is **₹99.50** (a top-up SKU priced
in paise as `9950`). Round amounts like ₹100 will mask the
"99.50 displays as 100" bug class.

---

## Step 1 — Real test purchase

1. Sign in on prod as a normal user (not the admin account).
2. Open the upgrade / top-up flow on `ProfilePage`.
3. Pay **₹99.50** with a real card via Razorpay.
4. Note the order id shown on the success screen: `order_id = ____________________`
5. Note the wall-clock time of the success screen: `t_pay = ____________________`

**Pass criteria:** payment completes, success state renders, no JS errors in the browser console.

---

## Step 2 — Admin dashboard "Revenue (INR)"

1. Within ~30 seconds of `t_pay`, log into the admin panel on prod.
2. Open the revenue / earnings widget that shows "Revenue (INR)".
3. Confirm the displayed total has increased by **exactly ₹99.50** (not ₹99, not ₹100).

**Pass criteria:** delta = ₹99.50 ± ₹0.00. Record observed delta: `____________________`

If the delta is ₹100, the dashboard is rounding paise — file a bug, do **not** continue.
If the delta is ₹9950, the dashboard is reading paise as rupees — file a bug, do **not** continue.

---

## Step 3 — Email receipt

1. Open the inbox of the buyer email.
2. Find the receipt sent by `email_templates.send_topup_confirmation`
   (or `send_plan_activation` if you bought a plan).
3. Confirm the amount line reads **`₹99.50`** exactly.

**Pass criteria:** amount line is `₹99.50`. Record observed text: `____________________`

If you see `₹100` or `₹100.00`, the template is rounding — file a bug.
If you see `₹9950.00`, the template is being passed rupees instead of paise — file a bug.

---

## Step 4 — Analytics `purchase_completed`

1. Open PostHog (or GA4 DebugView) for the prod project.
2. Filter to events from your buyer user / session in the last few minutes.
3. Find the `purchase_completed` event for `order_id` from Step 1.
4. Inspect the `price_inr` property.

**Pass criteria:** `price_inr` is in **rupees** (e.g. `99` or `99.5`), not paise (`9950`).
Record observed value: `price_inr = ____________________`

The normalizer lives at `Analytics._normalizePriceInr` in
`artifacts/syrabit/src/utils/analytics.jsx`. If the event still shows `9900`
or `9950`, the call site is bypassing the normalizer.

---

## Step 5 — Manual AdSense sync (happy path)

1. In the admin panel, open the **AdSense** section (`AdminAds.jsx`).
2. Confirm the "AdSense Management API" panel says it's configured (no
   "AdSense API not configured" warning).
3. Click the **manual sync** button. Backend route:
   `POST /admin/ads/adsense/sync` in `routes/admin_ads.py`.
4. Wait for the request to finish.
5. Reload the earnings table.

**Pass criteria for today's row:**
- [ ] Source badge reads **`API`** (green pill `adsense_api`)
- [ ] Hovering the row shows tooltip in the form
      `USD <revenue_usd> → ₹<revenue_inr> @ <fx_rate> (<fx_source>)`
- [ ] `revenue_usd`, `fx_rate`, `fx_source` are all non-empty in the tooltip

Record values:
- `revenue_usd = ____________________`
- `revenue_inr = ____________________`
- `fx_rate     = ____________________`
- `fx_source   = ____________________`

Also confirm the admin status card shows the green "last sync ok" state with a
recent timestamp matching when you clicked the button.

---

## Step 6 — AdSense sync failure path

This proves a broken sync flips the status panel red **and does not silently
write a ₹0 row**, which was the whole point of money-truth S6.

1. On the prod environment, set the AdSense access token (or refresh token)
   to an invalid value. Easiest options:
   - Replace `ADSENSE_REFRESH_TOKEN` with `invalid_for_test_736` and redeploy, **or**
   - Revoke the AdSense OAuth grant in the Google account.
2. In the admin panel, click the manual sync button again.
3. Reload the AdSense status panel.

**Pass criteria:**
- [ ] Status card flips to the red **"✕ Last sync failed"** state
- [ ] The actual error message from Google is shown (not a generic "error")
- [ ] No new `adsense_api` row was written to today's earnings (count rows
      before vs after — should be unchanged)
- [ ] `db.ad_sync_status` doc for `_id: "adsense"` has `last_status: "error"`,
      a non-empty `last_error`, and `last_rows_synced` did not increment

**Restore step (do not skip):** put the real `ADSENSE_REFRESH_TOKEN` back (or
re-grant the OAuth) and click sync once more to confirm the green state returns.

---

## Sign-off

| Step | Pass? | Notes |
|------|-------|-------|
| 1 — Test purchase | ☐ | order_id: |
| 2 — Admin Revenue (INR) delta = ₹99.50 | ☐ | observed: |
| 3 — Receipt shows ₹99.50 | ☐ | observed: |
| 4 — `purchase_completed.price_inr` in rupees | ☐ | observed: |
| 5 — AdSense sync writes API row with fx tooltip | ☐ | |
| 6 — Failure flips red, no silent ₹0 row | ☐ | |

Verifier: ____________________   Date: ____________________

When all six rows are checked, money-truth S10 is satisfied and admin can
trust the prod revenue numbers.
