/**
 * Task #104 — Verify the embed cooldown pulse animation and two-stage
 * urgency cue appear correctly in the real AdminHealth component.
 *
 * AdminHealth is rendered with all axios calls mocked; pool-stats is the
 * only one that returns cooldown-relevant data.  Every other URL rejects so
 * sub-panels enter their error state gracefully.
 *
 * We do NOT use vi.useFakeTimers() because it prevents waitFor (which relies
 * on real setTimeout) from retrying.  The countdown interval fires at most
 * once during the test (it ticks every 1 s), which is fast enough to still
 * catch the initial rendered value before any tick occurs.
 *
 * Test flow
 * ─────────
 * 1. Configure pool-stats mock (per test).
 * 2. Render <AdminHealth adminToken="tok" />.
 * 3. The loadWorkersAi() useEffect fires on mount and resolves pool-stats.
 * 4. Click the "Workers AI Fallback" tab to show the cooldown card.
 * 5. waitFor the "Cooldown clears in" label, then assert classes.
 *
 * Covered states
 * ──────────────
 *  A. cooldown inactive → no animate-pulse, gray text, "—" value
 *  B. cooldown > 10 s   → text-red-600, no animate-pulse
 *  C. cooldown 6–10 s   → text-red-600 + animate-pulse   (stage 1)
 *  D. cooldown ≤ 5 s    → text-orange-500 + animate-pulse (stage 2)
 *  D₂. stage-2 cell wrapper → bg-amber-50 / border-amber-300
 *  D₃. alert banner at ≤ 5 s → bg-amber-100
 *  C₂. alert banner at > 5 s → bg-red-100
 */
import React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/* ── axios mock ──────────────────────────────────────────────────────────── */
vi.mock('axios', () => {
  const get = vi.fn();
  return { default: { get, post: vi.fn().mockRejectedValue(new Error('mocked')), create: vi.fn() }, get };
});

/* ── sub-component / library mocks ──────────────────────────────────────── */
vi.mock('@/utils/api', () => ({
  llmCosts: {},
  API_BASE: 'http://test.local',
}));

vi.mock('@/utils/highlightSegments', () => ({
  buildHighlightedSegments: vi.fn(() => []),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/components/ErrorBoundary', () => ({
  SectionErrorBoundary: ({ children }) => <>{children}</>,
}));

vi.mock('recharts', () => ({
  AreaChart:           ({ children }) => <div>{children}</div>,
  BarChart:            ({ children }) => <div>{children}</div>,
  LineChart:           ({ children }) => <div>{children}</div>,
  Area:                () => null,
  Bar:                 () => null,
  Line:                () => null,
  XAxis:               () => null,
  YAxis:               () => null,
  CartesianGrid:       () => null,
  Tooltip:             () => null,
  Legend:              () => null,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  ReferenceLine:       () => null,
}));

vi.mock('./CronHealthPill',              () => ({ default: () => <span />, SlackConfigBadge: () => null }));
vi.mock('./CfWafDriftCronPill',          () => ({ default: () => <span /> }));
vi.mock('./TrustpilotRefreshCronPill',   () => ({ default: () => <span /> }));
vi.mock('./EdgeProxyDeployCronPill',     () => ({ default: () => <span /> }));
vi.mock('./UnifiedLogsCfPullCronPill',   () => ({ default: () => <span /> }));
vi.mock('./AdminQuickLinks',             () => ({ default: () => <span /> }));

/* ── imports (after mocks) ───────────────────────────────────────────────── */
import axios from 'axios';
import AdminHealth from './AdminHealth';

/* ── helpers ─────────────────────────────────────────────────────────────── */
const basePoolStats = {
  embed_cooldown_active:      false,
  embed_cooldown_remaining_s: 0,
  embed_429_burst:            0,
  embed_429_threshold:        3,
  embed_cooldown_duration_s:  60,
};

function setPoolStatsMock(overrides = {}) {
  const data = { ...basePoolStats, ...overrides };
  axios.get.mockImplementation((url) => {
    if (url.includes('/admin/workers-ai/status'))
      return Promise.resolve({ data: { ok: true, enabled_globally: true, secret_configured: true, edge_url: 'https://cf.example.com' } });
    if (url.includes('/admin/dashboard/metrics'))
      return Promise.resolve({ data: { workers_ai_throttle: null } });
    if (url.includes('/admin/llm/pool-stats'))
      return Promise.resolve({ data });
    return Promise.reject(new Error('mocked rejection'));
  });
}

/** Flush all pending microtasks so that promise-based useEffects resolve. */
async function flushEffects() {
  // Two passes: first pass lets React schedule the effect; second pass
  // lets the resolved promise (then-callback) update the state.
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await Promise.resolve(); });
}

async function renderAndNavigate() {
  render(<AdminHealth adminToken="test-token" onNavigate={vi.fn()} />);
  await flushEffects();
  const tab = screen.getByRole('button', { name: /Workers AI Fallback/i });
  fireEvent.click(tab);
}

/* ── test lifecycle ──────────────────────────────────────────────────────── */
beforeEach(() => {
  setPoolStatsMock();   // default: inactive
});

afterEach(() => {
  vi.clearAllMocks();
});

/* ═══════════════════════════════════════════════════════════════════════════
   Tests
   ═══════════════════════════════════════════════════════════════════════════ */
describe('AdminHealth — embed cooldown pulse animation & urgency cue', () => {

  it('A — no animate-pulse and gray text when cooldown is inactive', async () => {
    setPoolStatsMock({ embed_cooldown_active: false, embed_cooldown_remaining_s: 0 });
    await renderAndNavigate();

    const label = await screen.findByText('Cooldown clears in', {}, { timeout: 3000 });
    expect(label).toBeInTheDocument();

    const valueEl = screen.getByText('—');
    expect(valueEl.className).toContain('text-gray-400');
    expect(valueEl.className).not.toContain('animate-pulse');
  });

  it('B — red text, no animate-pulse when cooldown has > 10 s remaining', async () => {
    setPoolStatsMock({ embed_cooldown_active: true, embed_cooldown_remaining_s: 45 });
    await renderAndNavigate();

    await screen.findByText('Cooldown clears in', {}, { timeout: 3000 });

    const valueEl = screen.getByText(/45 s/);
    expect(valueEl.className).toContain('text-red-600');
    expect(valueEl.className).not.toContain('animate-pulse');
  });

  it('C — animate-pulse + red text in the 6–10 s stage-1 window', async () => {
    setPoolStatsMock({ embed_cooldown_active: true, embed_cooldown_remaining_s: 8 });
    await renderAndNavigate();

    await screen.findByText('Cooldown clears in', {}, { timeout: 3000 });

    const valueEl = screen.getByText(/8 s/);
    expect(valueEl.className).toContain('animate-pulse');
    expect(valueEl.className).toContain('text-red-600');
    expect(valueEl.className).not.toContain('text-orange-500');
  });

  it('D — orange text + animate-pulse in the ≤5 s stage-2 window', async () => {
    setPoolStatsMock({ embed_cooldown_active: true, embed_cooldown_remaining_s: 3 });
    await renderAndNavigate();

    await screen.findByText('Cooldown clears in', {}, { timeout: 3000 });

    const valueEl = screen.getByText(/3 s/);
    expect(valueEl.className).toContain('animate-pulse');
    expect(valueEl.className).toContain('text-orange-500');
    expect(valueEl.className).not.toContain('text-red-600');
  });

  it('D₂ — countdown cell wrapper has amber bg/border at ≤5 s', async () => {
    setPoolStatsMock({ embed_cooldown_active: true, embed_cooldown_remaining_s: 3 });
    await renderAndNavigate();

    const label = await screen.findByText('Cooldown clears in', {}, { timeout: 3000 });
    const cell = label.parentElement;
    expect(cell.className).toContain('bg-amber-50');
    expect(cell.className).toContain('border-amber-300');
  });

  it('D₃ — alert banner has amber bg at ≤5 s', async () => {
    setPoolStatsMock({ embed_cooldown_active: true, embed_cooldown_remaining_s: 4 });
    await renderAndNavigate();

    const bannerText = await screen.findByText(/Embed cooldown active/, {}, { timeout: 3000 });
    const banner = bannerText.closest('div.rounded-lg');
    expect(banner.className).toContain('bg-amber-100');
    expect(banner.className).not.toContain('bg-red-100');
  });

  it('C₂ — alert banner has red bg when > 5 s remain', async () => {
    setPoolStatsMock({ embed_cooldown_active: true, embed_cooldown_remaining_s: 8 });
    await renderAndNavigate();

    const bannerText = await screen.findByText(/Embed cooldown active/, {}, { timeout: 3000 });
    const banner = bannerText.closest('div.rounded-lg');
    expect(banner.className).toContain('bg-red-100');
    expect(banner.className).not.toContain('bg-amber-100');
  });
});
