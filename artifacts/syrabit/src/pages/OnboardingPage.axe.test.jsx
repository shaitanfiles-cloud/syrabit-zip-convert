/**
 * Task #194 — OnboardingPage: axe accessibility audit.
 *
 * Covers two key render states of the onboarding wizard:
 *  - Board-selection step while boards are still loading (Loader2 spinner)
 *  - Board-selection step after boards have resolved (board buttons visible)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { axe, toHaveNoViolations } from 'jest-axe';
import { render, act } from '@testing-library/react';
import React from 'react';

expect.extend(toHaveNoViolations);

const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

const mockRefreshUser = vi.fn();
const mockUpdateUser  = vi.fn();
const mockLogout      = vi.fn();

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user:              { email: 'test@example.com', onboarding_done: false },
    authChecked:       true,
    justAuthenticated: { current: true },
    refreshUser:       mockRefreshUser,
    updateUser:        mockUpdateUser,
    logout:            mockLogout,
  }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('@/components/Logo', () => ({
  LogoMark: () => <div data-testid="logo-mark" aria-hidden="true" />,
}));

const mockGetBoards = vi.fn();
vi.mock('@/utils/api', () => ({
  getBoards:      (...args) => mockGetBoards(...args),
  getClasses:     vi.fn().mockResolvedValue({ data: [] }),
  getStreams:      vi.fn().mockResolvedValue({ data: [] }),
  saveOnboarding: vi.fn().mockResolvedValue({}),
}));

import OnboardingPage from './OnboardingPage';

const SAMPLE_BOARDS = [
  { id: 'b1', name: 'AHSEC', description: 'Assam Higher Secondary Education Council' },
  { id: 'b2', name: 'SEBA', description: 'Board of Secondary Education, Assam' },
];

beforeEach(() => {
  mockNavigate.mockClear();
  mockGetBoards.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('OnboardingPage — axe accessibility audit', () => {
  it('has no axe violations while boards are loading (spinner state)', async () => {
    mockGetBoards.mockReturnValue(new Promise(() => {}));
    let container;
    await act(async () => {
      ({ container } = render(<OnboardingPage />));
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations when boards have loaded (board-selection step)', async () => {
    mockGetBoards.mockResolvedValue({ data: SAMPLE_BOARDS });
    let container;
    await act(async () => {
      ({ container } = render(<OnboardingPage />));
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
