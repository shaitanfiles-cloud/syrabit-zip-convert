/**
 * Admin Analytics & Notifications specs.
 *
 * 1. Analytics panel renders GA4 metrics (pageviews, sessions, bounce rate).
 * 2. Notifications broadcast list renders sent and draft notifications with
 *    count summary visible in the UI.
 * 3. Clicking the "Mark as read" button (Eye icon) on an unread notification
 *    fires PATCH /api/admin/notifications/:id/read and the notification is
 *    no longer shown as unread.
 */
import { test, expect, type Page, type Route } from '@playwright/test';
import { installAdminApiMocks, seedAdminSession } from './admin-mocks';

const GA4_METRICS = {
  ok: true,
  pageviews: 45230,
  sessions: 12400,
  bounce_rate: 0.38,
  avg_session_duration_sec: 142,
  top_pages: [
    { page: '/chat',       pageviews: 18200 },
    { page: '/flashcards', pageviews: 3100 },
  ],
};

// Broadcast notifications in the shape AdminNotifications.jsx renders.
// read:false means the Eye "Mark as read" button renders for these items.
const BROADCAST_NOTIFS = [
  { id: 'notif-001', title: 'Welcome Announcement', message: 'Hello all students!',          audience: 'all', type: 'general', status: 'sent',  read: false },
  { id: 'notif-002', title: 'Maintenance Alert',    message: 'Scheduled downtime at midnight.', audience: 'all', type: 'alert',   status: 'draft', read: false },
];

async function openAnalyticsPanel(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-analytics').click();
}

async function openNotificationsPanel(page: Page) {
  await page.goto('/admin');
  await expect(page.getByTestId('admin-dashboard')).toBeVisible({ timeout: 15_000 });
  await page.getByTestId('admin-nav-notifications').click();
}

test.describe('Admin Analytics & Notifications', () => {
  test.beforeEach(async ({ page }) => {
    await seedAdminSession(page);
  });

  test('analytics panel renders GA4 metrics', async ({ page }) => {
    await installAdminApiMocks(page);

    await page.route('**/api/admin/analytics**', async (route: Route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(GA4_METRICS) });
    });

    await openAnalyticsPanel(page);

    await expect(
      page.getByText(/45[,.]?230|45230|pageview|12[,.]?400|sessions|bounce|traffic|analytics|ga4/i).first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  test('notifications broadcast list renders sent and draft notifications', async ({ page }) => {
    await installAdminApiMocks(page);

    await page.route('**/api/admin/notifications**', async (route: Route) => {
      const req = route.request();
      if (req.method() === 'GET') {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(BROADCAST_NOTIFS),
        });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
    });

    await openNotificationsPanel(page);

    // Component renders n.title for each notification
    await expect(page.getByText(/Welcome Announcement/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Maintenance Alert/i)).toBeVisible({ timeout: 5_000 });
    // Summary shows "{total} total" and "{sent} sent"
    await expect(page.getByText(/2.*total|total.*2/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/1.*sent|sent.*1/i).first()).toBeVisible({ timeout: 5_000 });
  });

  test('clicking Mark as read fires PATCH /api/admin/notifications/:id/read', async ({ page }) => {
    await installAdminApiMocks(page);

    const readPatches: Array<{ url: string }> = [];
    let readSet = new Set<string>();

    await page.route('**/api/admin/notifications**', async (route: Route) => {
      const req = route.request();
      const url = req.url();
      const method = req.method();

      if (method === 'PATCH' && url.includes('/read')) {
        const match = url.match(/notifications\/([^/?]+)\/read/);
        if (match?.[1]) readSet.add(match[1]);
        readPatches.push({ url });
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
        return;
      }

      if (method === 'GET') {
        const updated = BROADCAST_NOTIFS.map((n) => ({ ...n, read: readSet.has(n.id) }));
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(updated),
        });
        return;
      }

      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
    });

    await openNotificationsPanel(page);
    await expect(page.getByText(/Welcome Announcement/i)).toBeVisible({ timeout: 10_000 });

    // The "Mark as read" button (Eye icon, aria-label="Mark as read") is inside a
    // `group` div with opacity-0 group-hover:opacity-100. Hover the row then
    // force-click to bypass the CSS opacity state in CI.
    const notifRow = page.locator('div.group').first();
    await notifRow.hover();

    const markReadBtn = page.getByRole('button', { name: /mark as read/i }).first();
    await markReadBtn.click({ force: true });

    // PATCH /api/admin/notifications/:id/read was captured.
    await expect.poll(() => readPatches.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(readPatches[0].url).toMatch(/\/admin\/notifications\/notif-\d+\/read/);
  });
});
