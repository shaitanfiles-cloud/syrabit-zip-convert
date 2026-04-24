import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Send, AlertTriangle, Square,
} from 'lucide-react';
import { MicButton } from '@/components/study/MicButton';
import { getTTSLang } from '@/hooks/useTTS';

export function InputBar({
  subject, messages, scopedChapters, input, setInput,
  isLoading, isOutOfCredits, isLow, credits,
  effectiveLimit, remaining, creditPercent,
  textareaRef, adjustTextarea, sendMsg, handleStop,
  isAnon,
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
                ? (isAnon
                    ? 'Free daily messages used — sign in to keep chatting'
                    : 'No credits remaining — upgrade to continue')
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
            <MicButton
              language={getTTSLang() === 'as' ? 'as-IN' : 'en-IN'}
              disabled={isOutOfCredits || isLoading}
              onTranscript={(text) => {
                if (!text) return;
                setInput((prev) => (prev ? prev + ' ' : '') + text);
                setTimeout(() => adjustTextarea && adjustTextarea(), 0);
              }}
            />
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
            {/*
              Task #796 — anonymous students get a slightly more
              explicit "X / 30 free messages left today" caption (the
              previous "12 left" was cryptic to first-time visitors who
              had never seen the cap), plus a tiny "Sign in for more"
              CTA once they're at the half-way mark. Logged-in users
              keep the compact "X left" badge they're used to.
            */}
            {isAnon ? (
              <span
                className="text-[10px] font-medium shrink-0 flex items-center gap-1.5"
                style={{ color: isLow || isOutOfCredits ? '#f87171' : 'hsl(var(--muted-foreground))' }}
              >
                <span data-testid="anon-credits-remaining">
                  {remaining !== null
                    ? (isOutOfCredits
                        ? `0 / ${effectiveLimit} free messages left today`
                        : `${remaining} / ${effectiveLimit} free messages left today`)
                    : ''}
                </span>
                {remaining !== null && remaining <= Math.ceil(effectiveLimit / 2) && (
                  <button
                    type="button"
                    onClick={() => navigate('/login')}
                    className="font-semibold underline hover:no-underline"
                    style={{ color: isOutOfCredits || isLow ? '#fca5a5' : '#a78bfa' }}
                    data-testid="anon-credits-signin-cta"
                    aria-label="Sign in for more messages"
                  >
                    {isOutOfCredits ? 'Sign in →' : 'Sign in for more'}
                  </button>
                )}
              </span>
            ) : (
              <span
                className="text-[10px] font-medium shrink-0"
                style={{ color: isLow || isOutOfCredits ? '#f87171' : 'hsl(var(--muted-foreground))' }}
              >
                {remaining !== null ? `${remaining} left` : ''}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
