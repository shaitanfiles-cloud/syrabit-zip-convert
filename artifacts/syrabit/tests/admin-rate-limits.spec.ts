/**
 * Admin Rate Limits specs.
 *
 * 1. Rate limit configuration page renders per-tier limits.
 * 2. Editing a tier policy and clicking save fires the rate-limit save endpoint.
 */
import { test, expect, type Page, type Route } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const RATE_POLICIES = {
  free:       { req_per_min: 5,  credits_per_day: 30,   max_tokens: 10000,  req_per_min_ip: 20 },
  starter:    { req_per_min: 10, credits_per_day: 500,  max_tokens: 15000,  req_per_min_ip: 30 },
  pro:        { req_per_min: 15, credits_per_day: 4000, max_tokens: 20000,  req_per_min_ip: 40 },
  enterprise: { req_per_min: 60, credits_per_day: 99999, max_tokens: 200000, req_per_min_ip: 200 },
};

async function openRateLimitsPanel(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-ratelimits').click();
}

test.describe('Admin Rate Limits', () => {
  test('rate limit configuration page renders per-tier limits', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page);
    await page.route('**/api/admin/rate-policies**', async (route: Route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RATE_POLICIES) });
    });

    await openRateLimitsPanel(page);

    await expect(page.getByText(/Free/i).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Starter/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Pro/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Enterprise/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Req\/min|Credits\/day|Max tokens/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test('editing a tier and clicking save fires the rate-limit save endpoint', async ({ page }) => {
    await seedAdminSession(page);
    await installAdminApiMocks(page);

    const saveCalls: Array<{ url: string; method: string; body: unknown }> = [];
    await page.route('**/api/admin/rate-policies**', async (route: Route) => {
      const req = route.request();
      const method = req.method();
      if (method === 'PUT' || method === 'PATCH' || method === 'POST') {
        let body: unknown = null;
        try { body = req.postDataJSON(); } catch { body = req.postData(); }
        saveCalls.push({ url: req.url(), method, body });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RATE_POLICIES) });
    });
    await page.route('**/api/admin/rate-limits**', async (route: Route) => {
      const req = route.request();
      const method = req.method();
      let body: unknown = null;
      try { body = req.postDataJSON(); } catch { body = req.postData(); }
      saveCalls.push({ url: req.url(), method, body });
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
    });

    await openRateLimitsPanel(page);
    await expect(page.getByText(/Free/i).first()).toBeVisible({ timeout: 10_000 });

    // Click the edit button for a tier to enter edit mode.
    const editBtn = page.getByRole('button', { name: /edit|configure|pencil/i }).first();
    await expect(editBtn).toBeVisible({ timeout: 8_000 });
    await editBtn.click();

    // Update a numeric input for the tier.
    const numericInput = page.getByRole('spinbutton').first();
    await expect(numericInput).toBeVisible({ timeout: 5_000 });
    await numericInput.fill('6');

    // Click the save button to persist changes.
    const saveBtn = page.getByRole('button', { name: /save|apply|update|confirm/i }).first();
    await expect(saveBtn).toBeVisible({ timeout: 5_000 });
    await saveBtn.click();

    await expect.poll(() => saveCalls.length, { timeout: 8_000 }).toBeGreaterThan(0);
    await expect(page.getByText(/Free|Starter|saved|success/i).first()).toBeVisible({ timeout: 5_000 });
  });
});
