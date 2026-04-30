/**
 * Task #940 — Playwright e2e for the Entity SEO admin panel.
 *
 * Seeds a snapshot with one regression + two missing claims via
 * `installAdminApiMocks` overrides, navigates to the SEO Manager,
 * switches to the Entity tab, and asserts the operator can:
 *
 *   * see the regression list with the offending signal name,
 *   * see deep-link buttons pointing at the Wikidata edit URLs,
 *   * see the per-signal status pills (one healthy, one degraded).
 */
import { test, expect } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const DRIFT_PAYLOAD = {
  configured: true,
  snapshot: {
    generated_at: '2026-04-26T04:30:00.000Z',
    iso_week: '2026-W17',
    aggregate_status: 'degraded',
    signals: {
      wikidata:  { status: 'missing', summary: 'Wikidata entity Q42 not found (deleted?).',
                   fields: { qid: 'Q42', claim_count: 0,
                             edit_url: 'https://www.wikidata.org/wiki/Q42' } },
      wikipedia: { status: 'ok', summary: 'Article live.',
                   fields: { title: 'Syrabit.ai',
                             page_url: 'https://en.wikipedia.org/wiki/Syrabit.ai' } },
      crunchbase:{ status: 'ok', summary: 'Crunchbase reachable.',
                   fields: { permalink: 'syrabit-ai', completeness_pct: 75,
                             page_url: 'https://www.crunchbase.com/organization/syrabit-ai' } },
      sameas:    { status: 'ok', summary: '7/7 verified profiles live.',
                   fields: { total: 7, broken: [] } },
      google_kg: { status: 'missing', summary: 'No Knowledge Panel entry surfaced.',
                   fields: { configured: true } },
    },
    summary: { wikidata_claims: 0, wikidata_missing: 7, sameas_broken: 0 },
    missing_claims: [],
  },
  previous: { iso_week: '2026-W16' },
  drift: {
    hadBaseline: true,
    regressions: [
      { name: 'wikidata', from: 'ok', to: 'missing',
        summary: 'Wikidata entity Q42 not found (deleted?).' },
      { name: 'google_kg', from: 'ok', to: 'missing',
        summary: 'No Knowledge Panel entry surfaced.' },
    ],
    improvements: [],
    summaryDeltas: {
      wikidata_claims:  { current: 0, previous: 7, delta: -7 },
      wikidata_missing: { current: 7, previous: 0, delta:  7 },
      sameas_broken:    { current: 0, previous: 0, delta:  0 },
    },
  },
  missingClaims: [
    { prop: 'P131', label: 'located in (Guwahati / Assam)', expected: 'Q207749',
      edit_url: 'https://www.wikidata.org/wiki/Q42#P131' },
    { prop: 'P112', label: 'founder (Dipak Rai)', expected: '',
      edit_url: 'https://www.wikidata.org/wiki/Q42#P112' },
  ],
  alertState: {
    lastPagedAt: '2026-04-26T05:00:00.000Z',
    fingerprint: 'google_kg,wikidata',
    regressionCount: 2,
  },
};

test.describe('Entity SEO admin panel', () => {
  test.beforeEach(async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        '/api/admin/seo/entity/status': DRIFT_PAYLOAD,
      },
    });
  });

  test('renders drift event with regressions + deep-link claims', async ({ page }) => {
    await page.goto('/admin');
    await page.getByTestId('admin-nav-seomanager').click();
    // Switch to the Entity SEO tab; the label includes the 🪪 emoji
    // so we match by case-insensitive substring.
    await page.getByRole('button', { name: /Entity SEO/i }).first().click();

    const tab = page.getByTestId('entity-seo-tab');
    await expect(tab).toBeVisible();

    // Aggregate pill is "degraded".
    await expect(tab.getByTestId('entity-status-pill-degraded')).toBeVisible();

    // Regression list surfaces the broken signals.
    const regressions = tab.getByTestId('entity-regressions');
    await expect(regressions).toBeVisible();
    await expect(regressions).toContainText('2 signal regressions');
    await expect(regressions).toContainText('wikidata');
    await expect(regressions).toContainText('google_kg');

    // Per-signal cards: wikidata is missing, wikipedia is healthy.
    await expect(tab.getByTestId('entity-signal-wikidata')
      .getByTestId('entity-status-pill-missing')).toBeVisible();
    await expect(tab.getByTestId('entity-signal-wikipedia')
      .getByTestId('entity-status-pill-ok')).toBeVisible();

    // Deep-link buttons pointing at the Wikidata edit URL.
    const link131 = tab.getByTestId('entity-missing-claim-P131');
    await expect(link131).toHaveAttribute('href', 'https://www.wikidata.org/wiki/Q42#P131');
    await expect(link131).toHaveAttribute('target', '_blank');
    await expect(tab.getByTestId('entity-missing-claim-P112')).toBeVisible();

    // Alert state caption surfaces the last-paged timestamp.
    await expect(tab.getByTestId('entity-alert-state'))
      .toContainText('Last drift alert paged');
  });
});
