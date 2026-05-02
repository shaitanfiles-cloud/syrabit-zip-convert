/**
 * AdminHealth cron-pill e2e coverage (Task #894).
 *
 * Task #882 already unit-tests <EdgeProxyDeployCronPill> in isolation
 * (EdgeProxyDeployCronPill.test.jsx) and the backing
 * /admin/health/edge-proxy-deploy/cron route on the Python side
 * (tests/test_admin_health_edge_proxy_deploy_cron_route.py). What was
 * missing — and what this suite adds — is a Playwright check that the
 * pill actually shows up *inside* AdminHealth: the JSX wires it under a
 * <SectionErrorBoundary>, the polling useEffect fires the GET, and the
 * `<prefix>-{tile,status,pill,run-link,refresh}` testIds documented in
 * the AdminHealth cron-pill testId convention block (replit.md) all
 * land in the rendered DOM with the colour the mocked status implies.
 *
 * The cf-waf-drift and Trustpilot refresh-cron pills had the same gap
 * — both were unit-tested but had no e2e — so this suite covers all
 * three siblings at once. A future refactor that drops one of the
 * pills from the JSX, breaks the loader useCallback dependency array,
 * or accidentally renames a testId now fails here instead of slipping
 * to production until the next CI failure / silent cron.
 */
import { test, expect, type Page } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const EDGE_PROXY_PREFIX = 'edge-proxy-deploy-cron';
const CF_WAF_DRIFT_PREFIX = 'cf-waf-drift-cron';
const TRUSTPILOT_PREFIX = 'trustpilot-refresh-cron';
const UNIFIED_LOGS_CF_PULL_PREFIX = 'unified-logs-cf-pull-cron';

const EDGE_PROXY_ENDPOINT = '/api/admin/health/edge-proxy-deploy/cron';
const CF_WAF_DRIFT_ENDPOINT = '/api/admin/health/cf-waf-drift/cron';
const TRUSTPILOT_ENDPOINT = '/api/admin/health/trustpilot/refresh-cron';
const UNIFIED_LOGS_CF_PULL_ENDPOINT = '/api/admin/health/unified-logs/cf-pull/cron';

const baseEdgeProxyHealthy = {
  configured: true,
  status: 'healthy',
  conclusion: 'success',
  html_url: 'https://github.com/syrabit/syrabit/actions/runs/777',
  lastRunUrl: 'https://github.com/syrabit/syrabit/actions/runs/777',
  updated_at: '2026-04-25T10:00:00Z',
  ageSeconds: 3600,
  runStatus: 'completed',
  workflowUrl:
    'https://github.com/syrabit/syrabit/actions/workflows/edge-proxy-deploy.yml',
  staleThresholdSeconds: 7 * 86400,
  error: null,
};

const baseCfWafDriftHealthy = {
  configured: true,
  status: 'healthy',
  lastHeartbeatAgeSeconds: 1800,
  lastSuccessHeartbeatAgeSeconds: 1800,
  lastRunUrl: 'https://github.com/syrabit/syrabit/actions/runs/555',
  workflowUrl:
    'https://github.com/syrabit/syrabit/actions/workflows/cf-waf-drift-daily.yml',
  staleThresholdSeconds: 36 * 3600,
  error: null,
};

const baseTrustpilotHealthy = {
  configured: true,
  status: 'healthy',
  lastHeartbeatAgeSeconds: 1800,
  lastSuccessHeartbeatAgeSeconds: 1800,
  workflowUrl:
    'https://github.com/syrabit/syrabit/actions/workflows/trustpilot-aggregate-refresh.yml',
  staleThresholdSeconds: 36 * 3600,
  error: null,
};

// Task #956 — fixture matching the
// /admin/health/unified-logs/cf-pull/cron response shape (no
// GitHub workflow URL — the data source is a backend cron loop
// polling Mongo, so the pill links to the JSON status snapshot
// at ``statusUrl`` instead).
const baseUnifiedLogsCfPullHealthy = {
  configured: true,
  status: 'healthy',
  lastUpdatedTs: 1_700_000_000,
  lastUpdatedAt: '2026-04-26T05:00:00Z',
  lastUpdatedAgeSeconds: 1800,
  leaseOwner: 'replica-A',
  leaseExpiresAt: '2026-04-26T05:30:00Z',
  cursor: 'cursor-xyz',
  silentThresholdSeconds: 900,
  statusUrl: '/api/admin/logs/status',
};

/**
 * Open AdminHealth as an authenticated admin. AdminPage defaults to
 * the Dashboard tab — click the "Health / Uptime" sidebar entry to
 * mount AdminHealth (lazy-loaded), which is what triggers the
 * cron-pill polling useEffect we want to assert ran.
 */
async function openAdminHealth(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible();
  await page.getByTestId('admin-nav-health').click();
}

/**
 * Cross-check every testId the AdminHealth cron-pill testId convention
 * (replit.md § "AdminHealth cron-pill testId convention") promises:
 * `<prefix>-{tile,status,pill,run-link,refresh}`. Visibility is
 * asserted on the tile so we know SectionErrorBoundary did NOT swap
 * the pill for an inline failure card.
 */
async function expectConventionTestIdsPresent(page: Page, prefix: string) {
  const tile = page.getByTestId(`${prefix}-tile`);
  await expect(tile).toBeVisible();
  await expect(tile.getByTestId(`${prefix}-status`)).toBeVisible();
  await expect(tile.getByTestId(`${prefix}-pill`)).toBeVisible();
  await expect(tile.getByTestId(`${prefix}-run-link`)).toBeVisible();
  await expect(tile.getByTestId(`${prefix}-refresh`)).toBeVisible();
  return tile;
}

test.describe('AdminHealth cron pills', () => {
  test('edge-proxy-deploy pill renders the healthy state with all convention testIds', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [EDGE_PROXY_ENDPOINT]: () => baseEdgeProxyHealthy,
      },
    });

    // Asserting the GET fires confirms the loader useCallback +
    // polling useEffect dependency array still wires up correctly.
    const edgeRequest = page.waitForRequest(
      (req) => req.url().includes(EDGE_PROXY_ENDPOINT),
      { timeout: 30_000 },
    );

    await openAdminHealth(page);
    await edgeRequest;

    const tile = await expectConventionTestIdsPresent(page, EDGE_PROXY_PREFIX);

    // Healthy → green container + green pill, with the
    // edge-proxy-specific copy from EdgeProxyDeployCronPill.
    await expect(tile).toHaveClass(/bg-emerald-50/);
    await expect(tile).toHaveClass(/border-emerald-200/);

    const status = tile.getByTestId(`${EDGE_PROXY_PREFIX}-status`);
    await expect(status).toContainText('Edge-proxy deploy CI — passing');
    await expect(status).toHaveClass(/text-emerald-600/);

    const pill = tile.getByTestId(`${EDGE_PROXY_PREFIX}-pill`);
    await expect(pill).toContainText('CI HEALTHY');
    await expect(pill).toHaveClass(/bg-emerald-100/);

    // The optional "Last run" deep-link only renders when the
    // payload carries a run URL — baseEdgeProxyHealthy has one, so
    // it must be visible alongside the convention testIds.
    await expect(tile.getByTestId(`${EDGE_PROXY_PREFIX}-last-run-link`)).toHaveAttribute(
      'href',
      baseEdgeProxyHealthy.html_url,
    );
  });

  test('edge-proxy-deploy pill turns red when the cron reports a failure', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [EDGE_PROXY_ENDPOINT]: () => ({
          ...baseEdgeProxyHealthy,
          status: 'silent',
          conclusion: 'failure',
          ageSeconds: 600,
        }),
      },
    });

    await openAdminHealth(page);

    const tile = await expectConventionTestIdsPresent(page, EDGE_PROXY_PREFIX);

    await expect(tile).toHaveClass(/bg-red-50/);
    await expect(tile).toHaveClass(/border-red-200/);

    const status = tile.getByTestId(`${EDGE_PROXY_PREFIX}-status`);
    await expect(status).toContainText('Edge-proxy deploy CI — last run failed');
    await expect(status).toHaveClass(/text-red-600/);

    const pill = tile.getByTestId(`${EDGE_PROXY_PREFIX}-pill`);
    await expect(pill).toContainText('CI FAILED');
    await expect(pill).toHaveClass(/bg-red-100/);
  });

  test('cf-waf-drift pill renders the healthy state with all convention testIds', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [CF_WAF_DRIFT_ENDPOINT]: () => baseCfWafDriftHealthy,
      },
    });

    const cfRequest = page.waitForRequest(
      (req) => req.url().includes(CF_WAF_DRIFT_ENDPOINT),
      { timeout: 30_000 },
    );
    await openAdminHealth(page);
    await cfRequest;

    const tile = await expectConventionTestIdsPresent(page, CF_WAF_DRIFT_PREFIX);

    await expect(tile).toHaveClass(/bg-emerald-50/);
    await expect(tile.getByTestId(`${CF_WAF_DRIFT_PREFIX}-status`)).toHaveClass(/text-emerald-600/);
    await expect(tile.getByTestId(`${CF_WAF_DRIFT_PREFIX}-pill`)).toHaveClass(/bg-emerald-100/);
  });

  test('cf-waf-drift pill turns red when the heartbeat is silent', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [CF_WAF_DRIFT_ENDPOINT]: () => ({
          ...baseCfWafDriftHealthy,
          status: 'silent',
          lastHeartbeatAgeSeconds: 200000,
          lastSuccessHeartbeatAgeSeconds: 200000,
        }),
      },
    });

    await openAdminHealth(page);

    const tile = await expectConventionTestIdsPresent(page, CF_WAF_DRIFT_PREFIX);

    await expect(tile).toHaveClass(/bg-red-50/);
    await expect(tile.getByTestId(`${CF_WAF_DRIFT_PREFIX}-status`)).toHaveClass(/text-red-600/);
    await expect(tile.getByTestId(`${CF_WAF_DRIFT_PREFIX}-pill`)).toHaveClass(/bg-red-100/);
  });

  test('trustpilot-refresh-cron pill renders the healthy state with all convention testIds', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [TRUSTPILOT_ENDPOINT]: () => baseTrustpilotHealthy,
      },
    });

    const tpRequest = page.waitForRequest(
      (req) => req.url().includes(TRUSTPILOT_ENDPOINT),
      { timeout: 30_000 },
    );
    await openAdminHealth(page);
    await tpRequest;

    const tile = await expectConventionTestIdsPresent(page, TRUSTPILOT_PREFIX);

    await expect(tile).toHaveClass(/bg-emerald-50/);

    const status = tile.getByTestId(`${TRUSTPILOT_PREFIX}-status`);
    await expect(status).toContainText('Trustpilot refresh cron — checking in');
    await expect(status).toHaveClass(/text-emerald-600/);
    await expect(tile.getByTestId(`${TRUSTPILOT_PREFIX}-pill`)).toHaveClass(/bg-emerald-100/);
  });

  test('trustpilot-refresh-cron pill turns amber when the last run is degraded', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [TRUSTPILOT_ENDPOINT]: () => ({
          ...baseTrustpilotHealthy,
          status: 'degraded',
          lastHeartbeatAgeSeconds: 200000,
          lastSuccessHeartbeatAgeSeconds: 500000,
        }),
      },
    });

    await openAdminHealth(page);

    const tile = await expectConventionTestIdsPresent(page, TRUSTPILOT_PREFIX);

    await expect(tile).toHaveClass(/bg-amber-50/);
    await expect(tile.getByTestId(`${TRUSTPILOT_PREFIX}-status`)).toHaveClass(/text-amber-600/);
    await expect(tile.getByTestId(`${TRUSTPILOT_PREFIX}-pill`)).toHaveClass(/bg-amber-100/);
  });

  test('unified-logs-cf-pull pill renders the healthy state with all convention testIds', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [UNIFIED_LOGS_CF_PULL_ENDPOINT]: () => baseUnifiedLogsCfPullHealthy,
      },
    });

    // Asserting the GET fires confirms the loader useCallback +
    // polling useEffect dependency array still wires up correctly
    // for the Task #956 pill (the same regression mode the sibling
    // pills already guard against).
    const cfPullRequest = page.waitForRequest(
      (req) => req.url().includes(UNIFIED_LOGS_CF_PULL_ENDPOINT),
      { timeout: 30_000 },
    );
    await openAdminHealth(page);
    await cfPullRequest;

    const tile = await expectConventionTestIdsPresent(page, UNIFIED_LOGS_CF_PULL_PREFIX);

    // Healthy → green container + green pill, with the
    // unified-logs-specific copy from UnifiedLogsCfPullCronPill.
    await expect(tile).toHaveClass(/bg-emerald-50/);
    await expect(tile).toHaveClass(/border-emerald-200/);

    const status = tile.getByTestId(`${UNIFIED_LOGS_CF_PULL_PREFIX}-status`);
    await expect(status).toContainText('Cloudflare log ingest — flowing');
    await expect(status).toHaveClass(/text-emerald-600/);

    const pill = tile.getByTestId(`${UNIFIED_LOGS_CF_PULL_PREFIX}-pill`);
    await expect(pill).toContainText('INGEST HEALTHY');
    await expect(pill).toHaveClass(/bg-emerald-100/);

    // The optional Status JSON deep-link points at the backend
    // statusUrl (no GitHub Actions workflow exists for this cron).
    await expect(tile.getByTestId(`${UNIFIED_LOGS_CF_PULL_PREFIX}-status-link`)).toHaveAttribute(
      'href',
      baseUnifiedLogsCfPullHealthy.statusUrl,
    );
  });

  test('unified-logs-cf-pull pill turns red when ingest goes silent', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page, {
      overrides: {
        [UNIFIED_LOGS_CF_PULL_ENDPOINT]: () => ({
          ...baseUnifiedLogsCfPullHealthy,
          status: 'silent',
          lastUpdatedAgeSeconds: 200000,
          leaseOwner: 'replica-zombie',
        }),
      },
    });

    await openAdminHealth(page);

    const tile = await expectConventionTestIdsPresent(page, UNIFIED_LOGS_CF_PULL_PREFIX);

    await expect(tile).toHaveClass(/bg-red-50/);
    await expect(tile).toHaveClass(/border-red-200/);

    const status = tile.getByTestId(`${UNIFIED_LOGS_CF_PULL_PREFIX}-status`);
    await expect(status).toContainText('Cloudflare log ingest — silent');
    await expect(status).toHaveClass(/text-red-600/);

    const pill = tile.getByTestId(`${UNIFIED_LOGS_CF_PULL_PREFIX}-pill`);
    await expect(pill).toContainText('INGEST SILENT');
    await expect(pill).toHaveClass(/bg-red-100/);
  });
});
