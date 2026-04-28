/**
 * Internal-linker tab smoke + approve-flow e2e (Task #939 acceptance gate).
 *
 * The architect review on Task #939 insisted that the agentic
 * internal-link agent ship with at least one Playwright e2e exercising
 * the operator surface end-to-end: open the SEO Manager, switch to the
 * Links tab, render the pending suggestions queue, click Approve on
 * one row, and verify the approve endpoint is hit with the right
 * record id.
 *
 * Backend service + route tests cover correctness; this test covers
 * "the operator-visible surface didn't regress".
 */
import { test, expect, type Page } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const PENDING_PAYLOAD = {
  items: [
    {
      id: 'rec-pending-001',
      sourcePageId: 'p-src',
      sourceTopicTitle: 'Understanding Inertia',
      targetPageId: 'p-tgt',
      targetTopicTitle: "Newton's First Law",
      anchorText: 'Newton',
      confidence: 0.62,
      reason: 'natural mention in body',
      diff: {
        beforeExcerpt: 'Newton wrote about motion in Principia.',
        afterExcerpt: '<a href="/x/newton">Newton</a> wrote about motion in Principia.',
      },
    },
  ],
};

// Mirror the actual backend contract from
// routes/admin_seo_internal_linker.py (nested ``budget`` and ``config``
// sub-objects). Using the real shape here means any future drift in
// the route response would actually fail the e2e instead of silently
// passing on a fake fixture shape.
const STATUS_PAYLOAD = {
  enabled: true,
  budget: { auto_used: 4, auto_cap: 100 },
  pendingCount: 1,
  recentAutoApplied24h: 4,
  config: {
    autoApplyThreshold: 0.75,
    minLinksPerTarget: 3,
    maxLinksPerTarget: 5,
    candidatePoolSize: 30,
    nightlyTopN: 50,
  },
};

interface ApproveCall {
  url: string;
  body: unknown;
}

test.describe('Internal-linker (Links tab)', () => {
  test('renders pending queue and submits approve', async ({ page }) => {
    const captured: ApproveCall[] = [];

    // Capture the approve POST. The record id lives in the URL path,
    // not the body — same convention as the topic-discovery override.
    await page.route(
      '**/api/admin/seo/internal-links/*/approve',
      async (route) => {
        const req = route.request();
        let body: unknown = null;
        try { body = req.postDataJSON(); } catch { body = req.postData(); }
        captured.push({ url: req.url(), body });
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, recId: 'rec-pending-001' }),
        });
      },
    );

    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        '/api/admin/seo/internal-links/status':  () => STATUS_PAYLOAD,
        '/api/admin/seo/internal-links/pending': () => PENDING_PAYLOAD,
        '/api/admin/seo/internal-links/history': () => ({ items: [] }),
      },
    });

    await page.goto('/admin');
    await expect(page.getByTestId('admin-dashboard')).toBeVisible();

    // The admin uses state-based section switching (not URL routing).
    await page.getByRole('button', { name: /SEO Manager/i }).first().click();
    // Switch to the Links tab (label includes a 🔗 icon character on
    // some builds; match the word case-insensitively).
    await page.getByRole('button', { name: /Links/i }).first().click();

    // The linker panel itself.
    await expect(page.getByTestId('linker-agent-panel')).toBeVisible();

    // Pending row is rendered with the approve + reject controls.
    const row = page.getByTestId('linker-pending-rec-pending-001');
    await expect(row).toBeVisible();
    await expect(row).toContainText('Inertia');
    await expect(row).toContainText("Newton's First Law");
    await expect(row).toContainText('"Newton"');

    const approveBtn = page.getByTestId('linker-approve-rec-pending-001');
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();

    // Approve endpoint hit with the right record id in the path.
    await expect
      .poll(() => captured.length, { timeout: 5_000 })
      .toBeGreaterThan(0);
    expect(captured[0].url).toContain(
      '/api/admin/seo/internal-links/rec-pending-001/approve',
    );
  });
});
