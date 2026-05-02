import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.PLAYWRIGHT_PORT || 4317);
const baseURL = `http://127.0.0.1:${PORT}`;

// Task #904 — on the Replit/NixOS image Playwright's bundled Chromium
// fails to load (`libgbm.so.1` missing, `libudev.so.1` only ships as
// .so.0, `libatk-bridge` symbol mismatch). Replit pre-stages a working
// Chromium under `REPLIT_PLAYWRIGHT_CHROMIUM_EXECUTABLE`; using it via
// `launchOptions.executablePath` skips the bundled binary entirely and
// avoids the lib shim dance. CI does not set this env var and falls
// back to the bundled Chromium, which it has the right libs for.
// (For local installs that *don't* have the env var set —
// e.g. a fresh checkout before opening the project — `scripts/run-e2e.sh`
// sets up an LD_LIBRARY_PATH shim so the bundled binary still works.)
const replitChromium = process.env.REPLIT_PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const launchOptions = replitChromium ? { executablePath: replitChromium } : undefined;

export default defineConfig({
  testDir: './tests',
  globalSetup: './tests/global-setup.ts',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    // Block service-worker registration so Playwright's page.route()
    // intercepts all /api/** requests before the SW can claim them.
    // In CI the app is served via `vite preview` with NODE_ENV=production
    // so import.meta.env.PROD === true and the SW would otherwise register
    // and intercept /api/content/boards, /api/content/subjects, etc.,
    // bypassing every page.route() mock and causing ECONNREFUSED proxy errors.
    serviceWorkers: 'block',
    ...(launchOptions ? { launchOptions } : {}),
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Service workers are blocked globally (see above) so page.route()
        // mocks work reliably for all non-PWA tests. The two desktop PWA
        // specs (pwa-push.spec.ts, pwa-permission.spec.ts) that need a live
        // SW handle run under the chromium-pwa-desktop project below instead.
        serviceWorkers: 'block',
      },
      // pwa-mobile.spec.ts is scoped to mobile-chrome (below).
      // pwa-push.spec.ts and pwa-permission.spec.ts run under
      // chromium-pwa-desktop (below) where SW is allowed.
      testIgnore: [
        '**/pwa-mobile.spec.ts',
        '**/pwa-push.spec.ts',
        '**/pwa-permission.spec.ts',
      ],
    },
    {
      // Desktop PWA specs that register /sw.js directly and obtain a
      // Playwright Worker handle via context.waitForEvent('serviceworker').
      // serviceWorkers:'allow' is required so the SW can register and fire
      // push/notificationclick events inside the test. All /api/** routes
      // in these tests are still mocked via page.route() — Playwright's CDP
      // interception fires before the SW fetch handler on non-navigation
      // requests so the mocks remain effective.
      name: 'chromium-pwa-desktop',
      use: {
        ...devices['Desktop Chrome'],
        serviceWorkers: 'allow',
      },
      testMatch: [
        '**/pwa-push.spec.ts',
        '**/pwa-permission.spec.ts',
      ],
    },
    {
      // Task #3 — mobile viewport for PWA install-prompt & offline-fallback tests.
      // Uses a Pixel 5 profile: 393 × 851 logical px, deviceScaleFactor 2.75,
      // touch enabled, mobile UA — mirrors how most users access the PWA.
      name: 'mobile-chrome',
      use: {
        ...devices['Pixel 5'],
        // pwa-mobile.spec.ts exercises navigator.serviceWorker.register() to
        // verify SW registration succeeds on the mobile viewport — allow SW
        // registration for this project so the context.waitForEvent call
        // doesn't time out.
        serviceWorkers: 'allow',
      },
      testMatch: '**/pwa-mobile.spec.ts',
    },
  ],
  webServer: {
    // In CI the app is pre-built (see all-tests.yml build step) so we serve
    // the compiled dist/ with `vite preview`.  This avoids Vite's on-demand
    // module compilation which on a cold GitHub Actions runner can take 20-30s
    // per first page load — far longer than the 10s toBeVisible() timeout.
    //
    // Locally we fall back to `vite dev` (or reuse an existing server) so the
    // hot-module-reload workflow is unchanged.
    command: process.env.CI
      ? `pnpm exec vite preview --port ${PORT} --host 127.0.0.1 --strictPort`
      : `pnpm exec vite --port ${PORT} --host 127.0.0.1 --strictPort`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
