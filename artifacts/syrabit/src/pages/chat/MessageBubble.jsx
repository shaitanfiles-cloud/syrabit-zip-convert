import { useState, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Copy, Check, FileText, Globe } from 'lucide-react';
import { log } from '@/utils/logger';
import { ThinkingIndicator } from './ThinkingIndicator';
import { MarkdownContent } from './MarkdownContent';

export const MessageBubble = memo(function MessageBubble({ msg, onCopy, onRegenerate, isLast }) {
  const [copied, setCopied] = useState(false);
  const navigate = useNavigate();
  const isUser = msg.role === 'user';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      if (onCopy) onCopy();
    } catch (err) {
      // Fallback for clipboard restrictions
      const textArea = document.createElement('textarea');
      textArea.value = msg.content || '';
      textArea.style.position = 'fixed';
      textArea.style.opacity = '0';
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        if (onCopy) onCopy();
      } catch (e) {
        log.error('Clipboard copy failed', { error: e.message });
      }
      document.body.removeChild(textArea);
    }
  };

  const timeStr = msg.timestamp
    ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  const cleanContent = useMemo(() => {
    if (!msg.content) return msg.content;
    return msg.content
      .replace(/\n*\n?Sources?:\s*((\[(PAGE|CHAPTER):[^\]]+\][,\s]*)+\.?\s*)$/gi, '')
      .replace(/\n*\n?SOURCE\s*:\s*.+$/i, '')
      .trim();
  }, [msg.content]);

  return (
    <div
      className={`group ${isUser ? 'flex flex-col items-end mb-2' : 'mb-3'}`}
      data-testid="chat-message-bubble"
    >
      {isUser && (
        <>
          <div
            className="whitespace-pre-wrap"
            style={{
              padding: '10px 16px',
              background: '#7c3aed',
              borderRadius: '18px 18px 4px 18px',
              fontSize: '15px',
              lineHeight: '1.6',
              color: '#fff',
              maxWidth: '70%',
              wordWrap: 'break-word',
            }}
          >
            {msg.content}
          </div>
          {!msg.streaming && (
            <div className="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {timeStr && <span className="text-[11px] text-muted-foreground">{timeStr}</span>}
              <button
                onClick={handleCopy}
                className="w-6 h-6 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                title="Copy"
              >
                {copied ? <Check size={12} style={{ color: '#34d399' }} /> : <Copy size={12} />}
              </button>
            </div>
          )}
        </>
      )}

      {!isUser && (
        <div className="w-full">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-5 h-5 rounded-full overflow-hidden flex-shrink-0">
              <img src="/logo.png" alt="Syrabit.ai" className="w-full h-full object-cover" />
            </div>
            <span className="text-xs font-semibold text-foreground/70">Syrabit AI</span>
          </div>
          <div className="w-full">
            {msg.streaming && !msg.content && <ThinkingIndicator />}

            {msg.streaming && msg.content && (
              <MarkdownContent content={cleanContent} streaming={true} sources={msg.sources} />
            )}

            {!msg.streaming && msg.content && (
              <MarkdownContent content={cleanContent} streaming={false} sources={msg.sources} />
            )}

            {!msg.streaming && msg.content && (() => {
              const subjectLabel = msg.rag_subject_name || msg.ctx_subject_name || null;
              const courseLabel = msg.rag_stream_name || null;
              const boardLabel = msg.rag_board_name || null;
              const classLabel = msg.rag_class_name || null;
              const subjectUrl = msg.rag_subject_id ? `/subject/${msg.rag_subject_id}` : null;
              const subjectIcon = msg.ctx_subject_icon || '📚';
              const handleCardNav = () => {
                if (!subjectUrl) return;
                navigate(subjectUrl);
              };
              const isDocument = msg.rag_source === 'document';
              const isWeb = msg.rag_source === 'web';
              const hasContext = boardLabel || subjectLabel || courseLabel || (msg.rag_source && msg.rag_source !== 'none');

              const GRAD_MAP = {
                math:      ['#4f46e5', '#7c3aed'],
                physics:   ['#2563eb', '#0891b2'],
                chemistry: ['#059669', '#0d9488'],
                biology:   ['#16a34a', '#15803d'],
                arts:      ['#d97706', '#b45309'],
                science:   ['#7c3aed', '#4f46e5'],
              };
              const gradKey = msg.ctx_subject_gradient || 'arts';
              const thumbColors = GRAD_MAP[gradKey] || GRAD_MAP.arts;

              return (
                <>
                  {hasContext && subjectLabel && !isDocument && !isWeb && (
                    <div
                      onClick={subjectUrl ? handleCardNav : undefined}
                      className={`mt-3 rounded-xl overflow-hidden ${subjectUrl ? 'cursor-pointer hover:opacity-90 transition-opacity' : ''}`}
                      style={{
                        background: 'var(--card, rgba(20,20,30,0.9))',
                        border: '1px solid rgba(139,92,246,0.10)',
                        maxWidth: 'fit-content',
                        minWidth: '220px',
                      }}
                      role={subjectUrl ? 'link' : undefined}
                      aria-label={subjectUrl ? `View ${subjectLabel}` : undefined}
                    >
                      <div className="flex items-start gap-3 px-3 py-2.5">
                        <div
                          className="w-10 h-10 rounded-xl flex items-center justify-center text-xl shrink-0"
                          style={{
                            background: `linear-gradient(135deg, ${thumbColors[0]}30, ${thumbColors[1]}20)`,
                            border: `1px solid ${thumbColors[0]}30`,
                          }}
                        >
                          {subjectIcon}
                        </div>
                        <div className="min-w-0 flex-1">
                          <h4
                            className="text-foreground font-bold leading-tight truncate"
                            style={{ fontSize: '0.95rem', textTransform: 'uppercase', letterSpacing: '0.03em' }}
                          >
                            {subjectLabel}
                          </h4>
                          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 mt-1">
                            {boardLabel && (
                              <span className="text-[11px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))' }}>
                                {boardLabel}
                              </span>
                            )}
                            {classLabel && (
                              <span className="text-[11px] text-muted-foreground">
                                {classLabel}
                              </span>
                            )}
                            {courseLabel && (
                              <>
                                <span className="text-[11px] text-muted-foreground/60">·</span>
                                <span className="text-[11px] text-muted-foreground/60">
                                  {courseLabel}
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                  {hasContext && isDocument && (
                    <div
                      className="flex items-center gap-2.5 mt-3 px-3 py-2 rounded-xl"
                      style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.18)', maxWidth: 'fit-content' }}
                    >
                      <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: 'rgba(167,139,250,0.15)' }}>
                        <FileText size={16} style={{ color: '#a78bfa' }} />
                      </div>
                      <span className="text-[13px] font-bold text-foreground" style={{ textTransform: 'uppercase', letterSpacing: '0.03em' }}>Uploaded Document</span>
                    </div>
                  )}
                  {hasContext && isWeb && (
                    <div
                      className="flex items-center gap-2.5 mt-3 px-3 py-2 rounded-xl"
                      style={{ background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.18)', maxWidth: 'fit-content' }}
                    >
                      <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: 'rgba(96,165,250,0.15)' }}>
                        <Globe size={16} style={{ color: '#60a5fa' }} />
                      </div>
                      <span className="text-[13px] font-bold text-foreground" style={{ textTransform: 'uppercase', letterSpacing: '0.03em' }}>Web Search</span>
                    </div>
                  )}
                  <div className="flex items-center gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {timeStr && (
                      <span className="text-[11px] text-muted-foreground">{timeStr}</span>
                    )}
                    <button
                      onClick={handleCopy}
                      className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                      title="Copy"
                      aria-label={copied ? 'Copied' : 'Copy'}
                    >
                      {copied ? <Check size={14} style={{ color: '#34d399' }} /> : <Copy size={14} />}
                    </button>
                    {isLast && onRegenerate && (
                      <button
                        onClick={onRegenerate}
                        className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                        title="Regenerate"
                        aria-label="Regenerate"
                      >
                        <RefreshCw size={14} />
                      </button>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
});
