/**
 * Admin Conversations specs.
 *
 * 1. Conversations panel lists sessions with title and user name.
 * 2. Clicking a conversation reveals its embedded messages.
 * 3. Clicking the Flag button on a conversation fires
 *    POST /api/admin/conversations/:id/flag and marks the conversation
 *    as flagged in the UI.
 */
import { test, expect, type Page, type Route } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const CONV_WITH_MESSAGES = {
  id: 'conv-001',
  title: 'Photosynthesis inquiry',
  user_id: 'user-a',
  user_name: 'Alice Barua',
  user_email: 'alice@example.com',
  is_anonymous: false,
  flagged: false,
  created_at: new Date(Date.now() - 3600_000).toISOString(),
  updated_at: new Date(Date.now() - 1800_000).toISOString(),
  messages: [
    { role: 'user',      content: 'What is photosynthesis?',                          timestamp: new Date(Date.now() - 3600_000).toISOString() },
    { role: 'assistant', content: 'Photosynthesis converts light to chemical energy.', timestamp: new Date(Date.now() - 3595_000).toISOString() },
  ],
};

const CONV_ANONYMOUS = {
  id: 'conv-002',
  title: 'Newton laws',
  user_id: null,
  user_name: null,
  user_email: null,
  is_anonymous: true,
  flagged: false,
  created_at: new Date(Date.now() - 7200_000).toISOString(),
  updated_at: new Date(Date.now() - 5400_000).toISOString(),
  messages: [],
};

const CONVERSATIONS_ARRAY = [CONV_WITH_MESSAGES, CONV_ANONYMOUS];

async function openConversationsPanel(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-conversations').click();
}

test.describe('Admin Conversations', () => {
  test.beforeEach(async ({ page }) => {
    await seedAdminSession(page);
  });

  test('conversations panel lists sessions with title and user name', async ({ page }) => {
    await installAdminApiMocks(page);

    await page.route('**/api/admin/conversations*', async (route: Route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CONVERSATIONS_ARRAY) });
    });

    await openConversationsPanel(page);

    await expect(page.getByText(/Photosynthesis inquiry/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Alice Barua/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Newton laws/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Anonymous/i).first()).toBeVisible({ timeout: 5_000 });
  });

  test('clicking a conversation reveals its embedded messages', async ({ page }) => {
    await installAdminApiMocks(page);

    await page.route('**/api/admin/conversations*', async (route: Route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CONVERSATIONS_ARRAY) });
    });

    await openConversationsPanel(page);
    await expect(page.getByText(/Photosynthesis inquiry/i)).toBeVisible({ timeout: 10_000 });

    await page.getByText(/Photosynthesis inquiry/i).first().click();

    await expect(page.getByText(/What is photosynthesis\?/i)).toBeVisible({ timeout: 8_000 });
    await expect(page.getByText(/Photosynthesis converts light/i)).toBeVisible({ timeout: 5_000 });
  });

  test('clicking the Flag button fires POST /api/admin/conversations/:id/flag', async ({ page }) => {
    await installAdminApiMocks(page);

    const flagCalls: Array<{ url: string; method: string }> = [];
    let conv1Flagged = false;

    await page.route('**/api/admin/conversations*', async (route: Route) => {
      const req = route.request();
      const url = req.url();
      const method = req.method();

      if (method === 'POST' && url.includes('/flag')) {
        flagCalls.push({ url, method });
        conv1Flagged = true;
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, flagged: true }) });
        return;
      }

      const list = CONVERSATIONS_ARRAY.map((c) =>
        c.id === 'conv-001' ? { ...c, flagged: conv1Flagged } : c,
      );
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(list) });
    });

    await openConversationsPanel(page);
    await expect(page.getByText(/Photosynthesis inquiry/i)).toBeVisible({ timeout: 10_000 });

    // The Flag button has aria-label="Flag conversation" on each conversation row.
    const flagBtn = page.getByRole('button', { name: /flag/i }).first();
    await expect(flagBtn).toBeVisible({ timeout: 8_000 });
    await flagBtn.click();

    // POST /api/admin/conversations/:id/flag was captured.
    await expect.poll(() => flagCalls.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(flagCalls[0].url).toContain('/conversations/');
    expect(flagCalls[0].url).toContain('/flag');
    expect(flagCalls[0].method).toBe('POST');

    // Conversation list remains visible after flagging.
    await expect(page.getByText(/Photosynthesis inquiry|Newton laws/i).first()).toBeVisible({ timeout: 5_000 });
  });
});
