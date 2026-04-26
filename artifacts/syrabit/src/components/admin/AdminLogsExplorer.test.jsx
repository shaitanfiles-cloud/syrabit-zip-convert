/**
 * Task #944 — AdminLogsExplorer component tests.
 *
 * The deep DOM/event story is covered by the e2e admin sweep — these
 * tests just lock down the SSR markup so a refactor of the column
 * layout, badge palette, or filter chip wiring trips a fast unit test
 * before reaching staging.
 */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/utils/api', () => ({
  adminLogsList:        vi.fn(() => Promise.resolve({ data: { logs: [], total: 0 } })),
  adminLogsStatus:      vi.fn(() => Promise.resolve({ data: {
    paused: false, ttl_days: 14, ingest_token_configured: true,
  } })),
  adminLogsTrace:       vi.fn(() => Promise.resolve({ data: { logs: [] } })),
  adminLogsPause:       vi.fn(),
  adminLogsResume:      vi.fn(),
  adminLogsRotateToken: vi.fn(),
  adminLogsClear:       vi.fn(),
  adminLogsExportUrl:   vi.fn(() => 'https://example.com/export'),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/components/ErrorBoundary', () => ({
  SectionErrorBoundary: ({ children }) => <div>{children}</div>,
}));

import AdminLogsExplorer from './AdminLogsExplorer';

describe('AdminLogsExplorer', () => {
  it('renders the title and the source filter chips', () => {
    const html = renderToStaticMarkup(
      <AdminLogsExplorer adminToken="t" />,
    );
    expect(html).toContain('Unified Logs');
    // Source filter chips
    expect(html).toContain('Edge worker');
    expect(html).toContain('Cloudflare GraphQL');
    expect(html).toContain('Backend (FastAPI)');
    expect(html).toContain('Cron / jobs');
  });

  it('renders the level filter chips', () => {
    const html = renderToStaticMarkup(
      <AdminLogsExplorer adminToken="t" />,
    );
    for (const lv of ['debug', 'info', 'warn', 'error']) {
      expect(html.toLowerCase()).toContain(lv);
    }
  });

  it('renders the time-window preset buttons', () => {
    const html = renderToStaticMarkup(
      <AdminLogsExplorer adminToken="t" />,
    );
    for (const lbl of ['Last 15m', 'Last 1h', 'Last 24h', 'Last 7d']) {
      expect(html).toContain(lbl);
    }
  });

  it('renders all the action buttons (refresh, export, pause, clear)', () => {
    const html = renderToStaticMarkup(
      <AdminLogsExplorer adminToken="t" />,
    );
    expect(html).toContain('Refresh');
    expect(html).toContain('Live tail');
    expect(html).toContain('CSV');
    expect(html).toContain('NDJSON');
    expect(html).toContain('Rotate token');
    expect(html).toContain('Clear');
  });

  it('renders the table header columns', () => {
    const html = renderToStaticMarkup(
      <AdminLogsExplorer adminToken="t" />,
    );
    for (const col of ['Time', 'Source', 'Level', 'Status', 'Route',
                       'Country / Colo', 'Cache', 'Duration', 'Correlation']) {
      expect(html).toContain(col);
    }
  });

});

// Live DOM tests for row expansion + copy-correlation-id workflows.
import { describe as describe2, it as it2, expect as expect2, vi as vi2, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

describe2('AdminLogsExplorer — row expansion + copy CID', () => {
  afterEach(() => {
    cleanup();
    vi2.clearAllMocks();
  });

  it2('expands a row to show full JSON payload, and copies the correlation id', async () => {
    const apiMod = await import('@/utils/api');
    const sampleRow = {
      _id: 'edge_abcdef123',
      timestamp: '2026-04-26T10:00:00.000Z',
      received_at: '2026-04-26T10:00:01.000Z',
      source: 'edge',
      level: 'error',
      status: 502,
      method: 'GET',
      route: '/api/test',
      duration_ms: 1234,
      country: 'IN',
      colo: 'BLR',
      cache: 'miss',
      correlation_id: 'corr-xyz-123',
      message: 'origin returned 502',
    };
    apiMod.adminLogsList.mockResolvedValue({
      data: { logs: [sampleRow], total: 1, total_capped: false, next_before: null },
    });
    apiMod.adminLogsStatus.mockResolvedValue({ data: {
      paused: false, ttl_days: 14, ingest_token_configured: true,
      backend_sample_rate: 0.05, max_ingest_batch: 500, cf_pull_interval_s: 60,
    } });
    const writeText = vi2.fn(() => Promise.resolve());
    Object.defineProperty(global.navigator, 'clipboard', {
      value: { writeText }, configurable: true,
    });

    render(<AdminLogsExplorer adminToken="t" />);

    // The row should appear once the mocked list resolves.
    await waitFor(() => {
      expect2(screen.getByTestId('row-expand-0')).toBeTruthy();
    });

    // Initially the JSON payload row is not in the DOM.
    expect2(screen.queryByTestId('row-json-0')).toBeNull();

    // Clicking the chevron expands the row and shows full JSON.
    fireEvent.click(screen.getByTestId('row-expand-0'));
    const pre = await screen.findByTestId('row-json-0');
    expect2(pre.textContent).toContain('"correlation_id"');
    expect2(pre.textContent).toContain('corr-xyz-123');
    expect2(pre.textContent).toContain('"_id"');

    // Copy correlation id button calls clipboard with the cid.
    fireEvent.click(screen.getByTestId('copy-cid-0'));
    await waitFor(() => expect2(writeText).toHaveBeenCalledWith('corr-xyz-123'));
  });
});
