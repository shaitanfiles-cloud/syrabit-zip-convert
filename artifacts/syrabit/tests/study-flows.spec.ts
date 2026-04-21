/**
 * Phase-3 study flows — Task #594.
 *
 * Covers the four user journeys the Phase-3 backend tests don't reach:
 *
 *   1. Highlight text in a chapter → save to Notebook (POST /api/edu/notes).
 *   2. Generate a quiz, answer all questions, see the result screen.
 *   3. Open Flashcards, flip a due card, grade it Good (POST review).
 *   4. Set a guardian PIN; mismatched confirm rejects, matching submits.
 *
 * The tests stub every `/api/**` call with `page.route` so the suite is
 * hermetic — no LLM cost, no Postgres needed, no auth flakiness. The
 * highlight + quiz flows run inside the dedicated `/__test/study-harness`
 * route (added with the same task) so we can exercise the popover and
 * quiz modal without mocking the entire ChapterPage data layer.
 */
import { test, expect, type Page, type Route } from '@playwright/test';

// ───────────────────── Shared API stub ─────────────────────

interface FlashcardRow {
  id: string; front: string; back: string; note_id: string;
  ef: number; interval_days: number; repetitions: number;
  due_at: string; last_reviewed: string | null;
}

interface StudyMockState {
  notes: Array<{
    id: string; text: string; tags: string[];
    source_url: string; source_title: string; chapter_ref: string;
    created_at: string; updated_at: string;
  }>;
  flashcards: FlashcardRow[];
  pin?: string;
  strict: boolean;
  pinVerifyAttempts: Array<{ pin: string }>;
  reviewCalls: Array<{ card_id: string; quality: number }>;
  notesCreated: Array<unknown>;
  pinSets: Array<unknown>;
  buildCalls: number;
  // Settings POSTs (?pin=…) reach this route as well; we record them so
  // the strict-mode-disable test can assert the PIN was carried.
  settingsPosts: Array<{ url: string; body: unknown; pinQuery: string }>;
  // Cards added the next time /edu/flashcards/build is called. Lets the
  // build test start with an empty deck and watch it fill in.
  buildAdds: FlashcardRow[];
}

async function installStudyApiMocks(page: Page, init: Partial<StudyMockState> = {}) {
  const state: StudyMockState = {
    notes: init.notes ?? [],
    flashcards: init.flashcards ?? [],
    pin: init.pin,
    strict: init.strict ?? false,
    pinVerifyAttempts: [],
    reviewCalls: [],
    notesCreated: [],
    pinSets: [],
    buildCalls: 0,
    settingsPosts: [],
    buildAdds: init.buildAdds ?? [],
  };

  await page.route('**/api/**', async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace(/^.*\/api/, '/api');
    const method = req.method();

    const json = (status: number, body: unknown) =>
      route.fulfill({
        status, contentType: 'application/json', body: JSON.stringify(body),
      });

    // ── Quiz generator ────────────────────────────────────
    if (path === '/api/edu/quiz/generate' && method === 'POST') {
      return json(200, {
        ok: true,
        count: 2,
        questions: [
          {
            id: 'q1', q: 'Photosynthesis happens primarily in?',
            choices: ['Mitochondria', 'Chloroplasts', 'Nucleus', 'Ribosomes'],
            answer: 1, explanation: 'Chloroplasts hold the chlorophyll.',
          },
          {
            id: 'q2', q: 'The output gas of photosynthesis is?',
            choices: ['CO2', 'N2', 'O2', 'H2'],
            answer: 2, explanation: 'Plants release oxygen.',
          },
        ],
      });
    }

    // ── Notes ─────────────────────────────────────────────
    if (path === '/api/edu/notes' && method === 'POST') {
      const payload = req.postDataJSON();
      const now = new Date().toISOString();
      const note = {
        id: `note-${state.notes.length + 1}`,
        text: payload.text, tags: payload.tags || [],
        source_url: payload.source_url || '', source_title: payload.source_title || '',
        chapter_ref: payload.chapter_ref || '', created_at: now, updated_at: now,
      };
      state.notes.unshift(note);
      state.notesCreated.push(payload);
      return json(200, { ok: true, note });
    }
    if (path === '/api/edu/notes' && method === 'GET') {
      return json(200, { ok: true, notes: state.notes, count: state.notes.length });
    }

    // ── Flashcards ────────────────────────────────────────
    if (path === '/api/edu/flashcards/due' && method === 'GET') {
      return json(200, { ok: true, cards: state.flashcards, total: state.flashcards.length });
    }
    if (path === '/api/edu/flashcards/streak' && method === 'GET') {
      // FlashcardsPage spreads this object into state, expecting
      // `current_streak`, `best_streak`, `today` at the top level.
      return json(200, {
        ok: true, current_streak: 3, best_streak: 5, today: 1,
      });
    }
    if (path === '/api/edu/flashcards/review' && method === 'POST') {
      const payload = req.postDataJSON();
      state.reviewCalls.push(payload);
      const card = state.flashcards.find((c) => c.id === payload.card_id);
      return json(200, {
        ok: true,
        card: { ...(card || {}), last_reviewed: new Date().toISOString() },
        streak: 4,
      });
    }
    if (path === '/api/edu/flashcards/build' && method === 'POST') {
      state.buildCalls += 1;
      const created = state.buildAdds.length;
      // Move queued cards into the deck so the next /due call returns
      // them. Mirrors the real backend: build inserts new cards with
      // due_at = now, then the page reloads and renders them.
      state.flashcards.push(...state.buildAdds);
      state.buildAdds = [];
      return json(200, { ok: true, created });
    }

    // ── Settings + PIN ────────────────────────────────────
    if (path === '/api/edu/study/settings' && method === 'GET') {
      return json(200, {
        ok: true, strict_mode: state.strict,
        guardian_locked: Boolean(state.pin),
        has_pin: Boolean(state.pin),
        streak: 0,
      });
    }
    if (path === '/api/edu/study/settings' && method === 'POST') {
      const body = req.postDataJSON();
      const pinQuery = url.searchParams.get('pin') || '';
      state.settingsPosts.push({ url: req.url(), body, pinQuery });
      // Mirror the real route's behaviour: when a PIN is set and the
      // caller is turning Strict Mode OFF, the supplied ?pin=… query
      // arg must match. Anything else is allowed.
      if (state.pin && body && body.strict_mode === false && pinQuery !== state.pin) {
        return json(403, { detail: 'pin_required_or_invalid' });
      }
      state.strict = Boolean(body?.strict_mode);
      return json(200, { ok: true, strict_mode: state.strict });
    }
    if (path === '/api/edu/guardian/pin/set' && method === 'POST') {
      const payload = req.postDataJSON();
      state.pin = payload.new_pin;
      state.pinSets.push(payload);
      return json(200, { ok: true });
    }
    if (path === '/api/edu/guardian/pin/verify' && method === 'POST') {
      const payload = req.postDataJSON();
      state.pinVerifyAttempts.push({ pin: String(payload?.pin ?? '') });
      if (!state.pin) return json(200, { ok: true, valid: true, set: false });
      return json(200, { ok: true, valid: payload.pin === state.pin, set: true });
    }

    // ── Permissive fallback so unrelated calls (analytics, voice
    //    status, language allowlist, etc.) don't 404 and pollute the
    //    error logs the test asserts against. ────────────────────
    if (method === 'OPTIONS') return route.fulfill({ status: 204, body: '' });
    return json(200, {});
  });

  return state;
}

// ───────────────────── 1. Highlight → save note ─────────────────────

test.describe('Phase-3 study flows', () => {
  test('highlighting savable text in a chapter fires a save → /api/edu/notes', async ({ page }) => {
    const state = await installStudyApiMocks(page);
    await page.goto('/__test/study-harness');
    await expect(page.getByTestId('study-harness')).toBeVisible();

    // Programmatically select a span of text inside the savable block.
    // The popover listens to `selectionchange` events and only mounts
    // when the selection is wholly inside `[data-savable="true"]`.
    await page.evaluate(() => {
      const node = document.querySelector('[data-testid="harness-savable"]');
      if (!node) throw new Error('savable block missing');
      const text = node.firstChild;
      if (!text || text.nodeType !== 3) throw new Error('no text node');
      const range = document.createRange();
      range.setStart(text, 0);
      range.setEnd(text, Math.min((text.textContent || '').length, 60));
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
      document.dispatchEvent(new Event('selectionchange'));
    });

    const saveBtn = page.getByRole('button', { name: /^Save$/ });
    await expect(saveBtn).toBeVisible({ timeout: 5000 });
    await saveBtn.click();

    // Server received the create request with the highlighted text.
    await expect.poll(() => state.notesCreated.length, { timeout: 5000 }).toBe(1);
    const created = state.notesCreated[0] as { text: string; chapter_ref: string };
    expect(created.text.length).toBeGreaterThan(5);
    expect(created.chapter_ref).toBe('test/harness/photosynthesis');
  });

  // ─────────────── 2. Quiz: generate → answer → result ───────────────
  test('quiz modal generates, grades, and shows the score screen', async ({ page }) => {
    await installStudyApiMocks(page);
    await page.goto('/__test/study-harness');
    await page.getByTestId('harness-open-quiz').click();

    // Q1
    await expect(page.getByText(/Question 1 of 2/)).toBeVisible({ timeout: 8000 });
    // Pick the correct answer (Chloroplasts).
    await page.getByRole('button', { name: /Chloroplasts/ }).click();
    await page.getByRole('button', { name: 'Submit' }).click();
    await expect(page.getByText(/Why:/)).toBeVisible();
    await page.getByRole('button', { name: /Next|See results/ }).click();

    // Q2 — pick a wrong answer to verify mixed scoring.
    await expect(page.getByText(/Question 2 of 2/)).toBeVisible();
    // CO2 is wrong (the correct answer is O2 / index 2).
    await page.getByRole('button', { name: /CO2/ }).click();
    await page.getByRole('button', { name: 'Submit' }).click();
    await page.getByRole('button', { name: /See results/ }).click();

    // Result screen: 1 / 2.
    await expect(page.getByText('1 / 2')).toBeVisible();
    await expect(page.getByText(/Review the explanations/i)).toBeVisible();
  });

  // ─────────────── 3. Flashcards: flip + grade ───────────────
  test('flashcards page lets the user flip a card and grade it Good', async ({ page }) => {
    const state = await installStudyApiMocks(page, {
      flashcards: [
        {
          id: 'card-1', note_id: 'note-1',
          front: 'What organelle hosts photosynthesis?',
          back: 'Chloroplasts',
          ef: 2.5, interval_days: 0, repetitions: 0,
          due_at: new Date(Date.now() - 60_000).toISOString(),
          last_reviewed: null,
        },
      ],
    });

    await page.goto('/flashcards');

    // Streak banner visible.
    await expect(page.getByText('Card 1 of 1')).toBeVisible({ timeout: 8000 });
    // Front shown first.
    await expect(page.getByText('What organelle hosts photosynthesis?')).toBeVisible();

    await page.getByRole('button', { name: /Show answer/ }).click();
    await expect(page.getByText('Chloroplasts')).toBeVisible();

    await page.getByRole('button', { name: 'Good' }).click();

    // Review POSTed with quality=4 (Good).
    await expect.poll(() => state.reviewCalls.length, { timeout: 5000 }).toBe(1);
    expect(state.reviewCalls[0]).toEqual({ card_id: 'card-1', quality: 4 });

    // Deck exhausted → completion card.
    await expect(page.getByText(/All caught up/i)).toBeVisible();
  });

  // ─────────────── 4. Guardian PIN: set + mismatch guard ───────────────
  test('guardian PIN: mismatched confirm rejects, matching values submit', async ({ page }) => {
    const state = await installStudyApiMocks(page);
    await page.goto('/guardian');

    await expect(page.getByRole('heading', { name: /Guardian Controls/ })).toBeVisible();

    // The setup form has two PIN inputs (no "current" since none is set).
    const newPin = page.getByPlaceholder('New PIN');
    const confirmPin = page.getByPlaceholder('Confirm new PIN');

    // Mismatch path: should not POST and should toast an error.
    await newPin.fill('1234');
    await confirmPin.fill('9999');
    await page.getByRole('button', { name: /Set PIN/ }).click();
    await expect(page.getByText(/PINs do not match/i)).toBeVisible({ timeout: 4000 });
    expect(state.pinSets).toHaveLength(0);

    // Happy path.
    await confirmPin.fill('1234');
    await page.getByRole('button', { name: /Set PIN/ }).click();
    await expect.poll(() => state.pinSets.length, { timeout: 5000 }).toBe(1);
    expect(state.pinSets[0]).toMatchObject({ new_pin: '1234' });
    expect(state.pin).toBe('1234');
  });

  // ─────────────── 5. Build a flashcard deck from empty state, then grade ───────────────
  test('flashcards page builds a deck from notes, then grades the first card', async ({ page }) => {
    // Start with NO due cards — page should render the empty state and
    // its "Build from notes" CTA. The mock will populate the deck on
    // the first /flashcards/build POST so the subsequent reload renders
    // a card we can grade.
    const seed: FlashcardRow = {
      id: 'card-built-1', note_id: 'note-99',
      front: 'Define photosynthesis',
      back: 'The process by which plants convert light into chemical energy.',
      ef: 2.5, interval_days: 0, repetitions: 0,
      due_at: new Date(Date.now() - 60_000).toISOString(),
      last_reviewed: null,
    };
    const state = await installStudyApiMocks(page, { buildAdds: [seed] });

    await page.goto('/flashcards');

    // Empty state copy and CTA wired up.
    await expect(page.getByText(/No cards due/i)).toBeVisible({ timeout: 8000 });
    const buildBtn = page.getByRole('button', { name: /Build from notes/ });
    await expect(buildBtn).toBeVisible();

    await buildBtn.click();

    // Build endpoint hit, success toast surfaced, and the deck reloaded.
    await expect.poll(() => state.buildCalls, { timeout: 5000 }).toBe(1);
    await expect(page.getByText(/Created 1 flashcards/i)).toBeVisible({ timeout: 4000 });
    await expect(page.getByText('Card 1 of 1')).toBeVisible();
    await expect(page.getByText('Define photosynthesis')).toBeVisible();

    // Now exercise the same grade path the existing test covers, but
    // against a card that only exists because the build flow ran.
    await page.getByRole('button', { name: /Show answer/ }).click();
    await page.getByRole('button', { name: 'Easy' }).click();

    await expect.poll(() => state.reviewCalls.length, { timeout: 5000 }).toBe(1);
    expect(state.reviewCalls[0]).toEqual({ card_id: 'card-built-1', quality: 5 });
    await expect(page.getByText(/All caught up/i)).toBeVisible();
  });

  // ─────────────── 6. Guardian PIN verification path (disable Strict Mode) ───────────────
  test('disabling Strict Mode requires the PIN and rejects a wrong one', async ({ page }) => {
    // The Phase-3 verification path the user actually walks: a PIN is
    // set, Strict Mode is on, and turning Strict Mode OFF requires
    // typing the PIN into the browser prompt. The page calls
    // POST /edu/study/settings?pin=… which the backend uses to verify
    // the PIN. We stub that endpoint to return 403 on mismatch and
    // 200 on match — exactly the contract Task #594 hardened.
    const state = await installStudyApiMocks(page, { pin: '4242', strict: true });
    // Pre-seed the local cache so the toggle renders ON immediately
    // (the hook hydrates from server settings async, and the toggle
    // initial state is read from localStorage to avoid a flash).
    await page.addInitScript(() => {
      try { localStorage.setItem('syrabit_strict_mode', '1'); } catch {}
    });

    await page.goto('/guardian');
    await expect(page.getByRole('heading', { name: /Guardian Controls/ })).toBeVisible();

    const toggle = page.getByRole('switch');
    await expect(toggle).toHaveAttribute('aria-checked', 'true', { timeout: 5000 });
    // Wait until the "PIN required" hint renders — that's the signal
    // that getSettings has resolved and `hasPin` is true. Without this
    // gate, the toggle click can race the settings fetch and skip the
    // window.prompt entirely.
    await expect(page.getByText(/PIN required to turn Strict Mode off/i)).toBeVisible();

    // Wrong-PIN path: browser prompt → 403 → "Wrong PIN" toast.
    page.once('dialog', (d) => d.accept('0000'));
    await toggle.click();
    await expect(page.getByText(/Wrong PIN/i)).toBeVisible({ timeout: 4000 });
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(state.settingsPosts.at(-1)).toMatchObject({
      body: { strict_mode: false }, pinQuery: '0000',
    });

    // Correct-PIN path: browser prompt → 200 → toast "Strict Mode off".
    page.once('dialog', (d) => d.accept('4242'));
    await toggle.click();
    await expect(page.getByText(/Strict Mode off/i)).toBeVisible({ timeout: 4000 });
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(state.settingsPosts.at(-1)).toMatchObject({
      body: { strict_mode: false }, pinQuery: '4242',
    });
    expect(state.strict).toBe(false);
  });
});
