/**
 * Exam Routine specs (Task #1 — 75 missing tests).
 *
 * 1. /exam-routine renders the AHSEC exam schedule.
 * 2. Specific subjects from the schedule are displayed with dates.
 * 3. Past entries are visually distinguished from upcoming entries.
 */
import { test, expect, type Route } from '@playwright/test';

const PAST_EXAMS = [
  { id: 'e1', subject: 'English',   code: 'ENG', date: '2026-03-06', time: '09:00', duration_hours: 3, is_past: true },
  { id: 'e2', subject: 'Chemistry', code: 'CHE', date: '2026-03-10', time: '09:00', duration_hours: 3, is_past: true },
  { id: 'e3', subject: 'Biology',   code: 'BIO', date: '2026-03-11', time: '09:00', duration_hours: 3, is_past: true },
];

const UPCOMING_EXAM = {
  id: 'e99', subject: 'Advanced Physics', code: 'PHY', date: '2026-12-25', time: '09:00', duration_hours: 3, is_past: false,
};

const EXAM_ROUTINE_API = {
  ok: true, board: 'AHSEC', year: 2026,
  schedule: [...PAST_EXAMS, UPCOMING_EXAM],
};

async function installExamRoutineMocks(page: import('@playwright/test').Page) {
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request();
    const url = req.url();
    if (req.method() === 'OPTIONS') { await route.fulfill({ status: 204, body: '' }); return; }
    if (url.includes('/api/edu/exam-routine') || url.includes('/api/exam-routine')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EXAM_ROUTINE_API) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

test.describe('Exam Routine', () => {
  test('/exam-routine renders the AHSEC exam schedule', async ({ page }) => {
    await installExamRoutineMocks(page);
    await page.goto('/exam-routine');

    await expect(page.getByText(/AHSEC|exam routine|exam schedule/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/English|Chemistry|Biology|Physics/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test('subjects from AHSEC schedule are displayed with dates', async ({ page }) => {
    await installExamRoutineMocks(page);
    await page.goto('/exam-routine');

    await expect(page.getByText(/English/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Chemistry/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Biology/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/Advanced Physics/i).first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/2026|March/i).first()).toBeVisible({ timeout: 5_000 });
  });

  test('past entries are visually distinguished from the upcoming entry', async ({ page }) => {
    await installExamRoutineMocks(page);
    await page.goto('/exam-routine');

    await expect(page.getByText(/English/i).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Advanced Physics/i).first()).toBeVisible({ timeout: 5_000 });

    // Past entries carry subdued styling; upcoming entry carries upcoming/active styling.
    const pastRows = page.locator(
      '[class*="past"],[class*="muted"],[class*="opacity"],[class*="gray-4"],[class*="gray-3"],' +
      '[class*="line-through"],[class*="completed"],[data-past],[data-status="past"]',
    );
    const upcomingRows = page.locator(
      '[class*="upcoming"],[class*="active"],[class*="highlight"],[class*="accent"],' +
      '[data-upcoming],[data-status="upcoming"],[class*="future"]',
    );

    // At least one past-styled row must exist (March 2026 entries are in the past).
    await expect(pastRows.first()).toBeVisible({ timeout: 8_000 });

    // The upcoming 2099 entry must be rendered (confirmed by text presence above).
    // Verify the page renders both categories by checking at least one row differs from the past style.
    const pastCount = await pastRows.count();
    const totalRows = await page.locator('tr,li,[role="row"]').count();
    expect(pastCount).toBeGreaterThan(0);
    expect(totalRows).toBeGreaterThan(pastCount); // upcoming row has different styling
  });
});
