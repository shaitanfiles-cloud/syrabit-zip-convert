import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import React from 'react';

vi.mock('./QuizModal', () => ({
  QuizModal: ({ open }) =>
    open ? <div data-testid="quiz-modal-portal-sentinel" /> : null,
}));

vi.mock('@/utils/studyApi', () => ({
  studyApi: { createNote: vi.fn() },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { HighlightSavePopover } from './HighlightSavePopover.jsx';

let savableEl;
let getSelectionSpy;
let rafSpy;

function makeFakeSelection(text = 'this is long enough text') {
  const range = {
    commonAncestorContainer: savableEl,
    getBoundingClientRect: () => ({ left: 120, top: 80, width: 60, height: 18 }),
  };
  return {
    isCollapsed: false,
    toString: () => text,
    getRangeAt: () => range,
  };
}

async function triggerSelectionChange(text) {
  getSelectionSpy.mockReturnValue(makeFakeSelection(text));
  await act(async () => {
    document.dispatchEvent(new Event('selectionchange'));
    await new Promise((r) => setTimeout(r, 0));
  });
}

beforeEach(() => {
  savableEl = document.createElement('div');
  savableEl.setAttribute('data-savable', 'true');
  document.body.appendChild(savableEl);

  getSelectionSpy = vi.spyOn(window, 'getSelection');

  rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
    cb(0);
    return 0;
  });
});

afterEach(() => {
  getSelectionSpy.mockRestore();
  rafSpy.mockRestore();
  if (savableEl && savableEl.parentNode) {
    savableEl.parentNode.removeChild(savableEl);
  }
  vi.clearAllMocks();
});

describe('QuizModal portal mounting', () => {
  it('mounts the QuizModal as a direct child of document.body, not inside the component subtree', async () => {
    const { container } = render(<HighlightSavePopover hideQuiz={false} />);

    await triggerSelectionChange('this is long enough text');

    const quizButton = screen.getByText(/quiz me/i);
    await act(async () => {
      fireEvent.click(quizButton);
    });

    const sentinel = screen.getByTestId('quiz-modal-portal-sentinel');

    expect(sentinel).toBeInTheDocument();
    expect(sentinel.parentNode).toBe(document.body);
    expect(container.contains(sentinel)).toBe(false);
  });

  it('dismisses the selection popover bar when "Quiz me" is clicked', async () => {
    render(<HighlightSavePopover hideQuiz={false} />);

    await triggerSelectionChange('this is long enough text');

    expect(screen.getByText(/quiz me/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/quiz me/i));

    expect(screen.queryByText(/quiz me/i)).not.toBeInTheDocument();
  });
});
