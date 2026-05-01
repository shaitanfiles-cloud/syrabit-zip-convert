/**
 * Task #197 — SubjectPage: axe accessibility audit.
 *
 * Covers two key render states for the subject/chapter browser:
 *  1. Loading state — animated skeleton while subject data is fetched
 *  2. Error state   — "Failed to load subject" UI when the request fails
 *
 * Sub-components used only in the fully-loaded view (BlogView, LegacyAccordion)
 * are not reached in these early returns, so only the minimum set of mocks
 * is needed.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { axe, toHaveNoViolations } from 'jest-axe';
import { render, act } from '@testing-library/react';
import React from 'react';

expect.extend(toHaveNoViolations);

vi.mock('react-router-dom', () => ({
  useParams: () => ({ subjectId: 'english-class-11' }),
  Link:      ({ children, to }) => <a href={to}>{children}</a>,
}));

vi.mock('@/components/layout/AppLayout', () => ({
  AppLayout: ({ children }) => <div data-testid="app-layout">{children}</div>,
}));

vi.mock('@/components/seo/PageMeta', () => ({
  default: () => null,
}));

vi.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, variant, className }) => (
    <button type="button" onClick={onClick} className={className}>{children}</button>
  ),
}));

vi.mock('@/components/ui/StickyToc', () => ({
  default: () => null,
}));

vi.mock('@/components/ui/skeleton', () => ({
  Skeleton: ({ className }) => <div className={className} aria-hidden="true" />,
}));

vi.mock('@/components/ui/accordion', () => ({
  Accordion:        ({ children }) => <div>{children}</div>,
  AccordionContent: ({ children }) => <div>{children}</div>,
  AccordionItem:    ({ children, value }) => <div data-value={value}>{children}</div>,
  AccordionTrigger: ({ children }) => <button type="button">{children}</button>,
}));

vi.mock('@/utils/api', () => ({
  getChunks:              vi.fn(),
  getChapterTopicSummary: vi.fn(),
  apiClient:              () => ({ get: vi.fn(), post: vi.fn() }),
}));

vi.mock('@/hooks/useShare', () => ({
  useShare: () => ({ sharing: false, share: vi.fn() }),
}));

vi.mock('@/hooks/useContent', () => ({
  useSubject:  vi.fn(),
  useChapters: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import SubjectPage from './SubjectPage';
import { useSubject, useChapters } from '@/hooks/useContent';

beforeEach(() => {
  vi.useRealTimers();
  vi.mocked(useSubject).mockReturnValue({
    data:     undefined,
    isLoading: true,
    isError:  false,
    refetch:  vi.fn(),
  });
  vi.mocked(useChapters).mockReturnValue({ data: [], isLoading: true });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('SubjectPage — axe accessibility audit', () => {
  it('has no axe violations while the subject is loading (skeleton state)', async () => {
    let container;
    await act(async () => {
      ({ container } = render(<SubjectPage />));
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations when the subject fails to load (error state)', async () => {
    vi.mocked(useSubject).mockReturnValue({
      data:      undefined,
      isLoading: false,
      isError:   true,
      refetch:   vi.fn(),
    });
    vi.mocked(useChapters).mockReturnValue({ data: [], isLoading: false });

    let container;
    await act(async () => {
      ({ container } = render(<SubjectPage />));
    });
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
