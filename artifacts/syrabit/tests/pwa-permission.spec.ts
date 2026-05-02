/**
 * Notification Permission Request Tests (Task #16)
 *
 * Verifies that the push subscription flow (usePushNotifications in
 * src/hooks/usePushNotifications.js) calls Notification.requestPermission()
 * at the RIGHT MOMENT — only after the admin clicks the "Push Off" toggle,
 * not during page load — and that the app behaves correctly for both outcomes:
 *
 *   'denied'  → subscribe() returns false; no VAPID fetch, no subscription POST
 *   'granted' → subscribe() continues: fetches VAPID key, calls PushManager.subscribe,
 *               POSTs subscription to /api/push/subscribe
 *
 * Why tests click the real UI button (not page.evaluate shortcuts)
 * ----------------------------------------------------------------
 * The whole point of this task is to verify the app's actual call site
 * (usePushNotifications.js:44, triggered by AdminDashboard push toggle)
 * invokes Notification.requestPermission() at the right moment. Calling
 * requestPermission() ourselves from page.evaluate would hide regressions in
 * the button handler or hook wiring. Both primary tests here click the real
 * "Push Off" button in the admin dashboard, which is the only production path
 * that calls pushNotif.subscribe() → Notification.requestPermission().
 *
 * Timing-correctness checks
 * --------------------------
 * Each primary test asserts __permCalled === false BEFORE clicking the toggle,
 * then asserts __permCalled === true AFTER clicking. This ensures the
 * permission request is not fired proactively on mount/render but exclusively
 * as a response to an explicit user action.
 *
 * Admin session bootstrapping
 * ----------------------------
 * seedAdminSession()      — writes admin_token to localStorage via addInitScript
 * installAdminApiMocks()  — intercepts all /api/** routes with fixture data
 *                           (from admin-mocks.ts, same as admin-smoke.spec.ts)
 * These are the canonical E2E helpers used across the admin test suite and
 * require no real backend or real admin credentials.
 *
 * Notification.requestPermission() control
 * -----------------------------------------
 * Stubbed via page.addInitScript so the stub is in place before any page
 * scripts run. The stub:
 *   - Sets window.__permCalled = true so tests can assert the call happened
 *   - Returns the desired outcome ('denied' or 'granted')
 * context.grantPermissions() is intentionally NOT used — that API sets the
 * browser-level permission flag BEFORE the page loads, bypassing the
 * Notification.requestPermission() JS call entirely.
 *
 * Why not intercept the browser's native permission dialog?
 * ----------------------------------------------------------
 * Playwright provides page.on('dialog') for alert/confirm/prompt dialogs, but
 * the Notification permission prompt is a browser-level UI element (not a JS
 * dialog) that is never surfaced to the page script in headless CI. It is
 * impossible to intercept via Playwright's JS-dialog API. Stubbing
 * Notification.requestPermission() via addInitScript is the standard headless
 * approach and still validates the correct call site and timing.
 *
 * navigator.serviceWorker.ready stubbing (granted path only)
 * -----------------------------------------------------------
 * The hook awaits navigator.serviceWorker.ready after permission is granted.
 * We replace navigator.serviceWorker with a lightweight mock object via
 * Object.defineProperty so no real SW registration is needed in CI. This
 * makes the granted-path test fully deterministic.
 *
 * Runs under the default 'chromium' project (Desktop Chrome).
 * Source file tested: artifacts/syrabit/src/hooks/usePushNotifications.js
 */
import { test, expect, type Page } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

// ---------------------------------------------------------------------------
// Shared constants
// ---------------------------------------------------------------------------

const FAKE_SUBSCRIPTION = {
  endpoint: 'https://push.example.com/endpoint/perm-test-abc',
  keys: {
    p256dh: 'BPermTestP256dhKey-playwright',
    auth: 'PermTestAuthKeyBase64',
  },
};

// Title attribute on the push toggle when push is disabled (AdminDashboard.jsx ~line 2535).
const PUSH_OFF_TITLE = 'Enable browser push notifications for critical alerts';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getPushToggle(page: Page) {
  return page.getByTitle(PUSH_OFF_TITLE)
    .or(page.getByRole('button', { name: /push.*notification|enable.*push|browser push/i }))
    .or(page.getByTitle(/push.*notification|enable.*push|browser push/i))
    .first();
}

async function readPermCalled(page: Page): Promise<boolean> {
  return page.evaluate(
    () => (window as unknown as Record<string, unknown>).__permCalled as boolean,
  );
}

/**
 * Install a permission stub via addInitScript that:
 *  - Replaces Notification.requestPermission with a function returning `outcome`
 *  - Records the call in window.__permCalled (initially false)
 * Must be called before page.goto.
 */
async function stubPermission(page: Page, outcome: 'denied' | 'granted') {
  await page.addInitScript((o) => {
    (window as unknown as Record<string, unknown>).__permCalled = false;
    Notification.requestPermission = async () => {
      (window as unknown as Record<string, unknown>).__permCalled = true;
      return o as NotificationPermission;
    };
  }, outcome);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Push notification permission request — real UI trigger', () => {
  test(
    'denied: requestPermission() is NOT called before click and IS called after; VAPID fetch and subscription POST are both skipped',
    async ({ page }) => {
      // Stub Notification.requestPermission → 'denied' and wire __permCalled tracking.
      await stubPermission(page, 'denied');

      await seedAdminSession(page);
      await installAdminApiMocks(page);

      // Track both the VAPID key fetch and the subscription POST — neither
      // must fire when permission is denied (hook aborts before fetching the key).
      let vapidFetched = false;
      let subscribePostFired = false;

      await page.route('**/push/vapid-public-key', async (route) => {
        vapidFetched = true;
        await route.fulfill({ json: { public_key: 'AAAA' } });
      });

      await page.route('**/push/subscribe', async (route) => {
        if (route.request().method() === 'POST') {
          subscribePostFired = true;
          await route.fulfill({ json: { ok: true } });
        } else {
          await route.continue();
        }
      });

      await page.goto('/admin');
      await expect(page.getByTestId('admin-dashboard')).toBeVisible();
      await page.waitForLoadState('networkidle');

      // ------------------------------------------------------------------
      // TIMING CHECK: permission must NOT have been requested yet.
      // A failure here means the app is calling requestPermission() on load.
      // ------------------------------------------------------------------
      expect(await readPermCalled(page)).toBe(false);

      // Click the real push toggle — the only production call site for subscribe().
      const pushBtn = getPushToggle(page);
      await expect(pushBtn).toBeVisible();
      await pushBtn.click();

      // ------------------------------------------------------------------
      // TIMING CHECK: permission MUST have been requested after the click.
      // ------------------------------------------------------------------
      expect(await readPermCalled(page)).toBe(true);

      // 'denied' path: hook returns early before fetching the VAPID key.
      await page.waitForTimeout(300);
      expect(vapidFetched).toBe(false);
      expect(subscribePostFired).toBe(false);
    },
  );

  test(
    'granted: requestPermission() is NOT called before click and IS called after; subscription is POSTed',
    async ({ page }) => {
      // Stub Notification.requestPermission → 'granted' and wire __permCalled tracking.
      await stubPermission(page, 'granted');

      // Also stub navigator.serviceWorker so the hook's `await sw.ready`
      // resolves immediately without a real SW registration.
      await page.addInitScript((fakeSub) => {

        // Build a fake PushSubscription.
        const fakeSubObj = {
          endpoint: fakeSub.endpoint,
          expirationTime: null,
          getKey: (_name: string) => null,
          toJSON: () => ({
            endpoint: fakeSub.endpoint,
            expirationTime: null,
            keys: fakeSub.keys,
          }),
          unsubscribe: async () => true,
        };

        // Build a fake ServiceWorkerRegistration.
        const fakeReg = {
          pushManager: {
            getSubscription: async () => null,
            subscribe: async (_opts: unknown) => fakeSubObj,
          },
          active: { state: 'activated' },
        };

        // Replace navigator.serviceWorker with a mock that resolves .ready
        // synchronously. Also keeps 'serviceWorker' in navigator truthy so
        // usePushNotifications.isSupported remains true.
        const mockSWContainer = {
          ready: Promise.resolve(fakeReg),
          controller: { state: 'activated' },
          register: async (_url: string, _opts?: unknown) => fakeReg,
          getRegistrations: async () => [fakeReg],
          addEventListener: (_type: string, _listener: unknown) => {},
          removeEventListener: (_type: string, _listener: unknown) => {},
          dispatchEvent: (_event: unknown) => false,
        };

        try {
          Object.defineProperty(navigator, 'serviceWorker', {
            get: () => mockSWContainer,
            configurable: true,
          });
        } catch {
          // Browser may reject the override; the test still validates the call
          // path via capturedBody + permCalled checks that follow.
        }
      }, FAKE_SUBSCRIPTION);

      await seedAdminSession(page);
      await installAdminApiMocks(page);

      // Register specific routes AFTER installAdminApiMocks; Playwright
      // evaluates page routes in LIFO order, so these take priority.
      await page.route('**/push/vapid-public-key', (route) =>
        route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({ public_key: 'AAAA' }),
        }),
      );

      let capturedBody: unknown = null;
      await page.route('**/push/subscribe', async (route) => {
        if (route.request().method() === 'POST') {
          const raw = route.request().postData();
          capturedBody = raw ? JSON.parse(raw) : null;
          await route.fulfill({
            contentType: 'application/json',
            body: JSON.stringify({ ok: true }),
          });
        } else {
          await route.continue();
        }
      });

      await page.goto('/admin');
      await expect(page.getByTestId('admin-dashboard')).toBeVisible();
      await page.waitForLoadState('networkidle');

      // ------------------------------------------------------------------
      // TIMING CHECK: requestPermission must NOT have fired during load.
      // ------------------------------------------------------------------
      expect(await readPermCalled(page)).toBe(false);

      // Click the real push toggle to trigger the subscription flow.
      const pushBtn = getPushToggle(page);
      await expect(pushBtn).toBeVisible();
      await pushBtn.click();

      // ------------------------------------------------------------------
      // TIMING CHECK: requestPermission MUST have fired after the click.
      // ------------------------------------------------------------------
      expect(await readPermCalled(page)).toBe(true);

      // Wait for the subscription POST (hook is async; 8 s covers slow CI).
      await expect
        .poll(() => capturedBody, { timeout: 8000 })
        .not.toBeNull();

      // Assert the POST body carries the expected subscription shape.
      const body = capturedBody as {
        subscription: { endpoint: string; keys: { p256dh: string; auth: string } };
      };
      expect(body.subscription).toBeDefined();
      expect(body.subscription.endpoint).toBe(FAKE_SUBSCRIPTION.endpoint);
      expect(body.subscription.keys.p256dh).toBe(FAKE_SUBSCRIPTION.keys.p256dh);
      expect(body.subscription.keys.auth).toBe(FAKE_SUBSCRIPTION.keys.auth);
    },
  );

  test(
    'baseline: app never calls requestPermission() automatically on page load or during idle',
    async ({ page }) => {
      // Instrument requestPermission to detect any proactive call.
      // We stub it so that if the app does call it, we know exactly.
      await page.addInitScript(() => {
        (window as unknown as Record<string, unknown>).__permCalled = false;
        // Preserve the original implementation but wrap it to detect calls.
        const _original = Notification.requestPermission.bind(Notification);
        Notification.requestPermission = async (...args: []) => {
          (window as unknown as Record<string, unknown>).__permCalled = true;
          return _original(...args);
        };
      });

      await page.goto('/');
      await page.waitForLoadState('networkidle');

      // Give deferred effects additional time to settle.
      await page.waitForTimeout(500);

      // requestPermission must not have been called at any point during load.
      expect(await readPermCalled(page)).toBe(false);
    },
  );
});
