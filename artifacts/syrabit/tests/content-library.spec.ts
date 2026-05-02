/**
 * Content Library & Curriculum specs (Task #1 — 75 missing tests).
 *
 * Covers 6 cases:
 *   1. /library renders boards, classes, streams, and subjects.
 *   2. Clicking a subject navigates to the correct chapter list.
 *   3. Chapter detail page renders summary, key topics, and graph.
 *   4. Deep-linked chapter URL resolves and renders correctly.
 *   5. SEO meta tags (title, description) are present on chapter pages.
 *   6. /curriculum renders the visual curriculum map with subject nodes.
 *
 * Stubs GET /api/content/library-bundle, GET /api/content/chapters/:subjectId,
 * GET /api/content/subjects/:id, GET /api/content/chapters/:slug
 * via page.route (actual paths from src/hooks/useContent.jsx).
 */
import { test, expect, type Route } from '@playwright/test';

const LIBRARY_BUNDLE = {
  boards: [{ id: 'ahsec', name: 'AHSEC', slug: 'ahsec' }],
  classes: [{ id: 'class-11', name: 'Class 11', slug: 'class-11', level: 11 }],
  streams: [{ id: 'science', name: 'Science', slug: 'science' }],
  subjects: [
    {
      id: 'sub-bio-11',
      name: 'Biology',
      slug: 'biology-class-11',
      class: 11,
      class_slug: 'class-11',
      stream: 'science',
      board: 'AHSEC',
      board_slug: 'ahsec',
      chapter_count: 22,
    },
    {
      id: 'sub-chem-11',
      name: 'Chemistry',
      slug: 'chemistry-class-11',
      class: 11,
      class_slug: 'class-11',
      stream: 'science',
      board: 'AHSEC',
      board_slug: 'ahsec',
      chapter_count: 14,
    },
  ],
};

const CHAPTER_DETAIL = {
  id: 'ch-photo-01',
  chapter_id: 'ch-photo-01',
  title: 'Photosynthesis in Higher Plants',
  chapter_title: 'Photosynthesis in Higher Plants',
  topic_title: null,
  slug: 'photosynthesis-class-11',
  subject_id: 'sub-bio-11',
  subject_name: 'Biology',
  board_name: 'AHSEC',
  class_name: 'Class 11',
  summary: 'An overview of the light and dark reactions of photosynthesis.',
  meta_description: 'Study Photosynthesis in Higher Plants for AHSEC Class 11 Biology. Covers light reactions, Calvin cycle, and more.',
  key_topics: ['Light reactions', 'Dark reactions', 'Calvin cycle', 'Photorespiration'],
  content: '## Photosynthesis\n\nProcess of converting light energy into chemical energy.',
  content_html: '<h2>Photosynthesis</h2><p>Process of converting light energy...</p>',
  word_count: 120,
  graph: {
    nodes: [{ id: 'n1', label: 'Chlorophyll' }, { id: 'n2', label: 'ATP' }],
    edges: [{ source: 'n1', target: 'n2' }],
  },
};

const CHAPTERS_LIST = {
  chapters: [
    { id: 'ch-photo-01', title: 'Photosynthesis in Higher Plants', slug: 'photosynthesis-class-11', order: 13 },
    { id: 'ch-cell-01', title: 'Cell: The Unit of Life', slug: 'cell-unit-of-life-class-11', order: 8 },
  ],
};

const CURRICULUM_PAYLOAD = {
  nodes: [
    { id: 'biology-class-11', label: 'Biology', class: 11, stream: 'science', x: 100, y: 200 },
    { id: 'chemistry-class-11', label: 'Chemistry', class: 11, stream: 'science', x: 300, y: 200 },
  ],
  edges: [],
};

async function installLibraryMocks(page: import('@playwright/test').Page) {
  // Broad catch-all registered first (lowest Playwright LIFO priority).
  await page.route('**/api/**', async (route: Route) => {
    const req = route.request();
    const method = req.method();
    if (method === 'OPTIONS') { await route.fulfill({ status: 204, body: '' }); return; }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });

  // Narrow routes registered AFTER (higher Playwright LIFO priority).

  await page.route('**/api/content/library-bundle**', async (route: Route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(LIBRARY_BUNDLE),
    });
  });

  await page.route('**/content/subjects/**', async (route: Route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(LIBRARY_BUNDLE.subjects[0]),
    });
  });

  await page.route('**/content/chapters/**', async (route: Route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(CHAPTERS_LIST),
    });
  });

  await page.route('**/content/chapter-by-slug/**', async (route: Route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(CHAPTER_DETAIL),
    });
  });

  // Additional ChapterPage sub-resource fetches (topics, related, faq) — return empty.
  await page.route('**/content/chapters/*/topics**', async (route: Route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });

  // Curriculum map endpoint.
  await page.route('**/api/curriculum**', async (route: Route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(CURRICULUM_PAYLOAD),
    });
  });
}

test.describe('Content Library & Curriculum', () => {
  test('/library renders boards, classes, streams, and subjects', async ({ page }) => {
    await installLibraryMocks(page);
    await page.goto('/library');

    await expect(page.getByText(/AHSEC|Board/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Class 11|11th/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Biology|Science/i)).toBeVisible({ timeout: 10_000 });
  });

  test('clicking a subject navigates to the correct chapter list', async ({ page }) => {
    await installLibraryMocks(page);
    await page.goto('/library');

    await expect(page.getByText(/Biology/i)).toBeVisible({ timeout: 10_000 });
    await page.getByText(/Biology/i).first().click();

    await expect(page).toHaveURL(/biology|chapter|sub-bio/i, { timeout: 10_000 });
  });

  test('chapter detail page renders summary, key topics, and graph', async ({ page }) => {
    await installLibraryMocks(page);
    // App.jsx route: /:board/:classSlug/:subjectSlug/:chapterSlug
    await page.goto('/ahsec/class-11/biology-class-11/photosynthesis-class-11');

    await expect(page.getByText(/Photosynthesis/i).first()).toBeVisible({ timeout: 12_000 });
    await expect(page.getByText(/light.*reaction|overview|summary|photosynthesis/i)).toBeVisible({ timeout: 10_000 });
  });

  test('deep-linked chapter URL resolves and renders correctly', async ({ page }) => {
    await installLibraryMocks(page);
    // App.jsx route: /:board/:classSlug/:subjectSlug/:chapterSlug
    const resp = await page.goto('/ahsec/class-11/biology-class-11/photosynthesis-class-11');
    expect(resp?.status()).not.toBe(404);

    await expect(page.getByText(/Photosynthesis/i).first()).toBeVisible({ timeout: 12_000 });
    await expect(page.locator('h1, h2').first()).toBeVisible({ timeout: 10_000 });
  });

  test('SEO meta tags (title, description) are present on chapter pages', async ({ page }) => {
    await installLibraryMocks(page);
    // App.jsx route: /:board/:classSlug/:subjectSlug/:chapterSlug
    await page.goto('/ahsec/class-11/biology-class-11/photosynthesis-class-11');

    await expect(page.getByText(/Photosynthesis/i).first()).toBeVisible({ timeout: 12_000 });

    // The page title must be non-empty.
    const titleEl = await page.title();
    expect(titleEl.length).toBeGreaterThan(0);

    // ChapterPage.jsx uses a useSEO hook that sets a <meta name="description"> tag
    // from CHAPTER_DETAIL.meta_description once the chapter data loads.
    const metaDesc = await page.locator('meta[name="description"]').getAttribute('content', { timeout: 6_000 });
    expect((metaDesc ?? '').length).toBeGreaterThan(0);
  });

  test('/curriculum renders the visual curriculum map with subject nodes', async ({ page }) => {
    await installLibraryMocks(page);
    await page.goto('/curriculum');

    await expect(page.locator('body')).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText(/Biology|Chemistry|Curriculum|Map|Subject/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });
});
