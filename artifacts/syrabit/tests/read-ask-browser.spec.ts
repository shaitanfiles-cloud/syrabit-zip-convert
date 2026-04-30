/**
 * Read & Ask Browser specs (Task #1 — 75 missing tests).
 *
 * Covers 6 cases against the actual BrowsePage/AskPanel component:
 *   BrowsePage: POST /api/edu/reader/fetch  → cleaned article payload
 *   AskPanel:   POST /api/edu/grounded-answer → SSE stream (chunks: {content: "..."})
 *
 * 1. Allowlisted URL fetches and renders Reader Mode content.
 * 2. Broken URL shows fetch-failure error.
 * 3. AskPanel textarea is visible on the browse page.
 * 4. Submitting a question fires POST /api/edu/grounded-answer.
 * 5. SSE tokens from grounded-answer stream render in the answer panel.
 * 6. AskPanel suggested prompt is visible in the ask panel.
 *
 * Route registration: broad "**/api/**" first, then narrow routes AFTER
 * (correct Playwright LIFO priority).
 */
import { test, expect, type Page, type Route } from '@playwright/test';

const ARTICLE_PAYLOAD = {
  ok: true,
  html: '<h1>Photosynthesis in Plants</h1><p>Photosynthesis is the process by which plants use sunlight to produce food.</p>',
  title: 'Photosynthesis in Plants',
  url: 'https://ncert.nic.in/photosynthesis',
};

function makeGroundedSseResponse(content: string): string {
  const chunks = content.match(/.{1,20}/g) ?? [content];
  return chunks.map(c => `data: ${JSON.stringify({ content: c })}\n\n`).join('') + 'data: [DONE]\n\n';
}

async function installBrowserMocks(
  page: Page,
  opts: { fetchOk?: boolean; askContent?: string } = {},
) {
  const { fetchOk = true, askContent = 'Photosynthesis converts light energy to glucose via chlorophyll.' } = opts;
  const groundedCalls: Array<{ url: string; body: unknown }> = [];

  // 1. Broad catch-all first.
  await page.route('**/api/**', async (route: Route) => {
    const method = route.request().method();
    if (method === 'OPTIONS') { await route.fulfill({ status: 204, body: '' }); return; }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });

  // 2. Narrow routes registered AFTER (higher Playwright LIFO priority).

  // reader/fetch — fetch and clean article.
  await page.route('**/api/edu/reader/fetch', async (route: Route) => {
    if (!fetchOk) {
      await route.fulfill({
        status: 502, contentType: 'application/json',
        body: JSON.stringify({ ok: false, error: 'fetch_failed', message: 'Could not fetch the URL.' }),
      });
      return;
    }
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(ARTICLE_PAYLOAD),
    });
  });

  // grounded-answer — SSE stream; record calls.
  await page.route('**/api/edu/grounded-answer', async (route: Route) => {
    const req = route.request();
    let body: unknown = null;
    try { body = req.postDataJSON(); } catch { body = req.postData(); }
    groundedCalls.push({ url: req.url(), body });
    await route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
      body: makeGroundedSseResponse(askContent),
    });
  });

  return { groundedCalls };
}

test.describe('Read & Ask Browser', () => {
  test('allowlisted URL fetches and renders Reader Mode content', async ({ page }) => {
    await installBrowserMocks(page, { fetchOk: true });
    await page.goto('/browse');

    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://ncert.nic.in/photosynthesis');

    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read/i }).first();
    await fetchBtn.click();

    await expect(page.getByText(/Photosynthesis in Plants/i)).toBeVisible({ timeout: 12_000 });
  });

  test('broken URL shows fetch-failure error', async ({ page }) => {
    await installBrowserMocks(page, { fetchOk: false });
    await page.goto('/browse');

    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://this-url-does-not-exist-broken.com/page');

    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read/i }).first();
    await fetchBtn.click();

    await expect(page.getByText(/could not|failed|error|fetch/i)).toBeVisible({ timeout: 10_000 });
  });

  test('AskPanel textarea is visible on the browse page', async ({ page }) => {
    await installBrowserMocks(page);
    await page.goto('/browse');

    const textarea = page.locator('#ask-syra-input, textarea').first();
    await expect(textarea).toBeVisible({ timeout: 10_000 });
  });

  test('submitting a question fires POST /api/edu/grounded-answer', async ({ page }) => {
    const { groundedCalls } = await installBrowserMocks(page, {
      fetchOk: true,
      askContent: 'Photosynthesis is a biochemical process.',
    });
    await page.goto('/browse');

    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://ncert.nic.in/photosynthesis');

    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read/i }).first();
    await fetchBtn.click();
    await expect(page.getByText(/Photosynthesis in Plants/i)).toBeVisible({ timeout: 12_000 });

    const textarea = page.locator('#ask-syra-input, textarea').first();
    await expect(textarea).toBeVisible({ timeout: 5_000 });
    await textarea.fill('What is photosynthesis?');
    await page.keyboard.press('Enter');

    await expect.poll(() => groundedCalls.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(groundedCalls[0].url).toContain('/api/edu/grounded-answer');
  });

  test('SSE tokens from grounded-answer stream render in the answer panel', async ({ page }) => {
    const answerText = 'Chlorophyll absorbs light at red and blue wavelengths for energy.';
    await installBrowserMocks(page, { fetchOk: true, askContent: answerText });
    await page.goto('/browse');

    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://ncert.nic.in/photosynthesis');

    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read/i }).first();
    await fetchBtn.click();
    await expect(page.getByText(/Photosynthesis in Plants/i)).toBeVisible({ timeout: 12_000 });

    const textarea = page.locator('#ask-syra-input, textarea').first();
    await expect(textarea).toBeVisible({ timeout: 5_000 });
    await textarea.fill('What does chlorophyll do?');
    await page.keyboard.press('Enter');

    // SSE chunks stream into the answer panel — content text must appear.
    await expect(page.getByText(/Chlorophyll|wavelength|absorbs/i)).toBeVisible({ timeout: 10_000 });
  });

  test('AskPanel suggested prompt "Explain this for an AHSEC student" is visible', async ({ page }) => {
    await installBrowserMocks(page);
    await page.goto('/browse');

    await expect(
      page.getByText(/Explain this for an AHSEC student/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('non-allowlisted domain returns 403 and shows domain-not-allowed error', async ({ page }) => {
    // Register broad mock first.
    await installBrowserMocks(page, { fetchOk: true });

    // Narrow override: reader/fetch returns 403 for a blocked domain (LIFO wins).
    await page.route('**/api/edu/reader/fetch', async (route: Route) => {
      await route.fulfill({
        status: 403, contentType: 'application/json',
        body: JSON.stringify({
          ok: false,
          error: 'not_allowed',
          message: 'Domain not in the educational allowlist.',
        }),
      });
    });

    await page.goto('/browse');

    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://random-not-in-allowlist-domain.com/page');

    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read|Open/i }).first();
    await fetchBtn.click();

    await expect(
      page.getByText(/not.*allowed|allowlist|domain|forbidden|blocked/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('clicking "Summarise this page" chip fires POST /api/edu/grounded-answer', async ({ page }) => {
    const { groundedCalls } = await installBrowserMocks(page, {
      fetchOk: true,
      askContent: 'Summary: Photosynthesis converts light to glucose and oxygen.',
    });
    await page.goto('/browse');

    // First, load an article so AskPanel enters canAsk=true state (shows chips).
    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://ncert.nic.in/photosynthesis');
    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read|Open/i }).first();
    await fetchBtn.click();
    await expect(page.getByText(/Photosynthesis in Plants/i)).toBeVisible({ timeout: 12_000 });

    const summariseChip = page.getByRole('button', { name: /Summarise this page in 5 bullet points/i });
    await expect(summariseChip).toBeVisible({ timeout: 8_000 });
    await summariseChip.click();

    await expect.poll(() => groundedCalls.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(groundedCalls[0].url).toContain('/api/edu/grounded-answer');
  });

  test('clicking "Make a short quiz" chip fires POST /api/edu/grounded-answer', async ({ page }) => {
    const { groundedCalls } = await installBrowserMocks(page, {
      fetchOk: true,
      askContent: 'Q1: What is photosynthesis? A) Energy conversion.',
    });
    await page.goto('/browse');

    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://ncert.nic.in/photosynthesis');
    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read|Open/i }).first();
    await fetchBtn.click();
    await expect(page.getByText(/Photosynthesis in Plants/i)).toBeVisible({ timeout: 12_000 });

    const quizChip = page.getByRole('button', { name: /Make a short quiz from this page/i });
    await expect(quizChip).toBeVisible({ timeout: 8_000 });
    await quizChip.click();

    await expect.poll(() => groundedCalls.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(groundedCalls[0].url).toContain('/api/edu/grounded-answer');
  });

  test('clicking "Explain this for an AHSEC student" chip fires POST /api/edu/grounded-answer', async ({ page }) => {
    const explainContent = 'Photosynthesis: plants convert CO2 + water + light → glucose + oxygen, explained simply.';
    const { groundedCalls } = await installBrowserMocks(page, {
      fetchOk: true,
      askContent: explainContent,
    });
    await page.goto('/browse');

    // Load an article so AskPanel enters canAsk=true state (suggestion chips appear).
    const urlInput = page.getByRole('textbox').first();
    await expect(urlInput).toBeVisible({ timeout: 10_000 });
    await urlInput.fill('https://ncert.nic.in/photosynthesis');
    const fetchBtn = page.locator('button').filter({ hasText: /fetch|go|load|read|Open/i }).first();
    await fetchBtn.click();
    await expect(page.getByText(/Photosynthesis in Plants/i)).toBeVisible({ timeout: 12_000 });

    // AskPanel.jsx: "Explain this for an AHSEC student" chip (visible once canAsk=true).
    const explainChip = page.getByRole('button', { name: /Explain this for an AHSEC student/i });
    await expect(explainChip).toBeVisible({ timeout: 8_000 });
    await explainChip.click();

    // Chip click triggers POST /api/edu/grounded-answer with the explain prompt.
    await expect.poll(() => groundedCalls.length, { timeout: 8_000 }).toBeGreaterThan(0);
    expect(groundedCalls[0].url).toContain('/api/edu/grounded-answer');

    // SSE stream response renders the explanation in the answer panel.
    await expect(page.getByText(/Photosynthesis|glucose|oxygen|CO2/i)).toBeVisible({ timeout: 10_000 });
  });
});
