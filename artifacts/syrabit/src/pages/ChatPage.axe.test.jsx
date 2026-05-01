/**
 * Task #197 — ChatPage: axe accessibility audit.
 *
 * Covers the two most common render states students encounter:
 *  1. Anonymous user with no active conversation (EmptyState shown)
 *  2. Authenticated user with no active conversation (EmptyState shown)
 *
 * Complex sub-components and API calls are stubbed so the audit focuses
 * on the page's own markup, not the rendering of child components.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { axe, toHaveNoViolations } from 'jest-axe';
import { render, act } from '@testing-library/react';
import React from 'react';

expect.extend(toHaveNoViolations);

vi.mock('react-router-dom', () => ({
  useNavigate:     () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));

const mockUseAuth = vi.fn(() => ({ user: null, authChecked: true }));
vi.mock('@/context/AuthContext', () => ({
  useAuth: (...args) => mockUseAuth(...args),
}));

vi.mock('@/context/LanguageContext', () => ({
  useContentLang: () => ({ contentLang: 'en', switchLang: vi.fn(), toggleLang: vi.fn() }),
}));

vi.mock('@/components/layout/AppLayout', () => ({
  AppLayout: ({ children }) => <div data-testid="app-layout">{children}</div>,
}));

vi.mock('./chat/EmptyState', () => ({
  EmptyState: () => (
    <main>
      <h2>Hi! I&apos;m Syra</h2>
      <p>Ask me anything about your syllabus.</p>
    </main>
  ),
}));

vi.mock('./chat/InputBar', () => ({
  InputBar: () => (
    <div role="region" aria-label="Message input">
      <label htmlFor="chat-input-stub">Message</label>
      <input id="chat-input-stub" type="text" />
    </div>
  ),
}));

vi.mock('./chat/ModelSelector', () => ({
  ModelSelector: () => <div />,
  MODELS: [{ id: 'gemini-flash', label: 'Gemini Flash' }],
}));

vi.mock('./chat/MessageBubble', () => ({
  MessageBubble: () => <div />,
}));

vi.mock('@/utils/api', () => ({
  getConversation:     vi.fn(() => new Promise(() => {})),
  getAnonConversation: vi.fn(() => new Promise(() => {})),
  getSubject:          vi.fn(() => new Promise(() => {})),
  getChapters:         vi.fn(() => new Promise(() => {})),
  API_BASE:            'http://localhost',
  apiClient:           () => ({
    get:  vi.fn(() => new Promise(() => {})),
    post: vi.fn(() => new Promise(() => {})),
  }),
  getAnonId: vi.fn(() => 'anon-test-id'),
}));

vi.mock('@/hooks/useTurnstile', () => ({
  useTurnstile: () => ({ token: null, reset: vi.fn(), ready: false, enabled: false }),
}));

vi.mock('@/utils/analytics', () => ({
  Analytics: { page: vi.fn(), event: vi.fn(), identify: vi.fn() },
}));

vi.mock('@/utils/firebasePerf', () => ({
  startTrace:      vi.fn(() => ({ finish: vi.fn() })),
  makeTraceparent: vi.fn(() => '00-abc123-def456-01'),
}));

vi.mock('@/hooks/useHashScroll', () => ({
  useHashScroll: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

import ChatPage from './ChatPage';

beforeEach(() => {
  vi.useRealTimers();
  HTMLElement.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ChatPage — axe accessibility audit', () => {
  it('has no axe violations for an anonymous user (empty chat, no conversation)', async () => {
    let container;
    await act(async () => {
      ({ container } = render(<ChatPage />));
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations for an authenticated user (empty chat, no conversation)', async () => {
    mockUseAuth.mockReturnValueOnce({
      user:        { id: 'u1', email: 'student@example.com', credits_used: 0, credits_limit: 50 },
      authChecked: true,
    });

    let container;
    await act(async () => {
      ({ container } = render(<ChatPage />));
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
