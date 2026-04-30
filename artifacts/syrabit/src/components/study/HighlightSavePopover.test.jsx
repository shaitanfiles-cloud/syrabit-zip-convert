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

describe('HighlightSavePopover — hideSave prop', () => {
  it('hides the Save button and divider but keeps Quiz me when hideSave={true}', async () => {
    render(<HighlightSavePopover hideSave={true} />);

    await triggerSelectionChange('enough text to show popover');

    expect(screen.queryByText(/save/i)).toBeNull();
    expect(document.querySelector('.w-px.h-5')).toBeNull();
    expect(screen.getByText(/quiz me/i)).toBeInTheDocument();
  });

  it('shows the Save button when hideSave={false}', async () => {
    render(<HighlightSavePopover hideSave={false} />);

    await triggerSelectionChange('enough text to show popover');

    expect(screen.getByText(/save/i)).toBeInTheDocument();
    expect(screen.getByText(/quiz me/i)).toBeInTheDocument();
    expect(document.querySelector('.w-px.h-5')).toBeInTheDocument();
  });

  it('does not render the popover at all when hideSave={true} and hideQuiz={true}', async () => {
    render(<HighlightSavePopover hideSave hideQuiz />);

    await triggerSelectionChange('enough text to show popover');

    expect(screen.queryByText(/save/i)).toBeNull();
    expect(screen.queryByText(/quiz me/i)).toBeNull();
    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeNull();
  });
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

describe('HighlightSavePopover — edge cases', () => {
  it('does not show the popover for text of exactly 5 chars (below minimum)', async () => {
    render(<HighlightSavePopover />);

    await triggerSelectionChange('abcde');

    expect(screen.queryByText(/save/i)).toBeNull();
    expect(screen.queryByText(/quiz me/i)).toBeNull();
    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeNull();
  });

  it('does not show the popover for text of exactly 4001 chars (above maximum)', async () => {
    render(<HighlightSavePopover />);

    await triggerSelectionChange('a'.repeat(4001));

    expect(screen.queryByText(/save/i)).toBeNull();
    expect(screen.queryByText(/quiz me/i)).toBeNull();
    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeNull();
  });

  it('shows the popover for text of exactly 6 chars (minimum valid length)', async () => {
    render(<HighlightSavePopover />);

    await triggerSelectionChange('abcdef');

    expect(screen.getByText(/save/i)).toBeInTheDocument();
    expect(screen.getByText(/quiz me/i)).toBeInTheDocument();
    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeInTheDocument();
  });

  it('shows the popover for text of exactly 4000 chars (maximum valid length)', async () => {
    render(<HighlightSavePopover />);

    await triggerSelectionChange('a'.repeat(4000));

    expect(screen.getByText(/save/i)).toBeInTheDocument();
    expect(screen.getByText(/quiz me/i)).toBeInTheDocument();
    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeInTheDocument();
  });

  it('does not show the popover when the selection is collapsed', async () => {
    render(<HighlightSavePopover />);

    getSelectionSpy.mockReturnValue({ isCollapsed: true, toString: () => 'enough text here', getRangeAt: () => ({}) });
    await act(async () => {
      document.dispatchEvent(new Event('selectionchange'));
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(screen.queryByText(/save/i)).toBeNull();
    expect(screen.queryByText(/quiz me/i)).toBeNull();
    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeNull();
  });

  it('shows the popover when the commonAncestorContainer is a text node inside a savable element', async () => {
    render(<HighlightSavePopover />);

    const textNode = document.createTextNode('highlighted content inside savable');
    savableEl.appendChild(textNode);

    const textNodeRange = {
      commonAncestorContainer: textNode,
      getBoundingClientRect: () => ({ left: 100, top: 60, width: 80, height: 18 }),
    };
    getSelectionSpy.mockReturnValue({
      isCollapsed: false,
      toString: () => 'highlighted content inside savable',
      getRangeAt: () => textNodeRange,
    });

    await act(async () => {
      document.dispatchEvent(new Event('selectionchange'));
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeInTheDocument();
  });

  it('does not show the popover when the selection is outside any savable container', async () => {
    render(<HighlightSavePopover />);

    const plainDiv = document.createElement('div');
    document.body.appendChild(plainDiv);

    const outsideRange = {
      commonAncestorContainer: plainDiv,
      getBoundingClientRect: () => ({ left: 50, top: 50, width: 80, height: 18 }),
    };
    getSelectionSpy.mockReturnValue({
      isCollapsed: false,
      toString: () => 'enough text to show popover',
      getRangeAt: () => outsideRange,
    });

    await act(async () => {
      document.dispatchEvent(new Event('selectionchange'));
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(screen.queryByText(/save/i)).toBeNull();
    expect(screen.queryByText(/quiz me/i)).toBeNull();
    expect(document.querySelector('.fixed.z-\\[110\\]')).toBeNull();

    plainDiv.parentNode.removeChild(plainDiv);
  });
});
