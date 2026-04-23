import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('@/utils/api', () => ({
  adminGetDiagnostics: vi.fn(),
  adminDisableBreakGlass: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

import BreakGlassBanner from './BreakGlassBanner.jsx';
import { adminGetDiagnostics } from '@/utils/api';

const BANNER = 'break-glass-banner';

describe('BreakGlassBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when adminToken is null (no fetch fired)', async () => {
    const { container } = render(<BreakGlassBanner adminToken={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(adminGetDiagnostics).not.toHaveBeenCalled();
  });

  it('renders nothing when diagnostics report break_glass_active=false', async () => {
    adminGetDiagnostics.mockResolvedValueOnce({
      data: { cf_access: { break_glass_active: false, break_glass_source: null } },
    });

    render(<BreakGlassBanner adminToken="admin.jwt" />);

    // Wait for the initial fetch to settle, then assert the banner is hidden.
    await waitFor(() => expect(adminGetDiagnostics).toHaveBeenCalledWith('admin.jwt'));
    expect(screen.queryByTestId(BANNER)).toBeNull();
  });

  it('renders the red banner with source copy when break_glass_active=true', async () => {
    adminGetDiagnostics.mockResolvedValueOnce({
      data: { cf_access: { break_glass_active: true, break_glass_source: 'env' } },
    });

    render(<BreakGlassBanner adminToken="admin.jwt" />);

    const banner = await screen.findByTestId(BANNER);
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(/Cloudflare Access is bypassed/i);
    expect(banner).toHaveTextContent(/via env/);
    // Action affordances are present.
    expect(screen.getByTestId('break-glass-banner-disable')).toBeInTheDocument();
    expect(screen.getByTestId('break-glass-banner-recheck')).toBeInTheDocument();
    expect(screen.getByTestId('break-glass-banner-runbook')).toBeInTheDocument();
    // No stale badge on the happy path.
    expect(screen.queryByTestId('break-glass-banner-stale')).toBeNull();
  });

  it('stays hidden when the diagnostics fetch errors before any successful poll', async () => {
    adminGetDiagnostics.mockRejectedValueOnce(new Error('network down'));

    render(<BreakGlassBanner adminToken="admin.jwt" />);

    // Drive the promise rejection to settle.
    await waitFor(() => expect(adminGetDiagnostics).toHaveBeenCalled());
    // Without a prior successful poll, a transient error must NOT pop the
    // banner — that would be a false-positive paging incident.
    expect(screen.queryByTestId(BANNER)).toBeNull();
  });
});
