import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('@/utils/studyApi', () => ({
  studyApi: { createNote: vi.fn() },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('./QuizModal', () => ({
  QuizModal: () => null,
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

describe('HighlightSavePopover — hideQuiz prop', () => {
  it('hides the Quiz me button and divider when hideQuiz={true}', async () => {
    render(<HighlightSavePopover hideQuiz={true} />);

    await triggerSelectionChange('enough text to show popover');

    expect(screen.queryByText(/quiz me/i)).toBeNull();
    expect(screen.getByText(/save/i)).toBeInTheDocument();
    expect(document.querySelector('.w-px.h-5')).toBeNull();
  });

  it('shows the Quiz me button when hideQuiz={false}', async () => {
    render(<HighlightSavePopover hideQuiz={false} />);

    await triggerSelectionChange('enough text to show popover');

    expect(screen.getByText(/quiz me/i)).toBeInTheDocument();
    expect(screen.getByText(/save/i)).toBeInTheDocument();
    expect(document.querySelector('.w-px.h-5')).toBeInTheDocument();
  });

  it('does not show the popover at all when text is too short', async () => {
    render(<HighlightSavePopover hideQuiz={false} />);

    await triggerSelectionChange('hi');

    expect(screen.queryByText(/quiz me/i)).toBeNull();
    expect(screen.queryByText(/save/i)).toBeNull();
  });
});
