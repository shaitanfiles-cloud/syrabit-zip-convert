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
 * invokes Notification.requestPermission() at the right moment. If we called
 * requestPermission() ourselves from page.evaluate, a regression in the button
 * handler or hook wiring would be invisible. Both tests here click the real
 * "Push Off" button in the admin dashboard, which is the only production path
 * that calls pushNotif.subscribe() → Notification.requestPermission().
 *
 * Admin session bootstrapping
 * ----------------------------
 * seedAdminSession()      — writes admin_token to localStorage via addInitScript
 * installAdminApiMocks()  — intercepts all /api/** routes with fixture data
 *                           (from admin-mocks.ts, same as admin-smoke.spec.ts)
 * These are the canonical E2E helpers used across the admin test suite and
 * require no real backend, no real admin credentials.
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
async function getPushToggle(page: Page) {
  return page.getByTitle(PUSH_OFF_TITLE);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Push notification permission request — real UI trigger', () => {
  test(
    'denied: clicking "Push Off" calls requestPermission(), gets denied, and skips the subscription POST',
    async ({ context, page }) => {
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
      const pushBtn = await getPushToggle(page);
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
    async ({ context, page }) => {
      // Stub requestPermission → 'granted' AND stub PushManager.prototype.subscribe
      // so no real VAPID server or push endpoint is needed in CI.
      await page.addInitScript((fakeSub) => {
        (window as unknown as Record<string, unknown>).__permCalled = false;
        Notification.requestPermission = async () => {
          (window as unknown as Record<string, unknown>).__permCalled = true;
          return 'granted';
        };

        if ('PushManager' in window) {
          (PushManager.prototype as unknown as { subscribe: unknown }).subscribe =
            async () => ({
              endpoint: fakeSub.endpoint,
              expirationTime: null,
              getKey: () => null,
              toJSON: () => ({
                endpoint: fakeSub.endpoint,
                expirationTime: null,
                keys: fakeSub.keys,
              }),
              unsubscribe: async () => true,
            });
        }
      }, FAKE_SUBSCRIPTION);

      // Also stub PushManager.prototype.getSubscription to return null so the
      // mount effect in the hook reports subscribed=false immediately.
      await page.addInitScript(() => {
        if ('PushManager' in window) {
          (PushManager.prototype as unknown as { getSubscription: unknown }).getSubscription =
            async () => null;
        }
      });

      // Admin session bootstrap.
      await seedAdminSession(page);
      await installAdminApiMocks(page);

      // Intercept the VAPID key endpoint. 'AAAA' is valid minimal base64url
      // that urlBase64ToUint8Array in the hook can decode without error.
      await page.route('**/push/vapid-public-key', (route) =>
        route.fulfill({ json: { public_key: 'AAAA' } }),
      );

      // Capture the subscription POST body.
      let capturedBody: unknown = null;
      await page.route('**/push/subscribe', async (route) => {
        if (route.request().method() === 'POST') {
          const raw = route.request().postData();
          capturedBody = raw ? JSON.parse(raw) : null;
          await route.fulfill({ json: { ok: true } });
        } else {
          await route.continue();
        }
      });

      // Pre-register the service worker so navigator.serviceWorker.ready
      // resolves immediately when the hook awaits it after permission is granted.
      // We do this at the initial '/' load before navigating to /admin.
      await page.goto('/');
      await page.waitForLoadState('domcontentloaded');
      await page.evaluate(async () => {
        if (!('serviceWorker' in navigator)) return;
        const reg = await navigator.serviceWorker.register('/sw.js', {
          updateViaCache: 'none',
        });
        // The SW calls skipWaiting() in install, so it becomes active quickly.
        // Wait for it to be the active controller before we navigate away.
        await new Promise<void>((resolve) => {
          if (navigator.serviceWorker.controller) {
            resolve();
            return;
          }
          navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), {
            once: true,
          });
          // Fallback: if controllerchange never fires, resolve after 2s
          // (the SW is installed/waiting even if not controlling yet, so
          // navigator.serviceWorker.ready will still resolve on /admin).
          setTimeout(resolve, 2000);
        });
      });

      // Now navigate to /admin with the SW in place.
      await page.goto('/admin');
      await expect(page.getByTestId('admin-dashboard')).toBeVisible();

      const pushBtn = await getPushToggle(page);
      await expect(pushBtn).toBeVisible();

      // Click the real push toggle → triggers the hook's subscribe():
      //   requestPermission() → 'granted'
      //   fetch /api/push/vapid-public-key → 'AAAA'
      //   navigator.serviceWorker.ready → active SW (pre-registered above)
      //   pushManager.subscribe() → FAKE_SUBSCRIPTION (stubbed)
      //   POST /api/push/subscribe → captured below
      await pushBtn.click();

      // requestPermission must have been called by the hook.
      const permCalled = await page.evaluate(
        () => (window as unknown as Record<string, unknown>).__permCalled as boolean,
      );
      expect(permCalled).toBe(true);

      // Wait for the POST to arrive (hook is async).
      await expect
        .poll(() => capturedBody, { timeout: 8000 })
        .not.toBeNull();

      // Assert the request body has the correct subscription shape.
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
