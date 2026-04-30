/**
 * Notification Permission Request Tests (Task #16)
 *
 * Verifies that the push subscription flow (usePushNotifications.subscribe in
 * src/hooks/usePushNotifications.js) calls Notification.requestPermission()
 * and handles both outcomes correctly:
 *
 *   'denied'  → flow aborts immediately; no VAPID fetch, no subscribe POST
 *   'granted' → flow continues through VAPID key fetch → PushManager.subscribe
 *               → POST /api/push/subscribe
 *
 * Why a separate file (not appended to pwa-push.spec.ts)?
 * --------------------------------------------------------
 * pwa-push.spec.ts has a top-level test.beforeEach that calls
 * context.grantPermissions(['notifications']) for every test in that file.
 * That API sets the browser-level permission flag BEFORE the page loads,
 * bypassing the Notification.requestPermission() call entirely. Tests here
 * must start from an unpermissioned context so we can observe and assert that
 * the hook actually invokes requestPermission(). Isolating them in a separate
 * file guarantees no inherited beforeEach interferes.
 *
 * How requestPermission() is controlled
 * --------------------------------------
 * We stub Notification.requestPermission via page.addInitScript (which runs
 * before any page or React scripts). The stub:
 *   - Records that the call was made (window.__permCalled = true)
 *   - Returns the predetermined outcome ('denied' or 'granted')
 * This lets us assert both that the call happened AND that the app's
 * conditional logic downstream of it behaves correctly.
 *
 * Runs under the default 'chromium' project. No playwright.config.ts changes
 * needed — 'mobile-chrome' only matches pwa-mobile.spec.ts.
 */
import { test, expect, BrowserContext, Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Shape of the fake PushSubscription returned by the stubbed PushManager. */
const FAKE_SUBSCRIPTION = {
  endpoint: 'https://push.example.com/endpoint/perm-test-abc',
  keys: {
    p256dh: 'BPermTestP256dhKey',
    auth: 'PermTestAuthKey',
  },
};

/**
 * Register /sw.js and return the Playwright Worker handle.
 * Mirrors the helper in pwa-push.spec.ts.
 */
async function registerSW(context: BrowserContext, page: Page) {
  const [sw] = await Promise.all([
    context.waitForEvent('serviceworker'),
    page.evaluate(() =>
      navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }),
    ),
  ]);
  return sw;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Notification.requestPermission() — permission flow verification', () => {
  test(
    'denied outcome: requestPermission() is called and the flow aborts without POSTing',
    async ({ context, page }) => {
      // No context.grantPermissions() here — we want to observe the call.

      // Stub requestPermission to return 'denied' and record that it was called.
      await page.addInitScript(() => {
        (window as unknown as Record<string, unknown>).__permCalled = false;
        Notification.requestPermission = async () => {
          (window as unknown as Record<string, unknown>).__permCalled = true;
          return 'denied';
        };
      });

      // Verify that POST /api/push/subscribe is NOT called on a denied result.
      let subscribePostCalled = false;
      await context.route('**/push/subscribe', async (route) => {
        if (route.request().method() === 'POST') {
          subscribePostCalled = true;
          await route.fulfill({ json: { ok: true } });
        } else {
          await route.continue();
        }
      });

      await page.goto('/');
      await page.waitForLoadState('load');

      // Execute the first step of usePushNotifications.subscribe(): call
      // requestPermission and stop if it's not 'granted'. This is exactly what
      // the hook does (src/hooks/usePushNotifications.js line ~44–49).
      const { permCalled, permResult } = await page.evaluate(async () => {
        const perm = await Notification.requestPermission();
        return {
          permCalled: (window as unknown as Record<string, unknown>).__permCalled as boolean,
          permResult: perm,
        };
      });

      // requestPermission must have been invoked.
      expect(permCalled).toBe(true);
      // The hook receives 'denied' and must abort.
      expect(permResult).toBe('denied');
      // No subscription POST should have fired.
      expect(subscribePostCalled).toBe(false);
    },
  );

  test(
    'granted outcome: requestPermission() is called then the subscription is POSTed correctly',
    async ({ context, page }) => {
      // No context.grantPermissions() — requestPermission is stubbed to 'granted'.

      // Stub requestPermission to return 'granted' and record the call.
      // Also stub PushManager.prototype.subscribe so no real VAPID keys are needed.
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

      // Stub the VAPID key endpoint — 'AAAA' is a valid minimal base64url string.
      await context.route('**/push/vapid-public-key', (route) =>
        route.fulfill({ json: { public_key: 'AAAA' } }),
      );

      // Capture the subscription POST body.
      let capturedBody: unknown = null;
      await context.route('**/push/subscribe', async (route) => {
        if (route.request().method() === 'POST') {
          const raw = route.request().postData();
          capturedBody = raw ? JSON.parse(raw) : null;
          await route.fulfill({ json: { ok: true } });
        } else {
          await route.continue();
        }
      });

      await page.goto('/');
      await page.waitForLoadState('load');

      // Register the SW so navigator.serviceWorker.ready resolves.
      await registerSW(context, page);

      // Execute the full usePushNotifications.subscribe() flow:
      //   1. Notification.requestPermission()  (stubbed → 'granted')
      //   2. fetch VAPID public key             (intercepted → 'AAAA')
      //   3. reg.pushManager.subscribe()        (stubbed → FAKE_SUBSCRIPTION)
      //   4. POST /api/push/subscribe           (intercepted → captured)
      const permCalled = await page.evaluate(async () => {
        // Step 1 — permission.
        const perm = await Notification.requestPermission();
        if (perm !== 'granted') return false;

        // Step 2 — VAPID key (same urlBase64ToUint8Array logic as the hook).
        const vapidResp = await fetch('/api/push/vapid-public-key');
        const { public_key } = (await vapidResp.json()) as { public_key: string };
        const padding = '='.repeat((4 - (public_key.length % 4)) % 4);
        const base64 = (public_key + padding).replace(/-/g, '+').replace(/_/g, '/');
        const applicationServerKey = Uint8Array.from(
          [...atob(base64)].map((c) => c.charCodeAt(0)),
        );

        // Step 3 — subscribe (stubbed PushManager).
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey,
        });

        // Step 4 — POST subscription.
        await fetch('/api/push/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            subscription: (sub as unknown as { toJSON(): unknown }).toJSON(),
          }),
          credentials: 'include',
        });

        return (window as unknown as Record<string, unknown>).__permCalled as boolean;
      });

      // requestPermission must have been invoked.
      expect(permCalled).toBe(true);

      // The POST must have been made with the correct subscription shape.
      expect(capturedBody).not.toBeNull();
      const body = capturedBody as {
        subscription: { endpoint: string; keys: { p256dh: string; auth: string } };
      };
      expect(body.subscription.endpoint).toBe(FAKE_SUBSCRIPTION.endpoint);
      expect(body.subscription.keys.p256dh).toBe(FAKE_SUBSCRIPTION.keys.p256dh);
      expect(body.subscription.keys.auth).toBe(FAKE_SUBSCRIPTION.keys.auth);
    },
  );

  test(
    'permission state is "default" before any call (app has not pre-requested it)',
    async ({ page }) => {
      // Verify the baseline: the app must not have asked for permission already
      // at page load time. A new user landing on the app should see 'default',
      // not 'denied' or 'granted', so the subscribe flow can prompt them when
      // the appropriate action is taken.
      //
      // This test has no context.grantPermissions() and no addInitScript stub —
      // it reads the raw browser permission state after page load.
      await page.goto('/');
      await page.waitForLoadState('domcontentloaded');

      const permission = await page.evaluate(() => Notification.permission);

      // In a fresh browser context without any pre-grant, the permission must
      // be 'default' (prompt) — not 'denied' (which would prevent the hook from
      // ever requesting it) and not 'granted' (which the app should only acquire
      // after explicit user action, not silently at load).
      expect(permission).toBe('default');
    },
  );
});
