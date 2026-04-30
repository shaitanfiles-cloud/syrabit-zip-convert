/**
 * Notification Permission Request Tests (Task #16)
 *
 * Verifies that the push subscription flow (usePushNotifications in
 * src/hooks/usePushNotifications.js) calls Notification.requestPermission()
 * at the right moment — when the admin clicks the "Push Off" toggle — and
 * that the app behaves correctly for both outcomes:
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
 * the button handler or hook wiring. Both tests here click the real "Push Off"
 * button in the admin dashboard, which is the only production path that calls
 * pushNotif.subscribe() → Notification.requestPermission().
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
 * navigator.serviceWorker.ready stubbing (granted path only)
 * -----------------------------------------------------------
 * The hook awaits navigator.serviceWorker.ready after permission is granted.
 * We stub the entire navigator.serviceWorker with a lightweight mock so no
 * real service worker registration is required in the test environment. This
 * makes the granted-path test fully deterministic and avoids timing issues.
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

// The push toggle button title when push is disabled (confirmed from AdminDashboard.jsx).
const PUSH_OFF_TITLE = 'Enable browser push notifications for critical alerts';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Wait for the push toggle button to appear in the admin dashboard.
 * It is conditionally rendered only when pushNotif.isSupported is true.
 */
function getPushToggle(page: Page) {
  return page.getByTitle(PUSH_OFF_TITLE);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Push notification permission request — real UI trigger', () => {
  test(
    'denied: clicking "Push Off" calls requestPermission(), gets denied, and skips the subscription POST',
    async ({ page }) => {
      // Stub Notification.requestPermission to return 'denied' and record the call.
      // This must be done before page.goto so the stub is in place when React mounts.
      await page.addInitScript(() => {
        (window as unknown as Record<string, unknown>).__permCalled = false;
        Notification.requestPermission = async () => {
          (window as unknown as Record<string, unknown>).__permCalled = true;
          return 'denied';
        };
      });

      // Standard admin session bootstrap (same pattern as admin-smoke.spec.ts).
      await seedAdminSession(page);
      await installAdminApiMocks(page);

      // Track whether /api/push/subscribe receives a POST — it must NOT.
      let subscribePostFired = false;
      await page.route('**/push/subscribe', async (route) => {
        if (route.request().method() === 'POST') {
          subscribePostFired = true;
          await route.fulfill({ json: { ok: true } });
        } else {
          await route.continue();
        }
      });

      await page.goto('/admin');

      // Wait for the admin dashboard shell to render.
      await expect(page.getByTestId('admin-dashboard')).toBeVisible();

      // The push toggle renders as "Push Off" because the notification-prefs
      // fixture has push_enabled=false (see admin-mocks.ts line ~38).
      const pushBtn = getPushToggle(page);
      await expect(pushBtn).toBeVisible();

      // Click the real button → triggers usePushNotifications.subscribe()
      // → calls the stubbed Notification.requestPermission() → 'denied'.
      await pushBtn.click();

      // requestPermission must have been called by the hook (not by test code).
      const permCalled = await page.evaluate(
        () => (window as unknown as Record<string, unknown>).__permCalled as boolean,
      );
      expect(permCalled).toBe(true);

      // With 'denied', the hook returns early — no subscription POST must fire.
      // Allow a brief moment for any spurious async tasks to settle.
      await page.waitForTimeout(300);
      expect(subscribePostFired).toBe(false);
    },
  );

  test(
    'granted: clicking "Push Off" calls requestPermission(), gets granted, and POSTs the subscription',
    async ({ page }) => {
      // ------------------------------------------------------------------
      // addInitScript runs before any page JS. We stub:
      //   1. Notification.requestPermission → 'granted'
      //   2. navigator.serviceWorker → a lightweight mock so the hook's
      //      `await navigator.serviceWorker.ready` resolves immediately.
      //      No real SW registration is needed.
      // ------------------------------------------------------------------
      await page.addInitScript((fakeSub) => {
        (window as unknown as Record<string, unknown>).__permCalled = false;

        // Stub permission to 'granted'.
        Notification.requestPermission = async () => {
          (window as unknown as Record<string, unknown>).__permCalled = true;
          return 'granted';
        };

        // Build a fake PushSubscription that toJSON() returns the expected shape.
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

        // Build a fake ServiceWorkerRegistration with a pushManager.
        const fakeReg = {
          pushManager: {
            getSubscription: async () => null,
            subscribe: async (_opts: unknown) => fakeSubObj,
          },
          active: { state: 'activated' },
        };

        // Replace navigator.serviceWorker with a mock that resolves .ready
        // synchronously. The hook checks 'serviceWorker' in navigator for
        // isSupported, so the property must exist.
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
          // If navigator.serviceWorker is non-configurable (strict browser
          // environment), fall through — the test may still pass if the
          // browser's own SW registration resolves in time.
        }
      }, FAKE_SUBSCRIPTION);

      // Admin session bootstrap.
      await seedAdminSession(page);
      await installAdminApiMocks(page);

      // Intercept the VAPID key endpoint. Registered AFTER installAdminApiMocks
      // so it takes priority (Playwright evaluates routes in LIFO order).
      await page.route('**/push/vapid-public-key', (route) =>
        route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({ public_key: 'AAAA' }),
        }),
      );

      // Capture the subscription POST — this is the final step of a successful
      // subscribe() call and is our primary assertion target.
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

      const pushBtn = getPushToggle(page);
      await expect(pushBtn).toBeVisible();

      // Click the real push toggle. The hook's subscribe() runs:
      //   requestPermission() → 'granted'                     (stubbed)
      //   GET /api/push/vapid-public-key → { public_key:'AAAA' }  (intercepted)
      //   navigator.serviceWorker.ready → fakeReg             (stubbed)
      //   pushManager.subscribe(...) → fakeSubObj             (stubbed)
      //   POST /api/push/subscribe → captured below           (intercepted)
      await pushBtn.click();

      // requestPermission must have been called by the hook, not test code.
      const permCalled = await page.evaluate(
        () => (window as unknown as Record<string, unknown>).__permCalled as boolean,
      );
      expect(permCalled).toBe(true);

      // Wait for the POST to arrive (hook is async; allow up to 8 s in slow CI).
      await expect
        .poll(() => capturedBody, { timeout: 8000 })
        .not.toBeNull();

      // Assert the request body carries the correct subscription shape.
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
    'baseline: Notification.permission is "default" at page load (app does not pre-request it)',
    async ({ page }) => {
      // No grantPermissions, no stubs — read the raw browser permission state.
      // The app must not call requestPermission() automatically at load time;
      // it should only be triggered by an explicit user action (the push toggle).
      await page.goto('/');
      await page.waitForLoadState('domcontentloaded');

      const permission = await page.evaluate(() => Notification.permission);

      // A fresh context without any action must be 'default' (prompt-able),
      // not 'denied' (which would block the hook forever) or 'granted'
      // (which the app must only acquire after the user explicitly enables push).
      expect(permission).toBe('default');
    },
  );
});
