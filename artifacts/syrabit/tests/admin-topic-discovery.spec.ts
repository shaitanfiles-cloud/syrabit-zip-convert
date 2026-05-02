/**
 * Topic Discovery tab smoke test (Task #937 acceptance gate).
 *
 * Architect code review insisted that the autonomous nightly
 * topic-discovery flow ships with at least one Playwright e2e that
 * exercises the admin panel: opens the SEO Manager, switches to the
 * Discovery tab, asserts the runs sidebar + candidates table render,
 * and verifies an admin override action wires up to the override
 * endpoint. Backend unit/route tests cover correctness; this test
 * covers "the operator-visible surface didn't regress".
 */
import { test, expect, type Page } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const RUN_ID = 'run_test_001';

const RUNS_PAYLOAD = {
  runs: [
    {
      id: RUN_ID,
      kind: 'run',
      startedAt: '2026-04-26T02:00:00Z',
      finishedAt: '2026-04-26T02:01:30Z',
      totals: { raw: 5, auto_published: 1, drafted: 2, rejected: 2, error: 0 },
    },
  ],
};

const CANDIDATES_PAYLOAD = {
  candidates: [
    {
      id: 'cand_published_001',
      runId: RUN_ID,
      query: 'photosynthesis class 11 ahsec',
      sources: ['gsc_near_miss'],
      signals: { gsc_near_miss: { impressions: 1200, position: 12.4 } },
      score: { intent_fit: 90, syllabus_alignment: 95, difficulty: 75,
               aeo_readability: 80, total: 87, reason: 'strong syllabus fit' },
      decision: 'auto_published',
      decisionReason: 'score above auto threshold',
      enqueuedTopic: 'photosynthesis-class-11-ahsec',
      enqueueError: null,
      createdAt: '2026-04-26T02:00:30Z',
    },
    {
      id: 'cand_drafted_002',
      runId: RUN_ID,
      query: 'newton laws class 11',
      sources: ['suggest_expansion'],
      signals: { suggest_expansion: { seed: 'newton', rank: 2 } },
      score: { intent_fit: 70, syllabus_alignment: 65, difficulty: 60,
               aeo_readability: 65, total: 65, reason: 'borderline' },
      decision: 'drafted',
      decisionReason: 'score in draft band',
      enqueuedTopic: 'newton-laws-class-11',
      enqueueError: null,
      createdAt: '2026-04-26T02:00:45Z',
    },
    {
      id: 'cand_rejected_003',
      runId: RUN_ID,
      query: 'random off-syllabus query',
      sources: ['trending'],
      signals: { trending: { score: 0.4 } },
      score: { intent_fit: 30, syllabus_alignment: 20, difficulty: 20,
               aeo_readability: 25, total: 24, reason: 'off-syllabus' },
      decision: 'rejected',
      decisionReason: 'score below draft threshold',
      enqueuedTopic: null,
      enqueueError: null,
      createdAt: '2026-04-26T02:00:50Z',
    },
  ],
};

interface OverrideCall {
  url: string;
  body: unknown;
}

function setupTopicDiscoveryRoutes(page: Page) {
  // Reserved for future test cases that don't need the POST body —
  // the override flow asserts via a dedicated page.route hook below.
  const overrideCalls: OverrideCall[] = [];
  void page;
  return { overrideCalls };
}

test.describe('Topic Discovery tab', () => {
  test('renders runs + candidates and submits an admin override', async ({ page }) => {
    const { overrideCalls } = setupTopicDiscoveryRoutes(page);
    const captured: OverrideCall[] = [];

    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        '/api/admin/seo/topic-discovery/runs': () => RUNS_PAYLOAD,
        '/api/admin/seo/topic-discovery/candidates': () => CANDIDATES_PAYLOAD,
      },
    });

    // Registered AFTER installAdminApiMocks (LIFO priority) so this narrow route
    // wins over the catch-all for the override endpoint.
    await page.route(
      '**/api/admin/seo/topic-discovery/**/override',
      async (route) => {
        const req = route.request();
        let body: unknown = null;
        try {
          body = req.postDataJSON();
        } catch {
          body = req.postData();
        }
        captured.push({ url: req.url(), body });
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, candidateId: 'cand_drafted_002' }),
        });
      },
    );

    await page.goto('/admin');

    // Wait for the dashboard shell to load before navigating sidebars.
    await expect(page.getByTestId('admin-dashboard')).toBeVisible();

    // The admin uses state-based section switching (not URL routing).
    // Click the SEO Manager nav button by label.
    await page.getByRole('button', { name: /SEO Manager/i }).first().click();

    // Switch to the Discovery tab — label is "🤖 Discovery".
    await page.getByRole('button', { name: /Discovery/i }).first().click();

    const tab = page.getByTestId('topic-discovery-tab');
    await expect(tab).toBeVisible();

    // Runs sidebar populated.
    const runsList = page.getByTestId('topic-discovery-runs');
    await expect(runsList).toBeVisible();
    await expect(page.getByTestId(`topic-discovery-run-${RUN_ID}`)).toBeVisible();

    // Candidates table populated. The default filter is "all" so all
    // three candidates render.
    const candidates = page.getByTestId('topic-discovery-candidates');
    await expect(candidates).toBeVisible();
    await expect(page.getByTestId('topic-discovery-candidate-cand_published_001')).toBeVisible();
    await expect(page.getByTestId('topic-discovery-candidate-cand_drafted_002')).toBeVisible();
    await expect(page.getByTestId('topic-discovery-candidate-cand_rejected_003')).toBeVisible();

    // Admin override: stub the prompt() that the tab uses to collect
    // the override reason, then click "promote" on the drafted row.
    page.once('dialog', async (dialog) => {
      // First call from override flow is a confirm or prompt asking
      // for a reason — accept with a stock reason.
      await dialog.accept('e2e: looks good, promote');
    });
    page.on('dialog', async (dialog) => {
      // Any subsequent dialog (confirm, etc.) — accept.
      await dialog.accept('e2e: looks good, promote');
    });

    const promoteBtn = page.getByTestId('topic-discovery-promote-cand_drafted_002');
    await expect(promoteBtn).toBeVisible();
    await promoteBtn.click();

    // Assert the override endpoint was hit. The candidate id lives in
    // the URL path; the JSON body carries {decision, reason} as
    // produced by adminTopicDiscoveryOverride() in utils/api.jsx.
    await expect
      .poll(() => captured.length, { timeout: 5_000 })
      .toBeGreaterThan(0);
    const call = captured[0];
    expect(call.url).toContain(
      '/api/admin/seo/topic-discovery/cand_drafted_002/override',
    );
    expect(call.body && typeof call.body === 'object').toBe(true);
    const body = call.body as Record<string, unknown>;
    expect(body).toHaveProperty('decision');
    // The promote button issues an "auto_published" override; reason
    // comes from our stubbed prompt() above.
    expect(body.decision).toBe('auto_published');
    expect(body).toHaveProperty('reason');
    expect(typeof body.reason).toBe('string');
    expect((body.reason as string).length).toBeGreaterThan(0);

    void overrideCalls;
  });
});
