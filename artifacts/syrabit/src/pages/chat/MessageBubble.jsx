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
              const chapterLabel = msg.rag_chapter_name || null;
              const subjectUrl = msg.rag_subject_id ? `/subject/${msg.rag_subject_id}` : null;
              const isDocument = msg.rag_source === 'document';
              const isWeb = msg.rag_source === 'web';
              const hasContext = boardLabel || subjectLabel || courseLabel || (msg.rag_source && msg.rag_source !== 'none');

              const sourceParts = sourceLine ? sourceLine.split('·').map(s => s.replace(/\s*\([^)]*\)\s*$/, '').trim()).filter(Boolean) : [];
              const hasAnything = hasContext || sourceParts.length > 0;
              if (!hasAnything) return null;

              const sourceIcon = isDocument ? FileText : isWeb ? Globe : BookOpen;
              const SourceIcon = sourceIcon;
              const sourceTypeLabel = isDocument ? 'Uploaded Document' : isWeb ? 'Web Search' : 'Syrabit Library';

              const tags = [];
              if (chapterLabel) tags.push(chapterLabel);
              for (const sp of sourceParts) {
                if (!tags.some(t => t.toLowerCase() === sp.toLowerCase())) tags.push(sp);
              }
              if (subjectLabel && !tags.some(t => t.toLowerCase() === subjectLabel.toLowerCase())) tags.push(subjectLabel);

              return (
                <>
                  <div
                    onClick={subjectUrl && !isDocument && !isWeb ? () => navigate(subjectUrl) : undefined}
                    className={`mt-3 rounded-xl overflow-hidden ${subjectUrl && !isDocument && !isWeb ? 'cursor-pointer hover:opacity-90 transition-opacity' : ''}`}
                    style={{ background: 'rgba(124,58,237,0.05)', border: '1px solid rgba(124,58,237,0.12)' }}
                    role={subjectUrl && !isDocument && !isWeb ? 'link' : undefined}
                    aria-label={subjectUrl && !isDocument && !isWeb ? `View ${subjectLabel}` : undefined}
                  >
                    <div className="flex items-center gap-2 px-3 pt-2.5 pb-1">
                      <SourceIcon size={14} style={{ color: '#a78bfa' }} />
                      <span className="text-[12px] font-semibold" style={{ color: '#a78bfa', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{sourceTypeLabel}</span>
                    </div>
                    {tags.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2.5">
                        {tags.map((tag, i) => (
                          <span key={i} className="text-[11px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.1)', color: 'hsl(var(--foreground) / 0.7)' }}>
                            {tag}
                          </span>
                        ))}
                        {boardLabel && !tags.some(t => t.toLowerCase() === boardLabel.toLowerCase()) && (
                          <span className="text-[11px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.1)', color: 'hsl(var(--foreground) / 0.7)' }}>
                            {boardLabel}
                          </span>
                        )}
                        {classLabel && (
                          <span className="text-[11px] text-muted-foreground">{classLabel}</span>
                        )}
                        {courseLabel && !tags.some(t => t.toLowerCase() === courseLabel.toLowerCase()) && (
                          <span className="text-[11px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.1)', color: 'hsl(var(--foreground) / 0.7)' }}>
                            {courseLabel}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
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
