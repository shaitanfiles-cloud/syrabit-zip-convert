import type { Page, Route } from '@playwright/test';

/**
 * Default JSON payload for any admin endpoint that the dashboard hits but
 * for which we don't want a tailored fixture. The dashboard uses defensive
 * `safeArr` / `safeObj` normalizers so an empty object is enough to render
 * the widget without crashing the global ErrorBoundary.
 */
const EMPTY = {};

/**
 * Per-endpoint fixtures. Keys are matched as substrings against the
 * request URL. The first match wins. Each handler returns the JSON body to
 * respond with (status 200) — return `null` to fall through to the
 * catch-all empty payload.
 */
type Fixture = (url: string) => unknown;

const FIXTURES: Array<[string, Fixture]> = [
  // --- Auth / session -----------------------------------------------------
  ['/api/admin/verify', () => ({
    name: 'E2E Admin',
    email: 'e2e-admin@syrabit.ai',
    access_token: 'e2e.admin.jwt',
  })],
  ['/api/admin/login', () => ({
    name: 'E2E Admin',
    email: 'e2e-admin@syrabit.ai',
    access_token: 'e2e.admin.jwt',
  })],

  // --- Top-level chrome ---------------------------------------------------
  // HealthOut (response_model on GET /api/health) requires: status, version,
  // service, workers, uptime_seconds, dependencies.  Keep all fields so the
  // global fixture-schema validator does not flag missing required fields.
  ['/api/health', () => ({
    status: 'ok',
    version: '0.0.0-e2e',
    service: 'syrabit-api',
    workers: 1,
    uptime_seconds: 0,
    dependencies: {},
  })],
  ['/api/admin/settings', () => ({ maintenance_mode: false })],
  ['/api/admin/alerts/unacknowledged-count', () => ({ count: 0 })],
  ['/api/admin/notification-prefs', () => ({
    sound_enabled: true,
    push_enabled: false,
    chime_tone: 'default',
    sound_severities: [],
    push_severities: [],
  })],
  ['/api/admin/push/delivery-stats', () => ({ totals: {}, daily: [] })],
  ['/api/admin/alert-settings', () => ({ channel_status: { push: null } })],
  ['/api/admin/seo/daily-summary-dispatches', () => ({ dispatches: [] })],
  ['/api/admin/kv-health', () => ({ configured: false })],
  ['/api/admin/ci-status', () => ({ configured: false })],

  // --- Dashboard data -----------------------------------------------------
  ['/api/admin/dashboard/metrics', () => ({})],
  ['/api/admin/dashboard', () => ({
    users: { total: 0, signups_today: 0 },
    conversations: { total: 0, today: 0 },
    content: { subjects: 0, chapters: 0 },
    activity: [],
    dependencies: {},
  })],
  ['/api/admin/rag/accuracy', () => ({ accuracy: 100, alert: 'green' })],
  ['/api/admin/chat/fallbacks', () => ({ daily: [], alert: 'green' })],
  ['/api/admin/vector/stats', () => ({ pages: {}, chapters: {} })],
  ['/api/admin/perf/latency', () => ({ daily: [], alert: 'green' })],
  ['/api/admin/chat/speedups', () => ({ daily: [], warm_runs: [], totals: {} })],
  ['/api/admin/analytics/queries', () => ({ top_queries: [] })],
  ['/api/admin/billing/tokens', () => ({ daily: [], totals: {} })],
  ['/api/admin/monetization/funnel', () => ({})],
  ['/api/admin/content/coverage', () => ({})],
  ['/api/admin/pwa/stats', () => ({})],
  ['/api/admin/analytics/bot-traffic', () => ({})],
  ['/api/admin/indexnow/stats', () => ({ endpoints: [] })],
  ['/api/admin/indexnow/history', () => ({ history: [] })],
  ['/api/admin/alerts', () => ({ alerts: [] })],
  ['/api/admin/seo/health-history', () => ({ history: [] })],
  ['/api/admin/seo/deep-scan-history', () => ({})],
  // Corrected from /api/admin/cf/overview — the real backend path is
  // /api/admin/analytics/cf-overview (confirmed in server.py + api.jsx).
  ['/api/admin/analytics/cf-overview', () => ({})],
  // Corrected from /api/seo/pipeline/status — the real backend path is
  // /api/admin/seo/pipeline-status (confirmed in server.py + api.jsx).
  ['/api/admin/seo/pipeline-status', () => ({
    total_topics: 0, published: 0, has_content: 0,
    needs_schema: 0, needs_internal_links: 0,
    pages_total: 0, published_today: 0,
  })],
  ['/api/seo/health', () => ({ sitemaps: [] })],

  // Task #940 — Entity SEO admin panel.
  // Default fixture surfaces a "healthy / nothing missing" snapshot so
  // the dashboard renders the panel chrome without erroring. Drift
  // scenarios are wired via per-test `overrides`.
  ['/api/admin/seo/entity/status', () => ({
    configured: true,
    snapshot: {
      generated_at: '2026-04-26T04:30:00.000Z',
      iso_week: '2026-W17',
      aggregate_status: 'ok',
      summary: {
        wikidata_claims: 7, wikidata_missing: 0,
        sameas_total: 7, sameas_broken: 0,
        wikipedia_present: true, crunchbase_present: true, google_kg_present: true,
      },
      signals: {
        wikidata:   { name: 'wikidata',   status: 'ok',
          summary: 'Syrabit.ai (Q123) — 7 claims, 0 desired claims missing.',
          fields: { qid: 'Q123', claim_count: 7, present_claims: ['P31','P17'],
                    missing_claims: [], edit_url: 'https://www.wikidata.org/wiki/Q123' } },
        wikipedia:  { name: 'wikipedia',  status: 'ok',
          summary: 'Article live: Syrabit.ai',
          fields: { title: 'Syrabit.ai', page_url: 'https://en.wikipedia.org/wiki/Syrabit.ai' } },
        crunchbase: { name: 'crunchbase', status: 'ok',
          summary: 'Crunchbase profile reachable (100% of tracked fields detected).',
          fields: { permalink: 'syrabit-ai', completeness_pct: 100,
                    page_url: 'https://www.crunchbase.com/organization/syrabit-ai' } },
        sameas:     { name: 'sameas',     status: 'ok',
          summary: 'All 7 verified profiles live.',
          fields: { total: 7, broken: [] } },
        google_kg:  { name: 'google_kg',  status: 'ok',
          summary: 'Knowledge Panel present for all 2 tracked queries.',
          fields: { configured: true, name: 'Syrabit.ai',
                    queries: [
                      { query: 'Syrabit',    status: 'ok', kg_id: 'kg:/m/syrabit', name: 'Syrabit.ai',    score: 950 },
                      { query: 'Syrabit.ai', status: 'ok', kg_id: 'kg:/m/syrabit', name: 'Syrabit.ai',    score: 940 },
                    ] } },
        mentions:   { name: 'mentions',   status: 'ok',
          summary: 'All 3 mention targets cover us.',
          fields: { total: 3, missing: [], targets: [] } },
      },
      missing_claims: [],
      missing_mentions: [],
    },
    previous: null,
    drift: { hadBaseline: false, regressions: [], improvements: [],
             summaryDeltas: {
               wikidata_claims:  { current: 7, previous: 7, delta: 0 },
               wikidata_missing: { current: 0, previous: 0, delta: 0 },
               sameas_broken:    { current: 0, previous: 0, delta: 0 },
             } },
    missingClaims: [],
    missingMentions: [],
    alertState: null,
  })],
  ['/api/admin/seo/entity/history', () => ({ items: [] })],
  ['/api/admin/seo/entity/refresh', () => ({
    configured: true,
    snapshot: null, previous: null,
    drift: { hadBaseline: false, regressions: [], improvements: [], summaryDeltas: {} },
    missingClaims: [], alertState: null,
    refresh: { claimed: true, stored: true, regression_count: 0, paged: false },
  })],
];

/**
 * Flat list of every URL substring key registered in FIXTURES.
 *
 * Imported by tests/global-setup.ts so the fixture-schema drift
 * validator can check each key against the committed OpenAPI snapshot
 * (tests/api-schema.json) at test startup without duplicating the list
 * here and in the setup file.
 */
export const FIXTURE_KEYS: readonly string[] = FIXTURES.map(([key]) => key);

/**
 * Representative fixture body for every URL key in FIXTURES.
 *
 * Each entry is the JSON object that the mock will actually return for
 * a request whose URL contains the corresponding key.  Calling the
 * fixture function with the key as the URL is correct for all fixtures
 * that ignore the URL argument (the vast majority); the few that do
 * use the URL (e.g. history paginators) return a type-stable shape at
 * any URL, so the key itself is a safe stand-in.
 *
 * Imported by tests/global-setup.ts so the drift validator can validate
 * these payloads against the OpenAPI response schemas for their
 * matching backend paths — catching field renames, type changes, and
 * removed required fields automatically at test startup.
 */
export const FIXTURE_SAMPLES: ReadonlyMap<string, unknown> = new Map(
  FIXTURES.map(([key, fn]) => [key, fn(key)] as const),
);

interface InstallOptions {
  /**
   * URL substrings to force-fail with a 500 status. Used to assert that
   * the dashboard degrades gracefully (inline "failed to load" card)
   * instead of falling through to the global ErrorBoundary.
   */
  failPatterns?: string[];
  /**
   * Per-endpoint fixture overrides keyed by URL substring. Checked
   * before the default FIXTURES list so a single test can replace
   * the catch-all empty payload for one endpoint (e.g. the
   * AdminHealth cron pills) without disturbing the rest of the
   * dashboard mocks. The value is the JSON body to respond with
   * (status 200), or a function returning that body.
   */
  overrides?: Record<string, unknown | ((url: string) => unknown)>;
}

export async function installAdminApiMocks(page: Page, opts: InstallOptions = {}) {
  const failPatterns = opts.failPatterns ?? [];
  // Match the more-specific override first so a key like
  // `/api/admin/health/edge-proxy-deploy/cron` doesn't shadow
  // `/api/admin/health/edge-proxy-deploy/cron/alert-state` (the
  // first is a prefix of the second, and `Array.find` returns
  // the first hit). Sorting by descending key length means
  // longer/more-specific patterns always win — author order
  // inside the `overrides` object then doesn't matter.
  const overrides = Object.entries(opts.overrides ?? {})
    .sort(([a], [b]) => b.length - a.length);

  await page.route('**/api/**', async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();

    if (failPatterns.some((p) => url.includes(p))) {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'forced failure (e2e)' }),
      });
      return;
    }

    if (method === 'OPTIONS') {
      await route.fulfill({ status: 204, body: '' });
      return;
    }

    const override = overrides.find(([key]) => url.includes(key));
    if (override) {
      const [, value] = override;
      const body = typeof value === 'function' ? (value as (u: string) => unknown)(url) : value;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body ?? EMPTY),
      });
      return;
    }

    const fixture = FIXTURES.find(([key]) => url.includes(key));
    const body = fixture ? fixture[1](url) : EMPTY;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body ?? EMPTY),
    });
  });
}

/**
 * Seed the admin token in localStorage so AdminPage's useEffect skips the
 * /admin/login redirect on first render. Must be called before navigating
 * to /admin.
 */
export async function seedAdminSession(page: Page) {
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem('admin_token', 'e2e.admin.jwt');
    } catch {}
  });
}
