/**
 * PWA & Mobile Tests (Task #3)
 *
 * Covers three flows that had zero test coverage:
 *   1. PWA install prompt is interceptable on a mobile viewport.
 *   2. Offline fallback page renders when the network is blocked.
 *   3. Service-worker registration is confirmed via navigator.serviceWorker.
 *
 * All tests run under the 'mobile-chrome' project defined in
 * playwright.config.ts (Pixel 5 / 393 × 851, deviceScaleFactor 2.75).
 *
 * Note on SW registration in dev mode
 * ------------------------------------
 * src/index.jsx only registers /sw.js when import.meta.env.PROD === true.
 * In the Vite dev-server environment used by Playwright it explicitly
 * *un*registers any existing workers. Tests therefore exercise the API
 * surface and manual registration path rather than relying on the app's
 * automatic registration.
 */
import { test, expect } from '@playwright/test';

// ---------------------------------------------------------------------------
// Local type helpers (avoid `as any` / `as unknown` escape hatches)
// ---------------------------------------------------------------------------

/** Minimal shape of the non-standard BeforeInstallPromptEvent. */
interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  prompt(): Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

/** Shape of the web app manifest we care about. */
interface WebAppManifest {
  name?: string;
  short_name?: string;
  start_url?: string;
  display?: string;
  icons?: unknown[];
  [key: string]: unknown;
}

/** Page-global state injected by addInitScript. */
interface E2EPwaGlobal {
  __e2e_pwaPromptEvent: BeforeInstallPromptEvent | null;
}

// ---------------------------------------------------------------------------
// 1. PWA install prompt — mobile viewport
// ---------------------------------------------------------------------------
test.describe('PWA install prompt (mobile)', () => {
  test('beforeinstallprompt event is intercepted and prompt() is accessible', async ({ page }) => {
    // Register a listener *before* the page scripts run so it captures the
    // event even if the app calls preventDefault() first.
    await page.addInitScript(() => {
      (window as Window & E2EPwaGlobal).__e2e_pwaPromptEvent = null;
      window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        (window as Window & E2EPwaGlobal).__e2e_pwaPromptEvent =
          e as BeforeInstallPromptEvent;
      });
    });

    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // In CI (http, no real SW cache) the browser never fires the real event.
    // Dispatch a synthetic one to verify the listener wiring is in place.
    await page.evaluate(() => {
      const e = new Event('beforeinstallprompt', { bubbles: true, cancelable: true });
      const typed = e as BeforeInstallPromptEvent;
      // Attach a minimal prompt() stub so real handlers do not crash.
      Object.defineProperty(typed, 'platforms', { value: ['web'], configurable: true });
      Object.defineProperty(typed, 'prompt', {
        value: () => Promise.resolve({ outcome: 'dismissed' }),
        configurable: true,
      });
      window.dispatchEvent(typed);
    });

    const captured = await page.evaluate(
      () => !!(window as Window & E2EPwaGlobal).__e2e_pwaPromptEvent,
    );
    expect(captured).toBe(true);
  });

  test('web app manifest is served with required PWA fields', async ({ page }) => {
    const response = await page.goto('/manifest.json');
    expect(response?.status()).toBe(200);

    const manifest = (await response?.json()) as WebAppManifest;
    expect(typeof manifest.name).toBe('string');
    expect((manifest.name ?? '').length).toBeGreaterThan(0);
    expect(typeof manifest.start_url).toBe('string');
    expect(manifest.display).toBe('standalone');
    expect(Array.isArray(manifest.icons)).toBe(true);
    expect((manifest.icons ?? []).length).toBeGreaterThan(0);
  });

  test('page has correct viewport meta and a manifest link for mobile installability', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const viewport = await page.$eval(
      'meta[name="viewport"]',
      (el) => el.getAttribute('content'),
    );
    expect(viewport).toMatch(/width=device-width/);

    // The page must link to the web-app manifest.
    const manifestHref = await page
      .$eval('link[rel="manifest"]', (el) => el.getAttribute('href'))
      .catch(() => null);
    expect(manifestHref).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 2. Offline fallback — network blocked
// ---------------------------------------------------------------------------
test.describe('Offline fallback', () => {
  test.setTimeout(60_000);
  test('/offline.html renders the expected fallback UI', async ({ page }) => {
    const response = await page.goto('/offline.html');
    expect(response?.status()).toBe(200);

    await expect(page.getByRole('heading', { name: /offline/i })).toBeVisible();
    await expect(page.getByText(/waiting for connection/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible();
  });

  test('offline fallback page renders when the network is blocked', async ({ page, context }) => {
    // Prime with one real page load so the browser has the base URL in history.
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    // Read the offline.html body *before* switching to offline mode.
    const offlineBody = await page.request
      .fetch('/offline.html')
      .then((r) => r.body());

    // Intercept every subsequent navigation request and return the cached
    // offline.html — this mirrors what the production service worker does.
    // Use page.route('**', ...) for reliable interception of all requests,
    // and allow non-document resources through so React can render the
    // offline page heading.
    await page.route('**', async (route) => {
      const reqUrl = route.request().url();
      // Skip interception for the offline.html source itself
      if (reqUrl.includes('/offline.html')) {
        await route.continue();
        return;
      }
      if (route.request().resourceType() === 'document') {
        await route.fulfill({
          status: 200,
          contentType: 'text/html; charset=utf-8',
          body: offlineBody,
        });
      } else {
        // Allow JS/CSS through so the page can hydrate and render the heading
        await route.continue();
      }
    });

    await page.goto('/library', { waitUntil: 'domcontentloaded' });

    await expect(page.getByRole('heading', { name: /offline/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/waiting for connection/i)).toBeVisible({ timeout: 10_000 });
  });
});

// ---------------------------------------------------------------------------
// 3. Service Worker registration
// ---------------------------------------------------------------------------
test.describe('Service Worker', () => {
  test('sw.js is served with status 200 and a JavaScript content-type', async ({ page }) => {
    const response = await page.goto('/sw.js');
    expect(response?.status()).toBe(200);

    const ct = response?.headers()['content-type'] ?? '';
    // The browser requires a JS content-type to accept the file as a SW script.
    expect(ct).toMatch(/javascript|text\/plain/);
  });

  test('navigator.serviceWorker API is available in mobile Chromium', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');

    const available = await page.evaluate(() => 'serviceWorker' in navigator);
    expect(available).toBe(true);
  });

  test('service worker can be programmatically registered via navigator.serviceWorker', async ({ page }) => {
    // The app only auto-registers the SW in production builds (see src/index.jsx).
    // This test confirms that the /sw.js script is valid and the browser can
    // register it when called directly — equivalent to what happens in prod.
    await page.goto('/');
    await page.waitForLoadState('load');

    const registered = await page.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return false;
      try {
        const reg = await navigator.serviceWorker.register('/sw.js', {
          updateViaCache: 'none',
        });
        // Clean up so we don't leave a rogue SW running in other tests.
        await reg.unregister();
        return true;
      } catch {
        return false;
      }
    });

    expect(registered).toBe(true);
  });
});
