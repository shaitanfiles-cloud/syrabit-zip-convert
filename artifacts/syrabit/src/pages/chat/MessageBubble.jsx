import { useState, useMemo, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, Copy, Check, FileText, Globe, BookOpen } from 'lucide-react';
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

  const { cleanContent, sourceLine } = useMemo(() => {
    if (!msg.content) return { cleanContent: msg.content, sourceLine: '' };
    let extracted = '';
    const cleaned = msg.content
      .replace(/\n*\n?Sources?:\s*((\[(PAGE|CHAPTER):[^\]]+\][,\s]*)+\.?\s*)$/gi, '')
      .replace(/\n*\n?SOURCE\s*:\s*(.+)$/i, (_, match) => { extracted = match.trim(); return ''; })
      .trim();
    return { cleanContent: cleaned, sourceLine: extracted };
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
              maxWidth: 'min(70%, calc(100vw - 5rem))',
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
                className="w-11 h-11 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                title="Copy"
                aria-label={copied ? 'Copied' : 'Copy'}
              >
                {copied ? <Check size={14} style={{ color: '#34d399' }} /> : <Copy size={14} />}
              </button>
            </div>
          )}
        </>
      )}

      {!isUser && (
        <div className="w-full">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-5 h-5 rounded-full overflow-hidden flex-shrink-0">
              <img src="/logo.png" alt="Syrabit.ai" width="20" height="20" className="w-full h-full object-cover" />
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
              const handleCardNav = () => {
                if (!subjectUrl) return;
                navigate(subjectUrl);
              };
              const isDocument = msg.rag_source === 'document';
              const isWeb = msg.rag_source === 'web';
              const hasContext = boardLabel || subjectLabel || courseLabel || (msg.rag_source && msg.rag_source !== 'none');

              return (
                <>
                  {hasContext && subjectLabel && !isDocument && !isWeb && (
                    <div
                      onClick={subjectUrl ? handleCardNav : undefined}
                      className={`mt-3 rounded-xl overflow-hidden ${subjectUrl ? 'cursor-pointer hover:opacity-90 transition-opacity' : ''}`}
                      style={{
                        background: 'var(--card, rgba(20,20,30,0.9))',
                        border: '1px solid rgba(74,222,128,0.15)',
                        maxWidth: 'fit-content',
                      }}
                      role={subjectUrl ? 'link' : undefined}
                      aria-label={subjectUrl ? `View ${subjectLabel}` : undefined}
                    >
                      <div className="px-3 py-2.5">
                        <h4
                          className="font-bold leading-tight truncate"
                          style={{ fontSize: '0.95rem', textTransform: 'uppercase', letterSpacing: '0.03em', color: '#4ade80' }}
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
                              <span className="text-[11px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'rgba(74,222,128,0.1)', color: '#4ade80' }}>
                                {courseLabel}
                              </span>
                            </>
                          )}
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
                  {(() => {
                    const libSources = (msg.sources || []).filter(s => s.url || s.slug);
                    const sourceParts = sourceLine ? sourceLine.split('·').map(s => s.replace(/\s*\([^)]*\)\s*$/, '').trim()).filter(Boolean) : [];
                    const hasLibSources = libSources.length > 0;
                    const hasSourceLine = sourceParts.length > 0;
                    if (!hasLibSources && !hasSourceLine) return null;
                    return (
                      <div className="mt-3 rounded-xl overflow-hidden" style={{ background: 'rgba(124,58,237,0.06)', border: '1px solid rgba(124,58,237,0.12)' }}>
                        <div className="flex items-center gap-2 px-3 pt-2.5 pb-1.5">
                          <BookOpen size={14} style={{ color: '#a78bfa' }} />
                          <span className="text-[12px] font-semibold" style={{ color: '#a78bfa', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sources</span>
                        </div>
                        {hasSourceLine && (
                          <div className="flex flex-wrap gap-1.5 px-3 pb-2">
                            {sourceParts.map((part, i) => (
                              <span key={i} className="text-[12px] px-2 py-0.5 rounded-md" style={{ background: 'rgba(124,58,237,0.08)', color: 'hsl(var(--foreground) / 0.75)' }}>
                                {part}
                              </span>
                            ))}
                          </div>
                        )}
                        {hasLibSources && (
                          <div className="flex flex-col gap-1 px-3 pb-2.5">
                            {libSources.slice(0, 5).map((s, i) => {
                              const label = s.title || s.slug || '';
                              const url = s.url || (s.slug ? `/learn/${s.slug}` : '');
                              if (!label) return null;
                              return (
                                <button
                                  key={i}
                                  onClick={() => url && navigate(url)}
                                  className="text-left text-[12.5px] truncate hover:underline"
                                  style={{ color: '#a78bfa', cursor: url ? 'pointer' : 'default' }}
                                >
                                  {label}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                  <div className="flex items-center gap-1.5 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {timeStr && (
                      <span className="text-[11px] text-muted-foreground">{timeStr}</span>
                    )}
                    <button
                      onClick={handleCopy}
                      className="w-11 h-11 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                      title="Copy"
                      aria-label={copied ? 'Copied' : 'Copy'}
                    >
                      {copied ? <Check size={16} style={{ color: '#34d399' }} /> : <Copy size={16} />}
                    </button>
                    {isLast && onRegenerate && (
                      <button
                        onClick={onRegenerate}
                        className="w-11 h-11 rounded-lg flex items-center justify-center hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
                        title="Regenerate"
                        aria-label="Regenerate"
                      >
                        <RefreshCw size={16} />
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
