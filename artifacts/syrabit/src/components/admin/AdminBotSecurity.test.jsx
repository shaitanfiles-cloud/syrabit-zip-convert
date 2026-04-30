/**
 * Task #1 — AdminBotSecurity component Vitest tests.
 *
 * Uses renderToStaticMarkup (synchronous, no effects). The component's
 * outer panel renders the "Bot Security" heading, but sub-sections with
 * their own loading states emit their loading text first.
 */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/utils/api', () => ({
  adminGetSpoofedBots:              vi.fn(() => Promise.resolve({ data: { bots: [] } })),
  adminGetBlockedIps:               vi.fn(() => Promise.resolve({ data: { blocked_ips: [] } })),
  adminGetBlockTrends:              vi.fn(() => Promise.resolve({ data: [] })),
  adminBlockIp:                     vi.fn(() => Promise.resolve({ data: {} })),
  adminUnblockIp:                   vi.fn(() => Promise.resolve({ data: {} })),
  adminGetAlertSettings:            vi.fn(() => Promise.resolve({ data: {} })),
  adminUpdateAlertSettings:         vi.fn(() => Promise.resolve({ data: {} })),
  adminTestAlertDelivery:           vi.fn(() => Promise.resolve({ data: {} })),
  adminGetTtlMonitor:               vi.fn(() => Promise.resolve({ data: {} })),
  adminGetCollectionSizeHistory:    vi.fn(() => Promise.resolve({ data: [] })),
  adminGetAlerts:                   vi.fn(() => Promise.resolve({ data: { alerts: [] } })),
  adminAcknowledgeAlert:            vi.fn(() => Promise.resolve({ data: {} })),
  adminAcknowledgeAllAlerts:        vi.fn(() => Promise.resolve({ data: {} })),
  adminBackfillThresholds:          vi.fn(() => Promise.resolve({ data: {} })),
  adminSendReviewPromptWeeklyDigest:vi.fn(() => Promise.resolve({ data: {} })),
  adminGetAlertCooldowns:           vi.fn(() => Promise.resolve({ data: {} })),
  adminReleaseAlertCooldown:        vi.fn(() => Promise.resolve({ data: {} })),
  API_BASE: 'http://localhost:8000',
}));

vi.mock('recharts', () => ({
  LineChart:           ({ children }) => <div>{children}</div>,
  AreaChart:           ({ children }) => <div>{children}</div>,
  BarChart:            ({ children }) => <div>{children}</div>,
  Line:                () => null,
  Area:                () => null,
  Bar:                 () => null,
  XAxis:               () => null,
  YAxis:               () => null,
  CartesianGrid:       () => null,
  Tooltip:             () => null,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  ReferenceLine:       () => null,
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('@/components/ErrorBoundary', () => ({
  SectionErrorBoundary: ({ children }) => <div>{children}</div>,
}));

import AdminBotSecurity from './AdminBotSecurity';

describe('AdminBotSecurity', () => {
  it('renders without throwing — shows loading state initially', () => {
    // The component starts in loading state — initial render shows spinner text.
    const html = renderToStaticMarkup(
      <AdminBotSecurity adminToken="test-token" />,
    );
    expect(html.length).toBeGreaterThan(0);
    // The component emits some loading indicator or animate-spin class.
    expect(html.toLowerCase()).toMatch(/loading|animate-spin/i);
  });

  it('renders with an empty adminToken without throwing', () => {
    expect(() =>
      renderToStaticMarkup(<AdminBotSecurity adminToken="" />),
    ).not.toThrow();
  });
});
