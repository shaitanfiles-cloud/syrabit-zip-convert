/**
 * Task #181 — SignupPage: handleSubmit post-registration redirect tests.
 *
 * Verifies that after a successful signup the page navigates to the
 * correct route based on the returned user object:
 *   - role === 'staff' or 'admin'  →  /staff
 *   - any other role (new user)    →  /onboarding
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import React from 'react';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
}));

const mockSignup = vi.fn();
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ signup: mockSignup }),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('@/hooks/usePublicStats', () => ({
  usePublicStats: () => ({ total_users: 500 }),
}));

vi.mock('@/components/Logo', () => ({
  LogoFull: () => <div data-testid="logo" />,
}));

vi.mock('@/components/GoogleSignInButton', () => ({
  default: () => <div data-testid="google-btn" />,
}));

vi.mock('@/lib/authErrors', () => ({
  formatAuthError: (_err, fallback) => fallback,
}));

import SignupPage from './SignupPage';
import { toast } from 'sonner';

async function triggerSignup() {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('Your name'), {
      target: { value: 'Test User' },
    });
    fireEvent.change(screen.getByTestId('auth-email-input'), {
      target: { value: 'user@test.com' },
    });
    fireEvent.change(screen.getByTestId('auth-password-input'), {
      target: { value: 'Password1!' },
    });
    const [confirmInput] = screen.getAllByPlaceholderText('••••••••').slice(-1);
    fireEvent.change(confirmInput, { target: { value: 'Password1!' } });
    fireEvent.click(screen.getByRole('button', { name: /agree to terms/i }));
    fireEvent.click(screen.getByRole('button', { name: /consent to data processing/i }));
  });
  await act(async () => {
    fireEvent.click(screen.getByTestId('auth-submit-button'));
  });
  await act(async () => {});
}

beforeEach(() => {
  mockNavigate.mockClear();
  mockSignup.mockClear();
  vi.mocked(toast.success).mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('SignupPage — handleSubmit redirect logic', () => {
  it('navigates to /onboarding when user has onboarding_done=false', async () => {
    mockSignup.mockResolvedValueOnce({ role: '', onboarding_done: false });
    render(<SignupPage />);
    await triggerSignup();
    expect(toast.success).toHaveBeenCalledWith('Account created! Welcome to Syrabit.ai!');
    expect(mockNavigate).toHaveBeenCalledWith('/onboarding');
  });

  it('navigates to /staff when role is "staff"', async () => {
    mockSignup.mockResolvedValueOnce({ role: 'staff', onboarding_done: false });
    render(<SignupPage />);
    await triggerSignup();
    expect(mockNavigate).toHaveBeenCalledWith('/staff');
  });

  it('navigates to /staff when role is "admin"', async () => {
    mockSignup.mockResolvedValueOnce({ role: 'admin', onboarding_done: false });
    render(<SignupPage />);
    await triggerSignup();
    expect(mockNavigate).toHaveBeenCalledWith('/staff');
  });

  it('does not navigate and does not show success toast when signup throws', async () => {
    mockSignup.mockRejectedValueOnce(new Error('Email already in use'));
    render(<SignupPage />);
    await triggerSignup();
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });
});
