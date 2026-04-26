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
    // Task #882 — primary refresh testId follows the AdminHealth
    // cron-pill convention (replit.md § "AdminHealth cron-pill testId
    // convention"). The legacy `button-refresh-<prefix>` form is
    // preserved on `data-testid-legacy` for external selectors.
    expect(html).toContain('data-testid="foo-refresh"');
    expect(html).toContain('data-testid-legacy="button-refresh-foo"');
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
    expect(html).toContain('data-testid="cf-waf-refresh"');
    expect(html).toContain('data-testid-legacy="button-refresh-cf-waf"');

    // No leftover ids from the other test's testId value.
    expect(html).not.toContain('data-testid="foo-tile"');
    expect(html).not.toContain('data-testid="foo-refresh"');
    expect(html).not.toContain('data-testid-legacy="button-refresh-foo"');
  });
});

describe('CronHealthPill — workflow URL fallback', () => {
  // Task #839 — every wrapper (CfWafDriftCronPill, TrustpilotCronPill,
  // …) passes a `defaultWorkflowUrl` so the GitHub Actions deep-link
  // still points somewhere sensible BEFORE the heartbeat row carries
  // a `workflowUrl`. The component prefers the per-heartbeat URL when
  // present, and falls back to `defaultWorkflowUrl` otherwise. Both
  // hyperlinks (the pill itself and the "Runs" link beside it) must
  // resolve to the same URL — they're the same link rendered twice.
  // Pin both behaviours so a future refactor of the fallback ladder
  // doesn't silently break either link.
  const DEFAULT_URL = 'https://github.com/example/actions/workflows/x.yml';
  const DATA_URL = 'https://github.com/example/actions/runs/9999';

  it('uses data.workflowUrl when the heartbeat carries one (overrides defaultWorkflowUrl)', () => {
    const html = renderPill({
      data: { status: 'healthy', workflowUrl: DATA_URL },
      defaultWorkflowUrl: DEFAULT_URL,
    });
    expect(extractAttrValue(html, 'foo-pill', 'href')).toBe(DATA_URL);
    expect(extractAttrValue(html, 'foo-run-link', 'href')).toBe(DATA_URL);
  });

  it('falls back to defaultWorkflowUrl when data has no workflowUrl', () => {
    const html = renderPill({
      data: { status: 'healthy' }, // no workflowUrl
      defaultWorkflowUrl: DEFAULT_URL,
    });
    expect(extractAttrValue(html, 'foo-pill', 'href')).toBe(DEFAULT_URL);
    expect(extractAttrValue(html, 'foo-run-link', 'href')).toBe(DEFAULT_URL);
  });

  it('falls back to defaultWorkflowUrl when data is null entirely', () => {
    const html = renderPill({
      data: null,
      defaultWorkflowUrl: DEFAULT_URL,
    });
    expect(extractAttrValue(html, 'foo-pill', 'href')).toBe(DEFAULT_URL);
    expect(extractAttrValue(html, 'foo-run-link', 'href')).toBe(DEFAULT_URL);
  });

  it('falls back to defaultWorkflowUrl when data is the _error sentinel (treated as no data)', () => {
    // The `_error` short-circuit replaces `data` with null inside the
    // component, so `data._error.workflowUrl` (if it ever existed)
    // must NOT be honoured — the URL must come from defaultWorkflowUrl.
    const html = renderPill({
      data: { _error: true, workflowUrl: DATA_URL, status: 'healthy' },
      defaultWorkflowUrl: DEFAULT_URL,
    });
    expect(extractAttrValue(html, 'foo-pill', 'href')).toBe(DEFAULT_URL);
    expect(extractAttrValue(html, 'foo-run-link', 'href')).toBe(DEFAULT_URL);
  });

  it('honours data.workflowUrl across every non-error status, not just healthy', () => {
    // Sanity: the data.workflowUrl preference is independent of the
    // status colour ladder. A silent or degraded heartbeat that
    // carries its own URL must still surface it.
    for (const status of ['silent', 'degraded', 'never_observed', 'not_configured']) {
      const html = renderPill({
        data: { status, workflowUrl: DATA_URL },
        defaultWorkflowUrl: DEFAULT_URL,
      });
      expect(extractAttrValue(html, 'foo-pill', 'href')).toBe(DATA_URL);
      expect(extractAttrValue(html, 'foo-run-link', 'href')).toBe(DATA_URL);
    }
  });
});

// Task #902 — alerter-state caption surfaced under subText.
// `formatAlertStateCaption` is itself unit-tested in
// `cronCaptionHelpers.test.js`; here we just verify the pill wires
// it up correctly: renders nothing without alertState, renders the
// caption testId when provided, and uses amber-vs-gray text colour
// based on `inDebounce`.
describe('alertState rendering', () => {
  it('renders no alert-state caption when no alertState prop is passed', () => {
    const html = renderToStaticMarkup(
      <CronHealthPill
        data={{ status: 'silent' }}
        testId="foo"
        defaultWorkflowUrl="https://example.test/workflow"
      />,
    );
    expect(html).not.toContain('foo-alert-state');
  });

  it('renders no alert-state caption when alertState.present is false', () => {
    // Brand-new deployment: alerter has never fired. The pill must
    // not render an orphan "last paged: never" line — the colour
    // already conveys "no page has been sent".
    const html = renderToStaticMarkup(
      <CronHealthPill
        data={{ status: 'healthy' }}
        testId="foo"
        defaultWorkflowUrl="https://example.test/workflow"
        alertState={{ present: false, lastAlertAt: null,
                      lastAlertAgeSeconds: null, inDebounce: false,
                      debounceRemainingSeconds: null }}
      />,
    );
    expect(html).not.toContain('foo-alert-state');
  });

  it('renders the caption in amber when inDebounce=true', () => {
    // Amber so admins glance at the pill and know "yes we paged,
    // and the next page is auto-suppressed for another ~22h".
    const html = renderToStaticMarkup(
      <CronHealthPill
        data={{ status: 'silent' }}
        testId="foo"
        defaultWorkflowUrl="https://example.test/workflow"
        alertState={{
          present: true,
          lastAlertAt: '2026-04-25T00:00:00+00:00',
          lastAlertAgeSeconds: 2 * 3600,
          inDebounce: true,
          debounceRemainingSeconds: 22 * 3600,
        }}
      />,
    );
    expect(html).toContain('foo-alert-state');
    expect(html).toContain('last paged 2h ago · in debounce ~22h remaining');
    // Amber colour class on the caption <p>.
    expect(html).toMatch(/text-amber-600[^"]*"[^>]*data-testid="foo-alert-state"/);
  });

  it('renders the caption in gray when inDebounce=false', () => {
    // Past the realert window: still informative ("we did page on
    // this") but neutral colour because the next poll can re-page.
    const html = renderToStaticMarkup(
      <CronHealthPill
        data={{ status: 'silent' }}
        testId="foo"
        defaultWorkflowUrl="https://example.test/workflow"
        alertState={{
          present: true,
          lastAlertAt: '2026-04-23T00:00:00+00:00',
          lastAlertAgeSeconds: 30 * 3600,
          inDebounce: false,
          debounceRemainingSeconds: null,
        }}
      />,
    );
    expect(html).toContain('foo-alert-state');
    expect(html).toContain('last paged 1d ago');
    expect(html).not.toContain('in debounce');
    expect(html).toMatch(/text-gray-500[^"]*"[^>]*data-testid="foo-alert-state"/);
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
