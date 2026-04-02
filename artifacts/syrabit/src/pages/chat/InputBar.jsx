import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Send, Database, AlertTriangle, Square,
} from 'lucide-react';

export function InputBar({
  subject, messages, scopedChapters, input, setInput,
  isLoading, isOutOfCredits, isLow, credits,
  effectiveLimit, remaining, creditPercent,
  textareaRef, adjustTextarea, sendMsg, handleStop,
}) {
  const navigate = useNavigate();
  const [maxTextareaHeight, setMaxTextareaHeight] = useState(160);

  const updateMaxHeight = useCallback(() => {
    if (window.visualViewport) {
      const vpHeight = window.visualViewport.height;
      const newMax = vpHeight < 500 ? 80 : vpHeight < 700 ? 120 : 160;
      setMaxTextareaHeight(newMax);
    }
  }, []);

  useEffect(() => {
    updateMaxHeight();
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', updateMaxHeight);
      return () => window.visualViewport.removeEventListener('resize', updateMaxHeight);
    }
  }, [updateMaxHeight]);

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-20 border-t border-border/50 px-4 md:px-6 py-3 pb-[calc(0.75rem+68px+env(safe-area-inset-bottom,0px))] md:pb-3"
      style={{ background: 'var(--card)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }}
      data-testid="chat-input"
    >
      <div className="max-w-3xl mx-auto">
        {subject && messages.length === 0 && scopedChapters.length > 0 && (
          <div className="flex items-center gap-2 mb-2 px-1 text-xs text-muted-foreground">
            <Database size={12} style={{ color: 'hsl(var(--primary) / 0.6)' }} />
            <span>RAG: {scopedChapters.length} chapters from {subject.name}</span>
          </div>
        )}

        <div
          className="flex items-end gap-3 p-3 rounded-2xl border transition-all duration-200"
          style={
            isOutOfCredits
              ? { borderColor: 'rgba(239,68,68,0.20)', opacity: 0.6, background: 'rgba(239,68,68,0.02)' }
              : { borderColor: 'rgba(139,92,246,0.15)', background: 'rgba(124,58,237,0.03)' }
          }
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => { setInput(e.target.value); adjustTextarea(); }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMsg(input);
              }
            }}
            placeholder={
              isOutOfCredits
                ? 'No credits remaining — upgrade to continue'
                : subject
                ? `Ask about ${subject.name}…`
                : 'Ask anything about your Syllabus...'
            }
            disabled={isOutOfCredits}
            rows={1}
            className="flex-1 bg-transparent resize-none outline-none text-sm text-foreground placeholder:text-muted-foreground disabled:cursor-not-allowed"
            style={{ minHeight: 24, maxHeight: maxTextareaHeight }}
            aria-label="Type your message"
          />
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-xs text-muted-foreground hidden sm:inline">↵ Enter</span>
            {isLoading ? (
              <button
                onClick={handleStop}
                className="w-11 h-11 rounded-xl flex items-center justify-center transition-all"
                style={{
                  background: 'rgba(239,68,68,0.15)',
                  border: '1px solid rgba(239,68,68,0.30)',
                  color: '#f87171',
                }}
                aria-label="Stop generating"
                title="Stop"
                data-testid="chat-stop-button"
              >
                <Square size={14} aria-hidden="true" />
              </button>
            ) : (
              <button
                onClick={() => sendMsg(input)}
                disabled={!input.trim() || isOutOfCredits}
                className="w-11 h-11 rounded-xl flex items-center justify-center transition-all disabled:cursor-not-allowed"
                style={
                  input.trim() && !isOutOfCredits
                    ? {
                        background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
                        color: '#fff',
                        boxShadow: '0 4px 15px rgba(139,92,246,0.4)',
                      }
                    : { background: 'hsl(var(--muted))', color: 'hsl(var(--muted-foreground))' }
                }
                data-testid="chat-send-button"
                aria-label="Send message"
              >
                <Send size={16} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>

        {effectiveLimit !== null && effectiveLimit > 0 && (
          <div className="mt-2 px-1 flex items-center gap-2">
            <div
              className="flex-1 h-1 rounded-full overflow-hidden"
              style={{ background: 'rgba(139,92,246,0.10)' }}
              role="progressbar"
              aria-valuenow={creditPercent}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Credit usage"
            >
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${creditPercent}%`,
                  background: isLow || isOutOfCredits
                    ? 'linear-gradient(90deg,#ef4444,#f87171)'
                    : 'linear-gradient(90deg,#7c3aed,#a78bfa)',
                }}
              />
            </div>
            <span
              className="text-[10px] font-medium shrink-0"
              style={{ color: isLow || isOutOfCredits ? '#f87171' : 'hsl(var(--muted-foreground))' }}
            >
              {remaining !== null ? `${remaining} left` : ''}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
