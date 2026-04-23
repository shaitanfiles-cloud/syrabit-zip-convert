/**
 * Task #767 — frontend Razorpay checkout regression coverage.
 *
 * The audit (FULL_APP_AUDIT_2026-04-23.md, finding T1) flagged that the
 * full upgrade journey — `/pricing` CTA → redirect to `/profile?upgrade=…`
 * → PaymentModal auto-open → window.Razorpay → /api/payments/verify →
 * success toast + post-payment refresh that bumps the user's credits — had
 * zero end-to-end coverage. A regression in any of those steps (button
 * wiring, query-string handler, order request shape, Razorpay options,
 * verify call signature, toast copy, post-success refetch) would only
 * surface in production.
 *
 * These tests stub:
 *   • /auth/me + /user/profile + /user/stats (so ProfilePage hydrates a
 *     free-plan user without a real backend, then upgrades to Starter
 *     credits after a successful verify);
 *   • POST /api/payments/create-order (returns a fake order envelope);
 *   • POST /api/payments/verify (returns success or 400 depending on case);
 *   • window.Razorpay (a tiny shim that records the options it was given
 *     and lets the test trigger the success/dismiss handlers manually).
 *
 * Cases:
 *   1. Happy path — start on /pricing, click upgrade-starter CTA, follow
 *      the /profile?upgrade=starter redirect, modal auto-opens, confirm,
 *      verify success → toast, modal closes, AND the credits counter on
 *      /profile reflects the upgraded Starter balance (post-success
 *      refetch ran).
 *   2. Verify failure — backend rejects the signature → error toast and
 *      modal stays open so the user can retry. Credits stay at the
 *      free-plan value.
 */
import { test, expect, type Page, type Route } from '@playwright/test';

interface PaymentMockState {
  orderRequests: Array<{ plan: string }>;
  verifyRequests: Array<{
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
    plan: string;
  }>;
  verifyShouldFail: boolean;
  // Flips true after a successful /api/payments/verify so the next
  // /user/profile + /user/stats fetch returns the Starter-plan numbers
  // — the post-success `refreshData()` that the page calls is what
  // proves the UI reconciled, not just the modal close + toast.
  upgraded: boolean;
}

const FREE_CREDITS_LIMIT = 30;
const STARTER_CREDITS_LIMIT = 1500;

async function installPaymentMocks(page: Page, init: Partial<PaymentMockState> = {}) {
  const state: PaymentMockState = {
    orderRequests: [],
    verifyRequests: [],
    verifyShouldFail: false,
    upgraded: false,
    ...init,
  };

  // Seed the in-memory token so AuthContext skips the cookie-only branch
  // and immediately hydrates with our stubbed /auth/me payload.
  await page.addInitScript(() => {
    try {
      window.sessionStorage.setItem('syrabit_token', 'e2e.user.jwt');
    } catch {}
  });

  // Replace window.Razorpay with a deterministic shim. We capture the
  // options the page passed in and expose `__rzpInvokeHandler` so the
  // test can drive the callback flow synchronously. The page's
  // `loadRazorpay()` helper short-circuits when `window.Razorpay`
  // already exists, so installing this on every page also bypasses the
  // CDN script load.
  await page.addInitScript(() => {
    (window as unknown as { __rzpOptions?: unknown }).__rzpOptions = null;
    (window as unknown as { Razorpay: unknown }).Razorpay = function (this: unknown, options: unknown) {
      (window as unknown as { __rzpOptions: unknown }).__rzpOptions = options;
      return {
        open: () => {
          // no-op — the test triggers the handler explicitly so the
          // assertions can run after the verify call resolves.
        },
        on: () => {},
      };
    };
  });

  await page.route('**/api/**', async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();

    if (method === 'OPTIONS') {
      await route.fulfill({ status: 204, body: '' });
      return;
    }

    // Auth / profile hydration ------------------------------------------------
    if (url.includes('/auth/me')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'user-e2e',
          email: 'e2e@syrabit.ai',
          name: 'E2E User',
          plan: state.upgraded ? 'starter' : 'free',
          credits_limit: state.upgraded ? STARTER_CREDITS_LIMIT : FREE_CREDITS_LIMIT,
          ads_opt_out: false,
        }),
      });
      return;
    }

    if (url.includes('/user/profile')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'user-e2e',
          email: 'e2e@syrabit.ai',
          name: 'E2E User',
          phone: '',
          plan: state.upgraded ? 'starter' : 'free',
          credits_used: 0,
          credits_limit: state.upgraded ? STARTER_CREDITS_LIMIT : FREE_CREDITS_LIMIT,
          saved_subjects: [],
        }),
      });
      return;
    }

    if (url.includes('/user/stats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          credits_used: 0,
          credits_limit: state.upgraded ? STARTER_CREDITS_LIMIT : FREE_CREDITS_LIMIT,
          plan: state.upgraded ? 'starter' : 'free',
        }),
      });
      return;
    }

    // Payment endpoints under test -------------------------------------------
    if (url.includes('/api/payments/create-order')) {
      const body = req.postDataJSON() as { plan: string } | null;
      state.orderRequests.push({ plan: body?.plan ?? '' });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          order_id: 'order_e2e_test_001',
          amount: 9900, // ₹99 in paise
          currency: 'INR',
          key_id: 'rzp_test_e2e_key',
          plan_label: 'Starter',
          plan: body?.plan ?? 'starter',
        }),
      });
      return;
    }

    if (url.includes('/api/payments/verify')) {
      const body = req.postDataJSON() as PaymentMockState['verifyRequests'][number] | null;
      if (body) state.verifyRequests.push(body);
      if (state.verifyShouldFail) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Invalid payment signature' }),
        });
      } else {
        // Flip the user to Starter for any subsequent profile/stats
        // refetch — this is exactly what the real backend does in the
        // verify route, and it's what the post-success
        // `refreshData()` call on /profile relies on.
        state.upgraded = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, plan: body?.plan ?? 'starter' }),
        });
      }
      return;
    }

    // PaymentHistory mounts on /profile and calls GET /user/payments —
    // it does `setPayments(res.data || [])` then `payments.map(...)`,
    // so the catch-all `{}` body would crash the render. Return an
    // explicit empty array.
    if (url.includes('/user/payments')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
      return;
    }

    if (url.includes('/api/payments/recover')) {
      // Recovery path — keep it returning "no record" so the
      // verify-failure test doesn't get a phantom success via the
      // fallback branch.
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: false }),
      });
      return;
    }

    // Catch-all — every other endpoint returns an empty object so the
    // page renders without ErrorBoundary blow-ups.
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });

  return state;
}

async function triggerRazorpaySuccess(page: Page) {
  await page.waitForFunction(() =>
    Boolean((window as unknown as { __rzpOptions?: { handler?: unknown } }).__rzpOptions?.handler),
  );
  await page.evaluate(() => {
    const opts = (window as unknown as {
      __rzpOptions: { handler: (r: unknown) => unknown };
    }).__rzpOptions;
    return opts.handler({
      razorpay_order_id: 'order_e2e_test_001',
      razorpay_payment_id: 'pay_e2e_test_001',
      razorpay_signature: 'sig_e2e_test_001',
    });
  });
}

test.describe('Razorpay payment flow: /pricing → /profile → verify', () => {
  test('happy path: pricing CTA → modal auto-opens → confirm → verify → toast + credits update on /profile', async ({ page }) => {
    const state = await installPaymentMocks(page);

    // 1. Start on the pricing page (the user's real entry point).
    await page.goto('/pricing');
    const pricingCta = page.getByTestId('pricing-starter-cta-button');
    await expect(pricingCta).toBeVisible({ timeout: 15_000 });

    // 2. Clicking the paid-plan CTA must redirect a logged-in user to
    //    /profile?upgrade=starter and ProfilePage must auto-open the
    //    PaymentModal (Task #767's UX promise).
    await pricingCta.click();
    await page.waitForURL(/\/profile/, { timeout: 10_000 });
    const confirmBtn = page.getByTestId('payment-confirm-button');
    await expect(confirmBtn).toBeVisible({ timeout: 10_000 });

    // Sanity: the free-plan user's credit limit is reflected on /profile
    // *before* the upgrade so the post-success assertion is meaningful.
    await expect(page.getByText(new RegExp(`${FREE_CREDITS_LIMIT}`))).toBeVisible({ timeout: 10_000 });

    // 3. Confirm → create-order → Razorpay shim records options.
    await confirmBtn.click();
    await expect.poll(() => state.orderRequests.length).toBeGreaterThan(0);
    expect(state.orderRequests[0].plan).toBe('starter');

    // 4. Drive the Razorpay success handler.
    await triggerRazorpaySuccess(page);

    // 5. Verify endpoint was called with the IDs Razorpay returned.
    await expect.poll(() => state.verifyRequests.length).toBe(1);
    expect(state.verifyRequests[0]).toMatchObject({
      razorpay_order_id: 'order_e2e_test_001',
      razorpay_payment_id: 'pay_e2e_test_001',
      razorpay_signature: 'sig_e2e_test_001',
      plan: 'starter',
    });

    // 6. Success toast + modal closes.
    await expect(page.getByText(/Starter plan activated/i)).toBeVisible({ timeout: 5_000 });
    await expect(confirmBtn).toBeHidden();

    // 7. Post-success state reconciliation: the page's `refreshData()`
    //    call must refetch /user/profile + /user/stats, which now return
    //    the upgraded Starter limit. This proves the UI actually
    //    updated, not just that the toast fired.
    await expect(page.getByText(new RegExp(`${STARTER_CREDITS_LIMIT}`))).toBeVisible({ timeout: 10_000 });
    expect(state.upgraded).toBe(true);
  });

  test('verify failure: backend rejects signature → error toast, modal stays open, credits unchanged', async ({ page }) => {
    const state = await installPaymentMocks(page, { verifyShouldFail: true });

    await page.goto('/pricing');
    const pricingCta = page.getByTestId('pricing-starter-cta-button');
    await expect(pricingCta).toBeVisible({ timeout: 15_000 });
    await pricingCta.click();

    const confirmBtn = page.getByTestId('payment-confirm-button');
    await expect(confirmBtn).toBeVisible({ timeout: 10_000 });
    await confirmBtn.click();

    await triggerRazorpaySuccess(page);

    await expect.poll(() => state.verifyRequests.length).toBe(1);

    // Error toast — copy is "Payment received but verification failed."
    // (after the recover fallback also returned no record).
    await expect(page.getByText(/verification failed/i)).toBeVisible({ timeout: 5_000 });
    // Modal must NOT auto-close on failure — user needs to retry/cancel.
    await expect(confirmBtn).toBeVisible();
    // Credits still show the free-plan value — no spurious upgrade.
    await expect(page.getByText(new RegExp(`${FREE_CREDITS_LIMIT}`))).toBeVisible();
    expect(state.upgraded).toBe(false);
  });
});
