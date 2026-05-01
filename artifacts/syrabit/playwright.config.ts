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
    ...(launchOptions ? { launchOptions } : {}),
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      // pwa-mobile.spec.ts is scoped to mobile-chrome; skip it here so the
      // suite does not run twice under a desktop UA where mobile assertions
      // (viewport meta, touch events, install prompt) have different semantics.
      testIgnore: '**/pwa-mobile.spec.ts',
    },
    {
      // Task #3 — mobile viewport for PWA install-prompt & offline-fallback tests.
      // Uses a Pixel 5 profile: 393 × 851 logical px, deviceScaleFactor 2.75,
      // touch enabled, mobile UA — mirrors how most users access the PWA.
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
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
