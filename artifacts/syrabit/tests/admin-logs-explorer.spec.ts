/**
 * Admin Logs Explorer specs.
 *
 * 1. Logs render with timestamp, level, and message in the table.
 * 2. Filtering by ERROR level returns only error entries.
 * 3. Keyword search returns only matching entries.
 */
import { test, expect, type Page, type Route } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const ERROR_LOG = {
  _id: 'log-err-001', timestamp: '2026-04-26T10:00:00.000Z', received_at: '2026-04-26T10:00:01.000Z',
  source: 'backend', level: 'error', status: 500, method: 'POST', route: '/api/ai/chat/stream',
  duration_ms: 4500, country: 'IN', colo: 'BLR', cache: 'miss', correlation_id: 'corr-err-001',
  message: 'Vertex AI returned 503 for chat request',
};
const INFO_LOG = {
  _id: 'log-info-002', timestamp: '2026-04-26T10:01:00.000Z', received_at: '2026-04-26T10:01:01.000Z',
  source: 'edge', level: 'info', status: 200, method: 'GET', route: '/chapter/photosynthesis-class-11',
  duration_ms: 45, country: 'IN', colo: 'BLR', cache: 'hit', correlation_id: 'corr-info-002',
  message: 'Cache hit for chapter page',
};
const WARN_LOG = {
  _id: 'log-warn-003', timestamp: '2026-04-26T10:02:00.000Z', received_at: '2026-04-26T10:02:01.000Z',
  source: 'backend', level: 'warn', status: 429, method: 'POST', route: '/api/edu/quiz/generate',
  duration_ms: 120, country: 'IN', colo: 'BLR', cache: 'miss', correlation_id: 'corr-warn-003',
  message: 'Rate limit hit for quiz generation',
};

const ALL_LOGS = [ERROR_LOG, INFO_LOG, WARN_LOG];

const LOGS_STATUS = {
  paused: false, ttl_days: 14, ingest_token_configured: true,
  backend_sample_rate: 0.05, edge_sample_rate: 0.05,
  max_ingest_batch: 500, cf_pull_interval_s: 60, cf_pull_24h: null,
};

async function openLogsExplorer(page: Page) {
  await seedAdminSession(page);

  await installAdminApiMocks(page);

  // Narrow logs routes registered AFTER installAdminApiMocks (LIFO priority).
  await page.route('**/api/admin/logs/status*', async (route: Route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LOGS_STATUS) });
  });

  // Dynamic log list stub: server-side filter by levels= and q= query params.
  await page.route('**/api/admin/logs*', async (route: Route) => {
    const url = new URL(route.request().url());
    const levelsParam = url.searchParams.get('levels') || '';
    const qParam = url.searchParams.get('q') || '';

    let filtered = ALL_LOGS;
    if (levelsParam) {
      const allowedLevels = levelsParam.split(',').map((s) => s.trim().toLowerCase());
      filtered = filtered.filter((e) => allowedLevels.includes(e.level.toLowerCase()));
    }
    if (qParam) {
      const lq = qParam.toLowerCase();
      filtered = filtered.filter((e) => e.message.toLowerCase().includes(lq) || e.route.toLowerCase().includes(lq));
    }

    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ logs: filtered, total: filtered.length, total_capped: false, next_before: null }),
    });
  });

  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-logsexplorer').click();
}

test.describe('Admin Logs Explorer (Playwright E2E)', () => {
  test('logs render with timestamp, level, and message in the table', async ({ page }) => {
    await openLogsExplorer(page);

    await expect(page.getByText(/Vertex AI returned 503/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Cache hit for chapter/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Rate limit hit/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/error/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/2026-04-26|10:0/i).first()).toBeVisible({ timeout: 5_000 });
  });

  test('filtering by ERROR level (levels=error) returns only error entries', async ({ page }) => {
    await openLogsExplorer(page);

    // Wait for all logs to render first.
    await expect(page.getByText(/Vertex AI returned 503/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Cache hit for chapter/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Rate limit hit/i)).toBeVisible({ timeout: 5_000 });

    const errorFilter = page.getByRole('button', { name: /^error$/i }).first();
    await expect(errorFilter).toBeVisible({ timeout: 8_000 });
    await errorFilter.click();

    await expect(page.getByText(/Vertex AI returned 503/i)).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(/Cache hit for chapter/i)).not.toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Rate limit hit/i)).not.toBeVisible({ timeout: 5_000 });
  });

  test('keyword search (q=Vertex) returns only matching entries', async ({ page }) => {
    await openLogsExplorer(page);

    await expect(page.getByText(/Vertex AI returned 503/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Cache hit for chapter/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Rate limit hit/i)).toBeVisible({ timeout: 5_000 });

    const searchInput = page.getByPlaceholder(/search|filter|keyword|query|text|message|free/i).first();
    await expect(searchInput).toBeVisible({ timeout: 8_000 });
    await searchInput.fill('Vertex');

    // Apply button is optional — some implementations search on input change or Enter.
    const applyBtn = page.getByRole('button', { name: /apply|search|filter|go/i }).first();
    const applyVisible = await applyBtn.isVisible({ timeout: 3_000 }).catch(() => false);
    if (applyVisible) {
      await applyBtn.click();
    } else {
      await searchInput.press('Enter');
    }

    // Wait for the search response before asserting absence of non-matching rows.
    await page.waitForResponse(
      (res) => res.url().includes('/api/admin/logs') && !res.url().includes('/status'),
      { timeout: 10_000 },
    );
    await expect(page.getByText(/Vertex AI returned 503/i)).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(/Cache hit for chapter/i)).not.toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(/Rate limit hit/i)).not.toBeVisible({ timeout: 8_000 });
  });
});
