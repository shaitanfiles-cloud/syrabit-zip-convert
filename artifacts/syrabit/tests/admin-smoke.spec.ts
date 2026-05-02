/**
 * Admin Dashboard smoke test (Task #571).
 *
 * Task #567 was caused by a runtime ReferenceError / TypeError in a single
 * admin widget that propagated up to the global ErrorBoundary. This suite
 * is the regression gate: it logs in as the E2E admin account, opens
 * `/admin`, waits for the dashboard, and asserts that:
 *
 *   1. The global "Something went wrong" ErrorBoundary screen is NOT shown.
 *   2. The `data-testid="admin-dashboard"` shell IS shown.
 *   3. No uncaught ReferenceError / TypeError was emitted during render.
 *
 * A second test wipes one of the admin metrics endpoints to verify the
 * dashboard degrades gracefully (inline "Some widgets failed to load"
 * card) instead of crashing the whole shell.
 */
import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

interface ConsoleCapture {
  errors: string[];
  pageErrors: Error[];
}

function attachConsoleCapture(page: Page): ConsoleCapture {
  const capture: ConsoleCapture = { errors: [], pageErrors: [] };

  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() !== 'error') return;
    capture.errors.push(msg.text());
  });
  page.on('pageerror', (err: Error) => {
    capture.pageErrors.push(err);
  });

  return capture;
}

function findFatalRuntimeErrors(capture: ConsoleCapture): string[] {
  const fatal: string[] = [];

  // Uncaught ReferenceError / TypeError in console.error output.
  for (const text of capture.errors) {
    if (/ReferenceError|TypeError/.test(text) && !/network|fetch|axios|500|forced failure/i.test(text)) {
      fatal.push(`console.error: ${text}`);
    }
  }

  // Real uncaught exceptions surface as `pageerror`.
  for (const err of capture.pageErrors) {
    if (err.name === 'ReferenceError' || err.name === 'TypeError') {
      fatal.push(`pageerror: ${err.name}: ${err.message}`);
    }
  }

  return fatal;
}

test.describe('Admin Dashboard smoke', () => {
  test('renders the dashboard shell without falling through to global ErrorBoundary', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page);

    const capture = attachConsoleCapture(page);

    await page.goto('/admin');

    const dashboard = page.getByTestId('admin-dashboard');
    await expect(dashboard).toBeVisible();

    // The global ErrorBoundary heading must NOT have replaced the dashboard.
    await expect(
      page.getByRole('heading', { name: 'Something went wrong' }),
    ).toHaveCount(0);

    // Wait one render tick so any deferred effect crash has a chance to fire.
    await page.waitForLoadState('networkidle');

    const fatal = findFatalRuntimeErrors(capture);
    expect(
      fatal,
      `Uncaught ReferenceError/TypeError detected during admin dashboard render:\n${fatal.join('\n')}`,
    ).toEqual([]);
  });

  test('degrades gracefully when a single metrics endpoint is wiped', async ({ page }) => {
    await seedAdminSession(page);
    // Force one of the dashboard's parallel fetches to fail. The component
    // collects failures into `failedSections` and shows an inline amber
    // "Some widgets failed to load" card — the rest of the shell must
    // still render and the global ErrorBoundary must NOT trip.
    await installAdminApiMocks(page, { failPatterns: ['/api/admin/rag/accuracy'] });

    const capture = attachConsoleCapture(page);

    await page.goto('/admin');

    await expect(page.getByTestId('admin-dashboard')).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Something went wrong' }),
    ).toHaveCount(0);

    // The inline degradation banner should appear once the failed
    // request resolves. The dashboard renders this exactly when
    // `failedSections.length > 0`.
    await expect(
      page.getByText(/Some widgets failed|failed to load|couldn't load|widget.*error|error.*widget/i).first(),
    ).toBeVisible({ timeout: 20_000 });

    const fatal = findFatalRuntimeErrors(capture);
    expect(
      fatal,
      `Uncaught ReferenceError/TypeError detected during degraded render:\n${fatal.join('\n')}`,
    ).toEqual([]);
  });
});
