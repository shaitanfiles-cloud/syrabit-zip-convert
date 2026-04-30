/**
 * Push Notification Tests (Task #9)
 *
 * Covers the two service-worker event handlers that had zero test coverage:
 *
 *   push          — triggered by the server via the Web Push API; reads the
 *                   payload and calls self.registration.showNotification().
 *   notificationclick — triggered when the user taps a notification; closes
 *                   it and navigates (or focuses) the correct client URL.
 *
 * Strategy
 * --------
 * Each test:
 *   1. Grants 'notifications' permission on the browser context so Chrome
 *      does not block showNotification() calls.
 *   2. Registers /sw.js programmatically (the app only auto-registers in
 *      production builds; see src/index.jsx). The SW calls skipWaiting()
 *      in its install handler so it activates immediately.
 *   3. Obtains the Playwright Worker handle via context.waitForEvent so we
 *      can call sw.evaluate() to run stubs directly inside the SW's scope.
 *   4. Stubs self.registration.showNotification (push tests) or
 *      self.clients.openWindow / matchAll (click tests), dispatches a
 *      synthetic event, and resolves the injected Promise with the captured
 *      arguments so Playwright can assert on them.
 *
 * notificationclick note
 * ----------------------
 * new Notification() is not constructable inside a service worker scope.
 * We use `new ExtendableEvent('notificationclick')` (which IS available in
 * SW scope) and attach a fake notification object via Object.defineProperty
 * so the handler can read event.notification.close() and
 * event.notification.data.url without throwing.
 *
 * Runs under the default 'chromium' project (Desktop Chrome). Push and
 * notification APIs are not viewport-specific, so the mobile-chrome project
 * is not needed for these tests. No changes to playwright.config.ts required.
 */
import { test, expect, BrowserContext, Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Shared setup
// ---------------------------------------------------------------------------

/** Grant notification permission before every test. */
test.beforeEach(async ({ context }) => {
  await context.grantPermissions(['notifications']);
});

/**
 * Register /sw.js from the page and return the Playwright Worker handle.
 * The SW calls self.skipWaiting() in its install handler, so it activates
 * without waiting for existing clients to be closed.
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
// push event handler
// ---------------------------------------------------------------------------

test.describe('Service Worker — push event handler', () => {
  test('JSON payload calls showNotification with the correct title, body, tag and data.url', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const shown = await sw.evaluate(async () => {
      return new Promise<{ title: string; body: string; tag: string; url: string }>(
        (resolve, reject) => {
          const orig = self.registration.showNotification.bind(self.registration);
          self.registration.showNotification = (title, options) => {
            resolve({
              title,
              body: (options && options.body) || '',
              tag: (options && options.tag) || '',
              url: ((options && options.data) ? (options.data as { url: string }).url : '') || '',
            });
            return orig(title, options);
          };

          const pushEvent = new PushEvent('push', {
            data: JSON.stringify({
              title: 'Study Reminder',
              body: 'Time to review Chapter 3',
              tag: 'study-ch3',
              url: '/library',
            }),
          });
          self.dispatchEvent(pushEvent);

          setTimeout(() => reject(new Error('showNotification was not called')), 5000);
        },
      );
    });

    expect(shown.title).toBe('Study Reminder');
    expect(shown.body).toBe('Time to review Chapter 3');
    expect(shown.tag).toBe('study-ch3');
    expect(shown.url).toBe('/library');
  });

  test('severity:critical sets requireInteraction=true and the long vibrate pattern', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const shown = await sw.evaluate(async () => {
      return new Promise<{ requireInteraction: boolean; vibrate: number[] }>(
        (resolve, reject) => {
          const orig = self.registration.showNotification.bind(self.registration);
          self.registration.showNotification = (title, options) => {
            resolve({
              requireInteraction: !!(options && options.requireInteraction),
              vibrate: (options && Array.isArray(options.vibrate) ? options.vibrate : []) as number[],
            });
            return orig(title, options);
          };

          const pushEvent = new PushEvent('push', {
            data: JSON.stringify({
              title: 'Admin Alert',
              body: 'Server error detected',
              severity: 'critical',
            }),
          });
          self.dispatchEvent(pushEvent);

          setTimeout(() => reject(new Error('showNotification was not called')), 5000);
        },
      );
    });

    expect(shown.requireInteraction).toBe(true);
    expect(shown.vibrate).toEqual([200, 100, 200, 100, 200]);
  });

  test('tag starting with "critical-alert" also sets requireInteraction=true', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const requireInteraction = await sw.evaluate(async () => {
      return new Promise<boolean>((resolve, reject) => {
        const orig = self.registration.showNotification.bind(self.registration);
        self.registration.showNotification = (title, options) => {
          resolve(!!(options && options.requireInteraction));
          return orig(title, options);
        };

        const pushEvent = new PushEvent('push', {
          data: JSON.stringify({
            title: 'Exam Alert',
            body: 'Results published',
            tag: 'critical-alert-exam-2026',
          }),
        });
        self.dispatchEvent(pushEvent);

        setTimeout(() => reject(new Error('showNotification was not called')), 5000);
      });
    });

    expect(requireInteraction).toBe(true);
  });

  test('non-critical push uses the standard short vibrate pattern and requireInteraction=false', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const shown = await sw.evaluate(async () => {
      return new Promise<{ requireInteraction: boolean; vibrate: number[] }>(
        (resolve, reject) => {
          const orig = self.registration.showNotification.bind(self.registration);
          self.registration.showNotification = (title, options) => {
            resolve({
              requireInteraction: !!(options && options.requireInteraction),
              vibrate: (options && Array.isArray(options.vibrate) ? options.vibrate : []) as number[],
            });
            return orig(title, options);
          };

          const pushEvent = new PushEvent('push', {
            data: JSON.stringify({ title: 'Tip', body: 'Read this chapter' }),
          });
          self.dispatchEvent(pushEvent);

          setTimeout(() => reject(new Error('showNotification was not called')), 5000);
        },
      );
    });

    expect(shown.requireInteraction).toBe(false);
    expect(shown.vibrate).toEqual([200, 100, 200]);
  });

  test('invalid JSON payload falls back to title "Syrabit.ai" and raw text as body', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const shown = await sw.evaluate(async () => {
      return new Promise<{ title: string; body: string }>((resolve, reject) => {
        const orig = self.registration.showNotification.bind(self.registration);
        self.registration.showNotification = (title, options) => {
          resolve({ title, body: (options && options.body) || '' });
          return orig(title, options);
        };

        // Plain string is not valid JSON → handler falls back to text()
        const pushEvent = new PushEvent('push', { data: 'not-valid-json' });
        self.dispatchEvent(pushEvent);

        setTimeout(() => reject(new Error('showNotification was not called')), 5000);
      });
    });

    expect(shown.title).toBe('Syrabit.ai');
    expect(shown.body).toBe('not-valid-json');
  });

  test('push event with no data does not call showNotification', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const called = await sw.evaluate(async () => {
      return new Promise<boolean>((resolve) => {
        let wasCalled = false;
        const orig = self.registration.showNotification.bind(self.registration);
        self.registration.showNotification = (title, options) => {
          wasCalled = true;
          return orig(title, options);
        };

        // PushEvent with no data property — handler guards with `if (!event.data) return`
        const pushEvent = new PushEvent('push');
        self.dispatchEvent(pushEvent);

        // Allow one microtask tick for the synchronous guard to run
        setTimeout(() => resolve(wasCalled), 200);
      });
    });

    expect(called).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// notificationclick handler
// ---------------------------------------------------------------------------

test.describe('Service Worker — notificationclick handler', () => {
  /**
   * Dispatch a fake 'notificationclick' event in the SW scope.
   *
   * new Notification() cannot be constructed inside a service worker context;
   * instead we create an ExtendableEvent (which IS available in SW scope and
   * is the real base class of NotificationEvent) and attach a plain-object
   * stub via Object.defineProperty. The handler only accesses:
   *   event.notification.close()
   *   event.notification.data?.url
   *   event.waitUntil()        ← available on ExtendableEvent
   * so this approach exercises the real code path without needing a real
   * Notification instance.
   */

  test('notificationclick opens the URL stored in notification.data.url', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const openedUrl = await sw.evaluate(async () => {
      return new Promise<string>((resolve, reject) => {
        // Stub openWindow to capture the URL instead of actually opening a tab
        (self.clients as unknown as Record<string, unknown>).openWindow = (url: string) => {
          resolve(url);
          return Promise.resolve(null);
        };
        // Stub matchAll to return no existing window clients → openWindow path is taken
        (self.clients as unknown as Record<string, unknown>).matchAll = () =>
          Promise.resolve([]);

        const fakeNotification = {
          close: () => {},
          title: 'Study Reminder',
          data: { url: '/library' },
        };
        const event = new ExtendableEvent('notificationclick');
        Object.defineProperty(event, 'notification', {
          value: fakeNotification,
          configurable: true,
        });
        self.dispatchEvent(event);

        setTimeout(() => reject(new Error('openWindow was not called')), 5000);
      });
    });

    expect(openedUrl).toBe('/library');
  });

  test('notificationclick falls back to "/" when notification data has no url', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const openedUrl = await sw.evaluate(async () => {
      return new Promise<string>((resolve, reject) => {
        (self.clients as unknown as Record<string, unknown>).openWindow = (url: string) => {
          resolve(url);
          return Promise.resolve(null);
        };
        (self.clients as unknown as Record<string, unknown>).matchAll = () =>
          Promise.resolve([]);

        // Notification data exists but has no url field
        const fakeNotification = { close: () => {}, title: 'Alert', data: {} };
        const event = new ExtendableEvent('notificationclick');
        Object.defineProperty(event, 'notification', {
          value: fakeNotification,
          configurable: true,
        });
        self.dispatchEvent(event);

        setTimeout(() => reject(new Error('openWindow was not called')), 5000);
      });
    });

    expect(openedUrl).toBe('/');
  });

  test('notificationclick focuses an existing window client instead of opening a new one', async ({
    context,
    page,
  }) => {
    await page.goto('/');
    await page.waitForLoadState('load');
    const sw = await registerSW(context, page);

    const result = await sw.evaluate(async () => {
      return new Promise<{ focused: boolean; opened: boolean }>((resolve) => {
        let focused = false;
        let opened = false;

        // Stub openWindow — should NOT be called when a matching client exists
        (self.clients as unknown as Record<string, unknown>).openWindow = () => {
          opened = true;
          return Promise.resolve(null);
        };

        // Stub matchAll to return one existing client whose URL includes the target
        const fakeClient = {
          url: 'http://localhost/library',
          focus: () => {
            focused = true;
            return Promise.resolve(fakeClient);
          },
        };
        (self.clients as unknown as Record<string, unknown>).matchAll = () =>
          Promise.resolve([fakeClient]);

        const fakeNotification = { close: () => {}, title: 'Tip', data: { url: '/library' } };
        const event = new ExtendableEvent('notificationclick');
        Object.defineProperty(event, 'notification', {
          value: fakeNotification,
          configurable: true,
        });
        self.dispatchEvent(event);

        // Allow async matchAll chain to settle
        setTimeout(() => resolve({ focused, opened }), 500);
      });
    });

    expect(result.focused).toBe(true);
    expect(result.opened).toBe(false);
  });
});
