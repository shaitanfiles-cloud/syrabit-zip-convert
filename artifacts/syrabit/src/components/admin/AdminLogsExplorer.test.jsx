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
