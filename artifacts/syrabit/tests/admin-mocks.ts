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
  ['/api/health', () => ({ status: 'ok', dependencies: {} })],
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
  ['/api/admin/cf/overview', () => ({})],
  ['/api/seo/pipeline/status', () => ({
    total_topics: 0, published: 0, has_content: 0,
    needs_schema: 0, needs_internal_links: 0,
    pages_total: 0, published_today: 0,
  })],
  ['/api/seo/health', () => ({ sitemaps: [] })],
];

interface InstallOptions {
  /**
   * URL substrings to force-fail with a 500 status. Used to assert that
   * the dashboard degrades gracefully (inline "failed to load" card)
   * instead of falling through to the global ErrorBoundary.
   */
  failPatterns?: string[];
}

export async function installAdminApiMocks(page: Page, opts: InstallOptions = {}) {
  const failPatterns = opts.failPatterns ?? [];

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
