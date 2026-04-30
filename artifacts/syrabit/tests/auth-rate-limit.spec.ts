/**
 * Rate limiting & auth middleware specs (Task #1 — 75 missing tests).
 *
 * 1. Per-IP rate limit returns 429 with retry-after reflected in UI.
 * 2. Invalid JWT triggers re-login toast or redirect.
 * 3. Admin-only route returns 403 for a non-admin user and redirects away from /admin.
 * 4. Missing Turnstile token for anonymous request returns 403 reflected in UI.
 * 5. Expired JWT triggers the refresh flow and resumes the session.
 */
import { test, expect, type Page, type Route } from '@playwright/test';

async function installAuthMocks(
  page: Page,
  opts: {
    scenario: 'rate-limited' | 'invalid-jwt' | 'admin-forbidden' | 'no-turnstile' | 'expired-jwt';
  },
) {
  const { scenario } = opts;

  await page.addInitScript(() => {
    try { window.sessionStorage.setItem('syrabit_token', 'e2e.user.jwt'); } catch {}
  });

  await page.route('**/api/**', async (route: Route) => {
    const req = route.request();
    const url = req.url();
    const method = req.method();

    if (method === 'OPTIONS') { await route.fulfill({ status: 204, body: '' }); return; }

    if (scenario === 'admin-forbidden' && (url.includes('/auth/me') || url.includes('/auth/user'))) {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ id: 'user-nonadmin', email: 'user@syrabit.ai', name: 'Regular User', is_admin: false, role: 'student' }),
      });
      return;
    }

    if (scenario === 'rate-limited' && (url.includes('/api/ai/chat') || url.includes('/api/edu'))) {
      await route.fulfill({
        status: 429, contentType: 'application/json',
        body: JSON.stringify({ detail: 'rate_limit_exceeded', retry_after: 60 }),
        headers: { 'Retry-After': '60', 'X-RateLimit-Limit': '10', 'X-RateLimit-Remaining': '0' },
      });
      return;
    }

    if (scenario === 'invalid-jwt' && url.includes('/auth/me')) {
      await route.fulfill({
        status: 401, contentType: 'application/json',
        body: JSON.stringify({ detail: 'invalid_jwt', message: 'Token is invalid or malformed' }),
      });
      return;
    }

    if (scenario === 'admin-forbidden' && url.includes('/api/admin')) {
      await route.fulfill({
        status: 403, contentType: 'application/json',
        body: JSON.stringify({ detail: 'forbidden', message: 'Admin access required' }),
      });
      return;
    }

    if (scenario === 'no-turnstile' && (url.includes('/api/ai/chat') || url.includes('/api/edu'))) {
      await route.fulfill({
        status: 403, contentType: 'application/json',
        body: JSON.stringify({ detail: 'turnstile_required', message: 'Turnstile verification required' }),
      });
      return;
    }

    if (scenario === 'expired-jwt') {
      if (url.includes('/auth/me')) {
        await route.fulfill({
          status: 401, contentType: 'application/json',
          body: JSON.stringify({ detail: 'token_expired', message: 'JWT has expired' }),
        });
        return;
      }
      if (url.includes('/auth/refresh')) {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ access_token: 'new.refreshed.jwt', token_type: 'bearer' }),
        });
        return;
      }
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

test.describe('Rate limiting & auth middleware', () => {
  test('per-IP rate limit returns 429 and the UI reflects retry-after', async ({ page }) => {
    await installAuthMocks(page, { scenario: 'rate-limited' });
    await page.goto('/chat');

    const input = page.getByRole('textbox').first();
    await expect(input).toBeVisible({ timeout: 10_000 });
    await input.fill('Test rate limited request');
    await page.keyboard.press('Enter');

    await expect(
      page.getByText(/rate limit|too many|retry|slow down|limit exceeded/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('invalid JWT triggers re-login toast or redirect', async ({ page }) => {
    await installAuthMocks(page, { scenario: 'invalid-jwt' });
    await page.goto('/chat');

    await expect(
      page.getByText(/login|sign in|session|invalid|expired/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('admin-only route returns 403 for a non-admin user and redirects away from /admin', async ({ page }) => {
    await installAuthMocks(page, { scenario: 'admin-forbidden' });
    await page.goto('/admin');

    // App must redirect a non-admin away from /admin or show a forbidden/login screen.
    await expect(async () => {
      const url = page.url();
      const hasRedirected = /login|signin|\/$/i.test(url) && !url.includes('/admin');
      const hasForbiddenText = await page.getByText(/forbidden|login|access|unauthorized|not allowed/i).first().isVisible();
      expect(hasRedirected || hasForbiddenText).toBe(true);
    }).toPass({ timeout: 10_000 });
  });

  test('missing Turnstile token for anonymous request returns 403 reflected in UI', async ({ page }) => {
    await installAuthMocks(page, { scenario: 'no-turnstile' });
    await page.goto('/chat');

    const input = page.getByRole('textbox').first();
    await expect(input).toBeVisible({ timeout: 10_000 });
    await input.fill('Test without turnstile');
    await page.keyboard.press('Enter');

    await expect(
      page.getByText(/verify|turnstile|captcha|forbidden|error/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('expired JWT triggers the refresh flow and resumes the session', async ({ page }) => {
    const refreshRequestPromise = page.waitForRequest(
      (req) => req.url().includes('/auth/refresh'),
      { timeout: 15_000 },
    );

    await installAuthMocks(page, { scenario: 'expired-jwt' });
    await page.goto('/chat');

    const refreshRequest = await refreshRequestPromise;
    expect(refreshRequest.url()).toContain('/auth/refresh');

    await expect(page.getByRole('textbox').first()).toBeVisible({ timeout: 10_000 });
  });
});
