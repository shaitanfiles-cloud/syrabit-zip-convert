import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect } from 'vitest';
import CronHealthPill, { ageLabel } from './CronHealthPill';

// Task #837 — Task #835 extracted the shared <CronHealthPill> used by
// the Trustpilot refresh and Cloudflare WAF drift admin tiles. The
// status -> colour/icon/pill-label mapping (healthy=emerald,
// silent=red, degraded=amber, never_observed/not_configured=gray,
// unknown=gray) lives in one place now. Lock the mapping down so a
// well-meant refactor of the colour ladder cannot silently flip the
// alarm states.

const STATUS_EXPECTATIONS = {
  healthy: {
    container: ['bg-emerald-50', 'border-emerald-200'],
    headerColor: 'text-emerald-600',
    pill: ['bg-emerald-100', 'text-emerald-700', 'border-emerald-200'],
    pillLabel: 'CRON HEALTHY',
    iconColor: 'text-emerald-500',
  },
  silent: {
    container: ['bg-red-50', 'border-red-200'],
    headerColor: 'text-red-600',
    pill: ['bg-red-100', 'text-red-700', 'border-red-200'],
    pillLabel: 'CRON SILENT',
    iconColor: 'text-red-500',
  },
  degraded: {
    container: ['bg-amber-50', 'border-amber-200'],
    headerColor: 'text-amber-600',
    pill: ['bg-amber-100', 'text-amber-700', 'border-amber-200'],
    pillLabel: 'CRON DEGRADED',
    iconColor: 'text-amber-500',
  },
  never_observed: {
    container: ['bg-gray-50', 'border-gray-200'],
    headerColor: 'text-gray-500',
    pill: ['bg-gray-100', 'text-gray-600', 'border-gray-200'],
    pillLabel: 'NEVER OBSERVED',
    iconColor: 'text-gray-400',
  },
  not_configured: {
    container: ['bg-gray-50', 'border-gray-200'],
    headerColor: 'text-gray-500',
    pill: ['bg-gray-100', 'text-gray-600', 'border-gray-200'],
    pillLabel: 'NOT CONFIGURED',
    iconColor: 'text-gray-400',
  },
};

const HEADER_TEXT_BY_STATUS = {
  healthy: 'Cron healthy',
  silent: 'Cron silent',
  degraded: 'Cron degraded',
  never_observed: 'Cron never observed',
  not_configured: 'Cron not configured',
  unknown: 'Cron — status unknown',
};

const renderPill = (overrides = {}) =>
  renderToStaticMarkup(
    <CronHealthPill
      data={overrides.data ?? null}
      loading={overrides.loading ?? false}
      onRefresh={overrides.onRefresh ?? (() => {})}
      testId={overrides.testId ?? 'foo'}
      headerTextByStatus={overrides.headerTextByStatus ?? HEADER_TEXT_BY_STATUS}
      pillLabelByStatus={overrides.pillLabelByStatus}
      defaultWorkflowUrl={overrides.defaultWorkflowUrl ?? 'https://example.com/workflow'}
      renderSubText={overrides.renderSubText}
      renderExtraActions={overrides.renderExtraActions}
    />
  );

const extractAttrValue = (html, testId, attr) => {
  const re = new RegExp(
    `<[^>]*data-testid="${testId}"[^>]*\\s${attr}="([^"]*)"|<[^>]*\\s${attr}="([^"]*)"[^>]*data-testid="${testId}"`
  );
  const m = html.match(re);
  return m ? (m[1] ?? m[2]) : null;
};

describe('CronHealthPill — status to colour/icon/label mapping', () => {
  for (const [status, expected] of Object.entries(STATUS_EXPECTATIONS)) {
    it(`maps status="${status}" to the locked tile/header/pill/icon classes and label`, () => {
      const html = renderPill({ data: { status, workflowUrl: 'https://example.com/wf' } });

      const tileCls = extractAttrValue(html, 'foo-tile', 'class') || '';
      for (const cls of expected.container) {
        expect(tileCls).toContain(cls);
      }

      const headerCls = extractAttrValue(html, 'foo-status', 'class') || '';
      expect(headerCls).toContain(expected.headerColor);

      const pillCls = extractAttrValue(html, 'foo-pill', 'class') || '';
      for (const cls of expected.pill) {
        expect(pillCls).toContain(cls);
      }

      // Pill text is the locked label for this status.
      const pillTextRe = new RegExp(
        `data-testid="foo-pill"[^>]*>\\s*${expected.pillLabel}\\s*<`
      );
      expect(html).toMatch(pillTextRe);

      // Icon colour is locked alongside the colour family.
      expect(html).toContain(expected.iconColor);

      // Header text is sourced from headerTextByStatus[status].
      expect(html).toContain(HEADER_TEXT_BY_STATUS[status]);
    });
  }

  it('treats null/missing data as the gray "unknown" state with the unknown header text', () => {
    const html = renderPill({ data: null });

    const tileCls = extractAttrValue(html, 'foo-tile', 'class') || '';
    expect(tileCls).toContain('bg-gray-50');
    expect(tileCls).toContain('border-gray-200');

    const headerCls = extractAttrValue(html, 'foo-status', 'class') || '';
    expect(headerCls).toContain('text-gray-500');

    const pillCls = extractAttrValue(html, 'foo-pill', 'class') || '';
    expect(pillCls).toContain('bg-gray-100');
    expect(pillCls).toContain('text-gray-600');
    expect(pillCls).toContain('border-gray-200');

    // No mapping entry exists for "unknown" -> default pill label is "UNKNOWN".
    expect(html).toMatch(/data-testid="foo-pill"[^>]*>\s*UNKNOWN\s*</);

    // Header falls back to headerTextByStatus.unknown.
    expect(html).toContain('Cron — status unknown');

    // Gray clock icon is used for the unknown state.
    expect(html).toContain('text-gray-400');
  });

  // NOTE: An explicit `data.status === 'unknown'` is intentionally NOT
  // tested as "gray" because the current component only routes to the
  // gray branch via `!data` (or status in {never_observed,
  // not_configured}). A literal "unknown" status string with a present
  // data object falls through to the emerald default — that quirk is
  // out of scope for this colour-pinning suite and would be its own fix.

  it('treats data with _error as the unknown/gray state', () => {
    const html = renderPill({ data: { _error: true, status: 'healthy' } });

    const tileCls = extractAttrValue(html, 'foo-tile', 'class') || '';
    expect(tileCls).toContain('bg-gray-50');
    expect(tileCls).toContain('border-gray-200');

    const pillCls = extractAttrValue(html, 'foo-pill', 'class') || '';
    expect(pillCls).toContain('bg-gray-100');
  });

  it('lets pillLabelByStatus override the default pill label for a status', () => {
    const html = renderPill({
      data: { status: 'healthy' },
      pillLabelByStatus: { healthy: 'TRUSTPILOT OK' },
    });
    expect(html).toMatch(/data-testid="foo-pill"[^>]*>\s*TRUSTPILOT OK\s*</);
  });
});

describe('CronHealthPill — testId templating', () => {
  it('renders all interactive testIds using the `${testId}-…` template', () => {
    const html = renderPill({
      testId: 'foo',
      data: { status: 'healthy', workflowUrl: 'https://example.com/wf' },
    });

    expect(html).toContain('data-testid="foo-tile"');
    expect(html).toContain('data-testid="foo-status"');
    expect(html).toContain('data-testid="foo-pill"');
    expect(html).toContain('data-testid="foo-run-link"');
    expect(html).toContain('data-testid="button-refresh-foo"');
  });

  it('changes every templated testId when the testId prop changes', () => {
    const html = renderPill({
      testId: 'cf-waf',
      data: { status: 'silent', workflowUrl: 'https://example.com/wf' },
    });

    expect(html).toContain('data-testid="cf-waf-tile"');
    expect(html).toContain('data-testid="cf-waf-status"');
    expect(html).toContain('data-testid="cf-waf-pill"');
    expect(html).toContain('data-testid="cf-waf-run-link"');
    expect(html).toContain('data-testid="button-refresh-cf-waf"');

    // No leftover ids from the other test's testId value.
    expect(html).not.toContain('data-testid="foo-tile"');
    expect(html).not.toContain('data-testid="button-refresh-foo"');
  });
});

describe('ageLabel helper', () => {
  const cases = [
    { input: null, expected: null, why: 'null input -> null' },
    { input: undefined, expected: null, why: 'undefined input -> null' },
    { input: 0, expected: '0s', why: '0 seconds -> "0s"' },
    { input: 1, expected: '1s', why: 'sub-minute -> seconds' },
    { input: 59, expected: '59s', why: 'just under 1m -> seconds' },
    { input: 60, expected: '1m', why: 'exactly 60s -> minutes' },
    { input: 119, expected: '1m', why: 'under 2m -> 1m (floor)' },
    { input: 3599, expected: '59m', why: 'just under 1h -> minutes' },
    { input: 3600, expected: '1h', why: 'exactly 1h -> hours' },
    { input: 86399, expected: '23h', why: 'just under 1d -> hours' },
    { input: 86400, expected: '1d', why: 'exactly 1d -> days' },
    { input: 172800, expected: '2d', why: '2d -> days' },
    { input: -5, expected: '0s', why: 'negative input clamped to 0s' },
  ];

  for (const { input, expected, why } of cases) {
    it(`${why} (ageLabel(${String(input)}) === ${JSON.stringify(expected)})`, () => {
      expect(ageLabel(input)).toBe(expected);
    });
  }
});
