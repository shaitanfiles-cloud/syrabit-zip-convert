/**
 * Admin SEO Manager extended specs (Task #1 — 75 missing tests).
 *
 * Covers 4 cases:
 *   1. IndexNow submission fires on content publish.
 *   2. Keyword discovery returns ranked suggestions.
 *   3. Internal linker "Reject" flow hits the reject endpoint.
 *   4. Internal linker history tab renders approved/rejected items.
 *
 * Route registration order: installAdminApiMocks FIRST (broad all-api catch-all),
 * then narrow per-test tracking routes AFTER (higher Playwright LIFO priority).
 */
import { test, expect, type Page, type Route } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

interface ApiCall { url: string; method: string; body: unknown; }

const KEYWORD_SUGGESTIONS = {
  suggestions: [
    { keyword: 'photosynthesis class 11 ahsec', volume: 5400, difficulty: 32, score: 91 },
    { keyword: 'what is photosynthesis', volume: 12000, difficulty: 45, score: 85 },
  ],
};

const PENDING_PAYLOAD = {
  items: [
    {
      id: 'rec-reject-001', sourcePageId: 'p-src', sourceTopicTitle: 'Plant Physiology',
      targetPageId: 'p-tgt', targetTopicTitle: 'Mineral Nutrition', anchorText: 'minerals',
      confidence: 0.55, reason: 'keyword match in body',
      diff: {
        beforeExcerpt: 'Plants absorb minerals through roots.',
        afterExcerpt: 'Plants absorb <a href="/x/minerals">minerals</a> through roots.',
      },
    },
  ],
};

const HISTORY_ITEMS = {
  items: [
    { id: 'hist-001', anchorText: 'osmosis', decision: 'approved', decidedAt: new Date().toISOString() },
    { id: 'hist-002', anchorText: 'diffusion', decision: 'rejected', decidedAt: new Date().toISOString() },
  ],
};

const LINKER_STATUS = {
  enabled: true, budget: { auto_used: 4, auto_cap: 100 },
  pendingCount: 1, recentAutoApplied24h: 4,
  config: { autoApplyThreshold: 0.75, minLinksPerTarget: 3, maxLinksPerTarget: 5, candidatePoolSize: 30, nightlyTopN: 50 },
};

async function openSeoManager(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-seomanager').click();
}

test.describe('Admin SEO Manager — extended', () => {
  test('IndexNow submission fires on content publish', async ({ page }) => {
    await seedAdminSession(page);

    // Broad catch-all first with IndexNow fixtures.
    await installAdminApiMocks(page, {
      overrides: {
        '/api/admin/indexnow/stats': () => ({ endpoints: [{ name: 'bing', submitted: 5, last_submitted_at: new Date().toISOString() }] }),
        '/api/admin/indexnow/history': () => ({ history: [{ url: '/chapter/photosynthesis', submitted_at: new Date().toISOString(), status: 'ok' }] }),
      },
    });

    // Narrow tracking route registered AFTER.
    const indexNowCalls: ApiCall[] = [];
    await page.route('**/api/admin/indexnow*', async (route: Route) => {
      const req = route.request();
      let body: unknown = null;
      try { body = req.postDataJSON(); } catch { body = req.postData(); }
      indexNowCalls.push({ url: req.url(), method: req.method(), body });
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, submitted: 1 }) });
    });

    await openSeoManager(page);

    const indexNowNav = page.getByRole('button', { name: /index.?now/i }).first();
    await expect(indexNowNav).toBeVisible({ timeout: 10_000 });
    await indexNowNav.click();

    const submitBtn = page.getByRole('button', { name: /submit|index now/i }).first();
    await expect(submitBtn).toBeVisible({ timeout: 8_000 });
    await submitBtn.click();

    await expect.poll(() => indexNowCalls.length, { timeout: 5_000 }).toBeGreaterThan(0);
  });

  test('keyword discovery returns ranked suggestions', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page);

    // Narrow keyword routes registered AFTER.
    await page.route('**/api/admin/seo/keywords*', async (route: Route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(KEYWORD_SUGGESTIONS) });
    });
    await page.route('**/api/admin/seo/keyword-discovery*', async (route: Route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(KEYWORD_SUGGESTIONS) });
    });

    await openSeoManager(page);

    const keywordsTab = page.getByRole('button', { name: /keyword/i }).first();
    await expect(keywordsTab).toBeVisible({ timeout: 10_000 });
    await keywordsTab.click();

    await expect(page.getByText(/photosynthesis.*ahsec|keyword/i).first()).toBeVisible({ timeout: 8_000 });
  });

  test('internal linker "Reject" flow hits the reject endpoint', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        '/api/admin/seo/internal-links/status': () => LINKER_STATUS,
        '/api/admin/seo/internal-links/pending': () => PENDING_PAYLOAD,
        '/api/admin/seo/internal-links/history': () => ({ items: [] }),
      },
    });

    // Narrow tracking route for reject calls, registered AFTER.
    const rejectCalls: ApiCall[] = [];
    await page.route('**/api/admin/seo/internal-links/**/reject', async (route: Route) => {
      const req = route.request();
      let body: unknown = null;
      try { body = req.postDataJSON(); } catch { body = req.postData(); }
      rejectCalls.push({ url: req.url(), method: req.method(), body });
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
    });

    await openSeoManager(page);
    await page.getByRole('button', { name: /Links/i }).first().click();

    const linkerPanel = page.getByTestId('linker-agent-panel');
    await expect(linkerPanel).toBeVisible({ timeout: 10_000 });

    const rejectBtn = page.getByTestId('linker-reject-rec-reject-001');
    await expect(rejectBtn).toBeVisible({ timeout: 8_000 });
    await rejectBtn.click();

    await expect.poll(() => rejectCalls.length, { timeout: 5_000 }).toBeGreaterThan(0);
    expect(rejectCalls[0].url).toContain('/api/admin/seo/internal-links/rec-reject-001/reject');
  });

  test('internal linker history tab renders approved and rejected items', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        '/api/admin/seo/internal-links/status': () => ({ ...LINKER_STATUS, pendingCount: 0 }),
        '/api/admin/seo/internal-links/pending': () => ({ items: [] }),
        '/api/admin/seo/internal-links/history': () => HISTORY_ITEMS,
      },
    });

    await openSeoManager(page);
    await page.getByRole('button', { name: /Links/i }).first().click();

    const linkerPanel = page.getByTestId('linker-agent-panel');
    await expect(linkerPanel).toBeVisible({ timeout: 10_000 });

    const historyTab = page.getByRole('button', { name: /history|log|past|approved/i }).first();
    await expect(historyTab).toBeVisible({ timeout: 10_000 });
    await historyTab.click();

    await expect(page.getByText(/osmosis|approved/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/diffusion|rejected/i)).toBeVisible({ timeout: 5_000 });
  });
});
