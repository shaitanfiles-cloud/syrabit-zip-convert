/**
 * Admin Users & Plans specs (Task #1 — 75 missing tests).
 *
 * 1. User list renders with email, plan type, and credit balance.
 * 2. Admin adjusts a user's credits via the Credits Management modal
 *    (CreditCard button → amount input → "Add Credits") → PATCH /api/admin/users/:id/credits.
 * 3. Admin changes a user's plan via the plan-badge DropdownMenu
 *    (Crown+"starter" button → "free" menuitem) → PATCH /api/admin/users/:id/plan.
 * 4. Plan config save uses the Edit2 toggle + "Save" button on a PlanCard
 *    → PUT /api/admin/plan-config.
 */
import { test, expect, type Page, type Route } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

interface AdminCall { url: string; method: string; body: unknown; }

const USER_LIST = {
  users: [
    { id: 'user-001', email: 'alice@example.com', name: 'Alice', plan: 'starter', credits_used: 45, credits_limit: 1500 },
    { id: 'user-002', email: 'bob@example.com', name: 'Bob', plan: 'free', credits_used: 8, credits_limit: 30 },
  ],
  total: 2, page: 1, per_page: 20,
};

// AdminPlans.jsx spreads the config object into its planConfig state,
// so we return the { free, starter, pro } shape it expects.
const PLAN_CONFIG = {
  free:    { price: 0,   credits: 30,   validity: 'daily reset' },
  starter: { price: 99,  credits: 500,  validity: 'daily reset' },
  pro:     { price: 999, credits: 4000, validity: 'daily reset' },
};

async function openUsersPanel(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-users').click();
}

async function openPlansPanel(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-plans').click();
}

test.describe('Admin Users & Plans', () => {
  test.beforeEach(async ({ page }) => {
    await seedAdminSession(page);
  });

  test('user list renders with email, plan type, and credit balance', async ({ page }) => {
    await installAdminApiMocks(page);

    await page.route('**/api/admin/users*', async (route: Route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(USER_LIST) });
    });

    await openUsersPanel(page);

    await expect(page.getByText(/alice@example\.com/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/starter/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/45|1500|credits/i).first()).toBeVisible({ timeout: 5_000 });
  });

  test('admin adjusts credits via Credits Management modal → PATCH /api/admin/users/:id/credits', async ({ page }) => {
    await installAdminApiMocks(page);

    const creditPatches: AdminCall[] = [];
    await page.route('**/api/admin/users*', async (route: Route) => {
      const req = route.request();
      const url = req.url();
      const method = req.method();
      let body: unknown = null;
      try { body = req.postDataJSON(); } catch { body = req.postData(); }

      if (url.includes('/credits') && method === 'PATCH') {
        creditPatches.push({ url, method, body });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(USER_LIST) });
    });

    await openUsersPanel(page);
    await expect(page.getByText(/alice@example\.com/i)).toBeVisible({ timeout: 10_000 });

    // The CreditCard button shows "{credits_used} / {credits_limit}" and has title="Manage credits".
    const creditBtn = page.getByTitle('Manage credits').first();
    await expect(creditBtn).toBeVisible({ timeout: 8_000 });
    await creditBtn.click();

    // Credits Management modal opens. Default mode is 'add'. Fill the amount.
    const creditInput = page.getByRole('spinbutton').first();
    await expect(creditInput).toBeVisible({ timeout: 5_000 });
    await creditInput.fill('500');

    // Click "Add Credits" — the save button label is "Add Credits" in 'add' mode.
    const addBtn = page.getByRole('button', { name: /Add Credits/i }).first();
    await expect(addBtn).toBeVisible({ timeout: 5_000 });
    await addBtn.click();

    await expect.poll(() => creditPatches.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(creditPatches[0].url).toContain('/credits');
  });

  test('admin changes user plan via plan-badge dropdown → PATCH /api/admin/users/:id/plan', async ({ page }) => {
    await installAdminApiMocks(page);

    const planPatches: AdminCall[] = [];
    await page.route('**/api/admin/users*', async (route: Route) => {
      const req = route.request();
      const url = req.url();
      const method = req.method();
      let body: unknown = null;
      try { body = req.postDataJSON(); } catch { body = req.postData(); }

      if (url.includes('/plan') && method === 'PATCH') {
        planPatches.push({ url, method, body });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(USER_LIST) });
    });

    await openUsersPanel(page);
    await expect(page.getByText(/alice@example\.com/i)).toBeVisible({ timeout: 10_000 });

    // The plan badge button shows Crown icon + plan name (e.g., "starter").
    // Clicking it opens a DropdownMenu with plan options.
    const planBadgeBtn = page.getByRole('button', { name: /starter/i }).first();
    await expect(planBadgeBtn).toBeVisible({ timeout: 8_000 });
    await planBadgeBtn.click();

    // DropdownMenuItem uses role="menuitem" internally in shadcn.
    const freeItem = page.getByRole('menuitem', { name: /^free$/i }).first();
    await expect(freeItem).toBeVisible({ timeout: 5_000 });
    await freeItem.click();

    // handlePlanChange fires immediately — no additional confirm button.
    await expect.poll(() => planPatches.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(planPatches[0].url).toContain('/plan');
    expect(JSON.stringify(planPatches[0].body)).toMatch(/free/);
  });

  test('plan config save via Edit2 → input → Save button fires PUT /api/admin/plan-config', async ({ page }) => {
    await installAdminApiMocks(page);

    const planConfigSaves: AdminCall[] = [];

    // GET returns proper { free, starter, pro } shape; PUT is intercepted.
    await page.route('**/api/admin/plan-config*', async (route: Route) => {
      const req = route.request();
      const method = req.method();
      let body: unknown = null;
      try { body = req.postDataJSON(); } catch { body = req.postData(); }

      if (method === 'PUT' || method === 'PATCH' || method === 'POST') {
        planConfigSaves.push({ url: req.url(), method, body });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }
      // GET
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PLAN_CONFIG) });
    });

    await openPlansPanel(page);
    await expect(page.getByText(/Plans & Credits/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Free|Starter|Pro/i).first()).toBeVisible({ timeout: 8_000 });

    // Each PlanCard has an Edit2 toggle button (icon-only, no aria-label).
    // AdminQuickLinks renders below the cards, so the first button on the page
    // is the Edit2 pencil on the first PlanCard.
    const editBtn = page.getByRole('button').first();
    await expect(editBtn).toBeVisible({ timeout: 8_000 });
    await editBtn.click();

    // Editing mode reveals numeric inputs for price, credits, validity.
    const priceInput = page.getByRole('spinbutton').first();
    await expect(priceInput).toBeVisible({ timeout: 5_000 });
    await priceInput.fill('5');

    // "Save" button appears when a PlanCard is in editing mode.
    const saveBtn = page.getByRole('button', { name: /^save$/i }).first();
    await expect(saveBtn).toBeVisible({ timeout: 5_000 });
    await saveBtn.click();

    // PUT /api/admin/plan-config was called by adminUpdatePlanConfig.
    await expect.poll(() => planConfigSaves.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(planConfigSaves[0].url).toContain('/plan-config');
    expect(planConfigSaves[0].method).toBe('PUT');
  });
});
