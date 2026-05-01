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

async function fillForm({ password = 'Password1!', confirmPassword = 'Password1!', agreed = false, consentDpdp = false } = {}) {
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText('Your name'), {
      target: { value: 'Test User' },
    });
    fireEvent.change(screen.getByTestId('auth-email-input'), {
      target: { value: 'user@test.com' },
    });
    fireEvent.change(screen.getByTestId('auth-password-input'), {
      target: { value: password },
    });
    const [confirmInput] = screen.getAllByPlaceholderText('••••••••').slice(-1);
    fireEvent.change(confirmInput, { target: { value: confirmPassword } });
    if (agreed) {
      fireEvent.click(screen.getByRole('button', { name: /agree to terms/i }));
    }
    if (consentDpdp) {
      fireEvent.click(screen.getByRole('button', { name: /consent to data processing/i }));
    }
  });
  await act(async () => {
    fireEvent.click(screen.getByTestId('auth-submit-button'));
  });
  await act(async () => {});
}

describe('SignupPage — inline password-mismatch hint', () => {
  it('shows the inline hint when confirm password differs from password', async () => {
    render(<SignupPage />);
    await act(async () => {
      fireEvent.change(screen.getByTestId('auth-password-input'), {
        target: { value: 'Password1!' },
      });
      const [confirmInput] = screen.getAllByPlaceholderText('••••••••').slice(-1);
      fireEvent.change(confirmInput, { target: { value: 'Different1!' } });
    });
    expect(screen.getByText("Passwords don't match")).toBeTruthy();
  });

  it('hides the inline hint once confirm password is corrected to match', async () => {
    render(<SignupPage />);
    await act(async () => {
      fireEvent.change(screen.getByTestId('auth-password-input'), {
        target: { value: 'Password1!' },
      });
      const [confirmInput] = screen.getAllByPlaceholderText('••••••••').slice(-1);
      fireEvent.change(confirmInput, { target: { value: 'Different1!' } });
    });
    expect(screen.getByText("Passwords don't match")).toBeTruthy();
    await act(async () => {
      const [confirmInput] = screen.getAllByPlaceholderText('••••••••').slice(-1);
      fireEvent.change(confirmInput, { target: { value: 'Password1!' } });
    });
    expect(screen.queryByText("Passwords don't match")).toBeNull();
  });
});

describe('SignupPage — handleSubmit validation guards', () => {
  it('shows "Passwords do not match" and never calls signup when passwords differ', async () => {
    render(<SignupPage />);
    await fillForm({ password: 'Password1!', confirmPassword: 'Different1!', agreed: true, consentDpdp: true });
    expect(screen.getByText('Passwords do not match')).toBeTruthy();
    expect(mockSignup).not.toHaveBeenCalled();
  });

  it('shows "Please agree to the Terms of Service" and never calls signup when Terms unchecked', async () => {
    render(<SignupPage />);
    await fillForm({ password: 'Password1!', confirmPassword: 'Password1!', agreed: false, consentDpdp: true });
    expect(screen.getByText('Please agree to the Terms of Service')).toBeTruthy();
    expect(mockSignup).not.toHaveBeenCalled();
  });

  it('shows the DPDP error and never calls signup when DPDP consent is missing', async () => {
    render(<SignupPage />);
    await fillForm({ password: 'Password1!', confirmPassword: 'Password1!', agreed: true, consentDpdp: false });
    expect(screen.getByText('Please provide consent for data processing under the DPDP Act')).toBeTruthy();
    expect(mockSignup).not.toHaveBeenCalled();
  });
});

describe('SignupPage — error banner is cleared on retry', () => {
  it('clears a stale validation error when the user fixes the form and resubmits', async () => {
    mockSignup.mockResolvedValueOnce({ role: '', onboarding_done: false });
    render(<SignupPage />);

    // Phase 1: submit with mismatched passwords → error banner appears
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
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Different1!' } });
      fireEvent.click(screen.getByRole('button', { name: /agree to terms/i }));
      fireEvent.click(screen.getByRole('button', { name: /consent to data processing/i }));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('auth-submit-button'));
    });
    await act(async () => {});

    expect(screen.getByText('Passwords do not match')).toBeTruthy();

    // Phase 2: fix the confirm password and resubmit — setError('') fires at
    // the top of handleSubmit, so the banner must be gone before signup runs
    await act(async () => {
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Password1!' } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('auth-submit-button'));
    });
    await act(async () => {});

    expect(screen.queryByText('Passwords do not match')).toBeNull();
    expect(mockSignup).toHaveBeenCalledTimes(1);
  });
});

describe('SignupPage — confirm-password red border', () => {
  it('applies border-red-500/40 to the confirm-password input when passwords do not match', async () => {
    render(<SignupPage />);
    await act(async () => {
      fireEvent.change(screen.getByTestId('auth-password-input'), {
        target: { value: 'Password1!' },
      });
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Different1!' } });
    });
    const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
    expect(confirmInput.className).toContain('border-red-500/40');
  });

  it('removes border-red-500/40 from the confirm-password input once passwords match', async () => {
    render(<SignupPage />);
    await act(async () => {
      fireEvent.change(screen.getByTestId('auth-password-input'), {
        target: { value: 'Password1!' },
      });
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Different1!' } });
    });
    // Confirm the red border is present first
    expect(screen.getAllByPlaceholderText('••••••••').slice(-1)[0].className).toContain('border-red-500/40');

    await act(async () => {
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Password1!' } });
    });
    const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
    expect(confirmInput.className).not.toContain('border-red-500/40');
  });
});

describe('SignupPage — password input red border', () => {
  it('applies border-red-500/40 to the password input when confirm password is non-empty and does not match', async () => {
    render(<SignupPage />);
    await act(async () => {
      fireEvent.change(screen.getByTestId('auth-password-input'), {
        target: { value: 'Password1!' },
      });
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Different1!' } });
    });
    const passwordInput = screen.getByTestId('auth-password-input');
    expect(passwordInput.className).toContain('border-red-500/40');
  });

  it('removes border-red-500/40 from the password input once passwords match', async () => {
    render(<SignupPage />);
    await act(async () => {
      fireEvent.change(screen.getByTestId('auth-password-input'), {
        target: { value: 'Password1!' },
      });
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Different1!' } });
    });
    expect(screen.getByTestId('auth-password-input').className).toContain('border-red-500/40');

    await act(async () => {
      const confirmInput = screen.getAllByPlaceholderText('••••••••').slice(-1)[0];
      fireEvent.change(confirmInput, { target: { value: 'Password1!' } });
    });
    expect(screen.getByTestId('auth-password-input').className).not.toContain('border-red-500/40');
  });

  it('does not apply border-red-500/40 to the password input when confirm password is empty', async () => {
    render(<SignupPage />);
    await act(async () => {
      fireEvent.change(screen.getByTestId('auth-password-input'), {
        target: { value: 'Password1!' },
      });
    });
    expect(screen.getByTestId('auth-password-input').className).not.toContain('border-red-500/40');
  });
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
