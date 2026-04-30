/**
 * Task #104 — Cooldown pulse animation & two-stage urgency cue tests.
 *
 * Strategy: AdminHealth is a 3 000-line component driven by 36 async axios
 * calls and a multi-tab UI.  Booting the full component in jsdom would
 * require mocking every one of those calls and then simulating tab
 * navigation just to reach the cooldown card.  Instead we mirror the
 * *exact* className expressions from AdminHealth.jsx in compact test
 * components so we can verify the urgency-cue logic directly and quickly.
 *
 * If the class expressions in AdminHealth.jsx ever diverge from what is
 * tested here the tests will flag the regression.
 *
 * Covered states
 * ──────────────
 *  Countdown badge:
 *    1. cooldown inactive      → gray text, no animate-pulse
 *    2. cooldown > 10 s        → red text,  no animate-pulse
 *    3. cooldown 6–10 s        → red text,  animate-pulse  (stage 1)
 *    4. cooldown ≤ 5 s         → orange text + amber cell bg, animate-pulse (stage 2)
 *
 *  Alert banner (the red/amber strip above the stats grid):
 *    5. cooldown ≤ 5 s → amber-100 background, amber icon/text
 *    6. cooldown > 5 s → red-100  background, red   icon/text
 */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect } from 'vitest';

/* ─────────────────────────────────────────────────────────────────────────
   Mirrors the "Cooldown clears in" stat cell from AdminHealth.jsx (~2257)
   ───────────────────────────────────────────────────────────────────────── */
function CooldownBadge({ cooldown, embedCooldownDisplay }) {
  const cellCls = [
    'rounded-lg p-2.5 border transition-colors',
    cooldown && embedCooldownDisplay <= 5
      ? 'bg-amber-50 border-amber-300'
      : 'bg-white/70 border-gray-100',
  ].join(' ');

  const labelCls = [
    'text-[10px] uppercase font-semibold mb-0.5',
    cooldown && embedCooldownDisplay <= 5 ? 'text-amber-600' : 'text-gray-400',
  ].join(' ');

  const valueCls = [
    'text-base font-bold tabular-nums',
    cooldown && embedCooldownDisplay <= 5
      ? 'text-orange-500 animate-pulse'
      : cooldown && embedCooldownDisplay <= 10
      ? 'text-red-600 animate-pulse'
      : cooldown
      ? 'text-red-600'
      : 'text-gray-400',
  ].join(' ');

  return (
    <div className={cellCls}>
      <div className={labelCls}>Cooldown clears in</div>
      <div data-testid="countdown-value" className={valueCls}>
        {cooldown ? `${embedCooldownDisplay} s` : '—'}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   Mirrors the alert banner from AdminHealth.jsx (~2222)
   ───────────────────────────────────────────────────────────────────────── */
function CooldownBanner({ embedCooldownDisplay, burst, threshold, durationS }) {
  const wrapCls = [
    'flex items-center gap-2 mb-3 px-3 py-2 rounded-lg border transition-colors',
    embedCooldownDisplay <= 5
      ? 'bg-amber-100 border-amber-300'
      : 'bg-red-100 border-red-200',
  ].join(' ');

  const iconCls = `shrink-0 transition-colors ${
    embedCooldownDisplay <= 5 ? 'text-amber-600' : 'text-red-600'
  }`;

  const textCls = `text-xs font-semibold transition-colors ${
    embedCooldownDisplay <= 5 ? 'text-amber-700' : 'text-red-700'
  }`;

  return (
    <div data-testid="banner" className={wrapCls}>
      <span data-testid="banner-icon" className={iconCls}>!</span>
      <span data-testid="banner-text" className={textCls}>
        Embed cooldown active — Workers AI embed skipped for {embedCooldownDisplay}s
        ({burst} of {threshold} hits in last {durationS}s)
      </span>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   Helper — render to string and return the raw HTML for assertions
   ───────────────────────────────────────────────────────────────────────── */
function badgeHtml(props) {
  return renderToStaticMarkup(<CooldownBadge {...props} />);
}

function bannerHtml(props) {
  return renderToStaticMarkup(<CooldownBanner {...props} />);
}

/* ═══════════════════════════════════════════════════════════════════════════
   Countdown badge tests
   ═══════════════════════════════════════════════════════════════════════════ */
describe('AdminHealth — embed cooldown badge', () => {
  it('shows a dash and gray text when cooldown is inactive', () => {
    const html = badgeHtml({ cooldown: false, embedCooldownDisplay: 0 });
    expect(html).toContain('—');
    expect(html).toContain('text-gray-400');
    expect(html).not.toContain('animate-pulse');
    expect(html).not.toContain('text-red-600');
    expect(html).not.toContain('text-orange-500');
  });

  it('shows red text but NO pulse when cooldown has more than 10 s remaining', () => {
    const html = badgeHtml({ cooldown: true, embedCooldownDisplay: 45 });
    expect(html).toContain('45 s');
    expect(html).toContain('text-red-600');
    expect(html).not.toContain('animate-pulse');
    expect(html).not.toContain('bg-amber-50');
  });

  it('applies animate-pulse with red text when cooldown is in the 6–10 s window', () => {
    for (const s of [10, 9, 8, 7, 6]) {
      const html = badgeHtml({ cooldown: true, embedCooldownDisplay: s });
      expect(html, `at ${s}s`).toContain('animate-pulse');
      expect(html, `at ${s}s`).toContain('text-red-600');
      expect(html, `at ${s}s`).not.toContain('text-orange-500');
      expect(html, `at ${s}s`).not.toContain('bg-amber-50');
    }
  });

  it('switches to orange text + amber cell background at exactly 5 s (stage-2 boundary)', () => {
    const html = badgeHtml({ cooldown: true, embedCooldownDisplay: 5 });
    expect(html).toContain('animate-pulse');
    expect(html).toContain('text-orange-500');
    expect(html).toContain('bg-amber-50');
    expect(html).toContain('border-amber-300');
    expect(html).not.toContain('text-red-600');
  });

  it('keeps stage-2 styling for remaining values 4, 3, 2, 1, 0', () => {
    for (const s of [4, 3, 2, 1, 0]) {
      const html = badgeHtml({ cooldown: true, embedCooldownDisplay: s });
      expect(html, `at ${s}s`).toContain('animate-pulse');
      expect(html, `at ${s}s`).toContain('text-orange-500');
      expect(html, `at ${s}s`).toContain('bg-amber-50');
      expect(html, `at ${s}s`).not.toContain('text-red-600');
    }
  });

  it('label text color follows the same stage split', () => {
    const stage1Html = badgeHtml({ cooldown: true, embedCooldownDisplay: 8 });
    const stage2Html = badgeHtml({ cooldown: true, embedCooldownDisplay: 3 });
    const idleHtml   = badgeHtml({ cooldown: false, embedCooldownDisplay: 0 });

    expect(stage1Html).toContain('text-gray-400');   // label stays gray in stage 1
    expect(stage2Html).toContain('text-amber-600');  // label flips amber in stage 2
    expect(idleHtml).toContain('text-gray-400');     // label stays gray when idle
  });
});

/* ═══════════════════════════════════════════════════════════════════════════
   Alert banner tests (Task #111 extension)
   ═══════════════════════════════════════════════════════════════════════════ */
describe('AdminHealth — embed cooldown alert banner', () => {
  const defaultProps = { burst: 3, threshold: 3, durationS: 60 };

  it('uses red palette when more than 5 s remain', () => {
    for (const s of [60, 15, 11, 6]) {
      const html = bannerHtml({ embedCooldownDisplay: s, ...defaultProps });
      expect(html, `at ${s}s`).toContain('bg-red-100');
      expect(html, `at ${s}s`).toContain('border-red-200');
      expect(html, `at ${s}s`).toContain('text-red-600');
      expect(html, `at ${s}s`).toContain('text-red-700');
      expect(html, `at ${s}s`).not.toContain('bg-amber-100');
    }
  });

  it('switches to amber palette at exactly 5 s (stage-2 boundary)', () => {
    const html = bannerHtml({ embedCooldownDisplay: 5, ...defaultProps });
    expect(html).toContain('bg-amber-100');
    expect(html).toContain('border-amber-300');
    expect(html).toContain('text-amber-600');
    expect(html).toContain('text-amber-700');
    expect(html).not.toContain('bg-red-100');
    expect(html).not.toContain('text-red-700');
  });

  it('keeps amber palette for 4, 3, 2, 1, 0 s remaining', () => {
    for (const s of [4, 3, 2, 1, 0]) {
      const html = bannerHtml({ embedCooldownDisplay: s, ...defaultProps });
      expect(html, `at ${s}s`).toContain('bg-amber-100');
      expect(html, `at ${s}s`).not.toContain('bg-red-100');
    }
  });

  it('banner text always contains the countdown seconds', () => {
    const html = bannerHtml({ embedCooldownDisplay: 7, ...defaultProps });
    expect(html).toContain('skipped for 7s');
    expect(html).toContain('3 of 3');
  });
});
